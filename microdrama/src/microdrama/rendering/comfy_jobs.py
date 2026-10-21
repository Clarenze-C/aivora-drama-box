"""ComfyUI job submission, progress and recovery adapter (T013, AT-04).

One ``render.shot`` job drives one paid ComfyUI prompt attempt through this service:

    reserve_attempt → submit (validate+bind → durable begin → queue_prompt → persist
    prompt_id) → poll (websocket progress → history/status → verified outputs → durable
    assets → settle)

Recovery rules this module is built on:

- The durable ``provider_operations`` row is the source of truth. ``prompt_id`` is
  persisted as ``external_id`` in the same transaction that records SUBMITTED, so a
  reconnect re-attaches to the running/completed prompt by id instead of re-rendering
  it. ``jobs.input`` carries the ``RenderRequest``; poll never needs in-memory state.
- A crash between ``queue_prompt`` and the persist leaves PENDING_SUBMIT with no
  prompt id. Past its deadline that is genuinely ambiguous (the prompt may be running),
  so the operation goes UNKNOWN and the caller receives ``NeedsReconciliation`` —
  never a blind resubmission.
- ``executed``/``progress`` websocket events only ever move the operation to RUNNING.
  Completion requires a history entry that is completed with outputs, and the fetched
  bytes must be a complete, probing, checksummed media file registered durably
  (``comfy_assets``) before SUCCEEDED is recorded.
- Every attempt is paid: a real ``BudgetService.reserve`` (worst case from the
  configured price) happens before dispatch, and terminal attempts settle their
  observed execution seconds — failures included. Failed attempts keep their charges;
  only a refusal that never dispatched releases its unused hold.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid5

from microdrama.budget import BudgetService, Reservation, ReservationState
from microdrama.config import Settings
from microdrama.contracts.cost import (
    BudgetReservationRequest,
    ExposureCeilings,
    OutputRef,
    PriceQuote,
    ProviderOperation,
    ProviderOperationResult,
    RenderRequest,
    UsageReceipt,
)
from microdrama.contracts.enums import (
    BudgetCategory,
    BudgetScopeKind,
    CostBasis,
    PriceSource,
    PriceUnit,
    Provenance,
    ProviderOperationState,
    QueueName,
    ReceiptKind,
)
from microdrama.contracts.errors import (
    Conflict,
    IdempotencyConflict,
    MicrodramaError,
    NeedsReconciliation,
    NotFound,
    ProviderError,
    SchemaInvalid,
    ServiceUnavailable,
    UnknownPrice,
    UnsupportedControl,
)
from microdrama.contracts.hashing import canonical_hash, sha256_hex
from microdrama.contracts.infra import Clock, IdGenerator, ObjectStore
from microdrama.contracts.media import AssetDescriptor
from microdrama.contracts.providers import ComfyClient, ComfyOutputFile, ComfyProgressEvent
from microdrama.core.provider_ops import begin, needs_reconcile, record_result
from microdrama.persistence.db import Database, Tx
from microdrama.rendering.comfy_assets import persist_output, prepare_output
from microdrama.rendering.comfy_graph import validate_api_graph
from microdrama.rendering.leases import RENDERING_NAMESPACE
from microdrama.rendering.workflows import (
    PRESET_TEMPLATES,
    WorkflowTemplate,
    bind_workflow,
)

#: Durable operation kind for one paid prompt submission (matches the frozen contract
#: example ``contracts.examples.provider_operation``).
RENDER_OPERATION_KIND = "comfy.queue_prompt"

#: The job type whose input model is ``RenderRequest`` (contracts.JOB_SPECS).
RENDER_JOB_TYPE = "render.shot"

MOCK_PRICE_AS_OF = datetime(2026, 10, 20, tzinfo=UTC)

_TERMINAL = frozenset(
    {
        ProviderOperationState.SUCCEEDED,
        ProviderOperationState.FAILED,
        ProviderOperationState.CANCELLED,
    }
)
_PROGRESS_EVENTS = frozenset({"executing", "progress"})
_DISPATCHABLE = frozenset({ProviderOperationState.PENDING_SUBMIT})


def mock_render_price() -> PriceQuote:
    """The OFFLINE_MOCK synthetic GPU-second price for one prompt attempt.

    Matches the T007 fake price table (GPU_SECOND = 250 micro-USD), the same synthetic
    source the pod lease uses, so fake billing and the mock reservation agree. The
    budget service refuses this price source outside OFFLINE_MOCK.
    """
    return PriceQuote(
        currency="USD",
        unit=PriceUnit.GPU_SECOND,
        unit_price_micro_usd=250,
        source=PriceSource.FAKE_SYNTHETIC,
        price_table_version="microdrama-mock-render-v1",
        as_of=MOCK_PRICE_AS_OF,
    )


@dataclass(frozen=True)
class ComfyRenderConfig:
    """Module-local configuration for ComfyUI attempts (T006 registries feed the price).

    ``price`` is the configured GPU-second quote for a prompt attempt; ``None`` means
    unknown and blocks every paid dispatch. ``required_media_kinds`` is what counts as a
    complete attempt: an attempt whose history lacks any of them is a failure, however
    many sampler steps executed.
    """

    price: PriceQuote | None
    timeout_ms: int = 600_000
    poll_after_ms: int = 1_000
    required_media_kinds: tuple[str, ...] = ("video",)

    @classmethod
    def for_mock(cls) -> ComfyRenderConfig:
        return cls(price=mock_render_price())


@dataclass(frozen=True)
class ComfyAttemptStatus:
    """What one attempt looks like right now. ``assets`` is empty until SUCCEEDED."""

    operation_id: UUID
    reservation_id: UUID
    state: ProviderOperationState
    prompt_id: str | None = None
    progress: ComfyProgressEvent | None = None
    assets: tuple[AssetDescriptor, ...] = ()
    error_code: str | None = None
    settled_micro_usd: int = 0
    replayed: bool = False


def render_client_token(semantic_key: str) -> str:
    """Deterministic idempotency token for one attempt (retries can never fork prompts)."""
    return f"md-comfy-{sha256_hex(semantic_key.encode('utf-8'))[:24]}"


def render_client_id(semantic_key: str) -> str:
    """Deterministic websocket client id, so reconnects are recognisable server-side."""
    return f"md-render-{sha256_hex(semantic_key.encode('utf-8'))[:12]}"


def render_id_for(semantic_key: str) -> UUID:
    """Deterministic render id: the same logical attempt always has the same identity."""
    return uuid5(RENDERING_NAMESPACE, f"render:{semantic_key}")


def _ceil_div(value: int, divisor: int) -> int:
    return -(-value // divisor)


class ComfyRenderService:
    """Drives paid ComfyUI prompt attempts against an injected ``ComfyClient``.

    The client is the T007 fake offline; a live HTTP/websocket adapter may only be wired
    in after T031 records rights/cost/quality evidence. No network code exists in this
    module.
    """

    def __init__(
        self,
        db: Database,
        budget: BudgetService,
        client: ComfyClient,
        clock: Clock,
        ids: IdGenerator,
        settings: Settings,
        config: ComfyRenderConfig,
        store: ObjectStore,
    ) -> None:
        self._db = db
        self._budget = budget
        self._client = client
        self._clock = clock
        self._ids = ids
        self._settings = settings
        self._config = config
        self._store = store
        self._id_lock = threading.Lock()

    # --- plumbing ---------------------------------------------------------------------

    def _now(self) -> datetime:
        now = self._clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise Conflict("clock must return a timezone-aware instant")
        return now

    @property
    def provenance(self) -> Provenance:
        if self._settings.is_offline_mock:
            return Provenance.FAKE_SYNTHETIC
        return Provenance.LIVE_PROVIDER

    def _load_row(self, operation_id: UUID) -> dict[str, Any]:
        with self._db.transaction(readonly=True) as tx:
            row = tx.fetchone("SELECT * FROM provider_operations WHERE id = %s", (operation_id,))
        if row is None:
            raise NotFound("comfy operation not found", operation_id=str(operation_id))
        return row

    @staticmethod
    def _op(row: Mapping[str, Any]) -> ProviderOperation:
        return ProviderOperation(
            operation_id=row["id"],
            provider=row["provider"],
            operation_kind=row["operation_kind"],
            client_token=row["client_token"],
            request_sha256=row["request_hash"],
            job_id=row["job_id"],
            reservation_id=row["reservation_id"],
            state=ProviderOperationState(row["state"]),
            external_id=row["external_id"],
            attempt=row["attempt"],
            submitted_at=row["submitted_at"],
            deadline_at=row["deadline_at"],
        )

    def _request_for(self, tx: Tx, job_id: UUID) -> RenderRequest:
        """The durable job input is the request of record for this attempt."""
        row = tx.fetchone("SELECT job_type, input FROM jobs WHERE id = %s", (job_id,))
        if row is None:
            raise NotFound("render job not found", job_id=str(job_id))
        if row["job_type"] != RENDER_JOB_TYPE:
            raise Conflict(
                "provider operation is not linked to a render.shot job",
                job_type=row["job_type"],
            )
        return RenderRequest.model_validate(row["input"])

    def _request_for_row(self, row: Mapping[str, Any]) -> RenderRequest:
        with self._db.transaction(readonly=True) as tx:
            return self._request_for(tx, row["job_id"])

    def _assets_for(self, op_row: Mapping[str, Any]) -> tuple[AssetDescriptor, ...]:
        with self._db.transaction(readonly=True) as tx:
            rows = tx.fetchall(
                "SELECT descriptor FROM assets WHERE generation_key = %s ORDER BY id",
                (op_row["request_hash"],),
            )
        return tuple(AssetDescriptor.model_validate(row["descriptor"]) for row in rows)

    def _settled_amount(self, reservation_id: UUID) -> int:
        with self._db.transaction(readonly=True) as tx:
            row = tx.fetchone(
                "SELECT COALESCE(SUM(amount_micro_usd), 0)::bigint AS amount FROM charges "
                "WHERE reservation_id = %s AND kind IN ('ACCRUAL', 'ADJUSTMENT', 'SETTLEMENT')",
                (reservation_id,),
            )
        assert row is not None
        return int(row["amount"])

    def _status(
        self,
        op_row: Mapping[str, Any],
        *,
        progress: ComfyProgressEvent | None = None,
        replayed: bool = False,
    ) -> ComfyAttemptStatus:
        return ComfyAttemptStatus(
            operation_id=op_row["id"],
            reservation_id=op_row["reservation_id"],
            state=ProviderOperationState(op_row["state"]),
            prompt_id=op_row["external_id"],
            progress=progress,
            assets=self._assets_for(op_row),
            error_code=(op_row["last_result"] or {}).get("error_code"),
            settled_micro_usd=self._settled_amount(op_row["reservation_id"]),
            replayed=replayed,
        )

    # --- reservation -------------------------------------------------------------------

    def reserve_attempt(self, *, episode_id: UUID, semantic_key: str) -> Reservation:
        """Hold the attempt's worst-case exposure before anything is dispatched.

        Follows the pod-lease house pattern (``leases._reserve_for_lease``): a typed
        ``UnknownPrice`` with no hold when the price is unknown, worst case from the
        configured GPU-second price bounded by the attempt timeout, idempotent on the
        attempt's semantic key with adoption of a committed hold after a crash.
        """
        if self._config.price is None:
            raise UnknownPrice(
                "render attempt price is unknown; paid dispatch blocked",
                operation_kind=RENDER_OPERATION_KIND,
            )
        request = self._reservation_request(episode_id=episode_id, semantic_key=semantic_key)
        try:
            return self._budget.reserve(request)
        except (IdempotencyConflict, Conflict):
            adopted = self._adopt_reservation(semantic_key)
            if adopted is None:
                raise
            return adopted

    def _reservation_request(
        self, *, episode_id: UUID, semantic_key: str
    ) -> BudgetReservationRequest:
        price = self._config.price
        assert price is not None  # reserve_attempt already refused None
        timeout = self._config.timeout_ms
        units = max(1, _ceil_div(timeout, 1000))
        return BudgetReservationRequest(
            request_id=uuid5(RENDERING_NAMESPACE, f"render-attempt:{semantic_key}"),
            semantic_key=semantic_key,
            scope_kind=BudgetScopeKind.EPISODE,
            episode_id=episode_id,
            season_id=None,
            category=BudgetCategory.GPU_GENERATION,
            queue=QueueName.PRODUCTION,
            job_id=None,
            provider=self._client.provider_id,
            operation_kind=RENDER_OPERATION_KIND,
            price=price,
            ceilings=ExposureCeilings(timeout_ms=timeout, max_units=units),
            worst_case_micro_usd=price.unit_price_micro_usd * units,
            is_shutdown_or_cleanup=False,
            expires_at=self._now() + timedelta(milliseconds=timeout),
        )

    def _adopt_reservation(self, semantic_key: str) -> Reservation | None:
        """Adopt a committed hold left by a crash between reserve and dispatch."""
        with self._db.transaction(readonly=True) as tx:
            row = tx.fetchone("SELECT * FROM reservations WHERE semantic_key = %s", (semantic_key,))
        if row is None:
            return None
        expected = self._reservation_request(
            episode_id=row["episode_id"], semantic_key=semantic_key
        )
        if (
            row["operation_kind"] != RENDER_OPERATION_KIND
            or row["provider"] != self._client.provider_id
            or row["state"] != ReservationState.ACTIVE.value
            or row["reserved_micro_usd"] != expected.worst_case_micro_usd
        ):
            return None
        return Reservation(
            id=row["id"],
            account_id=row["account_id"],
            category=BudgetCategory(row["category"]),
            semantic_key=row["semantic_key"],
            state=ReservationState(row["state"]),
            reserved_micro_usd=row["reserved_micro_usd"],
            accrued_micro_usd=row["accrued_micro_usd"],
            settled_micro_usd=row["settled_micro_usd"],
            replayed=True,  # the retry found its own committed hold: a replay, not a new one
        )

    def _verify_reservation(self, request: RenderRequest) -> None:
        """The attempt must already hold its own reservation for this exact attempt."""
        with self._db.transaction(readonly=True) as tx:
            row = tx.fetchone("SELECT * FROM reservations WHERE id = %s", (request.reservation_id,))
        if row is None:
            raise NotFound(
                "render attempt reservation not found; reserve before dispatch",
                reservation_id=str(request.reservation_id),
            )
        if row["state"] != ReservationState.ACTIVE.value:
            raise Conflict(
                "render attempt reservation is not ACTIVE",
                reservation_id=str(request.reservation_id),
                state=row["state"],
            )
        if (
            row["operation_kind"] != RENDER_OPERATION_KIND
            or row["provider"] != self._client.provider_id
            or row["semantic_key"] != request.semantic_key
            or row["episode_id"] != request.episode_id
        ):
            raise Conflict(
                "reservation does not belong to this render attempt",
                reservation_id=str(request.reservation_id),
                operation_kind=row["operation_kind"],
            )

    # --- submission ----------------------------------------------------------------------

    def _template_for(self, request: RenderRequest) -> WorkflowTemplate:
        template = PRESET_TEMPLATES.get(request.preset_id)
        if template is None:
            raise NotFound(
                "preset is not mapped to a workflow template (T014 registry)",
                preset_id=request.preset_id,
            )
        return template

    def submit(self, request: RenderRequest, *, job_id: UUID) -> ComfyAttemptStatus:
        """Validate, bind, durably begin and dispatch one paid prompt attempt.

        Replays are safe: if a durable operation already exists for this attempt's
        client token, nothing is ever re-queued — the call falls through to the
        recovery poll so a reconnect reattaches to the existing prompt (or replays its
        terminal outcome) instead of re-rendering it. Only the call that creates the
        operation dispatches; job-lease exclusivity (core T004) serializes workers, and
        ``begin``'s advisory locks arbitrate any residual race.
        """
        if self._config.price is None:
            raise UnknownPrice(
                "render attempt price is unknown; paid dispatch blocked",
                operation_kind=RENDER_OPERATION_KIND,
            )
        # Always: the durable job input is the request of record. A request that
        # differs from its job's input is refused even when an operation already
        # exists, so altered content can never silently ride the original attempt.
        self._verify_job(job_id, request)
        token = render_client_token(request.semantic_key)
        existing = self._find_by_token(token)
        if existing is not None:
            # A durable operation for this attempt already exists: reattach (or replay
            # its terminal outcome) without touching the provider queue. Its
            # reservation may legitimately be terminal already.
            return self.poll(existing["id"])
        try:
            template = self._template_for(request)
            bound = bind_workflow(template, request)
            missing = [
                kind
                for kind in self._config.required_media_kinds
                if kind not in template.produced_media_kinds
            ]
            if missing:
                raise UnsupportedControl(
                    "workflow template cannot produce the required output media kinds",
                    required=list(self._config.required_media_kinds),
                    produced=list(template.produced_media_kinds),
                )
            validate_api_graph(bound.graph, self._client.object_info())
            self._verify_reservation(request)
        except MicrodramaError:
            # A request that can never dispatch frees its own unused hold immediately;
            # it would otherwise sit as reserved exposure until expiry.
            self._release_attempt_hold_quietly(request)
            raise
        now = self._now()
        deadline = now + timedelta(milliseconds=self._config.timeout_ms)
        with self._db.transaction() as tx:
            operation = begin(
                tx,
                provider=self._client.provider_id,
                operation_kind=RENDER_OPERATION_KIND,
                client_token=token,
                request_hash=bound.request_hash,
                deadline_at=deadline,
                job_id=job_id,
                now=now,
                reservation_id=request.reservation_id,
                episode_id=request.episode_id,
            )

        if operation.state not in _DISPATCHABLE:
            # Lost a race to a concurrent begin: the winner owns the dispatch.
            return self.poll(operation.operation_id)

        try:
            prompt_id = self._client.queue_prompt(
                bound.graph, client_id=render_client_id(request.semantic_key)
            )
        except (SchemaInvalid, UnsupportedControl) as exc:
            # The server refused the graph before queueing anything: nothing was
            # dispatched and nothing was spent. The hold is released, the typed error
            # propagates, and the operation stays FAILED for this attempt's key.
            self._fail_without_dispatch(operation.operation_id, exc)
            raise
        except NeedsReconciliation:
            self._mark_unknown(operation.operation_id, now=self._now())
            raise
        with self._db.transaction() as tx:
            record_result(
                tx,
                operation.operation_id,
                self._result(
                    operation.operation_id,
                    ProviderOperationState.SUBMITTED,
                    external_id=prompt_id,
                ),
                now=self._now(),
            )
        return self.status(operation.operation_id)

    def _find_by_token(self, token: str) -> dict[str, Any] | None:
        with self._db.transaction(readonly=True) as tx:
            return tx.fetchone(
                "SELECT * FROM provider_operations WHERE provider = %s AND client_token = %s",
                (self._client.provider_id, token),
            )

    def _release_attempt_hold_quietly(self, request: RenderRequest) -> None:
        """Release this attempt's hold after a pre-dispatch refusal, when it is ours.

        Best effort and safe: a hold that already moved on (settled, released) or that
        belongs to a different operation kind (for example a pod lease) is never touched.
        """
        with self._db.transaction(readonly=True) as tx:
            row = tx.fetchone(
                "SELECT state, operation_kind, semantic_key FROM reservations WHERE id = %s",
                (request.reservation_id,),
            )
        if (
            row is None
            or row["state"] != ReservationState.ACTIVE.value
            or row["operation_kind"] != RENDER_OPERATION_KIND
            or row["semantic_key"] != request.semantic_key
        ):
            return
        try:
            self._budget.release(
                request.reservation_id,
                reason=f"comfy attempt {request.semantic_key} refused before dispatch",
            )
        except Conflict:
            pass

    def _verify_job(self, job_id: UUID, request: RenderRequest) -> None:
        with self._db.transaction(readonly=True) as tx:
            row = tx.fetchone("SELECT * FROM jobs WHERE id = %s", (job_id,))
        if row is None:
            raise NotFound("render job not found", job_id=str(job_id))
        if row["job_type"] != RENDER_JOB_TYPE:
            raise Conflict(
                "comfy attempts are submitted by render.shot jobs", job_type=row["job_type"]
            )
        if row["input_hash"] != canonical_hash(request):
            raise IdempotencyConflict(
                "the durable job input differs from the submitted request",
                job_id=str(job_id),
            )

    def _result(
        self,
        operation_id: UUID,
        state: ProviderOperationState,
        *,
        external_id: str | None = None,
        error_code: str | None = None,
        outputs: tuple[OutputRef, ...] = (),
    ) -> ProviderOperationResult:
        return ProviderOperationResult(
            operation_id=operation_id,
            state=state,
            external_id=external_id,
            outputs=list(outputs),
            error_code=error_code,
            provenance=self.provenance,
        )

    def _fail_without_dispatch(self, operation_id: UUID, exc: Exception) -> None:
        now = self._now()
        with self._db.transaction() as tx:
            row = tx.fetchone(
                "SELECT * FROM provider_operations WHERE id = %s FOR UPDATE", (operation_id,)
            )
            if row is None:
                raise NotFound("comfy operation not found", operation_id=str(operation_id))
            if row["state"] == ProviderOperationState.PENDING_SUBMIT.value:
                record_result(
                    tx,
                    operation_id,
                    self._result(
                        operation_id,
                        ProviderOperationState.FAILED,
                        error_code=getattr(exc, "code", "SUBMIT_REFUSED"),
                    ),
                    now=now,
                )
            reservation_id = row["reservation_id"]
        try:
            self._budget.release(
                reservation_id,
                reason=f"comfy attempt {operation_id} refused before dispatch",
            )
        except Conflict:
            pass  # already closed by an earlier attempt of the same recovery

    def _mark_unknown(self, operation_id: UUID, *, now: datetime) -> None:
        with self._db.transaction() as tx:
            row = tx.fetchone(
                "SELECT state FROM provider_operations WHERE id = %s FOR UPDATE",
                (operation_id,),
            )
            if row is None:
                raise NotFound("comfy operation not found", operation_id=str(operation_id))
            if row["state"] in (
                ProviderOperationState.PENDING_SUBMIT.value,
                ProviderOperationState.SUBMITTED.value,
                ProviderOperationState.RUNNING.value,
            ):
                record_result(
                    tx,
                    operation_id,
                    self._result(operation_id, ProviderOperationState.UNKNOWN),
                    now=now,
                )

    # --- polling / recovery ----------------------------------------------------------------

    def status(self, operation_id: UUID) -> ComfyAttemptStatus:
        """Pure durable read: no provider calls. For job status views and replays."""
        return self._status(self._load_row(operation_id))

    def poll(self, operation_id: UUID) -> ComfyAttemptStatus:
        """One monitoring step: websocket progress, then history/status recovery.

        Sampler progress and ``executed`` events only prove liveness (they move the
        operation to RUNNING at most). Completion requires a completed history entry
        with outputs whose fetched bytes verify, register and checksum durably. Any
        genuinely ambiguous observation is UNKNOWN plus ``NeedsReconciliation``.
        """
        row = self._load_row(operation_id)
        state = ProviderOperationState(row["state"])
        if state in _TERMINAL:
            self._settle_if_needed(row)
            return self._status(self._load_row(operation_id), replayed=True)
        if state is ProviderOperationState.UNKNOWN:
            raise NeedsReconciliation(
                "attempt outcome is unknown; reconcile before any resubmission",
                operation_id=str(operation_id),
            )

        now = self._now()
        prompt_id = row["external_id"]
        if prompt_id is None:
            # PENDING_SUBMIT: the dispatch has not (visibly) happened yet.
            if needs_reconcile(self._op(row), now=now):
                self._mark_unknown(operation_id, now=now)
                raise NeedsReconciliation(
                    "submission never completed and its deadline passed; the prompt may "
                    "still be running server-side",
                    operation_id=str(operation_id),
                )
            return self._status(row)

        events = self._client.progress_events(prompt_id)
        progress = events[-1] if events else None
        if state is ProviderOperationState.SUBMITTED and any(
            event.event in _PROGRESS_EVENTS for event in events
        ):
            with self._db.transaction() as tx:
                record_result(
                    tx,
                    operation_id,
                    self._result(
                        operation_id,
                        ProviderOperationState.RUNNING,
                        external_id=prompt_id,
                    ),
                    now=now,
                )
            row = self._load_row(operation_id)

        history = self._client.history(prompt_id)
        if history is None:
            if self._client.in_queue(prompt_id):
                if needs_reconcile(self._op(row), now=self._now()):
                    self._mark_unknown(operation_id, now=self._now())
                    raise NeedsReconciliation(
                        "attempt passed its deadline while queued/running",
                        operation_id=str(operation_id),
                    )
                return self._status(self._load_row(operation_id), progress=progress)
            self._mark_unknown(operation_id, now=self._now())
            raise NeedsReconciliation(
                "the server no longer knows this prompt (restart or eviction)",
                operation_id=str(operation_id),
                prompt_id=prompt_id,
            )

        if history.status_str == "error" or history.error_message:
            return self._finish_failure(
                row, error_code="COMFY_EXECUTION_ERROR", detail=history.error_message or ""
            )
        if not history.completed or not history.outputs:
            # executed events are not saved output; treat as a failed paid attempt
            return self._finish_failure(
                row, error_code="NO_COMPLETE_OUTPUT", detail="history has no complete outputs"
            )
        produced = {output.media_kind for output in history.outputs}
        missing = [kind for kind in self._config.required_media_kinds if kind not in produced]
        if missing:
            return self._finish_failure(
                row,
                error_code="MISSING_REQUIRED_OUTPUT",
                detail=f"required media kinds missing: {','.join(missing)}",
            )

        try:
            assets = self._collect_outputs(row, history.outputs)
        except (ProviderError, NotFound, ServiceUnavailable, Conflict) as exc:
            return self._finish_failure(
                row, error_code="OUTPUT_INCOMPLETE", detail=str(getattr(exc, "message", exc))
            )
        outputs = tuple(
            OutputRef(
                name=f"{output.node_id}:{output.filename}",
                media_type=output.media_kind,
                provider_ref=asset.object_key,
                sha256=asset.sha256,
                size_bytes=asset.size_bytes,
                complete=True,
            )
            for output, asset in zip(history.outputs, assets, strict=True)
        )
        with self._db.transaction() as tx:
            record_result(
                tx,
                operation_id,
                self._result(
                    operation_id,
                    ProviderOperationState.SUCCEEDED,
                    external_id=prompt_id,
                    outputs=outputs,
                ),
                now=self._now(),
            )
        self._settle_if_needed(self._load_row(operation_id))
        return self._status(self._load_row(operation_id))

    def _collect_outputs(
        self, row: Mapping[str, Any], outputs: list[ComfyOutputFile]
    ) -> tuple[AssetDescriptor, ...]:
        """Fetch+verify outside the transaction, then persist durably inside it."""
        request = self._request_for_row(row)
        prepared = [prepare_output(self._client, output) for output in outputs]
        now = self._now()
        assets: list[AssetDescriptor] = []
        with self._db.transaction() as tx:
            for item in prepared:
                assets.append(
                    persist_output(
                        tx,
                        self._store,
                        item,
                        request=request,
                        request_hash=row["request_hash"],
                        provenance=self.provenance,
                        now=now,
                    )
                )
        return tuple(assets)

    def _finish_failure(
        self, row: Mapping[str, Any], *, error_code: str, detail: str
    ) -> ComfyAttemptStatus:
        now = self._now()
        with self._db.transaction() as tx:
            current = tx.fetchone(
                "SELECT * FROM provider_operations WHERE id = %s FOR UPDATE", (row["id"],)
            )
            if current is None:
                raise NotFound("comfy operation not found", operation_id=str(row["id"]))
            if ProviderOperationState(current["state"]) not in _TERMINAL:
                record_result(
                    tx,
                    row["id"],
                    self._result(
                        row["id"],
                        ProviderOperationState.FAILED,
                        external_id=current["external_id"],
                        error_code=error_code,
                    ),
                    now=now,
                )
        # Failed attempts keep their charges: the execution seconds were spent.
        self._settle_if_needed(self._load_row(row["id"]))
        return self._status(self._load_row(row["id"]))

    # --- settlement -------------------------------------------------------------------------

    def _settle_if_needed(self, row: Mapping[str, Any]) -> int:
        """Settle a terminal attempt from durable state alone; idempotent.

        ``observed_at`` and the interval end both come from the operation row's own
        ``updated_at`` (fixed once terminal), so a crash between the terminal transition
        and this settlement replays byte-identically.
        """
        with self._db.transaction(readonly=True) as tx:
            reservation = tx.fetchone(
                "SELECT * FROM reservations WHERE id = %s", (row["reservation_id"],)
            )
        if reservation is None:
            raise NotFound(
                "render attempt reservation not found",
                reservation_id=str(row["reservation_id"]),
            )
        if reservation["state"] != ReservationState.ACTIVE.value:
            return self._settled_amount(row["reservation_id"])
        if row["submitted_at"] is None:
            # Never dispatched (validation refusal): release the unused hold.
            try:
                self._budget.release(
                    row["reservation_id"],
                    reason=f"comfy attempt {row['id']} never dispatched",
                )
            except Conflict:
                pass
            return 0
        price = self._config.price
        if price is None:
            raise UnknownPrice(
                "attempt settled without a configured price; cannot record its cost",
                operation_kind=RENDER_OPERATION_KIND,
            )
        interval_start = row["submitted_at"]
        interval_end = row["updated_at"]
        elapsed_ms = max(0, int((interval_end - interval_start).total_seconds() * 1000))
        units = _ceil_div(elapsed_ms, 1000)
        amount = price.unit_price_micro_usd * units
        mock = self._settings.is_offline_mock
        receipt = UsageReceipt(
            receipt_id=uuid5(RENDERING_NAMESPACE, f"render-settle:{row['id']}"),
            provider=row["provider"],
            provider_receipt_id=f"comfy-settle:{row['id']}",
            kind=ReceiptKind.SETTLEMENT,
            cost_basis=CostBasis.SYNTHETIC_FAKE if mock else CostBasis.PROVIDER_REPORTED,
            reservation_id=row["reservation_id"],
            episode_id=row["episode_id"],
            season_id=None,
            job_id=row["job_id"],
            category=BudgetCategory.GPU_GENERATION,
            amount_micro_usd=amount,
            currency="USD",
            units=units,
            unit=PriceUnit.GPU_SECOND,
            interval_start=interval_start,
            interval_end=interval_end,
            observed_at=interval_end,
            provenance=self.provenance,
        )
        self._budget.record_usage(receipt)
        return self._settled_amount(row["reservation_id"])


def build_comfy_render_service(
    db: Database,
    budget: BudgetService,
    client: ComfyClient,
    clock: Clock,
    ids: IdGenerator,
    settings: Settings,
    config: ComfyRenderConfig | None,
    store: ObjectStore,
) -> ComfyRenderService:
    """Composition factory for the integrator (route/job registration stays with them).

    Outside OFFLINE_MOCK a missing config means "no known price": the service refuses
    every paid dispatch rather than assuming one.
    """
    if config is None:
        if settings.is_offline_mock:
            config = ComfyRenderConfig.for_mock()
        else:
            config = ComfyRenderConfig(price=None)
    return ComfyRenderService(db, budget, client, clock, ids, settings, config, store)


__all__ = [
    "ComfyAttemptStatus",
    "ComfyRenderConfig",
    "ComfyRenderService",
    "MOCK_PRICE_AS_OF",
    "RENDER_JOB_TYPE",
    "RENDER_OPERATION_KIND",
    "build_comfy_render_service",
    "mock_render_price",
    "render_client_id",
    "render_client_token",
    "render_id_for",
]
