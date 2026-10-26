"""The sealed package's QA summary derives unknown coverage from evidence (F09).

``_qa_summary`` must keep every unknown visible in the sealed package: a check
that never ran, ran partially or ended UNKNOWN keeps its check id, and a required
critical check with no finding row at all is missing evidence (retained as
unknown, never assumed as a pass). Superseded findings are history, not evidence.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from microdrama.persistence.db import insert_row
from microdrama.pipeline.packaging import _qa_summary
from microdrama.qa.config import CRITICAL_CHECK_IDS
from microdrama.testing.seed import seed_episode, seed_season

pytestmark = [pytest.mark.db]


def _finding(
    tx,
    episode_id,
    *,
    check_id,
    coverage="CHECKED",
    outcome="PASS",
    severity="MINOR",
    resolution="OPEN",
    cycle=1,
):
    insert_row(
        tx,
        "qa_findings",
        {
            "id": uuid4(),
            "episode_id": episode_id,
            "qa_cycle": cycle,
            "asset_id": uuid4(),
            "start_ms": 0,
            "end_ms": 1000,
            "check_id": check_id,
            "check_family": check_id.split(".")[0],
            "source_pass": "TECHNICAL",
            "severity": severity,
            "coverage": coverage,
            "outcome": outcome,
            "body": {"check_id": check_id},
            "resolution": resolution,
        },
    )


def _episode(world):
    with world.db.transaction() as tx:
        season = seed_season(tx, state="SEASON_APPROVED")
        return seed_episode(tx, season, number=1, state="AI_REVIEW")


def test_unknown_and_partial_findings_keep_their_check_ids(world):
    episode = _episode(world)
    with world.db.transaction() as tx:
        _finding(
            tx, episode, check_id="temporal.black_frames", coverage="UNSAMPLED", outcome="UNKNOWN"
        )
        _finding(tx, episode, check_id="temporal.frozen_frames", outcome="UNKNOWN")
        _finding(
            tx,
            episode,
            check_id="caption.cue_within_media",
            coverage="PARTIAL",
            outcome="REPAIRABLE",
        )
        _finding(tx, episode, check_id="technical.decode")  # CHECKED/PASS
    with world.db.transaction(readonly=True) as tx:
        summary = _qa_summary(tx, episode)
    unknown = set(summary.unknown_coverage_check_ids)
    assert {
        "temporal.black_frames",
        "temporal.frozen_frames",
        "caption.cue_within_media",
    } <= unknown
    assert "technical.decode" not in unknown


def test_missing_critical_checks_are_unknown_never_assumed_passes(world):
    episode = _episode(world)
    with world.db.transaction() as tx:
        _finding(tx, episode, check_id="technical.decode")
    with world.db.transaction(readonly=True) as tx:
        summary = _qa_summary(tx, episode)
    observed = {"technical.decode"}
    assert set(summary.unknown_coverage_check_ids) >= set(CRITICAL_CHECK_IDS) - observed


def test_superseded_findings_are_history_not_evidence(world):
    episode = _episode(world)
    with world.db.transaction() as tx:
        for check_id in CRITICAL_CHECK_IDS:
            _finding(tx, episode, check_id=check_id, resolution="SUPERSEDED")
    with world.db.transaction(readonly=True) as tx:
        summary = _qa_summary(tx, episode)
    assert summary.finding_count == 0
    # Every critical check is now missing evidence — none of them is a pass.
    assert set(summary.unknown_coverage_check_ids) == set(CRITICAL_CHECK_IDS)


def test_fully_checked_episode_has_no_unknowns(world):
    episode = _episode(world)
    with world.db.transaction() as tx:
        for check_id in CRITICAL_CHECK_IDS:
            _finding(tx, episode, check_id=check_id)
    with world.db.transaction(readonly=True) as tx:
        summary = _qa_summary(tx, episode)
    assert summary.unknown_coverage_check_ids == []
    assert summary.finding_count == len(CRITICAL_CHECK_IDS)
    assert summary.blocking_finding_ids == []
