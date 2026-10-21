"""The bounded writer/critic loop: rewrites, IMP-02 termination, typed no-pass (T010)."""

from __future__ import annotations

from story_support import World

from microdrama.contracts.enums import RuntimeRole
from microdrama.story import (
    StoryConfig,
    WriteStatus,
    build_story_service,
    critic_client_token,
)
from microdrama.testing.fakes import LLMScenario


def _ready(world: World):
    season_id, scope = world.season()
    world.service.compile_season(season_id)
    episode_id = world.episode(season_id, scope)
    return episode_id


def test_critic_failure_then_rewrite_success(world: World) -> None:
    """Round 0 the critic fails; round 1 passes: the rewrite rescued the episode."""
    episode_id = _ready(world)
    token = critic_client_token(episode_id, 0)
    world.llm.script_token(
        token,
        {
            "passed": False,
            "findings": [{"code": " pacing", "severity": "REPAIRABLE", "detail": "scene 2 drags"}],
        },
    )
    outcome = world.service.write_episode(episode_id)

    assert outcome.status is WriteStatus.CURRENT
    assert outcome.rounds_used == 2
    # Both rounds billed: two writers + two critics.
    assert len([c for c in world.llm.calls]) == 4
    assert outcome.settled_micro_usd > 0
    assert world.service.script(episode_id).version == 1


def test_critic_failure_terminates_at_limit_and_keeps_spend(world: World) -> None:
    episode_id = _ready(world)
    world.llm.script_role(
        RuntimeRole.CRITIC,
        {
            "passed": False,
            "findings": [
                {"code": "canon-mismatch", "severity": "BLOCKED", "detail": "wrong baht amount"}
            ],
        },
    )
    outcome = world.service.write_episode(episode_id)

    assert outcome.status is WriteStatus.CRITIC_FAILED
    assert outcome.rounds_used == world.service.config.max_rewrite_rounds + 1
    assert outcome.settled_micro_usd > 0, "failed critic rounds keep their spend (MD-008)"
    # The spend is retained on the episode account; no credits were invented.
    assert world.committed(episode_id) == outcome.settled_micro_usd
    assert (
        world.count(
            "SELECT COUNT(*) FROM charges WHERE kind = 'CREDIT' AND episode_id = %s",
            (episode_id,),
        )
        == 0
    )
    # The failing draft is persisted as a typed CRITIC_FAILED script row.
    row = world.row("SELECT status FROM scripts WHERE episode_id = %s", (episode_id,))
    assert row["status"] == "CRITIC_FAILED"
    events = world.events(episode_id, "story.script_failed")
    assert events and events[-1]["status"] == "CRITIC_FAILED"
    # Terminal failure released the claim: an ordinary retry may run (same allowance).
    assert (
        world.row("SELECT correlation_id FROM episodes WHERE id = %s", (episode_id,))[
            "correlation_id"
        ]
        is None
    )


def test_unknown_speaker_in_synthesized_output_is_blocked(world: World) -> None:
    """A fresh fake (no writer scripting) synthesizes a draft whose speaker is not an
    approved character: the deterministic critic blocks it every round; never a pass."""
    episode_id = _ready(world)
    from microdrama.testing.fakes import FakeLLMProvider, SequentialIds

    fresh = FakeLLMProvider(clock=world.clock, ids=SequentialIds("story-unscripted"))
    fresh.script_role(RuntimeRole.CRITIC, {"passed": True, "findings": []})
    unscripted = build_story_service(
        world.db,
        world.clock,
        world.ids,
        world.settings,
        budget=world.budget,
        llm=fresh,
    )
    outcome = unscripted.write_episode(episode_id)

    assert outcome.status is WriteStatus.CRITIC_FAILED
    assert any(f.code == "unknown-speaker" for f in outcome.findings)
    assert outcome.settled_micro_usd > 0


def test_malformed_writer_output_consumes_attempts(world: World) -> None:
    episode_id = _ready(world)
    world.llm.queue_scenarios(
        LLMScenario.MALFORMED_OUTPUT, LLMScenario.MALFORMED_OUTPUT
    )  # round 0, attempts 1-2
    outcome = world.service.write_episode(episode_id)

    assert outcome.status is WriteStatus.WRITER_FAILED
    # Both attempts billed an invalid output: the spend is retained.
    assert outcome.settled_micro_usd > 0
    writer_calls = [c for c in world.llm.calls if c.key.startswith(f"story:{episode_id}:w")]
    assert len(writer_calls) == 2
    assert world.events(episode_id, "story.script_failed")


def test_unbilled_transport_failures_release_reservations(world: World) -> None:
    episode_id = _ready(world)
    # Round 0 attempt 1 (2 transports) + attempt 2 (2 transports): all time out unbilled.
    world.llm.queue_scenarios(*([LLMScenario.TRANSIENT_TIMEOUT] * 4))
    outcome = world.service.write_episode(episode_id)

    assert outcome.status is WriteStatus.WRITER_FAILED
    assert outcome.settled_micro_usd == 0, "nothing billed, nothing retained"
    states = {
        row["state"]
        for row in world.rows("SELECT state FROM reservations WHERE episode_id = %s", (episode_id,))
    }
    assert states == {"RELEASED"}, "unbilled holds were released"


def test_invalid_critic_output_is_a_typed_no_pass(world: World) -> None:
    episode_id = _ready(world)
    # The critic emits a structurally invalid verdict on every round.
    world.llm.script_role(RuntimeRole.CRITIC, {"findings": [], "note": "no passed field"})
    outcome = world.service.write_episode(episode_id)

    assert outcome.status is WriteStatus.CRITIC_FAILED
    assert any(f.code == "critic-output-invalid" for f in outcome.findings)
    assert outcome.settled_micro_usd > 0


def test_critic_blocked_finding_prevents_pass_despite_writer_quality(world: World) -> None:
    episode_id = _ready(world)
    world.llm.script_role(
        RuntimeRole.CRITIC,
        {
            "passed": True,
            "findings": [
                {"code": "negation-flip", "severity": "BLOCKED", "detail": "missing ไม่ใช่"}
            ],
        },
    )
    outcome = world.service.write_episode(episode_id)
    # A green critic "passed" cannot smuggle its own BLOCKED finding through.
    assert outcome.status is WriteStatus.CRITIC_FAILED


def test_no_configured_price_blocks_dispatch_typed(world: World) -> None:
    season_id, scope = world.season()
    world.service.compile_season(season_id)
    episode_id = world.episode(season_id, scope)
    unpriced = build_story_service(
        world.db,
        world.clock,
        world.ids,
        world.settings,
        budget=world.budget,
        llm=world.llm,
        config=StoryConfig(),  # no prices: unknown price blocks paid dispatch
    )
    outcome = unpriced.write_episode(episode_id)

    assert outcome.status is WriteStatus.NOT_DISPATCHED
    assert outcome.settled_micro_usd == 0
    assert world.generate_calls() == 0
    assert (
        world.count("SELECT COUNT(*) FROM reservations WHERE episode_id = %s", (episode_id,)) == 0
    )
    assert any("no configured writer/critic price" in n for n in outcome.uncertainty_notes)
    # The claim was released, so a configured retry can proceed later.
    assert (
        world.row("SELECT correlation_id FROM episodes WHERE id = %s", (episode_id,))[
            "correlation_id"
        ]
        is None
    )
    assert world.row("SELECT state FROM episodes WHERE id = %s", (episode_id,))["state"] == (
        "SCRIPTING"
    )
