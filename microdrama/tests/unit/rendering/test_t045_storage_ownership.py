"""T045 R3 (G3): storage ownership rows are written at activation/attach, survive warm
transfer unchanged, and close only at the verified terminate.

Red-first: nothing wrote ``pod_storage_ownership``, so every disk charge went to the
recovery pool and no ownership ever closed.
"""

from __future__ import annotations

import pytest
from rendering_support import T0, RenderWorld
from test_t045_timing import RunpodIdFakePods  # noqa: F401 - re-exported helper

from microdrama.persistence import Database
from microdrama.testing.fakes import FakeClock, SequentialIds

pytestmark = pytest.mark.db


def _ownership_rows(db: Database, pod_id: str) -> list[dict]:
    with db.transaction(readonly=True) as tx:
        return tx.fetchall(
            "SELECT * FROM pod_storage_ownership WHERE pod_id=%s ORDER BY valid_from",
            (pod_id,),
        )


def test_activation_writes_ownership_for_the_root_episode(world: RenderWorld) -> None:
    episode = world.episode()
    handle, activated = world.claim_and_acquire(episode, "t045-own-open")
    pod_id = activated.lease.pod_id
    rows = _ownership_rows(world.db, pod_id)
    assert len(rows) == 1
    lease_row = world.lease_row(handle.lease.lease_id)
    assert rows[0]["owner_episode_id"] == episode.episode_id
    assert rows[0]["creating_lease_id"] == handle.lease.lease_id
    assert rows[0]["valid_from"] == lease_row["create_requested_at"]
    assert rows[0]["valid_until"] is None


def test_warm_transfer_keeps_the_storage_owner(world: RenderWorld) -> None:
    episode_a = world.episode()
    episode_b = world.episode(number=2)
    handle, activated = world.claim_and_acquire(episode_a, "t045-own-transfer")
    pod_id = activated.lease.pod_id
    world.clock.advance(seconds=600)
    world.leases.transfer(
        handle.lease.lease_id,
        to_episode_id=episode_b.episode_id,
        to_semantic_key="t045-own-receiver",
    )
    rows = _ownership_rows(world.db, pod_id)
    assert len(rows) == 1
    assert rows[0]["owner_episode_id"] == episode_a.episode_id
    assert rows[0]["valid_until"] is None
    # Owner changes stay prospective: the receiver never opens a second interval here.
    assert rows[0]["creating_lease_id"] == handle.lease.lease_id


def test_runpod_terminate_closes_ownership_at_the_verified_instant(db: Database) -> None:
    provider = RunpodIdFakePods(clock=FakeClock(T0), ids=SequentialIds("t045-own"))
    world = RenderWorld(db, provider=provider)
    episode = world.episode()
    handle, activated = world.claim_and_acquire(episode, "t045-own-close")
    pod_id = activated.lease.pod_id
    world.clock.advance(seconds=600)
    world.leases.shutdown(handle.lease.lease_id, reason="t045 ownership close")
    rows = _ownership_rows(db, pod_id)
    assert len(rows) == 1
    lease_row = world.lease_row(handle.lease.lease_id)
    assert rows[0]["valid_until"] == lease_row["terminate_verified_at"]
    assert rows[0]["valid_until"] is not None


def test_fake_stop_only_leaves_ownership_open(world: RenderWorld) -> None:
    episode = world.episode()
    handle, activated = world.claim_and_acquire(episode, "t045-own-fake")
    world.leases.shutdown(handle.lease.lease_id, reason="fake stop keeps storage")
    rows = _ownership_rows(world.db, activated.lease.pod_id)
    assert len(rows) == 1
    assert rows[0]["valid_until"] is None


def test_ownership_opens_with_the_binding_while_verification_keeps_failing(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CN-4 (2026-11-09, canary-night review): the pod id is bound while the lease
    is still CLAIMED (early binding); endpoint verification then fails until the
    deadline. Storage ownership must exist from the durable binding on - never
    only at activation - and shutdown heals it before the verified terminate
    closes the interval, so the pod's disk is never recovery-pool orphaned."""
    from microdrama.contracts.errors import TransientProviderError

    provider = RunpodIdFakePods(clock=FakeClock(T0), ids=SequentialIds("t045-own-cn4"))
    world = RenderWorld(db, provider=provider)
    episode = world.episode()
    handle = world.claim(episode, "t045-own-cn4")

    def warmup_refusal(pod, spec, *, settings):
        raise TransientProviderError("pod endpoint not exposed yet (image pull/warmup)")

    monkeypatch.setattr(world.manager, "verify", warmup_refusal)
    with pytest.raises(TransientProviderError):
        world.leases.ensure_pod(handle.lease.lease_id)
    row = world.lease_row(handle.lease.lease_id)
    assert row["lease_state"] == "CLAIMED" and row["pod_id"] is not None
    assert _ownership_rows(db, row["pod_id"]), "ownership must exist while still CLAIMED"

    monkeypatch.undo()
    world.clock.advance(seconds=5)  # paid warmup time passes before the deadline shutdown
    world.leases.shutdown(handle.lease.lease_id, reason="CN-4 deadline reached")
    rows = _ownership_rows(db, row["pod_id"])
    assert len(rows) == 1
    assert rows[0]["owner_episode_id"] == episode.episode_id
    assert rows[0]["valid_until"] == world.lease_row(handle.lease.lease_id)["terminate_verified_at"]


def test_a_crash_before_the_ownership_write_is_healed_by_a_re_ensure(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T045-FIX A-S6: a crash between the ACTIVE write and the ownership open must not
    send the pod's disk to recovery forever - any later ensure opens it, exactly once.

    CN2-3 (2026-11-10): the POST-accept recorder now opens ownership atomically
    with the pod binding, so suppressing only the module-level open no longer
    reproduces the crash window - both open paths are suppressed to simulate a
    durable state where the row never landed, then the re-ensure heals it."""
    provider = RunpodIdFakePods(clock=FakeClock(T0), ids=SequentialIds("t045-own-crash1"))
    world = RenderWorld(db, provider=provider)
    episode = world.episode()
    monkeypatch.setattr("microdrama.rendering.leases.open_storage_ownership", lambda *a, **k: None)
    monkeypatch.setattr(
        "microdrama.rendering.leases.open_storage_ownership_in_tx", lambda *a, **k: None
    )
    handle, activated = world.claim_and_acquire(episode, "t045-own-crash-open")
    pod_id = activated.lease.pod_id
    assert activated.lease.lease_state == "ACTIVE"
    assert _ownership_rows(db, pod_id) == []  # the crash window: ACTIVE, no ownership row
    monkeypatch.undo()
    world.leases.ensure_pod(handle.lease.lease_id)
    rows = _ownership_rows(db, pod_id)
    assert len(rows) == 1
    assert rows[0]["owner_episode_id"] == episode.episode_id
    assert rows[0]["valid_until"] is None
    world.leases.ensure_pod(handle.lease.lease_id)  # the open is idempotent
    assert len(_ownership_rows(db, pod_id)) == 1


def test_a_crash_after_the_terminate_write_is_closed_by_the_janitor_at_the_persisted_instant(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T045-FIX A-S6: the terminate instant is persisted BEFORE the ownership close and
    the close reads the stored value; a crash in between is finished by the janitor at
    exactly terminate_verified_at - never a fresh clock read."""
    provider = RunpodIdFakePods(clock=FakeClock(T0), ids=SequentialIds("t045-own-crash2"))
    world = RenderWorld(db, provider=provider)
    episode = world.episode()
    handle, activated = world.claim_and_acquire(episode, "t045-own-crash-close")
    pod_id = activated.lease.pod_id
    world.clock.advance(seconds=600)
    monkeypatch.setattr("microdrama.rendering.leases.close_storage_ownership", lambda *a, **k: None)
    world.leases.shutdown(handle.lease.lease_id, reason="crash before the close")
    monkeypatch.undo()
    persisted = world.lease_row(handle.lease.lease_id)["terminate_verified_at"]
    assert persisted is not None  # the terminate write survived the crash
    assert _ownership_rows(db, pod_id)[0]["valid_until"] is None
    world.clock.advance(seconds=600)
    world.janitor().sweep()
    rows = _ownership_rows(db, pod_id)
    assert len(rows) == 1
    assert rows[0]["valid_until"] == persisted


def test_worker_death_right_after_post_accept_keeps_storage_attributed(
    db: Database,
) -> None:
    """CN2-3 (2026-11-10, re-review round 2): the POST-accept recorder bound the
    pod id durably, but a worker that dies immediately after the create POST
    never executes another ensure, activation or its shutdown handler - so no
    ownership row was ever opened (the round-1 heal paths all run inside the
    worker). The recorder must open storage ownership ATOMICALLY with the
    binding, and the janitor's bound-pod cleanup must heal any still-missing
    ownership before termination and accounting, or the pod's disk charges fall
    to the recovery pool."""
    from microdrama.contracts.errors import NeedsReconciliation
    from microdrama.testing.fakes import PodCreateScenario

    provider = RunpodIdFakePods(clock=FakeClock(T0), ids=SequentialIds("t045-own-postaccept"))
    provider.queue_scenarios(PodCreateScenario.CREATE_TIMEOUT_BUT_CREATED)
    world = RenderWorld(db, provider=provider)
    episode = world.episode()
    # A short ttl makes the abandoned claim expire by its own durable timestamps.
    handle = world.claim(episode, "t045-own-post-accept-death", ttl_ms=60_000)
    lease_id = handle.lease.lease_id
    row = world.lease_row(lease_id)
    world.leases._record_create_request(lease_id)
    spec = world.leases._spec_for(row)
    # The provider accepts the create POST and the recorder binds the pod id -
    # then the transport times out and the WORKER DIES: no manager-level
    # reconciliation, no ensure retry, no shutdown handler ever runs. (Going
    # through ensure_pod would legitimately adopt the just-created pod; the
    # direct provider call is exactly the POST-accept crash window.)
    with pytest.raises(NeedsReconciliation):
        world.provider.create_pod(
            world.manager.create_request(
                spec, name=world.leases._pod_name(row), client_token=row["client_token"]
            )
        )
    row = world.lease_row(lease_id)
    pod_id = row["pod_id"]
    assert pod_id is not None  # the POST-accept recorder bound it durably
    # Ownership opened ATOMICALLY with that binding - before any verification.
    rows = _ownership_rows(db, pod_id)
    assert len(rows) == 1
    assert rows[0]["owner_episode_id"] == episode.episode_id
    assert rows[0]["valid_from"] == row["create_requested_at"]
    assert rows[0]["valid_until"] is None
    # The worker stays dead; the janitor takes over the stale lease.
    world.clock.advance(seconds=900)
    world.janitor().sweep()
    lease_row = world.lease_row(lease_id)
    assert lease_row["terminate_verified_at"] is not None
    rows = _ownership_rows(db, pod_id)
    assert len(rows) == 1
    assert rows[0]["valid_until"] == lease_row["terminate_verified_at"]


def test_janitor_bound_pod_cleanup_heals_a_missing_ownership_row(db: Database) -> None:
    """CN2-3: independent belt-and-braces - even if the ownership open was lost
    (a pre-fix recorder binding, or an operator replay against old durable
    state), the janitor's BOUND-pod cleanup path heals the missing ownership
    before termination and accounting instead of closing a missing row and
    dropping the disk interval. The pre-fix state is CONSTRUCTED (binding
    without ownership), not produced by deleting guarded rows."""
    provider = RunpodIdFakePods(clock=FakeClock(T0), ids=SequentialIds("t045-own-heal"))
    world = RenderWorld(db, provider=provider)
    # Detach the recorder so the manual binding below reproduces exactly the
    # pre-CN2-3 durable state: pod id bound, create requested, no ownership.
    provider.created_pod_recorder = None
    episode = world.episode()
    handle = world.claim(episode, "t045-own-janitor-heal", ttl_ms=60_000)
    lease_id = handle.lease.lease_id
    row = world.lease_row(lease_id)
    world.leases._record_create_request(lease_id)
    spec = world.leases._spec_for(row)
    pod = world.manager.acquire_or_reconcile(
        spec, name=world.leases._pod_name(row), client_token=row["client_token"]
    )
    world.leases._record_pod_id(lease_id, pod.pod_id)
    pod_id = pod.pod_id
    assert _ownership_rows(db, pod_id) == []
    world.clock.advance(seconds=900)
    report = world.janitor().sweep()
    assert not report.failures, [f.detail for f in report.failures]
    lease_row = world.lease_row(lease_id)
    assert lease_row["terminate_verified_at"] is not None
    rows = _ownership_rows(db, pod_id)
    assert len(rows) == 1
    assert rows[0]["owner_episode_id"] == episode.episode_id
    assert rows[0]["valid_until"] == lease_row["terminate_verified_at"]
