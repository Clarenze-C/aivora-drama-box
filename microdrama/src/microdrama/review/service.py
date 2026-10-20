"""Gate 1 (season concept) and Gate 2 (episode final) decisions and the review views.

Only an authenticated human owner can decide (``require_human_owner``). Every decision runs inside
``IdempotencyService.execute``: the idempotency record, the approval row, the state changes and the
enqueued job commit or roll back together. Nothing here approves on a timer; a non-human principal
is refused before anything is read or written.

Gate 2 APPROVE order (contract of T008):
  record approval -> package APPROVED (DB checks the binding) -> identity-lock hook (episode one,
  same transaction) -> episode RELEASE_APPROVED (DB needs the APPROVED package) -> enqueue
  ``publish.schedule_release``.
Gate 2 REVISE: record -> episode to the repair stage implied by the most upstream feedback category
  -> qa_cycle + 1 -> package REVISED -> enqueue ``qa.plan_repairs``. The revised episode returns to
  this same gate with a new package version.
Gate 2 REJECT: record -> package REJECTED -> episode outcome REJECTED.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError

from microdrama.budget import BudgetService
from microdrama.contracts.enums import (
    ApprovalAction,
    EpisodeOutcome,
    EpisodeState,
    FeedbackCategory,
    GateType,
    ManagementActionKind,
    SeasonState,
)
from microdrama.contracts.errors import (
    GateNotReady,
    InvalidTransition,
    NotFound,
    SchemaInvalid,
    StaleRevision,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.infra import Clock, IdGenerator, ObjectStore
from microdrama.contracts.jobs import EpisodeStepInput, SeasonStepInput
from microdrama.contracts.media import CaptionTrack, HookExperiment
from microdrama.contracts.principals import Principal
from microdrama.contracts.qa import CoverageWindow, ObservationReport, QAFinding
from microdrama.contracts.release import CostSummary, ReleasePackage
from microdrama.contracts.routes import (
    CommandAccepted,
    EpisodeReviewView,
    ReviewMediaLink,
    SeasonProposalSummary,
    SeasonView,
)
from microdrama.contracts.season import ApprovalCommand, ManagementPolicy, SeasonScope
from microdrama.core.approvals import record_approval_event
from microdrama.core.auth import require_human_owner
from microdrama.core.hooks import ApprovalHook
from microdrama.core.idempotency import CommandResult, IdempotencyService
from microdrama.core.jobs import JobService
from microdrama.core.state_machine import (
    set_episode_outcome,
    transition_episode,
    transition_season,
)
from microdrama.persistence.db import Database, Tx, update_with_revision
from microdrama.review.gate_conditions import (
    ReleaseConditionsFn,
    approved_scope,
    episode_findings,
    finding_blocks,
    gate2_blockers,
)
from microdrama.review.packages import (
    PackageStatus,
    StoredPackage,
    current_package,
    record_package_decision,
)

# Repair stages in pipeline order; the smallest affected stage is the one a revision returns to.
_STAGE_RANK: tuple[EpisodeState, ...] = (
    EpisodeState.SCRIPTING,
    EpisodeState.REFERENCES,
    EpisodeState.RENDERING,
    EpisodeState.ASSEMBLING,
)
_STAGE_BY_CATEGORY: dict[FeedbackCategory, EpisodeState] = {
    FeedbackCategory.MOTIVATION: EpisodeState.SCRIPTING,
    FeedbackCategory.THAI_DIALOGUE: EpisodeState.REFERENCES,
    FeedbackCategory.IDENTITY_VOICE: EpisodeState.REFERENCES,
    FeedbackCategory.CONTINUITY_PROPS: EpisodeState.RENDERING,
    FeedbackCategory.SUBTITLES: EpisodeState.ASSEMBLING,
    FeedbackCategory.PACING: EpisodeState.ASSEMBLING,
    FeedbackCategory.SOUND: EpisodeState.ASSEMBLING,
    FeedbackCategory.OTHER: EpisodeState.ASSEMBLING,
}
# Management actions whose bounded metadata edits need no new human approval (SPEC §5 rule 4).
_WITHIN_POLICY_KINDS = frozenset(
    {
        ManagementActionKind.TITLE_EDIT,
        ManagementActionKind.CAPTION_EDIT,
        ManagementActionKind.DESCRIPTION_EDIT,
        ManagementActionKind.HASHTAG_EDIT,
        ManagementActionKind.PUBLIC_REPLY,
    }
)
_ACTUAL_AUDIO = "ACTUAL_AUDIO_ALIGNMENT"
_TIMECODE = re.compile(r"^(?:(\d{1,2}):)?(\d{1,3}):(\d{2})(?:\.(\d{1,3}))?$")


class QaFindingRow(BaseModel):
    """One QA finding with the QA cycle it was raised in and whether it blocks Gate 2 (V-26).

    The page and the JSON route both come from ``ReviewService.qa_finding_rows``; the episode JSON
    ``findings`` are the same rows' ``finding`` values, so the sets always agree.
    """

    finding_id: UUID
    qa_cycle: int
    resolution: str
    blocks_gate: bool
    finding: QAFinding


@dataclass(frozen=True)
class CaptionPreview:
    track_id: UUID
    locale: str
    timing_source: str
    state: str
    releasable: bool
    readable: bool
    cues: tuple[tuple[int, int, str], ...]


@dataclass(frozen=True)
class MediaFile:
    path: Path
    media_type: str
    sha256: str


@dataclass(frozen=True)
class EpisodePage:
    """Everything the episode review page shows beyond the JSON view (module-internal).

    ``can_decide`` is true when Revise and Reject are decidable (AWAITING_FINAL_REVIEW, no outcome,
    current package READY or BLOCKED); Approve additionally needs ``view.gate_enabled``.
    """

    view: EpisodeReviewView
    captions: tuple[CaptionPreview, ...]
    media_types: dict[str, str]
    hook_candidates: tuple[dict[str, Any], ...]
    can_decide: bool
    finding_rows: tuple[QaFindingRow, ...]


def parse_timecode(text: str) -> int:
    """Milliseconds from ``123456`` (ms), ``mm:ss``, ``mm:ss.mmm`` or ``h:mm:ss.mmm``."""
    if not isinstance(text, str):
        raise SchemaInvalid("timecode must be text")
    value = text.strip()
    if value.isdigit():
        return int(value)
    match = _TIMECODE.fullmatch(value)
    if match is None:
        raise SchemaInvalid(f"timecode {text!r} must be ms or [h:]mm:ss[.mmm]")
    hours, minutes, seconds, fraction = match.groups()
    if int(seconds) > 59 or (hours is not None and int(minutes) > 59):
        raise SchemaInvalid(f"timecode {text!r} has out-of-range minutes or seconds")
    millis = int((fraction or "0").ljust(3, "0"))
    total = (int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)) * 1000
    return total + millis


def repair_stage_for(feedback: Sequence[Any]) -> EpisodeState:
    """The most upstream stage any feedback category implies (the smallest affected stage)."""
    if not feedback:
        raise SchemaInvalid("a revision needs feedback")
    stages = [_STAGE_BY_CATEGORY[FeedbackCategory(item.category)] for item in feedback]
    return min(stages, key=_STAGE_RANK.index)


def is_material_change(old: ReleasePackage, new: ReleasePackage) -> bool:
    """True when the change needs a new Gate 2 decision (media, captions, scope or policy)."""

    def media(p: ReleasePackage) -> list[tuple[str, str, str]]:
        return sorted((m.role, str(m.asset_id), m.sha256) for m in p.media)

    return (
        media(old) != media(new)
        or sorted(map(str, old.caption_track_ids)) != sorted(map(str, new.caption_track_ids))
        or sorted(map(str, old.cast_package_asset_ids))
        != sorted(map(str, new.cast_package_asset_ids))
        or old.hook_experiment_id != new.hook_experiment_id
        or old.release_scope_hash != new.release_scope_hash
        or old.management_policy_hash != new.management_policy_hash
    )


def metadata_within_policy(policy: ManagementPolicy, change_kind: ManagementActionKind) -> bool:
    """True for a bounded metadata/reply change the approved policy already allows.

    Covers and links, media-bearing or factual changes, DMs, moderation and anything the policy
    does not list stay outside this rule and are therefore material or human-only.
    """
    kind = ManagementActionKind(change_kind)
    return kind in _WITHIN_POLICY_KINDS and kind in policy.allowed_actions


def _check_gate_fields(gate: GateType, route_entity_id: UUID, command: ApprovalCommand) -> None:
    if not isinstance(command, ApprovalCommand):
        raise SchemaInvalid("an ApprovalCommand is required")
    if command.gate is not gate:
        raise SchemaInvalid(f"this route decides {gate.value}, not {command.gate.value}")
    if command.entity_id != route_entity_id:
        raise SchemaInvalid("command entity_id does not match the route's entity")


class ReviewService:
    """Review reads and the two gate decisions. Construct once per process."""

    def __init__(
        self,
        db: Database,
        clock: Clock,
        ids: IdGenerator,
        *,
        jobs: JobService,
        idempotency: IdempotencyService,
        budget: BudgetService,
        store: ObjectStore,
        release_conditions_fn: ReleaseConditionsFn,
        approval_hooks: Sequence[ApprovalHook],
        identity_lock_hook: ApprovalHook | None = None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._ids = ids
        self._jobs = jobs
        self._idempotency = idempotency
        self._budget = budget
        self._store = store
        self._release_conditions_fn = release_conditions_fn
        self._approval_hooks = tuple(approval_hooks)
        self._identity_lock_hook = identity_lock_hook

    # --- helpers -------------------------------------------------------------------

    @property
    def store(self) -> ObjectStore:
        return self._store

    @staticmethod
    def is_material_change(old: ReleasePackage, new: ReleasePackage) -> bool:
        return is_material_change(old, new)

    @staticmethod
    def metadata_within_policy(policy: ManagementPolicy, change_kind: ManagementActionKind) -> bool:
        return metadata_within_policy(policy, change_kind)

    def _now(self) -> datetime:
        return self._clock.now()

    @staticmethod
    def _current_proposal(tx: Tx, season_id: UUID, *, lock: bool = False) -> dict[str, Any] | None:
        sql = (
            "SELECT * FROM season_proposals WHERE season_id = %s "
            "ORDER BY scope_version DESC LIMIT 1" + (" FOR UPDATE" if lock else "")
        )
        return tx.fetchone(sql, (season_id,))

    @staticmethod
    def _research_spend(tx: Tx, season_id: UUID) -> int:
        value = tx.fetchval(
            "SELECT COALESCE(SUM(settled_micro_usd + accrued_micro_usd), 0)::bigint "
            "FROM budget_accounts WHERE scope_kind = 'SEASON_RESEARCH' AND season_id = %s",
            (season_id,),
        )
        return int(value or 0)

    def _summary(self, tx: Tx, season: dict[str, Any], proposal: dict[str, Any]):
        scope = SeasonScope.model_validate(proposal["scope"])
        return SeasonProposalSummary(
            season_id=season["id"],
            proposal_id=proposal["id"],
            state=SeasonState(season["state"]),
            revision=season["revision"],
            scope_version=proposal["scope_version"],
            scope_hash=proposal["scope_hash"],
            title_th=scope.title_th,
            title_en=scope.title_en,
            logline=scope.logline,
            research_spend_micro_usd=self._research_spend(tx, season["id"]),
            uncertainty_notes=list(scope.uncertainty_notes),
        )

    # --- season reads --------------------------------------------------------------

    def season_proposals(self) -> list[SeasonProposalSummary]:
        """Every season with its newest proposal (no secrets: scope text only, no credentials)."""
        with self._db.transaction(readonly=True) as tx:
            out: list[SeasonProposalSummary] = []
            for season in tx.fetchall("SELECT * FROM seasons ORDER BY created_at, id"):
                proposal = self._current_proposal(tx, season["id"])
                if proposal is not None:
                    out.append(self._summary(tx, season, proposal))
        return out

    def season_view(self, season_id: UUID) -> SeasonView:
        with self._db.transaction(readonly=True) as tx:
            season = tx.fetchone("SELECT * FROM seasons WHERE id = %s", (season_id,))
            if season is None:
                raise NotFound(f"season {season_id} not found")
            proposal = self._current_proposal(tx, season_id)
            if proposal is None:
                raise NotFound(f"season {season_id} has no proposal")
            summary = self._summary(tx, season, proposal)
            scope = SeasonScope.model_validate(proposal["scope"])
        return SeasonView(
            summary=summary, scope=scope, evidence_refs=list(scope.research_evidence_refs)
        )

    # --- gate 1 --------------------------------------------------------------------

    def decide_season(
        self, principal: Principal, season_id: UUID, command: ApprovalCommand
    ) -> CommandResult:
        require_human_owner(principal)
        _check_gate_fields(GateType.SEASON_CONCEPT, season_id, command)
        if command.action not in (ApprovalAction.APPROVE, ApprovalAction.REJECT):
            raise SchemaInvalid("Gate 1 accepts APPROVE or REJECT only")
        return self._idempotency.execute(
            scope=f"POST /seasons/{season_id}/approval",
            key=command.idempotency_key,
            principal_id=principal.principal_id,
            request_hash=canonical_hash(command),
            action=lambda tx: self._gate1_action(tx, principal, season_id, command),
        )

    def _gate1_action(
        self, tx: Tx, principal: Principal, season_id: UUID, command: ApprovalCommand
    ) -> tuple[int, dict[str, Any]]:
        now = self._now()
        correlation = self._ids.new_id()
        season = tx.fetchone("SELECT * FROM seasons WHERE id = %s FOR UPDATE", (season_id,))
        if season is None:
            raise NotFound(f"season {season_id} not found")
        if season["state"] != SeasonState.PROPOSED.value:
            raise InvalidTransition(
                f"season is {season['state']}; only a PROPOSED season takes a Gate 1 decision",
                state=season["state"],
            )
        proposal = self._current_proposal(tx, season_id, lock=True)
        if proposal is None or proposal["status"] != "PROPOSED":
            raise GateNotReady("season has no open proposal to decide")
        if command.package_hash != proposal["scope_hash"]:
            raise StaleRevision(
                "the season proposal changed since this decision was prepared",
                current_scope_hash=proposal["scope_hash"],
            )
        if command.expected_revision != season["revision"]:
            raise StaleRevision(
                f"season is at revision {season['revision']}, decision was made at "
                f"{command.expected_revision}",
                current_revision=season["revision"],
            )

        approval_id = record_approval_event(
            tx, principal=principal, command=command, now=now, correlation_id=correlation
        )
        if command.action is ApprovalAction.REJECT:
            revision = transition_season(
                tx,
                season_id=season_id,
                to=SeasonState.REJECTED,
                expected_revision=season["revision"],
                actor=principal,
                now=now,
                correlation_id=correlation,
                approval_event_id=approval_id,
                reason=command.reason,
            )
            self._set_proposal_status(tx, proposal, "REJECTED", now)
            body = CommandAccepted(
                status="RECORDED", entity_id=season_id, event_id=approval_id, revision=revision
            )
            return 202, body.model_dump(mode="json")

        revision = transition_season(
            tx,
            season_id=season_id,
            to=SeasonState.SEASON_APPROVED,
            expected_revision=season["revision"],
            actor=principal,
            now=now,
            correlation_id=correlation,
            approval_event_id=approval_id,
            scope_version=proposal["scope_version"],
        )
        self._set_proposal_status(tx, proposal, "APPROVED", now)
        tx.execute(
            "UPDATE season_proposals SET status = 'SUPERSEDED', revision = revision + 1, "
            "updated_at = %s WHERE season_id = %s AND status = 'PROPOSED' AND id <> %s",
            (now, season_id, proposal["id"]),
        )
        job = self._jobs.enqueue(
            tx,
            job_type="story.compile_season",
            semantic_key=f"story.compile_season:{season_id}:{proposal['scope_version']}",
            payload=SeasonStepInput(
                season_id=season_id,
                scope_version=proposal["scope_version"],
                trigger="gate1_approved",
            ),
            season_id=season_id,
            correlation_id=correlation,
            causation_id=approval_id,
        )
        body = CommandAccepted(
            status="QUEUED",
            entity_id=season_id,
            job_id=job.job_id,
            event_id=approval_id,
            revision=revision,
        )
        return 202, body.model_dump(mode="json")

    @staticmethod
    def _set_proposal_status(tx: Tx, proposal: dict[str, Any], status: str, now: datetime) -> None:
        update_with_revision(
            tx,
            "season_proposals",
            proposal["id"],
            proposal["revision"],
            {"status": status},
            now=now,
        )

    # --- gate 2 reads --------------------------------------------------------------

    def _media_links(
        self, tx: Tx, package: ReleasePackage | None
    ) -> tuple[list[ReviewMediaLink], dict[str, str]]:
        if package is None:
            return [], {}
        entries: dict[UUID, tuple[str, str | None]] = {}
        for media in package.media:
            entries.setdefault(media.asset_id, (media.role, media.sha256))
        for asset_id in package.cast_package_asset_ids:
            entries.setdefault(asset_id, ("cast_package", None))
        for track_id in package.caption_track_ids:
            row = tx.fetchone("SELECT asset_id FROM caption_tracks WHERE id = %s", (track_id,))
            if row is not None and row["asset_id"] is not None:
                entries.setdefault(row["asset_id"], ("caption", None))
        links: list[ReviewMediaLink] = []
        media_types: dict[str, str] = {}
        for asset_id, (role, _sha) in entries.items():
            asset = tx.fetchone("SELECT sha256, media_type FROM assets WHERE id = %s", (asset_id,))
            if asset is None:
                continue
            media_types[str(asset_id)] = asset["media_type"]
            links.append(
                ReviewMediaLink(
                    asset_id=asset_id,
                    role=role,
                    sha256=asset["sha256"],
                    review_path=f"/ui/media/{asset_id}",
                )
            )
        return links, media_types

    @staticmethod
    def _coverage(tx: Tx, episode_id: UUID) -> list[CoverageWindow]:
        row = tx.fetchone(
            "SELECT report FROM qa_observations WHERE episode_id = %s "
            "ORDER BY frozen_at DESC, created_at DESC LIMIT 1",
            (episode_id,),
        )
        if row is None:
            return []
        return list(ObservationReport.model_validate(row["report"]).coverage)

    def _cost(self, episode_id: UUID) -> CostSummary | None:
        try:
            return self._budget.summary(episode_id)
        except NotFound:
            return None

    def _review_state(self, tx: Tx, episode_id: UUID):
        episode = tx.fetchone("SELECT * FROM episodes WHERE id = %s", (episode_id,))
        if episode is None:
            raise NotFound(f"episode {episode_id} not found")
        stored = current_package(tx, episode_id)
        blockers = gate2_blockers(
            tx,
            episode_row=episode,
            package=stored,
            store=self._store,
            release_conditions_fn=self._release_conditions_fn,
            clock=self._clock,
        )
        return episode, stored, blockers

    @staticmethod
    def _finding_rows(tx: Tx, episode_id: UUID) -> list[QaFindingRow]:
        return [
            QaFindingRow(
                finding_id=row["id"],
                qa_cycle=row["qa_cycle"],
                resolution=row["resolution"],
                blocks_gate=finding_blocks(row["severity"], row["outcome"], row["resolution"]),
                finding=QAFinding.model_validate(row["body"]),
            )
            for row in episode_findings(tx, episode_id)
        ]

    def qa_finding_rows(self, episode_id: UUID) -> list[QaFindingRow]:
        """Every QA finding of the episode, all cycles, with its cycle and gate effect."""
        with self._db.transaction(readonly=True) as tx:
            if tx.fetchone("SELECT id FROM episodes WHERE id = %s", (episode_id,)) is None:
                raise NotFound(f"episode {episode_id} not found")
            return self._finding_rows(tx, episode_id)

    def episode_review(self, episode_id: UUID) -> EpisodeReviewView:
        """The Gate 2 review: package, media, QA with every unknown, cost, policy and blockers."""
        with self._db.transaction() as tx:
            episode, stored, blockers = self._review_state(tx, episode_id)
            package = stored.package if stored is not None else None
            media, _types = self._media_links(tx, package)
            finding_rows = self._finding_rows(tx, episode_id)
            coverage = self._coverage(tx, episode_id)
            approved = approved_scope(tx, episode["season_id"])
        return EpisodeReviewView(
            episode_id=episode_id,
            episode_number=episode["episode_number"],
            state=EpisodeState(episode["state"]),
            outcome=EpisodeOutcome(episode["outcome"]) if episode["outcome"] else None,
            revision=episode["revision"],
            package=package,
            gate_enabled=not blockers,
            gate_blockers=blockers,
            media=media,
            findings=[row.finding for row in finding_rows],
            coverage=coverage,
            cost=self._cost(episode_id),
            management_policy=approved.management_policy if approved is not None else None,
        )

    def episode_page(self, episode_id: UUID) -> EpisodePage:
        view = self.episode_review(episode_id)
        with self._db.transaction(readonly=True) as tx:
            stored = current_package(tx, episode_id)
            _media, media_types = self._media_links(tx, view.package)
            captions: list[CaptionPreview] = []
            track_ids = list(view.package.caption_track_ids) if view.package else []
            for row in tx.fetchall(
                "SELECT id FROM caption_tracks WHERE episode_id = %s AND state = 'CURRENT' "
                "ORDER BY locale, id",
                (episode_id,),
            ):
                if row["id"] not in track_ids:
                    track_ids.append(row["id"])
            for track_id in track_ids:
                row = tx.fetchone("SELECT * FROM caption_tracks WHERE id = %s", (track_id,))
                if row is None:
                    continue
                try:
                    body = CaptionTrack.model_validate(row["body"])
                    cues = tuple((c.start_ms, c.end_ms, c.text) for c in body.cues)
                    readable = True
                except ValidationError:
                    # A stored track that does not parse is shown as unreadable, never as cues.
                    cues, readable = (), False
                captions.append(
                    CaptionPreview(
                        track_id=track_id,
                        locale=row["locale"],
                        timing_source=row["timing_source"],
                        state=row["state"],
                        releasable=row["state"] == "CURRENT"
                        and row["timing_source"] == _ACTUAL_AUDIO,
                        readable=readable,
                        cues=cues,
                    )
                )
            hooks: list[dict[str, Any]] = []
            if view.package is not None and view.package.hook_experiment_id is not None:
                row = tx.fetchone(
                    "SELECT body FROM hook_experiments WHERE id = %s",
                    (view.package.hook_experiment_id,),
                )
                if row is not None:
                    experiment = HookExperiment.model_validate(row["body"])
                    hooks = [
                        {
                            "candidate_id": c.candidate_id,
                            "duration_ms": c.duration_ms,
                            "treatment": c.treatment,
                        }
                        for c in experiment.candidates
                    ]
            finding_rows = tuple(self._finding_rows(tx, episode_id))
        can_decide = (
            view.state is EpisodeState.AWAITING_FINAL_REVIEW
            and view.outcome is None
            and stored is not None
            and stored.status in (PackageStatus.READY, PackageStatus.BLOCKED)
        )
        return EpisodePage(
            view=view,
            captions=tuple(captions),
            media_types=media_types,
            hook_candidates=tuple(hooks),
            can_decide=can_decide,
            finding_rows=finding_rows,
        )

    def media_file(self, asset_id: UUID) -> MediaFile:
        """Private object for an owner-authenticated stream; the caller checks the session."""
        with self._db.transaction(readonly=True) as tx:
            row = tx.fetchone(
                "SELECT object_key, media_type, sha256 FROM assets WHERE id = %s", (asset_id,)
            )
        if row is None:
            raise NotFound(f"asset {asset_id} not found")
        return MediaFile(
            path=self._store.local_path(row["object_key"]),
            media_type=row["media_type"],
            sha256=row["sha256"],
        )

    # --- gate 2 decisions ----------------------------------------------------------

    def decide_episode(
        self, principal: Principal, episode_id: UUID, command: ApprovalCommand
    ) -> CommandResult:
        require_human_owner(principal)
        _check_gate_fields(GateType.EPISODE_FINAL, episode_id, command)
        return self._idempotency.execute(
            scope=f"POST /episodes/{episode_id}/review",
            key=command.idempotency_key,
            principal_id=principal.principal_id,
            request_hash=canonical_hash(command),
            action=lambda tx: self._gate2_action(tx, principal, episode_id, command),
        )

    @staticmethod
    def _check_binding(command: ApprovalCommand, stored: StoredPackage) -> None:
        """Every hash the reviewer saw must still be the current package's (else 409)."""
        if command.package_hash != stored.package_hash:
            raise StaleRevision(
                "the release package this decision names is not the current package",
                current_package_hash=stored.package_hash,
            )
        if command.action is ApprovalAction.APPROVE:
            media_ok = sorted(command.media_hashes) == stored.media_hashes
            policy_ok = command.management_policy_hash == stored.management_policy_hash
            scope_ok = command.release_scope_hash == stored.release_scope_hash
        else:
            media_ok = (
                not command.media_hashes or sorted(command.media_hashes) == stored.media_hashes
            )
            policy_ok = (
                command.management_policy_hash is None
                or command.management_policy_hash == stored.management_policy_hash
            )
            scope_ok = (
                command.release_scope_hash is None
                or command.release_scope_hash == stored.release_scope_hash
            )
        if not (media_ok and policy_ok and scope_ok):
            raise StaleRevision(
                "the decision's media, management-policy or release-scope hashes do not match "
                "the current package",
                media_matches=media_ok,
                policy_matches=policy_ok,
                scope_matches=scope_ok,
            )

    def _gate2_action(
        self, tx: Tx, principal: Principal, episode_id: UUID, command: ApprovalCommand
    ) -> tuple[int, dict[str, Any]]:
        now = self._now()
        correlation = self._ids.new_id()
        episode = tx.fetchone("SELECT * FROM episodes WHERE id = %s FOR UPDATE", (episode_id,))
        if episode is None:
            raise NotFound(f"episode {episode_id} not found")
        if command.expected_revision != episode["revision"]:
            raise StaleRevision(
                f"episode is at revision {episode['revision']}, decision was made at "
                f"{command.expected_revision}",
                current_revision=episode["revision"],
            )
        stored = current_package(tx, episode_id)
        if stored is None:
            raise StaleRevision("no current release package to bind this decision to")
        self._check_binding(command, stored)

        if command.action is ApprovalAction.APPROVE:
            blockers = gate2_blockers(
                tx,
                episode_row=episode,
                package=stored,
                store=self._store,
                release_conditions_fn=self._release_conditions_fn,
                clock=self._clock,
            )
            if blockers:
                raise GateNotReady(
                    "Gate 2 approval is not enabled: " + "; ".join(blockers[:3]),
                    blockers=blockers,
                )
            if episode["episode_number"] == 1 and self._identity_lock_hook is None:
                raise GateNotReady("identity lock service not configured")
        else:
            self._require_decidable(episode, stored)

        approval_id = record_approval_event(
            tx,
            principal=principal,
            command=command,
            now=now,
            correlation_id=correlation,
            hooks=self._approval_hooks,
        )
        if command.action is ApprovalAction.APPROVE:
            return self._approve(
                tx, principal, episode, stored, command, approval_id, now, correlation
            )
        if command.action is ApprovalAction.REVISE:
            return self._revise(
                tx, principal, episode, stored, command, approval_id, now, correlation
            )
        return self._reject(tx, principal, episode, stored, command, approval_id, now, correlation)

    @staticmethod
    def _require_decidable(episode: dict[str, Any], stored: StoredPackage) -> None:
        if episode["state"] != EpisodeState.AWAITING_FINAL_REVIEW.value or episode["outcome"]:
            raise GateNotReady(
                f"episode is {episode['state']} (outcome {episode['outcome']}); "
                "Revise and Reject need AWAITING_FINAL_REVIEW",
            )
        if stored.status not in (PackageStatus.READY, PackageStatus.BLOCKED):
            raise GateNotReady(f"package v{stored.version} is {stored.status.value}, not decidable")

    def _approve(
        self,
        tx: Tx,
        principal: Principal,
        episode: dict[str, Any],
        stored: StoredPackage,
        command: ApprovalCommand,
        approval_id: UUID,
        now: datetime,
        correlation: UUID,
    ) -> tuple[int, dict[str, Any]]:
        episode_id = episode["id"]
        record_package_decision(
            tx, stored, status=PackageStatus.APPROVED, approval_event_id=approval_id, now=now
        )
        if episode["episode_number"] == 1:
            assert self._identity_lock_hook is not None  # checked before the approval was recorded
            self._identity_lock_hook.on_recorded(
                tx, approval_event_id=approval_id, command=command, principal=principal
            )
        revision = transition_episode(
            tx,
            episode_id=episode_id,
            to=EpisodeState.RELEASE_APPROVED,
            expected_revision=episode["revision"],
            actor=principal,
            now=now,
            correlation_id=correlation,
            approval_event_id=approval_id,
        )
        job = self._jobs.enqueue(
            tx,
            job_type="publish.schedule_release",
            semantic_key=f"publish.schedule_release:{episode_id}:{stored.package_hash}",
            payload=EpisodeStepInput(
                episode_id=episode_id, expected_revision=revision, trigger="gate2_approved"
            ),
            episode_id=episode_id,
            correlation_id=correlation,
            causation_id=approval_id,
        )
        body = CommandAccepted(
            status="QUEUED",
            entity_id=episode_id,
            job_id=job.job_id,
            event_id=approval_id,
            revision=revision,
        )
        return 202, body.model_dump(mode="json")

    def _revise(
        self,
        tx: Tx,
        principal: Principal,
        episode: dict[str, Any],
        stored: StoredPackage,
        command: ApprovalCommand,
        approval_id: UUID,
        now: datetime,
        correlation: UUID,
    ) -> tuple[int, dict[str, Any]]:
        episode_id = episode["id"]
        revision = transition_episode(
            tx,
            episode_id=episode_id,
            to=repair_stage_for(command.feedback),
            expected_revision=episode["revision"],
            actor=principal,
            now=now,
            correlation_id=correlation,
            approval_event_id=approval_id,
        )
        revised = update_with_revision(
            tx,
            "episodes",
            episode_id,
            revision,
            {"qa_cycle": episode["qa_cycle"] + 1},
            now=now,
        )
        revision = revised["revision"]
        record_package_decision(
            tx, stored, status=PackageStatus.REVISED, approval_event_id=approval_id, now=now
        )
        job = self._jobs.enqueue(
            tx,
            job_type="qa.plan_repairs",
            semantic_key=f"qa.plan_repairs:{episode_id}:{approval_id}",
            payload=EpisodeStepInput(
                episode_id=episode_id, expected_revision=revision, trigger="human_feedback"
            ),
            episode_id=episode_id,
            correlation_id=correlation,
            causation_id=approval_id,
        )
        body = CommandAccepted(
            status="QUEUED",
            entity_id=episode_id,
            job_id=job.job_id,
            event_id=approval_id,
            revision=revision,
        )
        return 202, body.model_dump(mode="json")

    def _reject(
        self,
        tx: Tx,
        principal: Principal,
        episode: dict[str, Any],
        stored: StoredPackage,
        command: ApprovalCommand,
        approval_id: UUID,
        now: datetime,
        correlation: UUID,
    ) -> tuple[int, dict[str, Any]]:
        episode_id = episode["id"]
        record_package_decision(
            tx, stored, status=PackageStatus.REJECTED, approval_event_id=approval_id, now=now
        )
        revision = set_episode_outcome(
            tx,
            episode_id=episode_id,
            outcome=EpisodeOutcome.REJECTED,
            expected_revision=episode["revision"],
            actor=principal,
            now=now,
            correlation_id=correlation,
            detail=(command.reason or "rejected at Gate 2"),
            approval_event_id=approval_id,
        )
        body = CommandAccepted(
            status="RECORDED", entity_id=episode_id, event_id=approval_id, revision=revision
        )
        return 202, body.model_dump(mode="json")


__all__ = [
    "CaptionPreview",
    "EpisodePage",
    "MediaFile",
    "ReviewService",
    "is_material_change",
    "metadata_within_policy",
    "parse_timecode",
    "repair_stage_for",
]
