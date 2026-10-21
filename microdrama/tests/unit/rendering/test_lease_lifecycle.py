"""Acquisition and cost accrual: reconcile-or-create, bases, once-only intervals."""

from __future__ import annotations

from datetime import timedelta

import pytest
from rendering_support import GPU_SECOND_MICRO, T0, RenderWorld

from microdrama.contracts.enums import PodState, ReceiptKind
from microdrama.contracts.errors import (
    InvalidTransition,
    TransientProviderError,
)
from microdrama.rendering import client_token_for
from microdrama.testing.fakes import PodCreateScenario
from microdrama.testing.fakes.pods import DEFAULT_FOREIGN_PODS

pytestmark = pytest.mark.db

KEY = "pod.lease:ep1:render-1"


def _intervals_by_basis(world: RenderWorld, pod_id: str) -> dict[str, list[tuple[int, int, int]]]:
    out: dict[str, list[tuple[int, int, int]]] = {}
    for row in world.intervals(pod_id):
        start = (row["interval_start"] - T0) // timedelta(milliseconds=1)
        end = (row["interval_end"] - T0) // timedelta(milliseconds=1)
        out.setdefault(row["basis"], []).append((start, end, row["amount_micro_usd"]))
    return out


def test_ensure_pod_acquires_verifies_and_activates(world: RenderWorld) -> None:
    ep = world.episode()
    job = world.job("render-job-1")
    handle, active = world.claim_and_acquire(ep, KEY, job=job)
    assert active.lease.lease_state.value == "ACTIVE"
    assert active.lease.pod_state.value == "RUNNING"
    assert active.lease.pod_id is not None
    assert active.lease.heartbeat_at == T0
    pod = world.provider.get_pod(active.lease.pod_id)
    assert pod is not None and pod.state is PodState.RUNNING
    assert pod.owned_tag == world.config.owned_tag
    assert [e[0] for e in world.lease_events(handle.lease.lease_id)] == [
        "pod_lease.claimed",
        "pod_lease.activated",
    ]
    # ensure_pod is idempotent: a second call re-verifies without creating anything.
    again = world.leases.ensure_pod(handle.lease.lease_id)
    assert again.replayed is False and again.lease.pod_id == active.lease.pod_id
    assert len(world.owned_pods()) == 1


def test_ambiguous_create_timeout_that_created_is_adopted(world: RenderWorld) -> None:
    ep = world.episode()
    world.provider.queue_scenarios(PodCreateScenario.CREATE_TIMEOUT_BUT_CREATED)
    handle = world.claim(ep, KEY)
    active = world.leases.ensure_pod(handle.lease.lease_id)
    assert active.lease.lease_state.value == "ACTIVE"
    assert len(world.owned_pods()) == 1  # no duplicate acquisition
    token_pods = world.provider.find_pods(client_token=client_token_for(KEY))
    assert len(token_pods) == 1
    assert token_pods[0].pod_id == active.lease.pod_id


def test_ambiguous_create_timeout_that_did_not_create_retries_once(world: RenderWorld) -> None:
    ep = world.episode()
    world.provider.queue_scenarios(PodCreateScenario.CREATE_TIMEOUT_NOT_CREATED)
    handle = world.claim(ep, KEY)
    active = world.leases.ensure_pod(handle.lease.lease_id)
    assert active.lease.lease_state.value == "ACTIVE"
    creates = [c for c in world.provider.calls if c.method == "create_pod"]
    assert len(creates) == 2  # reconciled in between; never a blind re-create
    assert len(world.owned_pods()) == 1


def test_crash_after_create_is_recovered_from_durable_state(world: RenderWorld) -> None:
    """Worker died after the provider accepted the create but before any DB write."""
    from microdrama.rendering import PodSpec

    ep = world.episode()
    handle = world.claim(ep, KEY)
    token = client_token_for(KEY)
    spec = PodSpec(
        gpu_type_allowlist=("FAKE-GPU-24GB",),
        max_hourly_price_micro_usd=900_000,
        min_host_ram_gb=32,
        container_image="registry.invalid/render@sha256:" + "b" * 64,
    )
    # The "crashed" worker's create reached the provider; nothing was persisted.
    pod = world.provider.create_pod(
        world.manager.create_request(spec, name="render", client_token=token)
    )
    world.clock.advance(seconds=30)  # paid time passes before anyone notices
    active = world.leases.ensure_pod(handle.lease.lease_id)
    assert active.lease.pod_id == pod.pod_id
    creates = [c for c in world.provider.calls if c.method == "create_pod"]
    assert len(creates) == 1  # adopted by token; no second pod
    # Unverified warmup time is honestly declared COLD_START.
    world.clock.advance(seconds=60)
    attributed = world.leases.accrue(handle.lease.lease_id)
    assert attributed == GPU_SECOND_MICRO * 90
    bases = _intervals_by_basis(world, pod.pod_id)
    assert bases["COLD_START"] == [(0, 30_000, GPU_SECOND_MICRO * 30)]
    assert bases["RUNNING"] == [(30_000, 90_000, GPU_SECOND_MICRO * 60)]


def test_unavailable_gpu_is_transient_and_leaves_the_claim_releasable(
    world: RenderWorld,
) -> None:
    ep = world.episode()
    world.provider.queue_scenarios(PodCreateScenario.NO_CAPACITY)
    handle = world.claim(ep, KEY)
    with pytest.raises(TransientProviderError):
        world.leases.ensure_pod(handle.lease.lease_id)
    row = world.lease_row(handle.lease.lease_id)
    assert row["lease_state"] == "CLAIMED" and row["pod_state"] == "REQUESTED"
    assert world.owned_pods() == []
    # Capacity returned: the same claim acquires exactly one pod.
    active = world.leases.ensure_pod(handle.lease.lease_id)
    assert active.lease.pod_state.value == "RUNNING"
    assert len(world.owned_pods()) == 1


def test_heartbeat_tracks_worker_life(world: RenderWorld) -> None:
    ep = world.episode()
    handle = world.claim(ep, KEY)
    # A claim without a pod has no worker to heartbeat.
    with pytest.raises(InvalidTransition):
        world.leases.heartbeat(handle.lease.lease_id)
    world.leases.ensure_pod(handle.lease.lease_id)
    world.clock.advance(seconds=10)
    when = world.leases.heartbeat(handle.lease.lease_id)
    assert when == T0 + timedelta(seconds=10)
    assert world.lease_row(handle.lease.lease_id)["heartbeat_at"] == when


def test_accrual_attributes_each_interval_once_by_declared_basis(world: RenderWorld) -> None:
    ep = world.episode()
    handle, _ = world.claim_and_acquire(ep, KEY)
    pod_id = world.lease_row(handle.lease.lease_id)["pod_id"]
    world.clock.advance(seconds=60)
    first = world.leases.accrue(handle.lease.lease_id)
    assert first == GPU_SECOND_MICRO * 60
    world.leases.mark_idle(handle.lease.lease_id)
    world.clock.advance(seconds=30)
    second = world.leases.accrue(handle.lease.lease_id)
    assert second == GPU_SECOND_MICRO * 30
    # Re-accruing with no elapsed time attributes nothing new (replay-safe).
    assert world.leases.accrue(handle.lease.lease_id) == 0
    bases = _intervals_by_basis(world, pod_id)
    assert bases["RUNNING"] == [(0, 60_000, GPU_SECOND_MICRO * 60)]
    assert bases["IDLE"] == [(60_000, 90_000, GPU_SECOND_MICRO * 30)]
    charges = world.charges(handle.lease.reservation_id)
    assert {c["kind"] for c in charges} == {ReceiptKind.ACCRUAL.value}
    assert sum(c["amount_micro_usd"] for c in charges) == GPU_SECOND_MICRO * 90
    assert world.counters(ep.account_id)["accrued"] == GPU_SECOND_MICRO * 90


def test_accrual_covers_shutdown_basis_after_a_crashed_release_start(
    world: RenderWorld,
) -> None:
    ep = world.episode()
    handle, _ = world.claim_and_acquire(ep, KEY)
    pod_id = world.lease_row(handle.lease.lease_id)["pod_id"]
    world.clock.advance(seconds=90)
    world.leases.accrue(handle.lease.lease_id)
    # The worker began shutdown and died; ten seconds of shutdown follow before the
    # janitor-equivalent recovery stops the pod.
    world.leases.begin_shutdown(handle.lease.lease_id, reason="render complete")
    world.clock.advance(seconds=10)
    world.provider.stop_pod(pod_id)
    world.leases.accrue(handle.lease.lease_id)
    bases = _intervals_by_basis(world, pod_id)
    assert bases["RUNNING"] == [(0, 90_000, GPU_SECOND_MICRO * 90)]
    assert bases["SHUTDOWN"] == [(90_000, 100_000, GPU_SECOND_MICRO * 10)]
    # The full paid window is covered exactly once, contiguously.
    covered = sorted(
        (row["interval_start"], row["interval_end"]) for row in world.intervals(pod_id)
    )
    assert covered[0][0] == T0
    for (_, end), (start, _) in zip(covered, covered[1:], strict=False):
        assert start == end
    assert covered[-1][1] == T0 + timedelta(seconds=100)


def test_accrual_is_noop_for_a_claim_without_pod(world: RenderWorld) -> None:
    ep = world.episode()
    handle = world.claim(ep, KEY)
    assert world.leases.accrue(handle.lease.lease_id) == 0
    assert world.intervals() == []


def test_lease_expiry_boundary_is_durable(world: RenderWorld) -> None:
    ep = world.episode()
    handle = world.claim(ep, KEY, ttl_ms=120_000)
    row = world.lease_row(handle.lease.lease_id)
    assert row["lease_expires_at"] == T0 + timedelta(milliseconds=120_000)
    reservation = world.reservation_row(handle.lease.reservation_id)
    # The hold covers the whole paid window: lease TTL plus the shutdown margin.
    assert reservation["expires_at"] == T0 + timedelta(milliseconds=420_000)


def test_foreign_pods_are_never_visible_to_the_lease_lifecycle(world: RenderWorld) -> None:
    ep = world.episode()
    handle, _ = world.claim_and_acquire(ep, KEY)
    assert {p.pod_id for p in world.provider.find_pods()} >= {
        seed.pod_id for seed in DEFAULT_FOREIGN_PODS
    }
    import uuid as _uuid

    from microdrama.contracts.errors import NotFound

    with pytest.raises(NotFound):
        world.leases.ensure_pod(_uuid.uuid4())
    assert world.provider.foreign_touches == []
