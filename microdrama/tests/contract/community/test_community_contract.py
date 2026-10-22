"""Contract tests for the community lane (T025): the frozen surfaces it consumes.

Pins, against the real migrated database and the frozen 1.6.0 contracts:
- the ``CommunityProvider`` protocol conformance of the T007 fake and its
  scripted-feed contract (duplicate delivery, DM window, injection-as-data);
- ``ManagementAction`` validation rules (content-bearing kinds, suppression
  reasons, reservation binding for metered EXECUTED, confidence bounds) and the
  DESTRUCTIVE/METADATA/CONTENT action sets;
- ``ManagementPolicy`` organic bounds (24h cooldown floor, two-edit ceiling,
  MD-018 flags impossible, no automatic bans);
- the ``community_events``/``management_actions`` table contracts (unique event
  dedupe, status-ladder CHECK, immutable untrusted text, unique action dedupe
  key, SUPPRESSED-requires-reason CHECK).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from microdrama.contracts.enums import (
    ActionDecision,
    BudgetCategory,
    CommunityEventKind,
    ManagementActionKind,
    Platform,
    Provenance,
)
from microdrama.contracts.errors import Conflict, DuplicateSemanticKey
from microdrama.contracts.examples import management_policy
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.providers import ActionResult, CommunityProvider
from microdrama.contracts.release import (
    CONTENT_ACTIONS,
    DESTRUCTIVE_ACTIONS,
    METADATA_ACTIONS,
    ManagementAction,
)
from microdrama.contracts.season import ManagementPolicy
from microdrama.persistence.db import insert_row
from microdrama.testing.fakes.common import FakeClock, SequentialIds
from microdrama.testing.fakes.community import (
    INJECTION_COMMENT,
    RETRY_AFTER_MS,
    CommunityScenario,
    FakeCommunityProvider,
)

FAKE = Provenance.FAKE_SYNTHETIC
T0 = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def fake_provider(*, scenarios: tuple[CommunityScenario, ...] = ()) -> FakeCommunityProvider:
    return FakeCommunityProvider(
        Platform.YOUTUBE,
        clock=FakeClock(T0),
        ids=SequentialIds("contract"),
        account_ref="acct:youtube-main",
        scenarios=scenarios,
    )


def action(*, kind: ManagementActionKind = ManagementActionKind.PUBLIC_REPLY, **updates: object):
    fields: dict[str, object] = {
        "action_id": uuid.uuid4(),
        "kind": kind,
        "platform": Platform.YOUTUBE,
        "account_ref": "acct:youtube-main",
        "content": "ขอบคุณค่ะ",
        "catalog_version": 1,
        "management_policy_hash": "0" * 64,
        "dedupe_key": f"contract:{uuid.uuid4().hex}",
        "decision": ActionDecision.PROPOSED,
    }
    fields.update(updates)
    return ManagementAction(**fields)  # type: ignore[arg-type]


# --- the provider protocol and the scripted feed ------------------------------------------


def test_fake_community_provider_satisfies_the_frozen_protocol() -> None:
    provider = fake_provider()
    assert isinstance(provider, CommunityProvider)
    assert provider.platform is Platform.YOUTUBE


def test_seeded_feed_contract_duplicate_dm_window_and_injection() -> None:
    provider = fake_provider()
    events = provider.fetch_events("acct:youtube-main", since=None)
    ids = [e.provider_event_id for e in events]
    assert ids.count("fake-comment-0001") == 2  # exact duplicate delivery
    kinds = {e.provider_event_id: e.kind for e in events}
    assert kinds["fake-reply-0002"] is CommunityEventKind.REPLY
    assert kinds["fake-dm-0003"] is CommunityEventKind.DIRECT_MESSAGE
    dm = [e for e in events if e.provider_event_id == "fake-dm-0003"][0]
    assert dm.dm_window_expires_at is not None and dm.dm_window_expires_at > T0
    injection = [e for e in events if e.provider_event_id == "fake-comment-0004"][0]
    assert injection.text == INJECTION_COMMENT  # data, never instructions
    assert all(e.provenance is FAKE for e in events)


def test_execute_is_deduped_by_dedupe_key_and_bills_a_settlement() -> None:
    provider = fake_provider()
    one = action()  # the same dedupe key dispatched twice executes once
    first = provider.execute(one)
    assert first.decision is ActionDecision.EXECUTED
    assert first.external_id is not None
    replay = provider.execute(one)
    assert replay.decision is ActionDecision.EXECUTED
    assert replay.external_id == first.external_id
    assert [c.scenario for c in provider.calls if c.method == "execute"] == [
        "HAPPY",
        "REPLAYED",
    ]
    # A metered action bills one synthetic SETTLEMENT receipt bound to the reservation.
    metered = action(estimated_cost_micro_usd=1_000, reservation_id=uuid.uuid4())
    result = provider.execute(metered)
    assert len(result.usage) == 1
    receipt = result.usage[0]
    assert receipt.kind.value == "SETTLEMENT"
    assert receipt.category is BudgetCategory.METERED_MANAGEMENT
    assert receipt.amount_micro_usd == 1_000
    assert receipt.reservation_id == metered.reservation_id


def test_rate_limited_scenario_returns_deferred_retryable() -> None:
    provider = fake_provider(scenarios=(CommunityScenario.RATE_LIMITED,))
    result = provider.execute(action())
    assert result.decision is ActionDecision.DEFERRED
    assert result.error_code == "RATE_LIMITED"
    assert result.transient is True
    assert result.retry_after_ms == RETRY_AFTER_MS
    assert (
        ActionResult(
            action_id=uuid.uuid4(),
            decision=ActionDecision.DEFERRED,
            error_code="RATE_LIMITED",
            transient=True,
            retry_after_ms=RETRY_AFTER_MS,
            provenance=FAKE,
        ).decision
        is ActionDecision.DEFERRED
    )


# --- the ManagementAction contract ---------------------------------------------------------


def test_content_actions_require_content() -> None:
    for kind in sorted(CONTENT_ACTIONS, key=lambda k: k.value):
        with pytest.raises(ValueError, match="requires content"):
            action(kind=kind, content=None)


def test_suppressed_actions_require_a_reason() -> None:
    with pytest.raises(ValueError, match="record a reason"):
        action(decision=ActionDecision.SUPPRESSED, reason=None)


def test_metered_execution_requires_a_reservation() -> None:
    with pytest.raises(ValueError, match="budget reservation"):
        action(
            decision=ActionDecision.EXECUTED,
            estimated_cost_micro_usd=1_000,
            reservation_id=None,
        )


def test_classifier_confidence_is_bounded_basis_points() -> None:
    with pytest.raises(ValueError):
        action(classifier_confidence_bp=10_001)
    with pytest.raises(ValueError):
        action(classifier_confidence_bp=-1)
    assert action(classifier_confidence_bp=9_000).classifier_confidence_bp == 9_000


def test_action_kind_sets_are_the_frozen_ones() -> None:
    assert DESTRUCTIVE_ACTIONS == frozenset(
        {ManagementActionKind.MODERATE_HIDE, ManagementActionKind.MODERATE_DELETE}
    )
    assert ManagementActionKind.MODERATE_REPORT not in DESTRUCTIVE_ACTIONS
    assert METADATA_ACTIONS == frozenset(
        {
            ManagementActionKind.TITLE_EDIT,
            ManagementActionKind.CAPTION_EDIT,
            ManagementActionKind.DESCRIPTION_EDIT,
            ManagementActionKind.HASHTAG_EDIT,
            ManagementActionKind.COVER_CHANGE,
            ManagementActionKind.LINK_UPDATE,
        }
    )
    assert CONTENT_ACTIONS == (METADATA_ACTIONS - {ManagementActionKind.COVER_CHANGE}) | {
        ManagementActionKind.PUBLIC_REPLY,
        ManagementActionKind.DM_SEND,
    }
    # No ban-like action kind exists in the frozen enum (no automatic bans).
    for kind in ManagementActionKind:
        assert "BAN" not in kind.value


# --- the ManagementPolicy bounds ---------------------------------------------------------------


def test_management_policy_organic_bounds() -> None:
    policy = management_policy()
    assert policy.metadata_cooldown_hours >= 24
    assert policy.max_substantive_edits_first_7_days <= 2
    assert policy.automatic_account_bans is False
    assert canonical_hash(policy)  # the Gate-2-bound policy hash is stable


def test_management_policy_refuses_forbidden_capabilities() -> None:
    base = management_policy()
    for forbidden in (
        {"metadata_cooldown_hours": 23},
        {"max_substantive_edits_first_7_days": 3},
        {"automatic_account_bans": True},
        {"remove_ordinary_criticism": True},
        {"cold_outbound_dms": True},
        {"accept_contracts_sponsors_refunds": True},
    ):
        with pytest.raises(ValueError):
            ManagementPolicy(
                allowed_actions=base.allowed_actions,
                dm_keywords=base.dm_keywords,
                **forbidden,  # type: ignore[arg-type]
            )


# --- the frozen table contracts (real migrated database) ----------------------------------------


def _event_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "platform": "YOUTUBE",
        "account_ref": "acct:youtube-main",
        "provider_event_id": f"contract-{uuid.uuid4().hex[:8]}",
        "kind": "COMMENT",
        "external_post_id": None,
        "author_ref": "author-contract",
        "text": "fixture contract text",
        "received_at": T0,
        "classification": None,
        "status": "RECEIVED",
        "provenance": FAKE.value,
    }
    values.update(overrides)
    return values


def test_community_events_unique_provider_dedupe_and_status_ladder(db) -> None:
    with db.transaction() as tx:
        values = _event_values()
        insert_row(tx, "community_events", values)
    with pytest.raises(DuplicateSemanticKey):
        with db.transaction() as tx:
            insert_row(tx, "community_events", {**values, "id": uuid.uuid4()})
    with pytest.raises(Conflict):  # the status CHECK: only the six ladder states
        with db.transaction() as tx:
            insert_row(tx, "community_events", _event_values(status="DELETED"))
    with pytest.raises(Conflict):  # untrusted text is immutable once ingested
        with db.transaction() as tx:
            tx.execute(
                "UPDATE community_events SET text = %s WHERE provider_event_id = %s",
                ("rewritten", values["provider_event_id"]),
            )


def test_management_actions_unique_dedupe_and_suppressed_reason_check(db) -> None:
    model = action(decision=ActionDecision.PROPOSED)
    with db.transaction() as tx:
        insert_row(
            tx,
            "management_actions",
            {
                "id": model.action_id,
                "kind": model.kind.value,
                "platform": model.platform.value,
                "account_ref": model.account_ref,
                "dedupe_key": model.dedupe_key,
                "body": model,
                "policy_hash": model.management_policy_hash,
                "catalog_version": model.catalog_version,
                "decision": model.decision.value,
                "provenance": FAKE.value,
            },
        )
    with pytest.raises(DuplicateSemanticKey):  # one row per dedupe key, forever
        with db.transaction() as tx:
            insert_row(
                tx,
                "management_actions",
                {
                    "id": uuid.uuid4(),
                    "kind": model.kind.value,
                    "platform": model.platform.value,
                    "account_ref": model.account_ref,
                    "dedupe_key": model.dedupe_key,
                    "body": model,
                    "policy_hash": model.management_policy_hash,
                    "catalog_version": model.catalog_version,
                    "decision": ActionDecision.PROPOSED.value,
                    "provenance": FAKE.value,
                },
            )
    with pytest.raises(Conflict):  # SUPPRESSED without a reason is not storable
        with db.transaction() as tx:
            insert_row(
                tx,
                "management_actions",
                {
                    "id": uuid.uuid4(),
                    "kind": model.kind.value,
                    "platform": model.platform.value,
                    "account_ref": model.account_ref,
                    "dedupe_key": f"contract:{uuid.uuid4().hex}",
                    "body": model,
                    "policy_hash": model.management_policy_hash,
                    "catalog_version": model.catalog_version,
                    "decision": ActionDecision.SUPPRESSED.value,
                    "reason": None,
                    "provenance": FAKE.value,
                },
            )
    with pytest.raises(Conflict):  # the action body is immutable once recorded
        with db.transaction() as tx:
            tx.execute(
                "UPDATE management_actions SET dedupe_key = %s WHERE id = %s",
                (f"contract:{uuid.uuid4().hex}", model.action_id),
            )
