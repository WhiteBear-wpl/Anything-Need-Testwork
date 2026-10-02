import json


def format_scope_hint(scope: dict | None) -> str:
    """把测试范围与风险格式化为可拼入 Prompt 的文本。"""
    if not isinstance(scope, dict):
        return ""
    out_scope = [str(s).strip() for s in (scope.get("out_scope") or []) if str(s).strip()]
    risks = [str(s).strip() for s in (scope.get("risks") or []) if str(s).strip()]
    if not out_scope and not risks:
        return ""

    lines = ["", "本次测试范围约束（来自需求评审）："]
    if out_scope:
        lines.append("- 不测范围（禁止生成相关用例）：")
        lines.extend(f"  · {item}" for item in out_scope)
    if risks:
        lines.append("- 风险 / 待澄清（优先覆盖，提高对应用例优先级）：")
        lines.extend(f"  · {item}" for item in risks)
    return "\n".join(lines)


def format_knowledge_hint(knowledge: list[dict] | None) -> str:
    """把检索知识格式化为 Prompt 文本，并附加防幻觉约束。"""
    if not knowledge:
        return ""
    lines = ["", "相关业务知识（来自项目知识库，按相关度排序）："]
    for index, item in enumerate(knowledge, 1):
        source = f"《{item.get('title', '')}》"
        if item.get("heading"):
            source += f" - {item['heading']}"
        lines.append(f"[知识{index}] 来源：{source}")
        lines.append(item.get("content", "").strip())
    lines.extend(
        [
            "",
            "约束：设计用例时必须结合以上业务知识；"
            "业务规则只能来自功能点描述和以上知识，禁止编造未提及的规则、金额、阈值或流程。",
        ]
    )
    return "\n".join(lines)


def feature_to_user_prompt(
    feature_item: dict,
    scope: dict | None = None,
    knowledge: list[dict] | None = None,
) -> str:
    parts = [f"功能点：\n{json.dumps(feature_item, ensure_ascii=False, indent=2)}"]
    scope_hint = format_scope_hint(scope)
    if scope_hint:
        parts.append(scope_hint)
    knowledge_hint = format_knowledge_hint(knowledge)
    if knowledge_hint:
        parts.append(knowledge_hint)
    return "\n".join(parts)
