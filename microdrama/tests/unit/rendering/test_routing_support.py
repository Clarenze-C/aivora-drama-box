"""Shared builders for the routing/presets/benchmark (T014) tests. Not a test module.

Real PostgreSQL, real budget service, real job queue, real preset registry, the T007
FakeComfyServerState and a filesystem object store — the same house pattern as
``comfy_support``/``rendering_support``, extended with the T006 ``PresetRegistry``
and the T014 catalog/router/benchmark tool.

Preset ids: only ``fake-quality-8step`` and ``fake-fast-4step`` have T013
``PRESET_TEMPLATES`` mappings (consumed as-is); ``fake-control-baseline`` is recorded
deliberately WITHOUT a mapping so the typed ``NO_TEMPLATE`` path and the handoff
proposal (extend PRESET_TEMPLATES) stay covered until T013/T031 add real entries.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from microdrama.budget import BudgetService
from microdrama.config import Settings
from microdrama.contracts.enums import (
    ControlKind,
    DialogueComplexity,
    EvidenceSource,
    ExecutionMode,
    Level,
    RenderTier,
    ShotPattern,
)
from microdrama.contracts.enums import (
    Provenance as ProvenanceEnum,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.primitives import EvidenceRef
from microdrama.contracts.registries import PresetMeasurements, PresetRecord
from microdrama.contracts.season import CostPolicy, Shot
from microdrama.core.jobs import JobService
from microdrama.core.registry.presets import PresetRegistry
from microdrama.persistence import Database
from microdrama.persistence.db import IsolationLevel
from microdrama.persistence.object_store import FilesystemObjectStore
from microdrama.rendering.comfy_jobs import (
    ComfyRenderConfig,
    ComfyRenderService,
    build_comfy_render_service,
)
from microdrama.rendering.presets import PresetCatalog
from microdrama.rendering.routing import RoutingPolicy, ShotRouter
from microdrama.rendering.workflows import PRESET_TEMPLATES, template_sha256
from microdrama.testing.fakes import (
    FakeClock,
    FakeComfyClient,
    FakeComfyServerState,
    SequentialIds,
)
from microdrama.testing.seed import seed_episode, seed_season

T0 = datetime(2026, 10, 21, tzinfo=UTC)
GPU_SECOND_MICRO = 250
RIGHTS_ROUTE = "route-video-fake"

#: The shot classes the fixture presets carry acceptance for.
INSERT_CLASSES = ("practical_prop_action_v1", "comic_reaction_v1")
ALL_CLASSES = tuple(pattern.value for pattern in ShotPattern)

FAKE_EVIDENCE = EvidenceRef(source=EvidenceSource.FAKE_FIXTURE, ref="fixture:routing-unit")


def template_sha_for(preset_id: str) -> str:
    template = PRESET_TEMPLATES.get(preset_id)
    if template is None:
        return canonical_hash({"unmapped": preset_id})
    return template_sha256(template)


def measurements(
    *,
    shot_classes: tuple[str, ...] = ALL_CLASSES,
    cost_per_accepted_shot: int = 120_000,
    downstream_repair: int = 10_000,
    critical_quality_bp: int = 7_000,
    acceptance_bp: int = 9_000,
    cold_start_ms: int = 180_000,
    warm_full_job_ms: int = 95_000,
    sample_count: int = 12,
) -> PresetMeasurements:
    return PresetMeasurements(
        sample_count=sample_count,
        cold_start_ms=cold_start_ms,
        warm_full_job_ms=warm_full_job_ms,
        cost_per_accepted_shot_micro_usd=cost_per_accepted_shot,
        cost_per_retained_second_micro_usd=30_000,
        downstream_repair_cost_micro_usd=downstream_repair,
        acceptance_bp_by_shot_class={name: acceptance_bp for name in shot_classes},
        critical_quality_pass_bp=critical_quality_bp,
        measured_with_references=True,
        measured_at=T0,
    )


def preset_record(
    *,
    preset_id: str,
    tier: RenderTier,
    controls: tuple[ControlKind, ...],
    version: int = 1,
    enabled: bool = True,
    measured: PresetMeasurements | None,
    evidence: list[EvidenceRef] | None = None,
) -> PresetRecord:
    return PresetRecord(
        preset_id=preset_id,
        version=version,
        tier=tier,
        workflow_sha256=template_sha_for(preset_id),
        model_mode="image_to_video",
        gpu_type="FAKE-GPU-24GB",
        min_vram_gb=24,
        host_ram_gb=64,
        precision="bf16",
        width=720,
        height=1280,
        frames=97,
        fps=24,
        steps=8 if tier is RenderTier.QUALITY_EIGHT_STEP else 4,
        attention_backend="sdpa",
        supported_controls=list(controls),
        supports_thai_dialogue=None,
        rights_route_id=RIGHTS_ROUTE,
        measured=measured,
        evidence=list(evidence if evidence is not None else [FAKE_EVIDENCE]),
        enabled=enabled,
    )


#: Controls the offline mock template can actually bind (MOCK_VIDEO_TEMPLATE).
REFERENCE_CONTROLS = (
    ControlKind.TEXT_PROMPT,
    ControlKind.SEED,
    ControlKind.CHARACTER_REFERENCE,
    ControlKind.WARDROBE_REFERENCE,
    ControlKind.STYLE_REFERENCE,
)
TEXT_ONLY_CONTROLS = (ControlKind.TEXT_PROMPT, ControlKind.SEED)


def standard_catalog_presets() -> list[PresetRecord]:
    """The standard offline catalog: fast text-only, quality reference-capable, and
    an unmapped control baseline (the NO_TEMPLATE/handoff-proposal case)."""
    return [
        preset_record(
            preset_id="fake-fast-4step",
            tier=RenderTier.FAST_FOUR_STEP,
            controls=TEXT_ONLY_CONTROLS,
            measured=measurements(
                shot_classes=ALL_CLASSES,
                cost_per_accepted_shot=200_000,
                warm_full_job_ms=20_000,  # advertises speed; costs more per accept
                critical_quality_bp=4_000,  # below the critical floor
            ),
        ),
        preset_record(
            preset_id="fake-quality-8step",
            tier=RenderTier.QUALITY_EIGHT_STEP,
            controls=REFERENCE_CONTROLS,
            measured=measurements(
                shot_classes=ALL_CLASSES,
                cost_per_accepted_shot=120_000,
                warm_full_job_ms=95_000,  # slower, cheaper per accepted shot
                critical_quality_bp=7_000,
            ),
        ),
        preset_record(
            preset_id="fake-control-baseline",
            tier=RenderTier.COMPATIBLE_BASELINE,
            controls=REFERENCE_CONTROLS,
            measured=measurements(
                shot_classes=ALL_CLASSES,
                cost_per_accepted_shot=90_000,
                critical_quality_bp=8_000,
            ),
        ),
    ]


def shot(
    *,
    pattern: ShotPattern = ShotPattern.PRACTICAL_PROP_ACTION,
    controls: tuple[ControlKind, ...] = (ControlKind.TEXT_PROMPT, ControlKind.CHARACTER_REFERENCE),
    shot_id: str = "sh1",
    importance: Level = Level.MEDIUM,
    speakers: int = 0,
    duration_ms: int = 4_000,
) -> Shot:
    speaker_ids = [f"char-{i}" for i in range(speakers)]
    complexity = {
        0: DialogueComplexity.NONE,
        1: DialogueComplexity.SINGLE_SPEAKER,
        2: DialogueComplexity.TWO_SPEAKER,
    }[speakers]
    return Shot(
        shot_id=shot_id,
        sequence=1,
        scene_id="scene-1",
        shot_pattern_id=pattern,
        coverage_role="objective",
        purpose="Make the practical detail legible.",
        dramatic_importance=importance,
        dialogue_complexity=complexity,
        temporal_risk=Level.LOW,
        required_identity_controls=list(controls),
        preferred_render_tier=RenderTier.QUALITY_EIGHT_STEP,
        fallback_edit="INSERT_STILL_WITH_AUDIO",
        line_ids=[],
        speaker_ids=speaker_ids,
        voice_ids=[],
        target_duration_ms=duration_ms,
        framing="Medium close-up",
        eyelines="down to the ledger",
        location_id="loc-street-stall",
        outfit_ids=["outfit-day-1"],
        prop_ids=["prop-ledger"],
        sound="street ambience",
        acceptance_criteria=["prop state legible"],
    )


class ColdPenaltyComfyClient(FakeComfyClient):
    """First queued prompt pays a model-load penalty so cold/warm measurably differ.

    ``queue_prompt`` lives on the client (it builds the prompt into the shared server
    state), so the penalty is applied here: the very first prompt of a fresh server
    completes ``cold_extra_ms`` later than every warm one.
    """

    def __init__(self, state: FakeComfyServerState, *, cold_extra_ms: int = 4_000) -> None:
        super().__init__(state)
        self._cold_extra_ms = cold_extra_ms
        self._first = True

    def queue_prompt(self, graph: dict[str, Any], *, client_id: str) -> str:
        prompt_id = super().queue_prompt(graph, client_id=client_id)
        if self._first:
            self._first = False
            self.state.prompts[prompt_id].completes_at += timedelta(
                milliseconds=self._cold_extra_ms
            )
        return prompt_id


@dataclass(frozen=True)
class Episode:
    season_id: uuid.UUID
    episode_id: uuid.UUID
    account_id: uuid.UUID


class RoutingWorld:
    """Everything routing/benchmark tests need, deterministically."""

    def __init__(
        self,
        db: Database,
        store_root: Path,
        *,
        scenarios: tuple[Any, ...] = (),
        settings: Settings | None = None,
        server: FakeComfyServerState | None = None,
        policy: RoutingPolicy | None = None,
        clock: FakeClock | None = None,
        client: FakeComfyClient | None = None,
    ) -> None:
        self.db = db
        self.clock = clock or FakeClock(T0)
        self.settings = settings or Settings(execution_mode=ExecutionMode.OFFLINE_MOCK)
        self.config = ComfyRenderConfig.for_mock()
        self.server = server or FakeComfyServerState(self.clock)
        if server is not None and server.clock is not self.clock:
            raise ValueError("a custom server must share the world's clock")
        self.client = client or FakeComfyClient(self.server, scenarios=scenarios)
        if client is not None and client.state is not self.server:
            raise ValueError("a custom client must share the world's server")
        self.ids = SequentialIds("render-routing")
        self.budget = BudgetService(db, self.clock, self.ids, self.settings)
        self.store = FilesystemObjectStore(store_root)
        self.jobs = JobService(db, self.clock, self.ids)
        self.service: ComfyRenderService = build_comfy_render_service(
            db,
            self.budget,
            self.client,
            self.clock,
            self.ids,
            self.settings,
            self.config,
            self.store,
        )
        self.registry = PresetRegistry(db, self.settings)
        self.catalog = PresetCatalog(db, self.registry)
        self.router = ShotRouter(db, self.catalog, self.clock, policy)

        from microdrama.rendering.presets_benchmark import PresetBenchmarkTool

        self.benchmark = PresetBenchmarkTool(
            db, self.service, self.jobs, self.registry, self.clock, self.settings
        )

    # --- seeding -------------------------------------------------------------------------

    def episode(self, *, number: int = 1) -> Episode:
        with self.db.transaction() as tx:
            season_id = seed_season(tx)
            episode_id = seed_episode(tx, season_id, number=number)
            account_id = self.budget.open_episode_account(
                tx, season_id=season_id, episode_id=episode_id, policy=CostPolicy()
            )
        return Episode(season_id, episode_id, account_id)

    def seed_presets(self, records: list[PresetRecord] | None = None) -> None:
        for record in records if records is not None else standard_catalog_presets():
            self.registry.record(record, source_provenance=ProvenanceEnum.FAKE_SYNTHETIC)

    def seed_reference_assets(self, count: int = 1) -> list[uuid.UUID]:
        """Register reference assets the render consumes (as the T011 lane would)."""
        from microdrama.contracts.enums import AssetKind, AssetState
        from microdrama.contracts.media import AssetDescriptor
        from microdrama.persistence.assets import register_asset

        reference_ids = [uuid.uuid5(uuid.NAMESPACE_URL, f"routing-ref-{i}") for i in range(count)]
        now = self.clock.now()
        for asset_id in reference_ids:
            payload = f"fixture-reference-{asset_id}".encode()
            stored = self.store.put_bytes(
                f"references/{asset_id}.png", payload, media_type="image/png"
            )
            descriptor = AssetDescriptor(
                asset_id=asset_id,
                asset_kind=AssetKind.IMAGE,
                object_key=stored.key,
                sha256=stored.sha256,
                size_bytes=stored.size_bytes,
                media_type="image/png",
                media=None,
                state=AssetState.ACCEPTED,
                provenance=ProvenanceEnum.FAKE_SYNTHETIC,
                episode_id=None,
                season_id=None,
                created_at=now,
            )
            with self.db.transaction() as tx:
                register_asset(tx, descriptor)
        return reference_ids

    # --- reads ---------------------------------------------------------------------------

    def routing_events(self, aggregate_id: uuid.UUID) -> list[dict[str, Any]]:
        with self.db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
            return tx.fetchall(
                "SELECT * FROM domain_events WHERE aggregate_id = %s ORDER BY sequence",
                (aggregate_id,),
            )

    def events_of_type(self, event_type: str) -> list[dict[str, Any]]:
        with self.db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
            return tx.fetchall(
                "SELECT * FROM domain_events WHERE event_type = %s ORDER BY global_position",
                (event_type,),
            )

    def operation_rows(self) -> list[dict[str, Any]]:
        with self.db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
            return tx.fetchall("SELECT * FROM provider_operations ORDER BY created_at")

    def operation_for(self, reservation_id: uuid.UUID) -> dict[str, Any]:
        with self.db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
            row = tx.fetchone(
                "SELECT * FROM provider_operations WHERE reservation_id = %s",
                (reservation_id,),
            )
        assert row is not None
        return row

    def reservation_row(self, reservation_id: uuid.UUID) -> dict[str, Any]:
        with self.db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
            row = tx.fetchone("SELECT * FROM reservations WHERE id = %s", (reservation_id,))
        assert row is not None
        return row

    def preset_rows(self, preset_id: str) -> list[dict[str, Any]]:
        with self.db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
            return tx.fetchall(
                "SELECT * FROM preset_registry WHERE preset_id = %s ORDER BY version",
                (preset_id,),
            )

    def job_row(self, job_id: uuid.UUID) -> dict[str, Any]:
        with self.db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
            row = tx.fetchone("SELECT * FROM jobs WHERE id = %s", (job_id,))
        assert row is not None
        return row


__all__ = [
    "ALL_CLASSES",
    "ColdPenaltyComfyClient",
    "Episode",
    "FAKE_EVIDENCE",
    "GPU_SECOND_MICRO",
    "INSERT_CLASSES",
    "REFERENCE_CONTROLS",
    "RIGHTS_ROUTE",
    "RoutingWorld",
    "T0",
    "TEXT_ONLY_CONTROLS",
    "measurements",
    "preset_record",
    "shot",
    "standard_catalog_presets",
    "template_sha_for",
]
