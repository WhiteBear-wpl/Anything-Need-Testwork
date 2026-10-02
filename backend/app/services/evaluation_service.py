"""离线评测：对评测样本走完整生成链路，产出五指标。

指标口径：
- success: 任务完成且产出用例
- usable_rate: Judge 综合分 >= 4 的用例占比（离线近似，线上以人工采纳率为准）
- recall: 标准测试点被生成用例覆盖的比例（LLM 批量判定，mock 模式用关键词匹配）
- duplicate_rate / hallucination_count: 来自质检报告
- tokens / duration: 成本
"""

import asyncio
import json
import time
from contextlib import nullcontext
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy.orm import Session, joinedload

from app.ai.chains import judge_checkpoint_coverage
from app.agent_runtime.contracts import BudgetExhausted, RunStatus, RuntimeCancelled
from app.agent_runtime import harness as runtime_harness_module
from app.agent_runtime.repository import AgentRunRepository
from app.database import SessionLocal
from app.models.agent_run import AgentRun
from app.models.evaluation import EvaluationScorecard, EvalResult, EvalRun, EvalSample, EvalRunSample
from app.models.generation import GeneratedCaseDraft, GenerationTask
from app.models.requirement import RequirementDocument
from app.services.generation_service import (
    confirm_requirements,
    structure_requirements,
)
from app.services.settings_service import RuntimeModelConfig, get_project_runtime_config
from app.services.llm import LLMCallError
from app.services.redaction import redact_output
from app.services.evaluation_scorecard_service import (
    RULESET_VERSION,
    assessment_status,
    judge_verdict,
    score_rule_track,
    scorecard_input_fingerprint,
    summarize_scorecard_payloads,
)
from app.services.evaluation_experiment_service import runtime_config_from_snapshot
from app.skills.base import SkillContext
from app.skills.case_judge.handler import (
    EVALUATION_DIMENSIONS,
    EVALUATION_PROMPT_VERSION,
    EvaluationJudgeContractError,
)
from app.skills.errors import SkillOutputError, SkillTimeoutError
from app.skills.registry import get_registry
from app.workflows.generation.runner import run_generation_workflow

USABLE_SCORE_THRESHOLD = 4.0

COVERAGE_PROMPT = """你是测试评审专家。给你一组标准测试点和一组 AI 生成的测试用例，判断每个测试点是否被至少一条用例覆盖。
覆盖的标准：有用例的标题/步骤/预期结果针对该测试点描述的场景做了验证。
只输出 JSON：{"covered_indexes": [0, 2, 5]}（被覆盖的测试点编号列表），不要解释。"""


def _parse_checkpoints(sample: EvalSample) -> list[dict]:
    try:
        data = json.loads(sample.checkpoints or "[]")
    except json.JSONDecodeError:
        return []
    result = []
    for cp in data if isinstance(data, list) else []:
        if isinstance(cp, str):
            result.append({"text": cp, "keywords": []})
        elif isinstance(cp, dict) and (cp.get("text") or "").strip():
            keywords = [str(k).strip() for k in (cp.get("keywords") or []) if str(k).strip()]
            result.append({"text": str(cp["text"]).strip(), "keywords": keywords})
    return result


def _keyword_coverage(checkpoints: list[dict], corpus: str) -> set[int]:
    covered = set()
    for idx, cp in enumerate(checkpoints):
        keywords = cp["keywords"] or [cp["text"]]
        if any(k and k in corpus for k in keywords):
            covered.add(idx)
    return covered


def _draft_to_scorecard_case(draft: GeneratedCaseDraft) -> dict:
    return {
        "title": draft.title,
        "precondition": draft.precondition,
        "steps": draft.steps,
        "expected_result": draft.expected_result,
    }


def _scorecard_checkpoints(run_sample: EvalRunSample) -> list[dict]:
    try:
        values = json.loads(run_sample.checkpoints_snapshot or "[]")
    except json.JSONDecodeError:
        return []
    return [value for value in values if isinstance(value, dict)] if isinstance(values, list) else []


def _validate_judge_batch(payload: object, expected_count: int) -> list[dict]:
    if not isinstance(payload, dict):
        raise EvaluationJudgeContractError("Judge did not return an object")
    if payload.get("prompt_version") != EVALUATION_PROMPT_VERSION:
        raise EvaluationJudgeContractError("Judge prompt version does not match the frozen version")
    items = payload.get("judgements")
    if not isinstance(items, list) or len(items) != expected_count:
        actual = len(items) if isinstance(items, list) else 0
        raise EvaluationJudgeContractError(
            f"Judge batch incomplete: expected {expected_count} results, received {actual}"
        )

    indexes: list[int] = []
    for item in items:
        if not isinstance(item, dict) or type(item.get("index")) is not int:
            raise EvaluationJudgeContractError("Judge result has an invalid index")
        dimensions = item.get("dimensions")
        if not isinstance(dimensions, dict) or set(dimensions) != set(EVALUATION_DIMENSIONS):
            raise EvaluationJudgeContractError("Judge result must contain exactly six dimensions")
        if any(type(dimensions[name]) is not int or not 1 <= dimensions[name] <= 5 for name in EVALUATION_DIMENSIONS):
            raise EvaluationJudgeContractError("Judge dimension scores must be integers from 1 to 5")
        indexes.append(item["index"])

    expected = list(range(expected_count))
    if sorted(indexes) != expected or len(set(indexes)) != len(indexes):
        raise EvaluationJudgeContractError(
            f"Judge indexes must match {expected}; received {indexes}"
        )
    return sorted(items, key=lambda item: item["index"])


def _judge_error_is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (EvaluationJudgeContractError, SkillOutputError, SkillTimeoutError, TimeoutError)):
        return True
    if exc.__class__.__module__.startswith(("pydantic", "json")) or "OutputParser" in exc.__class__.__name__:
        return True
    if isinstance(exc, LLMCallError):
        message = str(exc).lower()
        deterministic = ("api key", "未配置", "无效", "认证", "404", "模型名", "接口地址")
        if any(marker in message for marker in deterministic):
            return False
        transient = ("429", "限流", "连接", "网络", "超时", "timeout", "temporar")
        return any(marker in message for marker in transient)
    return False


def _judge_retry_feedback(exc: Exception) -> str:
    if isinstance(exc, EvaluationJudgeContractError):
        return redact_output(str(exc), limit=300)
    return ""


async def evaluate_result_scorecard(
    db: Session,
    result: EvalResult,
    run_sample: EvalRunSample,
    drafts: list[GeneratedCaseDraft],
    model_config: RuntimeModelConfig,
    *,
    run_context=None,
    registry=None,
) -> EvaluationScorecard:
    """Persist rules first, then add the independent Judge track if available."""
    checkpoints = _scorecard_checkpoints(run_sample)
    cases = [_draft_to_scorecard_case(draft) for draft in drafts]
    try:
        run_envelope = json.loads((result.run.config_snapshot if result.run else "") or "{}")
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("scorecard fingerprint mismatch: invalid run snapshot") from exc
    fingerprint = scorecard_input_fingerprint(
        run_sample.content_snapshot,
        checkpoints,
        {"cases": cases},
        run_envelope=run_envelope,
        ruleset_version=RULESET_VERSION,
        judge_prompt_version=EVALUATION_PROMPT_VERSION,
    )
    card = (
        db.query(EvaluationScorecard)
        .filter(EvaluationScorecard.result_id == result.id)
        .one_or_none()
    )
    if card is not None and card.input_fingerprint:
        if card.input_fingerprint != fingerprint:
            raise ValueError("scorecard fingerprint mismatch: create a new evaluation run")
        if card.judge_status == "completed":
            return card

    created_rule_track = card is None
    if card is None:
        rule_track = score_rule_track(cases, checkpoints)
        card = EvaluationScorecard(result_id=result.id)
        result.scorecard = card
        db.add(card)
        card.ruleset_version = RULESET_VERSION
        card.judge_prompt_version = EVALUATION_PROMPT_VERSION
        card.input_fingerprint = fingerprint
        card.rule_score = rule_track["rule_score"]
        card.rule_verdict = rule_track["verdict"]
        card.rule_dimensions = json.dumps(
            {
                "schema_version": "2",
                "cases": {
                    str(getattr(draft, "id", index)): scored
                    for index, (draft, scored) in enumerate(zip(drafts, rule_track["cases"]))
                },
                "suite": rule_track["suite"],
            },
            ensure_ascii=False,
        )
        card.judge_status = "not_evaluated"
        card.judge_verdict = ""
        card.judge_dimensions = "{}"
        card.judge_reason = ""
        card.golden_alignment = "{}"
        card.assessment_status = "not_evaluated"
        db.commit()
        db.refresh(card)

    harness = runtime_harness_module.get_active_runtime_harness()
    if harness is None and run_context is not None:
        harness = runtime_harness_module.RuntimeHarness(db, run_context)
    if harness is not None:
        harness.check_cancelled()
        if created_rule_track:
            harness.record_evaluation_event(
                "evaluation_rule_completed", "rule", result_id=result.id
            )

    judge_inputs = {
        "evaluation_mode": True,
        "requirement": run_sample.content_snapshot,
        "checkpoints": checkpoints,
        "cases": cases,
    }
    validated_judgements = None
    judge_error = ""
    active_registry = registry or get_registry()
    for attempt in range(2):
        if harness is not None and attempt > 0:
            harness.consume_quality_repair()
        try:
            if harness is not None:
                harness.check_cancelled()
                if attempt == 0:
                    harness.record_evaluation_event(
                        "evaluation_judge_started", "judge", result_id=result.id
                    )
            judge_result = await active_registry.run(
                "case_judge",
                judge_inputs,
                SkillContext(
                    model_config=model_config,
                    project_id=result.run.project_id if result.run else None,
                    task_id=result.task_id,
                    strategy="full",
                    use_mock=model_config.use_mock_llm,
                    runtime=harness,
                ),
            )
            # Cancellation can arrive while the provider call is in flight.
            # Re-check before accepting or persisting an otherwise valid batch.
            if harness is not None:
                harness.check_cancelled()
            validated_judgements = _validate_judge_batch(judge_result, len(drafts))
            break
        except (BudgetExhausted, RuntimeCancelled):
            card.judge_status = "not_evaluated"
            card.assessment_status = "not_evaluated"
            db.commit()
            raise
        except Exception as exc:
            judge_error = redact_output(str(exc), limit=500)
            retryable = _judge_error_is_retryable(exc)
            if retryable and attempt == 0:
                feedback = _judge_retry_feedback(exc)
                if feedback:
                    judge_inputs["contract_retry_feedback"] = feedback
            if harness is not None and retryable and attempt == 0:
                harness.record_evaluation_event(
                    "evaluation_judge_retry",
                    "judge",
                    result_id=result.id,
                    attempt=attempt + 1,
                    error_type=type(exc).__name__,
                    message=judge_error,
                )
            if not retryable:
                break

    if validated_judgements is None:
        card.judge_status = "unavailable"
        card.judge_verdict = ""
        card.judge_reason = judge_error or "Judge 未返回有效结果"
        card.assessment_status = assessment_status(card.rule_verdict, card.judge_status, card.judge_verdict)
        db.commit()
        if harness is not None:
            harness.record_evaluation_event(
                "evaluation_judge_unavailable",
                "judge",
                result_id=result.id,
                error_type="JudgeUnavailable",
                message=card.judge_reason,
            )
        return card

    judgements = {item["index"]: item for item in validated_judgements}

    case_judgements = {}
    reasons: list[str] = []
    golden = {}
    verdicts: list[str] = []
    for index, draft in enumerate(drafts):
        judgement = judgements.get(index)
        if not judgement:
            continue
        dimensions = judgement.get("dimensions") or {}
        verdict = judge_verdict(dimensions)
        verdicts.append(verdict)
        case_judgements[str(getattr(draft, "id", index))] = {
            "dimensions": dimensions,
            "verdict": verdict,
            "reason": str(judgement.get("reason") or "")[:500],
            "issue_tags": list(judgement.get("issue_tags") or [])[:10],
        }
        if judgement.get("reason"):
            reasons.append(str(judgement["reason"])[:500])
        if judgement.get("golden_alignment"):
            golden[str(getattr(draft, "id", index))] = str(judgement["golden_alignment"])[:300]

    card.judge_status = "completed"
    card.judge_verdict = "fail" if "fail" in verdicts else "concern" if "concern" in verdicts else "pass"
    card.judge_dimensions = json.dumps({"cases": case_judgements}, ensure_ascii=False)
    card.judge_reason = "\n".join(reasons)[:1000]
    card.golden_alignment = json.dumps(golden, ensure_ascii=False)
    card.assessment_status = assessment_status(card.rule_verdict, card.judge_status, card.judge_verdict)
    db.commit()
    if harness is not None:
        harness.record_evaluation_event(
            "evaluation_judge_completed", "judge", result_id=result.id
        )
    return card


async def _compute_recall(
    checkpoints: list[dict],
    drafts: list,
    model_config: RuntimeModelConfig,
) -> tuple[float | None, list[str]]:
    """返回 (召回率, 未覆盖的测试点文本列表)。"""
    if not checkpoints:
        return None, []
    corpus = "\n".join(f"{d.title} {d.steps} {d.expected_result}" for d in drafts)

    if model_config.use_mock_llm:
        covered = _keyword_coverage(checkpoints, corpus)
    else:
        cp_lines = [f"{i}. {cp['text']}" for i, cp in enumerate(checkpoints)]
        case_lines = [
            json.dumps(
                {"title": d.title, "steps": d.steps, "expected_result": d.expected_result},
                ensure_ascii=False,
            )
            for d in drafts
        ]
        user_prompt = "标准测试点：\n" + "\n".join(cp_lines) + "\n\n生成用例：\n" + "\n".join(case_lines)
        try:
            indexes = await judge_checkpoint_coverage(
                COVERAGE_PROMPT,
                user_prompt,
                model_config,
            )
            covered = {i for i in indexes if isinstance(i, int) and 0 <= i < len(checkpoints)}
        except (BudgetExhausted, RuntimeCancelled):
            raise
        except Exception:
            covered = _keyword_coverage(checkpoints, corpus)

    uncovered = [cp["text"] for i, cp in enumerate(checkpoints) if i not in covered]
    return round(len(covered) / len(checkpoints) * 100, 1), uncovered


async def _watch_task_progress(
    run_id: int, task_id: int, base_pct: float, slice_pct: float, stop: asyncio.Event
) -> None:
    """生成期间每 2 秒把生成任务的进度映射到评测运行的进度条上。

    用独立 Session 读写，避免与主流程的 Session 交叉；事件循环单线程，
    同步 DB 操作不会与主流程真正并发。
    """
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=2.0)
            break
        except asyncio.TimeoutError:
            pass
        wdb = SessionLocal()
        try:
            task = wdb.query(GenerationTask).get(task_id)
            run = wdb.query(EvalRun).get(run_id)
            if task and run and run.status == "running":
                run.progress = min(99, int(base_pct + slice_pct * task.progress / 100))
                if task.stage:
                    run.stage = task.stage
                wdb.commit()
        except Exception:
            pass
        finally:
            wdb.close()


async def _eval_one_sample(
    db: Session, run: EvalRun, sample: EvalSample, experiment_snapshot: dict,
    model_config: RuntimeModelConfig,
    base_pct: float = 0.0, slice_pct: float = 100.0,
    run_context=None,
) -> dict:
    started = time.monotonic()

    run.stage = "结构化需求"
    db.commit()

    doc = RequirementDocument(
        project_id=run.project_id,
        title=f"[评测] {sample.title}",
        source_type="eval",
        raw_content=sample.content,
        is_eval=True,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    await structure_requirements(db, doc, model_config=model_config)
    confirm_requirements(db, doc.id)

    task = GenerationTask(
        project_id=run.project_id,
        document_id=doc.id,
        strategy=str(experiment_snapshot["strategy"]),
        strategy_config=json.dumps(experiment_snapshot, ensure_ascii=False, sort_keys=True),
        status="pending",
        is_eval=True,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    stop = asyncio.Event()
    watcher = asyncio.create_task(_watch_task_progress(run.id, task.id, base_pct, slice_pct, stop))
    try:
        await run_generation_workflow(task.id, run_context=run_context)
    except (BudgetExhausted, RuntimeCancelled):
        raise
    except Exception:
        pass  # 失败信息已写入 task.error_message，计入成功率分母
    finally:
        stop.set()
        await watcher
    db.refresh(task)

    drafts = list(task.drafts or [])
    report = task.quality_report
    total = len(drafts)
    success = task.status == "completed" and total > 0

    usable = sum(1 for d in drafts if (d.judge_score or 0) >= USABLE_SCORE_THRESHOLD)
    checkpoints = _parse_checkpoints(sample)
    run.stage = "召回率判定"
    db.commit()
    if success:
        recall, uncovered_checkpoints = await _compute_recall(checkpoints, drafts, model_config)
    elif checkpoints:
        recall, uncovered_checkpoints = 0.0, [cp["text"] for cp in checkpoints]
    else:
        recall, uncovered_checkpoints = None, []

    return {
        "task_id": task.id,
        "success": success,
        "error": task.error_message or "",
        "total_cases": total,
        "usable_cases": usable,
        "usable_rate": round(usable / total * 100, 1) if total else 0.0,
        "recall": recall,
        "checkpoint_count": len(checkpoints),
        "uncovered_checkpoints": uncovered_checkpoints,
        "avg_judge_score": report.avg_judge_score if report else None,
        "hallucination_count": report.hallucination_count if report else 0,
        "duplicate_count": report.duplicate_count if report else 0,
        "duplicate_rate": round((report.duplicate_count if report else 0) / total * 100, 1) if total else 0.0,
        "tokens": task.tokens_used or 0,
        "duration_sec": round(time.monotonic() - started, 1),
    }


def _aggregate(sample_metrics: list[dict]) -> dict:
    total_samples = len(sample_metrics)
    success_count = sum(1 for m in sample_metrics if m["success"])
    total_cases = sum(m["total_cases"] for m in sample_metrics)
    usable_cases = sum(m["usable_cases"] for m in sample_metrics)
    duplicate_count = sum(m["duplicate_count"] for m in sample_metrics)
    recalls = [m["recall"] for m in sample_metrics if m["recall"] is not None]
    judge_scores = [m["avg_judge_score"] for m in sample_metrics if m["avg_judge_score"] is not None]

    def rate(part, whole):
        return round(part / whole * 100, 1) if whole else 0.0

    return {
        "sample_count": total_samples,
        "success_rate": rate(success_count, total_samples),
        "total_cases": total_cases,
        "usable_rate": rate(usable_cases, total_cases),
        "recall": round(sum(recalls) / len(recalls), 1) if recalls else None,
        "duplicate_rate": rate(duplicate_count, total_cases),
        "hallucination_count": sum(m["hallucination_count"] for m in sample_metrics),
        "avg_judge_score": round(sum(judge_scores) / len(judge_scores), 2) if judge_scores else None,
        "total_tokens": sum(m["tokens"] for m in sample_metrics),
        "total_duration_sec": round(sum(m["duration_sec"] for m in sample_metrics), 1),
    }


async def run_evaluation(db: Session, run_id: int, *, run_context=None) -> None:
    run = (
        db.query(EvalRun)
        .options(joinedload(EvalRun.results))
        .filter(EvalRun.id == run_id)
        .first()
    )
    if not run:
        return
    # The worker may reclaim an AgentRun after the EvalRun transaction already
    # committed but before the outer AgentRun was marked terminal.  A completed
    # evaluation is immutable, so never regenerate cases or invoke Judge again.
    if run.status == "completed":
        return
    try:
        config = json.loads(run.config_snapshot or "{}")
        model_config = runtime_config_from_snapshot(
            config,
            get_project_runtime_config(db, run.project_id),
        )
    except Exception as exc:
        run.status = "failed"
        run.stage = ""
        run.error_message = redact_output(str(exc), limit=2000)
        db.commit()
        raise
    if run_context is not None:
        runtime_harness = runtime_harness_module.RuntimeHarness(db, run_context)
    else:
        runtime_harness = None

    run.status = "running"
    run.progress = 0
    db.commit()

    try:
        results = (
            db.query(EvalResult)
            .filter(EvalResult.run_id == run.id)
            .all()
        )
        sample_metrics = []
        total = len(results)
        for idx, result in enumerate(results):
            result.status = "running"
            run.progress = int(idx / total * 100)
            db.commit()

            frozen = db.get(EvalRunSample, result.run_sample_id) if result.run_sample_id else None
            if frozen is None:
                raise ValueError(
                    f"incomplete immutable sample snapshot for evaluation result {result.id}"
                )
            source = frozen
            sample = SimpleNamespace(
                title=source.title_snapshot,
                content=source.content_snapshot,
                checkpoints=source.checkpoints_snapshot,
            )
            try:
                scope = runtime_harness_module.active_runtime_harness(runtime_harness) if runtime_harness is not None else nullcontext()
                with scope:
                    if runtime_harness is not None:
                        runtime_harness.check_cancelled()
                    metrics = await _eval_one_sample(
                        db, run, sample, config, model_config,
                        base_pct=idx / total * 100, slice_pct=100 / total,
                        run_context=run_context,
                    )
                    result.task_id = metrics["task_id"]
                    result.status = "completed" if metrics["success"] else "failed"
                    result.metrics = json.dumps(metrics, ensure_ascii=False)
                    if metrics["success"] and frozen is not None:
                        task = db.get(GenerationTask, metrics["task_id"])
                        await evaluate_result_scorecard(
                            db,
                            result,
                            frozen,
                            list(task.drafts or []) if task else [],
                            model_config,
                            run_context=run_context,
                        )
                sample_metrics.append(metrics)
            except BudgetExhausted as exc:
                result.status = "not_evaluated"
                result.error_summary = redact_output(str(exc), limit=500)
                db.commit()
                raise
            except RuntimeCancelled:
                result.status = "cancelled"
                db.commit()
                raise
            except Exception as exc:
                result.status = "failed"
                result.error_summary = redact_output(str(exc), limit=500)
                sample_metrics.append({"success": False, "total_cases": 0, "usable_cases": 0, "duplicate_count": 0, "recall": None, "avg_judge_score": None, "hallucination_count": 0, "tokens": 0, "duration_sec": 0})
            run.progress = int((idx + 1) / total * 100)
            db.commit()

        aggregate = _aggregate(sample_metrics)
        aggregate["dual_track"] = summarize_scorecard_payloads(
            db.query(EvaluationScorecard)
            .join(EvalResult, EvaluationScorecard.result_id == EvalResult.id)
            .filter(EvalResult.run_id == run.id)
            .all()
        )
        run.metrics = json.dumps(aggregate, ensure_ascii=False)
        run.status = "completed"
        run.progress = 100
        run.stage = ""
        db.commit()
    except BudgetExhausted:
        run.status = RunStatus.BUDGET_EXHAUSTED.value
        run.stage = ""
        for result in run.results:
            if result.status == "running":
                result.status = "not_evaluated"
        db.commit()
        raise
    except RuntimeCancelled:
        run.status = "cancelled"
        run.stage = ""
        for result in run.results:
            if result.status == "running":
                result.status = "cancelled"
        db.commit()
        raise
    except Exception as e:
        run.status = "failed"
        run.error_message = redact_output(str(e), limit=2000)
        run.stage = ""
        for result in run.results:
            if result.status == "running":
                result.status = "failed"
        db.commit()
        raise


async def run_evaluation_workflow(run_id: int, *, run_context=None) -> None:
    """Worker entry point; later calls consume only the EvalRun snapshots."""
    db = SessionLocal()
    try:
        try:
            await run_evaluation(db, run_id, run_context=run_context)
        except BudgetExhausted as exc:
            eval_run = db.get(EvalRun, run_id)
            if eval_run:
                eval_run.status = RunStatus.BUDGET_EXHAUSTED.value
                eval_run.stage = ""
                db.commit()
            if run_context is not None:
                AgentRunRepository(db).mark_terminal(
                    run_context.run_id,
                    RunStatus.BUDGET_EXHAUSTED,
                    payload_summary=json.dumps(
                        {
                            "dimension": exc.dimension,
                            "used": exc.used,
                            "limit": exc.limit,
                        },
                        ensure_ascii=False,
                    ),
                    now=datetime.now(),
                )
            return
        except RuntimeCancelled:
            eval_run = db.get(EvalRun, run_id)
            if eval_run:
                eval_run.status = "cancelled"
                eval_run.stage = ""
                db.commit()
            if run_context is not None:
                agent_run = db.get(AgentRun, run_context.run_id)
                if agent_run:
                    terminal_at = datetime.now()
                    AgentRunRepository(db).mark_terminal(
                        agent_run.id,
                        RunStatus.CANCELLED,
                        now=terminal_at,
                    )
            return
        except Exception as exc:
            if run_context is not None:
                agent_run = db.get(AgentRun, run_context.run_id)
                if agent_run:
                    terminal_at = datetime.now()
                    AgentRunRepository(db).mark_terminal(
                        agent_run.id,
                        RunStatus.FAILED,
                        payload_summary=json.dumps(
                            {"message": redact_output(str(exc), limit=500)},
                            ensure_ascii=False,
                        ),
                        now=terminal_at,
                    )
            raise
        if run_context is not None:
            run = db.get(AgentRun, run_context.run_id)
            if run:
                terminal_at = datetime.now()
                AgentRunRepository(db).mark_terminal(
                    run.id,
                    RunStatus.COMPLETED,
                    now=terminal_at,
                )
    finally:
        db.close()
