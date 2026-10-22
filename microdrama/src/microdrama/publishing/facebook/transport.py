"""Transport surface for the Facebook Pages publishing API (T024).

``FacebookTransport`` abstracts the documented Graph API Page surface the adapter
drives (official docs, snapshot 2026-10 — see ``capabilities.py`` for the refs):

- Page-scoped resumable video upload: ``POST /{page-id}/videos`` with the
  ``upload_phase`` protocol (start / transfer / finish), ``title``/``description``
  and ``scheduled_publish_time`` (videos edge; scheduled publish is documented on
  the videos edge ONLY).
- Reels container flow: ``POST /{page-id}/video_reels`` with ``upload_phase``
  (start / transfer / publish) and the container's ``video_status`` phase.
- Video fields (``GET /{video-id}``) for readback and ``POST /{video-id}``
  title/description edits.

The full-video route and the Reel route are EXPLICIT and separate: no method of one
route is reachable through the other, and nothing here infers long-video API support
from the Reels surface or the reverse.

Implementations:

- ``FixtureFacebookTransport`` — the ONE offline implementation: deterministic,
  scenario-queue driven (mirrors the T007 ``FakeBase``/``ScenarioQueue`` machinery),
  FAKE_SYNTHETIC provenance, URLs only under ``https://*.invalid``, external ids from
  ``stable_digest`` of the client token. It models the documented lifecycle: upload
  -> processing -> published, with scheduled full-video posts staying in processing
  until their documented publish window opens.
- ``RefusingFacebookTransport`` — the live placeholder: every call refuses with
  ``PolicyDenied("live publishing disabled until T032")``. There is no live HTTP
  transport in this packet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import ClassVar, NoReturn, Protocol, runtime_checkable

from microdrama.contracts.enums import Provenance
from microdrama.contracts.errors import NeedsReconciliation, NotFound, PolicyDenied, RateLimited
from microdrama.contracts.primitives import ContractModel, Count, Identifier, PositiveInt
from microdrama.testing.fakes.common import (
    FakeBase,
    FakeClock,
    SequentialIds,
    fake_https,
    stable_digest,
)

#: Documented fixture chunk size for the resumable transfer phase (5 MiB).
CHUNK_SIZE_BYTES = 5 * 1024 * 1024
RETRY_AFTER_MS = 60_000


class FacebookScenario(StrEnum):
    """Scripted platform outcomes consumed by the START call of each submit."""

    ACCEPTED = "ACCEPTED"
    DENIED_PERMISSION = "DENIED_PERMISSION"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT_CREATED = "TIMEOUT_CREATED"
    TIMEOUT_NOT_CREATED = "TIMEOUT_NOT_CREATED"


class TransportRefused(Exception):
    """The platform permanently refused the call (mapped to a FAILED publish result)."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class UploadSession(ContractModel):
    """A started resumable upload (``upload_phase=start`` on the videos edge)."""

    session_id: Identifier
    chunk_size: PositiveInt
    end_offset: Count
    timeout_after_create: bool = False


class TransferReceipt(ContractModel):
    """One accepted chunk (``upload_phase=transfer``)."""

    session_id: Identifier
    start_offset: Count
    end_offset: Count


class ReelContainer(ContractModel):
    """A started Reels container (``POST /{page-id}/video_reels`` start phase)."""

    container_id: Identifier
    upload_url: str
    timeout_after_create: bool = False


class PlatformVideoStatus(ContractModel):
    """The documented video processing/publish phase (``video_status`` / status fields)."""

    external_id: Identifier
    route: Identifier  # full (videos edge) | reel (video_reels edge)
    phase: Identifier  # uploaded | processing | published
    scheduled_publish_at: datetime | None = None
    permalink: str | None = None
    error_code: str | None = None


class PlatformVideoFields(ContractModel):
    """The readable video fields readback is built from (``GET /{video-id}``)."""

    external_id: Identifier
    route: Identifier
    permalink: str | None = None
    title: str | None = None
    description: str | None = None
    published: bool = False


@runtime_checkable
class FacebookTransport(Protocol):
    """The documented Page publishing surface, independent of any transport."""

    def find_post_by_token(self, client_token: str) -> str | None:
        """The external id of the post a client token created, if any (dedupe lookup)."""
        ...

    def start_page_video_upload(
        self, *, account_ref: str, client_token: str, size_bytes: int
    ) -> UploadSession: ...

    def transfer_chunk(
        self, session: UploadSession, *, start_offset: int, chunk: bytes
    ) -> TransferReceipt: ...

    def finish_page_video_upload(
        self,
        session: UploadSession,
        *,
        title: str,
        description: str,
        scheduled_publish_epoch: int | None,
    ) -> PlatformVideoStatus: ...

    def start_reel_container(self, *, account_ref: str, client_token: str) -> ReelContainer: ...

    def upload_reel_video(self, container: ReelContainer, *, size_bytes: int) -> None: ...

    def publish_reel(
        self, container: ReelContainer, *, description: str
    ) -> PlatformVideoStatus: ...

    def video_status(self, *, external_id: str) -> PlatformVideoStatus: ...

    def peek_video_status(self, *, external_id: str) -> PlatformVideoStatus:
        """The current status WITHOUT advancing the lifecycle (reconcile/dedupe reads)."""
        ...

    def get_video(self, *, external_id: str) -> PlatformVideoFields: ...

    def update_video(self, *, external_id: str, title: str, description: str) -> None: ...


# --- Fixture (offline) ---------------------------------------------------------------------


@dataclass
class _FixtureVideo:
    external_id: str
    route: str
    client_token: str
    phase: str
    title: str | None = None
    description: str | None = None
    scheduled_at: datetime | None = None
    permalink: str | None = None
    transferred_bytes: int = 0


@dataclass
class _FixtureSession:
    session_id: str
    client_token: str
    end_offset: int
    next_offset: int = 0
    timeout_after_create: bool = False
    received: dict[int, bytes] = field(default_factory=dict)


@dataclass
class _FixtureContainer:
    container_id: str
    client_token: str
    size_bytes: int = 0
    timeout_after_create: bool = False


def _as_utc(epoch_seconds: int) -> datetime:
    return datetime.fromtimestamp(epoch_seconds, tz=UTC)


class FixtureFacebookTransport(FakeBase):
    """Deterministic offline model of the documented Page surface.

    Scenario steps are consumed by the START call of a submit (upload session or
    Reel container); replayed submits are answered from the token index and consume
    no step. TIMEOUT_CREATED creates the post and then loses the response, exactly
    like the reference fake publisher.
    """

    default_scenario: ClassVar[FacebookScenario] = FacebookScenario.ACCEPTED

    def __init__(
        self,
        *,
        clock: FakeClock,
        ids: SequentialIds,
        scenarios: tuple[FacebookScenario, ...] = (),
        chunk_size: int = CHUNK_SIZE_BYTES,
    ) -> None:
        super().__init__(clock=clock, ids=ids, scenarios=scenarios)
        self.chunk_size = chunk_size
        self.videos: dict[str, _FixtureVideo] = {}
        self._by_token: dict[str, str] = {}
        self._sessions: dict[str, _FixtureSession] = {}
        self._containers: dict[str, _FixtureContainer] = {}

    # -- dedupe ----------------------------------------------------------------------

    def find_post_by_token(self, client_token: str) -> str | None:
        self._note("find_post_by_token", key=client_token)
        return self._by_token.get(client_token)

    # -- scenario handling --------------------------------------------------------------

    def _start_step(self, *, method: str, client_token: str) -> bool:
        """Consume one scenario step; returns True when the response times out AFTER create."""
        step = self._step(method, key=client_token)
        if step is FacebookScenario.RATE_LIMITED:
            raise RateLimited(
                "fixture facebook transport rate limit reached",
                retry_after_ms=RETRY_AFTER_MS,
                client_token=client_token,
            )
        if step is FacebookScenario.DENIED_PERMISSION:
            raise TransportRefused(
                "PERMISSION_DENIED",
                "fixture facebook transport refused the call: permission denied",
            )
        if step is FacebookScenario.TOKEN_EXPIRED:
            raise TransportRefused(
                "TOKEN_EXPIRED", "fixture facebook transport refused the call: token expired"
            )
        if step is FacebookScenario.TIMEOUT_NOT_CREATED:
            raise NeedsReconciliation(
                "fixture facebook transport timed out before creating anything",
                client_token=client_token,
            )
        return step is FacebookScenario.TIMEOUT_CREATED

    # -- full-video route (Page videos edge) ----------------------------------------------

    def start_page_video_upload(
        self, *, account_ref: str, client_token: str, size_bytes: int
    ) -> UploadSession:
        timeout_after_create = self._start_step(
            method="start_page_video_upload", client_token=client_token
        )
        session_id = f"upload-{stable_digest('page-video', client_token)}"
        self._sessions[session_id] = _FixtureSession(
            session_id=session_id,
            client_token=client_token,
            end_offset=size_bytes,
            timeout_after_create=timeout_after_create,
        )
        return UploadSession(
            session_id=session_id,
            chunk_size=self.chunk_size,
            end_offset=size_bytes,
            timeout_after_create=timeout_after_create,
        )

    def transfer_chunk(
        self, session: UploadSession, *, start_offset: int, chunk: bytes
    ) -> TransferReceipt:
        self._note("transfer_chunk", key=f"{session.session_id}:{start_offset}")
        fixture = self._sessions.get(session.session_id)
        if fixture is None:
            raise NotFound("upload session not found", session_id=session.session_id)
        if start_offset != fixture.next_offset:
            raise TransportRefused(
                "UPLOAD_OFFSET_MISMATCH", "resumable transfer offsets must be contiguous"
            )
        if len(chunk) > self.chunk_size:
            raise TransportRefused("CHUNK_TOO_LARGE", "chunk exceeds the session chunk size")
        fixture.received[start_offset] = chunk
        fixture.next_offset = start_offset + len(chunk)
        return TransferReceipt(
            session_id=session.session_id,
            start_offset=start_offset,
            end_offset=fixture.next_offset,
        )

    def finish_page_video_upload(
        self,
        session: UploadSession,
        *,
        title: str,
        description: str,
        scheduled_publish_epoch: int | None,
    ) -> PlatformVideoStatus:
        self._note("finish_page_video_upload", key=session.session_id)
        fixture = self._sessions.get(session.session_id)
        if fixture is None:
            raise NotFound("upload session not found", session_id=session.session_id)
        if fixture.next_offset != fixture.end_offset:
            raise TransportRefused(
                "UPLOAD_INCOMPLETE", "finish requires every chunk transferred first"
            )
        video = self._create_video(
            route="full",
            client_token=fixture.client_token,
            title=title,
            description=description,
            scheduled_at=_as_utc(scheduled_publish_epoch)
            if scheduled_publish_epoch is not None
            else None,
        )
        if fixture.timeout_after_create:
            raise NeedsReconciliation(
                "fixture facebook transport created the video but the response timed out",
                client_token=fixture.client_token,
            )
        return self._status_of(video)

    # -- short route (Page Reels container flow) -------------------------------------------

    def start_reel_container(self, *, account_ref: str, client_token: str) -> ReelContainer:
        timeout_after_create = self._start_step(
            method="start_reel_container", client_token=client_token
        )
        container_id = f"reelc-{stable_digest('page-reel', client_token)}"
        self._containers[container_id] = _FixtureContainer(
            container_id=container_id,
            client_token=client_token,
            timeout_after_create=timeout_after_create,
        )
        return ReelContainer(
            container_id=container_id,
            upload_url=fake_https("rupload.facebook", container_id),
            timeout_after_create=timeout_after_create,
        )

    def upload_reel_video(self, container: ReelContainer, *, size_bytes: int) -> None:
        self._note("upload_reel_video", key=container.container_id)
        fixture = self._containers.get(container.container_id)
        if fixture is None:
            raise NotFound("reel container not found", container_id=container.container_id)
        fixture.size_bytes = size_bytes

    def publish_reel(self, container: ReelContainer, *, description: str) -> PlatformVideoStatus:
        self._note("publish_reel", key=container.container_id)
        fixture = self._containers.get(container.container_id)
        if fixture is None:
            raise NotFound("reel container not found", container_id=container.container_id)
        if fixture.size_bytes <= 0:
            raise TransportRefused("REEL_VIDEO_MISSING", "the reel video was never uploaded")
        # The documented Reels surface carries a description only; there is no title.
        video = self._create_video(
            route="reel",
            client_token=fixture.client_token,
            title=None,
            description=description,
            scheduled_at=None,
        )
        if fixture.timeout_after_create:
            raise NeedsReconciliation(
                "fixture facebook transport created the reel but the response timed out",
                client_token=fixture.client_token,
            )
        return self._status_of(video)

    # -- shared surface ----------------------------------------------------------------------

    def video_status(self, *, external_id: str) -> PlatformVideoStatus:
        self._note("video_status", key=external_id)
        video = self.videos.get(external_id)
        if video is None:
            raise NotFound("video not found at the fixture transport", external_id=external_id)
        if video.phase == "uploaded":
            video.phase = "processing"
        elif video.phase == "processing":
            if video.scheduled_at is not None and self.clock.now() < video.scheduled_at:
                return self._status_of(video)  # the documented window has not opened yet
            video.phase = "published"
            video.permalink = self._permalink(video)
        return self._status_of(video)

    def peek_video_status(self, *, external_id: str) -> PlatformVideoStatus:
        """Current status without stepping the lifecycle (reconcile is a lookup)."""
        self._note("peek_video_status", key=external_id)
        video = self.videos.get(external_id)
        if video is None:
            raise NotFound("video not found at the fixture transport", external_id=external_id)
        return self._status_of(video)

    def get_video(self, *, external_id: str) -> PlatformVideoFields:
        self._note("get_video", key=external_id)
        video = self.videos.get(external_id)
        if video is None:
            raise NotFound("video not found at the fixture transport", external_id=external_id)
        return PlatformVideoFields(
            external_id=video.external_id,
            route=video.route,
            permalink=video.permalink,
            title=video.title,
            description=video.description,
            published=video.phase == "published",
        )

    def update_video(self, *, external_id: str, title: str, description: str) -> None:
        self._note("update_video", key=external_id)
        video = self.videos.get(external_id)
        if video is None:
            raise NotFound("video not found at the fixture transport", external_id=external_id)
        video.title = title
        video.description = description

    # -- internals ---------------------------------------------------------------------------

    def _create_video(
        self,
        *,
        route: str,
        client_token: str,
        title: str | None,
        description: str | None,
        scheduled_at: datetime | None,
    ) -> _FixtureVideo:
        external_id = f"fb-{route}-{stable_digest(client_token)}"
        video = _FixtureVideo(
            external_id=external_id,
            route=route,
            client_token=client_token,
            # Scheduled full-video posts sit in processing until their window opens.
            phase="processing" if scheduled_at is not None else "uploaded",
            title=title,
            description=description,
            scheduled_at=scheduled_at,
        )
        self.videos[external_id] = video
        self._by_token[client_token] = external_id
        return video

    def _permalink(self, video: _FixtureVideo) -> str:
        if video.route == "reel":
            return fake_https("facebook", f"reel/{video.external_id}")
        return fake_https("facebook", f"watch/?v={video.external_id}")

    def _status_of(self, video: _FixtureVideo) -> PlatformVideoStatus:
        return PlatformVideoStatus(
            external_id=video.external_id,
            route=video.route,
            phase=video.phase,
            scheduled_publish_at=video.scheduled_at,
            permalink=video.permalink,
            error_code=None,
        )

    @property
    def provenance(self) -> Provenance:
        return Provenance.FAKE_SYNTHETIC


# --- Live placeholder ------------------------------------------------------------------------


class RefusingFacebookTransport:
    """The live transport placeholder: every documented call refuses until T032.

    T031 (credential edge) and T032 (controlled account tests) own the real HTTP
    surface. Until then there is deliberately no live transport in this packet.
    """

    def _refuse(self, call: str) -> NoReturn:
        raise PolicyDenied(
            "live publishing disabled until T032 (controlled account tests); "
            "the Facebook adapter ships offline only",
            call=call,
        )

    def find_post_by_token(self, client_token: str) -> str | None:
        self._refuse("find_post_by_token")

    def start_page_video_upload(
        self, *, account_ref: str, client_token: str, size_bytes: int
    ) -> UploadSession:
        self._refuse("start_page_video_upload")

    def transfer_chunk(
        self, session: UploadSession, *, start_offset: int, chunk: bytes
    ) -> TransferReceipt:
        self._refuse("transfer_chunk")

    def finish_page_video_upload(
        self,
        session: UploadSession,
        *,
        title: str,
        description: str,
        scheduled_publish_epoch: int | None,
    ) -> PlatformVideoStatus:
        self._refuse("finish_page_video_upload")

    def start_reel_container(self, *, account_ref: str, client_token: str) -> ReelContainer:
        self._refuse("start_reel_container")

    def upload_reel_video(self, container: ReelContainer, *, size_bytes: int) -> None:
        self._refuse("upload_reel_video")

    def publish_reel(self, container: ReelContainer, *, description: str) -> PlatformVideoStatus:
        self._refuse("publish_reel")

    def video_status(self, *, external_id: str) -> PlatformVideoStatus:
        self._refuse("video_status")

    def peek_video_status(self, *, external_id: str) -> PlatformVideoStatus:
        self._refuse("peek_video_status")

    def get_video(self, *, external_id: str) -> PlatformVideoFields:
        self._refuse("get_video")

    def update_video(self, *, external_id: str, title: str, description: str) -> None:
        self._refuse("update_video")


__all__ = [
    "CHUNK_SIZE_BYTES",
    "FacebookScenario",
    "FacebookTransport",
    "FixtureFacebookTransport",
    "PlatformVideoFields",
    "PlatformVideoStatus",
    "ReelContainer",
    "RefusingFacebookTransport",
    "TransferReceipt",
    "TransportRefused",
    "UploadSession",
]
