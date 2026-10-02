import json


def normalize_steps(case: dict) -> tuple[str, list[str]]:
    steps = case.get("steps", [])
    if isinstance(steps, str):
        text = steps.strip()
        if not text:
            return "[]", []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                steps = parsed
            else:
                steps = [str(parsed)]
        except json.JSONDecodeError:
            steps = [s.strip() for s in text.split("\n") if s.strip()]
    elif not isinstance(steps, list):
        steps = []

    cleaned = [str(s).strip() for s in steps if str(s).strip()]
    return json.dumps(cleaned, ensure_ascii=False), cleaned


def is_meaningful_case(case: dict, steps: list[str]) -> bool:
    title = (case.get("title") or "").strip()
    expected = (case.get("expected_result") or "").strip()
    if not title:
        return False
    return bool(steps or expected)


def check_case(case: dict) -> tuple[str, list[str]]:
    """规则质检：返回 (status, issues)"""
    issues = []

    title = (case.get("title") or "").strip()
    if not title:
        issues.append("缺少标题")
    if not (case.get("expected_result") or "").strip():
        issues.append("缺少预期结果")

    steps = case.get("steps", [])
    if isinstance(steps, str):
        try:
            steps = json.loads(steps)
        except json.JSONDecodeError:
            steps = [s.strip() for s in steps.split("\n") if s.strip()]

    if not steps:
        issues.append("缺少操作步骤")

    for step in steps:
        if len(step) < 4:
            issues.append(f"步骤过短不可执行: {step}")
        vague_words = ["正常", "合理", "体验良好", "系统正确"]
        for word in vague_words:
            if word in case.get("expected_result", ""):
                issues.append(f"预期结果不可验证，包含模糊词: {word}")
                break

    if len(issues) == 0:
        return "pass", []
    if len(issues) <= 1:
        return "warning", issues
    return "fail", issues


def _trigrams(text: str) -> set[str]:
    text = "".join(text.split())
    if len(text) < 3:
        return {text} if text else set()
    return {text[i:i + 3] for i in range(len(text) - 2)}


def _similarity(a: str, b: str) -> float:
    ta, tb = _trigrams(a), _trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


DUPLICATE_THRESHOLD = 0.8


def detect_duplicates(drafts: list) -> int:
    """同功能点内两两比对（标题 + 步骤），标记疑似重复，返回重复条数。

    只标记后出现的那条，保留先出现的用例不受影响。
    """
    by_item: dict = {}
    for d in drafts:
        by_item.setdefault(d.requirement_item_id, []).append(d)

    duplicate_count = 0
    for group in by_item.values():
        for i in range(1, len(group)):
            current = group[i]
            text_i = f"{current.title} {current.steps}"
            for j in range(i):
                other = group[j]
                if _similarity(text_i, f"{other.title} {other.steps}") >= DUPLICATE_THRESHOLD:
                    duplicate_count += 1
                    try:
                        issues = json.loads(current.quality_issues or "[]")
                    except json.JSONDecodeError:
                        issues = []
                    issues.append(f"与用例《{other.title}》疑似重复")
                    current.quality_issues = json.dumps(issues, ensure_ascii=False)
                    if current.quality_status == "pass":
                        current.quality_status = "warning"
                    break
    return duplicate_count


def judge_summary(drafts: list) -> tuple[float | None, int]:
    """从草稿的 judge 字段汇总：平均综合分、幻觉数。"""
    scores = [d.judge_score for d in drafts if d.judge_score is not None]
    avg = round(sum(scores) / len(scores), 2) if scores else None
    hallucination = 0
    for d in drafts:
        try:
            data = json.loads(d.judge_issues or "{}")
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("hallucination"):
            hallucination += 1
    return avg, hallucination


def build_quality_report(
    drafts: list,
    requirement_items: list,
    item_case_map: dict[int, list],
    duplicate_count: int = 0,
) -> dict:
    total = len(drafts)
    pass_count = sum(1 for d in drafts if d.quality_status == "pass")
    warning_count = sum(1 for d in drafts if d.quality_status == "warning")
    fail_count = sum(1 for d in drafts if d.quality_status == "fail")

    confirmed_items = [i for i in requirement_items if i.confirmed]
    covered_ids = {item_id for item_id, cases in item_case_map.items() if cases}
    uncovered = [i.feature for i in confirmed_items if i.id not in covered_ids]
    coverage = (len(covered_ids) / len(confirmed_items) * 100) if confirmed_items else 0

    avg_judge_score, hallucination_count = judge_summary(drafts)

    suggestions = []
    if uncovered:
        suggestions.append(f"以下功能点尚未覆盖用例: {', '.join(uncovered)}")
    if fail_count > 0:
        suggestions.append(f"有 {fail_count} 条用例质量不合格，建议重新生成或人工编辑")
    if coverage < 80:
        suggestions.append("覆盖率偏低，建议补充异常和边界场景")
    if hallucination_count > 0:
        suggestions.append(f"AI 评分标记了 {hallucination_count} 条疑似幻觉用例（编造了需求中没有的规则），请评审时重点核对")
    if duplicate_count > 0:
        suggestions.append(f"检测到 {duplicate_count} 条疑似重复用例，建议去重后采纳")

    return {
        "total_cases": total,
        "pass_count": pass_count,
        "warning_count": warning_count,
        "fail_count": fail_count,
        "coverage_rate": round(coverage, 1),
        "uncovered_features": json.dumps(uncovered, ensure_ascii=False),
        "suggestions": "\n".join(suggestions) if suggestions else "质量良好，可进行人工评审",
        "avg_judge_score": avg_judge_score,
        "hallucination_count": hallucination_count,
        "duplicate_count": duplicate_count,
    }
