"""Frozen capability research snapshot for the YouTube route (T021).

Every support value and numeric limit below is sourced from OFFICIAL_DOCUMENTATION
only, with the snapshot date (``as of 2026-10``) carried inside every
``EvidenceRef.ref``. No controlled account test has run — that is T032 — so no
operation is ever SUPPORTED_TESTED and the research record ships ``enabled=False``:
a documented claim is not a live account fact, and neither is a marketing or
historical one. The OFFLINE_MOCK factory builds a FAKE_FIXTURE variant (enabled)
from the same snapshot so the publishing service runs end-to-end offline.

Platform facts encoded here (the exact claim sits in each evidence note):

- Uploads are ``videos.insert`` under the documented resumable-upload session
  protocol; long-form video and Shorts share that endpoint, the Shorts route
  being a duration/aspect contract rather than a separate API.
- Schedule-ahead is the documented ``status.publishAt`` + private-privacy model
  (the video exists privately and turns public at the instant); there is no
  separate queue surface to invent.
- The altered/synthetic-media disclosure is ONE documented field; it is mapped
  to AI_GENERATED_CONTENT, and SYNTHETIC_VOICE rides the same field because no
  separate synthetic-voice declaration surface is documented.
- Captions (``captions.insert``) and localizations (the ``localizations`` part of
  the video resource) are documented, but a PublicationCommand carries no caption
  payload, so submit never fabricates them — they are T029/T025 integration
  points surfaced as CAPTIONS_UPLOAD / LOCALIZED_METADATA support.
- The documented next-video (episode-linking) surface is playlists /
  playlistItems; end screens and pinned comments are Studio-only, so linking
  beyond playlists stays UNKNOWN here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid5

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

PROVIDER_ROUTE = "youtube-data-api-v3"
#: Snapshot date of every documentation claim below (mirrored in each ref string).
RESEARCH_AS_OF = datetime(2026, 10, 20, tzinfo=UTC)
_AS_OF = "as of 2026-10"

# --- documented surface --------------------------------------------------------------------


def _doc_ref(path: str, note: str) -> EvidenceRef:
    return EvidenceRef(
        source=EvidenceSource.OFFICIAL_DOCUMENTATION, ref=f"https://{path} ({_AS_OF})", note=note
    )


RESEARCH_EVIDENCE: tuple[EvidenceRef, ...] = (
    _doc_ref(
        "developers.google.com/youtube/v3/docs/videos/insert",
        "videos.insert creates the upload; long-form video and Shorts share this endpoint",
    ),
    _doc_ref(
        "developers.google.com/youtube/v3/guides/using_resumable_upload_protocol",
        "documented resumable session: metadata on the initiating request, then media PUTs "
        "to the session URI; the video id arrives with the completed-upload response",
    ),
    _doc_ref(
        "developers.google.com/youtube/v3/docs/videos/list",
        "videos.list part=status/snippet/localizations backs STATUS and READBACK",
    ),
    _doc_ref(
        "developers.google.com/youtube/v3/docs/videos/update",
        "videos.update backs METADATA_UPDATE (title/description/tags; documented title "
        "limit is 100 characters) and LOCALIZED_METADATA via the localizations part",
    ),
    _doc_ref(
        "developers.google.com/youtube/v3/docs/videos",
        "video resource: status.publishAt + private privacy is the documented "
        "schedule-ahead model; the altered/synthetic-media field on status is the "
        "disclosure surface for this route",
    ),
    _doc_ref(
        "developers.google.com/youtube/v3/docs/captions/insert",
        "documented captions surface; a PublicationCommand carries no caption payload, "
        "so submit never fabricates an upload (T029/T025 integration point)",
    ),
    _doc_ref(
        "developers.google.com/youtube/v3/docs/captions/list",
        "documented captions.list proves subtitles_present at readback",
    ),
    _doc_ref(
        "developers.google.com/youtube/v3/docs/thumbnails/set",
        "documented custom thumbnail set (COVER_UPDATE)",
    ),
    _doc_ref(
        "developers.google.com/youtube/v3/determine_quota_cost",
        "default project quota 10,000 units/day; documented per-call costs: "
        "videos.insert 1600, videos.update 50, videos.list 1, captions.insert 400 units",
    ),
    _doc_ref(
        "support.google.com/youtube/answer/71673",
        "15-minute default upload-length cap for channels without verified status "
        "(verified channels may upload longer); 256 GB maximum file size",
    ),
    _doc_ref(
        "support.google.com/youtube/answer/10059070",
        "Shorts route contract: up to 3 minutes, square or vertical aspect",
    ),
    _doc_ref(
        "support.google.com/youtube/answer/14334423",
        "one altered/synthetic-content disclosure covering realistic synthetic media; "
        "mapped to AI_GENERATED_CONTENT, with SYNTHETIC_VOICE riding the same field "
        "(no separate synthetic-voice declaration exists)",
    ),
    _doc_ref(
        "developers.google.com/youtube/v3/docs/playlistItems",
        "playlists/playlistItems are the documented episode-linking surface (the "
        "supported next-video path); end screens and pinned comments are Studio-only",
    ),
)

# --- support snapshot ----------------------------------------------------------------------

#: Documentation-sourced support only. SUPPORTED_TESTED is absent by construction:
#: no controlled account test has run (T032). Operations NOT listed here (INSIGHTS,
#: COMMENT_*, WEBHOOKS, SPONSOR_DISCLOSURE) stay UNKNOWN via ``CapabilityRecord.support``.
RESEARCH_OPERATIONS: dict[CapabilityOperation, CapabilitySupport] = {
    CapabilityOperation.UPLOAD_FULL_VIDEO: CapabilitySupport.SUPPORTED_DOCUMENTED,
    CapabilityOperation.UPLOAD_SHORT: CapabilitySupport.SUPPORTED_DOCUMENTED,
    CapabilityOperation.SCHEDULE: CapabilitySupport.SUPPORTED_DOCUMENTED,
    CapabilityOperation.STATUS: CapabilitySupport.SUPPORTED_DOCUMENTED,
    CapabilityOperation.READBACK: CapabilitySupport.SUPPORTED_DOCUMENTED,
    CapabilityOperation.AI_DISCLOSURE: CapabilitySupport.SUPPORTED_DOCUMENTED,
    CapabilityOperation.CAPTIONS_UPLOAD: CapabilitySupport.SUPPORTED_DOCUMENTED,
    CapabilityOperation.LOCALIZED_METADATA: CapabilitySupport.SUPPORTED_DOCUMENTED,
    CapabilityOperation.METADATA_UPDATE: CapabilitySupport.SUPPORTED_DOCUMENTED,
    CapabilityOperation.COVER_UPDATE: CapabilitySupport.SUPPORTED_DOCUMENTED,
    CapabilityOperation.DM_SEND: CapabilitySupport.UNSUPPORTED,  # no DM surface exists
}

#: Disclosure kinds the documented altered-content field can carry. Every other
#: kind (SPONSORED, MEMBER_OFFER) has no documented field on this route and is
#: therefore unsupported here regardless of the enum allowing it.
DISCLOSURE_FIELD_MAP: dict[DisclosureKind, str] = {
    DisclosureKind.AI_GENERATED_CONTENT: "status.altered-content disclosure",
    DisclosureKind.SYNTHETIC_VOICE: "status.altered-content disclosure (shared field)",
}
SUPPORTED_DISCLOSURES: tuple[DisclosureKind, ...] = (
    DisclosureKind.AI_GENERATED_CONTENT,
    DisclosureKind.SYNTHETIC_VOICE,
)

#: Documented limits, each sourced by an evidence note above. The upload-length and
#: file-size figures are the documented defaults for channels without verified status
#: — the honest snapshot for an account that has never been tested. The daily figure
#: is arithmetic on documented facts: 10,000 quota units/day at 1,600 units per
#: videos.insert call allows at most 6 upload calls per day (per-project quotas may
#: differ; that would be a T032 live fact, not this snapshot).
RESEARCH_LIMITS = CapabilityLimits(
    max_duration_ms=900_000,
    max_file_bytes=256 * 1024 * 1024 * 1024,
    daily_post_quota=6,
)

#: The documented next-video path: playlists. Anything beyond this surface stays
#: UNKNOWN and is not encoded in the adapter.
NEXT_VIDEO_SURFACE = "playlists/playlistItems"


def capability_id_for(account_ref: str) -> UUID:
    """Deterministic capability id for a YouTube account (stable across records)."""
    return uuid5(FAKE_NAMESPACE, f"capability:{Platform.YOUTUBE.value}:{account_ref}")


def _disclosures_for(
    operations: dict[CapabilityOperation, CapabilitySupport],
) -> list[DisclosureKind]:
    """Disclosure support follows AI_DISCLOSURE support on this snapshot."""
    support = operations.get(CapabilityOperation.AI_DISCLOSURE, CapabilitySupport.UNKNOWN)
    if support in (CapabilitySupport.SUPPORTED_DOCUMENTED, CapabilitySupport.SUPPORTED_TESTED):
        return list(SUPPORTED_DISCLOSURES)
    return []


def research_capability_record(account_ref: str) -> CapabilityRecord:
    """The disabled documentation snapshot for an account.

    ``enabled=False`` is the shipped default: live publishing stays off until a
    controlled account test (T032) produces evidence that can upgrade operations
    to SUPPORTED_TESTED and enable the route.
    """
    return CapabilityRecord(
        capability_id=capability_id_for(account_ref),
        version=1,
        platform=Platform.YOUTUBE,
        provider_route=PROVIDER_ROUTE,
        account_ref=account_ref,
        account_type="channel-unverified-default",
        operations=dict(RESEARCH_OPERATIONS),
        limits=RESEARCH_LIMITS.model_copy(),
        supported_disclosures=list(SUPPORTED_DISCLOSURES),
        evidence=list(RESEARCH_EVIDENCE),
        verified_at=RESEARCH_AS_OF,
        enabled=False,
    )


def fixture_capability_record(
    account_ref: str,
    *,
    verified_at: datetime,
    version: int = 1,
    enabled: bool = True,
    operations: dict[CapabilityOperation, CapabilitySupport] | None = None,
) -> CapabilityRecord:
    """The OFFLINE_MOCK variant: same frozen snapshot, FAKE_FIXTURE evidence, enabled.

    FAKE_FIXTURE evidence only (no OFFICIAL_DOCUMENTATION refs): fixture data may
    not carry real evidence sources (D3), and outside OFFLINE_MOCK a fake-only
    record is treated as unknown/disabled (V-4). Operations stay
    SUPPORTED_DOCUMENTED at most — a fixture run is not a controlled account test.
    """
    ops = dict(operations if operations is not None else RESEARCH_OPERATIONS)
    return CapabilityRecord(
        capability_id=capability_id_for(account_ref),
        version=version,
        platform=Platform.YOUTUBE,
        provider_route=PROVIDER_ROUTE,
        account_ref=account_ref,
        account_type="fixture-channel",
        operations=ops,
        limits=RESEARCH_LIMITS.model_copy(),
        supported_disclosures=_disclosures_for(ops),
        evidence=[
            EvidenceRef(
                source=EvidenceSource.FAKE_FIXTURE, ref=f"fixture:youtube-capability:{account_ref}"
            )
        ],
        verified_at=verified_at,
        enabled=enabled,
    )


__all__ = [
    "DISCLOSURE_FIELD_MAP",
    "NEXT_VIDEO_SURFACE",
    "PROVIDER_ROUTE",
    "RESEARCH_AS_OF",
    "RESEARCH_EVIDENCE",
    "RESEARCH_LIMITS",
    "RESEARCH_OPERATIONS",
    "SUPPORTED_DISCLOSURES",
    "capability_id_for",
    "fixture_capability_record",
    "research_capability_record",
]
