"""AT-08: a comment flood cannot starve a due release or spend protected funds."""

from __future__ import annotations

from uuid import uuid4

from microdrama.contracts.enums import BudgetCategory, QueueName
from microdrama.contracts.errors import PolicyDenied
from microdrama.workers import counting_handler

FLOOD = 250


class TestFloodCannotStarvePublication:
    def test_due_release_completes_in_the_first_cycle_under_flood(self, world):
        for _ in range(FLOOD):
            world.enqueue_event_job()
        release_job = world.enqueue_post_job()  # due at the same instant

        counter: dict[str, int] = {}
        runtime = world.runtime(
            {
                "community.ingest_event": counting_handler(counter, "ingest"),
                "publish.poll_status": counting_handler(counter, "poll"),
            },
            community=4,
            publication=1,
        )
        first_cycle = runtime.run_cycle()
        actions = {r.job_id: r.action for r in first_cycle.reports}
        assert actions[release_job] == "EXECUTED"  # served in the SAME cycle
        community_done = sum(1 for r in first_cycle.reports if r.queue is QueueName.COMMUNITY)
        assert community_done == 4  # the flood queues behind its own reservation
        assert world.job_row(release_job)["status"] == "SUCCEEDED"

    def test_production_work_also_progresses_under_flood(self, world):
        for _ in range(FLOOD):
            world.enqueue_event_job()
        production_job = world.enqueue_episode_job()

        runtime = world.runtime(
            {
                "community.ingest_event": counting_handler({}, "ingest"),
                "qa.technical": counting_handler({}, "qa"),
            },
            community=2,
            production=1,
        )
        first_cycle = runtime.run_cycle()
        actions = {r.job_id: r.action for r in first_cycle.reports}
        assert actions[production_job] == "EXECUTED"


class TestProtectedFunds:
    def test_community_queue_may_not_reserve_protected_categories(self, world):
        """The budget service's own queue-ownership rule, proven from behavior:
        a community-context reservation of GPU production funds is refused
        before anything is held (the ownership check is the first gate)."""
        from datetime import timedelta

        from microdrama.contracts.cost import (
            BudgetReservationRequest,
            ExposureCeilings,
            PriceQuote,
        )
        from microdrama.contracts.enums import BudgetScopeKind, PriceSource

        request = BudgetReservationRequest(
            request_id=uuid4(),
            semantic_key=f"at08:{uuid4().hex[:12]}",
            scope_kind=BudgetScopeKind.EPISODE,
            season_id=uuid4(),
            episode_id=uuid4(),
            category=BudgetCategory.GPU_GENERATION,
            queue=QueueName.COMMUNITY,  # the flood's queue asking for GPU money
            provider="runpod",
            operation_kind="pod.lease",
            price=PriceQuote(
                currency="USD",
                unit="GPU_SECOND",
                unit_price_micro_usd=1000,
                source=PriceSource.FAKE_SYNTHETIC,
                price_table_version="test-v1",
                as_of=world.clock.now(),
            ),
            ceilings=ExposureCeilings(timeout_ms=60_000, max_units=10),
            worst_case_micro_usd=100_000,
            expires_at=world.clock.now() + timedelta(hours=1),
        )
        try:
            world.budget.reserve(request)
        except PolicyDenied as exc:
            assert "may not reserve" in exc.message
        else:  # pragma: no cover
            raise AssertionError("community queue reserved protected GPU funds")

    def test_flood_processing_moves_no_money_at_all(self, world):
        """Offline flood handlers are unpaid spec-marked test doubles; the
        durable proof is that no reservation rows exist after the flood."""
        for _ in range(FLOOD):
            world.enqueue_event_job()
        runtime = world.runtime(
            {"community.ingest_event": counting_handler({}, "ingest")}, community=8
        )
        runtime.run_cycles()
        count = world.db.transaction(readonly=True)
        with count as tx:
            reservations = tx.fetchval("SELECT count(*) FROM reservations") or 0
            charges = tx.fetchval("SELECT count(*) FROM charges") or 0
        assert reservations == 0
        assert charges == 0
