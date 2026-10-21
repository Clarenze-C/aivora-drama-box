"""Hook candidate tests (T016): the IMP-07 acceptance, on real DB + local FFmpeg.

The long fixture (~32 s of accepted footage, assembled through the real T015
service) is re-cut into three 20-40 s candidates. The load-bearing assertions:

- ZERO video-render jobs / reservations / provider operations from hook
  generation — hooks are local re-cuts, never T013 dispatches;
- the payoff beat survives every candidate;
- three candidates create no release slots, posts or exposures — they are review
  material for the ordinary final-review package, not three obligations;
- non-accepted footage is a typed refusal before any export runs.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from editing_support import World
from test_variants_support import (
    TT_ACCOUNT,
    assembled_long_episode,
    capability_record,
    record_capability,
    seed_long_episode,
    variants_service,
)

from microdrama.contracts.cost import PriceQuote
from microdrama.contracts.enums import BudgetCategory, Platform, PriceSource, PriceUnit
from microdrama.contracts.errors import Conflict
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.media import EditDecisionList, HookExperiment
from microdrama.editing.config import EditingConfig
from microdrama.editing.variants_service import VariantTarget

pytestmark = pytest.mark.ffmpeg


def _priced() -> EditingConfig:
    return EditingConfig(
        transfer_price=PriceQuote(
            currency="USD",
            unit=PriceUnit.VIDEO_SECOND,
            unit_price_micro_usd=2_000,
            source=PriceSource.FAKE_SYNTHETIC,
            price_table_version="t016-v1",
            as_of=datetime(2026, 10, 21, tzinfo=UTC),
        )
    )


def _count(world: World, sql: str, params: tuple = ()) -> int:
    return int(world.row(sql, params)["n"])


def test_three_candidates_with_zero_render_jobs_or_reservations(world: World) -> None:
    episode_id = assembled_long_episode(world)
    outcome = variants_service(world).generate_hook_candidates(episode_id)

    # Three distinct 20-40 s re-cuts, each with its own EDL and treatment.
    assert len(outcome.candidates) == 3
    assert len({c.edl_id for c in outcome.candidates}) == 3
    assert len({c.treatment for c in outcome.candidates}) == 3
    for candidate in outcome.candidates:
        assert 20_000 <= candidate.duration_ms <= 40_000
        assert candidate.burned_asset_id is not None  # playable burned export exists

    # THE acceptance: no video-render jobs, no reservations, no provider ops — the
    # T013 dispatch path is never reached by this module.
    assert outcome.new_video_render_job_ids == []
    assert _count(world, "SELECT COUNT(*) AS n FROM jobs WHERE episode_id = %s", (episode_id,)) == 0
    assert _count(world, "SELECT COUNT(*) AS n FROM jobs WHERE job_type = 'render.shot'") == 0
    assert _count(world, "SELECT COUNT(*) AS n FROM reservations") == 0
    assert _count(world, "SELECT COUNT(*) AS n FROM provider_operations") == 0
    assert outcome.reservation_ids == []  # local exports are free by default

    # The experiment ledger row: contract body, lineage, zero obligations.
    row = world.row(
        "SELECT body, body_hash FROM hook_experiments WHERE episode_id = %s", (episode_id,)
    )
    assert row is not None
    experiment = HookExperiment.model_validate(row["body"])
    assert experiment.experiment_id == outcome.experiment_id
    assert experiment.assignments == []  # three candidates != three posts
    assert experiment.new_video_render_job_ids == []
    assert experiment.observational_only is True
    assert row["body_hash"] == canonical_hash(experiment)
    assert _count(world, "SELECT COUNT(*) AS n FROM platform_posts") == 0
    assert _count(world, "SELECT COUNT(*) AS n FROM hook_exposures") == 0
    assert _count(world, "SELECT COUNT(*) AS n FROM release_packages") == 0

    # Assets: DERIVED_LOCAL hook exports whose lineage names only accepted sources.
    hook_rows = world.rows(
        "SELECT id, edl, output_asset_id FROM edit_manifests WHERE episode_id = %s "
        "AND purpose = 'HOOK' ORDER BY variant_key",
        (episode_id,),
    )
    assert len(hook_rows) == 3
    accepted = {row_["id"]: row_["state"] for row_ in world.rows("SELECT id, state FROM assets")}
    for hook_row, candidate in zip(hook_rows, outcome.candidates, strict=True):
        edl = EditDecisionList.model_validate(hook_row["edl"])
        asset = world.row(
            "SELECT descriptor, provenance, state FROM assets WHERE id = %s",
            (candidate.clean_asset_id,),
        )
        assert asset["provenance"] == "DERIVED_LOCAL"
        assert asset["state"] == "ACCEPTED"
        assert set(asset["descriptor"]["lineage"]) == {
            str(clip.source_asset_id) for clip in edl.clips
        }
        # Every source the re-cut names is accepted (or locked) footage.
        for clip in edl.clips:
            assert accepted[clip.source_asset_id] in ("ACCEPTED", "LOCKED")

    # Production state untouched: no claim, no transition.
    assert world.episode_state(episode_id) == "AI_REVIEW"
    claim = world.row("SELECT correlation_id FROM episodes WHERE id = %s", (episode_id,))
    assert claim["correlation_id"] is None

    # The event summary and the final-review references carry the evidence.
    events = world.events(episode_id, "editing.hooks_built")
    assert len(events) == 1
    payload = events[0]
    assert payload["experiment_id"] == str(outcome.experiment_id)
    assert payload["new_video_render_job_ids"] == []
    assert payload["assignments_created"] == 0
    assert payload["payoff"]["shot_id"] == "ksh8"
    review = variants_service(world).final_review_media(episode_id)
    roles = {ref.role for ref in review.media}
    assert {"master", "burned", "hook"} <= roles
    assert review.hook_experiment_id == outcome.experiment_id
    assert review.hook_candidate_ids == ["hook-a", "hook-b", "hook-c"]


def test_payoff_lines_survive_in_every_exported_candidate(world: World) -> None:
    episode_id = assembled_long_episode(world)
    outcome = variants_service(world).generate_hook_candidates(episode_id)
    assert outcome.payoff_shot_id == "ksh8"
    assert outcome.payoff_line_ids == ["kl8"]
    for hook_row in world.rows(
        "SELECT edl FROM edit_manifests WHERE episode_id = %s AND purpose = 'HOOK'",
        (episode_id,),
    ):
        edl = EditDecisionList.model_validate(hook_row["edl"])
        spoken = {clip.dialogue_line_ids[0] for clip in edl.clips if clip.dialogue_line_ids}
        assert "kl8" in spoken
    # And the re-cut really is shorter than the episode it came from.
    main = world.row(
        "SELECT edl FROM edit_manifests WHERE episode_id = %s AND variant_key = 'main'",
        (episode_id,),
    )
    assert all(
        c.duration_ms < EditDecisionList.model_validate(main["edl"]).duration_ms
        for c in outcome.candidates
    )


def test_changed_framing_and_reading_load_are_logged(world: World) -> None:
    episode_id = assembled_long_episode(world)
    outcome = variants_service(world).generate_hook_candidates(episode_id)
    by_treatment = {c.treatment: c for c in outcome.candidates}
    punch = by_treatment["punch_in_reaction"]
    assert punch.changed_framing is True
    for name in ("payoff_first_cold_open", "chronological_tease"):
        assert by_treatment[name].changed_framing is False
    for candidate in outcome.candidates:
        assert "chars/s" in candidate.reading_load_note
        assert "master" in candidate.reading_load_note


def test_hook_replay_returns_existing_outputs_without_re_export(world: World) -> None:
    episode_id = assembled_long_episode(world)
    priced = variants_service(world, config=_priced())
    first = priced.generate_hook_candidates(episode_id)
    assert len(first.reservation_ids) == 1
    reservation = world.row(
        "SELECT category, state, closed_reason FROM reservations WHERE id = %s",
        (first.reservation_ids[0],),
    )
    assert reservation["category"] == BudgetCategory.CPU_STORAGE_TRANSFER.value
    assert reservation["state"] == "RELEASED" and reservation["closed_reason"]
    assert first.settled_micro_usd == 0

    second = variants_service(world).generate_hook_candidates(episode_id)
    assert second.status.value == "REPLAYED"
    assert second.experiment_id == first.experiment_id
    assert {c.clean_asset_id for c in second.candidates} == {
        c.clean_asset_id for c in first.candidates
    }
    assert second.reservation_ids == []
    assert _count(world, "SELECT COUNT(*) AS n FROM hook_experiments") == 1
    assert (
        _count(
            world,
            "SELECT COUNT(*) AS n FROM edit_manifests WHERE purpose = 'HOOK'",
        )
        == 3
    )


def test_non_accepted_source_is_a_typed_conflict_before_any_export(world: World) -> None:
    episode_id, assets = seed_long_episode(world)
    shot_assets = {k: v for k, v in assets.items() if k.startswith("ksh")}
    world.service.assemble_episode(episode_id, shot_assets=shot_assets)
    with world.db.transaction() as tx:
        tx.execute("UPDATE assets SET state = 'FAILED' WHERE id = %s", (assets["ksh8"],))
    with pytest.raises(Conflict, match="only re-cut accepted"):
        variants_service(world).generate_hook_candidates(episode_id)
    assert _count(world, "SELECT COUNT(*) AS n FROM hook_experiments") == 0
    assert (
        _count(
            world,
            "SELECT COUNT(*) AS n FROM edit_manifests WHERE episode_id = %s AND purpose = 'HOOK'",
            (episode_id,),
        )
        == 0
    )


def test_final_review_media_carries_variants_and_covers_too(world: World) -> None:
    # The short fixture keeps this cheap: variants + covers + review refs, no hooks
    # (a 6.5 s episode is honestly below the 20 s hook floor).
    episode_id, _season, assets = world.seed_prepared_episode()
    world.service.assemble_episode(episode_id, shot_assets=assets["shots"])
    record_capability(world, capability_record(ratios=("16:9",)))
    targets = [VariantTarget(platform=Platform.TIKTOK, account_ref=TT_ACCOUNT)]
    service = variants_service(world)
    service.build_variants(episode_id, targets=targets)
    service.derive_covers(episode_id, targets=targets)
    review = service.final_review_media(episode_id)
    roles = {ref.role for ref in review.media}
    assert {"master", "burned", "variant", "cover"} <= roles
    assert review.variant_keys == ["tiktok-16x9"]
    assert len(review.caption_track_ids) == 2  # th-TH + en-US from the assembly
    assert review.hook_experiment_id is None  # no hooks: honest, not faked
    for ref in review.media:
        assert len(ref.sha256) == 64
