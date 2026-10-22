"""Shared attempt/round/fund limits (T019 acceptance 4).

The caps are the SAME ``ProductionLimits`` the render service anchors on (no second
source), the attempt count comes from the render service's own durable ledger, and
every refusal fires typed BEFORE any reservation or charge.
"""

from __future__ import annotations

import pytest
from qa_support import QAWorld
from repairs_support import RepairsWorld

from microdrama.contracts.enums import (
    BudgetCategory,
    FeedbackCategory,
    FeedbackScope,
    PriceUnit,
)
from microdrama.contracts.errors import BudgetExhausted
from microdrama.contracts.primitives import DEFAULT_LIMITS
from microdrama.contracts.season import CostPolicy, TimecodedFeedback
from microdrama.qa.repairs import (
    RepairRoundExceeded,
    RepairsConfig,
)
from microdrama.rendering.routing import AttemptCapReached, RoutingPolicy
from microdrama.testing.fakes import fake_price_quote

pytestmark = pytest.mark.db


@pytest.fixture
def world(qa_world: QAWorld) -> RepairsWorld:
    return RepairsWorld(qa_world.db, qa_world.store, qa_world.settings, qa_world.truth)


def _shot_feedback(world: RepairsWorld, episode_id) -> None:
    world.revise_feedback(
        episode_id,
        [
            TimecodedFeedback(
                category=FeedbackCategory.CONTINUITY_PROPS,
                start_ms=0,
                end_ms=1_000,
                shot_id="sh1",
                comment="prop continuity broke",
                scope=FeedbackScope.SHOT,
            )
        ],
    )


def test_shot_repair_past_the_attempt_cap_is_refused_before_any_spend(
    world: RepairsWorld,
) -> None:
    episode_id, *_ = world.episode_with_tracks()
    _shot_feedback(world, episode_id)
    # three attempts already sit in the render service's OWN durable ledger
    world.render_attempt_jobs(episode_number=1, shot_id="sh1", attempts=3)
    approval = world.rows(
        "SELECT id FROM approval_events WHERE entity_id = %s AND action = 'REVISE'",
        (episode_id,),
    )[0]["id"]

    with pytest.raises(AttemptCapReached) as excinfo:
        world.repairs().plan_from_feedback(episode_id, approval)
    assert excinfo.value.details["cap"] == DEFAULT_LIMITS.max_attempts_per_shot

    # nothing was spent and nothing was planned: only the typed refusal event exists
    assert world.rows("SELECT * FROM repair_plans WHERE episode_id = %s", (episode_id,)) == []
    assert world.rows("SELECT * FROM reservations") == []
    assert world.rows("SELECT * FROM charges") == []
    refused = world.rows(
        "SELECT payload FROM domain_events WHERE event_type = 'qa.repair.refused'",
    )
    assert any(r["payload"]["code"] == "ATTEMPT_CAP_REACHED" for r in refused)


def test_the_attempt_cap_is_shared_with_the_render_service(world: RepairsWorld) -> None:
    # ProductionLimits is the single source: the router's policy and the repair
    # service anchor on the same instance and the same cap value.
    router_policy = RoutingPolicy.from_limits(DEFAULT_LIMITS)
    service = world.repairs(limits=DEFAULT_LIMITS)
    assert router_policy.max_attempts_per_shot == service.limits.max_attempts_per_shot == 3
    assert service.limits.max_final_repair_rounds == DEFAULT_LIMITS.max_final_repair_rounds == 2


def test_third_automatic_repair_round_is_refused_typed(world: RepairsWorld) -> None:
    episode_id, *_ = world.episode_with_tracks(state="AI_REVIEW")
    service = world.repairs()
    for cycle in (1, 2, 3):
        world.finding(
            episode_id,
            check_id="caption.critical_term_match",
            repair_targets=["CAPTION"],
            start_ms=10_000,
            end_ms=13_000 + cycle,  # distinct content per QA cycle
            cycle=cycle,
        )
        if cycle <= 2:
            outcome = service.plan_from_findings(episode_id)
            assert outcome.plan.round_number == cycle
        else:
            with pytest.raises(RepairRoundExceeded):
                service.plan_from_findings(episode_id)
    assert (
        len(
            world.rows(
                "SELECT * FROM repair_plans WHERE episode_id = %s AND trigger = 'QA_FINDING'",
                (episode_id,),
            )
        )
        == 2
    )


def test_priced_plan_beyond_remaining_funds_is_refused_before_any_spend(
    world: RepairsWorld,
) -> None:
    episode_id, *_ = world.episode_with_tracks()
    world.finding(
        episode_id,
        check_id="caption.critical_term_match",
        repair_targets=["CAPTION"],
        start_ms=10_000,
        end_ms=13_000,
    )
    # a priced step with NO episode budget account: remaining funds are zero
    config = RepairsConfig(caption_price=fake_price_quote(PriceUnit.REQUEST))
    with pytest.raises(BudgetExhausted):
        world.repairs(config=config).plan_from_findings(episode_id)
    assert world.rows("SELECT * FROM repair_plans WHERE episode_id = %s", (episode_id,)) == []
    assert world.rows("SELECT * FROM reservations") == []
    assert world.rows("SELECT * FROM charges") == []


def test_priced_repair_holds_a_real_reservation_and_settles(world: RepairsWorld) -> None:
    episode_id, thai, english, _package = world.episode_with_tracks()
    season_row = world.row("SELECT season_id FROM episodes WHERE id = %s", (episode_id,))
    with world.db.transaction() as tx:
        world.budget.open_episode_account(
            tx,
            season_id=season_row["season_id"],
            episode_id=episode_id,
            policy=CostPolicy(),
        )
    world.finding(
        episode_id,
        check_id="caption.critical_term_match",
        repair_targets=["CAPTION"],
        start_ms=10_000,
        end_ms=13_000,
    )
    price = fake_price_quote(PriceUnit.REQUEST)
    service = world.repairs(config=RepairsConfig(caption_price=price))
    outcome = service.plan_from_findings(episode_id)
    assert outcome.plan.total_estimated_micro_usd == price.unit_price_micro_usd * 2  # 2 cues

    execution = service.execute_plan(outcome.plan.plan_id)
    assert execution.status == "COMPLETED"
    assert execution.settled_micro_usd == price.unit_price_micro_usd * 2
    (charge,) = world.rows("SELECT * FROM charges WHERE episode_id = %s", (episode_id,))
    assert charge["category"] == BudgetCategory.QA_CAPTIONS.value
    reservation = world.row(
        "SELECT * FROM reservations WHERE id = %s", (execution.steps[0].reservation_id,)
    )
    assert reservation is not None and reservation["state"] != "ACTIVE"
