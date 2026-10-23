"""AT-03 reproduced independently: the render gate around the episode-one lock.

A later episode cannot obtain render bindings before the episode-one identity
lock exists; the refusal is the typed ``IdentityLockRequired`` raised BEFORE any
dispatch; and once the season lock exists, a later episode must adopt it
explicitly before it may render.
"""

from __future__ import annotations

import uuid

import pytest

from microdrama.contracts.errors import IdentityLockRequired
from microdrama.persistence.db import insert_row

pytestmark = [pytest.mark.db, pytest.mark.slow]


def _episode(world, season_id: uuid.UUID, number: int) -> uuid.UUID:
    """An episode row bound to the season's approved scope (the runner's rule)."""
    episode_id = uuid.uuid4()
    with world.db.transaction() as tx:
        scope = tx.fetchone("SELECT approved_scope_hash FROM seasons WHERE id = %s", (season_id,))
        insert_row(
            tx,
            "episodes",
            {
                "id": episode_id,
                "season_id": season_id,
                "episode_number": number,
                "state": "PLANNED",
                "approved_scope_hash": scope["approved_scope_hash"],
            },
        )
    return episode_id


def _season(world) -> uuid.UUID:
    season_id = uuid.uuid4()
    with world.db.transaction() as tx:
        insert_row(
            tx,
            "seasons",
            {
                "id": season_id,
                "state": "PROPOSED",
                "title_th": "t",
                "title_en": "t",
                # A pre-approved-shaped scope so episodes can bind to it (the
                # reference gate reads the episode's copy, not the live proposal).
                "approved_scope_hash": "a" * 64,
            },
        )
    return season_id


def _refusal(world, episode_id) -> IdentityLockRequired:
    with pytest.raises(IdentityLockRequired) as excinfo:
        world.references.render_request_bindings(episode_id)
    return excinfo.value


def _hint(exc: Exception) -> str:
    return str(getattr(exc, "details", {}).get("hint", ""))


def test_later_episode_render_refused_before_any_lock(validation_world) -> None:
    world = validation_world
    season_id = _season(world)
    ep2 = _episode(world, season_id, number=2)
    exc = _refusal(world, ep2)
    assert "identity lock" in str(exc)
    assert "episode one has not been approved" in _hint(exc)


def test_episode_two_waits_while_the_pilot_proves_the_exemption(pilot) -> None:
    """The pilot itself is the episode-one exemption proof: its renders completed
    BEFORE the Gate 2 lock existed (timestamps from the durable rows), while any
    second episode in that same season is refused until the lock is adopted."""
    world, report = pilot
    with world.db.transaction(readonly=True) as tx:
        lock = tx.fetchone(
            "SELECT created_at FROM identity_locks WHERE id = %s", (report.identity_lock_id,)
        )
        renders = tx.fetchval(
            "SELECT count(*) FROM assets WHERE episode_id = %s "
            "AND object_key LIKE 'renders/%%' AND created_at < %s",
            (report.episode_id, lock["created_at"]),
        )
    assert renders >= 1, "episode-one renders must pre-date the identity lock"

    ep2 = _episode(world, report.season_id, number=2)
    exc = _refusal(world, ep2)
    assert "identity lock" in str(exc)
    assert "has not adopted" in _hint(exc)


def test_pilot_lock_adoption_is_explicit(pilot) -> None:
    """On the finished pilot: a newly created episode does NOT silently inherit
    the season lock — the typed refusal names adoption — and after
    ``attach_identity_lock`` the episode is stamped with the season's lock."""
    world, report = pilot
    season_id = report.season_id
    assert report.identity_lock_id is not None

    ep5 = _episode(world, season_id, number=5)
    exc = _refusal(world, ep5)
    assert "has not adopted" in _hint(exc)

    attached = world.references.attach_identity_lock(ep5)
    assert attached == report.identity_lock_id
    with world.db.transaction(readonly=True) as tx:
        stamped = tx.fetchval("SELECT identity_lock_id FROM episodes WHERE id = %s", (ep5,))
    assert stamped == report.identity_lock_id
