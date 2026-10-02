import asyncio
import time
from typing import Any

from pydantic import ValidationError

from app.agent_runtime.contracts import BudgetExhausted, RuntimeCancelled
from app.agent_runtime.harness import active_runtime_harness
from app.skills.base import SkillContext, SkillDefinition
from app.skills.errors import SkillInputError, SkillOutputError, SkillTimeoutError


def _validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for error in exc.errors(include_url=False, include_context=False, include_input=False):
        path = "$"
        for part in error.get("loc") or ():
            if isinstance(part, int):
                path += f"[{part}]"
            else:
                path += f".{part}"
        normalized.append(
            {
                "path": path,
                "message": str(error.get("msg") or "contract validation failed"),
            }
        )
    return normalized


class SkillExecutor:
    """Validate and govern every Skill invocation behind one stable boundary."""

    async def execute(
        self,
        definition: SkillDefinition,
        inputs: dict[str, Any],
        context: SkillContext,
    ) -> dict[str, Any]:
        try:
            validated_input = definition.input_model.model_validate(inputs)
        except ValidationError as exc:
            raise SkillInputError(
                definition.meta.name,
                _validation_errors(exc),
            ) from exc

        runtime = context.runtime
        started_at = time.monotonic()

        def record(
            event_type: str,
            *,
            error_type: str = "",
            message: str = "",
        ) -> None:
            if runtime is None:
                return
            duration_ms = int((time.monotonic() - started_at) * 1000)
            runtime.record_skill_event(
                event_type,
                definition.meta.name,
                definition.meta.version,
                definition.meta.category,
                duration_ms=duration_ms,
                error_type=error_type,
                message=message,
            )

        if runtime is not None:
            try:
                runtime.check_cancelled()
            except RuntimeCancelled:
                record(
                    "skill_cancelled",
                    error_type="RuntimeCancelled",
                    message="skill cancelled",
                )
                raise
            runtime.record_skill_event(
                "skill_started",
                definition.meta.name,
                definition.meta.version,
                definition.meta.category,
            )

        try:
            timeout_seconds = (
                context.timeout_seconds
                if context.timeout_seconds is not None
                else definition.meta.timeout_seconds
            )
            if runtime is not None:
                remaining = runtime.remaining_runtime_seconds()
                if remaining <= 0:
                    limit = int(runtime.context.budget.max_runtime_seconds)
                    raise BudgetExhausted("runtime_seconds", limit, limit)
                timeout_seconds = min(timeout_seconds, remaining)
            if runtime is not None:
                with active_runtime_harness(runtime):
                    async with asyncio.timeout(timeout_seconds):
                        raw_output = await definition.handler(
                            validated_input.model_dump(), context
                        )
            else:
                async with asyncio.timeout(timeout_seconds):
                    raw_output = await definition.handler(
                        validated_input.model_dump(), context
                    )
            validated_output = definition.output_model.model_validate(raw_output).model_dump()
            if definition.meta.category == "specialist" and context.max_cases is not None:
                validated_output["cases"] = list(validated_output.get("cases") or [])[:context.max_cases]
        except RuntimeCancelled:
            record(
                "skill_cancelled",
                error_type="RuntimeCancelled",
                message="skill cancelled",
            )
            raise
        except BudgetExhausted:
            record(
                "skill_cancelled",
                error_type="BudgetExhausted",
                message="runtime budget exhausted",
            )
            raise
        except ValidationError as exc:
            errors = _validation_errors(exc)
            record(
                "skill_failed",
                error_type="SkillOutputError",
                message="output contract rejected",
            )
            raise SkillOutputError(definition.meta.name, errors) from exc
        except TimeoutError as exc:
            record(
                "skill_failed",
                error_type="SkillTimeoutError",
                message="skill timed out",
            )
            raise SkillTimeoutError(definition.meta.name) from exc
        except Exception as exc:
            record(
                "skill_failed",
                error_type=type(exc).__name__,
                message="handler failed",
            )
            raise

        record("skill_completed")
        return validated_output
