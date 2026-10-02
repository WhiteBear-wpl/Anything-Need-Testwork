from pathlib import Path

from app.ai.chains import generate_test_proposal
from langchain_core.exceptions import OutputParserException
from app.skills.base import SkillContext
from app.skills.shared.prompt_loader import load_prompt

SKILL_DIR = Path(__file__).resolve().parent

MOCK_SCOPE = {
    "in_scope": [
        "核心登录流程（账号密码、手机号验证码）",
        "密码错误提示与连续错误锁定策略",
        "输入校验与边界（空值、格式、长度）",
    ],
    "out_scope": [
        "第三方 OAuth / 扫码登录",
        "性能与并发压测",
        "UI 视觉走查",
    ],
    "risks": [
        "短信验证码通道稳定性未知",
        "锁定阈值与风控策略耦合，需与产品确认",
        "多端并发登录行为未在需求中明确",
    ],
}


def _normalize(data) -> dict:
    if not isinstance(data, dict):
        data = {}
    return {
        "in_scope": list(data.get("in_scope") or []),
        "out_scope": list(data.get("out_scope") or []),
        "risks": list(data.get("risks") or []),
    }


async def run(inputs: dict, context: SkillContext) -> dict:
    raw_content = inputs["raw_content"]
    if context.use_mock:
        return {"scope": MOCK_SCOPE}

    system_prompt = load_prompt(SKILL_DIR, "prompt.md")
    try:
        data = await generate_test_proposal(system_prompt, raw_content, context.model_config)
    except OutputParserException:
        data = {}
    return {"scope": _normalize(data)}
