"""Read-only progress projection for the owner workbench (T044a).

Everything here is computed from current persisted rows on every call — season and
episode plans, current V2 documents (hash-verified), the durable job ledger,
domain events, assets/QA, the existing budget read and platform posts. There is
no second progress store: a refresh and a fresh process reading the same rows
produce the same projection.

Truth rules this module honors:

- Production and release are independent stages; neither implies the other.
- ``accepted_work`` counts only current accepted rows for work the CURRENT plan
  requires; a failed or retried attempt never counts as accepted.
- The visible plan fingerprint and revision bind the WHOLE current required set
  (the current DirectingManifest plus every current wardrobe assignment), so a
  new required shot or outfit is always a visible plan change with a reason (the
  percent may go down). When no comparable historical requirement set is
  persisted, the current denominator is explained instead — no prior count is
  invented.
- Zero known denominator, or a provider job's internal percentage, is
  indeterminate — never a fabricated partial number.
- The canonical ``contracts.v2.ProgressSnapshot`` is attached only when its
  provenance requirements hold (a positive source revision and at least one real
  source event); otherwise the view stays local and cites no event ids.
- Costs come from the existing budget read; an unknown cost is ``None``, not zero.

No wall-clock value enters the projection: every timestamp is read from rows, so
two reads of unchanged rows are identical.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid5

from pydantic import Field, ValidationError

from microdrama.budget import BudgetService
from microdrama.contracts.enums import (
    EpisodeOutcome,
    EpisodeState,
    JobStatus,
    ReleaseState,
)
from microdrama.contracts.errors import Conflict
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.primitives import ContractModel, Revision, UtcDateTime, VersionedPayload
from microdrama.contracts.release import CostSummary
from microdrama.contracts.v2 import (
    DirectingManifest,
    ProgressSnapshot,
    ProgressStage,
    SceneWardrobeAssignment,
    verify_v2_record_hash,
)
from microdrama.persistence.db import Database
from microdrama.review.gate_conditions import episode_findings, finding_blocks

# --- module-local read-only response views (T044a) --------------------------------------------
#
# These are workbench-local projections over guardian-owned contract records, NOT
# public contract payloads: they are deliberately kept out of
# ``contracts/routes.py``/the registry until a contracts guardian freezes a new
# package (see docs/microdrama-system/T044a-contract-proposal.md for the precise
# schema proposal). They reuse the shared pydantic bases so wire consumers keep
# the same validation and hashing conventions.


class WorkProgress(ContractModel):
    """Current accepted/required work units of the production stage."""

    required: int = Field(ge=0)
    accepted: int = Field(ge=0)
    progress_bp: int | None = Field(default=None, ge=0, le=10_000)
    indeterminate_reason: str | None = None

    @property
    def indeterminate(self) -> bool:
        """True when no truthful percent exists (unknown denominator)."""
        return self.progress_bp is None


class PlanProvenance(ContractModel):
    """The exact plan the counts were computed against.

    Binds the ENTIRE current required set — the current DirectingManifest plus
    every current wardrobe assignment — not the manifest record alone: adding or
    removing a required outfit changes ``plan_fingerprint``/``plan_revision``
    even while the manifest record stays at the same version.
    ``plan_revision`` is derived (manifest version + every current assignment
    version), not a stored counter. ``denominator_basis`` always explains the
    current denominator, including when no comparable historical requirement set
    is persisted and therefore no prior count is claimed.
    """

    plan_kind: str
    record_id: UUID
    version: int
    content_sha256: str
    plan_fingerprint: str
    plan_revision: int
    previous_version: int | None = None
    denominator_changed: bool = False
    change_reason: str | None = None
    denominator_basis: str = ""


class JobsDigest(ContractModel):
    """The episode's durable job ledger, by status. No provider internals."""

    by_status: dict[str, int] = Field(default_factory=dict)
    retried_jobs: int = 0
    failed_jobs: int = 0
    waiting_external: int = 0
    latest_activity: UtcDateTime | None = None


class SlotProgress(ContractModel):
    """One platform post of the episode's release scope."""

    post_id: UUID
    platform: str
    release_slot: str
    required: bool
    state: ReleaseState
    verified_fields: list[str] = Field(default_factory=list)
    unverified_fields: list[str] = Field(default_factory=list)
    blocker: str | None = None


class EpisodeProgressView(VersionedPayload):
    """The local progress view; ``snapshot`` is set only with full provenance."""

    episode_id: UUID
    episode_number: int
    state: EpisodeState
    outcome: EpisodeOutcome | None = None
    revision: Revision
    production_stage: ProgressStage
    release_stage: ProgressStage
    production: WorkProgress
    plan: PlanProvenance | None = None
    jobs: JobsDigest = Field(default_factory=JobsDigest)
    open_blocking_findings: int = 0
    unknown_coverage: int = 0
    cost: CostSummary | None = None
    release_slots: list[SlotProgress] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    next_action: str | None = None
    snapshot: ProgressSnapshot | None = None
    indeterminate: list[str] = Field(default_factory=list)


class SeasonProgressView(VersionedPayload):
    """Season-level roll-up: every episode's projection, no extra store."""

    season_id: UUID
    state: str
    revision: Revision
    episodes: list[EpisodeProgressView] = Field(default_factory=list)


#: Deterministic identity of an episode's computed (never stored) progress record.
_PROGRESS_NAMESPACE = UUID("9d1f5c2a-47b0-4d6e-8a3f-2c5d61e0a7b4")

#: Episode states whose production work is finished (Gate 2 approved and beyond).
_PRODUCTION_DONE = frozenset(
    {
        EpisodeState.RELEASE_APPROVED,
        EpisodeState.SCHEDULED,
        EpisodeState.PUBLISHING,
        EpisodeState.PUBLISHED_VERIFIED,
        EpisodeState.MANAGED,
    }
)
#: Release slot states that block the release stage.
_RELEASE_BLOCKING = frozenset(
    {
        ReleaseState.FAILED,
        ReleaseState.HELD,
        ReleaseState.NEEDS_RECONCILIATION,
        ReleaseState.CANCELLED,
    }
)
#: Release slot states that mean work is in flight.
_RELEASE_RUNNING = frozenset(
    {ReleaseState.SCHEDULED, ReleaseState.SUBMITTED, ReleaseState.PROCESSING}
)
#: Release slot states that mean waiting (retry backoff, or scheduler pickup).
_RELEASE_WAITING = frozenset({ReleaseState.RETRY_WAIT, ReleaseState.RELEASE_APPROVED})
#: Asset states that count as accepted work (LOCKED = accepted and identity-locked).
_ACCEPTED_ASSET_STATES = frozenset({"ACCEPTED", "LOCKED"})
#: Render-asset object keys: renders/{episode_id}/{shot_id}/a{attempt}/{node}.ext
_RENDER_KEY_PREFIX = "renders/"


# --- internal carriers ----------------------------------------------------------------------


@dataclass(frozen=True)
class _DocRow:
    record_id: UUID
    version: int
    payload: dict[str, Any]
    payload_sha256: str


@dataclass(frozen=True)
class _WorkResult:
    work: WorkProgress
    plan: PlanProvenance | None
    indeterminate: tuple[str, ...]
    accepted_asset_ids: tuple[UUID, ...] = ()


# --- V2 document reads (hash-verified, fail closed on ambiguity) ----------------------------


def _current_docs(tx: Any, contract_type: str, episode_id: UUID) -> list[_DocRow]:
    return [
        _DocRow(row["record_id"], int(row["version"]), dict(row["payload"]), row["payload_sha256"])
        for row in tx.fetchall(
            "SELECT record_id, version, payload, payload_sha256 FROM v2_contract_documents "
            "WHERE contract_type = %s AND current AND payload->>'episode_id' = %s",
            (contract_type, str(episode_id)),
        )
    ]


def _previous_snapshot_docs(tx: Any, contract_type: str, episode_id: UUID) -> list[_DocRow]:
    """The document set as of one revision ago.

    Per record id still current at version V that is its (V-1) row; for a record
    id that is no longer current at all (replaced by a new record id) its newest
    superseded row. Returns ``[]`` when no history exists.
    """
    current_versions = {
        row["record_id"]: int(row["version"])
        for row in tx.fetchall(
            "SELECT record_id, version FROM v2_contract_documents "
            "WHERE contract_type = %s AND current AND payload->>'episode_id' = %s",
            (contract_type, str(episode_id)),
        )
    }
    history = tx.fetchall(
        "SELECT record_id, version, payload, payload_sha256 FROM v2_contract_documents "
        "WHERE contract_type = %s AND payload->>'episode_id' = %s AND NOT current "
        "ORDER BY record_id, version",
        (contract_type, str(episode_id)),
    )
    previous: dict[UUID, _DocRow] = {}
    for row in history:
        record_id, version = row["record_id"], int(row["version"])
        latest_current = current_versions.get(record_id)
        if latest_current is not None:
            if version == latest_current - 1:
                previous[record_id] = _DocRow(
                    record_id, version, dict(row["payload"]), row["payload_sha256"]
                )
        else:
            old = previous.get(record_id)
            if old is None or version > old.version:
                previous[record_id] = _DocRow(
                    record_id, version, dict(row["payload"]), row["payload_sha256"]
                )
    return list(previous.values())


def _verify_stored(record: Any, doc: _DocRow, episode_id: UUID, contract_type: str) -> None:
    """A stored document must validate, bind this episode, and match its stored hash."""
    verify_v2_record_hash(record)
    if getattr(record, "episode_id", None) != episode_id:
        raise Conflict(
            "stored V2 artifact is bound to a different episode",
            contract_type=contract_type,
            record_id=str(doc.record_id),
        )
    if canonical_hash(record) != doc.payload_sha256:
        raise Conflict(
            "stored V2 artifact payload hash is invalid",
            contract_type=contract_type,
            record_id=str(doc.record_id),
        )


def _verified_manifest(doc: _DocRow, episode_id: UUID) -> DirectingManifest:
    manifest = DirectingManifest.model_validate(doc.payload)
    _verify_stored(manifest, doc, episode_id, "DirectingManifest")
    return manifest


def _verified_assignment(doc: _DocRow, episode_id: UUID) -> SceneWardrobeAssignment:
    assignment = SceneWardrobeAssignment.model_validate(doc.payload)
    _verify_stored(assignment, doc, episode_id, "SceneWardrobeAssignment")
    return assignment


def _plan_fingerprint(
    manifest_doc: _DocRow,
    manifest: DirectingManifest,
    verified: Sequence[tuple[_DocRow, SceneWardrobeAssignment]],
) -> str:
    """A fingerprint over the ENTIRE current required set, not the manifest alone.

    Binds the current manifest (record id, version, content hash, required shot
    ids) together with every verified current assignment record (record id,
    version, payload hash), so any change to the required set — a new/removed
    shot OR a new/removed/reversioned outfit assignment — changes the
    fingerprint. Unverifiable current records contribute nothing here; they are
    reported through ``indeterminate`` instead.
    """
    return canonical_hash(
        {
            "manifest": {
                "record_id": str(manifest_doc.record_id),
                "version": manifest_doc.version,
                "content_sha256": manifest.content_sha256,
                "shots": sorted(shot.shot_id for shot in manifest.shots),
            },
            "assignments": sorted(
                f"{doc.record_id}:v{doc.version}:{doc.payload_sha256}" for doc, _a in verified
            ),
        }
    )


def _plan_revision(manifest_doc: _DocRow, verified: Sequence[tuple[_DocRow, Any]]) -> int:
    """A visible derived revision over the whole current required set:
    manifest version + every verified current assignment version. Any addition,
    reversion or removal of a required record moves it (a record replaced by a
    fresh record id can move it either way); it is a display companion to the
    exact ``plan_fingerprint``, not a stored counter."""
    return manifest_doc.version + sum(doc.version for doc, _a in verified)


# --- accepted render assets ------------------------------------------------------------------


def _latest_attempt_assets(tx: Any, episode_id: UUID) -> dict[str, list[dict[str, Any]]]:
    """shot_id -> asset rows of that shot's LATEST attempt only (numeric order).

    ``renders/{episode}/{shot}/a{attempt}/{node}`` — an earlier accepted attempt
    whose successor failed does not count: the current attempt is the durable
    truth the packaging step itself uses.
    """
    rows = tx.fetchall(
        "SELECT id, object_key, state FROM assets WHERE episode_id = %s "
        "AND object_key LIKE %s ORDER BY object_key",
        (episode_id, f"{_RENDER_KEY_PREFIX}%"),
    )
    attempts: dict[str, dict[int, list[dict[str, Any]]]] = {}
    for row in rows:
        parts = row["object_key"].split("/")
        if len(parts) < 4:
            continue
        shot_id, attempt_part = parts[2], parts[3]
        if not attempt_part.startswith("a") or not attempt_part[1:].isdigit():
            continue
        attempts.setdefault(shot_id, {}).setdefault(int(attempt_part[1:]), []).append(dict(row))
    return {shot_id: by_attempt[max(by_attempt)] for shot_id, by_attempt in attempts.items()}


def _shot_accepted(asset_rows: Sequence[dict[str, Any]]) -> bool:
    """A shot's latest attempt counts as accepted only when every output of that
    attempt is an accepted (or locked) asset; a failed output never counts."""
    return bool(asset_rows) and all(row["state"] in _ACCEPTED_ASSET_STATES for row in asset_rows)


# --- digests -----------------------------------------------------------------------------------


def _jobs_digest(tx: Any, episode_id: UUID) -> tuple[JobsDigest, tuple[UUID, ...]]:
    rows = tx.fetchall(
        "SELECT status, count(*) AS n FROM jobs WHERE episode_id = %s GROUP BY status",
        (episode_id,),
    )
    by_status = {row["status"]: int(row["n"]) for row in rows}
    retried = tx.fetchval(
        "SELECT count(*) FROM jobs WHERE episode_id = %s AND attempt > 1", (episode_id,)
    )
    activity = tx.fetchval("SELECT max(updated_at) FROM jobs WHERE episode_id = %s", (episode_id,))
    job_ids = tuple(
        row["id"]
        for row in tx.fetchall(
            "SELECT id FROM jobs WHERE episode_id = %s ORDER BY created_at, id",
            (episode_id,),
        )
    )
    digest = JobsDigest(
        by_status=by_status,
        retried_jobs=int(retried or 0),
        failed_jobs=by_status.get(JobStatus.FAILED.value, 0)
        + by_status.get(JobStatus.NEEDS_RECONCILIATION.value, 0),
        waiting_external=by_status.get(JobStatus.WAITING_EXTERNAL.value, 0),
        latest_activity=activity,
    )
    return digest, job_ids


def _release_slots(tx: Any, episode_id: UUID) -> list[SlotProgress]:
    return [
        SlotProgress(
            post_id=row["id"],
            platform=row["platform"],
            release_slot=row["release_slot"],
            required=row["required"],
            state=ReleaseState(row["state"]),
            verified_fields=list(row["verified_fields"] or []),
            unverified_fields=list(row["unverified_fields"] or []),
            blocker=row["blocker"],
        )
        for row in tx.fetchall(
            "SELECT id, platform, release_slot, required, state, verified_fields, "
            "unverified_fields, blocker FROM platform_posts WHERE episode_id = %s "
            "ORDER BY platform, release_slot, id",
            (episode_id,),
        )
    ]


def _unknown_coverage(tx: Any, episode_id: UUID) -> int:
    row = tx.fetchone(
        "SELECT report FROM qa_observations WHERE episode_id = %s "
        "ORDER BY frozen_at DESC, created_at DESC LIMIT 1",
        (episode_id,),
    )
    if row is None:
        return 0
    report = row["report"] or {}
    return sum(
        1
        for window in (report.get("coverage") or [])
        if window.get("status") in ("UNSAMPLED", "UNAVAILABLE")
    )


# --- stage computation ------------------------------------------------------------------------


def _release_stage(slots: Sequence[SlotProgress]) -> tuple[ProgressStage, list[str]]:
    if not slots:
        return ProgressStage.PLANNED, []
    blocking = [s for s in slots if s.state in _RELEASE_BLOCKING]
    if blocking:
        return ProgressStage.BLOCKED, [
            f"release slot {s.platform}/{s.release_slot} is {s.state.value}"
            + (f": {s.blocker}" if s.blocker else "")
            for s in blocking
        ]
    required = [s for s in slots if s.required]
    pool = required if required else list(slots)
    if all(s.state is ReleaseState.PUBLISHED_VERIFIED for s in pool):
        return ProgressStage.COMPLETE, []
    if any(s.state in _RELEASE_RUNNING for s in pool):
        return ProgressStage.RUNNING, []
    waiting = [s for s in pool if s.state in _RELEASE_WAITING]
    if waiting:
        return ProgressStage.WAITING, [
            f"release slot {s.platform}/{s.release_slot} waits at {s.state.value}" for s in waiting
        ]
    return ProgressStage.PLANNED, []


def _production_stage(
    episode: dict[str, Any],
    jobs: JobsDigest,
    blocking_findings: Sequence[dict[str, Any]],
) -> tuple[ProgressStage, list[str], str | None]:
    outcome = episode["outcome"]
    blockers: list[str] = []
    if outcome is not None:
        blockers.append(f"terminal outcome: {outcome}")
        return (
            ProgressStage.BLOCKED,
            blockers,
            "episode has a terminal outcome; see blockers",
        )
    state = EpisodeState(episode["state"])
    if state in _PRODUCTION_DONE:
        return ProgressStage.COMPLETE, [], None
    finding_blockers = [
        f"blocking QA finding {row['id']} ({row['check_id']}) from QA cycle {row['qa_cycle']}"
        for row in blocking_findings
    ]
    if state is EpisodeState.AWAITING_FINAL_REVIEW:
        # The episode waits on a human gate decision; findings only gate Approve.
        return (
            ProgressStage.WAITING,
            finding_blockers,
            "owner Gate 2 decision (approve, revise or reject)",
        )
    if jobs.failed_jobs:
        blockers.append(f"{jobs.failed_jobs} job(s) ended FAILED or NEEDS_RECONCILIATION")
        return (
            ProgressStage.BLOCKED,
            blockers,
            "resolve failed jobs (retry or repair) before work resumes",
        )
    if jobs.by_status.get(JobStatus.RUNNING.value, 0) or jobs.waiting_external:
        return ProgressStage.RUNNING, [], None
    if jobs.by_status.get(JobStatus.RETRY_WAIT.value, 0):
        return (
            ProgressStage.WAITING,
            ["a job is in retry backoff"],
            "retry scheduled; no action needed until the retry resolves",
        )
    if finding_blockers:
        blockers.extend(finding_blockers)
        return ProgressStage.BLOCKED, blockers, "plan repairs for the blocking QA findings"
    if jobs.by_status.get(JobStatus.QUEUED.value, 0):
        return ProgressStage.RUNNING, [], None
    return ProgressStage.PLANNED, [], "awaiting production jobs for this episode"


# --- the projection ---------------------------------------------------------------------------


class ProgressProjection:
    """Compute owner-workbench progress from current rows. Construct once."""

    def __init__(self, db: Database, budget: BudgetService) -> None:
        self._db = db
        self._budget = budget

    def episode_view(self, episode: dict[str, Any]) -> EpisodeProgressView:
        """The projection for one episode row (scope is the caller's duty)."""
        episode_id = episode["id"]
        with self._db.transaction(readonly=True) as tx:
            jobs, job_ids = _jobs_digest(tx, episode_id)
            slots = _release_slots(tx, episode_id)
            findings = [
                row
                for row in episode_findings(tx, episode_id)
                if finding_blocks(row["severity"], row["outcome"], row["resolution"])
            ]
            work_result = self._work(tx, episode_id)
            unknown_coverage = _unknown_coverage(tx, episode_id)
            source_events = self._source_events(tx, episode_id, slots)
        production_stage, blockers, next_action = _production_stage(episode, jobs, findings)
        release_stage, release_blockers = _release_stage(slots)
        blockers = [*blockers, *release_blockers]
        indeterminate = list(work_result.indeterminate)
        if unknown_coverage:
            indeterminate.append(
                f"{unknown_coverage} QA coverage window(s) unsampled or unavailable"
            )
        snapshot = self._snapshot(
            episode,
            source_events,
            job_ids,
            work_result,
            production_stage,
            release_stage,
            findings,
            next_action,
        )
        return EpisodeProgressView(
            episode_id=episode_id,
            episode_number=episode["episode_number"],
            state=EpisodeState(episode["state"]),
            outcome=EpisodeOutcome(episode["outcome"]) if episode["outcome"] else None,
            revision=episode["revision"],
            production_stage=production_stage,
            release_stage=release_stage,
            production=work_result.work,
            plan=work_result.plan,
            jobs=jobs,
            open_blocking_findings=len(findings),
            unknown_coverage=unknown_coverage,
            cost=self._cost(episode_id),
            release_slots=slots,
            blockers=blockers,
            next_action=next_action,
            snapshot=snapshot,
            indeterminate=indeterminate,
        )

    def season_view(
        self, season: dict[str, Any], episodes: Sequence[dict[str, Any]]
    ) -> SeasonProgressView:
        return SeasonProgressView(
            season_id=season["id"],
            state=season["state"],
            revision=season["revision"],
            episodes=[self.episode_view(episode) for episode in episodes],
        )

    # --- pieces -------------------------------------------------------------------------------

    def _work(self, tx: Any, episode_id: UUID) -> _WorkResult:
        """Required/accepted production work units from the current V2 plan."""
        manifests = _current_docs(tx, "DirectingManifest", episode_id)
        if len(manifests) > 1:
            return _WorkResult(
                work=WorkProgress(required=0, accepted=0, indeterminate_reason="ambiguous plan"),
                plan=None,
                indeterminate=("multiple current DirectingManifest documents for this episode",),
            )
        if not manifests:
            return _WorkResult(
                work=WorkProgress(
                    required=0, accepted=0, indeterminate_reason="no current directing plan"
                ),
                plan=None,
                indeterminate=("no current DirectingManifest: required shots are unknown",),
            )
        doc = manifests[0]
        try:
            manifest = _verified_manifest(doc, episode_id)
        except (Conflict, ValidationError, ValueError) as exc:
            return _WorkResult(
                work=WorkProgress(required=0, accepted=0, indeterminate_reason="plan unreadable"),
                plan=None,
                indeterminate=(f"current DirectingManifest failed verification: {exc}",),
            )
        assignments = _current_docs(tx, "SceneWardrobeAssignment", episode_id)
        verified: list[tuple[_DocRow, SceneWardrobeAssignment]] = []
        indeterminate: list[str] = []
        for assignment_doc in assignments:
            try:
                verified.append((assignment_doc, _verified_assignment(assignment_doc, episode_id)))
            except (Conflict, ValidationError, ValueError) as exc:
                indeterminate.append(f"a SceneWardrobeAssignment failed verification: {exc}")
        verified_assignments = [assignment for _doc, assignment in verified]

        required_shots = {shot.shot_id for shot in manifest.shots}
        required_outfits = {(a.character_id, a.outfit_id) for a in verified_assignments}
        previous_shots, previous_outfits, previous_version = self._previous_work(tx, episode_id)

        latest_assets = _latest_attempt_assets(tx, episode_id)
        accepted_shots = {
            shot_id for shot_id in required_shots if _shot_accepted(latest_assets.get(shot_id, []))
        }
        outfit_assets = [a.asset_id for a in verified_assignments]
        outfit_asset_states = (
            {
                row["id"]: row["state"]
                for row in tx.fetchall(
                    "SELECT id, state FROM assets WHERE id = ANY(%s)",
                    (outfit_assets,),
                )
            }
            if outfit_assets
            else {}
        )
        accepted_assignments = [
            a
            for a in verified_assignments
            if outfit_asset_states.get(a.asset_id) in _ACCEPTED_ASSET_STATES
        ]
        accepted_outfits = {(a.character_id, a.outfit_id) for a in accepted_assignments}

        required = len(required_shots) + len(required_outfits)
        accepted = len(accepted_shots) + len(accepted_outfits)
        progress_bp = min(10_000, accepted * 10_000 // required) if required else None
        if not required:
            indeterminate.append("plan requires no work units yet")

        change_reason = self._change_reason(
            previous_shots, previous_outfits, required_shots, required_outfits
        )
        plan = PlanProvenance(
            plan_kind="DirectingManifest+SceneWardrobeAssignments",
            record_id=doc.record_id,
            version=doc.version,
            content_sha256=manifest.content_sha256,
            plan_fingerprint=_plan_fingerprint(doc, manifest, verified),
            plan_revision=_plan_revision(doc, verified),
            previous_version=previous_version,
            denominator_changed=change_reason is not None,
            change_reason=change_reason,
            denominator_basis=self._denominator_basis(
                previous_shots, previous_outfits, required_shots, required_outfits
            ),
        )
        accepted_asset_ids = [
            *(row["id"] for shot_id in sorted(accepted_shots) for row in latest_assets[shot_id]),
            *(a.asset_id for a in accepted_assignments),
        ]
        return _WorkResult(
            work=WorkProgress(
                required=required,
                accepted=accepted,
                progress_bp=progress_bp,
                indeterminate_reason=None if required else "zero known denominator",
            ),
            plan=plan,
            indeterminate=tuple(indeterminate),
            accepted_asset_ids=tuple(accepted_asset_ids),
        )

    @staticmethod
    def _denominator_basis(
        previous_shots: set[str] | None,
        previous_outfits: set[tuple[str, str]] | None,
        required_shots: set[str],
        required_outfits: set[tuple[str, str]],
    ) -> str:
        """The honest explanation of the CURRENT denominator.

        Always states what the requirement set is; adds what comparability the
        persisted rows do and do not allow, and never states a prior count the
        rows cannot prove.
        """
        parts = [
            f"{len(required_shots)} required shot(s) + {len(required_outfits)} required "
            f"outfit(s) = {len(required_shots) + len(required_outfits)} work units"
        ]
        if previous_shots is None and previous_outfits is None:
            parts.append(
                "no comparable historical requirement set is persisted for this plan, "
                "so no earlier denominator is claimed"
            )
        elif previous_shots is None:
            parts.append(
                "no earlier manifest revision is persisted, so shot changes cannot be compared"
            )
        elif previous_outfits is None:
            parts.append(
                "assignment history is not persisted for this plan, so outfit additions "
                "cannot be dated or compared"
            )
        return "; ".join(parts)

    @staticmethod
    def _change_reason(
        previous_shots: set[str] | None,
        previous_outfits: set[tuple[str, str]] | None,
        required_shots: set[str],
        required_outfits: set[tuple[str, str]],
    ) -> str | None:
        if previous_shots is None and previous_outfits is None:
            return None
        parts: list[str] = []
        if previous_shots is not None and previous_shots != required_shots:
            if added := sorted(required_shots - previous_shots):
                parts.append(f"shots added: {', '.join(added)}")
            if removed := sorted(previous_shots - required_shots):
                parts.append(f"shots removed: {', '.join(removed)}")
        if previous_outfits is not None and previous_outfits != required_outfits:
            if added := sorted(f"{c}/{o}" for c, o in required_outfits - previous_outfits):
                parts.append(f"outfits added: {', '.join(added)}")
            if removed := sorted(f"{c}/{o}" for c, o in previous_outfits - required_outfits):
                parts.append(f"outfits removed: {', '.join(removed)}")
        if parts:
            if previous_shots is not None and previous_outfits is not None:
                parts.append(
                    f"required work {len(previous_shots) + len(previous_outfits)} -> "
                    f"{len(required_shots) + len(required_outfits)}"
                )
            elif previous_shots is not None:
                parts.append(f"required shots {len(previous_shots)} -> {len(required_shots)}")
            else:
                parts.append(f"required outfits {len(previous_outfits)} -> {len(required_outfits)}")
        return "; ".join(parts) or None

    def _previous_work(
        self, tx: Any, episode_id: UUID
    ) -> tuple[set[str] | None, set[tuple[str, str]] | None, int | None]:
        """(previous shots, previous outfits, previous manifest version) of the plan
        one revision ago; each dimension is ``None`` when no comparable history
        for it is persisted, so the two are judged independently.

        Outfit history is ``None`` (unknown, not empty) when no assignment record
        has any comparable revision: a record current at version 1 proves nothing
        about when it appeared, so no outfit change is claimed from thin air.
        """
        previous_shots: set[str] | None = None
        previous_version: int | None = None
        previous_manifests = _previous_snapshot_docs(tx, "DirectingManifest", episode_id)
        if previous_manifests:
            doc = max(previous_manifests, key=lambda item: item.version)
            try:
                manifest = _verified_manifest(doc, episode_id)
            except (Conflict, ValidationError, ValueError):
                manifest = None
            if manifest is not None:
                previous_shots = {shot.shot_id for shot in manifest.shots}
                previous_version = doc.version

        previous_docs = _previous_snapshot_docs(tx, "SceneWardrobeAssignment", episode_id)
        current_docs = _current_docs(tx, "SceneWardrobeAssignment", episode_id)
        if not previous_docs:
            previous_outfits: set[tuple[str, str]] | None = None if current_docs else set()
        else:
            # Comparable history exists: superseded outfits are real, and a current
            # record with no own history is conservatively counted as already
            # present (its novelty is unknowable from the rows).
            previous_outfits = set()
            with_history = set()
            for assignment_doc in previous_docs:
                try:
                    assignment = _verified_assignment(assignment_doc, episode_id)
                except (Conflict, ValidationError, ValueError):
                    continue
                previous_outfits.add((assignment.character_id, assignment.outfit_id))
                with_history.add(assignment_doc.record_id)
            for assignment_doc in current_docs:
                if assignment_doc.record_id in with_history:
                    continue
                try:
                    assignment = _verified_assignment(assignment_doc, episode_id)
                except (Conflict, ValidationError, ValueError):
                    continue
                previous_outfits.add((assignment.character_id, assignment.outfit_id))
        return previous_shots, previous_outfits, previous_version

    @staticmethod
    def _source_events(tx: Any, episode_id: UUID, slots: Sequence[SlotProgress]) -> list[UUID]:
        """Real domain-event ids the projection covers: the episode aggregate's
        events and its platform posts' events. Never fabricated."""
        ids = [
            row["event_id"]
            for row in tx.fetchall(
                "SELECT event_id FROM domain_events WHERE aggregate_id = %s ORDER BY sequence",
                (episode_id,),
            )
        ]
        for slot in slots:
            ids.extend(
                row["event_id"]
                for row in tx.fetchall(
                    "SELECT event_id FROM domain_events WHERE aggregate_id = %s ORDER BY sequence",
                    (slot.post_id,),
                )
            )
        return ids

    def _cost(self, episode_id: UUID) -> CostSummary | None:
        try:
            return self._budget.summary(episode_id)
        except Exception:  # an unreadable budget is unknown cost, never a crash
            return None

    @staticmethod
    def _snapshot(
        episode: dict[str, Any],
        source_events: Sequence[UUID],
        job_ids: Sequence[UUID],
        work_result: _WorkResult,
        production_stage: ProgressStage,
        release_stage: ProgressStage,
        findings: Sequence[dict[str, Any]],
        next_action: str | None,
    ) -> ProgressSnapshot | None:
        """The canonical record, only when its provenance requirements hold.

        ``projection_revision`` must be positive and cite the episode's real
        revision, and at least one real source event must exist. Otherwise the
        projection stays local (``snapshot=None``) rather than inventing ids.
        """
        revision = int(episode["revision"])
        if revision < 1 or not source_events:
            return None
        try:
            return ProgressSnapshot.seal(
                record_id=uuid5(_PROGRESS_NAMESPACE, f"owner-progress:{episode['id']}"),
                version=1,
                created_at=episode["updated_at"],
                updated_at=episode["updated_at"],
                valid_from=episode["updated_at"],
                aggregate_id=episode["id"],
                projection_revision=revision,
                source_event_ids=list(source_events),
                source_job_ids=list(job_ids),
                source_asset_ids=list(work_result.accepted_asset_ids),
                production_stage=production_stage,
                release_stage=release_stage,
                accepted_work=work_result.work.accepted,
                required_work=work_result.work.required,
                blocker_ids=[str(row["id"]) for row in findings],
                next_action=next_action,
                progress_bp=work_result.work.progress_bp,
            )
        except (ValidationError, ValueError):
            # A contract violation means this episode's numbers cannot be sealed
            # truthfully; the local view above still carries them.
            return None


__all__ = [
    "EpisodeProgressView",
    "JobsDigest",
    "PlanProvenance",
    "ProgressProjection",
    "SeasonProgressView",
    "SlotProgress",
    "WorkProgress",
]
