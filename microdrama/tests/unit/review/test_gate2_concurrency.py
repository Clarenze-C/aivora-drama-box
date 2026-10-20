"""Concurrent decisions on the real database: the approval runs exactly once."""

import threading

import pytest
from review_support import World

from microdrama.contracts.errors import MicrodramaError, StaleRevision

pytestmark = pytest.mark.db


def _race(workers: int, call) -> list[object]:
    """Start ``workers`` threads at once; return each outcome (a value or the raised error)."""
    barrier = threading.Barrier(workers)
    outcomes: list[object] = [None] * workers

    def run(index: int) -> None:
        barrier.wait()
        try:
            outcomes[index] = call(index)
        except MicrodramaError as exc:  # contract errors are the expected losing outcomes
            outcomes[index] = exc

    threads = [threading.Thread(target=run, args=(i,)) for i in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert all(not thread.is_alive() for thread in threads)
    return outcomes


def test_two_approvals_with_different_keys_only_one_is_recorded(world: World) -> None:
    _season, episode_id, package = world.ready_episode()
    human = world.human()
    commands = [world.gate2_command(episode_id, package) for _ in range(2)]

    outcomes = _race(2, lambda i: world.service.decide_episode(human, episode_id, commands[i]))

    winners = [o for o in outcomes if not isinstance(o, MicrodramaError)]
    losers = [o for o in outcomes if isinstance(o, MicrodramaError)]
    assert len(winners) == 1 and winners[0].status_code == 202
    assert len(losers) == 1 and isinstance(losers[0], StaleRevision)
    assert len(world.approvals(episode_id)) == 1
    assert len(world.jobs_of("publish.schedule_release")) == 1
    assert world.episode_state(episode_id)[0] == "RELEASE_APPROVED"


def test_one_key_sent_twice_at_once_runs_the_action_once(world: World) -> None:
    _season, episode_id, package = world.ready_episode()
    human = world.human()
    command = world.gate2_command(episode_id, package)

    outcomes = _race(2, lambda _i: world.service.decide_episode(human, episode_id, command))

    assert all(not isinstance(o, MicrodramaError) for o in outcomes), outcomes
    replayed = sorted(o.replayed for o in outcomes)
    assert replayed == [False, True]
    assert len({o.body["job_id"] for o in outcomes}) == 1
    assert len(world.approvals(episode_id)) == 1
    assert len(world.jobs_of("publish.schedule_release")) == 1


def test_gate1_double_submit_is_also_single_effect(world: World) -> None:
    season_id, scope = world.season(approved=False)
    from microdrama.contracts.hashing import canonical_hash

    human = world.human()
    command = world.gate1_command(season_id, canonical_hash(scope), 0)
    outcomes = _race(2, lambda _i: world.service.decide_season(human, season_id, command))
    assert all(not isinstance(o, MicrodramaError) for o in outcomes), outcomes
    assert len(world.approvals(season_id)) == 1
    assert len(world.jobs_of("story.compile_season")) == 1
