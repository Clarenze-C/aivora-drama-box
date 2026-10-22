"""Instagram publisher adapter (T023): documented platform rules over a Transport.

This is an OFFLINE adapter: platform rules (professional-account requirement,
REELS-vs-feed-VIDEO routing, documented duration ceilings and caption limits, the
container/process/publish state mapping, the image-only caption-update refusal and
the disclosure-readback truth) applied on top of the
:class:`~microdrama.publishing.instagram.transport.InstagramTransport` surface. It
implements the shared ``PublisherAdapter`` protocol and owns NO local approval,
budget or gate logic — those stay with Gate 2 and the publishing service.

State mapping (documented flow):

- ``submit``   → container created (``POST /media``): ``SUBMITTED`` with the
  container id as the external id.
- ``status``   → container ``in_progress``: ``PROCESSING``; container ``finished``:
  publish (``POST /media_publish``) and report ``PUBLISHED_VERIFIED`` with the
  published media id; container ``error``/``expired``: ``FAILED`` (non-transient).
- ``readback`` → the media node: visible, but ``disclosures_visible`` is always
  empty — there is no documented API field to set or read back a synthetic-media
  label, so verification of an AI disclosure can never succeed on this platform
  through this API (see ``capabilities.py``).

Dedupe: submit is deduplicated by ``client_token`` (and slot dedupe key); a replay
returns the current state and creates nothing. A submit that times out after the
container was created records the id from the timeout details and re-raises
``NeedsReconciliation``; ``reconcile`` then finds it by token.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from microdrama.contracts.enums import Platform, Provenance, ReleaseState, SlotKind
from microdrama.contracts.errors import NeedsReconciliation, NotFound
from microdrama.contracts.hashing import file_sha256
from microdrama.contracts.providers import PostReadback, ReconcileResult
from microdrama.contracts.release import (
    CapabilityRecord,
    PostMetadata,
    PublicationCommand,
    PublishResult,
)
from microdrama.publishing.instagram import capabilities as caps
from microdrama.publishing.instagram.transport import (
    GRAPH_CODE_PERMISSION_DENIED,
    GRAPH_CODE_TOKEN_INVALID,
    ContainerCreateRequest,
    ContainerKind,
    ContainerStatusCode,
    FixtureInstagramTransport,
    GraphApiError,
    InstagramTransport,
)
from microdrama.testing.fakes.common import fake_https, stable_digest

FAKE = Provenance.FAKE_SYNTHETIC

#: Documented routing: promo cuts and hooks are Reels; episodes/parts are feed video.
CONTAINER_KIND_BY_SLOT: dict[SlotKind, ContainerKind] = {
    SlotKind.FULL_EPISODE: ContainerKind.VIDEO,
    SlotKind.PART: ContainerKind.VIDEO,
    SlotKind.PROMO_CUT: ContainerKind.REELS,
    SlotKind.HOOK: ContainerKind.REELS,
}

#: Fields a completed publish can honestly claim to have proven at the adapter.
PUBLISH_VERIFIED_FIELDS = ("container_status", "media_id", "permalink")

#: Readback gaps the documented media node cannot close. "disclosures" is load
#: bearing: without a readable disclosure field, the service can never verify the
#: AI disclosure a slot declared — the documented outcome of this lane.
READBACK_UNVERIFIED_FIELDS = ("disclosures", "privacy", "subtitles_present", "cover")


def _failed(error_code: str) -> PublishResult:
    return PublishResult(
        state=ReleaseState.FAILED, error_code=error_code, transient=False, provenance=FAKE
    )


def caption_text(metadata: PostMetadata) -> str:
    """One caption string: caption text with the hashtags appended (documented shape)."""
    parts = [metadata.caption, *metadata.hashtags]
    return " ".join(part for part in parts if part)


class InstagramAdapter:
    """``PublisherAdapter`` for Instagram, offline-only until T032."""

    platform = Platform.INSTAGRAM
    provider_route = caps.PROVIDER_ROUTE

    def __init__(
        self,
        transport: InstagramTransport,
        *,
        duration_lookup: Callable[[UUID], int | None] | None = None,
        version: int = 1,
    ) -> None:
        self._transport = transport
        self._duration_lookup = duration_lookup or (lambda _asset_id: None)
        self._version = version
        self._container_by_token: dict[str, str] = {}
        self._container_by_dedupe: dict[str, str] = {}
        self._media_by_container: dict[str, str] = {}

    @property
    def version(self) -> int:
        return self._version

    def with_version(self, version: int) -> InstagramAdapter:
        """A view of this adapter whose capability reports a new record version.

        Shares the transport but not the submit ledgers — scheduling pins the
        capability version, so a bumped adapter is how CAPABILITY_STALE is produced.
        """
        return InstagramAdapter(
            self._transport, duration_lookup=self._duration_lookup, version=version
        )

    # --- capability -----------------------------------------------------------------------

    def capability(self, account_ref: str) -> CapabilityRecord:
        """The capability record for an account; account truth comes from the transport.

        Fixture transport: enabled (professional accounts only) with FAKE_FIXTURE
        evidence so the service runs e2e offline. Any other transport (the refusing
        live stub) raises PolicyDenied — capability truth needs an account query,
        and live account access stays disabled until T032.
        """
        account = self._transport.account(account_ref)
        if isinstance(self._transport, FixtureInstagramTransport):
            return caps.fixture_capability_record(
                account_ref=account_ref,
                account_type=account.account_type.value,
                professional=account.is_professional,
                version=self._version,
                verified_at=self._transport.clock.now(),
            )
        return caps.documented_capability_record(
            account_ref=account_ref, account_type=account.account_type.value
        )

    # --- submit ---------------------------------------------------------------------------

    def submit(self, command: PublicationCommand, media_path: Path) -> PublishResult:
        # 1. Replayed submits are answered from the dedupe cache; nothing is created.
        existing = self._container_by_token.get(command.client_token) or (
            self._container_by_dedupe.get(command.dedupe_key)
        )
        if existing is not None:
            return self._current_result(command, existing)

        # 2. Professional-account requirement (documented): personal accounts
        #    cannot use the publishing API.
        account = self._transport.account(command.slot.account_ref)
        if not account.is_professional:
            return _failed("NOT_PROFESSIONAL_ACCOUNT")

        # 3. Media truth: the file must exist and hash to the pinned value.
        if not Path(media_path).is_file():
            raise NotFound(
                "media file for publishing not found", command_id=str(command.command_id)
            )
        if file_sha256(str(media_path)) != command.asset_sha256:
            return _failed("ASSET_HASH_MISMATCH")

        # 4. Documented platform rules: routing, duration ceilings, caption shape.
        kind = CONTAINER_KIND_BY_SLOT[command.slot_kind]
        duration = self._duration_lookup(command.asset_id)
        if duration is not None:
            lo, hi = (
                (caps.REELS_MIN_DURATION_MS, caps.REELS_MAX_DURATION_MS)
                if kind is ContainerKind.REELS
                else (caps.FEED_VIDEO_MIN_DURATION_MS, caps.FEED_VIDEO_MAX_DURATION_MS)
            )
            if duration > hi:
                return _failed("DURATION_EXCEEDS_ROUTE_LIMIT")
            if duration < lo:
                return _failed("DURATION_BELOW_MINIMUM")
        caption = caption_text(command.metadata)
        if len(caption) > caps.CAPTION_MAX_CHARS:
            return _failed("CAPTION_TOO_LONG")

        # 5. The documented wire call: container create (scenario-driven fixture).
        request = ContainerCreateRequest(
            media_type=kind,
            video_url=_fixture_video_url(command),
            caption=caption,
            client_token=command.client_token,
            cover_url=None,
            share_to_feed=True if kind is ContainerKind.REELS else None,
            asset_id=command.asset_id,
        )
        try:
            state = self._transport.create_container(command.slot.account_ref, request)
        except GraphApiError as error:
            return self._map_graph_error(error)
        except NeedsReconciliation as needs:
            # TIMEOUT_CREATED: the container exists; record it so reconcile finds it.
            container_id = needs.details.get("container_id")
            if container_id is not None:
                self._remember(command, str(container_id))
            raise
        self._remember(command, state.container_id)
        return PublishResult(
            state=ReleaseState.SUBMITTED,
            external_id=state.container_id,
            provenance=FAKE,
        )

    @staticmethod
    def _map_graph_error(error: GraphApiError) -> PublishResult:
        if error.graph_code == GRAPH_CODE_PERMISSION_DENIED:
            return _failed("PERMISSION_DENIED")
        if error.graph_code == GRAPH_CODE_TOKEN_INVALID:
            return _failed("TOKEN_EXPIRED")
        return _failed(f"GRAPH_ERROR_{error.graph_code}")

    def _remember(self, command: PublicationCommand, container_id: str) -> None:
        self._container_by_token[command.client_token] = container_id
        self._container_by_dedupe[command.dedupe_key] = container_id

    # --- status / poll ----------------------------------------------------------------------

    def status(self, command: PublicationCommand, external_id: str) -> PublishResult:
        # Already-published media (either id shape): idempotent re-poll of a
        # verified post — the real API would refuse a second media_publish of the
        # same container, so the adapter answers from its own ledger.
        published = set(self._media_by_container.values())
        if external_id in published:
            return self._verified_result(external_id)
        media_id = self._media_by_container.get(external_id)
        if media_id is not None:
            return self._verified_result(media_id)

        state = self._transport.container_status(external_id)
        if state.status_code is ContainerStatusCode.IN_PROGRESS:
            return PublishResult(
                state=ReleaseState.PROCESSING, external_id=external_id, provenance=FAKE
            )
        if state.status_code is ContainerStatusCode.ERROR:
            return _failed("CONTAINER_ERROR")
        if state.status_code is ContainerStatusCode.EXPIRED:
            return _failed("CONTAINER_EXPIRED")

        # finished: the documented second call — publish the container now.
        media_id = self._transport.publish_container(external_id)
        self._media_by_container[external_id] = media_id
        return self._verified_result(media_id)

    def _verified_result(self, media_id: str) -> PublishResult:
        readback = self._transport.media(media_id)
        return PublishResult(
            state=ReleaseState.PUBLISHED_VERIFIED,
            external_id=media_id,
            url=readback.permalink,
            verified_fields=list(PUBLISH_VERIFIED_FIELDS),
            unverified_fields=list(READBACK_UNVERIFIED_FIELDS),
            provenance=FAKE,
        )

    # --- reconcile --------------------------------------------------------------------------

    def reconcile(self, command: PublicationCommand) -> ReconcileResult:
        container_id = self._container_by_token.get(command.client_token) or (
            self._container_by_dedupe.get(command.dedupe_key)
        )
        if container_id is None:
            return ReconcileResult(found=False, result=None)
        return ReconcileResult(found=True, result=self._current_result(command, container_id))

    def _current_result(self, command: PublicationCommand, container_id: str) -> PublishResult:
        """The result for a container this adapter already created (dedupe/reconcile).

        Answers from the adapter ledger, like the T007 fake: no platform call, no
        scenario step consumed. A container that was never advanced by ``status``
        is still SUBMITTED; a published one reports its verified media.
        """
        media_id = self._media_by_container.get(container_id)
        if media_id is not None:
            return self._verified_result(media_id)
        return PublishResult(
            state=ReleaseState.SUBMITTED, external_id=container_id, provenance=FAKE
        )

    # --- metadata / readback / insights ------------------------------------------------------

    def update_metadata(
        self, account_ref: str, external_id: str, metadata: PostMetadata
    ) -> PublishResult:
        """Caption edits only — and the documented surface refuses them for video.

        ``POST /{ig-media-id}`` caption update is documented for image media only;
        every container this lane publishes is video (VIDEO or REELS), so the
        operation honestly fails with METADATA_UPDATE_IMAGE_ONLY. The capability
        record carries the same truth (METADATA_UPDATE = UNSUPPORTED).
        """
        if external_id not in self._media_by_container.values():
            raise NotFound("no published media for this id", external_id=external_id)
        return _failed("METADATA_UPDATE_IMAGE_ONLY")

    def readback(self, account_ref: str, external_id: str) -> PostReadback:
        """The documented media node, honestly: visible, but disclosure-blind.

        ``disclosures_visible`` is always empty and "disclosures" stays in
        ``unverified_fields``: no documented API field reads back a synthetic-media
        label, so an AI-disclosure verification can never succeed here.
        """
        media = self._transport.media(external_id)
        return PostReadback(
            external_id=external_id,
            visible=True,
            privacy=None,
            disclosures_visible=[],
            subtitles_present=None,
            links=[media.permalink],
            unverified_fields=list(READBACK_UNVERIFIED_FIELDS),
            provenance=FAKE,
        )

    def insights(self, account_ref: str, external_id: str) -> tuple[str, ...]:
        """Documented media-insights edge (beyond the PublisherAdapter protocol).

        Returns the metric names available for the published media; a container id
        (nothing published yet) or an unknown id is NOT_FOUND.
        """
        return self._transport.insights(external_id).metric_names


def _fixture_video_url(command: PublicationCommand) -> str:
    return fake_https("cdn.instagram-fixture", f"media/{stable_digest(command.client_token)}.mp4")


__all__ = [
    "CONTAINER_KIND_BY_SLOT",
    "PUBLISH_VERIFIED_FIELDS",
    "READBACK_UNVERIFIED_FIELDS",
    "InstagramAdapter",
    "caption_text",
]
