import json
from pathlib import Path

from pydantic import ValidationError

from app.ai.chains import judge_cases, judge_evaluation_cases
from app.ai.schemas import EvaluationCaseJudgement
from app.skills.base import SkillContext
from app.skills.shared.prompt_loader import load_prompt

SKILL_DIR = Path(__file__).resolve().parent
SKILL_NAME = "case_judge"

DIMENSIONS = ("relevance", "executability", "verifiability")
EVALUATION_DIMENSIONS = (
    "business_relevance",
    "executability",
    "verifiability",
    "scenario_completeness",
    "boundary_awareness",
    "coverage_reasonableness",
)
EVALUATION_PROMPT_VERSION = "p1-2b-judge-v1"


class EvaluationJudgeContractError(ValueError):
    """The evaluation Judge returned an incomplete or invalid batch."""


def _validation_error_summary(exc: ValidationError) -> str:
    issues = []
    for error in exc.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    )[:6]:
        path = ".".join(str(part) for part in (error.get("loc") or ())) or "$"
        message = str(error.get("msg") or "invalid value")
        issues.append(f"{path}: {message}")
    return "; ".join(issues)[:400]


def _clamp(value, lo=1, hi=5) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return 3


def _normalize_judgement(raw: dict) -> dict:
    scores = {dim: _clamp(raw.get(dim)) for dim in DIMENSIONS}
    overall = round(sum(scores.values()) / len(scores), 1)
    return {
        "index": raw.get("index"),
        **scores,
        "overall": overall,
        "hallucination": bool(raw.get("hallucination", False)),
        "hallucination_reason": (raw.get("hallucination_reason") or "").strip(),
        "comment": (raw.get("comment") or "").strip(),
    }


def _mock_judgements(cases: list) -> list[dict]:
    result = []
    for i in range(len(cases)):
        result.append(_normalize_judgement({
            "index": i,
            "relevance": 5 - (i % 2),
            "executability": 4,
            "verifiability": 4 + (i % 2),
            "hallucination": False,
        }))
    return result


def _normalize_evaluation_judgement(raw: dict) -> dict:
    validated = EvaluationCaseJudgement.model_validate(raw).model_dump()
    dimensions = {name: validated[name] for name in EVALUATION_DIMENSIONS}
    return {
        "index": validated["index"],
        "dimensions": dimensions,
        "reason": (validated.get("reason") or "").strip()[:500],
        "issue_tags": [str(tag).strip()[:80] for tag in (validated.get("issue_tags") or []) if str(tag).strip()][:10],
        "golden_alignment": (validated.get("golden_alignment") or "").strip()[:300],
    }


def _validate_evaluation_batch(raw_list: object, case_count: int) -> list[dict]:
    if not isinstance(raw_list, list) or len(raw_list) != case_count:
        actual = len(raw_list) if isinstance(raw_list, list) else 0
        raise EvaluationJudgeContractError(
            f"Judge batch incomplete: expected {case_count} results, received {actual}"
        )

    try:
        judgements = [_normalize_evaluation_judgement(raw) for raw in raw_list]
    except ValidationError as exc:
        detail = _validation_error_summary(exc)
        raise EvaluationJudgeContractError(
            f"Judge result violates the six-dimension contract: {detail}"
        ) from exc
    except TypeError as exc:
        raise EvaluationJudgeContractError(
            "Judge result violates the six-dimension contract: result must be an object"
        ) from exc

    indexes = [item["index"] for item in judgements]
    expected = list(range(case_count))
    if sorted(indexes) != expected or len(set(indexes)) != len(indexes):
        raise EvaluationJudgeContractError(
            f"Judge indexes must match {expected}; received {indexes}"
        )
    return sorted(judgements, key=lambda item: item["index"])


def _mock_evaluation_judgements(cases: list) -> list[dict]:
    return [
        _normalize_evaluation_judgement({
            "index": index,
            "business_relevance": 5 - (index % 2),
            "executability": 4,
            "verifiability": 4,
            "scenario_completeness": 4,
            "boundary_awareness": 3,
            "coverage_reasonableness": 4,
            "reason": "Mock 评测结果",
        })
        for index in range(len(cases))
    ]


def _cases_to_prompt(feature_item: dict, cases: list[dict]) -> str:
    lines = [
        "功能点：",
        json.dumps(feature_item, ensure_ascii=False, indent=2),
        "",
        "待评分用例：",
    ]
    for idx, case in enumerate(cases):
        steps = case.get("steps")
        if isinstance(steps, str):
            try:
                steps = json.loads(steps)
            except json.JSONDecodeError:
                steps = [steps]
        lines.append(json.dumps({
            "index": idx,
            "title": case.get("title", ""),
            "precondition": case.get("precondition", ""),
            "steps": steps or [],
            "expected_result": case.get("expected_result", ""),
        }, ensure_ascii=False))
    return "\n".join(lines)


def _evaluation_cases_to_prompt(inputs: dict, cases: list[dict]) -> str:
    payload = {
        "requirement": inputs.get("requirement", ""),
        "checkpoints": inputs.get("checkpoints") or [],
        "golden_case": inputs.get("golden_case"),
        "contract_retry_feedback": inputs.get("contract_retry_feedback", ""),
        "cases": [
            {
                "index": index,
                "title": case.get("title", ""),
                "precondition": case.get("precondition", ""),
                "steps": case.get("steps", []),
                "expected_result": case.get("expected_result", ""),
            }
            for index, case in enumerate(cases)
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def run(inputs: dict, context: SkillContext) -> dict:
    cases = inputs.get("cases") or []
    if not cases:
        return {"judgements": [], "prompt_version": EVALUATION_PROMPT_VERSION} if inputs.get("evaluation_mode") else {"judgements": []}

    if inputs.get("evaluation_mode"):
        if context.use_mock:
            return {"judgements": _mock_evaluation_judgements(cases), "prompt_version": EVALUATION_PROMPT_VERSION}
        prompt = load_prompt(SKILL_DIR, "evaluation_prompt.md")
        raw_list = await judge_evaluation_cases(prompt, _evaluation_cases_to_prompt(inputs, cases), context.model_config)
        judgements = _validate_evaluation_batch(raw_list, len(cases))
        return {"judgements": judgements, "prompt_version": EVALUATION_PROMPT_VERSION}

    feature_item = inputs["feature_item"]
    if context.use_mock:
        return {"judgements": _mock_judgements(cases)}

    prompt = load_prompt(SKILL_DIR, "prompt.md")
    user_prompt = _cases_to_prompt(feature_item, cases)
    # Judge 用评测专用模型，与生成模型分离，避免"自评偏置"
    raw_list = await judge_cases(
        prompt,
        user_prompt,
        context.model_config,
    )
    if not isinstance(raw_list, list):
        raw_list = []

    # 按 index 对齐，缺失的条目不返回评分（保持未评状态）
    judgements = []
    seen = set()
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        item = _normalize_judgement(raw)
        idx = item["index"]
        if isinstance(idx, int) and 0 <= idx < len(cases) and idx not in seen:
            seen.add(idx)
            judgements.append(item)
    return {"judgements": judgements}
