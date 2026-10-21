"""The preset catalog: tier classes, template pinning and typed-unknown eligibility."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_routing_support import (
    REFERENCE_CONTROLS,
    RoutingWorld,
    measurements,
    preset_record,
)

from microdrama.contracts.enums import ControlKind, Provenance, RenderTier
from microdrama.contracts.errors import Conflict, SchemaInvalid
from microdrama.persistence import Database
from microdrama.rendering.presets import (
    PROMOTION_LADDER,
    EligibilityReason,
    PresetTierClass,
    control_set,
    promoted,
    tier_class_for,
)
from microdrama.rendering.workflows import PRESET_TEMPLATES, template_sha256

pytestmark = [pytest.mark.db]


@pytest.fixture
def world(db: Database, tmp_path: Path) -> RoutingWorld:
    return RoutingWorld(db, tmp_path / "store")


def test_tier_classes_map_the_three_routing_families() -> None:
    assert tier_class_for(RenderTier.FAST_FOUR_STEP) is PresetTierClass.FAST
    assert tier_class_for(RenderTier.QUALITY_EIGHT_STEP) is PresetTierClass.QUALITY
    assert tier_class_for(RenderTier.COMPATIBLE_BASELINE) is PresetTierClass.CONTROL


def test_promotion_ladder_is_strict_and_terminates_at_control() -> None:
    assert PROMOTION_LADDER == {
        PresetTierClass.FAST: PresetTierClass.QUALITY,
        PresetTierClass.QUALITY: PresetTierClass.CONTROL,
    }
    assert promoted(PresetTierClass.CONTROL) is None


def test_catalog_view_pins_the_record_to_the_mapped_template(world: RoutingWorld) -> None:
    world.seed_presets()
    record = world.registry.get("fake-quality-8step")
    assert record is not None
    view = world.catalog.view(record)
    assert view is not None
    assert view.template is PRESET_TEMPLATES["fake-quality-8step"]
    assert view.template_workflow_sha256 == template_sha256(view.template)
    assert record.workflow_sha256 == view.template_workflow_sha256
    assert view.tier_class is PresetTierClass.QUALITY
    assert view.total_accepted_cost_micro_usd == 120_000 + 10_000
    assert view.cold_start_ms == 180_000
    assert view.warm_full_job_ms == 95_000


def test_a_view_refuses_a_record_that_pins_a_foreign_workflow(world: RoutingWorld) -> None:
    world.seed_presets()
    record = preset_record(
        preset_id="fake-quality-8step",
        tier=RenderTier.QUALITY_EIGHT_STEP,
        controls=REFERENCE_CONTROLS,
        measured=measurements(),
        version=2,
    ).model_copy(update={"workflow_sha256": "0" * 64})  # a genuinely foreign pin
    with pytest.raises(Conflict, match="workflow hash"):
        world.catalog.view(record)


def test_a_view_refuses_a_record_claiming_controls_the_template_cannot_carry(
    world: RoutingWorld,
) -> None:
    # CAMERA_MOTION is a real control the mock template does not support.
    world.seed_presets()
    record = preset_record(
        preset_id="fake-quality-8step",
        tier=RenderTier.QUALITY_EIGHT_STEP,
        controls=REFERENCE_CONTROLS + (ControlKind.CAMERA_MOTION,),
        measured=measurements(),
        version=2,
    )
    with pytest.raises(Conflict, match="cannot carry"):
        world.catalog.view(record)


def test_an_unmapped_preset_has_no_view_and_is_reported_not_locally_extended(
    world: RoutingWorld,
) -> None:
    world.seed_presets()
    record = world.registry.get("fake-control-baseline")
    assert record is not None
    assert world.catalog.view(record) is None
    # the consumed mapping is exactly T013's; this lane never adds entries
    assert world.catalog.mapped_ids() == tuple(sorted(PRESET_TEMPLATES))
    assert "fake-control-baseline" not in PRESET_TEMPLATES


def test_control_set_is_typed_about_unknown_values() -> None:
    assert control_set(["TEXT_PROMPT", ControlKind.SEED]) == frozenset(
        {ControlKind.TEXT_PROMPT, ControlKind.SEED}
    )
    with pytest.raises(SchemaInvalid, match="unknown control kind"):
        control_set(["TEXT_PROMPT", "NOT_A_CONTROL"])


def test_current_records_surface_disabled_presets_for_rejection_receipts(
    world: RoutingWorld,
) -> None:
    world.seed_presets()
    world.registry.record(
        preset_record(
            preset_id="fake-offer-probe",
            tier=RenderTier.QUALITY_EIGHT_STEP,
            controls=REFERENCE_CONTROLS,
            measured=None,
            enabled=False,
        ),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    ids = [record.preset_id for record in world.catalog.current_records()]
    assert "fake-offer-probe" in ids
    assert "fake-fast-4step" in ids
    assert "fake-control-baseline" in ids


def test_eligibility_reasons_are_the_typed_closed_set() -> None:
    # the rejection vocabulary stays closed: unknowns are typed-unknown members,
    # never free text
    assert {reason.value for reason in EligibilityReason} == {
        "DISABLED",
        "UNMEASURED",
        "NO_TEMPLATE",
        "HARD_CONTROL",
        "TIER_POLICY",
        "QUALITY_GATE",
        "CLASS_UNMEASURED",
    }
