"""T047 integration: independent V2 composed mock and fault acceptance.

Three composed proofs over real PostgreSQL and the REAL composed world:
(1) the production typed-expectations reader composes ``clean`` fixture truth
from current hash-verified V2 records + the current edit manifest, and the QA
run compares those record-derived expectations against actual exported media
(a deliberate records-vs-media token mismatch must surface as a REAL finding,
which proves the reader feeds the comparator genuine content both ways);
(2) the dispatch boundary gates — ``verify_current_asset`` (ACCEPTED row at
the exact version/hash AND live stored bytes) and the authoritative
rights-registry resolver — fail closed on every wrong shape;
(3) the composed release path on a season born through the three-step intake:
candidates → Gate 1 → production stages → owner metadata manifest → Gate 2 →
scheduled posts, with the workbench rendering current documents (the T037
closure evidence). Fixture labels are OFFLINE_FIXTURE_ONLY.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from test_t044b_gate2_owner_metadata import (
    CAPTION,
    CTA,
    DESCRIPTION,
    HASHTAGS,
    SLOT_TITLES,
    _form_chunk,
    _parse_metadata_form,
)
from validation_qa_support import (
    register_media_asset,
    seed_episode_with_script,
    seed_season_with_gate1,
)

from microdrama.api.app import AppComponents, create_app
from microdrama.contracts.enums import QAOutcome, SlotKind, TrackKind
from microdrama.contracts.errors import MicrodramaError
from microdrama.contracts.examples import (
    V2_T0,
    h,
    season_scope,
    uid,
    v2_character_logic,
    v2_directing_manifest,
    v2_directing_section,
    v2_directing_shot,
    v2_episode_pack,
    v2_rights,
    v2_secret_ledger,
    v2_story_time,
    v2_style_bible,
    v2_wardrobe_assignment,
)
from microdrama.contracts.examples import (
    shot as example_shot,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.jobs import EpisodeStepInput
from microdrama.contracts.media import EditDecisionList, EdlClip, OutputFormat
from microdrama.contracts.season import DialogueLine, Script
from microdrama.contracts.season import Scene as ScriptScene
from microdrama.contracts.v2 import (
    AssetSheet,
    EpisodeScene,
    LocationLayout,
    OutfitDefinition,
    PackBeat,
    PropSheet,
    ReferenceRole,
    StateValue,
    WardrobeBible,
    validate_current_rights_grant,
)
from microdrama.core.http import human_session_dependency
from microdrama.persistence import insert_row, jsonb
from microdrama.persistence.object_store import FilesystemObjectStore
from microdrama.pipeline.runner import MockPipelineRunner
from microdrama.qa.continuity import CHECK_SPECS, ContinuityDimension, ContinuityEvaluator
from microdrama.qa.continuity import FixtureContinuityObserver as _Observer
from microdrama.qa.continuity_sources import V2RecordContinuityExpectations
from microdrama.qa.report import load_run_check_coverage
from microdrama.qa.service import TechnicalQAService
from microdrama.references.v2_dispatch_context import (
    load_reference_context,
    make_registry_rights_resolver,
    make_verify_current_asset,
)
from microdrama.story.v2_store import StoryV2Store
from microdrama.testing.fakes import FakeClock, SequentialIds
from microdrama.testing.media import (
    FixtureTruthRegistry,
    clean_continuity_expectations,
    continuity_defect_suite,
    continuity_proof_text_sha256,
)

pytestmark = [pytest.mark.db]

T0 = datetime(2026, 11, 1, tzinfo=UTC)
GEO_STALL = h("t047-stall-geometry")
GEO_ROOM = h("t047-room-geometry")


def _sealed_new(model, name, **values):
    from microdrama.contracts.examples import V2_T0

    fields = {
        "record_id": uid(f"t047-{name}"),
        "version": 1,
        "created_at": V2_T0,
        "updated_at": V2_T0,
        "valid_from": V2_T0,
    }
    fields.update(values)
    return model.seal(**fields)


def _resealed(record, **updates):
    updated = record.model_copy(update=updates)
    if hasattr(type(updated), "seal"):  # V2 records must re-seal their hash
        fields = updated.model_dump(mode="python", exclude={"content_sha256"})
        return type(updated).seal(**fields)
    return type(updated).model_validate(updated.model_dump(mode="python"))


class _QAWorld:
    """The slice of a composed world ``register_media_asset`` reads."""

    def __init__(self, world) -> None:
        self.db = world.db
        self.store = world.store
        self.clock = world.fakes.clock
        self.ids = world.fakes.ids
        self.fakes = world.fakes


class V2TruthSeed:
    """Expresses the fixture continuity truth as current typed V2 records."""

    def __init__(self, world, season_id, episode_id, scope_hash: str, episode_number: int = 1):
        self.world = world
        self.season_id = season_id
        self.episode_id = episode_id
        self.scope_hash = scope_hash
        logic = [
            _resealed(v2_character_logic(), record_id=uid(f"t047-logic-{c}"), character_id=c)
            for c in ("fon", "lek", "nok")
        ]
        scenes = [
            EpisodeScene(
                scene_id="s1",
                scene_number=1,
                story_time=v2_story_time(),
                location_id="stall",
                visible_character_ids=["fon", "lek"],
                prop_ids=["prop-debt-note"],
                state_in=[
                    StateValue(
                        entity_id="prop-debt-note", field="holder_character_id", value="lek"
                    ),
                    StateValue(entity_id="prop-debt-note", field="holder_hand", value="right"),
                    StateValue(entity_id="stall", field="light", value="morning"),
                ],
                state_out=[
                    StateValue(
                        entity_id="prop-debt-note", field="holder_character_id", value="fon"
                    ),
                    StateValue(entity_id="prop-debt-note", field="holder_hand", value="left"),
                    StateValue(entity_id="stall", field="light", value="morning"),
                ],
                beats=[
                    PackBeat(
                        beat_id="beat-1",
                        function="revelation",
                        visible_action="The debt note changes hands.",
                    )
                ],
            ),
            EpisodeScene(
                scene_id="s2",
                scene_number=2,
                story_time=v2_story_time(),
                location_id="shophouse-room",
                visible_character_ids=["nok"],
                state_in=[StateValue(entity_id="shophouse-room", field="light", value="night")],
                state_out=[StateValue(entity_id="shophouse-room", field="light", value="night")],
                beats=[
                    PackBeat(
                        beat_id="beat-2",
                        function="turn",
                        visible_action="Nok listens at the door.",
                    )
                ],
            ),
        ]
        self.pack = _resealed(
            v2_episode_pack(),
            record_id=uid("t047-pack"),
            episode_id=episode_id,
            season_id=season_id,
            approved_scope_hash=self.scope_hash,
            episode_number=episode_number,
            character_logic=logic,
            scenes=scenes,
        )
        section = v2_directing_section()
        shot = v2_directing_shot()

        def shot_sources(scene, beat):
            return (
                [self.pack.record_id.hex, scene.scene_id, beat.beat_id],
                [
                    canonical_hash(scene.model_copy(update={"beats": []})),
                    canonical_hash(beat),
                ],
            )

        deps1, hashes1 = shot_sources(scenes[0], scenes[0].beats[0])
        deps2, hashes2 = shot_sources(scenes[1], scenes[1].beats[0])
        shots = [
            _resealed(
                shot,
                record_id=uid("t047-shot-1"),
                shot_id="shot-s1",
                sequence=1,
                scene_id="s1",
                beat_id="beat-1",
                section_id=section.section_id,
                duration_ms=3_800,
                eyeline="fon looks toward lek",
                action_handoff="lek passes the debt note to fon",
                framing="two_handed_dialogue",
                events=[],
                state_in=[],
                state_out=[],
                source_dependency_ids=deps1,
                source_hashes=hashes1,
            ),
            _resealed(
                shot,
                record_id=uid("t047-shot-2"),
                shot_id="shot-s2",
                sequence=2,
                scene_id="s2",
                beat_id="beat-2",
                section_id=section.section_id,
                duration_ms=1_200,
                eyeline="nok looks toward the door",
                action_handoff="nok steadies the door frame",
                framing="single_dialogue",
                events=[],
                state_in=[],
                state_out=[],
                source_dependency_ids=deps2,
                source_hashes=hashes2,
            ),
        ]
        manifest_sources = list(
            dict.fromkeys(
                [self.pack.content_sha256, *(sha for s in shots for sha in s.source_hashes)]
            )
        )
        self.manifest = _resealed(
            v2_directing_manifest(),
            record_id=uid("t047-directing"),
            episode_id=episode_id,
            pack_id=self.pack.record_id,
            pack_version=self.pack.version,
            pack_hash=self.pack.content_sha256,
            approved_scope_hash=self.scope_hash,
            source_hashes=manifest_sources,
            shots=shots,
            sections=[_resealed(section, shot_ids=["shot-s1", "shot-s2"], duration_ms=5_000)],
        )
        self.wardrobe_bibles = []
        self._outfit_sheets = []
        self.assignments = []
        for cid, outfit, setting in (
            ("fon", "outfit-fon-market-a", "stall"),
            ("lek", "outfit-lek-market-a", "stall"),
            ("nok", "outfit-nok-room-b", "shophouse-room"),
        ):
            sheet = next(
                item
                for item in [
                    _sealed_new(
                        AssetSheet,
                        f"sheet-outfit-{outfit}",
                        asset_role="outfit",
                        subject_id=outfit,
                        asset_id=uid(f"t047-asset-outfit-{outfit}"),
                        asset_version=1,
                        asset_sha256=h(f"t047-bytes-outfit-{outfit}"),
                        view_name="front",
                        rights=v2_rights(),
                        validity_from=V2_T0,
                    )
                ]
                for _ in [0]
            )
            bible = _sealed_new(
                WardrobeBible,
                f"bible-{cid}",
                season_id=season_id,
                character_id=cid,
                outfits=[
                    OutfitDefinition(
                        outfit_id=outfit,
                        version=1,
                        asset_id=sheet.asset_id,
                        asset_version=1,
                        asset_sha256=sheet.asset_sha256,
                        story_day_from=1,
                        setting_tags=[setting],
                        rights=v2_rights(),
                    )
                ],
            )
            self.wardrobe_bibles.append(bible)
            self._outfit_sheets.append(sheet)
            self.assignments.append(
                _resealed(
                    v2_wardrobe_assignment(),
                    record_id=uid(f"t047-wear-{cid}"),
                    episode_id=episode_id,
                    scene_id="s1" if setting == "stall" else "s2",
                    character_id=cid,
                    story_day=1,
                    setting=setting,
                    wardrobe_bible_id=bible.record_id,
                    wardrobe_bible_version=1,
                    outfit_id=outfit,
                    outfit_version=1,
                    asset_id=sheet.asset_id,
                    asset_version=1,
                    asset_sha256=sheet.asset_sha256,
                )
            )
        self.layouts = [
            _sealed_new(
                LocationLayout,
                "layout-stall",
                location_id="stall",
                geometry_sha256=GEO_STALL,
                entrance_ids=["front-door"],
                camera_zones=["counter"],
                light_states=["morning"],
                prop_ownership={"prop-debt-note": "lek"},
                rights=v2_rights(),
            ),
            _sealed_new(
                LocationLayout,
                "layout-room",
                location_id="shophouse-room",
                geometry_sha256=GEO_ROOM,
                entrance_ids=["door"],
                camera_zones=["bed"],
                light_states=["night"],
                rights=v2_rights(),
            ),
        ]
        self.prop_sheet = _sealed_new(
            PropSheet,
            "prop-note",
            prop_id="prop-debt-note",
            owner_character_id="lek",
            purpose="The debt note Fon must read.",
            visual_anchor="Folded cream paper with a red stamp.",
            dimensions="A5 folded",
            known_states=["folded", "open"],
            text_layer_sha256=continuity_proof_text_sha256(),
            asset_id=uid("t047-prop-asset"),
            asset_version=1,
            asset_sha256=h("t047-prop-image"),
            rights=v2_rights(),
        )
        self.asset_sheets = [
            _sealed_new(
                AssetSheet,
                f"sheet-{role}-{subject}",
                asset_role=role,
                subject_id=subject,
                asset_id=uid(f"t047-asset-{role}-{subject}"),
                asset_version=1,
                # A location sheet is minted from the same empty plate as its
                # LocationLayout (the production shape): the sheet's asset hash
                # IS the layout's geometry hash.
                asset_sha256=(
                    {"stall": GEO_STALL, "shophouse-room": GEO_ROOM}.get(subject)
                    if role == "location"
                    else None
                )
                or h(f"t047-bytes-{role}-{subject}"),
                view_name="front",
                rights=v2_rights(),
                validity_from=V2_T0,
            )
            for role, subject in (
                ("character_identity", "fon"),
                ("character_identity", "lek"),
                ("character_identity", "nok"),
                ("location", "stall"),
                ("location", "shophouse-room"),
            )
        ] + self._outfit_sheets
        # The style moving sample carries REAL stored bytes so the dispatch
        # asset gate's happy path (ACCEPTED row + exact version/hash + live
        # stored bytes) is provable through the loaded context (DB-6).
        from microdrama.contracts.hashing import sha256_hex

        self.style_bytes = b"t047-style-moving-sample-fixture-bytes"
        self.style = _resealed(
            v2_style_bible(),
            record_id=uid("t047-style"),
            season_id=season_id,
            moving_sample_sha256=sha256_hex(self.style_bytes),
        )
        self.style_sheet = _sealed_new(
            AssetSheet,
            "sheet-style",
            asset_role="style",
            subject_id="style",
            asset_id=self.style.moving_sample_asset_id,
            asset_version=1,
            asset_sha256=self.style.moving_sample_sha256,
            view_name="front",
            rights=self.style.rights,
            validity_from=V2_T0,
        )
        self.asset_sheets.append(self.style_sheet)
        self.secret = _resealed(
            v2_secret_ledger(), record_id=uid("t047-secrets"), season_id=season_id
        )
        self.script = Script(
            script_id=uuid.uuid4(),
            episode_id=episode_id,
            version=1,
            approved_scope_hash=self.scope_hash,
            canon_version=1,
            scenes=[
                ScriptScene(
                    scene_id="s1",
                    location_id="stall",
                    summary="The stall at dawn",
                    lines=[
                        DialogueLine(
                            line_id=f"s1-l{index}",
                            speaker_character_id=speaker,
                            text_th="เส้นทางของเรา",
                            text_en="our path",
                            estimated_duration_ms=2_000,
                        )
                        for index, speaker in enumerate(("fon", "lek"))
                    ],
                ),
                ScriptScene(
                    scene_id="s2",
                    location_id="shophouse-room",
                    summary="The room at night",
                    lines=[
                        DialogueLine(
                            line_id="s2-l1",
                            speaker_character_id="nok",
                            text_th="ประตูค้าง",
                            text_en="the door sticks",
                            estimated_duration_ms=2_000,
                        )
                    ],
                ),
            ],
            estimated_runtime_ms=7_600,
        )

    def save(self, *, with_edit_manifest: bool = True, with_script: bool = True) -> None:
        StoryV2Store(self.world.db).save_bundle(
            [
                self.pack,
                self.manifest,
                self.style,
                self.secret,
                self.prop_sheet,
                *self.assignments,
                *self.wardrobe_bibles,
                *self.layouts,
                *self.asset_sheets,
            ]
        )
        # Production pairs every AssetSheet/PropSheet with a registered asset row
        # (v2_planning.persist_generated): the season-scoped dispatch context
        # (DB-2) proves sheets through exactly those rows. The style sample
        # carries real stored bytes; the other sheets register synthetic rows.
        style_key = "t047/style-moving-sample"
        self.world.store.put_bytes(style_key, self.style_bytes, media_type="video/mp4")
        from microdrama.contracts.examples import media_info

        with self.world.db.transaction() as tx:
            for sheet in (*self.asset_sheets, self.prop_sheet):
                is_style = sheet is self.style_sheet
                insert_row(
                    tx,
                    "assets",
                    {
                        "id": sheet.asset_id,
                        "asset_kind": "VIDEO" if is_style else "IMAGE",
                        "object_key": style_key if is_style else f"t047/sheets/{sheet.asset_id}",
                        "sha256": sheet.asset_sha256,
                        "size_bytes": len(self.style_bytes) if is_style else 0,
                        "media_type": "video/mp4" if is_style else "application/octet-stream",
                        **({"media": jsonb(media_info())} if is_style else {}),
                        "state": "ACCEPTED",
                        "provenance": "ORIGINAL_FIXTURE",
                        "season_id": self.season_id,
                        "descriptor": jsonb({}),
                    },
                )
        with self.world.db.transaction() as tx:
            if with_script:
                insert_row(
                    tx,
                    "scripts",
                    {
                        "id": self.script.script_id,
                        "episode_id": self.episode_id,
                        "version": 1,
                        "canon_version": 1,
                        "body": jsonb(self.script),
                        "body_hash": canonical_hash(self.script),
                        "status": "CURRENT",
                    },
                )
                tx.execute(
                    "UPDATE episodes SET current_script_id = %s WHERE id = %s",
                    (self.script.script_id, self.episode_id),
                )
            if with_edit_manifest:
                edl = EditDecisionList(
                    edl_id=uuid.uuid4(),
                    episode_id=self.episode_id,
                    version=1,
                    purpose=SlotKind.FULL_EPISODE,
                    output=OutputFormat(width=1080, height=1920, fps_num=30),
                    clips=[
                        EdlClip(
                            clip_id="shot-s1.v",
                            track=TrackKind.VIDEO,
                            source_asset_id=uuid.uuid4(),
                            source_in_ms=0,
                            source_out_ms=3_800,
                            timeline_in_ms=0,
                        ),
                        EdlClip(
                            clip_id="shot-s2.v",
                            track=TrackKind.VIDEO,
                            source_asset_id=uuid.uuid4(),
                            source_in_ms=0,
                            source_out_ms=1_200,
                            timeline_in_ms=3_800,
                        ),
                    ],
                )
                insert_row(
                    tx,
                    "edit_manifests",
                    {
                        "id": edl.edl_id,
                        "episode_id": self.episode_id,
                        "purpose": "FULL_EPISODE",
                        "variant_key": "main",  # the production timeline lane
                        "version": 1,
                        "edl": jsonb(edl),
                        "edl_hash": canonical_hash(edl),
                        "state": "RENDERED",
                    },
                )


@pytest.fixture
def v2_episode(validation_world):
    """An episode whose current V2 records express the fixture continuity truth."""
    from microdrama.testing.media import _CONTINUITY_VOICES
    from microdrama.testing.seed import seed_episode

    world = validation_world
    season_id = uuid.uuid4()
    scope = season_scope().model_copy(
        update={
            "season_id": season_id,
            "scope_version": 1,
            "characters": [
                character.model_copy(
                    update={"voice_direction": _CONTINUITY_VOICES[character.character_id]}
                )
                for character in season_scope().characters
                if character.character_id in _CONTINUITY_VOICES
            ],
        }
    )
    scope_hash = canonical_hash(scope)
    from microdrama.testing.seed import seed_gate1_approval

    with world.db.transaction() as tx:
        approval = seed_gate1_approval(tx, season_id, scope_hash)
        insert_row(
            tx,
            "seasons",
            {
                "id": season_id,
                "state": "SEASON_APPROVED",
                "title_th": "ตัวอย่าง T047",
                "title_en": "T047 example",
                "approved_scope_version": 1,
                "approved_scope_hash": scope_hash,
                "approval_event_id": approval,
                "approved_at": T0,
            },
        )
        tx.execute(
            "INSERT INTO season_proposals (id, season_id, scope_version, scope, scope_hash,"
            " status) VALUES (%s, %s, 1, %s, %s, 'APPROVED')",
            (uid("t047-proposal"), season_id, jsonb(scope), scope_hash),
        )
        episode_id = seed_episode(tx, season_id, state="AI_REVIEW")
    seed = V2TruthSeed(world, season_id, episode_id, scope_hash)
    seed.save()
    return world, seed, episode_id


# --- (1) the production reader ----------------------------------------------------------


def test_production_reader_composes_typed_expectations_from_current_records(
    v2_episode,
) -> None:
    world, seed, episode_id = v2_episode
    got = V2RecordContinuityExpectations(world.db).continuity_expectations(episode_id)
    assert got is not None, "records + edit manifest compose real expectations"
    wanted = clean_continuity_expectations(episode_id)
    assert [w.scene_id for w in got.windows] == ["s1", "s2"]
    assert [(w.start_ms, w.end_ms) for w in got.windows] == [
        (w.start_ms, w.end_ms) for w in wanted.windows
    ]
    for got_window, wanted_window in zip(got.windows, wanted.windows, strict=True):
        assert got_window.visible_character_ids == wanted_window.visible_character_ids
        assert got_window.outfit_by_character == wanted_window.outfit_by_character
        assert got_window.holder_by_prop == wanted_window.holder_by_prop
        assert got_window.location_id == wanted_window.location_id
        # Geometry tokens cannot equal the fixture's free strings (the layout
        # contract pins a hex sha); the reader must carry the RECORD's token.
        assert got_window.geometry_token == (
            GEO_STALL if wanted_window.scene_id == "s1" else GEO_ROOM
        )
        assert got_window.eyeline == wanted_window.eyeline
        if wanted_window.action_handoff is not None:
            assert got_window.action_handoff == wanted_window.action_handoff
        else:
            # the directing contract always carries a handoff intent, so the
            # record defines the dimension where the fixture truth leaves it absent
            assert isinstance(got_window.action_handoff, str) and got_window.action_handoff
        assert got_window.proof_text_sha256_by_prop == wanted_window.proof_text_sha256_by_prop
        assert got_window.speaking_character_ids == wanted_window.speaking_character_ids
        assert got_window.voice_by_character == wanted_window.voice_by_character
        assert got_window.expects_subtitles == wanted_window.expects_subtitles
        # the record's framing Identifier is lowercase; the fixture labels are not
        assert got_window.shot_class == wanted_window.shot_class.lower()
        assert got_window.shot_id in ("shot-s1", "shot-s2")


def test_composed_qa_compares_record_expectations_against_actual_media(
    offline_settings, fixture_truth: FixtureTruthRegistry, tmp_path, v2_episode
) -> None:
    """The record-derived expectations enter REAL comparison against media.

    The seeded location geometry tokens are the record shas, the fixture media
    truth carries its own tokens — a genuine records-vs-media disagreement the
    comparison must surface as a LOCATION_SPACE finding (never silently pass),
    while the dimensions the records define are actually compared.
    """
    world, seed, episode_id = v2_episode
    suite = continuity_defect_suite(tmp_path / "t047-suite", fixture_truth)
    asset_id = register_media_asset(_QAWorld(world), episode_id, suite["clean"].path)
    service = TechnicalQAService(
        world.db,
        FakeClock(T0),
        SequentialIds("t047-qa"),
        offline_settings,
        budget=world.budget,
        store=world.store,
        continuity_observer=_Observer(
            fixture_truth,
            offline_settings,
            ContinuityEvaluator(
                "fixture-continuity", "1", "fixture-truth", {d: 9_000 for d in ContinuityDimension}
            ),
        ),
        continuity_expectations=V2RecordContinuityExpectations(world.db),
    )
    run = service.run_episode_qa(episode_id, asset_id=asset_id)
    # findings carry PASS rows as evidence; only non-PASS outcomes are defects
    finding_checks = {
        finding.check_id for finding in run.findings if finding.outcome != QAOutcome.PASS
    }
    identity = CHECK_SPECS[ContinuityDimension.IDENTITY].check_id
    outfit = CHECK_SPECS[ContinuityDimension.OUTFIT].check_id
    location = CHECK_SPECS[ContinuityDimension.LOCATION_SPACE].check_id
    assert location in finding_checks, "the token mismatch is a REAL finding"
    for check in (identity, outfit):
        assert check not in finding_checks, "clean dimensions stay clean"
    covered = load_run_check_coverage(world.db, episode_id, run.run_key)
    by_check: dict[str, list[str]] = {}
    for row in covered:
        by_check.setdefault(row.check_id, []).append(str(row.status))
    for check in (identity, outfit, location):
        assert "CHECKED" in by_check.get(check, []), f"{check}: the comparison ran"
    assert not ({identity, outfit, location} & set(run.unknown_check_ids)), (
        "record-defined dimensions are never unknown"
    )


def test_reader_fails_closed_on_stale_tampered_or_missing_records(v2_episode) -> None:
    world, seed, episode_id = v2_episode
    reader = V2RecordContinuityExpectations(world.db)
    baseline = reader.continuity_expectations(episode_id)
    assert baseline is not None

    # An invalidated timeline defines nothing: expectations unknown, never
    # invented (the table is append-only, so invalidation is the durable shape).
    with world.db.transaction() as tx:
        tx.execute(
            "UPDATE edit_manifests SET state = 'INVALIDATED' WHERE episode_id = %s",
            (episode_id,),
        )
    assert reader.continuity_expectations(episode_id) is None
    with world.db.transaction() as tx:  # restore the timeline (append-only table)
        tx.execute(
            "UPDATE edit_manifests SET state = 'RENDERED' WHERE episode_id = %s", (episode_id,)
        )
    assert reader.continuity_expectations(episode_id) is not None

    # A tampered wardrobe assignment (fresh row, stale hash) loses its outfit
    # dimension AND changes the expectations hash, so no cached QA run survives.
    original = seed.assignments[0]
    fields = original.model_dump(mode="python", exclude={"content_sha256"})
    fields.update(outfit_id="outfit-fon-market-z", version=original.version + 1)
    tampered = type(original).seal(**fields)
    with world.db.transaction() as tx:
        tx.execute(
            "UPDATE v2_contract_documents SET current = false "
            "WHERE contract_type = 'SceneWardrobeAssignment' AND record_id = %s",
            (original.record_id,),
        )
        insert_row(
            tx,
            "v2_contract_documents",
            {
                "contract_type": "SceneWardrobeAssignment",
                "record_id": original.record_id,
                "version": tampered.version,
                "payload": jsonb(tampered),
                "payload_sha256": original.content_sha256,  # the STALE hash
                "valid_from": tampered.valid_from,
                "current": True,
                "created_at": T0,
            },
        )
    degraded = reader.continuity_expectations(episode_id)
    assert degraded is not None
    s1 = next(w for w in degraded.windows if w.scene_id == "s1")
    assert s1.outfit_by_character.get("fon") is None, "stale-hash content is unreadable"
    assert degraded.expectations_sha256() != baseline.expectations_sha256()


def _clip(clip_id: str, *, timeline_in_ms: int, source_in_ms: int, source_out_ms: int) -> EdlClip:
    return EdlClip(
        clip_id=clip_id,
        track=TrackKind.VIDEO,
        source_asset_id=uuid.uuid4(),
        source_in_ms=source_in_ms,
        source_out_ms=source_out_ms,
        timeline_in_ms=timeline_in_ms,
    )


def _append_manifest_row(seed: V2TruthSeed, *, variant_key: str, version: int, state: str, clips) -> None:
    """Append one edit_manifests row (the table's durable supersede shape)."""
    edl = EditDecisionList(
        edl_id=uuid.uuid4(),
        episode_id=seed.episode_id,
        version=version,
        purpose=SlotKind.FULL_EPISODE,
        output=OutputFormat(width=1080, height=1920, fps_num=30),
        clips=clips,
    )
    with seed.world.db.transaction() as tx:
        insert_row(
            tx,
            "edit_manifests",
            {
                "id": edl.edl_id,
                "episode_id": seed.episode_id,
                "purpose": "FULL_EPISODE",
                "variant_key": variant_key,
                "version": version,
                "edl": jsonb(edl),
                "edl_hash": canonical_hash(edl),
                "state": state,
            },
        )


def test_reader_fails_closed_on_unmapped_or_dropped_video_clips(v2_episode) -> None:
    """DB-3: a VIDEO clip that does not map, or a window that would be dropped,
    makes the expectations incomplete — never a silent partial list."""
    world, seed, episode_id = v2_episode
    reader = V2RecordContinuityExpectations(world.db)
    assert reader.continuity_expectations(episode_id) is not None

    clean = [
        _clip("shot-s1.v", timeline_in_ms=0, source_in_ms=0, source_out_ms=3_800),
        _clip("shot-s2.v", timeline_in_ms=3_800, source_in_ms=0, source_out_ms=1_200),
    ]
    # An unmapped shot is the one dropped-window shape a CONTRACT-VALID EDL can
    # carry: EdlClip/EditDecisionList already reject empty windows (out <= in)
    # and overlapping timelines at model-validation time, so those reader
    # branches are defense-in-depth for rows that bypass validation. The
    # unmapped clip reaches the reader today — and used to be silently skipped.
    shapes = {
        "unmapped shot": [
            _clip("shot-s1.v", timeline_in_ms=0, source_in_ms=0, source_out_ms=3_800),
            _clip("shot-unknown.v", timeline_in_ms=3_800, source_in_ms=0, source_out_ms=1_200),
        ],
    }
    version = 2
    for label, clips in shapes.items():
        _append_manifest_row(
            seed, variant_key="main", version=version, state="RENDERED", clips=clips
        )
        got = reader.continuity_expectations(episode_id)
        assert got is None, f"{label}: expectations must be incomplete, never partial"
        # restore a clean newest row so the next shape is evaluated on its own
        _append_manifest_row(
            seed, variant_key="main", version=version + 1, state="RENDERED", clips=clean
        )
        version += 2


def test_reader_reads_only_the_current_main_variant_timeline(v2_episode) -> None:
    """DB-4: the timeline lane is variant_key='main'; the newest MAIN row governs.

    A higher-versioned derivative variant must never define the expectations,
    and a newest main row that is INVALIDATED means no usable timeline at all —
    the reader must not fall back to the older RENDERED row."""
    world, seed, episode_id = v2_episode
    reader = V2RecordContinuityExpectations(world.db)
    assert [w.scene_id for w in reader.continuity_expectations(episode_id).windows] == ["s1", "s2"]

    # A derivative variant at a much higher version with fewer clips: invisible.
    _append_manifest_row(
        seed,
        variant_key="tiktok-9x16",
        version=5,
        state="RENDERED",
        clips=[_clip("shot-s1.v", timeline_in_ms=0, source_in_ms=0, source_out_ms=3_800)],
    )
    still_main = reader.continuity_expectations(episode_id)
    assert still_main is not None, "a variant timeline never defines the main expectations"
    assert [w.scene_id for w in still_main.windows] == ["s1", "s2"]

    # The newest MAIN row invalidated: expectations unknown, never the old row's.
    _append_manifest_row(
        seed,
        variant_key="main",
        version=6,
        state="INVALIDATED",
        clips=[
            _clip("shot-s1.v", timeline_in_ms=0, source_in_ms=0, source_out_ms=3_800),
            _clip("shot-s2.v", timeline_in_ms=3_800, source_in_ms=0, source_out_ms=1_200),
        ],
    )
    assert reader.continuity_expectations(episode_id) is None


def test_dispatch_context_is_scoped_to_the_episodes_season(v2_episode) -> None:
    """DB-2: sheets and layouts from ANOTHER season sharing the same subject ids
    (the 'style' subject, a character id, a prop id, a location id) are
    invisible to this episode's dispatch context — provenance is the season's
    asset rows, the same approach as the T044b2 F2 workbench fix."""
    world, seed, episode_id = v2_episode
    foreign_season = uuid.uuid4()
    foreign_assets = [uid(f"t047-foreign-asset-{name}") for name in ("style", "fon", "prop")]

    def _foreign_asset_row(asset_id, tx) -> None:
        insert_row(
            tx,
            "assets",
            {
                "id": asset_id,
                "asset_kind": "IMAGE",
                "object_key": f"t047/foreign/{asset_id}",
                "sha256": h(f"t047-foreign-bytes-{asset_id}"),
                "size_bytes": 0,
                "media_type": "application/octet-stream",
                "state": "ACCEPTED",
                "provenance": "ORIGINAL_FIXTURE",
                "season_id": foreign_season,
                "descriptor": jsonb({}),
            },
        )

    with world.db.transaction() as tx:
        insert_row(
            tx,
            "seasons",
            {
                "id": foreign_season,
                "state": "PROPOSED",
                "title_th": "ฤดูกาลอื่นของคนอื่น",
                "title_en": "Another owner's foreign season",
            },
        )
        for asset_id in foreign_assets:
            _foreign_asset_row(asset_id, tx)

    foreign_docs = [
        # a style sheet sharing the global 'style' subject
        _sealed_new(
            AssetSheet,
            "foreign-sheet-style",
            asset_role="style",
            subject_id="style",
            asset_id=foreign_assets[0],
            asset_version=1,
            asset_sha256=h(f"t047-foreign-bytes-{foreign_assets[0]}"),
            view_name="front",
            rights=v2_rights(),
            validity_from=V2_T0,
        ),
        # a character sheet sharing the character id 'fon'
        _sealed_new(
            AssetSheet,
            "foreign-sheet-fon",
            asset_role="character_identity",
            subject_id="fon",
            asset_id=foreign_assets[1],
            asset_version=1,
            asset_sha256=h(f"t047-foreign-bytes-{foreign_assets[1]}"),
            view_name="front",
            rights=v2_rights(),
            validity_from=V2_T0,
        ),
        # a prop sheet sharing the prop id
        _sealed_new(
            PropSheet,
            "foreign-prop-note",
            prop_id="prop-debt-note",
            owner_character_id="lek",
            purpose="A foreign season's debt note.",
            visual_anchor="A different folded paper.",
            dimensions="A6 folded",
            known_states=["folded"],
            text_layer_sha256=h("t047-foreign-prop-text"),
            asset_id=foreign_assets[2],
            asset_version=1,
            asset_sha256=h(f"t047-foreign-bytes-{foreign_assets[2]}"),
            rights=v2_rights(),
        ),
        # a layout for the shared 'stall' location on ITS OWN plate geometry
        _sealed_new(
            LocationLayout,
            "foreign-layout-stall",
            location_id="stall",
            geometry_sha256=h("t047-foreign-stall-plate"),
            entrance_ids=["back-door"],
            camera_zones=["table"],
            light_states=["evening"],
            prop_ownership={},
            rights=v2_rights(),
        ),
    ]
    StoryV2Store(world.db).save_bundle(foreign_docs)

    context = load_reference_context(
        world.db,
        world.store,
        episode_id,
        resolve_current_rights=make_registry_rights_resolver(world.db),
        territories=["TH"],
    )
    assert {str(sheet.asset_id) for sheet in context.asset_sheets} == {
        str(sheet.asset_id) for sheet in seed.asset_sheets
    }, "foreign-season sheets sharing subjects must be invisible"
    assert [str(sheet.asset_id) for sheet in context.prop_sheets] == [
        str(seed.prop_sheet.asset_id)
    ], "the foreign prop sheet must not shadow the season's own"
    assert {layout.location_id for layout in context.location_layouts} == {
        "stall",
        "shophouse-room",
    }, "only layouts proven by THIS season's plates are visible"

    # And the episode's own dispatch binding still resolves end-to-end.
    dispatch_shot = example_shot("shot-s1", 1).model_copy(
        update={
            "scene_id": "s1",
            "location_id": "stall",
            "prop_ids": ["prop-debt-note"],
            "outfit_ids": [],
        }
    )
    assert context.expectations_for(dispatch_shot), "own references still bind"


def test_current_doc_ambiguity_fails_closed(v2_episode) -> None:
    """DB-5: two current records for one payload key are a typed ambiguity
    error, never a fetchone guess between them.

    The store allows this shape (uniqueness is one current row per record_id,
    not per payload key): a season can carry two distinct current records that
    both name it."""
    world, seed, episode_id = v2_episode
    duplicate = _resealed(seed.secret, record_id=uid("t047-secret-dupe"))
    with world.db.transaction() as tx:
        insert_row(
            tx,
            "v2_contract_documents",
            {
                "contract_type": "SecretLedger",
                "record_id": duplicate.record_id,
                "version": duplicate.version,
                "payload": jsonb(duplicate),
                "payload_sha256": duplicate.content_sha256,
                "valid_from": duplicate.valid_from,
                "current": True,
                "created_at": T0,
            },
        )
    with pytest.raises(MicrodramaError, match="ambiguous current SecretLedger"):
        load_reference_context(
            world.db,
            world.store,
            episode_id,
            resolve_current_rights=make_registry_rights_resolver(world.db),
            territories=["TH"],
        )


# --- (2) the dispatch-boundary gates ----------------------------------------------------


def test_verify_current_asset_fails_closed(
    db, offline_settings, fixture_truth: FixtureTruthRegistry, tmp_path
) -> None:
    class Bare:
        pass

    world = Bare()
    world.db = db
    world.store = FilesystemObjectStore(tmp_path / "t047-assets")
    world.clock = FakeClock(T0)
    world.ids = SequentialIds("t047-verify")

    class _Fakes:
        clock = world.clock
        ids = world.ids

    world.fakes = _Fakes()
    season = seed_season_with_gate1(db)
    episode = seed_episode_with_script(db, season)
    suite = continuity_defect_suite(tmp_path / "t047-verify-suite", fixture_truth)
    asset_id = register_media_asset(world, episode, suite["clean"].path)

    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT version, sha256, object_key FROM assets WHERE id = %s", (asset_id,)
        )
    version, sha = int(row["version"]), str(row["sha256"])

    verify = make_verify_current_asset(db, world.store)
    verify(asset_id, version, sha)  # the exact live shape passes

    # Each refusal names its own gate (DB-6), never an anonymous MicrodramaError.
    with pytest.raises(MicrodramaError, match="version is not the live version"):
        verify(asset_id, version + 1, sha)  # superseded version
    with pytest.raises(MicrodramaError, match="hash differs from the registered row"):
        verify(asset_id, version, "0" * 64)  # wrong hash
    with pytest.raises(MicrodramaError, match="asset does not exist"):
        verify(uuid.uuid4(), 1, sha)  # no such row
    with db.transaction() as tx:
        tx.execute("UPDATE assets SET state = 'SUPERSEDED' WHERE id = %s", (asset_id,))
    with pytest.raises(MicrodramaError, match="is not ACCEPTED"):
        verify(asset_id, version, sha)  # not ACCEPTED
    with db.transaction() as tx:
        tx.execute("UPDATE assets SET state = 'ACCEPTED' WHERE id = %s", (asset_id,))
    # The stored-bytes leg: a row whose registered sha is a lie about its
    # bytes (the store itself refuses key overwrites, so the lie is seeded as
    # a row — exactly the corruption the verifier exists to catch).
    from microdrama.contracts.hashing import sha256_hex

    lying_key = "t047/mismatched-bytes"
    world.store.put_bytes(lying_key, b"t047-actual-bytes", media_type="video/mp4")
    lying_sha = sha256_hex(b"t047-registered-but-wrong")
    lying_id = uuid.uuid4()
    with db.transaction() as tx:
        insert_row(
            tx,
            "assets",
            {
                "id": lying_id,
                "asset_kind": "OTHER",
                "object_key": lying_key,
                "sha256": lying_sha,
                "size_bytes": 4,
                "media_type": "video/mp4",
                "state": "ACCEPTED",
                "provenance": "ORIGINAL_FIXTURE",
                "season_id": season,
                "descriptor": jsonb({}),
            },
        )
    with pytest.raises(MicrodramaError, match="stored asset bytes do not hash"):
        verify(lying_id, 1, lying_sha)


def _seed_rights_row(
    db,
    grant,
    *,
    version: int,
    status: str,
    expires_at: datetime | None = None,
    territories: list[str] | None = None,
) -> None:
    with db.transaction() as tx:
        tx.execute(
            "UPDATE rights_registry SET current = false WHERE rights_route_id = %s"
            " AND subject_kind = %s AND subject_ref = %s",
            (grant.rights_route_id, grant.subject_kind.value, grant.subject_ref),
        )
        insert_row(
            tx,
            "rights_registry",
            {
                "id": uuid.uuid4(),
                "rights_route_id": grant.rights_route_id,
                "version": version,
                "subject_kind": grant.subject_kind.value,
                "subject_ref": grant.subject_ref,
                "territories": jsonb(territories or ["TH"]),
                "commercial_use": True,
                "output_release_allowed": True,
                "required_disclosures": jsonb([]),
                "expires_at": expires_at,
                "evidence": jsonb([{"source": "FAKE_FIXTURE", "ref": "t047-seeded-evidence"}]),
                "status": status,
                "current": True,
            },
        )


def test_registry_resolver_and_context_gate_rights_and_references(v2_episode) -> None:
    world, seed, episode_id = v2_episode
    resolver = make_registry_rights_resolver(world.db)
    grant = v2_rights()
    # Absent registry subject: fail closed before any dispatch, and the error
    # names the gate that fired (DB-6 — each case asserts its own message).
    with pytest.raises(ValueError, match="no current rights registry record"):
        validate_current_rights_grant(grant, resolver, at=T0, territories=["TH"])
    _seed_rights_row(world.db, grant, version=1, status="ELIGIBLE")
    record = validate_current_rights_grant(grant, resolver, at=T0, territories=["TH"])
    assert record.status.value == "ELIGIBLE"
    # A non-eligible current version (the registry's revocation shapes are
    # INELIGIBLE/UNKNOWN — no REVOKED status exists): the grant dies with it.
    # Each case's grant carries the CURRENT row's version, so the status gate —
    # not the subject/version gate — is the one that fires.
    _seed_rights_row(world.db, grant, version=2, status="INELIGIBLE")
    grant_v2 = grant.model_copy(update={"rights_version": 2})
    with pytest.raises(ValueError, match="record is not eligible"):
        validate_current_rights_grant(grant_v2, resolver, at=T0, territories=["TH"])
    # An ELIGIBLE record whose expiry has since passed: expired is expired.
    # (The contract refuses to RECORD an already-expired ELIGIBLE row, so the
    # row expires after its recording date and validation runs later still.)
    passed = datetime(2026, 12, 1, tzinfo=UTC)
    _seed_rights_row(world.db, grant, version=3, status="ELIGIBLE", expires_at=passed)
    grant_v3 = grant.model_copy(update={"rights_version": 3, "expires_at": passed})
    with pytest.raises(ValueError, match="record has expired"):
        validate_current_rights_grant(
            grant_v3, resolver, at=datetime(2027, 1, 1, tzinfo=UTC), territories=["TH"]
        )
    # An ELIGIBLE, unexpired record that does not cover the requested territory.
    _seed_rights_row(world.db, grant, version=4, status="ELIGIBLE", territories=["TH"])
    grant_v4 = grant.model_copy(update={"rights_version": 4})
    with pytest.raises(ValueError, match="does not cover requested territories"):
        validate_current_rights_grant(grant_v4, resolver, at=T0, territories=["US"])
    # The clean ACCEPTED shape passes (status back to a plain ELIGIBLE row).
    _seed_rights_row(world.db, grant, version=5, status="ELIGIBLE")
    grant_v5 = grant.model_copy(update={"rights_version": 5})
    clean = validate_current_rights_grant(grant_v5, resolver, at=T0, territories=["TH"])
    assert clean.status.value == "ELIGIBLE"

    context = load_reference_context(
        world.db,
        world.store,
        episode_id,
        resolve_current_rights=resolver,
        territories=["TH"],
    )
    dispatch_shot = example_shot("shot-s1", 1).model_copy(
        update={
            "scene_id": "s1",
            "location_id": "stall",
            "prop_ids": ["prop-debt-note"],
            "outfit_ids": [],
        }
    )
    expected = context.expectations_for(dispatch_shot)
    assert expected, "the composed context resolves reference expectations"
    subjects = {subject for _role, subject in expected}
    assert "stall" in subjects, "the scene location is a bound reference subject"
    # The context's asset gate is the wired fail-closed verifier, and each
    # refusal names its gate (DB-6). The character sheet's asset row has no
    # stored bytes, so the stored-bytes leg is the one that refuses.
    fon_reference = expected[(ReferenceRole.CHARACTER_IDENTITY, "fon")]
    with pytest.raises(MicrodramaError, match="not found"):
        context.verify_current_asset(
            fon_reference.asset_id,
            int(fon_reference.asset_version),
            fon_reference.asset_sha256,
        )
    # The happy path through the LOADED context: the style moving sample is an
    # ACCEPTED row at the exact version/hash whose live stored bytes hash to
    # the registered sha256 — the gate passes (DB-6).
    context.verify_current_asset(seed.style_sheet.asset_id, 1, seed.style_sheet.asset_sha256)


# --- (3) the intake-born composed release path (T037 closure evidence) ------------------


def _sign_in_as(client, username: str, password: str) -> str:
    page = client.get("/auth/login")
    token = re.search(r'name="login_csrf" value="([^"]+)"', page.text).group(1)
    response = client.post(
        "/auth/login",
        data={"username": username, "password": password, "login_csrf": token},
    )
    assert response.status_code == 303, response.text
    csrf = client.cookies.get("md_csrf")
    assert csrf
    return csrf


def _candidate_payload() -> dict:
    def one(title_en: str) -> dict:
        return {
            "title_th": f"ฤดูกาลของ {title_en}",
            "title_en": title_en,
            "logline": f"An original season about {title_en.lower()} told in Thai.",
            "premise": "เรื่องเดิมที่แต่งขึ้นใหม่ทั้งหมดเกี่ยวกับครอบครัวและร้านอาหารของยาย",
            "genre_tags": ["family-drama"],
            "originality_statement": "Original fiction; no real persons or existing works imitated.",
            "arc": [
                {
                    "episode_number": episode,
                    "summary": f"จุดเปลี่ยนของเรื่องตอนที่ {episode}",
                    "planned_reveals": [] if episode != 2 else ["ความลับที่วางแผนไว้"],
                    "cliffhanger": "ใครบางคนมาถึง" if episode == 5 else None,
                }
                for episode in range(1, 6)
            ],
            "characters": [
                {
                    "character_id": "fon",
                    "name_th": "ฝน",
                    "name_en": "Fon",
                    "role": "daughter",
                    "description": "A resourceful daughter.",
                    "voice_direction": "Warm, quick delivery.",
                    "featured": True,
                },
                {
                    "character_id": "lek",
                    "name_th": "ลุงเล็ก",
                    "name_en": "Uncle Lek",
                    "role": "cook",
                    "description": "The stall cook hiding guilt.",
                    "voice_direction": "Low, gentle.",
                    "featured": True,
                },
                {
                    "character_id": "nok",
                    "name_th": "นก",
                    "name_en": "Nok",
                    "role": "neighbor",
                    "description": "The neighbor who knows more than she says.",
                    "voice_direction": "Bright, quick.",
                    "featured": True,
                },
            ],
        }

    return {"candidates": [one("The Last Market"), one("Uncle Lek's Shop")]}


def test_intake_born_season_reaches_gate2_manifest_and_scheduled_release(
    validation_world,
) -> None:
    from microdrama.review.intake import (
        INTAKE_GENERATION_KEY,
        IntakeAnswers,
        intake_record_id,
    )

    world = validation_world
    runner = MockPipelineRunner(
        world, owner_username="t047-owner", owner_password="t047-not-a-real-password"
    )
    ack = world.intake.submit(
        runner.human,
        answers=IntakeAnswers(
            story_idea="ร้านข้าวต้มของยายที่ลูกสาวต้องสู้รักษาไว้",
            genre_tags=("family-drama",),
            tone="อบอุ่นแต่ตึงเครียด",
            episode_count=5,
        ),
        key="t047-intake-key-1",
    )
    assert ack.status_code == 202
    season_id = uuid.UUID(ack.body["season_id"])
    # Token-script the generation (role-scripting would hijack the story
    # writer, which shares RuntimeRole.STORY_ARCHITECT with the Script Maker).
    world.fakes.llm.script_token(
        f"script-maker:{season_id}:{intake_record_id(season_id)}:{INTAKE_GENERATION_KEY}:t1",
        _candidate_payload(),
    )

    def _drain_intake() -> None:
        from microdrama.review.intake import INTAKE_JOB_TYPE

        while True:
            job = world.jobs.claim("production", worker_id="t047-worker", lease_ms=60_000)
            if job is None:
                break
            assert job.job_type == INTAKE_JOB_TYPE
            context = world.jobs.context(job, "t047-worker")
            outcome = world.intake.handle_research_job(context)
            assert outcome is not None
            world.jobs.finish(job.id, worker_id="t047-worker", outcome=outcome)

    _drain_intake()
    view = world.intake.status(runner.human, season_id)
    assert view.phase == "CANDIDATES_READY" and view.candidates
    chosen = view.candidates[0]
    if not chosen.is_current_proposal:
        world.intake.select(
            runner.human, season_id, chosen.record_id, intake_sha256=view.intake_sha256
        )
        _drain_intake()
    # The season was born through the intake: creator-linked at creation.
    owner_row = runner._row("SELECT source FROM season_owners WHERE season_id = %s", (season_id,))
    assert owner_row["source"] == "CREATOR_AT_CREATION"

    runner.gate1(season_id)
    runner.w02_compile(season_id)
    episode_id = runner.create_episode(season_id, number=1)

    runner.w03_write(episode_id)
    runner.w04_references(episode_id)
    runner.w05_render(episode_id)
    runner.w06_edit(episode_id)
    runner.w07_qa(episode_id)
    runner._enqueue(
        "review.prepare_package",
        EpisodeStepInput(episode_id=episode_id),
        episode_id=episode_id,
        semantic_key=f"review.prepare_package:{episode_id}:1",
    )
    runner._drain()
    assert runner._row("SELECT state FROM episodes WHERE id = %s", (episode_id,))["state"] == (
        "AWAITING_FINAL_REVIEW"
    )

    # The workbench renders the intake-born season's current documents. The
    # router must be built WITH the intake service (the wizard/workbench routes
    # exist only in that composition).
    from microdrama.review import build_router

    router = build_router(
        world.review,
        human_session=human_session_dependency(world.auth),
        auth=world.auth,
        cookie_secure=False,
        intake=world.intake,
    )
    client = TestClient(
        create_app(AppComponents(settings=world.settings, routers=[router])),
        follow_redirects=False,
    )
    csrf = _sign_in_as(client, "t047-owner", "t047-not-a-real-password")
    assert client.get(f"/ui/seasons/{season_id}/workbench").status_code == 200

    # Owner metadata → sealed manifest → the EXISTING Gate 2 binds its hash.
    world.memberships.catalog.record_not_released(
        season_id=season_id, episode_id=episode_id, episode_number=1
    )
    parsed = _parse_metadata_form(client.get(f"/ui/episodes/{episode_id}").text)
    assert len(parsed["slots"]) >= 2
    approvals_before = runner._row("SELECT count(*) AS n FROM approval_events")["n"]
    pairs: list[tuple[str, object]] = [
        ("csrf_token", csrf),
        ("package_hash", parsed["package_hash"]),
        ("policy_mutable_fields", "title"),
        ("policy_cooldown_hours", "24"),
        ("policy_max_substantive_edits", "2"),
    ]
    for slot in parsed["slots"]:
        sid = slot["slot_id"]
        title = SLOT_TITLES[slot["platform"].upper()]
        pairs += [
            ("md_slot", sid),
            (f"md_{sid}_title", title),
            (f"md_{sid}_caption", CAPTION),
            (f"md_{sid}_description", DESCRIPTION),
            (f"md_{sid}_hashtags", HASHTAGS),
            (f"md_{sid}_links", ""),
            (f"md_{sid}_cta", CTA),
        ]
        pairs += [(f"md_{sid}_disclosures", value) for value in slot["disclosures"]]
    body: dict[str, object] = {}
    for key, value in pairs:
        if key in body:
            current = body[key]
            body[key] = [*current, value] if isinstance(current, list) else [current, value]
        else:
            body[key] = value
    response = client.post(f"/ui/episodes/{episode_id}/metadata", data=body)
    assert response.status_code == 303, response.text
    assert runner._row("SELECT count(*) AS n FROM approval_events")["n"] == approvals_before

    manifest_row = runner._row(
        "SELECT payload FROM release_approval_manifests WHERE release_package_hash = %s "
        "ORDER BY created_at DESC LIMIT 1",
        (parsed["package_hash"],),
    )
    manifest = manifest_row["payload"]
    assert manifest["slots"], "the prepared manifest carries owner metadata"

    approve = _form_chunk(client.get(f"/ui/episodes/{episode_id}").text, "approve-form")
    fields = [
        (m.group(1), m.group(2))
        for m in re.finditer(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', approve)
    ]
    assert dict(fields)["release_manifest_hash"] == manifest["approval_manifest_sha256"]
    fields += [("action", "APPROVE"), ("idempotency_key", f"gate2:{episode_id}:t047")]
    approve_body: dict[str, object] = {}
    for key, value in fields:
        if key in approve_body:
            current = approve_body[key]
            approve_body[key] = [*current, value] if isinstance(current, list) else [current, value]
        else:
            approve_body[key] = value
    response = client.post(f"/ui/episodes/{episode_id}/review", data=approve_body)
    assert response.status_code == 303, response.text
    assert runner._row("SELECT state FROM episodes WHERE id = %s", (episode_id,))["state"] == (
        "RELEASE_APPROVED"
    )
    runner._drain()
    posts = runner._rows("SELECT * FROM platform_posts WHERE episode_id = %s", (episode_id,))
    assert posts, "the scheduler created slot posts"
    assert {post["state"] for post in posts} == {"SCHEDULED"}
    assert all(post["provider_operation_id"] is None for post in posts)
    assert (
        runner._row(
            "SELECT count(*) AS n FROM provider_operations WHERE operation_kind LIKE 'publish.%%'"
        )["n"]
        == 0
    ), "no transport was opened"
