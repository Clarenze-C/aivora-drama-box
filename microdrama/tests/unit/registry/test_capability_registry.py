"""Capability registry on the real database: only SUPPORTED_TESTED operations pass; documentation,
unknown and unsupported support each block with its own message; disclosures, versions, routes,
fake-only evidence and the D3 refusal."""

from __future__ import annotations

from datetime import timedelta

import pytest
from registry_support import (
    ACCOUNT,
    CAP_ROUTE,
    T0,
    capability,
    count,
    fixed_clock,
    live_settings,
    mock_settings,
    real_benchmark,
    switch_runtime_mode,
)

from microdrama.contracts.enums import (
    CapabilityOperation,
    CapabilitySupport,
    DisclosureKind,
    EvidenceSource,
    ExecutionMode,
    Platform,
    Provenance,
)
from microdrama.contracts.errors import (
    CapabilityUnavailable,
    Conflict,
    PolicyDenied,
    SchemaInvalid,
    Unauthorized,
)
from microdrama.contracts.primitives import EvidenceRef
from microdrama.core.registry import CapabilityRegistry
from microdrama.persistence import Database

pytestmark = pytest.mark.db

UPLOAD = {CapabilityOperation.UPLOAD_SHORT, CapabilityOperation.SCHEDULE}
AI = {DisclosureKind.AI_GENERATED_CONTENT}


def _registry(db: Database, settings=None) -> CapabilityRegistry:
    return CapabilityRegistry(db, fixed_clock(), settings or mock_settings())


def _evaluate(registry: CapabilityRegistry, **kwargs):
    kwargs.setdefault("platform", Platform.TIKTOK)
    kwargs.setdefault("account_ref", ACCOUNT)
    kwargs.setdefault("required", UPLOAD)
    return registry.evaluate(**kwargs)


def test_no_record_blocks(db: Database) -> None:
    decision = _evaluate(_registry(db))
    assert decision.available is False
    assert decision.record_version is None
    assert decision.blockers == [f"capability TIKTOK/{ACCOUNT}: no current record"]


def test_all_required_operations_tested_is_available(db: Database) -> None:
    registry = _registry(db)
    registry.record(capability(), source_provenance=Provenance.FAKE_SYNTHETIC)
    decision = _evaluate(registry, disclosures=AI)
    assert decision.available is True
    assert decision.blockers == []
    assert decision.record_version == 1
    assert registry.require(
        platform=Platform.TIKTOK, account_ref=ACCOUNT, required=UPLOAD, disclosures=AI
    ).available


def test_documentation_only_support_blocks_with_its_own_message(db: Database) -> None:
    registry = _registry(db)
    registry.record(
        capability(
            operations={CapabilityOperation.UPLOAD_SHORT: CapabilitySupport.SUPPORTED_DOCUMENTED}
        ),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    decision = _evaluate(registry)
    assert decision.available is False
    assert len(decision.blockers) == 1
    assert "UPLOAD_SHORT blocked, support is documented only, not tested" in decision.blockers[0]


@pytest.mark.parametrize(
    "support",
    [CapabilitySupport.UNSUPPORTED, CapabilitySupport.UNKNOWN],
    ids=lambda s: s.value,
)
def test_unsupported_and_unknown_support_block_with_distinct_messages(
    db: Database, support: CapabilitySupport
) -> None:
    registry = _registry(db)
    registry.record(
        capability(operations={CapabilityOperation.SCHEDULE: support}),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    decision = _evaluate(registry)
    assert decision.available is False
    assert "SCHEDULE blocked, support is " in decision.blockers[0]


def test_the_three_non_tested_messages_are_all_different(db: Database) -> None:
    registry = _registry(db)
    messages: set[str] = set()
    for index, support in enumerate(
        (
            CapabilitySupport.SUPPORTED_DOCUMENTED,
            CapabilitySupport.UNSUPPORTED,
            CapabilitySupport.UNKNOWN,
        )
    ):
        # One account per case: registry versions are per capability, so cases must not share one.
        account = f"acct:tiktok-case-{index}"
        registry.record(
            capability(account=account, operations={CapabilityOperation.STATUS: support}),
            source_provenance=Provenance.FAKE_SYNTHETIC,
        )
        decision = registry.evaluate(
            platform=Platform.TIKTOK,
            account_ref=account,
            required={CapabilityOperation.STATUS},
        )
        assert decision.available is False
        messages.add(decision.blockers[0].split(": ", 1)[1])
    assert len(messages) == 3


@pytest.mark.parametrize("support", list(CapabilitySupport), ids=lambda s: s.value)
def test_only_supported_tested_passes(db: Database, support: CapabilitySupport) -> None:
    registry = _registry(db)
    registry.record(
        capability(operations={CapabilityOperation.STATUS: support}),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    decision = _evaluate(registry, required={CapabilityOperation.STATUS})
    assert decision.available is (support is CapabilitySupport.SUPPORTED_TESTED)


def test_an_operation_absent_from_the_record_is_unknown(db: Database) -> None:
    registry = _registry(db)
    registry.record(capability(), source_provenance=Provenance.FAKE_SYNTHETIC)
    decision = _evaluate(registry, required={CapabilityOperation.COVER_UPDATE})
    assert decision.available is False
    assert "COVER_UPDATE blocked, support is unknown" in decision.blockers[0]


def test_a_disabled_record_blocks(db: Database) -> None:
    registry = _registry(db)
    registry.record(
        capability(enabled=False, verified_at=None), source_provenance=Provenance.FAKE_SYNTHETIC
    )
    decision = _evaluate(registry)
    assert decision.available is False
    assert decision.record_version == 1
    assert decision.blockers[0].endswith("(fake-tiktok-route v1): disabled")


def test_missing_ai_disclosure_support_blocks(db: Database) -> None:
    registry = _registry(db)
    registry.record(
        capability(disclosures=(DisclosureKind.SYNTHETIC_VOICE,)),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    decision = _evaluate(registry, disclosures=AI)
    assert decision.available is False
    assert decision.blockers == [
        f"capability TIKTOK/{ACCOUNT} ({CAP_ROUTE} v1): disclosure AI_GENERATED_CONTENT is not supported"
    ]


def test_require_raises_with_blockers_in_details(db: Database) -> None:
    registry = _registry(db)
    registry.record(
        capability(operations={CapabilityOperation.SCHEDULE: CapabilitySupport.UNSUPPORTED}),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    with pytest.raises(CapabilityUnavailable) as caught:
        registry.require(platform=Platform.TIKTOK, account_ref=ACCOUNT, required=UPLOAD)
    assert caught.value.details["record_version"] == 1
    assert len(caught.value.details["blockers"]) == 1


def test_an_empty_operation_requirement_is_refused_not_cleared(db: Database) -> None:
    registry = _registry(db)
    registry.record(capability(), source_provenance=Provenance.FAKE_SYNTHETIC)
    with pytest.raises(SchemaInvalid):
        _evaluate(registry, required=set())


def test_invalid_platform_or_operation_is_refused(db: Database) -> None:
    registry = _registry(db)
    with pytest.raises(SchemaInvalid):
        _evaluate(registry, platform="MYSPACE")
    with pytest.raises(SchemaInvalid):
        _evaluate(registry, required={"TELEPORT"})


# --- versioning and current record ---------------------------------------------------


def test_a_new_version_supersedes_and_history_is_kept(db: Database) -> None:
    registry = _registry(db)
    registry.record(capability(version=1), source_provenance=Provenance.FAKE_SYNTHETIC)
    assert _evaluate(registry).available

    registry.record(
        capability(
            version=2, operations={CapabilityOperation.UPLOAD_SHORT: CapabilitySupport.UNSUPPORTED}
        ),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    decision = _evaluate(registry)
    assert decision.available is False
    assert decision.record_version == 2
    current = registry.current(Platform.TIKTOK, ACCOUNT)
    assert current is not None and current.version == 2
    assert count(db, "SELECT count(*) FROM capability_registry WHERE current") == 1
    assert count(db, "SELECT count(*) FROM capability_registry WHERE NOT current") == 1


def test_versions_must_strictly_increase(db: Database) -> None:
    registry = _registry(db)
    registry.record(capability(version=2), source_provenance=Provenance.FAKE_SYNTHETIC)
    with pytest.raises(Conflict):
        registry.record(capability(version=2), source_provenance=Provenance.FAKE_SYNTHETIC)
    with pytest.raises(Conflict):
        registry.record(capability(version=1), source_provenance=Provenance.FAKE_SYNTHETIC)


def test_current_returns_the_contract_record_unchanged(db: Database) -> None:
    registry = _registry(db)
    original = capability()
    registry.record(original, source_provenance=Provenance.FAKE_SYNTHETIC)
    assert registry.current(Platform.TIKTOK, ACCOUNT) == original


def test_current_is_none_for_an_unknown_account(db: Database) -> None:
    assert _registry(db).current(Platform.TIKTOK, "acct:nobody") is None


def test_a_future_verification_date_is_refused(db: Database) -> None:
    registry = _registry(db)
    with pytest.raises(SchemaInvalid):
        registry.record(
            capability(verified_at=T0 + timedelta(days=1)),
            source_provenance=Provenance.FAKE_SYNTHETIC,
        )


# --- routes ----------------------------------------------------------------------------


def test_two_current_routes_are_ambiguous_without_a_named_route(db: Database) -> None:
    registry = _registry(db)
    registry.record(capability(route="fake-route-a"), source_provenance=Provenance.FAKE_SYNTHETIC)
    registry.record(
        capability(
            route="fake-route-b",
            operations={CapabilityOperation.UPLOAD_SHORT: CapabilitySupport.UNSUPPORTED},
        ),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    ambiguous = _evaluate(registry)
    assert ambiguous.available is False
    assert "2 provider routes are current; name provider_route" in ambiguous.blockers[0]
    with pytest.raises(Conflict):
        registry.current(Platform.TIKTOK, ACCOUNT)

    named_a = _evaluate(registry, provider_route="fake-route-a")
    assert named_a.available is True
    named_b = _evaluate(registry, provider_route="fake-route-b")
    assert named_b.available is False


# --- evidence ------------------------------------------------------------------------------


def test_fake_only_evidence_blocks_outside_mock_only(db: Database) -> None:
    _registry(db).record(capability(), source_provenance=Provenance.FAKE_SYNTHETIC)
    assert _evaluate(_registry(db, mock_settings())).available is True
    live = _evaluate(_registry(db, live_settings()))
    assert live.available is False
    assert live.blockers == [f"fake evidence only: {CAP_ROUTE}/{ACCOUNT}"]


def test_real_evidence_is_available_with_live_settings(db: Database) -> None:
    registry = _registry(db, live_settings())
    registry.record(
        capability(evidence=[real_benchmark()]), source_provenance=Provenance.LIVE_PROVIDER
    )
    assert _evaluate(registry).available is True


def test_d3_refuses_a_real_source_label_on_fake_provenance(db: Database) -> None:
    registry = _registry(db)
    with pytest.raises(PolicyDenied):
        registry.record(
            capability(evidence=[real_benchmark()]), source_provenance=Provenance.FAKE_SYNTHETIC
        )
    assert count(db, "SELECT count(*) FROM capability_registry") == 0


def test_a_live_database_refuses_an_enabled_fake_route(db: Database) -> None:
    switch_runtime_mode(db, ExecutionMode.CONTROLLED_ACCOUNT_TEST)
    with pytest.raises(Unauthorized):
        _registry(db, live_settings()).record(
            capability(), source_provenance=Provenance.FAKE_SYNTHETIC
        )
    assert count(db, "SELECT count(*) FROM capability_registry") == 0


def test_a_live_database_accepts_an_enabled_route_with_real_evidence(db: Database) -> None:
    switch_runtime_mode(db, ExecutionMode.CONTROLLED_ACCOUNT_TEST)
    registry = _registry(db, live_settings())
    registry.record(
        capability(
            evidence=[
                EvidenceRef(source=EvidenceSource.CONTROLLED_ACCOUNT_TEST, ref="controlled-test-42")
            ]
        ),
        source_provenance=Provenance.LIVE_PROVIDER,
    )
    assert _evaluate(registry).available is True


def test_a_disabled_route_without_evidence_is_stored_and_blocked(db: Database) -> None:
    registry = _registry(db)
    registry.record(
        capability(enabled=False, verified_at=None, evidence=[]),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    assert _evaluate(registry).available is False
    assert count(db, "SELECT count(*) FROM capability_registry WHERE enabled") == 0
