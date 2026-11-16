"""Allowlisted native Ref2VA graph. Fixtures establish OFFLINE_FIXTURE_ONLY evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from microdrama.contracts.cost import RenderRequest, validate_render_request_prompt_binding
from microdrama.contracts.errors import SchemaInvalid
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.v2 import PromptManifest, ReferenceRole
from microdrama.references.v2_binding import (
    ExpectedReference,
    RightsResolver,
    preflight_prompt_manifest,
)
from microdrama.rendering.workflows.binding import BoundWorkflow, SemanticWorkflowInput
from microdrama.rendering.workflows.templates import (
    PIKA_TEMPLATE,
    WorkflowTemplate,
    semantic_template_sha256,
    template_sha256,
)

FAMILY = "pika_h3_flex_ref2va"
TEMPLATE_ID = "pika-h3-flex-ref2va-benchmark-v1"
SIGMAS = "1.0, 0.972973, 0.923077, 0.8, 0.571429, 0.333333, 0.0"
MODEL_FILES = (
    "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
    "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
    "minimax_h3_video_vae_int8_convrot.safetensors",
    "minimax_h3_audio_vae_fp32.safetensors",
    "pika_h3_flex_ref2va_v1_bf16.safetensors",
)


@dataclass(frozen=True)
class PikaGraphConfig:
    """Candidate portrait adaptation; CPU schema/GPU readiness need separate receipts."""

    width: int = 480
    height: int = 832
    frames: int = 124
    fps: int = 24
    model_files: tuple[str, ...] = MODEL_FILES

    def __post_init__(self):
        if (self.width, self.height, self.frames, self.fps, self.model_files) != (
            480,
            832,
            124,
            24,
            MODEL_FILES,
        ):
            raise ValueError("unreviewed Pika graph configuration")

    @property
    def sha256(self):
        return canonical_hash(
            {
                "family": FAMILY,
                "width": self.width,
                "height": self.height,
                "frames": self.frames,
                "fps": self.fps,
                "model_files": self.model_files,
                "model_sha256": {
                    "minimax_h3_ref2va_pruned_int8_convrot.safetensors": "9255f52b6677845ad238f20dfaafa94727053694127ab7f255c048f0f9365779",
                    "pika_h3_flex_ref2va_v1_bf16.safetensors": "de3745ceb7d8d5c20898dd8fa3a05f1c0b00089ccd55297b2a8bab95c766b0e0",
                    "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors": "35a88d51044231fe332301d7a62aa81e3f2cba62febeb446e2c1e3e0ef76f2c6",
                    "minimax_h3_audio_vae_fp32.safetensors": "8e505d95dd1561d47abd43d4238fd40d9bb1ae9e147ed0a4cba778d76ae4db48",
                    "minimax_h3_video_vae_int8_convrot.safetensors": "52a2c8c73583c86e4f41cdcce3a6ad0ea562987bc0bf3d60a0cef5f5c8e60c0e",
                },
                "api_graph": _graph(
                    type("GraphInputs", (), {"prompt_text": "<PROMPT>", "seed": 0})(), self
                ),
                "sigmas": SIGMAS,
                "sampler": "lcm",
                "lora_strength": 1,
                "native_audio": "stereo32000",
                "topology": "VAEDecodeAudio+VAEDecode/CreateVideo/SaveVideo",
                "dynamic_ports": "explicit-zero-based-role-subject-map-v1",
            }
        )


@dataclass(frozen=True)
class PikaPortMap:
    role: ReferenceRole
    subject_id: str
    asset_id: UUID
    asset_version: int
    asset_sha256: str
    media_kind: str
    destination_slot: str


@dataclass(frozen=True)
class PikaUploadReceipt:
    experiment_id: UUID
    acquisition_id: UUID
    pod_id: str
    asset_sha256: str
    media_kind: str
    role: ReferenceRole
    subject_id: str
    destination_slot: str
    upload_key: str
    locator: str
    state: str
    verified_readback_sha256: str | None


@dataclass(frozen=True)
class PikaBindingContext:
    experiment_id: UUID
    acquisition_id: UUID
    pod_id: str
    ports: tuple[PikaPortMap, ...]
    uploads: tuple[PikaUploadReceipt, ...]
    expected_references: dict[tuple[ReferenceRole, str], ExpectedReference]
    resolve_current_rights: RightsResolver
    at: datetime
    territories: tuple[str, ...]
    raw_object_info: dict[str, Any]
    expected_schema_sha256: str
    config: PikaGraphConfig = field(default_factory=PikaGraphConfig)
    schema_evidence: str = "OFFLINE_FIXTURE_ONLY"
    unconditioned_voice: bool = False


def _node(kind, **inputs):
    return {"class_type": kind, "inputs": inputs}


def _graph(request, config):
    model, clip, video_vae, audio_vae, lora = config.model_files
    return {
        "model": _node("UNETLoader", unet_name=model, weight_dtype="default"),
        "clip": _node("CLIPLoader", clip_name=clip, type="minimax", device="default"),
        "video_vae": _node("VAELoader", vae_name=video_vae),
        "audio_vae": _node("VAELoader", vae_name=audio_vae),
        "lora": _node("LoraLoaderModelOnly", model=["model", 0], lora_name=lora, strength_model=1),
        "reference": _node(
            "MiniMaxH3ReferenceToVideo",
            clip=["clip", 0],
            vae=["video_vae", 0],
            audio_vae=["audio_vae", 0],
            prompt=request.prompt_text,
            width=config.width,
            height=config.height,
            length=config.frames,
            ref_image_size="match",
        ),
        "noise": _node("RandomNoise", noise_seed=request.seed),
        "guider": _node("BasicGuider", model=["lora", 0], conditioning=["reference", 0]),
        "sampler_select": _node("KSamplerSelect", sampler_name="lcm"),
        "sigmas": _node("ManualSigmas", sigmas=SIGMAS),
        "sample": _node(
            "SamplerCustomAdvanced",
            noise=["noise", 0],
            guider=["guider", 0],
            sampler=["sampler_select", 0],
            sigmas=["sigmas", 0],
            latent_image=["reference", 1],
        ),
        "decode_video": _node("VAEDecode", samples=["sample", 0], vae=["video_vae", 0]),
        "decode_audio": _node("VAEDecodeAudio", samples=["sample", 0], vae=["audio_vae", 0]),
        "create_video": _node(
            "CreateVideo", images=["decode_video", 0], audio=["decode_audio", 0], fps=24
        ),
        "save_video": _node(
            "SaveVideo",
            video=["create_video", 0],
            filename_prefix="video/t031_pika",
            format="mp4",
            **{"format.codec": "h264"},
        ),
    }


def bind_pika_workflow(
    template: WorkflowTemplate,
    request: RenderRequest,
    manifest: PromptManifest,
    context: PikaBindingContext | None,
) -> BoundWorkflow:
    from microdrama.rendering.pika_transport import mapped_schema_sha256, upload_key_for
    from microdrama.rendering.workflows.v2_binding import semantic_bound_request_hash

    if not isinstance(context, PikaBindingContext):
        raise SchemaInvalid("Pika binding requires sealed ordered ports and verified uploads")
    if template != PIKA_TEMPLATE or template.configuration_sha256 != context.config.sha256:
        raise SchemaInvalid("Pika configuration/template pin differs")
    if request.workflow_sha256 != template_sha256(template):
        raise SchemaInvalid("Pika request workflow pin differs")
    try:
        validate_render_request_prompt_binding(
            request,
            prompt_manifest_id=manifest.record_id,
            prompt_manifest_sha256=manifest.content_sha256,
            semantic_workflow_sha256=semantic_template_sha256(template),
        )
    except ValueError as exc:
        raise SchemaInvalid("Pika request semantic provenance differs") from exc
    if (
        request.episode_id,
        request.shot_id,
        request.duration_ms,
        request.prompt_text,
        request.fps,
    ) != (
        manifest.episode_id,
        manifest.shot_id,
        manifest.shot_duration_ms,
        manifest.prompt_text,
        24,
    ):
        raise SchemaInvalid("Pika request shot/prompt/fps differs")
    if (request.width, request.height) != (context.config.width, context.config.height):
        raise SchemaInvalid("Pika request pixel bucket differs from configuration")
    if request.audio_asset_id is not None:
        raise SchemaInvalid("Pika voices must use explicit VOICE slots, not legacy audio_asset_id")
    if request.negative_prompt_text or any(
        not template.supports(c) for c in request.required_controls
    ):
        raise SchemaInvalid("unsupported Pika control or negative prompt")
    if set(request.reference_asset_ids) != {b.asset_id for b in manifest.bindings}:
        raise SchemaInvalid("Pika flat assets differ from semantic sources")
    preflight_prompt_manifest(
        manifest,
        expected=context.expected_references,
        resolve_current_rights=context.resolve_current_rights,
        at=max(context.at, datetime.now(UTC)),
        territories=list(context.territories),
    )
    if (
        mapped_schema_sha256(context.raw_object_info, template.node_classes)
        != context.expected_schema_sha256
    ):
        raise SchemaInvalid("mapped runtime schema changed")
    bindings = {(b.role, b.subject_id): b for b in manifest.bindings}
    from microdrama.rendering.workflows.v2_binding import ROLE_CONTROL

    if not context.territories:
        raise SchemaInvalid("Pika rights preflight requires explicit territories")
    if context.schema_evidence not in {
        "OFFLINE_FIXTURE_ONLY",
        "ACTUAL_RUNTIME_CPU_NO_WEIGHTS",
        "LIVE",
    }:
        raise SchemaInvalid("unknown Pika schema evidence kind")
    if not context.unconditioned_voice and not any(
        b.role is ReferenceRole.VOICE for b in manifest.bindings
    ):
        raise SchemaInvalid("Pika requires a speaker anchor or explicit unconditioned voice plan")
    for binding in manifest.bindings:
        if binding.asset_sha256 not in manifest.source_hashes:
            raise SchemaInvalid("Pika manifest omits a bound source byte hash")
        control = ROLE_CONTROL.get(binding.role)
        if control is not None and control not in request.required_controls:
            raise SchemaInvalid("Pika required controls omit a typed reference role")
    if len(context.ports) != len(bindings) or len(context.uploads) != len(context.ports):
        raise SchemaInvalid("Pika ports/uploads do not cover every exact source")
    if len({(p.role, p.subject_id) for p in context.ports}) != len(context.ports):
        raise SchemaInvalid("duplicate Pika role/subject")
    if len({p.destination_slot for p in context.ports}) != len(context.ports):
        raise SchemaInvalid("duplicate Pika destination")
    graph = _graph(request, context.config)
    ordinals = {"image": 0, "audio": 0}
    semantic = []
    for index, (port, receipt) in enumerate(zip(context.ports, context.uploads, strict=True)):
        binding = bindings.get((port.role, port.subject_id))
        if binding is None or (port.asset_id, port.asset_version, port.asset_sha256) != (
            binding.asset_id,
            binding.asset_version,
            binding.asset_sha256,
        ):
            raise SchemaInvalid("Pika role/source mismatch")
        if port.role in {
            ReferenceRole.FIRST_FRAME,
            ReferenceRole.LAST_FRAME,
            ReferenceRole.HANDOFF_FRAME,
        }:
            raise SchemaInvalid("Pika Ref2VA does not support endpoint-frame roles")
        kind = "audio" if port.role is ReferenceRole.VOICE else "image"
        ordinal = ordinals[kind]
        expected_slot = (
            f"ref_{'audios.ref_audio' if kind == 'audio' else 'images.ref_image'}_{ordinal}"
        )
        if (
            port.media_kind != kind
            or port.destination_slot != expected_slot
            or ordinal >= (3 if kind == "audio" else 9)
        ):
            raise SchemaInvalid("Pika dynamic destination must be contiguous and role-typed")
        ordinals[kind] += 1
        key = upload_key_for(context.experiment_id, context.acquisition_id, port.asset_sha256, kind)
        if (
            receipt.experiment_id,
            receipt.acquisition_id,
            receipt.pod_id,
            receipt.asset_sha256,
            receipt.media_kind,
            receipt.role,
            receipt.subject_id,
            receipt.destination_slot,
            receipt.upload_key,
            receipt.locator,
            receipt.state,
            receipt.verified_readback_sha256,
        ) != (
            context.experiment_id,
            context.acquisition_id,
            context.pod_id,
            port.asset_sha256,
            kind,
            port.role,
            port.subject_id,
            port.destination_slot,
            key,
            key,
            "VERIFIED",
            port.asset_sha256,
        ):
            raise SchemaInvalid("Pika upload is unknown, foreign or differs from sealed slot")
        node_id = f"input_{index}"
        graph[node_id] = _node(
            "LoadAudio" if kind == "audio" else "LoadImage", **{kind: receipt.locator}
        )
        graph["reference"]["inputs"][port.destination_slot] = [node_id, 0]
        semantic.append(
            SemanticWorkflowInput(
                port.role.value,
                port.subject_id,
                port.destination_slot,
                str(port.asset_id),
                port.asset_version,
                port.asset_sha256,
                binding.rights.rights_route_id,
                binding.rights.rights_version,
            )
        )
    sources = tuple(sorted(manifest.source_hashes))
    sh = semantic_template_sha256(template)
    digest = semantic_bound_request_hash(
        graph,
        semantic_inputs=semantic,
        prompt_manifest_sha256=manifest.content_sha256,
        source_hashes=sources,
        semantic_template_sha256=sh,
    )
    return BoundWorkflow(
        template,
        graph,
        template_sha256(template),
        digest,
        tuple(semantic),
        sh,
        manifest.content_sha256,
        sources,
        context,
    )


def verify_pika_workflow(template, request, manifest, bound):
    expected = bind_pika_workflow(template, request, manifest, bound.pika_context)
    if bound != expected:
        raise SchemaInvalid("Pika graph, native audio or provenance was modified")


PIKA_CONFIG = PikaGraphConfig()
