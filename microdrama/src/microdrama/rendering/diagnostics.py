"""Bounded, credential-safe diagnostics shared by live HTTP transports."""

import errno
import re
import socket
from collections.abc import Callable, Collection, Mapping
from typing import Any
from contextvars import ContextVar, Token
from datetime import datetime

from microdrama.contracts.errors import EffectDenied

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
# CN-3 (2026-11-09, canary-night review): URL userinfo and signed-URL query
# parameters are credential material when an upstream echoes a request URL.
_URL_USERINFO = re.compile(r"(?i)\b((?:https?|ftps?|wss?)://)[^\s/@:\"']+:[^\s/@\"']+@")
_SIGNED_QUERY = re.compile(
    r"(?i)([?&][a-z0-9_.-]*(?:signature|sig|credential|token|secret|key|access)"
    r"[a-z0-9_.-]*=)[^&\s\"'<>]*"
)


def collect_body_secrets(body: Any) -> tuple[str, ...]:
    """CN2-2 (2026-11-10, re-review round 2): every resolved credential the
    request BODY carries - a nonempty string under a secret-shaped JSON key, at
    any depth - is redaction context for that request's diagnostics. The Runpod
    create payload's env carries the Comfy gateway token under
    ``MICRODRAMA_COMFY_TOKEN``; a provider rejection can echo it back unlabelled,
    where header-only redaction cannot catch it."""
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                if isinstance(value, str) and value and _SENSITIVE.search(str(key)):
                    found.append(value)
                else:
                    walk(value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item)

    walk(body)
    return tuple(found)


def safe_diagnostic(
    value: bytes | str, headers: Mapping[str, str], *, extra_secrets: Collection[str] = ()
) -> str:
    """Redact before truncating; never consult environment or credential files.

    The redaction context is every resolved credential the request carries: the
    sensitive header values AND any body-borne secrets the caller resolved
    (``collect_body_secrets``), so a provider echoing either one back - even
    unlabelled - cannot disclose it."""
    text = value[:DIAGNOSTIC_READ_LIMIT]
    text = text.decode("utf-8", "replace") if isinstance(text, bytes) else text
    secrets = set()
    for key, raw in headers.items():
        if _SENSITIVE.search(key):
            secrets.add(raw)
            if raw.lower().startswith(("bearer ", "basic ")):
                secrets.add(raw.split(" ", 1)[1])
    secrets.update(secret for secret in extra_secrets if secret)
    for secret in sorted(filter(None, secrets), key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
        # A bounded read may end halfway through a reflected known credential.
        for size in range(min(len(secret) - 1, len(text)), 0, -1):
            if text.endswith(secret[:size]):
                text = text[:-size] + "[REDACTED]"
                break
    text = _URL_USERINFO.sub(lambda match: match[1] + "[REDACTED]@", text)
    text = _SIGNED_QUERY.sub(lambda match: match[1] + "[REDACTED]", text)
    text = _QUOTED_HEADER.sub(lambda match: match[1] + '"[REDACTED]"', text)
    text = _HEADER.sub(lambda match: match[1] + "[REDACTED]", text)
    text = _BEARER.sub("[REDACTED]", text)
    return text.strip()[:DIAGNOSTIC_TEXT_LIMIT]


def uncertainty_cause(exc: BaseException) -> str:
    """CN-3 (2026-11-09, canary-night review): the cause an uncertainty message
    carries is the exception TYPE plus a sanitised category - never the raw
    exception text, which can quote request URLs with credentials, signed query
    strings, or reflected provider bodies.
    """
    reason = getattr(exc, "reason", None)
    name = type(exc).__name__
    if isinstance(exc, TimeoutError) or isinstance(reason, TimeoutError):
        return f"{name}/timeout"
    errno_value = getattr(reason, "errno", None)
    if errno_value in (errno.ECONNRESET, errno.ECONNABORTED):
        return f"{name}/connection-reset"
    if errno_value == errno.ECONNREFUSED:
        return f"{name}/connection-refused"
    if isinstance(reason, ConnectionResetError | ConnectionAbortedError):
        return f"{name}/connection-reset"
    if isinstance(reason, ConnectionRefusedError):
        return f"{name}/connection-refused"
    if isinstance(reason, ConnectionError):
        return f"{name}/connection-failed"
    if isinstance(reason, socket.gaierror):
        return f"{name}/dns-resolution"
    if isinstance(reason, OSError):
        return f"{name}/socket-error"
    return f"{name}/transport-error"


# CN-6 (2026-11-09, canary-night review): while a run deadline is set, every live
# transport's request timeout is bounded by the time remaining to it, so no
# provider request outlives the authorized wall limit by a fixed 30-second
# timeout. The pair carries the deadline and the run's clock (fake in tests).
_REQUEST_DEADLINE: ContextVar[tuple[datetime, Callable[[], datetime]] | None] = ContextVar(
    "microdrama_request_deadline", default=None
)


def set_request_deadline(deadline: datetime, now: Callable[[], datetime]) -> Token:
    """Bind all transport timeouts made in this context to the run deadline."""
    return _REQUEST_DEADLINE.set((deadline, now))


def reset_request_deadline(token: Token) -> None:
    _REQUEST_DEADLINE.reset(token)


def bound_request_timeout(default_seconds: float) -> float:
    """The timeout for one transport request: the default, or the time left to
    the deadline, capped at the ACTUAL POSITIVE REMAINDER - no floor.

    CN2-4 (2026-11-10, re-review round 2): a 1 s floor let a request started
    with 0.1 s left run a full second past the authorized wall limit, and outer
    deadline checks cannot protect requests nested inside one acquisition
    operation - so an expired deadline now refuses the dispatch here, at the
    transport boundary: no provider request starts after the deadline. Cleanup
    contexts reset the deadline (reset_request_deadline) and stay unbounded."""
    bound = _REQUEST_DEADLINE.get()
    if bound is None:
        return default_seconds
    deadline, now = bound
    remaining = (deadline - now()).total_seconds()
    if remaining <= 0:
        raise EffectDenied(
            "the request deadline has passed; refusing to start another provider request"
        )
    if remaining >= default_seconds:
        return default_seconds
    return remaining
