"""Render preset registry: benchmarked model/workflow settings and the controls they support.

A preset is selectable only when its current record is enabled. Enabled presets carry measured,
reproducible evidence (contract validators and migrations 0008-0011). Outside OFFLINE_MOCK a
preset backed only by fake evidence is not selectable. ``compatible`` never drops a required
control: a preset that lacks any requested control is simply not returned.
"""

from __future__ import annotations

from collections.abc import Iterable

from microdrama.config import Settings
from microdrama.contracts.enums import ControlKind, Provenance
from microdrama.contracts.errors import Conflict, SchemaInvalid
from microdrama.contracts.registries import PresetRecord
from microdrama.core.registry._common import (
    canonical_document,
    clean_route,
    deterministic_uuid,
    ensure_provenance,
    has_real_evidence,
    refuse_real_evidence_on_fake,
)
from microdrama.persistence.db import Database, insert_row, jsonb


class PresetRegistry:
    """Writes preset versions and answers which enabled presets satisfy a control set."""

    def __init__(self, db: Database, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    # --- writes -------------------------------------------------------------------

    def record(self, preset: PresetRecord, *, source_provenance: Provenance) -> None:
        """Insert a new version and retire the current version of the same preset id.

        Versions must strictly increase per ``preset_id``. D3 applies: fake-synthetic data may not
        name a real evidence source.
        """
        provenance = ensure_provenance(source_provenance)
        refuse_real_evidence_on_fake(provenance, preset.evidence, what=f"preset {preset.preset_id}")
        with self._db.transaction() as tx:
            latest = tx.fetchval(
                "SELECT max(version) FROM preset_registry WHERE preset_id = %s",
                (preset.preset_id,),
            )
            if latest is not None and preset.version <= latest:
                raise Conflict(
                    f"preset {preset.preset_id}: version {preset.version} must exceed {latest}",
                    current_version=latest,
                )
            tx.execute(
                "UPDATE preset_registry SET current = false WHERE preset_id = %s AND current",
                (preset.preset_id,),
            )
            insert_row(
                tx,
                "preset_registry",
                {
                    "id": deterministic_uuid("preset", preset.preset_id, str(preset.version)),
                    "preset_id": preset.preset_id,
                    "version": preset.version,
                    "tier": preset.tier.value,
                    "workflow_sha256": preset.workflow_sha256,
                    "record": jsonb(canonical_document(preset)),
                    "enabled": preset.enabled,
                    "evidence": jsonb(canonical_document(preset.evidence)),
                    "current": True,
                },
            )

    # --- reads --------------------------------------------------------------------

    def get(self, preset_id: str) -> PresetRecord | None:
        """The current version of a preset, enabled or not."""
        clean_id = _clean_preset_id(preset_id)
        with self._db.transaction(readonly=True) as tx:
            row = tx.fetchone(
                "SELECT record FROM preset_registry WHERE preset_id = %s AND current",
                (clean_id,),
            )
        return None if row is None else PresetRecord.model_validate(row["record"])

    def enabled(self) -> list[PresetRecord]:
        """Current, enabled presets, sorted by id. Outside OFFLINE_MOCK, fake-only ones are
        excluded."""
        with self._db.transaction(readonly=True) as tx:
            rows = tx.fetchall(
                "SELECT record FROM preset_registry WHERE current AND enabled ORDER BY preset_id"
            )
        presets = [PresetRecord.model_validate(row["record"]) for row in rows]
        if self._settings.is_offline_mock:
            return presets
        return [preset for preset in presets if has_real_evidence(preset.evidence)]

    def compatible(self, required_controls: Iterable[ControlKind | str]) -> list[PresetRecord]:
        """Enabled presets whose ``supported_controls`` include every required control."""
        required = {_control(item) for item in required_controls}
        return [
            preset for preset in self.enabled() if required.issubset(set(preset.supported_controls))
        ]


def _clean_preset_id(value: object) -> str:
    if not isinstance(value, str):
        raise SchemaInvalid("preset_id is malformed")
    return clean_route(value)


def _control(value: object) -> ControlKind:
    try:
        return ControlKind(value)
    except ValueError:
        raise SchemaInvalid("unknown control kind") from None


__all__ = ["PresetRegistry"]
