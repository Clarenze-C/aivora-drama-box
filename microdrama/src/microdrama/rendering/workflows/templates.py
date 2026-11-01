"""Declarative ComfyUI workflow templates (T013). Hashable, versioned, offline."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from microdrama.contracts.enums import ControlKind
from microdrama.contracts.hashing import canonical_json, sha256_hex

MOCK_VIDEO_TEMPLATE_ID = "mock-video-fake-sampler"
MOCK_SAMPLER_CLASS = "FakeVideoModelSampler"
MOCK_CHECKPOINT = "fake-video-model.safetensors"


@dataclass(frozen=True)
class WorkflowTemplate:
    """One workflow the rendering lane may submit.

    ``supported_controls`` is the contract with routing (T014): a ``RenderRequest`` whose
    ``required_controls`` exceed it is refused with a typed error, never silently
    simplified. ``node_classes`` are the ComfyUI ``class_type`` values a bound graph uses;
    they are validated against the server's live ``object_info`` catalog at submit time.
    """

    template_id: str
    version: int
    family: str
    """Binding family (see ``workflows.binding``); the binder constructs the graph."""
    supported_controls: frozenset[ControlKind]
    produced_media_kinds: tuple[str, ...]
    node_classes: frozenset[str]
    sampler_class: str = MOCK_SAMPLER_CLASS
    model_checkpoint: str = MOCK_CHECKPOINT
    binds_negative_prompt: bool = False
    semantic_role_ports: Mapping[str, str] = MappingProxyType({})
    control_ports: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        for field_name in ("semantic_role_ports", "control_ports"):
            values = dict(getattr(self, field_name))
            if any(not key or not value for key, value in values.items()):
                raise ValueError(f"{field_name} keys and ports must be non-empty")
            object.__setattr__(self, field_name, MappingProxyType(values))

    def supports(self, control: ControlKind) -> bool:
        return control in self.supported_controls


MOCK_VIDEO_TEMPLATE = WorkflowTemplate(
    template_id=MOCK_VIDEO_TEMPLATE_ID,
    version=1,
    family="mock_video",
    supported_controls=frozenset(
        {
            ControlKind.TEXT_PROMPT,
            ControlKind.SEED,
            ControlKind.FIRST_FRAME,
            ControlKind.LAST_FRAME,
            ControlKind.CHARACTER_REFERENCE,
            ControlKind.WARDROBE_REFERENCE,
            ControlKind.LOCATION_REFERENCE,
            ControlKind.STYLE_REFERENCE,
        }
    ),
    produced_media_kinds=("video",),
    node_classes=frozenset(
        {"LoadImage", "CheckpointLoaderSimple", MOCK_SAMPLER_CLASS, "VHS_VideoCombine"}
    ),
    semantic_role_ports=MappingProxyType(
        {
            "character_identity": "identity_{subject}",
            "outfit": "outfit_{subject}",
            "location": "location_{subject}",
            "prop": "prop_{subject}",
            "style": "style_{subject}",
            "first_frame": "first_frame",
            "last_frame": "last_frame",
            "handoff_frame": "handoff_frame_{subject}",
        }
    ),
    control_ports=MappingProxyType(
        {
            "TEXT_PROMPT": "prompt",
            "SEED": "seed",
        }
    ),
)

#: Preset-id → template mapping for the offline mock pipeline (T014 replaces/extends
#: this with its registry once preset records exist; real presets need T031 evidence).
PRESET_TEMPLATES: Mapping[str, WorkflowTemplate] = MappingProxyType(
    {
        "fake-quality-8step": MOCK_VIDEO_TEMPLATE,
        "fake-fast-4step": MOCK_VIDEO_TEMPLATE,
    }
)


def template_sha256(template: WorkflowTemplate) -> str:
    """Stable content hash of the template's identity (no UUIDs, no clocks, no floats).

    Two processes computing this for the same template always agree, so a pinned
    ``RenderRequest.workflow_sha256`` survives restarts and handoffs between lanes.
    """
    return sha256_hex(
        canonical_json(
            {
                "template_id": template.template_id,
                "version": template.version,
                "family": template.family,
                "supported_controls": sorted(c.value for c in template.supported_controls),
                "produced_media_kinds": list(template.produced_media_kinds),
                "node_classes": sorted(template.node_classes),
                "sampler_class": template.sampler_class,
                "model_checkpoint": template.model_checkpoint,
                "binds_negative_prompt": template.binds_negative_prompt,
            }
        ).encode("utf-8")
    )


def semantic_template_sha256(template: WorkflowTemplate) -> str:
    """Hash V2 semantic role/control ports while preserving the V1 template identity."""
    return sha256_hex(
        canonical_json(
            {
                "v1_template_sha256": template_sha256(template),
                "semantic_role_ports": dict(sorted(template.semantic_role_ports.items())),
                "control_ports": dict(sorted(template.control_ports.items())),
            }
        ).encode("utf-8")
    )


__all__ = [
    "MOCK_SAMPLER_CLASS",
    "MOCK_VIDEO_TEMPLATE",
    "MOCK_VIDEO_TEMPLATE_ID",
    "PRESET_TEMPLATES",
    "WorkflowTemplate",
    "template_sha256",
    "semantic_template_sha256",
]
