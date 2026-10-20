"""Policy and playbook import: exact micro-USD, refused safety flags, readiness blockers, import."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from registry_support import PLAYBOOK_EXAMPLE, POLICY_EXAMPLE, count

from microdrama.contracts.enums import BudgetCategory, ManagementActionKind, ShotPattern
from microdrama.contracts.errors import Conflict, PolicyDenied, SchemaInvalid
from microdrama.contracts.primitives import DEFAULT_BUDGET_ALLOCATION_MICRO_USD, DEFAULT_LIMITS
from microdrama.contracts.season import CostPolicy, Shot
from microdrama.core.registry import (
    import_policy,
    load_automation_policy,
    load_directing_playbook,
    usd_to_micro,
)
from microdrama.persistence import Database

SETUP_KEYS = [
    "approved_season_id",
    "approved_season_scope_sha256",
    "rights_route_id",
    "comfy_api_workflow_sha256",
    "model_and_node_version_registry",
    "voice_and_music_license_registry",
    "gpu_profile_and_actual_hourly_ceiling",
    "destination_account_capability_registry",
    "approved_schedule_windows",
    "credential_store_reference",
    "shared_research_spend_reservation",
    "management_policy_sha256",
]


def _policy_doc() -> dict[str, Any]:
    return json.loads(POLICY_EXAMPLE.read_text(encoding="utf-8"))


def _write(tmp_path: Path, doc: dict[str, Any], name: str = "policy.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _write_raw(tmp_path: Path, text: str, name: str = "policy.json") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# --- exact money ---------------------------------------------------------------------


def test_every_allocation_converts_exactly_and_sums_to_the_cap() -> None:
    settings = load_automation_policy(POLICY_EXAMPLE)
    allocation = settings.cost_policy.allocation_micro_usd
    assert allocation == {
        BudgetCategory.RESEARCH_SCRIPT_PROMPTS_METADATA: 1_000_000,
        BudgetCategory.REFERENCES_DIALOGUE: 1_500_000,
        BudgetCategory.GPU_GENERATION: 2_500_000,
        BudgetCategory.QA_CAPTIONS: 1_000_000,
        BudgetCategory.CPU_STORAGE_TRANSFER: 500_000,
        BudgetCategory.METERED_MANAGEMENT: 1_000_000,
        BudgetCategory.RECOVERY_HEADROOM: 2_500_000,
    }
    assert sum(allocation.values()) == 10_000_000
    assert settings.cost_policy.episode_cap_micro_usd == 10_000_000
    assert allocation == DEFAULT_BUDGET_ALLOCATION_MICRO_USD
    assert all(type(value) is int for value in allocation.values())


def test_example_policy_matches_the_contract_cost_defaults() -> None:
    settings = load_automation_policy(POLICY_EXAMPLE)
    assert settings.cost_policy == CostPolicy()
    assert settings.cost_policy.paid_advertising_budget_micro_usd == 0
    assert settings.cost_policy.automatic_cap_increase is False


def test_usd_to_micro_is_exact_for_decimal_and_int_amounts() -> None:
    # Python floats drift (1.005 * 1_000_000 is 1004999.9999999999); Decimal lands exactly.
    assert usd_to_micro(Decimal("1.005"), what="x") == 1_005_000
    assert usd_to_micro(Decimal("1.15"), what="x") == 1_150_000
    assert usd_to_micro(Decimal("0.29"), what="x") == 290_000
    assert usd_to_micro(Decimal("0.000001"), what="x") == 1
    assert usd_to_micro(Decimal("2.000000"), what="x") == 2_000_000
    assert usd_to_micro(10, what="x") == 10_000_000


@pytest.mark.parametrize("float_amount", [1.5, 1.005, 0.0])
def test_a_binary_float_is_refused_by_the_converter(float_amount: float) -> None:
    with pytest.raises(SchemaInvalid, match="not a binary float"):
        usd_to_micro(float_amount, what="amount")


@pytest.mark.parametrize(
    "bad",
    [
        Decimal("1.0000001"),
        Decimal("0.0000001"),
        Decimal("1e-7"),
        # 33 significant digits: a context multiply would round this into range.
        Decimal("2.00000000000000000000000000000001"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("1e40"),  # beyond any plausible amount; refused before big-number maths
    ],
    ids=lambda value: str(value)[:24],
)
def test_inexact_or_out_of_range_decimal_amounts_are_refused(bad: Decimal) -> None:
    with pytest.raises(SchemaInvalid):
        usd_to_micro(bad, what="amount")


@pytest.mark.parametrize("bad", [True, "1.0", None])
def test_non_numeric_usd_amounts_are_refused(bad: object) -> None:
    with pytest.raises(SchemaInvalid):
        usd_to_micro(bad, what="amount")


def test_an_inexact_amount_in_the_policy_file_is_refused_not_rounded(tmp_path: Path) -> None:
    """The coordinator's case: 2.0000000000000001 must not parse to 2.0 and be accepted."""
    text = POLICY_EXAMPLE.read_text(encoding="utf-8")
    old = '"gpu_generation_warmup_retries": 2.5'
    assert text.count(old) == 1
    text = text.replace(old, '"gpu_generation_warmup_retries": 2.0000000000000001')
    with pytest.raises(SchemaInvalid, match="whole number of micro-USD"):
        load_automation_policy(_write_raw(tmp_path, text))


def test_an_exact_amount_written_with_trailing_zeros_is_accepted(tmp_path: Path) -> None:
    """Control for the case above: the same allocation written exactly is accepted, and the
    total still matches the cap (GPU 2.000000 plus recovery 3.0 keeps the sum at 10.0)."""
    text = POLICY_EXAMPLE.read_text(encoding="utf-8")
    for old, new in (
        ('"gpu_generation_warmup_retries": 2.5', '"gpu_generation_warmup_retries": 2.000000'),
        (
            '"uncommitted_recovery_and_billing_exposure_headroom": 2.5',
            '"uncommitted_recovery_and_billing_exposure_headroom": 3.0',
        ),
    ):
        assert text.count(old) == 1
        text = text.replace(old, new)
    settings = load_automation_policy(_write_raw(tmp_path, text))
    assert settings.cost_policy.allocation_micro_usd[BudgetCategory.GPU_GENERATION] == 2_000_000
    assert settings.cost_policy.allocation_micro_usd[BudgetCategory.RECOVERY_HEADROOM] == 3_000_000


@pytest.mark.parametrize(
    "old, new",
    [
        ('"maximum_total_attempts_per_shot": 3,', '"maximum_total_attempts_per_shot": 3.0,'),
        (
            '"consecutive_qualifying_episodes_required": 10,',
            '"consecutive_qualifying_episodes_required": 10.0,',
        ),
    ],
    ids=["attempts-written-as-decimal", "streak-written-as-decimal"],
)
def test_integer_settings_refuse_a_decimal_spelling(tmp_path: Path, old: str, new: str) -> None:
    text = POLICY_EXAMPLE.read_text(encoding="utf-8")
    assert text.count(old) == 1
    with pytest.raises(SchemaInvalid):
        load_automation_policy(_write_raw(tmp_path, text.replace(old, new)))


def test_non_finite_numbers_in_the_policy_file_are_refused(tmp_path: Path) -> None:
    text = POLICY_EXAMPLE.read_text(encoding="utf-8").replace(
        '"references_and_dialogue": 1.5', '"references_and_dialogue": NaN'
    )
    with pytest.raises(SchemaInvalid):
        load_automation_policy(_write_raw(tmp_path, text))


def test_duplicate_keys_in_the_policy_file_are_refused(tmp_path: Path) -> None:
    text = POLICY_EXAMPLE.read_text(encoding="utf-8").replace(
        '"runtime_enabled": false,', '"runtime_enabled": false,\n  "runtime_enabled": true,', 1
    )
    with pytest.raises(SchemaInvalid):
        load_automation_policy(_write_raw(tmp_path, text))


# --- limits and management -----------------------------------------------------------


def test_retry_and_repair_limits_are_three_two_three() -> None:
    limits = load_automation_policy(POLICY_EXAMPLE).limits
    assert limits.max_attempts_per_shot == 3
    assert limits.max_final_repair_rounds == 2
    assert limits.max_transport_attempts == 3
    assert limits == DEFAULT_LIMITS


def test_management_defaults_come_from_the_community_policy() -> None:
    management = load_automation_policy(POLICY_EXAMPLE).management_defaults
    assert management.metadata_cooldown_hours == 24
    assert management.max_substantive_edits_first_7_days == 2
    assert management.cold_outbound_dms is False
    assert management.remove_ordinary_criticism is False
    assert management.automatic_account_bans is False
    assert management.accept_contracts_sponsors_refunds is False
    assert management.allowed_actions == frozenset(
        {
            ManagementActionKind.NO_ACTION,
            ManagementActionKind.TITLE_EDIT,
            ManagementActionKind.CAPTION_EDIT,
            ManagementActionKind.DESCRIPTION_EDIT,
            ManagementActionKind.HASHTAG_EDIT,
            ManagementActionKind.COVER_CHANGE,
            ManagementActionKind.LINK_UPDATE,
            ManagementActionKind.PUBLIC_REPLY,
            ManagementActionKind.DM_SEND,
            ManagementActionKind.MODERATE_HIDE,
            ManagementActionKind.MODERATE_DELETE,
            ManagementActionKind.MODERATE_REPORT,
        }
    )


# --- safety flags --------------------------------------------------------------------


def _flip(path: tuple[str, ...], value: object) -> Any:
    def mutate(doc: dict[str, Any]) -> None:
        node = doc
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value

    return mutate


def _drop(path: tuple[str, ...]) -> Any:
    def mutate(doc: dict[str, Any]) -> None:
        node = doc
        for key in path[:-1]:
            node = node[key]
        del node[path[-1]]

    return mutate


FLIPPED_SAFETY = [
    pytest.param(
        _flip(("quality_policy", "human_approval_on_timeout"), True), id="timeout-approval"
    ),
    pytest.param(
        _flip(("quality_policy", "missing_critical_coverage_is_pass"), True), id="missing-coverage"
    ),
    pytest.param(_flip(("budget_policy", "automatic_cap_increase"), True), id="cap-increase"),
    pytest.param(
        _flip(("budget_policy", "paid_advertising_budget_usd"), 0.5), id="paid-advertising"
    ),
    pytest.param(
        _flip(("requirements_confirmed_by_user", "variable_cost_limit_usd_per_episode"), 10.5),
        id="cost-over-ten",
    ),
    pytest.param(
        _flip(("requirements_confirmed_by_user", "maximum_final_episode_duration_seconds"), 301),
        id="duration-over-300",
    ),
    pytest.param(
        _flip(("proposed_community_policy", "remove_ordinary_criticism"), True), id="criticism"
    ),
    pytest.param(
        _flip(("approval_policy", "routine_manual_upload_fallback"), True), id="manual-fallback"
    ),
    pytest.param(
        _flip(
            (
                "requirements_confirmed_by_user",
                "intermediate_script_prompt_reference_audio_edit_approvals",
            ),
            True,
        ),
        id="extra-human-gates",
    ),
]


@pytest.mark.parametrize("mutate", FLIPPED_SAFETY)
def test_flipped_safety_flags_are_refused(tmp_path: Path, mutate: Any) -> None:
    doc = _policy_doc()
    mutate(doc)
    with pytest.raises(PolicyDenied):
        load_automation_policy(_write(tmp_path, doc))


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            _flip(
                (
                    "proposed_budget_allocation_usd",
                    "uncommitted_recovery_and_billing_exposure_headroom",
                ),
                2.6,
            ),
            id="allocation-sum-mismatch",
        ),
        pytest.param(
            _drop(("proposed_budget_allocation_usd", "cpu_edit_storage_transfer")),
            id="allocation-missing-category",
        ),
        pytest.param(
            _flip(("proposed_budget_allocation_usd", "surprise_bucket"), 0.0),
            id="allocation-unknown-category",
        ),
        pytest.param(
            _flip(("requirements_confirmed_by_user", "variable_cost_limit_usd_per_episode"), 9.5),
            id="cap-below-allocation",
        ),
        pytest.param(
            _flip(("proposed_retry_settings", "maximum_total_attempts_per_shot"), 4),
            id="attempts-above-maximum",
        ),
        pytest.param(
            _flip(("proposed_retry_settings", "maximum_total_attempts_per_shot"), True),
            id="attempts-bool",
        ),
        pytest.param(
            _flip(
                ("reliability_qualification_policy", "consecutive_qualifying_episodes_required"), 9
            ),
            id="streak-not-ten",
        ),
        pytest.param(
            _drop(("setup_required_before_execution", "rights_route_id")), id="setup-gone"
        ),
        pytest.param(
            _flip(("setup_required_before_execution", "rights_route_id"), 7), id="setup-not-text"
        ),
    ],
)
def test_structurally_invalid_policies_are_refused(tmp_path: Path, mutate: Any) -> None:
    doc = _policy_doc()
    mutate(doc)
    with pytest.raises(SchemaInvalid):
        load_automation_policy(_write(tmp_path, doc))


def test_the_safety_flags_expose_the_fixed_values() -> None:
    safety = load_automation_policy(POLICY_EXAMPLE).safety
    assert safety.human_approval_on_timeout is False
    assert safety.missing_critical_coverage_is_pass is False
    assert safety.automatic_cap_increase is False
    assert safety.review_actual_final_media is True
    assert safety.writer_cannot_self_certify_final_footage is True


def test_the_safety_model_cannot_hold_a_flipped_value() -> None:
    from pydantic import ValidationError

    from microdrama.core.registry.policy import PolicySafetyFlags

    with pytest.raises(ValidationError):
        PolicySafetyFlags(human_approval_on_timeout=True)
    with pytest.raises(ValidationError):
        PolicySafetyFlags(review_actual_final_media=False)


def test_example_policy_is_accepted_unchanged() -> None:
    settings = load_automation_policy(POLICY_EXAMPLE)
    assert settings.version == "automation-scope-2026-10-19-v2"
    assert settings.document_kind == "INACTIVE_DESIGN_EXAMPLE"
    assert settings.runtime_enabled is False
    assert settings.source_sha256 == hashlib.sha256(POLICY_EXAMPLE.read_bytes()).hexdigest()


# --- readiness -----------------------------------------------------------------------


def test_readiness_lists_every_null_setup_item_and_the_disabled_runtime() -> None:
    blockers = load_automation_policy(POLICY_EXAMPLE).readiness_blockers()
    assert "policy:runtime_enabled is false" in blockers
    assert "setup:rights_route_id missing" in blockers
    for key in SETUP_KEYS:
        assert f"setup:{key} missing" in blockers
    assert len(blockers) == len(SETUP_KEYS) + 1


def test_a_filled_setup_item_clears_only_its_own_blocker(tmp_path: Path) -> None:
    doc = _policy_doc()
    doc["setup_required_before_execution"]["rights_route_id"] = "route-voice-th-2026"
    blockers = load_automation_policy(_write(tmp_path, doc)).readiness_blockers()
    assert "setup:rights_route_id missing" not in blockers
    assert "policy:runtime_enabled is false" in blockers
    assert len(blockers) == len(SETUP_KEYS)


def test_enabling_the_runtime_flag_never_clears_the_setup_blockers(tmp_path: Path) -> None:
    doc = _policy_doc()
    doc["runtime_enabled"] = True
    blockers = load_automation_policy(_write(tmp_path, doc)).readiness_blockers()
    assert "policy:runtime_enabled is false" not in blockers
    assert len(blockers) == len(SETUP_KEYS)


# --- directing playbook --------------------------------------------------------------


def test_playbook_patterns_equal_the_contract_shot_patterns() -> None:
    playbook = load_directing_playbook(PLAYBOOK_EXAMPLE)
    assert playbook.pattern_ids == frozenset(ShotPattern)
    assert len(playbook.pattern_ids) == 6
    assert playbook.limits.active_locations_per_episode == 2
    assert playbook.limits.featured_speaking_characters_per_episode == 3
    assert playbook.limits.speakers_per_shot == 2
    assert set(playbook.required_shot_fields) <= set(Shot.model_fields)
    assert playbook.required_shot_fields == (
        "shot_pattern_id",
        "dramatic_importance",
        "dialogue_complexity",
        "temporal_risk",
        "required_identity_controls",
        "preferred_render_tier",
        "fallback_edit",
        "reference_lock_version",
    )


def _playbook_doc() -> dict[str, Any]:
    return json.loads(PLAYBOOK_EXAMPLE.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda d: d["patterns"].pop(), id="one-pattern-missing"),
        pytest.param(lambda d: d["patterns"][0].update(id="made_up_v1"), id="unknown-pattern"),
        pytest.param(
            lambda d: d["patterns"].append(dict(d["patterns"][0])), id="duplicate-pattern"
        ),
        pytest.param(
            lambda d: d["required_shot_fields"].append("camera_brand"), id="unknown-shot-field"
        ),
        pytest.param(lambda d: d["limits"].update(speakers_per_shot=3), id="above-hard-limit"),
    ],
)
def test_playbook_rejects_pattern_and_field_drift(tmp_path: Path, mutate: Any) -> None:
    doc = _playbook_doc()
    mutate(doc)
    path = tmp_path / "playbook.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(SchemaInvalid):
        load_directing_playbook(path)


# --- database import -----------------------------------------------------------------


@pytest.mark.db
def test_import_is_idempotent_and_hashes_the_raw_bytes(db: Database) -> None:
    with db.transaction() as tx:
        first = import_policy(tx, POLICY_EXAMPLE)
    with db.transaction() as tx:
        second = import_policy(tx, POLICY_EXAMPLE)
    assert first == second
    assert count(db, "SELECT count(*) FROM policy_versions") == 1
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT version, document_kind, body_hash, body->>'version' AS body_version "
            "FROM policy_versions"
        )
    assert row is not None
    assert row["version"] == "automation-scope-2026-10-19-v2"
    assert row["document_kind"] == "INACTIVE_DESIGN_EXAMPLE"
    assert row["body_hash"] == hashlib.sha256(POLICY_EXAMPLE.read_bytes()).hexdigest()
    assert row["body_version"] == "automation-scope-2026-10-19-v2"


@pytest.mark.db
def test_import_keeps_the_original_decimal_values_verbatim(db: Database) -> None:
    with db.transaction() as tx:
        import_policy(tx, POLICY_EXAMPLE)
    with db.transaction(readonly=True) as tx:
        value = tx.fetchval(
            "SELECT body->'proposed_budget_allocation_usd'->>'references_and_dialogue' "
            "FROM policy_versions"
        )
    assert value == "1.5"


@pytest.mark.db
def test_same_version_with_different_bytes_is_refused(db: Database, tmp_path: Path) -> None:
    with db.transaction() as tx:
        import_policy(tx, POLICY_EXAMPLE)
    doc = _policy_doc()
    doc["setup_required_before_execution"]["rights_route_id"] = "route-changed-after-review"
    changed = _write(tmp_path, doc)
    with pytest.raises(Conflict), db.transaction() as tx:
        import_policy(tx, changed)
    assert count(db, "SELECT count(*) FROM policy_versions") == 1


@pytest.mark.db
def test_a_flipped_policy_is_never_stored(db: Database, tmp_path: Path) -> None:
    doc = _policy_doc()
    doc["quality_policy"]["human_approval_on_timeout"] = True
    with pytest.raises(PolicyDenied), db.transaction() as tx:
        import_policy(tx, _write(tmp_path, doc))
    assert count(db, "SELECT count(*) FROM policy_versions") == 0
