"""Research allocation to episodes (deterministic, idempotent, rejected spend retained) and the
episode cost summary and cost view (lines, unknowns, overruns, synthetic portion)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from budget_support import (
    CAP,
    QA,
    RESEARCH,
    T0,
    World,
    fake_receipt,
    request_for,
)

from microdrama.contracts.enums import ReceiptKind
from microdrama.contracts.errors import BudgetExhausted, Conflict, NotFound, SchemaInvalid


def _research_setup(world: World):
    season = world.episode().season_id
    # The season already holds episode 1 (created above), so these are episodes 2..4.
    episodes = [world.episode(season=season, number=n) for n in (2, 3, 4)]
    envelope = world.research(season, envelope=2_000_000)
    return season, episodes, envelope


def test_research_allocation_is_exact_deterministic_and_idempotent(
    world: World, check_consistent
) -> None:
    season, episodes, envelope = _research_setup(world)
    svc = world.service
    idea_a = svc.reserve(
        request_for(key="research.idea.a", season_id=season, worst=600_000, category=RESEARCH)
    )
    svc.record_usage(
        fake_receipt(
            provider_receipt_id="research.idea.a.final",
            kind=ReceiptKind.SETTLEMENT,
            amount=600_000,
            category=RESEARCH,
            reservation=idea_a,
            season_id=season,
            observed_at=T0,
        )
    )
    svc.record_usage(
        fake_receipt(
            provider_receipt_id="research.idea.b",
            kind=ReceiptKind.ACCRUAL,
            amount=1_000_001,
            category=RESEARCH,
            season_id=season,
            observed_at=T0,
        )
    )
    assert world.counters(envelope)["settled"] == 1_600_001

    ids = [ep.episode_id for ep in episodes]
    first = svc.allocate_research_cost(
        season_id=season, episode_ids=ids, basis="pre-gate-1 research"
    )
    assert len(first) == 6  # two sources x three episodes
    settled = [world.counters(ep.account_id)["settled"] for ep in episodes]
    assert settled == [200_000 + 333_335, 200_000 + 333_333, 200_000 + 333_333]
    assert sum(settled) == 1_600_001
    assert world.counters(envelope)["settled"] == 1_600_001  # the research account keeps its spend
    for ep in episodes:
        check_consistent(ep.account_id)
    check_consistent(envelope)

    assert (
        svc.allocate_research_cost(season_id=season, episode_ids=ids, basis="pre-gate-1 research")
        == []
    )
    assert [world.counters(ep.account_id)["settled"] for ep in episodes] == settled


def test_rejected_idea_spend_stays_on_the_research_account_until_allocated(
    world: World, check_consistent
) -> None:
    season, episodes, envelope = _research_setup(world)
    svc = world.service
    svc.record_usage(
        fake_receipt(
            provider_receipt_id="research.first",
            kind=ReceiptKind.ACCRUAL,
            amount=900_000,
            category=RESEARCH,
            season_id=season,
            observed_at=T0,
        )
    )
    ids = [ep.episode_id for ep in episodes]
    svc.allocate_research_cost(season_id=season, episode_ids=ids, basis="batch 1")
    # A rejected idea: its spend is recorded on the envelope and is not allocated to any episode.
    svc.record_usage(
        fake_receipt(
            provider_receipt_id="research.rejected",
            kind=ReceiptKind.ACCRUAL,
            amount=50_000,
            category=RESEARCH,
            season_id=season,
            observed_at=T0,
        )
    )
    assert world.counters(envelope)["settled"] == 950_000
    assert [world.counters(ep.account_id)["settled"] for ep in episodes] == [
        300_000,
        300_000,
        300_000,
    ]
    later = svc.allocate_research_cost(season_id=season, episode_ids=ids, basis="batch 2")
    assert sum(a.amount_micro_usd for a in later) == 50_000
    assert world.counters(envelope)["settled"] == 950_000
    check_consistent(envelope)


def test_research_allocation_is_refused_across_seasons_and_for_unknown_episodes(
    world: World,
) -> None:
    season, episodes, envelope = _research_setup(world)
    other_season = world.episode().season_id
    stray = world.episode(season=other_season, number=2)
    with pytest.raises(Conflict):
        world.service.allocate_research_cost(
            season_id=season, episode_ids=[episodes[0].episode_id, stray.episode_id], basis="mixed"
        )
    with pytest.raises(NotFound):
        world.service.allocate_research_cost(
            season_id=season, episode_ids=[episodes[0].episode_id, uuid.uuid4()], basis="ghost"
        )
    with pytest.raises(SchemaInvalid):
        world.service.allocate_research_cost(season_id=season, episode_ids=[], basis="none")
    with pytest.raises(SchemaInvalid):
        world.service.allocate_research_cost(
            season_id=season,
            episode_ids=[episodes[0].episode_id, episodes[0].episode_id],
            basis="dup",
        )


def test_research_allocation_into_an_episode_is_subject_to_the_overrun_rule(
    world: World, check_consistent
) -> None:
    season = world.episode().season_id
    target = world.episode(season=season, number=7)
    envelope = world.research(season, envelope=10_000_000)
    world.service.reserve(
        request_for(key="near.cap.gpu", episode_id=target.episode_id, worst=4_750_000)
    )
    source = world.service.record_usage(
        fake_receipt(
            provider_receipt_id="research.big",
            kind=ReceiptKind.ACCRUAL,
            amount=6_000_000,
            category=RESEARCH,
            season_id=season,
            observed_at=T0,
        )
    )
    allocated = world.service.allocate_research_cost(
        season_id=season, episode_ids=[target.episode_id], basis="attributed"
    )
    assert [a.amount_micro_usd for a in allocated] == [6_000_000]
    counters = world.counters(target.account_id)
    assert counters["committed"] == 10_750_000 and counters["overrun"] == 750_000
    assert counters["blocked"] is True
    with pytest.raises(BudgetExhausted):
        world.service.reserve(
            request_for(key="after.overrun", episode_id=target.episode_id, worst=1)
        )
    assert world.counters(envelope)["settled"] == 6_000_000  # the envelope keeps the spend
    with db_overrun_charge(world, target.account_id) as charge_id:
        assert charge_id == source.charge_id
    check_consistent(target.account_id)
    check_consistent(envelope)


def db_overrun_charge(world: World, account_id):
    """Context manager returning the charge id that the recorded overrun points at."""

    class _Lookup:
        def __enter__(self):
            with world.db.transaction() as tx:
                self.value = tx.fetchval(
                    "SELECT charge_id FROM cost_overruns WHERE account_id = %s", (account_id,)
                )
            return self.value

        def __exit__(self, *exc):
            return False

    return _Lookup()


def test_summary_and_cost_view_explain_every_line_and_flag_unknowns(
    world: World, check_consistent
) -> None:
    ep = world.episode()
    svc = world.service
    spent = svc.reserve(
        request_for(
            key="rep.spent",
            episode_id=ep.episode_id,
            worst=700_000,
            expires_at=T0 + timedelta(hours=1),
        )
    )
    svc.record_usage(
        fake_receipt(
            provider_receipt_id="rep.spent.final",
            kind=ReceiptKind.SETTLEMENT,
            amount=300_000,
            reservation=spent,
            episode_id=ep.episode_id,
            observed_at=T0,
        )
    )
    svc.record_usage(
        fake_receipt(
            provider_receipt_id="rep.unreserved",
            kind=ReceiptKind.ACCRUAL,
            amount=100_000,
            episode_id=ep.episode_id,
            observed_at=T0,
        )
    )
    svc.reserve(
        request_for(
            key="rep.qa.expires",
            episode_id=ep.episode_id,
            worst=200_000,
            category=QA,
            expires_at=T0 + timedelta(hours=1),
        )
    )
    svc.reserve(
        request_for(
            key="rep.open",
            episode_id=ep.episode_id,
            worst=50_000,
            expires_at=T0 + timedelta(days=2),
        )
    )
    world.clock.advance(seconds=7200)
    assert svc.expire_stale() == 1  # only the QA reservation has expired

    summary = svc.summary(ep.episode_id)
    assert summary.episode_cap_micro_usd == CAP
    assert summary.settled_micro_usd == 400_000
    assert summary.accrued_micro_usd == 200_000  # the expired QA worst case, awaiting settlement
    assert summary.reserved_outstanding_micro_usd == 50_000
    assert summary.remaining_micro_usd == CAP - 650_000
    assert summary.synthetic_fake_micro_usd == 400_000  # every receipt here is synthetic

    view = svc.cost_view(ep.episode_id)
    assert view.summary == summary
    assert len(view.lines) == 2
    assert {(line.kind, line.amount_micro_usd, line.cost_basis) for line in view.lines} == {
        ("settlement", 300_000, "synthetic_fake"),
        ("accrual", 100_000, "synthetic_fake"),
    }
    assert view.overruns == []
    assert len(view.unknowns) == 1 and "expired unsettled" in view.unknowns[0]
    check_consistent(ep.account_id)


def test_cost_view_reports_overruns_and_keeps_the_receipt(world: World, check_consistent) -> None:
    ep = world.episode()
    world.service.record_usage(
        fake_receipt(
            provider_receipt_id="ovr.big",
            kind=ReceiptKind.ACCRUAL,
            amount=10_500_000,
            episode_id=ep.episode_id,
            observed_at=T0,
        )
    )
    view = world.service.cost_view(ep.episode_id)
    assert len(view.overruns) == 1
    assert "observed overrun of 500000 micro-USD" in view.overruns[0]
    assert "paid dispatch blocked" in view.overruns[0]
    assert [line.amount_micro_usd for line in view.lines] == [10_500_000]
    assert view.summary.remaining_micro_usd == 0
    check_consistent(ep.account_id)


def test_accrued_research_usage_is_not_attributed_twice(world: World, check_consistent) -> None:
    """Regression: an adjustment on an open research reservation sits in accrued usage and is
    counted again inside the final settlement. Attribution must count the final amount once."""
    season, episodes, envelope = _research_setup(world)
    svc = world.service
    idea = svc.reserve(
        request_for(key="research.accrued.idea", season_id=season, worst=700_000, category=RESEARCH)
    )
    svc.record_usage(
        fake_receipt(
            provider_receipt_id="research.accrued.adjust",
            kind=ReceiptKind.ADJUSTMENT,
            amount=100_000,
            category=RESEARCH,
            reservation=idea,
            season_id=season,
            observed_at=T0,
        )
    )
    svc.record_usage(
        fake_receipt(
            provider_receipt_id="research.accrued.final",
            kind=ReceiptKind.SETTLEMENT,
            amount=650_000,
            category=RESEARCH,
            reservation=idea,
            season_id=season,
            observed_at=T0,
        )
    )
    assert world.counters(envelope)["settled"] == 650_000
    allocated = svc.allocate_research_cost(
        season_id=season, episode_ids=[ep.episode_id for ep in episodes], basis="final amounts only"
    )
    assert sum(a.amount_micro_usd for a in allocated) == 650_000
    assert sum(world.counters(ep.account_id)["settled"] for ep in episodes) == 650_000
    for ep in episodes:
        check_consistent(ep.account_id)
    check_consistent(envelope)
