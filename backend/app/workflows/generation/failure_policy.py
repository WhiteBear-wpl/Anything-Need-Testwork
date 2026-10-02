"""case_writer 的失败分类、重试约束和安全输出摘录。"""

from dataclasses import dataclass
from enum import StrEnum

from langchain_core.exceptions import OutputParserException
from app.services.redaction import redact_output
from app.skills.errors import SkillOutputError


MAX_FEATURE_INVOCATIONS = 3
MAX_REPAIR_RETRIES = 1


class FailureCode(StrEnum):
    JSON_INVALID = "JSON_INVALID"
    SCHEMA_MISSING_FIELD = "SCHEMA_MISSING_FIELD"
    SCHEMA_TYPE_ERROR = "SCHEMA_TYPE_ERROR"
    RESPONSE_TRUNCATED = "RESPONSE_TRUNCATED"
    TIMEOUT = "TIMEOUT"
    RATE_LIMIT = "RATE_LIMIT"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    CONFIG_ERROR = "CONFIG_ERROR"


class RetryKind(StrEnum):
    NONE = "none"
    REPAIR = "repair"
    TRANSPORT = "transport"
    DOWNSCOPE = "downscope"


@dataclass(frozen=True)
class RetryDirective:
    message: str = ""
    delay_seconds: float = 0.0
    reduce_scope: bool = False


@dataclass(frozen=True)
class FailureDecision:
    code: FailureCode
    recoverable: bool
    retry_kind: RetryKind
    directive: RetryDirective


def _has_budget(attempt_count: int) -> bool:
    return attempt_count < MAX_FEATURE_INVOCATIONS


def _parser_decision(validation_errors: list[dict], attempt_count: int) -> FailureDecision:
    first_error = validation_errors[0] if validation_errors else {}
    path = str(first_error.get("path") or "$")
    message = str(first_error.get("message") or "无法解析为约定的结构化结果")
    lower_message = message.lower()
    code = FailureCode.SCHEMA_MISSING_FIELD if "required" in lower_message else FailureCode.SCHEMA_TYPE_ERROR
    if not validation_errors:
        code = FailureCode.JSON_INVALID

    can_repair = attempt_count <= MAX_REPAIR_RETRIES and _has_budget(attempt_count)
    directive = RetryDirective(
        message=(
            "仅返回符合既定 Schema 的 JSON，不要使用 Markdown 代码块。"
            f"校验错误位于 {path}：{message}。请仅修复该结构错误，不要补充未提供的业务信息。"
        )
    )
    return FailureDecision(code, can_repair, RetryKind.REPAIR if can_repair else RetryKind.NONE, directive)


def _transport_decision(exc: Exception, attempt_count: int) -> FailureDecision:
    text = str(exc).lower()
    if "429" in text or "rate limit" in text or "rate_limit" in text:
        code = FailureCode.RATE_LIMIT
    elif isinstance(exc, TimeoutError) or "timeout" in text or "timed out" in text:
        code = FailureCode.TIMEOUT
    else:
        code = FailureCode.UPSTREAM_ERROR

    can_retry = _has_budget(attempt_count)
    delay = float(2 ** max(0, attempt_count - 1))
    return FailureDecision(
        code,
        can_retry,
        RetryKind.TRANSPORT if can_retry else RetryKind.NONE,
        RetryDirective(delay_seconds=delay),
    )


def classify_failure(
    exc: Exception,
    validation_errors: list[dict] | None,
    attempt_count: int,
) -> FailureDecision:
    """Return a deterministic retry decision for a completed invocation count."""
    errors = validation_errors or []
    if isinstance(exc, SkillOutputError):
        return _parser_decision(exc.validation_errors, attempt_count)
    if isinstance(exc, OutputParserException):
        return _parser_decision(errors, attempt_count)
    return _transport_decision(exc, attempt_count)
