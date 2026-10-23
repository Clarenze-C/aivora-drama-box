"""Initial one-episode GPU ownership at the queue level (T028, IMP-01/IMP-06)."""

from __future__ import annotations

from uuid import uuid4

from microdrama.workers import counting_handler


class TestEpisodeGpuOwnership:
    def test_second_render_of_the_same_episode_defers(self, world):
        episode = uuid4()
        world.enqueue("render.shot", world.render_request(episode), episode_id=episode)
        second = world.enqueue(
            "render.shot",
            world.render_request(episode, shot="shot-2"),
            episode_id=episode,
        )
        # Simulate another worker holding the first render mid-flight (lease
        # claimed, RUNNING, not finished) — exactly the state a second worker
        # would see.
        world.jobs.claim("production", worker_id="gpu-worker-a", lease_ms=60_000)

        runtime = world.runtime({"render.shot": counting_handler({}, "render")})
        report = runtime.run_cycle()
        by_job = {r.job_id: r for r in report.reports}
        assert by_job[second].action == "GPU_DEFERRED"
        assert by_job[second].detail == "GPU_EPISODE_BUSY"
        row = world.job_row(second)
        assert row["status"] == "RETRY_WAIT"

    def test_a_different_episode_renders_freely(self, world):
        episode_a = uuid4()
        episode_b = uuid4()
        world.enqueue("render.shot", world.render_request(episode_a), episode_id=episode_a)
        job_b = world.enqueue("render.shot", world.render_request(episode_b), episode_id=episode_b)
        world.jobs.claim("production", worker_id="gpu-worker-a", lease_ms=60_000)

        counter: dict[str, int] = {}
        runtime = world.runtime({"render.shot": counting_handler(counter, "render")})
        report = runtime.run_cycle()
        by_job = {r.job_id: r for r in report.reports}
        assert by_job[job_b].action == "EXECUTED"
        assert counter["render"] == 1

    def test_non_gpu_jobs_of_the_same_episode_are_not_blocked(self, world):
        episode = uuid4()
        world.enqueue("render.shot", world.render_request(episode), episode_id=episode)
        qa_job = world.enqueue_episode_job("qa.technical", episode_id=episode)
        world.jobs.claim("production", worker_id="gpu-worker-a", lease_ms=60_000)

        counter: dict[str, int] = {}
        runtime = world.runtime(
            {
                "render.shot": counting_handler(counter, "render"),
                "qa.technical": counting_handler(counter, "qa"),
            },
            production=2,
        )
        report = runtime.run_cycle()
        by_job = {r.job_id: r for r in report.reports}
        assert by_job[qa_job].action == "EXECUTED"

    def test_finished_renders_release_the_episode(self, world):
        episode = uuid4()
        first = world.enqueue("render.shot", world.render_request(episode), episode_id=episode)
        second = world.enqueue(
            "render.shot",
            world.render_request(episode, shot="shot-2"),
            episode_id=episode,
        )
        runtime = world.runtime({"render.shot": counting_handler({}, "render")}, production=1)
        first_cycle = runtime.run_cycle()  # first render runs and finishes
        assert [r.action for r in first_cycle.reports] == ["EXECUTED"]
        assert world.job_row(first)["status"] == "SUCCEEDED"
        second_cycle = runtime.run_cycle()  # nothing RUNNING anymore
        assert [r.action for r in second_cycle.reports] == ["EXECUTED"]
        assert world.job_row(second)["status"] == "SUCCEEDED"
