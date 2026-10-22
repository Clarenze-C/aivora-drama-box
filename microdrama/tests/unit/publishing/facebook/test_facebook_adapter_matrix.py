"""The frozen scenario matrix at the Facebook adapter level (T024).

Adapter driven directly (no service): ACCEPTED / DENIED_PERMISSION / TOKEN_EXPIRED /
RATE_LIMITED / TIMEOUT_CREATED / TIMEOUT_NOT_CREATED, plus the client-token dedupe
that makes a replayed job run create nothing. With the SHIPPED operations the
ACCEPTED path still refuses an AI-disclosed submit (DISCLOSURE_UNVERIFIED) — that is
declaration truth, not a regression; the mechanics are exercised through the
``TEST_AI_CAPABLE_OPS`` test-only variant.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import pytest
from facebook_support import (
    FB_ACCOUNT,
    T0,
    TEST_AI_CAPABLE_OPS,
    fb_command,
    fixture_adapter,
    media_file,
)

from microdrama.contracts.enums import ReleaseState, SlotKind
from microdrama.contracts.errors import NeedsReconciliation, NotFound, RateLimited
from microdrama.contracts.release import PublicationCommand
from microdrama.publishing.facebook.transport import FacebookScenario
from microdrama.testing.fakes.common import FakeClock, SequentialIds


def adapter(operations=None, scenarios: tuple[FacebookScenario, ...] = ()):
    return fixture_adapter(  # fmt: skip
        FakeClock(T0), SequentialIds("fb-matrix"), operations=operations, scenarios=scenarios
    )


@pytest.fixture
def media(tmp_path: Path):
    return media_file(tmp_path)


@pytest.mark.parametrize(
    ("scenario", "error_code"),
    [
        (FacebookScenario.DENIED_PERMISSION, "PERMISSION_DENIED"),
        (FacebookScenario.TOKEN_EXPIRED, "TOKEN_EXPIRED"),
    ],
)
def test_permanent_refusals_map_to_failed_results(
    media, scenario: FacebookScenario, error_code: str
) -> None:
    """Refusals outrank the adapter's own gates (platform outcome first), like T007."""
    fb = adapter(operations=TEST_AI_CAPABLE_OPS, scenarios=(scenario,))
    command = fb_command(token="tok-refused", asset=media)
    result = fb.submit(command, media[0])
    assert result.state is ReleaseState.FAILED
    assert result.error_code == error_code
    assert result.transient is False
    assert fb.reconcile(command).found is False  # nothing was created


def test_accepted_with_shipped_operations_refuses_the_ai_disclosure(media) -> None:
    """Declaration truth: no documented AI-label field means no AI-disclosed post,
    even on the happy path. The submit FAILED before anything was created."""
    fb = adapter()  # shipped snapshot: AI_DISCLOSURE UNKNOWN
    command = fb_command(token="tok-truth", asset=media)
    result = fb.submit(command, media[0])
    assert result.state is ReleaseState.FAILED
    assert result.error_code == "DISCLOSURE_UNVERIFIED"
    assert fb.reconcile(command).found is False


def test_rate_limited_raises_with_retry_after_and_creates_nothing(media) -> None:
    fb = adapter(operations=TEST_AI_CAPABLE_OPS, scenarios=(FacebookScenario.RATE_LIMITED,))
    command = fb_command(token="tok-429", asset=media)
    with pytest.raises(RateLimited) as limited:
        fb.submit(command, media[0])
    assert limited.value.details["retry_after_ms"] == 60_000
    assert fb.reconcile(command).found is False


def test_timeout_not_created_needs_reconciliation_and_finds_nothing(media) -> None:
    fb = adapter(operations=TEST_AI_CAPABLE_OPS, scenarios=(FacebookScenario.TIMEOUT_NOT_CREATED,))
    command = fb_command(token="tok-tnc", asset=media)
    with pytest.raises(NeedsReconciliation):
        fb.submit(command, media[0])
    assert fb.reconcile(command).found is False  # proven absent: safe to re-arm


def test_timeout_created_leaves_a_findable_post_for_reconciliation(media) -> None:
    fb = adapter(operations=TEST_AI_CAPABLE_OPS, scenarios=(FacebookScenario.TIMEOUT_CREATED,))
    command = fb_command(token="tok-tc", asset=media)
    with pytest.raises(NeedsReconciliation):
        fb.submit(command, media[0])  # the response was lost AFTER creation
    outcome = fb.reconcile(command)
    assert outcome.found is True
    assert outcome.result is not None
    assert outcome.result.state is ReleaseState.SUBMITTED
    assert outcome.result.external_id.startswith("fb-full-")
    assert fb.status(command, outcome.result.external_id).state is ReleaseState.PROCESSING
    assert fb.status(command, outcome.result.external_id).state is ReleaseState.PUBLISHED_VERIFIED


def test_accepted_submit_walks_uploaded_processing_published(media) -> None:
    fb = adapter(operations=TEST_AI_CAPABLE_OPS)
    command = fb_command(token="tok-happy", asset=media)
    result = fb.submit(command, media[0])
    assert result.state is ReleaseState.SUBMITTED
    external_id = result.external_id
    assert external_id.startswith("fb-full-")
    assert fb.status(command, external_id).state is ReleaseState.PROCESSING
    published = fb.status(command, external_id)
    assert published.state is ReleaseState.PUBLISHED_VERIFIED
    assert published.url is not None
    assert urlparse(published.url).hostname.endswith(".invalid")


def test_replayed_submit_is_deduplicated_by_client_token(media) -> None:
    fb = adapter(operations=TEST_AI_CAPABLE_OPS)
    command = fb_command(token="tok-replay", asset=media)
    first = fb.submit(command, media[0])
    second = fb.submit(command, media[0])  # the job ran twice
    assert second.external_id == first.external_id
    assert len(fb.transport.videos) == 1  # exactly one post exists at the platform


def test_status_of_an_unknown_external_id_raises_not_found(media) -> None:
    fb = adapter(operations=TEST_AI_CAPABLE_OPS)
    command: PublicationCommand = fb_command(token="tok-unknown", asset=media)
    fb.submit(command, media[0])
    with pytest.raises(NotFound):
        fb.status(command, "fb-full-doesnotexist00")


def test_short_route_matrix_reel_refusals(media) -> None:
    """The same refusal mapping holds on the Reels route (PROMO_CUT)."""
    fb = adapter(operations=TEST_AI_CAPABLE_OPS, scenarios=(FacebookScenario.DENIED_PERMISSION,))
    command = fb_command(slot_kind=SlotKind.PROMO_CUT, token="tok-reel-denied", asset=media)
    result = fb.submit(command, media[0])
    assert result.state is ReleaseState.FAILED
    assert result.error_code == "PERMISSION_DENIED"
    assert command.slot_kind is SlotKind.PROMO_CUT
    assert FB_ACCOUNT == command.slot.account_ref
