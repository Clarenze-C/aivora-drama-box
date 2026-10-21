"""Episode writing: plan/script/manifest persistence, timings, replay, prerequisites."""

from __future__ import annotations

import uuid

import pytest
from story_support import World, canonical_writer_output

from microdrama.contracts.errors import Conflict, IdentityLockRequired, NotFound
from microdrama.contracts.season import EpisodePlan, Script, ShotManifest
from microdrama.story import WriteStatus, estimate_line_ms


def _ready(world: World, *, number: int = 1, identity_lock_id: uuid.UUID | None = None):
    season_id, scope = world.season()
    world.service.compile_season(season_id)
    episode_id = world.episode(season_id, scope, number=number, identity_lock_id=identity_lock_id)
    return episode_id, season_id, scope


def test_happy_write_persists_plan_script_and_manifest(world: World) -> None:
    episode_id, _season_id, _scope = _ready(world)
    outcome = world.service.write_episode(episode_id)

    assert outcome.status is WriteStatus.CURRENT
    assert outcome.script_version == 1
    assert outcome.settled_micro_usd > 0
    assert outcome.rounds_used == 1

    script_row = world.row("SELECT body, status FROM scripts WHERE episode_id = %s", (episode_id,))
    manifest_row = world.row(
        "SELECT body, status FROM shot_manifests WHERE episode_id = %s", (episode_id,)
    )
    assert script_row["status"] == "CURRENT"
    assert manifest_row["status"] == "CURRENT"
    script = Script.model_validate(script_row["body"])
    manifest = ShotManifest.model_validate(manifest_row["body"])
    assert manifest.script_id == script.script_id

    episode = world.row("SELECT * FROM episodes WHERE id = %s", (episode_id,))
    assert episode["state"] == "SCRIPTING"
    assert episode["current_script_id"] == script.script_id
    assert episode["current_manifest_id"] == manifest.manifest_id
    assert episode["plan"] is not None
    plan = EpisodePlan.model_validate(episode["plan"])
    assert plan.episode_number == 1
    assert plan.featured_character_ids == ["fon", "lek", "nok"]
    assert plan.location_ids == ["shophouse-room", "stall"]
    assert 180_000 <= plan.target_duration_ms <= 300_000
    events = world.events(episode_id, "story.script_written")
    assert len(events) == 1 and events[0]["settled_micro_usd"] == outcome.settled_micro_usd


def test_exact_thai_lines_and_translations_are_persisted(world: World) -> None:
    episode_id, _season_id, _scope = _ready(world)
    world.service.write_episode(episode_id)
    script = world.service.script(episode_id)
    draft_lines = [ln for scene in canonical_writer_output()["scenes"] for ln in scene["lines"]]

    persisted = [ln for sc in script.scenes for ln in sc.lines]
    assert len(persisted) == len(draft_lines)
    # Order-independent check: every exact Thai line and its translation survive verbatim.
    thai_pairs = {(ln.text_th, ln.text_en) for ln in persisted}
    expected = {(raw["text_th"], raw["text_en"]) for raw in draft_lines}
    assert thai_pairs == expected
    # Critical terms (money/negation/name/date) ride along exactly.
    money = next(ln for ln in persisted if ln.line_id == "sc2-l1")
    assert [t.value_th for t in money.critical_terms] == ["ห้าหมื่นบาท"]
    assert money.critical_terms[0].kind.value == "MONEY"


def test_actual_timings_stay_unknown_until_measured(world: World) -> None:
    episode_id, _season_id, _scope = _ready(world)
    world.service.write_episode(episode_id)
    script = world.service.script(episode_id)
    for scene in script.scenes:
        for line in scene.lines:
            assert line.actual_duration_ms is None, "actual timing is unknown until measured"
            assert line.estimated_duration_ms == estimate_line_ms(line.text_th)
    manifest = world.service.manifest(episode_id)
    for shot in manifest.shots:
        assert 1_000 <= shot.target_duration_ms <= 15_000


def test_replay_returns_current_script_without_new_paid_work(world: World) -> None:
    episode_id, _season_id, _scope = _ready(world)
    first = world.service.write_episode(episode_id)
    calls_after_first = world.generate_calls()
    second = world.service.write_episode(episode_id)

    assert second.status is WriteStatus.REPLAYED
    assert second.script_id == first.script_id
    assert second.settled_micro_usd == 0
    assert world.generate_calls() == calls_after_first
    assert world.count("SELECT COUNT(*) FROM scripts WHERE episode_id = %s", (episode_id,)) == 1


def test_write_requires_the_compiled_bible_first(world: World) -> None:
    season_id, scope = world.season()
    episode_id = world.episode(season_id, scope)
    with pytest.raises(Conflict, match="bible"):
        world.service.write_episode(episode_id)
    assert world.generate_calls() == 0
    assert world.row("SELECT state FROM episodes WHERE id = %s", (episode_id,))["state"] == (
        "PLANNED"
    )


def test_later_episode_requires_the_identity_lock_before_any_dispatch(world: World) -> None:
    episode_id, _season_id, _scope = _ready(world, number=2, identity_lock_id=None)
    with pytest.raises(IdentityLockRequired):
        world.service.write_episode(episode_id)
    assert world.generate_calls() == 0, "IMP-01: refused before any paid dispatch"


def test_later_episode_with_lock_carries_it_into_the_manifest(world: World) -> None:
    lock_id = uuid.uuid4()
    episode_id, _season_id, _scope = _ready(world, number=2, identity_lock_id=lock_id)
    outcome = world.service.write_episode(episode_id)
    assert outcome.status is WriteStatus.CURRENT
    manifest = world.service.manifest(episode_id)
    assert manifest.identity_lock_id == lock_id


def test_episode_without_an_arc_beat_gets_a_typed_uncertainty_note(world: World) -> None:
    # The example scope has arc beats for episodes 1-2 only.
    episode_id, _season_id, _scope = _ready(world, number=5, identity_lock_id=uuid.uuid4())
    outcome = world.service.write_episode(episode_id)
    assert outcome.status is WriteStatus.CURRENT
    assert any("no approved arc beat" in note for note in outcome.uncertainty_notes)


def test_write_on_missing_episode_is_typed_not_found(world: World) -> None:
    with pytest.raises(NotFound):
        world.service.write_episode(uuid.uuid4())


def test_episode_moved_during_writing_is_a_typed_conflict(world: World) -> None:
    episode_id, _season_id, _scope = _ready(world)
    original_generate = world.llm.generate

    def moving_generate(request):
        # The episode is pushed past SCRIPTING while the writer call is in flight.
        with world.db.transaction() as tx:
            tx.execute("UPDATE episodes SET state = 'REFERENCES' WHERE id = %s", (episode_id,))
        return original_generate(request)

    world.llm.generate = moving_generate  # type: ignore[method-assign]
    from microdrama.contracts.errors import Conflict as TypedConflict

    with pytest.raises(TypedConflict, match="moved to"):
        world.service.write_episode(episode_id)
    assert (
        world.row("SELECT correlation_id FROM episodes WHERE id = %s", (episode_id,))[
            "correlation_id"
        ]
        is None
    ), "failed write released its claim"
    # The spend of the dispatched call is retained, never refunded.
    assert sum(c["amount_micro_usd"] for c in world.episode_charges(episode_id)) > 0
