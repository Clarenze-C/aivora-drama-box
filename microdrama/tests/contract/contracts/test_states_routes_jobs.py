from __future__ import annotations

import pytest
from pydantic import ValidationError

from microdrama.contracts import states
from microdrama.contracts.enums import (
    ApprovalAction,
    EpisodeState,
    GateType,
    JobStatus,
    PrincipalKind,
    QueueName,
    ReleaseState,
    RuntimeRole,
    SeasonState,
)
from microdrama.contracts.jobs import JOB_SPECS, JOB_SPECS_BY_TYPE
from microdrama.contracts.primitives import VersionedPayload
from microdrama.contracts.principals import Principal
from microdrama.contracts.routes import ROUTES, AuthKind


@pytest.mark.parametrize(
    ("table", "enum"),
    [
        (states.SEASON_TRANSITIONS, SeasonState),
        (states.EPISODE_TRANSITIONS, EpisodeState),
        (states.RELEASE_TRANSITIONS, ReleaseState),
        (states.JOB_TRANSITIONS, JobStatus),
    ],
)
def test_tables_cover_every_state(table, enum) -> None:
    assert set(table) == set(enum)
    for targets in table.values():
        assert set(targets) <= set(enum)


def test_episode_order_is_spec_linear() -> None:
    order = list(EpisodeState)
    for current, nxt in zip(order, order[1:], strict=False):
        assert nxt in states.EPISODE_TRANSITIONS[current]
    assert not states.EPISODE_TRANSITIONS[EpisodeState.MANAGED]


def test_release_approval_is_human_only_and_not_reachable_by_skipping() -> None:
    assert (
        EpisodeState.AWAITING_FINAL_REVIEW,
        EpisodeState.RELEASE_APPROVED,
    ) in states.EPISODE_HUMAN_ONLY
    for source, targets in states.EPISODE_TRANSITIONS.items():
        if EpisodeState.RELEASE_APPROVED in targets:
            assert source is EpisodeState.AWAITING_FINAL_REVIEW
    assert (SeasonState.PROPOSED, SeasonState.SEASON_APPROVED) in states.SEASON_HUMAN_ONLY


def test_revisions_return_to_production_not_new_gate() -> None:
    back = states.EPISODE_TRANSITIONS[EpisodeState.AWAITING_FINAL_REVIEW] - {
        EpisodeState.RELEASE_APPROVED
    }
    assert back == states.EPISODE_REVISION_TARGETS
    assert all(t not in {EpisodeState.AWAITING_FINAL_REVIEW, EpisodeState.AI_REVIEW} for t in back)


def test_budget_exhaustion_is_terminal_no_reset() -> None:
    from microdrama.contracts.enums import EpisodeOutcome

    assert EpisodeOutcome.BUDGET_EXHAUSTED in states.TERMINAL_OUTCOMES
    assert EpisodeOutcome.NEEDS_RECONCILIATION in states.RECOVERABLE_OUTCOMES


def test_reconciliation_never_jumps_straight_from_submitted_to_verified() -> None:
    assert ReleaseState.PUBLISHED_VERIFIED not in states.RELEASE_TRANSITIONS[ReleaseState.SUBMITTED]


def test_gate_actions() -> None:
    assert states.GATE_ACTIONS[GateType.SEASON_CONCEPT] == {
        ApprovalAction.APPROVE,
        ApprovalAction.REJECT,
    }
    assert ApprovalAction.REVISE in states.GATE_ACTIONS[GateType.EPISODE_FINAL]


def test_route_table_matches_spec_shapes() -> None:
    shapes = {(r.method, r.path) for r in ROUTES}
    expected = {
        ("GET", "/seasons/proposals"),
        ("GET", "/seasons/{season_id}"),
        ("POST", "/seasons/{season_id}/approval"),
        ("GET", "/episodes/{episode_id}/review"),
        ("POST", "/episodes/{episode_id}/review"),
        ("GET", "/episodes/{episode_id}/events"),
        ("GET", "/episodes/{episode_id}/costs"),
        ("GET", "/episodes/{episode_id}/releases"),
        ("POST", "/internal/jobs"),
        ("GET", "/internal/jobs/{job_id}"),
        ("POST", "/webhooks/{provider}"),
        ("GET", "/health"),
        ("GET", "/ready"),
    }
    assert shapes == expected
    for r in ROUTES:
        if r.path.endswith("/approval") or (r.method == "POST" and r.path.endswith("/review")):
            assert r.auth is AuthKind.HUMAN_SESSION  # gates are human-session only


def test_job_specs() -> None:
    assert len(JOB_SPECS_BY_TYPE) == len(JOB_SPECS)
    assert {s.queue for s in JOB_SPECS} == set(QueueName)
    for spec in JOB_SPECS:
        assert issubclass(spec.input_model, VersionedPayload), spec.job_type
    assert JOB_SPECS_BY_TYPE["render.shot"].paid
    assert JOB_SPECS_BY_TYPE["publish.submit_slot"].queue is QueueName.PUBLICATION
    assert JOB_SPECS_BY_TYPE["community.respond"].queue is QueueName.COMMUNITY


def test_principal_rules() -> None:
    import uuid

    Principal(principal_id="owner", kind=PrincipalKind.HUMAN_OWNER, session_id=uuid.uuid4())
    with pytest.raises(ValidationError):
        Principal(principal_id="owner", kind=PrincipalKind.HUMAN_OWNER)
    with pytest.raises(ValidationError):
        Principal(principal_id="worker", kind=PrincipalKind.SERVICE_WORKER, session_id=uuid.uuid4())
    with pytest.raises(ValidationError):
        Principal(principal_id="model", kind=PrincipalKind.RUNTIME_MODEL)
    model = Principal(
        principal_id="critic", kind=PrincipalKind.RUNTIME_MODEL, runtime_role=RuntimeRole.CRITIC
    )
    assert not model.is_human_owner
    for scope in ("gate2:approve", "season:approval", "episode:reject"):
        with pytest.raises(ValidationError):
            Principal(
                principal_id="w", kind=PrincipalKind.SERVICE_WORKER, scopes=frozenset({scope})
            )
    human = Principal(
        principal_id="owner",
        kind=PrincipalKind.HUMAN_OWNER,
        session_id=uuid.uuid4(),
        scopes=frozenset({"gate2:approve"}),
    )
    assert human.is_human_owner
