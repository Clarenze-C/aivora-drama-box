"""Service-level tests (T015): state machine, claims, budget hook, typed refusals."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from editing_support import World

from microdrama.contracts.cost import PriceQuote
from microdrama.contracts.enums import BudgetCategory, PriceSource, PriceUnit
from microdrama.contracts.errors import Conflict, InvalidTransition, NotFound

pytestmark = pytest.mark.ffmpeg


def _transfer_price() -> PriceQuote:
    return PriceQuote(
        currency="USD",
        unit=PriceUnit.VIDEO_SECOND,
        unit_price_micro_usd=2_000,
        source=PriceSource.FAKE_SYNTHETIC,
        price_table_version="test-v1",
        as_of=datetime(2026, 10, 21, tzinfo=UTC),
    )


def test_assembly_moves_rendering_through_assembling_to_ai_review(world: World) -> None:
    episode_id, _season, assets = world.seed_prepared_episode(state="RENDERING")
    world.service.assemble_episode(episode_id, shot_assets=assets["shots"])
    assert world.episode_state(episode_id) == "AI_REVIEW"
    states = [e["to"] for e in world.events(episode_id, "episode.state_changed")]
    assert states == ["ASSEMBLING", "AI_REVIEW"]
    row = world.row("SELECT correlation_id FROM episodes WHERE id = %s", (episode_id,))
    assert row["correlation_id"] is None  # claim always released


def test_wrong_episode_state_is_a_typed_refusal(world: World) -> None:
    episode_id, _season, assets = world.seed_prepared_episode(state="REFERENCES")
    with pytest.raises(InvalidTransition, match="RENDERING"):
        world.service.assemble_episode(episode_id, shot_assets=assets["shots"])


def test_foreign_claim_is_a_typed_conflict(world: World) -> None:
    episode_id, _season, assets = world.seed_prepared_episode(state="RENDERING")
    token = uuid.uuid4()
    with world.db.transaction() as tx:
        tx.execute("UPDATE episodes SET correlation_id = %s WHERE id = %s", (token, episode_id))
    with pytest.raises(Conflict, match="already claimed"):
        world.service.assemble_episode(episode_id, shot_assets=assets["shots"])
    assert world.episode_state(episode_id) == "RENDERING"


def test_missing_script_is_typed_not_found(world: World) -> None:
    season_id, _scope = world.season()
    episode_id = world.episode(season_id, state="RENDERING")
    with pytest.raises(NotFound, match="no current script"):
        world.service.assemble_episode(episode_id, shot_assets={})


def test_unmeasured_line_blocks_assembly_typed(world: World) -> None:
    episode_id, _season, assets = world.seed_prepared_episode()
    script = world.service.script(episode_id)
    stripped = script.model_copy(
        update={
            "scenes": [
                scene.model_copy(
                    update={
                        "lines": [
                            line.model_copy(update={"actual_duration_ms": None})
                            for line in scene.lines
                        ]
                    }
                )
                for scene in script.scenes
            ]
        }
    )
    from microdrama.contracts.hashing import canonical_hash
    from microdrama.persistence import insert_row, jsonb

    with world.db.transaction() as tx:
        tx.execute(
            "UPDATE scripts SET status = 'SUPERSEDED' WHERE episode_id = %s AND status = 'CURRENT'",
            (episode_id,),
        )
        insert_row(
            tx,
            "scripts",
            {
                "id": uuid.uuid4(),
                "episode_id": episode_id,
                "version": 2,
                "canon_version": 1,
                "body": jsonb(stripped),
                "body_hash": canonical_hash(stripped),
                "status": "CURRENT",
            },
        )
    with pytest.raises(Conflict, match="no measured duration"):
        world.service.assemble_episode(episode_id, shot_assets=assets["shots"])
    assert world.episode_state(episode_id) == "RENDERING"


def test_budget_hook_holds_a_real_reservation_when_priced(world: World) -> None:
    from editing_support import World as WorldCls

    from microdrama.editing.config import EditingConfig

    priced = WorldCls(
        world.db,
        world.store,
        world.settings,
        world.clips,
        world.truth,
        config=EditingConfig(transfer_price=_transfer_price()),
    )
    episode_id, _season, assets = priced.seed_prepared_episode()
    outcome = priced.service.assemble_episode(episode_id, shot_assets=assets["shots"])
    assert len(outcome.reservation_ids) == 1
    rows = priced.rows(
        "SELECT category, state, closed_reason FROM reservations WHERE id = %s",
        (outcome.reservation_ids[0],),
    )
    assert rows[0]["category"] == BudgetCategory.CPU_STORAGE_TRANSFER.value
    # Local export billed nothing: the hold is released with an explicit reason.
    assert rows[0]["state"] == "RELEASED"
    assert rows[0]["closed_reason"]
    assert outcome.settled_micro_usd == 0
    assert outcome.uncertainty_notes == []  # a paid step existed; no "free" note claimed


def test_budget_hook_is_idle_by_default(world: World) -> None:
    episode_id, _season, assets = world.seed_prepared_episode()
    outcome = world.service.assemble_episode(episode_id, shot_assets=assets["shots"])
    assert outcome.reservation_ids == []
    count = world.row("SELECT COUNT(*) AS n FROM reservations", ())["n"]
    assert count == 0
    assert outcome.uncertainty_notes == ["export pipeline is local ffmpeg; no paid step configured"]


def test_assembly_event_carries_the_evidence_summary(world: World) -> None:
    episode_id, _season, assets = world.seed_prepared_episode()
    outcome = world.service.assemble_episode(episode_id, shot_assets=assets["shots"])
    events = world.events(episode_id, "editing.assembled")
    assert len(events) == 1
    payload = events[0]
    assert payload["edl_version"] == outcome.edl_version
    assert payload["clean_asset_id"] == str(outcome.clean_asset_id)
    assert set(payload["caption_track_ids"]) == {str(t) for t in outcome.caption_track_ids}
    assert payload["check_failures"] == []
    assert payload["font_ok"] is True


def test_exports_are_derived_local_assets_with_full_lineage(world: World) -> None:
    episode_id, season_id, assets = world.seed_prepared_episode()
    outcome = world.service.assemble_episode(episode_id, shot_assets=assets["shots"])
    master = world.row(
        "SELECT descriptor, provenance, state FROM assets WHERE id = %s",
        (outcome.clean_asset_id,),
    )
    assert master["provenance"] == "DERIVED_LOCAL"
    assert master["state"] == "ACCEPTED"
    lineage = set(master["descriptor"]["lineage"])
    expected = {str(a) for a in assets["shots"].values()} | {
        str(a) for a in assets["lines"].values()
    }
    assert expected <= lineage  # every source the cut came from is named
    # ...and the caption SRT assets derive from exactly the line audio.
    for track_id in outcome.caption_track_ids:
        row = world.row("SELECT asset_id FROM caption_tracks WHERE id = %s", (track_id,))
        srt = world.row("SELECT descriptor FROM assets WHERE id = %s", (row["asset_id"],))
        assert {str(a) for a in assets["lines"].values()} <= set(srt["descriptor"]["lineage"])
    del season_id


def test_reservation_expiry_is_bounded(world: World) -> None:
    # The hook's exposure ceilings must bound the worst case by the EDL duration.
    from microdrama.editing import EditingConfig

    config = EditingConfig(transfer_price=_transfer_price())
    assert config.reservation_ttl_ms <= 900_000
    assert config.ffmpeg_timeout_ms >= 1_000
    assert timedelta(milliseconds=config.reservation_ttl_ms) >= timedelta(minutes=10)
