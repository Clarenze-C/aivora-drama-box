"""Routed dispatch: every dispatch is paid through the T013 reserve→submit path."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from test_routing_support import GPU_SECOND_MICRO, RoutingWorld, shot

from microdrama.contracts.cost import RenderRequest
from microdrama.contracts.enums import (
    BudgetCategory,
    ControlKind,
    ProviderOperationState,
    ShotPattern,
)
from microdrama.contracts.errors import PolicyDenied
from microdrama.core.jobs import JobService
from microdrama.persistence import Database
from microdrama.rendering.comfy_jobs import RENDER_OPERATION_KIND
from microdrama.rendering.presets import PresetCatalog
from microdrama.rendering.routing import (
    ROUTE_DECISION_EVENT,
    dispatch_routed_attempt,
    route_id_for,
)
from microdrama.rendering.workflows import PRESET_TEMPLATES, template_sha256

pytestmark = [pytest.mark.db, pytest.mark.ffmpeg]


@pytest.fixture
def world(db: Database, tmp_path: Path) -> RoutingWorld:
    return RoutingWorld(db, tmp_path / "store")


def _route(world: RoutingWorld, episode):
    reference_shot = shot(
        pattern=ShotPattern.PRACTICAL_PROP_ACTION,
        controls=(ControlKind.TEXT_PROMPT, ControlKind.CHARACTER_REFERENCE),
    )
    decision = world.router.route_shot(
        reference_shot, episode_id=episode.episode_id, manifest_version=1
    )
    assert decision.chosen is not None
    return decision, reference_shot


def _dispatch(world: RoutingWorld, episode, decision, reference_shot):
    return dispatch_routed_attempt(
        world.db,
        world.service,
        world.jobs,
        decision=decision,
        shot=reference_shot,
        catalog=world.catalog,
        episode_number=1,
        reference_asset_ids=world.seed_reference_assets(count=1),
        identity_lock_id=None,
        prompt_text="Fon counts the day's earnings at the stall.",
    )


def test_every_routed_dispatch_is_paid_before_the_prompt_is_queued(
    world: RoutingWorld,
) -> None:
    """Acceptance: every routed render that dispatches goes through reserve→submit."""
    world.seed_presets()
    episode = world.episode()
    decision, reference_shot = _route(world, episode)
    routed = _dispatch(world, episode, decision, reference_shot)

    # the paid path: a comfy reservation exists, belongs to this attempt, and the
    # operation linked to it was submitted through the ordinary adapter
    reservation = world.reservation_row(routed.request.reservation_id)
    assert reservation["operation_kind"] == RENDER_OPERATION_KIND
    assert reservation["category"] == BudgetCategory.GPU_GENERATION.value
    assert reservation["semantic_key"] == routed.request.semantic_key
    assert reservation["reserved_micro_usd"] > 0  # never free
    operation = world.operation_for(routed.request.reservation_id)
    assert operation["state"] == ProviderOperationState.SUBMITTED.value
    assert operation["external_id"] in world.server.submissions
    assert operation["reservation_id"] == routed.request.reservation_id
    assert operation["job_id"] == routed.job_id
    # the durable job input IS the request of record
    job = world.job_row(routed.job_id)
    assert RenderRequest.model_validate(job["input"]) == routed.request


def test_the_routed_request_pins_the_chosen_templates_workflow(world: RoutingWorld) -> None:
    world.seed_presets()
    episode = world.episode()
    decision, reference_shot = _route(world, episode)
    routed = dispatch_routed_attempt(
        world.db,
        world.service,
        world.jobs,
        decision=decision,
        shot=reference_shot,
        catalog=world.catalog,
        episode_number=1,
        reference_asset_ids=world.seed_reference_assets(count=1),
        identity_lock_id=None,
        prompt_text="Fon counts the day's earnings at the stall.",
        submit=False,
    )
    assert decision.chosen is not None
    template = PRESET_TEMPLATES[decision.chosen.preset_id]
    assert routed.request.workflow_sha256 == template_sha256(template)
    assert routed.request.preset_id == decision.chosen.preset_id
    # the semantic key follows the ordinary house pattern
    assert routed.request.semantic_key == "render.shot:ep1:sh1:attempt1"
    assert world.server.submissions == []  # submit=False never queues anything


def test_a_routed_dispatch_survives_a_replay_without_a_second_prompt(
    world: RoutingWorld,
) -> None:
    world.seed_presets()
    episode = world.episode()
    decision, reference_shot = _route(world, episode)
    references = world.seed_reference_assets(count=1)
    kwargs = dict(
        decision=decision,
        shot=reference_shot,
        catalog=world.catalog,
        episode_number=1,
        reference_asset_ids=references,
        identity_lock_id=None,
        prompt_text="Fon counts the day's earnings at the stall.",
    )
    first = dispatch_routed_attempt(world.db, world.service, world.jobs, **kwargs)
    second = dispatch_routed_attempt(world.db, world.service, world.jobs, **kwargs)
    assert second.request == first.request
    assert second.job_id == first.job_id
    assert len(world.server.submissions) == 1  # exactly one prompt ever queued
    assert len(world.operation_rows()) == 1


def test_a_completed_routed_attempt_settles_its_observed_cost(world: RoutingWorld) -> None:
    world.seed_presets()
    episode = world.episode()
    decision, reference_shot = _route(world, episode)
    routed = _dispatch(world, episode, decision, reference_shot)
    operation_id = world.operation_for(routed.request.reservation_id)["id"]
    world.clock.advance(seconds=5)
    status = world.service.poll(operation_id)
    assert status.state is ProviderOperationState.SUCCEEDED
    assert status.assets  # verified durable output
    assert status.settled_micro_usd == GPU_SECOND_MICRO * 5


def test_a_decision_without_a_choice_cannot_dispatch(world: RoutingWorld) -> None:
    world.seed_presets()
    episode = world.episode()
    decision, reference_shot = _route(world, episode)
    empty = dataclasses.replace(decision, chosen=None)
    with pytest.raises(PolicyDenied):
        dispatch_routed_attempt(
            world.db,
            world.service,
            world.jobs,
            decision=empty,
            shot=reference_shot,
            catalog=world.catalog,
            episode_number=1,
            reference_asset_ids=world.seed_reference_assets(count=1),
            identity_lock_id=None,
            prompt_text="never dispatched",
        )
    assert world.server.submissions == []
    assert world.operation_rows() == []


def test_routing_decisions_are_durable_rows_not_logs(world: RoutingWorld) -> None:
    """A fresh process over the same database reads the same decisions and jobs."""
    world.seed_presets()
    episode = world.episode()
    decision, reference_shot = _route(world, episode)
    routed = _dispatch(world, episode, decision, reference_shot)

    with world.db.transaction(readonly=True) as tx:
        rows = tx.fetchall(
            "SELECT * FROM domain_events WHERE event_type = %s ORDER BY global_position",
            (ROUTE_DECISION_EVENT,),
        )
    assert len(rows) == 1
    event = rows[0]
    assert event["aggregate_id"] == route_id_for(episode.episode_id, "sh1", 1)
    payload = event["payload"]
    assert payload["shot_id"] == "sh1"
    assert decision.chosen is not None
    assert payload["chosen"]["preset_id"] == decision.chosen.preset_id

    # "restart": fresh catalog/job service over the same durable state see it all
    fresh_catalog = PresetCatalog(world.db, world.registry)
    assert fresh_catalog.mapped_ids() == tuple(sorted(PRESET_TEMPLATES))
    JobService(world.db, world.clock, world.ids)  # constructs cleanly on the same state
    with world.db.transaction(readonly=True) as tx:
        job_row = tx.fetchone("SELECT * FROM jobs WHERE id = %s", (routed.job_id,))
    assert job_row is not None
    assert RenderRequest.model_validate(job_row["input"]) == routed.request
