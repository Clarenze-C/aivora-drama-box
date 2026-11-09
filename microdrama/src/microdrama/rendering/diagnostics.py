"""Bounded, credential-safe diagnostics shared by live HTTP transports."""

import re
from collections.abc import Mapping

DIAGNOSTIC_READ_LIMIT = 8192
DIAGNOSTIC_TEXT_LIMIT = 500
_SENSITIVE = re.compile(r"authorization|cookie|api[-_]?key|token|secret|password", re.I)
_SENSITIVE_PREFIX = (
    r"([\"']?[\w-]*(?:authorization|cookie|api[-_]?key|token|secret|password)[\w-]*"
    r"[\"']?[ \t]*[:=][ \t]*)"
)
# Structured values end at their matching quote, not at punctuation within the
# credential. Consume an unterminated quoted value through the bounded input.
_QUOTED_HEADER = re.compile(
    _SENSITIVE_PREFIX + r"(?:\"(?:\\.|[^\"\\])*(?:\"|$)|'(?:\\.|[^'\\])*(?:'|$))",
    re.I,
)
# HTTP header values may contain commas/semicolons and folded continuation lines.
# Quoted values were handled above; do not consume adjacent JSON diagnostic fields.
_HEADER = re.compile(
    _SENSITIVE_PREFIX + r"(?![ \t\"'])(?:[^\r\n]*(?:\r?\n[ \t]+[^\r\n]*)*)",
    re.I,
)
_BEARER = re.compile(r"(?i)\b(?:bearer|basic)\s+[^\s\"']+")


def safe_diagnostic(value: bytes | str, headers: Mapping[str, str]) -> str:
    """Redact before truncating; never consult environment or credential files."""
    text = value[:DIAGNOSTIC_READ_LIMIT]
    text = text.decode("utf-8", "replace") if isinstance(text, bytes) else text
    secrets = set()
    for key, raw in headers.items():
        if _SENSITIVE.search(key):
            secrets.add(raw)
            if raw.lower().startswith(("bearer ", "basic ")):
                secrets.add(raw.split(" ", 1)[1])
    for secret in sorted(filter(None, secrets), key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
        # A bounded read may end halfway through a reflected known credential.
        for size in range(min(len(secret) - 1, len(text)), 0, -1):
            if text.endswith(secret[:size]):
                text = text[:-size] + "[REDACTED]"
                break
    text = _QUOTED_HEADER.sub(lambda match: match[1] + '"[REDACTED]"', text)
    text = _HEADER.sub(lambda match: match[1] + "[REDACTED]", text)
    text = _BEARER.sub("[REDACTED]", text)
    return text.strip()[:DIAGNOSTIC_TEXT_LIMIT]
