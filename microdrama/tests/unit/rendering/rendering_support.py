"""Shared builders for the rendering (T012) tests: a world wiring the real services
against the T007 FakePodProvider, the real budget service and the real database."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from microdrama.budget import BudgetService
from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode
from microdrama.contracts.season import CostPolicy
from microdrama.persistence import Database
from microdrama.persistence.db import IsolationLevel
from microdrama.rendering import (
    Janitor,
    LeaseService,
    PodLeaseClaimRequest,
    PodLeaseConfig,
    PodManager,
    build_janitor,
    build_lease_service,
)
from microdrama.testing.fakes import FakeClock, FakePodProvider, SequentialIds
from microdrama.testing.seed import seed_episode, seed_job, seed_season

T0 = datetime(2026, 10, 20, tzinfo=UTC)
GPU_SECOND_MICRO = 250  # the mock price, matching the fake pod's 900_000 micro-USD/hour


@dataclass(frozen=True)
class Episode:
    season_id: uuid.UUID
    episode_id: uuid.UUID
    account_id: uuid.UUID


class RenderWorld:
    """Real PostgreSQL, real budget service, fake pod provider, deterministic clock."""

    def __init__(
        self,
        db: Database,
        *,
        settings: Settings | None = None,
        config: PodLeaseConfig | None = None,
        create_steps: tuple[Any, ...] = (),
    ) -> None:
        self.db = db
        self.clock = FakeClock(T0)
        self.settings = settings or Settings(execution_mode=ExecutionMode.OFFLINE_MOCK)
        self.config = config or PodLeaseConfig.for_mock()
        self.provider = FakePodProvider(
            clock=self.clock, ids=SequentialIds("render-pods"), scenarios=create_steps
        )
        self.ids = SequentialIds("render")
        self.budget = BudgetService(db, self.clock, self.ids, self.settings)
        self.manager = PodManager(
            self.provider,
            self.clock,
            self.config,
            stop_attempts=self.config.stop_attempts,
            create_attempts=self.config.create_attempts,
        )
        self.leases: LeaseService = build_lease_service(
            db, self.budget, self.manager, self.clock, self.ids, self.settings, self.config
        )

    def janitor(self, *, config: PodLeaseConfig | None = None) -> Janitor:
        """A fresh, independently constructed janitor over the same durable state."""
        return build_janitor(
            self.db,
            BudgetService(self.db, self.clock, self.ids, self.settings),
            self.provider,
            self.clock,
            self.ids,
            self.settings,
            config or self.config,
        )

    # --- seeding ------------------------------------------------------------------

    def episode(self, *, state: str = "PLANNED", number: int = 1) -> Episode:
        with self.db.transaction() as tx:
            season_id = seed_season(tx)
            episode_id = seed_episode(tx, season_id, number=number, state=state)
            account_id = self.budget.open_episode_account(
                tx, season_id=season_id, episode_id=episode_id, policy=CostPolicy()
            )
        return Episode(season_id, episode_id, account_id)

    def job(self, key: str) -> uuid.UUID:
        with self.db.transaction() as tx:
            return seed_job(tx, semantic_key=key, job_type="render.pod_lease")

    # --- lease helpers -------------------------------------------------------------

    def claim(
        self,
        episode: Episode,
        key: str,
        *,
        gpu: str = "FAKE-GPU-24GB",
        ram: int = 32,
        job: uuid.UUID | None = None,
        ttl_ms: int | None = None,
    ):
        return self.leases.claim(
            PodLeaseClaimRequest(
                episode_id=episode.episode_id,
                semantic_key=key,
                gpu_type=gpu,
                host_ram_gb=ram,
                job_id=job,
                lease_ttl_ms=ttl_ms,
            )
        )

    def claim_and_acquire(self, episode: Episode, key: str, **kwargs):
        handle = self.claim(episode, key, **kwargs)
        return handle, self.leases.ensure_pod(handle.lease.lease_id)

    # --- reads ---------------------------------------------------------------------

    def lease_row(self, lease_id: uuid.UUID) -> dict[str, Any]:
        with self.db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
            row = tx.fetchone("SELECT * FROM pod_leases WHERE id = %s", (lease_id,))
        assert row is not None
        return row

    def live_leases(self) -> list[dict[str, Any]]:
        with self.db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
            return tx.fetchall(
                "SELECT * FROM pod_leases WHERE lease_state IN "
                "('CLAIMED', 'ACTIVE', 'TRANSFERRING') ORDER BY created_at"
            )

    def reservation_row(self, reservation_id: uuid.UUID) -> dict[str, Any]:
        with self.db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
            row = tx.fetchone("SELECT * FROM reservations WHERE id = %s", (reservation_id,))
        assert row is not None
        return row

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
            "blocked": row["paid_dispatch_blocked"],
        }

    def intervals(self, pod_id: str | None = None) -> list[dict[str, Any]]:
        with self.db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
            if pod_id is None:
                return tx.fetchall(
                    "SELECT * FROM pod_usage_intervals ORDER BY pod_id, interval_start"
                )
            return tx.fetchall(
                "SELECT * FROM pod_usage_intervals WHERE pod_id = %s ORDER BY interval_start",
                (pod_id,),
            )

    def charges(self, reservation_id: uuid.UUID) -> list[dict[str, Any]]:
        with self.db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
            return tx.fetchall(
                "SELECT * FROM charges WHERE reservation_id = %s ORDER BY created_at",
                (reservation_id,),
            )

    def lease_events(self, lease_id: uuid.UUID) -> list[tuple[str, datetime]]:
        with self.db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
            rows = tx.fetchall(
                "SELECT event_type, occurred_at FROM domain_events WHERE aggregate_id = %s "
                "ORDER BY sequence",
                (lease_id,),
            )
        return [(row["event_type"], row["occurred_at"]) for row in rows]

    def janitor_events(self) -> list[dict[str, Any]]:
        with self.db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
            return tx.fetchall(
                "SELECT * FROM domain_events WHERE aggregate_type = 'janitor_action' "
                "ORDER BY global_position"
            )

    def owned_pods(self) -> list[Any]:
        return [pod for pod in self.provider.find_pods() if pod.owned_tag == self.config.owned_tag]
