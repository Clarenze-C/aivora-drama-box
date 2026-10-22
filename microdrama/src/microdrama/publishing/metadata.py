"""Post metadata versions (T020): immutable rows, one current version per post.

Media on a slot is immutable (the platform_posts trigger pins asset_id/asset_sha256 at
schedule time); metadata is the mutable surface, and every change is a new append-only
``metadata_versions`` row — the row content itself is trigger-immutable, deletion is
forbidden. "Current" is the row ``platform_posts.current_metadata_version_id`` points at,
and only an applied row may be current.

Version ids are deterministic for the initial version (the publication command names the
version before it exists), and caller-supplied for later edits (T025's metadata workers
mint them). A rollback is an ordinary new version that records ``rollback_of``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

from microdrama.contracts.errors import Conflict, NotFound, SchemaInvalid
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.release import PostMetadata
from microdrama.persistence.db import Tx, insert_row, update_with_revision
from microdrama.publishing.slots import POST_NAMESPACE

# Fields whose change is substantive (needs the management policy) versus cosmetic.
SUBSTANTIVE_FIELDS = (
    "title",
    "caption",
    "description",
    "hashtags",
    "cover_asset_id",
    "links",
    "disclosures",
)


def initial_metadata_version_id(dedupe_key: str) -> UUID:
    """Deterministic id of a post's version-1 metadata row (the command names it first)."""
    return uuid5(POST_NAMESPACE, f"metadata-v1:{dedupe_key}")


def metadata_hash(metadata: PostMetadata) -> str:
    return canonical_hash(metadata)


def substantive_change(old: PostMetadata, new: PostMetadata) -> bool:
    """True when any policy-gated field differs between two metadata versions."""
    return any(getattr(old, field) != getattr(new, field) for field in SUBSTANTIVE_FIELDS)


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchemaInvalid(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _post(tx: Tx, post_id: UUID) -> dict[str, Any]:
    row = tx.fetchone("SELECT * FROM platform_posts WHERE id = %s", (post_id,))
    if row is None:
        raise NotFound(f"platform post {post_id} not found")
    return row


def create_version(
    tx: Tx,
    *,
    post_id: UUID,
    version_id: UUID,
    metadata: PostMetadata,
    policy_hash: str,
    now: datetime,
    rollback_of: UUID | None = None,
) -> int:
    """Insert the next metadata version row (applied immediately); return its version number.

    Version numbers are dense and per-post. The row lands applied (``applied_at`` set) and
    becomes the post's current version — there is no proposed-applied gap in this lane;
    T025's policy checks run before it calls this.
    """
    if not isinstance(metadata, PostMetadata):
        raise SchemaInvalid("a PostMetadata is required")
    instant = _aware(now, "now")
    post = _post(tx, post_id)
    if rollback_of is not None:
        target = tx.fetchone(
            "SELECT id, version FROM metadata_versions WHERE id = %s AND platform_post_id = %s",
            (rollback_of, post_id),
        )
        if target is None:
            raise NotFound(f"rollback target {rollback_of} is not a version of this post")
    latest = tx.fetchone(
        "SELECT version, metadata FROM metadata_versions WHERE platform_post_id = %s "
        "ORDER BY version DESC LIMIT 1",
        (post_id,),
    )
    version = 1 if latest is None else int(latest["version"]) + 1
    substantive = True
    if latest is not None:
        previous = PostMetadata.model_validate(latest["metadata"])
        substantive = substantive_change(previous, metadata)
    insert_row(
        tx,
        "metadata_versions",
        {
            "id": version_id,
            "platform_post_id": post_id,
            "version": version,
            "metadata": metadata,
            "metadata_hash": metadata_hash(metadata),
            "substantive": substantive,
            "policy_hash": policy_hash,
            "catalog_version": metadata.catalog_version,
            "rollback_of": rollback_of,
            "applied_at": instant,
            "created_at": instant,
        },
    )
    update_with_revision(
        tx,
        "platform_posts",
        post_id,
        int(post["revision"]),
        {"current_metadata_version_id": version_id},
        now=instant,
    )
    return version


def current_metadata(tx: Tx, post_id: UUID) -> tuple[UUID, PostMetadata] | None:
    """The post's current applied metadata, or None before the first submit."""
    post = _post(tx, post_id)
    if post["current_metadata_version_id"] is None:
        return None
    row = tx.fetchone(
        "SELECT * FROM metadata_versions WHERE id = %s", (post["current_metadata_version_id"],)
    )
    if row is None or row["applied_at"] is None:
        raise Conflict(
            "current metadata version is missing or unapplied; operator review needed",
            version_id=str(post["current_metadata_version_id"]),
        )
    return row["id"], PostMetadata.model_validate(row["metadata"])


def require_current(tx: Tx, post_id: UUID, version_id: UUID) -> PostMetadata:
    """The metadata a publication command must carry: exactly the current version."""
    current = current_metadata(tx, post_id)
    if current is None:
        raise Conflict("post has no current metadata version yet", post_id=str(post_id))
    if current[0] != version_id:
        raise Conflict(
            "command metadata version is not the post's current version",
            current_version=str(current[0]),
            command_version=str(version_id),
        )
    return current[1]
