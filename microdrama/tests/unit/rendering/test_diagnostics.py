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
    deadline is set, every transport timeout is the time remaining.

    CN2-4 (2026-11-10, re-review round 2): the timeout is the ACTUAL POSITIVE
    REMAINDER - the old 1 s floor let a request started with 0.1 s left run a
    full second past the authorized wall limit, and an expired deadline still
    granted a request. Now expiry refuses the dispatch at the transport
    boundary; no provider request starts after the deadline."""
    from microdrama.contracts.errors import EffectDenied
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
        # Sub-second remainder: capped at the actual positive remainder, no floor.
        clock["now"] = base + timedelta(seconds=59, microseconds=900_000)
        assert bound_request_timeout(30) == pytest.approx(0.1)
        clock["now"] = base + timedelta(seconds=59, microseconds=999_999)
        assert bound_request_timeout(30) == pytest.approx(1e-6)
        # An expired deadline refuses the dispatch: no request starts at all.
        clock["now"] = deadline
        with pytest.raises(EffectDenied, match="deadline"):
            bound_request_timeout(30)
        clock["now"] = base + timedelta(seconds=61)
        with pytest.raises(EffectDenied, match="deadline"):
            bound_request_timeout(30)
    finally:
        reset_request_deadline(token)
    # The cleanup reset restores the default: cleanup requests after the run
    # deadline are deliberately unbounded again.
    assert bound_request_timeout(30) == 30


def test_nested_requests_that_exhaust_the_deadline_refuse_later_ones() -> None:
    """CN2-4: outer deadline checks cannot protect subsequent HTTP requests
    nested inside one acquisition operation. The list call consumed the remaining
    time; the paid create that follows must refuse at the transport boundary
    instead of starting after expiry."""
    from microdrama.contracts.errors import EffectDenied
    from microdrama.rendering.diagnostics import reset_request_deadline

    base = datetime(2026, 11, 9, 12, tzinfo=UTC)
    clock = {"now": base}
    token = set_request_deadline(base + timedelta(seconds=1), lambda: clock["now"])
    try:
        # First request starts at t=0 with 1 s left: its timeout is the remainder.
        assert bound_request_timeout(30) == pytest.approx(1.0)
        # The request itself advances the clock past the deadline (a slow read).
        clock["now"] = base + timedelta(seconds=2)
        with pytest.raises(EffectDenied, match="deadline"):
            bound_request_timeout(30)
    finally:
        reset_request_deadline(token)
