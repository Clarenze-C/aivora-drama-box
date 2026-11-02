"""Timed GPU leases: atomic claim, acquisition, cost accrual, shutdown and transfer (T012).

Lifecycle (SPEC §8): one DB transaction claims the lease and its budget hold; the pod is
acquired or reconciled by ``client_token``; every paid interval is attributed exactly once
through ``BudgetService.record_gpu_interval`` with a declared basis (COLD_START / RUNNING /
IDLE / SHUTDOWN); shutdown verifies compute stopped and settles the hold.

Durability rules this module is built on:

- The ``pod_leases`` row is the source of truth. A crash between the budget reservation and
  the lease insert is recovered by *adoption* (an unclaimed reservation with this module's
  operation kind and semantic key) or by the janitor's unbound-hold sweep. No recovery path
  depends on an in-process ``finally``.
- Create timeouts reconcile by token before any retry; the create token is derived from the
  claim's semantic key, so retries and adoption can never create a second pod.
- The pilot rule (SPEC §6) is structural: the database allows exactly one lease in
  CLAIMED/ACTIVE/TRANSFERRING at a time, mapped here to a typed ``PolicyDenied``.
- No GPU may run during a human wait (SPEC §5 rule 8): ``human_wait_guard`` refuses the
  episode transition while a live lease exists, and ``stop_for_human_wait`` performs the
  shutdown before the transition is attempted. The janitor is the crash backstop.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from microdrama.budget import BudgetService, Reservation, ReservationState
from microdrama.config import Settings
from microdrama.contracts.cost import (
    BudgetReservationRequest,
    ExposureCeilings,
    PriceQuote,
    UsageReceipt,
)
from microdrama.contracts.cost import (
    PodLease as PodLeaseContract,
)
from microdrama.contracts.enums import (
    BudgetCategory,
    BudgetScopeKind,
    CostBasis,
    EpisodeState,
    LeaseState,
    PodState,
    PriceSource,
    PriceUnit,
    Provenance,
    QueueName,
    ReceiptKind,
)
from microdrama.contracts.errors import (
    Conflict,
    DuplicateSemanticKey,
    IdempotencyConflict,
    InvalidTransition,
    MicrodramaError,
    NotFound,
    PolicyDenied,
)
from microdrama.contracts.events import DomainEvent
from microdrama.contracts.hashing import sha256_hex
from microdrama.contracts.infra import Clock, IdGenerator
from microdrama.contracts.providers import PodInfo
from microdrama.core.events import append_event, list_events
from microdrama.persistence.db import Database, Tx, update_with_revision
from microdrama.rendering.finality import (
    LeaseBillingFinality,
    LeaseSettlement,
    check_finality_pairing,
)
from microdrama.rendering.pods import (
    LEASE_OPERATION_KIND,
    STOP_OPERATION_KIND,
    PodManager,
    PodSpec,
    check_acquisition_filters,
)

RENDERING_NAMESPACE = uuid5(NAMESPACE_URL, "https://microdrama.invalid/rendering/v1")
LIVE_LEASE_STATES = ("CLAIMED", "ACTIVE", "TRANSFERRING")
_LIVE_SQL = "lease_state IN ('CLAIMED', 'ACTIVE', 'TRANSFERRING')"
TERMINAL_LEASE_STATES = ("RELEASED", "EXPIRED", "ORPHANED")
# Episode states during which a human decision is pending: no GPU time may be billed across
# them (SPEC §5 rule 8). AWAITING_FINAL_REVIEW is the Gate 2 human wait.
HUMAN_WAIT_STATES = frozenset({EpisodeState.AWAITING_FINAL_REVIEW})

MOCK_PRICE_AS_OF = datetime(2026, 10, 20, tzinfo=UTC)


def mock_pod_price() -> PriceQuote:
    """The OFFLINE_MOCK synthetic GPU-second price (matches the T007 fake pod billing)."""
    return PriceQuote(
        currency="USD",
        unit=PriceUnit.GPU_SECOND,
        unit_price_micro_usd=250,
        source=PriceSource.FAKE_SYNTHETIC,
        price_table_version="microdrama-mock-pod-v1",
        as_of=MOCK_PRICE_AS_OF,
    )


def _ms(milliseconds: int) -> timedelta:
    return timedelta(milliseconds=milliseconds)


@dataclass(frozen=True)
class PodLeaseConfig:
    """Module-local configuration for the pod lifecycle (T006 registries feed the filters).

    ``price`` is the configured GPU-second quote; ``None`` means unknown and blocks every
    paid dispatch. ``allowed_gpu_types``/``min_host_ram_gb`` come from the enabled preset
    registry records; ``container_image`` is the pinned image reference.
    ``provider_account_ref`` (T045 R10) is the non-secret account label from the operator
    attestation, recorded on every lease claim so billing buckets attribute to it.
    """

    owned_tag: str
    allowed_gpu_types: frozenset[str]
    min_host_ram_gb: int
    container_image: str
    max_hourly_price_micro_usd: int
    price: PriceQuote | None
    provider_account_ref: str | None = None
    lease_ttl_ms: int = 1_800_000
    shutdown_margin_ms: int = 300_000
    heartbeat_timeout_ms: int = 300_000
    unbound_grace_ms: int = 60_000
    create_attempts: int = 2
    stop_attempts: int = 2

    @classmethod
    def for_mock(cls) -> PodLeaseConfig:
        """The OFFLINE_MOCK acquisition config: fake hardware, fake price, fake image.

        The synthetic price source is refused by the budget service outside OFFLINE_MOCK,
        so this config cannot dispatch anything real.
        """
        return cls(
            owned_tag="microdrama-owned:mock",
            allowed_gpu_types=frozenset({"FAKE-GPU-24GB"}),
            min_host_ram_gb=32,
            container_image="registry.invalid/render@sha256:" + "b" * 64,
            max_hourly_price_micro_usd=900_000,
            price=mock_pod_price(),
        )

    @property
    def paid_window_ms(self) -> int:
        return self.lease_ttl_ms + self.shutdown_margin_ms


@dataclass(frozen=True)
class PodLeaseClaimRequest:
    """One logical lease claim. ``semantic_key`` identifies it across retries/crashes."""

    episode_id: UUID
    semantic_key: str
    gpu_type: str
    host_ram_gb: int
    job_id: UUID | None = None
    pod_name: str = "microdrama-render"
    lease_ttl_ms: int | None = None


@dataclass(frozen=True)
class LeaseHandle:
    lease: PodLeaseContract
    replayed: bool = False


@dataclass(frozen=True)
class ShutdownResult:
    lease_id: UUID
    stop_verified_at: datetime | None
    settled_micro_usd: int
    replayed: bool = False
    compute_stopped: bool = True
    billing_pending: bool = False  # T045 R8: the hold stays until billing finality


def client_token_for(semantic_key: str) -> str:
    """Deterministic create token: retries of one logical claim can never fork pods."""
    return f"md-pod-{sha256_hex(semantic_key.encode('utf-8'))[:24]}"


def _ceil_div(value: int, divisor: int) -> int:
    return -(-value // divisor)


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise Conflict(f"{name} must be timezone-aware")
    return value


def episode_live_lease_count(tx: Tx, episode_id: UUID) -> int:
    row = tx.fetchone(
        f"SELECT count(*) AS n FROM pod_leases WHERE owner_episode_id = %s AND {_LIVE_SQL}",
        (episode_id,),
    )
    return int(row["n"]) if row else 0


def human_wait_guard(tx: Tx, entity_row: Mapping[str, Any], target: EpisodeState) -> None:
    """``core.TransitionGuard``: refuse a human-wait transition while any GPU lease is live.

    Mounted by the integrator on the episode state machine for the human-wait targets. The
    worker must call ``LeaseService.stop_for_human_wait`` (a full verified shutdown) first;
    the janitor enforces the same rule from durable state when a worker crashed.
    """
    if target not in HUMAN_WAIT_STATES:
        return
    episode_id = entity_row["id"]
    live = episode_live_lease_count(tx, episode_id)
    if live:
        raise PolicyDenied(
            "no GPU may run during a human wait; stop the episode's pod leases first "
            "(SPEC §5 rule 8)",
            episode_id=str(episode_id),
            live_leases=live,
        )


# --- boundaries and accrual (shared by the service and the independent janitor) ------------


def _first_event(events: list[DomainEvent], event_type: str) -> datetime | None:
    for event in events:
        if event.event_type == event_type:
            return event.occurred_at
    return None


_BASIS_RANK = {"COLD_START": 0, "RUNNING": 1, "IDLE": 2, "SHUTDOWN": 3}


def _basis_points(
    row: Mapping[str, Any], pod: PodInfo, events: list[DomainEvent]
) -> list[tuple[datetime, str]]:
    """Ordered (instant, basis) markers for the pod's paid lifetime.

    COLD_START runs from the pod's creation to the verified activation; RUNNING until the
    worker marks the lease idle; IDLE until shutdown starts; SHUTDOWN until the pod stops.
    A lease with no activation event yet (crash before attach) accrues everything as
    COLD_START, which is the honest declaration for unverified warmup time.
    """
    points: list[tuple[datetime, str]] = [(pod.created_at, "COLD_START")]
    activated = _first_event(events, "pod_lease.activated")
    if activated is not None:
        points.append((activated, "RUNNING"))
    idle = _first_event(events, "pod_lease.idle")
    if idle is not None and (activated is None or idle >= activated):
        points.append((idle, "IDLE"))
    release_started = _first_event(events, "pod_lease.release_started")
    if release_started is not None:
        points.append((release_started, "SHUTDOWN"))
    points.sort(key=lambda point: (point[0], _BASIS_RANK[point[1]]))
    deduped: list[tuple[datetime, str]] = []
    for instant, basis in points:
        if deduped and deduped[-1][0] == instant:
            # Equal instants keep the more specific (higher-rank) basis, so a pod whose
            # activation coincides with its creation has an empty COLD_START window
            # instead of mislabelling its whole run.
            deduped[-1] = (instant, basis)
            continue
        deduped.append((instant, basis))
    return deduped


def _segments(
    points: list[tuple[datetime, str]], cursor: datetime, bound: datetime
) -> list[tuple[datetime, datetime, str]]:
    """Split [cursor, bound) at the boundary points, labelling each piece with its basis."""
    effective = "COLD_START"
    for instant, basis in points:
        if instant <= cursor:
            effective = basis
        else:
            break
    segments: list[tuple[datetime, datetime, str]] = []
    walk = cursor
    for instant, basis in points:
        if instant <= cursor or instant >= bound:
            continue
        if instant > walk:
            segments.append((walk, instant, effective))
            walk = instant
        effective = basis
    if walk < bound:
        segments.append((walk, bound, effective))
    return segments


def accrue_lease_usage(
    db: Database,
    budget: BudgetService,
    manager: PodManager,
    *,
    lease_id: UUID,
    until: datetime,
) -> int:
    """Attribute every not-yet-recorded paid interval of the lease's pod, once, by basis.

    Pulls provider usage segment by segment (the provider clamps to the pod's real
    lifetime), and posts each receipt through ``BudgetService.record_gpu_interval`` with
    the segment's declared basis. ACCRUAL receipts take the segment basis; an ADJUSTMENT
    (late billing) is attributed as IDLE — unobserved time — and any overlap surfaces as
    the budget service's ``Conflict`` instead of being dropped. Replays are idempotent:
    the charge table dedupes on the provider receipt key and only newly recorded amounts
    count toward the return value.
    """
    bound = _aware(until, "until")
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone("SELECT * FROM pod_leases WHERE id = %s", (lease_id,))
        if row is None:
            raise NotFound("pod lease not found", lease_id=str(lease_id))
        events = list_events(tx, lease_id)
        account_id = tx.fetchval(
            "SELECT account_id FROM reservations WHERE id = %s", (row["reservation_id"],)
        )
    if account_id is None:
        raise Conflict("lease reservation is missing", lease_id=str(lease_id))
    if row["pod_id"] is None:
        return 0
    pod = manager.get(row["pod_id"])
    if pod is None:
        return 0
    cursor = row["accrued_until"] or pod.created_at
    if cursor >= bound:
        return 0
    attributed = 0
    advanced_to = cursor
    for start, end, basis in _segments(_basis_points(row, pod, events), cursor, bound):
        pos = start
        rounds = 0
        while pos < end and rounds < 100:
            rounds += 1
            receipts = manager.usage(row["pod_id"], since=pos, until=end)
            if not receipts:
                break
            progressed = False
            for receipt in receipts:
                r_start, r_end = receipt.interval_start, receipt.interval_end
                if r_start is None or r_end is None or r_end <= pos or r_end <= r_start:
                    continue
                attributed_receipt = receipt.model_copy(
                    update={
                        "reservation_id": row["reservation_id"],
                        "episode_id": row["owner_episode_id"],
                        "category": BudgetCategory.GPU_GENERATION,
                    }
                )
                receipt_basis = basis if receipt.kind is ReceiptKind.ACCRUAL else "IDLE"
                charge = budget.record_gpu_interval(
                    lease_id=lease_id,
                    provider=row["provider"],
                    pod_id=row["pod_id"],
                    account_id=account_id,
                    interval_start=r_start,
                    interval_end=r_end,
                    basis=receipt_basis,
                    receipt=attributed_receipt,
                )
                if not charge.replayed:
                    attributed += receipt.amount_micro_usd
                pos = max(pos, r_end)
                advanced_to = max(advanced_to, r_end)
                progressed = True
            if not progressed:
                break
    if advanced_to > cursor:
        with db.transaction() as tx:
            current = tx.fetchone(
                "SELECT accrued_until, revision FROM pod_leases WHERE id = %s FOR UPDATE",
                (lease_id,),
            )
            if current is None:
                raise NotFound("pod lease not found", lease_id=str(lease_id))
            existing = current["accrued_until"]
            if existing is None or existing < advanced_to:
                update_with_revision(
                    tx,
                    "pod_leases",
                    lease_id,
                    current["revision"],
                    {"accrued_until": advanced_to},
                )
    return attributed


def _settlement_totals(db: Database, reservation_id: UUID) -> tuple[int, int]:
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT COALESCE(SUM(amount_micro_usd), 0)::bigint AS amount, "
            "COALESCE(SUM(units), 0)::bigint AS units FROM charges "
            "WHERE reservation_id = %s AND kind IN ('ACCRUAL', 'ADJUSTMENT')",
            (reservation_id,),
        )
    assert row is not None
    return int(row["amount"]), int(row["units"])


def open_storage_ownership(db: Database, lease_id: UUID, pod_id: str) -> None:
    """Idempotently open the pod's storage-ownership row for the chain root (T045 R3).

    The owner is the root lease's episode (the episode that asked for the create), the
    interval starts at the root's ``create_requested_at``, and the row records its
    creating lease. A warm transfer never touches it; only the verified terminate closes.
    """
    with db.transaction() as tx:
        lease = tx.fetchone("SELECT * FROM pod_leases WHERE id = %s", (lease_id,))
        if lease is None:
            raise NotFound("pod lease not found", lease_id=str(lease_id))
        root = tx.fetchone(
            "SELECT id, owner_episode_id, create_requested_at FROM pod_leases "
            "WHERE provider = %s AND pod_id = %s AND transferred_from IS NULL "
            "ORDER BY created_at LIMIT 1",
            (lease["provider"], pod_id),
        )
        owner = root if root is not None else lease
        valid_from = (
            owner["create_requested_at"] or lease["create_requested_at"] or owner["created_at"]
        )
        existing = tx.fetchval(
            "SELECT 1 FROM pod_storage_ownership WHERE provider = %s AND pod_id = %s "
            "AND creating_lease_id = %s",
            (lease["provider"], pod_id, owner["id"]),
        )
        if existing is None:
            tx.execute(
                "INSERT INTO pod_storage_ownership (id, provider, pod_id, owner_episode_id, "
                "valid_from, creating_lease_id) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    uuid5(RENDERING_NAMESPACE, f"storage-ownership:{owner['id']}"),
                    lease["provider"],
                    pod_id,
                    owner["owner_episode_id"],
                    valid_from,
                    owner["id"],
                ),
            )


def close_storage_ownership(db: Database, provider: str, pod_id: str, instant: datetime) -> None:
    """Close the pod's open ownership interval at the verified terminate (set-once).

    The interval must stay non-empty (schema CHECK), so a terminate that lands on the
    same instant as the create request closes at create + 1µs: a pod that lived no time
    owns no storage time, and the row still records the close exactly once.
    """
    with db.transaction() as tx:
        tx.execute(
            "UPDATE pod_storage_ownership SET valid_until = GREATEST(%s, valid_from + "
            "interval '1 microsecond') WHERE provider = %s AND pod_id = %s "
            "AND valid_until IS NULL",
            (instant, provider, pod_id),
        )


def settle_reservation_for_lease(
    db: Database,
    budget: BudgetService,
    settings: Settings,
    *,
    finality: LeaseBillingFinality,
    lease_id: UUID,
    context: str,
) -> int:
    """Close the lease's budget hold through the required finality port (T045 R8).

    There is no default and no flag: the caller's finality decides whether an unused
    hold releases (offline synthetic) or waits for invoice finality (Runpod).
    T045-FIX A-N9: the pairing is checked here too, against the lease's own provider —
    a settle call cannot bypass the constructor-side gate by passing a foreign finality.
    """
    with db.transaction(readonly=True) as tx:
        provider = tx.fetchval("SELECT provider FROM pod_leases WHERE id = %s", (lease_id,))
    if provider is None:
        raise NotFound("pod lease not found", lease_id=str(lease_id))
    check_finality_pairing(finality, str(provider))
    return finality.settle_lease(
        db, budget, settings, lease_id=lease_id, context=context
    ).settled_micro_usd


def settle_from_recorded_usage(
    db: Database,
    budget: BudgetService,
    settings: Settings,
    *,
    lease_id: UUID,
    context: str,
) -> LeaseSettlement:
    """The offline synthetic settlement: settle to the recorded usage, release if unused.

    The settlement receipt is fully deterministic (stable receipt keys, ``observed_at``
    taken from the lease row's own ``updated_at``), so a crash between the lease update and
    this call replays idempotently, and the janitor can finish an unsettled hold later.
    """
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone("SELECT * FROM pod_leases WHERE id = %s", (lease_id,))
        if row is None:
            raise NotFound("pod lease not found", lease_id=str(lease_id))
    total, units = _settlement_totals(db, row["reservation_id"])
    if total == 0:
        try:
            budget.release(
                row["reservation_id"],
                reason=f"pod lease {lease_id} closed without usage ({context})",
            )
        except Conflict:
            pass  # already closed by an earlier attempt (replay)
        return LeaseSettlement(0, released=True)
    mock = settings.is_offline_mock
    receipt = UsageReceipt(
        receipt_id=uuid5(RENDERING_NAMESPACE, f"settle:{row['provider']}:{lease_id}"),
        provider=row["provider"],
        provider_receipt_id=f"podlease-settle:{lease_id}",
        kind=ReceiptKind.SETTLEMENT,
        cost_basis=CostBasis.SYNTHETIC_FAKE if mock else CostBasis.PROVIDER_REPORTED,
        reservation_id=row["reservation_id"],
        episode_id=row["owner_episode_id"],
        season_id=None,
        category=BudgetCategory.GPU_GENERATION,
        amount_micro_usd=total,
        currency="USD",
        units=units,
        unit=PriceUnit.GPU_SECOND,
        interval_start=None,
        interval_end=None,
        observed_at=row["updated_at"],
        provenance=Provenance.FAKE_SYNTHETIC if mock else Provenance.LIVE_PROVIDER,
    )
    budget.record_usage(receipt)
    return LeaseSettlement(settled_micro_usd=total)


# --- the lease service ---------------------------------------------------------------------


class LeaseService:
    """Owns ``pod_leases`` rows and drives the pod lifecycle against a ``PodManager``."""

    def __init__(
        self,
        db: Database,
        budget: BudgetService,
        manager: PodManager,
        clock: Clock,
        ids: IdGenerator,
        settings: Settings,
        config: PodLeaseConfig,
        finality: LeaseBillingFinality,
    ) -> None:
        check_finality_pairing(finality, manager.provider_id)
        self._finality = finality
        self._db = db
        self._budget = budget
        self._manager = manager
        self._clock = clock
        self._ids = ids
        self._settings = settings
        self._config = config
        self._id_lock = threading.Lock()

    # --- plumbing ----------------------------------------------------------------------

    def _new_id(self) -> UUID:
        with self._id_lock:
            return self._ids.new_id()

    def _now(self) -> datetime:
        now = self._clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise Conflict("clock must return a timezone-aware instant")
        return now

    def _spec_for(self, row: Mapping[str, Any]) -> PodSpec:
        return PodSpec(
            gpu_type_allowlist=(row["gpu_type"],),
            max_hourly_price_micro_usd=self._config.max_hourly_price_micro_usd,
            min_host_ram_gb=self._config.min_host_ram_gb,
            container_image=self._config.container_image,
        )

    def _load(self, lease_id: UUID) -> dict[str, Any]:
        with self._db.transaction(readonly=True) as tx:
            row = tx.fetchone("SELECT * FROM pod_leases WHERE id = %s", (lease_id,))
        if row is None:
            raise NotFound("pod lease not found", lease_id=str(lease_id))
        return row

    @staticmethod
    def _contract(row: Mapping[str, Any]) -> PodLeaseContract:
        return PodLeaseContract(
            lease_id=row["id"],
            provider=row["provider"],
            pod_id=row["pod_id"],
            owned_tag=row["owned_tag"],
            client_token=row["client_token"],
            owner_episode_id=row["owner_episode_id"],
            owner_job_id=row["owner_job_id"],
            reservation_id=row["reservation_id"],
            lease_state=LeaseState(row["lease_state"]),
            pod_state=PodState(row["pod_state"]),
            gpu_type=row["gpu_type"],
            hourly_price_micro_usd=row["hourly_price_micro_usd"],
            heartbeat_at=row["heartbeat_at"],
            lease_expires_at=row["lease_expires_at"],
            accrued_until=row["accrued_until"],
            transferred_from=row.get("transferred_from"),
            created_at=row["created_at"],
        )

    def _emit(
        self,
        tx: Tx,
        lease_id: UUID,
        event_type: str,
        payload: Mapping[str, Any],
        now: datetime,
    ) -> None:
        append_event(
            tx,
            aggregate_type="pod_lease",
            aggregate_id=lease_id,
            event_type=event_type,
            payload=dict(payload),
            correlation_id=lease_id,
            occurred_at=now,
        )

    # --- claim -------------------------------------------------------------------------

    def claim(self, request: PodLeaseClaimRequest) -> LeaseHandle:
        """Atomically claim the pilot's single GPU lease and its budget hold.

        The budget reservation commits first; the lease row (CLAIMED, REQUESTED, tied to
        the reservation) follows in its own transaction. A crash in between is repaired by
        adoption on retry and by the janitor's unbound-hold sweep — never by a second pod.
        Refusals leave nothing behind: unknown price/hardware/RAM filter blocks happen
        before the reservation; a failed lease insert unwinds the hold it just created.
        """
        spec = PodSpec(
            gpu_type_allowlist=(request.gpu_type,),
            max_hourly_price_micro_usd=self._config.max_hourly_price_micro_usd,
            min_host_ram_gb=request.host_ram_gb,
            container_image=self._config.container_image,
        )
        check_acquisition_filters(
            spec,
            allowed_gpu_types=self._config.allowed_gpu_types,
            min_host_ram_gb=self._config.min_host_ram_gb,
            price=self._config.price,
        )
        token = client_token_for(request.semantic_key)
        existing = self._find_by_token(token)
        if existing is not None:
            if existing["owner_episode_id"] != request.episode_id:
                raise Conflict(
                    "lease semantic key already claimed by another episode",
                    semantic_key=request.semantic_key,
                )
            return LeaseHandle(self._contract(existing), replayed=True)
        ttl = request.lease_ttl_ms or self._config.lease_ttl_ms
        reservation, adopted = self._reserve_for_lease(request, ttl)
        try:
            return self._insert_claim(request, reservation, token, ttl)
        except MicrodramaError:
            # Best-effort in-process unwind. Durable recovery never relies on it: an
            # adopted or concurrently-shared hold must stay for its winner, and the
            # janitor releases truly unbound holds after the grace period.
            if not adopted:
                try:
                    self._budget.release(
                        reservation.id, reason=f"claim aborted: {request.semantic_key}"
                    )
                except MicrodramaError:
                    pass
            raise

    def _find_by_token(self, token: str) -> dict[str, Any] | None:
        with self._db.transaction(readonly=True) as tx:
            return tx.fetchone(
                "SELECT * FROM pod_leases WHERE provider = %s AND client_token = %s",
                (self._manager.provider_id, token),
            )

    def _reserve_for_lease(
        self, request: PodLeaseClaimRequest, ttl: int
    ) -> tuple[Reservation, bool]:
        price = self._config.price
        assert price is not None  # check_acquisition_filters already refused None
        window = ttl + self._config.shutdown_margin_ms
        worst = price.unit_price_micro_usd * _ceil_div(window, 1000)
        budget_request = BudgetReservationRequest(
            request_id=uuid5(RENDERING_NAMESPACE, f"claim:{request.semantic_key}"),
            semantic_key=request.semantic_key,
            scope_kind=BudgetScopeKind.EPISODE,
            episode_id=request.episode_id,
            season_id=None,
            category=BudgetCategory.GPU_GENERATION,
            queue=QueueName.PRODUCTION,
            job_id=request.job_id,
            provider=self._manager.provider_id,
            operation_kind=LEASE_OPERATION_KIND,
            price=price,
            ceilings=ExposureCeilings(timeout_ms=window, max_units=1),
            worst_case_micro_usd=worst,
            is_shutdown_or_cleanup=False,
            expires_at=self._now() + _ms(window),
        )
        try:
            return self._budget.reserve(budget_request), False
        except (IdempotencyConflict, DuplicateSemanticKey):
            # The same logical claim retried after a crash (or racing itself) rebuilt a
            # slightly different request (expiry drift). Adopt the committed hold when it
            # is provably ours: right kind, provider, episode, size, and still unbound.
            adopted = self._adopt_reservation(request, worst)
            if adopted is None:
                raise
            return adopted, True

    def _adopt_reservation(self, request: PodLeaseClaimRequest, worst: int) -> Reservation | None:
        with self._db.transaction(readonly=True) as tx:
            row = tx.fetchone(
                "SELECT * FROM reservations WHERE semantic_key = %s",
                (request.semantic_key,),
            )
            if row is None:
                return None
            bound = tx.fetchval("SELECT 1 FROM pod_leases WHERE reservation_id = %s", (row["id"],))
        if (
            row["operation_kind"] != LEASE_OPERATION_KIND
            or row["provider"] != self._manager.provider_id
            or row["state"] != "ACTIVE"
            or row["episode_id"] != request.episode_id
            or row["reserved_micro_usd"] != worst
            or bound is not None
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
        )

    def _insert_claim(
        self,
        request: PodLeaseClaimRequest,
        reservation: Reservation,
        token: str,
        ttl: int,
    ) -> LeaseHandle:
        now = self._now()
        price = self._config.price
        assert price is not None
        lease_id = self._new_id()
        try:
            with self._db.transaction() as tx:
                inserted = tx.fetchone(
                    "INSERT INTO pod_leases (id, schema_version, provider, pod_id, owned_tag, "
                    "client_token, owner_episode_id, owner_job_id, reservation_id, lease_state, "
                    "pod_state, gpu_type, hourly_price_micro_usd, lease_expires_at, "
                    "provider_account_ref) "
                    "VALUES (%s, '1.0', %s, NULL, %s, %s, %s, %s, %s, 'CLAIMED', 'REQUESTED', "
                    "%s, %s, %s, %s) "
                    "ON CONFLICT (provider, client_token) DO NOTHING RETURNING *",
                    (
                        lease_id,
                        self._manager.provider_id,
                        self._config.owned_tag,
                        token,
                        request.episode_id,
                        request.job_id,
                        reservation.id,
                        request.gpu_type,
                        price.unit_price_micro_usd * 3600,
                        now + _ms(ttl),
                        self._config.provider_account_ref,
                    ),
                )
                if inserted is None:
                    winner = tx.fetchone(
                        "SELECT * FROM pod_leases WHERE provider = %s AND client_token = %s",
                        (self._manager.provider_id, token),
                    )
                    if winner is None:  # pragma: no cover - conflict implies a row
                        raise Conflict("lease claim conflict without an existing row")
                    if winner["owner_episode_id"] != request.episode_id:
                        raise Conflict(
                            "lease semantic key already claimed by another episode",
                            semantic_key=request.semantic_key,
                        )
                    return LeaseHandle(self._contract(winner), replayed=True)
                self._emit(
                    tx,
                    lease_id,
                    "pod_lease.claimed",
                    {
                        "episode_id": str(request.episode_id),
                        "semantic_key": request.semantic_key,
                        "reservation_id": str(reservation.id),
                        "ttl_ms": ttl,
                    },
                    now,
                )
        except DuplicateSemanticKey as exc:
            # A concurrent claim of the same key may have committed its live lease between
            # our reserve and this insert, and the insertion can hit the single-live-lease
            # index before the token arbiter. Re-read by token: if the winner exists this
            # is a replay of the same logical claim; otherwise it is a real pilot-rule or
            # pod-conflict refusal.
            constraint = str(exc.details.get("constraint") or "")
            winner = self._find_by_token(token)
            if winner is not None:
                if winner["owner_episode_id"] != request.episode_id:
                    raise Conflict(
                        "lease semantic key already claimed by another episode",
                        semantic_key=request.semantic_key,
                    ) from exc
                return LeaseHandle(self._contract(winner), replayed=True)
            if "single_live_lease" in constraint:
                raise PolicyDenied(
                    "pilot rule: only one episode may own the live GPU lease at a time",
                    episode_id=str(request.episode_id),
                ) from exc
            if "live_pod" in constraint:
                raise Conflict("this pod already has a live lease") from exc
            raise
        return LeaseHandle(self._contract(inserted))

    # --- acquisition -------------------------------------------------------------------

    def ensure_pod(self, lease_id: UUID) -> LeaseHandle:
        """Acquire or reconcile the lease's pod, verify it, and activate the lease."""
        row = self._load(lease_id)
        if row["lease_state"] not in LIVE_LEASE_STATES:
            raise Conflict("lease is not live", lease_id=str(lease_id), state=row["lease_state"])
        spec = self._spec_for(row)
        if row["pod_id"]:
            pod = self._manager.get(row["pod_id"])
            if pod is None:
                raise Conflict(
                    "leased pod vanished from the provider; needs reconciliation",
                    lease_id=str(lease_id),
                    pod_id=row["pod_id"],
                )
            self._manager.verify(pod, spec, settings=self._settings)
            if row["lease_state"] == "CLAIMED":
                self._activate(lease_id, pod)
        else:
            # Durable create-request proof is committed in its own transaction BEFORE the
            # create call is sent (T045 R8/G13): with it, a later list miss can no longer
            # be read as "nothing was sent" and the hold cannot be quietly released.
            self._record_create_request(lease_id)
            pod = self._manager.acquire_or_reconcile(
                spec, name=self._pod_name(row), client_token=row["client_token"]
            )
            self._manager.verify(pod, spec, settings=self._settings)
            self._activate(lease_id, pod)
        return LeaseHandle(self._contract(self._load(lease_id)))

    def _record_create_request(self, lease_id: UUID) -> datetime:
        """Commit the create-request instant (and the root's window start) before create."""
        now = self._now()
        with self._db.transaction() as tx:
            row = tx.fetchone(
                "SELECT create_requested_at, compute_window_start_at, revision "
                "FROM pod_leases WHERE id = %s FOR UPDATE",
                (lease_id,),
            )
            if row is None:
                raise NotFound("pod lease not found", lease_id=str(lease_id))
            if row["create_requested_at"] is None:
                update_with_revision(
                    tx,
                    "pod_leases",
                    lease_id,
                    row["revision"],
                    # A chain root's compute window starts when its create was requested.
                    {"create_requested_at": now, "compute_window_start_at": now},
                    now=now,
                )
                return now
            return row["create_requested_at"]

    @staticmethod
    def _pod_name(row: Mapping[str, Any]) -> str:
        return f"md-render-{str(row['owner_episode_id'])[:8]}"

    def _activate(self, lease_id: UUID, pod: PodInfo) -> None:
        now = self._now()
        with self._db.transaction() as tx:
            row = tx.fetchone("SELECT * FROM pod_leases WHERE id = %s FOR UPDATE", (lease_id,))
            if row is None:
                raise NotFound("pod lease not found", lease_id=str(lease_id))
            if row["lease_state"] not in LIVE_LEASE_STATES:
                raise Conflict(
                    "lease is not live", lease_id=str(lease_id), state=row["lease_state"]
                )
            if row["pod_id"] not in (None, pod.pod_id):
                raise Conflict(
                    "lease is bound to a different pod",
                    lease_id=str(lease_id),
                    pod_id=row["pod_id"],
                )
            update_with_revision(
                tx,
                "pod_leases",
                lease_id,
                row["revision"],
                {
                    "pod_id": pod.pod_id,
                    "pod_state": PodState.RUNNING.value,
                    "lease_state": LeaseState.ACTIVE.value,
                    "heartbeat_at": now,
                    # Adopted pods whose create proof predates the window columns still
                    # get a window start; set-once keeps the first value forever.
                    "compute_window_start_at": (
                        row["compute_window_start_at"] or row["create_requested_at"] or now
                    ),
                },
                now=now,
            )
            self._emit(
                tx,
                lease_id,
                "pod_lease.activated",
                {
                    "pod_id": pod.pod_id,
                    "gpu_type": pod.gpu_type,
                    "client_token": row["client_token"],
                },
                now,
            )
        # The pod is now durably ours: its storage belongs to the chain root's episode
        # from the create request on (T045 R3). Idempotent on every re-activation.
        open_storage_ownership(self._db, lease_id, pod.pod_id)

    # --- operation ---------------------------------------------------------------------

    def heartbeat(self, lease_id: UUID) -> datetime:
        """Proof of life. The janitor treats a stale heartbeat as a dead worker."""
        now = self._now()
        with self._db.transaction() as tx:
            row = tx.fetchone(
                "SELECT l.*, e.state AS episode_state FROM pod_leases l "
                "LEFT JOIN episodes e ON e.id = l.owner_episode_id "
                "WHERE l.id = %s FOR UPDATE OF l",
                (lease_id,),
            )
            if row is None:
                raise NotFound("pod lease not found", lease_id=str(lease_id))
            if row["lease_state"] != LeaseState.ACTIVE.value:
                if row["episode_state"] in HUMAN_WAIT_STATES:
                    # SPEC §5 rule 8: no GPU during a human wait. A lease released for the
                    # gate is dead for good; heartbeat-ing it back is policy, not ordering.
                    raise PolicyDenied(
                        "episode is in a human wait; a released lease cannot be resurrected",
                        lease_id=str(lease_id),
                        episode_state=row["episode_state"],
                    )
                raise InvalidTransition(
                    "only an ACTIVE lease has a worker to heartbeat",
                    state=row["lease_state"],
                )
            update_with_revision(
                tx, "pod_leases", lease_id, row["revision"], {"heartbeat_at": now}, now=now
            )
        return now

    def mark_idle(self, lease_id: UUID) -> None:
        """Declare the render work finished while the pod stays warm (pending transfer)."""
        now = self._now()
        with self._db.transaction() as tx:
            row = tx.fetchone("SELECT * FROM pod_leases WHERE id = %s FOR UPDATE", (lease_id,))
            if row is None:
                raise NotFound("pod lease not found", lease_id=str(lease_id))
            if row["lease_state"] != LeaseState.ACTIVE.value:
                raise InvalidTransition(
                    "only an ACTIVE lease can be marked idle", state=row["lease_state"]
                )
            self._emit(
                tx, lease_id, "pod_lease.idle", {"episode_id": str(row["owner_episode_id"])}, now
            )

    def accrue(self, lease_id: UUID, *, until: datetime | None = None) -> int:
        return accrue_lease_usage(
            self._db,
            self._budget,
            self._manager,
            lease_id=lease_id,
            until=until or self._now(),
        )

    # --- shutdown ----------------------------------------------------------------------

    def begin_shutdown(self, lease_id: UUID, *, reason: str) -> datetime:
        """Durably start the shutdown: final usage accrual, RELEASING mark, event.

        Split from ``complete_shutdown`` so a crash between the two leaves state the
        janitor can finish: the release_started event both fixes the SHUTDOWN basis
        boundary and proves the stop was intended.
        """
        now = self._now()
        self.accrue(lease_id)
        with self._db.transaction() as tx:
            row = tx.fetchone("SELECT * FROM pod_leases WHERE id = %s FOR UPDATE", (lease_id,))
            if row is None:
                raise NotFound("pod lease not found", lease_id=str(lease_id))
            if row["lease_state"] not in LIVE_LEASE_STATES:
                raise Conflict(
                    "lease is not live", lease_id=str(lease_id), state=row["lease_state"]
                )
            events = list_events(tx, lease_id)
            if _first_event(events, "pod_lease.release_started") is None:
                self._emit(tx, lease_id, "pod_lease.release_started", {"reason": reason}, now)
            if row["pod_state"] != PodState.RELEASING.value and row["pod_id"] is not None:
                update_with_revision(
                    tx,
                    "pod_leases",
                    lease_id,
                    row["revision"],
                    {"pod_state": PodState.RELEASING.value},
                    now=now,
                )
        return now

    def shutdown(self, lease_id: UUID, *, reason: str) -> ShutdownResult:
        """Stop the pod, verify compute stopped, account the shutdown interval, settle.

        The stop happens whether or not a shutdown-grant reservation could be made: the
        lease's own hold already covers the margin, and ``record_gpu_interval`` is not
        blocked by an exhausted account, so an overrun is recorded rather than a leaked pod.
        Idempotent: a replay on a RELEASED lease reports the recorded outcome.
        """
        row = self._load(lease_id)
        if row["lease_state"] == LeaseState.RELEASED.value:
            settled, _ = _settlement_totals(self._db, row["reservation_id"])
            state = self._reservation_state(row["reservation_id"])
            return ShutdownResult(
                lease_id=lease_id,
                stop_verified_at=row["stop_verified_at"],
                settled_micro_usd=settled,
                replayed=True,
                billing_pending=state in ("ACTIVE", "EXPIRED"),
            )
        if row["lease_state"] not in LIVE_LEASE_STATES:
            raise Conflict("lease is not live", lease_id=str(lease_id), state=row["lease_state"])
        if row["pod_id"] is None:
            pod = self._manager.reconcile_by_token(row["client_token"])
            if pod is None:
                return self._close_claim_without_pod(lease_id, reason)
            spec = self._spec_for(row)
            self._manager.verify(pod, spec, settings=self._settings)
            self._activate(lease_id, pod)
        self.begin_shutdown(lease_id, reason=reason)
        row = self._load(lease_id)
        cleanup_id = self._reserve_cleanup_grant(row)
        try:
            terminal = self._manager.stop(row["pod_id"])
        except MicrodramaError as exc:
            with self._db.transaction() as tx:
                self._emit(
                    tx,
                    lease_id,
                    "pod_lease.stop_failed",
                    {"reason": reason, "error": exc.code, "detail": str(exc.message)},
                    self._now(),
                )
            raise
        window_end = self._now()
        terminate_verified: datetime | None = None
        if self._manager.is_runpod():
            # T045 R8: the final release of a Runpod chain terminates the pod. A stopped
            # pod still bills its volume, so the chain's compute window (and the storage
            # ownership it grounds) only ends at a verified terminate.
            terminal = self._manager.terminate(row["pod_id"])
            terminate_verified = self._now()
            window_end = terminate_verified
            close_storage_ownership(self._db, row["provider"], row["pod_id"], terminate_verified)
        self.accrue(lease_id)
        now = self._now()
        with self._db.transaction() as tx:
            current = tx.fetchone("SELECT * FROM pod_leases WHERE id = %s FOR UPDATE", (lease_id,))
            assert current is not None
            update_with_revision(
                tx,
                "pod_leases",
                lease_id,
                current["revision"],
                {
                    "lease_state": LeaseState.RELEASED.value,
                    "pod_state": terminal.value,
                    "stop_verified_at": current["stop_verified_at"] or now,
                    # Set once: the verified stop, or the verified terminate for Runpod.
                    "compute_window_end_at": current["compute_window_end_at"] or window_end,
                    "terminate_verified_at": current["terminate_verified_at"] or terminate_verified,
                },
                now=now,
            )
            self._emit(
                tx,
                lease_id,
                "pod_lease.released",
                {"reason": reason, "pod_state": terminal.value},
                now,
            )
        outcome = self._finality.settle_lease(
            self._db, self._budget, self._settings, lease_id=lease_id, context=reason, now=now
        )
        self._release_cleanup_grant(cleanup_id, lease_id)
        return ShutdownResult(
            lease_id=lease_id,
            stop_verified_at=now,
            settled_micro_usd=outcome.settled_micro_usd,
            billing_pending=outcome.pending,
        )

    def _close_claim_without_pod(self, lease_id: UUID, reason: str) -> ShutdownResult:
        now = self._now()
        with self._db.transaction() as tx:
            row = tx.fetchone("SELECT * FROM pod_leases WHERE id = %s FOR UPDATE", (lease_id,))
            assert row is not None
            # T045-FIX A-S1: a create that was sent but never produced a Pod still has
            # a compute window; its end is this close instant. Without it readiness
            # stays PENDING forever; the audited operator resolution (or a stray
            # adoption) settles what the window means.
            update_with_revision(
                tx,
                "pod_leases",
                lease_id,
                row["revision"],
                {
                    "lease_state": LeaseState.RELEASED.value,
                    "compute_window_end_at": row["compute_window_end_at"]
                    or (
                        # Only a sent create opened a window worth closing.
                        now if row["create_requested_at"] is not None else None
                    ),
                },
                now=now,
            )
            self._emit(
                tx,
                lease_id,
                "pod_lease.released",
                {"reason": reason, "compute": "none"},
                now,
            )
        outcome = self._finality.settle_lease(
            self._db, self._budget, self._settings, lease_id=lease_id, context=reason, now=now
        )
        return ShutdownResult(
            lease_id=lease_id,
            stop_verified_at=None,
            settled_micro_usd=outcome.settled_micro_usd,
            billing_pending=outcome.pending,
        )

    def _reserve_cleanup_grant(self, row: Mapping[str, Any]) -> UUID | None:
        """Best-effort ``pod.stop`` shutdown grant (T005 cleanup privilege).

        Refusal (exhausted cap, blocked account) never prevents the stop; it is recorded
        as an event and the interval is still attributed to the lease's own hold.
        """
        price = self._config.price
        if price is None:
            return None
        margin = self._config.shutdown_margin_ms
        worst = price.unit_price_micro_usd * _ceil_div(margin, 1000)
        key = f"{STOP_OPERATION_KIND}:{row['id']}"
        request = BudgetReservationRequest(
            request_id=uuid5(RENDERING_NAMESPACE, f"stop:{row['id']}"),
            semantic_key=key,
            scope_kind=BudgetScopeKind.EPISODE,
            episode_id=row["owner_episode_id"],
            season_id=None,
            category=BudgetCategory.GPU_GENERATION,
            queue=QueueName.PRODUCTION,
            job_id=row["owner_job_id"],
            provider=row["provider"],
            operation_kind=STOP_OPERATION_KIND,
            price=price,
            ceilings=ExposureCeilings(timeout_ms=margin, max_units=1),
            worst_case_micro_usd=worst,
            is_shutdown_or_cleanup=True,
            expires_at=self._now() + _ms(margin),
        )
        try:
            return self._budget.reserve(request).id
        except MicrodramaError as exc:
            with self._db.transaction() as tx:
                self._emit(
                    tx,
                    row["id"],
                    "pod_lease.cleanup_grant_refused",
                    {"error": exc.code},
                    self._now(),
                )
            return None

    def _release_cleanup_grant(self, cleanup_id: UUID | None, lease_id: UUID) -> None:
        if cleanup_id is None:
            return
        try:
            self._budget.release(cleanup_id, reason=f"pod lease {lease_id} shutdown grant unused")
        except MicrodramaError:
            # An unreleased grant expires on its own short deadline; the janitor also
            # sweeps stale pod.stop holds. Never block the shutdown path on it.
            pass

    def _reservation_state(self, reservation_id: UUID) -> str:
        with self._db.transaction(readonly=True) as tx:
            state = tx.fetchval("SELECT state FROM reservations WHERE id = %s", (reservation_id,))
        return str(state) if state else "MISSING"

    # --- cancellation / human wait -------------------------------------------------------

    def release_claim(self, lease_id: UUID, *, reason: str) -> ShutdownResult:
        """Cancel a claim that never produced compute (or shut down its stray pod)."""
        row = self._load(lease_id)
        if row["lease_state"] not in LIVE_LEASE_STATES:
            raise Conflict("lease is not live", lease_id=str(lease_id), state=row["lease_state"])
        return self.shutdown(lease_id, reason=reason)

    def stop_for_human_wait(self, episode_id: UUID) -> list[ShutdownResult]:
        """Shut down every live lease of an episode before it enters a human wait."""
        results = []
        for row in self.live_leases_for_episode(episode_id):
            results.append(
                self.shutdown(
                    row["id"], reason=f"human-wait: episode {episode_id} awaits a human gate"
                )
            )
        return results

    # --- warm-pod transfer ----------------------------------------------------------------

    def transfer(
        self,
        lease_id: UUID,
        *,
        to_episode_id: UUID,
        to_semantic_key: str,
        to_job_id: UUID | None = None,
    ) -> LeaseHandle:
        """Transactionally move a warm pod's ownership to another episode.

        The old lease closes (RELEASED, accounted to the transfer instant) and the new
        lease opens ACTIVE on the new episode's own reservation in the *same* database
        transaction, so the pilot single-live-lease invariant and the pod's usage-interval
        exclusion constraint together guarantee each paid second is owned — and billed —
        exactly once across the handover.
        """
        row = self._load(lease_id)
        if row["lease_state"] != LeaseState.ACTIVE.value or row["pod_id"] is None:
            raise Conflict(
                "only an ACTIVE lease with a running pod can transfer",
                lease_id=str(lease_id),
                state=row["lease_state"],
            )
        pod = self._manager.get(row["pod_id"])
        if pod is None:
            raise Conflict("leased pod vanished from the provider", pod_id=row["pod_id"])
        self._manager.verify(pod, self._spec_for(row), settings=self._settings)
        self.accrue(lease_id)
        ttl = self._config.lease_ttl_ms
        request = PodLeaseClaimRequest(
            episode_id=to_episode_id,
            semantic_key=to_semantic_key,
            gpu_type=row["gpu_type"],
            host_ram_gb=self._config.min_host_ram_gb,
            job_id=to_job_id,
        )
        price = self._config.price
        assert price is not None
        reservation, _adopted = self._reserve_for_lease(request, ttl)
        now = self._now()
        new_token = client_token_for(to_semantic_key)
        new_id = self._new_id()
        with self._db.transaction() as tx:
            old = tx.fetchone("SELECT * FROM pod_leases WHERE id = %s FOR UPDATE", (lease_id,))
            assert old is not None
            if old["lease_state"] != LeaseState.ACTIVE.value:
                raise Conflict(
                    "lease is no longer ACTIVE", lease_id=str(lease_id), state=old["lease_state"]
                )
            update_with_revision(
                tx,
                "pod_leases",
                lease_id,
                old["revision"],
                {
                    "lease_state": LeaseState.RELEASED.value,
                    "accrued_until": now,
                    # T045 R8/G16: a lease that transferred away has no verified stop of
                    # its own; its compute window ends at the transfer instant.
                    "compute_window_end_at": old["compute_window_end_at"] or now,
                },
                now=now,
            )
            self._emit(
                tx,
                lease_id,
                "pod_lease.transferred_away",
                {"to_reservation_id": str(reservation.id), "to_episode_id": str(to_episode_id)},
                now,
            )
            inserted = tx.fetchone(
                "INSERT INTO pod_leases (id, schema_version, provider, pod_id, owned_tag, "
                "client_token, owner_episode_id, owner_job_id, reservation_id, lease_state, "
                "pod_state, gpu_type, hourly_price_micro_usd, heartbeat_at, lease_expires_at, "
                "accrued_until, transferred_from, compute_window_start_at) "
                "VALUES (%s, '1.0', %s, %s, %s, %s, %s, %s, %s, 'ACTIVE', 'RUNNING', %s, %s, "
                "%s, %s, %s, %s, %s) RETURNING *",
                (
                    new_id,
                    old["provider"],
                    old["pod_id"],
                    old["owned_tag"],
                    new_token,
                    to_episode_id,
                    to_job_id,
                    reservation.id,
                    old["gpu_type"],
                    old["hourly_price_micro_usd"],
                    now,
                    now + _ms(ttl),
                    now,
                    lease_id,
                    # A transfer receiver's compute window starts at the transfer instant.
                    now,
                ),
            )
            assert inserted is not None
            self._emit(
                tx,
                new_id,
                "pod_lease.activated",
                {"pod_id": old["pod_id"], "transferred_from": str(lease_id)},
                now,
            )
        settle_reservation_for_lease(
            self._db,
            self._budget,
            self._settings,
            finality=self._finality,
            lease_id=lease_id,
            context="transferred",
        )
        return LeaseHandle(self._contract(inserted))

    # --- reads ---------------------------------------------------------------------------

    def get(self, lease_id: UUID) -> PodLeaseContract:
        return self._contract(self._load(lease_id))

    def live_leases_for_episode(self, episode_id: UUID) -> list[dict[str, Any]]:
        with self._db.transaction(readonly=True) as tx:
            return tx.fetchall(
                f"SELECT * FROM pod_leases WHERE owner_episode_id = %s AND {_LIVE_SQL} "
                "ORDER BY created_at",
                (episode_id,),
            )


def build_lease_service(
    db: Database,
    budget: BudgetService,
    provider: PodManager,
    clock: Clock,
    ids: IdGenerator,
    settings: Settings,
    config: PodLeaseConfig,
    finality: LeaseBillingFinality,
) -> LeaseService:
    """Composition factory for the integrator (route/job registration stays with them)."""
    return LeaseService(db, budget, provider, clock, ids, settings, config, finality)


__all__ = [
    "HUMAN_WAIT_STATES",
    "LIVE_LEASE_STATES",
    "LeaseHandle",
    "LeaseService",
    "PodLeaseClaimRequest",
    "PodLeaseConfig",
    "ShutdownResult",
    "TERMINAL_LEASE_STATES",
    "accrue_lease_usage",
    "build_lease_service",
    "client_token_for",
    "human_wait_guard",
    "mock_pod_price",
    "settle_reservation_for_lease",
]
