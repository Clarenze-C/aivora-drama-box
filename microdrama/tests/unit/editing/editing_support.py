"""Shared builders for the editing tests (T015). Not a test module.

Real PostgreSQL, the real BudgetService, a filesystem object store and the REAL
local FFmpeg. Scripts/manifests are seeded in the shape T010+T011 leave them
(``voice_id``/``actual_duration_ms`` filled, per-line audio assets persisted with
the references lane's deterministic asset ids), and shot video assets are T007
original synthetic fixture clips. A fixture-truth-backed ``SpeechObserver`` stands
in for ASR offline: it reports what each audio asset actually contains, which is
how the wrong-audio defect is simulated honestly (the asset's registered speech is
changed, never the caption text alone).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from microdrama.budget import BudgetService
from microdrama.config import Settings
from microdrama.contracts.enums import (
    AssetKind,
    AssetState,
    Provenance,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.infra import ObjectStore
from microdrama.contracts.media import AssetDescriptor
from microdrama.contracts.season import (
    DialogueLine,
    Scene,
    Script,
    Shot,
    ShotManifest,
)
from microdrama.editing import EditingConfig, EditingService
from microdrama.editing.captions import SpeechObserver
from microdrama.editing.models import ObservedSpeech
from microdrama.persistence import Database, insert_row, jsonb
from microdrama.references.anchors import ref_id_for
from microdrama.testing.fakes import FakeClock, SequentialIds
from microdrama.testing.media import (
    FixtureTruth,
    FixtureTruthRegistry,
    MediaInfo,
    SpokenTruth,
    make_clip,
    make_wav_bytes,
    probe,
)
from microdrama.testing.seed import seed_episode, seed_gate1_approval

T0 = datetime(2026, 10, 21, tzinfo=UTC)

# Two-scene script, T011-filled shape. Thai lines reuse the critical money term.
LINES: list[tuple[str, str, str, int]] = [
    # line_id, speaker, text_th, actual audio ms
    ("sc1-l1", "fon", "ลุงเล็ก ร้านข้าวมันไก่ของแม่เปิดได้อีกไหมคะ", 1_500),
    ("sc1-l2", "lek", "เปิดได้ แต่ต้องรีบเก็บรายได้ก่อนสิ้นเดือนนะหนู", 1_200),
    ("sc1-l3", "fon", "ทำไมลุงถึงเคร่งเครียดแบบนี้คะ", 1_000),
]
SHOT_TARGETS: dict[str, int] = {"sh1": 4_000, "sh2": 2_500}
SHOT_OF_LINE: dict[str, str] = {"sc1-l1": "sh1", "sc1-l2": "sh1", "sc1-l3": "sh2"}


def _shot(shot_id: str, sequence: int, line_ids: list[str], speakers: list[str]) -> Shot:
    return Shot(
        shot_id=shot_id,
        sequence=sequence,
        scene_id="sc1",
        shot_pattern_id="quiet_confession_v1",
        coverage_role="master",
        purpose="Fon gently probes Uncle Lek.",
        dramatic_importance="HIGH",
        dialogue_complexity="TWO_SPEAKER" if len(set(speakers)) == 2 else "SINGLE_SPEAKER",
        temporal_risk="LOW",
        required_identity_controls=["TEXT_PROMPT", "CHARACTER_REFERENCE"],
        preferred_render_tier="quality_eight_step",
        fallback_edit="CUT_TO_REACTION",
        reference_lock_version=None,
        line_ids=line_ids,
        speaker_ids=speakers,
        voice_ids=[f"voice-{s}.v1" for s in sorted(set(speakers))],
        target_duration_ms=SHOT_TARGETS[shot_id],
        framing="medium two-shot",
        eyelines="fon to lek",
        location_id="stall",
        outfit_ids=[],
        prop_ids=[],
        required_reference_asset_ids=[],
        sound="morning market",
        acceptance_criteria=["both faces consistent"],
        depends_on_shot_ids=[],
    )


class FixtureSpeechObserver:
    """SpeechObserver backed by the T007 fixture-truth registry (the offline ASR stand-in)."""

    def __init__(self, registry: FixtureTruthRegistry) -> None:
        self._registry = registry

    def observe(self, audio_sha256: str) -> ObservedSpeech | None:
        truth = self._registry.get(audio_sha256)
        if truth is None or not truth.spoken:
            return None
        first = truth.spoken[0]
        return ObservedSpeech(text_th=first.text_th, speaker_id=first.speaker_id)


def build_script(episode_id: uuid.UUID, lines: list[tuple[str, str, str, int]]) -> Script:
    """A T011-filled script (actual durations + voice ids) for builder-level tests."""
    return Script(
        script_id=uuid.uuid4(),
        episode_id=episode_id,
        version=1,
        approved_scope_hash="a" * 64,
        canon_version=1,
        scenes=[
            Scene(
                scene_id="sc1",
                location_id="stall",
                summary="Fon asks Uncle Lek about reopening.",
                lines=[
                    DialogueLine(
                        line_id=line_id,
                        speaker_character_id=speaker,
                        voice_id=f"voice-{speaker}.v1",
                        text_th=text,
                        text_en=f"EN({line_id})",
                        estimated_duration_ms=max(1_000, 800 + 300 * len(text)),
                        actual_duration_ms=actual_ms,
                        critical_terms=[],
                    )
                    for line_id, speaker, text, actual_ms in lines
                ],
            )
        ],
        estimated_runtime_ms=sum(actual for *_, actual in lines) + 3_000,
    )


def build_manifest(episode_id: uuid.UUID, script: Script) -> ShotManifest:
    """A manifest with the support lines mapped onto the two standard shots."""
    lines = [
        (line.line_id, line.speaker_character_id) for scene in script.scenes for line in scene.lines
    ]
    by_shot: dict[str, list[tuple[str, str]]] = {}
    for line_id, speaker in lines:
        by_shot.setdefault(SHOT_OF_LINE.get(line_id, "sh1"), []).append((line_id, speaker))
    shots = [
        _shot(
            shot_id,
            index + 1,
            [line_id for line_id, _ in members],
            sorted({speaker for _, speaker in members}),
        )
        for index, (shot_id, members) in enumerate(sorted(by_shot.items()))
    ]
    return ShotManifest(
        manifest_id=uuid.uuid4(),
        episode_id=episode_id,
        episode_number=1,
        script_id=script.script_id,
        script_version=1,
        version=1,
        identity_lock_id=None,
        shots=shots,
    )


class ClipCache:
    """Renders each distinct fixture clip once per test session (CPU bound)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._entries: dict[int, tuple[bytes, MediaInfo]] = {}

    def clip(self, duration_ms: int, *, tone: int = 0) -> tuple[bytes, MediaInfo]:
        key = duration_ms * 10 + tone
        if key not in self._entries:
            path = self.root / f"clip-{key}.mp4"
            make_clip(
                path,
                duration_ms=duration_ms,
                width=360,
                height=640,
                comment=f"editing-test-{key}",
            )
            self._entries[key] = (path.read_bytes(), probe(path))
        return self._entries[key]


class World:
    """One editing service on the real database, store and local FFmpeg."""

    def __init__(
        self,
        db: Database,
        store: ObjectStore,
        settings: Settings,
        clips: ClipCache,
        registry: FixtureTruthRegistry,
        *,
        config: EditingConfig | None = None,
        observer: SpeechObserver | None = None,
    ) -> None:
        self.db = db
        self.store = store
        self.settings = settings
        self.clock = FakeClock(T0)
        self.ids = SequentialIds("editing-tests")
        self.budget = BudgetService(db, self.clock, SequentialIds("editing-budget"), settings)
        self.truth = registry
        self.clips = clips
        self.config = config or EditingConfig()
        self.service: EditingService = EditingService(
            db,
            self.clock,
            self.ids,
            settings,
            budget=self.budget,
            store=store,
            config=self.config,
            speech_observer=observer if observer is not None else FixtureSpeechObserver(registry),
        )

    # --- seeds -------------------------------------------------------------------------

    def season(self) -> tuple[uuid.UUID, Any]:
        season_id = uuid.uuid4()
        from microdrama.contracts.examples import season_scope

        scope = season_scope().model_copy(update={"season_id": season_id, "scope_version": 1})
        scope_hash = canonical_hash(scope)
        with self.db.transaction() as tx:
            approval = seed_gate1_approval(tx, season_id, scope_hash)
            tx.execute(
                "INSERT INTO seasons (id, state, title_th, title_en, approved_scope_version, "
                "approved_scope_hash, approval_event_id, approved_at) VALUES (%s, "
                "'SEASON_APPROVED', %s, 'Test season', 1, %s, %s, %s)",
                (season_id, scope.title_th, scope_hash, approval, T0),
            )
            tx.execute(
                "INSERT INTO season_proposals (id, season_id, scope_version, scope, scope_hash, "
                "status) VALUES (%s, %s, 1, %s, %s, 'APPROVED')",
                (uuid.uuid4(), season_id, jsonb(scope), scope_hash),
            )
        return season_id, scope

    def episode(self, season_id: uuid.UUID, *, state: str = "RENDERING") -> uuid.UUID:
        with self.db.transaction() as tx:
            return seed_episode(tx, season_id, state=state)

    def seed_prepared_episode(
        self,
        *,
        state: str = "RENDERING",
        lines: list[tuple[str, str, str, int]] | None = None,
        spoken_text: dict[str, str] | None = None,
    ) -> tuple[uuid.UUID, uuid.UUID, dict[str, uuid.UUID]]:
        """Season + episode + T011-shaped script/manifest + line audio + shot assets."""
        season_id, _scope = self.season()
        episode_id = self.episode(season_id, state=state)
        lines = lines if lines is not None else list(LINES)
        spoken_text = spoken_text or {}
        script = self._script(episode_id, lines)
        manifest = self._manifest(episode_id, script, lines)
        with self.db.transaction() as tx:
            insert_row(
                tx,
                "scripts",
                {
                    "id": script.script_id,
                    "episode_id": episode_id,
                    "version": 1,
                    "canon_version": 1,
                    "body": jsonb(script),
                    "body_hash": canonical_hash(script),
                    "status": "CURRENT",
                },
            )
            insert_row(
                tx,
                "shot_manifests",
                {
                    "id": manifest.manifest_id,
                    "episode_id": episode_id,
                    "script_id": script.script_id,
                    "version": 1,
                    "identity_lock_id": None,
                    "body": jsonb(manifest),
                    "body_hash": canonical_hash(manifest),
                    "status": "CURRENT",
                },
            )
            tx.execute(
                "UPDATE episodes SET current_script_id = %s, current_manifest_id = %s "
                "WHERE id = %s",
                (script.script_id, manifest.manifest_id, episode_id),
            )
        line_assets = {
            line_id: self._register_line_audio(
                episode_id, season_id, line_id, speaker, text, actual_ms, spoken_text
            )
            for line_id, speaker, text, actual_ms in lines
        }
        shot_assets = {
            shot_id: self._register_shot_asset(episode_id, season_id, shot_id, target_ms)
            for shot_id, target_ms in SHOT_TARGETS.items()
        }
        return episode_id, season_id, {"lines": line_assets, "shots": shot_assets}

    def _script(self, episode_id: uuid.UUID, lines: list[tuple[str, str, str, int]]) -> Script:
        return build_script(episode_id, lines)

    def _manifest(
        self, episode_id: uuid.UUID, script: Script, lines: list[tuple[str, str, str, int]]
    ) -> ShotManifest:
        del lines
        return build_manifest(episode_id, script)

    def _register_line_audio(
        self,
        episode_id: uuid.UUID,
        season_id: uuid.UUID,
        line_id: str,
        speaker: str,
        text_th: str,
        actual_ms: int,
        spoken_text: dict[str, str],
    ) -> uuid.UUID:
        """Persist the line's audio asset exactly where the references lane put it.

        The registered fixture truth declares what the audio ACTUALLY contains; the
        seeded-defect tests override ``spoken_text`` so the truth disagrees with the
        intended script line (the honest wrong-audio defect).
        """
        asset_id = ref_id_for(
            "line-audio", f"{episode_id}:{line_id}:{canonical_hash(text_th)[:12]}"
        )
        spoken = spoken_text.get(line_id, text_th)
        # Distinct tone per line keeps bytes (and shas) distinct per content.
        tone = 440 + sum(ord(ch) for ch in f"{line_id}:{spoken}") % 400
        data = make_wav_bytes(actual_ms, tone)
        asset_id = self._register_asset(
            asset_id,
            AssetKind.AUDIO,
            f"episodes/{episode_id}/dialogue/{line_id}-{canonical_hash(text_th)[:12]}.wav",
            data,
            "audio/wav",
            episode_id,
            season_id,
        )
        row = self.row("SELECT sha256 FROM assets WHERE id = %s", (asset_id,))
        assert row is not None
        self.truth.register(
            row["sha256"],
            FixtureTruth(
                fixture_id=f"line-audio:{line_id}",
                duration_ms=actual_ms,
                has_audio=True,
                has_video=False,
                spoken=(
                    SpokenTruth(start_ms=0, end_ms=actual_ms, text_th=spoken, speaker_id=speaker),
                ),
                identities=(),
                text_items=(),
                video_defects=(),
                covered_ranges_ms=((0, actual_ms),),
            ),
        )
        return asset_id

    def _register_shot_asset(
        self,
        episode_id: uuid.UUID,
        season_id: uuid.UUID,
        shot_id: str,
        target_ms: int,
        *,
        attempt: int = 1,
    ) -> uuid.UUID:
        asset_id = uuid.uuid4()
        duration = min(5_000, target_ms + 1_000)  # measured longer than target sometimes
        data, media = self.clips.clip(duration)
        return self._register_asset(
            asset_id,
            AssetKind.VIDEO,
            f"renders/{episode_id}/{shot_id}/a{attempt}/output.mp4",
            data,
            "video/mp4",
            episode_id,
            season_id,
            media=media,
        )

    def _register_asset(
        self,
        asset_id: uuid.UUID,
        kind: AssetKind,
        key: str,
        data: bytes,
        media_type: str,
        episode_id: uuid.UUID,
        season_id: uuid.UUID,
        *,
        media: MediaInfo | None = None,
    ) -> uuid.UUID:
        stored = self.store.put_bytes(key, data, media_type=media_type)
        if media is None and kind in (AssetKind.VIDEO, AssetKind.AUDIO):
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".bin") as tmp:
                tmp.write(data)
                tmp.flush()
                media = probe(Path(tmp.name))
        descriptor = AssetDescriptor(
            asset_id=asset_id,
            asset_kind=kind,
            object_key=stored.key,
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            media_type=media_type,
            media=media,
            state=AssetState.ACCEPTED,
            provenance=Provenance.ORIGINAL_FIXTURE,
            episode_id=episode_id,
            season_id=season_id,
            created_at=self.clock.now(),
        )
        with self.db.transaction() as tx:
            from microdrama.persistence import register_asset

            register_asset(tx, descriptor)
        return asset_id

    # --- reads -------------------------------------------------------------------------

    def row(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        with self.db.transaction(readonly=True) as tx:
            return tx.fetchone(sql, params)

    def rows(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self.db.transaction(readonly=True) as tx:
            return tx.fetchall(sql, params)

    def episode_state(self, episode_id: uuid.UUID) -> str:
        row = self.row("SELECT state FROM episodes WHERE id = %s", (episode_id,))
        assert row is not None
        return row["state"]

    def events(self, episode_id: uuid.UUID, event_type: str) -> list[dict[str, Any]]:
        rows = self.rows(
            "SELECT payload FROM domain_events WHERE aggregate_id = %s AND event_type = %s "
            "ORDER BY sequence",
            (episode_id, event_type),
        )
        return [dict(row["payload"]) for row in rows]


__all__ = [
    "ClipCache",
    "FixtureSpeechObserver",
    "LINES",
    "SHOT_OF_LINE",
    "SHOT_TARGETS",
    "T0",
    "World",
    "build_manifest",
    "build_script",
]
