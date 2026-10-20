"""Builders and constants shared by the registry tests. Not a test module.

All evidence here is FAKE_FIXTURE unless a test builds a real-source record on purpose. Route,
account and preset names are synthetic.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from microdrama.config import Settings
from microdrama.contracts.enums import (
    CapabilityOperation,
    CapabilitySupport,
    ControlKind,
    DisclosureKind,
    EvidenceSource,
    ExecutionMode,
    Platform,
    RenderTier,
    RightsStatus,
    RightsSubjectKind,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.primitives import EvidenceRef
from microdrama.contracts.registries import PresetMeasurements, PresetRecord, RightsRecord
from microdrama.contracts.release import CapabilityRecord
from microdrama.persistence.db import Database, jsonb
from microdrama.testing.fakes.common import FakeClock

T0 = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
ROUTE = "route-voice-th"
VOICE_REF = "voice-th-01"
CAP_ROUTE = "fake-tiktok-route"
ACCOUNT = "acct:tiktok-main"
PRESET_ID = "fake-quality-8step"

# Repository root: microdrama/ sits directly under the aivora-root checkout.
REPO_ROOT = Path(__file__).resolve().parents[4]
POLICY_EXAMPLE = (
    REPO_ROOT / "deliverables/thai-microdrama-research-2026-10-19/automation-policy.example.json"
)
PLAYBOOK_EXAMPLE = (
    REPO_ROOT / "deliverables/thai-microdrama-research-2026-10-19/directing-playbook.example.json"
)

FAKE_EVIDENCE = EvidenceRef(source=EvidenceSource.FAKE_FIXTURE, ref="fixture:registry-unit")

DEFAULT_CAP_OPERATIONS: dict[CapabilityOperation, CapabilitySupport] = {
    CapabilityOperation.UPLOAD_FULL_VIDEO: CapabilitySupport.SUPPORTED_TESTED,
    CapabilityOperation.UPLOAD_SHORT: CapabilitySupport.SUPPORTED_TESTED,
    CapabilityOperation.SCHEDULE: CapabilitySupport.SUPPORTED_TESTED,
    CapabilityOperation.STATUS: CapabilitySupport.SUPPORTED_TESTED,
    CapabilityOperation.READBACK: CapabilitySupport.SUPPORTED_TESTED,
    CapabilityOperation.AI_DISCLOSURE: CapabilitySupport.SUPPORTED_TESTED,
    CapabilityOperation.DM_SEND: CapabilitySupport.UNSUPPORTED,
    CapabilityOperation.INSIGHTS: CapabilitySupport.UNKNOWN,
}
DEFAULT_DISCLOSURES = (DisclosureKind.AI_GENERATED_CONTENT, DisclosureKind.SYNTHETIC_VOICE)
DEFAULT_CONTROLS = (
    ControlKind.TEXT_PROMPT,
    ControlKind.FIRST_FRAME,
    ControlKind.CHARACTER_REFERENCE,
)


def fixed_clock() -> FakeClock:
    return FakeClock(T0)


def live_settings() -> Settings:
    """Non-mock settings with every effect switch off (no effect is enabled by the tests)."""
    return Settings(execution_mode=ExecutionMode.CONTROLLED_ACCOUNT_TEST)


def mock_settings() -> Settings:
    return Settings()


def uid(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"https://microdrama.invalid/tests/registry/{name}")


def real_license(ref: str = "licence:th-voice-0001") -> EvidenceRef:
    return EvidenceRef(source=EvidenceSource.LICENSE_DOCUMENT, ref=ref)


def real_benchmark(ref: str = "benchmark:unit-run-1") -> EvidenceRef:
    return EvidenceRef(source=EvidenceSource.MEASURED_BENCHMARK, ref=ref)


def controlled_evidence(ref: str = "controlled-test-42") -> EvidenceRef:
    """Evidence that a controlled authorised account tested the operations (contract 1.3.0)."""
    return EvidenceRef(source=EvidenceSource.CONTROLLED_ACCOUNT_TEST, ref=ref)


def documentation_only_operations() -> dict[CapabilityOperation, CapabilitySupport]:
    """Every tested default operation downgraded to documentation: valid without evidence."""
    return {
        op: CapabilitySupport.SUPPORTED_DOCUMENTED
        for op, support in DEFAULT_CAP_OPERATIONS.items()
        if support is CapabilitySupport.SUPPORTED_TESTED
    }


def rights(
    *,
    version: int = 1,
    status: RightsStatus = RightsStatus.ELIGIBLE,
    territories: tuple[str, ...] = ("TH",),
    commercial: bool | None = True,
    output: bool | None = True,
    expires: datetime | None = T0 + timedelta(days=365),
    evidence: list[EvidenceRef] | None = None,
    route: str = ROUTE,
    ref: str = VOICE_REF,
    kind: RightsSubjectKind = RightsSubjectKind.VOICE,
    recorded_at: datetime = T0,
) -> RightsRecord:
    return RightsRecord(
        record_id=uid(f"rights:{route}:{kind.value}:{ref}:{version}"),
        rights_route_id=route,
        version=version,
        subject_kind=kind,
        subject_ref=ref,
        territories=list(territories),
        commercial_use=commercial,
        output_release_allowed=output,
        required_disclosures=[DisclosureKind.SYNTHETIC_VOICE],
        expires_at=expires,
        evidence=[FAKE_EVIDENCE] if evidence is None else list(evidence),
        status=status,
        recorded_at=recorded_at,
    )


def capability(
    *,
    version: int = 1,
    enabled: bool = True,
    operations: dict[CapabilityOperation, CapabilitySupport] | None = None,
    disclosures: tuple[DisclosureKind, ...] = DEFAULT_DISCLOSURES,
    route: str = CAP_ROUTE,
    account: str = ACCOUNT,
    platform: Platform = Platform.TIKTOK,
    evidence: list[EvidenceRef] | None = None,
    verified_at: datetime | None = T0,
) -> CapabilityRecord:
    ops = {**DEFAULT_CAP_OPERATIONS, **(operations or {})}
    if evidence is None:
        evidence = [FAKE_EVIDENCE] if enabled else []
    return CapabilityRecord(
        capability_id=uid(f"capability:{platform.value}:{account}:{route}"),
        version=version,
        platform=platform,
        provider_route=route,
        account_ref=account,
        account_type="creator",
        operations=ops,
        supported_disclosures=list(disclosures),
        evidence=list(evidence),
        verified_at=verified_at,
        enabled=enabled,
    )


def preset(
    *,
    version: int = 1,
    enabled: bool = True,
    controls: tuple[ControlKind, ...] = DEFAULT_CONTROLS,
    measured: bool = True,
    evidence: list[EvidenceRef] | None = None,
    preset_id: str = PRESET_ID,
    critical_pass_bp: int = 7000,
    sample_count: int = 12,
) -> PresetRecord:
    measurements = (
        PresetMeasurements(
            sample_count=sample_count,
            cold_start_ms=180_000,
            warm_full_job_ms=95_000,
            cost_per_accepted_shot_micro_usd=120_000,
            cost_per_retained_second_micro_usd=30_000,
            acceptance_bp_by_shot_class={"insert": 9000},
            critical_quality_pass_bp=critical_pass_bp,
            measured_with_references=True,
            measured_at=T0,
        )
        if measured
        else None
    )
    return PresetRecord(
        preset_id=preset_id,
        version=version,
        tier=RenderTier.QUALITY_EIGHT_STEP,
        workflow_sha256=canonical_hash({"preset": preset_id, "version": version}),
        model_mode="image_to_video",
        gpu_type="FAKE-GPU-24GB",
        min_vram_gb=24,
        host_ram_gb=64,
        precision="bf16",
        width=720,
        height=1280,
        frames=97,
        fps=24,
        steps=8,
        attention_backend="sdpa",
        supported_controls=list(controls),
        supports_thai_dialogue=None,
        rights_route_id=ROUTE,
        measured=measurements,
        evidence=[FAKE_EVIDENCE] if evidence is None else list(evidence),
        enabled=enabled,
    )


def tamper_stored_capability(
    db: Database,
    *,
    capability_id: UUID,
    version: int,
    edit: Callable[[dict[str, Any]], None],
    sync_sources: bool = True,
) -> None:
    """Simulate an owner-level SQL edit of a stored capability row (test databases only).

    ``edit`` changes the stored ``record`` JSON in place. ``evidence_sources`` is rewritten from the
    edited evidence when ``sync_sources`` is true, which is what a careful tamperer would do; set it
    to false to leave the two columns inconsistent. ``session_replication_role = replica`` skips the
    immutability and integer triggers for this transaction only; the schema is not altered.
    """
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT record FROM capability_registry WHERE capability_id = %s AND version = %s",
            (capability_id, version),
        )
    assert row is not None
    record = copy.deepcopy(row["record"])
    edit(record)
    with db.transaction() as tx:
        tx.execute("SET LOCAL session_replication_role = replica")
        if sync_sources:
            tx.execute(
                "UPDATE capability_registry SET record = %s, evidence_sources = %s "
                "WHERE capability_id = %s AND version = %s",
                (jsonb(record), jsonb(record["evidence"]), capability_id, version),
            )
        else:
            tx.execute(
                "UPDATE capability_registry SET record = %s "
                "WHERE capability_id = %s AND version = %s",
                (jsonb(record), capability_id, version),
            )


def count(db: Database, sql: str, params: tuple[Any, ...] = ()) -> int:
    with db.transaction(readonly=True) as tx:
        return int(tx.fetchval(sql, params))


def switch_runtime_mode(db: Database, mode: ExecutionMode) -> None:
    """Change the database's own execution mode (migration 0008 guard). Test databases only."""
    with db.transaction() as tx:
        tx.execute("UPDATE md_runtime_mode SET execution_mode = %s", (mode.value,))


def all_registry_rows_text(db: Database) -> str:
    """Every row of every registry table as JSON text, for secret-leak scans."""
    tables = (
        "credential_refs",
        "capability_registry",
        "rights_registry",
        "preset_registry",
        "policy_versions",
    )
    chunks: list[str] = []
    with db.transaction(readonly=True) as tx:
        for table in tables:
            for row in tx.fetchall(f"SELECT row_to_json(t)::text AS body FROM {table} t"):
                chunks.append(row["body"])
    return "\n".join(chunks)


__all__ = [
    "ACCOUNT",
    "CAP_ROUTE",
    "DEFAULT_CAP_OPERATIONS",
    "DEFAULT_CONTROLS",
    "DEFAULT_DISCLOSURES",
    "FAKE_EVIDENCE",
    "PLAYBOOK_EXAMPLE",
    "POLICY_EXAMPLE",
    "PRESET_ID",
    "ROUTE",
    "T0",
    "VOICE_REF",
    "all_registry_rows_text",
    "capability",
    "controlled_evidence",
    "count",
    "documentation_only_operations",
    "fixed_clock",
    "live_settings",
    "mock_settings",
    "preset",
    "real_benchmark",
    "real_license",
    "rights",
    "switch_runtime_mode",
    "tamper_stored_capability",
    "uid",
]
