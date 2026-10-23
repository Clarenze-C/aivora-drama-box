"""T030-02a regression: the runner's drain must fail the stage on FAILED jobs.

The accepted T029 pilot reported W06 OK with a FAILED variants/hooks job and
exited 0 because ``_drain`` never inspected job outcomes. These tests pin the
fix: a terminal FAILED job raises from ``_drain`` with the job type and detail,
and a clean drain stays silent.
"""

from __future__ import annotations

import uuid

import pytest

from microdrama.contracts.jobs import EpisodeStepInput
from microdrama.pipeline.runner import MockPipelineRunner

pytestmark = [pytest.mark.db, pytest.mark.slow]


def _enqueue(world, job_type: str, payload, *, episode_id=None) -> None:
    with world.db.transaction() as tx:
        world.jobs.enqueue(
            tx,
            job_type=job_type,
            semantic_key=f"{job_type}:t30-drain:{uuid.uuid4().hex[:8]}",
            payload=payload,
            episode_id=episode_id,
        )


def test_drain_raises_on_a_terminal_failed_job(world) -> None:
    runner = MockPipelineRunner(world)
    # A write job for an episode that does not exist fails terminally
    # (non-transient NotFound), which the drain must surface — never swallow.
    missing = uuid.uuid4()
    _enqueue(
        world,
        "story.write_episode",
        EpisodeStepInput(episode_id=missing),
        episode_id=missing,
    )
    with pytest.raises(RuntimeError, match="FAILED job"):
        runner._drain()


def test_clean_drain_stays_silent_and_counts(world) -> None:
    runner = MockPipelineRunner(world)
    stats = runner._drain()  # nothing enqueued: idle immediately, no raise
    assert stats == {"jobs_executed": 0}
