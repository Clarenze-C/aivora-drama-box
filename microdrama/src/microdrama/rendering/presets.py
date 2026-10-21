"""The fast/quality/control preset catalog routing selects from (T014, IMP-03).

This module is the routing-facing view over T006's ``PresetRegistry`` plus T013's
``PRESET_TEMPLATES`` mapping (both consumed, never edited here):

- ``PresetTierClass`` collapses the contract's three ``RenderTier`` values into the
  routing families the packet names: FAST (simple inserts may use), QUALITY (the
  emotional/dialogue default) and CONTROL (the compatible baseline a failure-driven
  promotion terminates on).
- ``PresetCatalog`` joins a stored ``PresetRecord`` with the workflow template its
  ``preset_id`` maps to and exposes the facts ranking needs: measured total accepted
  cost (accepted-shot cost *including failed attempts* plus downstream repairs),
  per-shot-class acceptance, and the cold/warm full-job latencies. Latency is a
  receipt fact, never a ranking input — advertised speed is not accepted cost.
- Eligibility is typed and fail-closed. An unmeasured preset is NEVER eligible
  (contract 1.2.0 V-7): ``UNMEASURED`` and a zero/missing per-class acceptance
  (``CLASS_UNMEASURED``) are typed-unknown rejections, not silent skips. A preset id
  with no ``PRESET_TEMPLATES`` entry is a typed ``NO_TEMPLATE`` case: the mapping
  itself is T013-owned, so extending it is a handoff proposal, not a local edit.

Enabling a real preset stays gated on T031 evidence; nothing here flips ``enabled``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from microdrama.contracts.enums import ControlKind, RenderTier
from microdrama.contracts.errors import Conflict, SchemaInvalid
from microdrama.contracts.registries import PresetMeasurements, PresetRecord
from microdrama.core.registry.presets import PresetRegistry
from microdrama.persistence.db import Database
from microdrama.rendering.workflows import (
    PRESET_TEMPLATES,
    WorkflowTemplate,
    template_sha256,
)


class PresetTierClass(StrEnum):
    """The three routing families (task_breakdown §5 T014: fast/quality/control)."""

    FAST = "fast"
    QUALITY = "quality"
    CONTROL = "control"


_TIER_CLASS: dict[RenderTier, PresetTierClass] = {
    RenderTier.FAST_FOUR_STEP: PresetTierClass.FAST,
    RenderTier.QUALITY_EIGHT_STEP: PresetTierClass.QUALITY,
    RenderTier.COMPATIBLE_BASELINE: PresetTierClass.CONTROL,
}


def tier_class_for(tier: RenderTier) -> PresetTierClass:
    return _TIER_CLASS[RenderTier(tier)]


#: Failure-driven promotion ladder: a failed attempt may only promote to a strictly
#: stronger class, terminating at CONTROL (the compatible baseline). Every promotion
#: consumes an ordinary attempt inside the existing cap; the ladder never adds one.
PROMOTION_LADDER: dict[PresetTierClass, PresetTierClass] = {
    PresetTierClass.FAST: PresetTierClass.QUALITY,
    PresetTierClass.QUALITY: PresetTierClass.CONTROL,
}


def promoted(tier_class: PresetTierClass) -> PresetTierClass | None:
    """The next tier class after a failure, or ``None`` at the terminal class."""
    return PROMOTION_LADDER.get(PresetTierClass(tier_class))


class EligibilityReason(StrEnum):
    """Typed reason a preset was not selected. Unknowns stay unknown, never eligible."""

    DISABLED = "DISABLED"  # registry record not enabled (T031 evidence still missing)
    UNMEASURED = "UNMEASURED"  # no PresetMeasurements: NEVER eligible (V-7)
    NO_TEMPLATE = "NO_TEMPLATE"  # preset id has no PRESET_TEMPLATES entry (T013-owned)
    HARD_CONTROL = "HARD_CONTROL"  # a required control is not supported; never dropped
    TIER_POLICY = "TIER_POLICY"  # tier class not allowed for this shot class
    QUALITY_GATE = "QUALITY_GATE"  # measured critical quality below the policy floor
    CLASS_UNMEASURED = "CLASS_UNMEASURED"  # zero/missing acceptance for the shot class


@dataclass(frozen=True)
class PresetView:
    """One preset as routing sees it: record + pinned template + measured facts."""

    record: PresetRecord
    template: WorkflowTemplate
    tier_class: PresetTierClass

    @property
    def preset_id(self) -> str:
        return self.record.preset_id

    @property
    def measured(self) -> PresetMeasurements:
        # The catalog only builds views for records that carry measurements.
        assert self.record.measured is not None
        return self.record.measured

    @property
    def cold_start_ms(self) -> int:
        return self.measured.cold_start_ms

    @property
    def warm_full_job_ms(self) -> int:
        return self.measured.warm_full_job_ms

    @property
    def template_workflow_sha256(self) -> str:
        """The pinned template hash routed requests must carry (T013 ``template_sha256``)."""
        return template_sha256(self.template)

    @property
    def total_accepted_cost_micro_usd(self) -> int:
        """Accepted-shot cost (failed attempts amortized in) plus downstream repairs.

        This is the only ranking figure: a cheaper accepted shot wins even when the
        preset advertises slower full-job latency.
        """
        return (
            self.measured.cost_per_accepted_shot_micro_usd
            + self.measured.downstream_repair_cost_micro_usd
        )

    def acceptance_bp(self, shot_class: str) -> int | None:
        """Measured acceptance for one shot class; ``None`` = never measured (unknown)."""
        return self.measured.acceptance_bp_by_shot_class.get(shot_class)

    def supports_all(self, required: frozenset[ControlKind] | set[ControlKind]) -> bool:
        return required.issubset(set(self.record.supported_controls))


class PresetCatalog:
    """Read-side catalog: current preset records joined with their workflow templates.

    Writes stay with T006's ``PresetRegistry`` (and the T031 evidence process); this
    class never mutates registry rows. ``current_records`` reads the registry table
    directly (a cross-module *read*, which is permitted) so disabled-but-recorded
    presets surface in rejection receipts — ``PresetRegistry`` only exposes enabled
    rows, and a preset the router silently cannot see would hide the damage.
    """

    def __init__(self, db: Database, registry: PresetRegistry) -> None:
        self._db = db
        self._registry = registry

    @property
    def registry(self) -> PresetRegistry:
        return self._registry

    def template_for(self, preset_id: str) -> WorkflowTemplate | None:
        """The T013-owned preset→template mapping, consumed as-is (no local extension)."""
        return PRESET_TEMPLATES.get(preset_id)

    def current_records(self) -> list[PresetRecord]:
        """Every current preset record, enabled or not, sorted by preset id.

        A row that no longer validates raises a typed ``Conflict`` instead of being
        skipped: a skipped preset would silently vanish from routing (the same rule
        T006's registry applies to its own reads).
        """
        from pydantic import ValidationError

        with self._db.transaction(readonly=True) as tx:
            rows = tx.fetchall(
                "SELECT preset_id, record FROM preset_registry WHERE current ORDER BY preset_id"
            )
        records: list[PresetRecord] = []
        for row in rows:
            try:
                records.append(PresetRecord.model_validate(row["record"]))
            except ValidationError:
                raise Conflict(
                    f"stored preset record for {row['preset_id']} fails contract validation",
                    preset_id=row["preset_id"],
                ) from None
        return records

    def mapped_ids(self) -> tuple[str, ...]:
        """Preset ids T013's mapping can dispatch today (consumed, not extended)."""
        return tuple(sorted(PRESET_TEMPLATES))

    def view(self, record: PresetRecord) -> PresetView | None:
        """Join a record with its template, or ``None`` when no mapping exists.

        A *wrong* pin is a hard inconsistency and raises a typed ``Conflict``: a
        stored request whose preset claims one workflow while the mapped template
        hashes another would render through a different graph than measured.
        """
        template = self.template_for(record.preset_id)
        if template is None:
            return None
        if record.workflow_sha256 != template_sha256(template):
            raise Conflict(
                "preset pins a workflow hash the mapped template does not have",
                preset_id=record.preset_id,
                record_workflow_sha256=record.workflow_sha256,
                template_workflow_sha256=template_sha256(template),
            )
        unsupported = sorted(
            control.value
            for control in set(record.supported_controls) - set(template.supported_controls)
        )
        if unsupported:
            raise Conflict(
                "preset claims controls the mapped workflow template cannot carry",
                preset_id=record.preset_id,
                controls=unsupported,
                template_id=template.template_id,
            )
        return PresetView(
            record=record,
            template=template,
            tier_class=tier_class_for(record.tier),
        )


def control_set(values: Any) -> frozenset[ControlKind]:
    """Normalize an iterable of control kinds/strings; unknown values are typed errors."""
    if isinstance(values, (str, bytes)) or not hasattr(values, "__iter__"):
        raise SchemaInvalid("controls must be an iterable of ControlKind values")
    cleaned: set[ControlKind] = set()
    for value in values:
        try:
            cleaned.add(ControlKind(value))
        except ValueError:
            raise SchemaInvalid("unknown control kind", control=str(value)) from None
    return frozenset(cleaned)


__all__ = [
    "EligibilityReason",
    "PROMOTION_LADDER",
    "PresetCatalog",
    "PresetTierClass",
    "PresetView",
    "control_set",
    "promoted",
    "tier_class_for",
]
