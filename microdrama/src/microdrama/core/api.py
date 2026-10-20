"""Core HTTP routes (SPEC §4.3): episode events, internal job enqueue and job status.

Exported factory only. The integrator registers the router in ``microdrama.api``.

Kind policy (one allow-list each, in ``core.auth``):
- ``POST /internal/jobs`` admits ``OPERATOR_KINDS`` (SERVICE_WORKER, SCHEDULER) and only the job
  types in ``contracts.jobs.API_ENQUEUEABLE_JOB_TYPES``. Anything else is 403 POLICY_DENIED before the
  payload is validated. Gate-dependent jobs (publish.*, render, submission) are enqueued in-process
  by their owning service. Runtime models only propose; provider webhooks enqueue through their own
  verified ``/webhooks`` route.
- ``GET /internal/jobs/{id}`` admits ``OPERATOR_KINDS``.
- ``GET /episodes/{id}/events`` admits ``OWNER_OR_OPERATOR_KINDS`` (a HUMAN_OWNER session plus the
  operators). The outbox holds approval decisions, so models and webhooks may not read it.
Any other kind is 403 ``POLICY_DENIED``; authentication failures stay 401.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from microdrama.contracts.errors import NotFound, PolicyDenied, SchemaInvalid
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.jobs import API_ENQUEUEABLE_JOB_TYPES, JOB_SPECS_BY_TYPE
from microdrama.contracts.principals import Principal
from microdrama.contracts.routes import (
    CommandAccepted,
    EventsView,
    JobEnqueueRequest,
    JobStatusView,
)
from microdrama.core.auth import OPERATOR_KINDS, OWNER_OR_OPERATOR_KINDS, require_principal_kind
from microdrama.core.events import list_events
from microdrama.core.http import Dependency
from microdrama.core.idempotency import IdempotencyService
from microdrama.core.jobs import JobService
from microdrama.persistence.db import Database

ENQUEUE_SCOPE = "POST /internal/jobs"


def build_router(
    *,
    db: Database,
    jobs: JobService,
    idempotency: IdempotencyService,
    human_or_service: Dependency,
    service: Dependency,
) -> APIRouter:
    """Routes owned by core. ``human_or_service`` and ``service`` are FastAPI dependencies."""
    router = APIRouter()

    @router.get("/episodes/{episode_id}/events", response_model=EventsView, status_code=200)
    def episode_events(
        episode_id: UUID,
        principal: Annotated[Principal, Depends(human_or_service)],
    ) -> EventsView:
        require_principal_kind(
            principal,
            OWNER_OR_OPERATOR_KINDS,
            action="read the event outbox",
            error=PolicyDenied,
        )
        with db.transaction(readonly=True) as tx:
            if tx.fetchone("SELECT id FROM episodes WHERE id = %s", (episode_id,)) is None:
                raise NotFound(f"episode {episode_id} not found")
            events = list_events(tx, episode_id)
        return EventsView(aggregate_id=episode_id, events=events)

    @router.post("/internal/jobs", status_code=202)
    def enqueue_job(
        body: JobEnqueueRequest,
        principal: Annotated[Principal, Depends(service)],
    ) -> JSONResponse:
        require_principal_kind(
            principal,
            OPERATOR_KINDS,
            action="enqueue jobs directly",
            error=PolicyDenied,
        )
        # Closed list (contract 1.4.0): gate-dependent work such as publish.* is enqueued only
        # in-process by the service that owns its precondition. Refused before payload validation.
        if body.job_type not in API_ENQUEUEABLE_JOB_TYPES:
            raise PolicyDenied(
                "this job type cannot be enqueued through the API",
                job_type=body.job_type,
            )
        spec = JOB_SPECS_BY_TYPE.get(body.job_type)
        if spec is None:
            raise SchemaInvalid(f"unknown job type {body.job_type!r}")
        try:
            payload = spec.input_model.model_validate(body.input)
        except ValidationError as exc:
            raise SchemaInvalid(
                f"input does not match {spec.input_model.__name__}",
                errors=[{"loc": list(e["loc"]), "type": e["type"]} for e in exc.errors()],
            ) from exc
        input_episode = getattr(payload, "episode_id", None)
        if (
            body.episode_id is not None
            and input_episode is not None
            and input_episode != body.episode_id
        ):
            raise SchemaInvalid("the envelope episode_id must match the job input's episode_id")
        episode_id = body.episode_id or input_episode
        request_hash = canonical_hash(
            {
                "job_type": spec.job_type,
                "semantic_key": body.semantic_key,
                "input": payload.model_dump(mode="json"),
                "episode_id": episode_id,
                "correlation_id": body.correlation_id,
            }
        )

        def action(tx):
            result = jobs.enqueue(
                tx,
                job_type=spec.job_type,
                semantic_key=body.semantic_key,
                payload=payload,
                episode_id=episode_id,
                correlation_id=body.correlation_id,
            )
            if result.created:
                accepted = CommandAccepted(status="QUEUED", job_id=result.job_id)
                return 202, accepted.model_dump(mode="json")
            # The same semantic command was already accepted under another key.
            replayed = CommandAccepted(status="REPLAYED", job_id=result.job_id)
            return 200, replayed.model_dump(mode="json")

        outcome = idempotency.execute(
            scope=ENQUEUE_SCOPE,
            key=body.idempotency_key,
            principal_id=principal.principal_id,
            request_hash=request_hash,
            action=action,
        )
        content = dict(outcome.body)
        status_code = outcome.status_code
        if outcome.replayed:
            content["status"] = "REPLAYED"
            status_code = 200
        return JSONResponse(status_code=status_code, content=content)

    @router.get("/internal/jobs/{job_id}", response_model=JobStatusView, status_code=200)
    def job_status(
        job_id: UUID,
        principal: Annotated[Principal, Depends(service)],
    ) -> JobStatusView:
        require_principal_kind(
            principal,
            OPERATOR_KINDS,
            action="read job status",
            error=PolicyDenied,
        )
        return jobs.status_view(job_id)

    return router


__all__ = ["ENQUEUE_SCOPE", "build_router"]
