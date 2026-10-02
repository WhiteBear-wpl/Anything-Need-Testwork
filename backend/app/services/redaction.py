"""Small shared helpers for removing credentials from persisted diagnostics."""

import re


_SECRET_PATTERNS = (
    (re.compile(r"(?im)(authorization\s*:\s*)[^\r\n]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(://[^/\s:@]+:)[^@\s/]+(@)"), r"\1[REDACTED]\2"),
    (re.compile(r"(?im)(authorization\s*:\s*bearer\s+)[^\s\"']+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._-]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(\b(?:api[_-]?key|authorization|password|token|client[_-]?secret|access[_-]?token|refresh[_-]?token)\s*[:=]\s*)(?:[^\s,;\"']+|\"[^\"]*\"|'[^']*')"), r"\1[REDACTED]"),
    (re.compile(r"(?i)([\"']?(?:api[_-]?key|authorization|password|token|client[_-]?secret|access[_-]?token|refresh[_-]?token)[\"']?\s*[:=]\s*[\"'])[^\"']*"), r"\1[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]+"), "[REDACTED]"),
)


def redact_output(raw: str | None, limit: int = 4000) -> str:
    """Mask common secret forms before storing a bounded diagnostic excerpt."""
    text = str(raw or "")
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text[: max(0, limit)]
