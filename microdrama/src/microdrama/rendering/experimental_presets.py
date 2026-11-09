"""Narrow experimental eligibility; production PresetCatalog is unchanged."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from microdrama.contracts.errors import SchemaInvalid
from microdrama.contracts.registries import PresetRecord
from microdrama.rendering.workflows.templates import PIKA_TEMPLATE, template_sha256


@dataclass(frozen=True)
class ExperimentalPresetPolicy:
    experiment_id: UUID
    plan_sha256: str
    sealed_sha256: str
    authorization_sha256: str
    preset_version: int
    workflow_sha256: str

    def __post_init__(self):
        if self.preset_version <= 0 or any(
            not re.fullmatch(r"[0-9a-f]{64}", value)
            for value in (
                self.plan_sha256,
                self.sealed_sha256,
                self.authorization_sha256,
                self.workflow_sha256,
            )
        ):
            raise ValueError("experimental policy needs exact version and SHA256 pins")

    def validate(
        self,
        record: PresetRecord,
        *,
        experiment_id: UUID,
        plan_sha256: str,
        sealed_sha256: str,
        authorization_sha256: str,
    ) -> None:
        if (
            self.experiment_id,
            self.plan_sha256,
            self.sealed_sha256,
            self.authorization_sha256,
        ) != (experiment_id, plan_sha256, sealed_sha256, authorization_sha256):
            raise SchemaInvalid("experimental policy differs from sealed authorization")
        if (
            record.preset_id != PIKA_TEMPLATE.template_id
            or record.version != self.preset_version
            or record.workflow_sha256 != self.workflow_sha256
            or self.workflow_sha256 != template_sha256(PIKA_TEMPLATE)
        ):
            raise SchemaInvalid("experimental preset current version/workflow changed")
        if (
            record.enabled
            or record.measured is not None
            or record.supports_thai_dialogue is not None
        ):
            raise SchemaInvalid("experimental preset must remain disabled and unmeasured")
        if (record.width, record.height, record.frames, record.fps, record.steps) != (
            480,
            832,
            124,
            24,
            6,
        ):
            raise SchemaInvalid("experimental preset configuration changed")
