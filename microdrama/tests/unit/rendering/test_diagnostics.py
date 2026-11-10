"""CN-3 (2026-11-09, canary-night review): the diagnostics contract.

Upstream bodies and exception texts reach exceptions, persisted run records and
stderr. Everything secret-shaped must be redacted BEFORE a message is built:
reflected Authorization/Bearer values, api_key/token fields, URL userinfo and
signed-URL query parameters; and an uncertainty cause is the exception TYPE plus
a sanitised category - never raw exception text. All secrets here are synthetic.
"""

from __future__ import annotations

import socket
from datetime import UTC, datetime, timedelta
from urllib.error import URLError

import pytest

from microdrama.rendering.diagnostics import (
    bound_request_timeout,
    safe_diagnostic,
    set_request_deadline,
    uncertainty_cause,
)


def test_url_userinfo_and_signed_query_parameters_are_redacted() -> None:
    body = (
        b"request refused by upstream\n"
        b"mirror: https://operator:synthetic-url-password@api.runpod.io/v1/pods?alt=json\n"
        b"https://cdn.invalid/f.mp4?X-Goog-Signature=synthetic-signed-value\n"
        b"https://q.invalid/t?token=synthetic-query-token"
    )
    out = safe_diagnostic(body, {})
    for secret in (
        "synthetic-url-password",
        "synthetic-signed-value",
        "synthetic-query-token",
    ):
        assert secret not in out, secret
    # The non-secret diagnostic material survives.
    assert "refused by upstream" in out
    assert "api.runpod.io" in out and "alt=json" in out


def test_resolved_header_credentials_stay_redacted() -> None:
    out = safe_diagnostic(
        b"rejected; echoed Authorization: Bearer synthetic-bearer-echo",
        {"Authorization": "Bearer synthetic-bearer-echo"},
    )
    assert "synthetic-bearer-echo" not in out
    assert "rejected" in out


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (TimeoutError("timed out; bearer synthetic-timeout-secret"), "TimeoutError/timeout"),
        (
            URLError(TimeoutError("op timed out; key=synthetic-key")),
            "URLError/timeout",
        ),
        (
            URLError(ConnectionResetError(104, "Connection reset by peer")),
            "URLError/connection-reset",
        ),
        (
            URLError(ConnectionRefusedError(111, "Connection refused")),
            "URLError/connection-refused",
        ),
        (
            URLError(socket.gaierror("name resolution failed for evil.invalid")),
            "URLError/dns-resolution",
        ),
        (URLError(ValueError("odd cause text")), "URLError/transport-error"),
    ],
)
def test_uncertainty_cause_is_type_and_category_never_raw_text(
    exc: BaseException, expected: str
) -> None:
    cause = uncertainty_cause(exc)
    assert cause == expected
    # The raw exception text - which may quote credentials, signed URLs or
    # reflected bodies - must not be carried into the cause.
    assert "timed out" not in cause
    assert "reset by peer" not in cause
    assert "refused" not in cause or expected.endswith("connection-refused")
    assert "evil.invalid" not in cause
    assert "synthetic" not in cause.lower()


def test_request_timeouts_are_bounded_by_the_remaining_deadline() -> None:
    """CN-6 (2026-11-09, canary-night review): a fixed 30-second transport
    timeout could outlive the run's authorized wall limit; while a request
    deadline is set, every transport timeout is the time remaining (with a
    small floor so a request started just before expiry still gets its chance)."""
    from microdrama.rendering.diagnostics import reset_request_deadline

    base = datetime(2026, 11, 9, 12, tzinfo=UTC)
    deadline = base + timedelta(seconds=60)
    clock = {"now": base}

    # No deadline set: the transport default applies.
    assert bound_request_timeout(30) == 30

    token = set_request_deadline(deadline, lambda: clock["now"])
    try:
        assert bound_request_timeout(30) == 30  # plenty left: the default
        clock["now"] = base + timedelta(seconds=55)
        assert bound_request_timeout(30) == 5.0  # bounded by the remainder
        clock["now"] = base + timedelta(seconds=59, microseconds=900_000)
        assert bound_request_timeout(30) == 1.0  # floored, never zero
    finally:
        reset_request_deadline(token)
    assert bound_request_timeout(30) == 30  # the reset restores the default
