import asyncio
import json
import time
from dataclasses import replace

from langchain_core.exceptions import OutputParserException

from app.ai.retrievers import AITCHybridRetriever, documents_to_knowledge
from app.agent_runtime.contracts import BudgetExhausted, RuntimeCancelled
from app.database import SessionLocal
from app.models.generation import (
    GeneratedCaseDraft,
    GenerationAttempt,
    GenerationFailureCandidate,
    GenerationTask,
    QualityReport,
)
from app.models.requirement import RequirementDocument, RequirementItem
from app.services.quality_checker import (
    build_quality_report,
    check_case,
    detect_duplicates,
    is_meaningful_case,
    normalize_steps,
)
from app.services.knowledge_service import (
    DEFAULT_TOP_K,
    RECALL_TOP_K,
    RRF_K,
    SIMILARITY_THRESHOLD,
)
from app.services.settings_service import get_project_runtime_config
from app.services.evaluation_experiment_service import runtime_config_from_snapshot
from app.services.multi_agent_service import (
    CandidateCase,
    classify_candidate_dispositions,
    merge_candidates,
    persist_candidate_cases,
    run_specialists,
)
from app.skills.base import SkillContext
from app.skills.registry import get_registry
from app.workflows.generation.state import GenerationState
from app.workflows.generation.failure_policy import classify_failure, redact_output


def _task_or_raise(db, task_id: int) -> GenerationTask:
    task = db.get(GenerationTask, task_id)
    if not task:
        raise RuntimeError("生成任务不存在")
    return task


def _feature_data(item: RequirementItem) -> dict:
    return {
        "module": item.module,
        "feature": item.feature,
        "description": item.description,
        "acceptance_criteria": item.acceptance_criteria,
        "constraints": item.constraints,
        "priority": item.priority,
    }


def _parse_scope(raw: str) -> dict | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    normalized = {
        "in_scope": [str(s).strip() for s in (data.get("in_scope") or []) if str(s).strip()],
        "out_scope": [str(s).strip() for s in (data.get("out_scope") or []) if str(s).strip()],
        "risks": [str(s).strip() for s in (data.get("risks") or []) if str(s).strip()],
    }
    return normalized if any(normalized.values()) else None


def _strategy_config(task: GenerationTask) -> dict:
    registry = get_registry()
    try:
        data = json.loads(task.strategy_config or "{}")
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    preset = data.get("strategy") or data.get("preset") or task.strategy
    raw_policy = data.get("skill_policy")
    specialist_policy: dict[str, dict] = {}
    if isinstance(raw_policy, dict) and isinstance(raw_policy.get("specialists"), dict):
        for raw_name, raw_value in raw_policy["specialists"].items():
            if not isinstance(raw_value, dict):
                if task.is_eval:
                    raise ValueError(
                        f"incomplete immutable Skill policy: {raw_name}"
                    )
                continue
            try:
                skill = registry.get_skill(str(raw_name))
                if skill.category != "specialist" or not skill.ui.selectable:
                    if task.is_eval:
                        raise ValueError("Skill is not a selectable Specialist")
                    continue
                timeout_seconds = float(raw_value["timeout_seconds"])
                max_cases = int(raw_value["max_cases"])
                execution_order = int(raw_value["execution_order"])
                prompt_version = str(raw_value["prompt_version"])
                if not 30 <= timeout_seconds <= skill.timeout_seconds:
                    if task.is_eval:
                        raise ValueError("Specialist timeout exceeds the frozen contract")
                    continue
                if skill.policy is None or not 1 <= max_cases <= skill.policy.max_cases:
                    if task.is_eval:
                        raise ValueError("Specialist case budget exceeds the frozen contract")
                    continue
                if prompt_version not in skill.policy.prompt_versions:
                    if task.is_eval:
                        raise ValueError("Specialist prompt version is unavailable")
                    continue
            except (KeyError, TypeError, ValueError) as exc:
                if task.is_eval:
                    raise ValueError(
                        f"frozen Specialist policy is unavailable: {raw_name}"
                    ) from exc
                continue
            specialist_policy[skill.name] = {
                "timeout_seconds": timeout_seconds,
                "max_cases": max_cases,
                "execution_order": execution_order,
                "prompt_version": prompt_version,
            }
    ordered_specialists = [
        name for name, _ in sorted(
            specialist_policy.items(),
            key=lambda item: (item[1]["execution_order"], item[0]),
        )
    ]
    if task.is_eval:
        requested_specialists = {
            str(name) for name in (data.get("specialist_skills") or [])
        }
        if requested_specialists != set(ordered_specialists):
            raise ValueError(
                "incomplete immutable Skill policy: selected Specialists do not match"
            )
    raw_retrieval = data.get("retrieval") if isinstance(data.get("retrieval"), dict) else {}
    retrieval = {
        "top_k": int(raw_retrieval.get("top_k", DEFAULT_TOP_K)),
        "recall_top_k": int(raw_retrieval.get("recall_top_k", RECALL_TOP_K)),
        "similarity_threshold": float(
            raw_retrieval.get("similarity_threshold", SIMILARITY_THRESHOLD)
        ),
        "rrf_k": int(raw_retrieval.get("rrf_k", RRF_K)),
    }
    return {
        "strategy": registry.normalize_strategy(preset),
        "specialist_skills": ordered_specialists,
        "specialist_policy": specialist_policy,
        "use_knowledge": bool(data.get("use_knowledge", False)),
        "retrieval": retrieval,
    }


def _runtime_model_config(db, task: GenerationTask):
    live_secrets = get_project_runtime_config(db, task.project_id)
    if not task.is_eval:
        return live_secrets
    try:
        snapshot = json.loads(task.strategy_config or "{}")
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("incomplete immutable config snapshot: invalid JSON") from exc
    return runtime_config_from_snapshot(snapshot, live_secrets)


def _skill_context(task: GenerationTask, strategy: str, model_config) -> SkillContext:
    from app.agent_runtime.harness import get_active_runtime_harness

    return SkillContext(
        model_config=model_config,
        project_id=task.project_id,
        task_id=task.id,
        strategy=strategy,
        use_mock=model_config.use_mock_llm,
        runtime=get_active_runtime_harness(),
    )


def _structured_output_failure(state: GenerationState, exc: OutputParserException) -> dict:
    """首次格式错误交给 Graph 重试；第二次直接失败并停在生成节点前。"""
    if state.get("retry_count", 0) >= 1:
        raise RuntimeError(f"模型连续两次未返回有效结构化结果：{exc}") from exc
    return {"current_cases": [], "generation_error": str(exc)}


def _decision_data(decision) -> dict:
    return {
        "code": str(decision.code),
        "recoverable": decision.recoverable,
        "retry_kind": str(decision.retry_kind),
        "message": decision.directive.message,
        "delay_seconds": decision.directive.delay_seconds,
        "reduce_scope": decision.directive.reduce_scope,
    }


def _record_case_writer_attempt(
    db,
    state: GenerationState,
    *,
    status: str,
    started_at: float,
    failure_code: str = "",
    failure_detail: dict | None = None,
    retry_directive: dict | None = None,
    raw_output: str = "",
) -> int:
    item_id = state.get("current_feature_id")
    attempt_no = (
        db.query(GenerationAttempt)
        .filter(
            GenerationAttempt.task_id == state["task_id"],
            GenerationAttempt.requirement_item_id == item_id,
            GenerationAttempt.skill_name == "case_writer",
        )
        .count()
        + 1
    )
    task = _task_or_raise(db, state["task_id"])
    db.add(
        GenerationAttempt(
            task_id=task.id,
            requirement_item_id=item_id,
            skill_name="case_writer",
            attempt_no=attempt_no,
            status=status,
            failure_code=failure_code,
            failure_detail=json.dumps(failure_detail or {}, ensure_ascii=False),
            retry_directive=json.dumps(retry_directive or {}, ensure_ascii=False),
            model_snapshot=task.strategy_config or "{}",
            raw_output=redact_output(raw_output),
            latency_ms=int((time.monotonic() - started_at) * 1000),
        )
    )
    db.commit()
    return attempt_no


async def load_task(state: GenerationState) -> dict:
    task_id = state["task_id"]
    db = SessionLocal()
    try:
        task = _task_or_raise(db, task_id)
        items = (
            db.query(RequirementItem)
            .filter(
                RequirementItem.document_id == task.document_id,
                RequirementItem.confirmed == True,
            )
            .order_by(RequirementItem.sort_order)
            .all()
        )
        if not items:
            raise RuntimeError("没有已确认的功能点")

        document = db.get(RequirementDocument, task.document_id)
        config = _strategy_config(task)

        task.status = "generating"
        task.progress = 0
        task.stage = "准备中"
        task.error_message = ""
        db.query(GeneratedCaseDraft).filter(GeneratedCaseDraft.task_id == task.id).delete()
        existing_report = db.query(QualityReport).filter(QualityReport.task_id == task.id).first()
        if existing_report:
            db.delete(existing_report)
        db.commit()

        return {
            "project_id": task.project_id,
            "document_id": task.document_id,
            "feature_ids": [item.id for item in items],
            "feature_index": 0,
            "current_feature_id": None,
            "current_feature": None,
            "strategy": config["strategy"],
            "specialist_skills": config["specialist_skills"],
            "specialist_policy": config["specialist_policy"],
            "use_knowledge": config["use_knowledge"],
            "retrieval": config["retrieval"],
            "scope": _parse_scope(document.test_scope) if document else None,
            "retrieval_query": "",
            "knowledge": [],
            "knowledge_refs": {},
            "current_cases": [],
            "core_cases": [],
            "specialist_cases": {},
            "specialist_warnings": [],
            "retry_count": 0,
            "generation_error": "",
            "case_writer_attempt_count": 0,
            "retry_directive": "",
            "failure_decision": {},
            "has_failure_candidates": False,
            "duplicate_count": 0,
        }
    finally:
        db.close()


async def prepare_feature(state: GenerationState) -> dict:
    item_id = state["feature_ids"][state["feature_index"]]
    db = SessionLocal()
    try:
        item = db.get(RequirementItem, item_id)
        if not item:
            raise RuntimeError(f"功能点不存在: {item_id}")
        task = _task_or_raise(db, state["task_id"])
        total = len(state["feature_ids"])
        task.stage = f"生成用例 {state['feature_index'] + 1}/{total}：{item.feature}"
        db.commit()
        return {
            "current_feature_id": item.id,
            "current_feature": _feature_data(item),
            "retrieval_query": " ".join(filter(None, [item.module, item.feature, item.description])),
            "knowledge": [],
            "current_cases": [],
            "retry_count": 0,
            "generation_error": "",
            "case_writer_attempt_count": 0,
            "retry_directive": "",
            "failure_decision": {},
        }
    finally:
        db.close()


async def retrieve_knowledge(state: GenerationState) -> dict:
    if not state.get("use_knowledge"):
        return {"knowledge": []}

    db = SessionLocal()
    try:
        task = _task_or_raise(db, state["task_id"])
        task.stage = f"检索知识：{(state.get('current_feature') or {}).get('feature', '')}"
        db.commit()
        model_config = _runtime_model_config(db, task)
        retrieval = state.get("retrieval") or {}
        retriever = AITCHybridRetriever(
            db=db,
            project_id=state["project_id"],
            runtime_config=model_config,
            top_k=int(retrieval.get("top_k", DEFAULT_TOP_K)),
            recall_top_k=int(retrieval.get("recall_top_k", RECALL_TOP_K)),
            threshold=float(
                retrieval.get("similarity_threshold", SIMILARITY_THRESHOLD)
            ),
            rrf_k=int(retrieval.get("rrf_k", RRF_K)),
        )
        try:
            documents = await retriever.ainvoke(state.get("retrieval_query", ""))
        except (BudgetExhausted, RuntimeCancelled):
            raise
        except Exception:
            return {"knowledge": []}

        knowledge = documents_to_knowledge(documents)
        refs = dict(state.get("knowledge_refs") or {})
        if knowledge:
            refs[str(state["current_feature_id"])] = [
                {
                    "title": item.get("title", ""),
                    "heading": item.get("heading", ""),
                    "score": item.get("score", 0.0),
                    "match": item.get("match", "vector"),
                }
                for item in knowledge
            ]
        return {"knowledge": knowledge, "knowledge_refs": refs}
    finally:
        db.close()


async def generate_core_cases(state: GenerationState) -> dict:
    db = SessionLocal()
    try:
        task = _task_or_raise(db, state["task_id"])
        model_config = _runtime_model_config(db, task)
        context = _skill_context(task, state["strategy"], model_config)
        task.stage = f"生成基础用例：{(state.get('current_feature') or {}).get('feature', '')}"
        db.commit()
        started_at = time.monotonic()
        try:
            result = await get_registry().run(
                "case_writer",
                {
                    "feature_item": state["current_feature"],
                    "strategy": state["strategy"],
                    "scope": state.get("scope"),
                    "knowledge": state.get("knowledge") or [],
                    "repair_instruction": state.get("retry_directive", ""),
                },
                context,
            )
        except (BudgetExhausted, RuntimeCancelled):
            raise
        except Exception as exc:
            decision = classify_failure(
                exc,
                [],
                state.get("case_writer_attempt_count", 0) + 1,
            )
            decision_data = _decision_data(decision)
            attempt_no = _record_case_writer_attempt(
                db,
                state,
                status="failed",
                started_at=started_at,
                failure_code=decision_data["code"],
                failure_detail={"message": redact_output(str(exc))},
                retry_directive=decision_data,
                raw_output=getattr(exc, "llm_output", "") or str(exc),
            )
            return {
                "current_cases": [],
                "case_writer_attempt_count": attempt_no,
                "generation_error": redact_output(str(exc)),
                "failure_decision": decision_data,
                "retry_directive": decision_data["message"],
            }
        cases = list(result.get("cases") or [])
        attempt_no = _record_case_writer_attempt(
            db,
            state,
            status="succeeded",
            started_at=started_at,
            raw_output=json.dumps(cases, ensure_ascii=False),
        )
        return {
            "current_cases": cases,
            "core_cases": cases,
            "case_writer_attempt_count": attempt_no,
            "generation_error": "",
            "failure_decision": {},
            "retry_directive": "",
        }
    finally:
        db.close()


async def generate_specialist_cases(state: GenerationState) -> dict:
    specialist_skills = state.get("specialist_skills") or []
    if not specialist_skills:
        return {"generation_error": ""}

    db = SessionLocal()
    try:
        task = _task_or_raise(db, state["task_id"])
        model_config = _runtime_model_config(db, task)
        context = _skill_context(task, state["strategy"], model_config)
        if context.runtime is not None:
            snapshot = context.runtime.context.spec_snapshot
            runtime_policy = snapshot.get("skill_policy")
            if runtime_policy != json.loads(task.strategy_config or "{}").get("skill_policy"):
                specialist_skills = []
        if not specialist_skills:
            return {"specialist_cases": {}, "specialist_warnings": [], "generation_error": ""}
        async def invoke(skill_name: str) -> list[dict]:
            policy = (state.get("specialist_policy") or {}).get(skill_name)
            if not isinstance(policy, dict):
                return []
            result = await get_registry().run(
                skill_name,
                {
                    "feature_item": state["current_feature"],
                    "scope": state.get("scope"),
                    "knowledge": state.get("knowledge") or [],
                    "core_cases": list(state.get("core_cases") or state.get("current_cases") or [])[:20],
                },
                replace(
                    context,
                    timeout_seconds=policy["timeout_seconds"],
                    max_cases=policy["max_cases"],
                    prompt_version=policy["prompt_version"],
                ),
            )
            cases = list(result.get("cases") or [])
            for case in cases:
                case["skill_name"] = skill_name
            return cases

        specialist_cases, warnings = await run_specialists(
            specialist_skills, invoke, runtime=context.runtime
        )
        return {
            "specialist_cases": specialist_cases,
            "specialist_warnings": warnings,
            "generation_error": "",
        }

    finally:
        db.close()


async def merge_agent_candidates(state: GenerationState) -> dict:
    """Coordinator-only deterministic merge before validation and draft persistence."""
    candidates = [
        CandidateCase("case_writer", case, list(state.get("knowledge") or []))
        for case in (state.get("core_cases") or state.get("current_cases") or [])
    ]
    for source_agent, cases in (state.get("specialist_cases") or {}).items():
        candidates.extend(
            CandidateCase(source_agent, case, list(state.get("knowledge") or []))
            for case in cases
        )
    merged = merge_candidates(candidates)
    from app.agent_runtime.harness import get_active_runtime_harness

    runtime = get_active_runtime_harness()
    if runtime is not None:
        db = SessionLocal()
        try:
            persist_candidate_cases(
                db,
                state["task_id"],
                state.get("current_feature_id"),
                runtime.context.run_id,
                candidates,
                classify_candidate_dispositions(candidates),
                attempt_no=state.get("retry_count", 0),
            )
        finally:
            db.close()
    return {
        "current_cases": [
            {
                **item.case,
                "source_agents": item.source_agents,
                "evidence_refs": item.evidence_refs,
                "merge_reason": item.merge_reason,
            }
            for item in merged
        ],
    }


async def validate_cases(state: GenerationState) -> dict:
    normalized_cases = []
    for case in state.get("current_cases") or []:
        if not isinstance(case, dict):
            continue
        steps_text, steps_list = normalize_steps(case)
        if not is_meaningful_case(case, steps_list):
            continue
        quality_status, quality_issues = check_case({**case, "steps": steps_list})
        normalized_cases.append(
            {
                "title": (case.get("title") or "").strip(),
                "priority": case.get("priority", "P2"),
                "case_type": case.get("case_type", "functional"),
                "is_smoke": bool(case.get("is_smoke", False)),
                "precondition": (case.get("precondition") or "").strip(),
                "steps": steps_text,
                "expected_result": (case.get("expected_result") or "").strip(),
                "quality_status": quality_status,
                "quality_issues": json.dumps(quality_issues, ensure_ascii=False),
                "skill_name": case.get("skill_name", ""),
                "source_agents": case.get("source_agents", [case.get("skill_name", "")]),
                "evidence_refs": case.get("evidence_refs", []),
                "merge_reason": case.get("merge_reason", ""),
            }
        )
    return {"current_cases": normalized_cases}


async def retry_feature(state: GenerationState) -> dict:
    retry_count = state.get("retry_count", 0) + 1
    delay_seconds = float((state.get("failure_decision") or {}).get("delay_seconds") or 0)
    if delay_seconds:
        await asyncio.sleep(delay_seconds)
    db = SessionLocal()
    try:
        task = _task_or_raise(db, state["task_id"])
        task.stage = f"结构校验失败，重新生成（{retry_count}/1）"
        db.commit()
    finally:
        db.close()
    retry_directive = state.get("retry_directive") or (
        "未生成可用测试用例；请只返回符合既定 Schema 的 JSON，并确保至少包含一条可执行用例。"
    )
    return {
        "retry_count": retry_count,
        "current_cases": [],
        "generation_error": "",
        "retry_directive": retry_directive,
        "failure_decision": {},
    }


async def record_feature_failure(state: GenerationState) -> dict:
    """记录最终失败并让图继续处理下一个功能点。"""
    db = SessionLocal()
    try:
        task = _task_or_raise(db, state["task_id"])
        item_id = state.get("current_feature_id")
        latest_attempt = (
            db.query(GenerationAttempt)
            .filter(
                GenerationAttempt.task_id == task.id,
                GenerationAttempt.requirement_item_id == item_id,
                GenerationAttempt.skill_name == "case_writer",
            )
            .order_by(GenerationAttempt.attempt_no.desc())
            .first()
        )
        decision = state.get("failure_decision") or {}
        existing = (
            db.query(GenerationFailureCandidate)
            .filter(
                GenerationFailureCandidate.task_id == task.id,
                GenerationFailureCandidate.requirement_item_id == item_id,
                GenerationFailureCandidate.status == "pending",
            )
            .first()
        )
        if not existing:
            feature = state.get("current_feature") or {}
            db.add(
                GenerationFailureCandidate(
                    task_id=task.id,
                    requirement_item_id=item_id,
                    final_attempt_id=latest_attempt.id if latest_attempt else None,
                    title=feature.get("feature", ""),
                    input_snapshot=json.dumps(
                        {"feature_item": feature, "scope": state.get("scope")},
                        ensure_ascii=False,
                    ),
                    failure_code=decision.get("code") or "EMPTY_CASES",
                )
            )
        db.commit()
        return {
            "feature_index": state["feature_index"] + 1,
            "current_cases": [],
            "generation_error": "",
            "has_failure_candidates": True,
        }
    finally:
        db.close()


async def persist_feature_cases(state: GenerationState) -> dict:
    from app.agent_runtime.harness import get_active_runtime_harness

    runtime = get_active_runtime_harness()
    db = SessionLocal()
    try:
        task = _task_or_raise(db, state["task_id"])
        item_id = state["current_feature_id"]
        for index, case in enumerate(state.get("current_cases") or []):
            skill_name = case.get("skill_name", "")
            generation_key = f"{task.id}:{item_id}:{skill_name}:{index}"
            draft = (
                db.query(GeneratedCaseDraft)
                .filter(GeneratedCaseDraft.generation_key == generation_key)
                .first()
            )
            if draft is None:
                draft = GeneratedCaseDraft(
                    task_id=task.id,
                    requirement_item_id=item_id,
                    generation_key=generation_key,
                )
                db.add(draft)
            draft.agent_run_id = runtime.context.run_id if runtime is not None else None
            draft.title = case["title"]
            draft.priority = case["priority"]
            draft.case_type = case["case_type"]
            draft.is_smoke = case["is_smoke"]
            draft.precondition = case["precondition"]
            draft.steps = case["steps"]
            draft.expected_result = case["expected_result"]
            draft.quality_status = case["quality_status"]
            draft.quality_issues = case["quality_issues"]
            draft.skill_name = skill_name
            draft.source_agents = json.dumps(case.get("source_agents") or [], ensure_ascii=False)
            draft.evidence_refs = json.dumps(case.get("evidence_refs") or [], ensure_ascii=False)
            draft.merge_reason = case.get("merge_reason", "")

        next_index = state["feature_index"] + 1
        task.progress = int(next_index / len(state["feature_ids"]) * 80)
        db.commit()
        return {"feature_index": next_index, "current_cases": []}
    finally:
        db.close()


async def detect_task_duplicates(state: GenerationState) -> dict:
    db = SessionLocal()
    try:
        task = _task_or_raise(db, state["task_id"])
        task.stage = "重复检测"
        task.progress = 85
        drafts = db.query(GeneratedCaseDraft).filter(GeneratedCaseDraft.task_id == task.id).all()
        duplicate_count = detect_duplicates(drafts)
        db.commit()
        return {"duplicate_count": duplicate_count}
    finally:
        db.close()


async def run_task_judge(state: GenerationState) -> dict:
    # 延迟导入，避免 generation_service 的兼容门面与 Graph 模块循环依赖。
    from app.services.generation_service import run_judge_for_task

    db = SessionLocal()
    try:
        task = _task_or_raise(db, state["task_id"])
        model_config = _runtime_model_config(db, task)
        await run_judge_for_task(db, task, model_config)
        return {}
    finally:
        db.close()


async def build_task_report(state: GenerationState) -> dict:
    db = SessionLocal()
    try:
        task = _task_or_raise(db, state["task_id"])
        task.stage = "生成质检报告"
        task.progress = 95
        items = (
            db.query(RequirementItem)
            .filter(RequirementItem.id.in_(state["feature_ids"]))
            .order_by(RequirementItem.sort_order)
            .all()
        )
        drafts = db.query(GeneratedCaseDraft).filter(GeneratedCaseDraft.task_id == task.id).all()
        item_case_map: dict[int, list[GeneratedCaseDraft]] = {}
        for draft in drafts:
            item_case_map.setdefault(draft.requirement_item_id, []).append(draft)
        report_data = build_quality_report(
            drafts,
            items,
            item_case_map,
            state.get("duplicate_count", 0),
        )
        existing = db.query(QualityReport).filter(QualityReport.task_id == task.id).first()
        if existing:
            db.delete(existing)
        db.add(QualityReport(task_id=task.id, **report_data))
        refs = state.get("knowledge_refs") or {}
        task.knowledge_refs = json.dumps(refs, ensure_ascii=False) if refs else ""
        db.commit()
        return {}
    finally:
        db.close()


async def finalize_task(state: GenerationState) -> dict:
    db = SessionLocal()
    try:
        task = _task_or_raise(db, state["task_id"])
        has_failure_candidates = db.query(GenerationFailureCandidate).filter(
            GenerationFailureCandidate.task_id == task.id
        ).count() > 0
        task.status = final_task_status(has_failure_candidates)
        task.progress = 100
        task.stage = ""
        task.error_message = ""
        db.commit()
        return {}
    finally:
        db.close()


def final_task_status(has_failure_candidates: bool) -> str:
    return "completed_with_warnings" if has_failure_candidates else "completed"


def route_after_generation(state: GenerationState) -> str:
    if not state.get("generation_error"):
        return "continue"
    decision = state.get("failure_decision") or {}
    if decision and not decision.get("recoverable"):
        return "feature_failed"
    return "retry"


def route_after_validation(state: GenerationState) -> str:
    if state.get("current_cases"):
        return "persist"
    if state.get("retry_count", 0) >= 1:
        return "feature_failed"
    return "retry"


def route_next_feature(state: GenerationState) -> str:
    if state["feature_index"] < len(state["feature_ids"]):
        return "next"
    return "quality"
