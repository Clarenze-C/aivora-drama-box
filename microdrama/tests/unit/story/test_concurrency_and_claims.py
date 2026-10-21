"""Concurrency: exactly one paid writer per episode; stale-claim recovery (T010)."""

from __future__ import annotations

import threading

import pytest
from story_support import World

from microdrama.contracts.errors import Conflict
from microdrama.story import WriteStatus


def _ready(world: World):
    season_id, scope = world.season()
    world.service.compile_season(season_id)
    episode_id = world.episode(season_id, scope)
    return episode_id


def test_concurrent_writers_dispatch_exactly_one(world: World) -> None:
    """Two racing writes on one episode: one full paid run, one typed refusal."""
    episode_id = _ready(world)
    barrier = threading.Barrier(3)
    results: list[object] = []
    errors: list[BaseException] = []

    def run() -> None:
        barrier.wait()
        try:
            results.append(world.service.write_episode(episode_id))
        except BaseException as exc:  # noqa: BLE001 - collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    assert len(errors) == 1 and isinstance(errors[0], Conflict)
    assert "already claimed" in str(errors[0])
    assert len(results) == 1
    outcome = results[0]
    assert isinstance(outcome, object) and getattr(outcome, "status", None) is WriteStatus.CURRENT
    # Exactly one paid pipeline ran: writer + critic = 2 model calls.
    assert world.generate_calls() == 2
    assert world.count("SELECT COUNT(*) FROM scripts WHERE episode_id = %s", (episode_id,)) == 1
    # The winner released its claim on success.
    assert (
        world.row("SELECT correlation_id FROM episodes WHERE id = %s", (episode_id,))[
            "correlation_id"
        ]
        is None
    )


def test_stale_claim_from_a_crash_blocks_then_recovers(world: World) -> None:
    """A hard crash can leave the write claim behind: blocked writes until it is cleared
    with a reason (documented recovery gap, mirroring T009's RUNNING-run row)."""
    episode_id = _ready(world)
    with world.db.transaction() as tx:
        tx.execute(
            "UPDATE episodes SET correlation_id = %s WHERE id = %s",
            ("a3f6f8e2-0000-4000-8000-000000000001", episode_id),
        )

    with pytest.raises(Conflict, match="already claimed"):
        world.service.write_episode(episode_id)
    assert world.generate_calls() == 0

    from microdrama.contracts.errors import SchemaInvalid

    with pytest.raises(SchemaInvalid):  # a blank reason is refused
        world.service.clear_write_claim(episode_id, reason="   ")
    world.service.clear_write_claim(episode_id, reason="recovered after worker crash")
    outcome = world.service.write_episode(episode_id)
    assert outcome.status is WriteStatus.CURRENT


def test_clear_claim_refuses_when_a_current_script_exists(world: World) -> None:
    episode_id = _ready(world)
    assert world.service.write_episode(episode_id).status is WriteStatus.CURRENT
    with pytest.raises(Conflict, match="current script"):
        world.service.clear_write_claim(episode_id, reason="nothing to clear")
