"""Semantic V2 prompt binding to named workflow ports (T041b)."""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from microdrama.contracts.cost import (
    RenderRequest,
    validate_render_request_prompt_binding,
)
from microdrama.contracts.enums import ControlKind
from microdrama.contracts.errors import SchemaInvalid, UnsupportedControl
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.v2 import PromptManifest, ReferenceRole, verify_v2_record_hash
from microdrama.rendering.workflows.binding import (
    BoundWorkflow,
    SemanticWorkflowInput,
    bind_workflow,
)
from microdrama.rendering.workflows.templates import (
    WorkflowTemplate,
    semantic_template_sha256,
    template_sha256,
)

ROLE_CONTROL = {
    ReferenceRole.CHARACTER_IDENTITY: ControlKind.CHARACTER_REFERENCE,
    ReferenceRole.OUTFIT: ControlKind.WARDROBE_REFERENCE,
    ReferenceRole.LOCATION: ControlKind.LOCATION_REFERENCE,
    ReferenceRole.STYLE: ControlKind.STYLE_REFERENCE,
    ReferenceRole.FIRST_FRAME: ControlKind.FIRST_FRAME,
    ReferenceRole.LAST_FRAME: ControlKind.LAST_FRAME,
}
_CONTROL_INPUT = {ControlKind.TEXT_PROMPT, ControlKind.SEED}


def bind_v2_workflow(
    template: WorkflowTemplate,
    request: RenderRequest,
    manifest: PromptManifest,
) -> BoundWorkflow:
    """Produce a graph with explicit semantic input names; unknown roles block closed."""
    verify_v2_record_hash(manifest)
    if request.workflow_sha256 != template_sha256(template):
        raise SchemaInvalid("V2 RenderRequest workflow hash differs from pinned template")
    if request.prompt_manifest_id != manifest.record_id or (
        request.prompt_manifest_sha256 != manifest.content_sha256
    ):
        raise SchemaInvalid("V2 RenderRequest does not pin this exact PromptManifest")
    expected_semantic_hash = semantic_template_sha256(template)
    try:
        validate_render_request_prompt_binding(
            request,
            prompt_manifest_id=manifest.record_id,
            prompt_manifest_sha256=manifest.content_sha256,
            semantic_workflow_sha256=expected_semantic_hash,
        )
    except ValueError as exc:
        raise SchemaInvalid("V2 RenderRequest does not pin this exact semantic workflow") from exc
    if (request.episode_id, request.shot_id, request.duration_ms) != (
        manifest.episode_id,
        manifest.shot_id,
        manifest.shot_duration_ms,
    ):
        raise SchemaInvalid("V2 prompt and RenderRequest shot identity/duration differ")
    binding_assets = [binding.asset_id for binding in manifest.bindings]
    if request.prompt_text != manifest.prompt_text:
        raise SchemaInvalid("V2 RenderRequest prompt differs from exact PromptManifest")
    if set(binding_assets) != set(request.reference_asset_ids):
        raise SchemaInvalid("flat RenderRequest assets differ from typed PromptManifest bindings")
    role_set = {binding.role for binding in manifest.bindings}
    for control in request.required_controls:
        if control in _CONTROL_INPUT:
            if control.value not in template.control_ports:
                raise UnsupportedControl(
                    "workflow has no pinned input mapping for required control",
                    control=control.value,
                )
            continue
        role = next((role for role, mapped in ROLE_CONTROL.items() if mapped is control), None)
        if role is None or role not in role_set:
            raise UnsupportedControl(
                "required control has no explicit semantic reference binding",
                control=control.value,
            )
    base = bind_workflow(template, request)
    graph = base.graph
    sampler = graph.get("sampler", {}).get("inputs")
    if sampler is None:
        raise UnsupportedControl(
            "workflow has no recognized sampler inputs", family=template.family
        )
    sampler.pop("reference_images", None)
    sampler.pop("first_frame", None)
    sampler.pop("last_frame", None)
    for node_id in [key for key in graph if key.startswith("reference_")]:
        graph.pop(node_id)
    for control in request.required_controls:
        port = template.control_ports.get(control.value)
        if port is not None:
            value = request.prompt_text if control is ControlKind.TEXT_PROMPT else request.seed
            sampler[port] = value
    ports = {
        template.control_ports[control.value]
        for control in request.required_controls
        if control.value in template.control_ports
    }
    semantic_inputs: list[SemanticWorkflowInput] = []
    for binding in manifest.bindings:
        role_key = binding.role.value
        port_template = template.semantic_role_ports.get(role_key)
        if port_template is None:
            raise UnsupportedControl(
                "workflow has no pinned semantic port for required reference role",
                role=role_key,
                template_id=template.template_id,
            )
        control = ROLE_CONTROL.get(binding.role)
        if control is not None and control not in request.required_controls:
            raise UnsupportedControl(
                "RenderRequest omitted control required by typed semantic role",
                role=role_key,
                control=control.value,
            )
        try:
            port = port_template.format(subject=re.sub(r"[^A-Za-z0-9_-]", "_", binding.subject_id))
        except (IndexError, KeyError, ValueError) as exc:
            raise SchemaInvalid("invalid semantic role port template", role=role_key) from exc
        if port in ports:
            raise SchemaInvalid("semantic workflow port collision", port=port)
        ports.add(port)
        node_id = f"semantic_{canonical_hash([role_key, binding.subject_id])[:16]}"
        graph[node_id] = {
            "class_type": "LoadImage",
            "inputs": {"image": f"asset/{binding.asset_id}.png"},
        }
        sampler[port] = [node_id, 0]
        semantic_inputs.append(
            SemanticWorkflowInput(
                role=role_key,
                subject_id=binding.subject_id,
                port=port,
                asset_id=str(binding.asset_id),
                asset_version=binding.asset_version,
                asset_sha256=binding.asset_sha256,
                rights_route_id=binding.rights.rights_route_id,
                rights_version=binding.rights.rights_version,
            )
        )
    source_hashes = tuple(sorted(manifest.source_hashes))
    prompt_manifest_sha256 = manifest.content_sha256
    semantic_hash = expected_semantic_hash
    request_hash = semantic_bound_request_hash(
        graph,
        semantic_inputs=semantic_inputs,
        prompt_manifest_sha256=prompt_manifest_sha256,
        source_hashes=source_hashes,
        semantic_template_sha256=semantic_hash,
    )
    return BoundWorkflow(
        template=template,
        graph=graph,
        workflow_sha256=base.workflow_sha256,
        request_hash=request_hash,
        semantic_inputs=tuple(semantic_inputs),
        semantic_template_sha256=semantic_hash,
        prompt_manifest_sha256=prompt_manifest_sha256,
        source_hashes=source_hashes,
    )


def semantic_bound_request_hash(
    graph: dict[str, Any],
    *,
    semantic_inputs: list[SemanticWorkflowInput] | tuple[SemanticWorkflowInput, ...],
    prompt_manifest_sha256: str,
    source_hashes: tuple[str, ...],
    semantic_template_sha256: str,
) -> str:
    """Hash vendor graph plus immutable semantic provenance and port mapping pin."""
    return canonical_hash(
        {
            "graph": graph,
            "semantic_inputs": [asdict(item) for item in semantic_inputs],
            "prompt_manifest_sha256": prompt_manifest_sha256,
            "source_hashes": source_hashes,
            "semantic_template_sha256": semantic_template_sha256,
        }
    )


def verify_bound_v2_workflow(
    template: WorkflowTemplate,
    request: RenderRequest,
    manifest: PromptManifest,
    bound: BoundWorkflow,
) -> None:
    """Revalidate exact V2 graph identity without ever rebuilding via the V1 binder."""
    verify_v2_record_hash(manifest)
    expected_template_hash = template_sha256(template)
    expected_semantic_hash = semantic_template_sha256(template)
    if bound.template != template or request.workflow_sha256 != expected_template_hash:
        raise SchemaInvalid("V2 bound graph/template differs from the RenderRequest pin")
    if bound.workflow_sha256 != expected_template_hash or (
        bound.semantic_template_sha256 != expected_semantic_hash
    ):
        raise SchemaInvalid("V2 bound graph has a stale template or semantic-port hash")
    if request.prompt_manifest_id != manifest.record_id or (
        request.prompt_manifest_sha256 != manifest.content_sha256
    ):
        raise SchemaInvalid("RenderRequest does not pin the exact current PromptManifest")
    try:
        validate_render_request_prompt_binding(
            request,
            prompt_manifest_id=manifest.record_id,
            prompt_manifest_sha256=manifest.content_sha256,
            semantic_workflow_sha256=expected_semantic_hash,
        )
    except ValueError as exc:
        raise SchemaInvalid("RenderRequest semantic workflow pin is stale or mismatched") from exc
    if bound.prompt_manifest_sha256 != manifest.content_sha256 or (
        bound.source_hashes != tuple(sorted(manifest.source_hashes))
    ):
        raise SchemaInvalid("V2 graph provenance differs from the current PromptManifest")
    if (request.episode_id, request.shot_id, request.duration_ms, request.prompt_text) != (
        manifest.episode_id,
        manifest.shot_id,
        manifest.shot_duration_ms,
        manifest.prompt_text,
    ):
        raise SchemaInvalid("V2 RenderRequest differs from the exact PromptManifest shot")
    if set(request.reference_asset_ids) != {item.asset_id for item in manifest.bindings}:
        raise SchemaInvalid("V2 RenderRequest reference IDs differ from typed manifest bindings")
    roles = {binding.role for binding in manifest.bindings}
    for control in request.required_controls:
        if not template.supports(control):
            raise UnsupportedControl(
                "V2 RenderRequest requires a control unsupported by its template",
                control=control.value,
            )
        if control in _CONTROL_INPUT:
            if control.value not in template.control_ports:
                raise UnsupportedControl("V2 scalar control has no pinned template port")
        else:
            role = next((role for role, mapped in ROLE_CONTROL.items() if mapped is control), None)
            if role is None or role not in roles:
                raise UnsupportedControl(
                    "V2 required control has no matching typed semantic role",
                    control=control.value,
                )
    for role, control in ROLE_CONTROL.items():
        if role in roles and control not in request.required_controls:
            raise UnsupportedControl(
                "V2 request omitted the control required by a semantic role",
                role=role.value,
                control=control.value,
            )
    if len(bound.semantic_inputs) != len(manifest.bindings):
        raise SchemaInvalid("V2 graph semantic input count differs from PromptManifest")
    if len({item.port for item in bound.semantic_inputs}) != len(bound.semantic_inputs):
        raise SchemaInvalid("V2 semantic roles collide on a workflow input port")
    actual = {(item.role, item.subject_id): item for item in bound.semantic_inputs}
    if len(actual) != len(bound.semantic_inputs):
        raise SchemaInvalid("V2 graph has duplicate semantic role inputs")
    for binding in manifest.bindings:
        key = (binding.role.value, binding.subject_id)
        item = actual.get(key)
        port_pattern = template.semantic_role_ports.get(binding.role.value)
        if item is None or port_pattern is None:
            raise UnsupportedControl("V2 graph omitted or disabled a typed semantic role")
        port = port_pattern.format(subject=re.sub(r"[^A-Za-z0-9_-]", "_", binding.subject_id))
        expected = SemanticWorkflowInput(
            role=binding.role.value,
            subject_id=binding.subject_id,
            port=port,
            asset_id=str(binding.asset_id),
            asset_version=binding.asset_version,
            asset_sha256=binding.asset_sha256,
            rights_route_id=binding.rights.rights_route_id,
            rights_version=binding.rights.rights_version,
        )
        if item != expected:
            raise SchemaInvalid("V2 semantic input differs from exact role/source binding")
        sampler = bound.graph.get("sampler", {}).get("inputs", {})
        link = sampler.get(port)
        if not isinstance(link, list) or len(link) != 2:
            raise SchemaInvalid(
                "V2 semantic port is not connected in the provider graph", port=port
            )
        node = bound.graph.get(link[0])
        if (
            node is None
            or node.get("class_type") != "LoadImage"
            or node.get("inputs", {}).get("image") != f"asset/{binding.asset_id}.png"
        ):
            raise SchemaInvalid("V2 semantic port points to an unrelated graph asset", port=port)
    graph_inputs = bound.graph.get("sampler", {}).get("inputs", {})
    for control in request.required_controls:
        if control.value in template.control_ports:
            port = template.control_ports[control.value]
            expected_value = (
                request.prompt_text if control is ControlKind.TEXT_PROMPT else request.seed
            )
            if graph_inputs.get(port) != expected_value:
                raise SchemaInvalid("V2 graph scalar control differs from the RenderRequest")
    if "reference_images" in graph_inputs or any(
        key.startswith("reference_") for key in bound.graph
    ):
        raise SchemaInvalid("V2 graph contains untyped positional reference nodes")
    expected_hash = semantic_bound_request_hash(
        bound.graph,
        semantic_inputs=bound.semantic_inputs,
        prompt_manifest_sha256=manifest.content_sha256,
        source_hashes=bound.source_hashes,
        semantic_template_sha256=expected_semantic_hash,
    )
    if bound.request_hash != expected_hash:
        raise SchemaInvalid("V2 semantic graph request hash is invalid")


__all__ = [
    "ROLE_CONTROL",
    "bind_v2_workflow",
    "semantic_bound_request_hash",
    "verify_bound_v2_workflow",
]
