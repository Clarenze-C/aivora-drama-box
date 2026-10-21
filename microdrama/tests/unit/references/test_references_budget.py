"""T011 budget binding: real reservations, prospective fit, kept charges, typed unknowns."""

from __future__ import annotations

import pytest
from references_support import SCENE_1_LINES, SCENE_2_LINES

from microdrama.contracts.enums import BudgetCategory, QueueName
from microdrama.contracts.errors import BudgetExhausted, ProviderError, RightsUncleared
from microdrama.contracts.season import CostPolicy
from microdrama.references import PrepareStatus, ReferencesConfig
from microdrama.testing.fakes import GenerationScenario
from microdrama.testing.fakes.generation import voice_duration_ms


def test_every_paid_call_holds_a_real_reservation(world):
    season_id, scope = world.season()
    episode_id = world.episode(season_id, scope)
    world.seed_script_and_manifest(episode_id=episode_id, scope=scope)
    outcome = world.service.prepare_episode(episode_id)
    assert outcome.status is PrepareStatus.CURRENT
    reservations = world.rows(
        "SELECT id, category, operation_kind, reserved_micro_usd FROM reservations "
        "WHERE episode_id = %s",
        (episode_id,),
    )
    # 9 image anchors (GPU-bounded) + 3 voice anchors + 6 dialogue lines.
    assert len(reservations) == 18
    gpu = [r for r in reservations if r["category"] == BudgetCategory.GPU_GENERATION.value]
    refs = [r for r in reservations if r["category"] == BudgetCategory.REFERENCES_DIALOGUE.value]
    assert len(gpu) == 9 and len(refs) == 9
    assert all(r["reserved_micro_usd"] > 0 for r in reservations)
    # Every settled charge links back to one of these reservations (no orphan spend).
    charges = world.rows(
        "SELECT reservation_id, amount_micro_usd FROM charges WHERE episode_id = %s",
        (episode_id,),
    )
    assert charges and all(c["reservation_id"] is not None for c in charges)
    assert {c["reservation_id"] for c in charges} <= {r["id"] for r in reservations}
    settled = sum(c["amount_micro_usd"] for c in charges)
    assert settled == outcome.settled_micro_usd > 0
    # The GPU-bounded holds carry the provider's IMAGE-unit receipts (forced pairing).
    gpu_units = world.rows(
        "SELECT c.unit FROM charges c JOIN reservations r ON r.id = c.reservation_id "
        "WHERE c.episode_id = %s AND r.category = 'GPU_GENERATION'",
        (episode_id,),
    )
    assert {u["unit"] for u in gpu_units} == {"IMAGE"}


def _tiny_cap_scope():
    from microdrama.contracts.examples import season_scope

    return season_scope().model_copy(
        update={
            "cost_policy": CostPolicy(
                episode_cap_micro_usd=300_000,
                allocation_micro_usd={
                    BudgetCategory.RESEARCH_SCRIPT_PROMPTS_METADATA: 40_000,
                    BudgetCategory.REFERENCES_DIALOGUE: 40_000,
                    BudgetCategory.GPU_GENERATION: 60_000,
                    BudgetCategory.QA_CAPTIONS: 20_000,
                    BudgetCategory.CPU_STORAGE_TRANSFER: 20_000,
                    BudgetCategory.METERED_MANAGEMENT: 20_000,
                    BudgetCategory.RECOVERY_HEADROOM: 100_000,
                },
                shutdown_reserve_micro_usd=30_000,
            )
        }
    )


def test_worst_case_that_does_not_fit_is_refused_before_dispatch(world):
    scope = _tiny_cap_scope()
    season_id, scope = world.season(scope=scope)
    episode_id = world.episode(season_id, scope)
    world.seed_script_and_manifest(episode_id=episode_id, scope=scope)
    with pytest.raises(BudgetExhausted):
        world.service.prepare_episode(episode_id)
    # Refused prospectively: nothing dispatched, nothing held, nothing claimed.
    assert [c for c in world.image.calls if c.method == "submit"] == []
    assert (
        world.count("SELECT COUNT(*) FROM reservations WHERE episode_id = %s", (episode_id,)) == 0
    )
    assert world.episode_state(episode_id) == "SCRIPTING"
    assert (
        world.row("SELECT correlation_id FROM episodes WHERE id = %s", (episode_id,))[
            "correlation_id"
        ]
        is None
    )


def test_unknown_price_blocks_dispatch_typed_with_zero_spend(world):
    from microdrama.references import build_references_service

    season_id, scope = world.season()
    episode_id = world.episode(season_id, scope)
    world.seed_script_and_manifest(episode_id=episode_id, scope=scope)
    unpriced = build_references_service(
        world.db,
        world.clock,
        world.ids,
        world.settings,
        budget=world.budget,
        store=world.store,
        image_provider=world.image,
        voice_provider=world.voice,
        rights=world.rights,
        config=ReferencesConfig(),
    )
    outcome = unpriced.prepare_episode(episode_id)
    assert outcome.status is PrepareStatus.NOT_DISPATCHED
    assert outcome.settled_micro_usd == 0
    assert outcome.uncertainty_notes
    assert [c for c in world.image.calls if c.method == "submit"] == []
    assert [c for c in world.voice.calls if c.method == "submit"] == []
    assert (
        world.count("SELECT COUNT(*) FROM reservations WHERE episode_id = %s", (episode_id,)) == 0
    )
    # The episode was left claimable: the priced service succeeds afterwards.
    priced = world.service.prepare_episode(episode_id)
    assert priced.status is PrepareStatus.CURRENT


def test_no_rights_route_blocks_the_provider_not_a_fabricated_licence(world):
    from microdrama.references import build_references_service

    season_id, scope = world.season()
    episode_id = world.episode(season_id, scope)
    world.seed_script_and_manifest(episode_id=episode_id, scope=scope)
    unrouted = build_references_service(
        world.db,
        world.clock,
        world.ids,
        world.settings,
        budget=world.budget,
        store=world.store,
        image_provider=world.image,
        voice_provider=world.voice,
        rights=None,  # no registry: the route is unknown, fail closed
    )
    with pytest.raises(RightsUncleared):
        unrouted.prepare_episode(episode_id)
    assert (
        world.count("SELECT COUNT(*) FROM reference_versions WHERE season_id = %s", (season_id,))
        == 0
    )
    # A licence hash was never invented: no license rows, no charges.
    assert world.count("SELECT COUNT(*) FROM charges WHERE episode_id = %s", (episode_id,)) == 0


def test_denied_rights_fails_typed_and_releases_the_unbilled_hold(world):
    season_id, scope = world.season()
    episode_id = world.episode(season_id, scope)
    world.seed_script_and_manifest(episode_id=episode_id, scope=scope)
    world.image.queue_scenarios(*[GenerationScenario.DENIED_RIGHTS] * 12)
    with pytest.raises(RightsUncleared):
        world.service.prepare_episode(episode_id)
    released = world.rows("SELECT state FROM reservations WHERE episode_id = %s", (episode_id,))
    assert released and all(r["state"] == "RELEASED" for r in released)
    assert world.count("SELECT COUNT(*) FROM charges WHERE episode_id = %s", (episode_id,)) == 0


def test_partial_output_keeps_the_charge_and_fails_typed(world):
    season_id, scope = world.season()
    episode_id = world.episode(season_id, scope)
    world.seed_script_and_manifest(episode_id=episode_id, scope=scope)
    world.image.queue_scenarios(
        GenerationScenario.HAPPY,
        GenerationScenario.PARTIAL_OUTPUT,
        *[GenerationScenario.HAPPY] * 10,
    )
    with pytest.raises(ProviderError):
        world.service.prepare_episode(episode_id)
    charges = world.rows(
        "SELECT amount_micro_usd FROM charges WHERE episode_id = %s", (episode_id,)
    )
    assert charges  # the billed-but-unusable attempt keeps its spend (MD-008)
    events = world.events(episode_id, "references.prepare_failed")
    assert events and events[0]["error_code"] == "PROVIDER_ERROR"


def test_failed_attempt_does_not_reset_the_allowance(world):
    season_id, scope = world.season()
    episode_id = world.episode(season_id, scope)
    world.seed_script_and_manifest(episode_id=episode_id, scope=scope)
    # One scripted refusal; the queue's default (HAPPY) takes over afterwards.
    world.image.queue_scenarios(GenerationScenario.DENIED_RIGHTS)
    with pytest.raises(RightsUncleared):
        world.service.prepare_episode(episode_id)
    # A retry against the SAME allowance succeeds once the route is healthy; the
    # earlier refused attempt neither refunded nor relabelled anything.
    outcome = world.service.prepare_episode(episode_id)
    assert outcome.status is PrepareStatus.CURRENT
    committed = world.row(
        "SELECT reserved_outstanding_micro_usd + accrued_micro_usd + settled_micro_usd "
        "AS committed FROM budget_accounts WHERE episode_id = %s",
        (episode_id,),
    )["committed"]
    assert committed == outcome.settled_micro_usd


def test_voice_lines_settle_at_character_pricing_with_actual_durations(world):
    season_id, scope = world.season()
    episode_id = world.episode(season_id, scope)
    world.seed_script_and_manifest(episode_id=episode_id, scope=scope)
    outcome = world.service.prepare_episode(episode_id)
    line_charges = world.rows(
        "SELECT r.semantic_key, c.unit, c.amount_micro_usd FROM charges c "
        "JOIN reservations r ON r.id = c.reservation_id "
        "WHERE c.episode_id = %s AND r.operation_kind = 'references.voice_line'",
        (episode_id,),
    )
    assert len(line_charges) == 6
    assert all(c["unit"] == "CHARACTER_1K" for c in line_charges)
    texts = {lid: t for lid, _s, t in [*SCENE_1_LINES, *SCENE_2_LINES]}
    for audio in outcome.lines:
        assert audio.actual_duration_ms == voice_duration_ms(texts[audio.line_id])


def test_reservations_live_on_the_episode_account_in_production_queue(world):
    season_id, scope = world.season()
    episode_id = world.episode(season_id, scope)
    world.seed_script_and_manifest(episode_id=episode_id, scope=scope)
    world.service.prepare_episode(episode_id)
    rows = world.rows(
        "SELECT r.queue, r.provider, a.scope_kind FROM reservations r "
        "JOIN budget_accounts a ON a.id = r.account_id WHERE r.episode_id = %s",
        (episode_id,),
    )
    assert rows and all(
        r["queue"] == QueueName.PRODUCTION.value and r["scope_kind"] == "EPISODE" for r in rows
    )
    assert all(r["provider"] == "fake-generation" for r in rows)
