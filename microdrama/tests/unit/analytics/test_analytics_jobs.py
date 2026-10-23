"""Analytics job handlers: due windows wait honestly, runs ride the community queue (T027)."""

from __future__ import annotations

import uuid

from analytics_support import AnalyticsWorld

from microdrama.analytics import analytics_handlers
from microdrama.contracts.enums import QueueName, SnapshotWindow
from microdrama.contracts.jobs import MetricWindowInput, SeasonStepInput
from microdrama.core.jobs import Failed, JobService, Succeeded, WaitExternal


class TestSnapshotHandler:
    def _enqueue(self, world: AnalyticsWorld, payload) -> uuid.UUID:
        jobs = JobService(world.db, world.clock, world.ids)
        with world.db.transaction() as tx:
            result = jobs.enqueue(
                tx,
                job_type="analytics.snapshot",
                semantic_key=f"analytics.snapshot:{uuid.uuid4()}",
                payload=payload,
            )
        return result.job_id

    def test_due_but_unrecorded_waits_for_provider_data(self, world):
        season = world.season()
        _episode, post = world.published_episode(season, number=2)
        world.clock.advance(ms=25 * 60 * 60 * 1000)  # past the H24 boundary
        handlers = analytics_handlers(world.analytics)
        job_id = self._enqueue(
            world,
            MetricWindowInput(platform_post_id=post["id"], window=SnapshotWindow.H24),
        )
        jobs = JobService(world.db, world.clock, world.ids)
        job = jobs.claim(QueueName.COMMUNITY, worker_id="w1", lease_ms=60_000)
        assert job is not None and job.id == job_id
        outcome = handlers["analytics.snapshot"](jobs.context(job, "w1"))
        # Boundary passed but nothing recorded: wait for provider-side data.
        assert isinstance(outcome, WaitExternal)

    def test_recorded_window_succeeds_with_summary(self, world):
        season = world.season()
        _episode, post = world.published_episode(season, number=2)
        world.analytics.record_snapshot(
            world.snapshot(
                post,
                window=SnapshotWindow.H24,
                observed_at_hours=25,
                metrics={"views": world.metric(321)},
            )
        )
        handlers = analytics_handlers(world.analytics)
        self._enqueue(
            world,
            MetricWindowInput(platform_post_id=post["id"], window=SnapshotWindow.H24),
        )
        jobs = JobService(world.db, world.clock, world.ids)
        job = jobs.claim(QueueName.COMMUNITY, worker_id="w1", lease_ms=60_000)
        outcome = handlers["analytics.snapshot"](jobs.context(job, "w1"))
        assert isinstance(outcome, Succeeded)
        assert outcome.result["status"] == "RECORDED"
        assert outcome.result["metrics"]["views"] == 321

    def test_early_window_fails_the_job_not_retries_it(self, world):
        season = world.season()
        _episode, post = world.published_episode(season, number=2)
        # clock still at T0: the H24 boundary (T0+24h) is in the future
        handlers = analytics_handlers(world.analytics)
        self._enqueue(
            world,
            MetricWindowInput(platform_post_id=post["id"], window=SnapshotWindow.H24),
        )
        jobs = JobService(world.db, world.clock, world.ids)
        job = jobs.claim(QueueName.COMMUNITY, worker_id="w1", lease_ms=60_000)
        outcome = handlers["analytics.snapshot"](jobs.context(job, "w1"))
        assert isinstance(outcome, Failed)
        assert "early" in outcome.detail or "boundary" in outcome.detail


class TestQualificationHandler:
    def test_run_succeeds_and_reports_counts(self, world):
        season = world.season()
        episode, _post = world.published_episode(season, number=2)
        world.charge(episode, 100_000)
        handlers = analytics_handlers(world.analytics)
        jobs = JobService(world.db, world.clock, world.ids)
        with world.db.transaction() as tx:
            result = jobs.enqueue(
                tx,
                job_type="analytics.qualification",
                semantic_key=f"analytics.qualification:{uuid.uuid4()}",
                payload=SeasonStepInput(season_id=season),
            )
        job = jobs.claim(QueueName.COMMUNITY, worker_id="w1", lease_ms=60_000)
        assert job is not None and job.id == result.job_id
        outcome = handlers["analytics.qualification"](jobs.context(job, "w1"))
        assert isinstance(outcome, Succeeded)
        assert outcome.result["successful_episodes"] == 1
        assert outcome.result["consecutive"] == 1


class TestQueueRouting:
    def test_analytics_jobs_live_on_the_community_queue_only(self, world):
        season = world.season()
        _episode, post = world.published_episode(season, number=2)
        jobs = JobService(world.db, world.clock, world.ids)
        with world.db.transaction() as tx:
            snap = jobs.enqueue(
                tx,
                job_type="analytics.snapshot",
                semantic_key=f"analytics.snapshot:{uuid.uuid4()}",
                payload=MetricWindowInput(platform_post_id=post["id"], window=SnapshotWindow.H24),
            )
            qual = jobs.enqueue(
                tx,
                job_type="analytics.qualification",
                semantic_key=f"analytics.qualification:{uuid.uuid4()}",
                payload=SeasonStepInput(season_id=season),
            )
        assert jobs.get(snap.job_id).queue is QueueName.COMMUNITY
        assert jobs.get(qual.job_id).queue is QueueName.COMMUNITY
        # The analytics jobs are claimable only on the community queue. (The
        # publication queue legitimately holds this episode's publish.schedule_release
        # job enqueued by Gate 2 — that is the T020 lane's routing, not ours.)
        assert jobs.claim(QueueName.PRODUCTION, worker_id="w1", lease_ms=1_000) is None
        claimed = jobs.claim(QueueName.COMMUNITY, worker_id="w1", lease_ms=1_000)
        assert claimed is not None and claimed.job_type.startswith("analytics.")
