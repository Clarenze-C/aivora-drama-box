"""T028 test support: a world with the real JobService/BudgetService and the
worker runtime pieces. Jobs are enqueued through the real frozen specs; the
light payload models (``PlatformPostRef``/``CommunityEventRef``) let flood and
routing tests run without fabricating provider state.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from microdrama.budget import BudgetService
from microdrama.config import Settings
from microdrama.contracts.cost import RenderRequest
from microdrama.contracts.enums import ControlKind, QueueName, RenderTier
from microdrama.contracts.infra import RateLimiter
from microdrama.contracts.jobs import (
    CommunityEventRef,
    EpisodeStepInput,
    PlatformPostRef,
)
from microdrama.core.clock import UuidIds
from microdrama.core.jobs import JobService
from microdrama.persistence import Database
from microdrama.testing.fakes.common import FakeClock, SequentialIds, ensure_mock_mode
from microdrama.workers import (
    QueueSlots,
    SharedRateLimiter,
    WorkerDeployment,
    WorkerRuntime,
)

T0 = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
HEX64 = "a" * 64


class WorkersWorld:
    def __init__(self, db: Database, tmp: Path, settings: Settings) -> None:
        ensure_mock_mode(settings)
        self.db = db
        self.clock = FakeClock(T0)
        self.ids = SequentialIds("workers")
        self.uuid_ids = UuidIds()
        self.jobs = JobService(self.db, self.clock, self.ids)
        self.budget = BudgetService(self.db, self.clock, self.ids, settings)
        self.limiter = SharedRateLimiter(self.clock)
        self._counter = 0

    # --- enqueue helpers ----------------------------------------------------------------

    def enqueue(self, job_type: str, payload: Any, *, episode_id: UUID | None = None) -> UUID:
        self._counter += 1
        with self.db.transaction() as tx:
            result = self.jobs.enqueue(
                tx,
                job_type=job_type,
                semantic_key=f"{job_type}:{self._counter}:{uuid.uuid4().hex[:8]}",
                payload=payload,
                episode_id=episode_id,
            )
        return result.job_id

    def enqueue_post_job(self, job_type: str = "publish.poll_status") -> UUID:
        return self.enqueue(job_type, PlatformPostRef(platform_post_id=uuid.uuid4()))

    def enqueue_event_job(self, job_type: str = "community.ingest_event") -> UUID:
        return self.enqueue(job_type, CommunityEventRef(community_event_id=uuid.uuid4()))

    def enqueue_episode_job(
        self, job_type: str = "qa.technical", episode_id: UUID | None = None
    ) -> UUID:
        episode = episode_id or uuid.uuid4()
        return self.enqueue(job_type, EpisodeStepInput(episode_id=episode), episode_id=episode)

    def render_request(
        self, episode_id: UUID, *, number: int = 1, shot: str = "shot-1"
    ) -> RenderRequest:
        return RenderRequest(
            render_id=uuid.uuid4(),
            semantic_key=f"render:{episode_id}:{shot}",
            episode_id=episode_id,
            episode_number=number,
            shot_id=shot,
            manifest_version=1,
            attempt_number=1,
            preset_id="preset-fast",
            tier=RenderTier.FAST_FOUR_STEP,
            required_controls=[ControlKind.TEXT_PROMPT],
            workflow_sha256=HEX64,
            seed=1,
            width=768,
            height=1344,
            fps=24,
            duration_ms=4000,
            reservation_id=uuid.uuid4(),
            prompt_text="test render",
        )

    # --- runtime helpers ------------------------------------------------------------------

    def runtime(
        self,
        handlers: dict,
        *,
        name: str = "worker-1",
        community: int = 2,
        publication: int = 1,
        production: int = 1,
        limiter: RateLimiter | None = None,
        bindings: dict | None = None,
    ) -> WorkerRuntime:
        reserved = (
            (QueueName.PRODUCTION, production),
            (QueueName.PUBLICATION, publication),
            (QueueName.COMMUNITY, community),
        )
        deployment = WorkerDeployment(
            name=name,
            slots=tuple(QueueSlots(queue, n) for queue, n in reserved if n > 0),
            handlers=handlers,
            limiter=limiter,
            bindings=bindings or {},
        )
        return WorkerRuntime(self.jobs, self.db, self.clock, deployment)

    # --- effects table ----------------------------------------------------------------------

    def create_effects_table(self) -> None:
        with self.db.transaction() as tx:
            tx.execute(
                "CREATE TABLE IF NOT EXISTS worker_effects "
                "(id uuid PRIMARY KEY, effect_key text NOT NULL UNIQUE)"
            )

    def effect_rows(self) -> list[dict[str, Any]]:
        with self.db.transaction(readonly=True) as tx:
            return [dict(row) for row in tx.fetchall("SELECT * FROM worker_effects")]

    def job_row(self, job_id: UUID) -> dict[str, Any]:
        with self.db.transaction(readonly=True) as tx:
            row = tx.fetchone("SELECT * FROM jobs WHERE id = %s", (job_id,))
        assert row is not None
        return dict(row)


__all__ = ["T0", "WorkersWorld"]
