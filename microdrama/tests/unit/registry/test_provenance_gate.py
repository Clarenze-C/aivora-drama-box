"""V-9: the application gate on real evidence labels, for every Provenance and every writer.

A real source (OFFICIAL_DOCUMENTATION, CONTROLLED_ACCOUNT_TEST, MEASURED_BENCHMARK,
LICENSE_DOCUMENT) is accepted only with LIVE_PROVIDER or LICENSED provenance. Any other provenance
is refused with PolicyDenied and nothing is written. The database trusts the label it is given
(D3), so this gate is the only check on it.
"""

from __future__ import annotations

import pytest
from registry_support import (
    FAKE_EVIDENCE,
    capability,
    count,
    fixed_clock,
    live_settings,
    mock_settings,
    preset,
    real_license,
    rights,
)

from microdrama.contracts.enums import EvidenceSource, Provenance
from microdrama.contracts.errors import PolicyDenied
from microdrama.contracts.primitives import EvidenceRef
from microdrama.core.registry import CapabilityRegistry, PresetRegistry, RightsRegistry
from microdrama.persistence import Database

pytestmark = pytest.mark.db

REAL_SOURCES = [
    EvidenceSource.OFFICIAL_DOCUMENTATION,
    EvidenceSource.CONTROLLED_ACCOUNT_TEST,
    EvidenceSource.MEASURED_BENCHMARK,
    EvidenceSource.LICENSE_DOCUMENT,
]
ACCEPTED = frozenset({Provenance.LIVE_PROVIDER, Provenance.LICENSED})
WRITERS = ["rights", "capability", "preset"]
TABLES = {
    "rights": "rights_registry",
    "capability": "capability_registry",
    "preset": "preset_registry",
}


def _evidence(source: EvidenceSource) -> list[EvidenceRef]:
    # Capability records that test operations need CONTROLLED_ACCOUNT_TEST or FAKE_FIXTURE
    # evidence (contract 1.3.0), so a real non-controlled source is paired with a fixture here.
    # The gate looks at the real label either way.
    return [EvidenceRef(source=source, ref=f"unit:{source.value.lower()}")]


def _write(writer: str, db: Database, provenance: Provenance, evidence: list[EvidenceRef]) -> None:
    if writer == "rights":
        RightsRegistry(db, fixed_clock(), mock_settings()).record(
            rights(evidence=evidence), source_provenance=provenance
        )
    elif writer == "capability":
        has_fixture = any(item.source is EvidenceSource.FAKE_FIXTURE for item in evidence)
        capability_evidence = evidence if has_fixture else evidence + [FAKE_EVIDENCE]
        CapabilityRegistry(db, fixed_clock(), mock_settings()).record(
            capability(evidence=capability_evidence), source_provenance=provenance
        )
    else:
        PresetRegistry(db, mock_settings()).record(
            preset(evidence=evidence), source_provenance=provenance
        )


@pytest.mark.parametrize("writer", WRITERS)
@pytest.mark.parametrize("provenance", list(Provenance), ids=lambda p: p.value)
@pytest.mark.parametrize("source", REAL_SOURCES, ids=lambda s: s.value)
def test_a_real_evidence_label_is_accepted_only_from_live_or_licensed_provenance(
    db: Database, writer: str, provenance: Provenance, source: EvidenceSource
) -> None:
    table = TABLES[writer]
    if provenance in ACCEPTED:
        _write(writer, db, provenance, _evidence(source))
        assert count(db, f"SELECT count(*) FROM {table}") == 1
        return
    with pytest.raises(PolicyDenied) as caught:
        _write(writer, db, provenance, _evidence(source))
    assert count(db, f"SELECT count(*) FROM {table}") == 0
    assert provenance.value in caught.value.message
    assert source.value in caught.value.message


@pytest.mark.parametrize("writer", WRITERS)
@pytest.mark.parametrize("provenance", list(Provenance), ids=lambda p: p.value)
def test_fixture_evidence_is_recorded_under_any_provenance_and_stays_mock_only(
    db: Database, writer: str, provenance: Provenance
) -> None:
    """The gate restricts real labels only. FAKE_FIXTURE evidence is recorded and is blocked
    outside OFFLINE_MOCK by the evaluators (see the capability and rights tests)."""
    _write(writer, db, provenance, [FAKE_EVIDENCE])
    assert count(db, f"SELECT count(*) FROM {TABLES[writer]}") == 1


@pytest.mark.parametrize("provenance", [Provenance.ORIGINAL_FIXTURE, Provenance.DERIVED_LOCAL])
def test_fixture_or_derived_data_cannot_clear_rights_under_live_settings(
    db: Database, provenance: Provenance
) -> None:
    """The scenario that reached live clearance before V-9: local fixture data carrying a licence
    label. The record is refused, so live evaluation finds no record and stays UNKNOWN."""
    with pytest.raises(PolicyDenied):
        RightsRegistry(db, fixed_clock(), mock_settings()).record(
            rights(evidence=[real_license()]), source_provenance=provenance
        )
    decision = RightsRegistry(db, fixed_clock(), live_settings()).evaluate(
        rights_route_id="route-voice-th",
        subjects=[("VOICE", "voice-th-01")],
        territories=["TH"],
    )
    assert decision.eligible is False
    assert decision.blockers == ["rights unknown: no current record for route-voice-th/voice-th-01"]


@pytest.mark.parametrize("provenance", [Provenance.ORIGINAL_FIXTURE, Provenance.DERIVED_LOCAL])
def test_fixture_or_derived_data_cannot_clear_a_route_under_live_settings(
    db: Database, provenance: Provenance
) -> None:
    with pytest.raises(PolicyDenied):
        CapabilityRegistry(db, fixed_clock(), mock_settings()).record(
            capability(
                evidence=[EvidenceRef(source=EvidenceSource.CONTROLLED_ACCOUNT_TEST, ref="x")]
            ),
            source_provenance=provenance,
        )
    decision = CapabilityRegistry(db, fixed_clock(), live_settings()).evaluate(
        platform="TIKTOK",
        account_ref="acct:tiktok-main",
        required={"UPLOAD_SHORT"},
    )
    assert decision.available is False
    assert decision.record_version is None


def test_a_refused_new_version_leaves_the_current_version_untouched(db: Database) -> None:
    """The gate runs before any write, so a refused version does not retire the current one."""
    rights_registry = RightsRegistry(db, fixed_clock(), mock_settings())
    rights_registry.record(rights(version=1), source_provenance=Provenance.FAKE_SYNTHETIC)
    with pytest.raises(PolicyDenied):
        rights_registry.record(
            rights(version=2, evidence=[real_license()]),
            source_provenance=Provenance.ORIGINAL_FIXTURE,
        )
    with db.transaction(readonly=True) as tx:
        rows = tx.fetchall("SELECT version, current FROM rights_registry ORDER BY version")
    assert [(row["version"], row["current"]) for row in rows] == [(1, True)]
