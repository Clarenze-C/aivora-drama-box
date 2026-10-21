"""Bind a ``RenderRequest`` onto a ``WorkflowTemplate`` into an API-format graph (T013).

Binding is deterministic: the same request and template always produce the same graph,
so ``request_hash`` (the canonical graph hash) is a stable identity for the prompt and
doubles as ``provider_operations.request_hash`` / the assets' ``generation_key``.

Rules enforced here, all with typed errors before anything is dispatched:
- the request's ``workflow_sha256`` must equal the template's content hash (a stored
  request cannot silently render through a different workflow);
- every ``required_control`` must be carried by the template (required controls are
  never dropped, SPEC §2.1/§8);
- a negative prompt the template cannot carry is refused, not discarded;
- reference-hungry controls need reference assets to bind.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from microdrama.contracts.cost import RenderRequest
from microdrama.contracts.enums import ControlKind
from microdrama.contracts.errors import SchemaInvalid, UnsupportedControl
from microdrama.contracts.hashing import canonical_hash
from microdrama.rendering.workflows.templates import WorkflowTemplate, template_sha256

#: Controls that bind reference images into the graph.
REFERENCE_CONTROLS = frozenset(
    {
        ControlKind.CHARACTER_REFERENCE,
        ControlKind.WARDROBE_REFERENCE,
        ControlKind.LOCATION_REFERENCE,
        ControlKind.STYLE_REFERENCE,
    }
)


@dataclass(frozen=True)
class BoundWorkflow:
    """A validated, ready-to-submit API-format prompt graph plus its identities."""

    template: WorkflowTemplate
    graph: dict[str, Any]
    workflow_sha256: str
    request_hash: str

    @property
    def media_kinds(self) -> tuple[str, ...]:
        return self.template.produced_media_kinds


def _frames(request: RenderRequest) -> int:
    """Whole frames covering ``duration_ms`` at ``fps`` (at least one)."""
    return max(1, -(-request.duration_ms * request.fps // 1000))


def _bind_mock_video(template: WorkflowTemplate, request: RenderRequest) -> dict[str, Any]:
    references = list(request.reference_asset_ids)
    reference_controls = REFERENCE_CONTROLS & set(request.required_controls)
    if (reference_controls or ControlKind.FIRST_FRAME in request.required_controls) and not (
        references
    ):
        raise SchemaInvalid(
            "reference/first-frame controls require reference_asset_ids",
            controls=sorted(c.value for c in reference_controls),
        )

    nodes: dict[str, Any] = {}
    nodes["checkpoint"] = {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": template.model_checkpoint},
    }
    for index, asset_id in enumerate(references):
        nodes[f"reference_{index}"] = {
            "class_type": "LoadImage",
            "inputs": {"image": f"asset/{asset_id}.png"},
        }

    sampler_inputs: dict[str, Any] = {
        "model": ["checkpoint", 0],
        "prompt": request.prompt_text,
        "frames": _frames(request),
        "seed": request.seed,
        "width": request.width,
        "height": request.height,
    }
    if references:
        sampler_inputs["reference_images"] = [
            [f"reference_{index}", 0] for index in range(len(references))
        ]
    if ControlKind.FIRST_FRAME in request.required_controls:
        sampler_inputs["first_frame"] = ["reference_0", 0]
    if ControlKind.LAST_FRAME in request.required_controls:
        sampler_inputs["last_frame"] = [f"reference_{len(references) - 1}", 0]
    nodes["sampler"] = {"class_type": template.sampler_class, "inputs": sampler_inputs}

    nodes["combine"] = {
        "class_type": "VHS_VideoCombine",
        "inputs": {
            "images": ["sampler", 0],
            "frame_rate": request.fps,
            "filename_prefix": (
                f"md/ep{request.episode_number}/{request.shot_id}/a{request.attempt_number}"
            ),
            "format": "video/h264-mp4",
        },
    }
    return nodes


_BINDERS = {"mock_video": _bind_mock_video}


def bind_workflow(template: WorkflowTemplate, request: RenderRequest) -> BoundWorkflow:
    """Produce the API-format graph for one attempt, or refuse with a typed error."""
    pinned = template_sha256(template)
    if request.workflow_sha256 != pinned:
        raise SchemaInvalid(
            "workflow_sha256 does not match the template this request pins",
            expected=pinned,
            workflow_sha256=request.workflow_sha256,
            template_id=template.template_id,
        )
    unsupported = [c.value for c in request.required_controls if not template.supports(c)]
    if unsupported:
        raise UnsupportedControl(
            "required controls cannot be dropped and this workflow cannot carry them",
            controls=unsupported,
            template_id=template.template_id,
        )
    if request.negative_prompt_text and not template.binds_negative_prompt:
        raise UnsupportedControl(
            "a negative prompt cannot be carried by this workflow; refusing instead of "
            "silently discarding it",
            template_id=template.template_id,
        )
    binder = _BINDERS.get(template.family)
    if binder is None:
        raise UnsupportedControl("unknown workflow binding family", family=template.family)
    graph = binder(template, request)
    return BoundWorkflow(
        template=template,
        graph=graph,
        workflow_sha256=pinned,
        request_hash=canonical_hash(graph),
    )


__all__ = ["BoundWorkflow", "REFERENCE_CONTROLS", "bind_workflow"]
