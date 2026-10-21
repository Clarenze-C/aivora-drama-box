"""Preset registry on the real database: compatible() never drops a required control; disabled and
unmeasured presets are never selectable; fake-only presets are excluded outside OFFLINE_MOCK."""

from __future__ import annotations

import pytest
from registry_support import (
    PRESET_ID,
    count,
    live_settings,
    mock_settings,
    preset,
    switch_runtime_mode,
)

from microdrama.contracts.enums import ControlKind, EvidenceSource, ExecutionMode, Provenance
from microdrama.contracts.errors import Conflict, PolicyDenied, SchemaInvalid, Unauthorized
from microdrama.contracts.primitives import EvidenceRef
from microdrama.core.registry import PresetRegistry
from microdrama.persistence import Database

pytestmark = pytest.mark.db

TEXT = ControlKind.TEXT_PROMPT
FIRST = ControlKind.FIRST_FRAME
CHARACTER = ControlKind.CHARACTER_REFERENCE
SEED = ControlKind.SEED


def _registry(db: Database, settings=None) -> PresetRegistry:
    return PresetRegistry(db, settings or mock_settings())


def _ids(presets) -> list[str]:
    return [item.preset_id for item in presets]


def test_compatible_returns_only_presets_with_every_required_control(db: Database) -> None:
    registry = _registry(db)
    registry.record(
        preset(preset_id="fake-full", controls=(TEXT, FIRST, CHARACTER)),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    registry.record(
        preset(preset_id="fake-text-only", controls=(TEXT,)),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    assert _ids(registry.compatible({TEXT, FIRST})) == ["fake-full"]
    assert _ids(registry.compatible({TEXT})) == ["fake-full", "fake-text-only"]


def test_empty_required_controls_are_a_caller_bug_not_a_pass_all(db: Database) -> None:
    """V-36: compatible([]) would return every enabled preset — a caller bug, not clearance,
    matching CapabilityRegistry.evaluate's refusal of an empty operation set."""
    registry = _registry(db)
    registry.record(preset(), source_provenance=Provenance.FAKE_SYNTHETIC)
    with pytest.raises(SchemaInvalid):
        registry.compatible([])
    with pytest.raises(SchemaInvalid):
        registry.compatible(set())


def test_no_preset_is_returned_when_a_required_control_is_missing_everywhere(db: Database) -> None:
    registry = _registry(db)
    registry.record(
        preset(controls=(TEXT, FIRST, CHARACTER)), source_provenance=Provenance.FAKE_SYNTHETIC
    )
    assert registry.compatible({TEXT, SEED}) == []


def test_an_unknown_control_name_is_refused_not_dropped(db: Database) -> None:
    registry = _registry(db)
    registry.record(preset(), source_provenance=Provenance.FAKE_SYNTHETIC)
    with pytest.raises(SchemaInvalid):
        registry.compatible({"TELEPORT"})


def test_disabled_presets_are_never_returned_but_remain_readable(db: Database) -> None:
    registry = _registry(db)
    registry.record(
        preset(enabled=False, measured=False, evidence=[]),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    assert registry.enabled() == []
    assert registry.compatible({TEXT}) == []
    current = registry.get(PRESET_ID)
    assert current is not None and current.enabled is False and current.measured is None


def test_a_new_version_supersedes_and_retires_the_old_selection(db: Database) -> None:
    registry = _registry(db)
    registry.record(preset(version=1), source_provenance=Provenance.FAKE_SYNTHETIC)
    assert _ids(registry.compatible({TEXT})) == [PRESET_ID]

    registry.record(
        preset(version=2, enabled=False, measured=False, evidence=[]),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    assert registry.compatible({TEXT}) == []
    current = registry.get(PRESET_ID)
    assert current is not None and current.version == 2
    assert count(db, "SELECT count(*) FROM preset_registry WHERE current") == 1


def test_versions_must_strictly_increase(db: Database) -> None:
    registry = _registry(db)
    registry.record(preset(version=3), source_provenance=Provenance.FAKE_SYNTHETIC)
    with pytest.raises(Conflict):
        registry.record(preset(version=3), source_provenance=Provenance.FAKE_SYNTHETIC)


def test_get_round_trips_the_contract_record(db: Database) -> None:
    registry = _registry(db)
    original = preset()
    registry.record(original, source_provenance=Provenance.FAKE_SYNTHETIC)
    assert registry.get(PRESET_ID) == original
    assert registry.get("fake-missing") is None


def test_an_enabled_preset_needs_measured_evidence_at_the_contract_level() -> None:
    """Unmeasured presets cannot even be built as enabled, so the registry never sees one."""
    with pytest.raises(ValueError):
        preset(enabled=True, measured=False)


def test_fake_only_presets_are_selectable_in_mock_and_excluded_with_live_settings(
    db: Database,
) -> None:
    _registry(db).record(preset(), source_provenance=Provenance.FAKE_SYNTHETIC)
    assert _ids(_registry(db, mock_settings()).compatible({TEXT})) == [PRESET_ID]
    assert _registry(db, live_settings()).enabled() == []
    assert _registry(db, live_settings()).compatible({TEXT}) == []


def test_real_measured_presets_are_selectable_with_live_settings(db: Database) -> None:
    registry = _registry(db, live_settings())
    registry.record(
        preset(
            evidence=[
                EvidenceRef(
                    source=EvidenceSource.MEASURED_BENCHMARK, ref="benchmark:run-2026-10-20"
                )
            ]
        ),
        source_provenance=Provenance.LIVE_PROVIDER,
    )
    assert _ids(registry.compatible({TEXT, FIRST})) == [PRESET_ID]


def test_d3_refuses_a_real_source_label_on_fake_provenance(db: Database) -> None:
    registry = _registry(db)
    with pytest.raises(PolicyDenied):
        registry.record(
            preset(
                evidence=[
                    EvidenceRef(source=EvidenceSource.MEASURED_BENCHMARK, ref="claimed-benchmark")
                ]
            ),
            source_provenance=Provenance.FAKE_SYNTHETIC,
        )
    assert count(db, "SELECT count(*) FROM preset_registry") == 0


def test_a_live_database_refuses_an_enabled_fake_preset(db: Database) -> None:
    switch_runtime_mode(db, ExecutionMode.CONTROLLED_ACCOUNT_TEST)
    with pytest.raises(Unauthorized):
        _registry(db, live_settings()).record(preset(), source_provenance=Provenance.FAKE_SYNTHETIC)
    assert count(db, "SELECT count(*) FROM preset_registry") == 0


def test_a_tampered_preset_row_that_fails_validation_raises_on_read(db: Database) -> None:
    """An enabled preset whose stored rights route was cleared by SQL no longer validates. Reads
    raise a typed Conflict; the damaged preset is never silently skipped or selected."""
    registry = _registry(db)
    registry.record(preset(), source_provenance=Provenance.FAKE_SYNTHETIC)
    with db.transaction() as tx:
        tx.execute("SET LOCAL session_replication_role = replica")
        tx.execute(
            "UPDATE preset_registry SET record = jsonb_set(record, '{rights_route_id}', 'null'::jsonb) "
            "WHERE preset_id = %s",
            (PRESET_ID,),
        )
    with pytest.raises(Conflict):
        registry.get(PRESET_ID)
    with pytest.raises(Conflict):
        registry.enabled()
    with pytest.raises(Conflict):
        registry.compatible({TEXT})
