"""Job handlers for the two frozen analytics job specs (T027).

``workers/`` (T028) registers these against ``JOB_SPECS``; nothing here starts
threads, opens sockets or decides queues — the job specs already pin
``analytics.snapshot`` and ``analytics.qualification`` to the community queue.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from microdrama.contracts.errors import MicrodramaError, NotFound
from microdrama.core.jobs import (
    Failed,
    JobContext,
    JobOutcome,
    Succeeded,
    WaitExternal,
)

from .service import AnalyticsService

Handler = Callable[[JobContext], JobOutcome]


def _snapshot_handler(service: AnalyticsService) -> Handler:
    from microdrama.contracts.jobs import MetricWindowInput

    def handle(context: JobContext) -> JobOutcome:
        payload = context.payload
        assert isinstance(payload, MetricWindowInput)  # spec-pinned input model
        try:
            summary = service.run_snapshot_job(payload)
        except (NotFound, ValueError) as error:
            # An early or unknown window is a bad request, not a retryable fault.
            return Failed(error_code=type(error).__name__, detail=str(error))
        if summary["status"] == "WAITING_EXTERNAL":
            return WaitExternal(
                external_id=f"insights:{payload.platform_post_id}:{payload.window.value}",
                poll_after_ms=60 * 60 * 1000,
            )
        return Succeeded(result=summary)

    return handle


def _qualification_handler(service: AnalyticsService) -> Handler:
    from microdrama.contracts.jobs import SeasonStepInput

    def handle(context: JobContext) -> JobOutcome:
        payload = context.payload
        assert isinstance(payload, SeasonStepInput)
        result = service.run_qualification_job(payload)
        return Succeeded(
            result={
                "run_id": str(result.run_id),
                "production_status": result.production_status.value,
                "management_status": result.management_status.value,
                "consecutive": result.consecutive_qualifying_production,
                "successful_episodes": result.successful_episodes,
            }
        )

    return handle


def analytics_handlers(service: AnalyticsService) -> Mapping[str, Handler]:
    """The analytics slice of the worker handler registry (T028 composes this)."""
    return {
        "analytics.snapshot": _snapshot_handler(service),
        "analytics.qualification": _qualification_handler(service),
    }


# Retrying a qualification run is harmless (append-only runs); a snapshot job
# that raises a MicrodramaError fails its attempt rather than retrying blind.
def failure_outcome(error: MicrodramaError) -> JobOutcome:
    return Failed(error_code=type(error).__name__, detail=str(error))


__all__ = ["Handler", "analytics_handlers", "failure_outcome"]
