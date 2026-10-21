"""Contract-level behaviour of the T016 variant/hook/cover modules.

Pure tests pin the frozen surfaces this lane consumes and produces: the reserved
``edit.variants_and_hooks`` job spec, the frozen ``HookExperiment``/``HookCandidate``
/``HookAssignment`` contracts (bounds, distinctness, MD-018, observational-only),
the review ``MediaRef`` roles, and the one deliberate divergence from T015 — the
crop-blind semantic hash — proven here so a future contract bump cannot silently
collapse cropped and uncropped variants.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from test_hooks_pure import EPISODE, main_edl
from test_hooks_pure import plan as plan_hooks
from test_variants_support import capability_record

from microdrama.contracts.enums import QueueName, TrafficKind
from microdrama.contracts.examples import hook_experiment
from microdrama.contracts.jobs import JOB_SPECS_BY_TYPE
from microdrama.contracts.media import HookAssignment, HookCandidate, HookExperiment
from microdrama.contracts.primitives import AccountRef
from microdrama.editing import edl_semantic_hash
from microdrama.editing.variants import variant_semantic_hash


def test_the_reserved_variants_and_hooks_job_spec_is_owned_by_editing() -> None:
    spec = JOB_SPECS_BY_TYPE["edit.variants_and_hooks"]
    assert spec.owner_module == "editing"
    assert spec.queue is QueueName.PRODUCTION
    assert spec.input_model.__name__ == "EpisodeStepInput"


def test_frozen_hook_experiment_example_round_trips() -> None:
    example = hook_experiment()
    again = HookExperiment.model_validate(example.model_dump(mode="json"))
    assert again == example
    assert len({c.edl_id for c in again.candidates}) == 3
    assert again.assignments == []
    assert again.observational_only is True


def test_planned_experiment_bodies_validate_as_the_frozen_contract() -> None:
    result = plan_hooks()
    experiment = HookExperiment(
        experiment_id=uuid4(),
        episode_id=EPISODE,
        candidates=[candidate.candidate for candidate in result.candidates],
    )
    again = HookExperiment.model_validate(experiment.model_dump(mode="json"))
    assert again == experiment
    assert {c.candidate_id for c in again.candidates} == {"hook-a", "hook-b", "hook-c"}
    for candidate in again.candidates:
        assert 20_000 <= candidate.duration_ms <= 40_000
        assert candidate.source_asset_ids


def test_hook_candidate_duration_bounds_are_frozen() -> None:
    example = hook_experiment()
    too_short = example.candidates[0].model_copy(update={"duration_ms": 15_000})
    with pytest.raises(ValueError, match="20-40"):
        HookCandidate.model_validate(too_short.model_dump(mode="json"))
    too_long = example.candidates[0].model_copy(update={"duration_ms": 45_000})
    with pytest.raises(ValueError, match="20-40"):
        HookCandidate.model_validate(too_long.model_dump(mode="json"))


def test_three_distinct_candidates_are_required_by_the_contract() -> None:
    example = hook_experiment()
    duplicated = example.model_copy(
        update={
            "candidates": [
                c.model_copy(update={"candidate_id": "hook-a"}) for c in example.candidates
            ]
        }
    )
    with pytest.raises(ValueError, match="three distinct"):
        HookExperiment.model_validate(duplicated.model_dump(mode="json"))


def test_organic_comparisons_stay_observational_by_contract() -> None:
    example = hook_experiment()
    causal = example.model_copy(update={"observational_only": False})
    with pytest.raises(ValueError, match="observational"):
        HookExperiment.model_validate(causal.model_dump(mode="json"))


def test_paid_hook_assignments_violate_md018_by_contract() -> None:
    with pytest.raises(ValueError, match="MD-018"):
        HookAssignment(
            candidate_id="hook-a",
            platform="TIKTOK",
            account_ref="acct:tiktok-main",
            release_slot="promo.slot-1",
            cohort="organic-a",
            scheduled_utc="2026-10-22T10:00:00+00:00",
            traffic=TrafficKind.PAID,
        )
    assert AccountRef  # the account namespace the variants/cover targets share


def test_media_refs_validate_for_every_role_final_review_emits() -> None:
    from microdrama.contracts.release import MediaRef

    # "burned" deliberately extends the contract docstring's example list (the
    # caption-burned master is distinct review media); flagged to the guardian.
    roles = ("master", "burned", "variant", "cover", "hook")
    for role in roles:
        ref = MediaRef(asset_id=uuid4(), sha256="a" * 64, role=role)
        assert ref.role == role


def test_t015s_semantic_hash_cannot_see_crops_so_t016_hashes_decisions_itself() -> None:
    from microdrama.contracts.media import CropSpec

    base = main_edl()
    crop = CropSpec(x=0, y=219, width=360, height=202)
    cropped = base.model_copy(
        update={
            "clips": [
                clip.model_copy(update={"crop": crop}) if index == 0 else clip
                for index, clip in enumerate(base.clips)
            ]
        }
    )
    # T015's hash is crop-blind (crops were not part of its decisions)...
    assert edl_semantic_hash(base) == edl_semantic_hash(cropped)
    # ...which is exactly why T016's variant hash includes them.
    assert variant_semantic_hash(base, variant_key="k") != variant_semantic_hash(
        cropped, variant_key="k"
    )


def test_capability_limits_feed_planning_through_the_frozen_record() -> None:
    record = capability_record(ratios=("16:9",))
    assert record.limits.aspect_ratios == ["16:9"]
    assert record.limits.max_duration_ms == 300_000
    assert record.operations  # the ops surface T020 evaluates at assignment time
