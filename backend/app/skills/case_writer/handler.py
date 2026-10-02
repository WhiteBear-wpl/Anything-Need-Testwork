from pathlib import Path

from app.skills.base import SkillContext
from app.skills.shared.llm_runner import call_for_cases
from app.skills.shared.mock import mock_cases
from app.skills.shared.prompt_formatter import feature_to_user_prompt
from app.skills.shared.prompt_loader import load_prompt

SKILL_DIR = Path(__file__).resolve().parent
SKILL_NAME = "case_writer"
PROMPT_PATH = "prompts/write.md"

QUICK_SUFFIX = (
    "\n\n【本次仅生成冒烟用例】只输出核心主路径用例，每个功能点 2～4 条，"
    "全部 is_smoke=true，优先 P0/P1，case_type 以 functional 为主，可含 1 条关键异常。"
)


async def run(inputs: dict, context: SkillContext) -> dict:
    feature_item = inputs["feature_item"]
    scope = inputs.get("scope")
    knowledge = inputs.get("knowledge")
    strategy = inputs.get("strategy", "full")
    quick = strategy == "quick"
    repair_instruction = (inputs.get("repair_instruction") or "").strip()

    if context.use_mock:
        if quick:
            cases = mock_cases(
                feature_item["feature"], 3,
                ["functional", "functional", "exception"], SKILL_NAME, smoke=True,
            )
        else:
            cases = mock_cases(
                feature_item["feature"], 6,
                ["functional", "boundary", "exception"], SKILL_NAME,
            )
        return {"cases": cases}

    prompt = load_prompt(SKILL_DIR, PROMPT_PATH)
    if quick:
        prompt = prompt + QUICK_SUFFIX
    if repair_instruction:
        prompt = prompt + "\n\n【上次结构校验反馈】\n" + repair_instruction
    user_prompt = feature_to_user_prompt(feature_item, scope, knowledge)
    cases = await call_for_cases(
        prompt,
        user_prompt,
        SKILL_NAME,
        context.model_config,
        runtime=context.runtime,
    )
    return {"cases": cases}
