"""AT-04 reproduced independently: crash/ambiguity at the GPU boundaries.

Pod-create ambiguity, dead workers (expired heartbeats), stop failures — driven
through the composed lease service's claim→ensure_pod boundary, the fake Runpod
provider and the independent janitor. Plus the pilot-level proof that no render
was submitted twice anywhere in the full run (the W05 recovery path exercises
NEEDS_RECONCILIATION by design).
"""

from __future__ import annotations

import uuid

import pytest

from microdrama.rendering.leases import PodLeaseClaimRequest
from microdrama.testing.fakes.pods import PodCreateScenario, PodStopScenario
from microdrama.testing.seed import seed_episode, seed_season

pytestmark = [pytest.mark.db, pytest.mark.slow]

GPU_TYPE = "FAKE-GPU-24GB"
RAM_GB = 32
OWNED_TAG = "microdrama-owned:mock"


def _episode_with_budget(world) -> uuid.UUID:
    from microdrama.contracts.season import CostPolicy

    with world.db.transaction() as tx:
        season_id = seed_season(tx)
        episode_id = seed_episode(tx, season_id, number=1)
        world.budget.open_episode_account(
            tx, season_id=season_id, episode_id=episode_id, policy=CostPolicy()
        )
    return episode_id


def _claim(world, episode_id: uuid.UUID, key: str):
    return world.leases.claim(
        PodLeaseClaimRequest(
            episode_id=episode_id, semantic_key=key, gpu_type=GPU_TYPE, host_ram_gb=RAM_GB
        )
    )


def _running_pipeline_pods(world) -> list[str]:
    return [
        pod.pod_id
        for pod in world.fakes.pods.find_pods(owned_tag=OWNED_TAG)
        if pod.state.value == "RUNNING"
    ]


def test_ambiguous_pod_create_is_adopted_never_duplicated(validation_world) -> None:
    """CREATE_TIMEOUT_BUT_CREATED at the ensure_pod boundary: the provider created
    the pod AND raised. Recovery reconciles by the durable client token — the
    EXISTING pod is adopted (no second create), and after the worker dies the
    janitor stops it; foreign pods are never touched."""
    world = validation_world
    episode_id = _episode_with_budget(world)
    handle = _claim(world, episode_id, "t030.ambiguous-create")
    world.fakes.pods.queue_scenarios(PodCreateScenario.CREATE_TIMEOUT_BUT_CREATED)
    # The provider creates the pod AND raises; ensure_pod's reconciliation adopts
    # the already-created pod (durable client token) instead of creating another.
    active = world.leases.ensure_pod(handle.lease.lease_id)
    assert active.lease.lease_state.value == "ACTIVE"
    assert active.lease.pod_id is not None
    creates = [
        call for call in world.fakes.pods.calls if call.method == "create_pod"
    ]
    assert len(creates) == 1, "adoption must not create a second pod"

    ttl_ms = world.gpu_janitor._config.lease_ttl_ms  # noqa: SLF001
    margin_ms = world.gpu_janitor._config.shutdown_margin_ms  # noqa: SLF001
    world.fakes.clock.advance(ms=ttl_ms + margin_ms + 60_000)
    world.gpu_janitor.sweep()
    assert _running_pipeline_pods(world) == []
    assert world.fakes.pods.foreign_touches == []


def test_dead_worker_expired_lease_is_reclaimed_idempotently(validation_world) -> None:
    """An ACTIVE lease whose worker dies: past TTL the janitor shuts the pod down
    and a second sweep is a no-op (no double stop, no double release)."""
    world = validation_world
    episode_id = _episode_with_budget(world)
    handle = _claim(world, episode_id, "t030.dead-worker")
    active = world.leases.ensure_pod(handle.lease.lease_id)
    assert active.lease.lease_state.value == "ACTIVE"

    ttl_ms = world.gpu_janitor._config.lease_ttl_ms  # noqa: SLF001 - read-only probe
    margin_ms = world.gpu_janitor._config.shutdown_margin_ms  # noqa: SLF001
    world.fakes.clock.advance(ms=ttl_ms + margin_ms + 60_000)

    first = world.gpu_janitor.sweep()
    assert first.lease_outcomes, "the expired lease must be reconciled by the janitor"
    assert _running_pipeline_pods(world) == []

    second = world.gpu_janitor.sweep()
    assert second.stopped_pods == [], "second sweep must find nothing to do"
    assert world.fakes.pods.foreign_touches == []


def test_stop_failure_retries_to_a_clean_shutdown(validation_world) -> None:
    """STOP_FAILS_ONCE: the provider refuses the first stop; the next janitor run
    must still land the pod stopped (never a zombie burning money)."""
    world = validation_world
    episode_id = _episode_with_budget(world)
    handle = _claim(world, episode_id, "t030.stop-fails")
    world.leases.ensure_pod(handle.lease.lease_id)
    ttl_ms = world.gpu_janitor._config.lease_ttl_ms  # noqa: SLF001
    margin_ms = world.gpu_janitor._config.shutdown_margin_ms  # noqa: SLF001
    world.fakes.clock.advance(ms=ttl_ms + margin_ms + 60_000)

    world.fakes.pods.queue_scenarios(PodStopScenario.STOP_FAILS_ONCE)
    world.gpu_janitor.sweep()  # stop refused once — the failure is recorded, not lost
    world.gpu_janitor.sweep()  # next run retries with the default HAPPY stop
    assert _running_pipeline_pods(world) == [], "a once-failing stop must converge to stopped"
    assert world.fakes.pods.foreign_touches == []


def test_pilot_never_resubmitted_a_render(pilot) -> None:
    """Across the WHOLE pilot run — including the W05 reconciliation path that
    re-claims jobs after in-flight refusals — every Comfy prompt was queued
    exactly once (no duplicated paid work at the submit boundary)."""
    world, _report = pilot
    submissions = list(world.fakes.comfy.state.submissions)
    assert submissions, "the pilot rendered shots"
    assert len(submissions) == len(set(submissions)), "a prompt id was submitted twice"
    with world.db.transaction(readonly=True) as tx:
        render_ops = tx.fetchval(
            "SELECT count(*) FROM provider_operations po JOIN jobs j ON j.id = po.job_id "
            "WHERE j.job_type = 'render.shot'"
        )
    assert render_ops == len(submissions), "one provider operation per submitted prompt"
