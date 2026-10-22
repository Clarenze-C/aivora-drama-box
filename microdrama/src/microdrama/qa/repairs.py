"""Targeted repair planning and execution (T019; IMP-05, AT-07).

The planner turns typed repair inputs — REPAIRABLE QA findings (T017/T018) or
timecoded Gate 2 human feedback (T008 writes ``feedback_events``) — into the frozen
``RepairPlan`` contract: root cause per finding, cost estimate per step, dependency
order, and the smallest affected scope (only the cues/lines/shots the evidence
names — never a blanket re-render). Plans are durable ``repair_plans`` rows plus one
bounded ``qa.repair.planned`` event.

Limits are SHARED with the render service, never re-invented here: the attempt cap
and the final-repair-round cap come from the same ``ProductionLimits`` instance
``RoutingPolicy.from_limits`` anchors on, and a repair that would exceed them is
refused typed BEFORE any reservation or charge. The per-shot attempt count is read
from the render service's own durable ledger (``render.shot`` jobs, whose semantic
keys share ``routing.attempt_semantic_key``), and the cap refusal reuses the
router's own typed error.

Execution is cue-level where the root cause is caption-side: a subtitle defect
re-derives the affected cues from the current script into a new caption track
version — the render/shot pipeline is never invoked (the shot-dispatch port is the
seam; zero render operations is a test invariant, not a promise). Line/shot/script
repairs invalidate exactly the named assets and requeue only the affected stage
job. Changed final media reopens the review package path typed: the current open
package is superseded so no Gate 2 decision can bind changed content, and the
episode returns to Gate 2 through recorded state transitions — from RELEASE_APPROVED
on there is no path back, so the repair is refused with ``InvalidTransition``
instead of silently bypassing the gate.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid5

from pydantic import Field

from microdrama.budget import BudgetService
from microdrama.config import Settings
from microdrama.contracts.cost import (
    BudgetReservationRequest,
    ExposureCeilings,
    PriceQuote,
    UsageReceipt,
)
from microdrama.contracts.enums import (
    AssetState,
    BudgetCategory,
    BudgetScopeKind,
    CostBasis,
    EpisodeState,
    FeedbackCategory,
    PrincipalKind,
    Provenance,
    QueueName,
    ReceiptKind,
    RepairTarget,
    RepairTrigger,
)
from microdrama.contracts.errors import (
    BudgetExhausted,
    Conflict,
    GateNotReady,
    InvalidTransition,
    NotFound,
    PolicyDenied,
    ProviderError,
    SchemaInvalid,
    ServiceUnavailable,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.infra import Clock, IdGenerator
from microdrama.contracts.jobs import EpisodeStepInput
from microdrama.contracts.media import CaptionCue, CaptionTrack
from microdrama.contracts.primitives import (
    DEFAULT_LIMITS,
    ContractModel,
    Identifier,
    MicroUSD,
    ProductionLimits,
    ShortText,
)
from microdrama.contracts.principals import Principal
from microdrama.contracts.qa import QAFinding, RepairPlan, RepairStep
from microdrama.contracts.season import Script
from microdrama.core.events import append_event
from microdrama.core.jobs import JobService
from microdrama.core.state_machine import transition_episode
from microdrama.editing.captions import track_body_hash
from microdrama.editing.edl import caption_track_id_for
from microdrama.persistence.db import Database, Tx, insert_row, jsonb, update_with_revision
from microdrama.qa.report import load_cycles, load_findings
from microdrama.references.anchors import ref_id_for
from microdrama.rendering.routing import AttemptCapReached, attempt_semantic_key

REPAIRS_NAMESPACE = uuid5(UUID(int=0), "https://microdrama.invalid/ns/qa-repairs")

#: Durable events of this lane (rows in ``domain_events``).
PLAN_EVENT = "qa.repair.planned"
EXECUTED_EVENT = "qa.repair.executed"
RETURN_EVENT = "qa.repair.returned_to_gate2"
REFUSED_EVENT = "qa.repair.refused"

#: Pipeline rank for dependency ordering: upstream stages repair first, captions last.
TARGET_RANK: dict[RepairTarget, int] = {
    RepairTarget.SCRIPT: 0,
    RepairTarget.LINE: 1,
    RepairTarget.SHOT: 2,
    RepairTarget.AUDIO_MIX: 3,
    RepairTarget.EDIT: 4,
    RepairTarget.CAPTION: 5,
}

#: Budget category each repair target spends from (frozen allocation groups).
CATEGORY_BY_TARGET: dict[RepairTarget, BudgetCategory] = {
    RepairTarget.CAPTION: BudgetCategory.QA_CAPTIONS,
    RepairTarget.LINE: BudgetCategory.REFERENCES_DIALOGUE,
    RepairTarget.SHOT: BudgetCategory.GPU_GENERATION,
    RepairTarget.AUDIO_MIX: BudgetCategory.CPU_STORAGE_TRANSFER,
    RepairTarget.EDIT: BudgetCategory.CPU_STORAGE_TRANSFER,
    RepairTarget.SCRIPT: BudgetCategory.RESEARCH_SCRIPT_PROMPTS_METADATA,
}

#: Check ids the recheck scope covers per target ("necessary scope", SPEC §9).
RECHECKS_BY_TARGET: dict[RepairTarget, tuple[str, ...]] = {
    RepairTarget.CAPTION: (
        "caption.critical_term_match",
        "caption.cue_within_media",
        "caption.cue_bounds",
        "caption.cue_stale",
    ),
    RepairTarget.LINE: (
        "asr.critical_term_match",
        "asr.speaker_match",
        "asr.line_present",
    ),
    RepairTarget.SHOT: (
        "visual_identity.match",
        "visual_identity.anchor_match",
        "visual_identity.prop_match",
    ),
    RepairTarget.AUDIO_MIX: ("audio.silence", "audio.peaks"),
    RepairTarget.EDIT: ("temporal.black_frames", "temporal.frozen_frames"),
    RepairTarget.SCRIPT: ("narrative.planned_reveal_absent",),
}

#: Feedback category → repair targets (root cause of a human revision note).
TARGETS_BY_CATEGORY: dict[FeedbackCategory, tuple[RepairTarget, ...]] = {
    FeedbackCategory.SUBTITLES: (RepairTarget.CAPTION,),
    FeedbackCategory.IDENTITY_VOICE: (RepairTarget.LINE, RepairTarget.CAPTION),
    FeedbackCategory.THAI_DIALOGUE: (RepairTarget.LINE, RepairTarget.CAPTION),
    FeedbackCategory.CONTINUITY_PROPS: (RepairTarget.SHOT,),
    FeedbackCategory.MOTIVATION: (RepairTarget.SCRIPT,),
    FeedbackCategory.PACING: (RepairTarget.EDIT,),
    FeedbackCategory.SOUND: (RepairTarget.AUDIO_MIX,),
}

#: Episode states a final-media repair may run from; anything later (RELEASE_APPROVED
#: and the publication pipeline) has no typed path back to Gate 2 and is refused.
_REPAIRABLE_STATES = frozenset(
    {"SCRIPTING", "REFERENCES", "RENDERING", "ASSEMBLING", "AI_REVIEW", "AWAITING_FINAL_REVIEW"}
)
_PACKAGE_OPEN_STATUSES = ("DRAFT", "READY", "BLOCKED")
_MAX_EVENT_LIST = 50
_REPAIR_PRINCIPAL = Principal(principal_id="svc:qa-repairs", kind=PrincipalKind.SERVICE_WORKER)


class RepairCauseUnknown(PolicyDenied):
    """A repair input this planner cannot root-cause to a targeted scope."""

    code = "REPAIR_CAUSE_UNKNOWN"


class RepairRoundExceeded(PolicyDenied):
    """The automatic final-QA repair round cap (shared ProductionLimits) is exhausted."""

    code = "REPAIR_ROUND_LIMIT"


class NoRepairableInput(PolicyDenied):
    """Nothing repairable to plan from (typed, never a silent empty plan)."""

    code = "NOTHING_REPAIRABLE"


@dataclass(frozen=True)
class RepairsConfig:
    """Prices for paid repair steps. None (default) means the offline step is free
    and nothing is reserved — the same discipline as ``QAConfig.observer_price``."""

    caption_price: PriceQuote | None = None
    line_price: PriceQuote | None = None
    shot_price: PriceQuote | None = None
    media_price: PriceQuote | None = None  # EDIT / AUDIO_MIX steps
    script_price: PriceQuote | None = None
    reservation_ttl_ms: int = 900_000

    def __post_init__(self) -> None:
        if self.reservation_ttl_ms < 60_000:
            raise ValueError("reservation_ttl_ms must be at least one minute")

    def price_for(self, target: RepairTarget) -> PriceQuote | None:
        return {
            RepairTarget.CAPTION: self.caption_price,
            RepairTarget.LINE: self.line_price,
            RepairTarget.SHOT: self.shot_price,
            RepairTarget.EDIT: self.media_price,
            RepairTarget.AUDIO_MIX: self.media_price,
            RepairTarget.SCRIPT: self.script_price,
        }[target]


class ShotDispatchPort(Protocol):
    """The render-service seam: attempt accounting plus shot requeue dispatch.

    The composition root wires the router-backed implementation (T014's
    ``plan_promotion`` / ``dispatch_routed_attempt``); offline the default counts
    attempts from the durable ``render.shot`` job ledger and refuses dispatch.
    """

    def attempts_used(self, *, episode_number: int, shot_id: str) -> int: ...

    def dispatch_repair(
        self, *, episode_id: UUID, episode_number: int, shot_id: str, attempt_number: int
    ) -> UUID: ...


class JobsShotDispatch:
    """Default port: attempts from the render service's own job ledger.

    Attempt keys are counted with ``routing.attempt_semantic_key``'s format, so the
    ledger this reads and the ledger the router writes are the same one.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def attempts_used(self, *, episode_number: int, shot_id: str) -> int:
        prefix = attempt_semantic_key(episode_number, shot_id, 1).rsplit("attempt", 1)[0]
        with self._db.transaction(readonly=True) as tx:
            rows = tx.fetchall(
                "SELECT semantic_key FROM jobs WHERE job_type = 'render.shot' "
                "AND semantic_key LIKE %s",
                (prefix + "attempt%",),
            )
        attempts: set[int] = set()
        for row in rows:
            suffix = str(row["semantic_key"]).rsplit("attempt", 1)[-1]
            if suffix.isdigit():
                attempts.add(int(suffix))
        return len(attempts)

    def dispatch_repair(
        self, *, episode_id: UUID, episode_number: int, shot_id: str, attempt_number: int
    ) -> UUID:
        raise ServiceUnavailable(
            "shot repair dispatch is not wired in this composition; the integrator "
            "registers the router-backed ShotDispatchPort",
            shot_id=shot_id,
        )


class RepairPlanOutcome(ContractModel):
    """What one planning call returns (the plan plus its durable row state)."""

    plan: RepairPlan
    status: ShortText
    replayed: bool
    notes: list[ShortText] = Field(default_factory=list)


class StepExecution(ContractModel):
    step_id: Identifier
    executed: bool
    detail: ShortText
    reservation_id: UUID | None = None
    settled_micro_usd: MicroUSD = 0


class RepairExecution(ContractModel):
    """What one ``execute_plan`` call did. Failed attempts keep their spend."""

    plan_id: UUID
    episode_id: UUID
    status: ShortText  # COMPLETED | FAILED
    steps: list[StepExecution] = Field(default_factory=list)
    invalidated_asset_ids: list[UUID] = Field(default_factory=list)
    new_caption_track_ids: list[UUID] = Field(default_factory=list)
    requeued_job_ids: list[UUID] = Field(default_factory=list)
    findings_resolved: list[UUID] = Field(default_factory=list)
    returns_to_gate2: bool
    settled_micro_usd: MicroUSD = 0
    notes: list[ShortText] = Field(default_factory=list)


def _line_audio_asset_id(episode_id: UUID, line_id: str, text_th: str) -> UUID:
    """The deterministic line-audio asset id the editing/references lanes share."""
    return ref_id_for("line-audio", f"{episode_id}:{line_id}:{canonical_hash(text_th)[:12]}")


def _script_lines(script: Script) -> dict[str, Any]:
    return {line.line_id: line for scene in script.scenes for line in scene.lines}


def _overlap(start_ms: int, end_ms: int, window: tuple[int, int]) -> bool:
    return start_ms < window[1] and max(end_ms, start_ms + 1) > window[0]


def _bounded(values: list[str]) -> list[str]:
    return values[:_MAX_EVENT_LIST]


class RepairService:
    """Plans and executes targeted repairs. Construct once per process."""

    def __init__(
        self,
        db: Database,
        clock: Clock,
        ids: IdGenerator,
        settings: Settings,
        *,
        budget: BudgetService,
        jobs: JobService | None = None,
        config: RepairsConfig | None = None,
        limits: ProductionLimits | None = None,
        shot_dispatch: ShotDispatchPort | None = None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._ids = ids
        self._settings = settings
        self._budget = budget
        self._jobs = jobs or JobService(db, clock, ids)
        self._config = config or RepairsConfig()
        # The SAME ProductionLimits the render service anchors on (single source).
        self._limits = limits or DEFAULT_LIMITS
        self._shot_dispatch: ShotDispatchPort = shot_dispatch or JobsShotDispatch(db)
        self._id_lock = threading.Lock()

    # --- plumbing --------------------------------------------------------------------

    @property
    def limits(self) -> ProductionLimits:
        return self._limits

    @property
    def config(self) -> RepairsConfig:
        return self._config

    def _new_id(self) -> UUID:
        with self._id_lock:
            return self._ids.new_id()

    def _now(self) -> datetime:
        now = self._clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise SchemaInvalid("clock must return a timezone-aware instant")
        return now

    def _row(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        with self._db.transaction(readonly=True) as tx:
            return tx.fetchone(sql, params)

    # --- reads -----------------------------------------------------------------------

    def _episode(self, episode_id: UUID) -> dict[str, Any]:
        row = self._row("SELECT * FROM episodes WHERE id = %s", (episode_id,))
        if row is None:
            raise NotFound("episode not found", episode_id=str(episode_id))
        return row

    def _script(self, episode_id: UUID) -> Script:
        row = self._row(
            "SELECT body FROM scripts WHERE episode_id = %s AND status = 'CURRENT'",
            (episode_id,),
        )
        if row is None:
            raise NotFound("episode has no current script", episode_id=str(episode_id))
        return Script.model_validate(row["body"])

    def _current_tracks(self, episode_id: UUID) -> list[CaptionTrack]:
        with self._db.transaction(readonly=True) as tx:
            rows = tx.fetchall(
                "SELECT body FROM caption_tracks WHERE episode_id = %s AND state = 'CURRENT' "
                "ORDER BY locale, id",
                (episode_id,),
            )
        return [CaptionTrack.model_validate(row["body"]) for row in rows]

    def _remaining_micro_usd(self, episode_id: UUID) -> int:
        try:
            return int(self._budget.summary(episode_id).remaining_micro_usd)
        except NotFound:
            return 0  # no episode account: there is nothing to spend from

    def _plan_row(self, plan_id: UUID) -> dict[str, Any] | None:
        return self._row("SELECT * FROM repair_plans WHERE id = %s", (plan_id,))

    # --- planning: findings ------------------------------------------------------------

    def plan_from_findings(self, episode_id: UUID) -> RepairPlanOutcome:
        """Plan one automatic final-QA repair round from the latest QA cycle."""
        episode = self._episode(episode_id)
        cycles = load_cycles(self._db, episode_id)
        if not cycles:
            raise NoRepairableInput("no QA findings exist for this episode")
        findings = load_findings(self._db, episode_id, cycle=cycles[-1])
        repairable = [f for f in findings if f.outcome.value == "REPAIRABLE"]
        if not repairable:
            raise NoRepairableInput(
                "the latest QA cycle has no REPAIRABLE finding to plan from",
                cycle=cycles[-1],
            )
        with self._db.transaction(readonly=True) as tx:
            # One round per planned QA cycle: re-planning the same cycle replays
            # the same round; a fresh QA cycle (post-repair re-check) is the next.
            prior_rounds = int(
                tx.fetchval(
                    "SELECT count(DISTINCT qa_cycle) FROM repair_plans "
                    "WHERE episode_id = %s AND trigger = 'QA_FINDING'",
                    (episode_id,),
                )
                or 0
            )
            existing = tx.fetchone(
                "SELECT * FROM repair_plans WHERE episode_id = %s "
                "AND trigger = 'QA_FINDING' AND qa_cycle = %s",
                (episode_id, cycles[-1]),
            )
        if existing is not None:
            return RepairPlanOutcome(
                plan=RepairPlan.model_validate(existing["body"]),
                status=str(existing["status"]),
                replayed=True,
                notes=["identical repair plan already persisted; nothing re-planned"],
            )
        round_number = prior_rounds + 1
        if round_number > self._limits.max_final_repair_rounds:
            self._refuse(
                episode_id,
                RepairRoundExceeded(
                    "the automatic final-QA repair round cap is exhausted; the episode "
                    "ends with a visible failure (no budget or round reset)",
                    round_number=round_number,
                    cap=self._limits.max_final_repair_rounds,
                ),
            )
        plan_id = uuid5(REPAIRS_NAMESPACE, f"plan:qa:{episode_id}:{cycles[-1]}:{round_number}")
        steps = self._steps_for_findings(episode_id, episode, repairable)
        return self._persist_plan(
            episode_id,
            episode,
            plan_id=plan_id,
            trigger=RepairTrigger.QA_FINDING,
            round_number=round_number,
            qa_cycle=cycles[-1],
            steps=steps,
            finding_ids=[f.finding_id for f in repairable],
            feedback_event_ids=[],
            source_approval_event_id=None,
        )

    # --- planning: human feedback --------------------------------------------------------

    def plan_from_feedback(self, episode_id: UUID, approval_event_id: UUID) -> RepairPlanOutcome:
        """Plan the smallest-scope repair for one Gate 2 REVISE decision."""
        episode = self._episode(episode_id)
        with self._db.transaction(readonly=True) as tx:
            approval = tx.fetchone(
                "SELECT id, gate_type, action, entity_id FROM approval_events WHERE id = %s",
                (approval_event_id,),
            )
            if approval is None:
                raise NotFound("approval event not found", approval_event_id=str(approval_event_id))
            if (
                approval["gate_type"] != "EPISODE_FINAL"
                or approval["action"] != "REVISE"
                or str(approval["entity_id"]) != str(episode_id)
            ):
                raise Conflict(
                    "repair planning consumes a Gate 2 REVISE decision for this episode",
                    approval_event_id=str(approval_event_id),
                )
            feedback = tx.fetchall(
                "SELECT * FROM feedback_events WHERE approval_event_id = %s ORDER BY id",
                (approval_event_id,),
            )
        if not feedback:
            raise NoRepairableInput("the REVISE decision carried no feedback items")
        plan_id = uuid5(REPAIRS_NAMESPACE, f"plan:feedback:{approval_event_id}")
        existing = self._plan_row(plan_id)
        if existing is not None:
            return RepairPlanOutcome(
                plan=RepairPlan.model_validate(existing["body"]),
                status=str(existing["status"]),
                replayed=True,
                notes=["identical repair plan already persisted; nothing re-planned"],
            )
        steps = self._steps_for_feedback(episode_id, episode, feedback)
        qa_cycle = max(int(episode["qa_cycle"] or 1), 1)
        return self._persist_plan(
            episode_id,
            episode,
            plan_id=plan_id,
            trigger=RepairTrigger.HUMAN_FEEDBACK,
            round_number=1,
            qa_cycle=qa_cycle,
            steps=steps,
            finding_ids=[],
            feedback_event_ids=[row["id"] for row in feedback],
            source_approval_event_id=approval_event_id,
        )

    # --- step construction ---------------------------------------------------------------

    def _steps_for_findings(
        self, episode_id: UUID, episode: dict[str, Any], findings: list[QAFinding]
    ) -> list[RepairStep]:
        script = self._script(episode_id)
        tracks = self._current_tracks(episode_id)
        line_targets: dict[str, set[str]] = {}
        caption_cues: set[str] = set()
        shot_ids: set[str] = set()
        stage_targets: set[RepairTarget] = set()
        for finding in findings:
            for target in finding.repair_targets:
                if target is RepairTarget.CAPTION:
                    caption_cues.update(
                        self._cues_in_window(tracks, finding.start_ms, finding.end_ms)
                    )
                elif target is RepairTarget.LINE:
                    lines = self._lines_in_window(tracks, finding.start_ms, finding.end_ms)
                    if not lines:
                        self._refuse(
                            episode_id,
                            RepairCauseUnknown(
                                "the finding's time range names no dialogue line; a line "
                                "repair cannot be targeted (never blanket)",
                                check_id=finding.check_id,
                                start_ms=finding.start_ms,
                                end_ms=finding.end_ms,
                            ),
                        )
                    for line_id in lines:
                        line_targets.setdefault(line_id, set()).update(
                            cue.cue_id
                            for track in tracks
                            for cue in track.cues
                            if cue.line_id == line_id
                        )
                elif target is RepairTarget.SHOT:
                    shots = self._shots_for_window(
                        episode_id, tracks, finding.start_ms, finding.end_ms
                    )
                    if not shots:
                        self._refuse(
                            episode_id,
                            RepairCauseUnknown(
                                "the finding's time range names no shot; a shot re-render "
                                "cannot be targeted (never blanket)",
                                check_id=finding.check_id,
                            ),
                        )
                    shot_ids.update(shots)
                else:
                    stage_targets.add(target)
        return self._assemble_steps(
            episode_id,
            episode,
            script,
            tracks,
            line_targets=line_targets,
            caption_cues=caption_cues,
            shot_ids=shot_ids,
            stage_targets=stage_targets,
        )

    def _steps_for_feedback(
        self, episode_id: UUID, episode: dict[str, Any], feedback: list[dict[str, Any]]
    ) -> list[RepairStep]:
        script = self._script(episode_id)
        tracks = self._current_tracks(episode_id)
        line_targets: dict[str, set[str]] = {}
        caption_cues: set[str] = set()
        shot_ids: set[str] = set()
        stage_targets: set[RepairTarget] = set()
        for item in feedback:
            category = FeedbackCategory(item["category"])
            window = (int(item["start_ms"]), int(item["end_ms"]))
            targets = TARGETS_BY_CATEGORY.get(category)
            if targets is None:
                self._refuse(
                    episode_id,
                    RepairCauseUnknown(
                        "feedback category has no root-cause mapping; it needs triage, "
                        "not a guessed repair",
                        category=category.value,
                    ),
                )
            for target in targets:
                if target is RepairTarget.CAPTION:
                    cues = self._cues_in_window(tracks, *window)
                    if not cues:
                        self._refuse(
                            episode_id,
                            RepairCauseUnknown(
                                "no caption cue falls inside the feedback timecodes; a "
                                "caption repair cannot be targeted (never blanket)",
                                start_ms=window[0],
                                end_ms=window[1],
                            ),
                        )
                    caption_cues.update(cues)
                elif target is RepairTarget.LINE:
                    lines = self._lines_in_window(tracks, *window)
                    if not lines:
                        self._refuse(
                            episode_id,
                            RepairCauseUnknown(
                                "no dialogue line falls inside the feedback timecodes",
                                start_ms=window[0],
                                end_ms=window[1],
                            ),
                        )
                    for line_id in lines:
                        line_targets.setdefault(line_id, set()).update(
                            cue.cue_id
                            for track in tracks
                            for cue in track.cues
                            if cue.line_id == line_id
                        )
                elif target is RepairTarget.SHOT:
                    shot_key = item["shot_key"]
                    if shot_key:
                        shot_ids.add(str(shot_key))
                        continue
                    shots = self._shots_for_window(episode_id, tracks, *window)
                    if not shots:
                        self._refuse(
                            episode_id,
                            RepairCauseUnknown(
                                "the feedback names no shot and its timecodes map to no "
                                "shot in the current manifest; a re-render cannot be "
                                "targeted (never blanket)",
                                category=category.value,
                            ),
                        )
                    shot_ids.update(shots)
                else:
                    stage_targets.add(target)
        return self._assemble_steps(
            episode_id,
            episode,
            script,
            tracks,
            line_targets=line_targets,
            caption_cues=caption_cues,
            shot_ids=shot_ids,
            stage_targets=stage_targets,
        )

    def _assemble_steps(
        self,
        episode_id: UUID,
        episode: dict[str, Any],
        script: Script,
        tracks: list[CaptionTrack],
        *,
        line_targets: dict[str, set[str]],
        caption_cues: set[str],
        shot_ids: set[str],
        stage_targets: set[RepairTarget],
    ) -> list[RepairStep]:
        # Line audio replacement invalidates exactly the derivative cues of the
        # replaced lines (every cue whose line_id is being re-voiced, across all
        # CURRENT locale tracks) — never another line's cues.
        caption_cues |= {
            cue.cue_id for track in tracks for cue in track.cues if cue.line_id in line_targets
        }

        steps: list[RepairStep] = []

        def add(
            step_id: str,
            target: RepairTarget,
            target_ids: list[str],
            action: str,
            *,
            invalidates: list[UUID] | None = None,
            consumes_shot_attempt: bool = False,
        ) -> None:
            price = self._config.price_for(target)
            units = max(1, len(target_ids))
            steps.append(
                RepairStep(
                    step_id=step_id,
                    target=target,
                    target_ids=target_ids,
                    action=action,
                    category=CATEGORY_BY_TARGET[target],
                    estimated_cost_micro_usd=(
                        price.unit_price_micro_usd * units if price is not None else 0
                    ),
                    invalidates_asset_ids=invalidates or [],
                    recheck_check_ids=list(RECHECKS_BY_TARGET.get(target, ())),
                    consumes_shot_attempt=consumes_shot_attempt,
                )
            )

        if RepairTarget.SCRIPT in stage_targets:
            add(
                "script",
                RepairTarget.SCRIPT,
                [str(episode_id)],
                "rewrite script inside approved scope",
            )
        if line_targets:
            lines = _script_lines(script)
            invalidates: list[UUID] = []
            for line_id in sorted(line_targets):
                line = lines.get(line_id)
                if line is not None:
                    invalidates.append(_line_audio_asset_id(episode_id, line_id, line.text_th))
            add(
                "lines",
                RepairTarget.LINE,
                sorted(line_targets),
                "replace the affected lines' audio with the intended voice",
                invalidates=invalidates,
            )
        for shot_id in sorted(shot_ids):
            add(
                f"shot.{shot_id}",
                RepairTarget.SHOT,
                [shot_id],
                "re-render the affected shot (an ordinary attempt)",
                consumes_shot_attempt=True,
            )
        for target in (RepairTarget.AUDIO_MIX, RepairTarget.EDIT):
            if target in stage_targets:
                add(str(target.value), target, [str(episode_id)], "re-cut from accepted footage")
        if caption_cues:
            add(
                "captions",
                RepairTarget.CAPTION,
                sorted(caption_cues),
                "re-derive the affected cues from the current script and actual audio",
            )
        if not steps:
            self._refuse(
                episode_id,
                NoRepairableInput("the repair inputs resolved to no repairable scope"),
            )
        steps.sort(key=lambda step: TARGET_RANK[step.target])
        return steps

    # --- scope resolution ------------------------------------------------------------------

    def _cues_in_window(self, tracks: list[CaptionTrack], start_ms: int, end_ms: int) -> list[str]:
        return [
            cue.cue_id
            for track in tracks
            for cue in track.cues
            if _overlap(cue.start_ms, cue.end_ms, (start_ms, end_ms))
        ]

    def _lines_in_window(self, tracks: list[CaptionTrack], start_ms: int, end_ms: int) -> list[str]:
        seen: list[str] = []
        for track in tracks:
            for cue in track.cues:
                if cue.line_id is not None and _overlap(
                    cue.start_ms, cue.end_ms, (start_ms, end_ms)
                ):
                    if cue.line_id not in seen:
                        seen.append(cue.line_id)
        return seen

    def _shots_for_window(
        self,
        episode_id: UUID,
        tracks: list[CaptionTrack],
        start_ms: int,
        end_ms: int,
    ) -> list[str]:
        """Shots owning the lines in the window, via the current shot manifest."""
        lines = set(self._lines_in_window(tracks, start_ms, end_ms))
        if not lines:
            return []
        row = self._row(
            "SELECT body FROM shot_manifests WHERE episode_id = %s AND status = 'CURRENT'",
            (episode_id,),
        )
        if row is None:
            return []
        from microdrama.contracts.season import ShotManifest

        manifest = ShotManifest.model_validate(row["body"])
        return [shot.shot_id for shot in manifest.shots if set(shot.line_ids) & lines]

    # --- plan persistence --------------------------------------------------------------------

    def _persist_plan(
        self,
        episode_id: UUID,
        episode: dict[str, Any],
        *,
        plan_id: UUID,
        trigger: RepairTrigger,
        round_number: int,
        qa_cycle: int,
        steps: list[RepairStep],
        finding_ids: list[UUID],
        feedback_event_ids: list[UUID],
        source_approval_event_id: UUID | None,
    ) -> RepairPlanOutcome:
        # Shared-limit guard: a SHOT repair would exceed the per-shot attempt cap —
        # refused typed BEFORE any reservation or charge (same cap, same error class
        # the router raises).
        episode_number = int(episode["episode_number"])
        for step in steps:
            if step.target is RepairTarget.SHOT:
                shot_id = step.target_ids[0]
                used = self._shot_dispatch.attempts_used(
                    episode_number=episode_number, shot_id=shot_id
                )
                if used + 1 > self._limits.max_attempts_per_shot:
                    self._refuse(
                        episode_id,
                        AttemptCapReached(
                            "repair re-render exceeds the existing per-shot attempt cap; "
                            "the shot's fallback edit path owns the next step",
                            attempt_number=used + 1,
                            cap=self._limits.max_attempts_per_shot,
                            shot_id=shot_id,
                        ),
                    )
        remaining = self._remaining_micro_usd(episode_id)
        total = sum(step.estimated_cost_micro_usd for step in steps)
        if total > remaining:
            self._refuse(
                episode_id,
                BudgetExhausted(
                    "repair plan exceeds the remaining episode funds; refused before any "
                    "spend (failed/rejected attempts do not reset the allowance)",
                    estimated_micro_usd=total,
                    remaining_micro_usd=remaining,
                ),
            )
        plan = RepairPlan(
            plan_id=plan_id,
            episode_id=episode_id,
            trigger=trigger,
            finding_ids=finding_ids,
            feedback_event_ids=feedback_event_ids,
            round_number=round_number,
            steps=steps,
            total_estimated_micro_usd=total,
            remaining_budget_micro_usd=remaining,
            returns_to_gate2=True,
            created_at=self._now(),
        )
        notes: list[str] = []
        if total == 0:
            notes.append("offline repair steps are free; no paid step configured")
        now = self._now()
        with self._db.transaction() as tx:
            insert_row(
                tx,
                "repair_plans",
                {
                    "id": plan_id,
                    "episode_id": episode_id,
                    "qa_cycle": qa_cycle,
                    "trigger": trigger.value,
                    "round_number": round_number,
                    "source_approval_event_id": source_approval_event_id,
                    "body": jsonb(plan),
                    "body_hash": canonical_hash(plan),
                    "total_estimated_micro_usd": total,
                    "status": "PLANNED",
                },
            )
            append_event(
                tx,
                aggregate_type="episode",
                aggregate_id=episode_id,
                event_type=PLAN_EVENT,
                payload={
                    "plan_id": str(plan_id),
                    "trigger": trigger.value,
                    "round_number": round_number,
                    "qa_cycle": qa_cycle,
                    "steps": [
                        {
                            "step_id": step.step_id,
                            "target": step.target.value,
                            "target_ids": _bounded(list(step.target_ids)),
                            "estimated_cost_micro_usd": step.estimated_cost_micro_usd,
                            "consumes_shot_attempt": step.consumes_shot_attempt,
                        }
                        for step in steps
                    ],
                    "total_estimated_micro_usd": total,
                    "remaining_budget_micro_usd": remaining,
                    "finding_ids": _bounded([str(f) for f in finding_ids]),
                    "feedback_event_ids": _bounded([str(f) for f in feedback_event_ids]),
                },
                correlation_id=self._new_id(),
                occurred_at=now,
            )
        return RepairPlanOutcome(plan=plan, status="PLANNED", replayed=False, notes=notes)

    def _refuse(self, episode_id: UUID, error: Exception) -> None:
        """Persist the typed refusal as an event, then raise it (nothing was spent)."""
        with self._db.transaction() as tx:
            append_event(
                tx,
                aggregate_type="episode",
                aggregate_id=episode_id,
                event_type=REFUSED_EVENT,
                payload={
                    "code": getattr(error, "code", "REPAIR_REFUSED"),
                    "detail": str(error)[:1000],
                },
                correlation_id=self._new_id(),
                occurred_at=self._now(),
            )
        raise error

    # --- execution -------------------------------------------------------------------------

    def execute_plan(self, plan_id: UUID) -> RepairExecution:
        """Execute one durable plan: reserve → step effects → recheck → Gate 2 return.

        Idempotent: a COMPLETED plan replays its stored outcome without re-executing
        anything; a FAILED plan cannot re-execute (plan a new round). A repair that
        would change final media while the episode sits past Gate 2 is refused typed
        BEFORE any mutation — there is no state path back, never a silent bypass.
        """
        row = self._plan_row(plan_id)
        if row is None:
            raise NotFound("repair plan not found", plan_id=str(plan_id))
        plan = RepairPlan.model_validate(row["body"])
        status = str(row["status"])
        if status == "COMPLETED":
            stored = self._stored_execution(plan_id)
            if stored is not None:
                return stored.model_copy(
                    update={"notes": stored.notes + ["plan already completed; nothing re-executed"]}
                )
            raise Conflict(
                "plan is COMPLETED but its execution event is missing", plan_id=str(plan_id)
            )
        if status != "PLANNED":
            raise Conflict(
                f"plan is {status}; only a PLANNED plan can execute",
                plan_id=str(plan_id),
                status=status,
            )
        episode = self._episode(plan.episode_id)
        # Typed gate guard FIRST: a final-media change with no path back to Gate 2 is
        # refused before anything is written or reserved.
        if episode["state"] not in _REPAIRABLE_STATES or episode["outcome"] is not None:
            self._refuse(
                plan.episode_id,
                InvalidTransition(
                    "this repair changes final media, but the episode is "
                    f"{episode['state']} (outcome {episode['outcome']}); there is no "
                    "state path back to Gate 2 — refused, never silently bypassed",
                    from_state=episode["state"],
                    to_state="AWAITING_FINAL_REVIEW",
                ),
            )
        remaining = self._remaining_micro_usd(plan.episode_id)
        if plan.total_estimated_micro_usd > remaining:
            self._refuse(
                plan.episode_id,
                BudgetExhausted(
                    "remaining funds fell below the plan estimate before execution",
                    estimated_micro_usd=plan.total_estimated_micro_usd,
                    remaining_micro_usd=remaining,
                ),
            )

        steps_done: list[StepExecution] = []
        invalidated: list[UUID] = []
        new_tracks: list[UUID] = []
        requeued: list[UUID] = []
        settled_total = 0
        with self._db.transaction() as tx:
            claimed = tx.fetchone(
                "UPDATE repair_plans SET status = 'EXECUTING', revision = revision + 1, "
                "updated_at = %s WHERE id = %s AND status = 'PLANNED' RETURNING id",
                (self._now(), plan_id),
            )
            if claimed is None:
                raise Conflict("another executor claimed this plan", plan_id=str(plan_id))
        script = self._script(plan.episode_id)
        duration_ms = self._media_duration_ms(plan)
        for step in plan.steps:
            reservation = self._maybe_reserve(plan, step)
            try:
                detail, step_invalidated, step_tracks, step_jobs = self._execute_step(
                    plan, step, script, duration_ms
                )
            except Exception as exc:
                # The dispatch happened; its charge is kept, never released.
                settled_total += self._settle_failure(plan, step, reservation)
                self._mark_failed(plan, step, steps_done, settled_total, str(exc))
                raise ProviderError(
                    "repair step failed after dispatch; the charge is kept",
                    provider=REPAIR_PROVIDER,
                    step_id=step.step_id,
                    settled_micro_usd=settled_total,
                ) from exc
            settled = self._settle_success(plan, step, reservation)
            settled_total += settled
            invalidated.extend(step_invalidated)
            new_tracks.extend(step_tracks)
            requeued.extend(step_jobs)
            steps_done.append(
                StepExecution(
                    step_id=step.step_id,
                    executed=True,
                    detail=detail[:500],
                    reservation_id=reservation.id if reservation is not None else None,
                    settled_micro_usd=settled,
                )
            )
        # Only cue-level (caption) plans complete synchronously offline; their
        # scoped recheck decides the typed return to Gate 2.
        synchronous = all(step.target is RepairTarget.CAPTION for step in plan.steps)
        returns_to_gate2 = False
        if synchronous:
            recheck_failures = _recheck_captions(
                self._current_tracks(plan.episode_id), script, duration_ms
            )
            if recheck_failures:
                self._mark_failed(
                    plan,
                    None,
                    steps_done,
                    settled_total,
                    "recheck failed: " + ",".join(recheck_failures[:5]),
                )
                raise GateNotReady(
                    "the scoped recheck still fails after the repair; the episode "
                    "does NOT return to Gate 2",
                    failing_checks=recheck_failures[:10],
                )
        with self._db.transaction() as tx:
            if synchronous:
                returns_to_gate2 = self._reopen_gate2(tx, plan)
            else:
                # Asynchronous stages own the climb back; the open package is
                # superseded now so no decision can bind media that is changing.
                self._supersede_open_packages(tx, plan.episode_id)
            if plan.finding_ids:
                tx.execute(
                    "UPDATE qa_findings SET resolution = 'RESOLVED' "
                    "WHERE id = ANY(%s) AND resolution = 'OPEN'",
                    ([str(f) for f in plan.finding_ids],),
                )
            self._mark_completed(
                tx,
                plan,
                steps_done,
                invalidated,
                new_tracks,
                requeued,
                settled_total,
                returns_to_gate2,
            )
        return RepairExecution(
            plan_id=plan_id,
            episode_id=plan.episode_id,
            status="COMPLETED",
            steps=steps_done,
            invalidated_asset_ids=invalidated,
            new_caption_track_ids=new_tracks,
            requeued_job_ids=requeued,
            findings_resolved=list(plan.finding_ids),
            returns_to_gate2=returns_to_gate2,
            settled_micro_usd=settled_total,
            notes=["caption repair is cue-level; the render pipeline was never invoked"]
            if synchronous
            else ["stage requeues own the return to Gate 2"],
        )

    def _execute_step(
        self,
        plan: RepairPlan,
        step: RepairStep,
        script: Script,
        duration_ms: int,
    ) -> tuple[str, list[UUID], list[UUID], list[UUID]]:
        """One step's durable effect (own transaction; a later failure never rolls
        back an earlier step's real invalidation)."""
        if step.target is RepairTarget.CAPTION:
            with self._db.transaction() as tx:
                new_ids = self._repair_captions(tx, plan, step, script, duration_ms)
            return (
                f"re-derived {len(step.target_ids)} cue(s) into new caption track versions",
                [],
                new_ids,
                [],
            )
        if step.target is RepairTarget.LINE:
            invalidated: list[UUID] = []
            lines = _script_lines(script)
            with self._db.transaction() as tx:
                for line_id in step.target_ids:
                    line = lines.get(line_id)
                    if line is None:
                        raise Conflict(
                            "plan names a line the current script no longer carries",
                            line_id=line_id,
                        )
                    asset_id = _line_audio_asset_id(plan.episode_id, line_id, line.text_th)
                    asset = tx.fetchone(
                        "SELECT id, state, revision FROM assets WHERE id = %s", (asset_id,)
                    )
                    if asset is not None and asset["state"] != AssetState.SUPERSEDED.value:
                        update_with_revision(
                            tx,
                            "assets",
                            asset_id,
                            int(asset["revision"]),
                            {"state": AssetState.SUPERSEDED.value},
                            now=self._now(),
                        )
                        invalidated.append(asset_id)
                job = self._jobs.enqueue(
                    tx,
                    job_type="references.prepare_episode",
                    semantic_key=f"repair:{plan.plan_id}:references",
                    payload=EpisodeStepInput(episode_id=plan.episode_id, trigger="qa_repair_line"),
                    episode_id=plan.episode_id,
                    correlation_id=plan.plan_id,
                )
            return (
                f"superseded {len(invalidated)} line audio asset(s); re-voicing requeued",
                invalidated,
                [],
                [job.job_id],
            )
        if step.target is RepairTarget.SHOT:
            # Dispatch runs through the render-service port OUTSIDE a repair
            # transaction: the port owns its own reservation and durable job.
            episode = self._episode(plan.episode_id)
            used = self._shot_dispatch.attempts_used(
                episode_number=int(episode["episode_number"]), shot_id=step.target_ids[0]
            )
            if used + 1 > self._limits.max_attempts_per_shot:
                raise AttemptCapReached(
                    "attempt exceeds the existing per-shot attempt cap during execution",
                    attempt_number=used + 1,
                    cap=self._limits.max_attempts_per_shot,
                )
            render_ref = self._shot_dispatch.dispatch_repair(
                episode_id=plan.episode_id,
                episode_number=int(episode["episode_number"]),
                shot_id=step.target_ids[0],
                attempt_number=used + 1,
            )
            return (
                f"re-render dispatched as ordinary attempt {used + 1} "
                f"(cap {self._limits.max_attempts_per_shot})",
                [],
                [],
                [render_ref],
            )
        job_type = (
            "story.write_episode" if step.target is RepairTarget.SCRIPT else "edit.assemble_episode"
        )
        trigger = "qa_repair_script" if step.target is RepairTarget.SCRIPT else "qa_repair_edit"
        with self._db.transaction() as tx:
            job = self._jobs.enqueue(
                tx,
                job_type=job_type,
                semantic_key=f"repair:{plan.plan_id}:{trigger}",
                payload=EpisodeStepInput(episode_id=plan.episode_id, trigger=trigger),
                episode_id=plan.episode_id,
                correlation_id=plan.plan_id,
            )
        return ("stage requeued through its ordinary job", [], [], [job.job_id])

    # --- caption repair (cue-level, no re-render) --------------------------------------------

    def _repair_captions(
        self,
        tx: Tx,
        plan: RepairPlan,
        step: RepairStep,
        script: Script,
        duration_ms: int,
    ) -> list[UUID]:
        """Re-derive ONLY the affected cues into new caption track versions.

        Every other cue is carried over byte-identical; no video/audio asset is
        touched and the render pipeline is never invoked. Old CURRENT rows flip to
        SUPERSEDED; the new row is the locale's next version (same one-current rule
        the editing lane enforces).
        """
        affected = set(step.target_ids)
        lines = _script_lines(script)
        new_ids: list[UUID] = []
        rows = tx.fetchall(
            "SELECT id, locale, version, body FROM caption_tracks "
            "WHERE episode_id = %s AND state = 'CURRENT' ORDER BY locale, id",
            (plan.episode_id,),
        )
        for row in rows:
            track = CaptionTrack.model_validate(row["body"])
            if not any(cue.cue_id in affected for cue in track.cues):
                continue  # this locale has no affected cue: nothing changes here
            thai = track.locale.lower().startswith("th")
            cues: list[CaptionCue] = []
            for cue in track.cues:
                if cue.cue_id not in affected:
                    cues.append(cue)
                    continue
                line = lines.get(cue.line_id) if cue.line_id else None
                text = cue.text
                if line is not None:
                    text = line.text_th if thai else line.text_en
                start = max(0, min(cue.start_ms, max(duration_ms - 1, 1)))
                end = max(start + 1, min(max(cue.end_ms, start + 1), duration_ms))
                cues.append(
                    CaptionCue(
                        cue_id=cue.cue_id,
                        start_ms=start,
                        end_ms=end,
                        text=text,
                        line_id=cue.line_id,
                    )
                )
            cues = _normalize_cues(cues, duration_ms)
            draft = CaptionTrack(
                track_id=UUID(int=0),
                episode_id=track.episode_id,
                version=int(row["version"]) + 1,
                locale=track.locale,
                timing_source=track.timing_source,
                derived_from_audio_sha256=list(track.derived_from_audio_sha256),
                cues=cues,
            )
            body_hash = track_body_hash(draft)
            track_id = caption_track_id_for(plan.episode_id, track.locale, body_hash)
            repaired = draft.model_copy(update={"track_id": track_id})
            tx.execute(
                "UPDATE caption_tracks SET state = 'SUPERSEDED', revision = revision + 1, "
                "updated_at = %s WHERE id = %s AND state = 'CURRENT'",
                (self._now(), row["id"]),
            )
            insert_row(
                tx,
                "caption_tracks",
                {
                    "id": track_id,
                    "episode_id": plan.episode_id,
                    "locale": track.locale,
                    "version": int(row["version"]) + 1,
                    "timing_source": repaired.timing_source.value,
                    "body": jsonb(repaired),
                    "body_hash": body_hash,
                    "state": "CURRENT",
                },
                returning="id",
            )
            new_ids.append(track_id)
        if not new_ids:
            raise Conflict(
                "the plan's affected cues belong to no current caption track",
                plan_id=str(plan.plan_id),
            )
        return new_ids

    # --- gate 2 return --------------------------------------------------------------------

    def _reopen_gate2(self, tx: Tx, plan: RepairPlan) -> bool:
        """Changed final media reopens the review package path, typed and recorded.

        The current open package is superseded (no decision can bind changed media),
        a ``review.prepare_package`` job re-opens the package path, and the episode
        moves through recorded transitions back to AWAITING_FINAL_REVIEW. From
        states with no path the caller already refused; here every hop is legal.
        """
        episode = tx.fetchone(
            "SELECT state, outcome, revision FROM episodes WHERE id = %s FOR UPDATE",
            (plan.episode_id,),
        )
        if episode is None:
            raise NotFound("episode vanished during repair execution")
        self._supersede_open_packages(tx, plan.episode_id)
        job = self._jobs.enqueue(
            tx,
            job_type="review.prepare_package",
            semantic_key=f"repair:{plan.plan_id}:prepare_package",
            payload=EpisodeStepInput(episode_id=plan.episode_id, trigger="qa_repair_gate2"),
            episode_id=plan.episode_id,
            correlation_id=plan.plan_id,
        )
        now = self._now()
        revision = int(episode["revision"])
        current = str(episode["state"])
        hops: list[str] = []
        if current == "ASSEMBLING":
            revision = transition_episode(
                tx,
                episode_id=plan.episode_id,
                to=EpisodeState.AI_REVIEW,
                expected_revision=revision,
                actor=_REPAIR_PRINCIPAL,
                now=now,
                correlation_id=plan.plan_id,
                reason="repair executed; re-entering AI review",
            )
            hops.append("ASSEMBLING->AI_REVIEW")
            current = "AI_REVIEW"
        if current == "AI_REVIEW":
            transition_episode(
                tx,
                episode_id=plan.episode_id,
                to=EpisodeState.AWAITING_FINAL_REVIEW,
                expected_revision=revision,
                actor=_REPAIR_PRINCIPAL,
                now=now,
                correlation_id=plan.plan_id,
                reason="scoped recheck passed; final media returns to Gate 2",
            )
            hops.append("AI_REVIEW->AWAITING_FINAL_REVIEW")
        else:
            # Deeper repair stages: the requeued stages own the climb; nothing is
            # skipped and no state is claimed that did not actually run.
            append_event(
                tx,
                aggregate_type="episode",
                aggregate_id=plan.episode_id,
                event_type=RETURN_EVENT,
                payload={
                    "plan_id": str(plan.plan_id),
                    "returned": False,
                    "detail": "episode stays at its stage; requeued stages own the climb",
                    "state": current,
                },
                correlation_id=plan.plan_id,
                occurred_at=now,
            )
            return False
        append_event(
            tx,
            aggregate_type="episode",
            aggregate_id=plan.episode_id,
            event_type=RETURN_EVENT,
            payload={
                "plan_id": str(plan.plan_id),
                "returned": True,
                "hops": hops,
                "prepare_package_job_id": str(job.job_id),
                "package_status": "OPEN_PACKAGES_SUPERSEDED",
            },
            correlation_id=plan.plan_id,
            occurred_at=now,
        )
        return True

    def _supersede_open_packages(self, tx: Tx, episode_id: UUID) -> None:
        """Flip open packages (DRAFT/READY/BLOCKED) to SUPERSEDED (decision-proof)."""
        tx.execute(
            "UPDATE release_packages SET status = 'SUPERSEDED', revision = revision + 1, "
            "updated_at = %s WHERE episode_id = %s AND status = ANY(%s)",
            (self._now(), episode_id, list(_PACKAGE_OPEN_STATUSES)),
        )

    # --- budget hook ---------------------------------------------------------------------

    def _maybe_reserve(self, plan: RepairPlan, step: RepairStep):
        price = self._config.price_for(step.target)
        if price is None:
            return None
        semantic_key = f"qa.repair:{plan.episode_id}:{plan.plan_id.hex[:12]}:{step.step_id}"
        units = max(1, len(step.target_ids))
        now = self._now()
        return self._budget.reserve(
            BudgetReservationRequest(
                request_id=uuid5(REPAIRS_NAMESPACE, f"repairreq:{semantic_key}"),
                semantic_key=semantic_key,
                scope_kind=BudgetScopeKind.EPISODE,
                episode_id=plan.episode_id,
                category=CATEGORY_BY_TARGET[step.target],
                queue=QueueName.PRODUCTION,
                provider=REPAIR_PROVIDER,
                operation_kind=f"qa.repair.{step.target.value.lower()}",
                price=price,
                ceilings=ExposureCeilings(
                    timeout_ms=self._config.reservation_ttl_ms,
                    max_units=units,
                ),
                worst_case_micro_usd=price.unit_price_micro_usd * units,
                expires_at=now + timedelta(milliseconds=self._config.reservation_ttl_ms),
            )
        )

    def _settle_success(self, plan: RepairPlan, step: RepairStep, reservation) -> int:
        if reservation is None:
            return 0
        price = self._config.price_for(step.target)
        if price is None:  # pragma: no cover - a reservation implies a configured price
            raise SchemaInvalid("repair price disappeared between plan and execution")
        units = max(1, len(step.target_ids))
        amount = price.unit_price_micro_usd * units
        self._budget.record_usage(
            _repair_receipt(reservation, plan, step, price, units, amount, "settle", self._now())
        )
        return amount

    def _settle_failure(self, plan: RepairPlan, step: RepairStep, reservation) -> int:
        """A failed repair step keeps its charge: settle the held worst case."""
        if reservation is None:
            return 0
        price = self._config.price_for(step.target)
        if price is None:  # pragma: no cover - a reservation implies a configured price
            raise SchemaInvalid("repair price disappeared between plan and execution")
        units = max(1, len(step.target_ids))
        amount = max(price.unit_price_micro_usd * units, int(reservation.reserved_micro_usd))
        self._budget.record_usage(
            _repair_receipt(reservation, plan, step, price, units, amount, "failure", self._now())
        )
        return amount

    # --- status persistence -----------------------------------------------------------------

    def _mark_completed(
        self,
        tx: Tx,
        plan: RepairPlan,
        steps: list[StepExecution],
        invalidated: list[UUID],
        new_tracks: list[UUID],
        requeued: list[UUID],
        settled_total: int,
        returns_to_gate2: bool,
    ) -> None:
        execution = RepairExecution(
            plan_id=plan.plan_id,
            episode_id=plan.episode_id,
            status="COMPLETED",
            steps=steps,
            invalidated_asset_ids=invalidated,
            new_caption_track_ids=new_tracks,
            requeued_job_ids=requeued,
            findings_resolved=list(plan.finding_ids),
            returns_to_gate2=returns_to_gate2,
            settled_micro_usd=settled_total,
        )
        tx.execute(
            "UPDATE repair_plans SET status = 'COMPLETED', reservation_ids = %s, "
            "revision = revision + 1, updated_at = %s WHERE id = %s AND status = 'EXECUTING'",
            (
                jsonb([str(s.reservation_id) for s in steps if s.reservation_id is not None]),
                self._now(),
                plan.plan_id,
            ),
        )
        append_event(
            tx,
            aggregate_type="episode",
            aggregate_id=plan.episode_id,
            event_type=EXECUTED_EVENT,
            payload=_bounded_payload(execution),
            correlation_id=self._new_id(),
            occurred_at=self._now(),
        )

    def _mark_failed(
        self,
        plan: RepairPlan,
        step: RepairStep | None,
        steps: list[StepExecution],
        settled_total: int,
        detail: str,
    ) -> None:
        """Persist the FAILED status in its OWN transaction (a rolled-back step
        effect must not erase the failure record — failures stay visible)."""
        with self._db.transaction() as tx:
            tx.execute(
                "UPDATE repair_plans SET status = 'FAILED', revision = revision + 1, "
                "updated_at = %s WHERE id = %s AND status = 'EXECUTING'",
                (self._now(), plan.plan_id),
            )
            append_event(
                tx,
                aggregate_type="episode",
                aggregate_id=plan.episode_id,
                event_type=EXECUTED_EVENT,
                payload={
                    "plan_id": str(plan.plan_id),
                    "episode_id": str(plan.episode_id),
                    "status": "FAILED",
                    "steps": [s.model_dump(mode="json") for s in steps],
                    "settled_micro_usd": settled_total,
                    "failed_step_id": step.step_id if step is not None else None,
                    "detail": detail[:1000],
                    "returns_to_gate2": False,
                },
                correlation_id=self._new_id(),
                occurred_at=self._now(),
            )

    def _stored_execution(self, plan_id: UUID) -> RepairExecution | None:
        episode = self._row("SELECT episode_id FROM repair_plans WHERE id = %s", (plan_id,))
        if episode is None:
            return None
        row = self._row(
            "SELECT payload FROM domain_events WHERE aggregate_id = %s "
            "AND event_type = %s AND payload ->> 'plan_id' = %s "
            "AND payload ->> 'status' = 'COMPLETED' ORDER BY sequence DESC LIMIT 1",
            (episode["episode_id"], EXECUTED_EVENT, str(plan_id)),
        )
        if row is None:
            return None
        return RepairExecution.model_validate(row["payload"])

    def _media_duration_ms(self, plan: RepairPlan) -> int:
        """Duration for cue clamping: the episode's newest video asset's measured
        duration, else the furthest cue end (clamping never shortens the timeline)."""
        asset_row = self._row(
            "SELECT descriptor FROM assets WHERE episode_id = %s AND asset_kind = 'VIDEO' "
            "ORDER BY created_at DESC LIMIT 1",
            (plan.episode_id,),
        )
        if asset_row is not None:
            descriptor = asset_row["descriptor"] or {}
            duration = descriptor.get("media") or {}
            if duration.get("duration_ms"):
                return int(duration["duration_ms"])
        tracks = self._current_tracks(plan.episode_id)
        return max((cue.end_ms for track in tracks for cue in track.cues), default=1)


def _normalize_cues(cues: list[CaptionCue], duration_ms: int) -> list[CaptionCue]:
    """Keep cues ordered, non-overlapping and inside the media (deterministic)."""
    out: list[CaptionCue] = []
    for cue in cues:
        start = max(0, cue.start_ms)
        end = min(max(cue.end_ms, start + 1), max(duration_ms, start + 1))
        if out and start < out[-1].end_ms:
            start = out[-1].end_ms
            end = max(end, start + 1)
        if end <= start:
            end = start + 1
        out.append(cue.model_copy(update={"start_ms": start, "end_ms": end}))
    return out


def _recheck_captions(tracks: list[CaptionTrack], script: Script, duration_ms: int) -> list[str]:
    """Deterministic final-consistency recheck over the repaired caption tracks.

    Only what a caption-side repair can own: cue bounds/order inside the media and
    cue text re-derived from the current script. Anything deeper (audio, identity)
    is not claimed here — those rechecks belong to the re-observation cycle.
    """
    failures: set[str] = set()
    lines = _script_lines(script)
    for track in tracks:
        thai = track.locale.lower().startswith("th")
        previous_end = 0
        for cue in track.cues:
            if cue.start_ms < 0 or cue.end_ms > duration_ms or cue.end_ms <= cue.start_ms:
                failures.add("caption.cue_within_media")
            if cue.start_ms < previous_end:
                failures.add("caption.cue_bounds")
            previous_end = cue.end_ms
            line = lines.get(cue.line_id) if cue.line_id else None
            if line is not None:
                expected = line.text_th if thai else line.text_en
                if cue.text != expected:
                    failures.add("caption.critical_term_match")
    return sorted(failures)


def _bounded_payload(execution: RepairExecution) -> dict[str, Any]:
    payload = execution.model_dump(mode="json")
    for key in (
        "invalidated_asset_ids",
        "new_caption_track_ids",
        "requeued_job_ids",
        "findings_resolved",
    ):
        values = payload.get(key) or []
        payload[key] = values[:_MAX_EVENT_LIST]
        if len(values) > _MAX_EVENT_LIST:
            payload.setdefault("notes", []).append(f"{key} truncated to {_MAX_EVENT_LIST}")
    return payload


def _repair_receipt(
    reservation,
    plan: RepairPlan,
    step: RepairStep,
    price: PriceQuote,
    units: int,
    amount_micro_usd: int,
    suffix: str,
    observed_at: datetime,
) -> UsageReceipt:
    return UsageReceipt(
        receipt_id=uuid5(
            REPAIRS_NAMESPACE,
            f"repairreceipt:{reservation.semantic_key}:{suffix}:{units}",
        ),
        provider=REPAIR_PROVIDER,
        provider_receipt_id=f"qa-repair-{suffix}:{reservation.id}",
        kind=ReceiptKind.SETTLEMENT,
        cost_basis=CostBasis.SYNTHETIC_FAKE,
        reservation_id=reservation.id,
        episode_id=plan.episode_id,
        category=CATEGORY_BY_TARGET[step.target],
        amount_micro_usd=amount_micro_usd,
        units=units,
        unit=price.unit,
        observed_at=observed_at,
        provenance=Provenance.FAKE_SYNTHETIC,
    )


REPAIR_PROVIDER = "qa-repair-offline"


def build_repair_service(
    db: Database,
    clock: Clock,
    ids: IdGenerator,
    settings: Settings,
    *,
    budget: BudgetService,
    jobs: JobService | None = None,
    config: RepairsConfig | None = None,
    limits: ProductionLimits | None = None,
    shot_dispatch: ShotDispatchPort | None = None,
) -> RepairService:
    """Composition-time factory (the integrator registers routes/jobs, not this module)."""
    return RepairService(
        db,
        clock,
        ids,
        settings,
        budget=budget,
        jobs=jobs,
        config=config,
        limits=limits,
        shot_dispatch=shot_dispatch,
    )


__all__ = [
    "AttemptCapReached",
    "CATEGORY_BY_TARGET",
    "EXECUTED_EVENT",
    "NoRepairableInput",
    "PLAN_EVENT",
    "REFUSED_EVENT",
    "RECHECKS_BY_TARGET",
    "REPAIR_PROVIDER",
    "REPAIRS_NAMESPACE",
    "RepairCauseUnknown",
    "RepairExecution",
    "RepairPlanOutcome",
    "RepairRoundExceeded",
    "RepairService",
    "RepairsConfig",
    "RETURN_EVENT",
    "ShotDispatchPort",
    "StepExecution",
    "TARGET_RANK",
    "TARGETS_BY_CATEGORY",
    "JobsShotDispatch",
    "build_repair_service",
]
