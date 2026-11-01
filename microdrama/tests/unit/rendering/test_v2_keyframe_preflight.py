"""T042a: pre-motion still-frame keyframe preflight over verified frame bytes.

Every persistence-touching case runs on real isolated PostgreSQL. The fixture
inspector is an offline fake with declared calibration; it observes media-only
frame bytes and never sees an intended fact, assignment or prompt text.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import fields, replace
from datetime import UTC, datetime
from types import MappingProxyType, SimpleNamespace
from uuid import UUID, uuid4

import pytest
from test_routing_support import shot as v1_shot

from microdrama.contracts.enums import (
    ControlKind,
    EvidenceSource,
    RenderTier,
    RightsStatus,
)
from microdrama.contracts.errors import SchemaInvalid, UnsupportedControl
from microdrama.contracts.examples import (
    V2_T0,
    h,
    uid,
    v2_character_logic,
    v2_episode_pack,
    v2_location_layout,
    v2_rights,
    v2_secret_ledger,
    v2_state_event,
    v2_style_bible,
    v2_wardrobe_assignment,
    v2_wardrobe_bible,
)
from microdrama.contracts.hashing import canonical_hash, sha256_hex
from microdrama.contracts.primitives import EvidenceRef
from microdrama.contracts.registries import RightsRecord
from microdrama.contracts.v2 import (
    AssetSheet,
    CharacterLogic,
    DirectingManifest,
    DirectingShot,
    EpisodePack,
    LocationLayout,
    PropSheet,
    ReferenceRole,
    ShotReferenceBinding,
    StateEvent,
    StateValue,
)
from microdrama.core.jobs import JobService
from microdrama.persistence import Database
from microdrama.references.v2_binding import (
    compile_prompt_manifest,
    resolve_shot_reference_expectations,
)
from microdrama.references.v2_planning import V2ReferenceRepository
from microdrama.rendering.keyframe_preflight import (
    KEYFRAME_PREFLIGHT_EVENT,
    DimensionOutcome,
    FrameAsset,
    FrameOutcome,
    KeyframeDimension,
    KeyframePreflightFailed,
    KeyframePreflightResult,
    KeyframePreflightStatus,
    StillFrameObservation,
    StillMediaInspector,
    build_expected_keyframe_facts,
    ensure_keyframe_preflight_allows_dispatch,
    keyframe_preflight_input_sha256,
    run_keyframe_preflight,
)
from microdrama.rendering.routing import (
    V2ReferencePreflightContext,
    dispatch_v2_routed_attempt,
)
from microdrama.rendering.workflows import (
    MOCK_VIDEO_TEMPLATE,
    semantic_template_sha256,
    template_sha256,
)
from microdrama.testing.fakes import FakeClock, SequentialIds

pytestmark = [pytest.mark.db]

AT = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
SHOT_ID = "shot-t042a"
EYELINE = "Fon looks at the ledger."
ACTION_HANDOFF = "Fon opens the ledger."
PROOF_TEXT = "debt total 20000 baht"
ALL_DIMENSIONS = tuple(KeyframeDimension)
FRAME_NAMES = ("first", "last", "handoff")
FRAME_ROLES = {
    "first": ReferenceRole.FIRST_FRAME,
    "last": ReferenceRole.LAST_FRAME,
    "handoff": ReferenceRole.HANDOFF_FRAME,
}
NO_STILL_TEMPLATE = replace(
    MOCK_VIDEO_TEMPLATE,
    supported_controls=frozenset(
        {
            ControlKind.TEXT_PROMPT,
            ControlKind.SEED,
            ControlKind.CHARACTER_REFERENCE,
            ControlKind.WARDROBE_REFERENCE,
            ControlKind.LOCATION_REFERENCE,
            ControlKind.STYLE_REFERENCE,
        }
    ),
    semantic_role_ports=MappingProxyType(
        {
            key: value
            for key, value in MOCK_VIDEO_TEMPLATE.semantic_role_ports.items()
            if key not in ("first_frame", "last_frame", "handoff_frame")
        }
    ),
)


def _scene_states() -> list[StateValue]:
    return [
        StateValue(entity_id="ledger", field="holder", value="fon"),
        StateValue(entity_id="ledger", field="hand", value="left"),
        StateValue(entity_id="stall", field="light_state", value="morning"),
    ]


def _exit_scene_states() -> list[StateValue]:
    """Scene-level exit baseline agreeing with the mid-shot transition chain."""
    return [
        StateValue(entity_id="ledger", field="holder", value="lek"),
        StateValue(entity_id="ledger", field="hand", value="left"),
        StateValue(entity_id="stall", field="light_state", value="evening"),
    ]


def _lek_character_logic() -> CharacterLogic:
    """Lek takes the ledger mid-shot; a holder must name a pack character."""
    baseline = v2_character_logic()
    return CharacterLogic.seal(
        record_id=uid("t042a-lek-logic"),
        version=1,
        created_at=V2_T0,
        updated_at=V2_T0,
        valid_from=V2_T0,
        character_id="lek",
        season_id=baseline.season_id,
        observable_goal="Collect what the family owes.",
        strategy="Wait at the stall until Fon relents.",
        flaw="Believes pressure is persuasion.",
        secret_id=baseline.secret_id,
        relationship_pressures=["Fon keeps the ledger closed."],
        knowledge_by_episode={"1": ["debt_exists"]},
    )


def _transition_events(episode_id: UUID) -> list[StateEvent]:
    """Mid-shot transitions after the ledger opens: it changes holder, light changes."""
    return [
        StateEvent.seal(
            record_id=uid("t042a-holder-event"),
            version=1,
            created_at=V2_T0,
            updated_at=V2_T0,
            valid_from=V2_T0,
            episode_id=episode_id,
            sequence=2,
            entity_id="ledger",
            field="holder",
            before="fon",
            after="lek",
            scene_id="scene-1",
            effective_from_ms=4_000,
            effective_until_ms=8_000,
            evidence_sha256=h("t042a-holder-observation"),
        ),
        StateEvent.seal(
            record_id=uid("t042a-light-event"),
            version=1,
            created_at=V2_T0,
            updated_at=V2_T0,
            valid_from=V2_T0,
            episode_id=episode_id,
            sequence=3,
            entity_id="stall",
            field="light_state",
            before="morning",
            after="evening",
            scene_id="scene-1",
            effective_from_ms=8_000,
            effective_until_ms=12_000,
            evidence_sha256=h("t042a-light-observation"),
        ),
    ]


def build_world(*, with_frames: bool = True, mid_shot_transition: bool = False) -> SimpleNamespace:
    """Deterministic typed records for one shot, optionally with keyframes.

    ``mid_shot_transition`` moves every holder/light fact onto shot-level entry
    and exit states joined by typed state events: the ledger changes holder from
    Fon to Lek and the stall light changes from morning to evening while the
    shot runs, so the first and last frames must show deliberately different
    stills.
    """
    rights = v2_rights()
    pack = v2_episode_pack()
    original_scene = pack.scenes[0]
    beat = original_scene.beats[0].model_copy(update={"proof_object_ids": ["ledger"]})
    scene = original_scene.model_copy(
        update={
            "prop_ids": ["ledger"],
            "beats": [beat],
            "state_in": _scene_states(),
            "state_out": _exit_scene_states() if mid_shot_transition else _scene_states(),
        }
    )
    pack_kwargs = {
        **pack.model_dump(mode="python", exclude={"content_sha256"}),
        "scenes": [scene],
    }
    if mid_shot_transition:
        pack_kwargs["character_logic"] = [pack.character_logic[0], _lek_character_logic()]
    pack = EpisodePack.seal(**pack_kwargs)
    scene = pack.scenes[0]
    beat = scene.beats[0]
    if mid_shot_transition:
        shot_state_in = [
            StateValue(entity_id="ledger", field="holder", value="fon"),
            StateValue(entity_id="stall", field="light_state", value="morning"),
        ]
        shot_events = [v2_state_event(), *_transition_events(pack.episode_id)]
        shot_state_out = [
            StateValue(entity_id="ledger", field="open", value="open"),
            StateValue(entity_id="ledger", field="holder", value="lek"),
            StateValue(entity_id="stall", field="light_state", value="evening"),
        ]
    else:
        shot_state_in = beat.state_in
        shot_events = [v2_state_event()]
        shot_state_out = beat.state_out
    directing_shot = DirectingShot(
        shot_id=SHOT_ID,
        scene_id=scene.scene_id,
        beat_id=beat.beat_id,
        sequence=1,
        duration_ms=15_000,
        section_id="section-t042a",
        state_in=shot_state_in,
        events=shot_events,
        state_out=shot_state_out,
        screen_axis="counter",
        screen_direction="STATIC",
        eyeline=EYELINE,
        action_handoff=ACTION_HANDOFF,
        sound_intent="Paper movement over quiet stall ambience.",
        edit_intent="Cut to the ledger insert.",
        framing="medium_close_up",
        source_dependency_ids=[pack.record_id.hex, scene.scene_id, beat.beat_id],
        source_hashes=sorted(
            {
                canonical_hash(scene.model_copy(update={"beats": []})),
                canonical_hash(beat),
                *(event.content_sha256 for event in shot_events),
            }
        ),
    )
    directing = DirectingManifest.seal(
        record_id=uuid4(),
        version=1,
        created_at=V2_T0,
        updated_at=V2_T0,
        valid_from=V2_T0,
        episode_id=pack.episode_id,
        pack_id=pack.record_id,
        pack_version=pack.version,
        pack_hash=pack.content_sha256,
        approved_scope_hash=pack.approved_scope_hash,
        shots=[directing_shot],
        sections=[
            {
                "section_id": "section-t042a",
                "sequence": 1,
                "shot_ids": [SHOT_ID],
                "duration_ms": 15_000,
            }
        ],
        source_hashes=sorted({pack.content_sha256, *directing_shot.source_hashes}),
    )
    bible = v2_wardrobe_bible()
    style_bible = v2_style_bible()
    assignment = v2_wardrobe_assignment()
    identity = AssetSheet.seal(
        record_id=uid("t042a-fon-identity-sheet"),
        version=1,
        created_at=V2_T0,
        updated_at=V2_T0,
        valid_from=V2_T0,
        asset_role="character_identity",
        subject_id="fon",
        asset_id=uid("fon-id"),
        asset_version=1,
        asset_sha256=h("fon-id-image"),
        view_name="front",
        rights=rights,
        validity_from=V2_T0,
    )
    location = AssetSheet.seal(
        record_id=uid("t042a-stall-location-sheet"),
        version=1,
        created_at=V2_T0,
        updated_at=V2_T0,
        valid_from=V2_T0,
        asset_role="location",
        subject_id="stall",
        asset_id=uid("stall-front"),
        asset_version=1,
        asset_sha256=h("stall-image"),
        view_name="front",
        rights=rights,
        validity_from=V2_T0,
    )
    style = AssetSheet.seal(
        record_id=uid("t042a-style-sheet"),
        version=1,
        created_at=V2_T0,
        updated_at=V2_T0,
        valid_from=V2_T0,
        asset_role="style",
        subject_id="series",
        asset_id=style_bible.moving_sample_asset_id,
        asset_version=1,
        asset_sha256=style_bible.moving_sample_sha256,
        view_name="moving_sample",
        rights=rights,
        validity_from=V2_T0,
    )
    prop = PropSheet.seal(
        record_id=uid("t042a-ledger-prop-sheet"),
        version=1,
        created_at=V2_T0,
        updated_at=V2_T0,
        valid_from=V2_T0,
        prop_id="ledger",
        purpose="Carries the debt evidence Fon reads.",
        visual_anchor="Dark green cloth ledger with a brass corner.",
        owner_character_id="fon",
        dimensions="A5 notebook",
        known_states=["closed", "open"],
        text_layer_sha256=sha256_hex(PROOF_TEXT.encode("utf-8")),
        asset_id=uid("ledger-prop-asset"),
        asset_version=1,
        asset_sha256=h("ledger-prop-image"),
        rights=rights,
    )
    if mid_shot_transition:
        base_layout = v2_location_layout()
        layout = LocationLayout.seal(
            **{
                **base_layout.model_dump(mode="python", exclude={"content_sha256"}),
                "light_states": ["morning", "evening"],
            }
        )
    else:
        layout = v2_location_layout()
    frame_payloads = {name: f"t042a-frame-bytes-{name}".encode() for name in FRAME_NAMES}
    frames = []
    if with_frames:
        for name in FRAME_NAMES:
            frames.append(
                ShotReferenceBinding.seal(
                    record_id=uid(f"t042a-frame-binding-{name}"),
                    version=1,
                    created_at=V2_T0,
                    updated_at=V2_T0,
                    valid_from=V2_T0,
                    role=FRAME_ROLES[name],
                    subject_id=SHOT_ID,
                    asset_id=uid(f"t042a-frame-asset-{name}"),
                    asset_version=1,
                    asset_sha256=sha256_hex(frame_payloads[name]),
                    rights=rights,
                )
            )
    required_roles = frozenset(FRAME_ROLES.values()) if with_frames else frozenset()
    expected = resolve_shot_reference_expectations(
        pack,
        directing,
        secret_ledger=v2_secret_ledger(),
        shot_id=SHOT_ID,
        shot_prop_ids=["ledger"],
        wardrobe_assignments=[assignment],
        wardrobe_bibles=[bible],
        style_bible=style_bible,
        asset_sheets=[identity, location, style],
        prop_sheets=[prop],
        location_layouts=[layout],
        explicit_frames=frames,
        required_frame_roles=required_roles,
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
        recorded_at=V2_T0,
    )
    prompt = compile_prompt_manifest(
        pack,
        directing,
        secret_ledger=v2_secret_ledger(),
        shot_id=SHOT_ID,
        expected=expected,
        resolve_current_rights=lambda *_: current_rights,
        at=AT,
        territories=["TH"],
    )
    facts_by_role = {
        role: build_expected_keyframe_facts(
            scene=scene,
            directing_shot=directing_shot,
            shot_prop_ids=["ledger"],
            wardrobe_assignments=[assignment],
            location_layouts=[layout],
            prop_sheets=[prop],
            frame_role=role,
        )
        for role in sorted(FRAME_ROLES.values())
    }
    return SimpleNamespace(
        pack=pack,
        directing=directing,
        directing_shot=directing_shot,
        scene=scene,
        assignment=assignment,
        bible=bible,
        style_bible=style_bible,
        identity=identity,
        location=location,
        style=style,
        prop=prop,
        layout=layout,
        frames=frames,
        frame_payloads=frame_payloads,
        required_roles=required_roles,
        expected=expected,
        prompt=prompt,
        current_rights=current_rights,
        facts_by_role=facts_by_role,
    )


class DirectingDb:
    """Real PostgreSQL plus an in-memory current row for the DirectingManifest.

    The ``v2_contract_documents`` migration deliberately has no
    ``DirectingManifest`` contract type (production persists it elsewhere;
    T044/T047 own that wiring). Every statement — keyframe evidence events,
    jobs, budget reads — hits the real database; only the directing manifest's
    current-row lookup is served from memory, exactly like the T041 trace test.
    """

    def __init__(self, db: Database, directing) -> None:
        self._db = db
        self._directing = directing

    def transaction(self, *args, **kwargs):
        outer = self._db.transaction(*args, **kwargs)
        directing = self._directing

        class _Tx:
            def __init__(self, tx):
                self._tx = tx

            def fetchone(self, sql, params=None):
                if (
                    params
                    and "v2_contract_documents" in sql
                    and str(params[0]) == "DirectingManifest"
                    and UUID(str(params[1])) == directing.record_id
                ):
                    return {
                        "payload": directing.model_dump(mode="json"),
                        "payload_sha256": canonical_hash(directing),
                    }
                return self._tx.fetchone(sql, params)

            def __getattr__(self, name):
                return getattr(self._tx, name)

        @contextmanager
        def _cm():
            with outer as tx:
                yield _Tx(tx)

        return _cm()


def seed_world(db: Database, world: SimpleNamespace) -> None:
    V2ReferenceRepository(db, None).persist_companion_records(
        [
            world.pack,
            v2_secret_ledger(),
            world.style_bible,
            world.identity,
            world.location,
            world.style,
            world.assignment,
            world.bible,
            world.prop,
            world.layout,
            *world.frames,
            world.prompt,
        ]
    )


def clean_observation(
    world: SimpleNamespace, *, confidence_bp: int = 10_000
) -> StillFrameObservation:
    return StillFrameObservation(
        visible_subject_ids=frozenset({"fon"}),
        outfit_by_character={"fon": "fon-apron"},
        holder_by_prop={"ledger": "fon"},
        location_id="stall",
        geometry_token=world.layout.geometry_sha256,
        light_state="morning",
        eyeline=EYELINE,
        proof_text=PROOF_TEXT,
        handoff=ACTION_HANDOFF,
        confidence_bp={dimension: confidence_bp for dimension in ALL_DIMENSIONS},
    )


def make_inspector(
    observation: StillFrameObservation,
    *,
    dimensions=ALL_DIMENSIONS,
    threshold_bp: int = 7_500,
    evaluator_id: str = "offline-fixture-inspector",
) -> tuple[StillMediaInspector, list[FrameAsset]]:
    calls: list[FrameAsset] = []

    def observe(frame: FrameAsset) -> StillFrameObservation:
        calls.append(frame)
        return observation

    inspector = StillMediaInspector(
        evaluator_id=evaluator_id,
        evaluator_version="1",
        source_label="OFFLINE_FIXTURE",
        calibrated_threshold_bp={dimension: threshold_bp for dimension in dimensions},
        observe=observe,
    )
    return inspector, calls


def transition_observation(
    world: SimpleNamespace, frame_name: str, *, swapped: bool = False
) -> StillFrameObservation:
    """One frame of the mid-shot-transition world at its own state boundary.

    The first frame stands at the entry state (Fon holds the ledger, morning
    light); the last and handoff frames stand at the exit state (Lek holds it,
    evening light). ``swapped`` crosses the boundaries precisely so the entry
    and exit expectations can be told apart.
    """
    at_entry = (frame_name == "first") != swapped
    return replace(
        clean_observation(world),
        holder_by_prop={"ledger": "fon" if at_entry else "lek"},
        light_state="morning" if at_entry else "evening",
    )


def make_frame_inspector(
    observations_by_frame: dict[str, StillFrameObservation],
    *,
    threshold_bp: int = 7_500,
) -> tuple[StillMediaInspector, list[str]]:
    """Observe each frame by its own name; records which frame was seen."""
    calls: list[str] = []

    def observe(frame: FrameAsset) -> StillFrameObservation:
        for name in FRAME_NAMES:
            if frame.asset_id == uid(f"t042a-frame-asset-{name}"):
                calls.append(name)
                return observations_by_frame[name]
        raise AssertionError(f"unknown frame asset {frame.asset_id}")

    inspector = StillMediaInspector(
        evaluator_id="offline-fixture-inspector",
        evaluator_version="1",
        source_label="OFFLINE_FIXTURE",
        calibrated_threshold_bp={dimension: threshold_bp for dimension in ALL_DIMENSIONS},
        observe=observe,
    )
    return inspector, calls


def frame_loader(world: SimpleNamespace, *, tamper: bool = False):
    def read(asset_id, _version, _sha256):
        for name, payload in world.frame_payloads.items():
            if uid(f"t042a-frame-asset-{name}") == asset_id:
                return b"tampered-frame-bytes" if tamper else payload
        raise AssertionError(f"unknown frame asset {asset_id}")

    return read


class ComfySpy:
    """Records the reserve/submit order; never touches a provider."""

    def __init__(self) -> None:
        self.reserve_calls: list[dict] = []
        self.submit_calls: list[dict] = []

    def reserve_attempt(self, **kwargs):
        self.reserve_calls.append(kwargs)
        return SimpleNamespace(id=uuid4())

    def submit_v2(self, request, bound, *, job_id):
        self.submit_calls.append({"request": request, "job_id": job_id})
        return SimpleNamespace(prompt_id=f"fake-{job_id}")


def dispatch(
    db: Database,
    world: SimpleNamespace,
    *,
    inspector: StillMediaInspector | None = None,
    read_bytes=None,
    template=MOCK_VIDEO_TEMPLATE,
    shot_controls: tuple[ControlKind, ...] = (
        ControlKind.TEXT_PROMPT,
        ControlKind.CHARACTER_REFERENCE,
    ),
    submit: bool = False,
    comfy: ComfySpy | None = None,
):
    seed_world(db, world)
    preset_record = SimpleNamespace(preset_id="fake-quality-8step")
    preset_view = SimpleNamespace(
        preset_id=preset_record.preset_id,
        record=SimpleNamespace(
            tier=RenderTier.QUALITY_EIGHT_STEP,
            width=720,
            height=1280,
            fps=24,
        ),
        template=template,
        template_workflow_sha256=template_sha256(template),
    )
    catalog = SimpleNamespace(
        current_records=lambda: [preset_record],
        view=lambda _record: preset_view,
    )
    context = V2ReferencePreflightContext(
        episode_pack=world.pack,
        directing_manifest=world.directing,
        secret_ledger=v2_secret_ledger(),
        wardrobe_assignments=[world.assignment],
        wardrobe_bibles=[world.bible],
        style_bible=world.style_bible,
        asset_sheets=[world.identity, world.location, world.style],
        prop_sheets=[world.prop],
        location_layouts=[world.layout],
        resolve_current_rights=lambda *_: world.current_rights,
        verify_current_asset=lambda *_: None,
        territories=["TH"],
        style_subject_id="series",
        explicit_frames=world.frames,
        required_frame_roles=world.required_roles,
    )
    decision = SimpleNamespace(
        chosen=SimpleNamespace(preset_id=preset_record.preset_id),
        episode_id=world.pack.episode_id,
        manifest_version=1,
        attempt_number=1,
    )
    comfy = comfy or ComfySpy()
    dispatch_db = DirectingDb(db, world.directing)
    jobs = JobService(dispatch_db, FakeClock(AT), SequentialIds("t042a-keyframe"))
    attempt = dispatch_v2_routed_attempt(
        dispatch_db,
        comfy,
        jobs,
        decision=decision,
        shot=v1_shot(
            shot_id=SHOT_ID, prop_ids=("ledger",), duration_ms=15_000, controls=shot_controls
        ),
        catalog=catalog,
        episode_number=world.pack.episode_number,
        identity_lock_id=None,
        prompt_manifest_id=world.prompt.record_id,
        prompt_manifest_sha256=world.prompt.content_sha256,
        semantic_workflow_sha256=semantic_template_sha256(template),
        reference_context=context,
        dispatch_at=AT,
        submit=submit,
        still_inspector=inspector,
        read_frame_bytes=read_bytes,
    )
    return attempt, comfy, db


def render_job_count(db: Database) -> int:
    with db.transaction(readonly=True) as tx:
        return int(
            tx.fetchone("SELECT count(*) AS n FROM jobs WHERE job_type = 'render.shot'")["n"]
        )


def keyframe_event_count(db: Database, result_id) -> int:
    with db.transaction(readonly=True) as tx:
        return int(
            tx.fetchone(
                "SELECT count(*) AS n FROM domain_events WHERE aggregate_id = %s "
                "AND event_type = %s",
                (result_id, KEYFRAME_PREFLIGHT_EVENT),
            )["n"]
        )


def run(
    db: Database,
    world: SimpleNamespace,
    *,
    inspector=None,
    read_bytes=None,
    facts_by_role=None,
    template=MOCK_VIDEO_TEMPLATE,
):
    return run_keyframe_preflight(
        db,
        episode_id=world.pack.episode_id,
        shot_id=SHOT_ID,
        manifest=world.prompt,
        expected=world.expected,
        facts_by_role=facts_by_role or world.facts_by_role,
        required_frame_roles=world.required_roles,
        template=template,
        inspector=inspector,
        read_frame_bytes=read_bytes,
        at=AT,
    )


# --- clean pass ----------------------------------------------------------------------


def test_clean_observed_keyframes_pass_still_check_only(db: Database) -> None:
    world = build_world()
    inspector, calls = make_inspector(clean_observation(world))
    attempt, comfy, database = dispatch(
        db, world, inspector=inspector, read_bytes=frame_loader(world)
    )
    assert len(comfy.reserve_calls) == 1
    assert render_job_count(database) == 1
    assert comfy.submit_calls == []
    result = attempt.keyframe_preflight
    assert result is not None
    assert result.status is KeyframePreflightStatus.PASS
    # Still frames only: the receipt says so and certifies no motion.
    assert result.scope == "STILL_FRAME_ONLY"
    assert len(result.frames) == 3
    assert {frame.role for frame in result.frames} == set(FRAME_ROLES.values())
    for frame in result.frames:
        assert frame.outcome.value == "PASS"
        assert frame.bytes_checksum_verified is True
        assert {f.outcome for f in frame.findings} == {DimensionOutcome.MATCH}
    assert len(calls) == 3
    assert keyframe_event_count(database, result.result_id) == 1


def test_observer_receives_media_only_input(db: Database) -> None:
    world = build_world()
    inspector, calls = make_inspector(clean_observation(world))
    run(db, world, inspector=inspector, read_bytes=frame_loader(world))
    (frame,) = calls[:1]
    assert {field.name for field in fields(FrameAsset)} == {
        "asset_id",
        "asset_version",
        "asset_sha256",
        "payload",
    }
    assert frame.payload == world.frame_payloads["first"]
    # No intended fact, assignment, eyeline or prompt text rides along.
    text = repr(frame)
    assert "fon-apron" not in text
    assert EYELINE not in text
    assert world.prompt.prompt_text not in text


# --- blocking paths (never reserve, never submit) ------------------------------------


def test_stale_frame_hash_blocks_before_reserve(db: Database) -> None:
    world = build_world()
    inspector, _calls = make_inspector(clean_observation(world))
    with pytest.raises(KeyframePreflightFailed, match="keyframe preflight blocked"):
        dispatch(db, world, inspector=inspector, read_bytes=frame_loader(world, tamper=True))
    assert render_job_count(db) == 0


def test_frame_showing_unassigned_outfit_blocks_before_reserve(db: Database) -> None:
    """The frame wears an outfit the current assignment does not name."""
    world = build_world()
    observation = replace(clean_observation(world), outfit_by_character={"fon": "fon-raincoat-v9"})
    inspector, _calls = make_inspector(observation)
    with pytest.raises(KeyframePreflightFailed, match="keyframe preflight blocked"):
        dispatch(db, world, inspector=inspector, read_bytes=frame_loader(world))
    assert render_job_count(db) == 0


def test_known_identity_mismatch_blocks_before_reserve(db: Database) -> None:
    world = build_world()
    base = clean_observation(world)
    observation = replace(base, visible_subject_ids=frozenset({"fon", "lek"}))
    inspector, _calls = make_inspector(observation)
    with pytest.raises(KeyframePreflightFailed, match="keyframe preflight blocked"):
        dispatch(db, world, inspector=inspector, read_bytes=frame_loader(world))
    assert render_job_count(db) == 0


def test_missing_inspector_blocks_before_reserve(db: Database) -> None:
    world = build_world()
    with pytest.raises(KeyframePreflightFailed, match="keyframe preflight blocked"):
        dispatch(db, world, inspector=None, read_bytes=frame_loader(world))
    assert render_job_count(db) == 0


def test_unsupported_required_still_frame_control_blocks_before_reserve(
    db: Database,
) -> None:
    world = build_world()
    inspector, _calls = make_inspector(clean_observation(world))
    # The template check fires as either the missing semantic port or the
    # unsupported required control; both are typed and both precede reserve.
    with pytest.raises(UnsupportedControl, match="no semantic input|required render controls"):
        dispatch(
            db,
            world,
            inspector=inspector,
            read_bytes=frame_loader(world),
            template=NO_STILL_TEMPLATE,
            shot_controls=(
                ControlKind.TEXT_PROMPT,
                ControlKind.CHARACTER_REFERENCE,
                ControlKind.FIRST_FRAME,
            ),
        )
    assert render_job_count(db) == 0


def test_uncalibrated_dimension_is_unavailable_and_blocks(db: Database) -> None:
    world = build_world()
    dimensions = tuple(d for d in ALL_DIMENSIONS if d is not KeyframeDimension.LIGHT)
    inspector, _calls = make_inspector(clean_observation(world), dimensions=dimensions)
    result = run(db, world, inspector=inspector, read_bytes=frame_loader(world))
    assert result.status is KeyframePreflightStatus.UNKNOWN
    light = {f.dimension: f for frame in result.frames for f in frame.findings}[
        KeyframeDimension.LIGHT
    ]
    assert light.outcome is DimensionOutcome.UNAVAILABLE
    with pytest.raises(KeyframePreflightFailed):
        ensure_keyframe_preflight_allows_dispatch(result)
    with pytest.raises(KeyframePreflightFailed, match="keyframe preflight blocked"):
        dispatch(db, world, inspector=inspector, read_bytes=frame_loader(world))
    assert render_job_count(db) == 0


def test_below_threshold_confidence_is_unknown_and_blocks(db: Database) -> None:
    world = build_world()
    observation = clean_observation(world)
    observation = replace(
        observation,
        confidence_bp={
            **observation.confidence_bp,
            KeyframeDimension.LIGHT: 6_000,
        },
    )
    inspector, _calls = make_inspector(observation)
    result = run(db, world, inspector=inspector, read_bytes=frame_loader(world))
    assert result.status is KeyframePreflightStatus.UNKNOWN
    light = {f.dimension: f for frame in result.frames for f in frame.findings}[
        KeyframeDimension.LIGHT
    ]
    assert light.outcome is DimensionOutcome.UNKNOWN
    assert light.note == "observation confidence is below the calibrated threshold"
    with pytest.raises(KeyframePreflightFailed, match="keyframe preflight blocked"):
        dispatch(db, world, inspector=inspector, read_bytes=frame_loader(world))
    assert render_job_count(db) == 0


def test_unobserved_dimension_is_unknown_never_pass(db: Database) -> None:
    world = build_world()
    observation = replace(clean_observation(world), light_state=None)
    inspector, _calls = make_inspector(observation)
    result = run(db, world, inspector=inspector, read_bytes=frame_loader(world))
    assert result.status is KeyframePreflightStatus.UNKNOWN
    light = {f.dimension: f for frame in result.frames for f in frame.findings}[
        KeyframeDimension.LIGHT
    ]
    assert light.outcome is DimensionOutcome.UNKNOWN
    with pytest.raises(KeyframePreflightFailed):
        ensure_keyframe_preflight_allows_dispatch(result)


def test_bound_frames_on_stillless_route_is_unsupported(db: Database) -> None:
    world = build_world()
    inspector, _calls = make_inspector(clean_observation(world))
    with pytest.raises(UnsupportedControl, match="still-frame support"):
        run_keyframe_preflight(
            db,
            episode_id=world.pack.episode_id,
            shot_id=SHOT_ID,
            manifest=world.prompt,
            expected=world.expected,
            facts_by_role=world.facts_by_role,
            required_frame_roles=world.required_roles,
            template=NO_STILL_TEMPLATE,
            inspector=inspector,
            read_frame_bytes=frame_loader(world),
            at=AT,
        )


# --- NOT_APPLICABLE route ------------------------------------------------------------


def test_stillless_route_without_frames_records_not_applicable(db: Database) -> None:
    world = build_world(with_frames=False)
    attempt, comfy, database = dispatch(
        db, world, inspector=None, read_bytes=None, template=NO_STILL_TEMPLATE
    )
    assert len(comfy.reserve_calls) == 1
    assert render_job_count(database) == 1
    result = attempt.keyframe_preflight
    assert result is not None
    assert result.status is KeyframePreflightStatus.NOT_APPLICABLE
    assert result.frames == ()
    assert result.route_supports_still_frames is False
    ensure_keyframe_preflight_allows_dispatch(result)
    assert keyframe_event_count(database, result.result_id) == 1


# --- idempotent replay and invalidation ----------------------------------------------


def test_replay_uses_identical_evidence_without_reobservation(db: Database) -> None:
    world = build_world()
    inspector, calls = make_inspector(clean_observation(world))
    first = run(db, world, inspector=inspector, read_bytes=frame_loader(world))
    second = run(db, world, inspector=inspector, read_bytes=frame_loader(world))
    assert second == first
    assert len(calls) == 3  # three frames observed once; replay observed nothing
    assert keyframe_event_count(db, first.result_id) == 1


def test_restart_readback_returns_identical_evidence(db: Database, db_dsn: str) -> None:
    world = build_world()
    inspector, calls = make_inspector(clean_observation(world))
    first = run(db, world, inspector=inspector, read_bytes=frame_loader(world))
    restarted = Database(db_dsn, min_size=1, max_size=2).open()
    try:
        second = run(restarted, world, inspector=inspector, read_bytes=frame_loader(world))
    finally:
        restarted.close()
    assert second == first
    assert len(calls) == 3


def test_changed_source_invalidates_cached_result(db: Database) -> None:
    world = build_world()
    inspector, calls = make_inspector(clean_observation(world))
    first = run(db, world, inspector=inspector, read_bytes=frame_loader(world))
    changed_facts = {
        role: replace(facts, outfit_by_character={"fon": "fon-raincoat-v9"})
        for role, facts in world.facts_by_role.items()
    }
    second = run(
        db,
        world,
        inspector=inspector,
        read_bytes=frame_loader(world),
        facts_by_role=changed_facts,
    )
    assert second.result_id != first.result_id
    assert second.input_sha256 != first.input_sha256
    assert second.status is KeyframePreflightStatus.BLOCKED
    outfit = {f.dimension: f for frame in second.frames for f in frame.findings}[
        KeyframeDimension.OUTFIT
    ]
    assert outfit.outcome is DimensionOutcome.MISMATCH
    assert len(calls) == 6  # re-observed after the typed expectation changed


def test_evaluator_config_change_invalidates_cached_result(db: Database) -> None:
    world = build_world()
    inspector, calls = make_inspector(clean_observation(world), threshold_bp=7_500)
    first = run(db, world, inspector=inspector, read_bytes=frame_loader(world))
    recalibrated, calls2 = make_inspector(clean_observation(world), threshold_bp=9_000)
    second = run(db, world, inspector=recalibrated, read_bytes=frame_loader(world))
    assert second.result_id != first.result_id
    assert second.capability_sha256 != first.capability_sha256
    assert second.status is KeyframePreflightStatus.PASS
    assert len(calls) == 3
    assert len(calls2) == 3


def test_input_hash_covers_every_result_input() -> None:
    world = build_world()
    base = dict(
        episode_id=world.pack.episode_id,
        shot_id=SHOT_ID,
        prompt_manifest_sha256=world.prompt.content_sha256,
        route_template_sha256=semantic_template_sha256(MOCK_VIDEO_TEMPLATE),
        frame_specs=[
            (FRAME_ROLES[name], SHOT_ID, uid(f"t042a-frame-asset-{name}"), 1, sha256_hex(b"x"))
            for name in FRAME_NAMES
        ],
        evaluator=None,
        facts_by_role=world.facts_by_role,
        required_frame_roles=world.required_roles,
    )
    baseline = keyframe_preflight_input_sha256(**base)
    assert keyframe_preflight_input_sha256(**base) == baseline  # deterministic

    changed_frame = {**base, "frame_specs": base["frame_specs"][:2]}
    assert keyframe_preflight_input_sha256(**changed_frame) != baseline
    changed_manifest = {**base, "prompt_manifest_sha256": sha256_hex(b"other-manifest")}
    assert keyframe_preflight_input_sha256(**changed_manifest) != baseline
    # The selected route's semantic template hash (control/role ports included)
    # is a result input: a PASS can never be replayed for another route.
    changed_route = {**base, "route_template_sha256": semantic_template_sha256(NO_STILL_TEMPLATE)}
    assert keyframe_preflight_input_sha256(**changed_route) != baseline
    # Facts are hashed per frame role: moving one role's expectation moves the hash.
    changed_facts = {
        **base,
        "facts_by_role": {
            **world.facts_by_role,
            ReferenceRole.LAST_FRAME: replace(
                world.facts_by_role[ReferenceRole.LAST_FRAME], light_state="evening"
            ),
        },
    }
    assert keyframe_preflight_input_sha256(**changed_facts) != baseline
    changed_roles = {
        **base,
        "required_frame_roles": frozenset({ReferenceRole.FIRST_FRAME}),
    }
    assert keyframe_preflight_input_sha256(**changed_roles) != baseline
    inspector = StillMediaInspector(
        evaluator_id="fixture",
        evaluator_version="1",
        source_label="OFFLINE_FIXTURE",
        calibrated_threshold_bp={dimension: 7_500 for dimension in ALL_DIMENSIONS},
        observe=lambda _frame: StillFrameObservation(),
    )
    with_evaluator = {**base, "evaluator": inspector}
    assert keyframe_preflight_input_sha256(**with_evaluator) != baseline


def test_naive_evaluation_instant_is_refused(db: Database) -> None:
    world = build_world(with_frames=False)
    with pytest.raises(SchemaInvalid, match="aware evaluation instant"):
        run_keyframe_preflight(
            db,
            episode_id=world.pack.episode_id,
            shot_id=SHOT_ID,
            manifest=world.prompt,
            expected=world.expected,
            facts_by_role=world.facts_by_role,
            required_frame_roles=world.required_roles,
            template=MOCK_VIDEO_TEMPLATE,
            inspector=None,
            read_frame_bytes=None,
            at=datetime(2026, 10, 30, 12, 0),
        )


# --- per-boundary state expectations (mid-shot transitions) ---------------------------


def test_mid_shot_transition_compares_entry_and_exit_states(db: Database) -> None:
    """Holder, light and the ledger action change during the shot.

    The first frame must show the shot/scene entry state and the last and
    handoff frames the exit state, so a legitimate transition needs two
    deliberately different stills — never identical ones.
    """
    world = build_world(mid_shot_transition=True)
    # The typed expectations themselves differ per state boundary.
    entry = world.facts_by_role[ReferenceRole.FIRST_FRAME]
    assert entry.holder_by_prop == {"ledger": "fon"}
    assert entry.light_state == "morning"
    for role in (ReferenceRole.LAST_FRAME, ReferenceRole.HANDOFF_FRAME):
        exit_facts = world.facts_by_role[role]
        assert exit_facts.holder_by_prop == {"ledger": "lek"}
        assert exit_facts.light_state == "evening"
    observations = {name: transition_observation(world, name) for name in FRAME_NAMES}
    # A correct first frame and a correct last frame are different media.
    assert observations["first"].holder_by_prop != observations["last"].holder_by_prop
    assert observations["first"].light_state != observations["last"].light_state
    inspector, calls = make_frame_inspector(observations)
    result = run(db, world, inspector=inspector, read_bytes=frame_loader(world))
    assert result.status is KeyframePreflightStatus.PASS
    assert sorted(calls) == ["first", "handoff", "last"]
    for frame in result.frames:
        assert frame.outcome is FrameOutcome.PASS
        assert {finding.outcome for finding in frame.findings} == {DimensionOutcome.MATCH}
    ensure_keyframe_preflight_allows_dispatch(result)


def test_swapped_entry_exit_observations_block(db: Database) -> None:
    """First frame showing the exit state (and last the entry state) is a mismatch."""
    world = build_world(mid_shot_transition=True)
    observations = {name: transition_observation(world, name, swapped=True) for name in FRAME_NAMES}
    inspector, _calls = make_frame_inspector(observations)
    result = run(db, world, inspector=inspector, read_bytes=frame_loader(world))
    assert result.status is KeyframePreflightStatus.BLOCKED
    by_role = {frame.role: frame for frame in result.frames}

    first = {finding.dimension: finding for finding in by_role[ReferenceRole.FIRST_FRAME].findings}
    first_holder = first[KeyframeDimension.PROP_HOLDER]
    assert first_holder.outcome is DimensionOutcome.MISMATCH
    assert first_holder.expected == "ledger=fon"
    assert first_holder.observed == "ledger=lek"
    first_light = first[KeyframeDimension.LIGHT]
    assert first_light.outcome is DimensionOutcome.MISMATCH
    assert first_light.expected == "morning"
    assert first_light.observed == "evening"

    last = {finding.dimension: finding for finding in by_role[ReferenceRole.LAST_FRAME].findings}
    last_holder = last[KeyframeDimension.PROP_HOLDER]
    assert last_holder.outcome is DimensionOutcome.MISMATCH
    assert last_holder.expected == "ledger=lek"
    assert last_holder.observed == "ledger=fon"
    last_light = last[KeyframeDimension.LIGHT]
    assert last_light.outcome is DimensionOutcome.MISMATCH
    assert last_light.expected == "evening"
    assert last_light.observed == "morning"

    with pytest.raises(KeyframePreflightFailed, match="keyframe preflight blocked"):
        ensure_keyframe_preflight_allows_dispatch(result)


# --- route template binding (cache key and capability) --------------------------------


def test_changed_route_template_cannot_reuse_prior_pass(db: Database) -> None:
    """A PASS is bound to the route's semantic template hash, not just its frames."""
    world = build_world()
    inspector, calls = make_inspector(clean_observation(world))
    first = run(db, world, inspector=inspector, read_bytes=frame_loader(world))
    assert first.status is KeyframePreflightStatus.PASS
    # Same template id and still-frame capability, different semantic mapping:
    # only the semantic hash (control/role ports) moves.
    changed_template = replace(
        MOCK_VIDEO_TEMPLATE,
        semantic_role_ports=MappingProxyType(
            {**MOCK_VIDEO_TEMPLATE.semantic_role_ports, "prop": "prop_input_{subject}"}
        ),
    )
    assert semantic_template_sha256(changed_template) != semantic_template_sha256(
        MOCK_VIDEO_TEMPLATE
    )
    second = run(
        db,
        world,
        inspector=inspector,
        read_bytes=frame_loader(world),
        template=changed_template,
    )
    assert second.route_template_id == first.route_template_id
    assert second.input_sha256 != first.input_sha256
    assert second.result_id != first.result_id
    assert len(calls) == 6  # the prior PASS was not reused: every frame re-observed
    assert keyframe_event_count(db, first.result_id) == 1
    assert keyframe_event_count(db, second.result_id) == 1


def test_unsupported_route_cannot_replay_prior_pass_or_reserve(db: Database) -> None:
    """A stillless route is refused even when a still-capable route's PASS is on disk."""
    world = build_world()
    inspector, calls = make_inspector(clean_observation(world))
    first = run(db, world, inspector=inspector, read_bytes=frame_loader(world))
    assert first.status is KeyframePreflightStatus.PASS
    assert keyframe_event_count(db, first.result_id) == 1
    # Route capability is checked before any cached replay: the prior PASS was
    # recorded for a different route and can never wave this one through.
    with pytest.raises(UnsupportedControl, match="still-frame support"):
        run(
            db,
            world,
            inspector=inspector,
            read_bytes=frame_loader(world),
            template=NO_STILL_TEMPLATE,
        )
    assert len(calls) == 3  # nothing re-observed; nothing replayed
    assert keyframe_event_count(db, first.result_id) == 1
    # ...and through dispatch the stillless route never reaches a reserve.
    comfy = ComfySpy()
    with pytest.raises(
        UnsupportedControl, match="no semantic input|required render controls|still-frame support"
    ):
        dispatch(
            db,
            world,
            inspector=inspector,
            read_bytes=frame_loader(world),
            template=NO_STILL_TEMPLATE,
            comfy=comfy,
        )
    assert comfy.reserve_calls == []  # nothing was ever reserved for the stillless route
    assert render_job_count(db) == 0
    assert len(calls) == 3  # the prior PASS was still not reused
    assert keyframe_event_count(db, first.result_id) == 1


# --- single-flight durable evidence ----------------------------------------------------


def test_concurrent_identical_calls_append_one_event_and_agree(db: Database) -> None:
    """Two concurrent callers with identical inputs get one event, one identity.

    Both callers pass the initial "no recorded event" read before either can
    write: the barrier inside the observer pins them mid-observation, proving no
    DB lock is held over the inspector and that the append itself is
    single-flight.
    """
    world = build_world()
    observation = clean_observation(world)
    barrier = threading.Barrier(2, timeout=60)
    calls: list[FrameAsset] = []

    def observe(frame: FrameAsset) -> StillFrameObservation:
        calls.append(frame)
        barrier.wait()  # both callers observe before either may append
        return observation

    inspector = StillMediaInspector(
        evaluator_id="offline-fixture-inspector",
        evaluator_version="1",
        source_label="OFFLINE_FIXTURE",
        calibrated_threshold_bp={dimension: 7_500 for dimension in ALL_DIMENSIONS},
        observe=observe,
    )
    outcomes: list[KeyframePreflightResult | BaseException | None] = [None, None]

    def call(index: int) -> None:
        try:
            outcomes[index] = run(db, world, inspector=inspector, read_bytes=frame_loader(world))
        except BaseException as exc:  # surfaced by the assertions below
            outcomes[index] = exc

    threads = [threading.Thread(target=call, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert not any(thread.is_alive() for thread in threads), "a concurrent preflight hung"
    assert not any(isinstance(outcome, BaseException) for outcome in outcomes), [
        str(outcome) for outcome in outcomes
    ]
    first, second = outcomes
    assert isinstance(first, KeyframePreflightResult)
    assert isinstance(second, KeyframePreflightResult)
    assert first.status is KeyframePreflightStatus.PASS
    assert second == first  # one consistent result identity
    assert second.result_id == first.result_id
    assert keyframe_event_count(db, first.result_id) == 1  # exactly one durable event
    assert len(calls) == 6  # both callers observed; the loser's work is discarded
    # A sequential replay after the race still adds no second inspector call.
    replayed = run(db, world, inspector=inspector, read_bytes=frame_loader(world))
    assert replayed == first
    assert len(calls) == 6
    assert keyframe_event_count(db, first.result_id) == 1
