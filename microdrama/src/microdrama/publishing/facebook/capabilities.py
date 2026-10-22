"""Frozen research snapshot of the Facebook Pages publishing surface (T024).

Every claim below is sourced from OFFICIAL_DOCUMENTATION only (Meta developers docs,
snapshot as-of 2026-10, refs inline). The strongest claim this file may make is
``SUPPORTED_DOCUMENTED`` — ``SUPPORTED_TESTED`` is reserved for T032 (controlled
account tests) and must never appear here. Uncertain == ``UNKNOWN``; there is no
speculative capability.

The core truth of this packet (task_breakdown §5 T024): the SHORT-Reel route and the
FULL-video route are EXPLICIT and separate documented surfaces. Neither implies the
other:

- ``UPLOAD_FULL_VIDEO`` — Page videos edge ``POST /{page-id}/videos`` with the
  documented resumable ``upload_phase`` protocol (start / transfer / finish),
  ``title``/``description`` and ``scheduled_publish_time``.
- ``UPLOAD_SHORT`` — Page Reels container flow ``POST /{page-id}/video_reels``
  (upload_phase start/transfer/publish) with ``GET /{video-id}/video_status``.
- ``SCHEDULE`` — ``scheduled_publish_time`` is documented on the Page VIDEOS edge
  only; the Reels surface documents no scheduled-publish parameter, so the adapter
  refuses future-window short slots instead of inferring schedule support.

Declaration truth (AI disclosure): the snapshot found NO documented Graph API field
that both SETS and READS BACK a synthetic-content/AI label for an organic Page video
post. ``AI_DISCLOSURE`` is therefore ``UNKNOWN`` and ``supported_disclosures`` stays
empty — every release slot (MD-015 requires ``AI_GENERATED_CONTENT`` on every slot)
HELDs with ``UNSUPPORTED_DISCLOSURE`` through the service. That hold IS the documented
outcome until Meta documents such a field; only T032 evidence may change it.

Page scope: publishing happens as a Page with a Page token on the Page's own surface.
Personal profiles have no publishing API; the adapter refuses user-timeline routes.

Limit snapshot (``CapabilityLimits``): the contract has ONE limits box per record, so
it carries the documented REEL ceilings (duration 0.5s–90s, aspect 9:16 — Video API
publishing guide). The full-video route has its own (much larger) documented ceilings
that this box cannot express; flagged to the integrator as a route-scoped-limits
contract proposal. Nothing in the publishing service enforces limits today.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid5

from microdrama.contracts.enums import (
    CapabilityOperation,
    CapabilitySupport,
    DisclosureKind,
    EvidenceSource,
    Platform,
)
from microdrama.contracts.primitives import EvidenceRef
from microdrama.contracts.release import CapabilityLimits, CapabilityRecord
from microdrama.testing.fakes.common import FAKE_NAMESPACE

#: Research snapshot date for every OFFICIAL_DOCUMENTATION ref below.
SNAPSHOT_AS_OF = datetime(2026, 10, 20, tzinfo=UTC)

DOC_VIDEO_UPLOADS = "https://developers.facebook.com/docs/graph-api/video-uploads (as of 2026-10)"
DOC_PAGE_VIDEOS = (
    "https://developers.facebook.com/docs/graph-api/reference/page/videos/ (as of 2026-10)"
)
DOC_PUBLISHING_GUIDE = (
    "https://developers.facebook.com/docs/video-api/guides/facebook-publishing (as of 2026-10)"
)

PROVIDER_ROUTE = "facebook-page"
ACCOUNT_TYPE = "page"
#: Default mock Page account for OFFLINE_MOCK fixture variants.
FB_PAGE_ACCOUNT = "acct:facebook-main"

#: The frozen per-operation snapshot. Operations not listed read as UNKNOWN via
#: ``CapabilityRecord.support`` (out of this snapshot's scope), never SUPPORTED.
FB_PAGE_OPERATIONS: dict[CapabilityOperation, CapabilitySupport] = {
    # Page videos edge + resumable upload_phase protocol (start/transfer/finish).
    CapabilityOperation.UPLOAD_FULL_VIDEO: CapabilitySupport.SUPPORTED_DOCUMENTED,
    # Page Reels container flow (video_reels upload_phase + video_status).
    CapabilityOperation.UPLOAD_SHORT: CapabilitySupport.SUPPORTED_DOCUMENTED,
    # scheduled_publish_time on the Page videos edge (NOT on the Reels surface).
    CapabilityOperation.SCHEDULE: CapabilitySupport.SUPPORTED_DOCUMENTED,
    # Video status fields incl. the Reels video_status processing phase.
    CapabilityOperation.STATUS: CapabilitySupport.SUPPORTED_DOCUMENTED,
    # GET /{video-id} permalink/fields prove existence and visibility.
    CapabilityOperation.READBACK: CapabilitySupport.SUPPORTED_DOCUMENTED,
    # POST /{video-id} title/description edits.
    CapabilityOperation.METADATA_UPDATE: CapabilitySupport.SUPPORTED_DOCUMENTED,
    # No documented settable/readable organic AI-label field (snapshot 2026-10).
    CapabilityOperation.AI_DISCLOSURE: CapabilitySupport.UNKNOWN,
    # Messenger send API is a separate provider route (community lane), not this
    # publishing route; the Page publishing surface itself carries no DM operation.
    CapabilityOperation.DM_SEND: CapabilitySupport.UNSUPPORTED,
}

#: Documented Reel ceilings (Video API publishing guide, as of 2026-10). Single-box
#: caveat: see the module docstring — full-video ceilings are NOT expressible here.
FB_REEL_LIMITS = CapabilityLimits(
    min_duration_ms=500,
    max_duration_ms=90_000,
    aspect_ratios=["9:16"],
)

_SUPPORTED = (CapabilitySupport.SUPPORTED_DOCUMENTED, CapabilitySupport.SUPPORTED_TESTED)


def supported_disclosures_of(
    operations: dict[CapabilityOperation, CapabilitySupport],
) -> list[DisclosureKind]:
    """Disclosure truth derived from the AI_DISCLOSURE operation.

    A disclosure kind is supported exactly when the surface can SET it and READ it
    BACK. With the snapshot's ``AI_DISCLOSURE == UNKNOWN`` this is always empty —
    the honest outcome — and every MD-015 slot HELDs with UNSUPPORTED_DISCLOSURE.
    """
    if operations.get(CapabilityOperation.AI_DISCLOSURE) in _SUPPORTED:
        return [DisclosureKind.AI_GENERATED_CONTENT]
    return []


def documentation_evidence() -> list[EvidenceRef]:
    """The OFFICIAL_DOCUMENTATION refs backing the snapshot (never TESTED evidence)."""
    return [
        EvidenceRef(source=EvidenceSource.OFFICIAL_DOCUMENTATION, ref=DOC_VIDEO_UPLOADS),
        EvidenceRef(source=EvidenceSource.OFFICIAL_DOCUMENTATION, ref=DOC_PAGE_VIDEOS),
        EvidenceRef(source=EvidenceSource.OFFICIAL_DOCUMENTATION, ref=DOC_PUBLISHING_GUIDE),
    ]  # fmt: skip


def facebook_page_capability_record(
    account_ref: str,
    *,
    operations: dict[CapabilityOperation, CapabilitySupport] | None = None,
    version: int = 1,
    fixture: bool = False,
    verified_at: datetime | None = None,
) -> CapabilityRecord:
    """Build the capability record for a Facebook Page account on this route.

    - Default (``fixture=False``): the frozen documentation snapshot, ``enabled=False``
      — live publishing stays disabled until T032 supplies CONTROLLED_ACCOUNT_TEST
      evidence, and no operation ever claims SUPPORTED_TESTED here.
    - Fixture (``fixture=True``, OFFLINE_MOCK only): same platform truth (operations
      and disclosure derivation are shared), ``enabled=True`` with FAKE_FIXTURE
      evidence so the service runs end to end offline. The evidence label changes;
      the platform rules do not.
    """
    ops = dict(operations if operations is not None else FB_PAGE_OPERATIONS)
    if any(support is CapabilitySupport.SUPPORTED_TESTED for support in ops.values()):
        raise ValueError(
            "SUPPORTED_TESTED is reserved for T032 controlled account tests; "
            "the Facebook snapshot may claim at most SUPPORTED_DOCUMENTED"
        )
    return CapabilityRecord(
        capability_id=uuid5(FAKE_NAMESPACE, f"capability:{Platform.FACEBOOK.value}:{account_ref}"),
        version=version,
        platform=Platform.FACEBOOK,
        provider_route=PROVIDER_ROUTE,
        account_ref=account_ref,
        account_type=ACCOUNT_TYPE,
        operations=ops,
        limits=FB_REEL_LIMITS,
        supported_disclosures=supported_disclosures_of(ops),
        evidence=(
            [
                EvidenceRef(
                    source=EvidenceSource.FAKE_FIXTURE, ref="fixture:facebook-page-capability"
                )
            ]
            if fixture
            else documentation_evidence()
        ),  # fmt: skip
        verified_at=verified_at if verified_at is not None else SNAPSHOT_AS_OF,
        enabled=fixture,
    )


__all__ = [
    "ACCOUNT_TYPE",
    "DOC_PAGE_VIDEOS",
    "DOC_PUBLISHING_GUIDE",
    "DOC_VIDEO_UPLOADS",
    "FB_PAGE_ACCOUNT",
    "FB_PAGE_OPERATIONS",
    "FB_REEL_LIMITS",
    "PROVIDER_ROUTE",
    "SNAPSHOT_AS_OF",
    "facebook_page_capability_record",
    "supported_disclosures_of",
]
