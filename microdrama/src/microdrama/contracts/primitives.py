"""Primitive contract types and frozen constants.

Conventions (contract v1):
- Money is integer micro-USD (1 USD = 1_000_000). Floats are rejected everywhere.
- Durations and timecodes are integer milliseconds (``*_ms``).
- Ratios/confidences are integer basis points 0..10000 (``*_bp``).
- Datetimes are timezone-aware and normalized to UTC; naive datetimes are rejected.
- Schedules carry an IANA zone plus the concrete UTC instant (see ``ScheduleInstant``).
- Hashes are lowercase hex SHA-256 of canonical JSON (``hashing.py``) or raw bytes.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    Strict,
    StrictBool,
    model_validator,
)

from microdrama.contracts.enums import BudgetCategory, EvidenceSource

SCHEMA_VERSION = "1.0"

EPISODE_CAP_MICRO_USD = 10_000_000
MICRO_USD_PER_USD = 1_000_000

# Accepted policy v2 initial allocation (SPEC §6). An allocation, not evidence of fit.
DEFAULT_BUDGET_ALLOCATION_MICRO_USD: dict[BudgetCategory, int] = {
    BudgetCategory.RESEARCH_SCRIPT_PROMPTS_METADATA: 1_000_000,
    BudgetCategory.REFERENCES_DIALOGUE: 1_500_000,
    BudgetCategory.GPU_GENERATION: 2_500_000,
    BudgetCategory.QA_CAPTIONS: 1_000_000,
    BudgetCategory.CPU_STORAGE_TRANSFER: 500_000,
    BudgetCategory.METERED_MANAGEMENT: 1_000_000,
    BudgetCategory.RECOVERY_HEADROOM: 2_500_000,
}
assert sum(DEFAULT_BUDGET_ALLOCATION_MICRO_USD.values()) == EPISODE_CAP_MICRO_USD

MAX_EVENT_PAYLOAD_BYTES = 16_384


class ProductionLimits(BaseModel):
    """Initial test settings (SPEC §2.1). Configurable inside approved scope only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_attempts_per_shot: Annotated[int, Strict(), Field(ge=1, le=3)] = 3
    max_final_repair_rounds: Annotated[int, Strict(), Field(ge=0, le=2)] = 2
    max_transport_attempts: Annotated[int, Strict(), Field(ge=1, le=3)] = 3
    max_active_locations: Annotated[int, Strict(), Field(ge=1)] = 2
    max_featured_speaking_characters: Annotated[int, Strict(), Field(ge=1)] = 3
    max_speakers_per_shot: Annotated[int, Strict(), Field(ge=1)] = 2
    max_shot_duration_ms: Annotated[int, Strict(), Field(ge=1, le=15_000)] = 15_000
    episode_min_duration_ms: Annotated[int, Strict()] = 180_000
    episode_max_duration_ms: Annotated[int, Strict(), Field(le=300_000)] = 300_000
    hook_min_duration_ms: Annotated[int, Strict()] = 20_000
    hook_max_duration_ms: Annotated[int, Strict()] = 40_000
    hook_candidates_per_episode: Literal[3] = 3
    metadata_cooldown_hours: Annotated[int, Strict(), Field(ge=24)] = 24
    max_substantive_metadata_edits_first_7_days: Annotated[int, Strict(), Field(ge=0, le=2)] = 2
    qualification_streak_required: Literal[10] = 10
    management_window_days: Literal[7] = 7


DEFAULT_LIMITS = ProductionLimits()


# --- Primitive annotated types ------------------------------------------------------

MicroUSD = Annotated[int, Strict(), Field(ge=0, description="Integer micro-USD (no floats)")]
SignedMicroUSD = Annotated[int, Strict(), Field(description="Signed integer micro-USD")]
DurationMs = Annotated[int, Strict(), Field(ge=0, description="Integer milliseconds")]
PositiveMs = Annotated[int, Strict(), Field(gt=0, description="Integer milliseconds > 0")]
Count = Annotated[int, Strict(), Field(ge=0)]
PositiveInt = Annotated[int, Strict(), Field(ge=1)]
Revision = Annotated[int, Strict(), Field(ge=0, description="Optimistic revision")]
BasisPoints = Annotated[int, Strict(), Field(ge=0, le=10_000, description="0..10000")]

Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", description="Lowercase SHA-256 hex")]
IdempotencyKey = Annotated[str, Field(min_length=8, max_length=200, pattern=r"^[A-Za-z0-9._:\-]+$")]
SemanticKey = Annotated[str, Field(min_length=3, max_length=400, pattern=r"^[A-Za-z0-9._:/\-|=]+$")]


def _object_key(value: str) -> str:
    if value.startswith("/") or any(seg in ("", ".", "..") for seg in value.split("/")):
        raise ValueError("object key must be relative with no empty, '.' or '..' segments")
    return value


ObjectKey = Annotated[
    str,
    Field(
        min_length=1,
        max_length=512,
        pattern=r"^[A-Za-z0-9._\-/]+$",
        description="Private object-store key; relative, no '..' segments",
    ),
    AfterValidator(_object_key),
]
LocaleTag = Annotated[str, Field(pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$", description="e.g. th-TH")]
CurrencyCode = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
CredentialRef = Annotated[
    str,
    Field(pattern=r"^credref:[a-z0-9][a-z0-9._\-]{1,120}$", description="Name, never a secret"),
]
AccountRef = Annotated[str, Field(pattern=r"^acct:[a-z0-9][a-z0-9._\-]{1,120}$")]
ShortText = Annotated[str, Field(min_length=1, max_length=500)]
LongText = Annotated[str, Field(min_length=1, max_length=20_000)]
Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_.\-]{0,119}$")]


def _sorted_list(value: frozenset) -> list:
    return sorted(value)


# Sets serialize as sorted lists so generated files and hashes are deterministic
# (frozenset iteration order varies between processes).
SortedStrSet = Annotated[frozenset[str], PlainSerializer(_sorted_list, return_type=list[str])]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


UtcDateTime = Annotated[datetime, AfterValidator(_utc)]


def _iana(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_+\-]*(/[A-Za-z0-9_+\-]+)*", value):
        raise ValueError("not an IANA zone name")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown IANA zone {value!r}") from exc
    return value


IanaZone = Annotated[str, AfterValidator(_iana)]


class ContractModel(BaseModel):
    """Base for every contract payload: closed (unknown fields rejected), immutable."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        use_enum_values=False,
        validate_default=True,
        ser_json_timedelta="iso8601",
    )


class VersionedPayload(ContractModel):
    """Top-level cross-module payload: carries the schema version it was built against."""

    schema_version: Literal["1.0"] = Field(
        default=SCHEMA_VERSION, description="Unsupported/stale versions are rejected"
    )


class ScheduleInstant(ContractModel):
    """A schedule point: IANA zone + local wall time + the concrete UTC instant.

    Validation rejects nonexistent local times (DST gaps) and ambiguous local times
    (DST overlaps) unless ``fold`` is given, and requires ``utc_instant`` to equal
    the conversion, so a DST change can never silently move an announced time.
    """

    iana_zone: IanaZone
    local_time: str = Field(
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$",
        description="Wall-clock time in iana_zone, ISO 'YYYY-MM-DDTHH:MM[:SS]' without offset",
    )
    fold: Literal[0, 1] | None = None
    utc_instant: UtcDateTime

    @property
    def local_datetime(self) -> datetime:
        return datetime.fromisoformat(self.local_time)

    @model_validator(mode="after")
    def _consistent(self) -> ScheduleInstant:
        local = self.local_datetime
        zone = ZoneInfo(self.iana_zone)

        def exists(fold: int) -> bool:
            aware = local.replace(tzinfo=zone, fold=fold)
            return aware.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == local

        if not exists(0) and not exists(1):
            raise ValueError("nonexistent local time (DST gap)")
        a = local.replace(tzinfo=zone, fold=0)
        b = local.replace(tzinfo=zone, fold=1)
        if a.utcoffset() != b.utcoffset() and self.fold is None:
            raise ValueError("ambiguous local time (DST overlap); set fold explicitly")
        chosen = local.replace(tzinfo=zone, fold=self.fold or 0)
        if chosen.astimezone(UTC) != self.utc_instant:
            raise ValueError("utc_instant does not match local_time in iana_zone")
        return self

    @classmethod
    def from_local(
        cls, iana_zone: str, local_time: datetime, fold: int | None = None
    ) -> ScheduleInstant:
        """Build from a naive wall-clock datetime; raises on DST gaps/ambiguity."""
        if local_time.tzinfo is not None:
            raise ValueError("local_time must be naive (wall clock in iana_zone)")
        zone = ZoneInfo(iana_zone)
        utc = local_time.replace(tzinfo=zone, fold=fold or 0).astimezone(UTC)
        return cls(
            iana_zone=iana_zone,
            local_time=local_time.isoformat(timespec="seconds"),
            fold=fold,
            utc_instant=utc,
        )


class TimeRange(ContractModel):
    start_ms: DurationMs
    end_ms: DurationMs

    @model_validator(mode="after")
    def _ordered(self) -> TimeRange:
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms must be >= start_ms")
        return self


class EvidenceRef(ContractModel):
    """Pointer to evidence. A hash proves integrity/identity, not truth or rights."""

    source: EvidenceSource
    ref: ShortText
    sha256: Sha256Hex | None = None
    note: str | None = Field(default=None, max_length=2000)
    recorded_at: UtcDateTime | None = None


__all__ = [
    "SCHEMA_VERSION",
    "EPISODE_CAP_MICRO_USD",
    "MICRO_USD_PER_USD",
    "DEFAULT_BUDGET_ALLOCATION_MICRO_USD",
    "MAX_EVENT_PAYLOAD_BYTES",
    "ProductionLimits",
    "DEFAULT_LIMITS",
    "MicroUSD",
    "SignedMicroUSD",
    "DurationMs",
    "PositiveMs",
    "Count",
    "PositiveInt",
    "Revision",
    "BasisPoints",
    "Sha256Hex",
    "IdempotencyKey",
    "SemanticKey",
    "ObjectKey",
    "LocaleTag",
    "CurrencyCode",
    "CredentialRef",
    "AccountRef",
    "ShortText",
    "LongText",
    "Identifier",
    "UtcDateTime",
    "IanaZone",
    "ContractModel",
    "VersionedPayload",
    "ScheduleInstant",
    "TimeRange",
    "EvidenceRef",
    "StrictBool",
    "SortedStrSet",
    "UUID",
]
