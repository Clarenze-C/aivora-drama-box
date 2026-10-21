"""Season compilation: PLANNED canon, approved-scope binding, arc immutability (T010)."""

from __future__ import annotations

import pytest
from story_support import World, thai_reveal_scope

from microdrama.contracts.errors import Conflict, InvalidTransition, NotFound
from microdrama.story import CanonKind, FactKind


def test_compile_writes_planned_canon_and_seeds_characters(world: World) -> None:
    season_id, _scope = world.season()
    result = world.service.compile_season(season_id)

    assert result.replayed is False
    assert result.canon_version == 1
    row = world.row(
        "SELECT kind, version, facts, facts_hash FROM canon_versions WHERE season_id = %s",
        (season_id,),
    )
    assert row is not None and row["kind"] == "PLANNED" and row["version"] == 1
    assert row["facts_hash"] == result.facts_hash
    assert row["facts"]["bible"]["approved_scope_hash"] == result.bible.approved_scope_hash

    characters = world.rows(
        "SELECT character_key, state FROM characters WHERE season_id = %s ORDER BY character_key",
        (season_id,),
    )
    assert [c["character_key"] for c in characters] == ["fon", "lek", "nok"]
    assert all(c["state"] == "PROVISIONAL" for c in characters)
    assert world.events(season_id, "story.season_compiled"), "compile event missing"


def test_bible_facts_are_traceable_and_reveals_are_scheduled(world: World) -> None:
    season_id, _scope = world.season(scope=thai_reveal_scope())
    result = world.service.compile_season(season_id)
    bible = result.bible

    kinds = {f.kind for f in bible.facts}
    assert FactKind.PREMISE in kinds
    assert FactKind.CHARACTER in kinds
    assert FactKind.ARC_BEAT in kinds
    assert FactKind.PLANNED_REVEAL in kinds
    assert FactKind.CLIFFHANGER in kinds
    assert all(f.source_field for f in bible.facts), "every fact names its scope source field"

    reveal = next(f for f in bible.facts if f.kind is FactKind.PLANNED_REVEAL)
    assert reveal.episode_number == 2, "the co-sign reveal is scheduled for episode 2"
    assert bible.knowledge == [
        k for k in bible.knowledge if k.fact_key == reveal.fact_key and k.known_from_episode == 2
    ]
    assert bible.knowledge[0].fact_key == reveal.fact_key


def test_compile_is_idempotent_and_replays(world: World) -> None:
    season_id, _scope = world.season()
    first = world.service.compile_season(season_id)
    second = world.service.compile_season(season_id)
    assert second.replayed is True
    assert second.facts_hash == first.facts_hash
    assert (
        world.count("SELECT COUNT(*) FROM canon_versions WHERE season_id = %s", (season_id,)) == 1
    )


def test_compile_refuses_a_proposed_season(world: World) -> None:
    season_id, _scope = world.season(approved=False)
    with pytest.raises(InvalidTransition, match="PROPOSED"):
        world.service.compile_season(season_id)
    assert (
        world.count("SELECT COUNT(*) FROM canon_versions WHERE season_id = %s", (season_id,)) == 0
    )


def test_later_trend_evidence_cannot_silently_change_the_approved_arc(world: World) -> None:
    season_id, approved_scope = world.season()
    compiled = world.service.compile_season(season_id)
    original_arc = [b.summary for b in compiled.bible.arc]

    # Later research produces a NEW proposal (scope v2, different arc) — still PROPOSED.
    drifted = approved_scope.model_copy(
        update={
            "title_en": "River of Bigger Debts",
            "arc": [
                b.model_copy(update={"summary": f"drifted {b.summary}"}) for b in approved_scope.arc
            ],
        }
    )
    world.add_proposal(season_id, drifted, version=2, status="PROPOSED")

    # Recompiling the season replays the approved bible unchanged.
    replay = world.service.compile_season(season_id)
    assert replay.replayed is True
    assert [b.summary for b in replay.bible.arc] == original_arc
    # Asking to compile the later, unapproved version is a typed refusal.
    with pytest.raises(Conflict, match="cannot silently"):
        world.service.compile_season(season_id, scope_version=2)
    assert [b.summary for b in world.service.bible(season_id).arc] == original_arc


def test_compile_refuses_proposal_hash_drift(world: World) -> None:
    # The season row is bound to a hash the (approved) proposal no longer matches.
    season_id, _scope = world.season(season_scope_hash="f" * 64)
    with pytest.raises(Conflict, match="scope hash"):
        world.service.compile_season(season_id)


def test_compile_unknown_scope_version_is_typed_not_found(world: World) -> None:
    season_id, _scope = world.season()
    with pytest.raises(NotFound):
        world.service.compile_season(season_id, scope_version=99)


def test_planned_final_and_published_canon_stay_separate(world: World) -> None:
    season_id, _scope = world.season()
    world.service.compile_season(season_id)

    planned = world.service.canon_facts(season_id, CanonKind.PLANNED)
    assert len(planned) == 1 and "bible" in planned[0]
    assert world.service.canon_facts(season_id, CanonKind.FINAL_APPROVED) == []
    assert world.service.canon_facts(season_id, CanonKind.PUBLISHED) == []
    # The story module cannot mint final-approved or published canon, and PLANNED rows
    # come only from compile_season.
    from microdrama.contracts.errors import PolicyDenied

    for kind in ("PLANNED", "FINAL_APPROVED", "PUBLISHED"):
        with pytest.raises(PolicyDenied):
            world.service.write_canon(season_id, kind, {"facts": []})


def test_planned_canon_row_is_append_only(world: World) -> None:
    season_id, _scope = world.season()
    world.service.compile_season(season_id)
    with pytest.raises(Exception, match="append-only"):
        with world.db.transaction() as tx:
            tx.execute(
                "UPDATE canon_versions SET facts = '{\"tampered\": true}'::jsonb "
                "WHERE season_id = %s",
                (season_id,),
            )


def test_season_scope_hash_binds_bible_and_episode_writes(world: World) -> None:
    season_id, scope = world.season()
    world.service.compile_season(season_id)
    episode_id = world.episode(season_id, scope)
    # Rebind the episode to a different approved scope: a typed conflict, zero dispatch.
    with world.db.transaction() as tx:
        tx.execute(
            "UPDATE episodes SET approved_scope_hash = %s WHERE id = %s",
            ("e" * 64, episode_id),
        )
    with pytest.raises(Conflict, match="different approved scope"):
        world.service.write_episode(episode_id)
    assert world.generate_calls() == 0
