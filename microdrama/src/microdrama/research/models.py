"""Module-local research payloads (T009). Contracts are frozen at 1.2.1, so these extend
``ContractModel`` inside the research module only; none of them conflict with a contracts/
schema. A contract-change proposal to promote them is recorded in evidence/T009.md.

Rules encoded here (SPEC §7/§12, task packet T009):
- Source text, comments and comparator material are DATA. They are carried in dedicated
  untrusted fields, never merged into instructions.
- Unknowns are first-class: a probe outcome is RETRIEVED or UNKNOWN (never PASS-by-default),
  a missing publication date is a NULL ``published_at`` plus an explicit date_status, and an
  originality verdict has an UNKNOWN state for an unavailable comparator corpus.
- Money never appears in these payloads except as integer micro-USD.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field

from microdrama.contracts.enums import Provenance, SourceQuality
from microdrama.contracts.primitives import (
    BasisPoints,
    ContractModel,
    Count,
    Identifier,
    PositiveInt,
    SemanticKey,
    Sha256Hex,
    ShortText,
    UtcDateTime,
    VersionedPayload,
)
from microdrama.contracts.season import SeasonScope


class ResearchTrigger(StrEnum):
    SCHEDULED = "SCHEDULED"
    MANUAL = "MANUAL"


class ProbeOutcome(StrEnum):
    RETRIEVED = "RETRIEVED"
    UNKNOWN = "UNKNOWN"  # source failure, unavailable provider, missing data


class SynthesisStatus(StrEnum):
    USED = "USED"
    UNKNOWN = "UNKNOWN"  # the model output could not be validated; nothing invented


class DateStatus(StrEnum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"  # published_at is NULL: the date is unknown, not absent-by-accident


class ResemblanceKind(StrEnum):
    SCENE = "SCENE"
    PERSONA = "PERSONA"
    TITLE = "TITLE"


class ResemblanceSeverity(StrEnum):
    BLOCKED = "BLOCKED"
    FLAG = "FLAG"


class OriginalityStatus(StrEnum):
    CLEAR = "CLEAR"
    FLAGGED = "FLAGGED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"  # comparator corpus unavailable: originality is unverified


# --- inputs -------------------------------------------------------------------------------


class CommentIn(ContractModel):
    """One public comment, verbatim, as untrusted data (a qualitative clue, never a share)."""

    author_ref: ShortText
    text: str = Field(
        min_length=1, max_length=5000, description="Untrusted data; never instructions"
    )


class PersonaProfile(ContractModel):
    """A comparator persona: supplied comparable material, used only for resemblance checks."""

    name: ShortText
    traits: list[ShortText] = Field(default_factory=list)


class ComparatorCorpus(ContractModel):
    """Comparator material supplied as data. Empty means the check cannot run (UNKNOWN)."""

    scenes: list[str] = Field(default_factory=list, max_length=200)
    personas: list[PersonaProfile] = Field(default_factory=list, max_length=200)

    @property
    def available(self) -> bool:
        return bool(self.scenes or self.personas)


class ConceptDraft(ContractModel):
    """One candidate season concept. ``scope`` supplies the narrative fields; the service
    stamps season_id / scope_version / source_proposal_id, merges uncertainty notes and
    evidence refs, so the draft's values for those fields are ignored (and excluded from the
    request hash)."""

    concept_id: Identifier
    theme_keys: list[Identifier] = Field(default_factory=list)
    scope: SeasonScope


class ResearchRequest(VersionedPayload):
    """One bounded research run. ``trigger_key`` is the scheduler's stable semantic key:
    repeating a scheduled trigger replays the same run and never resets the allowance."""

    trigger: ResearchTrigger
    trigger_key: SemanticKey
    source_provider_id: Identifier = "fake-sources"
    allowed_source_ids: list[Identifier] = Field(min_length=1)
    query_texts: list[ShortText] = Field(min_length=1)
    comments: list[CommentIn] = Field(default_factory=list, max_length=500)
    comparator_corpus: ComparatorCorpus
    candidate_concepts: list[ConceptDraft] = Field(min_length=1, max_length=20)


# --- ledger and analysis views ------------------------------------------------------------


class SourceProbe(ContractModel):
    """Typed per-source outcome of one run. UNKNOWN is terminal data, never upgraded later."""

    source_id: Identifier
    outcome: ProbeOutcome
    detail: ShortText | None = None


class LedgerEntryView(ContractModel):
    """One provenance/date/quality ledger row as the service reports it."""

    source_id: Identifier
    url: str
    title: ShortText
    published_at: UtcDateTime | None
    retrieved_at: UtcDateTime
    date_status: DateStatus
    quality: SourceQuality
    provenance: Provenance
    content_sha256: Sha256Hex
    mention_count: PositiveInt
    first_seen_run_id: UUID | None = None
    last_seen_run_id: UUID | None = None

    @property
    def is_fixture(self) -> bool:
        """Mock citations are distinguishable from actual sources (FIXTURE / *.invalid)."""
        return (
            self.quality is SourceQuality.FIXTURE and self.provenance is Provenance.FAKE_SYNTHETIC
        )


class CommentCluster(ContractModel):
    """Deduplicated public-comment signal: near-duplicate comments collapse to one cluster."""

    cluster_key: Sha256Hex
    representative_text: str = Field(max_length=5000)
    size: PositiveInt
    distinct_authors: PositiveInt
    sample_author_refs: list[ShortText] = Field(default_factory=list)


class ThemeCluster(ContractModel):
    """A theme mined from source documents, supported by distinct sources."""

    theme_key: Identifier
    label: ShortText
    distinct_sources: PositiveInt
    occurrences: PositiveInt
    source_ids: list[Identifier]


class ResemblanceFinding(ContractModel):
    kind: ResemblanceKind
    severity: ResemblanceSeverity
    comparator_ref: ShortText
    matched_excerpt: str = Field(max_length=2000)
    matched_in: Identifier = Field(description="Which concept field matched")
    detail: ShortText


class OriginalityVerdict(ContractModel):
    """Proposal-level originality result. BLOCKED concepts are never proposed; UNKNOWN means
    the comparator corpus was unavailable and the proposal must carry that uncertainty."""

    status: OriginalityStatus
    findings: list[ResemblanceFinding] = Field(default_factory=list)
    note: ShortText | None = None


class RankedConcept(ContractModel):
    concept_id: Identifier
    verdict: OriginalityVerdict
    theme_support_bp: BasisPoints
    rank: PositiveInt | None = Field(default=None, description="Set for eligible concepts only")


class ResearchOutcome(VersionedPayload):
    """The typed result persisted on a COMPLETED run."""

    probes: list[SourceProbe]
    documents: list[LedgerEntryView] = Field(description="This run's view of the ledger")
    new_documents: Count
    duplicate_documents: Count
    date_unknown_source_ids: list[Identifier]
    themes: list[ThemeCluster]
    comment_clusters: list[CommentCluster]
    synthesis: SynthesisStatus
    uncertainty_notes: list[ShortText]
    ranked: list[RankedConcept]
    chosen_concept_id: Identifier | None = Field(
        default=None, description="None when no eligible concept existed"
    )
    settled_micro_usd: Count = Field(description="Spend retained by this run, failures included")


class ResearchResult(ContractModel):
    """What ``run_research`` returns. ``replayed`` marks an idempotent return of a past run."""

    run_id: UUID
    state: str
    replayed: bool
    outcome: ResearchOutcome | None = None
    failure_code: str | None = None
    proposal_id: UUID | None = None


__all__ = [
    "CommentCluster",
    "CommentIn",
    "ComparatorCorpus",
    "ConceptDraft",
    "DateStatus",
    "LedgerEntryView",
    "OriginalityStatus",
    "OriginalityVerdict",
    "PersonaProfile",
    "ProbeOutcome",
    "RankedConcept",
    "ResearchOutcome",
    "ResearchRequest",
    "ResearchResult",
    "ResearchTrigger",
    "ResemblanceFinding",
    "ResemblanceKind",
    "ResemblanceSeverity",
    "SourceProbe",
    "SynthesisStatus",
]
