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

from collections.abc import Callable, Sequence
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
    UnsupportedControl,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.infra import Clock
from microdrama.contracts.primitives import DEFAULT_LIMITS, ProductionLimits
from microdrama.contracts.season import Shot, ShotManifest
from microdrama.contracts.v2 import (
    AssetSheet,
    DirectingManifest,
    EpisodePack,
    LocationLayout,
    PromptManifest,
    PropSheet,
    ReferenceRole,
    SceneWardrobeAssignment,
    SecretLedger,
    ShotReferenceBinding,
    StyleBible,
    V2Record,
    WardrobeBible,
    verify_v2_record_hash,
)
from microdrama.core.events import append_event
from microdrama.core.jobs import JobService
from microdrama.persistence.db import Database
from microdrama.references.v2_binding import (
    ExpectedReference,
    RightsResolver,
    resolve_shot_reference_expectations,
)
from microdrama.rendering.comfy_jobs import ComfyRenderService, render_id_for
from microdrama.rendering.keyframe_preflight import (
    FRAME_ROLES,
    KeyframePreflightResult,
    StillMediaInspector,
    build_expected_keyframe_facts,
    ensure_keyframe_preflight_allows_dispatch,
    run_keyframe_preflight,
)
from microdrama.rendering.leases import RENDERING_NAMESPACE
from microdrama.rendering.presets import (
    EligibilityReason,
    PresetCatalog,
    PresetTierClass,
    PresetView,
    promoted,
)
from microdrama.rendering.v2_preflight import validate_v2_prompt_preflight
from microdrama.rendering.workflows import BoundWorkflow, bind_v2_workflow
from microdrama.rendering.workflows.v2_binding import ROLE_CONTROL

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


@dataclass(frozen=True)
class V2ReferencePreflightContext:
    """Current typed records prepared by T047's caller before V2 shot dispatch.

    Asset/reference documents in this value must have been loaded from their current
    rows. The resolver still verifies their frozen hashes, exact relationships, time
    intervals and state chain; rights are re-read through ``resolve_current_rights``.
    ``verify_current_asset`` must check the live descriptor is accepted at the exact
    version/hash and verify its stored bytes before render reservation.
    """

    episode_pack: EpisodePack
    directing_manifest: DirectingManifest
    secret_ledger: SecretLedger
    wardrobe_assignments: Sequence[SceneWardrobeAssignment]
    wardrobe_bibles: Sequence[WardrobeBible]
    style_bible: StyleBible
    asset_sheets: Sequence[AssetSheet]
    prop_sheets: Sequence[PropSheet]
    location_layouts: Sequence[LocationLayout]
    resolve_current_rights: RightsResolver
    verify_current_asset: Callable[[UUID, int, str], None]
    territories: list[str]
    style_subject_id: str
    explicit_frames: Sequence[ShotReferenceBinding] = ()
    required_frame_roles: frozenset[ReferenceRole] = frozenset()

    def expectations_for(
        self, shot: Shot, *, assert_current: Callable[[V2Record], None] | None = None
    ) -> dict[tuple[ReferenceRole, str], ExpectedReference]:
        return resolve_shot_reference_expectations(
            self.episode_pack,
            self.directing_manifest,
            secret_ledger=self.secret_ledger,
            shot_id=shot.shot_id,
            shot_prop_ids=shot.prop_ids,
            wardrobe_assignments=self.wardrobe_assignments,
            wardrobe_bibles=self.wardrobe_bibles,
            style_bible=self.style_bible,
            asset_sheets=self.asset_sheets,
            prop_sheets=self.prop_sheets,
            location_layouts=self.location_layouts,
            explicit_frames=self.explicit_frames,
            required_frame_roles=self.required_frame_roles,
            style_subject_id=self.style_subject_id,
            assert_current=assert_current,
        )


@dataclass(frozen=True)
class V2RoutedAttempt(RoutedAttempt):
    """V2 attempt plus the semantic graph receipt derived before reservation."""

    bound_workflow: BoundWorkflow
    keyframe_preflight: KeyframePreflightResult | None = None


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
    prompt_manifest: Any | None = None,
    prop_sheets: tuple[Any, ...] | list[Any] = (),
    dispatch_at: datetime | None = None,
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
    if shot.prop_ids and prompt_manifest is None:
        raise SchemaInvalid(
            "shot prop IDs require a typed PromptManifest and PropSheet before render dispatch",
            shot_id=shot.shot_id,
        )
    if prompt_manifest is not None:
        if dispatch_at is None:
            raise SchemaInvalid("typed V2 prop dispatch requires an explicit current instant")
        if (
            prompt_manifest.episode_id != decision.episode_id
            or prompt_manifest.shot_id != shot.shot_id
        ):
            raise SchemaInvalid("PromptManifest does not belong to the routed episode and shot")
        if prompt_manifest.prompt_text != prompt_text:
            raise SchemaInvalid("render prompt differs from the hash-bound PromptManifest")
        from microdrama.references.v2_planning import resolve_shot_prop_bindings

        resolve_shot_prop_bindings(shot, prompt_manifest, prop_sheets, at=dispatch_at)
        reference_asset_ids = list(
            dict.fromkeys(binding.asset_id for binding in prompt_manifest.bindings)
        )
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


def load_current_prompt_manifest(
    db: Database, *, prompt_manifest_id: UUID, prompt_manifest_sha256: str
) -> PromptManifest:
    """Read the current persisted V2 prompt by exact ID/hash; stale rows fail closed."""
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT payload, payload_sha256 FROM v2_contract_documents "
            "WHERE contract_type = 'PromptManifest' AND record_id = %s AND current",
            (prompt_manifest_id,),
        )
    if row is None:
        raise NotFound("current PromptManifest not found", record_id=str(prompt_manifest_id))
    manifest = PromptManifest.model_validate(row["payload"])
    if canonical_hash(manifest) != row["payload_sha256"]:
        raise Conflict("persisted PromptManifest payload hash failed integrity check")
    verify_v2_record_hash(manifest)
    if (manifest.record_id, manifest.content_sha256) != (
        prompt_manifest_id,
        prompt_manifest_sha256,
    ):
        raise Conflict("current PromptManifest does not match the exact render request locator")
    return manifest


def assert_current_v2_source_record(db: Database, record: V2Record) -> None:
    """Require the exact typed source payload to be its current durable document row."""
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT payload, payload_sha256 FROM v2_contract_documents "
            "WHERE contract_type = %s AND record_id = %s AND current",
            (type(record).__name__, record.record_id),
        )
    if row is None:
        raise NotFound(
            "current V2 reference source record not found",
            contract_type=type(record).__name__,
            record_id=str(record.record_id),
        )
    current = type(record).model_validate(row["payload"])
    verify_v2_record_hash(current)
    if canonical_hash(current) != row["payload_sha256"] or current != record:
        raise Conflict(
            "V2 reference source is stale or failed persisted hash verification",
            contract_type=type(record).__name__,
            record_id=str(record.record_id),
        )


def dispatch_v2_routed_attempt(
    db: Database,
    comfy: ComfyRenderService,
    jobs: JobService,
    *,
    decision: RouteDecision,
    shot: Shot,
    catalog: PresetCatalog,
    episode_number: int,
    identity_lock_id: UUID | None,
    prompt_manifest_id: UUID,
    prompt_manifest_sha256: str,
    semantic_workflow_sha256: str,
    reference_context: V2ReferencePreflightContext,
    dispatch_at: datetime,
    submit: bool = True,
    still_inspector: StillMediaInspector | None = None,
    read_frame_bytes: Callable[[UUID, int, str], bytes] | None = None,
) -> V2RoutedAttempt:
    """Run all V2 semantic/reference checks before a budget hold or provider operation.

    The V1 Comfy submit method is deliberately not used because it binds flat reference
    lists positionally. V2 uses only the semantic ``submit_v2`` handoff; offline callers
    may use ``submit=False`` to persist/inspect the exactly bound typed job.

    T042a: after the T041 exact-reference/rights checks and before
    ``reserve_attempt``, the pre-motion still-frame keyframe preflight runs.
    A bound keyframe is never waved through by omission: its verdict must be
    ``PASS`` (still frames only, never a motion certification) or the dispatch
    blocks typed before any budget hold.
    """
    if decision.chosen is None:
        raise PolicyDenied("cannot dispatch a decision without a chosen preset")
    if dispatch_at.tzinfo is None or dispatch_at.utcoffset() is None:
        raise SchemaInvalid("V2 dispatch requires an aware current instant")
    view = _view_for(catalog, decision.chosen.preset_id)
    manifest = load_current_prompt_manifest(
        db,
        prompt_manifest_id=prompt_manifest_id,
        prompt_manifest_sha256=prompt_manifest_sha256,
    )
    if (
        manifest.episode_id != decision.episode_id
        or manifest.episode_id != reference_context.episode_pack.episode_id
        or manifest.shot_id != shot.shot_id
        or manifest.shot_duration_ms != shot.target_duration_ms
    ):
        raise SchemaInvalid("PromptManifest does not bind this routed episode/shot/duration")
    expected = reference_context.expectations_for(
        shot, assert_current=lambda record: assert_current_v2_source_record(db, record)
    )
    for item in expected.values():
        reference_context.verify_current_asset(item.asset_id, item.asset_version, item.asset_sha256)
    controls = set(required_controls_for(shot))
    controls.update(
        control for binding in manifest.bindings if (control := ROLE_CONTROL.get(binding.role))
    )
    ordered_controls = sorted(controls, key=lambda item: item.value)
    validate_v2_prompt_preflight(
        manifest,
        prompt_manifest_id=prompt_manifest_id,
        prompt_manifest_sha256=prompt_manifest_sha256,
        expected=expected,
        resolve_current_rights=reference_context.resolve_current_rights,
        at=dispatch_at,
        territories=reference_context.territories,
        template=view.template,
        workflow_sha256=view.template_workflow_sha256,
        semantic_workflow_sha256=semantic_workflow_sha256,
        required_controls=set(ordered_controls),
    )
    reference_asset_ids = list(dict.fromkeys(binding.asset_id for binding in manifest.bindings))
    semantic_key = attempt_semantic_key(episode_number, shot.shot_id, decision.attempt_number)
    # Build and fully bind a zero-side-effect request first. The reservation ID is the
    # sole field not known yet; it is never persisted or sent to a provider.
    dry_request = build_render_request(
        decision,
        shot,
        view=view,
        episode_id=decision.episode_id,
        episode_number=episode_number,
        reference_asset_ids=reference_asset_ids,
        identity_lock_id=identity_lock_id,
        reservation_id=UUID(int=0),
        attempt_number=decision.attempt_number,
        prompt_text=manifest.prompt_text,
    ).model_copy(
        update={
            "required_controls": ordered_controls,
            "prompt_manifest_id": manifest.record_id,
            "prompt_manifest_sha256": manifest.content_sha256,
            "semantic_workflow_sha256": semantic_workflow_sha256,
        }
    )
    dry_bound = bind_v2_workflow(view.template, dry_request, manifest)
    submit_v2 = getattr(comfy, "submit_v2", None)
    if submit and not callable(submit_v2):
        raise UnsupportedControl(
            "render transport does not accept a semantic V2 workflow graph; no reservation made",
            preset_id=view.preset_id,
        )

    # T042a pre-motion still-frame preflight: every earlier check above is an
    # exact-reference/rights or transport-capability check; this is the last
    # gate before the budget hold. NOT_APPLICABLE is recorded when the route
    # carries no bound keyframes — never a silent pass.
    directing_shot = next(
        (
            item
            for item in reference_context.directing_manifest.shots
            if item.shot_id == shot.shot_id
        ),
        None,
    )
    scene = (
        next(
            (
                item
                for item in reference_context.episode_pack.scenes
                if item.scene_id == directing_shot.scene_id
            ),
            None,
        )
        if directing_shot is not None
        else None
    )
    if directing_shot is None or scene is None:
        raise SchemaInvalid(
            "V2 keyframe preflight cannot resolve the directing shot's scene",
            shot_id=shot.shot_id,
        )
    # Each frame role is verified against the facts of its own state boundary:
    # the first frame against the shot/scene entry state, the last and handoff
    # frames against the exit state.
    keyframe_facts_by_role = {
        role: build_expected_keyframe_facts(
            scene=scene,
            directing_shot=directing_shot,
            shot_prop_ids=shot.prop_ids,
            wardrobe_assignments=reference_context.wardrobe_assignments,
            location_layouts=reference_context.location_layouts,
            prop_sheets=reference_context.prop_sheets,
            frame_role=role,
        )
        for role in sorted(FRAME_ROLES, key=lambda item: item.value)
    }
    keyframe_result = run_keyframe_preflight(
        db,
        episode_id=decision.episode_id,
        shot_id=shot.shot_id,
        manifest=manifest,
        expected=expected,
        facts_by_role=keyframe_facts_by_role,
        required_frame_roles=reference_context.required_frame_roles,
        template=view.template,
        inspector=still_inspector,
        read_frame_bytes=read_frame_bytes,
        at=dispatch_at,
    )
    ensure_keyframe_preflight_allows_dispatch(keyframe_result)

    reservation = comfy.reserve_attempt(episode_id=decision.episode_id, semantic_key=semantic_key)
    request = dry_request.model_copy(update={"reservation_id": reservation.id})
    bound = bind_v2_workflow(view.template, request, manifest)
    with db.transaction() as tx:
        result = jobs.enqueue(
            tx, job_type="render.shot", semantic_key=semantic_key, payload=request
        )
    if submit:
        submit_v2(request, bound, job_id=result.job_id)
    return V2RoutedAttempt(
        request=request,
        job_id=result.job_id,
        decision=decision,
        bound_workflow=bound if submit else dry_bound,
        keyframe_preflight=keyframe_result,
    )


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
    "V2ReferencePreflightContext",
    "V2RoutedAttempt",
    "allowed_tier_classes",
    "attempt_seed",
    "attempt_semantic_key",
    "RouterShotDispatch",
    "build_render_request",
    "dispatch_routed_attempt",
    "dispatch_v2_routed_attempt",
    "is_critical_shot",
    "load_current_prompt_manifest",
    "required_controls_for",
    "route_id_for",
    "shot_class_key",
]


class RouterShotDispatch:
    """The ShotDispatchPort over the ordinary router (build-review F03).

    A SHOT repair re-renders as an ORDINARY routed attempt: route through
    ``ShotRouter`` (the repair gets no preset shortcut), reserve through
    ``ComfyRenderService.reserve_attempt`` (a real budget hold), enqueue the
    durable ``render.shot`` job and submit — exactly ``dispatch_routed_attempt``.
    The integrator wires the manifest lookup and the episode's reference
    bindings; attempts are counted from the same durable job ledger the router
    writes, so the cap the planner checks and the cap this port enforces are one
    number.
    """

    def __init__(
        self,
        db: Database,
        comfy: ComfyRenderService,
        jobs: JobService,
        router: ShotRouter,
        catalog: PresetCatalog,
        *,
        manifest_for: Callable[[UUID], ShotManifest],
        bindings_for: Callable[[UUID], Any],
    ) -> None:
        self._db = db
        self._comfy = comfy
        self._jobs = jobs
        self._router = router
        self._catalog = catalog
        self._manifest_for = manifest_for
        self._bindings_for = bindings_for

    def _shot(self, episode_id: UUID, shot_id: str) -> tuple[Shot, int, int]:
        manifest = self._manifest_for(episode_id)
        shot = next((s for s in manifest.shots if s.shot_id == shot_id), None)
        if shot is None:
            raise NotFound(
                "repair dispatch names a shot the current manifest does not carry",
                shot_id=shot_id,
            )
        return shot, manifest.version, int(manifest.episode_number)

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
        shot, manifest_version, _ = self._shot(episode_id, shot_id)
        prompt_text = f"repair re-render for shot {shot_id}"
        prompt_manifest = None
        prop_sheets = ()
        dispatch_at = datetime.now().astimezone()
        if shot.prop_ids:
            from microdrama.references.v2_planning import (
                V2ReferenceRepository,
                build_prop_prompt_manifest,
            )

            prompt_manifest, prop_sheets = build_prop_prompt_manifest(
                self._db,
                episode_id=episode_id,
                manifest_version=manifest_version,
                shot=shot,
                prompt_text=prompt_text,
                at=dispatch_at,
            )
            prompt_manifest = V2ReferenceRepository(self._db, None).persist_companion_records(
                [prompt_manifest]
            )[0]
        decision = self._router.route_shot(
            shot,
            episode_id=episode_id,
            manifest_version=manifest_version,
            attempt_number=attempt_number,
        )
        bindings = self._bindings_for(episode_id)
        attempt = dispatch_routed_attempt(
            self._db,
            self._comfy,
            self._jobs,
            decision=decision,
            shot=shot,
            catalog=self._catalog,
            episode_number=episode_number,
            reference_asset_ids=list(bindings.reference_asset_ids),
            identity_lock_id=bindings.lock_id,
            prompt_text=prompt_text,
            prompt_manifest=prompt_manifest,
            prop_sheets=prop_sheets,
            dispatch_at=dispatch_at if prompt_manifest is not None else None,
        )
        return attempt.job_id
