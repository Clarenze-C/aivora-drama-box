"""The independently scheduled janitor and crash-resume durability (T028)."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from workers_support import WorkersWorld

from microdrama.workers import (
    JanitorStep,
    WorkersJanitor,
    build_janitor,
    effect_once_handler,
)


def _janitor(world: WorkersWorld) -> WorkersJanitor:
    return build_janitor(world.db, world.jobs, world.budget, world.clock, world.ids)


class TestSweep:
    def test_sweep_requeues_an_expired_lease(self, world):
        job_id = world.enqueue_event_job()
        world.jobs.claim("community", worker_id="dead-worker", lease_ms=1_000)
        world.clock.advance(seconds=5)  # the lease is long gone
        report = _janitor(world).sweep()
        requeue = [step for step in report.steps if step.name == "requeue_expired"]
        assert requeue and requeue[0].done == 1
        assert world.job_row(job_id)["status"] == "QUEUED"  # durable work resumes

    def test_sweep_reports_depths_and_appends_evidence(self, world):
        for _ in range(3):
            world.enqueue_event_job()
        world.enqueue_post_job()
        report = _janitor(world).sweep()
        assert report.queue_depths["community"] == 3
        assert report.queue_depths["publication"] == 1
        assert report.queue_depths["production"] == 0
        with world.db.transaction(readonly=True) as tx:
            events = tx.fetchall(
                "SELECT * FROM domain_events WHERE event_type = 'workers.janitor.swept'"
            )
        assert len(events) == 1
        assert events[0]["payload"]["queue_depths"]["community"] == 3

    def test_quarantined_jobs_are_listed_not_requeued(self, world):
        """An expired lease whose provider operation is in flight goes to
        NEEDS_RECONCILIATION (frozen job-service semantics); the janitor's job
        is to surface it, never to rerun it blindly."""
        from microdrama.contracts.enums import JobStatus
        from microdrama.persistence.db import insert_row

        job_id = world.enqueue_event_job()
        world.jobs.claim("community", worker_id="dead-worker", lease_ms=1_000)
        with world.db.transaction() as tx:
            insert_row(
                tx,
                "provider_operations",
                {
                    "id": uuid4(),
                    "provider": "youtube",
                    "operation_kind": "publish.poll_status",  # a job-linked unmetered kind (migration 0016)
                    "client_token": f"ct-{uuid4().hex[:8]}",
                    "request_hash": "b" * 64,
                    "job_id": job_id,
                    "state": "SUBMITTED",
                    "attempt": 1,
                    "deadline_at": world.clock.now() + timedelta(minutes=5),
                },
            )
        world.clock.advance(seconds=5)
        report = _janitor(world).sweep()
        assert report.quarantined and report.quarantined[0]["job_id"] == str(job_id)
        assert world.job_row(job_id)["status"] == JobStatus.NEEDS_RECONCILIATION.value

    def test_a_step_failure_does_not_block_the_rest(self, world):
        janitor = _janitor(world)

        def broken() -> int:
            raise RuntimeError("step blew up")

        # _step only traps MicrodramaError by contract; a hard crash in a step
        # is a bug — pin that telemetry still ran by calling sweep with one
        # broken constituent replaced.
        original = janitor._step  # noqa: SLF001
        janitor._step = lambda name, action: (  # noqa: SLF001
            JanitorStep(name=name, done=0, error="synthetic failure")
            if name == "requeue_expired"
            else original(name, action)
        )
        report = janitor.sweep()
        janitor._step = original  # noqa: SLF001
        assert report.steps[0].error == "synthetic failure"
        assert report.queue_depths != {}  # the rest of the sweep still happened
        assert report.to_dict()["failures"] == 1


class TestCrashResume:
    def test_crashed_job_resumes_with_one_durable_effect(self, world):
        """Effect exactly once across a crash: the handler runs, the worker
        dies before finish, the janitor requeues, the retry replays idempotently."""
        world.create_effects_table()
        job_id = world.enqueue_event_job()
        handler = effect_once_handler(
            world.db,
            table="worker_effects",
            effect_key_column="effect_key",
            effect_key="the-effect",
        )
        runtime = world.runtime({"community.ingest_event": handler})

        # First run executes the effect... then the worker "crashes": finish the
        # claim without an outcome by simply never finishing — simulate by
        # claiming manually, running the handler body, and abandoning the lease.
        job = world.jobs.claim("community", worker_id="doomed", lease_ms=1_000)
        assert job is not None and job.id == job_id
        context = world.jobs.context(job, "doomed")
        outcome = handler(context)  # the effect is durably written here
        assert outcome.result["replayed"] is False
        # (no finish: the process died right after the effect)

        world.clock.advance(seconds=5)  # the lease expires
        _janitor(world).sweep()  # requeues the abandoned job
        assert world.job_row(job_id)["status"] == "QUEUED"

        second = runtime.run_cycle()
        assert [r.action for r in second.reports] == ["EXECUTED"]
        assert world.job_row(job_id)["status"] == "SUCCEEDED"
        rows = world.effect_rows()
        assert len(rows) == 1  # exactly one durable effect, not two
