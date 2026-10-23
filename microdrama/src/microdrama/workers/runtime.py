"""The worker runtime: reserved concurrency, shared throttles, GPU ownership (T028).

Builds on the frozen ``JobService`` (durable jobs, leased claims, typed
outcomes) and the frozen ``JOB_SPECS`` routing — this module never chooses a
queue for a job and never re-implements a gate. Truth rules (IMP-06, MD-013):

- **Reserved concurrency per queue.** One ``run_cycle`` visits every queue the
  deployment serves and executes at most ``slots`` jobs per queue. A comment
  flood can fill the community slots of every cycle; the publication and
  production slots are structurally separate and are visited in the same
  cycle, so due releases keep moving (AT-08). Slots are admission counts, not
  threads — the runtime is single-threaded and synchronous by house rule.
- **The shared limiter gates provider-bound job types before the handler.**
  A ``bindings`` entry maps a job type to the job-input field carrying its
  shared-bucket key. A denial finishes the job as ``RetryLater`` with the
  limiter's own ``retry_after_ms`` — the handler never runs, and the next
  claim re-acquires from scratch: a retry cannot bypass the limiter. (By
  frozen ``JobService`` semantics each re-claim consumes an attempt —
  deployments size ``max_attempts`` so a rate wait cannot exhaust a healthy
  job; that truth is pinned in tests, not hidden.)
- **Initial one-episode GPU ownership.** While a lease-held ``render.shot``
  for an episode is RUNNING, another render for the same episode defers — one
  episode owns the pipeline's GPU window at a time (the rendering lane's
  pod-lease ownership sits underneath as the paid-side backstop).
- **Crashes resume without duplicate effects.** A worker that dies mid-job
  leaves the lease to expire; the janitor requeues it, and job semantic keys
  plus handler idempotency keep the effect once. The runtime never repeats an
  ambiguous provider operation itself — that is NEEDS_RECONCILIATION
  territory, owned by the frozen job service.
- **Capability pinning decision (open item from the T025/T026 wave):**
  ``CommunityProvider`` has no capability surface, so the runtime does NOT
  invent one. Community job admission stays exactly what the frozen specs and
  the community service's own policy gates allow; real platform COMMENT_*
  capability pinning waits for T032's account qualification, where capability
  evidence exists. Recorded here so the decision is findable.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from microdrama.contracts.enums import JobStatus, QueueName
from microdrama.contracts.errors import DuplicateSemanticKey, MicrodramaError, SchemaInvalid
from microdrama.contracts.infra import Clock, RateLimiter
from microdrama.core.jobs import (
    Failed,
    Job,
    JobContext,
    JobOutcome,
    JobService,
    RetryLater,
    Succeeded,
)
from microdrama.persistence.db import Database

# Job types whose paid GPU work makes episodes mutually exclusive initially.
GPU_EXCLUSIVE_TYPES: frozenset[str] = frozenset({"render.shot"})

#: A handler receives the claimed job with its validated input and returns a
#: typed outcome for the frozen job service to record (same shape T027 uses).
Handler = Callable[["JobContext"], "JobOutcome"]


@dataclass(frozen=True)
class QueueSlots:
    """Reserved concurrency for one queue inside one deployment."""

    queue: QueueName
    slots: int

    def __post_init__(self) -> None:
        if self.slots < 1:
            raise SchemaInvalid("a queue reservation needs at least one slot")


@dataclass(frozen=True)
class WorkerDeployment:
    """Deployment definition the integrator owns: queues, slots, handlers, bindings.

    ``name`` identifies the worker process in leases. Handlers are frozen
    job-type callables (e.g. T027's ``analytics_handlers``); ``bindings`` maps
    a job type to the input field that carries its shared limiter key.
    """

    name: str
    slots: tuple[QueueSlots, ...]
    handlers: Mapping[str, Handler]
    limiter: RateLimiter | None = None
    bindings: Mapping[str, str] = field(default_factory=dict)
    lease_ms: int = 300_000

    def slots_for(self, queue: QueueName) -> int:
        for slot in self.slots:
            if slot.queue is queue:
                return slot.slots
        return 0


@dataclass(frozen=True)
class RunReport:
    """What one execution did — evidence for tests and operators."""

    queue: QueueName
    job_id: UUID
    job_type: str
    action: str  # EXECUTED | FAILED | RATE_DEFERRED | GPU_DEFERRED
    detail: str = ""


@dataclass(frozen=True)
class CycleReport:
    """One pass over every reserved queue."""

    reports: tuple[RunReport, ...] = ()
    idle_queues: tuple[QueueName, ...] = ()


class WorkerRuntime:
    """Claim→throttle→execute→finish for one deployment."""

    def __init__(
        self,
        jobs: JobService,
        db: Database,
        clock: Clock,
        deployment: WorkerDeployment,
    ) -> None:
        self._jobs = jobs
        self._db = db
        self._clock = clock
        self._deployment = deployment

    # --- cycles -------------------------------------------------------------------------

    def run_cycle(self, *, now: datetime | None = None) -> CycleReport:
        """Every reserved queue gets its slots this cycle, in declaration order.

        This is the anti-starvation guarantee: a deep community backlog cannot
        push a due publication job behind it, because each cycle serves every
        queue's reservation before the next cycle starts.
        """
        instant = now or self._clock.now()
        reports: list[RunReport] = []
        idle: list[QueueName] = []
        for slot in self._deployment.slots:
            served = 0
            for _ in range(slot.slots):
                job = self._jobs.claim(
                    slot.queue,
                    worker_id=self._deployment.name,
                    lease_ms=self._deployment.lease_ms,
                    now=instant,
                )
                if job is None:
                    break
                reports.append(self._execute(job, now=instant))
                served += 1
            if served == 0:
                idle.append(slot.queue)
        return CycleReport(reports=tuple(reports), idle_queues=tuple(idle))

    def run_cycles(
        self, *, max_cycles: int = 100, now: datetime | None = None
    ) -> list[CycleReport]:
        """Run cycles until every queue is idle or ``max_cycles`` is reached."""
        cycles: list[CycleReport] = []
        for _ in range(max_cycles):
            cycle = self.run_cycle(now=now)
            cycles.append(cycle)
            if len(cycle.idle_queues) == len(self._deployment.slots):
                break
        return cycles

    # --- execution ------------------------------------------------------------------------

    def _execute(self, job: Job, *, now: datetime) -> RunReport:
        defer = self._throttle(job)
        if defer is None and self._episode_gpu_busy(job):
            defer = RetryLater(error_code="GPU_EPISODE_BUSY", retry_after_ms=5_000)
        if defer is not None:
            action = "GPU_DEFERRED" if defer.error_code == "GPU_EPISODE_BUSY" else "RATE_DEFERRED"
            self._finish(job, defer, now=now)
            return RunReport(job.queue, job.id, job.job_type, action, defer.error_code)
        handler = self._deployment.handlers.get(job.job_type)
        if handler is None:
            outcome = Failed(
                error_code="NO_HANDLER",
                detail=f"deployment {self._deployment.name} has no handler for {job.job_type}",
            )
        else:
            context = self._jobs.context(job, self._deployment.name)
            try:
                outcome = handler(context)
            except MicrodramaError as error:
                outcome = Failed(error_code=error.code, detail=error.message)
            except Exception as error:  # a handler bug fails the attempt, never the worker
                outcome = Failed(error_code=type(error).__name__, detail=str(error)[:500])
        self._finish(job, outcome, now=now)
        if isinstance(outcome, Failed):
            action, detail = "FAILED", outcome.error_code
        elif isinstance(outcome, RetryLater):
            action, detail = "RATE_DEFERRED", outcome.error_code
        else:
            action, detail = "EXECUTED", type(outcome).__name__
        return RunReport(job.queue, job.id, job.job_type, action, detail)

    def _throttle(self, job: Job) -> RetryLater | None:
        """Shared-bucket admission for bound job types; None means run."""
        if self._deployment.limiter is None:
            return None
        key_field = self._deployment.bindings.get(job.job_type)
        if key_field is None:
            return None
        key = str(job.input.get(key_field, "")) if isinstance(job.input, dict) else ""
        if not key:
            raise SchemaInvalid(
                "limiter binding field missing from job input",
                job_type=job.job_type,
                field=key_field,
            )
        decision = self._deployment.limiter.try_acquire(key)
        if decision.allowed:
            return None
        return RetryLater(
            error_code="RATE_LIMITED",
            retry_after_ms=decision.retry_after_ms or 1_000,
        )

    def _episode_gpu_busy(self, job: Job) -> bool:
        """True while another lease-held render of the same episode is RUNNING."""
        if job.job_type not in GPU_EXCLUSIVE_TYPES or job.episode_id is None:
            return False
        with self._db.transaction(readonly=True) as tx:
            other = tx.fetchone(
                "SELECT id FROM jobs WHERE job_type = %s AND episode_id = %s "
                "AND status = %s AND id <> %s LIMIT 1",
                (job.job_type, job.episode_id, JobStatus.RUNNING.value, job.id),
            )
        return other is not None

    def _finish(self, job: Job, outcome: JobOutcome, *, now: datetime) -> None:
        self._jobs.finish(job.id, worker_id=self._deployment.name, outcome=outcome, now=now)


# --- helper handlers for deployments ----------------------------------------------------


def counting_handler(counter: dict[str, int], key: str) -> Handler:
    """A deterministic handler that records executions per key (tests/AT-08)."""

    def handle(context: JobContext) -> JobOutcome:
        counter[key] = counter.get(key, 0) + 1
        return Succeeded(result={"key": key})

    return handle


def effect_once_handler(
    db: Database,
    *,
    table: str,
    effect_key_column: str,
    effect_key: str,
) -> Handler:
    """A handler whose durable effect happens exactly once per key (crash tests).

    The effect row is UNIQUE on its key: the first run inserts it, any replay
    after a crash-resume sees the row and reports ``replayed`` — duplicate
    effects are structurally impossible, exactly like the real lanes' semantic
    keys.
    """

    def handle(context: JobContext) -> JobOutcome:
        from microdrama.persistence.db import insert_row

        try:
            with db.transaction() as tx:
                insert_row(
                    tx,
                    table,
                    {"id": context.job.id, effect_key_column: effect_key},
                    returning="id",
                )
        except DuplicateSemanticKey:
            return Succeeded(result={"effect": effect_key, "replayed": True})
        return Succeeded(result={"effect": effect_key, "replayed": False})

    return handle


__all__ = [
    "GPU_EXCLUSIVE_TYPES",
    "CycleReport",
    "QueueSlots",
    "RunReport",
    "WorkerDeployment",
    "WorkerRuntime",
    "counting_handler",
    "effect_once_handler",
]
