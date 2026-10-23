"""Runtime basics: cycles serve every queue, slots cap, handlers dispatch (T028)."""

from __future__ import annotations

from microdrama.contracts.enums import QueueName
from microdrama.workers import counting_handler


class TestCycles:
    def test_cycle_serves_every_reserved_queue(self, world):
        post_job = world.enqueue_post_job()
        event_job = world.enqueue_event_job()
        world.create_effects_table()
        runtime = world.runtime(
            {
                "publish.poll_status": counting_handler({}, "poll"),
                "community.ingest_event": counting_handler({}, "ingest"),
            }
        )
        report = runtime.run_cycle()
        executed = {r.job_id for r in report.reports if r.action == "EXECUTED"}
        assert executed == {post_job, event_job}
        assert set(report.idle_queues) == {QueueName.PRODUCTION}

    def test_slots_cap_each_queue_per_cycle(self, world):
        for _ in range(6):
            world.enqueue_event_job()
        runtime = world.runtime(
            {"community.ingest_event": counting_handler({}, "ingest")}, community=2
        )
        report = runtime.run_cycle()
        community_reports = [r for r in report.reports if r.queue is QueueName.COMMUNITY]
        assert len(community_reports) == 2  # the reservation, not the backlog, caps the cycle

    def test_run_cycles_drains_until_idle(self, world):
        for _ in range(5):
            world.enqueue_event_job()
        counter: dict[str, int] = {}
        runtime = world.runtime(
            {"community.ingest_event": counting_handler(counter, "ingest")}, community=2
        )
        cycles = runtime.run_cycles()
        assert counter["ingest"] == 5
        assert cycles[-1].idle_queues == (
            QueueName.PRODUCTION,
            QueueName.PUBLICATION,
            QueueName.COMMUNITY,
        )

    def test_an_unreserved_queue_is_never_served(self, world):
        world.enqueue_post_job()
        runtime = world.runtime({}, publication=0)  # this deployment reserves no publication slot
        report = runtime.run_cycle()
        assert report.reports == ()
        row = world.job_row(world.enqueue_post_job())  # durable, never claimed
        assert row["status"] == "QUEUED"

    def test_a_zero_slot_declaration_is_refused(self, world):
        # A reservation of zero is a configuration mistake, not "unreserved".
        import pytest

        from microdrama.contracts.errors import SchemaInvalid
        from microdrama.workers import QueueSlots

        with pytest.raises(SchemaInvalid):
            QueueSlots(QueueName.PUBLICATION, 0)


class TestDispatch:
    def test_handler_runs_and_finishes_succeeded(self, world):
        job_id = world.enqueue_event_job()
        counter: dict[str, int] = {}
        runtime = world.runtime({"community.ingest_event": counting_handler(counter, "k")})
        runtime.run_cycle()
        assert counter["k"] == 1
        assert world.job_row(job_id)["status"] == "SUCCEEDED"

    def test_missing_handler_fails_the_job_visibly(self, world):
        job_id = world.enqueue_event_job()
        runtime = world.runtime({})  # no handler registered for the type
        report = runtime.run_cycle()
        (one,) = report.reports
        assert one.action == "FAILED" and one.detail == "NO_HANDLER"
        assert world.job_row(job_id)["status"] == "FAILED"
        assert world.job_row(job_id)["error_code"] == "NO_HANDLER"

    def test_handler_exception_fails_the_attempt_not_the_worker(self, world):
        world.enqueue_event_job()

        def broken(context):
            raise RuntimeError("handler bug")

        runtime = world.runtime({"community.ingest_event": broken})
        report = runtime.run_cycle()  # must not raise
        (one,) = report.reports
        assert one.action == "FAILED" and one.detail == "RuntimeError"

    def test_unknown_job_type_never_reaches_the_runtime(self, world):
        # The frozen JobService refuses to enqueue unknown types; the runtime
        # therefore never sees a job outside JOB_SPECS.
        from microdrama.contracts.errors import SchemaInvalid
        from microdrama.contracts.jobs import CommunityEventRef

        with world.db.transaction() as tx:
            try:
                world.jobs.enqueue(
                    tx,
                    job_type="community.nonexistent",
                    semantic_key="nope",
                    payload=CommunityEventRef(community_event_id=world.ids.new_id()),
                )
            except SchemaInvalid:
                pass
            else:  # pragma: no cover
                raise AssertionError("unknown job type was accepted")
