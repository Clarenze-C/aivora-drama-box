"""Research attribution at the story claim (build-review F06, MD-007).

The episode account opens, unallocated settled season research is booked into
the season's open episode accounts BEFORE any paid dispatch, and a research
share that cannot fit the episode cap refuses the dispatch typed.
"""

from __future__ import annotations

import uuid

import pytest
from story_support import World

from microdrama.contracts.cost import UsageReceipt
from microdrama.contracts.enums import BudgetCategory, CostBasis, ReceiptKind
from microdrama.contracts.errors import BudgetExhausted
from microdrama.contracts.examples import season_scope
from microdrama.contracts.season import CostPolicy
from microdrama.story.service import StoryService

pytestmark = [pytest.mark.db]


def _research_charge(world: World, season_id: uuid.UUID, amount: int) -> None:
    world.budget.record_usage(
        UsageReceipt(
            receipt_id=uuid.uuid4(),
            provider="fake-sources",
            provider_receipt_id=f"story-research-{uuid.uuid4().hex[:12]}",
            kind=ReceiptKind.SETTLEMENT,
            cost_basis=CostBasis.SYNTHETIC_FAKE,
            season_id=season_id,
            category=BudgetCategory.RESEARCH_SCRIPT_PROMPTS_METADATA,
            amount_micro_usd=amount,
            units=1,
            unit="REQUEST",
            observed_at=world.clock.now(),
            provenance="FAKE_SYNTHETIC",
        )
    )


def _ready_with_research(world: World, *, research_amount: int = 300_000):
    season_id, scope = world.season()
    with world.db.transaction() as tx:
        world.budget.open_research_account(tx, season_id=season_id, envelope_micro_usd=1_000_000)
    _research_charge(world, season_id, research_amount)
    world.service.compile_season(season_id)
    episode_id = world.episode(season_id, scope, number=1)
    return episode_id, season_id, scope


def test_write_books_research_into_the_episode_before_paid_dispatch(world: World) -> None:
    episode_id, season_id, _scope = _ready_with_research(world, research_amount=300_000)
    outcome = world.service.write_episode(episode_id)
    assert outcome.status is not None  # the write ran

    allocation = world.row(
        "SELECT * FROM cost_allocations a JOIN budget_accounts t ON t.id = a.target_account_id "
        "WHERE t.episode_id = %s",
        (episode_id,),
    )
    assert allocation is not None, "claim-time research attribution must be booked"
    assert allocation["amount_micro_usd"] == 300_000
    assert allocation["basis"] == StoryService.RESEARCH_ALLOCATION_BASIS
    # The share is inside the episode's committed spend, so the US$10 verdict and
    # the near-cap dispatch check both see it.
    committed = world.row(
        "SELECT settled_micro_usd + accrued_micro_usd + reserved_outstanding_micro_usd AS c "
        "FROM budget_accounts WHERE episode_id = %s",
        (episode_id,),
    )["c"]
    assert committed >= 300_000


def test_attribution_is_idempotent_across_replays(world: World) -> None:
    episode_id, _season_id, _scope = _ready_with_research(world, research_amount=120_000)
    world.service.write_episode(episode_id)
    world.service.write_episode(episode_id)  # replay
    count = world.count(
        "SELECT count(*) FROM cost_allocations a JOIN budget_accounts t "
        "ON t.id = a.target_account_id WHERE t.episode_id = %s",
        (episode_id,),
    )
    assert count == 1  # one share per (source charge, episode), ever


def test_research_share_that_cannot_fit_refuses_the_dispatch(world: World) -> None:
    # A research spend larger than a small episode policy's RESEARCH allocation:
    # the share cannot fit, so the claim refuses typed before any paid dispatch.
    season_id, scope = world.season(
        scope=season_scope().model_copy(
            update={
                "cost_policy": CostPolicy(
                    allocation_micro_usd={
                        BudgetCategory.RESEARCH_SCRIPT_PROMPTS_METADATA: 50_000,
                        BudgetCategory.REFERENCES_DIALOGUE: 2_950_000,
                        BudgetCategory.GPU_GENERATION: 2_500_000,
                        BudgetCategory.QA_CAPTIONS: 1_000_000,
                        BudgetCategory.CPU_STORAGE_TRANSFER: 500_000,
                        BudgetCategory.METERED_MANAGEMENT: 1_000_000,
                        BudgetCategory.RECOVERY_HEADROOM: 2_000_000,
                    }
                )
            }
        )
    )
    with world.db.transaction() as tx:
        world.budget.open_research_account(tx, season_id=season_id, envelope_micro_usd=1_000_000)
    _research_charge(world, season_id, 400_000)
    world.service.compile_season(season_id)
    episode_id = world.episode(season_id, scope, number=1)

    with pytest.raises(BudgetExhausted):
        world.service.write_episode(episode_id)
    # Nothing was dispatched: no script row, no charge on the episode account.
    assert world.row("SELECT id FROM scripts WHERE episode_id = %s", (episode_id,)) is None
    assert (
        world.count(
            "SELECT count(*) FROM charges c JOIN budget_accounts a ON a.id = c.account_id "
            "WHERE a.episode_id = %s",
            (episode_id,),
        )
        == 0
    )
