"""Transport abstraction over the documented TikTok Content Posting API surface (T022).

The protocol mirrors only what the official documentation (as-of 2026-10) describes for
an ELIGIBLE route — an audited app/provider holding the ``video.publish`` grant:

- ``user_settings``: the documented user-info fields that carry account truth for
  publishing (privacy/comment options, whether the account permits direct post, and the
  account's actual max video duration). Marketing numbers are never a substitute.
- ``direct_post_init`` / ``upload_chunk``: the documented direct-post flow (init returns
  a ``publish_id`` plus chunk upload URLs; bytes are PUT per chunk; processing starts
  when the full size has arrived — there is no separate complete call).
- ``fetch_status``: the documented status fetch by ``publish_id``.
- ``find_publish_id``: reconcile-by-client-token lookup. The documented API reconciles
  by ``publish_id``; the token map is the offline fixture's stand-in for the durable
  client-token → publish-id association a live adapter persists at init.

Two implementations ship in this packet:

- ``FixtureTikTokTransport`` — the ONE offline implementation: deterministic,
  scenario-queue driven (``FakeBase``/``ScenarioQueue`` mirror), FAKE_SYNTHETIC
  everywhere, ``*.invalid`` URLs only, external ids via ``stable_digest``.
- ``LiveTikTokTransport`` — a refusing stub. No live HTTP transport exists in this
  build: every call raises ``PolicyDenied`` until T032 (controlled account tests).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, Protocol, runtime_checkable

from microdrama.contracts.errors import NotFound, PolicyDenied
from microdrama.testing.fakes.common import (
    FakeBase,
    FakeClock,
    ScenarioQueue,
    SequentialIds,
    fake_https,
    stable_digest,
)

#: Retry hint a rate-limited response carries (documented quota/rate semantics).
RETRY_AFTER_MS = 60_000
#: The documented chunk-size window is 4–64 MiB; the fixture streams the minimum.
FIXTURE_CHUNK_SIZE_BYTES = 4 * 1024 * 1024


class TikTokScenario(StrEnum):
    """The frozen submit-scenario matrix every publisher adapter must handle."""

    ACCEPTED = "ACCEPTED"
    DENIED_PERMISSION = "DENIED_PERMISSION"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT_CREATED = "TIMEOUT_CREATED"
    TIMEOUT_NOT_CREATED = "TIMEOUT_NOT_CREATED"


class TikTokTransportError(Exception):
    """A documented-shaped API failure surfaced by a transport."""

    def __init__(self, *, api_error_code: str, message: str) -> None:
        super().__init__(message)
        self.api_error_code = api_error_code
        self.message = message


class TikTokTimeoutError(TikTokTransportError):
    """The request outcome is unknown (timeout / 5xx): reconcile, never blindly resubmit."""


@dataclass(frozen=True)
class TikTokAccountSettings:
    """Account truth from the documented user-info fields (never marketing claims)."""

    privacy_level_options: tuple[str, ...]
    comment_options: tuple[str, ...]
    direct_post_permitted: bool
    max_video_duration_sec: int


DEFAULT_ACCOUNT_SETTINGS = TikTokAccountSettings(
    privacy_level_options=("PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "SELF_ONLY"),
    comment_options=("OPEN_TO_COMMENT", "CLOSE_TO_COMMENT"),
    direct_post_permitted=True,
    max_video_duration_sec=600,
)


@dataclass(frozen=True)
class DirectPostInitRequest:
    """The payload the adapter sends to the documented direct-post init endpoint."""

    client_token: str
    title: str
    privacy_level: str
    comment_level: str
    aigc_label: bool
    video_size_bytes: int
    chunk_size: int


@dataclass(frozen=True)
class DirectPostInitResult:
    publish_id: str
    upload_urls: tuple[str, ...]


class TikTokPublishPhase(StrEnum):
    """Publish phases of the documented status-fetch response (as-of 2026-10)."""

    SEND_TO_INBOX = "SEND_TO_INBOX"
    PROCESSING = "PROCESSING"
    PUBLISH_COMPLETE = "PUBLISH_COMPLETE"
    PUBLISH_FAILED = "PUBLISH_FAILED"


@dataclass(frozen=True)
class TikTokPublishStatus:
    phase: TikTokPublishPhase
    fail_code: str | None = None
    share_url: str | None = None


@runtime_checkable
class TikTokTransport(Protocol):
    """The documented Content Posting API surface an adapter drives."""

    def user_settings(self, account_ref: str) -> TikTokAccountSettings: ...

    def direct_post_init(
        self, account_ref: str, request: DirectPostInitRequest
    ) -> DirectPostInitResult: ...

    def upload_chunk(self, account_ref: str, publish_id: str, url: str, data: bytes) -> int: ...

    def fetch_status(self, account_ref: str, publish_id: str) -> TikTokPublishStatus: ...

    def find_publish_id(self, client_token: str) -> str | None: ...


class LiveTikTokTransport:
    """Refusing stub: live publishing stays disabled until T032 (controlled account tests)."""

    def _refuse(self, method: str) -> PolicyDenied:
        return PolicyDenied(
            f"live publishing disabled until T032: TikTok transport.{method} refuses to run",
            method=method,
            provider_route="tiktok",
        )

    def user_settings(self, account_ref: str) -> TikTokAccountSettings:
        raise self._refuse("user_settings")

    def direct_post_init(
        self, account_ref: str, request: DirectPostInitRequest
    ) -> DirectPostInitResult:
        raise self._refuse("direct_post_init")

    def upload_chunk(self, account_ref: str, publish_id: str, url: str, data: bytes) -> int:
        raise self._refuse("upload_chunk")

    def fetch_status(self, account_ref: str, publish_id: str) -> TikTokPublishStatus:
        raise self._refuse("fetch_status")

    def find_publish_id(self, client_token: str) -> str | None:
        raise self._refuse("find_publish_id")


def fixture_publish_id(client_token: str) -> str:
    """Deterministic publish id for a client token (external ids via stable_digest)."""
    return f"tiktok-{stable_digest(client_token)}"


@dataclass
class _PublishRecord:
    publish_id: str
    client_token: str
    account_ref: str
    request: DirectPostInitRequest
    uploaded_bytes: int = 0
    fully_uploaded: bool = False
    fetch_count: int = 0
    failed_code: str | None = None
    share_url: str | None = None


class FixtureTikTokTransport(FakeBase):
    """Deterministic offline transport: scenario queue, fixture accounts, *.invalid URLs.

    Scenario steps are consumed by ``direct_post_init`` (the submit's first external
    call). Status/reconcile calls never consume steps, mirroring the T007 fake. The
    publish lifecycle advances one phase per ``fetch_status``: the first fetch after a
    complete upload reports PROCESSING, the next PUBLISH_COMPLETE with a fixture share
    URL (sticky afterwards). ``fail_next_status`` scripts a PUBLISH_FAILED outcome.
    """

    default_scenario: ClassVar[TikTokScenario] = TikTokScenario.ACCEPTED

    def __init__(
        self,
        *,
        clock: FakeClock,
        ids: SequentialIds,
        scenarios: Iterable[TikTokScenario] = (),
        account_settings: Mapping[str, TikTokAccountSettings] | None = None,
    ) -> None:
        super().__init__(clock=clock, ids=ids, scenarios=scenarios)
        self._accounts: dict[str, TikTokAccountSettings] = dict(account_settings or {})
        self._publish: dict[str, _PublishRecord] = {}
        self._by_token: dict[str, str] = {}
        self._status_failures: deque[str] = deque()
        #: Every init payload that reached the API (assertion surface for the AIGC label).
        self.init_requests: list[DirectPostInitRequest] = []

    # --- accounts ---------------------------------------------------------------------

    def user_settings(self, account_ref: str) -> TikTokAccountSettings:
        self._note("user_settings", key=account_ref)
        return self._accounts.get(account_ref, DEFAULT_ACCOUNT_SETTINGS)

    # --- direct post --------------------------------------------------------------------

    def direct_post_init(
        self, account_ref: str, request: DirectPostInitRequest
    ) -> DirectPostInitResult:
        step = self._step("direct_post_init", key=request.client_token)
        if step is TikTokScenario.RATE_LIMITED:
            raise TikTokTransportError(
                api_error_code="RATE_LIMITED",
                message="fixture transport rate limit; retry with backoff",
            )
        if step is TikTokScenario.DENIED_PERMISSION:
            raise TikTokTransportError(
                api_error_code="PERMISSION_DENIED",
                message="fixture transport: app lacks the video.publish grant for this user",
            )
        if step is TikTokScenario.TOKEN_EXPIRED:
            raise TikTokTransportError(
                api_error_code="TOKEN_EXPIRED",
                message="fixture transport: access token expired",
            )

        # The request reached the API in every remaining case (even the timeouts).
        self.init_requests.append(request)
        if step is TikTokScenario.TIMEOUT_NOT_CREATED:
            raise TikTokTimeoutError(
                api_error_code="TIMEOUT",
                message="fixture transport timed out before creating anything",
            )

        publish_id = fixture_publish_id(request.client_token)
        chunks = max(1, -(-request.video_size_bytes // request.chunk_size))
        urls = tuple(
            fake_https("upload.tiktok", f"{publish_id}/chunk/{index}") for index in range(chunks)
        )
        record = _PublishRecord(
            publish_id=publish_id,
            client_token=request.client_token,
            account_ref=account_ref,
            request=request,
        )
        self._publish[publish_id] = record
        self._by_token[request.client_token] = publish_id
        if step is TikTokScenario.TIMEOUT_CREATED:
            # The post exists and the platform accepted the video; only the response
            # was lost (the T007 matrix semantics: reconcile finds a completable post).
            record.fully_uploaded = True
            raise TikTokTimeoutError(
                api_error_code="TIMEOUT",
                message="fixture transport created the post but the response timed out",
            )
        return DirectPostInitResult(publish_id=publish_id, upload_urls=urls)

    def upload_chunk(self, account_ref: str, publish_id: str, url: str, data: bytes) -> int:
        self._note("upload_chunk", key=publish_id)
        record = self._require(publish_id)
        record.uploaded_bytes += len(data)
        if record.uploaded_bytes >= record.request.video_size_bytes:
            # Processing starts once the declared size has fully arrived.
            record.fully_uploaded = True
        return len(data)

    # --- status and reconcile ------------------------------------------------------------

    def fetch_status(self, account_ref: str, publish_id: str) -> TikTokPublishStatus:
        self._note("fetch_status", key=publish_id)
        record = self._require(publish_id)
        if self._status_failures:
            record.failed_code = self._status_failures.popleft()
        if record.failed_code is not None:
            return TikTokPublishStatus(
                phase=TikTokPublishPhase.PUBLISH_FAILED, fail_code=record.failed_code
            )
        record.fetch_count += 1
        if not record.fully_uploaded or record.fetch_count == 1:
            return TikTokPublishStatus(phase=TikTokPublishPhase.PROCESSING)
        record.share_url = fake_https("tiktok", f"@fixture/video/{publish_id}")
        return TikTokPublishStatus(
            phase=TikTokPublishPhase.PUBLISH_COMPLETE, share_url=record.share_url
        )

    def find_publish_id(self, client_token: str) -> str | None:
        self._note("find_publish_id", key=client_token)
        return self._by_token.get(client_token)

    # --- fixture knobs -------------------------------------------------------------------

    def fail_next_status(self, fail_code: str) -> None:
        """Script the next status fetch of any live record to report PUBLISH_FAILED."""
        self._status_failures.append(fail_code)

    @property
    def publish_ids(self) -> tuple[str, ...]:
        return tuple(self._publish)

    def _require(self, publish_id: str) -> _PublishRecord:
        record = self._publish.get(publish_id)
        if record is None:
            raise NotFound("fixture transport has no such publish id", external_id=publish_id)
        return record


def read_media_chunks(path: Path, chunk_size: int) -> Any:
    """Yield the file's bytes in documented-size chunks (streamed, never whole-file)."""
    with open(path, "rb") as handle:
        while chunk := handle.read(chunk_size):
            yield chunk


__all__ = [
    "DEFAULT_ACCOUNT_SETTINGS",
    "FIXTURE_CHUNK_SIZE_BYTES",
    "FixtureTikTokTransport",
    "LiveTikTokTransport",
    "DirectPostInitRequest",
    "DirectPostInitResult",
    "RETRY_AFTER_MS",
    "ScenarioQueue",
    "TikTokAccountSettings",
    "TikTokPublishPhase",
    "TikTokPublishStatus",
    "TikTokScenario",
    "TikTokTimeoutError",
    "TikTokTransport",
    "TikTokTransportError",
    "fixture_publish_id",
    "read_media_chunks",
]
