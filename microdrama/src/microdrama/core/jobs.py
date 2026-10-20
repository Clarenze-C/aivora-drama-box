"""Durable job queue on the ``jobs`` table: semantic-key enqueue, leased claims, typed outcomes.

Invariants:
- A job type, its queue and its input model come from ``contracts.jobs.JOB_SPECS``; callers cannot
  choose a queue, and input is validated against the spec's model before it is stored.
- Enqueue is idempotent on ``semantic_key``: the same type and input return the existing job; a
  different type or input is ``IdempotencyConflict``.
- A claim is one transaction that locks the row with ``FOR UPDATE SKIP LOCKED``. Two claimers never
  receive the same job. A QUEUED claim increments ``attempt``; polling a WAITING_EXTERNAL job does not.
- Only the worker holding an unexpired lease can finish, heartbeat or write a job's outcome.
- Every state change and its ``job.*`` outbox event commit in one transaction.
- Ambiguous external work is never blindly requeued: an expired lease with an in-flight
  provider operation goes to NEEDS_RECONCILIATION. Only an explicit reconciliation with evidence
  can resolve it, and never directly to SUCCEEDED from an automatic path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from microdrama.contracts.cost import ProviderOperationState
from microdrama.contracts.enums import JobStatus, QueueName
from microdrama.contracts.errors import (
    Conflict,
    IdempotencyConflict,
    InvalidTransition,
    NotFound,
    SchemaInvalid,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.infra import Clock, IdGenerator
from microdrama.contracts.jobs import JOB_SPECS_BY_TYPE
from microdrama.contracts.primitives import ContractModel
from microdrama.contracts.routes import JobStatusView
from microdrama.contracts.states import JOB_TRANSITIONS
from microdrama.core.events import append_event
from microdrama.persistence.db import Database, Tx, jsonb, update_with_revision

_MAX_TEXT = 2000
_MAX_LEASE_MS = 24 * 60 * 60 * 1000
_IN_FLIGHT_OPERATIONS = (
    ProviderOperationState.PENDING_SUBMIT.value,
    ProviderOperationState.SUBMITTED.value,
    ProviderOperationState.RUNNING.value,
    ProviderOperationState.UNKNOWN.value,
)


# --- outcomes a handler returns ---------------------------------------------------------


@dataclass(frozen=True)
class Succeeded:
    result: dict[str, Any]


@dataclass(frozen=True)
class WaitExternal:
    external_id: str
    poll_after_ms: int


@dataclass(frozen=True)
class RetryLater:
    error_code: str
    retry_after_ms: int


@dataclass(frozen=True)
class Failed:
    error_code: str
    detail: str = ""


@dataclass(frozen=True)
class NeedsReconciliation:
    detail: str
    external_id: str | None = None


JobOutcome = Succeeded | WaitExternal | RetryLater | Failed | NeedsReconciliation


# --- views ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Job:
    id: UUID
    job_type: str
    job_version: int
    queue: QueueName
    semantic_key: str
    input_hash: str
    input: dict[str, Any] = field(repr=False)
    status: JobStatus
    priority: int
    attempt: int
    max_attempts: int
    run_after: datetime
    lease_owner: str | None
    lease_expires_at: datetime | None
    heartbeat_at: datetime | None
    external_id: str | None
    outcome: dict[str, Any] | None
    error_code: str | None
    season_id: UUID | None
    episode_id: UUID | None
    correlation_id: UUID | None
    causation_id: UUID | None
    created_at: datetime
    updated_at: datetime
    revision: int


@dataclass(frozen=True)
class JobContext:
    job: Job
    worker_id: str
    payload: ContractModel


@dataclass(frozen=True)
class EnqueueResult:
    job_id: UUID
    created: bool


def _job(row: Mapping[str, Any]) -> Job:
    return Job(
        id=row["id"],
        job_type=row["job_type"],
        job_version=row["job_version"],
        queue=QueueName(row["queue"]),
        semantic_key=row["semantic_key"],
        input_hash=row["input_hash"],
        input=row["input"],
        status=JobStatus(row["status"]),
        priority=row["priority"],
        attempt=row["attempt"],
        max_attempts=row["max_attempts"],
        run_after=row["run_after"],
        lease_owner=row["lease_owner"],
        lease_expires_at=row["lease_expires_at"],
        heartbeat_at=row["heartbeat_at"],
        external_id=row["external_id"],
        outcome=row["outcome"],
        error_code=row["error_code"],
        season_id=row["season_id"],
        episode_id=row["episode_id"],
        correlation_id=row["correlation_id"],
        causation_id=row["causation_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        revision=row["revision"],
    )


# --- validation helpers -----------------------------------------------------------------


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchemaInvalid(f"{name} must be timezone-aware")
    return value


def _text(value: object, name: str, *, limit: int = _MAX_TEXT) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise SchemaInvalid(f"{name} must be a non-empty string of at most {limit} characters")
    return value


def _whole(value: object, name: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise SchemaInvalid(f"{name} must be an integer >= {minimum}")
    return value


def _lease_ms(value: object) -> int:
    lease = _whole(value, "lease_ms", minimum=1)
    if lease > _MAX_LEASE_MS:
        raise SchemaInvalid("lease_ms may not exceed 24 hours")
    return lease


def _worker(value: object) -> str:
    return _text(value, "worker_id", limit=200)


def _queue(value: QueueName | str) -> QueueName:
    try:
        return QueueName(value)
    except ValueError as exc:
        raise SchemaInvalid(f"unknown queue {value!r}") from exc


def _check_transition(current: JobStatus, target: JobStatus) -> None:
    if target not in JOB_TRANSITIONS.get(current, frozenset()):
        raise InvalidTransition(
            f"job {current.value} -> {target.value} is not allowed",
            from_state=current.value,
            to_state=target.value,
        )


def _finish_plan(
    row: Mapping[str, Any], outcome: JobOutcome, now: datetime
) -> tuple[JobStatus, dict[str, Any]]:
    """Target status and column changes for each handler outcome."""
    if isinstance(outcome, Succeeded):
        if not isinstance(outcome.result, dict):
            raise SchemaInvalid("Succeeded.result must be a JSON object")
        return JobStatus.SUCCEEDED, {
            "error_code": None,
            "outcome": {"kind": "SUCCEEDED", "result": outcome.result},
        }
    if isinstance(outcome, WaitExternal):
        external = _text(outcome.external_id, "external_id", limit=500)
        poll = _whole(outcome.poll_after_ms, "poll_after_ms")
        return JobStatus.WAITING_EXTERNAL, {
            "external_id": external,
            "run_after": now + timedelta(milliseconds=poll),
            "outcome": {"kind": "WAITING_EXTERNAL", "external_id": external, "poll_after_ms": poll},
        }
    if isinstance(outcome, RetryLater):
        code = _text(outcome.error_code, "error_code", limit=200)
        delay = _whole(outcome.retry_after_ms, "retry_after_ms")
        if row["attempt"] < row["max_attempts"]:
            return JobStatus.RETRY_WAIT, {
                "error_code": code,
                "run_after": now + timedelta(milliseconds=delay),
                "outcome": {"kind": "RETRY_LATER", "error_code": code, "retry_after_ms": delay},
            }
        final = f"MAX_ATTEMPTS:{code}"
        return JobStatus.FAILED, {
            "error_code": final,
            "outcome": {"kind": "FAILED", "error_code": final},
        }
    if isinstance(outcome, Failed):
        code = _text(outcome.error_code, "error_code", limit=200)
        detail = outcome.detail[:_MAX_TEXT] if isinstance(outcome.detail, str) else ""
        return JobStatus.FAILED, {
            "error_code": code,
            "outcome": {"kind": "FAILED", "error_code": code, "detail": detail},
        }
    if isinstance(outcome, NeedsReconciliation):
        detail = _text(outcome.detail, "detail")
        changes: dict[str, Any] = {
            "error_code": "NEEDS_RECONCILIATION",
            "outcome": {"kind": "NEEDS_RECONCILIATION", "detail": detail},
        }
        if outcome.external_id is not None:
            changes["external_id"] = _text(outcome.external_id, "external_id", limit=500)
        return JobStatus.NEEDS_RECONCILIATION, changes
    raise SchemaInvalid(f"unknown job outcome {type(outcome).__name__}")


class JobService:
    """Durable job operations. Each method runs in its own transaction unless given ``tx``."""

    def __init__(self, db: Database, clock: Clock, ids: IdGenerator) -> None:
        self._db = db
        self._clock = clock
        self._ids = ids

    # -- internals --------------------------------------------------------------------

    def _now(self, now: datetime | None) -> datetime:
        return _aware(now, "now") if now is not None else self._clock.now()

    @staticmethod
    def _lock(tx: Tx, job_id: UUID) -> dict[str, Any]:
        row = tx.fetchone("SELECT * FROM jobs WHERE id = %s FOR UPDATE", (job_id,))
        if row is None:
            raise NotFound(f"job {job_id} not found")
        return row

    @staticmethod
    def _emit(
        tx: Tx, row: Mapping[str, Any], event_type: str, now: datetime, payload: dict
    ) -> None:
        append_event(
            tx,
            aggregate_type="job",
            aggregate_id=row["id"],
            event_type=event_type,
            payload=payload,
            correlation_id=row["correlation_id"] or row["id"],
            causation_id=row["causation_id"],
            occurred_at=now,
        )

    def _move(
        self,
        tx: Tx,
        row: Mapping[str, Any],
        target: JobStatus,
        *,
        now: datetime,
        changes: dict[str, Any],
        event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Apply a validated status change: clear the lease, bump revision, emit ``job.<status>``."""
        current = JobStatus(row["status"])
        _check_transition(current, target)
        values: dict[str, Any] = {
            "status": target.value,
            "lease_owner": None,
            "lease_expires_at": None,
            "heartbeat_at": None,
        }
        values.update(changes)
        updated = update_with_revision(tx, "jobs", row["id"], row["revision"], values, now=now)
        payload = {
            "from": current.value,
            "to": target.value,
            "attempt": row["attempt"],
            "error_code": updated["error_code"],
        }
        payload.update(event or {})
        self._emit(tx, row, f"job.{target.value.lower()}", now, payload)
        return updated

    # -- enqueue ----------------------------------------------------------------------

    def enqueue(
        self,
        tx: Tx,
        *,
        job_type: str,
        semantic_key: str,
        payload: ContractModel,
        episode_id: UUID | None = None,
        season_id: UUID | None = None,
        correlation_id: UUID | None = None,
        causation_id: UUID | None = None,
        run_after: datetime | None = None,
        max_attempts: int = 3,
        priority: int = 100,
    ) -> EnqueueResult:
        """Insert a durable job inside ``tx``, or return the existing job for ``semantic_key``."""
        spec = JOB_SPECS_BY_TYPE.get(job_type)
        if spec is None:
            raise SchemaInvalid(f"unknown job type {job_type!r}")
        if type(payload) is not spec.input_model:
            raise SchemaInvalid(
                f"{job_type} expects {spec.input_model.__name__}, got {type(payload).__name__}"
            )
        key = _text(semantic_key, "semantic_key", limit=400)
        attempts = _whole(max_attempts, "max_attempts", minimum=1)
        if attempts > 10:
            raise SchemaInvalid("max_attempts may not exceed 10")
        _whole(priority, "priority")
        now = self._clock.now()
        when = _aware(run_after, "run_after") if run_after is not None else now
        input_hash = canonical_hash(payload)
        job_id = self._ids.new_id()

        inserted = tx.fetchone(
            "INSERT INTO jobs (id, job_type, job_version, queue, semantic_key, input_hash, input, "
            "status, priority, attempt, max_attempts, run_after, season_id, episode_id, "
            "correlation_id, causation_id, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'QUEUED', %s, 0, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (semantic_key) DO NOTHING "
            "RETURNING id, correlation_id, causation_id",
            (
                job_id,
                spec.job_type,
                spec.version,
                spec.queue.value,
                key,
                input_hash,
                jsonb(payload.model_dump(mode="json")),
                priority,
                attempts,
                when,
                season_id,
                episode_id,
                correlation_id or self._ids.new_id(),
                causation_id,
                now,
                now,
            ),
        )
        if inserted is not None:
            self._emit(
                tx,
                {
                    "id": job_id,
                    "correlation_id": inserted["correlation_id"],
                    "causation_id": inserted["causation_id"],
                },
                "job.enqueued",
                now,
                {"job_type": spec.job_type, "queue": spec.queue.value, "to": "QUEUED"},
            )
            return EnqueueResult(job_id=job_id, created=True)

        existing = tx.fetchone(
            "SELECT id, job_type, input_hash FROM jobs WHERE semantic_key = %s", (key,)
        )
        if existing is None:  # pragma: no cover - only if a concurrent delete were possible
            raise Conflict("semantic key changed during enqueue; retry")
        if existing["job_type"] != spec.job_type or existing["input_hash"] != input_hash:
            raise IdempotencyConflict(
                "semantic key was already used for a different job or input",
                semantic_key=key,
            )
        return EnqueueResult(job_id=existing["id"], created=False)

    # -- claim / heartbeat / lease ----------------------------------------------------

    def claim(
        self,
        queue: QueueName | str,
        *,
        worker_id: str,
        lease_ms: int,
        now: datetime | None = None,
    ) -> Job | None:
        """Lease the highest-priority due job on ``queue``; None when nothing is due."""
        target_queue = _queue(queue)
        worker = _worker(worker_id)
        lease = _lease_ms(lease_ms)
        instant = self._now(now)
        lease_until = instant + timedelta(milliseconds=lease)
        with self._db.transaction() as tx:
            due_retries = tx.fetchall(
                "SELECT * FROM jobs WHERE queue = %s AND status = 'RETRY_WAIT' AND run_after <= %s "
                "ORDER BY run_after FOR UPDATE SKIP LOCKED",
                (target_queue.value, instant),
            )
            for retry in due_retries:
                self._move(tx, retry, JobStatus.QUEUED, now=instant, changes={})

            row = tx.fetchone(
                "SELECT * FROM jobs WHERE queue = %s AND status IN ('QUEUED', 'WAITING_EXTERNAL') "
                "AND run_after <= %s ORDER BY priority, run_after, created_at "
                "LIMIT 1 FOR UPDATE SKIP LOCKED",
                (target_queue.value, instant),
            )
            if row is None:
                return None
            _check_transition(JobStatus(row["status"]), JobStatus.RUNNING)
            from_queued = row["status"] == JobStatus.QUEUED.value
            attempt = row["attempt"] + 1 if from_queued else row["attempt"]
            values = {
                "status": JobStatus.RUNNING.value,
                "lease_owner": worker,
                "lease_expires_at": lease_until,
                "heartbeat_at": instant,
                "attempt": attempt,
            }
            updated = update_with_revision(
                tx, "jobs", row["id"], row["revision"], values, now=instant
            )
            self._emit(
                tx,
                row,
                "job.claimed",
                instant,
                {
                    "from": row["status"],
                    "to": JobStatus.RUNNING.value,
                    "attempt": attempt,
                    "worker_id": worker,
                },
            )
            return _job(updated)

    def heartbeat(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        lease_ms: int,
        now: datetime | None = None,
    ) -> Job:
        """Extend a live lease. An expired lease cannot be revived."""
        worker = _worker(worker_id)
        lease = _lease_ms(lease_ms)
        instant = self._now(now)
        with self._db.transaction() as tx:
            row = self._lock(tx, job_id)
            if not self._holds_lease(row, worker, instant):
                raise Conflict("lease lost", job_id=str(job_id))
            updated = update_with_revision(
                tx,
                "jobs",
                job_id,
                row["revision"],
                {
                    "lease_expires_at": instant + timedelta(milliseconds=lease),
                    "heartbeat_at": instant,
                },
                now=instant,
            )
            return _job(updated)

    @staticmethod
    def _holds_lease(row: Mapping[str, Any], worker: str, instant: datetime) -> bool:
        return (
            row["status"] == JobStatus.RUNNING.value
            and row["lease_owner"] == worker
            and row["lease_expires_at"] is not None
            and row["lease_expires_at"] > instant
        )

    def lease_guard(
        self,
        tx: Tx,
        job_id: UUID,
        *,
        worker_id: str,
        now: datetime | None = None,
    ) -> None:
        """Prove inside ``tx`` that the worker still holds the lease.

        Takes a shared row lock, so a concurrent ``requeue_expired`` (which needs an exclusive
        lock) waits for ``tx`` to finish. Call it in the same transaction as any provider-operation
        ``begin``, so an ambiguous external submission is always visible to recovery.
        """
        worker = _worker(worker_id)
        instant = self._now(now)
        row = tx.fetchone(
            "SELECT * FROM jobs WHERE id = %s FOR SHARE",
            (job_id,),
        )
        if row is None:
            raise NotFound(f"job {job_id} not found")
        if not self._holds_lease(row, worker, instant):
            raise Conflict("lease lost", job_id=str(job_id))

    # -- finish -----------------------------------------------------------------------

    def finish(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        outcome: JobOutcome,
        now: datetime | None = None,
    ) -> Job:
        """Record the handler's outcome. Only the lease holder may finish; others get Conflict."""
        worker = _worker(worker_id)
        instant = self._now(now)
        with self._db.transaction() as tx:
            row = self._lock(tx, job_id)
            if not self._holds_lease(row, worker, instant):
                raise Conflict("lease lost", job_id=str(job_id), status=row["status"])
            target, changes = _finish_plan(row, outcome, instant)
            updated = self._move(tx, row, target, now=instant, changes=changes)
            return _job(updated)

    # -- recovery ---------------------------------------------------------------------

    def requeue_expired(self, now: datetime | None = None) -> int:
        """Recover RUNNING jobs whose lease expired. Returns how many changed."""
        instant = self._now(now)
        changed = 0
        with self._db.transaction() as tx:
            expired = tx.fetchall(
                "SELECT * FROM jobs WHERE status = 'RUNNING' AND lease_expires_at <= %s "
                "ORDER BY lease_expires_at FOR UPDATE SKIP LOCKED",
                (instant,),
            )
            for row in expired:
                in_flight = tx.fetchone(
                    "SELECT 1 AS present FROM provider_operations WHERE job_id = %s "
                    "AND state = ANY(%s) LIMIT 1",
                    (row["id"], list(_IN_FLIGHT_OPERATIONS)),
                )
                if in_flight is not None:
                    self._move(
                        tx,
                        row,
                        JobStatus.NEEDS_RECONCILIATION,
                        now=instant,
                        changes={
                            "error_code": "LEASE_EXPIRED",
                            "outcome": {
                                "kind": "NEEDS_RECONCILIATION",
                                "detail": "lease expired with an external operation in flight",
                            },
                        },
                    )
                elif row["attempt"] < row["max_attempts"]:
                    self._move(tx, row, JobStatus.QUEUED, now=instant, changes={})
                else:
                    self._move(
                        tx,
                        row,
                        JobStatus.FAILED,
                        now=instant,
                        changes={
                            "error_code": "LEASE_EXPIRED",
                            "outcome": {"kind": "FAILED", "error_code": "LEASE_EXPIRED"},
                        },
                    )
                changed += 1
        return changed

    def resolve_reconciliation(
        self,
        job_id: UUID,
        *,
        resolution: str,
        evidence: str,
        now: datetime | None = None,
        worker_id: str | None = None,
        lease_ms: int | None = None,
    ) -> Job:
        """Resolve a NEEDS_RECONCILIATION job with written evidence.

        ``RESUME`` returns it to RUNNING under a new lease (``worker_id`` and ``lease_ms`` required)
        and does not count as a new attempt. ``SUCCEEDED`` and ``FAILED`` are the only other ways
        out; no other path can mark the job SUCCEEDED.
        """
        if resolution not in ("RESUME", "SUCCEEDED", "FAILED"):
            raise SchemaInvalid("resolution must be RESUME, SUCCEEDED or FAILED")
        proof = _text(evidence, "evidence")
        instant = self._now(now)
        with self._db.transaction() as tx:
            row = self._lock(tx, job_id)
            if row["status"] != JobStatus.NEEDS_RECONCILIATION.value:
                raise InvalidTransition(
                    f"job is {row['status']}, not NEEDS_RECONCILIATION",
                    status=row["status"],
                )
            event = {"resolution": resolution, "evidence": proof}
            if resolution == "RESUME":
                worker = _worker(worker_id)
                lease = _lease_ms(lease_ms)
                updated = self._move(
                    tx,
                    row,
                    JobStatus.RUNNING,
                    now=instant,
                    changes={
                        "lease_owner": worker,
                        "lease_expires_at": instant + timedelta(milliseconds=lease),
                        "heartbeat_at": instant,
                    },
                    event=event,
                )
            elif resolution == "SUCCEEDED":
                updated = self._move(
                    tx,
                    row,
                    JobStatus.SUCCEEDED,
                    now=instant,
                    changes={
                        "error_code": None,
                        "outcome": {"kind": "SUCCEEDED", "reconciled": True, "evidence": proof},
                    },
                    event=event,
                )
            else:
                updated = self._move(
                    tx,
                    row,
                    JobStatus.FAILED,
                    now=instant,
                    changes={
                        "error_code": "RECONCILED_FAILED",
                        "outcome": {"kind": "FAILED", "reconciled": True, "evidence": proof},
                    },
                    event=event,
                )
            return _job(updated)

    def cancel(self, job_id: UUID, *, reason: str, now: datetime | None = None) -> Job:
        """Cancel a job that has not reached a terminal state (and is not awaiting reconciliation).

        Cancelling does not touch external work. A provider operation still in flight for this job
        (PENDING_SUBMIT, SUBMITTED, RUNNING or UNKNOWN) is left as it is: it is not cancelled,
        resubmitted or refunded here. It stays for reconciliation, and its budget reservation stays
        open until the reconciler settles it. A RUNNING holder loses its lease and its later
        ``finish`` is refused with ``Conflict``.
        """
        why = _text(reason, "reason")
        instant = self._now(now)
        with self._db.transaction() as tx:
            row = self._lock(tx, job_id)
            updated = self._move(
                tx,
                row,
                JobStatus.CANCELLED,
                now=instant,
                changes={
                    "error_code": "CANCELLED",
                    "outcome": {"kind": "CANCELLED", "reason": why},
                },
                event={"reason": why},
            )
            return _job(updated)

    # -- reads ------------------------------------------------------------------------

    def get(self, job_id: UUID) -> Job:
        with self._db.transaction(readonly=True) as tx:
            row = tx.fetchone("SELECT * FROM jobs WHERE id = %s", (job_id,))
        if row is None:
            raise NotFound(f"job {job_id} not found")
        return _job(row)

    def status_view(self, job_id: UUID) -> JobStatusView:
        job = self.get(job_id)
        return JobStatusView(
            job_id=job.id,
            job_type=job.job_type,
            queue=job.queue,
            status=job.status,
            attempt=job.attempt,
            external_id=job.external_id,
            error_code=job.error_code,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    @staticmethod
    def context(job: Job, worker_id: str) -> JobContext:
        """Pair a claimed job with its validated input model (what a handler receives)."""
        spec = JOB_SPECS_BY_TYPE.get(job.job_type)
        if spec is None:
            raise SchemaInvalid(f"unknown job type {job.job_type!r}")
        return JobContext(
            job=job,
            worker_id=worker_id,
            payload=spec.input_model.model_validate(job.input),
        )


__all__ = [
    "EnqueueResult",
    "Failed",
    "Job",
    "JobContext",
    "JobOutcome",
    "JobService",
    "NeedsReconciliation",
    "RetryLater",
    "Succeeded",
    "WaitExternal",
]
