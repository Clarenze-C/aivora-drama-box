"""Grounded metadata workers (T025): titles/captions/hashtags/cover selection.

Metadata optimization is bounded and grounded: hashtags come only from the
approved vocabulary (season genre tags plus hashtags already live on the post),
and covers are selected only from the episode's approved release-package cover
assets. The worker never invents facts — a title/caption rewrite that is not
backed by the grounding facts fails ``validate_claims`` in the service before
any version row exists. Costs: the optimization step is metered management
(the service reserves before applying); the platform API push itself is
unmetered (contract 1.6.0 ``publish.update_metadata``).
"""

from __future__ import annotations

from uuid import UUID

from microdrama.community.grounding import GroundingFacts
from microdrama.contracts.errors import PolicyDenied
from microdrama.contracts.release import PostMetadata
from microdrama.persistence.db import Tx

#: Contract ceiling on PostMetadata.hashtags; the worker stays well below it.
MAX_HASHTAGS = 30


def propose_hashtag_optimization(current: PostMetadata, facts: GroundingFacts) -> PostMetadata:
    """Append missing approved hashtags (deterministic, sorted, bounded).

    Raises PolicyDenied when there is nothing to add — an edit that changes
    nothing is not an optimization and must not create a version row.
    """
    missing = sorted(facts.approved_hashtags - set(current.hashtags))
    if not missing:
        raise PolicyDenied(
            "no approved hashtag is missing from the current metadata",
            current_hashtags=list(current.hashtags),
        )
    merged = sorted({*current.hashtags, *missing})[:MAX_HASHTAGS]
    return current.model_copy(update={"hashtags": merged})


def cover_assets_for_post(tx: Tx, platform_post_id: UUID) -> frozenset[UUID]:
    """Cover-role asset ids from the post's approved release package (read-only)."""
    row = tx.fetchone(
        "SELECT rp.body FROM platform_posts p JOIN release_packages rp "
        "ON rp.id = p.release_package_id WHERE p.id = %s",
        (platform_post_id,),
    )
    if row is None:
        return frozenset()
    from microdrama.contracts.release import ReleasePackage

    package = ReleasePackage.model_validate(row["body"])
    return frozenset(media.asset_id for media in package.media if media.role == "cover")


def propose_cover_change(
    current: PostMetadata, cover_asset_id: UUID, *, allowed_cover_asset_ids: frozenset[UUID]
) -> PostMetadata:
    """Select a cover only from the approved cover assets of this post's package."""
    if cover_asset_id not in allowed_cover_asset_ids:
        raise PolicyDenied(
            "cover asset is not an approved cover of this post's release package",
            cover_asset_id=str(cover_asset_id),
        )
    if current.cover_asset_id == cover_asset_id:
        raise PolicyDenied("cover asset is already the selected cover")
    return current.model_copy(update={"cover_asset_id": cover_asset_id})


__all__ = [
    "MAX_HASHTAGS",
    "cover_assets_for_post",
    "propose_cover_change",
    "propose_hashtag_optimization",
]
