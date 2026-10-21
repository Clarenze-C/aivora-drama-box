"""Lease claiming: atomic claim+hold, idempotency, adoption, pilot rule, budget stop."""

from __future__ import annotations

import threading
import uuid
from dataclasses import replace
from datetime import timedelta

import pytest
from rendering_support import GPU_SECOND_MICRO, T0, Episode, RenderWorld

from microdrama.contracts.cost import BudgetReservationRequest, ExposureCeilings
from microdrama.contracts.enums import BudgetCategory, BudgetScopeKind, QueueName
from microdrama.contracts.errors import (
    BudgetExhausted,
    Conflict,
    PolicyDenied,
    UnknownPrice,
)
from microdrama.rendering import LEASE_OPERATION_KIND, PodManager, build_lease_service

pytestmark = pytest.mark.db

KEY = "pod.lease:ep1:render-1"


def test_claim_creates_lease_and_budget_hold_atomically(world: RenderWorld) -> None:
    ep = world.episode()
    job = world.job("render-job-1")
    handle = world.claim(ep, KEY, job=job)
    lease = handle.lease
    assert not handle.replayed
    assert lease.lease_state.value == "CLAIMED"
    assert lease.pod_state.value == "REQUESTED"
    assert lease.pod_id is None
    assert lease.owner_episode_id == ep.episode_id
    assert lease.owned_tag == world.config.owned_tag
    assert lease.hourly_price_micro_usd == 900_000
    assert lease.lease_expires_at == T0 + timedelta(milliseconds=world.config.lease_ttl_ms)
    reservation = world.reservation_row(lease.reservation_id)
    assert reservation["state"] == "ACTIVE"
    assert reservation["operation_kind"] == LEASE_OPERATION_KIND
    window = world.config.paid_window_ms
    assert reservation["reserved_micro_usd"] == GPU_SECOND_MICRO * (window // 1000)
    assert world.counters(ep.account_id)["reserved"] == reservation["reserved_micro_usd"]
    assert [e[0] for e in world.lease_events(lease.lease_id)] == ["pod_lease.claimed"]


def test_claim_is_idempotent_per_semantic_key(world: RenderWorld) -> None:
    ep = world.episode()
    first = world.claim(ep, KEY)
    world.clock.advance(seconds=5)
    second = world.claim(ep, KEY)
    assert second.replayed
    assert second.lease.lease_id == first.lease.lease_id
    with world.db.transaction(readonly=True) as tx:
        leases = tx.fetchall("SELECT * FROM pod_leases")
        reservations = tx.fetchall(
            "SELECT * FROM reservations WHERE operation_kind = %s", (LEASE_OPERATION_KIND,)
        )
    assert len(leases) == 1
    assert len(reservations) == 1


def test_claim_semantic_key_reused_for_another_episode_is_refused(world: RenderWorld) -> None:
    ep1 = world.episode()
    ep2 = world.episode()
    world.claim(ep1, KEY)
    with pytest.raises(Conflict):
        world.claim(ep2, KEY)
    assert len(world.live_leases()) == 1


def test_claim_adopts_a_reservation_left_by_a_crash(world: RenderWorld) -> None:
    """Crash between reserve() and the lease insert: the retry adopts the committed hold."""
    ep = world.episode()
    window = world.config.paid_window_ms
    price = world.config.price
    assert price is not None
    request = BudgetReservationRequest(
        request_id=uuid.uuid4(),
        semantic_key=KEY,
        scope_kind=BudgetScopeKind.EPISODE,
        episode_id=ep.episode_id,
        season_id=None,
        category=BudgetCategory.GPU_GENERATION,
        queue=QueueName.PRODUCTION,
        job_id=None,
        provider="fake-runpod",
        operation_kind=LEASE_OPERATION_KIND,
        price=price,
        ceilings=ExposureCeilings(timeout_ms=window, max_units=1),
        worst_case_micro_usd=price.unit_price_micro_usd * (window // 1000),
        is_shutdown_or_cleanup=False,
        expires_at=T0 + timedelta(milliseconds=window + 60_000),
    )
    world.budget.reserve(request)  # committed; the "crash" happened before the insert
    handle = world.claim(ep, KEY)
    assert not handle.replayed
    with world.db.transaction(readonly=True) as tx:
        reservations = tx.fetchall(
            "SELECT * FROM reservations WHERE operation_kind = %s", (LEASE_OPERATION_KIND,)
        )
    assert len(reservations) == 1  # adopted, not duplicated
    assert handle.lease.reservation_id == reservations[0]["id"]
    assert world.counters(ep.account_id)["reserved"] == reservations[0]["reserved_micro_usd"]


def test_pilot_rule_only_one_episode_owns_the_live_lease(world: RenderWorld) -> None:
    ep1 = world.episode()
    ep2 = world.episode()
    world.claim(ep1, "pod.lease:ep1:render")
    with pytest.raises(PolicyDenied) as exc:
        world.claim(ep2, "pod.lease:ep2:render")
    assert "pilot rule" in str(exc.value.message)
    assert len(world.live_leases()) == 1
    # A terminal lease frees the slot for the next episode.
    world.leases.release_claim(world.live_leases()[0]["id"], reason="test done")
    handle2 = world.claim(ep2, "pod.lease:ep2:render")
    assert handle2.lease.owner_episode_id == ep2.episode_id


def test_budget_stop_exhausted_account_refuses_claim_without_any_pod(world: RenderWorld) -> None:
    """The largest GPU hold the allocations allow (4.75M after recovery spill) leaves no
    room for a lease's worst case: the claim is refused before any dispatch."""
    ep = world.episode()
    fill = world.budget.reserve(
        BudgetReservationRequest(
            request_id=uuid.uuid4(),
            semantic_key="fill.gpu",
            scope_kind=BudgetScopeKind.EPISODE,
            episode_id=ep.episode_id,
            season_id=None,
            category=BudgetCategory.GPU_GENERATION,
            queue=QueueName.PRODUCTION,
            job_id=None,
            provider="fake-runpod",
            operation_kind="gpu.render_shot",
            price=world.config.price,
            ceilings=ExposureCeilings(timeout_ms=world.config.paid_window_ms, max_units=1),
            worst_case_micro_usd=4_750_000,
            is_shutdown_or_cleanup=False,
            expires_at=T0 + timedelta(hours=1),
        )
    )
    assert fill.reserved_micro_usd == 4_750_000
    with pytest.raises(BudgetExhausted):
        world.claim(ep, KEY)
    with world.db.transaction(readonly=True) as tx:
        assert tx.fetchall("SELECT * FROM pod_leases") == []
        assert (
            tx.fetchall(
                "SELECT * FROM reservations WHERE operation_kind = %s", (LEASE_OPERATION_KIND,)
            )
            == []
        )
    assert world.provider.calls == []  # no provider dispatch happened


def test_unknown_price_config_blocks_claim(world: RenderWorld) -> None:
    ep = world.episode()
    world.config = replace(world.config, price=None)
    world.manager = PodManager(world.provider, world.clock, world.config)
    world.leases = build_lease_service(
        world.db, world.budget, world.manager, world.clock, world.ids, world.settings, world.config
    )
    with pytest.raises(UnknownPrice):
        world.claim(ep, KEY)
    with world.db.transaction(readonly=True) as tx:
        assert tx.fetchall("SELECT * FROM pod_leases") == []
    assert world.provider.calls == []


def test_gpu_outside_allowlist_blocks_claim_before_budget(world: RenderWorld) -> None:
    ep = world.episode()
    with pytest.raises(PolicyDenied):
        world.claim(ep, KEY, gpu="RTX-FORBIDDEN")
    with world.db.transaction(readonly=True) as tx:
        assert tx.fetchall("SELECT * FROM reservations") == []
        assert tx.fetchall("SELECT * FROM pod_leases") == []
    assert world.provider.calls == []


def test_ram_below_floor_blocks_claim(world: RenderWorld) -> None:
    ep = world.episode()
    with pytest.raises(PolicyDenied):
        world.claim(ep, KEY, ram=8)
    with world.db.transaction(readonly=True) as tx:
        assert tx.fetchall("SELECT * FROM reservations") == []


@pytest.mark.slow
def test_concurrent_claims_of_one_key_produce_exactly_one_lease(world: RenderWorld) -> None:
    ep = world.episode()
    results: list[object] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def claim(_: int) -> None:
        barrier.wait(timeout=60)
        try:
            results.append(world.claim(ep, KEY))
        except BaseException as exc:  # noqa: BLE001 - collected for the assertion
            errors.append(exc)

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert not any(t.is_alive() for t in threads)
    assert errors == []
    lease_ids = {handle.lease.lease_id for handle in results}  # type: ignore[attr-defined]
    assert len(lease_ids) == 1
    with world.db.transaction(readonly=True) as tx:
        assert len(tx.fetchall("SELECT * FROM pod_leases")) == 1
        assert (
            len(
                tx.fetchall(
                    "SELECT * FROM reservations WHERE operation_kind = %s",
                    (LEASE_OPERATION_KIND,),
                )
            )
            == 1
        )


@pytest.mark.slow
def test_concurrent_claims_of_two_episodes_keep_the_pilot_single_lease(
    world: RenderWorld,
) -> None:
    ep1 = world.episode()
    ep2 = world.episode()
    outcomes: list[str] = []
    barrier = threading.Barrier(2)

    def claim(ep: Episode, key: str) -> None:
        barrier.wait(timeout=60)
        try:
            world.claim(ep, key)
            outcomes.append("claimed")
        except PolicyDenied:
            outcomes.append("denied")

    threads = [
        threading.Thread(target=claim, args=(ep1, "pod.lease:ep1:render")),
        threading.Thread(target=claim, args=(ep2, "pod.lease:ep2:render")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert not any(t.is_alive() for t in threads)
    assert sorted(outcomes) == ["claimed", "denied"]
    assert len(world.live_leases()) == 1
