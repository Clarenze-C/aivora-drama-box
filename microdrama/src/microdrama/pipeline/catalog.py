"""The offline mock preset catalog the composed pipeline seeds (T029).

Runtime-owned equivalent of the routing test helper: the same pinned
``PRESET_TEMPLATES`` mappings (T013) with clearly-fake measured evidence. Real
presets stay unregistered until T031 qualification — the router refuses
UNMEASURED/DISABLED presets, so this catalog is what makes the mock path runnable
while every routing rule stays active.
"""

from __future__ import annotations

from datetime import UTC, datetime

from microdrama.contracts.enums import (
    ControlKind,
    EvidenceSource,
    Provenance,
    RenderTier,
    ShotPattern,
)
from microdrama.contracts.primitives import EvidenceRef
from microdrama.contracts.registries import PresetMeasurements, PresetRecord
from microdrama.rendering.workflows import PRESET_TEMPLATES, template_sha256

MOCK_EVIDENCE = EvidenceRef(
    source=EvidenceSource.FAKE_FIXTURE, ref="fixture:pipeline-mock-catalog-v1"
)

#: Controls the mock video template can actually bind (MOCK_VIDEO_TEMPLATE,
#: declared in full so the catalog view matches the template by construction).
REFERENCE_CONTROLS = (
    ControlKind.TEXT_PROMPT,
    ControlKind.SEED,
    ControlKind.FIRST_FRAME,
    ControlKind.LAST_FRAME,
    ControlKind.CHARACTER_REFERENCE,
    ControlKind.WARDROBE_REFERENCE,
    ControlKind.LOCATION_REFERENCE,
    ControlKind.STYLE_REFERENCE,
)
TEXT_ONLY_CONTROLS = (ControlKind.TEXT_PROMPT, ControlKind.SEED)

#: The fixture presets carry acceptance for every shot class the story lane emits.
_ALL_CLASSES = tuple(pattern.value for pattern in ShotPattern)


def _measurements(
    *,
    cost_per_accepted_shot: int,
    critical_quality_bp: int,
    warm_full_job_ms: int,
) -> PresetMeasurements:
    return PresetMeasurements(
        sample_count=12,
        cold_start_ms=180_000,
        warm_full_job_ms=warm_full_job_ms,
        cost_per_accepted_shot_micro_usd=cost_per_accepted_shot,
        cost_per_retained_second_micro_usd=30_000,
        downstream_repair_cost_micro_usd=10_000,
        acceptance_bp_by_shot_class={name: 9_000 for name in _ALL_CLASSES},
        critical_quality_pass_bp=critical_quality_bp,
        measured_with_references=True,
        measured_at=datetime(2026, 10, 21, tzinfo=UTC),
    )


def _record(
    preset_id: str,
    tier: RenderTier,
    controls: tuple[ControlKind, ...],
    measured: PresetMeasurements,
) -> PresetRecord:
    template = PRESET_TEMPLATES[preset_id]
    return PresetRecord(
        preset_id=preset_id,
        version=1,
        tier=tier,
        workflow_sha256=template_sha256(template),
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
        rights_route_id="route-video-fake",
        measured=measured,
        evidence=[MOCK_EVIDENCE],
        enabled=True,
    )


def mock_catalog_presets() -> list[PresetRecord]:
    """The standard offline catalog: fast text-only + quality reference-capable."""
    return [
        _record(
            "fake-fast-4step",
            RenderTier.FAST_FOUR_STEP,
            TEXT_ONLY_CONTROLS,
            _measurements(
                cost_per_accepted_shot=200_000,
                critical_quality_bp=4_000,
                warm_full_job_ms=20_000,
            ),
        ),
        _record(
            "fake-quality-8step",
            RenderTier.QUALITY_EIGHT_STEP,
            REFERENCE_CONTROLS,
            _measurements(
                cost_per_accepted_shot=120_000,
                critical_quality_bp=7_000,
                warm_full_job_ms=95_000,
            ),
        ),
    ]


def seed_mock_catalog(registry) -> None:
    """Record every mock preset with FAKE_SYNTHETIC provenance (idempotent replay)."""
    for record in mock_catalog_presets():
        registry.record(record, source_provenance=Provenance.FAKE_SYNTHETIC)


__all__ = [
    "MOCK_EVIDENCE",
    "REFERENCE_CONTROLS",
    "TEXT_ONLY_CONTROLS",
    "mock_catalog_presets",
    "seed_mock_catalog",
]
