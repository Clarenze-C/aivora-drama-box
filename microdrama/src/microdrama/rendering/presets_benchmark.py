"""Offline compatible-preset benchmark tooling (T014; live runs are T031 evidence).

The tool measures one mapped preset per shot class by driving the REAL paid pipeline
end to end — ``ComfyRenderService.reserve_attempt`` → ``RenderRequest`` → durable
``render.shot`` job → ``submit`` → ``poll`` to a terminal state — so every benchmark
sample is a paid, recoverable attempt against the T007 fake server, never a free
shortcut and never a synthetic timing.

Timings are distinguished by measurement context, not labelled after the fact:

- ``cold_start_ms`` is the full job (submit → verified durable output) of the FIRST
  sample of the run on a fresh server state — the run that pays the model-load cost;
- ``warm_full_job_ms`` is the same full-job measurement on subsequent (warm) samples
  (the slowest accepted warm job, so a stored warm number never understates);
- per-sample ``full_job_ms`` values and accept/fail outcomes are kept in the receipt,
  and a sample whose history never yields complete verified output (sampler
  ``executed`` events without saved output, execution errors, partial files) counts
  as a FAILED attempt with its charge kept — exactly like production.

The receipt is durable twice over: a new (still disabled) ``preset_registry`` version
carrying the ``PresetMeasurements``, and a ``render.benchmark_receipt`` domain event.
Every sample is also traceable to a ``render.route_decision`` event flagged
``benchmark``. Fake evidence never enables anything: enabling real presets requires
T031 evidence (IMP-03/AT-07), and outside OFFLINE_MOCK this tool refuses to run.

The benchmarked preset must already have a current registry record (a disabled,
unmeasured stub is fine — the benchmark is what adds the measurements); recording
brand-new preset ids is T006/T031 work, not this tool's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from microdrama.config import Settings
from microdrama.contracts.enums import (
    ControlKind,
    DialogueComplexity,
    EvidenceSource,
    Level,
    Provenance,
    ProviderOperationState,
    RenderTier,
    ShotPattern,
)
from microdrama.contracts.errors import Conflict, EffectDenied, NotFound, SchemaInvalid
from microdrama.contracts.infra import Clock
from microdrama.contracts.primitives import EvidenceRef
from microdrama.contracts.registries import PresetMeasurements, PresetRecord
from microdrama.contracts.season import Shot
from microdrama.core.events import append_event
from microdrama.core.jobs import JobService
from microdrama.core.registry.presets import PresetRegistry
from microdrama.persistence.db import Database
from microdrama.rendering.comfy_jobs import ComfyRenderService
from microdrama.rendering.leases import RENDERING_NAMESPACE
from microdrama.rendering.presets import PresetCatalog, tier_class_for
from microdrama.rendering.routing import (
    ROUTE_DECISION_EVENT,
    ROUTING_AGGREGATE_TYPE,
    RankedChoice,
    RoutedAttempt,
    RouteDecision,
    dispatch_routed_attempt,
    route_id_for,
)

BENCHMARK_AGGREGATE_TYPE = "render_benchmark"
BENCHMARK_RECEIPT_EVENT = "render.benchmark_receipt"

#: Manifest version a benchmark decision pins. Benchmark shots live in the
#: ``bench-*`` id namespace, so their routing aggregates never collide with a
#: production manifest's shots (which pin their own real manifest version).
BENCHMARK_MANIFEST_VERSION = 1

_TERMINAL_STATES = frozenset(
    {
        ProviderOperationState.SUCCEEDED,
        ProviderOperationState.FAILED,
        ProviderOperationState.CANCELLED,
        ProviderOperationState.UNKNOWN,
    }
)


@dataclass(frozen=True)
class BenchmarkShot:
    """One representative shot a preset is measured against (per shot class)."""

    shot: Shot
    reference_asset_ids: list[UUID]
    prompt_text: str


def default_benchmark_matrix(references: list[UUID]) -> list[BenchmarkShot]:
    """One representative shot per directing pattern, all reference-capable.

    Reference controls are required for every class: a reference-capable preset must
    be benchmarked with the reference controls it claims (contract 1.2.0), and
    text-only speed results never qualify (SPEC §8).
    """
    if not references:
        raise SchemaInvalid("the benchmark matrix needs reference assets")
    matrix: list[BenchmarkShot] = []
    for index, pattern in enumerate(ShotPattern):
        shot = Shot(
            shot_id=f"bench-{pattern.value}",
            sequence=index + 1,
            scene_id="bench-s1",
            shot_pattern_id=pattern,
            coverage_role="benchmark_probe",
            purpose=f"Benchmark representative shot for {pattern.value}",
            dramatic_importance=Level.MEDIUM,
            dialogue_complexity=DialogueComplexity.NONE,
            temporal_risk=Level.LOW,
            required_identity_controls=[
                ControlKind.TEXT_PROMPT,
                ControlKind.CHARACTER_REFERENCE,
            ],
            preferred_render_tier=RenderTier.QUALITY_EIGHT_STEP,
            fallback_edit="CUT_TO_REACTION",
            line_ids=[],
            speaker_ids=[],
            voice_ids=[],
            target_duration_ms=4_000,
            framing="Medium close-up, benchmark framing",
            eyelines="to camera-left anchor",
            location_id="bench-loc",
            outfit_ids=["bench-outfit"],
            prop_ids=[],
            sound="room tone",
            acceptance_criteria=["benchmark output decodes and verifies"],
        )
        matrix.append(
            BenchmarkShot(
                shot=shot,
                reference_asset_ids=list(references),
                prompt_text="Benchmark reference-capable probe shot for preset compatibility.",
            )
        )
    return matrix


@dataclass(frozen=True)
class SampleOutcome:
    """One paid benchmark sample. Failures keep their charge and their timing."""

    shot_class: str
    attempt: int
    accepted: bool
    full_job_ms: int
    settled_micro_usd: int
    cold: bool
    error_code: str | None = None


@dataclass(frozen=True)
class BenchmarkReceipt:
    """The durable summary of one offline benchmark run."""

    run_id: UUID
    preset_id: str
    recorded_version: int
    cold_start_ms: int
    warm_full_job_ms: int
    cost_per_accepted_shot_micro_usd: int
    cost_per_retained_second_micro_usd: int
    acceptance_bp_by_shot_class: dict[str, int]
    critical_quality_pass_bp: int
    samples: tuple[SampleOutcome, ...]
    event_id: UUID
    enabled: bool = False
    provenance: Provenance = Provenance.FAKE_SYNTHETIC
    notes: tuple[str, ...] = field(default_factory=tuple)


class PresetBenchmarkTool:
    """Runs the offline benchmark for one mapped preset and records the receipt."""

    def __init__(
        self,
        db: Database,
        comfy: ComfyRenderService,
        jobs: JobService,
        registry: PresetRegistry,
        clock: Clock,
        settings: Settings,
    ) -> None:
        self._db = db
        self._comfy = comfy
        self._jobs = jobs
        self._registry = registry
        self._clock = clock
        self._settings = settings

    def run(
        self,
        preset_id: str,
        *,
        episode_id: UUID,
        episode_number: int = 1,
        matrix: list[BenchmarkShot] | None = None,
        samples_per_class: int = 2,
    ) -> BenchmarkReceipt:
        """Benchmark ``preset_id`` across the matrix; record measurements durably.

        Offline only: a live-mode call is a typed ``EffectDenied`` — real benchmark
        evidence is T031's to record with authorized spending, and this tool must
        never be the thing that spends it.
        """
        if not self._settings.is_offline_mock:
            raise EffectDenied(
                "the benchmark tool runs offline only; real preset benchmarks are T031 "
                "evidence requiring authorized paid benchmarks"
            )
        if samples_per_class < 1:
            raise SchemaInvalid("samples_per_class must be at least 1")
        if samples_per_class > 3:
            # The RenderRequest contract caps attempts at 3 per shot id; benchmark
            # samples reuse the class's shot id, so the same ordinary cap applies.
            raise SchemaInvalid("samples_per_class exceeds the per-shot attempt cap")
        if not matrix:
            raise SchemaInvalid("the benchmark matrix must not be empty")

        catalog = PresetCatalog(self._db, self._registry)
        if catalog.template_for(preset_id) is None:
            raise NotFound(
                "preset has no PRESET_TEMPLATES mapping to benchmark through",
                preset_id=preset_id,
            )
        record = self._registry.get(preset_id)
        if record is None:
            raise NotFound(
                "preset has no current registry record; record a disabled stub first "
                "(registry writes are T006/T031 work)",
                preset_id=preset_id,
            )

        samples: list[SampleOutcome] = []
        global_attempt = 0
        for bench in matrix:
            for sample_index in range(1, samples_per_class + 1):
                global_attempt += 1
                samples.append(
                    self._run_sample(
                        catalog,
                        preset_id,
                        bench,
                        episode_id=episode_id,
                        episode_number=episode_number,
                        sample_index=sample_index,
                        global_attempt=global_attempt,
                        cold=(len(samples) == 0),
                    )
                )

        accepted = [sample for sample in samples if sample.accepted]
        if not accepted:
            raise Conflict(
                "the benchmark produced no accepted shots; cost per accepted shot "
                "cannot be expressed and the preset stays unmeasured",
                preset_id=preset_id,
                failed=[sample.error_code or "FAILED" for sample in samples][:12],
            )
        total_settled = sum(sample.settled_micro_usd for sample in samples)
        retained_ms = sum(
            bench.shot.target_duration_ms
            for bench in matrix
            for sample in accepted
            if sample.shot_class == bench.shot.shot_pattern_id.value
        )
        retained_seconds = max(1, retained_ms // 1000)
        cold = samples[0]
        warm = [sample for sample in samples[1:] if sample.accepted]
        warm_ms = max((sample.full_job_ms for sample in warm), default=cold.full_job_ms)

        acceptance_bp: dict[str, int] = {}
        for bench in matrix:
            shot_class = bench.shot.shot_pattern_id.value
            class_samples = [sample for sample in samples if sample.shot_class == shot_class]
            accepted_count = sum(1 for sample in class_samples if sample.accepted)
            acceptance_bp[shot_class] = round(accepted_count * 10_000 / len(class_samples))

        run_id = uuid5(
            RENDERING_NAMESPACE,
            f"benchmark:{preset_id}:{len(samples)}:{self._clock.now().isoformat()}",
        )
        measured = PresetMeasurements(
            sample_count=len(samples),
            cold_start_ms=cold.full_job_ms,
            warm_full_job_ms=warm_ms,
            cost_per_accepted_shot_micro_usd=round(total_settled / len(accepted)),
            cost_per_retained_second_micro_usd=round(total_settled / retained_seconds),
            downstream_repair_cost_micro_usd=0,
            acceptance_bp_by_shot_class=dict(sorted(acceptance_bp.items())),
            critical_quality_pass_bp=min(acceptance_bp.values()),
            measured_with_references=True,
            measured_at=self._now(),
        )
        recorded_version = self._record_preset(record, measured)
        event = self._append_receipt(
            run_id,
            preset_id=preset_id,
            recorded_version=recorded_version,
            measured=measured,
            samples=tuple(samples),
            total_settled=total_settled,
        )
        return BenchmarkReceipt(
            run_id=run_id,
            preset_id=preset_id,
            recorded_version=recorded_version,
            cold_start_ms=measured.cold_start_ms,
            warm_full_job_ms=measured.warm_full_job_ms,
            cost_per_accepted_shot_micro_usd=measured.cost_per_accepted_shot_micro_usd,
            cost_per_retained_second_micro_usd=measured.cost_per_retained_second_micro_usd,
            acceptance_bp_by_shot_class=measured.acceptance_bp_by_shot_class,
            critical_quality_pass_bp=measured.critical_quality_pass_bp,
            samples=tuple(samples),
            event_id=event.event_id,
            enabled=False,
            provenance=Provenance.FAKE_SYNTHETIC,
            notes=(
                "offline fake benchmark: SYNTHETIC_FAKE timings/costs, never measured "
                "quality; enabling this preset requires T031 evidence",
            ),
        )

    # --- one paid sample -------------------------------------------------------------------

    def _run_sample(
        self,
        catalog: PresetCatalog,
        preset_id: str,
        bench: BenchmarkShot,
        *,
        episode_id: UUID,
        episode_number: int,
        sample_index: int,
        global_attempt: int,
        cold: bool,
    ) -> SampleOutcome:
        """One full paid attempt: decision → reserve → request → job → submit → poll."""
        decision = self._benchmark_decision(
            catalog,
            preset_id,
            bench,
            episode_id=episode_id,
            sample_index=sample_index,
        )
        routed = dispatch_routed_attempt(
            self._db,
            self._comfy,
            self._jobs,
            decision=decision,
            shot=bench.shot,
            catalog=catalog,
            episode_number=episode_number,
            reference_asset_ids=bench.reference_asset_ids,
            identity_lock_id=None,
            prompt_text=bench.prompt_text,
        )
        operation_id = self._operation_id(routed)
        # Drive the offline clock so the prompt completes, then poll to a terminal
        # state; failures (no complete verified output) keep their charge.
        status = self._poll_to_terminal(operation_id)
        return SampleOutcome(
            shot_class=bench.shot.shot_pattern_id.value,
            attempt=global_attempt,
            accepted=status.state is ProviderOperationState.SUCCEEDED,
            full_job_ms=self._full_job_ms(routed),
            settled_micro_usd=status.settled_micro_usd,
            cold=cold,
            error_code=status.error_code,
        )

    def _benchmark_decision(
        self,
        catalog: PresetCatalog,
        preset_id: str,
        bench: BenchmarkShot,
        *,
        episode_id: UUID,
        sample_index: int,
    ) -> RouteDecision:
        """A benchmark-isolated routing decision, durable like a production one.

        The benchmark measures ONE preset in isolation, so instead of ranking the
        whole catalog it pins the benchmarked preset and appends a
        ``render.route_decision`` event flagged ``benchmark`` — every sample stays
        traceable to a decision row exactly like production dispatches. The choice
        facts come from whatever is currently measured (zeros on a first run): they
        are informational here; the receipt carries the new measurements.
        """
        record = self._registry.get(preset_id)
        if record is None:  # pragma: no cover - run() already refused this
            raise NotFound("preset record vanished mid-benchmark", preset_id=preset_id)
        view = catalog.view(record)
        if view is None:  # pragma: no cover - run() already refused this
            raise NotFound("preset lost its template mapping", preset_id=preset_id)
        measured = record.measured
        shot_class = bench.shot.shot_pattern_id.value
        choice = RankedChoice(
            preset_id=record.preset_id,
            tier_class=tier_class_for(record.tier),
            total_accepted_cost_micro_usd=(
                measured.cost_per_accepted_shot_micro_usd
                + measured.downstream_repair_cost_micro_usd
                if measured
                else 0
            ),
            critical_quality_bp=measured.critical_quality_pass_bp if measured else 0,
            class_acceptance_bp=(
                measured.acceptance_bp_by_shot_class.get(shot_class, 0) if measured else 0
            ),
            cold_start_ms=measured.cold_start_ms if measured else 0,
            warm_full_job_ms=measured.warm_full_job_ms if measured else 0,
        )
        decision_id = route_id_for(episode_id, bench.shot.shot_id, BENCHMARK_MANIFEST_VERSION)
        with self._db.transaction() as tx:
            event = append_event(
                tx,
                aggregate_type=ROUTING_AGGREGATE_TYPE,
                aggregate_id=decision_id,
                event_type=ROUTE_DECISION_EVENT,
                payload={
                    "benchmark": True,
                    "episode_id": str(episode_id),
                    "shot_id": bench.shot.shot_id,
                    "manifest_version": BENCHMARK_MANIFEST_VERSION,
                    "shot_class": shot_class,
                    "critical": False,
                    "attempt_number": sample_index,
                    "chosen": choice.as_payload(),
                    "ranked": [choice.as_payload()],
                    "rejections": [],
                    "policy": {},
                },
                correlation_id=decision_id,
                occurred_at=self._now(),
            )
        return RouteDecision(
            decision_id=decision_id,
            episode_id=episode_id,
            shot_id=bench.shot.shot_id,
            manifest_version=BENCHMARK_MANIFEST_VERSION,
            shot_class=shot_class,
            critical=False,
            chosen=choice,
            ranked=(choice,),
            rejections=(),
            attempt_number=sample_index,
            promotion_from=None,
            max_attempts_per_shot=3,
            event_id=event.event_id,
        )

    def _poll_to_terminal(self, operation_id: UUID):
        status = self._comfy.poll(operation_id)
        while status.state not in _TERMINAL_STATES:
            self._advance_clock()
            status = self._comfy.poll(operation_id)
        return status

    def _advance_clock(self) -> None:
        advance = getattr(self._clock, "advance", None)
        if advance is None:
            raise Conflict("the benchmark tool needs an advancable (offline) clock")
        advance(seconds=5)

    def _full_job_ms(self, routed: RoutedAttempt) -> int:
        """Measured full-job interval: submit → terminal durable transition."""
        with self._db.transaction(readonly=True) as tx:
            row = tx.fetchone(
                "SELECT submitted_at, updated_at FROM provider_operations "
                "WHERE reservation_id = %s",
                (routed.request.reservation_id,),
            )
        if row is None or row["submitted_at"] is None:
            raise Conflict("benchmark sample has no submitted operation interval")
        elapsed = (row["updated_at"] - row["submitted_at"]).total_seconds()
        return max(1, int(elapsed * 1000))

    def _operation_id(self, routed: RoutedAttempt) -> UUID:
        with self._db.transaction(readonly=True) as tx:
            row = tx.fetchone(
                "SELECT id FROM provider_operations WHERE reservation_id = %s",
                (routed.request.reservation_id,),
            )
        if row is None:
            raise Conflict("benchmark sample has no provider operation")
        return row["id"]

    # --- durable receipt -------------------------------------------------------------------

    def _record_preset(
        self,
        current: PresetRecord,
        measured: PresetMeasurements,
    ) -> int:
        """Record the measured version; ``enabled`` stays False (T031 owns enabling)."""
        record = current.model_copy(
            update={
                "version": current.version + 1,
                "measured": measured,
                "evidence": [
                    EvidenceRef(
                        source=EvidenceSource.FAKE_FIXTURE,
                        ref=f"benchmark:offline:{measured.measured_at.isoformat()}",
                        note="offline fake-server benchmark receipt (T014 tool)",
                    )
                ],
                "enabled": False,
            }
        )
        self._registry.record(record, source_provenance=Provenance.FAKE_SYNTHETIC)
        return record.version

    def _append_receipt(
        self,
        run_id: UUID,
        *,
        preset_id: str,
        recorded_version: int,
        measured: PresetMeasurements,
        samples: tuple[SampleOutcome, ...],
        total_settled: int,
    ):
        payload: dict[str, Any] = {
            "preset_id": preset_id,
            "recorded_version": recorded_version,
            "enabled": False,
            "sample_count": measured.sample_count,
            "cold_start_ms": measured.cold_start_ms,
            "warm_full_job_ms": measured.warm_full_job_ms,
            "cost_per_accepted_shot_micro_usd": measured.cost_per_accepted_shot_micro_usd,
            "cost_per_retained_second_micro_usd": measured.cost_per_retained_second_micro_usd,
            "acceptance_bp_by_shot_class": measured.acceptance_bp_by_shot_class,
            "critical_quality_pass_bp": measured.critical_quality_pass_bp,
            "measured_with_references": True,
            "provenance": Provenance.FAKE_SYNTHETIC.value,
            "total_settled_micro_usd": total_settled,
            "samples": [
                {
                    "shot_class": sample.shot_class,
                    "attempt": sample.attempt,
                    "accepted": sample.accepted,
                    "full_job_ms": sample.full_job_ms,
                    "cold": sample.cold,
                    "settled_micro_usd": sample.settled_micro_usd,
                    "error_code": sample.error_code,
                }
                for sample in samples
            ],
        }
        with self._db.transaction() as tx:
            return append_event(
                tx,
                aggregate_type=BENCHMARK_AGGREGATE_TYPE,
                aggregate_id=run_id,
                event_type=BENCHMARK_RECEIPT_EVENT,
                payload=payload,
                correlation_id=run_id,
                occurred_at=self._now(),
            )

    def _now(self) -> datetime:
        now = self._clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise Conflict("clock must return a timezone-aware instant")
        return now


__all__ = [
    "BENCHMARK_AGGREGATE_TYPE",
    "BENCHMARK_MANIFEST_VERSION",
    "BENCHMARK_RECEIPT_EVENT",
    "BenchmarkReceipt",
    "BenchmarkShot",
    "PresetBenchmarkTool",
    "SampleOutcome",
    "default_benchmark_matrix",
]
