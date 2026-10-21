"""Sources, provenance, originality, season proposals (T009: bounded source research).

Public surface:
- ``ResearchService``: bounded research runs against the season research envelope; writes
  versioned ``season_proposals`` rows with provenance, never published canon.
- ``build_research_service``: composition factory for the integrator (route/job
  registration is the integrator's job, not this module's).
- ``ResearchRequest`` / ``ResearchOutcome`` / related module-local payloads (contracts are
  frozen at 1.2.1; a promotion proposal is recorded in evidence/T009.md).
- ``build_source_registry``: config-driven source provider registry; live adapters stay
  disabled without configured credentials (no real HTTP exists in this lane).
"""

from microdrama.research.models import (
    CommentCluster,
    CommentIn,
    ComparatorCorpus,
    ConceptDraft,
    DateStatus,
    LedgerEntryView,
    OriginalityStatus,
    OriginalityVerdict,
    PersonaProfile,
    ProbeOutcome,
    RankedConcept,
    ResearchOutcome,
    ResearchRequest,
    ResearchResult,
    ResearchTrigger,
    ResemblanceFinding,
    ResemblanceKind,
    ResemblanceSeverity,
    SourceProbe,
    SynthesisStatus,
    ThemeCluster,
)
from microdrama.research.service import (
    LLM_INSTRUCTION,
    ResearchConfig,
    ResearchService,
    RunState,
    build_research_service,
    normalized_request_hash,
)
from microdrama.research.sources import SourceAdapterRecord, build_source_registry

__all__ = [
    "CommentCluster",
    "CommentIn",
    "ComparatorCorpus",
    "ConceptDraft",
    "DateStatus",
    "LLM_INSTRUCTION",
    "LedgerEntryView",
    "OriginalityStatus",
    "OriginalityVerdict",
    "PersonaProfile",
    "ProbeOutcome",
    "RankedConcept",
    "ResearchConfig",
    "ResearchOutcome",
    "ResearchRequest",
    "ResearchResult",
    "ResearchService",
    "ResearchTrigger",
    "ResemblanceFinding",
    "ResemblanceKind",
    "ResemblanceSeverity",
    "RunState",
    "SourceAdapterRecord",
    "SourceProbe",
    "SynthesisStatus",
    "ThemeCluster",
    "build_research_service",
    "build_source_registry",
    "normalized_request_hash",
]
