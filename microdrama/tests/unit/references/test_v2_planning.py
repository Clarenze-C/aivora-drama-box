from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

import pytest

from microdrama.contracts.errors import Conflict, SchemaInvalid
from microdrama.contracts.examples import (
    h,
    rights_record,
    v2_episode_pack,
    v2_location_layout,
    v2_outfit,
    v2_prompt_manifest,
    v2_prop_sheet,
    v2_reference_binding,
    v2_rights,
    v2_story_time,
    v2_wardrobe_bible,
)
from microdrama.contracts.v2 import (
    EpisodePack,
    EpisodeScene,
    PackBeat,
    ReferenceRole,
    StateEvent,
    StateValue,
    StoryTime,
)
from microdrama.references.v2_planning import (
    AssetDemand,
    MockAsset,
    V2ReferenceRepository,
    assign_scene_wardrobes,
    demand_key,
    generate_offline_missing,
    make_offline_style_video,
    outfit_for_scene_time,
    resolve_shot_prop_bindings,
    seal_reference_record,
    targeted_invalidation,
    validate_episode_reference_state,
)

NOW = datetime(2026, 10, 30, tzinfo=UTC)


def test_shot_prop_resolves_to_exact_semantic_binding_and_source_hash():
    from types import SimpleNamespace

    prop = v2_prop_sheet()
    base = v2_prompt_manifest()
    prop_binding = v2_reference_binding(
        ReferenceRole.PROP, prop.prop_id, "ledger-prop-asset", "ledger-prop-image"
    )
    manifest = type(base).seal(
        **{
            **base.model_dump(mode="python"),
            "bindings": [*base.bindings, prop_binding],
            "source_hashes": [*base.source_hashes, prop.asset_sha256],
        }
    )
    assets, hashes = resolve_shot_prop_bindings(
        SimpleNamespace(prop_ids=[prop.prop_id]), manifest, [prop], at=NOW
    )
    assert assets == (prop.asset_id,)
    assert prop.asset_sha256 in hashes


def test_shot_prop_resolution_rejects_missing_stale_and_unrelated_bindings():
    from types import SimpleNamespace

    from microdrama.contracts.errors import SchemaInvalid

    prop = v2_prop_sheet()
    manifest = v2_prompt_manifest()
    with pytest.raises(SchemaInvalid, match="match exactly"):
        resolve_shot_prop_bindings(
            SimpleNamespace(prop_ids=[prop.prop_id]), manifest, [prop], at=NOW
        )
    retired = prop.model_copy(update={"asset_valid_until": NOW})
    prop_binding = v2_reference_binding(
        ReferenceRole.PROP, prop.prop_id, "ledger-prop-asset", "ledger-prop-image"
    )
    composed = type(manifest).seal(
        **{
            **manifest.model_dump(mode="python"),
            "bindings": [*manifest.bindings, prop_binding],
            "source_hashes": [*manifest.source_hashes, prop.asset_sha256],
        }
    )
    with pytest.raises(SchemaInvalid, match="retired"):
        resolve_shot_prop_bindings(
            SimpleNamespace(prop_ids=[prop.prop_id]), composed, [retired], at=NOW
        )


def current_rights(_route, _kind, _ref):
    row = rights_record().model_copy(
        update={
            "rights_route_id": "original-fiction",
            "subject_kind": v2_rights().subject_kind,
            "subject_ref": "original-fiction-output",
            "version": 1,
            "territories": ["TH"],
            "expires_at": None,
        }
    )
    return row


def test_wardrobe_planning_covers_visible_cast_and_changes_next_day():
    pack = v2_episode_pack()
    second_scene = EpisodeScene(
        scene_id="scene-2",
        scene_number=2,
        story_time=StoryTime.seal(
            **{
                **v2_story_time().model_dump(mode="python"),
                "story_day": 2,
                "local_time": "10:00",
            }
        ),
        location_id="stall",
        visible_character_ids=["fon"],
        beats=[PackBeat(**{**pack.scenes[0].beats[0].model_dump(), "beat_id": "beat-2"})],
    )
    pack = EpisodePack.seal(
        **{
            **pack.model_dump(mode="python"),
            "scenes": [pack.scenes[0], second_scene],
        }
    )
    outfit = v2_outfit().model_copy(update={"setting_tags": ["stall"]})
    next_outfit = outfit.model_copy(
        update={"outfit_id": "fon-apron-v2", "version": 2, "story_day_from": 2}
    )
    bible = v2_wardrobe_bible()
    bible = type(bible).seal(
        **{**bible.model_dump(mode="python"), "outfits": [outfit, next_outfit]}
    )

    result = assign_scene_wardrobes(
        pack,
        [bible],
        at=NOW,
        resolve_current=current_rights,
        territories=["TH"],
    )
    assert [(item.scene_id, item.character_id) for item in result] == [
        ("scene-1", "fon"),
        ("scene-2", "fon"),
    ]
    assert [item.outfit_id for item in result] == ["fon-apron", "fon-apron-v2"]


def test_next_day_same_outfit_requires_explicit_reuse_reason():
    pack = v2_episode_pack()
    second_scene = EpisodeScene(
        scene_id="scene-2",
        scene_number=2,
        story_time=StoryTime.seal(
            **{
                **v2_story_time().model_dump(mode="python"),
                "story_day": 2,
                "local_time": "10:00",
            }
        ),
        location_id="stall",
        visible_character_ids=["fon"],
        beats=[PackBeat(**{**pack.scenes[0].beats[0].model_dump(), "beat_id": "beat-2"})],
    )
    pack = EpisodePack.seal(
        **{**pack.model_dump(mode="python"), "scenes": [pack.scenes[0], second_scene]}
    )
    with pytest.raises(SchemaInvalid, match="next-day outfit reuse"):
        assign_scene_wardrobes(
            pack,
            [
                type(v2_wardrobe_bible()).seal(
                    **{
                        **v2_wardrobe_bible().model_dump(mode="python"),
                        "outfits": [v2_outfit()],
                    }
                )
            ],
            at=NOW,
            resolve_current=current_rights,
            territories=["TH"],
        )
    planned = assign_scene_wardrobes(
        pack,
        [
            type(v2_wardrobe_bible()).seal(
                **{
                    **v2_wardrobe_bible().model_dump(mode="python"),
                    "outfits": [v2_outfit()],
                }
            )
        ],
        at=NOW,
        resolve_current=current_rights,
        territories=["TH"],
        reuse_reasons={("fon", 2, "stall"): "Still working the same stall shift."},
    )
    assert planned[1].reuse_reason == "Still working the same stall shift."


def test_in_scene_wardrobe_change_resolves_only_inside_its_state_interval():
    pack = v2_episode_pack()
    first = v2_outfit()
    second = first.model_copy(
        update={"outfit_id": "fon-apron-overcoat", "version": 2, "story_day_from": 1}
    )
    bible = v2_wardrobe_bible()
    bible = type(bible).seal(**{**bible.model_dump(mode="python"), "outfits": [first, second]})
    assignment = assign_scene_wardrobes(
        pack,
        [bible],
        at=NOW,
        resolve_current=current_rights,
        territories=["TH"],
    )[0]
    event = seal_reference_record(
        StateEvent,
        "wardrobe-event",
        NOW,
        episode_id=pack.episode_id,
        sequence=1,
        entity_id="fon",
        field="outfit_id",
        before="fon-apron",
        after="fon-apron-overcoat",
        scene_id="scene-1",
        effective_from_ms=500,
        effective_until_ms=5000,
        evidence_sha256=h("wardrobe-change-proof"),
    )
    assert (
        outfit_for_scene_time(
            assignment,
            bible,
            [event],
            at_ms=1000,
            now=NOW,
            resolve_current=current_rights,
            territories=["TH"],
        ).outfit_id
        == "fon-apron-overcoat"
    )
    assert (
        outfit_for_scene_time(
            assignment,
            bible,
            [event],
            at_ms=6000,
            now=NOW,
            resolve_current=current_rights,
            territories=["TH"],
        ).outfit_id
        == "fon-apron"
    )


def test_demand_key_changes_with_rights_version_and_full_generation_inputs():
    grant = v2_rights()
    base = dict(
        asset_role="character_identity",
        subject_id="fon",
        view_name="left_profile",
        prompt="Gate 1 approved visual description",
        model_config_ref="mock-image-v1",
        grant=grant,
        dimensions=(512, 512),
    )
    key = demand_key(**base)
    assert key != demand_key(**{**base, "dimensions": (768, 768)})
    assert key != demand_key(**{**base, "grant": grant.model_copy(update={"rights_version": 2})})
    assert key != demand_key(**{**base, "lineage_sha256": [h("new-lineage")]})
    assert key != demand_key(**{**base, "seed": 99})


def test_offline_generation_forecasts_unique_missing_assets_and_caches_replay():
    grant = v2_rights()
    demand = AssetDemand(
        role="prop",
        subject_id="ledger",
        view_name="detail",
        prompt="ledger front detail",
        cache_key="a" * 64,
        rights=grant,
        estimated_micro_usd=250,
    )
    reservations = []
    generated, forecast = generate_offline_missing(
        [demand, demand],
        cache={},
        episode_cap_micro_usd=1_000,
        current_spend_micro_usd=100,
        at=NOW,
        resolve_current=current_rights,
        territories=["TH"],
        reserve=reservations.append,
        cached_allocation_micro_usd={},
    )
    assert forecast == 250
    assert reservations == [demand]
    assert len(generated) == 1 and generated[0].provenance == "OFFLINE_MOCK"
    allocations = []
    replay, replay_forecast = generate_offline_missing(
        [demand],
        cache={demand.cache_key: generated[0]},
        episode_cap_micro_usd=400,
        current_spend_micro_usd=100,
        at=NOW,
        resolve_current=current_rights,
        territories=["TH"],
        reserve=lambda _item: pytest.fail("cache replay must not reserve again"),
        cached_allocation_micro_usd={demand.cache_key: 50},
        allocate_cached=lambda item, amount: allocations.append((item.cache_key, amount)),
    )
    assert replay == [] and replay_forecast == 50
    assert allocations == [(demand.cache_key, 50)]
    _replay, replay_forecast = generate_offline_missing(
        [demand],
        cache={demand.cache_key: generated[0]},
        episode_cap_micro_usd=150,
        current_spend_micro_usd=150,
        at=NOW,
        resolve_current=current_rights,
        territories=["TH"],
        reserve=lambda _item: pytest.fail("cache replay must not reserve again"),
        cached_allocation_micro_usd={demand.cache_key: 50},
        already_allocated_cache_keys={demand.cache_key},
    )
    assert replay_forecast == 0


def test_offline_generation_checks_all_rights_and_budget_before_reserving():
    demand = AssetDemand(
        role="prop",
        subject_id="ledger",
        view_name="detail",
        prompt="ledger front detail",
        cache_key="b" * 64,
        rights=v2_rights(),
        estimated_micro_usd=251,
    )
    reservations = []
    with pytest.raises(SchemaInvalid, match="forecast exceeds"):
        generate_offline_missing(
            [demand],
            cache={},
            episode_cap_micro_usd=350,
            current_spend_micro_usd=100,
            at=NOW,
            resolve_current=current_rights,
            territories=["TH"],
            reserve=reservations.append,
            cached_allocation_micro_usd={},
        )
    assert reservations == []

    with pytest.raises(SchemaInvalid, match="current rights"):
        generate_offline_missing(
            [demand],
            cache={},
            episode_cap_micro_usd=1_000,
            current_spend_micro_usd=0,
            at=NOW,
            resolve_current=lambda *_: None,
            territories=["TH"],
            reserve=reservations.append,
            cached_allocation_micro_usd={},
        )
    assert reservations == []


def test_invalidation_follows_only_the_changed_asset_dependency_branch():
    graph = {
        "shot-a": ["face-fon-v1", "prop-ledger-v1"],
        "caption-a": ["shot-a"],
        "poster-b": ["face-nok-v1"],
    }
    assert targeted_invalidation(["face-fon-v1"], graph) == ["caption-a", "shot-a"]


def test_prop_holder_hand_and_location_light_events_match_scene_state():
    pack = v2_episode_pack()
    scene = pack.scenes[0].model_copy(
        update={
            "prop_ids": ["ledger"],
            "state_in": [
                StateValue(entity_id="ledger", field="holder_character_id", value=None),
                StateValue(entity_id="ledger", field="hand", value="none"),
                StateValue(entity_id="stall", field="light_state", value="morning"),
            ],
            "state_out": [
                StateValue(entity_id="ledger", field="holder_character_id", value="fon"),
                StateValue(entity_id="ledger", field="hand", value="right"),
                StateValue(entity_id="stall", field="light_state", value="morning"),
            ],
        }
    )
    pack = EpisodePack.seal(**{**pack.model_dump(mode="python"), "scenes": [scene]})
    events = [
        seal_reference_record(
            StateEvent,
            f"ledger-handoff-{field}",
            NOW,
            episode_id=pack.episode_id,
            sequence=seq,
            entity_id="ledger",
            field=field,
            before=before,
            after=after,
            scene_id="scene-1",
            effective_from_ms=100,
            effective_until_ms=5000,
            evidence_sha256=h(f"handoff-{field}"),
        )
        for seq, field, before, after in [
            (1, "holder_character_id", None, "fon"),
            (2, "hand", "none", "right"),
        ]
    ]
    validate_episode_reference_state(pack, [v2_prop_sheet()], [v2_location_layout()], events)
    contradictory = [
        events[0],
        StateEvent.seal(**{**events[1].model_dump(mode="python"), "before": "left"}),
    ]
    with pytest.raises(Conflict, match="before value contradicts"):
        validate_episode_reference_state(
            pack, [v2_prop_sheet()], [v2_location_layout()], contradictory
        )


def test_prop_hand_without_holder_and_unlisted_light_state_are_rejected():
    pack = v2_episode_pack()
    scene = pack.scenes[0].model_copy(
        update={
            "prop_ids": ["ledger"],
            "state_in": [
                StateValue(entity_id="ledger", field="holder_character_id", value=None),
                StateValue(entity_id="ledger", field="hand", value="left"),
                StateValue(entity_id="stall", field="light_state", value="afternoon"),
            ],
            "state_out": [
                StateValue(entity_id="ledger", field="holder_character_id", value=None),
                StateValue(entity_id="ledger", field="hand", value="left"),
                StateValue(entity_id="stall", field="light_state", value="afternoon"),
            ],
        }
    )
    pack = EpisodePack.seal(**{**pack.model_dump(mode="python"), "scenes": [scene]})
    with pytest.raises(SchemaInvalid, match="light state"):
        validate_episode_reference_state(pack, [v2_prop_sheet()], [v2_location_layout()], [])

    scene = scene.model_copy(
        update={
            "state_in": [
                StateValue(entity_id="ledger", field="holder_character_id", value=None),
                StateValue(entity_id="ledger", field="hand", value="left"),
                StateValue(entity_id="stall", field="light_state", value="morning"),
            ],
            "state_out": [
                StateValue(entity_id="ledger", field="holder_character_id", value=None),
                StateValue(entity_id="ledger", field="hand", value="left"),
                StateValue(entity_id="stall", field="light_state", value="morning"),
            ],
        }
    )
    pack = EpisodePack.seal(**{**pack.model_dump(mode="python"), "scenes": [scene]})
    with pytest.raises(Conflict, match="without a holder"):
        validate_episode_reference_state(pack, [v2_prop_sheet()], [v2_location_layout()], [])


def test_asset_sheet_and_bytes_survive_repository_restart(db, object_store):
    demand = AssetDemand(
        role="character_identity",
        subject_id="fon",
        view_name="front",
        prompt="approved Gate-1 appearance",
        cache_key="c" * 64,
        rights=v2_rights(),
        estimated_micro_usd=50,
    )
    from microdrama.testing.seed import seed_episode, seed_season

    with db.transaction() as tx:
        season_id = seed_season(tx, state="SEASON_APPROVED")
        episode_id = seed_episode(tx, season_id)

    payload = b"offline fake image bytes"
    generated = MockAsset(demand.cache_key, payload, sha256(payload).hexdigest())
    repository = V2ReferenceRepository(db, object_store)
    first = repository.persist_generated(
        demand, generated, episode_id=episode_id, season_id=season_id, now=NOW
    )
    restarted = V2ReferenceRepository(db, object_store)
    cached = restarted.load_cached(demand)
    assert cached is not None
    assert cached.descriptor.asset_id == first.descriptor.asset_id
    assert cached.sheet == first.sheet
    assert cached.reused is True
    assert object_store.get_bytes(cached.descriptor.object_key) == payload

    def persist_role(role, subject, cache_key):
        view_name = "moving_sample" if role == "style" else "front"
        item = AssetDemand(
            role=role,
            subject_id=subject,
            view_name=view_name,
            prompt=f"{role} {subject}",
            cache_key=cache_key,
            rights=v2_rights(),
            estimated_micro_usd=50,
        )
        data = make_offline_style_video() if role == "style" else f"fake {role} bytes".encode()
        result = repository.persist_generated(
            item,
            MockAsset(item.cache_key, data, sha256(data).hexdigest()),
            episode_id=episode_id,
            season_id=season_id,
            now=NOW,
        )
        return result

    prop_asset = persist_role("prop", "ledger", "d" * 64)
    location_asset = persist_role("location", "stall", "e" * 64)
    style_asset = persist_role("style", str(season_id), "f" * 64)
    assert style_asset.descriptor.asset_kind.value == "VIDEO"
    assert style_asset.descriptor.media is not None
    assert style_asset.descriptor.media.has_video is True
    assert style_asset.descriptor.media.duration_ms > 0
    assert style_asset.descriptor.provenance.value == "FAKE_SYNTHETIC"
    prop_sheet = repository.make_prop_sheet(
        prop_id="ledger",
        asset=prop_asset,
        purpose="evidence of the hidden debt",
        visual_anchor="red hardbound ledger with a torn corner",
        dimensions="A5 notebook",
        known_states=["closed", "open"],
        owner_character_id="fon",
        now=NOW,
    )
    layout = repository.make_location_layout(
        location_id="stall",
        empty_plate=location_asset,
        entrance_ids=["front-door"],
        camera_zones=["counter", "street-side"],
        light_states=["morning", "night"],
        prop_ownership={"ledger": "fon"},
        now=NOW,
    )
    style = repository.make_style_bible(
        season_id=season_id,
        moving_sample=style_asset,
        medium="2D illustrated drama",
        realism="stylized naturalism",
        palette=["warm amber", "deep teal"],
        lighting_language="soft practical light with restrained contrast",
        lens_and_movement="stable medium frames with slow motivated moves",
        material_rules=["matte surfaces", "natural cloth texture"],
        typography_rules=["clear Thai glyphs", "high contrast subtitles"],
        subtitle_safe_top_bp=500,
        subtitle_safe_bottom_bp=1800,
        sound_motifs=["market bells"],
        exclusions=["watermarks", "brand marks"],
        now=NOW,
    )
    saved = repository.persist_companion_records([prop_sheet, layout, style])
    assert [type(item).__name__ for item in saved] == ["PropSheet", "LocationLayout", "StyleBible"]
    with db.transaction(readonly=True) as tx:
        count = tx.fetchval(
            "SELECT count(*) FROM v2_contract_documents WHERE current AND contract_type IN "
            "('PropSheet', 'LocationLayout', 'StyleBible')"
        )
    assert count == 3
