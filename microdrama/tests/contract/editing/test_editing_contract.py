"""Contract-level behaviour of the editing module (T015).

Pure tests pin the frozen surfaces this lane consumes and produces — the
``edit.assemble_episode`` job spec, the frozen ``EditDecisionList``/``CaptionTrack``
contracts the module writes, the DB rows it persists (edit_manifests/caption_tracks
constraints), and the Gate-2 releasability preconditions its outputs satisfy. The
frozen contract examples must round-trip through the module's own hashing and
serialization helpers.
"""

from __future__ import annotations

import pytest
from editing_support import World
from pydantic import ValidationError

from microdrama.contracts.enums import CaptionTimingSource, QueueName
from microdrama.contracts.examples import caption_track, edit_decision_list
from microdrama.contracts.jobs import JOB_SPECS_BY_TYPE
from microdrama.contracts.media import CaptionTrack, EditDecisionList
from microdrama.editing import (
    build_editing_service,
    edl_semantic_hash,
    srt_bytes,
    track_body_hash,
)

pytestmark = pytest.mark.ffmpeg


def test_the_frozen_job_spec_exists_and_is_owned_by_editing() -> None:
    spec = JOB_SPECS_BY_TYPE["edit.assemble_episode"]
    assert spec.owner_module == "editing"
    assert spec.queue is QueueName.PRODUCTION
    assert spec.paid is True  # frozen; the local pipeline runs free (open item noted)
    assert spec.input_model.__name__ == "EpisodeStepInput"
    variants = JOB_SPECS_BY_TYPE["edit.variants_and_hooks"]
    assert variants.owner_module == "editing"  # T016's surface already reserved


def test_frozen_edl_example_round_trips_the_module_hasher() -> None:
    example = edit_decision_list()
    assert edl_semantic_hash(example) == edl_semantic_hash(edit_decision_list())
    assert EditDecisionList.model_validate(example.model_dump(mode="json")) == example


def test_frozen_caption_example_round_trips_serialization() -> None:
    example = caption_track()
    again = CaptionTrack.model_validate(example.model_dump(mode="json"))
    assert track_body_hash(example) == track_body_hash(again)
    assert srt_bytes(example) == srt_bytes(again)
    assert b"\xef\xbb\xbf" not in srt_bytes(example)  # plain UTF-8, no BOM


def test_assembly_outputs_validate_as_the_frozen_contracts(world: World) -> None:
    episode_id, _season, assets = world.seed_prepared_episode()
    outcome = world.service.assemble_episode(episode_id, shot_assets=assets["shots"])
    edl_row = world.row("SELECT edl, edl_hash FROM edit_manifests WHERE id = %s", (outcome.edl_id,))
    edl = EditDecisionList.model_validate(edl_row["edl"])
    assert edl.edl_id == outcome.edl_id
    assert edl.duration_ms == outcome.duration_ms
    assert edl_semantic_hash(edl) == edl_row["edl_hash"]
    for locale in ("th-TH", "en-US"):
        row = world.row(
            "SELECT body, timing_source FROM caption_tracks WHERE episode_id = %s "
            "AND locale = %s AND state = 'CURRENT'",
            (episode_id, locale),
        )
        track = CaptionTrack.model_validate(row["body"])
        assert track.timing_source is CaptionTimingSource.ACTUAL_AUDIO_ALIGNMENT
        assert track.releasable is True
        assert row["timing_source"] == "ACTUAL_AUDIO_ALIGNMENT"


def test_caption_rows_satisfy_the_db_releasability_constraints(world: World) -> None:
    episode_id, _season, assets = world.seed_prepared_episode()
    world.service.assemble_episode(episode_id, shot_assets=assets["shots"])
    # The 0008/0010 Gate-2 helpers demand CURRENT + ACTUAL_AUDIO_ALIGNMENT for every
    # current track of the episode: the module's writes satisfy them by construction.
    current = world.rows(
        "SELECT timing_source FROM caption_tracks WHERE episode_id = %s AND state = 'CURRENT'",
        (episode_id,),
    )
    assert current
    assert all(r["timing_source"] == "ACTUAL_AUDIO_ALIGNMENT" for r in current)
    # And a releasable track cannot be built without naming its audio (frozen model).
    with pytest.raises(ValidationError, match="name the audio"):
        CaptionTrack(
            track_id=edit_decision_list().edl_id,
            episode_id=episode_id,
            version=99,
            locale="th-TH",
            timing_source=CaptionTimingSource.ACTUAL_AUDIO_ALIGNMENT,
            derived_from_audio_sha256=[],
            cues=caption_track().cues[:1],
        )


def test_module_writes_reject_stale_contract_versions(world: World) -> None:
    # The module writes only through the frozen models: a schema bump that changes
    # EditDecisionList/CaptionTrack breaks these tests before anything ships.
    with pytest.raises(ValidationError):
        CaptionTrack.model_validate(
            {**caption_track().model_dump(mode="json"), "schema_version": "2.0"}
        )
    with pytest.raises(ValidationError):
        EditDecisionList.model_validate(
            {**edit_decision_list().model_dump(mode="json"), "schema_version": "9.9"}
        )


def test_factory_signature_is_composition_root_friendly(db, object_store, offline_settings) -> None:
    from datetime import UTC, datetime

    from microdrama.budget import BudgetService
    from microdrama.testing.fakes import FakeClock, SequentialIds

    budget = BudgetService(
        db,
        FakeClock(datetime(2026, 10, 21, tzinfo=UTC)),
        SequentialIds("c-edit-budget"),
        offline_settings,
    )
    service = build_editing_service(
        db,
        FakeClock(datetime(2026, 10, 21, tzinfo=UTC)),
        SequentialIds("c-edit"),
        offline_settings,
        budget=budget,
        store=object_store,
    )
    assert service.config.output_width == 360
    assert callable(service.assemble_episode)
