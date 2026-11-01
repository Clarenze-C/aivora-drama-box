from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import MappingProxyType, SimpleNamespace
from uuid import uuid4

import pytest
from test_routing_support import shot as v1_shot

from microdrama.contracts.enums import ControlKind, EvidenceSource, RenderTier, RightsStatus
from microdrama.contracts.errors import SchemaInvalid, UnsupportedControl
from microdrama.contracts.examples import (
    h,
    render_request,
    v2_episode_pack,
    v2_location_layout,
    v2_prompt_manifest,
    v2_prop_sheet,
    v2_reference_binding,
    v2_rights,
    v2_secret_ledger,
    v2_state_event,
    v2_style_bible,
    v2_wardrobe_assignment,
    v2_wardrobe_bible,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.primitives import EvidenceRef
from microdrama.contracts.registries import RightsRecord
from microdrama.contracts.v2 import (
    AssetSheet,
    DirectingManifest,
    DirectingShot,
    EpisodePack,
    PromptManifest,
    ReferenceRole,
    StateValue,
)
from microdrama.references.v2_binding import (
    compile_prompt_manifest,
    resolve_shot_reference_expectations,
)
from microdrama.rendering.routing import (
    V2ReferencePreflightContext,
    dispatch_v2_routed_attempt,
)
from microdrama.rendering.v2_preflight import validate_v2_prompt_preflight
from microdrama.rendering.workflows import (
    MOCK_VIDEO_TEMPLATE,
    bind_v2_workflow,
    semantic_template_sha256,
    template_sha256,
)


def _request(manifest):
    return render_request().model_copy(
        update={
            "shot_id": manifest.shot_id,
            "duration_ms": manifest.shot_duration_ms,
            "prompt_text": manifest.prompt_text,
            "required_controls": [
                ControlKind.TEXT_PROMPT,
                ControlKind.CHARACTER_REFERENCE,
                ControlKind.WARDROBE_REFERENCE,
                ControlKind.LOCATION_REFERENCE,
            ],
            "reference_asset_ids": list(dict.fromkeys(item.asset_id for item in manifest.bindings)),
            "workflow_sha256": template_sha256(MOCK_VIDEO_TEMPLATE),
            "semantic_workflow_sha256": semantic_template_sha256(MOCK_VIDEO_TEMPLATE),
            "prompt_manifest_id": manifest.record_id,
            "prompt_manifest_sha256": manifest.content_sha256,
        }
    )


def test_v2_graph_uses_named_role_subject_ports():
    manifest = v2_prompt_manifest()
    bound = bind_v2_workflow(MOCK_VIDEO_TEMPLATE, _request(manifest), manifest)
    inputs = bound.graph["sampler"]["inputs"]
    assert "identity_fon" in inputs
    assert "outfit_fon" in inputs
    assert "location_stall" in inputs
    assert "reference_images" not in inputs
    assert all(
        node["class_type"] == "LoadImage"
        for key, node in bound.graph.items()
        if key.startswith("semantic_")
    )
    semantic = {(item.role, item.subject_id): item for item in bound.semantic_inputs}
    for binding in manifest.bindings:
        record = semantic[(binding.role.value, binding.subject_id)]
        assert (record.asset_id, record.asset_version, record.asset_sha256) == (
            str(binding.asset_id),
            binding.asset_version,
            binding.asset_sha256,
        )
    assert bound.prompt_manifest_sha256 == manifest.content_sha256
    assert bound.source_hashes == tuple(sorted(manifest.source_hashes))


def test_missing_semantic_role_mapping_is_disabled():
    manifest = v2_prompt_manifest()
    mapping = dict(MOCK_VIDEO_TEMPLATE.semantic_role_ports)
    del mapping[ReferenceRole.LOCATION.value]
    unsupported = replace(MOCK_VIDEO_TEMPLATE, semantic_role_ports=MappingProxyType(mapping))
    request = _request(manifest).model_copy(
        update={
            "workflow_sha256": template_sha256(unsupported),
            "semantic_workflow_sha256": semantic_template_sha256(unsupported),
        }
    )
    with pytest.raises(UnsupportedControl, match="semantic port"):
        bind_v2_workflow(unsupported, request, manifest)


def test_composed_episode_pack_to_semantic_render_graph_trace():
    at = datetime(2026, 10, 30, tzinfo=UTC)
    rights = v2_rights()
    pack = v2_episode_pack()
    original_scene = pack.scenes[0]
    beat = original_scene.beats[0].model_copy(update={"proof_object_ids": ["ledger"]})
    scene = original_scene.model_copy(
        update={
            "prop_ids": ["ledger"],
            "beats": [beat],
            "state_in": [
                *original_scene.state_in,
                StateValue(entity_id="ledger", field="holder", value="fon"),
                StateValue(entity_id="ledger", field="hand", value="left"),
                StateValue(entity_id="stall", field="light_state", value="morning"),
            ],
            "state_out": [
                *original_scene.state_out,
                StateValue(entity_id="ledger", field="holder", value="fon"),
                StateValue(entity_id="ledger", field="hand", value="left"),
                StateValue(entity_id="stall", field="light_state", value="morning"),
            ],
        }
    )
    pack = EpisodePack.seal(
        **{
            **pack.model_dump(mode="python", exclude={"content_sha256"}),
            "scenes": [scene],
        }
    )
    scene = pack.scenes[0]
    beat = scene.beats[0]
    event = v2_state_event()
    shot = DirectingShot(
        shot_id="shot-t041",
        scene_id=scene.scene_id,
        beat_id=beat.beat_id,
        sequence=1,
        duration_ms=15_000,
        section_id="section-t041",
        state_in=beat.state_in,
        events=[event],
        state_out=beat.state_out,
        screen_axis="counter",
        screen_direction="STATIC",
        eyeline="Fon looks at the ledger.",
        action_handoff="Fon opens the ledger.",
        sound_intent="Paper movement over quiet stall ambience.",
        edit_intent="Cut to the ledger insert.",
        framing="medium_close_up",
        source_dependency_ids=[pack.record_id.hex, scene.scene_id, beat.beat_id],
        source_hashes=sorted(
            {
                canonical_hash(scene.model_copy(update={"beats": []})),
                canonical_hash(beat),
                event.content_sha256,
            }
        ),
    )
    directing = DirectingManifest.seal(
        record_id=uuid4(),
        version=1,
        created_at=at,
        updated_at=at,
        valid_from=at,
        episode_id=pack.episode_id,
        pack_id=pack.record_id,
        pack_version=pack.version,
        pack_hash=pack.content_sha256,
        approved_scope_hash=pack.approved_scope_hash,
        shots=[shot],
        sections=[
            {
                "section_id": "section-t041",
                "sequence": 1,
                "shot_ids": [shot.shot_id],
                "duration_ms": 15_000,
            }
        ],
        source_hashes=sorted({pack.content_sha256, *shot.source_hashes}),
    )

    bible = v2_wardrobe_bible()
    style_bible = v2_style_bible()
    assignment = v2_wardrobe_assignment()
    identity = AssetSheet.seal(
        record_id=uuid4(),
        version=1,
        created_at=at,
        updated_at=at,
        valid_from=at,
        asset_role="character_identity",
        subject_id="fon",
        asset_id=uuid4(),
        asset_version=1,
        asset_sha256=h("t041-fon-identity"),
        view_name="front",
        rights=rights,
        validity_from=at,
    )
    location = AssetSheet.seal(
        record_id=uuid4(),
        version=1,
        created_at=at,
        updated_at=at,
        valid_from=at,
        asset_role="location",
        subject_id="stall",
        asset_id=uuid4(),
        asset_version=1,
        asset_sha256=h("t041-stall-location"),
        view_name="front",
        rights=rights,
        validity_from=at,
    )
    style = AssetSheet.seal(
        record_id=uuid4(),
        version=1,
        created_at=at,
        updated_at=at,
        valid_from=at,
        asset_role="style",
        subject_id="series",
        asset_id=style_bible.moving_sample_asset_id,
        asset_version=1,
        asset_sha256=style_bible.moving_sample_sha256,
        view_name="moving_sample",
        rights=rights,
        validity_from=at,
    )
    prop = v2_prop_sheet()
    frame_bindings = [
        v2_reference_binding(
            ReferenceRole.FIRST_FRAME, "shot-t041", "t041-first", "t041-first-hash"
        ),
        v2_reference_binding(ReferenceRole.LAST_FRAME, "shot-t041", "t041-last", "t041-last-hash"),
        v2_reference_binding(
            ReferenceRole.HANDOFF_FRAME, "shot-t041", "t041-handoff", "t041-handoff-hash"
        ),
    ]
    expected = resolve_shot_reference_expectations(
        pack,
        directing,
        secret_ledger=v2_secret_ledger(),
        shot_id=shot.shot_id,
        shot_prop_ids=["ledger"],
        wardrobe_assignments=[assignment],
        wardrobe_bibles=[bible],
        style_bible=style_bible,
        asset_sheets=[identity, location, style],
        prop_sheets=[prop],
        location_layouts=[v2_location_layout()],
        explicit_frames=frame_bindings,
        required_frame_roles=frozenset(
            {ReferenceRole.FIRST_FRAME, ReferenceRole.LAST_FRAME, ReferenceRole.HANDOFF_FRAME}
        ),
        style_subject_id="series",
    )
    with pytest.raises(SchemaInvalid, match="unrelated to its episode scene"):
        resolve_shot_reference_expectations(
            pack,
            directing,
            secret_ledger=v2_secret_ledger(),
            shot_id=shot.shot_id,
            shot_prop_ids=["unrelated-prop"],
            wardrobe_assignments=[assignment],
            wardrobe_bibles=[bible],
            style_bible=style_bible,
            asset_sheets=[identity, location, style],
            prop_sheets=[prop],
            location_layouts=[v2_location_layout()],
            style_subject_id="series",
        )

    current_rights = RightsRecord(
        record_id=uuid4(),
        rights_route_id=rights.rights_route_id,
        version=rights.rights_version,
        subject_kind=rights.subject_kind,
        subject_ref=rights.subject_ref,
        territories=rights.territories,
        commercial_use=True,
        output_release_allowed=True,
        expires_at=rights.expires_at,
        evidence=[EvidenceRef(source=EvidenceSource.FAKE_FIXTURE, ref="fixture:current-rights")],
        status=RightsStatus.ELIGIBLE,
        recorded_at=at,
    )
    prompt = compile_prompt_manifest(
        pack,
        directing,
        secret_ledger=v2_secret_ledger(),
        shot_id=shot.shot_id,
        expected=expected,
        resolve_current_rights=lambda *_: current_rights,
        at=at,
        territories=["TH"],
        forbidden_facts=("future secret",),
    )
    assert "Lek co-signed the loan" not in prompt.prompt_text
    controls = {
        ControlKind.TEXT_PROMPT,
        ControlKind.CHARACTER_REFERENCE,
        ControlKind.WARDROBE_REFERENCE,
        ControlKind.LOCATION_REFERENCE,
        ControlKind.STYLE_REFERENCE,
        ControlKind.FIRST_FRAME,
        ControlKind.LAST_FRAME,
    }
    workflow_hash = template_sha256(MOCK_VIDEO_TEMPLATE)
    validate_v2_prompt_preflight(
        prompt,
        prompt_manifest_id=prompt.record_id,
        prompt_manifest_sha256=prompt.content_sha256,
        expected=expected,
        resolve_current_rights=lambda *_: current_rights,
        at=at,
        territories=["TH"],
        template=MOCK_VIDEO_TEMPLATE,
        workflow_sha256=workflow_hash,
        semantic_workflow_sha256=semantic_template_sha256(MOCK_VIDEO_TEMPLATE),
        required_controls=controls,
    )
    no_prop_port = replace(
        MOCK_VIDEO_TEMPLATE,
        semantic_role_ports=MappingProxyType(
            {
                key: value
                for key, value in MOCK_VIDEO_TEMPLATE.semantic_role_ports.items()
                if key != "prop"
            }
        ),
    )
    with pytest.raises(UnsupportedControl, match="no semantic input"):
        validate_v2_prompt_preflight(
            prompt,
            prompt_manifest_id=prompt.record_id,
            prompt_manifest_sha256=prompt.content_sha256,
            expected=expected,
            resolve_current_rights=lambda *_: current_rights,
            at=at,
            territories=["TH"],
            template=no_prop_port,
            workflow_sha256=template_sha256(no_prop_port),
            semantic_workflow_sha256=semantic_template_sha256(no_prop_port),
            required_controls=controls,
        )
    with pytest.raises(UnsupportedControl, match="required render controls"):
        validate_v2_prompt_preflight(
            prompt,
            prompt_manifest_id=prompt.record_id,
            prompt_manifest_sha256=prompt.content_sha256,
            expected=expected,
            resolve_current_rights=lambda *_: current_rights,
            at=at,
            territories=["TH"],
            template=MOCK_VIDEO_TEMPLATE,
            workflow_sha256=workflow_hash,
            semantic_workflow_sha256=semantic_template_sha256(MOCK_VIDEO_TEMPLATE),
            required_controls=controls | {ControlKind.CAMERA_MOTION},
        )
    with pytest.raises(SchemaInvalid, match="semantic workflow hash differs"):
        validate_v2_prompt_preflight(
            prompt,
            prompt_manifest_id=prompt.record_id,
            prompt_manifest_sha256=prompt.content_sha256,
            expected=expected,
            resolve_current_rights=lambda *_: current_rights,
            at=at,
            territories=["TH"],
            template=MOCK_VIDEO_TEMPLATE,
            workflow_sha256=workflow_hash,
            semantic_workflow_sha256=semantic_template_sha256(no_prop_port),
            required_controls=controls,
        )
    request = render_request().model_copy(
        update={
            "episode_id": pack.episode_id,
            "episode_number": pack.episode_number,
            "shot_id": shot.shot_id,
            "duration_ms": shot.duration_ms,
            "prompt_text": prompt.prompt_text,
            "required_controls": sorted(controls, key=lambda value: value.value),
            "reference_asset_ids": list(dict.fromkeys(item.asset_id for item in prompt.bindings)),
            "workflow_sha256": workflow_hash,
            "semantic_workflow_sha256": semantic_template_sha256(MOCK_VIDEO_TEMPLATE),
            "prompt_manifest_id": prompt.record_id,
            "prompt_manifest_sha256": prompt.content_sha256,
        }
    )
    graph = bind_v2_workflow(MOCK_VIDEO_TEMPLATE, request, prompt).graph
    ports = graph["sampler"]["inputs"]
    assert {
        "identity_fon",
        "outfit_fon",
        "location_stall",
        "prop_ledger",
        "style_series",
        "first_frame",
        "last_frame",
        "handoff_frame_shot-t041",
    }.issubset(ports)

    # A persisted prompt with an unrelated semantic role is rejected before reserve.
    unrelated = v2_reference_binding(
        ReferenceRole.PROP, "unrelated", "unrelated-prop", "unrelated-prop-hash"
    )
    wrong_role_manifest = PromptManifest.seal(
        **{
            **prompt.model_dump(mode="python", exclude={"content_sha256"}),
            "bindings": [*prompt.bindings, unrelated],
            "source_hashes": sorted(set(prompt.source_hashes) | {unrelated.asset_sha256}),
        }
    )

    class PromptDb:
        def __init__(self, manifest, source_records):
            self.manifest = manifest
            self.source_records = {record.record_id: record for record in source_records}

        def transaction(self, **_kwargs):
            manifest = self.manifest
            source_records = self.source_records

            class TxContext:
                def __enter__(self):
                    def fetchone(query, params):
                        record = (
                            manifest
                            if "PromptManifest" in query
                            else source_records.get(params[-1])
                        )
                        if record is None:
                            return None
                        return {
                            "payload": record.model_dump(mode="json"),
                            "payload_sha256": canonical_hash(record),
                        }

                    return SimpleNamespace(fetchone=fetchone)

                def __exit__(self, *_args):
                    return False

            return TxContext()

    preset_record = SimpleNamespace(preset_id="fake-quality-8step")
    preset_view = SimpleNamespace(
        preset_id=preset_record.preset_id,
        record=SimpleNamespace(
            tier=RenderTier.QUALITY_EIGHT_STEP,
            width=720,
            height=1280,
            fps=24,
        ),
        template=MOCK_VIDEO_TEMPLATE,
        template_workflow_sha256=workflow_hash,
    )
    catalog = SimpleNamespace(
        current_records=lambda: [preset_record],
        view=lambda _record: preset_view,
    )
    context = V2ReferencePreflightContext(
        episode_pack=pack,
        directing_manifest=directing,
        secret_ledger=v2_secret_ledger(),
        wardrobe_assignments=[assignment],
        wardrobe_bibles=[bible],
        style_bible=style_bible,
        asset_sheets=[identity, location, style],
        prop_sheets=[prop],
        location_layouts=[v2_location_layout()],
        resolve_current_rights=lambda *_: current_rights,
        verify_current_asset=lambda *_: None,
        territories=["TH"],
        style_subject_id="series",
        explicit_frames=frame_bindings,
        required_frame_roles=frozenset(
            {ReferenceRole.FIRST_FRAME, ReferenceRole.LAST_FRAME, ReferenceRole.HANDOFF_FRAME}
        ),
    )
    source_records = [
        pack,
        directing,
        v2_secret_ledger(),
        assignment,
        bible,
        style_bible,
        identity,
        location,
        style,
        prop,
        v2_location_layout(),
        *frame_bindings,
    ]
    reserve_calls = []

    class ComfySpy:
        def reserve_attempt(self, **_kwargs):
            reserve_calls.append("reserve")
            raise AssertionError("invalid V2 prompt reached reservation")

    decision = SimpleNamespace(
        chosen=SimpleNamespace(preset_id=preset_record.preset_id),
        episode_id=pack.episode_id,
        manifest_version=1,
        attempt_number=1,
    )
    with pytest.raises(SchemaInvalid, match="do not match current shot assignments"):
        dispatch_v2_routed_attempt(
            PromptDb(wrong_role_manifest, source_records),
            ComfySpy(),
            object(),
            decision=decision,
            shot=v1_shot(shot_id=shot.shot_id, prop_ids=("ledger",), duration_ms=15_000),
            catalog=catalog,
            episode_number=pack.episode_number,
            identity_lock_id=None,
            prompt_manifest_id=wrong_role_manifest.record_id,
            prompt_manifest_sha256=wrong_role_manifest.content_sha256,
            semantic_workflow_sha256=semantic_template_sha256(MOCK_VIDEO_TEMPLATE),
            reference_context=context,
            dispatch_at=at,
            submit=False,
        )
    assert reserve_calls == []

    with pytest.raises(SchemaInvalid, match="semantic workflow hash differs"):
        dispatch_v2_routed_attempt(
            PromptDb(prompt, source_records),
            ComfySpy(),
            object(),
            decision=decision,
            shot=v1_shot(shot_id=shot.shot_id, prop_ids=("ledger",), duration_ms=15_000),
            catalog=catalog,
            episode_number=pack.episode_number,
            identity_lock_id=None,
            prompt_manifest_id=prompt.record_id,
            prompt_manifest_sha256=prompt.content_sha256,
            semantic_workflow_sha256=semantic_template_sha256(no_prop_port),
            reference_context=context,
            dispatch_at=at,
            submit=False,
        )
    assert reserve_calls == []

    with pytest.raises(UnsupportedControl, match="does not accept a semantic V2 workflow"):
        dispatch_v2_routed_attempt(
            PromptDb(prompt, source_records),
            ComfySpy(),
            object(),
            decision=decision,
            shot=v1_shot(shot_id=shot.shot_id, prop_ids=("ledger",), duration_ms=15_000),
            catalog=catalog,
            episode_number=pack.episode_number,
            identity_lock_id=None,
            prompt_manifest_id=prompt.record_id,
            prompt_manifest_sha256=prompt.content_sha256,
            semantic_workflow_sha256=semantic_template_sha256(MOCK_VIDEO_TEMPLATE),
            reference_context=context,
            dispatch_at=at,
            submit=True,
        )
    assert reserve_calls == []

    def retired_asset(*_args):
        raise SchemaInvalid("reference asset descriptor is not current/accepted")

    with pytest.raises(SchemaInvalid, match="not current/accepted"):
        dispatch_v2_routed_attempt(
            PromptDb(prompt, source_records),
            ComfySpy(),
            object(),
            decision=decision,
            shot=v1_shot(shot_id=shot.shot_id, prop_ids=("ledger",), duration_ms=15_000),
            catalog=catalog,
            episode_number=pack.episode_number,
            identity_lock_id=None,
            prompt_manifest_id=prompt.record_id,
            prompt_manifest_sha256=prompt.content_sha256,
            semantic_workflow_sha256=semantic_template_sha256(MOCK_VIDEO_TEMPLATE),
            reference_context=replace(context, verify_current_asset=retired_asset),
            dispatch_at=at,
            submit=False,
        )
    assert reserve_calls == []

    unsupported_shot = v1_shot(
        shot_id=shot.shot_id,
        prop_ids=("ledger",),
        duration_ms=15_000,
        controls=(
            ControlKind.TEXT_PROMPT,
            ControlKind.CHARACTER_REFERENCE,
            ControlKind.CAMERA_MOTION,
        ),
    )
    with pytest.raises(UnsupportedControl, match="required render controls"):
        dispatch_v2_routed_attempt(
            PromptDb(prompt, source_records),
            ComfySpy(),
            object(),
            decision=decision,
            shot=unsupported_shot,
            catalog=catalog,
            episode_number=pack.episode_number,
            identity_lock_id=None,
            prompt_manifest_id=prompt.record_id,
            prompt_manifest_sha256=prompt.content_sha256,
            semantic_workflow_sha256=semantic_template_sha256(MOCK_VIDEO_TEMPLATE),
            reference_context=context,
            dispatch_at=at,
            submit=False,
        )
    assert reserve_calls == []
