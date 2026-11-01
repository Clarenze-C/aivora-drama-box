from datetime import UTC, datetime, timedelta

import pytest

from microdrama.config import Settings
from microdrama.contracts.enums import (
    EvidenceSource,
    ExecutionMode,
    Provenance,
    RightsStatus,
    RightsSubjectKind,
)
from microdrama.contracts.errors import EffectDenied, PolicyDenied
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.primitives import EvidenceRef
from microdrama.contracts.registries import RightsRecord
from microdrama.core.clock import SystemClock
from microdrama.core.registry.presets import PresetRegistry
from microdrama.core.registry.rights import RightsRegistry
from microdrama.pipeline.catalog import mock_catalog_presets
from microdrama.pipeline.live_world import (
    LiveBenchmarkEvidence,
    RunpodQuoteEvidence,
    build_live_benchmark_world,
    validate_registry_evidence,
)
from microdrama.rendering.runpod_transport import RunpodQuoteAttestation
from microdrama.rendering.workflows import MOCK_VIDEO_TEMPLATE, template_sha256


def _attestation(*, active: bool = True) -> RunpodQuoteAttestation:
    now = datetime.now(UTC)
    return RunpodQuoteAttestation(
        namespace="mdtest",
        quote_micro_usd_per_hour=500_000,
        quote_as_of=now - timedelta(seconds=1),
        expires_at=now + timedelta(minutes=10),
        container_disk_gb=20,
        container_storage_micro_usd_per_gb_month=100,
        persistent_storage_micro_usd_per_gb_month=100,
        pinned_image="registry.example/render@sha256:" + "a" * 64,
        allowed_gpu_types=frozenset({"A40"}),
        host_ram_gb_by_gpu={"A40": 64},
        rights_evidence_id="rights-v3",
        preset_evidence_id="preset-v2",
        activation_enabled=active,
    )


def _evidence(attestation: RunpodQuoteAttestation) -> LiveBenchmarkEvidence:
    required = ("TEXT_PROMPT", "SEED")
    supported = sorted(control.value for control in MOCK_VIDEO_TEMPLATE.supported_controls)
    return LiveBenchmarkEvidence(
        rights_route_id="route-video-fake",
        rights_subject_ref="model-output:qualified",
        rights_subject_kind=RightsSubjectKind.MODEL_OUTPUT,
        rights_version=1,
        territories=("TH",),
        preset_id="fake-quality-8step",
        preset_version=1,
        workflow_sha256=template_sha256(MOCK_VIDEO_TEMPLATE),
        image_digest="a" * 64,
        node_schema_sha256=canonical_hash(
            {
                "template_id": MOCK_VIDEO_TEMPLATE.template_id,
                "template_sha256": template_sha256(MOCK_VIDEO_TEMPLATE),
                "node_classes": sorted(MOCK_VIDEO_TEMPLATE.node_classes),
            }
        ),
        output_controls_sha256=canonical_hash(
            {
                "required_controls": sorted(required),
                "supported_controls": supported,
                "control_ports": dict(MOCK_VIDEO_TEMPLATE.control_ports),
            }
        ),
        eligible_until=attestation.expires_at,
        required_controls=required,
        quote=RunpodQuoteEvidence(
            quote_id="quote-current",
            captured_at=attestation.quote_as_of,
            expires_at=attestation.expires_at,
            compute_micro_usd_per_hour=attestation.quote_micro_usd_per_hour,
            container_disk_gb=attestation.container_disk_gb,
            container_storage_micro_usd_per_gb_month=attestation.container_storage_micro_usd_per_gb_month,
            allowed_gpu_types=attestation.allowed_gpu_types,
            host_ram_gb_by_gpu=dict(attestation.host_ram_gb_by_gpu),
            persistent_volume_gb=1,
            persistent_storage_micro_usd_per_gb_month=attestation.persistent_storage_micro_usd_per_gb_month,
            maximum_runtime_ms=60_000,
            maximum_exposure_micro_usd=20_000,
        ),
        maximum_exposure_micro_usd=20_000,
    )


def test_live_world_rejects_offline_before_accessing_dependencies() -> None:
    attestation = _attestation()
    with pytest.raises(EffectDenied, match="PAID_BENCHMARK"):
        build_live_benchmark_world(
            Settings(),
            None,
            None,
            None,
            attestation=attestation,
            evidence=_evidence(attestation),
            runpod_credential_ref="credref:runpod",
            comfy_credential_ref="credref:comfy",
            credential_resolver=lambda _: pytest.fail("credentials must not resolve"),
            comfy_endpoint="https://comfy.invalid",
            pod_config=None,
            render_config=None,
        )


def test_live_world_rejects_missing_effect_flags_before_credentials() -> None:
    attestation = _attestation()
    with pytest.raises(EffectDenied, match="PAID_REQUEST"):
        build_live_benchmark_world(
            Settings(execution_mode=ExecutionMode.PAID_BENCHMARK),
            None,
            None,
            None,
            attestation=attestation,
            evidence=_evidence(attestation),
            runpod_credential_ref="credref:runpod",
            comfy_credential_ref="credref:comfy",
            credential_resolver=lambda _: pytest.fail("credentials must not resolve"),
            comfy_endpoint="https://comfy.invalid",
            pod_config=None,
            render_config=None,
        )


def test_quote_exposure_must_cover_compute_and_storage() -> None:
    attestation = _attestation()
    evidence = _evidence(attestation)
    underquoted = evidence.quote.__class__(
        **{
            **evidence.quote.__dict__,
            "maximum_exposure_micro_usd": 1,
        }
    )
    with pytest.raises(PolicyDenied, match="exposure ceiling"):
        underquoted.check(now=datetime.now(UTC), attestation=attestation)


def test_image_digest_is_an_exact_suffix_of_the_attested_image() -> None:
    attestation = _attestation()
    evidence = _evidence(attestation)
    mismatched = evidence.__class__(**{**evidence.__dict__, "image_digest": "f" * 64})
    with pytest.raises(PolicyDenied, match="image digest"):
        mismatched.check(now=datetime.now(UTC), attestation=attestation)


def test_registry_evidence_checks_current_rights_and_enabled_preset(db, offline_settings) -> None:
    now = datetime.now(UTC)
    preset_registry = PresetRegistry(db, offline_settings)
    preset = next(p for p in mock_catalog_presets() if p.preset_id == "fake-quality-8step")
    preset = preset.model_copy(update={"gpu_type": "A40", "host_ram_gb": 64})
    preset_registry.record(preset, source_provenance=Provenance.FAKE_SYNTHETIC)
    rights_registry = RightsRegistry(db, SystemClock(), offline_settings)
    rights_registry.record(
        RightsRecord(
            record_id="4f0c5c28-77be-44e2-9050-c7b350b839be",
            rights_route_id="route-video-fake",
            version=1,
            subject_kind=RightsSubjectKind.MODEL_OUTPUT,
            subject_ref="model-output:qualified",
            territories=["TH"],
            commercial_use=True,
            output_release_allowed=True,
            evidence=[EvidenceRef(source=EvidenceSource.FAKE_FIXTURE, ref="fixture:rights")],
            status=RightsStatus.ELIGIBLE,
            recorded_at=now,
        ),
        source_provenance=Provenance.FAKE_SYNTHETIC,
    )
    attestation = _attestation()
    evidence = _evidence(attestation)
    validate_registry_evidence(
        db=db,
        settings=offline_settings,
        evidence=evidence,
        now=now,
        attestation=attestation,
        clock=SystemClock(),
    )

    stale_rights = evidence.__class__(**{**evidence.__dict__, "rights_version": 2})
    with pytest.raises(PolicyDenied, match="selected current record"):
        validate_registry_evidence(
            db=db,
            settings=offline_settings,
            evidence=stale_rights,
            now=now,
            attestation=attestation,
            clock=SystemClock(),
        )

    stale_workflow = evidence.__class__(**{**evidence.__dict__, "workflow_sha256": "e" * 64})
    with pytest.raises(PolicyDenied, match="workflow hash"):
        validate_registry_evidence(
            db=db,
            settings=offline_settings,
            evidence=stale_workflow,
            now=now,
            attestation=attestation,
            clock=SystemClock(),
        )
