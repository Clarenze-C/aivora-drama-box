"""Shared builders for the QA lane tests (T017). Not a test module.

Real PostgreSQL, the real BudgetService, a filesystem object store and the REAL local
ffmpeg. The media under review is the T007 seeded-defect suite (session-scoped,
generated once) plus purpose-built clips; each test registers the media it needs as a
real asset row and runs the service against it. The offline observer is the production
``OfflineMediaObserver`` over the same session fixture-truth registry the defect suite
registered into — the ASR stand-in reads what the media actually contains.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from microdrama.budget import BudgetService
from microdrama.config import Settings
from microdrama.contracts.enums import AssetKind, AssetState, Provenance
from microdrama.contracts.examples import script as example_script
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.infra import ObjectStore
from microdrama.contracts.media import AssetDescriptor, CaptionTrack, MediaInfo
from microdrama.persistence import Database, insert_row, jsonb, register_asset
from microdrama.qa.audio import MediaObservation, OfflineMediaObserver
from microdrama.qa.config import QAConfig
from microdrama.qa.service import TechnicalQAService
from microdrama.testing.fakes import FakeClock, SequentialIds
from microdrama.testing.media import FixtureTruth, FixtureTruthRegistry, probe
from microdrama.testing.seed import seed_episode, seed_gate1_approval

T0 = datetime(2026, 10, 21, tzinfo=UTC)


class StubCaptionSource:
    """Structural T015 stand-in: fixed tracks and stale-cue ids."""

    def __init__(
        self, tracks: list[CaptionTrack] | None = None, stale: list[str] | None = None
    ) -> None:
        self._tracks = tracks or []
        self._stale = list(stale or [])

    def captions(self, episode_id: uuid.UUID) -> list[CaptionTrack]:
        return self._tracks

    def stale_caption_cues(self, episode_id: uuid.UUID) -> list[str]:
        return list(self._stale)


class RecordingObserver:
    """Observer stub: records reservation state at call time; optionally fails."""

    def __init__(
        self,
        *,
        raises: Exception | None = None,
        probe: Callable[[], Any] | None = None,
        observation: MediaObservation | None = None,
    ) -> None:
        self.calls = 0
        self.snapshots: list[Any] = []
        self._raises = raises
        self._probe = probe
        self._observation = observation

    def observe(
        self,
        *,
        asset_id: uuid.UUID,
        asset_sha256: str,
        media_path: Path,
        duration_ms: int,
    ) -> MediaObservation:
        self.calls += 1
        if self._probe is not None:
            self.snapshots.append(self._probe())
        if self._raises is not None:
            raise self._raises
        if self._observation is not None:
            return self._observation
        from microdrama.contracts.enums import CheckFamily, Provenance
        from microdrama.qa.coverage import partition_coverage

        coverage = [
            window
            for family in (CheckFamily.ASR, CheckFamily.VISUAL_IDENTITY)
            for window in partition_coverage(
                asset_id, family, max(duration_ms, 1), ((0, max(duration_ms, 1)),)
            )
        ]
        return MediaObservation(
            coverage=coverage,
            provenance=Provenance.ORIGINAL_FIXTURE,
            source_label="fixture-truth",
            fixture_id="stub",
        )


def unregistered_observation() -> MediaObservation:
    from microdrama.contracts.enums import CheckFamily, CoverageStatus, Provenance
    from microdrama.qa.coverage import partition_coverage

    coverage = [
        window
        for family in (CheckFamily.ASR, CheckFamily.VISUAL_IDENTITY)
        for window in partition_coverage(
            uuid.UUID(int=1),
            family,
            1,
            (),
            outside=CoverageStatus.UNAVAILABLE,
            note="stub",
        )
    ]
    return MediaObservation(
        coverage=coverage,
        provenance=Provenance.DERIVED_LOCAL,
        source_label="unregistered",
    )


class QAWorld:
    """One technical QA service on the real database, store and local FFmpeg."""

    def __init__(
        self,
        db: Database,
        store: ObjectStore,
        settings: Settings,
        truth: FixtureTruthRegistry,
    ) -> None:
        self.db = db
        self.store = store
        self.settings = settings
        self.truth = truth
        self.clock = FakeClock(T0)
        self.ids = SequentialIds("qa-tests")
        self.budget = BudgetService(db, self.clock, SequentialIds("qa-budget"), settings)

    def observer(self) -> OfflineMediaObserver:
        return OfflineMediaObserver(self.truth, self.settings)

    def service(
        self,
        config: QAConfig | None = None,
        *,
        observer=None,
        caption_source=None,
    ) -> TechnicalQAService:
        return TechnicalQAService(
            self.db,
            self.clock,
            self.ids,
            self.settings,
            budget=self.budget,
            store=self.store,
            config=config,
            observer=self.observer() if observer is None else observer,
            caption_source=caption_source,
        )

    # --- seeds -------------------------------------------------------------------------

    def season(self) -> uuid.UUID:
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
        return season_id

    def episode(self, season_id: uuid.UUID | None = None, *, state: str = "AI_REVIEW") -> uuid.UUID:
        season_id = season_id or self.season()
        with self.db.transaction() as tx:
            return seed_episode(tx, season_id, state=state)

    def seed_script(self, episode_id: uuid.UUID) -> None:
        """The pristine intended script (examples.script) as the episode's CURRENT one."""
        script = example_script().model_copy(
            update={"episode_id": episode_id, "script_id": uuid.uuid4()}
        )
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
            tx.execute(
                "UPDATE episodes SET current_script_id = %s WHERE id = %s",
                (script.script_id, episode_id),
            )

    def register_media(
        self,
        episode_id: uuid.UUID,
        *,
        data: bytes,
        media: MediaInfo | None = None,
        key: str | None = None,
        truth: FixtureTruth | None = None,
    ) -> uuid.UUID:
        season_row = self.row("SELECT season_id FROM episodes WHERE id = %s", (episode_id,))
        assert season_row is not None
        stored = self.store.put_bytes(
            key or f"qa/{episode_id}/{uuid.uuid4().hex}.mp4", data, media_type="video/mp4"
        )
        if media is None:
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp:
                tmp.write(data)
                tmp.flush()
                media = probe(Path(tmp.name))
        asset_id = uuid.uuid4()
        with self.db.transaction() as tx:
            register_asset(
                tx,
                AssetDescriptor(
                    asset_id=asset_id,
                    asset_kind=AssetKind.VIDEO,
                    object_key=stored.key,
                    sha256=stored.sha256,
                    size_bytes=stored.size_bytes,
                    media_type="video/mp4",
                    media=media,
                    state=AssetState.ACCEPTED,
                    provenance=Provenance.ORIGINAL_FIXTURE,
                    episode_id=episode_id,
                    season_id=season_row["season_id"],
                    created_at=self.clock.now(),
                ),
            )
        if truth is not None:
            self.truth.register(stored.sha256, truth)
        return asset_id

    def seeded_episode_with(
        self,
        *,
        fixture=None,
        media: bytes | None = None,
        media_info: MediaInfo | None = None,
        truth: FixtureTruth | None = None,
        state: str = "AI_REVIEW",
    ) -> tuple[uuid.UUID, uuid.UUID]:
        """Episode + pristine script + the given media registered as the asset under review."""
        episode_id = self.episode(state=state)
        self.seed_script(episode_id)
        if fixture is not None:
            data = fixture.path.read_bytes()
            truth = fixture.truth
        else:
            data = media or b""
        asset_id = self.register_media(episode_id, data=data, media=media_info, truth=truth)
        return episode_id, asset_id

    # --- reads -------------------------------------------------------------------------

    def row(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        with self.db.transaction(readonly=True) as tx:
            return tx.fetchone(sql, params)

    def rows(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self.db.transaction(readonly=True) as tx:
            return tx.fetchall(sql, params)

    def findings_rows(self, episode_id: uuid.UUID) -> list[dict[str, Any]]:
        return self.rows(
            "SELECT * FROM qa_findings WHERE episode_id = %s ORDER BY id", (episode_id,)
        )

    def run_events(self, episode_id: uuid.UUID) -> list[dict[str, Any]]:
        rows = self.rows(
            "SELECT payload FROM domain_events WHERE aggregate_id = %s "
            "AND event_type = 'qa.technical.completed' ORDER BY sequence",
            (episode_id,),
        )
        return [dict(row["payload"]) for row in rows]


__all__ = [
    "QAWorld",
    "RecordingObserver",
    "StubCaptionSource",
    "T0",
    "unregistered_observation",
]
