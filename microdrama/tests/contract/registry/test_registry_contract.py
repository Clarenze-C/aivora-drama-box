"""Contract conformance for the registries: the example policy and playbook map onto the frozen
contract types, contract example payloads pass through the registries unchanged, and what the
registries store is contract-valid, integer-only JSON."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from microdrama.config import Settings
from microdrama.contracts.enums import (
    BudgetCategory,
    CapabilityOperation,
    Platform,
    Provenance,
    RightsSubjectKind,
    ShotPattern,
)
from microdrama.contracts.examples import capability_record, preset_record, rights_record
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.primitives import DEFAULT_BUDGET_ALLOCATION_MICRO_USD, DEFAULT_LIMITS
from microdrama.contracts.registries import PresetRecord, RightsRecord
from microdrama.contracts.release import CapabilityRecord
from microdrama.contracts.season import CostPolicy, Shot
from microdrama.core.registry import (
    ALLOCATION_KEYS,
    CapabilityRegistry,
    PresetRegistry,
    RightsRegistry,
    import_policy,
    load_automation_policy,
    load_directing_playbook,
)
from microdrama.core.registry._common import canonical_document
from microdrama.persistence import Database
from microdrama.testing.fakes.common import FakeClock

REPO_ROOT = Path(__file__).resolve().parents[4]
POLICY = (
    REPO_ROOT / "deliverables/thai-microdrama-research-2026-10-19/automation-policy.example.json"
)
PLAYBOOK = (
    REPO_ROOT / "deliverables/thai-microdrama-research-2026-10-19/directing-playbook.example.json"
)
T0 = rights_record().recorded_at
MOCK = Settings()


def _no_floats(value: Any) -> None:
    if isinstance(value, float):
        raise AssertionError(f"float found in stored JSON: {value!r}")
    if isinstance(value, dict):
        for item in value.values():
            _no_floats(item)
    elif isinstance(value, list):
        for item in value:
            _no_floats(item)


# --- policy and playbook against the contract ------------------------------------------


def test_example_policy_is_the_contract_cost_and_limit_default() -> None:
    settings = load_automation_policy(POLICY)
    assert settings.cost_policy == CostPolicy()
    assert settings.limits == DEFAULT_LIMITS
    assert settings.cost_policy.allocation_micro_usd == DEFAULT_BUDGET_ALLOCATION_MICRO_USD


def test_the_allocation_mapping_covers_every_budget_category_exactly_once() -> None:
    assert set(ALLOCATION_KEYS.values()) == set(BudgetCategory)
    assert len(ALLOCATION_KEYS) == len(set(BudgetCategory))


def test_the_example_playbook_is_the_contract_shot_surface() -> None:
    playbook = load_directing_playbook(PLAYBOOK)
    assert playbook.pattern_ids == frozenset(ShotPattern)
    assert all(field in Shot.model_fields for field in playbook.required_shot_fields)


def test_readiness_on_the_example_policy_is_the_full_setup_list() -> None:
    blockers = load_automation_policy(POLICY).readiness_blockers()
    assert len(blockers) == 13
    assert all(blocker.startswith(("policy:", "setup:")) for blocker in blockers)


# --- contract examples through the registries -------------------------------------------


@pytest.mark.db
def test_a_contract_capability_example_round_trips_unchanged(db: Database) -> None:
    original = capability_record()
    registry = CapabilityRegistry(db, FakeClock(T0), MOCK)
    registry.record(original, source_provenance=Provenance.FAKE_SYNTHETIC)
    stored = registry.current(original.platform, original.account_ref)
    assert stored == original
    assert isinstance(stored, CapabilityRecord)
    assert registry.evaluate(
        platform=Platform.YOUTUBE,
        account_ref=original.account_ref,
        required={CapabilityOperation.UPLOAD_FULL_VIDEO, CapabilityOperation.SCHEDULE},
    ).available


@pytest.mark.db
def test_a_contract_preset_example_round_trips_unchanged(db: Database) -> None:
    original = preset_record()
    registry = PresetRegistry(db, MOCK)
    registry.record(original, source_provenance=Provenance.FAKE_SYNTHETIC)
    stored = registry.get(original.preset_id)
    assert stored == original
    assert isinstance(stored, PresetRecord)


@pytest.mark.db
def test_a_contract_rights_example_is_eligible_for_its_route(db: Database) -> None:
    original = rights_record()
    registry = RightsRegistry(db, FakeClock(T0), MOCK)
    registry.record(original, source_provenance=Provenance.FAKE_SYNTHETIC)
    decision = registry.evaluate(
        rights_route_id=original.rights_route_id,
        subjects=[(RightsSubjectKind.VOICE, original.subject_ref)],
        territories=["TH"],
        at=T0 + timedelta(days=1),
    )
    assert decision.eligible
    stored_evidence = _row_value(
        db,
        "SELECT evidence FROM rights_registry WHERE rights_route_id = %s",
        original.rights_route_id,
    )
    assert stored_evidence == canonical_document(original.evidence)


@pytest.mark.db
def test_stored_registry_json_is_contract_valid_and_integer_only(db: Database) -> None:
    capability = capability_record()
    preset = preset_record()
    CapabilityRegistry(db, FakeClock(T0), MOCK).record(
        capability, source_provenance=Provenance.FAKE_SYNTHETIC
    )
    PresetRegistry(db, MOCK).record(preset, source_provenance=Provenance.FAKE_SYNTHETIC)

    stored_capability = _row_value(
        db,
        "SELECT record FROM capability_registry WHERE capability_id = %s",
        capability.capability_id,
    )
    stored_preset = _row_value(
        db, "SELECT record FROM preset_registry WHERE preset_id = %s", preset.preset_id
    )
    _no_floats(stored_capability)
    _no_floats(stored_preset)
    assert CapabilityRecord.model_validate(stored_capability) == capability
    assert PresetRecord.model_validate(stored_preset) == preset
    assert canonical_hash(stored_capability) == canonical_hash(capability)
    assert canonical_hash(stored_preset) == canonical_hash(preset)


@pytest.mark.db
def test_a_stored_rights_record_keeps_its_contract_territory_and_scope(db: Database) -> None:
    original: RightsRecord = rights_record()
    RightsRegistry(db, FakeClock(T0), MOCK).record(
        original, source_provenance=Provenance.FAKE_SYNTHETIC
    )
    row = _row_value(
        db,
        "SELECT to_jsonb(r) FROM (SELECT territories, commercial_use, output_release_allowed, "
        "required_disclosures FROM rights_registry WHERE rights_route_id = %s) r",
        original.rights_route_id,
    )
    assert row["territories"] == original.territories
    assert row["commercial_use"] is original.commercial_use
    assert row["output_release_allowed"] is original.output_release_allowed
    assert row["required_disclosures"] == [d.value for d in original.required_disclosures]


@pytest.mark.db
def test_the_policy_row_keeps_the_original_decimal_document(db: Database) -> None:
    with db.transaction() as tx:
        import_policy(tx, POLICY)
    with db.transaction(readonly=True) as tx:
        value = tx.fetchval(
            "SELECT body->'proposed_budget_allocation_usd'->>'uncommitted_recovery_and_billing_exposure_headroom' "
            "FROM policy_versions"
        )
    assert value == "2.5"


def _row_value(db: Database, sql: str, param: Any) -> Any:
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(sql, (param,))
    assert row is not None
    return next(iter(row.values()))
