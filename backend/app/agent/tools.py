"""测试助手工具集：六个只读查询工具 + 五个用例生成流水线工具，输出统一为 JSON 字符串。

全部工具在构建时绑定 project_id，LLM 无法跨项目取数或操作；列表类输出做条数与
文本截断，避免把整个用例库塞进上下文。

流水线工具复用现有生成链路（structure_requirements / confirm_requirements /
GenerationTask + LangGraph 工作流 / adopt_drafts / reject_drafts），Agent 只是新入口，
产物与向导页、生成记录页、评审页完全共用。
"""

import asyncio
import contextvars
import json
from dataclasses import asdict

from langchain_core.tools import StructuredTool
from sqlalchemy.orm import Session, selectinload

from app.models.execution import TestBatch, TestBatchCase, TestTask
from app.models.generation import GeneratedCaseDraft, GenerationTask
from app.models.requirement import RequirementDocument, RequirementItem
from app.models.testcase import TestCase
from app.agent_runtime.service import create_case_writer_run
from app.agent_runtime.contracts import BudgetExhausted, RuntimeCancelled
from app.services import knowledge_service
from app.services.generation_service import (
    adopt_drafts,
    build_strategy_config,
    confirm_requirements,
    reject_drafts,
    structure_requirements,
)
from app.services.skill_policy_service import get_project_policy_state
from app.skills.policy import PolicyResolver
from app.skills.registry import get_registry
from app.services.settings_service import RuntimeModelConfig
from app.workflows.generation.runner import run_generation_workflow

MAX_LIST_ITEMS = 20  # 列表类工具单次最多返回条数
SNIPPET_CHARS = 400  # 知识分块注入上下文的最大字符数

# 持有后台生成任务的引用，防止 asyncio.Task 被垃圾回收后中断
_background_tasks: set[asyncio.Task] = set()


def start_generation_background(task_id: int) -> None:
    """在当前事件循环中后台执行生成工作流（runner 自建 session，不依赖调用方事务）。"""
    # 使用空 Context，避免继承 Agent 图的 recursion_limit、callbacks 等运行配置。
    task = asyncio.get_running_loop().create_task(
        run_generation_workflow(task_id),
        context=contextvars.Context(),
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _dump(data) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _clip(text: str, limit: int = SNIPPET_CHARS) -> str:
    text = text or ""
    return text if len(text) <= limit else f"{text[:limit]}……（已截断）"


def build_agent_tools(
    db: Session,
    project_id: int,
    model_config: RuntimeModelConfig,
    *,
    parent_run_id: int | None = None,
) -> list[StructuredTool]:
    """构建绑定到指定项目的查询工具与用例生成流水线工具。"""

    async def search_knowledge(query: str) -> str:
        try:
            hits = await knowledge_service.retrieve(
                db, project_id, query, top_k=5, model_config=model_config
            )
        except (BudgetExhausted, RuntimeCancelled):
            raise
        except Exception as exc:
            return _dump({"error": f"知识库检索失败：{exc}"})
        if not hits:
            return _dump({"hits": [], "message": "知识库中没有检索到相关内容"})
        return _dump({
            "hits": [
                {
                    "title": h["title"],
                    "heading": h["heading"],
                    "content": _clip(h["content"]),
                    "score": h["score"],
                    "match": h["match"],
                }
                for h in hits
            ]
        })

    def list_testcases(
        keyword: str = "",
        priority: str = "",
        case_type: str = "",
        module: str = "",
        limit: int = MAX_LIST_ITEMS,
    ) -> str:
        q = (
            db.query(TestCase, RequirementItem.module, RequirementItem.feature)
            .outerjoin(RequirementItem, TestCase.requirement_item_id == RequirementItem.id)
            .filter(TestCase.project_id == project_id)
        )
        if keyword.strip():
            q = q.filter(TestCase.title.ilike(f"%{keyword.strip()}%"))
        if priority.strip():
            q = q.filter(TestCase.priority == priority.strip().upper())
        if case_type.strip():
            q = q.filter(TestCase.case_type == case_type.strip())
        if module.strip():
            q = q.filter(RequirementItem.module.ilike(f"%{module.strip()}%"))
        total = q.count()
        limit = max(1, min(limit, MAX_LIST_ITEMS))
        rows = q.order_by(TestCase.priority, TestCase.id).limit(limit).all()
        return _dump({
            "total": total,
            "returned": len(rows),
            "note": "" if total <= limit else f"共 {total} 条，仅返回前 {limit} 条，可用筛选条件缩小范围",
            "cases": [
                {
                    "id": tc.id,
                    "title": tc.title,
                    "priority": tc.priority,
                    "case_type": tc.case_type,
                    "is_smoke": tc.is_smoke,
                    "module": m or "",
                    "feature": f or "",
                }
                for tc, m, f in rows
            ],
        })

    def get_testcase_detail(case_id: int) -> str:
        row = (
            db.query(TestCase, RequirementItem.module, RequirementItem.feature)
            .outerjoin(RequirementItem, TestCase.requirement_item_id == RequirementItem.id)
            .filter(TestCase.project_id == project_id, TestCase.id == case_id)
            .first()
        )
        if not row:
            return _dump({"error": f"该项目中不存在 ID 为 {case_id} 的用例"})
        tc, module, feature = row
        return _dump({
            "id": tc.id,
            "title": tc.title,
            "priority": tc.priority,
            "case_type": tc.case_type,
            "is_smoke": tc.is_smoke,
            "module": module or "",
            "feature": feature or "",
            "precondition": tc.precondition,
            "steps": tc.steps,
            "expected_result": tc.expected_result,
            "status": tc.status,
            "source": tc.source,
        })

    def get_coverage_summary() -> str:
        items = (
            db.query(RequirementItem)
            .join(RequirementDocument, RequirementItem.document_id == RequirementDocument.id)
            .filter(RequirementDocument.project_id == project_id, RequirementItem.confirmed == True)  # noqa: E712
            .all()
        )
        if not items:
            return _dump({"message": "该项目还没有已确认的功能点，无法统计覆盖率"})
        covered_ids = {
            item_id
            for (item_id,) in db.query(TestCase.requirement_item_id)
            .filter(TestCase.project_id == project_id, TestCase.requirement_item_id.isnot(None))
            .distinct()
        }
        uncovered = [i for i in items if i.id not in covered_ids]
        return _dump({
            "confirmed_features": len(items),
            "covered_features": len(items) - len(uncovered),
            "coverage_rate": round((len(items) - len(uncovered)) / len(items) * 100, 1),
            "uncovered": [
                {"module": i.module, "feature": i.feature}
                for i in uncovered[:MAX_LIST_ITEMS]
            ],
        })

    def get_test_task_stats(task_name: str = "") -> str:
        q = (
            db.query(TestTask)
            .options(selectinload(TestTask.batches).selectinload(TestBatch.batch_cases))
            .filter(TestTask.project_id == project_id)
        )
        if task_name.strip():
            q = q.filter(TestTask.name.ilike(f"%{task_name.strip()}%"))
        tasks = q.order_by(TestTask.created_at.desc()).limit(10).all()
        if not tasks:
            return _dump({"message": "没有找到匹配的测试任务"})
        return _dump({
            "tasks": [
                {
                    "id": t.id,
                    "name": t.name,
                    "status": t.status,
                    "stats": t.stats,
                    "batches": [
                        {"id": b.id, "name": b.name, "status": b.status, "stats": b.stats}
                        for b in t.batches
                    ],
                }
                for t in tasks
            ]
        })

    def _get_document(document_id: int) -> RequirementDocument | None:
        return (
            db.query(RequirementDocument)
            .filter(
                RequirementDocument.id == document_id,
                RequirementDocument.project_id == project_id,
            )
            .first()
        )

    def _items_summary(document_id: int) -> list[dict]:
        items = (
            db.query(RequirementItem)
            .filter(RequirementItem.document_id == document_id)
            .order_by(RequirementItem.sort_order)
            .all()
        )
        return [
            {
                "id": it.id,
                "module": it.module,
                "feature": it.feature,
                "priority": it.priority,
                "description": _clip(it.description, 120),
                "confirmed": it.confirmed,
            }
            for it in items
        ]

    async def parse_requirement_document(document_id: int) -> str:
        doc = _get_document(document_id)
        if not doc:
            return _dump({"error": f"该项目中不存在 ID 为 {document_id} 的需求文档"})
        if not (doc.raw_content or "").strip():
            return _dump({"error": "该文档没有原文内容（可能是导入的功能清单），无需 AI 解析"})
        try:
            await structure_requirements(db, doc)
        except (BudgetExhausted, RuntimeCancelled):
            raise
        except Exception as exc:
            return _dump({"error": f"需求解析失败：{exc}"})
        items = _items_summary(document_id)
        return _dump({
            "document_id": document_id,
            "title": doc.title,
            "item_count": len(items),
            "items": items,
            "next_step": "请把功能点清单展示给用户，等用户明确确认后再调用 confirm_features 和 start_generation",
        })

    def confirm_features(document_id: int, item_ids: list[int] | None = None) -> str:
        doc = _get_document(document_id)
        if not doc:
            return _dump({"error": f"该项目中不存在 ID 为 {document_id} 的需求文档"})
        if not doc.items:
            return _dump({"error": "该文档还没有功能点，请先调用 parse_requirement_document 解析"})
        if item_ids:
            valid_ids = {it.id for it in doc.items}
            invalid = [i for i in item_ids if i not in valid_ids]
            if invalid:
                return _dump({"error": f"以下功能点 ID 不属于该文档：{invalid}"})
        confirm_requirements(db, document_id, item_ids or None)
        confirmed = sum(1 for it in doc.items if it.confirmed)
        return _dump({
            "document_id": document_id,
            "confirmed_count": confirmed,
            "message": f"已确认 {confirmed} 个功能点，可以调用 start_generation 启动生成",
        })

    async def start_generation(
        document_id: int,
        strategy: str = "full",
        specialist_skills: list[str] | None = None,
        use_knowledge: bool = False,
    ) -> str:
        doc = _get_document(document_id)
        if not doc:
            return _dump({"error": f"该项目中不存在 ID 为 {document_id} 的需求文档"})
        if doc.status != "confirmed":
            return _dump({"error": "功能点尚未确认，请先与用户确认清单后调用 confirm_features"})

        try:
            policy_state = get_project_policy_state(db, project_id)
            resolved_policy = PolicyResolver(get_registry()).resolve_requested(
                list(policy_state.overrides),
                specialist_skills or [],
                revision_no=policy_state.revision_no,
            )
            strategy_config = build_strategy_config(
                strategy=strategy,
                specialist_skills=specialist_skills or [],
                use_knowledge=use_knowledge,
                model_config=model_config,
                strict_specialists=True,
                policy_state=resolved_policy,
            )
        except ValueError as exc:
            return _dump({"error": str(exc)})

        task = GenerationTask(
            project_id=project_id,
            document_id=document_id,
            strategy=strategy,
            strategy_config=json.dumps(strategy_config, ensure_ascii=False),
            status="pending",
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        response = {
            "task_id": task.id,
            "document_id": document_id,
            "strategy": strategy,
            "status": "pending",
            "message": (
                f"生成任务 #{task.id} 已启动，会在后台执行几分钟。"
                "告诉用户可以在对话里追问进度，或到「AI 生成」页查看与评审。"
            ),
        }
        if parent_run_id is not None:
            child = create_case_writer_run(
                db,
                task,
                model_snapshot=asdict(model_config),
                parent_run_id=parent_run_id,
            )
            response["agent_run_id"] = child.id
        else:
            start_generation_background(task.id)
        return _dump(response)

    def get_generation_status(task_id: int) -> str:
        # 工作流在独立 session 写库，先失效缓存拿最新状态
        db.expire_all()
        task = (
            db.query(GenerationTask)
            .filter(GenerationTask.id == task_id, GenerationTask.project_id == project_id)
            .first()
        )
        if not task:
            return _dump({"error": f"该项目中不存在 ID 为 {task_id} 的生成任务"})
        report = task.quality_report
        return _dump({
            "task_id": task.id,
            "status": task.status,
            "stage": task.stage,
            "progress": task.progress,
            "error_message": task.error_message,
            "draft_count": len(task.drafts or []),
            "review_stats": task.review_stats,
            "quality_report": {
                "coverage_rate": report.coverage_rate,
                "avg_judge_score": report.avg_judge_score,
                "hallucination_count": report.hallucination_count,
                "duplicate_count": report.duplicate_count,
            } if report else None,
        })

    def review_generated_drafts(
        task_id: int,
        action: str,
        draft_ids: list[int] | None = None,
        priority: str = "",
        smoke_only: bool = False,
        reject_reason: str = "",
    ) -> str:
        if action not in ("adopt", "reject"):
            return _dump({"error": "action 只能是 adopt（采纳）或 reject（驳回）"})
        task = (
            db.query(GenerationTask)
            .filter(GenerationTask.id == task_id, GenerationTask.project_id == project_id)
            .first()
        )
        if not task:
            return _dump({"error": f"该项目中不存在 ID 为 {task_id} 的生成任务"})

        q = db.query(GeneratedCaseDraft).filter(
            GeneratedCaseDraft.task_id == task_id,
            # 已采纳/已驳回是终态，不允许重复操作
            GeneratedCaseDraft.review_status.notin_(["adopted", "rejected"]),
        )
        if draft_ids:
            q = q.filter(GeneratedCaseDraft.id.in_(draft_ids))
        if priority.strip():
            q = q.filter(GeneratedCaseDraft.priority == priority.strip().upper())
        if smoke_only:
            q = q.filter(GeneratedCaseDraft.is_smoke == True)  # noqa: E712
        target_ids = [d.id for d in q.all()]
        if not target_ids:
            return _dump({"message": "没有符合条件的待评审用例（已采纳/已驳回的不会重复操作）"})

        if action == "adopt":
            adopted = adopt_drafts(db, task_id, target_ids)
            return _dump({
                "action": "adopt",
                "count": len(adopted),
                "message": f"已采纳 {len(adopted)} 条用例并入库为正式测试用例",
            })
        reject_drafts(db, task_id, target_ids, reject_reason)
        return _dump({
            "action": "reject",
            "count": len(target_ids),
            "message": f"已驳回 {len(target_ids)} 条用例",
        })

    def list_defects(include_blocked: bool = True) -> str:
        results = ["failed", "blocked"] if include_blocked else ["failed"]
        rows = (
            db.query(TestBatchCase, TestBatch, TestTask, TestCase)
            .join(TestBatch, TestBatchCase.batch_id == TestBatch.id)
            .join(TestTask, TestBatch.task_id == TestTask.id)
            .join(TestCase, TestBatchCase.case_id == TestCase.id)
            .filter(TestTask.project_id == project_id, TestBatchCase.result.in_(results))
            .order_by(TestBatchCase.executed_at.desc())
            .limit(MAX_LIST_ITEMS)
            .all()
        )
        if not rows:
            return _dump({"defects": [], "message": "当前没有失败或阻塞的执行记录"})
        return _dump({
            "defects": [
                {
                    "case_id": tc.id,
                    "title": tc.title,
                    "priority": tc.priority,
                    "result": bc.result,
                    "note": _clip(bc.note, 200),
                    "defect_ref": bc.defect_ref,
                    "task": task.name,
                    "batch": batch.name,
                    "executed_at": bc.executed_at,
                }
                for bc, batch, task, tc in rows
            ]
        })

    return [
        StructuredTool.from_function(
            coroutine=search_knowledge,
            name="search_knowledge",
            description=(
                "检索本项目知识库（业务规则、历史文档、缺陷经验等）。"
                "当用户询问业务规则、名词解释、历史背景等需要文档依据的问题时使用。"
                "参数 query 为检索关键词或问题原文。"
            ),
        ),
        StructuredTool.from_function(
            func=list_testcases,
            name="list_testcases",
            description=(
                "按条件查询本项目的测试用例列表（返回摘要，不含步骤详情）。"
                "可选参数：keyword（标题关键词）、priority（P0/P1/P2）、"
                "case_type（functional/boundary/exception）、module（所属模块名）、limit（最多 20）。"
                "当用户想了解有哪些用例、某类用例数量时使用。"
            ),
        ),
        StructuredTool.from_function(
            func=get_testcase_detail,
            name="get_testcase_detail",
            description=(
                "按用例 ID 查询单条用例的完整内容（前置条件、步骤、预期结果）。"
                "用户询问某条具体用例的细节时使用，case_id 可先通过 list_testcases 获得。"
            ),
        ),
        StructuredTool.from_function(
            func=get_coverage_summary,
            name="get_coverage_summary",
            description=(
                "统计本项目需求功能点的用例覆盖情况：已确认功能点数、已覆盖数、"
                "覆盖率与未覆盖功能点清单。用户询问覆盖率、哪些需求没有用例时使用。"
            ),
        ),
        StructuredTool.from_function(
            func=get_test_task_stats,
            name="get_test_task_stats",
            description=(
                "查询本项目测试任务的执行进度与通过率（任务与批次两级统计：总数/通过/失败/阻塞/未执行）。"
                "可选参数 task_name 按任务名模糊过滤。用户询问测试进度、通过率时使用。"
            ),
        ),
        StructuredTool.from_function(
            func=list_defects,
            name="list_defects",
            description=(
                "列出本项目测试执行中失败（可含阻塞）的用例记录，含备注与缺陷单号。"
                "可选参数 include_blocked 是否包含阻塞记录（默认包含）。用户询问缺陷、失败用例时使用。"
            ),
        ),
        StructuredTool.from_function(
            coroutine=parse_requirement_document,
            name="parse_requirement_document",
            description=(
                "用 AI 把需求文档解析为功能点清单（FeatureList）。参数 document_id 为需求文档 ID"
                "（用户上传文档后消息中会附带）。解析完成后必须把功能点清单展示给用户，"
                "等用户明确确认后才能继续确认与生成。"
            ),
        ),
        StructuredTool.from_function(
            func=confirm_features,
            name="confirm_features",
            description=(
                "确认需求文档的功能点，确认后才能生成用例。必须在用户明确表示确认后调用。"
                "参数：document_id；item_ids 可选，只确认指定功能点（不传则全部确认）。"
            ),
        ),
        StructuredTool.from_function(
            coroutine=start_generation,
            name="start_generation",
            description=(
                "启动测试用例生成任务（后台执行，需数分钟）。必须在功能点确认后、且用户明确同意生成时调用。"
                "参数：document_id；strategy 生成策略 full（完整用例）或 quick（快速冒烟），默认 full；"
                "specialist_skills 可选专项能力列表，名称必须来自当前 /skills Catalog；"
                "use_knowledge 是否启用知识库 RAG 增强。返回 task_id 供追踪进度。"
            ),
        ),
        StructuredTool.from_function(
            func=get_generation_status,
            name="get_generation_status",
            description=(
                "查询生成任务的状态与进度（阶段、百分比、草稿数、质检报告、评审统计）。"
                "用户追问生成进度或结果时使用，参数 task_id 为 start_generation 返回的任务 ID。"
            ),
        ),
        StructuredTool.from_function(
            func=review_generated_drafts,
            name="review_generated_drafts",
            description=(
                "批量采纳或驳回生成任务中的候选用例。必须在用户明确下达采纳/驳回指令后调用，禁止自行决定。"
                "参数：task_id；action 为 adopt 或 reject；draft_ids 可选指定用例 ID；"
                "priority 可选按优先级筛选（P0/P1/P2）；smoke_only 只操作冒烟用例；"
                "reject_reason 驳回原因。不传筛选条件则操作全部待评审用例。"
                "已采纳/已驳回的用例是终态，不会被重复操作。"
            ),
        ),
    ]
