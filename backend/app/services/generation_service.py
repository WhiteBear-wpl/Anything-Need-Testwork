import hashlib
import json

from sqlalchemy.orm import Session

from app.ai.vector_store_factory import VECTOR_COLLECTION_VERSION
from app.agent_runtime.contracts import BudgetExhausted, RuntimeCancelled
from app.models.generation import GeneratedCaseDraft, GenerationTask
from app.models.requirement import RequirementDocument, RequirementItem
from app.models.testcase import TestCase
from app.services.knowledge_service import (
    DEFAULT_TOP_K,
    RECALL_TOP_K,
    RRF_K,
    SIMILARITY_THRESHOLD,
)
from app.services.settings_service import RuntimeModelConfig, get_project_runtime_config
from app.skills import parse_requirements
from app.skills.base import SkillContext
from app.skills.registry import get_registry


def normalize_strategy(strategy: str) -> str:
    return get_registry().normalize_strategy(strategy)


def _prompt_fingerprint(skill) -> str:
    if not skill.directory:
        return ""
    digest = hashlib.sha256()
    try:
        prompt_files = sorted(skill.directory.rglob("*.md"))
        for path in prompt_files:
            digest.update(str(path.relative_to(skill.directory)).encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
    except OSError:
        return ""
    return digest.hexdigest()[:16] if prompt_files else ""


def parse_strategy_config(task: GenerationTask) -> dict:
    registry = get_registry()
    if not task.strategy_config:
        return {
            "strategy": registry.normalize_strategy(task.strategy),
            "specialist_skills": [],
            "use_knowledge": False,
        }
    try:
        data = json.loads(task.strategy_config)
        if isinstance(data, dict):
            preset = data.get("strategy") or data.get("preset") or task.strategy
            skills = data.get("specialist_skills") or []
            return {
                "strategy": registry.normalize_strategy(preset),
                "specialist_skills": registry.validate_specialist_selection(
                    skills,
                    strict=False,
                ),
                "use_knowledge": bool(data.get("use_knowledge", False)),
            }
    except json.JSONDecodeError:
        pass
    return {
        "strategy": registry.normalize_strategy(task.strategy),
        "specialist_skills": [],
        "use_knowledge": False,
    }


def build_strategy_config(
    strategy: str,
    specialist_skills: list[str] | None = None,
    use_knowledge: bool = False,
    model_config: RuntimeModelConfig | None = None,
    strict_specialists: bool = False,
    policy_state=None,
) -> dict:
    """固化一次生成运行的非敏感配置，便于评测对比与问题复现。"""
    registry = get_registry()
    validated_skills = registry.validate_specialist_selection(
        specialist_skills or [],
        strict=strict_specialists,
    )
    skills = registry.list_skills()
    config = {
        "workflow_version": "langgraph-v1",
        "strategy": registry.normalize_strategy(strategy),
        "specialist_skills": validated_skills,
        "use_knowledge": bool(use_knowledge),
        "skill_versions": {
            skill.name: skill.version
            for skill in skills
        },
        "prompt_fingerprints": {
            skill.name: fingerprint
            for skill in skills
            if (fingerprint := _prompt_fingerprint(skill))
        },
        "generation_parameters": {
            "temperature": 0.3,
            "structured_output": "pydantic_output_parser",
        },
        "retrieval": {
            "mode": "vector_bm25_rrf_optional_rerank",
            "embedding_adapter": "langchain_openai",
            "vector_store": "langchain_chroma",
            "collection_version": VECTOR_COLLECTION_VERSION,
            "top_k": DEFAULT_TOP_K,
            "recall_top_k": RECALL_TOP_K,
            "similarity_threshold": SIMILARITY_THRESHOLD,
            "rrf_k": RRF_K,
        },
    }
    if model_config is not None:
        config["models"] = {
            "generation": {
                "base_url": model_config.llm_base_url,
                "model": model_config.llm_model,
                "mock_mode": model_config.use_mock_llm,
            },
            "evaluation": {
                "base_url": model_config.eval_llm_base_url or model_config.llm_base_url,
                "model": model_config.eval_llm_model or model_config.llm_model,
            },
            "embedding": {
                "base_url": model_config.embedding_base_url,
                "model": model_config.embedding_model,
            },
            "rerank": {
                "base_url": model_config.rerank_base_url,
                "model": model_config.rerank_model,
            },
        }
    if policy_state is not None:
        config["skill_policy"] = policy_state.to_snapshot()
    return config


def build_strategy_config_payload(
    data,
    model_config: RuntimeModelConfig | None = None,
    *,
    strict_specialists: bool = False,
    policy_state=None,
) -> str:
    return json.dumps(
        build_strategy_config(
            strategy=data.strategy,
            specialist_skills=data.specialist_skills or [],
            use_knowledge=bool(getattr(data, "use_knowledge", False)),
            model_config=model_config,
            strict_specialists=strict_specialists,
            policy_state=policy_state,
        ),
        ensure_ascii=False,
    )


def _skill_context(
    task: GenerationTask,
    strategy: str,
    model_config: RuntimeModelConfig,
) -> SkillContext:
    from app.agent_runtime.harness import get_active_runtime_harness

    return SkillContext(
        model_config=model_config,
        project_id=task.project_id,
        task_id=task.id,
        strategy=strategy,
        use_mock=model_config.use_mock_llm,
        runtime=get_active_runtime_harness(),
    )


async def structure_requirements(
    db: Session,
    document: RequirementDocument,
    model_config: RuntimeModelConfig | None = None,
) -> list[RequirementItem]:
    model_config = model_config or get_project_runtime_config(db, document.project_id)
    items_data = await parse_requirements(document.raw_content, model_config)
    document.status = "structured"
    db.query(RequirementItem).filter(RequirementItem.document_id == document.id).delete()

    db_items = []
    for idx, item in enumerate(items_data):
        db_item = RequirementItem(
            document_id=document.id,
            module=item.get("module", ""),
            feature=item.get("feature", ""),
            description=item.get("description", ""),
            acceptance_criteria=item.get("acceptance_criteria", ""),
            constraints=item.get("constraints", ""),
            priority=item.get("priority", "P1"),
            sort_order=idx,
            confirmed=False,
        )
        db.add(db_item)
        db_items.append(db_item)

    db.commit()
    for item in db_items:
        db.refresh(item)
    return db_items


def confirm_requirements(db: Session, document_id: int, item_ids: list[int] | None = None):
    if item_ids is not None:
        db.query(RequirementItem).filter(
            RequirementItem.document_id == document_id,
            RequirementItem.id.in_(item_ids),
        ).update({"confirmed": True}, synchronize_session=False)
        db.query(RequirementItem).filter(
            RequirementItem.document_id == document_id,
            ~RequirementItem.id.in_(item_ids),
        ).update({"confirmed": False}, synchronize_session=False)
    else:
        db.query(RequirementItem).filter(RequirementItem.document_id == document_id).update(
            {"confirmed": True}, synchronize_session=False
        )

    doc = db.get(RequirementDocument, document_id)
    doc.status = "confirmed"
    db.commit()


def _item_feature_data(item: RequirementItem) -> dict:
    return {
        "module": item.module,
        "feature": item.feature,
        "description": item.description,
        "acceptance_criteria": item.acceptance_criteria,
        "constraints": item.constraints,
        "priority": item.priority,
    }


def _draft_for_judge(draft: GeneratedCaseDraft) -> dict:
    return {
        "title": draft.title,
        "precondition": draft.precondition,
        "steps": draft.steps,
        "expected_result": draft.expected_result,
    }


async def run_judge_for_task(
    db: Session,
    task: GenerationTask,
    model_config: RuntimeModelConfig | None = None,
) -> None:
    """对任务下全部草稿按功能点批量运行 AI Judge，评分写回草稿。

    单个功能点评分失败不中断整体流程（对应草稿保持未评状态）。
    """
    registry = get_registry()
    model_config = model_config or get_project_runtime_config(db, task.project_id)
    context = _skill_context(task, "full", model_config)

    drafts = (
        db.query(GeneratedCaseDraft)
        .filter(GeneratedCaseDraft.task_id == task.id)
        .order_by(GeneratedCaseDraft.id)
        .all()
    )
    if not drafts:
        return

    item_ids = {d.requirement_item_id for d in drafts if d.requirement_item_id}
    items_map = {
        item.id: item
        for item in db.query(RequirementItem).filter(RequirementItem.id.in_(item_ids)).all()
    } if item_ids else {}

    grouped: dict[int | None, list[GeneratedCaseDraft]] = {}
    for d in drafts:
        grouped.setdefault(d.requirement_item_id, []).append(d)

    group_count = len(grouped)
    for group_idx, (item_id, group) in enumerate(grouped.items()):
        item = items_map.get(item_id)
        feature_data = _item_feature_data(item) if item else {"feature": "未知功能点"}
        # 仅在生成流程中更新进度/阶段；手动重评（任务已完成）不动进度
        if task.status == "generating":
            task.stage = f"AI 评分 {group_idx + 1}/{group_count}：{feature_data.get('feature', '')}"
            task.progress = 85 + int(10 * group_idx / group_count)
            db.commit()
        try:
            result = await registry.run(
                "case_judge",
                {"feature_item": feature_data, "cases": [_draft_for_judge(d) for d in group]},
                context,
            )
        except (BudgetExhausted, RuntimeCancelled):
            raise
        except Exception:
            continue

        for judgement in result.get("judgements") or []:
            idx = judgement.get("index")
            if not isinstance(idx, int) or not (0 <= idx < len(group)):
                continue
            draft = group[idx]
            draft.judge_score = judgement.get("overall")
            draft.judge_issues = json.dumps(
                {
                    "relevance": judgement.get("relevance"),
                    "executability": judgement.get("executability"),
                    "verifiability": judgement.get("verifiability"),
                    "hallucination": judgement.get("hallucination", False),
                    "hallucination_reason": judgement.get("hallucination_reason", ""),
                    "comment": judgement.get("comment", ""),
                },
                ensure_ascii=False,
            )
    db.commit()


def adopt_drafts(db: Session, task_id: int, draft_ids: list[int]) -> list[TestCase]:
    task = db.query(GenerationTask).get(task_id)
    adopted = []

    for draft_id in draft_ids:
        draft = db.query(GeneratedCaseDraft).filter(
            GeneratedCaseDraft.id == draft_id,
            GeneratedCaseDraft.task_id == task_id,
        ).first()
        if not draft:
            continue

        tc = TestCase(
            project_id=task.project_id,
            draft_id=draft.id,
            requirement_item_id=draft.requirement_item_id,
            title=draft.title,
            priority=draft.priority,
            case_type=draft.case_type,
            is_smoke=draft.is_smoke,
            precondition=draft.precondition,
            steps=draft.steps,
            expected_result=draft.expected_result,
            source="ai_generated",
        )
        db.add(tc)
        draft.review_status = "adopted"
        adopted.append(tc)

    db.commit()
    for tc in adopted:
        db.refresh(tc)
    return adopted


def reject_drafts(db: Session, task_id: int, draft_ids: list[int], reject_reason: str = ""):
    db.query(GeneratedCaseDraft).filter(
        GeneratedCaseDraft.task_id == task_id,
        GeneratedCaseDraft.id.in_(draft_ids),
    ).update({"review_status": "rejected", "reject_reason": reject_reason[:200]})
    db.commit()
