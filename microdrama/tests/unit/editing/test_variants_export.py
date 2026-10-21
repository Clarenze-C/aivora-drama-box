"""Variant export tests (T016): real DB + store + local FFmpeg end-to-end.

The fixture episode is assembled through the REAL T015 service first; variants are
then re-cuts of that accepted master for a T006-recorded TikTok account. CPU is
bounded by ``max_export_duration_ms`` and the 5 s fixture clips exactly as in T015.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from editing_support import World
from test_variants_support import (
    TT_ACCOUNT,
    capability_record,
    record_capability,
    variants_service,
)

from microdrama.contracts.cost import PriceQuote
from microdrama.contracts.enums import BudgetCategory, Platform, PriceSource, PriceUnit
from microdrama.contracts.errors import NotFound
from microdrama.editing.config import EditingConfig
from microdrama.editing.variants_service import VariantTarget, build_variants_service

pytestmark = pytest.mark.ffmpeg


def _target() -> VariantTarget:
    return VariantTarget(platform=Platform.TIKTOK, account_ref=TT_ACCOUNT)


def _assembled(world: World):
    episode_id, _season, assets = world.seed_prepared_episode()
    world.service.assemble_episode(episode_id, shot_assets=assets["shots"])
    return episode_id, assets


def _transfer_price() -> PriceQuote:
    return PriceQuote(
        currency="USD",
        unit=PriceUnit.VIDEO_SECOND,
        unit_price_micro_usd=2_000,
        source=PriceSource.FAKE_SYNTHETIC,
        price_table_version="t016-v1",
        as_of=datetime(2026, 10, 21, tzinfo=UTC),
    )


def test_variant_exports_end_to_end_from_the_accepted_master(world: World) -> None:
    episode_id, assets = _assembled(world)
    record_capability(world, capability_record(ratios=("16:9",)))
    outcome = variants_service(world).build_variants(episode_id, targets=[_target()])
    assert outcome.status.value == "ASSEMBLED"
    assert outcome.blockers == []
    assert len(outcome.results) == 1
    result = outcome.results[0]
    assert result.variant_key == "tiktok-16x9"
    assert result.framing.cropped is True
    assert result.framing.lost_pixels == 360 * 640 - 360 * 202
    assert "16:9" in result.framing.detail
    # Durable rows: a variant EDL manifest pointing at a DERIVED_LOCAL asset.
    row = world.row(
        "SELECT edl, state, output_asset_id FROM edit_manifests WHERE id = %s", (result.edl_id,)
    )
    assert row is not None
    assert row["state"] == "RENDERED"
    assert row["output_asset_id"] == result.clean_asset_id
    asset = world.row(
        "SELECT descriptor, provenance, state FROM assets WHERE id = %s", (result.clean_asset_id,)
    )
    assert asset["provenance"] == "DERIVED_LOCAL"
    assert asset["state"] == "ACCEPTED"
    assert (asset["descriptor"]["media"]["width"], asset["descriptor"]["media"]["height"]) == (
        360,
        202,
    )
    expected_sources = {str(a) for a in assets["shots"].values()} | {
        str(a) for a in assets["lines"].values()
    }
    assert expected_sources <= set(asset["descriptor"]["lineage"])
    # Burned variant rides on the clean one (Thai font is present on this host).
    assert result.burned_asset_id is not None
    burned = world.row("SELECT descriptor FROM assets WHERE id = %s", (result.burned_asset_id,))
    assert burned["descriptor"]["lineage"] == [str(result.clean_asset_id)]
    # Event evidence and untouched production state.
    events = world.events(episode_id, "editing.variants_built")
    assert len(events) == 1
    assert events[0]["variant_keys"] == ["tiktok-16x9"]
    assert world.episode_state(episode_id) == "AI_REVIEW"
    claim = world.row("SELECT correlation_id FROM episodes WHERE id = %s", (episode_id,))
    assert claim["correlation_id"] is None


def test_missing_capability_record_is_a_typed_blocker(world: World) -> None:
    episode_id, _assets = _assembled(world)
    outcome = variants_service(world).build_variants(episode_id, targets=[_target()])
    assert outcome.results == []
    assert len(outcome.blockers) == 1
    assert "no current capability record" in outcome.blockers[0].reason
    rows = world.rows(
        "SELECT id FROM edit_manifests WHERE episode_id = %s AND variant_key <> 'main'",
        (episode_id,),
    )
    assert rows == []


def test_second_call_replays_without_re_export(world: World) -> None:
    episode_id, _assets = _assembled(world)
    record_capability(world, capability_record(ratios=("16:9",)))
    service = variants_service(world)
    first = service.build_variants(episode_id, targets=[_target()])
    second = service.build_variants(episode_id, targets=[_target()])
    assert second.status.value == "REPLAYED"
    assert second.results[0].replayed is True
    assert second.results[0].clean_asset_id == first.results[0].clean_asset_id
    assert second.results[0].clean_sha256 == first.results[0].clean_sha256
    rows = world.rows(
        "SELECT id FROM edit_manifests WHERE episode_id = %s AND variant_key = 'tiktok-16x9'",
        (episode_id,),
    )
    assert len(rows) == 1  # no duplicate manifest row on replay


def test_variant_content_is_addressed_across_identical_episodes(world: World) -> None:
    first_id, _a1 = _assembled(world)
    second_id, _a2 = _assembled(world)
    record_capability(world, capability_record(ratios=("16:9",)))
    service = variants_service(world)
    first = service.build_variants(first_id, targets=[_target()])
    second = service.build_variants(second_id, targets=[_target()])
    # Identical accepted footage re-cut identically -> identical derivative bytes,
    # even though the EDL ids differ (they are episode-scoped).
    assert first.results[0].edl_id != second.results[0].edl_id
    assert first.results[0].clean_sha256 == second.results[0].clean_sha256


def test_no_assembled_master_is_a_typed_not_found(world: World) -> None:
    season_id, _scope = world.season()
    episode_id = world.episode(season_id, state="AI_REVIEW")
    with pytest.raises(NotFound, match="no assembled master"):
        variants_service(world).build_variants(episode_id, targets=[_target()])


def test_variant_budget_hook_holds_a_real_reservation_when_priced(world: World) -> None:
    episode_id, _assets = _assembled(world)
    record_capability(world, capability_record(ratios=("16:9",)))
    priced = variants_service(world, config=EditingConfig(transfer_price=_transfer_price()))
    outcome = priced.build_variants(episode_id, targets=[_target()])
    assert len(outcome.reservation_ids) == 1
    row = world.row(
        "SELECT category, state, closed_reason FROM reservations WHERE id = %s",
        (outcome.reservation_ids[0],),
    )
    assert row["category"] == BudgetCategory.CPU_STORAGE_TRANSFER.value
    assert row["state"] == "RELEASED" and row["closed_reason"]
    assert outcome.settled_micro_usd == 0


def test_variant_budget_hook_is_idle_by_default(world: World) -> None:
    episode_id, _assets = _assembled(world)
    record_capability(world, capability_record(ratios=("16:9",)))
    outcome = variants_service(world).build_variants(episode_id, targets=[_target()])
    assert outcome.reservation_ids == []
    assert world.row("SELECT COUNT(*) AS n FROM reservations", ())["n"] == 0


def test_factory_signature_is_composition_root_friendly(world: World) -> None:
    service = build_variants_service(
        world.db,
        world.clock,
        world.ids,
        world.settings,
        budget=world.budget,
        store=world.store,
    )
    assert callable(service.build_variants)
    assert callable(service.derive_covers)
    assert callable(service.generate_hook_candidates)
    assert callable(service.final_review_media)
    assert service.config.output_width == 360
