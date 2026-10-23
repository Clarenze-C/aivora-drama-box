"""Workers lane (T028): queue-isolated worker runtime, shared throttles, janitor.

Consumes only frozen surfaces: ``core.jobs.JobService`` (durable jobs, leased
claims, typed outcomes, NEEDS_RECONCILIATION semantics), ``contracts.jobs``
JOB_SPECS routing, the ``contracts.infra.RateLimiter`` protocol and the real
``BudgetService`` queue-ownership rules. No routers, no contracts changes, no
migrations; deployment configuration stays integrator-owned.
"""

from __future__ import annotations

from .janitor import JanitorReport, JanitorStep, WorkersJanitor, build_janitor
from .limiter import ProviderLimit, SharedRateLimiter, limiter_key
from .runtime import (
    GPU_EXCLUSIVE_TYPES,
    CycleReport,
    QueueSlots,
    RunReport,
    WorkerDeployment,
    WorkerRuntime,
    counting_handler,
    effect_once_handler,
)

__all__ = [
    "GPU_EXCLUSIVE_TYPES",
    "CycleReport",
    "JanitorReport",
    "JanitorStep",
    "ProviderLimit",
    "QueueSlots",
    "RunReport",
    "SharedRateLimiter",
    "WorkersJanitor",
    "WorkerDeployment",
    "WorkerRuntime",
    "build_janitor",
    "counting_handler",
    "effect_once_handler",
    "limiter_key",
]
