"""T011 concurrency: one lock per approval, one prepare per episode (two threads each)."""

from __future__ import annotations

import threading
import uuid

from microdrama.contracts.enums import ApprovalAction, GateType
from microdrama.contracts.season import ApprovalCommand


def _seed_gate2_approval(world, episode_id: uuid.UUID, *, revision: int) -> uuid.UUID:
    """A Gate 2 APPROVE row bound to the episode's stored package (DB-trigger-valid)."""
    import json

    from psycopg.types.json import Jsonb

    stored = world.row(
        "SELECT package_hash, media_hashes, management_policy_hash, release_scope_hash "
        "FROM release_packages WHERE episode_id = %s ORDER BY version DESC LIMIT 1",
        (episode_id,),
    )
    assert stored is not None
    media = stored["media_hashes"]
    if isinstance(media, str):  # psycopg may hand jsonb back as text in this context
        media = json.loads(media)
    with world.db.transaction() as tx:
        from microdrama.testing.seed import seed_human_session, seed_owner

        owner = seed_owner(tx)
        session = seed_human_session(tx, owner)
        approval_id = uuid.uuid4()
        tx.execute(
            "INSERT INTO approval_events (id, gate_type, action, entity_type, entity_id, "
            "expected_revision, package_hash, media_hashes, management_policy_hash, "
            "release_scope_hash, actor_owner_id, actor_session_id, idempotency_key, "
            "command_hash) VALUES (%s, 'EPISODE_FINAL', 'APPROVE', 'episode', %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, %s)",
            (
                approval_id,
                episode_id,
                revision,
                stored["package_hash"],
                Jsonb(media),
                stored["management_policy_hash"],
                stored["release_scope_hash"],
                owner,
                session,
                f"conc-{approval_id.hex}",
                stored["package_hash"],
            ),
        )
    return approval_id


def test_two_racing_lock_creations_produce_exactly_one_lock(world):
    season_id, scope, ep1, _outcome = world.prepared_episode()
    world.to_awaiting_review(ep1)
    package = world.store_review_package(season_id=season_id, scope=scope, episode_id=ep1)
    world.service.mark_reviewed_in_package(ep1)
    # Two independent approval events race to create the season's lock through the
    # real hook. The package is APPROVED the way the review flow leaves it.
    approval_a = _seed_gate2_approval(world, ep1, revision=0)
    approval_b = _seed_gate2_approval(world, ep1, revision=1)
    with world.db.transaction() as tx:
        tx.execute(
            "UPDATE release_packages SET status = 'APPROVED', approval_event_id = %s "
            "WHERE episode_id = %s",
            (approval_a, ep1),
        )
    hook = world.service.identity_lock_hook()
    command = ApprovalCommand(
        gate=GateType.EPISODE_FINAL,
        action=ApprovalAction.APPROVE,
        entity_id=ep1,
        expected_revision=0,
        package_hash=package.package_hash,
        media_hashes=package.media_hashes,
        management_policy_hash=package.management_policy_hash,
        release_scope_hash=package.release_scope_hash,
        idempotency_key=f"conc-{uuid.uuid4().hex}",
    )
    outcomes: list = []
    barrier = threading.Barrier(2)

    def run(approval_id):
        barrier.wait()
        try:
            with world.db.transaction() as tx:
                hook.on_recorded(
                    tx,
                    approval_event_id=approval_id,
                    command=command.model_copy(
                        update={"idempotency_key": f"conc-{approval_id.hex}"}
                    ),
                    principal=world.human(),
                )
            outcomes.append(("ok", approval_id))
        except Exception as exc:  # noqa: BLE001 - the loser's typed error is the answer
            outcomes.append((type(exc).__name__, approval_id))

    threads = [
        threading.Thread(target=run, args=(approval_a,)),
        threading.Thread(target=run, args=(approval_b,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert sorted(tag for tag, _ in outcomes) == ["Conflict", "ok"]
    assert (
        world.count("SELECT COUNT(*) FROM identity_locks WHERE season_id = %s", (season_id,)) == 1
    )
    assert (
        world.count(
            "SELECT COUNT(*) FROM identity_lock_assets la JOIN identity_locks l "
            "ON l.id = la.lock_id WHERE l.season_id = %s",
            (season_id,),
        )
        == 12
    )


def test_two_racing_prepares_dispatch_exactly_one(world):
    season_id, scope = world.season()
    episode_id = world.episode(season_id, scope)
    world.seed_script_and_manifest(episode_id=episode_id, scope=scope)
    outcomes: list = []
    barrier = threading.Barrier(2)

    def run():
        barrier.wait()
        try:
            outcomes.append(("ok", world.service.prepare_episode(episode_id)))
        except Exception as exc:  # noqa: BLE001 - the racer's typed conflict is expected
            outcomes.append((type(exc).__name__, None))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    tags = sorted(tag for tag, _ in outcomes)
    assert tags == ["Conflict", "ok"]
    # Exactly one paid pipeline ran: 18 reservations, one current filled script pair.
    assert (
        world.count("SELECT COUNT(*) FROM reservations WHERE episode_id = %s", (episode_id,)) == 18
    )
    assert (
        world.count(
            "SELECT COUNT(*) FROM scripts WHERE episode_id = %s AND status = 'CURRENT'",
            (episode_id,),
        )
        == 1
    )
    assert (
        world.row("SELECT correlation_id FROM episodes WHERE id = %s", (episode_id,))[
            "correlation_id"
        ]
        is None
    )
    assert world.episode_state(episode_id) == "RENDERING"
