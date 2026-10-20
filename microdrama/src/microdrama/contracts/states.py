"""Frozen state-machine tables (SPEC §5, §10). Enforcement lives in ``core`` (T004).

Episodes advance linearly; automatic repairs and Gate 2 revisions move *back* to
the smallest affected production stage and then forward again to the same
Gate 2 (no new gate). Failures are typed outcomes recorded alongside the last
valid stage rather than extra states.
"""

from __future__ import annotations

from collections.abc import Mapping

from microdrama.contracts.enums import (
    ApprovalAction,
    EpisodeOutcome,
    EpisodeState,
    GateType,
    JobStatus,
    ReleaseState,
    SeasonState,
)

S = SeasonState
E = EpisodeState
R = ReleaseState
J = JobStatus

SEASON_TRANSITIONS: Mapping[SeasonState, frozenset[SeasonState]] = {
    S.PROPOSED: frozenset({S.SEASON_APPROVED, S.REJECTED, S.CANCELLED}),
    S.SEASON_APPROVED: frozenset({S.ACTIVE, S.CANCELLED}),
    S.ACTIVE: frozenset({S.COMPLETE, S.CANCELLED}),
    S.COMPLETE: frozenset(),
    S.REJECTED: frozenset(),
    S.CANCELLED: frozenset(),
}

# Season transitions that only an authenticated human Gate 1 event may cause.
SEASON_HUMAN_ONLY: frozenset[tuple[SeasonState, SeasonState]] = frozenset(
    {(S.PROPOSED, S.SEASON_APPROVED), (S.PROPOSED, S.REJECTED)}
)

_REPAIR_STAGES = frozenset({E.SCRIPTING, E.REFERENCES, E.RENDERING, E.ASSEMBLING})

EPISODE_TRANSITIONS: Mapping[EpisodeState, frozenset[EpisodeState]] = {
    E.PLANNED: frozenset({E.SCRIPTING}),
    E.SCRIPTING: frozenset({E.REFERENCES}),
    E.REFERENCES: frozenset({E.RENDERING}),
    E.RENDERING: frozenset({E.ASSEMBLING}),
    E.ASSEMBLING: frozenset({E.AI_REVIEW}),
    # QA pass opens Gate 2; QA repair returns to the smallest affected stage.
    E.AI_REVIEW: frozenset({E.AWAITING_FINAL_REVIEW}) | _REPAIR_STAGES,
    # Gate 2 approve, or Revise → targeted repair (then back to this same gate).
    E.AWAITING_FINAL_REVIEW: frozenset({E.RELEASE_APPROVED}) | _REPAIR_STAGES,
    E.RELEASE_APPROVED: frozenset({E.SCHEDULED}),
    E.SCHEDULED: frozenset({E.PUBLISHING}),
    E.PUBLISHING: frozenset({E.PUBLISHED_VERIFIED}),
    E.PUBLISHED_VERIFIED: frozenset({E.MANAGED}),
    E.MANAGED: frozenset(),
}

# Only an authenticated human Gate 2 event may move an episode here.
EPISODE_HUMAN_ONLY: frozenset[tuple[EpisodeState, EpisodeState]] = frozenset(
    {(E.AWAITING_FINAL_REVIEW, E.RELEASE_APPROVED)}
)

# Revisions from Gate 2 are human-initiated but executed automatically.
EPISODE_REVISION_TARGETS: frozenset[EpisodeState] = _REPAIR_STAGES

# Outcomes that end the episode's production for good (no budget reset/retry).
TERMINAL_OUTCOMES: frozenset[EpisodeOutcome] = frozenset(
    {
        EpisodeOutcome.BUDGET_EXHAUSTED,
        EpisodeOutcome.FAILED_QA,
        EpisodeOutcome.REJECTED,
        EpisodeOutcome.CANCELLED,
    }
)
# Outcomes that hold progress until reconciled/cleared by evidence.
RECOVERABLE_OUTCOMES: frozenset[EpisodeOutcome] = frozenset(EpisodeOutcome) - TERMINAL_OUTCOMES

# REJECTED as an episode outcome can only come from a Gate 2 human event.
HUMAN_ONLY_OUTCOMES: frozenset[EpisodeOutcome] = frozenset({EpisodeOutcome.REJECTED})

RELEASE_TRANSITIONS: Mapping[ReleaseState, frozenset[ReleaseState]] = {
    R.RELEASE_APPROVED: frozenset({R.SCHEDULED, R.HELD, R.CANCELLED}),
    R.SCHEDULED: frozenset({R.SUBMITTED, R.HELD, R.CANCELLED, R.FAILED}),
    R.SUBMITTED: frozenset({R.PROCESSING, R.RETRY_WAIT, R.NEEDS_RECONCILIATION, R.FAILED}),
    # RETRY_WAIT only after a *definitive* non-acceptance (e.g. 429 before accept).
    R.RETRY_WAIT: frozenset({R.SUBMITTED, R.FAILED, R.HELD, R.CANCELLED}),
    R.PROCESSING: frozenset({R.PUBLISHED_VERIFIED, R.NEEDS_RECONCILIATION, R.FAILED}),
    # Reconcile: found → PROCESSING/VERIFIED; proven absent → SUBMITTED again.
    R.NEEDS_RECONCILIATION: frozenset({R.SUBMITTED, R.PROCESSING, R.PUBLISHED_VERIFIED, R.FAILED}),
    R.HELD: frozenset({R.SCHEDULED, R.CANCELLED}),
    R.PUBLISHED_VERIFIED: frozenset(),
    R.FAILED: frozenset(),
    R.CANCELLED: frozenset(),
}

JOB_TRANSITIONS: Mapping[JobStatus, frozenset[JobStatus]] = {
    # A queued or retry-waiting job that still has in-flight provider work is quarantined
    # straight to reconciliation; it never pretends to run (V-30).
    J.QUEUED: frozenset({J.RUNNING, J.CANCELLED, J.NEEDS_RECONCILIATION}),
    J.RUNNING: frozenset(
        {
            J.SUCCEEDED,
            J.FAILED,
            J.WAITING_EXTERNAL,
            J.RETRY_WAIT,
            J.NEEDS_RECONCILIATION,
            J.CANCELLED,
            J.QUEUED,  # lease expired / worker crash → requeue the same durable job
        }
    ),
    J.WAITING_EXTERNAL: frozenset({J.RUNNING, J.NEEDS_RECONCILIATION, J.CANCELLED}),
    J.RETRY_WAIT: frozenset({J.QUEUED, J.FAILED, J.CANCELLED, J.NEEDS_RECONCILIATION}),
    J.NEEDS_RECONCILIATION: frozenset({J.RUNNING, J.SUCCEEDED, J.FAILED}),
    J.SUCCEEDED: frozenset(),
    J.FAILED: frozenset(),
    J.CANCELLED: frozenset(),
}

GATE_ACTIONS: Mapping[GateType, frozenset[ApprovalAction]] = {
    GateType.SEASON_CONCEPT: frozenset({ApprovalAction.APPROVE, ApprovalAction.REJECT}),
    GateType.EPISODE_FINAL: frozenset(
        {ApprovalAction.APPROVE, ApprovalAction.REVISE, ApprovalAction.REJECT}
    ),
}


def can_transition(table: Mapping, current: object, target: object) -> bool:
    return target in table.get(current, frozenset())
