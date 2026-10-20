"""Public surface of core (T004): names, keyword-only signatures and protocol conformance.

Other lanes import these names. A drift here breaks them, so it fails loudly in this test.
"""

from __future__ import annotations

import inspect
import typing

from microdrama.contracts.enums import PrincipalKind
from microdrama.contracts.infra import Clock, IdGenerator
from microdrama.core import (
    approvals,
    auth,
    clock,
    events,
    hooks,
    http,
    idempotency,
    jobs,
    provider_ops,
    state_machine,
)
from microdrama.core.api import build_router


def _params(fn) -> dict[str, inspect.Parameter]:
    return dict(inspect.signature(fn).parameters)


def _kinds(fn) -> dict[str, str]:
    return {name: p.kind.name for name, p in _params(fn).items()}


def test_clock_and_ids_implement_the_infra_protocols() -> None:
    assert isinstance(clock.SystemClock(), Clock)
    assert isinstance(clock.UuidIds(), IdGenerator)


def test_outbox_signatures() -> None:
    sig = _kinds(events.append_event)
    assert sig == {
        "tx": "POSITIONAL_OR_KEYWORD",
        "aggregate_type": "KEYWORD_ONLY",
        "aggregate_id": "KEYWORD_ONLY",
        "event_type": "KEYWORD_ONLY",
        "payload": "KEYWORD_ONLY",
        "correlation_id": "KEYWORD_ONLY",
        "occurred_at": "KEYWORD_ONLY",
        "causation_id": "KEYWORD_ONLY",
        "event_id": "KEYWORD_ONLY",
    }
    assert _params(events.append_event)["causation_id"].default is None
    assert _params(events.list_events).keys() == {"tx", "aggregate_id"}
    dispatch = _params(events.OutboxDispatcher.__init__)
    assert (
        dispatch["transport"].kind.name == "KEYWORD_ONLY"
        and dispatch["publish"].kind.name == "KEYWORD_ONLY"
    )
    assert _params(events.OutboxDispatcher.dispatch_pending)["limit"].default == 100
    assert list(_params(events.consume_once)) == ["tx", "consumer", "event_id"]


def test_state_machine_signatures_match_the_brief() -> None:
    season = _params(state_machine.transition_season)
    assert list(season) == [
        "tx",
        "season_id",
        "to",
        "expected_revision",
        "actor",
        "now",
        "correlation_id",
        "approval_event_id",
        "scope_version",
        "reason",
    ]
    assert all(season[n].kind.name == "KEYWORD_ONLY" for n in list(season)[1:])
    episode = _params(state_machine.transition_episode)
    assert list(episode) == [
        "tx",
        "episode_id",
        "to",
        "expected_revision",
        "actor",
        "now",
        "correlation_id",
        "approval_event_id",
        "reason",
        "guards",
    ]
    outcome = _params(state_machine.set_episode_outcome)
    assert {
        "episode_id",
        "outcome",
        "expected_revision",
        "actor",
        "now",
        "correlation_id",
        "detail",
    } <= set(outcome)
    assert outcome["approval_event_id"].default is None
    clear = _params(state_machine.clear_episode_outcome)
    assert set(clear) == {
        "tx",
        "episode_id",
        "expected_revision",
        "actor",
        "now",
        "correlation_id",
        "evidence",
    }


def test_hook_protocols_are_runtime_checkable() -> None:
    class Guard:
        def __call__(self, tx, entity_row, target) -> None:
            return None

    class Hook:
        def on_recorded(self, tx, *, approval_event_id, command, principal) -> None:
            return None

    assert isinstance(Guard(), hooks.TransitionGuard)
    assert isinstance(Hook(), hooks.ApprovalHook)
    assert not isinstance(object(), hooks.ApprovalHook)


def test_job_outcome_union_is_exactly_the_five_handler_outcomes() -> None:
    members = set(typing.get_args(jobs.JobOutcome))
    assert members == {
        jobs.Succeeded,
        jobs.WaitExternal,
        jobs.RetryLater,
        jobs.Failed,
        jobs.NeedsReconciliation,
    }


def test_job_service_surface() -> None:
    assert list(_params(jobs.JobService.enqueue)) == [
        "self",
        "tx",
        "job_type",
        "semantic_key",
        "payload",
        "episode_id",
        "season_id",
        "correlation_id",
        "causation_id",
        "run_after",
        "max_attempts",
        "priority",
    ]
    assert _params(jobs.JobService.claim)["lease_ms"].kind.name == "KEYWORD_ONLY"
    assert _params(jobs.JobService.finish)["outcome"].kind.name == "KEYWORD_ONLY"
    for name in (
        "heartbeat",
        "requeue_expired",
        "resolve_reconciliation",
        "cancel",
        "get",
        "status_view",
        "lease_guard",
    ):
        assert hasattr(jobs.JobService, name), name
    resolve = _params(jobs.JobService.resolve_reconciliation)
    assert {"resolution", "evidence"} <= set(resolve)


def test_provider_operation_and_idempotency_surface() -> None:
    begin = _params(provider_ops.begin)
    assert {"provider", "operation_kind", "client_token", "request_hash", "deadline_at"} <= set(
        begin
    )
    assert all(begin[n].kind.name == "KEYWORD_ONLY" for n in ("provider", "client_token"))
    assert list(_params(provider_ops.record_result))[:3] == ["tx", "operation_id", "result"]
    assert list(_params(provider_ops.needs_reconcile))[0] == "op"
    assert list(_params(provider_ops.resubmit_allowed))[:2] == ["tx", "operation_id"]
    execute = _params(idempotency.IdempotencyService.execute)
    assert list(execute) == ["self", "scope", "key", "principal_id", "request_hash", "action"]
    assert all(execute[n].kind.name == "KEYWORD_ONLY" for n in list(execute)[1:])


def test_auth_surface_and_secret_helpers() -> None:
    for name in (
        "create_owner",
        "login",
        "authenticate_session",
        "verify_csrf",
        "revoke_session",
        "issue_service_credential",
        "authenticate_service",
        "owner_id_of",
    ):
        assert hasattr(auth.AuthService, name), name
    assert _params(auth.AuthService.__init__)["session_ttl"].default is not inspect.Parameter.empty
    assert (
        callable(auth.hash_secret) and callable(auth.verify_secret) and callable(auth.token_digest)
    )
    assert callable(auth.require_human_owner)
    assert PrincipalKind.HUMAN_OWNER.value == "HUMAN_OWNER"


def test_approval_recorder_signature() -> None:
    sig = _params(approvals.record_approval_event)
    assert list(sig) == ["tx", "principal", "command", "now", "correlation_id", "hooks"]
    assert sig["hooks"].default == ()
    assert all(sig[n].kind.name == "KEYWORD_ONLY" for n in list(sig)[1:])


def test_http_dependency_factories_and_router_factory() -> None:
    for factory in (
        http.human_session_dependency,
        http.service_dependency,
        http.human_or_service_dependency,
    ):
        assert list(_params(factory)) == ["auth"]
    assert http.SESSION_COOKIE == "md_session"
    assert http.CSRF_HEADER == "X-CSRF-Token"
    assert list(_params(build_router)) == [
        "db",
        "jobs",
        "idempotency",
        "human_or_service",
        "service",
    ]
    assert all(_params(build_router)[n].kind.name == "KEYWORD_ONLY" for n in _params(build_router))
