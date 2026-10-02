"""Pure, versioned helpers for P1-2b dual-track evaluation scorecards."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from app.services.quality_checker import normalize_steps


RULESET_VERSION = "p1-2b-rules-v1"
CASE_RULE_DIMENSIONS = (
    "completeness",
    "step_executability",
    "expected_verifiability",
    "internal_consistency",
)
SUITE_RULE_DIMENSIONS = (
    "duplicate_rate",
    "checkpoint_coverage",
)
RULE_DIMENSIONS = CASE_RULE_DIMENSIONS + SUITE_RULE_DIMENSIONS
JUDGE_CORE_DIMENSIONS = ("business_relevance", "executability", "verifiability")
_VAGUE_EXPECTED_WORDS = ("正常", "符合预期", "合理", "体验良好", "系统正确")


def _dimension(score: int, evidence: list[str] | None = None) -> dict[str, Any]:
    bounded = max(0, min(100, int(score)))
    verdict = "pass" if bounded >= 80 else "warning" if bounded >= 50 else "fail"
    return {
        "score": bounded,
        "verdict": verdict,
        "evidence": [str(item)[:200] for item in (evidence or [])[:10]],
    }


def _case_text(case: dict[str, Any]) -> str:
    _, steps = normalize_steps(case)
    return " ".join(
        [
            str(case.get("title") or "").strip(),
            str(case.get("precondition") or "").strip(),
            " ".join(steps),
            str(case.get("expected_result") or "").strip(),
        ]
    )


def _trigrams(text: str) -> set[str]:
    normalized = "".join(text.split())
    if len(normalized) < 3:
        return {normalized} if normalized else set()
    return {normalized[index:index + 3] for index in range(len(normalized) - 2)}


def _similarity(left: str, right: str) -> float:
    left_set, right_set = _trigrams(left), _trigrams(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def _checkpoint_coverage(case_text: str, checkpoints: list[dict[str, Any]]) -> dict[str, Any]:
    if not checkpoints:
        return {**_dimension(100, []), "covered_checkpoints": [], "missing_checkpoints": []}
    covered = 0
    covered_items: list[str] = []
    missing: list[str] = []
    for checkpoint in checkpoints:
        text = str(checkpoint.get("text") or "").strip()
        keywords = [str(item).strip() for item in checkpoint.get("keywords", []) if str(item).strip()]
        terms = keywords or ([text] if text else [])
        if any(term and term in case_text for term in terms):
            covered += 1
            if text:
                covered_items.append(text)
        elif text:
            missing.append(text)
    score = round(covered / len(checkpoints) * 100) if checkpoints else 100
    evidence = [f"已覆盖检查点：{text}" for text in covered_items]
    evidence.extend(f"未覆盖检查点：{text}" for text in missing)
    return {
        **_dimension(score, evidence),
        "covered_checkpoints": covered_items,
        "missing_checkpoints": missing,
    }


def _suite_duplicate_rate(texts: list[str]) -> dict[str, Any]:
    duplicate_pairs: list[dict[str, int]] = []
    evidence: list[str] = []
    for index in range(len(texts)):
        for previous in range(index):
            if _similarity(texts[index], texts[previous]) >= 0.8:
                duplicate_pairs.append({"left": previous, "right": index})
                evidence.append(f"第 {previous + 1} 条与第 {index + 1} 条用例疑似重复")
    return {
        **_dimension(0 if duplicate_pairs else 100, evidence),
        "duplicate_pairs": duplicate_pairs,
    }


def _internal_consistency(title: str, precondition: str, steps: list[str], expected: str) -> dict[str, Any]:
    evidence: list[str] = []
    if not title or not steps or not expected:
        evidence.append("标题、步骤或预期结果不完整，无法形成一致验证链路")
        return _dimension(30, evidence)

    action_text = " ".join([title, precondition, *steps])
    failure_markers = ("失败", "错误", "无效", "锁定", "拒绝")
    success_markers = ("成功", "进入首页", "通过验证")
    action_expects_failure = any(marker in action_text for marker in failure_markers)
    expected_is_success = any(marker in expected for marker in success_markers)
    title_expects_success = any(marker in title for marker in success_markers)
    expected_is_failure = any(marker in expected for marker in failure_markers)
    if action_expects_failure and expected_is_success:
        evidence.append("用例动作描述失败/错误场景，但预期结果要求成功，验证链路存在矛盾")
    elif title_expects_success and expected_is_failure:
        evidence.append("用例标题要求成功，但预期结果描述失败，验证目标存在矛盾")
    return _dimension(30 if evidence else 100, evidence)


def score_cases(cases: list[dict[str, Any]], checkpoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return deterministic rule-track results in the same order as ``cases``."""
    normalized_cases = [case if isinstance(case, dict) else {} for case in cases]
    results: list[dict[str, Any]] = []

    for case in normalized_cases:
        title = str(case.get("title") or "").strip()
        precondition = str(case.get("precondition") or "").strip()
        expected = str(case.get("expected_result") or "").strip()
        _, steps = normalize_steps(case)

        completeness_evidence: list[str] = []
        if not title:
            completeness_evidence.append("缺少用例标题")
        if not precondition:
            completeness_evidence.append("缺少前置条件")
        completeness = _dimension((60 if title else 0) + (40 if precondition else 0), completeness_evidence)

        step_evidence: list[str] = []
        if not steps:
            step_evidence.append("缺少操作步骤")
            steps_dimension = _dimension(0, step_evidence)
        else:
            short_steps = [step for step in steps if len(step) < 4]
            if short_steps:
                step_evidence.extend(f"步骤过短：{step}" for step in short_steps)
            steps_dimension = _dimension(100 if not short_steps else 50, step_evidence)

        expected_evidence: list[str] = []
        if not expected:
            expected_evidence.append("缺少预期结果")
            expected_dimension = _dimension(0, expected_evidence)
        else:
            vague = next((word for word in _VAGUE_EXPECTED_WORDS if word in expected), "")
            if vague:
                expected_evidence.append(f"预期结果包含模糊表述：{vague}")
                expected_dimension = _dimension(30, expected_evidence)
            else:
                expected_dimension = _dimension(100, expected_evidence)

        consistency = _internal_consistency(title, precondition, steps, expected)

        dimensions = {
            "completeness": completeness,
            "step_executability": steps_dimension,
            "expected_verifiability": expected_dimension,
            "internal_consistency": consistency,
        }
        rule_score = round(sum(item["score"] for item in dimensions.values()) / len(dimensions))
        verdicts = {item["verdict"] for item in dimensions.values()}
        rule_verdict = "fail" if "fail" in verdicts else "warning" if "warning" in verdicts else "pass"
        results.append({"rule_score": rule_score, "verdict": rule_verdict, "dimensions": dimensions})
    return results


def score_rule_track(cases: list[dict[str, Any]], checkpoints: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_cases = [case if isinstance(case, dict) else {} for case in cases]
    case_results = score_cases(normalized_cases, checkpoints)
    texts = [_case_text(case) for case in normalized_cases]
    suite = {
        "duplicate_rate": _suite_duplicate_rate(texts),
        "checkpoint_coverage": _checkpoint_coverage(" ".join(texts), checkpoints),
    }
    dimensions = [
        dimension
        for item in case_results
        for dimension in item["dimensions"].values()
    ] + list(suite.values())
    score = round(sum(item["score"] for item in dimensions) / len(dimensions)) if dimensions else 0
    verdicts = {item["verdict"] for item in dimensions}
    verdict = "fail" if "fail" in verdicts else "warning" if "warning" in verdicts else "pass"
    return {
        "rule_score": score,
        "verdict": verdict,
        "cases": case_results,
        "suite": suite,
    }


def judge_verdict(dimensions: dict[str, Any]) -> str:
    scores = [int(dimensions.get(name, 3)) for name in JUDGE_CORE_DIMENSIONS]
    if any(score <= 2 for score in scores):
        return "fail"
    if all(score >= 4 for score in scores):
        return "pass"
    return "concern"


def assessment_status(rule_verdict: str, judge_status: str, judge_result: str) -> str:
    if judge_status != "completed":
        return "judge_unavailable" if judge_status == "unavailable" else "not_evaluated"
    if rule_verdict == "fail" and judge_result == "fail":
        return "dual_fail"
    if rule_verdict in {"warning", "fail"}:
        return "rule_issue"
    if judge_result != "pass":
        return "judge_concern"
    return "dual_pass"


def scorecard_input_fingerprint(
    requirement: str,
    checkpoints: list[dict[str, Any]],
    case: dict[str, Any],
    golden_case: dict[str, Any] | None = None,
    *,
    run_envelope: dict[str, Any] | None = None,
    ruleset_version: str = "",
    judge_prompt_version: str = "",
) -> str:
    payload = {
        "requirement": str(requirement or ""),
        "checkpoints": checkpoints or [],
        "case": case or {},
        "golden_case": golden_case or None,
        "run_envelope": run_envelope or {},
        "ruleset_version": str(ruleset_version or ""),
        "judge_prompt_version": str(judge_prompt_version or ""),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _read(item: Any, key: str, default: Any = "") -> Any:
    return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)


def summarize_scorecard_payloads(scorecards: list[Any]) -> dict[str, Any]:
    count = len(scorecards)
    rule_passes = sum(_read(card, "rule_verdict") == "pass" for card in scorecards)
    completed_judges = [card for card in scorecards if _read(card, "judge_status") == "completed"]
    judge_passes = sum(_read(card, "judge_verdict") == "pass" for card in completed_judges)
    statuses = Counter(str(_read(card, "assessment_status", "not_evaluated")) for card in scorecards)
    return {
        "rule_pass_rate": round(rule_passes / count * 100, 1) if count else None,
        "judge_pass_rate": round(judge_passes / len(completed_judges) * 100, 1) if completed_judges else None,
        "judge_unavailable_count": sum(_read(card, "judge_status") == "unavailable" for card in scorecards),
        "assessment_status_counts": dict(sorted(statuses.items())),
        "evaluated_case_count": count,
    }
