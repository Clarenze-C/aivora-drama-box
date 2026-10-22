"""Facebook Page publishing adapter (T024): platform rules over a transport.

Implements the frozen ``PublisherAdapter`` protocol (T020) as an OFFLINE adapter =
documented platform rules + a transport (fixture offline; refusing stub until T032).
No local approval, budget or gate logic — those belong to the service.

Route truth (the core of this packet): the SHORT-Reel route and the FULL-video route
are chosen STRICTLY from ``slot_kind`` and the explicit capability operations:

- ``FULL_EPISODE`` / ``PART`` -> the Page videos edge (resumable ``upload_phase``
  upload; ``UPLOAD_FULL_VIDEO``), supporting ``title``/``description`` and
  ``scheduled_publish_time`` (the only documented schedule surface).
- ``PROMO_CUT`` / ``HOOK`` -> the Reels container flow (``UPLOAD_SHORT``),
  description-only, with NO scheduled-publish parameter — a future-window short
  slot is refused (``SCHEDULE_UNSUPPORTED_ON_REELS``), never silently published now.

Nothing infers long-video API support from the Reels surface or the reverse; an
upload operation the record does not support is a policy refusal.

Declaration truth: with the snapshot's ``AI_DISCLOSURE == UNKNOWN`` the adapter
derives an empty ``supported_disclosures``, refuses AI-disclosed submits itself
(defense in depth — the service HELDs such slots earlier with
``UNSUPPORTED_DISCLOSURE``), and its readback can never report the AI label as
visible or verified. That IS the documented outcome until Meta documents a field.

Page scope: publishing happens as a Page with a Page token on the Page's own
surface. ``capability`` refuses non-Page accounts — personal profiles have no
publishing API, and the adapter will not shape a user-timeline route.

Verification is readback-gated by the service; this adapter's readback reports
``visible`` from the documented permalink/fields and only the disclosures the
record's derivation actually supports. Scenario outcomes (matrix): refusals map to
FAILED results, RATE_LIMITED raises ``RateLimited`` with ``retry_after_ms``, and
the TIMEOUT_* outcomes raise ``NeedsReconciliation`` for the service to reconcile
by ``client_token`` — never a blind resubmit.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from microdrama.contracts.enums import (
    CapabilityOperation,
    CapabilitySupport,
    DisclosureKind,
    Platform,
    Provenance,
    ReleaseState,
    SlotKind,
)
from microdrama.contracts.errors import NotFound, PolicyDenied
from microdrama.contracts.hashing import file_sha256
from microdrama.contracts.providers import PostReadback, ReconcileResult
from microdrama.contracts.release import (
    CapabilityRecord,
    PostMetadata,
    PublicationCommand,
    PublishResult,
)
from microdrama.publishing.facebook.capabilities import (
    ACCOUNT_TYPE,
    FB_PAGE_ACCOUNT,
    FB_PAGE_OPERATIONS,
    PROVIDER_ROUTE,
    facebook_page_capability_record,
    supported_disclosures_of,
)
from microdrama.publishing.facebook.transport import (
    FacebookScenario,
    FacebookTransport,
    FixtureFacebookTransport,
    PlatformVideoStatus,
    TransportRefused,
    UploadSession,
)
from microdrama.testing.fakes.common import FakeClock

_SUPPORTED = (CapabilitySupport.SUPPORTED_DOCUMENTED, CapabilitySupport.SUPPORTED_TESTED)

#: Explicit route selection: slot_kind -> documented surface. No inference anywhere.
_ROUTE_BY_KIND: dict[SlotKind, str] = {
    SlotKind.FULL_EPISODE: "full",
    SlotKind.PART: "full",
    SlotKind.PROMO_CUT: "reel",
    SlotKind.HOOK: "reel",
}
_UPLOAD_OP_BY_ROUTE: dict[str, CapabilityOperation] = {
    "full": CapabilityOperation.UPLOAD_FULL_VIDEO,
    "reel": CapabilityOperation.UPLOAD_SHORT,
}

_PHASE_STATE = {
    "uploaded": ReleaseState.SUBMITTED,
    "processing": ReleaseState.PROCESSING,
    "published": ReleaseState.PUBLISHED_VERIFIED,
}


class FacebookPageAdapter:
    """The Facebook Page ``PublisherAdapter``: documented rules over a transport."""

    platform = Platform.FACEBOOK
    provider_route = PROVIDER_ROUTE

    default_scenario: ClassVar[FacebookScenario] = FacebookScenario.ACCEPTED

    def __init__(
        self,
        *,
        clock: FakeClock,
        transport: FacebookTransport,
        operations: dict[CapabilityOperation, CapabilitySupport] | None = None,
        page_accounts: dict[str, str] | None = None,
        version: int = 1,
        fixture: bool = True,
        enabled: bool | None = None,
    ) -> None:
        self.clock = clock
        self.transport = transport
        self._operations = dict(operations if operations is not None else FB_PAGE_OPERATIONS)
        self._page_accounts = dict(page_accounts or {FB_PAGE_ACCOUNT: "Facebook Page (fixture)"})
        self._version = version
        self._fixture = fixture
        self._enabled = fixture if enabled is None else enabled
        self.metadata_versions: dict[str, list[PostMetadata]] = {}

    # --- capability ---------------------------------------------------------------------

    def capability(self, account_ref: str) -> CapabilityRecord:
        """The capability record for a Page account on this route.

        Refuses user-timeline routes: personal profiles have no publishing API, and
        the account-type truth lives here (``account_type='page'``), not in callers.
        """
        if account_ref not in self._page_accounts:
            raise PolicyDenied(
                "only Page-scoped publishing is implemented; personal profiles have no "
                "publishing API (user-timeline routes are refused)",
                account_ref=account_ref,
                account_type=ACCOUNT_TYPE,
            )
        return facebook_page_capability_record(
            account_ref,
            operations=self._operations,
            version=self._version,
            fixture=self._fixture and self._enabled,
            verified_at=self.clock.now() if self._fixture and self._enabled else None,
        )

    def queue_scenarios(self, *steps: FacebookScenario) -> None:
        """Forward scripted platform outcomes to the fixture transport (offline tests)."""
        if not isinstance(self.transport, FixtureFacebookTransport):
            raise PolicyDenied("scenario scripting exists only for the fixture transport")
        self.transport.queue_scenarios(*steps)

    # --- route selection -------------------------------------------------------------------

    @staticmethod
    def _route_for(slot_kind: SlotKind) -> str:
        try:
            return _ROUTE_BY_KIND[slot_kind]
        except KeyError:
            raise PolicyDenied(
                "slot kind has no documented Facebook route", slot_kind=slot_kind.value
            ) from None

    def _support(self, op: CapabilityOperation) -> CapabilitySupport:
        return self._operations.get(op, CapabilitySupport.UNKNOWN)

    def _disclosures(self) -> list[DisclosureKind]:
        return supported_disclosures_of(self._operations)

    # --- submit -----------------------------------------------------------------------------

    def submit(self, command: PublicationCommand, media_path: Path) -> PublishResult:
        # Replayed submit: the platform dedupe (client token) answers from cache and
        # creates nothing — a repeated job run must never create a second post, and
        # the replayed answer must not advance the platform lifecycle.
        existing = self.transport.find_post_by_token(command.client_token)
        if existing is not None:
            return self._result(self.transport.peek_video_status(external_id=existing))

        route = self._route_for(command.slot_kind)
        upload_op = _UPLOAD_OP_BY_ROUTE[route]
        support = self._support(upload_op)
        if support not in _SUPPORTED:
            raise PolicyDenied(
                f"{upload_op.value} is {support.value} on the Facebook Page route; "
                "no speculative capability is encoded",
                operation=upload_op.value,
            )

        try:
            return self._submit_on_route(command, media_path, route)
        except TransportRefused as refused:
            # Documented permanent refusals (permission/token, disclosure truth,
            # schedule truth, hash mismatch) are FAILED publishes, not exceptions.
            return self._failed(refused.error_code)

    def _submit_on_route(
        self, command: PublicationCommand, media_path: Path, route: str
    ) -> PublishResult:
        # Local media integrity first: the pinned asset must hash out (it is read for
        # the upload size regardless; a mismatch never reaches the platform).
        size_bytes, media = self._media(command, media_path)

        # The platform-side START consumes the scenario step — the scripted platform
        # outcome outranks the adapter's own gates, mirroring the reference adapter:
        # refusals, rate limits and pre-create timeouts happen before any post exists.
        if route == "full":
            session = self.transport.start_page_video_upload(
                account_ref=command.slot.account_ref,
                client_token=command.client_token,
                size_bytes=size_bytes,
            )
        else:
            container = self.transport.start_reel_container(
                account_ref=command.slot.account_ref,
                client_token=command.client_token,
            )

        self._disclosure_gate(command)
        scheduled_epoch = self._schedule_epoch(command, route)

        if route == "full":
            status = self._transfer_and_finish(command, session, media, scheduled_epoch)
        else:
            self.transport.upload_reel_video(container, size_bytes=size_bytes)
            status = self.transport.publish_reel(
                container, description=command.metadata.description or command.metadata.caption
            )
        return self._result(status)

    def _disclosure_gate(self, command: PublicationCommand) -> None:
        """Declaration truth, enforced at the adapter as defense in depth.

        The service HELDs unsupported-disclosure slots before the adapter runs; this
        keeps the adapter honest when driven directly (T032-style probes included).
        """
        if DisclosureKind.AI_GENERATED_CONTENT not in command.metadata.disclosures:
            return
        ai = self._support(CapabilityOperation.AI_DISCLOSURE)
        if ai is CapabilitySupport.UNSUPPORTED:
            raise TransportRefused(
                "UNSUPPORTED_DISCLOSURE",
                "the Facebook Page surface cannot set an AI-generated-content label",
            )
        if ai is CapabilitySupport.UNKNOWN:
            raise TransportRefused(
                "DISCLOSURE_UNVERIFIED",
                "no documented Facebook Page API field sets or reads back an "
                "AI-generated-content label (snapshot 2026-10); the submit is refused",
            )

    def _media(self, command: PublicationCommand, media_path: Path) -> tuple[int, bytes]:
        path = Path(media_path)
        if not path.is_file():
            raise NotFound(
                "media file for publishing not found", command_id=str(command.command_id)
            )
        media = path.read_bytes()
        if file_sha256(str(path)) != command.asset_sha256:
            raise TransportRefused(
                "ASSET_HASH_MISMATCH", "uploaded media does not hash to the pinned asset"
            )
        return len(media), media

    def _schedule_epoch(self, command: PublicationCommand, route: str) -> int | None:
        """Scheduled publish, only where the documentation actually provides it.

        ``scheduled_publish_time`` exists on the Page VIDEOS edge; the Reels surface
        documents no schedule parameter, so a future-window short slot is refused
        (``SCHEDULE_UNSUPPORTED_ON_REELS``), never published early.
        """
        scheduled_at = command.schedule.utc_instant
        if scheduled_at <= self.clock.now():
            return None  # the window already opened; publish immediately
        if route == "reel":
            raise TransportRefused(
                "SCHEDULE_UNSUPPORTED_ON_REELS",
                "the documented Reels surface has no scheduled-publish parameter; "
                "future-window short slots cannot be scheduled ahead",
            )
        if self._support(CapabilityOperation.SCHEDULE) not in _SUPPORTED:
            raise TransportRefused(
                "SCHEDULE_UNSUPPORTED", "SCHEDULE is not supported on this route"
            )
        return int(scheduled_at.timestamp())

    def _transfer_and_finish(
        self,
        command: PublicationCommand,
        session: UploadSession,
        media: bytes,
        scheduled_epoch: int | None,
    ) -> PlatformVideoStatus:
        """The documented resumable protocol: contiguous chunks, then finish."""
        offset = 0
        while offset < session.end_offset:
            end = min(offset + session.chunk_size, session.end_offset)
            self.transport.transfer_chunk(session, start_offset=offset, chunk=media[offset:end])
            offset = end
        return self.transport.finish_page_video_upload(
            session,
            title=command.metadata.title,
            description=command.metadata.description or command.metadata.caption,
            scheduled_publish_epoch=scheduled_epoch,
        )

    # --- status / reconcile -------------------------------------------------------------------

    def status(self, command: PublicationCommand, external_id: str) -> PublishResult:
        return self._result(self.transport.video_status(external_id=external_id))

    def reconcile(self, command: PublicationCommand) -> ReconcileResult:
        """Find a possibly-submitted post by client token; NOT_FOUND = safe to re-arm.

        Reconciliation is a lookup: it reports the post's current state without
        advancing the platform lifecycle (polling owns the advancement).
        """
        external_id = self.transport.find_post_by_token(command.client_token)
        if external_id is None:
            return ReconcileResult(found=False, result=None)
        return ReconcileResult(
            found=True,
            result=self._result(self.transport.peek_video_status(external_id=external_id)),
        )

    # --- metadata / readback --------------------------------------------------------------------

    def update_metadata(
        self, account_ref: str, external_id: str, metadata: PostMetadata
    ) -> PublishResult:
        support = self._support(CapabilityOperation.METADATA_UPDATE)
        if support not in _SUPPORTED:
            raise PolicyDenied(
                f"METADATA_UPDATE is {support.value} on the Facebook Page route",
                external_id=external_id,
            )
        self.transport.update_video(
            external_id=external_id, title=metadata.title, description=metadata.description
        )
        self.metadata_versions.setdefault(external_id, []).append(metadata)
        return self._result(self.transport.video_status(external_id=external_id))

    def readback(self, account_ref: str, external_id: str) -> PostReadback:
        fields = self.transport.get_video(external_id=external_id)
        published = fields.published
        # Declaration truth: only a mechanism the surface can SET and READ BACK may
        # appear as a visible disclosure. With the snapshot (AI_DISCLOSURE UNKNOWN)
        # this list is always empty and 'disclosures' stays an unverified field.
        disclosures = self._disclosures() if published else []
        unverified = ["privacy", "subtitles_present"]
        if self._support(CapabilityOperation.AI_DISCLOSURE) not in _SUPPORTED:
            unverified.append("disclosures")
        return PostReadback(
            external_id=external_id,
            visible=True if published else None,
            privacy=None,
            disclosures_visible=disclosures,
            subtitles_present=None,
            links=[fields.permalink] if fields.permalink else [],
            unverified_fields=unverified,
            provenance=Provenance.FAKE_SYNTHETIC,
        )

    # --- mapping ----------------------------------------------------------------------------------

    def _result(self, status: PlatformVideoStatus) -> PublishResult:
        try:
            state = _PHASE_STATE[status.phase]
        except KeyError:
            raise PolicyDenied(
                "transport reported an unknown video phase", phase=str(status.phase)
            ) from None
        published = state is ReleaseState.PUBLISHED_VERIFIED
        # Fields the documented surface can actually read back: description always,
        # title on the full-video route only (Reels carry a description alone).
        fields = ["description"] + (["title"] if status.route == "full" else [])
        return PublishResult(
            state=state,
            external_id=status.external_id,
            url=status.permalink,
            verified_fields=fields if published else [],
            unverified_fields=["ai_disclosure"] if published else [],
            provenance=Provenance.FAKE_SYNTHETIC,
        )

    def _failed(self, error_code: str) -> PublishResult:
        return PublishResult(
            state=ReleaseState.FAILED,
            error_code=error_code,
            transient=False,
            provenance=Provenance.FAKE_SYNTHETIC,
        )


__all__ = ["FacebookPageAdapter"]
