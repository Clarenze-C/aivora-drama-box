"""Helpers for the story contract tests: DB-free bible/compile fixtures."""

from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

_SUPPORT_ROOT = Path(__file__).resolve().parents[2] / "unit" / "story"
sys.path.insert(0, str(_SUPPORT_ROOT))

from story_support import canonical_writer_output  # noqa: E402

from microdrama.contracts.hashing import canonical_hash  # noqa: E402
from microdrama.contracts.primitives import DEFAULT_LIMITS  # noqa: E402
from microdrama.contracts.season import SeasonScope  # noqa: E402
from microdrama.story.critics import check_draft  # noqa: E402
from microdrama.story.models import SeasonBible  # noqa: E402
from microdrama.story.playbook import PLAYBOOK_VERSION  # noqa: E402
from microdrama.story.prompts import estimate_line_ms  # noqa: E402


def bible_from_scope(scope: SeasonScope) -> SeasonBible:
    """A deterministic PLANNED bible for contract-level compile checks (no database)."""
    facts = [
        {
            "fact_key": "premise",
            "kind": "PREMISE",
            "statement": scope.premise[:2000],
            "source_field": "premise",
            "episode_number": None,
        }
    ]
    knowledge = []
    for beat in scope.arc:
        facts.append(
            {
                "fact_key": f"beat.{beat.episode_number}",
                "kind": "ARC_BEAT",
                "statement": beat.summary[:2000],
                "source_field": "arc",
                "episode_number": beat.episode_number,
            }
        )
        for index, reveal in enumerate(beat.planned_reveals, start=1):
            facts.append(
                {
                    "fact_key": f"reveal.{beat.episode_number}.{index}",
                    "kind": "PLANNED_REVEAL",
                    "statement": reveal,
                    "source_field": "arc.planned_reveals",
                    "episode_number": beat.episode_number,
                }
            )
            knowledge.append(
                {
                    "fact_key": f"reveal.{beat.episode_number}.{index}",
                    "known_from_episode": beat.episode_number,
                }
            )
    return SeasonBible(
        bible_id=uuid.uuid5(uuid.NAMESPACE_URL, "contract-bible"),
        season_id=scope.season_id,
        scope_version=scope.scope_version,
        approved_scope_hash=canonical_hash(scope),
        canon_version=1,
        title_th=scope.title_th,
        title_en=scope.title_en,
        logline=scope.logline,
        premise=scope.premise,
        characters=list(scope.characters),
        arc=list(scope.arc),
        facts=facts,
        knowledge=knowledge,
        playbook_version=PLAYBOOK_VERSION,
        compiled_at=datetime(2026, 10, 21, tzinfo=UTC),
    )


__all__ = [
    "DEFAULT_LIMITS",
    "bible_from_scope",
    "canonical_writer_output",
    "check_draft",
    "estimate_line_ms",
]
