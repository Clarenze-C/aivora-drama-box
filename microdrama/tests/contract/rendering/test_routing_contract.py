"""Contract pins for shot routing (T014).

Freezes the interfaces other lanes (T019 repairs, T031 qualification) build against:
the preset→template mapping routing consumes, the pinned mock template hash routed
requests must carry, the operation kind/provider of every routed dispatch (frozen
contract example), and the durability of routing decisions/benchmark receipts across
a process restart (rows in the T004 outbox, not logs).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_routing_support import RoutingWorld, shot

from microdrama.contracts.cost import RenderRequest
from microdrama.contracts.enums import ControlKind, ShotPattern
from microdrama.contracts.examples import provider_operation
from microdrama.persistence import Database
from microdrama.rendering.comfy_jobs import RENDER_OPERATION_KIND
from microdrama.rendering.presets_benchmark import (
    BENCHMARK_RECEIPT_EVENT,
    default_benchmark_matrix,
)
from microdrama.rendering.routing import (
    ROUTE_DECISION_EVENT,
    dispatch_routed_attempt,
)
from microdrama.rendering.workflows import (
    MOCK_VIDEO_TEMPLATE,
    PRESET_TEMPLATES,
    bind_workflow,
    template_sha256,
)

#: The consumed mapping: routing may only dispatch presets T013 mapped. Adding an
#: entry is a conscious T013 change (handoff proposal), never a local one.
PINNED_PRESET_TEMPLATE_KEYS = ("fake-fast-4step", "fake-quality-8step")

pytestmark = [pytest.mark.db, pytest.mark.ffmpeg]


@pytest.fixture
def world(db: Database, tmp_path: Path) -> RoutingWorld:
    return RoutingWorld(db, tmp_path / "store")


def test_the_consumed_preset_mapping_is_pinned() -> None:
    assert tuple(sorted(PRESET_TEMPLATES)) == PINNED_PRESET_TEMPLATE_KEYS
    assert PRESET_TEMPLATES["fake-quality-8step"] is MOCK_VIDEO_TEMPLATE


def test_every_routed_dispatch_matches_the_frozen_operation_contract(
    world: RoutingWorld,
) -> None:
    """Routed dispatches ride the same comfy.queue_prompt/fake-comfy contract pin."""
    world.seed_presets()
    episode = world.episode()
    reference_shot = shot(
        pattern=ShotPattern.PRACTICAL_PROP_ACTION,
        controls=(ControlKind.TEXT_PROMPT, ControlKind.CHARACTER_REFERENCE),
    )
    decision = world.router.route_shot(
        reference_shot, episode_id=episode.episode_id, manifest_version=1
    )
    assert decision.chosen is not None
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
        prompt_text="Contract pin probe.",
    )
    example = provider_operation()
    operation = world.operation_for(routed.request.reservation_id)
    assert operation["operation_kind"] == RENDER_OPERATION_KIND == example.operation_kind
    assert operation["provider"] == example.provider == "fake-comfy"
    assert operation["external_id"] is not None  # prompt id persisted like the example


def test_a_routing_built_request_binds_through_the_pinned_template(
    world: RoutingWorld,
) -> None:
    world.seed_presets()
    episode = world.episode()
    reference_shot = shot(
        pattern=ShotPattern.PRACTICAL_PROP_ACTION,
        controls=(ControlKind.TEXT_PROMPT, ControlKind.CHARACTER_REFERENCE),
    )
    decision = world.router.route_shot(
        reference_shot, episode_id=episode.episode_id, manifest_version=1
    )
    assert decision.chosen is not None
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
        prompt_text="Contract pin probe.",
        submit=False,
    )
    assert isinstance(routed.request, RenderRequest)
    bound = bind_workflow(MOCK_VIDEO_TEMPLATE, routed.request)
    assert bound.workflow_sha256 == template_sha256(MOCK_VIDEO_TEMPLATE)
    assert routed.request.workflow_sha256 == bound.workflow_sha256


def test_decisions_and_receipts_survive_a_restart_as_outbox_rows(
    world: RoutingWorld,
) -> None:
    """Durability contract: a fresh process reads routing decisions and benchmark
    receipts from the durable outbox — they are rows, never logs."""
    from test_routing_support import standard_catalog_presets

    # the standard catalog (routing can decide) plus a disabled stub for the
    # benchmark to measure: the stub's id must differ from any enabled preset so
    # the benchmark's re-record (disabled) cannot disturb routing
    world.seed_presets(standard_catalog_presets())
    episode = world.episode()
    references = world.seed_reference_assets(count=1)
    # route first (while the quality preset is still enabled), then benchmark: the
    # benchmark re-records the preset disabled, but the earlier decision stays durable
    reference_shot = shot(controls=(ControlKind.TEXT_PROMPT, ControlKind.CHARACTER_REFERENCE))
    routed_decision = world.router.route_shot(
        reference_shot, episode_id=episode.episode_id, manifest_version=1
    )
    assert routed_decision.chosen is not None
    receipt = world.benchmark.run(
        "fake-quality-8step",
        episode_id=episode.episode_id,
        matrix=default_benchmark_matrix(references)[:1],
        samples_per_class=1,
    )

    # a "restarted" process: fresh world objects over the same database
    restarted = RoutingWorld(world.db, Path(f"{world.store.root}-restart"))
    with restarted.db.transaction(readonly=True) as tx:
        decisions = tx.fetchall(
            "SELECT * FROM domain_events WHERE event_type = %s", (ROUTE_DECISION_EVENT,)
        )
        receipts = tx.fetchall(
            "SELECT * FROM domain_events WHERE event_type = %s", (BENCHMARK_RECEIPT_EVENT,)
        )
    assert len(decisions) >= 1  # the benchmark samples' decisions + the routed one
    assert len(receipts) == 1
    assert receipts[0]["event_id"] == receipt.event_id
    assert receipts[0]["aggregate_type"] == "render_benchmark"
    assert decisions[0]["aggregate_type"] == "render_routing"
