"""Instagram capability truth (T023): a frozen research snapshot, documentation only.

Every per-operation claim below is sourced from OFFICIAL_DOCUMENTATION only, dated
2026-10 (``RESEARCH_AS_OF``). Nothing here is SUPPORTED_TESTED — a controlled
authorized account test is T032's job, not research. Uncertain claims are UNKNOWN,
absent-from-the-documented-surface claims are UNSUPPORTED.

**Declaration truth (the core honesty decision of this packet):** the documented
container-create parameters (``POST /{ig-user-id}/media``) and the media-node
readback fields (``GET /{ig-media-id}``) contain NO parameter or field to set a
synthetic-media/AI label at publish time and read it back. Meta's documented
labelling mechanisms (automatic detection, the in-app self-label toggle, C2PA
Content Credentials embedded in the file) are not reachable through the publishing
API: none can be SET by this adapter and none can be READ BACK. Therefore
``AI_DISCLOSURE = UNSUPPORTED`` and ``supported_disclosures`` stays empty on every
record this lane builds — which means, under MD-015 (every release slot must
declare AI_GENERATED_CONTENT), Instagram slots HELD with ``UNSUPPORTED_DISCLOSURE``
through the publishing service until a verified mechanism exists. That is the
documented outcome this lane ships, not a gap to paper over.
"""

from __future__ import annotations

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
from microdrama.testing.fakes.common import FAKE_NAMESPACE, stable_digest

RESEARCH_AS_OF = "2026-10"

PROVIDER_ROUTE = "instagram-graph-content-publishing"

# --- Official documentation references (frozen snapshot) ---------------------------------

PLATFORM_DOC = "https://developers.facebook.com/docs/instagram-platform"
CONTENT_PUBLISHING_GUIDE = (
    "https://developers.facebook.com/docs/instagram-api/guides/content-publishing"
)
CONTAINER_CREATE_REF = "https://developers.facebook.com/docs/instagram-api/reference/ig-user/media"
MEDIA_PUBLISH_REF = (
    "https://developers.facebook.com/docs/instagram-api/reference/ig-user/media_publish"
)
IG_MEDIA_NODE = "https://developers.facebook.com/docs/instagram-api/reference/ig-media"
IG_MEDIA_INSIGHTS = "https://developers.facebook.com/docs/instagram-api/reference/ig-media/insights"
IG_MEDIA_COMMENTS = "https://developers.facebook.com/docs/instagram-api/reference/ig-media/comments"
IG_COMMENT_NODE = "https://developers.facebook.com/docs/instagram-api/reference/ig-comment"
PERMISSION_DOC = (
    "https://developers.facebook.com/docs/facebook-login/permissions/reference/"
    "instagram-content-publish"
)
MESSAGING_DOC = "https://developers.facebook.com/docs/messenger-platform/instagram"
WEBHOOKS_DOC = "https://developers.facebook.com/docs/instagram-api/webhooks"
HELP_CAPTION_LIMITS = "https://help.instagram.com/1631821649443347"


def _doc(url: str, note: str = "") -> EvidenceRef:
    ref = f"{url} (as of {RESEARCH_AS_OF})"
    return EvidenceRef(source=EvidenceSource.OFFICIAL_DOCUMENTATION, ref=ref, note=note or None)


#: The frozen per-operation snapshot. Values are (support, doc refs).
#: SUPPORTED_DOCUMENTED at most — SUPPORTED_TESTED is T032, never research.
OPERATION_SNAPSHOT: dict[CapabilityOperation, tuple[CapabilitySupport, tuple[EvidenceRef, ...]]] = {
    CapabilityOperation.UPLOAD_FULL_VIDEO: (
        CapabilitySupport.SUPPORTED_DOCUMENTED,
        (
            _doc(CONTENT_PUBLISHING_GUIDE, "Publishing videos: POST /media media_type=VIDEO"),
            _doc(CONTAINER_CREATE_REF, "video_url / media_type parameters"),
        ),
    ),
    CapabilityOperation.UPLOAD_SHORT: (
        CapabilitySupport.SUPPORTED_DOCUMENTED,
        (
            _doc(CONTENT_PUBLISHING_GUIDE, "Publishing reels: POST /media media_type=REELS"),
            _doc(CONTAINER_CREATE_REF, "reels container parameters (cover_url, share_to_feed)"),
        ),
    ),
    CapabilityOperation.SCHEDULE: (
        CapabilitySupport.UNSUPPORTED,
        (
            _doc(
                CONTAINER_CREATE_REF,
                "no publish-time scheduling parameter exists on /media or /media_publish",
            ),
        ),
    ),
    CapabilityOperation.STATUS: (
        CapabilitySupport.SUPPORTED_DOCUMENTED,
        (
            _doc(
                CONTENT_PUBLISHING_GUIDE,
                "container status_code: in_progress / finished / error / expired",
            ),
        ),
    ),
    CapabilityOperation.READBACK: (
        CapabilitySupport.SUPPORTED_DOCUMENTED,
        (
            _doc(
                IG_MEDIA_NODE,
                "media node fields (caption, permalink, media_type, ...) — NOTE: no "
                "disclosure/AI-label field is readable",
            ),
        ),
    ),
    CapabilityOperation.AI_DISCLOSURE: (
        CapabilitySupport.UNSUPPORTED,
        (
            _doc(
                CONTAINER_CREATE_REF,
                "no parameter sets a synthetic-media/AI label at publish time",
            ),
            _doc(
                IG_MEDIA_NODE,
                "no field reads back whether any AI label is applied; Meta's documented "
                "labelling (automatic detection, in-app self-label, C2PA file signals) is "
                "not reachable through the publishing API",
            ),
        ),
    ),
    CapabilityOperation.SPONSOR_DISCLOSURE: (
        CapabilitySupport.UNKNOWN,
        (
            _doc(
                PLATFORM_DOC,
                "branded-content tooling outside the publishing reference; unresearched",
            ),
        ),
    ),
    CapabilityOperation.CAPTIONS_UPLOAD: (
        CapabilitySupport.UNSUPPORTED,
        (
            _doc(
                CONTAINER_CREATE_REF,
                "no caption-track upload parameter; captions ride in the single caption string",
            ),
        ),
    ),
    CapabilityOperation.LOCALIZED_METADATA: (
        CapabilitySupport.UNSUPPORTED,
        (_doc(CONTAINER_CREATE_REF, "one caption per media; no per-locale metadata fields"),),
    ),
    CapabilityOperation.METADATA_UPDATE: (
        CapabilitySupport.UNSUPPORTED,
        (
            _doc(
                IG_MEDIA_NODE,
                "caption update via POST /{ig-media-id} is documented for image media only; "
                "video captions cannot be updated through the API",
            ),
        ),
    ),
    CapabilityOperation.COVER_UPDATE: (
        CapabilitySupport.UNSUPPORTED,
        (
            _doc(
                CONTAINER_CREATE_REF,
                "cover_url (reels) / thumb_offset (feed video) are container-creation "
                "parameters only; no post-publish cover update is documented",
            ),
        ),
    ),
    CapabilityOperation.INSIGHTS: (
        CapabilitySupport.SUPPORTED_DOCUMENTED,
        (_doc(IG_MEDIA_INSIGHTS, "media insights edge"),),
    ),
    CapabilityOperation.COMMENT_READ: (
        CapabilitySupport.SUPPORTED_DOCUMENTED,
        (_doc(IG_MEDIA_COMMENTS, "GET /{ig-media-id}/comments"),),
    ),
    CapabilityOperation.COMMENT_REPLY: (
        CapabilitySupport.SUPPORTED_DOCUMENTED,
        (_doc(IG_COMMENT_NODE, "POST /{ig-comment-id}/replies"),),
    ),
    CapabilityOperation.COMMENT_MODERATE: (
        CapabilitySupport.SUPPORTED_DOCUMENTED,
        (_doc(IG_COMMENT_NODE, "DELETE /{ig-comment-id}"),),
    ),
    CapabilityOperation.DM_SEND: (
        CapabilitySupport.SUPPORTED_DOCUMENTED,
        (_doc(MESSAGING_DOC, "Instagram messaging via the Messenger Platform"),),
    ),
    CapabilityOperation.WEBHOOKS: (
        CapabilitySupport.SUPPORTED_DOCUMENTED,
        (_doc(WEBHOOKS_DOC, "Instagram webhooks (comments, mentions, ...)"),),
    ),
}

#: Route ceilings documented with the content publishing guide (frozen snapshot).
#: Feed VIDEO containers accept up to 60 minutes; REELS containers up to 15 minutes;
#: both have a 3-second minimum. Stored on the record as the full-video route ceiling
#: (the record carries one duration ceiling; the reels ceiling lives in the adapter's
#: routing rules and is asserted there).
FEED_VIDEO_MAX_DURATION_MS = 3_600_000
FEED_VIDEO_MIN_DURATION_MS = 3_000
REELS_MAX_DURATION_MS = 900_000
REELS_MIN_DURATION_MS = 3_000

#: One caption string per post, hashtags included (official Instagram help centre).
CAPTION_MAX_CHARS = 2_200

#: Documented publishing limit: 50 posts within a rolling 24-hour period per account.
MAX_DAILY_POSTS = 50

#: Declaration truth: no documented API disclosure surface on this platform.
SUPPORTED_DISCLOSURES: tuple[DisclosureKind, ...] = ()


def _operations() -> dict[CapabilityOperation, CapabilitySupport]:
    return {op: support for op, (support, _refs) in OPERATION_SNAPSHOT.items()}


def _all_doc_evidence() -> list[EvidenceRef]:
    seen: dict[str, EvidenceRef] = {}
    for _support, refs in OPERATION_SNAPSHOT.values():
        for ref in refs:
            seen.setdefault(ref.ref, ref)
    return list(seen.values())


def capability_id_for(account_ref: str):
    """Deterministic capability id; mirrors the T007 fake capability id scheme."""
    return uuid5(FAKE_NAMESPACE, f"capability:{Platform.INSTAGRAM.value}:{account_ref}")


def documented_limits() -> CapabilityLimits:
    return CapabilityLimits(
        max_duration_ms=FEED_VIDEO_MAX_DURATION_MS,
        min_duration_ms=FEED_VIDEO_MIN_DURATION_MS,
        daily_post_quota=MAX_DAILY_POSTS,
    )


def documented_capability_record(
    *, account_ref: str, account_type: str, version: int = 1
) -> CapabilityRecord:
    """The documentation-only record: research claims, never enabled.

    Live publishing stays disabled until T032 records controlled-account evidence,
    so ``enabled=False`` and no ``verified_at``. ``account_type`` truth (the
    professional-account requirement) still matters: only Business/Creator accounts
    can use the publishing API at all.
    """
    return CapabilityRecord(
        capability_id=capability_id_for(account_ref),
        version=version,
        platform=Platform.INSTAGRAM,
        provider_route=PROVIDER_ROUTE,
        account_ref=account_ref,
        account_type=account_type,
        operations=_operations(),
        limits=documented_limits(),
        supported_disclosures=list(SUPPORTED_DISCLOSURES),
        evidence=_all_doc_evidence(),
        verified_at=None,
        enabled=False,
    )


def fixture_capability_record(
    *,
    account_ref: str,
    account_type: str,
    professional: bool,
    version: int,
    verified_at,
) -> CapabilityRecord:
    """The OFFLINE_MOCK variant: enabled so the service runs e2e offline.

    Every operation claim is still the frozen documentation snapshot (fixture
    evidence never upgrades a claim to SUPPORTED_TESTED); ``enabled`` reflects the
    account truth — a personal account's route cannot publish, so its fixture
    record is disabled and the service HELDs with CAPABILITY_UNAVAILABLE.
    """
    evidence = [
        EvidenceRef(
            source=EvidenceSource.FAKE_FIXTURE,
            ref=f"fixture:instagram-adapter:{stable_digest(account_ref)}",
            note="offline fixture; operation claims remain documentation-only",
        ),
        *_all_doc_evidence(),
    ]
    return CapabilityRecord(
        capability_id=capability_id_for(account_ref),
        version=version,
        platform=Platform.INSTAGRAM,
        provider_route=PROVIDER_ROUTE,
        account_ref=account_ref,
        account_type=account_type,
        operations=_operations(),
        limits=documented_limits(),
        supported_disclosures=list(SUPPORTED_DISCLOSURES),
        evidence=evidence,
        verified_at=verified_at,
        enabled=professional,
    )


__all__ = [
    "CAPTION_MAX_CHARS",
    "FEED_VIDEO_MAX_DURATION_MS",
    "FEED_VIDEO_MIN_DURATION_MS",
    "MAX_DAILY_POSTS",
    "OPERATION_SNAPSHOT",
    "PROVIDER_ROUTE",
    "RESEARCH_AS_OF",
    "REELS_MAX_DURATION_MS",
    "REELS_MIN_DURATION_MS",
    "SUPPORTED_DISCLOSURES",
    "capability_id_for",
    "documented_capability_record",
    "documented_limits",
    "fixture_capability_record",
]
