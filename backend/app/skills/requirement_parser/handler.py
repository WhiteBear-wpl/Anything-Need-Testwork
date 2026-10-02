from app.ai.chains import parse_requirement_items
from app.skills.base import SkillContext
from app.skills.shared.mock import MOCK_REQUIREMENT_ITEMS
from app.skills.shared.prompt_loader import load_prompt

SKILL_DIR = __import__("pathlib").Path(__file__).resolve().parent


async def run(inputs: dict, context: SkillContext) -> dict:
    raw_content = inputs["raw_content"]
    if context.use_mock:
        return {"items": MOCK_REQUIREMENT_ITEMS}

    system_prompt = load_prompt(SKILL_DIR, "prompt.md")
    items = await parse_requirement_items(system_prompt, raw_content, context.model_config)
    return {"items": items}
