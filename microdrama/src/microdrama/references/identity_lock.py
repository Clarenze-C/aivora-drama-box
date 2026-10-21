"""The episode-one identity lock and its Gate 2 approval hook (T011, IMP-01, AT-03).

``IdentityLockHook`` implements the frozen ``core.hooks.ApprovalHook`` protocol T008
calls *inside* the Gate 2 approval transaction: episode one only, APPROVE only. A
raising hook rolls the whole approval back (T008 proved that with a stub; this is
the real implementation the integrator wires in through
``ReferencesService.identity_lock_hook()``).

What gets locked — exactly the *included reviewed* asset versions of the approved
package:

- the reference version's asset is in the approved package's
  ``cast_package_asset_ids`` (included), and
- the version is state ACCEPTED with ``reviewed_in_package_id`` set (reviewed) —
  ``mark_reviewed_in_package`` sets this when the packaging step stores a package.

PROVISIONAL (never reviewed) and SUPERSEDED/FAILED versions are never locked, so
unreviewed or invalidated assets never inherit a lock. If nothing qualifies the
lock is refused typed and the approval transaction rolls back — a Gate 2 approval
that cannot create the lock it promises is not an approval.

Locks are append-only (migration 0002): ``identity_locks``/``identity_lock_assets``
rows can never be updated or deleted, and a member version superseded later leaves
the lock intact but *broken* — ``broken_member_keys`` reports it and
``render_request_bindings`` refuses to bind later-episode renders to a broken lock
until a new Gate 2 approval mints a new lock version.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from microdrama.contracts.enums import (
    ApprovalAction,
    GateType,
    IdentityAssetKind,
)
from microdrama.contracts.errors import Conflict, NotFound, SchemaInvalid, StaleRevision
from microdrama.contracts.principals import Principal
from microdrama.contracts.season import ApprovalCommand, IdentityLock, LockedAsset
from microdrama.core.events import append_event
from microdrama.persistence.db import Tx, insert_row, jsonb, update_with_revision
from microdrama.references.anchors import ref_id_for
from microdrama.review.packages import PackageStatus, current_package


class IdentityLockHook:
    """The ``ApprovalHook`` T008 calls inside the episode-one Gate 2 approval."""

    def __init__(self, locks: IdentityLocks) -> None:
        self._locks = locks

    def on_recorded(
        self,
        tx: Tx,
        *,
        approval_event_id: UUID,
        command: ApprovalCommand,
        principal: Principal,
    ) -> None:
        self._locks.create_lock(
            tx,
            approval_event_id=approval_event_id,
            command=command,
            principal=principal,
        )


class IdentityLocks:
    """Lock creation and queries. All writes run inside the caller's transaction."""

    def __init__(self, clock) -> None:
        self._clock = clock

    def _now(self) -> datetime:
        return self._clock.now()

    # --- creation (inside the approval transaction) --------------------------------------

    def create_lock(
        self,
        tx: Tx,
        *,
        approval_event_id: UUID,
        command: ApprovalCommand,
        principal: Principal,
    ) -> UUID:
        del principal  # the review service already authenticated the human owner
        if (
            command.gate is not GateType.EPISODE_FINAL
            or command.action is not ApprovalAction.APPROVE
        ):
            raise SchemaInvalid(
                "the identity lock is created by an episode Gate 2 APPROVE only",
                gate=command.gate.value,
                action=command.action.value,
            )
        episode = tx.fetchone(
            "SELECT * FROM episodes WHERE id = %s FOR UPDATE", (command.entity_id,)
        )
        if episode is None:
            raise NotFound(
                "identity lock source episode not found", episode_id=str(command.entity_id)
            )
        if episode["episode_number"] != 1:
            raise SchemaInvalid(
                "the identity lock comes from the episode-one Gate 2 approval only",
                episode_number=episode["episode_number"],
            )
        # Serialise concurrent lock creation on the season row before reading versions.
        season = tx.fetchone(
            "SELECT * FROM seasons WHERE id = %s FOR UPDATE", (episode["season_id"],)
        )
        if season is None:
            raise NotFound("season not found", season_id=str(episode["season_id"]))
        stored = current_package(tx, command.entity_id)
        if stored is None:
            raise Conflict("episode one has no release package to derive the identity lock from")
        if stored.status is not PackageStatus.APPROVED:
            raise Conflict(
                f"the identity lock binds the APPROVED package; this one is {stored.status.value}",
                package_status=stored.status.value,
            )
        if stored.package_hash != command.package_hash:
            raise StaleRevision(
                "the approved package hash does not match the decision",
                current_package_hash=stored.package_hash,
            )
        existing_for_episode = tx.fetchone(
            "SELECT id, version FROM identity_locks WHERE source_episode_id = %s",
            (command.entity_id,),
        )
        if existing_for_episode is not None:
            raise Conflict(
                "this episode already created its identity lock",
                lock_id=str(existing_for_episode["id"]),
                version=existing_for_episode["version"],
            )
        cast_ids = list(stored.package.cast_package_asset_ids)
        members = tx.fetchall(
            "SELECT * FROM reference_versions WHERE season_id = %s "
            "AND state = 'ACCEPTED' AND reviewed_in_package_id IS NOT NULL "
            "AND asset_id = ANY(%s) ORDER BY ref_kind, ref_key, version",
            (season["id"], cast_ids),
        )
        if not members:
            raise Conflict(
                "the approved package contains no reviewed reference versions to lock; "
                "unreviewed assets never inherit a lock",
                cast_assets=len(cast_ids),
            )
        version = int(
            tx.fetchval(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM identity_locks WHERE season_id = %s",
                (season["id"],),
            )
            or 1
        )
        lock_id = ref_id_for("lock", f"{season['id']}:v{version}")
        body = IdentityLock(
            lock_id=lock_id,
            season_id=season["id"],
            source_episode_id=command.entity_id,
            version=version,
            approval_event_id=approval_event_id,
            release_package_hash=stored.package_hash,
            locked_assets=[
                LockedAsset(
                    asset_kind=IdentityAssetKind(member["ref_kind"]),
                    asset_id=member["asset_id"],
                    asset_version=member["version"],
                    content_sha256=member["content_sha256"],
                    character_id=member["character_key"],
                    label=f"{member['ref_kind']} {member['ref_key']} v{member['version']}"[:500],
                )
                for member in members
            ],
            created_at=self._now(),
        )
        insert_row(
            tx,
            "identity_locks",
            {
                "id": lock_id,
                "season_id": season["id"],
                "source_episode_id": command.entity_id,
                "version": version,
                "approval_event_id": approval_event_id,
                "release_package_hash": stored.package_hash,
                "body": jsonb(body),
                "created_at": self._now(),
            },
            returning="id",
        )
        locked_character_keys: list[str] = []
        identity_kinds = (IdentityAssetKind.FACE.value, IdentityAssetKind.VOICE.value)
        for member in members:
            insert_row(
                tx,
                "identity_lock_assets",
                {
                    "lock_id": lock_id,
                    "reference_version_id": member["id"],
                    "asset_id": member["asset_id"],
                    "content_sha256": member["content_sha256"],
                    "asset_kind": member["ref_kind"],
                },
                returning="lock_id",
            )
            update_with_revision(
                tx,
                "reference_versions",
                member["id"],
                member["revision"],
                {"state": "LOCKED"},
                now=self._now(),
            )
            if member["character_key"] and member["ref_kind"] in identity_kinds:
                locked_character_keys.append(member["character_key"])
        tx.execute(
            "UPDATE voices SET state = 'LOCKED', revision = revision + 1, updated_at = %s "
            "WHERE season_id = %s AND anchor_asset_id = ANY(%s) "
            "AND state IN ('PROVISIONAL', 'ACCEPTED')",
            (self._now(), season["id"], [m["asset_id"] for m in members]),
        )
        if locked_character_keys:
            tx.execute(
                "UPDATE characters SET state = 'LOCKED', revision = revision + 1, updated_at = %s "
                "WHERE season_id = %s AND character_key = ANY(%s) AND state = 'PROVISIONAL'",
                (self._now(), season["id"], sorted(set(locked_character_keys))),
            )
        # Stamp the season's LATER episodes so story/render lanes see the lock. The
        # source episode itself is deliberately not stamped here: the review flow
        # still holds its row at the revision it read, and its lock binding lives in
        # identity_locks.source_episode_id anyway.
        stamped = tx.fetchall(
            "SELECT id, revision FROM episodes WHERE season_id = %s "
            "AND episode_number > 1 AND identity_lock_id IS NULL FOR UPDATE",
            (season["id"],),
        )
        for row in stamped:
            update_with_revision(
                tx,
                "episodes",
                row["id"],
                row["revision"],
                {"identity_lock_id": lock_id},
                now=self._now(),
            )
        append_event(
            tx,
            aggregate_type="season",
            aggregate_id=season["id"],
            event_type="references.identity_lock_created",
            payload={
                "lock_id": str(lock_id),
                "version": version,
                "source_episode_id": str(command.entity_id),
                "approval_event_id": str(approval_event_id),
                "release_package_hash": stored.package_hash,
                "locked_members": len(members),
                "locked_ref_keys": [f"{m['ref_kind']}:{m['ref_key']}" for m in members[:20]],
                "episodes_stamped": len(stamped),
            },
            correlation_id=approval_event_id,
            occurred_at=self._now(),
        )
        return lock_id

    # --- queries ----------------------------------------------------------------------------

    @staticmethod
    def current_lock_row(tx: Tx, season_id: UUID) -> dict[str, Any] | None:
        return tx.fetchone(
            "SELECT * FROM identity_locks WHERE season_id = %s ORDER BY version DESC LIMIT 1",
            (season_id,),
        )

    @staticmethod
    def members(tx: Tx, lock_id: UUID) -> list[dict[str, Any]]:
        return tx.fetchall(
            "SELECT rv.*, la.asset_kind AS locked_kind FROM identity_lock_assets la "
            "JOIN reference_versions rv ON rv.id = la.reference_version_id "
            "WHERE la.lock_id = %s ORDER BY rv.ref_kind, rv.ref_key",
            (lock_id,),
        )

    @classmethod
    def broken_member_keys(cls, tx: Tx, lock_id: UUID) -> list[str]:
        """Members whose version left LOCKED state (superseded after the lock)."""
        rows = cls.members(tx, lock_id)
        return [f"{r['ref_kind']}:{r['ref_key']}" for r in rows if r["state"] != "LOCKED"]


def reviewed_members_of(
    tx: Tx, season_id: UUID, cast_asset_ids: list[UUID]
) -> list[dict[str, Any]]:
    """The reviewed ACCEPTED versions of a package's cast assets (lock candidates)."""
    return tx.fetchall(
        "SELECT * FROM reference_versions WHERE season_id = %s AND state = 'ACCEPTED' "
        "AND reviewed_in_package_id IS NOT NULL AND asset_id = ANY(%s) "
        "ORDER BY ref_kind, ref_key, version",
        (season_id, list(cast_asset_ids)),
    )


def mark_reviewed(
    tx: Tx,
    *,
    season_id: UUID,
    package_row_id: UUID,
    cast_asset_ids: list[UUID],
    now: datetime,
) -> int:
    """PROVISIONAL cast reference versions of a stored package become ACCEPTED/reviewed."""
    updated = tx.fetchall(
        "UPDATE reference_versions SET state = 'ACCEPTED', reviewed_in_package_id = %s, "
        "revision = revision + 1, updated_at = %s "
        "WHERE season_id = %s AND asset_id = ANY(%s) AND state = 'PROVISIONAL' "
        "RETURNING id, ref_kind, ref_key, version",
        (package_row_id, now, season_id, list(cast_asset_ids)),
    )
    if updated:
        append_event(
            tx,
            aggregate_type="season",
            aggregate_id=season_id,
            event_type="references.cast_reviewed",
            payload={
                "package_row_id": str(package_row_id),
                "reviewed": [
                    f"{row['ref_kind']}:{row['ref_key']}:v{row['version']}" for row in updated[:20]
                ],
                "reviewed_count": len(updated),
            },
            correlation_id=package_row_id,
            occurred_at=now,
        )
    return len(updated)


__all__ = [
    "IdentityLockHook",
    "IdentityLocks",
    "mark_reviewed",
    "reviewed_members_of",
]
