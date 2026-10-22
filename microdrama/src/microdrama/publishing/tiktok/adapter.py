"""TikTok publisher adapter (T022): documented platform rules over a transport.

The adapter implements the frozen ``PublisherAdapter`` protocol exactly — no local
approval, budget or gate logic (all of that belongs to the T020 core). Platform rules
encoded here come from the official Content Posting API documentation (as-of 2026-10)
for an ELIGIBLE route: an audited app/provider with the ``video.publish`` grant.

Rules this adapter owns:

- **Two routes, one truth.** ``direct_post`` is the only unattended route. The inbox
  route (``INBOX_UPLOAD``) lands the video in the user's inbox/drafts where a human
  must act: an inbox submit is refused with a typed ``INBOX_REQUIRES_HUMAN`` failure
  and its capability record never advertises the unattended upload operations, so the
  service holds such slots before any adapter call.
- **Account truth over marketing.** Capability limits and upload support come from the
  account's actual user-info settings (privacy/comment options, direct-post
  permission, the account's own max video duration), never from marketing claims or
  historical quotas.
- **AIGC declaration.** ``DisclosureKind.AI_GENERATED_CONTENT`` maps to the documented
  AIGC declaration field on direct post. A route/account whose capability marks
  ``AI_DISCLOSURE`` UNSUPPORTED or UNKNOWN refuses the declaration (typed failure)
  rather than publishing an undeclared synthetic post.
- **Duration bounds.** Direct-post media must fit the account's duration window
  (documented 3 s – 10 min by default): over-ceiling and under-minimum submits fail
  with typed errors before anything is created.
- **Submit dedupe.** Replays of the same ``client_token`` return the existing post's
  state and create nothing.
- **Status/reconcile.** Documented publish phases map to contract states; publish
  failures keep their typed fail codes; a found-by-token reconcile reports the post,
  an absent one reports ``found=False``.
- **Metadata updates.** The documented surface has no metadata-update endpoint, so
  ``update_metadata`` is a typed refusal (``METADATA_UPDATE_UNSUPPORTED``).

All results carry ``Provenance.FAKE_SYNTHETIC`` and ``*.invalid`` URLs: this build
ships only the offline fixture transport (live publishing stays disabled until T032).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from microdrama.contracts.enums import (
    CapabilityOperation,
    CapabilitySupport,
    DisclosureKind,
    Platform,
    Provenance,
    ReleaseState,
)
from microdrama.contracts.errors import NeedsReconciliation, NotFound, RateLimited
from microdrama.contracts.hashing import file_sha256
from microdrama.contracts.providers import PostReadback, ReconcileResult
from microdrama.contracts.release import (
    CapabilityRecord,
    PostMetadata,
    PublicationCommand,
    PublishResult,
)
from microdrama.publishing.tiktok.capabilities import (
    DIRECT_POST_DOCUMENTED_OPERATIONS,
    DOCUMENTED_MAX_DURATION_MS,
    DOCUMENTED_MIN_DURATION_MS,
    INBOX_DOCUMENTED_OPERATIONS,
    ROUTE_IDENTIFIERS,
    TikTokRoute,
    build_capability_record,
)
from microdrama.publishing.tiktok.transport import (
    FIXTURE_CHUNK_SIZE_BYTES,
    RETRY_AFTER_MS,
    DirectPostInitRequest,
    TikTokAccountSettings,
    TikTokPublishPhase,
    TikTokPublishStatus,
    TikTokTimeoutError,
    TikTokTransport,
    TikTokTransportError,
    read_media_chunks,
)

#: Typed submit-refusal codes of this adapter (documented decisions, frozen for tests).
INBOX_REQUIRES_HUMAN = "INBOX_REQUIRES_HUMAN"
DIRECT_POST_DISABLED_ON_ACCOUNT = "DIRECT_POST_DISABLED_ON_ACCOUNT"
DURATION_EXCEEDS_LIMIT = "DURATION_EXCEEDS_LIMIT"
DURATION_BELOW_MINIMUM = "DURATION_BELOW_MINIMUM"
UNSUPPORTED_DISCLOSURE = "UNSUPPORTED_DISCLOSURE"
DISCLOSURE_UNVERIFIED = "DISCLOSURE_UNVERIFIED"
ASSET_HASH_MISMATCH = "ASSET_HASH_MISMATCH"
METADATA_UPDATE_UNSUPPORTED = "METADATA_UPDATE_UNSUPPORTED"
PUBLISH_FAILED = "PUBLISH_FAILED"
PERMISSION_DENIED = "PERMISSION_DENIED"
TOKEN_EXPIRED = "TOKEN_EXPIRED"

#: Documented publish-failure codes kept verbatim; anything else collapses to the
#: generic typed failure so no undocumented code leaks into slot rows untyped.
DOCUMENTED_FAIL_CODES = frozenset({"VIDEO_REFUSED", "SIZE_TOO_LARGE", "FORMAT_UNSUPPORTED"})

DurationProbe = Callable[[Path], int]


class FixtureDurationProbe:
    """Offline duration probe: sha256-keyed table with the fixture master default.

    A live adapter (T032) measures duration from the actual file (ffprobe); offline,
    the test world seeds ``by_sha`` with the durations it registered for its assets.
    The default mirrors the fixture master asset (30 s, within the documented window).
    """

    def __init__(self, *, default_ms: int = 30_000) -> None:
        self.default_ms = default_ms
        self.by_sha: dict[str, int] = {}

    def __call__(self, media_path: Path) -> int:
        return self.by_sha.get(file_sha256(str(media_path)), self.default_ms)


class TikTokPublisherAdapter:
    """``PublisherAdapter`` for the documented TikTok Content Posting API surface."""

    platform = Platform.TIKTOK

    def __init__(
        self,
        *,
        transport: TikTokTransport,
        route: TikTokRoute = TikTokRoute.DIRECT_POST,
        duration_probe: DurationProbe | None = None,
        operations_override: Mapping[CapabilityOperation, CapabilitySupport] | None = None,
        account_settings: Callable[[str], TikTokAccountSettings | None] | None = None,
        chunk_size: int = FIXTURE_CHUNK_SIZE_BYTES,
        enabled: bool = True,
        fixture: bool = True,
        version: int = 1,
        clock=None,
    ) -> None:
        if fixture and clock is None:
            raise ValueError("a fixture adapter needs a clock for capability verified_at")
        self._transport = transport
        self._route = route
        self.provider_route = ROUTE_IDENTIFIERS[route]
        self._duration_probe = duration_probe or FixtureDurationProbe()
        self._operations_override = dict(operations_override) if operations_override else None
        # Account-truth resolver. The fixture transport supplies it in-process; a live
        # adapter must inject a cached resolver (never a network call). When absent —
        # the documentation-only adapter — capability records carry the documented
        # defaults and account truth stays unknown.
        if account_settings is not None:
            self._account_settings = account_settings
        elif fixture:
            self._account_settings = self._transport.user_settings
        else:
            self._account_settings = None
        self._chunk_size = chunk_size
        self._enabled = enabled
        self._fixture = fixture
        #: Mutable so a test (or a live refresh) can move the record version forward.
        self.version = version
        self._clock = clock
        #: Declarations this process made at init (offline readback memory; live
        #: disclosure-visibility readback is UNKNOWN until T032). Keyed by publish id
        #: once known, and by client token from the moment the request is built so a
        #: timeout-created post can be re-associated at reconcile time.
        self._declarations: dict[str, DirectPostInitRequest] = {}
        self._declarations_by_token: dict[str, DirectPostInitRequest] = {}

    # --- capability -----------------------------------------------------------------------

    def capability(self, account_ref: str) -> CapabilityRecord:
        """Record for this route/account. Fixture variants are enabled; the default
        (documented) variant is disabled until T032.

        Live adapters must serve this from cached account info: the service calls it
        inside its submit transaction, so it may never perform a network round-trip.
        The offline fixture transport is in-process and deterministic.
        """
        settings = self._settings_for(account_ref)
        return build_capability_record(
            route=self._route,
            account_ref=account_ref,
            account_settings=settings,
            operations_override=self._operations_override,
            version=self.version,
            enabled=self._enabled,
            fixture=self._fixture,
            now=self._clock.now() if (self._fixture and self._clock is not None) else None,
        )

    def bump_version(self) -> int:
        """Move the capability record version forward (staleness tests/refreshes)."""
        self.version += 1
        return self.version

    # --- submit ----------------------------------------------------------------------------

    def submit(self, command: PublicationCommand, media_path: Path) -> PublishResult:
        existing = self._transport.find_publish_id(command.client_token)
        if existing is not None:
            # Replay of the same client token: answer from the existing post, create
            # nothing, consume no scenario step.
            status = self._transport.fetch_status(command.slot.account_ref, existing)
            return self._status_result(existing, status)

        if self._route is TikTokRoute.INBOX_UPLOAD:
            return self._failed(
                INBOX_REQUIRES_HUMAN,
                "inbox uploads land in the user's inbox/drafts; a human must complete "
                "the post, so this route is never published unattended",
            )

        ai_support = self._ai_support()
        wants_aigc = DisclosureKind.AI_GENERATED_CONTENT in command.metadata.disclosures
        if wants_aigc:
            if ai_support is CapabilitySupport.UNSUPPORTED:
                return self._failed(
                    UNSUPPORTED_DISCLOSURE,
                    "route/account does not support the AIGC declaration",
                )
            if ai_support is CapabilitySupport.UNKNOWN:
                return self._failed(
                    DISCLOSURE_UNVERIFIED,
                    "AIGC declaration support is unknown; refusing to publish undeclared",
                )

        settings = self._settings_for(command.slot.account_ref)
        if settings is not None and not settings.direct_post_permitted:
            return self._failed(
                DIRECT_POST_DISABLED_ON_ACCOUNT,
                "account settings do not permit direct post (account truth, not marketing)",
            )

        media = Path(media_path)
        if not media.is_file():
            raise NotFound(
                "media file for publishing not found", command_id=str(command.command_id)
            )
        sha = file_sha256(str(media))
        if sha != command.asset_sha256:
            return self._failed(
                ASSET_HASH_MISMATCH, "media bytes do not match the command's pinned asset"
            )

        duration_ms = self._duration_probe(media)
        limits = self.capability(command.slot.account_ref).limits
        max_ms = limits.max_duration_ms or DOCUMENTED_MAX_DURATION_MS
        min_ms = limits.min_duration_ms or DOCUMENTED_MIN_DURATION_MS
        if duration_ms > max_ms:
            return self._failed(
                DURATION_EXCEEDS_LIMIT,
                f"media duration {duration_ms} ms exceeds the account/route ceiling "
                f"{max_ms} ms for direct post",
            )
        if duration_ms < min_ms:
            return self._failed(
                DURATION_BELOW_MINIMUM,
                f"media duration {duration_ms} ms is under the documented minimum {min_ms} ms",
            )

        privacy = "PUBLIC_TO_EVERYONE"
        if settings is not None and privacy not in settings.privacy_level_options:
            privacy = settings.privacy_level_options[0]
        comment = settings.comment_options[0] if settings else "CLOSE_TO_COMMENT"
        request = DirectPostInitRequest(
            client_token=command.client_token,
            title=command.metadata.title,
            privacy_level=privacy,
            comment_level=comment,
            aigc_label=wants_aigc,
            video_size_bytes=media.stat().st_size,
            chunk_size=self._chunk_size,
        )
        self._declarations_by_token[command.client_token] = request
        try:
            init = self._transport.direct_post_init(command.slot.account_ref, request)
        except TikTokTransportError as err:
            return self._map_init_error(err, command)
        self._declarations[init.publish_id] = request

        for url, chunk in zip(
            init.upload_urls, read_media_chunks(media, self._chunk_size), strict=False
        ):
            self._transport.upload_chunk(command.slot.account_ref, init.publish_id, url, chunk)

        return PublishResult(
            state=ReleaseState.SUBMITTED,
            external_id=init.publish_id,
            provenance=Provenance.FAKE_SYNTHETIC,
        )

    def _map_init_error(
        self, err: TikTokTransportError, command: PublicationCommand
    ) -> PublishResult:
        if isinstance(err, TikTokTimeoutError):
            raise NeedsReconciliation(
                "tiktok direct-post outcome unknown (timeout)",
                client_token=command.client_token,
            ) from err
        if err.api_error_code == "RATE_LIMITED":
            raise RateLimited(
                "tiktok direct-post rate limited",
                retry_after_ms=RETRY_AFTER_MS,
                client_token=command.client_token,
            ) from err
        if err.api_error_code in (PERMISSION_DENIED, TOKEN_EXPIRED):
            return self._failed(err.api_error_code, err.message)
        return self._failed(PUBLISH_FAILED, err.message)

    # --- status / reconcile ------------------------------------------------------------------

    def status(self, command: PublicationCommand, external_id: str) -> PublishResult:
        status = self._transport.fetch_status(command.slot.account_ref, external_id)
        return self._status_result(external_id, status)

    def reconcile(self, command: PublicationCommand) -> ReconcileResult:
        publish_id = self._transport.find_publish_id(command.client_token)
        if publish_id is None:
            return ReconcileResult(found=False, result=None)
        # A post found after an ambiguous submit adopts the declaration this process
        # made when it built the init request (a live adapter persists this link).
        declaration = self._declarations_by_token.get(command.client_token)
        if declaration is not None:
            self._declarations.setdefault(publish_id, declaration)
        status = self._transport.fetch_status(command.slot.account_ref, publish_id)
        return ReconcileResult(found=True, result=self._status_result(publish_id, status))

    def _status_result(self, publish_id: str, status: TikTokPublishStatus) -> PublishResult:
        if status.phase is TikTokPublishPhase.PROCESSING:
            return PublishResult(
                state=ReleaseState.PROCESSING,
                external_id=publish_id,
                provenance=Provenance.FAKE_SYNTHETIC,
            )
        if status.phase is TikTokPublishPhase.PUBLISH_COMPLETE:
            return PublishResult(
                state=ReleaseState.PUBLISHED_VERIFIED,
                external_id=publish_id,
                url=status.share_url,
                verified_fields=["publish_state", "share_url"],
                unverified_fields=["privacy_level", "comment_settings"],
                provenance=Provenance.FAKE_SYNTHETIC,
            )
        if status.phase is TikTokPublishPhase.PUBLISH_FAILED:
            code = status.fail_code if status.fail_code in DOCUMENTED_FAIL_CODES else None
            return PublishResult(
                state=ReleaseState.FAILED,
                external_id=publish_id,
                error_code=code or PUBLISH_FAILED,
                transient=False,
                provenance=Provenance.FAKE_SYNTHETIC,
            )
        # SEND_TO_INBOX: the upload waits for a human in the app — reported, never
        # mistaken for unattended progress towards verification.
        return PublishResult(
            state=ReleaseState.SUBMITTED,
            external_id=publish_id,
            unverified_fields=["inbox_state"],
            provenance=Provenance.FAKE_SYNTHETIC,
        )

    # --- metadata / readback -------------------------------------------------------------------

    def update_metadata(
        self, account_ref: str, external_id: str, metadata: PostMetadata
    ) -> PublishResult:
        """Typed refusal: the documented surface has no metadata-update endpoint."""
        return self._failed(
            METADATA_UPDATE_UNSUPPORTED,
            "tiktok content posting api documents no metadata update endpoint",
        )

    def readback(self, account_ref: str, external_id: str) -> PostReadback:
        status = self._transport.fetch_status(account_ref, external_id)
        complete = status.phase is TikTokPublishPhase.PUBLISH_COMPLETE
        declared = self._declarations.get(external_id)
        disclosures: list[DisclosureKind] = []
        if complete and declared is not None and declared.aigc_label:
            disclosures = [DisclosureKind.AI_GENERATED_CONTENT]
        if complete:
            unverified = ["subtitles_present", "thumbnail", "comment_settings"]
        else:
            unverified = ["visibility", "disclosures", "privacy_level", "subtitles_present"]
        return PostReadback(
            external_id=external_id,
            visible=True if complete else None,
            # The contract field is a lowercase Identifier; the documented TikTok
            # privacy enum (e.g. PUBLIC_TO_EVERYONE) maps onto it lowercased.
            privacy=declared.privacy_level.lower() if declared is not None else None,
            disclosures_visible=disclosures,
            subtitles_present=None,
            links=[status.share_url] if status.share_url else [],
            unverified_fields=unverified,
            provenance=Provenance.FAKE_SYNTHETIC,
        )

    # --- helpers -----------------------------------------------------------------------------

    def _settings_for(self, account_ref: str) -> TikTokAccountSettings | None:
        return self._account_settings(account_ref) if self._account_settings else None

    def _ai_support(self) -> CapabilitySupport:
        table = (
            DIRECT_POST_DOCUMENTED_OPERATIONS
            if self._route is TikTokRoute.DIRECT_POST
            else INBOX_DOCUMENTED_OPERATIONS
        )
        operations = dict(table)
        if self._operations_override:
            operations.update(self._operations_override)
        return operations.get(CapabilityOperation.AI_DISCLOSURE, CapabilitySupport.UNKNOWN)

    def _failed(self, error_code: str, message: str) -> PublishResult:
        return PublishResult(
            state=ReleaseState.FAILED,
            error_code=error_code,
            transient=False,
            provenance=Provenance.FAKE_SYNTHETIC,
        )


__all__ = [
    "ASSET_HASH_MISMATCH",
    "DIRECT_POST_DISABLED_ON_ACCOUNT",
    "DISCLOSURE_UNVERIFIED",
    "DOCUMENTED_FAIL_CODES",
    "DURATION_BELOW_MINIMUM",
    "DURATION_EXCEEDS_LIMIT",
    "DurationProbe",
    "FixtureDurationProbe",
    "INBOX_REQUIRES_HUMAN",
    "METADATA_UPDATE_UNSUPPORTED",
    "PERMISSION_DENIED",
    "PUBLISH_FAILED",
    "TikTokPublisherAdapter",
    "TOKEN_EXPIRED",
    "UNSUPPORTED_DISCLOSURE",
]
