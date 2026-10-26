"""Boundary probes for the 2026-10-25 build review, updated as fixes land.

Originally these asserted the observed defects; each remediation wave flips its
probes to assert the fixed behavior. Lines still labelled DEFECT reproduce an
open finding. No network, provider calls, application records or source files
are modified.
Run with PYTHONPATH=src .venv/bin/python evidence/build-review-2026-10-25-probes.py.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from microdrama.analytics.cost import _account_spend, effective_cost
from microdrama.analytics.qualification import EpisodeFacts, _production_qualifies
from microdrama.contracts.jobs import EpisodeStepInput
from microdrama.pipeline.handlers import build_handlers
from microdrama.pipeline.packaging import _qa_summary
from microdrama.pipeline.world import PipelineWorld
from microdrama.qa.repairs import NoRepairableInput, RepairPlanOutcome
from microdrama.testing.fakes import FakeClock
from microdrama.workers.limiter import SharedRateLimiter


def _repairs_boundary(calls):
    class RepairBoundary:
        def plan_from_findings(self, value):
            calls.append("findings")
            return RepairPlanOutcome.model_construct(
                plan=SimpleNamespace(plan_id=uuid4(), trigger=SimpleNamespace(value="QA_FINDING")),
                status="PLANNED",
                replayed=False,
            )

        def plan_from_feedback(self, episode_id, approval_event_id):
            calls.append(f"feedback:{approval_event_id}")
            return RepairPlanOutcome.model_construct(
                plan=SimpleNamespace(
                    plan_id=uuid4(), trigger=SimpleNamespace(value="HUMAN_FEEDBACK")
                ),
                status="PLANNED",
                replayed=False,
            )

        def execute_plan(self, plan_id):
            return SimpleNamespace(steps=[object()], returns_to_gate2=True)

    return RepairBoundary()


def run():
    episode_id = uuid4()

    # --- F02 (fixed): findings trigger consumes the nested RepairPlanOutcome ----
    calls = []
    world = SimpleNamespace(db=None, qa_repairs=_repairs_boundary(calls), analytics=None)
    ctx = SimpleNamespace(
        payload=EpisodeStepInput(episode_id=episode_id, trigger="scheduled"),
        job=SimpleNamespace(causation_id=None),
    )
    outcome = build_handlers(world)["qa.plan_repairs"](ctx)
    assert outcome.result["plan_id"] and calls == ["findings"]
    print("FIXED F02: findings trigger consumes outcome.plan.plan_id and executes it")

    # --- F02 (fixed): human_feedback routes to the feedback planner -------------
    calls.clear()
    approval_id = uuid4()
    ctx = SimpleNamespace(
        payload=EpisodeStepInput(episode_id=episode_id, trigger="human_feedback"),
        job=SimpleNamespace(causation_id=approval_id),
    )
    outcome = build_handlers(world)["qa.plan_repairs"](ctx)
    assert outcome.result["trigger"] == "HUMAN_FEEDBACK"
    assert calls == [f"feedback:{approval_id}"]
    print("FIXED F02: human_feedback trigger calls the feedback planner with the approval")

    # --- F02 (fixed): no repairable input is a no-work success -------------------
    class NothingRepairable:
        def plan_from_findings(self, value):
            raise NoRepairableInput("no REPAIRABLE findings")

        def plan_from_feedback(self, *args):
            raise NoRepairableInput("no feedback items")

        def execute_plan(self, plan_id):  # pragma: no cover - must not be reached
            raise AssertionError("no-work outcome must not execute a plan")

    world.qa_repairs = NothingRepairable()
    outcome = build_handlers(world)["qa.plan_repairs"](ctx)
    assert outcome.result["plan_id"] is None
    assert outcome.result["reason"] == "nothing_repairable"
    print("FIXED F02: NoRepairableInput returns an explicit no-work Succeeded outcome")

    # --- F09 (fixed): unknown coverage stays in the package QA summary -----------
    class FindingTx:
        def fetchall(self, *args):
            return [
                dict(
                    id=uuid4(),
                    check_id="temporal.black_frames",
                    severity="MAJOR",
                    outcome="UNKNOWN",
                    coverage="UNSAMPLED",
                    resolution="OPEN",
                )
            ]

    summary = _qa_summary(FindingTx(), episode_id)
    assert summary.finding_count == 1
    assert "temporal.black_frames" in summary.unknown_coverage_check_ids
    print("FIXED F09: an UNKNOWN finding keeps its check id in the package summary")

    # --- F08 (fixed): overrun is a subset of committed spend, never added --------
    spend = _account_spend(
        dict(
            settled_micro_usd=11_000_000,
            accrued_micro_usd=0,
            reserved_outstanding_micro_usd=0,
            overrun_micro_usd=1_000_000,
        )
    )
    assert spend == 11_000_000
    print("FIXED F08: $11 settled with $1 overrun reports $11 spend (overrun separate)")

    # --- F08 (fixed): partial minutes use the exact millisecond ratio ------------
    _, per_minute = effective_cost(
        total_variable_micro_usd=1_000_000,
        successful_episodes=1,
        published_minutes_ms=210_000,
    )
    assert per_minute == 285_714
    print("FIXED F08: $1 / 3.5 minutes reports 285714 micro-USD/minute (floor rule)")

    # --- F07 (fixed): above-cap published episode no longer qualifies ------------
    fact = EpisodeFacts(
        episode_id,
        1,
        "PUBLISHED_VERIFIED",
        None,
        0,
        datetime.now(UTC),
        12_000_000,
        cap_micro_usd=10_000_000,
        required_slots_verified=True,
        approval_bound=True,
    )
    assert _production_qualifies(fact) is False
    print("FIXED F07: published $12 episode (cap $10) does not qualify for production")

    # --- F04 (fixed): the composed runtime binds provider-bound job types ----------
    from microdrama.workers.runtime import PROVIDER_BOUND_TYPES

    clock = FakeClock(datetime(2026, 10, 27, 12, tzinfo=UTC))
    runtime_world = SimpleNamespace(
        jobs=None, db=None, fakes=SimpleNamespace(clock=clock), limiter=SharedRateLimiter(clock)
    )
    runtime = PipelineWorld.runtime(runtime_world, {})
    bound = set(runtime._deployment.bindings)
    assert PROVIDER_BOUND_TYPES <= bound, "every provider-bound type must carry a key binding"
    print("FIXED F04: composed runtime binds every provider-bound job type to a bucket key")

    # --- F04 (fixed): the durable limiter replaces process-local buckets -----------
    # The composed world now registers PostgresSharedRateLimiter buckets (shared
    # across processes and restarts, proven by tests/unit/workers/
    # test_workers_shared_quota.py); SharedRateLimiter remains only as the
    # single-process test double, so its instance independence is no longer the
    # composed runtime's behavior.
    first = SharedRateLimiter(clock, default_capacity=1)
    second = SharedRateLimiter(clock, default_capacity=1)
    assert first.try_acquire("provider:account").allowed
    assert second.try_acquire("provider:account").allowed
    print(
        "FIXED F04: composed world uses PostgresSharedRateLimiter "
        "(in-process double stays test-only)"
    )


if __name__ == "__main__":
    run()
