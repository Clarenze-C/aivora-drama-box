"""YouTube Data API v3 transport surface (T021): the documented protocol, one fixture.

``YouTubeTransport`` abstracts only the documented Data API v3 surface this adapter
needs. Under the documented resumable-upload protocol an upload IS a videos.insert:
the initiating request carries the video metadata (snippet, status — including
``publishAt`` and the altered-content disclosure — and localizations) and returns a
session URI; the media PUTs go to that URI and the completed upload returns the
video resource with its id. That is why the protocol below has session-init and
media-PUT methods rather than a separate ``videos_insert``. ``videos_update``,
``videos_list`` and the captions surface mirror the documented endpoints; captions
exist as a surface (and as captions.list proof for readback) but the adapter never
fabricates caption uploads — a PublicationCommand carries no caption payload.

There is NO live implementation. ``LiveYouTubeTransport`` is a named refusal point
that raises ``PolicyDenied("live publishing disabled until T032")`` on construction,
and the offline factory only ever builds ``FixtureYouTubeTransport``, which follows
the T007 fake conventions: a scripted scenario queue, ``FAKE_SYNTHETIC``
provenance, ``https://*.invalid`` URLs (``fake_https``) and deterministic
stable-digest external ids.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Protocol, runtime_checkable

from pydantic import Field, model_validator

from microdrama.contracts.enums import DisclosureKind, Provenance
from microdrama.contracts.errors import (
    NeedsReconciliation,
    NotFound,
    PolicyDenied,
    RateLimited,
    Unauthenticated,
)
from microdrama.contracts.primitives import (
    ContractModel,
    Identifier,
    LocaleTag,
    ShortText,
    UtcDateTime,
)
from microdrama.contracts.release import check_url_provenance
from microdrama.testing.fakes.common import (
    FakeBase,
    FakeClock,
    SequentialIds,
    fake_https,
    stable_digest,
)

LIVE_DISABLED_UNTIL = "T032"
EXTERNAL_ID_PREFIX = "yt"
RETRY_AFTER_MS = 60_000
WATCH_HOST = "youtube.fake"

# --- documented resource shapes --------------------------------------------------------------


class VideoLocalization(ContractModel):
    """The documented per-language title/description inside video.localizations."""

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)


class VideoSnippet(ContractModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    tags: list[ShortText] = Field(default_factory=list)
    default_language: LocaleTag | None = None


class VideoStatus(ContractModel):
    """The documented status fields this route uses.

    ``privacy_status`` is private/unlisted/public; ``publish_at`` is the documented
    schedule-ahead field (the video is private until the instant, then public);
    ``contain_synthetic_media`` is the documented altered-content disclosure field;
    ``upload_status`` follows the documented progression uploaded -> processing ->
    processed (or failed/rejected).
    """

    privacy_status: Identifier = "private"
    publish_at: UtcDateTime | None = None
    contain_synthetic_media: bool | None = None
    upload_status: Identifier | None = None
    failure_reason: ShortText | None = None


class VideoResource(ContractModel):
    video_id: str = Field(default="", description="assigned by the provider at upload")
    snippet: VideoSnippet
    status: VideoStatus
    localizations: dict[LocaleTag, VideoLocalization] = Field(default_factory=dict)


class UploadSessionRequest(ContractModel):
    """The initiating request of the documented resumable protocol (videos.insert)."""

    client_token: ShortText
    dedupe_key: str
    route: Identifier = Field(description="long_form | shorts, decided by the adapter")
    video: VideoResource
    disclosures: list[DisclosureKind] = Field(default_factory=list)


class UploadSession(ContractModel):
    session_url: str
    client_token: ShortText
    route: Identifier
    provenance: Provenance

    @model_validator(mode="after")
    def _url(self) -> UploadSession:
        check_url_provenance(self.session_url, self.provenance)
        return self


class UploadedVideo(ContractModel):
    """The documented completed-upload response: the video resource with its id."""

    video: VideoResource
    provenance: Provenance


class CaptionUploadRequest(ContractModel):
    """A documented captions.insert payload (T029/T025 integration; not carried by commands)."""

    video_id: ShortText
    language: LocaleTag
    name: ShortText | None = None
    body_text: str = Field(min_length=1)


class CaptionResource(ContractModel):
    caption_id: ShortText
    video_id: ShortText
    language: LocaleTag
    provenance: Provenance


class YouTubeScenario(StrEnum):
    """Scripted provider responses (the frozen T020 matrix), consumed at session init."""

    ACCEPTED = "ACCEPTED"
    DENIED_PERMISSION = "DENIED_PERMISSION"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT_CREATED = "TIMEOUT_CREATED"
    TIMEOUT_NOT_CREATED = "TIMEOUT_NOT_CREATED"


@runtime_checkable
class YouTubeTransport(Protocol):
    """The documented Data API v3 surface the YouTube adapter is allowed to use."""

    def init_resumable_session(self, request: UploadSessionRequest) -> UploadSession: ...

    def upload_media(self, session: UploadSession, media_path: Path) -> UploadedVideo: ...

    def videos_update(self, video_id: str, video: VideoResource) -> VideoResource: ...

    def videos_list(
        self, video_id: str, parts: tuple[str, ...] = ("snippet", "status")
    ) -> VideoResource | None: ...

    def captions_insert(self, request: CaptionUploadRequest) -> CaptionResource: ...

    def captions_list(self, video_id: str) -> list[CaptionResource]: ...

    def lookup_video(self, client_token: str) -> VideoResource | None:
        """Dedupe lookup by upload token (documented idempotency basis); no state change."""
        ...


class LiveYouTubeTransport:
    """Named refusal: no live HTTP transport exists until the T032 controlled tests.

    Constructing this class always raises — the offline factory is the only way to
    obtain a YouTube transport in this task, and live publishing stays disabled.
    """

    def __init__(self, *, provider_route: str = "youtube-data-api-v3") -> None:
        raise PolicyDenied(
            "live publishing disabled until T032",
            blocked_until=LIVE_DISABLED_UNTIL,
            provider_route=provider_route,
        )


# --- offline fixture --------------------------------------------------------------------------


@dataclass
class _FixtureVideo:
    resource: VideoResource
    client_token: str
    dedupe_key: str
    route: str
    disclosures: tuple[DisclosureKind, ...]
    caption_languages: list[str] = field(default_factory=list)


class FixtureYouTubeTransport(FakeBase):
    """Deterministic fixture transport: one scripted response per session init.

    Scenario steps are consumed by ``init_resumable_session`` (the videos.insert
    call); ``upload_media`` completes the documented protocol for whatever the
    scripted init accepted. For TIMEOUT_CREATED the upload completes and the
    response is lost (``NeedsReconciliation`` raised after the video exists), so a
    client-token reconcile can find it; for TIMEOUT_NOT_CREATED nothing exists.
    Upload processing advances one documented step per ``videos_list`` call
    (uploaded -> processing -> processed), and a scheduled video turns public at
    its ``publish_at`` instant according to the fake clock — the documented
    private-until-publishAt model, not an invented queue.
    """

    default_scenario: ClassVar[YouTubeScenario] = YouTubeScenario.ACCEPTED

    def __init__(
        self,
        *,
        clock: FakeClock,
        ids: SequentialIds,
        scenarios: Iterable[YouTubeScenario] = (),
    ) -> None:
        super().__init__(clock=clock, ids=ids, scenarios=scenarios)
        self._videos: dict[str, _FixtureVideo] = {}
        self._by_token: dict[str, str] = {}
        self._by_dedupe: dict[str, str] = {}
        self._sessions: dict[str, UploadSession] = {}
        self._pending: dict[str, UploadSessionRequest] = {}
        self._created_timeouts: set[str] = set()

    # --- documented upload surface -------------------------------------------------------

    def init_resumable_session(self, request: UploadSessionRequest) -> UploadSession:
        if request.client_token in self._by_token:
            # A repeated token is the documented dedupe basis: same session, nothing new.
            self._log_replay("videos.insert.init", request.client_token)
            return self._sessions[request.client_token]
        step = self._step("videos.insert.init", key=request.client_token)
        if step is YouTubeScenario.RATE_LIMITED:
            raise RateLimited(
                "fixture: upload quota exceeded for the project",
                retry_after_ms=RETRY_AFTER_MS,
                client_token=request.client_token,
            )
        if step is YouTubeScenario.TOKEN_EXPIRED:
            raise Unauthenticated("fixture: OAuth token expired", client_token=request.client_token)
        if step is YouTubeScenario.DENIED_PERMISSION:
            raise PolicyDenied(
                "fixture: upload forbidden for this channel", client_token=request.client_token
            )
        if step is YouTubeScenario.TIMEOUT_NOT_CREATED:
            raise NeedsReconciliation(
                "fixture: session init timed out; no video was created",
                client_token=request.client_token,
            )
        session = UploadSession(
            session_url=fake_https(
                "youtube-upload.fake", f"resumable/{stable_digest(request.client_token)}"
            ),
            client_token=request.client_token,
            route=request.route,
            provenance=Provenance.FAKE_SYNTHETIC,
        )
        self._sessions[request.client_token] = session
        self._pending[request.client_token] = request
        if step is YouTubeScenario.TIMEOUT_CREATED:
            self._created_timeouts.add(request.client_token)
        return session

    def upload_media(self, session: UploadSession, media_path: Path) -> UploadedVideo:
        request = self._pending[session.client_token]
        video_id = youtube_external_id(request.client_token)
        resource = request.video.model_copy(
            update={
                "video_id": video_id,
                "status": _with_upload_status(request.video.status, "uploaded"),
            }
        )
        self._videos[video_id] = _FixtureVideo(
            resource=resource,
            client_token=request.client_token,
            dedupe_key=request.dedupe_key,
            route=request.route,
            disclosures=tuple(request.disclosures),
        )
        self._by_token[request.client_token] = video_id
        self._by_dedupe[request.dedupe_key] = video_id
        self._note("videos.insert.put", key=video_id)
        if request.client_token in self._created_timeouts:
            self._created_timeouts.discard(request.client_token)
            raise NeedsReconciliation(
                "fixture: the upload completed but the response was lost",
                client_token=request.client_token,
            )
        return UploadedVideo(video=self._snapshot(video_id), provenance=Provenance.FAKE_SYNTHETIC)

    # --- documented management/readback surface -------------------------------------------

    def videos_update(self, video_id: str, video: VideoResource) -> VideoResource:
        self._note("videos.update", key=video_id)
        existing = self._videos.get(video_id)
        if existing is None:
            raise NotFound("fixture: video not found", external_id=video_id)
        existing.resource = existing.resource.model_copy(
            update={
                "snippet": video.snippet,
                "status": video.status,
                "localizations": video.localizations or existing.resource.localizations,
            }
        )
        return self._snapshot(video_id)

    def videos_list(
        self, video_id: str, parts: tuple[str, ...] = ("snippet", "status")
    ) -> VideoResource | None:
        self._note("videos.list", key=video_id)
        video = self._videos.get(video_id)
        if video is None:
            return None
        self._advance(video)
        return self._snapshot(video_id)

    def captions_insert(self, request: CaptionUploadRequest) -> CaptionResource:
        self._note("captions.insert", key=request.video_id)
        video = self._videos.get(request.video_id)
        if video is None:
            raise NotFound("fixture: video not found", external_id=request.video_id)
        language = request.language
        if language not in video.caption_languages:
            video.caption_languages.append(language)
        return CaptionResource(
            caption_id=f"{EXTERNAL_ID_PREFIX}-cap-{stable_digest(request.video_id, language)}",
            video_id=request.video_id,
            language=request.language,
            provenance=Provenance.FAKE_SYNTHETIC,
        )

    def captions_list(self, video_id: str) -> list[CaptionResource]:
        self._note("captions.list", key=video_id)
        video = self._videos.get(video_id)
        if video is None:
            raise NotFound("fixture: video not found", external_id=video_id)
        return [
            CaptionResource(
                caption_id=f"{EXTERNAL_ID_PREFIX}-cap-{stable_digest(video_id, language)}",
                video_id=video_id,
                language=language,
                provenance=Provenance.FAKE_SYNTHETIC,
            )
            for language in video.caption_languages
        ]

    def lookup_video(self, client_token: str) -> VideoResource | None:
        video_id = self._by_token.get(client_token) or self._by_dedupe.get(client_token)
        if video_id is None:
            return None
        return self._snapshot(video_id)

    # --- fixture helpers ------------------------------------------------------------------

    def route_of(self, video_id: str) -> str | None:
        """The route a video was uploaded under (fixture introspection for tests)."""
        video = self._videos.get(video_id)
        return video.route if video is not None else None

    def video_count(self) -> int:
        return len(self._videos)

    def _snapshot(self, video_id: str) -> VideoResource:
        return self._videos[video_id].resource.model_copy(deep=True)

    def _advance(self, video: _FixtureVideo) -> None:
        """One documented processing step per list call; public at publishAt."""
        status = video.resource.status
        updated = status
        if status.upload_status == "uploaded":
            updated = _with_upload_status(status, "processing")
        elif status.upload_status == "processing":
            updated = _with_upload_status(status, "processed")
        if (
            updated.upload_status == "processed"
            and updated.publish_at is not None
            and updated.privacy_status == "private"
            and self.clock.now() >= updated.publish_at
        ):
            updated = updated.model_copy(update={"privacy_status": "public"})
        if updated is not status:
            video.resource = video.resource.model_copy(update={"status": updated})


def _with_upload_status(status: VideoStatus, upload_status: str) -> VideoStatus:
    return status.model_copy(update={"upload_status": upload_status})


def youtube_external_id(client_token: str) -> str:
    """Deterministic external video id for an upload token (stable_digest)."""
    return f"{EXTERNAL_ID_PREFIX}-{stable_digest(client_token)}"


def watch_url(video_id: str) -> str:
    """The fixture watch URL (``https://*.invalid`` only)."""
    return fake_https(WATCH_HOST, f"watch?v={video_id}")


__all__ = [
    "EXTERNAL_ID_PREFIX",
    "FixtureYouTubeTransport",
    "LIVE_DISABLED_UNTIL",
    "LiveYouTubeTransport",
    "RETRY_AFTER_MS",
    "UploadSession",
    "UploadSessionRequest",
    "UploadedVideo",
    "VideoLocalization",
    "VideoResource",
    "VideoSnippet",
    "VideoStatus",
    "CaptionResource",
    "CaptionUploadRequest",
    "YouTubeScenario",
    "YouTubeTransport",
    "watch_url",
    "youtube_external_id",
]
