"""Community, membership and webhook fakes: duplicates visible, injection as data, HMAC rules."""

from __future__ import annotations

import json
import uuid

import pytest

from microdrama.contracts.enums import (
    ActionDecision,
    CatalogPublicState,
    CommunityEventKind,
    MembershipProviderKind,
    Platform,
    Provenance,
)
from microdrama.contracts.errors import PolicyDenied, SchemaInvalid
from microdrama.contracts.examples import management_action, membership_catalog_entry
from microdrama.contracts.providers import CommunityProvider, MembershipProvider, WebhookVerifier
from microdrama.contracts.release import ManagementAction
from microdrama.testing.fakes import (
    FAKE_WEBHOOK_SECRET,
    CommunityScenario,
    EntitlementScenario,
    FakeClock,
    FakeCommunityProvider,
    FakeMembershipProvider,
    FakeWebhookVerifier,
    SequentialIds,
    fake_signature,
)
from microdrama.testing.fakes.community import INJECTION_COMMENT
from microdrama.testing.media import make_clip


def _provider(
    clock: FakeClock, ids: SequentialIds, *steps: CommunityScenario
) -> FakeCommunityProvider:
    return FakeCommunityProvider(Platform.TIKTOK, clock=clock, ids=ids, scenarios=steps)


def _action(**updates: object) -> ManagementAction:
    base = management_action().model_dump(mode="python")
    base.update(platform=Platform.TIKTOK, **updates)
    return ManagementAction(**base)


def test_community_fake_satisfies_protocol(clock, ids) -> None:
    assert isinstance(_provider(clock, ids), CommunityProvider)


def test_seeded_feed_has_an_exact_duplicate_and_is_returned_with_duplicates(clock, ids) -> None:
    events = _provider(clock, ids).fetch_events("acct:fake-main", since=None)
    ids_seen = [e.provider_event_id for e in events]
    assert ids_seen.count("fake-comment-0001") == 2
    assert all(e.provenance is Provenance.FAKE_SYNTHETIC for e in events)


def test_dm_carries_its_window_and_injection_stays_plain_text(clock, ids) -> None:
    events = _provider(clock, ids).fetch_events("acct:fake-main", since=None)
    dm = next(e for e in events if e.kind is CommunityEventKind.DIRECT_MESSAGE)
    assert dm.dm_window_expires_at is not None
    injected = [e for e in events if e.text == INJECTION_COMMENT]
    assert len(injected) == 1 and injected[0].author_ref.startswith("author-")


def test_since_filter_and_flood_generator(clock, ids) -> None:
    provider = _provider(clock, ids)
    later = provider.fetch_events("acct:fake-main", since=None)[-1].received_at
    assert all(e.received_at >= later for e in provider.fetch_events("acct:fake-main", since=later))
    flood = provider.flood(25)
    assert len(flood) == 25
    assert len(provider.fetch_events("acct:fake-main", since=None)) == 5 + 25


def test_execute_is_deduplicated_by_dedupe_key_and_billed_once(clock, ids) -> None:
    provider = _provider(clock, ids)
    metered = _action(estimated_cost_micro_usd=2_000, reservation_id=uuid.UUID(int=91))
    first = provider.execute(metered)
    second = provider.execute(metered)
    assert first == second
    assert first.decision is ActionDecision.EXECUTED
    assert first.external_id and first.external_id.startswith("fake-tiktok-action-")
    assert len(provider.ledger) == 1
    assert provider.ledger[0].amount_micro_usd == 2_000
    assert provider.ledger[0].provenance is Provenance.FAKE_SYNTHETIC


def test_rate_limited_action_is_deferred_and_can_run_later(clock, ids) -> None:
    provider = _provider(clock, ids, CommunityScenario.RATE_LIMITED)
    action = _action()
    deferred = provider.execute(action)
    assert deferred.decision is ActionDecision.DEFERRED
    assert deferred.transient is True and deferred.retry_after_ms == 60_000
    assert provider.execute(action).decision is ActionDecision.EXECUTED


def test_non_proposed_actions_and_wrong_platform_are_refused(clock, ids) -> None:
    provider = _provider(clock, ids)
    with pytest.raises(PolicyDenied):
        provider.execute(_action(decision=ActionDecision.SUPPRESSED, reason="fixture"))
    youtube = FakeCommunityProvider(Platform.YOUTUBE, clock=clock, ids=ids)
    with pytest.raises(SchemaInvalid):
        youtube.execute(_action())  # a TikTok action sent to the YouTube fake


@pytest.fixture
def membership(clock, ids) -> FakeMembershipProvider:
    return FakeMembershipProvider(MembershipProviderKind.PATREON, clock=clock, ids=ids)


def test_membership_fake_satisfies_protocol(membership) -> None:
    assert isinstance(membership, MembershipProvider)


def test_early_access_publish_is_idempotent_and_uses_invalid_tld_urls(membership, tmp_path) -> None:
    media = make_clip(tmp_path / "ep2.mp4", duration_ms=1_000, with_audio=False)
    entry = membership_catalog_entry()
    first = membership.publish_early_access(entry, media)
    second = membership.publish_early_access(entry, media)
    assert first == second
    assert first.member_url.startswith("https://members.fake.invalid/")


def test_free_or_unreleased_entries_are_never_published_to_members(membership, tmp_path) -> None:
    media = make_clip(tmp_path / "ep2.mp4", duration_ms=1_000, with_audio=False)
    entry = membership_catalog_entry().model_copy(
        update={"public_state": CatalogPublicState.NOT_RELEASED}
    )
    with pytest.raises(PolicyDenied):
        membership.publish_early_access(entry, media)


@pytest.mark.parametrize(
    ("scenario", "active", "tier"),
    [
        (EntitlementScenario.ACTIVE, True, "fake-supporter"),
        (EntitlementScenario.REVOKED, False, None),
        (EntitlementScenario.UNVERIFIABLE, None, None),
    ],
)
def test_entitlement_scenarios_keep_unknown_as_unknown(clock, ids, scenario, active, tier) -> None:
    provider = FakeMembershipProvider(
        MembershipProviderKind.PATREON, clock=clock, ids=ids, scenarios=(scenario,)
    )
    check = provider.check_entitlement("member-1", membership_catalog_entry())
    assert check.active is active
    assert check.tier == tier
    assert check.verified_at == clock.now()


def _signed(body: dict) -> tuple[dict[str, str], bytes]:
    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    return {"X-Fake-Signature": fake_signature(raw)}, raw


def test_secret_constant_is_clearly_named_test_only() -> None:
    assert FAKE_WEBHOOK_SECRET == b"fake-test-only-secret-not-for-production"


def test_valid_webhook_is_verified_and_duplicates_are_not_deduped(membership) -> None:
    headers, body = _signed({"id": "evt-100", "type": "member.created"})
    first = membership.verify_webhook(headers, body)
    second = membership.verify_webhook(headers, body)
    assert first.valid and first == second
    assert first.event_id == "evt-100" and first.event_type == "member.created"
    assert first.payload == {"id": "evt-100", "type": "member.created"}
    assert isinstance(membership.verifier, WebhookVerifier)


def test_bad_signature_is_invalid_with_no_payload(membership) -> None:
    _, body = _signed({"id": "evt-200"})
    result = membership.verify_webhook({"X-Fake-Signature": "0" * 64}, body)
    assert result.valid is False
    assert result.failure_reason == "SIGNATURE_MISMATCH"
    assert result.payload == {}


def test_missing_signature_and_malformed_or_idless_bodies_are_rejected(membership) -> None:
    _, body = _signed({"id": "evt-300"})
    assert membership.verify_webhook({}, body).failure_reason == "MISSING_SIGNATURE"
    garbage = b"not-json"
    signed = {"x-fake-signature": fake_signature(garbage)}
    assert membership.verify_webhook(signed, garbage).failure_reason == "MALFORMED_BODY"
    no_id = b'{"type":"x"}'
    assert FakeWebhookVerifier("fake-patreon").verify(
        {"x-fake-signature": fake_signature(no_id)}, no_id
    ).failure_reason == "MISSING_EVENT_ID"  # fmt: skip
