"""The rate gate: deferrals without handler runs, retries re-acquire (T028)."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from workers_support import WorkersWorld

from microdrama.contracts.errors import SchemaInvalid
from microdrama.contracts.jobs import PlatformPostRef
from microdrama.workers import counting_handler

BINDINGS = {
    "publish.poll_status": "platform_post_id",
    "community.optimize_metadata": "platform_post_id",
}


def _bound_post(world: WorkersWorld, job_type: str, key: UUID) -> UUID:
    """Enqueue ``job_type`` whose input field carries the shared-bucket key."""
    return world.enqueue(job_type, PlatformPostRef(platform_post_id=key))


class TestDeferral:
    def test_denial_defers_without_running_the_handler(self, world):
        key = world.ids.new_id()
        world.limiter.set_limit(str(key), capacity=1, refill_per_second=1)
        world.limiter.try_acquire(str(key))  # the bucket is now empty
        job = _bound_post(world, "publish.poll_status", key)

        counter: dict[str, int] = {}
        runtime = world.runtime(
            {"publish.poll_status": counting_handler(counter, "poll")},
            limiter=world.limiter,
            bindings={"publish.poll_status": "platform_post_id"},
        )
        report = runtime.run_cycle()
        (one,) = report.reports
        assert one.action == "RATE_DEFERRED" and one.detail == "RATE_LIMITED"
        assert counter == {}  # the handler never ran
        row = world.job_row(job)
        assert row["status"] == "RETRY_WAIT"
        assert row["run_after"] > world.clock.now()

    def test_retry_after_is_the_limiters_own_wait(self, world):
        key = world.ids.new_id()
        world.limiter.set_limit(str(key), capacity=1, refill_per_second=2)
        world.limiter.try_acquire(str(key))
        job = _bound_post(world, "publish.poll_status", key)
        runtime = world.runtime(
            {"publish.poll_status": counting_handler({}, "poll")},
            limiter=world.limiter,
            bindings={"publish.poll_status": "platform_post_id"},
        )
        runtime.run_cycle()
        row = world.job_row(job)
        assert row["status"] == "RETRY_WAIT"
        expected = world.clock.now() + timedelta(milliseconds=500)
        assert abs((row["run_after"] - expected).total_seconds()) < 0.001

    def test_refilled_token_lets_the_retry_run(self, world):
        key = world.ids.new_id()
        world.limiter.set_limit(str(key), capacity=1, refill_per_second=1)
        world.limiter.try_acquire(str(key))
        job = _bound_post(world, "publish.poll_status", key)
        counter: dict[str, int] = {}
        runtime = world.runtime(
            {"publish.poll_status": counting_handler(counter, "poll")},
            limiter=world.limiter,
            bindings={"publish.poll_status": "platform_post_id"},
        )
        runtime.run_cycle()  # deferred
        world.clock.advance(seconds=2)  # one token refilled; run_after is due
        runtime.run_cycle()
        assert counter["poll"] == 1
        assert world.job_row(job)["status"] == "SUCCEEDED"


class TestNoBypassOnRetry:
    def test_a_retry_reacquires_and_can_defer_again(self, world):
        """The deferred job re-acquires on every attempt; an empty bucket keeps
        deferring it. Rate-limit deferrals consume attempts by frozen job
        semantics — pinned here so the truth is visible, not hidden."""
        key = world.ids.new_id()
        world.limiter.set_limit(str(key), capacity=1, refill_per_second=1)
        world.limiter.try_acquire(str(key))
        job = _bound_post(world, "publish.poll_status", key)
        counter: dict[str, int] = {}
        runtime = world.runtime(
            {"publish.poll_status": counting_handler(counter, "poll")},
            limiter=world.limiter,
            bindings={"publish.poll_status": "platform_post_id"},
        )
        assert runtime.run_cycle().reports[0].action == "RATE_DEFERRED"

        # Freeze refill: the clock jumps to just past run_after with NO elapsed
        # real time for the bucket (set() moves the clock without refilling the
        # bucket's *elapsed* credit — the refill math uses clock-now, so instead
        # drain the refilled token explicitly and retry: still deferred.
        row = world.job_row(job)
        world.clock.set(row["run_after"] + timedelta(milliseconds=1))
        # the wait refilled exactly one token; spend it on something else so the
        # job's re-acquire finds an empty bucket again
        world.limiter.try_acquire(str(key))
        second = runtime.run_cycle()
        assert second.reports[0].action == "RATE_DEFERRED"  # re-acquired, still empty
        assert counter == {}

        world.clock.advance(seconds=2)  # refill + due
        runtime.run_cycle()
        assert counter["poll"] == 1
        assert world.job_row(job)["status"] == "SUCCEEDED"

    def test_rate_deferrals_consume_attempts_by_frozen_semantics(self, world):
        key = world.ids.new_id()
        world.limiter.set_limit(str(key), capacity=1, refill_per_second=1)
        world.limiter.try_acquire(str(key))
        job = _bound_post(world, "publish.poll_status", key)
        runtime = world.runtime(
            {"publish.poll_status": counting_handler({}, "poll")},
            limiter=world.limiter,
            bindings={"publish.poll_status": "platform_post_id"},
        )
        row = world.job_row(job)
        assert row["max_attempts"] == 3  # the frozen default
        # three deferral cycles with the bucket drained every time
        for _ in range(3):
            runtime.run_cycle()
            row = world.job_row(job)
            if row["status"] == "RETRY_WAIT":
                world.clock.set(row["run_after"] + timedelta(milliseconds=1))
                world.limiter.try_acquire(str(key))  # spend the refilled token
        assert row["status"] == "FAILED"  # visible, never silently dropped
        assert row["error_code"].endswith("RATE_LIMITED")

    def test_shared_key_serializes_across_queues(self, world):
        """A publication job and a community job on one provider account take
        turns through the same bucket (IMP-06: shared provider quota)."""
        key = world.ids.new_id()
        world.limiter.set_limit(str(key), capacity=1, refill_per_second=1)
        pub = _bound_post(world, "publish.poll_status", key)
        com = _bound_post(world, "community.optimize_metadata", key)
        counter: dict[str, int] = {}
        runtime = world.runtime(
            {
                "publish.poll_status": counting_handler(counter, "pub"),
                "community.optimize_metadata": counting_handler(counter, "com"),
            },
            limiter=world.limiter,
            bindings=BINDINGS,
        )
        first = runtime.run_cycle()
        assert sorted(r.action for r in first.reports) == ["EXECUTED", "RATE_DEFERRED"]
        world.clock.advance(seconds=2)  # refill + due
        second = runtime.run_cycle()
        assert [r.action for r in second.reports] == ["EXECUTED"]
        assert sorted(counter) == ["com", "pub"]
        assert world.job_row(pub)["status"] == "SUCCEEDED"
        assert world.job_row(com)["status"] == "SUCCEEDED"

    def test_missing_binding_field_is_a_deployment_error(self, world):
        world.enqueue_event_job()
        runtime = world.runtime(
            {"community.ingest_event": counting_handler({}, "k")},
            limiter=world.limiter,
            bindings={"community.ingest_event": "account_ref"},  # not in CommunityEventRef
        )
        try:
            runtime.run_cycle()
        except SchemaInvalid:
            pass
        else:  # pragma: no cover
            raise AssertionError("a broken binding must fail loudly, not skip throttling")
