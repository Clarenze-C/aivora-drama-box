"""Module-local story payloads (T010). Contracts are frozen at 1.5.0, so these extend
``ContractModel`` inside the story module only; none of them conflict with a contracts/
schema. A contract-change proposal to promote them is recorded in evidence/T010.md.

Rules encoded here (SPEC §5/§7, task packet T010):
- Planned, final-approved and published facts are SEPARATE kinds (``canon_versions.kind``).
  This module writes PLANNED only; a planned reveal is never published canon.
- The writer/critic model outputs are DATA: they arrive as untrusted dictionaries, are
  parsed defensively and can never carry instructions into the pipeline.
- Actual timings are unknown until measured: a compiled line keeps ``actual_duration_ms``
  None; unknowns stay typed (``NOT_DISPATCHED`` is a typed outcome, never success).
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field

from microdrama.contracts.enums import FallbackEdit
from microdrama.contracts.primitives import (
    ContractModel,
    Count,
    Identifier,
    MicroUSD,
    PositiveInt,
    Sha256Hex,
    ShortText,
    UtcDateTime,
    VersionedPayload,
)
from microdrama.contracts.season import ArcBeat, CharacterBrief


class FactKind(StrEnum):
    PREMISE = "PREMISE"
    CHARACTER = "CHARACTER"
    ARC_BEAT = "ARC_BEAT"
    PLANNED_REVEAL = "PLANNED_REVEAL"  # planned only; not published canon
    CLIFFHANGER = "CLIFFHANGER"


class BibleFact(ContractModel):
    """One compiled canon fact with the scope field it was derived from (traceable)."""

    fact_key: Identifier
    kind: FactKind
    statement: str = Field(min_length=1, max_length=2000)
    source_field: ShortText
    episode_number: PositiveInt | None = Field(
        default=None, description="Set for arc-scoped facts (the episode they belong to)"
    )


class KnowledgeEntry(ContractModel):
    """From which episode a planned reveal becomes character knowledge (anti-spoiler basis)."""

    fact_key: Identifier
    known_from_episode: PositiveInt


class SeasonBible(VersionedPayload):
    """Deterministic compilation of the Gate-1-approved scope. Hash-bound to that scope."""

    bible_id: UUID
    season_id: UUID
    scope_version: PositiveInt
    approved_scope_hash: Sha256Hex
    canon_version: Count = Field(description="PLANNED canon version this bible became")
    title_th: ShortText
    title_en: ShortText
    logline: str
    premise: str
    characters: list[CharacterBrief] = Field(min_length=1)
    arc: list[ArcBeat] = Field(min_length=1)
    facts: list[BibleFact] = Field(min_length=1)
    knowledge: list[KnowledgeEntry] = Field(default_factory=list)
    playbook_version: ShortText
    compiled_at: UtcDateTime


# --- writer draft (untrusted model output, parsed defensively) ---------------------------


class RawCriticalTerm(ContractModel):
    kind: str = Field(description="Validated against CriticalTermKind by the parser")
    value_th: str = Field(min_length=1, max_length=200)
    value_en: str | None = None


class RawStaging(ContractModel):
    """Writer-requested staging. Controls are a wish-list: unsupported ones are simplified."""

    pattern_id: str | None = None
    controls: list[str] = Field(default_factory=list, max_length=16)
    framing: str | None = None
    eyelines: str | None = None
    sound: str | None = None
    prop_ids: list[str] = Field(default_factory=list, max_length=12)
    fallback_edit: str | None = None


class RawLine(ContractModel):
    speaker_character_id: str = Field(min_length=1, max_length=120)
    text_th: str = Field(min_length=1, max_length=1000)
    text_en: str = Field(min_length=1, max_length=1000)
    critical_terms: list[RawCriticalTerm] = Field(default_factory=list, max_length=8)
    staging: RawStaging = Field(default_factory=RawStaging)


class RawScene(ContractModel):
    summary: str | None = Field(default=None, max_length=500)
    location_id: str | None = Field(default=None, max_length=120)
    lines: list[RawLine] = Field(min_length=1, max_length=40)
    staging: RawStaging = Field(default_factory=RawStaging)


class WriterDraft(ContractModel):
    scenes: list[RawScene] = Field(min_length=1, max_length=12)


# --- critics -----------------------------------------------------------------------------


class CriticSeverity(StrEnum):
    BLOCKED = "BLOCKED"  # canon/knowledge/term violation: never passes, needs a rewrite
    REPAIRABLE = "REPAIRABLE"  # complexity/pacing: a bounded rewrite may fix it


class DraftFinding(ContractModel):
    code: Identifier
    severity: CriticSeverity
    detail: str = Field(min_length=1, max_length=1000)
    scene_index: Count | None = None
    line_index: Count | None = None


class CriticVerdict(ContractModel):
    passed: bool
    findings: list[DraftFinding] = Field(default_factory=list)


# --- outcomes ---------------------------------------------------------------------------


class StagingSimplification(ContractModel):
    """Recorded whenever unsupported staging was simplified (SPEC §7).

    The dramatic change is preserved: purpose, pattern payoff and dialogue bindings stay;
    only the unsupported staging (controls/framing/fallback) is replaced.
    """

    shot_id: Identifier
    removed_controls: list[str] = Field(default_factory=list)
    fallback_applied: FallbackEdit
    preserved_change: ShortText


class WriteStatus(StrEnum):
    CURRENT = "CURRENT"  # script + manifest persisted as the episode's current versions
    REPLAYED = "REPLAYED"  # idempotent return of an existing current script
    CRITIC_FAILED = "CRITIC_FAILED"  # bounded rewrite limit reached; spend retained
    WRITER_FAILED = "WRITER_FAILED"  # no valid writer output within attempts; spend retained
    NOT_DISPATCHED = "NOT_DISPATCHED"  # no configured price: nothing dispatched (typed)


class WriteOutcome(VersionedPayload):
    """What ``write_episode`` returns. Failed attempts keep their spend (MD-008)."""

    episode_id: UUID
    status: WriteStatus
    script_id: UUID | None = None
    manifest_id: UUID | None = None
    script_version: Count = 0
    settled_micro_usd: MicroUSD = Field(
        description="Spend retained by this call, failures included"
    )
    rounds_used: Count = 0
    findings: list[DraftFinding] = Field(default_factory=list)
    simplifications: list[StagingSimplification] = Field(default_factory=list)
    uncertainty_notes: list[ShortText] = Field(default_factory=list)


class CompileResult(VersionedPayload):
    """What ``compile_season`` returns."""

    season_id: UUID
    scope_version: PositiveInt
    canon_version: Count
    replayed: bool
    facts_hash: Sha256Hex
    bible: SeasonBible


__all__ = [
    "BibleFact",
    "CompileResult",
    "CriticSeverity",
    "CriticVerdict",
    "DraftFinding",
    "FactKind",
    "KnowledgeEntry",
    "RawCriticalTerm",
    "RawLine",
    "RawScene",
    "RawStaging",
    "SeasonBible",
    "StagingSimplification",
    "WriteOutcome",
    "WriteStatus",
    "WriterDraft",
]
