"""Rights registry on the real database: UNKNOWN vs INELIGIBLE vs ELIGIBLE vs EXPIRED, coverage,
versioning, fake-only evidence and the D3 refusal."""

from __future__ import annotations

from datetime import timedelta

import pytest
from registry_support import (
    ROUTE,
    T0,
    VOICE_REF,
    count,
    fixed_clock,
    live_settings,
    mock_settings,
    real_license,
    rights,
    switch_runtime_mode,
)

from microdrama.config import Settings
from microdrama.contracts.enums import (
    DisclosureKind,
    EvidenceSource,
    ExecutionMode,
    Provenance,
    RightsStatus,
    RightsSubjectKind,
)
from microdrama.contracts.errors import (
    Conflict,
    PolicyDenied,
    RightsUncleared,
    SchemaInvalid,
    Unauthorized,
)
from microdrama.contracts.primitives import EvidenceRef
from microdrama.core.registry import RightsRegistry
from microdrama.persistence import Database

pytestmark = pytest.mark.db

VOICE = [(RightsSubjectKind.VOICE, VOICE_REF)]


def _registry(db: Database, settings: Settings | None = None) -> RightsRegistry:
    return RightsRegistry(db, fixed_clock(), settings or mock_settings())


def _decide(
    registry: RightsRegistry,
    *,
    territories: list[str] | None = None,
    at=None,
    subjects=None,
):
    return registry.evaluate(
        rights_route_id=ROUTE,
        subjects=VOICE if subjects is None else subjects,
        territories=["TH"] if territories is None else territories,
        at=at,
    )


# --- unknown, ineligible, eligible ----------------------------------------------------


def test_no_record_is_unknown_and_blocks(db: Database) -> None:
    decision = _decide(_registry(db))
    assert decision.status is RightsStatus.UNKNOWN
    assert decision.eligible is False
    assert decision.blockers == [f"rights unknown: no current record for {ROUTE}/{VOICE_REF}"]


def test_an_ineligible_record_blocks_and_require_cleared_raises_with_blockers(db: Database) -> None:
    registry = _registry(db)
    registry.record(
        rights(status=RightsStatus.INELIGIBLE, commercial=False, output=False, expires=None),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    decision = _decide(registry)
    assert decision.status is RightsStatus.INELIGIBLE
    assert decision.blockers == [f"rights ineligible: {ROUTE}/{VOICE_REF}"]
    with pytest.raises(RightsUncleared) as caught:
        registry.require_cleared(rights_route_id=ROUTE, subjects=VOICE, territories=["TH"])
    assert caught.value.details["blockers"] == [f"rights ineligible: {ROUTE}/{VOICE_REF}"]
    assert caught.value.details["status"] == "INELIGIBLE"


def test_an_unknown_status_record_blocks_like_ineligible(db: Database) -> None:
    registry = _registry(db)
    registry.record(
        rights(status=RightsStatus.UNKNOWN, commercial=None, output=None, expires=None),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    decision = _decide(registry)
    assert decision.status is RightsStatus.UNKNOWN
    assert not decision.eligible


def test_an_eligible_record_clears_and_require_cleared_returns_the_decision(db: Database) -> None:
    registry = _registry(db)
    registry.record(rights(), source_provenance=Provenance.FAKE_SYNTHETIC)
    decision = _decide(registry)
    assert decision.status is RightsStatus.ELIGIBLE
    assert decision.blockers == []
    assert decision.eligible is True
    cleared = registry.require_cleared(rights_route_id=ROUTE, subjects=VOICE, territories=["TH"])
    assert cleared.eligible is True


@pytest.mark.parametrize("status", list(RightsStatus), ids=lambda s: s.value)
def test_only_an_eligible_status_clears(db: Database, status: RightsStatus) -> None:
    """Every RightsStatus member: only ELIGIBLE can ever clear a route."""
    registry = _registry(db)
    eligible = status is RightsStatus.ELIGIBLE
    registry.record(
        rights(
            status=status,
            commercial=True if eligible else None,
            output=True if eligible else None,
            expires=T0 + timedelta(days=30) if eligible else None,
        ),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    decision = _decide(registry)
    assert decision.eligible is eligible


# --- expiry boundary -----------------------------------------------------------------


def test_expiry_is_exact_at_the_boundary(db: Database) -> None:
    expires = T0 + timedelta(days=365)
    registry = _registry(db)
    registry.record(rights(expires=expires), source_provenance=Provenance.FAKE_SYNTHETIC)

    just_before = _decide(registry, at=expires - timedelta(microseconds=1))
    assert just_before.status is RightsStatus.ELIGIBLE

    exactly_at = _decide(registry, at=expires)
    assert exactly_at.status is RightsStatus.EXPIRED
    assert exactly_at.blockers == [f"rights expired at {expires.isoformat()}: {ROUTE}/{VOICE_REF}"]

    after = _decide(registry, at=expires + timedelta(days=1))
    assert after.status is RightsStatus.EXPIRED


def test_an_expired_status_row_is_expired_not_unknown(db: Database) -> None:
    registry = _registry(db)
    registry.record(
        rights(status=RightsStatus.EXPIRED, commercial=None, output=None, expires=None),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    assert _decide(registry).status is RightsStatus.EXPIRED


def test_evaluation_clock_defaults_to_the_injected_clock(db: Database) -> None:
    clock = fixed_clock()
    registry = RightsRegistry(db, clock, mock_settings())
    registry.record(
        rights(expires=T0 + timedelta(hours=1)), source_provenance=Provenance.FAKE_SYNTHETIC
    )
    assert _decide(registry).status is RightsStatus.ELIGIBLE
    clock.advance(seconds=3600)
    assert _decide(registry).status is RightsStatus.EXPIRED


def test_a_naive_evaluation_instant_is_refused(db: Database) -> None:
    registry = _registry(db)
    registry.record(rights(), source_provenance=Provenance.FAKE_SYNTHETIC)
    with pytest.raises(SchemaInvalid):
        _decide(registry, at=T0.replace(tzinfo=None))


# --- territories -----------------------------------------------------------------------


def test_territory_coverage_is_checked_for_every_target(db: Database) -> None:
    registry = _registry(db)
    registry.record(rights(territories=("TH", "US")), source_provenance=Provenance.FAKE_SYNTHETIC)
    assert _decide(registry, territories=["TH"]).eligible
    assert _decide(registry, territories=["TH", "US"]).eligible

    uncovered = _decide(registry, territories=["TH", "JP"])
    assert uncovered.status is RightsStatus.INELIGIBLE
    assert uncovered.blockers == [f"territory not covered: {ROUTE}/{VOICE_REF} lacks JP"]


def test_worldwide_covers_every_territory(db: Database) -> None:
    registry = _registry(db)
    registry.record(rights(territories=("WORLDWIDE",)), source_provenance=Provenance.FAKE_SYNTHETIC)
    assert _decide(registry, territories=["JP", "TH", "BR"]).eligible


def test_a_worldwide_request_is_not_covered_by_named_territories(db: Database) -> None:
    registry = _registry(db)
    registry.record(rights(territories=("TH",)), source_provenance=Provenance.FAKE_SYNTHETIC)
    decision = _decide(registry, territories=["WORLDWIDE"])
    assert decision.status is RightsStatus.INELIGIBLE
    assert decision.blockers == [f"territory not covered: {ROUTE}/{VOICE_REF} lacks WORLDWIDE"]


@pytest.mark.parametrize("bad", [[], ["Thailand"], ["th"], ["WORLD"]])
def test_malformed_or_empty_territories_are_refused(db: Database, bad: list[str]) -> None:
    registry = _registry(db)
    registry.record(rights(), source_provenance=Provenance.FAKE_SYNTHETIC)
    with pytest.raises(SchemaInvalid):
        _decide(registry, territories=bad)


def test_empty_subjects_are_refused(db: Database) -> None:
    registry = _registry(db)
    with pytest.raises(SchemaInvalid):
        _decide(registry, subjects=[])


def test_every_required_subject_must_clear(db: Database) -> None:
    registry = _registry(db)
    registry.record(rights(), source_provenance=Provenance.FAKE_SYNTHETIC)
    two = [(RightsSubjectKind.VOICE, VOICE_REF), (RightsSubjectKind.MUSIC, "track-07")]
    decision = _decide(registry, subjects=two)
    assert decision.status is RightsStatus.UNKNOWN
    assert decision.blockers == [f"rights unknown: no current record for {ROUTE}/track-07"]


# --- versioning ------------------------------------------------------------------------


def test_a_new_version_supersedes_the_previous_one(db: Database) -> None:
    registry = _registry(db)
    registry.record(rights(version=1), source_provenance=Provenance.FAKE_SYNTHETIC)
    assert _decide(registry).eligible

    registry.record(
        rights(
            version=2, status=RightsStatus.INELIGIBLE, commercial=False, output=False, expires=None
        ),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    assert _decide(registry).status is RightsStatus.INELIGIBLE

    with db.transaction(readonly=True) as tx:
        rows = tx.fetchall(
            "SELECT version, current FROM rights_registry WHERE rights_route_id = %s ORDER BY version",
            (ROUTE,),
        )
    assert [(row["version"], row["current"]) for row in rows] == [(1, False), (2, True)]


def test_versions_must_strictly_increase(db: Database) -> None:
    registry = _registry(db)
    registry.record(rights(version=2), source_provenance=Provenance.FAKE_SYNTHETIC)
    with pytest.raises(Conflict):
        registry.record(rights(version=2), source_provenance=Provenance.FAKE_SYNTHETIC)
    with pytest.raises(Conflict):
        registry.record(rights(version=1), source_provenance=Provenance.FAKE_SYNTHETIC)
    assert count(db, "SELECT count(*) FROM rights_registry WHERE current") == 1


def test_a_record_dated_in_the_future_is_refused(db: Database) -> None:
    registry = _registry(db)
    with pytest.raises(SchemaInvalid):
        registry.record(
            rights(recorded_at=T0 + timedelta(days=1)), source_provenance=Provenance.FAKE_SYNTHETIC
        )


# --- evidence: fake-only, D3, live database ----------------------------------------------


def test_fake_only_evidence_is_eligible_in_mock_but_unknown_with_live_settings(
    db: Database,
) -> None:
    _registry(db).record(rights(), source_provenance=Provenance.FAKE_SYNTHETIC)
    assert _decide(_registry(db, mock_settings())).status is RightsStatus.ELIGIBLE

    live = _decide(_registry(db, live_settings()))
    assert live.status is RightsStatus.UNKNOWN
    assert live.blockers == [f"fake evidence only: {ROUTE}/{VOICE_REF}"]


def test_real_evidence_clears_with_live_settings(db: Database) -> None:
    registry = _registry(db, live_settings())
    registry.record(rights(evidence=[real_license()]), source_provenance=Provenance.LICENSED)
    assert _decide(registry).eligible


def test_d3_refuses_a_real_source_label_on_fake_provenance(db: Database) -> None:
    registry = _registry(db)
    for source in (
        EvidenceSource.LICENSE_DOCUMENT,
        EvidenceSource.OFFICIAL_DOCUMENTATION,
        EvidenceSource.CONTROLLED_ACCOUNT_TEST,
        EvidenceSource.MEASURED_BENCHMARK,
    ):
        with pytest.raises(PolicyDenied):
            registry.record(
                rights(evidence=[EvidenceRef(source=source, ref="claimed-real")]),
                source_provenance=Provenance.FAKE_SYNTHETIC,
            )
    assert count(db, "SELECT count(*) FROM rights_registry") == 0


def test_a_live_database_refuses_an_active_fake_only_row(db: Database) -> None:
    switch_runtime_mode(db, ExecutionMode.CONTROLLED_ACCOUNT_TEST)
    registry = _registry(db, live_settings())
    with pytest.raises(Unauthorized):
        registry.record(rights(), source_provenance=Provenance.FAKE_SYNTHETIC)
    assert count(db, "SELECT count(*) FROM rights_registry") == 0


def test_a_live_database_accepts_an_inactive_fake_row(db: Database) -> None:
    switch_runtime_mode(db, ExecutionMode.CONTROLLED_ACCOUNT_TEST)
    registry = _registry(db, live_settings())
    registry.record(
        rights(status=RightsStatus.INELIGIBLE, commercial=None, output=None, expires=None),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    # Outside OFFLINE_MOCK, fake-only evidence is UNKNOWN before the stored status is read.
    decision = _decide(registry)
    assert decision.status is RightsStatus.UNKNOWN
    assert decision.blockers == [f"fake evidence only: {ROUTE}/{VOICE_REF}"]


def test_the_database_refuses_to_leave_mock_while_fake_eligible_rows_exist(db: Database) -> None:
    _registry(db).record(rights(), source_provenance=Provenance.FAKE_SYNTHETIC)
    with pytest.raises(Unauthorized):
        switch_runtime_mode(db, ExecutionMode.CONTROLLED_ACCOUNT_TEST)


def test_a_live_database_evaluates_real_rights_end_to_end(db: Database) -> None:
    switch_runtime_mode(db, ExecutionMode.CONTROLLED_ACCOUNT_TEST)
    registry = _registry(db, live_settings())
    registry.record(rights(evidence=[real_license()]), source_provenance=Provenance.LICENSED)
    assert _decide(registry).eligible
    assert _decide(registry, at=T0 + timedelta(days=366)).status is RightsStatus.EXPIRED


def test_required_disclosures_come_from_the_current_records(db: Database) -> None:
    registry = _registry(db)
    assert registry.required_disclosures(rights_route_id=ROUTE, subjects=VOICE) == frozenset()
    registry.record(rights(), source_provenance=Provenance.FAKE_SYNTHETIC)
    assert registry.required_disclosures(rights_route_id=ROUTE, subjects=VOICE) == frozenset(
        {DisclosureKind.SYNTHETIC_VOICE}
    )
    registry.record(
        rights(version=2, status=RightsStatus.EXPIRED, commercial=None, output=None, expires=None),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    # The current version decides: a superseded record's disclosures no longer apply.
    assert registry.required_disclosures(rights_route_id=ROUTE, subjects=VOICE) == frozenset(
        {DisclosureKind.SYNTHETIC_VOICE}
    )


# --- tampering: read-time revalidation (V-33, V-35) -------------------------------------


def _replica_bypass(db: Database, sql: str, params: tuple) -> None:
    """An owner-level SQL edit that bypasses the immutability triggers (CHECKs still hold)."""
    with db.transaction() as tx:
        tx.execute("SET LOCAL session_replication_role = replica")
        tx.execute(sql, params)


_FLIP_CURRENT = (
    "UPDATE rights_registry SET status = 'ELIGIBLE', commercial_use = true, "
    "output_release_allowed = true WHERE rights_route_id = %s AND subject_kind = %s "
    "AND subject_ref = %s AND current"
)
_CURRENT_ROW = (ROUTE, RightsSubjectKind.VOICE.value, VOICE_REF)


def test_a_replica_bypass_flip_to_eligible_fails_closed(db: Database) -> None:
    """V-33: rights rows are revalidated on every read. A trigger-bypassing owner session that
    flips an INELIGIBLE row and its decision columns to ELIGIBLE never reads back as eligible."""
    registry = RightsRegistry(db, fixed_clock(), live_settings())
    registry.record(
        rights(
            status=RightsStatus.INELIGIBLE,
            commercial=False,
            output=False,
            expires=T0 + timedelta(days=365),
            evidence=[real_license()],
        ),
        source_provenance=Provenance.LICENSED,
    )
    assert _decide(registry).status is RightsStatus.INELIGIBLE
    _replica_bypass(db, _FLIP_CURRENT, _CURRENT_ROW)

    decision = _decide(registry)
    assert decision.eligible is False
    assert decision.status is RightsStatus.UNKNOWN
    assert decision.blockers == [f"rights record fails integrity revalidation: {ROUTE}/{VOICE_REF}"]
    with pytest.raises(RightsUncleared):
        registry.require_cleared(rights_route_id=ROUTE, subjects=VOICE, territories=["TH"])


def test_a_replica_bypass_edit_of_a_decision_column_raises_on_disclosure_reads(
    db: Database,
) -> None:
    """V-33: any stored decision column edit (expires_at alone here; the ELIGIBLE CHECK leaves
    nothing else loose) breaks the re-derived row id: reads refuse the row instead of returning
    the edited record."""
    registry = _registry(db)
    registry.record(rights(), source_provenance=Provenance.FAKE_SYNTHETIC)
    _replica_bypass(
        db,
        "UPDATE rights_registry SET expires_at = '2031-10-20T00:00:00Z' "
        "WHERE rights_route_id = %s AND subject_kind = %s AND subject_ref = %s AND current",
        _CURRENT_ROW,
    )
    with pytest.raises(Conflict):
        registry.required_disclosures(rights_route_id=ROUTE, subjects=VOICE)
    decision = _decide(registry)
    assert decision.eligible is False and decision.status is RightsStatus.UNKNOWN


def test_a_corrupted_required_disclosures_value_is_a_typed_schema_error(db: Database) -> None:
    """V-35: required_disclosures never leaks a raw ValueError out of the release path when a
    stored disclosure string no longer decodes."""
    registry = _registry(db)
    registry.record(rights(), source_provenance=Provenance.FAKE_SYNTHETIC)
    _replica_bypass(
        db,
        "UPDATE rights_registry SET required_disclosures = '[\"GARBAGE\"]'::jsonb "
        "WHERE rights_route_id = %s AND subject_kind = %s AND subject_ref = %s AND current",
        _CURRENT_ROW,
    )
    with pytest.raises(SchemaInvalid):
        registry.required_disclosures(rights_route_id=ROUTE, subjects=VOICE)
