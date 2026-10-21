"""Mock-citation honesty and module sanity (T009): fixture sources are distinguishable
from actual sources in the ledger, the evidence refs and the contract itself."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from research_support import World, request

from microdrama.contracts.enums import Provenance, SourceQuality
from microdrama.contracts.hashing import sha256_hex
from microdrama.contracts.providers import SourceDocument


def _document(url: str, quality: SourceQuality, provenance: Provenance) -> SourceDocument:
    excerpt = "Synthetic fixture excerpt. Not a real source."
    return SourceDocument(
        source_id="src-x",
        url=url,
        title="Fixture document",
        published_at=datetime(2026, 10, 1, tzinfo=UTC),
        retrieved_at=datetime(2026, 10, 2, tzinfo=UTC),
        quality=quality,
        excerpt=excerpt,
        content_sha256=sha256_hex(excerpt.encode("utf-8")),
        provenance=provenance,
    )


def test_contract_forbids_fake_provenance_with_a_real_url() -> None:
    with pytest.raises(ValidationError):
        _document("https://example.com/real", SourceQuality.FIXTURE, Provenance.FAKE_SYNTHETIC)


def test_contract_forbids_fixture_quality_with_live_provenance() -> None:
    with pytest.raises(ValidationError):
        _document(
            "https://sources.invalid/x",
            SourceQuality.FIXTURE,
            Provenance.LIVE_PROVIDER,
        )


def test_ledger_labels_fixture_documents(world: World) -> None:
    season = world.season()
    result = world.service.run_research(season, request())
    assert result.outcome is not None
    ledger = world.service.ledger(season)
    assert ledger
    for entry in ledger:
        assert entry.quality is SourceQuality.FIXTURE
        assert entry.provenance is Provenance.FAKE_SYNTHETIC
        assert entry.url.split("/")[2].endswith(".invalid")
        assert entry.is_fixture is True
        assert entry.published_at is not None  # default scenario publishes a date


def test_proposal_evidence_refs_distinguish_fixture_from_actual(world: World) -> None:
    season = world.season()
    result = world.service.run_research(season, request())
    assert result.proposal_id is not None
    proposal = world.row("SELECT * FROM season_proposals WHERE id = %s", (result.proposal_id,))
    refs = proposal["scope"]["research_evidence_refs"]
    assert refs and all(ref.startswith("fixture:") for ref in refs)
    assert all("#" in ref for ref in refs)  # each ref pins the content hash


def test_dedupe_key_is_content_not_url(world: World) -> None:
    """Two runs see the same fixture content: one ledger row, mention count 2."""
    season = world.season()
    world.service.run_research(season, request())
    world.service.run_research(season, request(key="research.daily:v2"))
    rows = world.rows("SELECT * FROM research_source_documents WHERE season_id = %s", (season,))
    assert len(rows) == 2
    assert all(row["mention_count"] == 2 for row in rows)


def test_theme_mining_needs_multiple_distinct_sources(world: World) -> None:
    """The default fixture excerpts carry 'thai'/'drama' in both source ids, so themes
    exist; a single allowed source cannot mint a theme (min distinct sources = 2)."""
    season = world.season()
    result = world.service.run_research(
        season, request(source_ids=("src-thai-drama-1",), key="research.solo:v1")
    )
    assert result.outcome is not None
    assert result.outcome.themes == []
    # And the run's documents cannot support a theme key either.
    assert result.outcome.documents[0].source_id == "src-thai-drama-1"


def test_theme_support_ranks_concepts(world: World) -> None:
    season = world.season()
    result = world.service.run_research(season, request())
    assert result.outcome is not None
    theme_keys = {theme.theme_key for theme in result.outcome.themes}
    assert {"thai", "drama"} <= theme_keys  # from src-thai-drama-1/2 fixture excerpts
    by_id = {ranked.concept_id: ranked for ranked in result.outcome.ranked}
    assert by_id["concept-a"].theme_support_bp == 10_000  # thai + drama
    assert by_id["concept-b"].theme_support_bp == 10_000  # drama only: 1/1 keys matched


def test_ledger_content_columns_are_immutable(world: World) -> None:
    season = world.season()
    world.service.run_research(season, request())
    row = world.rows(
        "SELECT id FROM research_source_documents WHERE season_id = %s LIMIT 1", (season,)
    )[0]
    with pytest.raises(Exception, match="immutable"):
        with world.db.transaction() as tx:
            tx.execute(
                "UPDATE research_source_documents SET excerpt = 'tampered', title = 'tampered' "
                "WHERE id = %s",
                (row["id"],),
            )
