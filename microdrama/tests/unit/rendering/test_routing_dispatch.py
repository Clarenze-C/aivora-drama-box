"""Routed dispatch: every dispatch is paid through the T013 reserve→submit path."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_routing_support import GPU_SECOND_MICRO, RoutingWorld, shot

from microdrama.contracts.cost import RenderRequest
from microdrama.contracts.enums import (
    BudgetCategory,
    ControlKind,
    ProviderOperationState,
    ShotPattern,
)
from microdrama.contracts.errors import PolicyDenied, SchemaInvalid
from microdrama.contracts.examples import (
    season_scope,
    v2_binding_example,
    v2_outfit,
    v2_prompt_manifest,
    v2_prop_sheet,
    v2_reference_binding,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.v2 import PromptManifest, ReferenceRole, read_v1_manifest
from microdrama.core.jobs import JobService
from microdrama.persistence import Database
from microdrama.rendering.comfy_jobs import RENDER_OPERATION_KIND
from microdrama.rendering.presets import PresetCatalog
from microdrama.rendering.routing import (
    ROUTE_DECISION_EVENT,
    RouterShotDispatch,
    dispatch_routed_attempt,
    route_id_for,
)
from microdrama.rendering.workflows import PRESET_TEMPLATES, template_sha256
from microdrama.story.compiler import compile_episode
from microdrama.story.models import BibleFact, FactKind, SeasonBible
from microdrama.story.service import parse_writer_draft

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


def test_composed_writer_props_bind_exactly_before_reservation_and_retry_normally(
    world: RoutingWorld,
) -> None:
    """Writer staging survives the typed prop preflight and ordinary retry path."""
    world.seed_presets()
    episode = world.episode()
    scope = season_scope()
    raw = {
        "scenes": [
            {
                "location_id": "stall",
                "summary": "Fon opens the ledger at the stall.",
                "staging": {"prop_ids": ["ledger"]},
                "lines": [
                    {
                        "speaker_character_id": "fon",
                        "text_th": "สมุดเล่มนี้ค่ะ",
                        "text_en": "This is the ledger.",
                        "staging": {"prop_ids": ["ledger"]},
                    },
                    {
                        "speaker_character_id": "lek",
                        "text_th": "ใช่แล้ว",
                        "text_en": "That's right.",
                    },
                ],
            }
        ]
    }
    draft = parse_writer_draft(raw)
    bible = SeasonBible(
        bible_id=uuid4(),
        season_id=scope.season_id,
        scope_version=scope.scope_version,
        approved_scope_hash=canonical_hash(scope),
        canon_version=1,
        title_th=scope.title_th,
        title_en=scope.title_en,
        logline=scope.logline,
        premise=scope.premise,
        characters=scope.characters,
        arc=scope.arc,
        facts=[
            BibleFact(
                fact_key="episode-1-debt",
                kind=FactKind.ARC_BEAT,
                statement="Fon finds the hidden debt.",
                source_field="arc[0]",
                episode_number=1,
            )
        ],
        playbook_version="fixture-v1",
        compiled_at=datetime(2026, 10, 30, tzinfo=UTC),
    )
    _plan, _script, manifest, _simplifications, _notes = compile_episode(
        draft=draft,
        scope=scope,
        bible=bible,
        episode_id=episode.episode_id,
        episode_number=1,
        script_id=uuid4(),
        manifest_id=uuid4(),
        script_version=1,
        manifest_version=1,
        identity_lock_id=None,
        supported_controls=frozenset(ControlKind),
    )
    establishing = next(shot for shot in manifest.shots if not shot.line_ids)
    dialogue = next(shot for shot in manifest.shots if shot.line_ids)
    assert establishing.prop_ids == dialogue.prop_ids == ["ledger"]
    assert establishing.outfit_ids == dialogue.outfit_ids == []

    prop = v2_prop_sheet()
    now = datetime(2026, 10, 30, tzinfo=UTC)
    identity = v2_binding_example()
    outfit = v2_outfit()

    def prompt_for(manifest_shot):
        template = v2_prompt_manifest()

        def exact_binding(role, subject_id, asset_id, asset_version, asset_hash):
            sample = v2_reference_binding(role, subject_id, "asset-placeholder", "hash-placeholder")
            return type(sample).seal(
                **{
                    **sample.model_dump(mode="python"),
                    "asset_id": asset_id,
                    "asset_version": asset_version,
                    "asset_sha256": asset_hash,
                }
            )

        prop_binding = exact_binding(
            ReferenceRole.PROP, "ledger", prop.asset_id, prop.asset_version, prop.asset_sha256
        )
        outfit_binding = exact_binding(
            ReferenceRole.OUTFIT, "fon", outfit.asset_id, outfit.asset_version, outfit.asset_sha256
        )
        location_binding = exact_binding(
            ReferenceRole.LOCATION,
            "stall",
            uuid4(),
            1,
            v2_reference_binding(ReferenceRole.LOCATION, "stall", "x", "stall-image").asset_sha256,
        )
        return PromptManifest.seal(
            **{
                **template.model_dump(mode="python"),
                "episode_id": episode.episode_id,
                "shot_id": manifest_shot.shot_id,
                "shot_sequence": manifest_shot.sequence,
                "shot_duration_ms": manifest_shot.target_duration_ms,
                "prompt_text": f"{manifest_shot.purpose} Keep the ledger visible.",
                "bindings": [
                    identity,
                    outfit_binding,
                    location_binding,
                    prop_binding,
                ],
                "source_hashes": [
                    identity.asset_sha256,
                    outfit.asset_sha256,
                    location_binding.asset_sha256,
                    prop.asset_sha256,
                ],
            }
        )

    baseline_refs = world.seed_reference_assets(count=1)
    packets = []

    def reservation_count() -> int:
        with world.db.transaction(readonly=True) as tx:
            row = tx.fetchone(
                "SELECT COUNT(*) AS n FROM reservations WHERE episode_id = %s",
                (episode.episode_id,),
            )
        return int(row["n"])

    for manifest_shot in (establishing, dialogue):
        prompt = prompt_for(manifest_shot)
        routed_shot = manifest_shot.model_copy(
            update={
                "required_identity_controls": [
                    ControlKind.TEXT_PROMPT,
                    ControlKind.CHARACTER_REFERENCE,
                ]
            }
        )
        decision = world.router.route_shot(
            routed_shot, episode_id=episode.episode_id, manifest_version=manifest.version
        )
        assert decision.chosen is not None
        kwargs = dict(
            decision=decision,
            shot=routed_shot,
            catalog=world.catalog,
            episode_number=1,
            reference_asset_ids=baseline_refs,
            identity_lock_id=None,
            prompt_text=prompt.prompt_text,
            prompt_manifest=prompt,
            dispatch_at=now,
        )
        before = len(world.operation_rows())
        reservations_before = reservation_count()
        with pytest.raises(SchemaInvalid, match="no current PropSheet"):
            dispatch_routed_attempt(world.db, world.service, world.jobs, prop_sheets=(), **kwargs)
        unknown_shot = routed_shot.model_copy(update={"prop_ids": ["unknown-prop"]})
        with pytest.raises(SchemaInvalid, match="match exactly"):
            dispatch_routed_attempt(
                world.db,
                world.service,
                world.jobs,
                prop_sheets=[prop],
                **{**kwargs, "shot": unknown_shot},
            )
        stale_sheet = prop.model_copy(update={"valid_until": now})
        with pytest.raises(SchemaInvalid, match="stale"):
            dispatch_routed_attempt(
                world.db, world.service, world.jobs, prop_sheets=[stale_sheet], **kwargs
            )
        retired_sheet = prop.model_copy(update={"asset_valid_until": now})
        with pytest.raises(SchemaInvalid, match="retired"):
            dispatch_routed_attempt(
                world.db, world.service, world.jobs, prop_sheets=[retired_sheet], **kwargs
            )
        stale_binding = type(prompt.bindings[-1]).seal(
            **{
                **prompt.bindings[-1].model_dump(mode="python"),
                "valid_until": now + timedelta(seconds=1),
            }
        )
        stale_prompt = PromptManifest.seal(
            **{
                **prompt.model_dump(mode="python"),
                "bindings": [*prompt.bindings[:-1], stale_binding],
            }
        )
        with pytest.raises(SchemaInvalid, match="stale"):
            dispatch_routed_attempt(
                world.db,
                world.service,
                world.jobs,
                prop_sheets=[prop],
                **{
                    **kwargs,
                    "prompt_manifest": stale_prompt,
                    "dispatch_at": now + timedelta(seconds=2),
                },
            )
        wrong_version = type(prompt.bindings[-1]).seal(
            **{
                **prompt.bindings[-1].model_dump(mode="python"),
                "asset_version": prop.asset_version + 1,
            }
        )
        wrong_version_prompt = PromptManifest.seal(
            **{
                **prompt.model_dump(mode="python"),
                "bindings": [*prompt.bindings[:-1], wrong_version],
            }
        )
        with pytest.raises(SchemaInvalid, match="exact PropSheet"):
            dispatch_routed_attempt(
                world.db,
                world.service,
                world.jobs,
                prop_sheets=[prop],
                **{**kwargs, "prompt_manifest": wrong_version_prompt},
            )
        assert len(world.operation_rows()) == before
        assert reservation_count() == reservations_before
        first = dispatch_routed_attempt(
            world.db, world.service, world.jobs, prop_sheets=[prop], **kwargs
        )
        again = dispatch_routed_attempt(
            world.db, world.service, world.jobs, prop_sheets=[prop], **kwargs
        )
        assert again.request == first.request
        assert again.job_id == first.job_id
        assert first.request.reference_asset_ids == list(
            dict.fromkeys(binding.asset_id for binding in prompt.bindings)
        )
        assert outfit.asset_id in first.request.reference_asset_ids
        assert prop.asset_sha256 in prompt.source_hashes
        assert reservation_count() == reservations_before + 1
        assert len(world.operation_rows()) == (1 if manifest_shot is establishing else 2)
        packets.append(first.request)
    assert packets[0].shot_id != packets[1].shot_id
    assert all(request.prompt_text.endswith("Keep the ledger visible.") for request in packets)

    repair_shot = establishing.model_copy(
        update={
            "required_identity_controls": [ControlKind.TEXT_PROMPT, ControlKind.CHARACTER_REFERENCE]
        }
    )
    repair_manifest = manifest.model_copy(
        update={
            "shots": [
                repair_shot if item.shot_id == establishing.shot_id else item
                for item in manifest.shots
            ]
        }
    )
    repair = RouterShotDispatch(
        world.db,
        world.service,
        world.jobs,
        world.router,
        world.catalog,
        manifest_for=lambda _episode_id: repair_manifest,
        bindings_for=lambda _episode_id: SimpleNamespace(
            reference_asset_ids=baseline_refs, lock_id=None
        ),
    )
    reservations_before_repair = reservation_count()
    operations_before_repair = len(world.operation_rows())
    with pytest.raises(SchemaInvalid, match="one current typed PropSheet"):
        repair.dispatch_repair(
            episode_id=episode.episode_id,
            episode_number=1,
            shot_id=establishing.shot_id,
            attempt_number=2,
        )
    assert reservation_count() == reservations_before_repair
    assert len(world.operation_rows()) == operations_before_repair

    legacy = manifest.model_dump(mode="json")
    legacy["shots"][0]["outfit_ids"] = ["ledger"]
    readback = read_v1_manifest(legacy)
    assert readback.manifest["shots"][0]["outfit_ids"] == ["ledger"]
    assert readback.v2_ready is False
