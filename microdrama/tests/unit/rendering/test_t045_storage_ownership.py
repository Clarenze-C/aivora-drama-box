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
