"""Shutdown, budget stop, human wait and warm-pod transfer."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from rendering_support import GPU_SECOND_MICRO, T0, RenderWorld

from microdrama.contracts.enums import EpisodeState, PodState, ReceiptKind
from microdrama.contracts.errors import Conflict, PolicyDenied, TransientProviderError
from microdrama.contracts.principals import Principal
from microdrama.core.state_machine import transition_episode
from microdrama.rendering import human_wait_guard
from microdrama.testing.fakes import PodStopScenario

pytestmark = pytest.mark.db

KEY = "pod.lease:ep1:render-1"
WORKER = Principal(principal_id="worker:render-01", kind="SERVICE_WORKER")


def _intervals(world: RenderWorld, pod_id: str) -> list[dict]:
    return world.intervals(pod_id)


def _stop_failures(provider) -> None:
    provider.queue_scenarios(PodStopScenario.STOP_FAILS_ONCE, PodStopScenario.STOP_FAILS_ONCE)


class _NeverStopsProvider:
    """Wraps the fake so stop and terminate both keep failing (shutdown failure drill)."""

    def __init__(self, inner) -> None:
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    @property
    def provider_id(self) -> str:
        return self._inner.provider_id

    def stop_pod(self, pod_id: str):
        raise TransientProviderError("stop refused", pod_id=pod_id)

    def terminate_pod(self, pod_id: str):
        raise TransientProviderError("terminate refused", pod_id=pod_id)


def test_shutdown_stops_verifies_and_settles_the_hold(world: RenderWorld) -> None:
    ep = world.episode()
    handle, _ = world.claim_and_acquire(ep, KEY)
    pod_id = world.lease_row(handle.lease.lease_id)["pod_id"]
    world.clock.advance(seconds=120)
    result = world.leases.shutdown(handle.lease.lease_id, reason="render complete")
    assert result.stop_verified_at == T0 + timedelta(seconds=120)
    assert result.settled_micro_usd == GPU_SECOND_MICRO * 120
    row = world.lease_row(handle.lease.lease_id)
    assert row["lease_state"] == "RELEASED"
    assert row["pod_state"] == "STOPPED"
    assert row["stop_verified_at"] == result.stop_verified_at
    assert world.provider.get_pod(pod_id).state is PodState.STOPPED  # type: ignore[union-attr]
    reservation = world.reservation_row(handle.lease.reservation_id)
    assert reservation["state"] == "SETTLED"
    assert reservation["settled_micro_usd"] == GPU_SECOND_MICRO * 120
    counters = world.counters(ep.account_id)
    assert counters == {
        "reserved": 0,
        "accrued": 0,
        "settled": GPU_SECOND_MICRO * 120,
        "committed": GPU_SECOND_MICRO * 120,
        "blocked": 0,
    }
    kinds = {c["kind"] for c in world.charges(handle.lease.reservation_id)}
    assert kinds == {ReceiptKind.ACCRUAL.value, ReceiptKind.SETTLEMENT.value}
    events = [e[0] for e in world.lease_events(handle.lease.lease_id)]
    assert "pod_lease.release_started" in events and "pod_lease.released" in events


def test_shutdown_is_idempotent(world: RenderWorld) -> None:
    ep = world.episode()
    handle, _ = world.claim_and_acquire(ep, KEY)
    world.clock.advance(seconds=30)
    first = world.leases.shutdown(handle.lease.lease_id, reason="done")
    second = world.leases.shutdown(handle.lease.lease_id, reason="done again")
    assert second.replayed is True
    assert second.settled_micro_usd == first.settled_micro_usd == GPU_SECOND_MICRO * 30
    stops = [c for c in world.provider.calls if c.method == "stop_pod"]
    assert len(stops) == 1  # no second provider stop on replay


def test_shutdown_of_a_claim_without_pod_releases_the_hold(world: RenderWorld) -> None:
    ep = world.episode()
    handle = world.claim(ep, KEY)
    result = world.leases.release_claim(handle.lease.lease_id, reason="never started")
    assert result.settled_micro_usd == 0
    assert world.lease_row(handle.lease.lease_id)["lease_state"] == "RELEASED"
    assert world.reservation_row(handle.lease.reservation_id)["state"] == "RELEASED"
    assert world.counters(ep.account_id)["committed"] == 0
    assert world.owned_pods() == []


def test_transient_stop_failure_is_retried_within_shutdown(world: RenderWorld) -> None:
    ep = world.episode()
    handle, _ = world.claim_and_acquire(ep, KEY)
    world.provider.queue_scenarios(PodStopScenario.STOP_FAILS_ONCE)
    world.clock.advance(seconds=60)
    result = world.leases.shutdown(handle.lease.lease_id, reason="done")
    assert world.lease_row(handle.lease.lease_id)["lease_state"] == "RELEASED"
    assert result.settled_micro_usd == GPU_SECOND_MICRO * 60


def test_shutdown_failure_leaves_durable_state_the_janitor_finishes(world: RenderWorld) -> None:
    """Stop and terminate both fail: the failure is durable, the pod is not abandoned."""
    ep = world.episode()
    handle, _ = world.claim_and_acquire(ep, KEY)
    pod_id = world.lease_row(handle.lease.lease_id)["pod_id"]
    world.clock.advance(seconds=60)
    broken = _NeverStopsProvider(world.provider)
    from microdrama.rendering import PodManager

    world.manager = PodManager(broken, world.clock, world.config, stop_attempts=2)
    world.leases = __import__(
        "microdrama.rendering", fromlist=["build_lease_service"]
    ).build_lease_service(
        world.db, world.budget, world.manager, world.clock, world.ids, world.settings, world.config
    )
    with pytest.raises(TransientProviderError):
        world.leases.shutdown(handle.lease.lease_id, reason="done")
    row = world.lease_row(handle.lease.lease_id)
    assert row["lease_state"] == "ACTIVE"
    assert row["pod_state"] == "RELEASING"
    events = [e[0] for e in world.lease_events(handle.lease.lease_id)]
    assert "pod_lease.release_started" in events and "pod_lease.stop_failed" in events
    assert world.provider.get_pod(pod_id).state is PodState.RUNNING  # type: ignore[union-attr]
    # Recovery does not depend on the failed process: the independent janitor finishes.
    world.clock.advance(seconds=10)
    report = world.janitor().sweep()
    assert [o.outcome for o in report.lease_outcomes] == ["ORPHANED"]
    assert world.lease_row(handle.lease.lease_id)["lease_state"] == "ORPHANED"
    assert world.provider.get_pod(pod_id).state is PodState.STOPPED  # type: ignore[union-attr]
    assert world.reservation_row(handle.lease.reservation_id)["state"] == "SETTLED"


def test_stop_escalation_terminates_the_pod(world: RenderWorld) -> None:
    ep = world.episode()
    handle, _ = world.claim_and_acquire(ep, KEY)
    world.lease_row(handle.lease.lease_id)["pod_id"]
    _stop_failures(world.provider)  # both stop attempts fail; terminate succeeds
    world.leases.shutdown(handle.lease.lease_id, reason="done")
    row = world.lease_row(handle.lease.lease_id)
    assert row["lease_state"] == "RELEASED"
    assert row["pod_state"] == "TERMINATED"
    assert world.provider.foreign_touches == []


def _drain_every_category(world: RenderWorld, episode) -> None:
    """Consume each category's exact free headroom with rule-true reservations.

    Reserving exactly the free amount of a category never spills; the recovery tranche
    goes in as a cleanup reserve (the only request kind allowed to consume the shutdown
    reserve), so the account ends fully committed with no overrun and no blocked flag.
    """
    from microdrama.contracts.cost import BudgetReservationRequest, ExposureCeilings
    from microdrama.contracts.enums import (
        BudgetCategory,
        BudgetScopeKind,
        PriceUnit,
        QueueName,
    )

    with world.db.transaction(readonly=True) as tx:
        rows = tx.fetchall(
            "SELECT category, allocated_micro_usd - reserved_outstanding_micro_usd "
            "- accrued_micro_usd - settled_micro_usd AS free_micro_usd "
            "FROM budget_category_allocations WHERE account_id = %s",
            (episode.account_id,),
        )
    for row in rows:
        free = row["free_micro_usd"]
        if free <= 0:
            continue
        is_gpu = row["category"] == BudgetCategory.GPU_GENERATION.value
        is_recovery = row["category"] == BudgetCategory.RECOVERY_HEADROOM.value
        # Rule-true shapes: GPU work is priced per GPU_SECOND; metered management belongs
        # to the community queue; only pod.stop/pod.terminate/storage.cleanup may carry the
        # cleanup flag that lets the recovery tranche consume the shutdown reserve.
        price = (
            world.config.price
            if is_gpu
            else world.config.price.model_copy(
                update={"unit": PriceUnit.REQUEST, "unit_price_micro_usd": 1}
            )
        )
        world.budget.reserve(
            BudgetReservationRequest(
                request_id=uuid.uuid4(),
                semantic_key=f"drain.after.lease:{row['category']}",
                scope_kind=BudgetScopeKind.EPISODE,
                episode_id=episode.episode_id,
                season_id=None,
                category=BudgetCategory(row["category"]),
                queue=(
                    QueueName.COMMUNITY
                    if row["category"] == BudgetCategory.METERED_MANAGEMENT.value
                    else QueueName.PRODUCTION
                ),
                job_id=None,
                provider="fake-runpod",
                operation_kind="pod.stop" if is_recovery else "test.drain",
                price=price,
                ceilings=ExposureCeilings(
                    timeout_ms=(free * 1000) // GPU_SECOND_MICRO if is_gpu else 1_000,
                    max_units=1 if is_gpu else free,
                ),
                worst_case_micro_usd=free,
                is_shutdown_or_cleanup=is_recovery,
                expires_at=T0 + timedelta(hours=1),
            )
        )


def test_budget_stop_cannot_reserve_a_shutdown_grant_but_the_pod_still_stops(
    world: RenderWorld,
) -> None:
    """The account is drained after the lease started: no cleanup grant, no leaked pod."""
    ep = world.episode()
    handle, _ = world.claim_and_acquire(ep, KEY)
    _drain_every_category(world, ep)
    assert world.counters(ep.account_id)["committed"] == 10_000_000  # cap, not over
    world.clock.advance(seconds=60)
    result = world.leases.shutdown(handle.lease.lease_id, reason="budget stopped")
    row = world.lease_row(handle.lease.lease_id)
    assert row["lease_state"] == "RELEASED" and row["stop_verified_at"] is not None
    assert world.leases.get(handle.lease.lease_id).pod_state is PodState.STOPPED
    assert result.settled_micro_usd == GPU_SECOND_MICRO * 60
    events = [e[0] for e in world.lease_events(handle.lease.lease_id)]
    assert "pod_lease.cleanup_grant_refused" in events
    # The account never went over the cap and nothing was left running.
    counters = world.counters(ep.account_id)
    assert counters["committed"] <= 10_000_000 and counters["blocked"] == 0


# --- no GPU during human waits (SPEC §5 rule 8) ------------------------------------------------


def _transition(world: RenderWorld, episode_id, target: EpisodeState) -> None:
    with world.db.transaction() as tx:
        row = tx.fetchone("SELECT revision FROM episodes WHERE id = %s", (episode_id,))
        assert row is not None
        transition_episode(
            tx,
            episode_id=episode_id,
            to=target,
            expected_revision=row["revision"],
            actor=WORKER,
            now=world.clock.now(),
            correlation_id=uuid.uuid4(),
            guards={EpisodeState.AWAITING_FINAL_REVIEW: [human_wait_guard]},
        )


def test_human_wait_transition_is_refused_while_a_lease_is_live(world: RenderWorld) -> None:
    ep = world.episode(state="AI_REVIEW")
    handle, _ = world.claim_and_acquire(ep, KEY)
    with pytest.raises(PolicyDenied) as exc:
        _transition(world, ep.episode_id, EpisodeState.AWAITING_FINAL_REVIEW)
    assert "human wait" in str(exc.value.message)
    with world.db.transaction(readonly=True) as tx:
        state = tx.fetchval("SELECT state FROM episodes WHERE id = %s", (ep.episode_id,))
    assert state == "AI_REVIEW"  # the transition itself was refused


def test_stop_for_human_wait_releases_the_gpu_then_the_transition_passes(
    world: RenderWorld,
) -> None:
    ep = world.episode(state="AI_REVIEW")
    handle, _ = world.claim_and_acquire(ep, KEY)
    world.clock.advance(seconds=45)
    results = world.leases.stop_for_human_wait(ep.episode_id)
    assert len(results) == 1 and results[0].settled_micro_usd == GPU_SECOND_MICRO * 45
    assert world.lease_row(handle.lease.lease_id)["lease_state"] == "RELEASED"
    _transition(world, ep.episode_id, EpisodeState.AWAITING_FINAL_REVIEW)
    with world.db.transaction(readonly=True) as tx:
        state = tx.fetchval("SELECT state FROM episodes WHERE id = %s", (ep.episode_id,))
    assert state == "AWAITING_FINAL_REVIEW"
    # The lease cannot be resurrected after the gate is open.
    with pytest.raises(PolicyDenied):
        world.leases.heartbeat(handle.lease.lease_id)


# --- warm-pod transfer ---------------------------------------------------------------------------


def test_transfer_moves_ownership_and_accounts_each_interval_once(world: RenderWorld) -> None:
    ep1 = world.episode()
    ep2 = world.episode()
    handle1, _ = world.claim_and_acquire(ep1, KEY)
    pod_id = world.lease_row(handle1.lease.lease_id)["pod_id"]
    world.clock.advance(seconds=60)
    handle2 = world.leases.transfer(
        handle1.lease.lease_id,
        to_episode_id=ep2.episode_id,
        to_semantic_key="pod.lease:ep2:render-1",
    )
    assert handle2.lease.owner_episode_id == ep2.episode_id
    assert handle2.lease.pod_id == pod_id
    assert handle2.lease.lease_state.value == "ACTIVE"
    assert handle2.lease.transferred_from == handle1.lease.lease_id
    assert world.lease_row(handle1.lease.lease_id)["lease_state"] == "RELEASED"
    assert len(world.live_leases()) == 1  # exactly one live lease across the handover
    # Episode one paid for its minute; the reservation settled on its account.
    assert world.reservation_row(handle1.lease.reservation_id)["state"] == "SETTLED"
    assert world.counters(ep1.account_id)["settled"] == GPU_SECOND_MICRO * 60
    assert world.counters(ep2.account_id)["reserved"] > 0
    # Episode two runs, then shuts down.
    world.clock.advance(seconds=60)
    world.leases.shutdown(handle2.lease.lease_id, reason="done")
    intervals = _intervals(world, pod_id)
    assert len(intervals) == 2
    first, second = intervals
    assert first["account_id"] == ep1.account_id and second["account_id"] == ep2.account_id
    assert first["interval_end"] == second["interval_start"]  # no gap, no overlap
    assert sum(i["amount_micro_usd"] for i in intervals) == GPU_SECOND_MICRO * 120
    assert world.provider.get_pod(pod_id).state is PodState.STOPPED  # type: ignore[union-attr]


def test_transfer_requires_an_active_lease(world: RenderWorld) -> None:
    ep1 = world.episode()
    ep2 = world.episode()
    handle, _ = world.claim_and_acquire(ep1, KEY)
    world.leases.shutdown(handle.lease.lease_id, reason="done")
    with pytest.raises(Conflict):
        world.leases.transfer(
            handle.lease.lease_id,
            to_episode_id=ep2.episode_id,
            to_semantic_key="pod.lease:ep2:render-x",
        )


def test_pilot_rule_blocks_a_second_lease_while_a_transferred_one_is_live(
    world: RenderWorld,
) -> None:
    ep1 = world.episode()
    ep2 = world.episode()
    ep3 = world.episode()
    handle1, _ = world.claim_and_acquire(ep1, KEY)
    world.leases.transfer(
        handle1.lease.lease_id,
        to_episode_id=ep2.episode_id,
        to_semantic_key="pod.lease:ep2:render-1",
    )
    with pytest.raises(PolicyDenied):
        world.claim(ep3, "pod.lease:ep3:render-1")
