"""Invalidation tests (T015): source-line replacement invalidates associated cues.

A replaced line's audio asset changes the sha the caption track was derived from;
exactly that line's cues are invalidated (never a blunt whole-track wipe), the old
EDL row flips INVALIDATED, and identical re-assemblies replay without re-export.
"""

from __future__ import annotations

import uuid

import pytest
from editing_support import LINES, World

from microdrama.contracts.hashing import canonical_hash
from microdrama.editing.models import AssemblyStatus
from microdrama.persistence import insert_row, jsonb
from microdrama.references.anchors import ref_id_for

pytestmark = pytest.mark.ffmpeg

REPLACEMENT_TEXT = "ลุงเล็ก ร้านจะเปิดพรุ่งนี้ค่ะ"
REPLACED_LINE = "sc1-l1"
REPLACEMENT_MS = 1_400


def _assemble(world: World):
    episode_id, _season, assets = world.seed_prepared_episode()
    outcome = world.service.assemble_episode(episode_id, shot_assets=assets["shots"])
    return episode_id, assets, outcome


def _replace_line(
    world: World,
    episode_id: uuid.UUID,
    *,
    text: str = REPLACEMENT_TEXT,
    ms: int = REPLACEMENT_MS,
    register_audio: bool = True,
) -> None:
    """A source-line replacement, T019 style: new script version + new audio asset.

    ``register_audio=False`` swaps the script back to text whose audio asset already
    exists (the replace-back path).
    """
    script = world.service.script(episode_id)
    new_lines = []
    for scene in script.scenes:
        for line in scene.lines:
            new_lines.append(
                (line.line_id, line.speaker_character_id, line.text_th, line.actual_duration_ms)
            )
    new_lines = [
        (lid, spk, text if lid == REPLACED_LINE else t, ms if lid == REPLACED_LINE else d)
        for lid, spk, t, d in new_lines
    ]
    from editing_support import build_manifest, build_script

    new_script = build_script(episode_id, new_lines)
    new_script = new_script.model_copy(
        update={"version": script.version + 1, "script_id": uuid.uuid4()}
    )
    new_manifest = build_manifest(episode_id, new_script).model_copy(
        update={
            "version": world.service.manifest(episode_id).version + 1,
            "script_id": new_script.script_id,
            "script_version": new_script.version,
            "manifest_id": uuid.uuid4(),
        }
    )
    season_id = world.row("SELECT season_id FROM episodes WHERE id = %s", (episode_id,))[
        "season_id"
    ]
    # New measured audio asset for the replaced line (new text -> new deterministic id).
    from microdrama.testing.media import FixtureTruth, SpokenTruth, make_wav_bytes

    if register_audio:
        tone = 440 + sum(ord(ch) for ch in f"{REPLACED_LINE}:{text}") % 400
        data = make_wav_bytes(ms, tone)
        asset_id = ref_id_for(
            "line-audio",
            f"{episode_id}:{REPLACED_LINE}:{canonical_hash(text)[:12]}",
        )
        stored = world.store.put_bytes(
            f"episodes/{episode_id}/dialogue/{REPLACED_LINE}-replaced-{ms}.wav",
            data,
            media_type="audio/wav",
        )
        import tempfile
        from pathlib import Path

        from microdrama.contracts.enums import AssetKind, AssetState, Provenance
        from microdrama.contracts.media import AssetDescriptor
        from microdrama.persistence import register_asset
        from microdrama.testing.media import probe

        with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
            tmp.write(data)
            tmp.flush()
            media = probe(Path(tmp.name))
        with world.db.transaction() as tx:
            register_asset(
                tx,
                AssetDescriptor(
                    asset_id=asset_id,
                    asset_kind=AssetKind.AUDIO,
                    object_key=stored.key,
                    sha256=stored.sha256,
                    size_bytes=stored.size_bytes,
                    media_type="audio/wav",
                    media=media,
                    state=AssetState.ACCEPTED,
                    provenance=Provenance.ORIGINAL_FIXTURE,
                    episode_id=episode_id,
                    season_id=season_id,
                    created_at=world.clock.now(),
                ),
            )
            world.truth.register(
                stored.sha256,
                FixtureTruth(
                    fixture_id=f"line-audio:{REPLACED_LINE}:replaced",
                    duration_ms=ms,
                    has_audio=True,
                    has_video=False,
                    spoken=(
                        SpokenTruth(
                            start_ms=0,
                            end_ms=ms,
                            text_th=text,
                            speaker_id="fon",
                        ),
                    ),
                    identities=(),
                    text_items=(),
                    video_defects=(),
                    covered_ranges_ms=((0, ms),),
                ),
            )
    with world.db.transaction() as tx:
        tx.execute(
            "UPDATE scripts SET status = 'SUPERSEDED', revision = revision + 1 "
            "WHERE episode_id = %s AND status = 'CURRENT'",
            (episode_id,),
        )
        tx.execute(
            "UPDATE shot_manifests SET status = 'SUPERSEDED', revision = revision + 1 "
            "WHERE episode_id = %s AND status = 'CURRENT'",
            (episode_id,),
        )
        insert_row(
            tx,
            "scripts",
            {
                "id": new_script.script_id,
                "episode_id": episode_id,
                "version": new_script.version,
                "canon_version": 1,
                "body": jsonb(new_script),
                "body_hash": canonical_hash(new_script),
                "status": "CURRENT",
            },
        )
        insert_row(
            tx,
            "shot_manifests",
            {
                "id": new_manifest.manifest_id,
                "episode_id": episode_id,
                "script_id": new_script.script_id,
                "version": new_manifest.version,
                "identity_lock_id": None,
                "body": jsonb(new_manifest),
                "body_hash": canonical_hash(new_manifest),
                "status": "CURRENT",
            },
        )
        tx.execute(
            "UPDATE episodes SET current_script_id = %s, current_manifest_id = %s WHERE id = %s",
            (new_script.script_id, new_manifest.manifest_id, episode_id),
        )


def _back_to_assembling(world: World, episode_id: uuid.UUID) -> None:
    """QA repair returns the episode to ASSEMBLING (the repair-stage transition)."""
    row = world.row("SELECT revision FROM episodes WHERE id = %s", (episode_id,))
    with world.db.transaction() as tx:
        tx.execute(
            "UPDATE episodes SET state = 'ASSEMBLING', revision = revision + 1 WHERE id = %s",
            (episode_id,),
        )
    del row


def test_line_replacement_invalidates_exactly_the_associated_cues(world: World) -> None:
    episode_id, assets, first = _assemble(world)
    assert first.invalidated_cue_ids == []
    _replace_line(world, episode_id)
    # Before re-assembly the stale-cue query already names the line's cues.
    stale = world.service.stale_caption_cues(episode_id)
    assert stale == [f"{REPLACED_LINE}.enus", f"{REPLACED_LINE}.thth"]
    _back_to_assembling(world, episode_id)
    second = world.service.assemble_episode(episode_id, shot_assets=assets["shots"])
    assert second.status is AssemblyStatus.ASSEMBLED
    assert second.invalidated_cue_ids == [f"{REPLACED_LINE}.enus", f"{REPLACED_LINE}.thth"]
    # Old tracks are INVALIDATED (source changed), new CURRENT tracks carry the new text.
    rows = world.rows(
        "SELECT locale, version, state, body FROM caption_tracks WHERE episode_id = %s "
        "ORDER BY locale, version",
        (episode_id,),
    )
    old_th = next(r for r in rows if r["locale"] == "th-TH" and r["version"] == 1)
    new_th = next(r for r in rows if r["locale"] == "th-TH" and r["version"] == 2)
    assert old_th["state"] == "INVALIDATED"
    assert new_th["state"] == "CURRENT"
    replaced_cue = next(c for c in new_th["body"]["cues"] if c["line_id"] == REPLACED_LINE)
    assert replaced_cue["text"] == REPLACEMENT_TEXT
    # Unchanged lines' cues survived into the new track untouched.
    kept = {c["line_id"]: c["text"] for c in new_th["body"]["cues"]}
    assert kept["sc1-l2"].startswith("เปิดได้")
    # The old EDL row is INVALIDATED; the new one is RENDERED v2.
    manifests = world.rows(
        "SELECT version, state FROM edit_manifests WHERE episode_id = %s ORDER BY version",
        (episode_id,),
    )
    assert [(m["version"], m["state"]) for m in manifests] == [(1, "INVALIDATED"), (2, "RENDERED")]
    events = world.events(episode_id, "editing.captions_invalidated")
    assert events and events[-1]["cue_ids"] == [f"{REPLACED_LINE}.enus", f"{REPLACED_LINE}.thth"]


def test_identical_reassembly_replays_without_re_export(world: World) -> None:
    episode_id, assets, first = _assemble(world)
    asset_rows_before = world.rows(
        "SELECT id FROM assets WHERE episode_id = %s AND provenance = 'DERIVED_LOCAL'",
        (episode_id,),
    )
    second = world.service.assemble_episode(episode_id, shot_assets=assets["shots"])
    assert second.status is AssemblyStatus.REPLAYED
    assert second.clean_asset_id == first.clean_asset_id
    assert second.clean_sha256 == first.clean_sha256
    assert second.burned_asset_id == first.burned_asset_id
    asset_rows_after = world.rows(
        "SELECT id FROM assets WHERE episode_id = %s AND provenance = 'DERIVED_LOCAL'",
        (episode_id,),
    )
    assert {r["id"] for r in asset_rows_after} == {r["id"] for r in asset_rows_before}
    manifests = world.rows(
        "SELECT version, state FROM edit_manifests WHERE episode_id = %s", (episode_id,)
    )
    assert [(m["version"], m["state"]) for m in manifests] == [(1, "RENDERED")]


def test_shot_source_swap_creates_a_new_edl_version(world: World) -> None:
    episode_id, _season, assets = world.seed_prepared_episode()
    first = world.service.assemble_episode(episode_id, shot_assets=assets["shots"])
    _back_to_assembling(world, episode_id)
    # A different accepted render of the same shot (new asset, same measured duration).
    season_id = world.row("SELECT season_id FROM episodes WHERE id = %s", (episode_id,))[
        "season_id"
    ]
    new_shot = world._register_shot_asset(  # noqa: SLF001
        episode_id, season_id, "sh1", 4_000, attempt=2
    )
    swapped = dict(assets["shots"])
    swapped["sh1"] = new_shot
    second = world.service.assemble_episode(episode_id, shot_assets=swapped)
    assert second.status is AssemblyStatus.ASSEMBLED
    assert second.edl_id != first.edl_id
    manifests = world.rows(
        "SELECT version, state, edl_hash FROM edit_manifests WHERE episode_id = %s "
        "ORDER BY version",
        (episode_id,),
    )
    assert [(m["version"], m["state"]) for m in manifests] == [
        (1, "INVALIDATED"),
        (2, "RENDERED"),
    ]
    assert manifests[0]["edl_hash"] != manifests[1]["edl_hash"]


def test_replacing_the_line_back_repromotes_the_identical_track(world: World) -> None:
    episode_id, assets, first = _assemble(world)
    original = next(t for lid, _s, t, _m in LINES if lid == REPLACED_LINE)
    original_ms = next(ms for lid, _s, _t, ms in LINES if lid == REPLACED_LINE)
    _replace_line(world, episode_id)
    _back_to_assembling(world, episode_id)
    second = world.service.assemble_episode(episode_id, shot_assets=assets["shots"])
    assert second.edl_id != first.edl_id
    # Replace the line BACK: the new track's body equals the v1 body bit-for-bit.
    _replace_line(world, episode_id, text=original, ms=original_ms, register_audio=False)
    _back_to_assembling(world, episode_id)
    third = world.service.assemble_episode(episode_id, shot_assets=assets["shots"])
    rows = world.rows(
        "SELECT id, version, state FROM caption_tracks WHERE episode_id = %s "
        "AND locale = 'th-TH' ORDER BY version",
        (episode_id,),
    )
    current = [r for r in rows if r["state"] == "CURRENT"]
    assert len(current) == 1  # never two current rows (DB unique index backs this)
    v1_th = next(r for r in rows if r["version"] == 1)
    assert current[0]["id"] == v1_th["id"]  # the identical v1 body, re-promoted
    del first
    assert third.invalidated_cue_ids == [f"{REPLACED_LINE}.enus", f"{REPLACED_LINE}.thth"]
