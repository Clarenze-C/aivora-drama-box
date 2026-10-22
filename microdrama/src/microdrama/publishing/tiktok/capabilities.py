"""Frozen capability research snapshot for TikTok publishing (T022).

Every claim in this module is sourced from OFFICIAL_DOCUMENTATION only, each evidence
ref naming its developers.tiktok.com page and the as-of month (2026-10). Support never
exceeds ``SUPPORTED_DOCUMENTED``: ``SUPPORTED_TESTED`` requires a controlled account
test and is reserved for T032. Where the documentation is silent or the surface is
absent from the documented API, the operation is ``UNSUPPORTED``; where research could
not settle the question, it is ``UNKNOWN``.

Two provider routes exist for an eligible (audited app, ``video.publish`` grant) route:

- ``tiktok-direct-post`` — the documented direct-post ``post_mode`` (fully unattended).
- ``tiktok-inbox-upload`` — the documented inbox upload: the video lands in the user's
  inbox/drafts and a human must act. An inbox upload is NEVER unattended, so its
  capability record must not advertise the unattended upload operations as supported
  for the service's slot flow.

Account truth over marketing: limits and operation support are merged with the
account's actual user-info settings when a transport can supply them (privacy/comment
options, whether the account permits direct post, the account's real max duration).
Historical durations and marketing quotas are not live account facts, so
``daily_post_quota`` stays ``None``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
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
from microdrama.publishing.tiktok.transport import TikTokAccountSettings
from microdrama.testing.fakes.common import FAKE_NAMESPACE

AS_OF = "as-of 2026-10"
DOC_CONTENT_POSTING = f"https://developers.tiktok.com/doc/content-posting-api-get-started ({AS_OF})"
DOC_DIRECT_POST = f"https://developers.tiktok.com/doc/content-posting-api-direct-post ({AS_OF})"
DOC_STATUS_FETCH = f"https://developers.tiktok.com/doc/content-posting-api-video-status ({AS_OF})"
DOC_USER_INFO = f"https://developers.tiktok.com/doc/content-posting-api-get-user-info ({AS_OF})"
DOC_INBOX_UPLOAD = f"https://developers.tiktok.com/doc/content-posting-api-inbox-upload ({AS_OF})"
DOC_API_SURFACE = f"https://developers.tiktok.com/doc/overview ({AS_OF})"

#: Documented media bounds of the direct-post route (3 s – 10 min).
DOCUMENTED_MIN_DURATION_MS = 3_000
DOCUMENTED_MAX_DURATION_MS = 600_000

# --- provider routes ------------------------------------------------------------------------


class TikTokRoute(StrEnum):
    """The two documented Content Posting API post modes this packet models."""

    DIRECT_POST = "direct_post"
    INBOX_UPLOAD = "inbox_upload"


ROUTE_IDENTIFIERS: dict[TikTokRoute, str] = {
    TikTokRoute.DIRECT_POST: "tiktok-direct-post",
    TikTokRoute.INBOX_UPLOAD: "tiktok-inbox-upload",
}

# --- documented operation tables (frozen research snapshot) ----------------------------------

DIRECT_POST_DOCUMENTED_OPERATIONS: dict[CapabilityOperation, CapabilitySupport] = {
    CapabilityOperation.UPLOAD_FULL_VIDEO: CapabilitySupport.SUPPORTED_DOCUMENTED,
    CapabilityOperation.UPLOAD_SHORT: CapabilitySupport.SUPPORTED_DOCUMENTED,
    # No schedule field exists on the documented direct-post init; a future window
    # cannot be handed to TikTok, so the service must wait for the window to open.
    CapabilityOperation.SCHEDULE: CapabilitySupport.UNSUPPORTED,
    CapabilityOperation.STATUS: CapabilitySupport.SUPPORTED_DOCUMENTED,
    # Status fetch proves publish state and share URL; whether disclosure visibility
    # is readable through the API is NOT documented, so readback stays UNKNOWN.
    CapabilityOperation.READBACK: CapabilitySupport.UNKNOWN,
    CapabilityOperation.AI_DISCLOSURE: CapabilitySupport.SUPPORTED_DOCUMENTED,
    # The branded-content field is documented (SPONSORED is out of scope by MD-018).
    CapabilityOperation.SPONSOR_DISCLOSURE: CapabilitySupport.SUPPORTED_DOCUMENTED,
    CapabilityOperation.CAPTIONS_UPLOAD: CapabilitySupport.UNSUPPORTED,
    CapabilityOperation.LOCALIZED_METADATA: CapabilitySupport.UNSUPPORTED,
    CapabilityOperation.METADATA_UPDATE: CapabilitySupport.UNSUPPORTED,
    CapabilityOperation.COVER_UPDATE: CapabilitySupport.UNSUPPORTED,
    CapabilityOperation.DM_SEND: CapabilitySupport.UNSUPPORTED,
    CapabilityOperation.WEBHOOKS: CapabilitySupport.UNSUPPORTED,
    CapabilityOperation.INSIGHTS: CapabilitySupport.UNKNOWN,
    CapabilityOperation.COMMENT_READ: CapabilitySupport.UNKNOWN,
    CapabilityOperation.COMMENT_REPLY: CapabilitySupport.UNKNOWN,
    CapabilityOperation.COMMENT_MODERATE: CapabilitySupport.UNKNOWN,
}

INBOX_DOCUMENTED_OPERATIONS: dict[CapabilityOperation, CapabilitySupport] = {
    # Inbox uploads land in the user's inbox/drafts: a human must complete the post.
    # Never advertised as unattended upload support for the slot flow.
    CapabilityOperation.UPLOAD_FULL_VIDEO: CapabilitySupport.UNSUPPORTED,
    CapabilityOperation.UPLOAD_SHORT: CapabilitySupport.UNSUPPORTED,
    CapabilityOperation.SCHEDULE: CapabilitySupport.UNSUPPORTED,
    CapabilityOperation.STATUS: CapabilitySupport.SUPPORTED_DOCUMENTED,
    CapabilityOperation.READBACK: CapabilitySupport.UNKNOWN,
    CapabilityOperation.AI_DISCLOSURE: CapabilitySupport.UNKNOWN,
    CapabilityOperation.SPONSOR_DISCLOSURE: CapabilitySupport.UNKNOWN,
    CapabilityOperation.CAPTIONS_UPLOAD: CapabilitySupport.UNSUPPORTED,
    CapabilityOperation.LOCALIZED_METADATA: CapabilitySupport.UNSUPPORTED,
    CapabilityOperation.METADATA_UPDATE: CapabilitySupport.UNSUPPORTED,
    CapabilityOperation.COVER_UPDATE: CapabilitySupport.UNSUPPORTED,
    CapabilityOperation.DM_SEND: CapabilitySupport.UNSUPPORTED,
    CapabilityOperation.WEBHOOKS: CapabilitySupport.UNSUPPORTED,
    CapabilityOperation.INSIGHTS: CapabilitySupport.UNKNOWN,
    CapabilityOperation.COMMENT_READ: CapabilitySupport.UNKNOWN,
    CapabilityOperation.COMMENT_REPLY: CapabilitySupport.UNKNOWN,
    CapabilityOperation.COMMENT_MODERATE: CapabilitySupport.UNKNOWN,
}

_DOCUMENTED_OPERATIONS: dict[TikTokRoute, dict[CapabilityOperation, CapabilitySupport]] = {
    TikTokRoute.DIRECT_POST: DIRECT_POST_DOCUMENTED_OPERATIONS,
    TikTokRoute.INBOX_UPLOAD: INBOX_DOCUMENTED_OPERATIONS,
}

_ROUTE_EVIDENCE: dict[TikTokRoute, tuple[str, ...]] = {
    TikTokRoute.DIRECT_POST: (DOC_DIRECT_POST, DOC_STATUS_FETCH, DOC_USER_INFO),
    TikTokRoute.INBOX_UPLOAD: (DOC_INBOX_UPLOAD, DOC_STATUS_FETCH),
}

_SUPPORTED = (CapabilitySupport.SUPPORTED_DOCUMENTED, CapabilitySupport.SUPPORTED_TESTED)


def capability_id_for(account_ref: str, provider_route: str):
    """Deterministic capability id per (platform, account, provider route)."""
    return uuid5(FAKE_NAMESPACE, f"capability:TIKTOK:{account_ref}:{provider_route}")


def build_capability_record(
    *,
    route: TikTokRoute,
    account_ref: str,
    account_settings: TikTokAccountSettings | None = None,
    operations_override: Mapping[CapabilityOperation, CapabilitySupport] | None = None,
    version: int = 1,
    enabled: bool,
    fixture: bool,
    now: datetime | None = None,
) -> CapabilityRecord:
    """Build the capability record for one route/account.

    ``fixture=True`` produces the OFFLINE_MOCK variant: enabled, FAKE_FIXTURE evidence
    next to the documented refs, ``verified_at`` set. The default (documented) variant
    is disabled — live publishing stays off until T032 — and carries documentation
    evidence only, with account truth unknown (no transport account info yet).
    """
    provider_route = ROUTE_IDENTIFIERS[route]
    operations = dict(_DOCUMENTED_OPERATIONS[route])
    if operations_override:
        operations.update(dict(operations_override))

    # Account truth over marketing: an account that does not permit direct post does
    # not support the unattended upload operations, whatever the docs promise in
    # general. Inbox-route uploads are already UNSUPPORTED by the frozen table.
    if (
        route is TikTokRoute.DIRECT_POST
        and account_settings is not None
        and not account_settings.direct_post_permitted
    ):
        operations[CapabilityOperation.UPLOAD_FULL_VIDEO] = CapabilitySupport.UNSUPPORTED
        operations[CapabilityOperation.UPLOAD_SHORT] = CapabilitySupport.UNSUPPORTED

    supported_disclosures: list[DisclosureKind] = []
    if (
        operations[CapabilityOperation.AI_DISCLOSURE] in _SUPPORTED
        and route is TikTokRoute.DIRECT_POST
    ):
        supported_disclosures = [DisclosureKind.AI_GENERATED_CONTENT]

    limits = CapabilityLimits()
    if route is TikTokRoute.DIRECT_POST:
        max_ms = DOCUMENTED_MAX_DURATION_MS
        if account_settings is not None:
            max_ms = account_settings.max_video_duration_sec * 1_000
        limits = CapabilityLimits(
            max_duration_ms=max_ms,
            min_duration_ms=DOCUMENTED_MIN_DURATION_MS,
        )

    evidence = [
        EvidenceRef(source=EvidenceSource.OFFICIAL_DOCUMENTATION, ref=ref)
        for ref in _ROUTE_EVIDENCE[route]
    ]
    verified_at: datetime | None = None
    account_type = "unverified-account"
    if fixture:
        evidence.append(
            EvidenceRef(
                source=EvidenceSource.FAKE_FIXTURE,
                ref=f"fixture:tiktok-{route.value}-offline-profile",
            )
        )
        verified_at = now
        account_type = "fixture-creator-account"

    return CapabilityRecord(
        capability_id=capability_id_for(account_ref, provider_route),
        version=version,
        platform=Platform.TIKTOK,
        provider_route=provider_route,
        account_ref=account_ref,
        account_type=account_type,
        operations=operations,
        limits=limits,
        supported_disclosures=supported_disclosures,
        evidence=evidence,
        verified_at=verified_at,
        enabled=enabled,
    )


__all__ = [
    "AS_OF",
    "DIRECT_POST_DOCUMENTED_OPERATIONS",
    "DOC_API_SURFACE",
    "DOC_CONTENT_POSTING",
    "DOC_DIRECT_POST",
    "DOC_INBOX_UPLOAD",
    "DOC_STATUS_FETCH",
    "DOC_USER_INFO",
    "DOCUMENTED_MAX_DURATION_MS",
    "DOCUMENTED_MIN_DURATION_MS",
    "INBOX_DOCUMENTED_OPERATIONS",
    "ROUTE_IDENTIFIERS",
    "TikTokRoute",
    "build_capability_record",
    "capability_id_for",
]
