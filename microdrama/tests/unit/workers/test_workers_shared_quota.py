"""Durable shared quotas and lane capacity isolation (build-review F04/F05).

The limiter buckets live in PostgreSQL: separate limiter instances (separate
worker processes) and restarts share ONE allowance per provider account, and a
composed deployment that serves a provider-bound type without a binding refuses
to build. Lane-scoped deployments give production/publication/community
structurally separate capacity: a blocked community handler cannot delay a due
publication job past the declared bound, and the janitor stays independent.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from uuid import UUID

import pytest
from workers_support import WorkersWorld

from microdrama.contracts.enums import QueueName
from microdrama.contracts.errors import SchemaInvalid
from microdrama.contracts.jobs import PlatformPostRef
from microdrama.workers import (
    PostgresSharedRateLimiter,
    QueueSlots,
    WorkerDeployment,
    WorkerRuntime,
    counting_handler,
)

pytestmark = [pytest.mark.db]

T0 = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
KEY = "youtube:acct:fake-main"


class TestPostgresSharedRateLimiter:
    def test_separate_instances_share_one_allowance(self, world: WorkersWorld):
        first = PostgresSharedRateLimiter(world.db, world.clock, default_capacity=1)
        second = PostgresSharedRateLimiter(world.db, world.clock, default_capacity=1)
        first.set_limit(KEY, capacity=1, refill_per_second=1)
        assert first.try_acquire(KEY).allowed
        # A different process (instance) sees the SAME spent bucket — the old
        # in-process dictionaries each held an independent full allowance.
        assert not second.try_acquire(KEY).allowed

    def test_restart_keeps_the_bucket_state(self, world: WorkersWorld):
        before = PostgresSharedRateLimiter(world.db, world.clock, default_capacity=1)
        before.set_limit(KEY, capacity=1, refill_per_second=1)
        assert before.try_acquire(KEY).allowed
        after = PostgresSharedRateLimiter(world.db, world.clock, default_capacity=1)
        assert not after.try_acquire(KEY).allowed  # the restart did not reset quota
        row_after = after.try_acquire(KEY)
        assert not row_after.allowed
        assert row_after.retry_after_ms > 0  # with the real wait, not a refusal

    def test_refill_uses_the_clock_between_processes(self, world: WorkersWorld):
        limiter = PostgresSharedRateLimiter(world.db, world.clock, default_capacity=1)
        limiter.set_limit(KEY, capacity=1, refill_per_second=1)
        limiter.try_acquire(KEY)
        world.clock.advance(seconds=2)
        other = PostgresSharedRateLimiter(world.db, world.clock, default_capacity=1)
        assert other.try_acquire(KEY).allowed  # one token refilled for everyone


class TestProviderBoundBindingsRequired:
    def test_a_limited_deployment_serving_a_provider_bound_type_needs_a_binding(self, world):
        with pytest.raises(SchemaInvalid, match="provider-bound"):
            WorkerDeployment(
                name="incomplete",
                slots=(QueueSlots(QueueName.PUBLICATION, 1),),
                handlers={"publish.poll_status": counting_handler({}, "poll")},
                limiter=world.limiter,
            )

    def test_callable_bindings_compose_provider_account_keys(self, world):
        """A resolver composes the shared key from the job input; admission runs
        against that key exactly as a plain field binding would."""
        from microdrama.core.jobs import JobContext  # noqa: F401  (type context)

        def resolver(job) -> str:
            return f"youtube:{job.input['platform_post_id']}"

        key_post = "00000000-0000-0000-0000-0000000000b1"
        world.limiter.set_limit(f"youtube:{key_post}", capacity=1, refill_per_second=1)
        world.limiter.try_acquire(f"youtube:{key_post}")  # the shared bucket is spent
        deployment = WorkerDeployment(
            name="bound",
            slots=(QueueSlots(QueueName.PUBLICATION, 1),),
            handlers={"publish.poll_status": counting_handler({}, "poll")},
            limiter=world.limiter,
            bindings={"publish.poll_status": resolver},
        )
        runtime = WorkerRuntime(world.jobs, world.db, world.clock, deployment)
        with world.db.transaction() as tx:
            world.jobs.enqueue(
                tx,
                job_type="publish.poll_status",
                semantic_key="binding-composition:1",
                payload=PlatformPostRef(
                    platform_post_id=UUID("00000000-0000-0000-0000-0000000000b1")
                ),
            )
        report = runtime.run_cycle()
        assert report.reports[0].action == "RATE_DEFERRED"


class TestLaneIsolation:
    def test_blocked_community_does_not_delay_a_due_publication(self, world: WorkersWorld):
        """F05's acceptance: a community handler that blocks and a publication
        deadline that arrives — publication proceeds in its own lane within the
        declared bound, and the janitor-independent truth is untouched."""
        from microdrama.pipeline.deployments import LANE_ISOLATION_BOUND_MS

        release = threading.Event()
        ran: dict[str, int] = {}

        def blocked_community(ctx):
            ran["blocked_entered"] = ran.get("blocked_entered", 0) + 1
            release.wait(timeout=30)  # simulate the stuck provider call
            ran["blocked_finished"] = ran.get("blocked_finished", 0) + 1
            from microdrama.core.jobs import Succeeded

            return Succeeded(result={"after": "block"})

        def fast_publication(ctx):
            ran["publication"] = ran.get("publication", 0) + 1
            from microdrama.core.jobs import Succeeded

            return Succeeded(result={"on": "time"})

        community = WorkerRuntime(
            world.jobs,
            world.db,
            world.clock,
            WorkerDeployment(
                name="worker-community",
                slots=(QueueSlots(QueueName.COMMUNITY, 1),),
                handlers={"community.respond": blocked_community},
            ),
        )
        publication = WorkerRuntime(
            world.jobs,
            world.db,
            world.clock,
            WorkerDeployment(
                name="worker-publication",
                slots=(QueueSlots(QueueName.PUBLICATION, 1),),
                handlers={"publish.poll_status": fast_publication},
            ),
        )
        world.enqueue("community.respond", _community_action_payload())
        world.enqueue("publish.poll_status", PlatformPostRef(platform_post_id=world.ids.new_id()))

        community_thread = threading.Thread(target=community.run_cycle)
        started = time.monotonic()
        community_thread.start()
        while "blocked_entered" not in ran and time.monotonic() - started < 10:
            time.sleep(0.005)
        assert "blocked_entered" in ran, "the community handler must be inside its block"
        # The community handler is STILL blocked: publication must complete in
        # its own lane well inside the declared isolation bound.
        report = publication.run_cycle()
        elapsed_ms = (time.monotonic() - started) * 1000
        release.set()
        community_thread.join(timeout=10)
        assert report.reports and report.reports[0].action == "EXECUTED"
        assert ran["publication"] == 1
        assert ran.get("blocked_finished") == 1
        assert elapsed_ms < LANE_ISOLATION_BOUND_MS


def _community_action_payload():
    from uuid import uuid4

    from microdrama.contracts.release import ManagementAction

    return ManagementAction(
        action_id=uuid4(),
        kind="PUBLIC_REPLY",
        platform="YOUTUBE",
        account_ref="acct:fake-main",
        content="ขอบคุณมากค่ะ",
        catalog_version=1,
        management_policy_hash="a" * 64,
        dedupe_key="isolation-1",
    )
