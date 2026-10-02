from typing import Any

from app.ai.chains import generate_cases
from app.services.settings_service import RuntimeModelConfig


async def call_for_cases(
    system_prompt: str,
    user_prompt: str,
    skill_name: str,
    model_config: RuntimeModelConfig,
    *,
    runtime: Any | None = None,
) -> list[dict]:
    return await generate_cases(system_prompt, user_prompt, skill_name, model_config)
