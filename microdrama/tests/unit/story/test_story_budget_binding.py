"""Budget binding: real reservations before every paid call, typed refusals (T010)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from story_support import World

from microdrama.contracts.enums import BudgetCategory, PriceUnit, ReceiptKind
from microdrama.contracts.errors import BudgetExhausted
from microdrama.contracts.primitives import DEFAULT_LIMITS
from microdrama.story import WriteStatus
from microdrama.testing.fakes.common import synthetic_receipt


def _ready(world: World):
    season_id, scope = world.season()
    world.service.compile_season(season_id)
    episode_id = world.episode(season_id, scope)
    return episode_id


def test_every_paid_call_holds_a_real_reservation(world: World) -> None:
    episode_id = _ready(world)
    outcome = world.service.write_episode(episode_id)
    assert outcome.status is WriteStatus.CURRENT

    reservations = world.rows(
        "SELECT semantic_key, operation_kind, state, reserved_micro_usd FROM reservations "
        "WHERE episode_id = %s ORDER BY created_at, id",
        (episode_id,),
    )
    billed = [c for c in world.llm.ledger]
    assert len(reservations) >= len(billed) > 0
    assert {r["operation_kind"] for r in reservations} <= {"story.writer", "story.critic"}
    assert all(r["state"] == "SETTLED" for r in reservations)
    # Every provider receipt is linked to one of this episode's reservations.
    reservation_ids = {
        str(r["id"])
        for r in world.rows("SELECT id FROM reservations WHERE episode_id = %s", (episode_id,))
    }
    for receipt in billed:
        assert str(receipt.reservation_id) in reservation_ids
    # Settled spend equals the outcome's retained spend, and the plan worst case bounded it.
    charges = world.episode_charges(episode_id)
    assert sum(c["amount_micro_usd"] for c in charges) == outcome.settled_micro_usd
    assert world.committed(episode_id) == outcome.settled_micro_usd


def test_worst_case_that_does_not_fit_is_refused_before_dispatch(world: World) -> None:
    episode_id = _ready(world)
    # Open the episode account, then pre-settle synthetic spend so the planned story
    # worst case cannot fit under the cap (cap minus shutdown reserve).
    from microdrama.contracts.season import CostPolicy

    with world.db.transaction() as tx:
        world.budget.open_episode_account(
            tx,
            season_id=world.row("SELECT season_id FROM episodes WHERE id = %s", (episode_id,))[
                "season_id"
            ],
            episode_id=episode_id,
            policy=CostPolicy(),
        )
    worst = world.service._planned_worst_case(episode_id)  # noqa: SLF001 - lane-local probe
    near_cap = 10_000_000 - worst - 250_000 + 1  # one micro-USD over what still fits
    receipt = synthetic_receipt(
        provider="fake-llm",
        provider_receipt_id=f"presettle:{episode_id}",
        kind=ReceiptKind.SETTLEMENT,
        category=BudgetCategory.RESEARCH_SCRIPT_PROMPTS_METADATA,
        unit=PriceUnit.INPUT_TOKEN_1K,
        units=1,
        amount_micro_usd=near_cap,
        observed_at=datetime(2026, 10, 21, tzinfo=UTC),
        episode_id=episode_id,
    )
    world.budget.record_usage(receipt)

    with pytest.raises(BudgetExhausted, match="nothing is dispatched"):
        world.service.write_episode(episode_id)
    assert world.generate_calls() == 0
    assert world.count("SELECT COUNT(*) FROM scripts WHERE episode_id = %s", (episode_id,)) == 0
    # The pre-settled spend was not refunded to make room.
    assert world.committed(episode_id) == near_cap


def test_failed_spend_is_never_reset_by_a_retry(world: World) -> None:
    from microdrama.contracts.enums import RuntimeRole

    episode_id = _ready(world)
    world.llm.script_role(RuntimeRole.CRITIC, {"passed": False, "findings": []})
    first = world.service.write_episode(episode_id)
    assert first.status is WriteStatus.CRITIC_FAILED
    committed_after_failure = world.committed(episode_id)

    # A content-changing retry (write_attempt=2) runs against the SAME allowance: the
    # failed spend stays counted, and the successful pass adds to it.
    world.llm.script_role(RuntimeRole.CRITIC, {"passed": True, "findings": []})
    second = world.service.write_episode(episode_id, write_attempt=2)
    assert second.status is WriteStatus.CURRENT
    assert world.committed(episode_id) > committed_after_failure, (
        "the failed attempt's spend stayed counted; the retry added to it"
    )
    assert second.settled_micro_usd > 0
    assert (
        world.count(
            "SELECT COUNT(*) FROM charges WHERE kind = 'CREDIT' AND episode_id = %s",
            (episode_id,),
        )
        == 0
    )
    # The retry superseded the CRITIC_FAILED draft and became the current script.
    statuses = {
        row["status"]
        for row in world.rows("SELECT status FROM scripts WHERE episode_id = %s", (episode_id,))
    }
    assert statuses == {"CURRENT", "CRITIC_FAILED"}


def test_shot_durations_respect_the_fifteen_second_unit(world: World) -> None:
    episode_id = _ready(world)
    world.service.write_episode(episode_id)
    manifest = world.service.manifest(episode_id)
    limits = DEFAULT_LIMITS
    for shot in manifest.shots:
        assert shot.target_duration_ms <= limits.max_shot_duration_ms
    script = world.service.script(episode_id)
    # Every exact Thai line is bound to exactly one shot, with its speaker.
    line_ids = [lid for s in manifest.shots for lid in s.line_ids]
    all_lines = [ln.line_id for sc in script.scenes for ln in sc.lines]
    assert sorted(line_ids) == sorted(all_lines)
    for shot in manifest.shots:
        for line in shot.line_ids:
            scene_line = next(ln for sc in script.scenes for ln in sc.lines if ln.line_id == line)
            assert shot.speaker_ids == [scene_line.speaker_character_id]
