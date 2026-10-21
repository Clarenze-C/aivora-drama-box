"""Bible, canon, directing playbook, scripts and prompts (T010).

Public surface:
- ``StoryService``: deterministic approved-scope bible/canon compilation (PLANNED canon
  only; later trend evidence cannot silently change an approved arc) and the paid, bounded
  writer/critic episode pipeline with staging simplification and IMP-02 termination.
- ``build_story_service``: composition factory for the integrator (route/job registration
  is the integrator's job, not this module's).
- Module-local payloads (contracts frozen at 1.5.0; promotion proposal in evidence/T010.md)
  and the six-pattern directing playbook compiled from the shared accepted example.
"""

from microdrama.story.compiler import compile_episode
from microdrama.story.critics import check_draft
from microdrama.story.models import (
    BibleFact,
    CompileResult,
    CriticSeverity,
    CriticVerdict,
    DraftFinding,
    FactKind,
    KnowledgeEntry,
    RawCriticalTerm,
    RawLine,
    RawScene,
    RawStaging,
    SeasonBible,
    StagingSimplification,
    WriteOutcome,
    WriterDraft,
    WriteStatus,
)
from microdrama.story.playbook import (
    DIRECTING_PLAYBOOK,
    PLAYBOOK_VERSION,
    DirectingPattern,
    default_playbook_path,
    load_playbook_example,
)
from microdrama.story.prompts import (
    CRITIC_INSTRUCTION,
    CRITIC_OUTPUT_SCHEMA,
    WRITER_INSTRUCTION,
    WRITER_OUTPUT_SCHEMA,
    build_shot_prompt,
    estimate_line_ms,
)
from microdrama.story.service import (
    DEFAULT_SUPPORTED_CONTROLS,
    WRITABLE_CANON_KINDS,
    CanonKind,
    StoryConfig,
    StoryService,
    budget_key_prefix,
    build_story_service,
    critic_client_token,
    estimated_runtime_ms,
    parse_critic_verdict,
    parse_writer_draft,
    writer_client_token,
)

__all__ = [
    "BibleFact",
    "CanonKind",
    "CompileResult",
    "CRITIC_INSTRUCTION",
    "CRITIC_OUTPUT_SCHEMA",
    "CriticSeverity",
    "CriticVerdict",
    "DEFAULT_SUPPORTED_CONTROLS",
    "DIRECTING_PLAYBOOK",
    "DirectingPattern",
    "DraftFinding",
    "FactKind",
    "KnowledgeEntry",
    "PLAYBOOK_VERSION",
    "RawCriticalTerm",
    "RawLine",
    "RawScene",
    "RawStaging",
    "SeasonBible",
    "StagingSimplification",
    "StoryConfig",
    "StoryService",
    "WRITABLE_CANON_KINDS",
    "WRITER_INSTRUCTION",
    "WRITER_OUTPUT_SCHEMA",
    "WriteOutcome",
    "WriteStatus",
    "WriterDraft",
    "budget_key_prefix",
    "build_shot_prompt",
    "build_story_service",
    "check_draft",
    "compile_episode",
    "critic_client_token",
    "default_playbook_path",
    "estimate_line_ms",
    "estimated_runtime_ms",
    "load_playbook_example",
    "parse_critic_verdict",
    "parse_writer_draft",
    "writer_client_token",
]
