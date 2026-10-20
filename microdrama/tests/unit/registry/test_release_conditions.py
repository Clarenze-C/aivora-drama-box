"""AT-13 release conditions: rights and capability blockers survive a green QA result; optional
destinations hold only themselves; every blocker is returned together."""

from __future__ import annotations

from datetime import timedelta

import pytest
from registry_support import (
    ACCOUNT,
    CAP_ROUTE,
    ROUTE,
    T0,
    VOICE_REF,
    capability,
    fixed_clock,
    live_settings,
    mock_settings,
    real_license,
    rights,
)

from microdrama.contracts.enums import (
    CapabilityOperation,
    CapabilitySupport,
    DisclosureKind,
    EvidenceSource,
    Platform,
    Provenance,
    RightsStatus,
    RightsSubjectKind,
)
from microdrama.contracts.errors import SchemaInvalid
from microdrama.contracts.primitives import EvidenceRef
from microdrama.core.registry import (
    CapabilityRegistry,
    DestinationRequirement,
    RightsRegistry,
    evaluate_release_conditions,
)
from microdrama.core.registry.release_conditions import QA_BLOCKER
from microdrama.persistence import Database

pytestmark = pytest.mark.db

VOICE = [(RightsSubjectKind.VOICE, VOICE_REF)]
TERRITORIES = ["TH"]
AI = frozenset({DisclosureKind.AI_GENERATED_CONTENT})
UPLOAD = frozenset({CapabilityOperation.UPLOAD_SHORT, CapabilityOperation.SCHEDULE})
TIKTOK = DestinationRequirement(
    platform=Platform.TIKTOK,
    account_ref=ACCOUNT,
    required_ops=UPLOAD,
    disclosures=AI,
    required=True,
)
YOUTUBE_ACCOUNT = "acct:youtube-main"


def _gate(db: Database, settings=None) -> tuple[RightsRegistry, CapabilityRegistry]:
    chosen = settings or mock_settings()
    return (
        RightsRegistry(db, fixed_clock(), chosen),
        CapabilityRegistry(db, fixed_clock(), chosen),
    )


def _release(
    db: Database,
    *,
    destinations: list[DestinationRequirement] | None = None,
    qa_all_green: bool,
    at=T0,
    settings=None,
) -> list[str]:
    rights_registry, capability_registry = _gate(db, settings)
    return evaluate_release_conditions(
        rights=rights_registry,
        capabilities=capability_registry,
        rights_route_id=ROUTE,
        rights_subjects=VOICE,
        territories=TERRITORIES,
        destinations=[TIKTOK] if destinations is None else destinations,
        at=at,
        qa_all_green=qa_all_green,
    )


def _clear_rights(db: Database) -> None:
    RightsRegistry(db, fixed_clock(), mock_settings()).record(
        rights(), source_provenance=Provenance.FAKE_SYNTHETIC
    )


def _clear_capability(db: Database) -> None:
    CapabilityRegistry(db, fixed_clock(), mock_settings()).record(
        capability(), source_provenance=Provenance.FAKE_SYNTHETIC
    )


def test_green_qa_does_not_clear_an_unknown_rights_route(db: Database) -> None:
    _clear_capability(db)
    blockers = _release(db, qa_all_green=True)
    assert blockers == [f"rights unknown: no current record for {ROUTE}/{VOICE_REF}"]


def test_qa_failure_adds_its_own_blocker_on_top_of_rights(db: Database) -> None:
    _clear_capability(db)
    blockers = _release(db, qa_all_green=False)
    assert blockers == [
        f"rights unknown: no current record for {ROUTE}/{VOICE_REF}",
        QA_BLOCKER,
    ]


def test_green_qa_does_not_clear_a_documentation_only_operation(db: Database) -> None:
    _clear_rights(db)
    CapabilityRegistry(db, fixed_clock(), mock_settings()).record(
        capability(
            operations={CapabilityOperation.SCHEDULE: CapabilitySupport.SUPPORTED_DOCUMENTED}
        ),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    blockers = _release(db, qa_all_green=True)
    assert len(blockers) == 1
    assert "SCHEDULE blocked, support is documented only, not tested" in blockers[0]


def test_green_qa_does_not_clear_a_missing_ai_disclosure(db: Database) -> None:
    _clear_rights(db)
    CapabilityRegistry(db, fixed_clock(), mock_settings()).record(
        capability(disclosures=(DisclosureKind.SYNTHETIC_VOICE,)),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    blockers = _release(db, qa_all_green=True)
    assert blockers == [
        f"capability TIKTOK/{ACCOUNT} ({CAP_ROUTE} v1): disclosure AI_GENERATED_CONTENT is not supported"
    ]


def test_a_disclosure_the_route_requires_must_be_made_by_the_destination(db: Database) -> None:
    """MD-015: the rights record requires SYNTHETIC_VOICE; a destination that cannot make it holds
    the route, even with green QA."""
    _clear_rights(db)
    CapabilityRegistry(db, fixed_clock(), mock_settings()).record(
        capability(disclosures=(DisclosureKind.AI_GENERATED_CONTENT,)),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    blockers = _release(db, qa_all_green=True)
    assert blockers == [
        f"capability TIKTOK/{ACCOUNT} ({CAP_ROUTE} v1): disclosure SYNTHETIC_VOICE is not supported"
    ]


def test_expired_rights_still_block_on_the_release_day(db: Database) -> None:
    RightsRegistry(db, fixed_clock(), mock_settings()).record(
        rights(expires=T0 + timedelta(days=1)), source_provenance=Provenance.FAKE_SYNTHETIC
    )
    _clear_capability(db)
    blockers = _release(db, qa_all_green=True, at=T0 + timedelta(days=2))
    assert len(blockers) == 1
    assert blockers[0].startswith("rights expired at ")


def test_everything_clear_with_green_qa_releases(db: Database) -> None:
    _clear_rights(db)
    _clear_capability(db)
    assert _release(db, qa_all_green=True) == []


def test_all_blockers_are_returned_together(db: Database) -> None:
    blockers = _release(db, qa_all_green=False)
    assert blockers == [
        f"rights unknown: no current record for {ROUTE}/{VOICE_REF}",
        f"capability TIKTOK/{ACCOUNT}: no current record",
        QA_BLOCKER,
    ]


def test_an_optional_destination_holds_only_itself(db: Database) -> None:
    _clear_rights(db)
    _clear_capability(db)
    optional_youtube = DestinationRequirement(
        platform=Platform.YOUTUBE,
        account_ref=YOUTUBE_ACCOUNT,
        required_ops=frozenset({CapabilityOperation.UPLOAD_FULL_VIDEO}),
        disclosures=AI,
        required=False,
    )
    blockers = _release(db, destinations=[TIKTOK, optional_youtube], qa_all_green=True)
    assert blockers == [f"optional: capability YOUTUBE/{YOUTUBE_ACCOUNT}: no current record"]


def test_a_required_destination_blocker_is_not_prefixed(db: Database) -> None:
    _clear_rights(db)
    required_youtube = DestinationRequirement(
        platform=Platform.YOUTUBE,
        account_ref=YOUTUBE_ACCOUNT,
        required_ops=frozenset({CapabilityOperation.UPLOAD_FULL_VIDEO}),
        disclosures=AI,
        required=True,
    )
    blockers = _release(db, destinations=[TIKTOK, required_youtube], qa_all_green=True)
    assert all(not blocker.startswith("optional:") for blocker in blockers)
    assert f"capability YOUTUBE/{YOUTUBE_ACCOUNT}: no current record" in blockers


def test_fake_rights_and_routes_block_with_live_settings_even_when_qa_is_green(
    db: Database,
) -> None:
    _clear_rights(db)
    _clear_capability(db)
    blockers = _release(db, qa_all_green=True, settings=live_settings())
    assert blockers == [
        f"fake evidence only: {ROUTE}/{VOICE_REF}",
        f"fake evidence only: {CAP_ROUTE}/{ACCOUNT}",
    ]


def test_real_rights_and_a_real_route_release_with_live_settings(db: Database) -> None:
    live_rights = RightsRegistry(db, fixed_clock(), live_settings())
    live_rights.record(rights(evidence=[real_license()]), source_provenance=Provenance.LICENSED)
    live_capability = CapabilityRegistry(db, fixed_clock(), live_settings())
    live_capability.record(
        capability(
            evidence=[
                EvidenceRef(source=EvidenceSource.CONTROLLED_ACCOUNT_TEST, ref="controlled-test-42")
            ]
        ),
        source_provenance=Provenance.LIVE_PROVIDER,
    )
    assert _release(db, qa_all_green=True, settings=live_settings()) == []


def test_a_release_names_at_least_one_destination(db: Database) -> None:
    with pytest.raises(SchemaInvalid):
        _release(db, destinations=[], qa_all_green=True)


def test_qa_must_be_a_boolean(db: Database) -> None:
    with pytest.raises(SchemaInvalid):
        _release(db, qa_all_green="yes")  # type: ignore[arg-type]


def test_a_destination_names_only_known_contract_values() -> None:
    with pytest.raises(SchemaInvalid):
        DestinationRequirement(
            platform="MYSPACE",  # type: ignore[arg-type]
            account_ref=ACCOUNT,
            required_ops=frozenset(),
            disclosures=frozenset(),
            required=True,
        )
    with pytest.raises(SchemaInvalid):
        DestinationRequirement(
            platform=Platform.TIKTOK,
            account_ref="tiktok-main",  # not an acct: reference
            required_ops=frozenset(),
            disclosures=frozenset(),
            required=True,
        )


def test_an_expired_status_row_blocks_the_gate_despite_green_qa(db: Database) -> None:
    registry = RightsRegistry(db, fixed_clock(), mock_settings())
    registry.record(
        rights(status=RightsStatus.EXPIRED, commercial=None, output=None, expires=None),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    _clear_capability(db)
    blockers = _release(db, qa_all_green=True)
    assert blockers == [f"rights expired: {ROUTE}/{VOICE_REF}"]
