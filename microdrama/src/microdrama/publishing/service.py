"""Release execution (T020): submit, poll, reconcile and qualify publication slots.

The service drives one slot at a time through the provider-operation pattern the render
lane established: durable intent first (``provider_ops.begin`` committed BEFORE the
external call), then the adapter call, then the outcome transaction that moves slot,
operation and episode together. Publishing calls are unmetered (contract 1.6.0): free
platform API requests carry no fabricated budget hold, but every submit is still a
job-linked provider operation, so a crash between "sent" and "recorded" is always
recoverable by reconciliation and never by a blind repeat (AT-09).

Acceptance rules this module owns:

- **No release before approval.** A command must name the slot's own package (id + hash)
  and its approval event; the schedule already refused to create rows without them.
- **Media is immutable; metadata is versioned.** The command's asset hash must equal the
  slot's pinned hash and the stored object's actual hash. Metadata must be exactly the
  post's current version (the first submit creates it deterministically).
- **CTA dependencies wait for the actual target.** Every ``depends_on`` slot must be
  PUBLISHED_VERIFIED with a live external id before this slot may submit.
- **Crash after submit never blindly repeats.** Ambiguous outcomes land in
  NEEDS_RECONCILIATION; only a reconcile that proves the post absent re-arms the SAME
  client token for one more attempt (capped); a found post is adopted by external id.
- **Verification is readback-gated.** PUBLISHED_VERIFIED requires the provider readback
  to confirm visibility and every declared disclosure; an unknown readback leaves the
  slot processing with the gap recorded, never verified.
- **A missing required destination blocks full release.** The episode reaches
  PUBLISHED_VERIFIED only when every required slot is PUBLISHED_VERIFIED; HELD or failed
  required slots surface as blockers in the release view instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid5

from microdrama.contracts.enums import (
    CapabilityOperation,
    CapabilitySupport,
    EpisodeState,
    Platform,
    PrincipalKind,
    Provenance,
    ProviderOperationState,
    ReleaseState,
    SlotKind,
)
from microdrama.contracts.errors import (
    Conflict,
    InvalidTransition,
    NeedsReconciliation,
    NotFound,
    PolicyDenied,
    RateLimited,
    SchemaInvalid,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.infra import ObjectStore
from microdrama.contracts.primitives import ScheduleInstant
from microdrama.contracts.principals import Principal
from microdrama.contracts.providers import PublisherAdapter
from microdrama.contracts.release import (
    PostMetadata,
    PublicationCommand,
    PublishResult,
    ReleasePackage,
    ReleaseSlotKey,
)
from microdrama.contracts.states import RELEASE_TRANSITIONS
from microdrama.core import provider_ops
from microdrama.core.events import append_event
from microdrama.core.state_machine import transition_episode
from microdrama.persistence import Database
from microdrama.persistence.db import Tx, update_with_revision
from microdrama.publishing import metadata as meta
from microdrama.publishing.slots import POST_NAMESPACE

#: How long a submit may stay ambiguous before it must be reconciled.
PUBLISH_DEADLINE_MS = 300_000
#: Submissions per slot: the initial one plus re-arms after proven-absent reconciles.
MAX_SUBMIT_ATTEMPTS = 3
#: Readback fields a publication must be able to prove before it counts as verified.
REQUIRED_VERIFY_FIELDS = ("visibility", "disclosures")

SUPPORTED = (CapabilitySupport.SUPPORTED_DOCUMENTED, CapabilitySupport.SUPPORTED_TESTED)

_UPLOAD_OP_BY_KIND: dict[SlotKind, CapabilityOperation] = {
    SlotKind.FULL_EPISODE: CapabilityOperation.UPLOAD_FULL_VIDEO,
    SlotKind.PART: CapabilityOperation.UPLOAD_FULL_VIDEO,
    SlotKind.PROMO_CUT: CapabilityOperation.UPLOAD_SHORT,
    SlotKind.HOOK: CapabilityOperation.UPLOAD_SHORT,
}

SERVICE_PRINCIPAL = Principal(
    principal_id="svc:publishing-worker", kind=PrincipalKind.SERVICE_WORKER
)


class HeldSlot(PolicyDenied):
    """A destination blocker (capability/rights): the slot HELDs, the episode does not fail."""

    def __init__(self, blocker: str, reason: str) -> None:
        super().__init__(reason, blocker=blocker)
        self.blocker = blocker


def command_id_for(dedupe_key: str) -> UUID:
    """Deterministic command id: a rebuilt command hashes identically to the original."""
    return uuid5(POST_NAMESPACE, f"command:{dedupe_key}")


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchemaInvalid(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _supports_schedule(record: Any) -> bool:
    return record.support(CapabilityOperation.SCHEDULE) in SUPPORTED


class PublishingService:
    """Slot lifecycle over registered platform adapters (T021–T024 register theirs)."""

    def __init__(
        self,
        db: Database,
        clock: Any,
        ids: Any,
        adapters: Mapping[Platform, PublisherAdapter],
        store: ObjectStore,
        *,
        principal: Principal | None = None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._ids = ids
        self._adapters = dict(adapters)
        self._store = store
        self._principal = principal or SERVICE_PRINCIPAL

    # --- helpers -----------------------------------------------------------------------

    def _now(self) -> datetime:
        return _aware(self._clock.now(), "clock.now()")

    def _adapter(self, platform: Platform) -> PublisherAdapter:
        adapter = self._adapters.get(platform)
        if adapter is None:
            raise PolicyDenied(
                "no adapter registered for this platform; the destination cannot publish",
                platform=platform.value,
            )
        return adapter

    def _lock_post(self, tx: Tx, post_id: UUID) -> dict[str, Any]:
        row = tx.fetchone("SELECT * FROM platform_posts WHERE id = %s FOR UPDATE", (post_id,))
        if row is None:
            raise NotFound(f"platform post {post_id} not found")
        return row

    def _package_row(self, tx: Tx, package_id: UUID) -> dict[str, Any]:
        row = tx.fetchone("SELECT * FROM release_packages WHERE id = %s", (package_id,))
        if row is None:
            raise NotFound(f"release package {package_id} not found")
        return row

    def _declared_disclosures(self, tx: Tx, row: Mapping[str, Any]) -> list[str]:
        """The slot's declared disclosures, read from its own package body."""
        package = self._package_row(tx, row["release_package_id"])
        body = ReleasePackage.model_validate(package["body"])
        for plan in body.release_scope:
            if plan.slot.dedupe_key == row["dedupe_key"]:
                return [kind.value for kind in plan.disclosures]
        raise Conflict("slot plan missing from its own package", post_id=str(row["id"]))

    def _emit(
        self,
        tx: Tx,
        row: Mapping[str, Any],
        previous: ReleaseState,
        target: ReleaseState,
        now: datetime,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "from": previous.value,
            "to": target.value,
            "slot": row["release_slot"],
            "platform": row["platform"],
        }
        if detail:
            payload.update(detail)
        append_event(
            tx,
            aggregate_type="platform_post",
            aggregate_id=row["id"],
            event_type="platform_post.state_changed",
            payload=payload,
            correlation_id=row["episode_id"],
            occurred_at=now,
        )

    def _move(
        self,
        tx: Tx,
        row: Mapping[str, Any],
        path: list[ReleaseState],
        changes: Mapping[str, Any],
        *,
        now: datetime,
        detail: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Move a slot along ``path``; each real step is checked against RELEASE_TRANSITIONS.

        A path whose single step equals the current state is a no-op transition (the row
        still takes ``changes``), so re-polling a PROCESSING slot does not need a fake
        self-loop in the frozen state table.
        """
        current = ReleaseState(row["state"])
        steps = [step for step in path if step is not current]
        previous = current
        for step in steps:
            if step not in RELEASE_TRANSITIONS[current]:
                raise InvalidTransition(
                    f"slot {row['release_slot']} cannot move {current.value} -> {step.value}",
                    from_state=current.value,
                    to_state=step.value,
                )
            previous, current = current, step
        merged = dict(changes)
        merged["state"] = current.value
        if current is ReleaseState.PUBLISHED_VERIFIED and "verified_at" not in merged:
            merged["verified_at"] = now
        updated = update_with_revision(
            tx, "platform_posts", row["id"], int(row["revision"]), merged, now=now
        )
        if steps:
            self._emit(tx, row, previous, current, now, detail)
        return dict(updated)

    # --- command reconstruction ----------------------------------------------------------

    def _schedule_of(self, row: Mapping[str, Any]) -> ScheduleInstant:
        """Rebuild the slot's ScheduleInstant, resolving a DST-overlap fold from the UTC.

        ``None`` (the unambiguous default) is tried first so a rebuilt command hashes
        identically to the originally-validated one.
        """
        for fold in (None, 0, 1):
            try:
                return ScheduleInstant(
                    iana_zone=row["iana_zone"],
                    local_time=row["local_time"],
                    fold=fold,
                    utc_instant=row["scheduled_utc"],
                )
            except ValueError:
                continue
        raise Conflict(
            "stored schedule is not representable; operator review needed",
            post_id=str(row["id"]),
        )

    def _rebuild_command(
        self,
        tx: Tx,
        row: Mapping[str, Any],
        metadata: PostMetadata,
        metadata_version_id: UUID,
    ) -> PublicationCommand:
        package = self._package_row(tx, row["release_package_id"])
        slot = ReleaseSlotKey(
            series_id=row["series_id"],
            episode_id=row["episode_id"],
            part=row["part"],
            locale=row["locale"],
            platform=Platform(row["platform"]),
            account_ref=row["account_ref"],
            release_slot=row["release_slot"],
        )
        return PublicationCommand(
            command_id=command_id_for(row["dedupe_key"]),
            release_package_id=row["release_package_id"],
            release_package_hash=package["package_hash"],
            approval_event_id=row["approval_event_id"],
            slot=slot,
            slot_kind=SlotKind(row["slot_kind"]),
            asset_id=row["asset_id"],
            asset_sha256=row["asset_sha256"],
            metadata=metadata,
            metadata_version_id=metadata_version_id,
            schedule=self._schedule_of(row),
            capability_id=row["capability_id"],
            capability_version=row["capability_version"],
            client_token=row["client_token"],
        )

    def _command_for_post(self, tx: Tx, row: Mapping[str, Any]) -> PublicationCommand:
        current = meta.current_metadata(tx, row["id"])
        if current is None:
            raise Conflict("slot has no metadata version; it was never submitted")
        return self._rebuild_command(tx, row, current[1], current[0])

    # --- submit --------------------------------------------------------------------------

    def submit_slot(self, command: PublicationCommand, *, job_id: UUID) -> dict[str, Any]:
        """Validate, durably begin, submit and record one slot publication attempt."""
        if not isinstance(command, PublicationCommand):
            raise SchemaInvalid("a PublicationCommand is required")
        now = self._now()
        deadline = now + timedelta(milliseconds=PUBLISH_DEADLINE_MS)

        # Phase 1: validation + durable intent (committed before any external call).
        try:
            with self._db.transaction() as tx:
                row = self._validate_and_begin(
                    tx, command=command, job_id=job_id, now=now, deadline=deadline
                )
                media_path = row.pop("_media_path")
        except HeldSlot as held:
            return self._record_held(command, held)

        # Phase 2: the external call (no transaction held).
        adapter = self._adapter(Platform(row["platform"]))
        try:
            result = adapter.submit(command, media_path)
        except RateLimited as limited:
            retry_ms = limited.details.get("retry_after_ms")
            return self._record_rate_limited(row, int(retry_ms) if retry_ms else 60_000, now=now)
        except NeedsReconciliation:
            return self._record_needs_reconciliation(row, now=now)

        # Phase 3: the outcome transaction.
        with self._db.transaction() as tx:
            fresh = self._lock_post(tx, row["id"])
            return self._record_submit_result(tx, fresh, result, now=now)

    def _validate_and_begin(
        self,
        tx: Tx,
        *,
        command: PublicationCommand,
        job_id: UUID,
        now: datetime,
        deadline: datetime,
    ) -> dict[str, Any]:
        row = self._lock_post_by_key(tx, command)
        state = ReleaseState(row["state"])
        if state not in (ReleaseState.SCHEDULED, ReleaseState.RETRY_WAIT, ReleaseState.SUBMITTED):
            raise Conflict(f"slot is {state.value}; it cannot be submitted", state=state.value)
        episode = tx.fetchone("SELECT state FROM episodes WHERE id = %s", (row["episode_id"],))
        # Optional slots (promo cuts, hooks) keep publishing through PUBLISHED_VERIFIED and
        # MANAGED — the content waterfall runs for weeks after the hub post. The gate
        # exists to stop slots for episodes still in production or already failed.
        if episode is None or EpisodeState(episode["state"]) not in (
            EpisodeState.SCHEDULED,
            EpisodeState.PUBLISHING,
            EpisodeState.PUBLISHED_VERIFIED,
            EpisodeState.MANAGED,
        ):
            raise PolicyDenied(
                "episode is not in its publication window",
                episode_state=episode["state"] if episode else "missing",
            )
        package = self._package_row(tx, row["release_package_id"])
        if package["id"] != command.release_package_id or package["package_hash"] != (
            command.release_package_hash
        ):
            raise Conflict("command does not name the slot's approved package")
        if package["status"] != "APPROVED" or package["approval_event_id"] is None:
            raise PolicyDenied("package is not approval-bound; refusing to publish")
        if row["approval_event_id"] != command.approval_event_id:
            raise Conflict("command approval event does not match the slot")
        if row["asset_id"] != command.asset_id or row["asset_sha256"] != command.asset_sha256:
            raise Conflict(
                "command media does not match the slot's pinned asset (media is immutable)"
            )
        if row["client_token"] != command.client_token:
            raise Conflict("command client token does not match the slot")
        if int(row["attempt"]) >= MAX_SUBMIT_ATTEMPTS:
            raise PolicyDenied(
                "submit attempt cap reached for this slot", attempts=int(row["attempt"])
            )

        # Metadata: the command must carry exactly the current version; a first submit
        # creates version 1 at the deterministic id the command names.
        current = meta.current_metadata(tx, row["id"])
        if current is None:
            expected = meta.initial_metadata_version_id(row["dedupe_key"])
            if command.metadata_version_id != expected:
                raise Conflict(
                    "first submit must name the deterministic initial metadata version",
                    expected=str(expected),
                )
            meta.create_version(
                tx,
                post_id=row["id"],
                version_id=command.metadata_version_id,
                metadata=command.metadata,
                policy_hash=package["management_policy_hash"],
                now=now,
            )
        else:
            meta.require_current(tx, row["id"], command.metadata_version_id)

        self._check_dependencies(tx, row)
        self._check_capability(tx, row, now=now)

        asset = tx.fetchone("SELECT object_key FROM assets WHERE id = %s", (row["asset_id"],))
        if asset is None:
            raise NotFound(f"slot asset {row['asset_id']} not found")
        if not self._store.verify(asset["object_key"], row["asset_sha256"]):
            raise Conflict(
                "stored media no longer matches the pinned asset hash; refusing to publish"
            )

        adapter = self._adapter(Platform(row["platform"]))
        op = provider_ops.begin(
            tx,
            provider=adapter.provider_route,
            operation_kind="publish.submit_slot",
            client_token=row["client_token"],
            request_hash=canonical_hash(command),
            deadline_at=deadline,
            job_id=job_id,
            now=now,
            episode_id=row["episode_id"],
        )
        if row["provider_operation_id"] is None:
            # Persist the link so poll/reconcile find the operation through the slot.
            # The metadata creation above may have bumped the revision: re-read it.
            fresh_rev = tx.fetchone(
                "SELECT revision FROM platform_posts WHERE id = %s", (row["id"],)
            )["revision"]
            updated = update_with_revision(
                tx,
                "platform_posts",
                row["id"],
                int(fresh_rev),
                {"provider_operation_id": op.operation_id},
                now=now,
            )
            row = {**row, **dict(updated)}
        row = dict(row)
        row["_media_path"] = self._store.local_path(asset["object_key"])
        return row

    def _lock_post_by_key(self, tx: Tx, command: PublicationCommand) -> dict[str, Any]:
        row = tx.fetchone(
            "SELECT * FROM platform_posts WHERE dedupe_key = %s FOR UPDATE",
            (command.slot.dedupe_key,),
        )
        if row is None:
            raise NotFound(
                "no scheduled slot for this command's key",
                dedupe_key=command.slot.dedupe_key,
            )
        return row

    def _check_capability(self, tx: Tx, row: Mapping[str, Any], *, now: datetime) -> None:
        """Destination checks whose failure HELDs the slot (capability/rights blockers)."""
        platform = Platform(row["platform"])
        adapter = self._adapter(platform)
        record = adapter.capability(row["account_ref"])
        if record.capability_id != row["capability_id"] or record.version != int(
            row["capability_version"]
        ):
            raise HeldSlot("CAPABILITY_STALE", "capability record changed since scheduling")
        if not record.enabled:
            raise HeldSlot("CAPABILITY_UNAVAILABLE", "capability is not enabled")
        operation = _UPLOAD_OP_BY_KIND[SlotKind(row["slot_kind"])]
        support = record.support(operation)
        if support not in SUPPORTED:
            raise HeldSlot(
                "CAPABILITY_UNAVAILABLE",
                f"{operation.value} is {support.value} on this destination",
            )
        declared = self._declared_disclosures(tx, row)
        missing = [kind for kind in declared if kind not in record.supported_disclosures]
        if missing:
            raise HeldSlot(
                "UNSUPPORTED_DISCLOSURE",
                "destination does not support a declared disclosure",
            )
        if row["scheduled_utc"].astimezone(UTC) > now and not _supports_schedule(record):
            raise PolicyDenied(
                "schedule window has not opened and the destination cannot schedule ahead",
                scheduled_utc=row["scheduled_utc"].isoformat(),
            )

    def _check_dependencies(self, tx: Tx, row: Mapping[str, Any]) -> None:
        """CTA dependencies wait for the actual target: verified posts with external ids."""
        for dep_key in list(row["depends_on"] or []):
            dep = tx.fetchone(
                "SELECT state, external_id, release_slot FROM platform_posts WHERE dedupe_key = %s",
                (dep_key,),
            )
            if dep is None:
                raise PolicyDenied("dependency slot does not exist", dependency=dep_key)
            if dep["state"] != ReleaseState.PUBLISHED_VERIFIED.value or dep["external_id"] is None:
                raise PolicyDenied(
                    "dependency is not PUBLISHED_VERIFIED yet; this slot waits",
                    dependency_slot=dep["release_slot"],
                    dependency_state=dep["state"],
                )

    # --- submit outcomes -----------------------------------------------------------------

    def _record_held(self, command: PublicationCommand, held: HeldSlot) -> dict[str, Any]:
        with self._db.transaction() as tx:
            row = self._lock_post_by_key(tx, command)
            if ReleaseState(row["state"]) is ReleaseState.HELD:
                return dict(row)  # a replay of the same held submit
            return self._move(
                tx,
                row,
                [ReleaseState.HELD],
                {"blocker": held.blocker},
                now=self._now(),
                detail={"blocker": held.blocker},
            )

    def _record_rate_limited(
        self, row: Mapping[str, Any], retry_ms: int, *, now: datetime
    ) -> dict[str, Any]:
        with self._db.transaction() as tx:
            fresh = self._lock_post(tx, row["id"])
            self._finish_operation(
                tx,
                fresh,
                state="FAILED",
                error_code="RATE_LIMITED",
                transient=True,
                retry_after_ms=retry_ms,
                now=now,
            )
            start = ReleaseState(fresh["state"])
            path = (
                [ReleaseState.SUBMITTED, ReleaseState.RETRY_WAIT]
                if start is ReleaseState.SCHEDULED
                else [ReleaseState.RETRY_WAIT]
            )
            return self._move(
                tx,
                fresh,
                path,
                {
                    "last_error_code": "RATE_LIMITED",
                    "attempt": int(fresh["attempt"]) + 1,
                },
                now=now,
            )

    def _record_needs_reconciliation(
        self, row: Mapping[str, Any], *, now: datetime
    ) -> dict[str, Any]:
        with self._db.transaction() as tx:
            fresh = self._lock_post(tx, row["id"])
            self._finish_operation(tx, fresh, state="UNKNOWN", now=now)
            start = ReleaseState(fresh["state"])
            path = (
                [ReleaseState.SUBMITTED, ReleaseState.NEEDS_RECONCILIATION]
                if start is ReleaseState.SCHEDULED
                else [ReleaseState.NEEDS_RECONCILIATION]
            )
            return self._move(tx, fresh, path, {"attempt": int(fresh["attempt"]) + 1}, now=now)

    def _record_submit_result(
        self, tx: Tx, row: Mapping[str, Any], result: PublishResult, *, now: datetime
    ) -> dict[str, Any]:
        target = result.state
        if target is ReleaseState.FAILED:
            self._finish_operation(
                tx,
                row,
                state="FAILED",
                error_code=result.error_code or "PROVIDER_FAILED",
                transient=result.transient,
                retry_after_ms=result.retry_after_ms,
                external_id=result.external_id,
                now=now,
            )
            start = ReleaseState(row["state"])
            path = (
                [ReleaseState.SUBMITTED, ReleaseState.FAILED]
                if start is ReleaseState.SCHEDULED
                else [ReleaseState.FAILED]
            )
            return self._move(
                tx,
                row,
                path,
                {"last_error_code": result.error_code, "attempt": int(row["attempt"]) + 1},
                now=now,
            )
        if target not in (ReleaseState.SUBMITTED, ReleaseState.PROCESSING):
            raise Conflict(
                f"adapter reported unsupported submit state {target.value}", state=target.value
            )
        self._finish_operation(tx, row, state="SUBMITTED", external_id=result.external_id, now=now)
        path = [ReleaseState.SUBMITTED]
        if target is ReleaseState.PROCESSING:
            path.append(ReleaseState.PROCESSING)
        changes: dict[str, Any] = {
            "attempt": int(row["attempt"]) + 1,
            "external_id": result.external_id,
            "submitted_at": row["submitted_at"] or now,
        }
        updated = self._move(tx, row, path, changes, now=now)
        self._mark_publishing(tx, row["episode_id"], now=now)
        return updated

    def _mark_publishing(self, tx: Tx, episode_id: UUID, *, now: datetime) -> None:
        episode = tx.fetchone(
            "SELECT state, revision FROM episodes WHERE id = %s FOR UPDATE", (episode_id,)
        )
        if episode is not None and EpisodeState(episode["state"]) is EpisodeState.SCHEDULED:
            transition_episode(
                tx,
                episode_id=episode_id,
                to=EpisodeState.PUBLISHING,
                expected_revision=int(episode["revision"]),
                actor=self._principal,
                now=now,
                correlation_id=episode_id,
            )

    # --- poll ---------------------------------------------------------------------------

    def poll_status(self, post_id: UUID) -> dict[str, Any]:
        """Provider status + readback verification; completes the episode when due."""
        now = self._now()
        with self._db.transaction() as tx:
            row = self._lock_post(tx, post_id)
            state = ReleaseState(row["state"])
            if state not in (ReleaseState.SUBMITTED, ReleaseState.PROCESSING):
                raise Conflict(f"slot is {state.value}; nothing to poll")
            if row["external_id"] is None:
                raise Conflict("slot has no external id; reconcile it first")
            command = self._command_for_post(tx, row)
            platform = Platform(row["platform"])
            external_id = row["external_id"]
        result = self._adapter(platform).status(command, external_id)
        # A provider that announces completion must prove it: readback happens while no
        # transaction is held (it is an external call), then one outcome tx applies it.
        readback = None
        if result.state is ReleaseState.PUBLISHED_VERIFIED:
            readback = self._adapter(platform).readback(row["account_ref"], external_id)
        with self._db.transaction() as tx:
            fresh = self._lock_post(tx, post_id)
            if result.state is ReleaseState.PROCESSING:
                return self._move(tx, fresh, [ReleaseState.PROCESSING], {}, now=now)
            if result.state is ReleaseState.PUBLISHED_VERIFIED:
                assert readback is not None  # guarded above
                return self._apply_verification(tx, fresh, command, result, readback, now=now)
            if result.state is ReleaseState.FAILED:
                self._finish_operation(
                    tx,
                    fresh,
                    state="FAILED",
                    error_code=result.error_code or "PROVIDER_FAILED",
                    transient=result.transient,
                    now=now,
                )
                return self._move(
                    tx,
                    fresh,
                    [ReleaseState.FAILED],
                    {"last_error_code": result.error_code},
                    now=now,
                )
            raise Conflict(
                f"adapter reported unsupported status state {result.state.value}",
                state=result.state.value,
            )

    def _verify(
        self,
        row: Mapping[str, Any],
        command: PublicationCommand,
        result: PublishResult,
    ) -> Any:
        """External half of verification: the readback call (never inside a transaction)."""
        external = result.external_id or row["external_id"]
        return self._adapter(Platform(row["platform"])).readback(row["account_ref"], external)

    def _apply_verification(
        self,
        tx: Tx,
        row: Mapping[str, Any],
        command: PublicationCommand,
        result: PublishResult,
        readback: Any,
        *,
        now: datetime,
    ) -> dict[str, Any]:
        if not self._readback_verifies(readback, command):
            # An unknown readback is a coverage gap, never a verification (AT-09).
            return self._move(
                tx,
                row,
                [ReleaseState.PROCESSING],
                {"unverified_fields": list(readback.unverified_fields)},
                now=now,
                detail={"readback_unverified": list(readback.unverified_fields)},
            )
        self._finish_operation(
            tx, row, state="SUCCEEDED", external_id=readback.external_id, now=now
        )
        start = ReleaseState(row["state"])
        path = (
            [ReleaseState.PROCESSING, ReleaseState.PUBLISHED_VERIFIED]
            if start is ReleaseState.SUBMITTED
            else [ReleaseState.PUBLISHED_VERIFIED]
        )
        updated = self._move(
            tx,
            row,
            path,
            {
                "external_id": readback.external_id,
                "verified_fields": list(REQUIRED_VERIFY_FIELDS),
                "unverified_fields": list(readback.unverified_fields),
                "url": result.url,
            },
            now=now,
        )
        self._maybe_complete_episode(tx, row["episode_id"], now=now)
        return updated

    def _readback_verifies(self, readback: Any, command: PublicationCommand) -> bool:
        if readback.visible is not True:
            return False
        declared = {kind.value for kind in command.metadata.disclosures}
        if not declared <= set(readback.disclosures_visible):
            return False
        return not (set(REQUIRED_VERIFY_FIELDS) & set(readback.unverified_fields))

    def _maybe_complete_episode(self, tx: Tx, episode_id: UUID, *, now: datetime) -> None:
        episode = tx.fetchone(
            "SELECT state, revision FROM episodes WHERE id = %s FOR UPDATE", (episode_id,)
        )
        if episode is None:
            return
        state = EpisodeState(episode["state"])
        if state is EpisodeState.SCHEDULED:
            # A slot adopted+verified through reconciliation may complete the release
            # without ever passing through a recorded submit; the episode still walks
            # the frozen SCHEDULED -> PUBLISHING -> PUBLISHED_VERIFIED path.
            transition_episode(
                tx,
                episode_id=episode_id,
                to=EpisodeState.PUBLISHING,
                expected_revision=int(episode["revision"]),
                actor=self._principal,
                now=now,
                correlation_id=episode_id,
            )
            episode = tx.fetchone(
                "SELECT state, revision FROM episodes WHERE id = %s", (episode_id,)
            )
            state = EpisodeState(episode["state"])
        if state is not EpisodeState.PUBLISHING:
            return
        open_required = tx.fetchval(
            "SELECT count(*) FROM platform_posts WHERE episode_id = %s AND required "
            "AND state <> 'PUBLISHED_VERIFIED'",
            (episode_id,),
        )
        if int(open_required or 0) > 0:
            return
        transition_episode(
            tx,
            episode_id=episode_id,
            to=EpisodeState.PUBLISHED_VERIFIED,
            expected_revision=int(episode["revision"]),
            actor=self._principal,
            now=now,
            correlation_id=episode_id,
        )

    # --- reconcile -----------------------------------------------------------------------

    def reconcile_slot(self, post_id: UUID) -> dict[str, Any]:
        """Resolve an ambiguous submit: adopt a found post, re-arm only a proven-absent one."""
        now = self._now()
        with self._db.transaction() as tx:
            row = self._lock_post(tx, post_id)
            state = ReleaseState(row["state"])
            if state not in (
                ReleaseState.NEEDS_RECONCILIATION,
                ReleaseState.SUBMITTED,
                ReleaseState.PROCESSING,
            ):
                raise Conflict(f"slot is {state.value}; nothing to reconcile")
            op_row = self._operation_row(tx, row)
            if op_row is not None and not provider_ops.needs_reconcile(
                _as_operation(op_row), now=now
            ):
                raise Conflict("operation is not due for reconciliation", state=op_row["state"])
            command = self._command_for_post(tx, row)
            platform = Platform(row["platform"])
        outcome = self._adapter(platform).reconcile(command)
        # A found post that claims completion needs its readback proof fetched outside
        # the transaction, exactly like the poll path.
        readback = None
        if (
            outcome.found
            and outcome.result is not None
            and (outcome.result.state is ReleaseState.PUBLISHED_VERIFIED)
        ):
            readback = self._verify(row, command, outcome.result)
        with self._db.transaction() as tx:
            fresh = self._lock_post(tx, post_id)
            if outcome.found and outcome.result is not None:
                return self._adopt_found(tx, fresh, command, outcome.result, readback, now=now)
            return self._rearm_absent(tx, fresh, now=now)

    def _adopt_found(
        self,
        tx: Tx,
        row: Mapping[str, Any],
        command: PublicationCommand,
        result: PublishResult,
        readback: Any | None,
        *,
        now: datetime,
    ) -> dict[str, Any]:
        external = result.external_id
        if external is None:
            raise Conflict("reconcile found a post without an external id")
        self._finish_operation(
            tx, row, state="SUBMITTED", external_id=external, now=now, force_state=True
        )
        moved = self._move(
            tx,
            row,
            [ReleaseState.SUBMITTED],
            {"external_id": external, "submitted_at": row["submitted_at"] or now},
            now=now,
        )
        if result.state is ReleaseState.PUBLISHED_VERIFIED:
            assert readback is not None  # fetched by the caller outside the transaction
            return self._apply_verification(tx, moved, command, result, readback, now=now)
        target = (
            ReleaseState.PROCESSING
            if result.state is ReleaseState.PROCESSING
            else ReleaseState.SUBMITTED
        )
        return self._move(tx, moved, [target], {}, now=now)

    def _rearm_absent(self, tx: Tx, row: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
        op_row = self._operation_row(tx, row)
        if op_row is None:
            raise Conflict("slot has no provider operation to reconcile")
        self._finish_operation(tx, row, state="NOT_FOUND", now=now, force_state=True)
        provider_ops.resubmit_allowed(
            tx,
            op_row["id"],
            now=now,
            deadline_at=now + timedelta(milliseconds=PUBLISH_DEADLINE_MS),
        )
        if int(row["attempt"]) >= MAX_SUBMIT_ATTEMPTS:
            return self._move(
                tx,
                row,
                [ReleaseState.FAILED],
                {"last_error_code": "ATTEMPT_CAP_REACHED"},
                now=now,
            )
        return self._move(
            tx,
            row,
            [ReleaseState.SUBMITTED],
            {"attempt": int(row["attempt"]) + 1},
            now=now,
            detail={"reconciled": "absent", "rearmed": True},
        )

    # --- cancellation and holds -----------------------------------------------------------

    def cancel_slot(self, post_id: UUID, *, reason: str) -> dict[str, Any]:
        """Rollback state: stop a slot that has not reached the provider."""
        now = self._now()
        with self._db.transaction() as tx:
            row = self._lock_post(tx, post_id)
            if row["external_id"] is not None:
                raise PolicyDenied(
                    "post is live at the provider; use management actions, not cancel",
                    external_id=row["external_id"],
                )
            state = ReleaseState(row["state"])
            if state in (ReleaseState.PUBLISHED_VERIFIED, ReleaseState.FAILED):
                raise Conflict(f"slot is terminal ({state.value}); it cannot be cancelled")
            return self._move(tx, row, [ReleaseState.CANCELLED], {"blocker": reason}, now=now)

    def retry_held_slot(self, post_id: UUID) -> dict[str, Any]:
        """HELD -> SCHEDULED, but only when the destination checks now pass."""
        now = self._now()
        with self._db.transaction() as tx:
            row = self._lock_post(tx, post_id)
            if ReleaseState(row["state"]) is not ReleaseState.HELD:
                raise Conflict("only a HELD slot can be retried")
            self._check_capability(tx, row, now=now)  # HeldSlot while the blocker stands
            return self._move(tx, row, [ReleaseState.SCHEDULED], {"blocker": None}, now=now)

    # --- views ---------------------------------------------------------------------------

    def release_view(self, episode_id: UUID) -> dict[str, Any]:
        """Full-release qualification: per-slot state, readiness and blockers."""
        with self._db.transaction(readonly=True) as tx:
            episode = tx.fetchone(
                "SELECT state, outcome FROM episodes WHERE id = %s", (episode_id,)
            )
            if episode is None:
                raise NotFound(f"episode {episode_id} not found")
            rows = tx.fetchall(
                "SELECT id, release_slot, platform, required, state, blocker, external_id, "
                "last_error_code, depends_on FROM platform_posts WHERE episode_id = %s "
                "ORDER BY created_at, id",
                (episode_id,),
            )
        slots = [
            {
                "post_id": row["id"],
                "slot": row["release_slot"],
                "platform": row["platform"],
                "required": row["required"],
                "state": row["state"],
                "blocker": row["blocker"],
                "external_id": row["external_id"],
                "last_error_code": row["last_error_code"],
                "depends_on": row["depends_on"],
            }
            for row in rows
        ]
        required = [slot for slot in slots if slot["required"]]
        blockers = [
            {
                "slot": slot["slot"],
                "state": slot["state"],
                "blocker": slot["blocker"] or slot["last_error_code"],
            }
            for slot in required
            if slot["state"] != ReleaseState.PUBLISHED_VERIFIED.value
        ]
        return {
            "episode_id": str(episode_id),
            "episode_state": episode["state"],
            "episode_outcome": episode["outcome"],
            "slots": slots,
            "full_release_ready": bool(required) and not blockers,
            "blockers": blockers,
        }

    # --- provider-operation plumbing -------------------------------------------------------

    def _operation_row(self, tx: Tx, row: Mapping[str, Any]) -> dict[str, Any] | None:
        if row["provider_operation_id"] is None:
            return None
        return tx.fetchone(
            "SELECT * FROM provider_operations WHERE id = %s", (row["provider_operation_id"],)
        )

    def _finish_operation(
        self,
        tx: Tx,
        row: Mapping[str, Any],
        *,
        state: str,
        now: datetime,
        external_id: str | None = None,
        error_code: str | None = None,
        transient: bool = False,
        retry_after_ms: int | None = None,
        force_state: bool = False,
    ) -> None:
        """Record a submit outcome on the slot's provider operation, tolerating replays.

        A recording that would repeat the state the operation already has (a replayed
        poll, a second rate limit) is a no-op unless ``force_state``; only genuinely
        illegal moves raise.
        """
        from microdrama.contracts.cost import ProviderOperationResult

        op_row = self._operation_row(tx, row)
        if op_row is None:
            return
        current = ProviderOperationState(op_row["state"])
        target = ProviderOperationState(state)
        if current is target:
            return  # already recorded (a replay, or an adoption of the same state)
        if target is ProviderOperationState.FAILED and error_code is None:
            error_code = "PROVIDER_FAILED"
        result = ProviderOperationResult(
            operation_id=op_row["id"],
            state=target,
            external_id=external_id,
            error_code=error_code,
            transient=transient,
            retry_after_ms=retry_after_ms,
            provenance=Provenance.FAKE_SYNTHETIC,
        )
        try:
            provider_ops.record_result(tx, op_row["id"], result, now=now)
        except InvalidTransition:
            if force_state:
                raise
            # Already moved past this recording (a replayed outcome); the slot state
            # below remains the source of truth.


def _as_operation(row: Mapping[str, Any]):
    from microdrama.contracts.cost import ProviderOperation

    return ProviderOperation(
        operation_id=row["id"],
        provider=row["provider"],
        operation_kind=row["operation_kind"],
        client_token=row["client_token"],
        request_sha256=row["request_hash"],
        state=ProviderOperationState(row["state"]),
        attempt=row["attempt"],
        deadline_at=row["deadline_at"],
        external_id=row["external_id"],
    )
