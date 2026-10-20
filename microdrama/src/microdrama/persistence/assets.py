"""Asset metadata repository: private object references, hashes, lineage, state.

The database row is the durable record of an asset (descriptor JSON plus indexed
columns); the bytes live in the private object store under ``object_key``.
``verify_persisted`` re-hashes the stored object before a pipeline step may rely
on it (e.g. before GPU shutdown or Gate 2).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from microdrama.contracts.enums import AssetState
from microdrama.contracts.errors import Conflict, NotFound
from microdrama.contracts.infra import ObjectStore
from microdrama.contracts.media import AssetDescriptor
from microdrama.persistence.db import Tx, get_row, insert_row, jsonb, update_with_revision


def register_asset(
    tx: Tx, descriptor: AssetDescriptor, *, generation_key: str | None = None
) -> AssetDescriptor:
    """Insert an asset row and its lineage edges. Idempotent for an identical descriptor."""
    existing = tx.fetchone("SELECT descriptor FROM assets WHERE id = %s", (descriptor.asset_id,))
    if existing is not None:
        stored = AssetDescriptor.model_validate(existing["descriptor"])
        if stored != descriptor:
            raise Conflict(f"asset {descriptor.asset_id} already registered with different content")
        return stored
    media = descriptor.media
    insert_row(
        tx,
        "assets",
        {
            "id": descriptor.asset_id,
            "schema_version": descriptor.schema_version,
            "asset_kind": descriptor.asset_kind.value,
            "object_key": descriptor.object_key,
            "sha256": descriptor.sha256,
            "size_bytes": descriptor.size_bytes,
            "media_type": descriptor.media_type,
            "media": jsonb(media) if media is not None else None,
            "duration_ms": media.duration_ms if media is not None else None,
            "state": descriptor.state.value,
            "provenance": descriptor.provenance.value,
            "season_id": descriptor.season_id,
            "episode_id": descriptor.episode_id,
            "version": descriptor.version,
            "license_refs": jsonb(descriptor.license_refs),
            "generation_key": generation_key,
            "descriptor": jsonb(descriptor),
            "created_at": descriptor.created_at,
            "updated_at": descriptor.created_at,
        },
        returning="id",
    )
    for source in descriptor.lineage:
        tx.execute(
            "INSERT INTO asset_lineage (asset_id, source_asset_id) VALUES (%s, %s)",
            (descriptor.asset_id, source),
        )
    return descriptor


def get_asset(tx: Tx, asset_id: UUID) -> AssetDescriptor:
    row = get_row(tx, "assets", asset_id)
    descriptor = AssetDescriptor.model_validate(row["descriptor"])
    if descriptor.state.value != row["state"]:
        descriptor = descriptor.model_copy(update={"state": AssetState(row["state"])})
    return descriptor


def asset_revision(tx: Tx, asset_id: UUID) -> int:
    row = tx.fetchone("SELECT revision FROM assets WHERE id = %s", (asset_id,))
    if row is None:
        raise NotFound(f"asset {asset_id} not found")
    return int(row["revision"])


def set_asset_state(tx: Tx, asset_id: UUID, state: AssetState, *, expected_revision: int) -> None:
    update_with_revision(tx, "assets", asset_id, expected_revision, {"state": state.value})


def lineage_sources(tx: Tx, asset_id: UUID) -> list[UUID]:
    rows = tx.fetchall(
        "SELECT source_asset_id FROM asset_lineage WHERE asset_id = %s ORDER BY source_asset_id",
        (asset_id,),
    )
    return [r["source_asset_id"] for r in rows]


def verify_persisted(
    tx: Tx, store: ObjectStore, asset_id: UUID, *, now: datetime | None = None
) -> bool:
    """Re-hash the stored object; records ``verified_at`` only on a match."""
    row = get_row(tx, "assets", asset_id)
    ok = store.verify(row["object_key"], row["sha256"])
    if ok:
        tx.execute(
            "UPDATE assets SET verified_at = coalesce(%s, now()) WHERE id = %s",
            (now, asset_id),
        )
    return ok
