"""YouTube platform rules over the documented Data API v3 transport (T021).

This is the OFFLINE adapter: platform rules (routing, the documented
private-until-``publishAt`` schedule model, the altered-content disclosure
mapping, readback reporting) applied to a ``YouTubeTransport``. It contains no
local approval, budget or gate logic — every gate stays in the T020 service —
and it never reaches beyond the documented surface:

- Routing: FULL_EPISODE/PART slots take the long-form video route, PROMO_CUT/HOOK
  slots the Shorts route. Both are the same documented ``videos.insert`` surface;
  the route is decided from the slot kind plus the capability record (whose
  limits document the Shorts duration/aspect contract). The command carries no
  duration/aspect data, so the adapter never probes or guesses media shape.
- Schedule-ahead: a window in the future submits through the documented model —
  the video exists privately with ``status.publishAt`` and turns public at that
  instant. No queue is invented.
- Disclosure: AI_GENERATED_CONTENT maps to the documented altered-content field;
  SYNTHETIC_VOICE rides the same field (no separate declaration exists). Any
  other declared disclosure is refused, never silently dropped. At readback the
  single field covers both kinds, so a set field proves both visible.
- Captions/localizations are NOT uploaded by submit: a PublicationCommand
  carries no caption payload (T029/T025 integration points; the capability
  snapshot records them as documented operations).
- Status progression follows the documented uploadStatus ladder
  (uploaded -> processing -> processed); reconcile/dedupe is by ``client_token``.
"""

from __future__ import annotations

from pathlib import Path

from microdrama.contracts.enums import (
    CapabilityOperation,
    CapabilitySupport,
    Platform,
    Provenance,
    ReleaseState,
    SlotKind,
)
from microdrama.contracts.errors import (
    NotFound,
    PolicyDenied,
    RateLimited,
    Unauthenticated,
)
from microdrama.contracts.hashing import file_sha256
from microdrama.contracts.infra import Clock
from microdrama.contracts.providers import PostReadback, PublishResult, ReconcileResult
from microdrama.contracts.release import (
    CapabilityRecord,
    PostMetadata,
    PublicationCommand,
)
from microdrama.publishing.youtube.capabilities import (
    DISCLOSURE_FIELD_MAP,
    PROVIDER_ROUTE,
    RESEARCH_OPERATIONS,
    fixture_capability_record,
)
from microdrama.publishing.youtube.transport import (
    CaptionResource,
    CaptionUploadRequest,
    UploadSessionRequest,
    VideoResource,
    VideoSnippet,
    VideoStatus,
    YouTubeScenario,
    YouTubeTransport,
    watch_url,
)

FAKE = Provenance.FAKE_SYNTHETIC
SUPPORTED_OPS = (CapabilitySupport.SUPPORTED_DOCUMENTED, CapabilitySupport.SUPPORTED_TESTED)

#: Documented routing: long-form vs Shorts is decided by slot kind, nothing else.
LONG_FORM_KINDS = frozenset({SlotKind.FULL_EPISODE, SlotKind.PART})
SHORTS_KINDS = frozenset({SlotKind.PROMO_CUT, SlotKind.HOOK})
ROUTE_LONG_FORM = "long_form"
ROUTE_SHORTS = "shorts"
_ROUTE_BY_KIND: dict[SlotKind, str] = {
    SlotKind.FULL_EPISODE: ROUTE_LONG_FORM,
    SlotKind.PART: ROUTE_LONG_FORM,
    SlotKind.PROMO_CUT: ROUTE_SHORTS,
    SlotKind.HOOK: ROUTE_SHORTS,
}
_OP_BY_ROUTE: dict[str, CapabilityOperation] = {
    ROUTE_LONG_FORM: CapabilityOperation.UPLOAD_FULL_VIDEO,
    ROUTE_SHORTS: CapabilityOperation.UPLOAD_SHORT,
}


class YouTubeAdapter:
    """``PublisherAdapter`` for the YouTube route (offline fixture transport only)."""

    platform = Platform.YOUTUBE
    provider_route = PROVIDER_ROUTE

    def __init__(
        self,
        *,
        transport: YouTubeTransport,
        clock: Clock,
        provider_route: str = PROVIDER_ROUTE,
        version: int = 1,
        enabled: bool = True,
        operations: dict[CapabilityOperation, CapabilitySupport] | None = None,
    ) -> None:
        self.transport = transport
        self._clock = clock
        self.provider_route = provider_route
        # Test knobs (the T007 fake pattern): bump/disable to drive HELD paths.
        self._version = version
        self._enabled = enabled
        self._operations = dict(operations if operations is not None else RESEARCH_OPERATIONS)

    def queue_scenarios(self, *steps: YouTubeScenario) -> None:
        """Script provider responses (fixture transport only)."""
        self.transport.queue_scenarios(*steps)

    # --- capability --------------------------------------------------------------------

    def capability(self, account_ref: str) -> CapabilityRecord:
        """The fixture variant of the frozen snapshot (OFFLINE_MOCK adapter)."""
        return fixture_capability_record(
            account_ref,
            verified_at=self._clock.now(),
            version=self._version,
            enabled=self._enabled,
            operations=self._operations,
        )

    # --- submit ------------------------------------------------------------------------

    def submit(self, command: PublicationCommand, media_path: Path) -> PublishResult:
        existing = self.transport.lookup_video(command.client_token)
        if existing is not None:
            return self._result_for(existing)  # replayed token: same post, nothing created

        route = _ROUTE_BY_KIND[command.slot_kind]
        operation = _OP_BY_ROUTE[route]
        record = self.capability(command.slot.account_ref)
        if record.support(operation) not in SUPPORTED_OPS:
            return self._failed(f"{operation.value}_UNSUPPORTED")
        declared = set(command.metadata.disclosures)
        if not declared <= set(DISCLOSURE_FIELD_MAP) or not declared <= set(
            record.supported_disclosures
        ):
            return self._failed("UNSUPPORTED_DISCLOSURE")
        if not Path(media_path).is_file():
            raise NotFound(
                "media file for publishing not found", command_id=str(command.command_id)
            )
        if file_sha256(str(media_path)) != command.asset_sha256:
            return self._failed("ASSET_HASH_MISMATCH")

        ahead = command.schedule.utc_instant > self._clock.now()
        if ahead and record.support(CapabilityOperation.SCHEDULE) not in SUPPORTED_OPS:
            return self._failed("SCHEDULE_UNSUPPORTED")

        status = VideoStatus(
            privacy_status="private" if ahead else "public",
            publish_at=command.schedule.utc_instant if ahead else None,
            contain_synthetic_media=bool(declared & set(DISCLOSURE_FIELD_MAP)) or None,
        )
        snippet = VideoSnippet(
            title=command.metadata.title,
            description=command.metadata.description,
            tags=list(command.metadata.hashtags),
            default_language=command.metadata.locale,
        )
        request = UploadSessionRequest(
            client_token=command.client_token,
            dedupe_key=command.dedupe_key,
            route=route,
            video=VideoResource(snippet=snippet, status=status),
            disclosures=list(command.metadata.disclosures),
        )
        try:
            session = self.transport.init_resumable_session(request)
            uploaded = self.transport.upload_media(session, media_path)
        except RateLimited:
            raise  # the service owns retry pacing
        except Unauthenticated:
            return self._failed("TOKEN_EXPIRED")
        except PolicyDenied:
            return self._failed("PERMISSION_DENIED")
        return self._result_for(uploaded.video)

    # --- status / reconcile / metadata / readback ----------------------------------------

    def status(self, command: PublicationCommand, external_id: str) -> PublishResult:
        video = self._require(external_id)
        status = video.status
        if status.upload_status in ("failed", "rejected", "deleted"):
            return self._failed(f"UPLOAD_{status.upload_status.upper()}")
        return self._result_for(video)

    def reconcile(self, command: PublicationCommand) -> ReconcileResult:
        video = self.transport.lookup_video(command.client_token)
        if video is None:
            return ReconcileResult(found=False, result=None)
        return ReconcileResult(found=True, result=self._result_for(video))

    def update_metadata(
        self, account_ref: str, external_id: str, metadata: PostMetadata
    ) -> PublishResult:
        current = self._require(external_id)
        record = self.capability(account_ref)
        if record.support(CapabilityOperation.METADATA_UPDATE) not in SUPPORTED_OPS:
            return self._failed("METADATA_UPDATE_UNSUPPORTED")
        updated = self.transport.videos_update(
            external_id,
            current.model_copy(
                update={
                    "snippet": VideoSnippet(
                        title=metadata.title,
                        description=metadata.description,
                        tags=list(metadata.hashtags),
                        default_language=metadata.locale,
                    )
                }
            ),
        )
        result = self._result_for(updated)
        return result.model_copy(update={"unverified_fields": ["title", *result.unverified_fields]})

    def readback(self, account_ref: str, external_id: str) -> PostReadback:
        video = self._require(external_id)
        status = video.status
        processed = status.upload_status == "processed"
        visible = processed and status.privacy_status == "public"
        # The documented altered-content field is one surface covering both mapped
        # kinds; a set field proves both visible, an unset one proves neither.
        disclosures = (
            [kind.value for kind in DISCLOSURE_FIELD_MAP]
            if visible and status.contain_synthetic_media
            else []
        )
        return PostReadback(
            external_id=external_id,
            visible=True if visible else (False if processed else None),
            privacy=status.privacy_status if processed else None,
            disclosures_visible=disclosures,
            subtitles_present=True if self.transport.captions_list(external_id) else None,
            links=[watch_url(external_id)] if visible else [],
            unverified_fields=["thumbnail", "category"],
            provenance=FAKE,
        )

    def upload_captions(self, request: CaptionUploadRequest) -> CaptionResource:
        """Documented captions surface for the T029/T025 integration; NOT part of submit.

        A PublicationCommand carries no caption payload, so ``submit`` never calls
        this. It exists so the integration lanes can use the same transport and the
        readback can prove ``subtitles_present`` through the documented surface.
        """
        return self.transport.captions_insert(request)

    # --- mapping helpers ------------------------------------------------------------------

    def _require(self, external_id: str) -> VideoResource:
        video = self.transport.videos_list(external_id)
        if video is None:
            raise NotFound("youtube video not found", external_id=external_id)
        return video

    def _result_for(self, video: VideoResource) -> PublishResult:
        state = self._release_state(video)
        published = state is ReleaseState.PUBLISHED_VERIFIED
        return PublishResult(
            state=state,
            external_id=video.video_id,
            url=watch_url(video.video_id) if published else None,
            verified_fields=["visibility", "ai_disclosure"] if published else [],
            unverified_fields=["thumbnail"] if published else [],
            provenance=FAKE,
        )

    def _release_state(self, video: VideoResource) -> ReleaseState:
        status = video.status
        if status.upload_status == "processed":
            window_open = status.publish_at is None or self._clock.now() >= status.publish_at
            if status.privacy_status == "public" and window_open:
                return ReleaseState.PUBLISHED_VERIFIED
            return ReleaseState.PROCESSING  # processed but not public yet (scheduled)
        if status.upload_status == "processing":
            return ReleaseState.PROCESSING
        return ReleaseState.SUBMITTED

    def _failed(self, error_code: str) -> PublishResult:
        return PublishResult(
            state=ReleaseState.FAILED, error_code=error_code, transient=False, provenance=FAKE
        )


__all__ = [
    "LONG_FORM_KINDS",
    "ROUTE_LONG_FORM",
    "ROUTE_SHORTS",
    "SHORTS_KINDS",
    "SUPPORTED_OPS",
    "YouTubeAdapter",
]
