"""Reservation-free checks for V2 semantic render packets (T041b)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from microdrama.contracts.enums import ControlKind
from microdrama.contracts.errors import SchemaInvalid, UnsupportedControl
from microdrama.contracts.v2 import PromptManifest, ReferenceRole, ShotReferenceBinding
from microdrama.references.v2_binding import (
    ExpectedReference,
    RightsResolver,
    preflight_prompt_manifest,
)
from microdrama.rendering.workflows.templates import (
    WorkflowTemplate,
    semantic_template_sha256,
    template_sha256,
)
from microdrama.rendering.workflows.v2_binding import ROLE_CONTROL


def validate_v2_prompt_preflight(
    manifest: PromptManifest,
    *,
    prompt_manifest_id: UUID,
    prompt_manifest_sha256: str,
    expected: Mapping[tuple[ReferenceRole, str], ExpectedReference | tuple[UUID, int, str]],
    resolve_current_rights: RightsResolver,
    at: datetime,
    territories: list[str],
    template: WorkflowTemplate,
    workflow_sha256: str,
    semantic_workflow_sha256: str,
    required_controls: set[ControlKind] | frozenset[ControlKind],
    forbidden_facts: tuple[str, ...] = (),
) -> tuple[ShotReferenceBinding, ...]:
    """Validate prompt, exact current rights and control support before reserving funds."""
    if (prompt_manifest_id, prompt_manifest_sha256) != (
        manifest.record_id,
        manifest.content_sha256,
    ):
        raise SchemaInvalid("V2 preflight must pin the exact PromptManifest identity and hash")
    bindings = preflight_prompt_manifest(
        manifest,
        expected=expected,
        resolve_current_rights=resolve_current_rights,
        at=at,
        territories=territories,
        forbidden_facts=forbidden_facts,
    )
    source_hashes = set(manifest.source_hashes)
    roles = {binding.role for binding in bindings}
    for binding in bindings:
        if binding.asset_sha256 not in source_hashes:
            raise SchemaInvalid(
                "PromptManifest source hashes omit a bound semantic asset",
                role=binding.role.value,
                subject=binding.subject_id,
            )
        role_port = template.semantic_role_ports.get(binding.role.value)
        if role_port is None:
            raise UnsupportedControl(
                "pinned workflow has no semantic input for required role",
                template_id=template.template_id,
                role=binding.role.value,
            )
        control = ROLE_CONTROL.get(binding.role)
        if control is not None and control not in required_controls:
            raise SchemaInvalid(
                "required control set omits typed semantic reference role",
                role=binding.role.value,
                control=control.value,
            )
    unsupported = sorted(
        control.value for control in required_controls if not template.supports(control)
    )
    unsupported.extend(
        control.value
        for control in required_controls
        if control not in ROLE_CONTROL.values()
        and control not in {ControlKind.TEXT_PROMPT, ControlKind.SEED}
    )
    unsupported.extend(
        control.value
        for control in required_controls
        if control in {ControlKind.TEXT_PROMPT, ControlKind.SEED}
        and control.value not in template.control_ports
    )
    missing_roles = sorted(
        control.value
        for control, role in ((control, role) for role, control in ROLE_CONTROL.items())
        if control in required_controls and role not in roles
    )
    if missing_roles:
        raise UnsupportedControl(
            "required control has no explicit semantic reference asset",
            controls=missing_roles,
        )
    unsupported = sorted(set(unsupported))
    if unsupported:
        raise UnsupportedControl(
            "required render controls are unsupported by pinned workflow",
            template_id=template.template_id,
            controls=unsupported,
        )
    if workflow_sha256 != template_sha256(template):
        raise SchemaInvalid("preflight workflow hash differs from selected pinned template")
    if semantic_workflow_sha256 != semantic_template_sha256(template):
        raise SchemaInvalid("preflight semantic workflow hash differs from selected port mapping")
    return bindings


__all__ = ["validate_v2_prompt_preflight"]
