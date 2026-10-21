"""Shot routing over compatible, benchmarked presets (T014, IMP-03).

SPEC §8 routing order, implemented exactly: first the hard-control filter (required
controls are never dropped — a fast text-only preset is *rejected* when the shot
requires references), then the quality gate, then ranking by **total accepted cost**
(``cost_per_accepted_shot`` + downstream repair), never by advertised speed. Simple
inserts may use FAST presets; emotional/dialogue shots route among QUALITY (with
CONTROL as the promotion terminal). Every routing decision — chosen preset, the full
rank table with cold/warm latencies, and every typed rejection — is a durable
``render.route_decision`` domain event, not a log line.

Attempt accounting is ordinary: attempts are numbered inside the existing cap the
``RenderRequest`` contract itself enforces (``ProductionLimits.max_attempts_per_shot``,
three by default). Failure-driven tier promotion (AT-07) re-routes the *next* attempt
on the PROMOTION_LADDER and consumes it — the router never invents an extra attempt,
and an attempt past the cap is refused typed before anything is reserved.

Dispatch is never free and never bypasses T013: ``dispatch_routed_attempt`` runs
``ComfyRenderService.reserve_attempt`` (real budget hold) before building the
``RenderRequest``, enqueues the durable ``render.shot`` job whose input is that exact
request, and submits through the ordinary adapter path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from microdrama.contracts.cost import RenderRequest
from microdrama.contracts.enums import ControlKind
from microdrama.contracts.errors import (
    Conflict,
    NotFound,
    PolicyDenied,
    SchemaInvalid,
)
from microdrama.contracts.infra import Clock
from microdrama.contracts.primitives import DEFAULT_LIMITS, ProductionLimits
from microdrama.contracts.season import Shot
from microdrama.core.events import append_event
from microdrama.core.jobs import JobService
from microdrama.persistence.db import Database
from microdrama.rendering.comfy_jobs import ComfyRenderService, render_id_for
from microdrama.rendering.leases import RENDERING_NAMESPACE
from microdrama.rendering.presets import (
    EligibilityReason,
    PresetCatalog,
    PresetTierClass,
    PresetView,
    promoted,
)

#: Aggregate/event names for durable routing decisions (rows in ``domain_events``).
ROUTING_AGGREGATE_TYPE = "render_routing"
ROUTE_DECISION_EVENT = "render.route_decision"

#: Shot classes that must route among QUALITY/CONTROL presets (SPEC §8: emotional and
#: dialogue shots use the best qualifying accepted-cost preset, never a fast one).
EMOTIONAL_PATTERNS = frozenset(
    {"confrontation_v1", "revelation_v1", "quiet_confession_v1", "cliffhanger_v1"}
)

#: Allowed tier classes per pattern. Everything not in the emotional set is a simple
#: insert class that may also use FAST presets (comic beats, practical prop action).
_ALLOWED_CLASSES: dict[str, frozenset[PresetTierClass]] = {
    **{
        pattern: frozenset({PresetTierClass.QUALITY, PresetTierClass.CONTROL})
        for pattern in EMOTIONAL_PATTERNS
    },
    "comic_reaction_v1": frozenset(
        {PresetTierClass.FAST, PresetTierClass.QUALITY, PresetTierClass.CONTROL}
    ),
    "practical_prop_action_v1": frozenset(
        {PresetTierClass.FAST, PresetTierClass.QUALITY, PresetTierClass.CONTROL}
    ),
}


def allowed_tier_classes(shot: Shot) -> frozenset[PresetTierClass]:
    """Tier classes this shot's pattern permits (routing policy, SPEC §8)."""
    return _ALLOWED_CLASSES.get(shot.shot_pattern_id.value, frozenset())


def is_critical_shot(shot: Shot) -> bool:
    """Critical shots face the quality gate: emotional patterns and any dialogue."""
    return shot.shot_pattern_id.value in EMOTIONAL_PATTERNS or (
        shot.dialogue_complexity.value != "NONE"
    )


def shot_class_key(shot: Shot) -> str:
    """The per-class key acceptance is measured against: the directing pattern id."""
    return shot.shot_pattern_id.value


#: After a promotion the eligible classes are the promoted class and everything
#: stronger on the ladder, intersected with the shot's own allowed classes.
_PROMOTION_CHAIN: dict[PresetTierClass, frozenset[PresetTierClass]] = {
    PresetTierClass.QUALITY: frozenset({PresetTierClass.QUALITY, PresetTierClass.CONTROL}),
    PresetTierClass.CONTROL: frozenset({PresetTierClass.CONTROL}),
}


def required_controls_for(shot: Shot) -> frozenset[ControlKind]:
    """Hard controls for the shot: identity controls plus the always-bound prompt."""
    return frozenset(set(shot.required_identity_controls) | {ControlKind.TEXT_PROMPT})


class RoutingPolicy:
    """Quality floors and the attempt cap. The cap IS the existing contract cap."""

    def __init__(
        self,
        *,
        critical_min_quality_bp: int = 5_000,
        min_class_acceptance_bp: int = 1_000,
        limits: ProductionLimits | None = None,
    ) -> None:
        if not 0 <= critical_min_quality_bp <= 10_000:
            raise SchemaInvalid("critical_min_quality_bp must be 0..10000")
        if not 0 <= min_class_acceptance_bp <= 10_000:
            raise SchemaInvalid("min_class_acceptance_bp must be 0..10000")
        self.critical_min_quality_bp = critical_min_quality_bp
        self.min_class_acceptance_bp = min_class_acceptance_bp
        self.limits = limits or DEFAULT_LIMITS

    @classmethod
    def from_limits(cls, limits: ProductionLimits) -> RoutingPolicy:
        """Policy anchored on the shared production limits (no second cap source)."""
        return cls(limits=limits)

    @property
    def max_attempts_per_shot(self) -> int:
        """The EXISTING attempt cap (contract ``RenderRequest`` enforces the same 3)."""
        return self.limits.max_attempts_per_shot


@dataclass(frozen=True)
class RouteRejection:
    """One preset's typed rejection. Part of the durable decision receipt."""

    preset_id: str
    reason: EligibilityReason
    detail: str

    def as_payload(self) -> dict[str, str]:
        return {"preset_id": self.preset_id, "reason": self.reason.value, "detail": self.detail}


@dataclass(frozen=True)
class RankedChoice:
    """One eligible preset with the figures ranking used (latency is receipt-only)."""

    preset_id: str
    tier_class: PresetTierClass
    total_accepted_cost_micro_usd: int
    critical_quality_bp: int
    class_acceptance_bp: int
    cold_start_ms: int
    warm_full_job_ms: int

    def as_payload(self) -> dict[str, Any]:
        return {
            "preset_id": self.preset_id,
            "tier_class": self.tier_class.value,
            "total_accepted_cost_micro_usd": self.total_accepted_cost_micro_usd,
            "critical_quality_bp": self.critical_quality_bp,
            "class_acceptance_bp": self.class_acceptance_bp,
            "cold_start_ms": self.cold_start_ms,
            "warm_full_job_ms": self.warm_full_job_ms,
        }


@dataclass(frozen=True)
class RouteDecision:
    """The durable outcome of routing one shot attempt."""

    decision_id: UUID
    episode_id: UUID
    shot_id: str
    manifest_version: int
    shot_class: str
    critical: bool
    chosen: RankedChoice | None
    ranked: tuple[RankedChoice, ...]
    rejections: tuple[RouteRejection, ...]
    attempt_number: int
    promotion_from: PresetTierClass | None
    max_attempts_per_shot: int
    event_id: UUID


def route_id_for(episode_id: UUID, shot_id: str, manifest_version: int) -> UUID:
    """Deterministic routing-aggregate id: one aggregate per shot per manifest version."""
    return uuid5(RENDERING_NAMESPACE, f"route:{episode_id}:{shot_id}:v{manifest_version}")


def attempt_semantic_key(episode_number: int, shot_id: str, attempt_number: int) -> str:
    """The ordinary attempt key (house pattern from T013's mock pipeline)."""
    return f"render.shot:ep{episode_number}:{shot_id}:attempt{attempt_number}"


def attempt_seed(episode_id: UUID, shot_id: str, attempt_number: int) -> int:
    """Deterministic per-attempt seed (idempotency: same attempt, same seed)."""
    digest = uuid5(RENDERING_NAMESPACE, f"seed:{episode_id}:{shot_id}:a{attempt_number}")
    return digest.int % (2**31)


class NoCompatiblePreset(PolicyDenied):
    """No enabled, measured, compatible preset survived the filters."""

    code = "NO_COMPATIBLE_PRESET"


class AttemptCapReached(PolicyDenied):
    """The next attempt would exceed the existing per-shot attempt cap."""

    code = "ATTEMPT_CAP_REACHED"


class ShotRouter:
    """Filters, gates and ranks presets for one shot; persists every decision."""

    def __init__(
        self,
        db: Database,
        catalog: PresetCatalog,
        clock: Clock,
        policy: RoutingPolicy | None = None,
    ) -> None:
        self._db = db
        self._catalog = catalog
        self._clock = clock
        self._policy = policy or RoutingPolicy()

    @property
    def policy(self) -> RoutingPolicy:
        return self._policy

    # --- routing -------------------------------------------------------------------------

    def route_shot(
        self,
        shot: Shot,
        *,
        episode_id: UUID,
        manifest_version: int,
        attempt_number: int = 1,
        promotion_from: PresetTierClass | None = None,
    ) -> RouteDecision:
        """Route one attempt of a shot and persist the decision durably.

        ``promotion_from`` marks a failure-driven promotion (AT-07): the allowed tier
        classes shrink to the ladder successor chain of the failed class, and the
        attempt number is the ordinary next attempt — validated against the existing
        cap first, so a promotion past the cap is refused before anything is reserved.
        """
        self._check_attempt_number(attempt_number)
        if promotion_from is not None and attempt_number < 2:
            raise SchemaInvalid(
                "a promotion is a retry: attempt_number must be the next ordinary attempt"
            )
        allowed = self._allowed_classes_for(shot, promotion_from)
        required = required_controls_for(shot)
        shot_class = shot_class_key(shot)
        critical = is_critical_shot(shot)

        ranked: list[RankedChoice] = []
        rejections: list[RouteRejection] = []
        for record in self._catalog.current_records():
            view = self._catalog.view(record)
            if view is None:
                rejections.append(
                    RouteRejection(
                        preset_id=record.preset_id,
                        reason=EligibilityReason.NO_TEMPLATE,
                        detail="preset id has no PRESET_TEMPLATES mapping; extending "
                        "the mapping is a T013 handoff proposal",
                    )
                )
                continue
            outcome = self._evaluate(view, shot, required, allowed, critical)
            if isinstance(outcome, RouteRejection):
                rejections.append(outcome)
            else:
                ranked.append(outcome)

        # Rank by TOTAL ACCEPTED COST ascending (never by advertised speed); the
        # preset id breaks ties so the order is deterministic across processes.
        ranked.sort(key=lambda choice: (choice.total_accepted_cost_micro_usd, choice.preset_id))
        chosen = ranked[0] if ranked else None
        decision_id = route_id_for(episode_id, shot.shot_id, manifest_version)
        event = self._persist_decision(
            decision_id,
            episode_id=episode_id,
            shot=shot,
            shot_class=shot_class,
            critical=critical,
            chosen=chosen,
            ranked=tuple(ranked),
            rejections=tuple(rejections),
            attempt_number=attempt_number,
            promotion_from=promotion_from,
            manifest_version=manifest_version,
        )
        if chosen is None:
            raise NoCompatiblePreset(
                "no enabled, measured, compatible preset survived routing for this shot",
                shot_id=shot.shot_id,
                shot_class=shot_class,
                rejections=[r.as_payload() for r in rejections][:12],
            )
        return RouteDecision(
            decision_id=decision_id,
            episode_id=episode_id,
            shot_id=shot.shot_id,
            manifest_version=manifest_version,
            shot_class=shot_class,
            critical=critical,
            chosen=chosen,
            ranked=tuple(ranked),
            rejections=tuple(rejections),
            attempt_number=attempt_number,
            promotion_from=promotion_from,
            max_attempts_per_shot=self._policy.max_attempts_per_shot,
            event_id=event.event_id,
        )

    def plan_promotion(
        self,
        shot: Shot,
        *,
        episode_id: UUID,
        manifest_version: int,
        failed_attempt_number: int,
        failed_tier_class: PresetTierClass,
    ) -> RouteDecision:
        """Failure-driven tier promotion (AT-07): the NEXT ordinary attempt, stronger.

        Uses the existing attempt cap: the promoted attempt is number
        ``failed_attempt_number + 1`` and a promotion past the cap is refused typed
        (``AttemptCapReached``) before any reservation or dispatch. No new attempts
        are invented — the failed attempt already spent its ordinary slot.
        """
        if promoted(failed_tier_class) is None:
            raise NoCompatiblePreset(
                "the failed attempt already used the terminal tier class; the fallback "
                "edit path (not another paid attempt) owns the next step",
                shot_id=shot.shot_id,
                failed_tier_class=failed_tier_class.value,
            )
        return self.route_shot(
            shot,
            episode_id=episode_id,
            manifest_version=manifest_version,
            attempt_number=failed_attempt_number + 1,
            promotion_from=failed_tier_class,
        )

    def _check_attempt_number(self, attempt_number: int) -> None:
        cap = self._policy.max_attempts_per_shot
        if not 1 <= attempt_number <= cap:
            raise AttemptCapReached(
                "attempt exceeds the existing per-shot attempt cap; no new attempts "
                "are invented by routing or promotion",
                attempt_number=attempt_number,
                cap=cap,
            )

    def _allowed_classes_for(
        self, shot: Shot, promotion_from: PresetTierClass | None
    ) -> frozenset[PresetTierClass]:
        allowed = allowed_tier_classes(shot)
        if not allowed:
            raise SchemaInvalid(
                "shot pattern has no routing rule", pattern=shot.shot_pattern_id.value
            )
        if promotion_from is None:
            return allowed
        stronger = promoted(promotion_from)
        if stronger is None:
            raise SchemaInvalid("cannot promote past the terminal tier class")
        return allowed & _PROMOTION_CHAIN[stronger]

    def _evaluate(
        self,
        view: PresetView,
        shot: Shot,
        required: frozenset[ControlKind],
        allowed: frozenset[PresetTierClass],
        critical: bool,
    ) -> RankedChoice | RouteRejection:
        record = view.record
        if record.measured is None:
            # V-7 typed-unknown FIRST: an unmeasured preset is NEVER eligible, whatever
            # its enabled flag says (the contract already forbids enabled-unmeasured
            # records; this guard keeps that precedence if one shows up anyway).
            return RouteRejection(
                preset_id=record.preset_id,
                reason=EligibilityReason.UNMEASURED,
                detail="no measured benchmark evidence; unknown quality/cost is never eligible",
            )
        if not record.enabled:
            return RouteRejection(
                preset_id=record.preset_id,
                reason=EligibilityReason.DISABLED,
                detail="preset stays disabled until T031 records rights/quality/cost evidence",
            )
        missing = sorted(control.value for control in required - set(record.supported_controls))
        if missing:
            return RouteRejection(
                preset_id=record.preset_id,
                reason=EligibilityReason.HARD_CONTROL,
                detail="required controls not supported (never dropped): " + ",".join(missing),
            )
        if view.tier_class not in allowed:
            return RouteRejection(
                preset_id=record.preset_id,
                reason=EligibilityReason.TIER_POLICY,
                detail=f"tier class {view.tier_class.value} is not allowed for shot "
                f"class {shot_class_key(shot)}",
            )
        acceptance = view.acceptance_bp(shot_class_key(shot))
        if acceptance is None or acceptance <= 0:
            return RouteRejection(
                preset_id=record.preset_id,
                reason=EligibilityReason.CLASS_UNMEASURED,
                detail=f"acceptance for shot class {shot_class_key(shot)} is unknown "
                "(never measured, or measured zero)",
            )
        if acceptance < self._policy.min_class_acceptance_bp:
            return RouteRejection(
                preset_id=record.preset_id,
                reason=EligibilityReason.QUALITY_GATE,
                detail=f"class acceptance {acceptance}bp below policy floor "
                f"{self._policy.min_class_acceptance_bp}bp",
            )
        if critical and view.measured.critical_quality_pass_bp < (
            self._policy.critical_min_quality_bp
        ):
            return RouteRejection(
                preset_id=record.preset_id,
                reason=EligibilityReason.QUALITY_GATE,
                detail=f"critical quality {view.measured.critical_quality_pass_bp}bp "
                f"below policy floor {self._policy.critical_min_quality_bp}bp",
            )
        return RankedChoice(
            preset_id=record.preset_id,
            tier_class=view.tier_class,
            total_accepted_cost_micro_usd=view.total_accepted_cost_micro_usd,
            critical_quality_bp=view.measured.critical_quality_pass_bp,
            class_acceptance_bp=acceptance,
            cold_start_ms=view.cold_start_ms,
            warm_full_job_ms=view.warm_full_job_ms,
        )

    # --- durability ----------------------------------------------------------------------

    def _persist_decision(
        self,
        decision_id: UUID,
        *,
        episode_id: UUID,
        shot: Shot,
        shot_class: str,
        critical: bool,
        chosen: RankedChoice | None,
        ranked: tuple[RankedChoice, ...],
        rejections: tuple[RouteRejection, ...],
        attempt_number: int,
        promotion_from: PresetTierClass | None,
        manifest_version: int,
    ):
        now = self._now()
        payload: dict[str, Any] = {
            "episode_id": str(episode_id),
            "shot_id": shot.shot_id,
            "manifest_version": manifest_version,
            "shot_class": shot_class,
            "critical": critical,
            "attempt_number": attempt_number,
            "max_attempts_per_shot": self._policy.max_attempts_per_shot,
            "chosen": chosen.as_payload() if chosen else None,
            "ranked": [choice.as_payload() for choice in ranked],
            "rejections": [rejection.as_payload() for rejection in rejections],
            "policy": {
                "critical_min_quality_bp": self._policy.critical_min_quality_bp,
                "min_class_acceptance_bp": self._policy.min_class_acceptance_bp,
            },
        }
        if promotion_from is not None:
            payload["promotion_from"] = promotion_from.value
        with self._db.transaction() as tx:
            return append_event(
                tx,
                aggregate_type=ROUTING_AGGREGATE_TYPE,
                aggregate_id=decision_id,
                event_type=ROUTE_DECISION_EVENT,
                payload=payload,
                correlation_id=decision_id,
                occurred_at=now,
            )

    def _now(self) -> datetime:
        now = self._clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise Conflict("clock must return a timezone-aware instant")
        return now


@dataclass(frozen=True)
class RoutedAttempt:
    """A dispatched routed attempt: the request of record plus its durable links."""

    request: RenderRequest
    job_id: UUID
    decision: RouteDecision


def build_render_request(
    decision: RouteDecision,
    shot: Shot,
    *,
    view: PresetView,
    episode_id: UUID,
    episode_number: int,
    reference_asset_ids: list[UUID],
    identity_lock_id: UUID | None,
    reservation_id: UUID,
    attempt_number: int,
    prompt_text: str,
) -> RenderRequest:
    """Assemble the ``RenderRequest`` for a routed attempt (workflow pinned by routing).

    The template pin comes from the catalog view of the *chosen* preset, so a stored
    request always renders through the workflow the decision was ranked against.
    """
    semantic_key = attempt_semantic_key(episode_number, shot.shot_id, attempt_number)
    return RenderRequest(
        render_id=render_id_for(semantic_key),
        semantic_key=semantic_key,
        episode_id=episode_id,
        episode_number=episode_number,
        shot_id=shot.shot_id,
        manifest_version=decision.manifest_version,
        attempt_number=attempt_number,
        preset_id=view.preset_id,
        tier=view.record.tier,
        required_controls=sorted(required_controls_for(shot), key=lambda control: control.value),
        reference_asset_ids=list(reference_asset_ids),
        audio_asset_id=None,
        identity_lock_id=identity_lock_id,
        workflow_sha256=view.template_workflow_sha256,
        seed=attempt_seed(episode_id, shot.shot_id, attempt_number),
        width=view.record.width,
        height=view.record.height,
        fps=view.record.fps,
        duration_ms=shot.target_duration_ms,
        reservation_id=reservation_id,
        prompt_text=prompt_text,
        negative_prompt_text="",
    )


def dispatch_routed_attempt(
    db: Database,
    comfy: ComfyRenderService,
    jobs: JobService,
    *,
    decision: RouteDecision,
    shot: Shot,
    catalog: PresetCatalog,
    episode_number: int,
    reference_asset_ids: list[UUID],
    identity_lock_id: UUID | None,
    prompt_text: str,
    submit: bool = True,
) -> RoutedAttempt:
    """Pay for and dispatch one routed attempt through the T013 reserve→submit path.

    Order is fixed and observable: (1) ``reserve_attempt`` puts the real worst-case
    hold on the episode budget, (2) the ``RenderRequest`` is built against that hold
    with the routing-pinned workflow hash, (3) the durable ``render.shot`` job is
    enqueued with the exact request as input, (4) the ordinary T013 ``submit`` runs.
    There is no free path: without the reservation the request cannot even be built,
    and T013's own verification re-checks reservation ownership at submit time.
    """
    chosen = decision.chosen
    if chosen is None:
        raise PolicyDenied("cannot dispatch a decision without a chosen preset")
    view = _view_for(catalog, chosen.preset_id)
    key = attempt_semantic_key(episode_number, shot.shot_id, decision.attempt_number)
    reservation = comfy.reserve_attempt(episode_id=decision.episode_id, semantic_key=key)
    request = build_render_request(
        decision,
        shot,
        view=view,
        episode_id=decision.episode_id,
        episode_number=episode_number,
        reference_asset_ids=reference_asset_ids,
        identity_lock_id=identity_lock_id,
        reservation_id=reservation.id,
        attempt_number=decision.attempt_number,
        prompt_text=prompt_text,
    )
    with db.transaction() as tx:
        result = jobs.enqueue(tx, job_type="render.shot", semantic_key=key, payload=request)
    if submit:
        comfy.submit(request, job_id=result.job_id)
    return RoutedAttempt(request=request, job_id=result.job_id, decision=decision)


def _view_for(catalog: PresetCatalog, preset_id: str) -> PresetView:
    for record in catalog.current_records():
        if record.preset_id == preset_id:
            view = catalog.view(record)
            if view is None:
                raise NotFound("chosen preset has no template mapping", preset_id=preset_id)
            return view
    raise NotFound("preset record not found", preset_id=preset_id)


__all__ = [
    "AttemptCapReached",
    "EMOTIONAL_PATTERNS",
    "NoCompatiblePreset",
    "ROUTE_DECISION_EVENT",
    "ROUTING_AGGREGATE_TYPE",
    "RankedChoice",
    "RouteDecision",
    "RouteRejection",
    "RoutedAttempt",
    "RoutingPolicy",
    "ShotRouter",
    "allowed_tier_classes",
    "attempt_seed",
    "attempt_semantic_key",
    "build_render_request",
    "dispatch_routed_attempt",
    "is_critical_shot",
    "required_controls_for",
    "route_id_for",
    "shot_class_key",
]
