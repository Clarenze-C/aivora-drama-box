"""Shared builders for the ComfyUI adapter (T013) tests.

Real PostgreSQL, real budget service, real job queue, the T007 FakeComfyServerState and
a filesystem object store. A second service over the same server state simulates a
reconnect (fresh websocket client, same ComfyUI memory)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from microdrama.budget import BudgetService
from microdrama.config import Settings
from microdrama.contracts.cost import RenderRequest
from microdrama.contracts.enums import (
    ControlKind,
    ExecutionMode,
    RenderTier,
)
from microdrama.contracts.enums import Provenance as ProvenanceEnum
from microdrama.contracts.hashing import sha256_hex
from microdrama.contracts.season import CostPolicy
from microdrama.core.jobs import JobService
from microdrama.persistence import Database
from microdrama.persistence.db import IsolationLevel
from microdrama.persistence.object_store import FilesystemObjectStore
from microdrama.rendering.comfy_jobs import (
    ComfyRenderConfig,
    ComfyRenderService,
    build_comfy_render_service,
    render_id_for,
)
from microdrama.testing.fakes import FakeClock, FakeComfyClient, FakeComfyServerState, SequentialIds
from microdrama.testing.fakes.comfy import EXECUTION_MS
from microdrama.testing.seed import seed_episode, seed_season

T0 = datetime(2026, 10, 21, tzinfo=UTC)
GPU_SECOND_MICRO = 250  # the mock attempt price, matching the fake price table
DEFAULT_KEY = "render.shot:ep1:sh1:attempt1"
DEFAULT_ATTEMPT_MS = 600_000


@dataclass(frozen=True)
class Episode:
    season_id: uuid.UUID
    episode_id: uuid.UUID
    account_id: uuid.UUID


@dataclass(frozen=True)
class Attempt:
    request: RenderRequest
    job_id: uuid.UUID


class ComfyWorld:
    """Everything one ComfyUI attempt needs, deterministically."""

    def __init__(
        self,
        db: Database,
        store_root: Path,
        *,
        scenarios: tuple[Any, ...] = (),
        config: ComfyRenderConfig | None = None,
        settings: Settings | None = None,
        execution_ms: int = EXECUTION_MS,
    ) -> None:
        self.db = db
        self.clock = FakeClock(T0)
        self.settings = settings or Settings(execution_mode=ExecutionMode.OFFLINE_MOCK)
        self.config = config or ComfyRenderConfig.for_mock()
        self.server = FakeComfyServerState(self.clock, execution_ms=execution_ms)
        self.client = FakeComfyClient(self.server, scenarios=scenarios)
        self.ids = SequentialIds("render-comfy")
        self.budget = BudgetService(db, self.clock, self.ids, self.settings)
        self.store = FilesystemObjectStore(store_root)
        self.jobs = JobService(db, self.clock, self.ids)
        self.service = build_comfy_render_service(
            db,
            self.budget,
            self.client,
            self.clock,
            self.ids,
            self.settings,
            self.config,
            self.store,
        )

    def reconnect(self) -> ComfyRenderService:
        """A fresh client (new connection) over the same shared server state."""
        client = FakeComfyClient(self.server)
        return ComfyRenderService(
            self.db,
            BudgetService(self.db, self.clock, self.ids, self.settings),
            client,
            self.clock,
            self.ids,
            self.settings,
            self.config,
            self.store,
        )

    # --- seeding -------------------------------------------------------------------

    def episode(self, *, number: int = 1) -> Episode:
        with self.db.transaction() as tx:
            season_id = seed_season(tx)
            episode_id = seed_episode(tx, season_id, number=number)
            account_id = self.budget.open_episode_account(
                tx, season_id=season_id, episode_id=episode_id, policy=CostPolicy()
            )
        return Episode(season_id, episode_id, account_id)

    def attempt(
        self,
        episode: Episode,
        *,
        key: str = DEFAULT_KEY,
        preset: str = "fake-quality-8step",
        controls: tuple[ControlKind, ...] = (ControlKind.CHARACTER_REFERENCE,),
        references: int = 1,
        prompt: str = "Medium close-up of Fon reading a ledger at a street food stall.",
        negative: str = "",
        duration_ms: int = 4_000,
        reservation_id: uuid.UUID | None = None,
    ) -> Attempt:
        """Reserve, build and enqueue one render attempt (deterministic ids).

        ``reservation_id`` overrides the hold (for refusal tests); production callers
        always let the attempt reserve its own hold first.
        """
        if reservation_id is None:
            reservation_id = self.service.reserve_attempt(
                episode_id=episode.episode_id, semantic_key=key
            ).id
        reference_ids = [uuid.uuid5(uuid.NAMESPACE_URL, f"ref-{i}") for i in range(references)]
        self._seed_reference_assets(reference_ids)
        request = RenderRequest(
            render_id=render_id_for(key),
            semantic_key=key,
            episode_id=episode.episode_id,
            episode_number=1,
            shot_id="sh1",
            manifest_version=1,
            attempt_number=1,
            preset_id=preset,
            tier=RenderTier.QUALITY_EIGHT_STEP,
            required_controls=list(controls),
            reference_asset_ids=reference_ids,
            audio_asset_id=None,
            identity_lock_id=None,
            workflow_sha256=_workflow_sha_for(preset),
            seed=1234,
            width=720,
            height=1280,
            fps=24,
            duration_ms=duration_ms,
            reservation_id=reservation_id,
            prompt_text=prompt,
            negative_prompt_text=negative,
        )
        with self.db.transaction() as tx:
            result = self.jobs.enqueue(
                tx, job_type="render.shot", semantic_key=key, payload=request
            )
        return Attempt(request=request, job_id=result.job_id)

    def _seed_reference_assets(self, reference_ids: list[uuid.UUID]) -> None:
        """Register the reference assets the render consumes (as the T011 lane would).

        The ``asset_lineage`` foreign keys make this real: a render's lineage may only
        name assets that exist.
        """
        from microdrama.contracts.enums import AssetKind, AssetState
        from microdrama.contracts.media import AssetDescriptor
        from microdrama.persistence.assets import register_asset

        now = self.clock.now()
        for asset_id in reference_ids:
            payload = f"fixture-reference-{asset_id}".encode()
            key = f"references/{asset_id}.png"
            stored = self.store.put_bytes(key, payload, media_type="image/png")
            descriptor = AssetDescriptor(
                asset_id=asset_id,
                asset_kind=AssetKind.IMAGE,
                object_key=stored.key,
                sha256=stored.sha256,
                size_bytes=stored.size_bytes,
                media_type="image/png",
                media=None,
                state=AssetState.ACCEPTED,
                provenance=ProvenanceEnum.FAKE_SYNTHETIC,
                episode_id=None,
                season_id=None,
                created_at=now,
            )
            with self.db.transaction() as tx:
                register_asset(tx, descriptor)

    # --- reads ---------------------------------------------------------------------

    def counters(self, account_id: uuid.UUID) -> dict[str, int]:
        with self.db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
            row = tx.fetchone("SELECT * FROM budget_accounts WHERE id = %s", (account_id,))
        assert row is not None
        return {
            "reserved": row["reserved_outstanding_micro_usd"],
            "accrued": row["accrued_micro_usd"],
            "settled": row["settled_micro_usd"],
            "committed": row["reserved_outstanding_micro_usd"]
            + row["accrued_micro_usd"]
            + row["settled_micro_usd"],
        }

    def op_rows(self) -> list[dict[str, Any]]:
        with self.db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
            return tx.fetchall("SELECT * FROM provider_operations ORDER BY created_at")

    def charges(self, reservation_id: uuid.UUID) -> list[dict[str, Any]]:
        with self.db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
            return tx.fetchall(
                "SELECT * FROM charges WHERE reservation_id = %s ORDER BY created_at",
                (reservation_id,),
            )

    def reservation_row(self, reservation_id: uuid.UUID) -> dict[str, Any]:
        with self.db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
            row = tx.fetchone("SELECT * FROM reservations WHERE id = %s", (reservation_id,))
        assert row is not None
        return row

    def asset_rows(self) -> list[dict[str, Any]]:
        with self.db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
            return tx.fetchall("SELECT * FROM assets ORDER BY id")

    def render_asset_rows(self) -> list[dict[str, Any]]:
        """Only the outputs of render attempts (the seeded references excluded)."""
        with self.db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
            return tx.fetchall("SELECT * FROM assets WHERE object_key LIKE 'renders/%' ORDER BY id")

    def served_bytes(self, filename: str) -> bytes:
        return self.server.serve(filename)


def _workflow_sha_for(preset: str) -> str:
    from microdrama.rendering.workflows import PRESET_TEMPLATES, template_sha256

    template = PRESET_TEMPLATES[preset]
    return template_sha256(template)


def checksum(data: bytes) -> str:
    return sha256_hex(data)


__all__ = [
    "DEFAULT_ATTEMPT_MS",
    "DEFAULT_KEY",
    "Episode",
    "Attempt",
    "ComfyWorld",
    "GPU_SECOND_MICRO",
    "ProvenanceEnum",
    "T0",
    "checksum",
]
