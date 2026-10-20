"""Release packages: the immutable content Gate 2 reviews, one current package per episode.

Table ``release_packages`` (migration 0005, guarded by 0007-0009). The row's content (body, media
hashes, policy hash, release-scope hash) is immutable; only status, gate blockers, the decision
link and revision move. The status machine enforced by the database is:

- DRAFT/READY/BLOCKED -> SUPERSEDED when a newer version is stored (REVISED/REJECTED are terminal
  decisions and stay as they are);
- READY -> APPROVED | REVISED | REJECTED, BLOCKED -> REVISED | REJECTED (each bound to the Gate 2
  event with the same package hash); APPROVED is only ever left by supersession.

A material media change is therefore always a new package with a new hash.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from microdrama.contracts.enums import EpisodeState
from microdrama.contracts.errors import Conflict, NotFound, SchemaInvalid
from microdrama.contracts.release import ReleasePackage
from microdrama.persistence.db import Tx, insert_row, jsonb, update_with_revision

# Episode states in which a new release package may still be stored. From RELEASE_APPROVED on the
# package is decided and the episode is in the publication pipeline.
_PACKAGE_STORABLE_STATES = frozenset(
    {
        EpisodeState.PLANNED.value,
        EpisodeState.SCRIPTING.value,
        EpisodeState.REFERENCES.value,
        EpisodeState.RENDERING.value,
        EpisodeState.ASSEMBLING.value,
        EpisodeState.AI_REVIEW.value,
        EpisodeState.AWAITING_FINAL_REVIEW.value,
    }
)


class PackageStatus(StrEnum):
    DRAFT = "DRAFT"
    READY = "READY"
    BLOCKED = "BLOCKED"
    APPROVED = "APPROVED"
    REVISED = "REVISED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


_NEW_STATUSES = frozenset({PackageStatus.DRAFT, PackageStatus.READY, PackageStatus.BLOCKED})
_OPEN_STATUSES = ("DRAFT", "READY", "BLOCKED")


@dataclass(frozen=True)
class StoredPackage:
    """A stored release package together with its row state (module-internal helper)."""

    row_id: UUID
    episode_id: UUID
    version: int
    status: PackageStatus
    revision: int
    approval_event_id: UUID | None
    gate_blockers: tuple[str, ...]
    package: ReleasePackage

    @property
    def package_hash(self) -> str:
        return self.package.package_hash

    @property
    def media_hashes(self) -> list[str]:
        return self.package.media_hashes

    @property
    def management_policy_hash(self) -> str:
        return self.package.management_policy_hash

    @property
    def release_scope_hash(self) -> str:
        return self.package.release_scope_hash


def _from_row(row: dict[str, Any]) -> StoredPackage:
    return StoredPackage(
        row_id=row["id"],
        episode_id=row["episode_id"],
        version=row["version"],
        status=PackageStatus(row["status"]),
        revision=row["revision"],
        approval_event_id=row["approval_event_id"],
        gate_blockers=tuple(row["gate_blockers"] or []),
        package=ReleasePackage.model_validate(row["body"]),
    )


def current_package(tx: Tx, episode_id: UUID) -> StoredPackage | None:
    """The newest non-superseded package of the episode (the one a decision must name)."""
    row = tx.fetchone(
        "SELECT * FROM release_packages WHERE episode_id = %s AND status <> 'SUPERSEDED' "
        "ORDER BY version DESC LIMIT 1",
        (episode_id,),
    )
    return None if row is None else _from_row(row)


def store_release_package(
    tx: Tx,
    package: ReleasePackage,
    *,
    status: PackageStatus | str,
    now: datetime | None = None,
) -> UUID:
    """Store a new package version for its episode and make it the current one.

    - ``status`` is DRAFT, READY (no gate blockers) or BLOCKED (at least one blocker).
    - The version must be greater than every stored version of the episode.
    - Earlier DRAFT/READY/BLOCKED versions are superseded; REVISED/REJECTED stay terminal.
    - An episode with an APPROVED package, a recorded outcome, or a state past Gate 2 cannot
      receive a new package here (a material change after approval has no state path back to
      Gate 2 in the frozen state table, so it is refused rather than silently approved).
    - ``episodes.current_package_id`` is updated with a revision bump, so any decision prepared
      against the previous view is stale.
    """
    if not isinstance(package, ReleasePackage):
        raise SchemaInvalid("a ReleasePackage is required")
    new_status = PackageStatus(status)
    if new_status not in _NEW_STATUSES:
        raise SchemaInvalid("new release packages start as DRAFT, READY or BLOCKED")
    if new_status is PackageStatus.READY and package.gate_blockers:
        raise SchemaInvalid("a READY package carries no gate blockers")
    if new_status is PackageStatus.BLOCKED and not package.gate_blockers:
        raise SchemaInvalid("a BLOCKED package must name its blockers")

    episode = tx.fetchone(
        "SELECT id, season_id, episode_number, state, outcome, revision FROM episodes "
        "WHERE id = %s FOR UPDATE",
        (package.episode_id,),
    )
    if episode is None:
        raise NotFound(f"episode {package.episode_id} not found")
    if episode["season_id"] != package.season_id or episode["episode_number"] != (
        package.episode_number
    ):
        raise Conflict("package does not match the episode it is stored for")
    if episode["outcome"] is not None or episode["state"] not in _PACKAGE_STORABLE_STATES:
        raise Conflict(
            f"episode is {episode['state']} (outcome {episode['outcome']}); "
            "no new release package can be stored",
        )
    approved = tx.fetchone(
        "SELECT id FROM release_packages WHERE episode_id = %s AND status = 'APPROVED'",
        (package.episode_id,),
    )
    if approved is not None:
        raise Conflict("episode already has an APPROVED release package")
    latest = tx.fetchone(
        "SELECT version FROM release_packages WHERE episode_id = %s ORDER BY version DESC LIMIT 1",
        (package.episode_id,),
    )
    if latest is not None and package.version <= latest["version"]:
        raise Conflict(
            "package version must increase",
            stored_version=latest["version"],
            requested_version=package.version,
        )

    tx.execute(
        "UPDATE release_packages SET status = 'SUPERSEDED', revision = revision + 1, "
        "updated_at = coalesce(%s, now()) WHERE episode_id = %s AND status = ANY(%s)",
        (now, package.episode_id, list(_OPEN_STATUSES)),
    )
    row_values: dict[str, Any] = {
        "id": package.package_id,
        "episode_id": package.episode_id,
        "version": package.version,
        "package_hash": package.package_hash,
        "body": jsonb(package),
        "media_hashes": jsonb(package.media_hashes),
        "management_policy_hash": package.management_policy_hash,
        "release_scope_hash": package.release_scope_hash,
        "status": new_status.value,
        "gate_blockers": jsonb(list(package.gate_blockers)),
    }
    if now is not None:
        row_values.update(created_at=now, updated_at=now)
    inserted = insert_row(tx, "release_packages", row_values, returning="id")
    package_row_id: UUID = inserted["id"]
    update_with_revision(
        tx,
        "episodes",
        package.episode_id,
        episode["revision"],
        {"current_package_id": package_row_id},
        now=now,
    )
    return package_row_id


def record_package_decision(
    tx: Tx,
    stored: StoredPackage,
    *,
    status: PackageStatus,
    approval_event_id: UUID,
    now: datetime,
) -> None:
    """Bind a Gate 2 decision to the package (the database checks hashes and blockers)."""
    update_with_revision(
        tx,
        "release_packages",
        stored.row_id,
        stored.revision,
        {"status": status.value, "approval_event_id": approval_event_id},
        now=now,
    )


__all__ = [
    "PackageStatus",
    "StoredPackage",
    "current_package",
    "record_package_decision",
    "store_release_package",
]
