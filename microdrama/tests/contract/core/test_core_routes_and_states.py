"""Core's HTTP routes match the frozen route table; core enforces the frozen state tables."""

from __future__ import annotations

import typing

import pytest
from fastapi import APIRouter

from microdrama.contracts import states as frozen
from microdrama.contracts.enums import JobStatus
from microdrama.contracts.events import DomainEvent
from microdrama.contracts.routes import ROUTES
from microdrama.core import state_machine
from microdrama.core.api import build_router
from microdrama.core.http import human_or_service_dependency, service_dependency


def _named(name: str):
    """A stand-in dependency. The router only stores it; it is never called while building."""

    def dependency(*args, **kwargs):  # pragma: no cover - must not run at build time
        raise AssertionError("dependencies must not run while building the router")

    dependency.__name__ = name
    return dependency


@pytest.fixture(scope="module")
def router() -> APIRouter:
    return build_router(
        db=None,
        jobs=None,
        idempotency=None,
        human_or_service=_named("human_or_service"),
        service=_named("service"),
    )


def _route_map(router: APIRouter) -> dict[tuple[str, str], object]:
    out = {}
    for route in router.routes:
        for method in route.methods:
            out[(method, route.path)] = route
    return out


CORE_ROUTES = [r for r in ROUTES if r.owner_module == "core"]


def test_core_owns_exactly_the_three_documented_routes() -> None:
    assert {(r.method, r.path) for r in CORE_ROUTES} == {
        ("GET", "/episodes/{episode_id}/events"),
        ("POST", "/internal/jobs"),
        ("GET", "/internal/jobs/{job_id}"),
    }


def test_every_core_route_is_registered_with_a_contract_success_status(router) -> None:
    mapped = _route_map(router)
    for spec in CORE_ROUTES:
        route = mapped[(spec.method, spec.path)]
        assert route.status_code in spec.success_statuses, spec.path


def test_auth_channels_follow_the_route_table(router) -> None:
    mapped = _route_map(router)
    for spec in CORE_ROUTES:
        route = mapped[(spec.method, spec.path)]
        dependencies = [d.call for d in route.dependant.dependencies]
        if spec.auth.name == "HUMAN_OR_SERVICE":
            assert "human_or_service" in {getattr(d, "__name__", "") for d in dependencies}
        elif spec.auth.name == "SERVICE_TOKEN":
            assert "service" in {getattr(d, "__name__", "") for d in dependencies}
            assert "human_session" not in {getattr(d, "__name__", "") for d in dependencies}


def test_human_or_service_and_service_factories_build_distinct_callables() -> None:
    class _Auth:
        pass

    assert human_or_service_dependency(_Auth()) is not service_dependency(_Auth())


def test_core_enforces_the_frozen_tables_by_identity() -> None:
    """No copies of the transition tables: core uses the contract's objects."""
    assert state_machine.SEASON_TRANSITIONS is frozen.SEASON_TRANSITIONS
    assert state_machine.EPISODE_TRANSITIONS is frozen.EPISODE_TRANSITIONS
    assert state_machine.SEASON_HUMAN_ONLY is frozen.SEASON_HUMAN_ONLY
    assert state_machine.EPISODE_HUMAN_ONLY is frozen.EPISODE_HUMAN_ONLY
    assert state_machine.EPISODE_REVISION_TARGETS is frozen.EPISODE_REVISION_TARGETS
    assert state_machine.TERMINAL_OUTCOMES is frozen.TERMINAL_OUTCOMES
    assert state_machine.RECOVERABLE_OUTCOMES is frozen.RECOVERABLE_OUTCOMES
    assert state_machine.HUMAN_ONLY_OUTCOMES is frozen.HUMAN_ONLY_OUTCOMES


def test_job_transitions_cover_every_status() -> None:
    assert set(frozen.JOB_TRANSITIONS) == set(JobStatus)
    assert frozen.JOB_TRANSITIONS[JobStatus.SUCCEEDED] == frozenset()
    assert frozen.JOB_TRANSITIONS[JobStatus.FAILED] == frozenset()
    assert frozen.JOB_TRANSITIONS[JobStatus.CANCELLED] == frozenset()
    # Only a reconciliation step may leave NEEDS_RECONCILIATION, and never to a silent success path.
    assert frozen.JOB_TRANSITIONS[JobStatus.NEEDS_RECONCILIATION] == frozenset(
        {JobStatus.RUNNING, JobStatus.SUCCEEDED, JobStatus.FAILED}
    )


@pytest.mark.parametrize(
    "event_type",
    [
        "season.state_changed",
        "episode.state_changed",
        "episode.outcome_set",
        "episode.outcome_cleared",
        "approval.recorded",
        "job.enqueued",
        "job.claimed",
        "provider_operation.state_changed",
        *[f"job.{status.value.lower()}" for status in JobStatus],
    ],
)
def test_every_event_core_emits_is_a_valid_contract_event_type(event_type: str) -> None:
    event = DomainEvent(
        event_id="00000000-0000-4000-8000-000000000001",
        event_type=event_type,
        aggregate_type="episode",
        aggregate_id="00000000-0000-4000-8000-000000000002",
        sequence=1,
        correlation_id="00000000-0000-4000-8000-000000000003",
        occurred_at="2026-10-20T09:00:00+00:00",
        payload={"from": "A", "to": "B"},
    )
    assert event.event_type == event_type


def test_outcome_union_and_hook_names_are_stable() -> None:
    from microdrama.core import hooks, jobs

    assert set(typing.get_args(jobs.JobOutcome)) == {
        jobs.Succeeded,
        jobs.WaitExternal,
        jobs.RetryLater,
        jobs.Failed,
        jobs.NeedsReconciliation,
    }
    assert hooks.TransitionGuard.__name__ == "TransitionGuard"
    assert hooks.ApprovalHook.__name__ == "ApprovalHook"
