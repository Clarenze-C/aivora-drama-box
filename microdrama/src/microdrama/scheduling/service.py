"""Schedule firing: due schedules become durable jobs or direct actions (T029).

``TriggerScheduler.fire`` is invoked by the deployment timer (systemd/service
loop calling ``python -m microdrama.scheduling.fire``, or the demo runner) and
is safe to call concurrently or after a crash:

- job-schedules discover their due work from durable state (seasons, episodes,
  posts, operations) and enqueue frozen job types with period-bucketed semantic
  keys — one enqueue per period per entity, ever;
- action-schedules (W05 reconcile polling, W12 janitors) run their sweep
  directly: they are the "independent timer" the SPEC requires, never queued
  behind a blocked queue;
- firing state (``schedule_state`` rows) only prevents busy-spinning; missing
  state can never duplicate an effect because the semantic keys dedupe.

No schedule reads a secret, checks a capability or evaluates a gate: it only
proposes work. The owning services stay the sole authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from microdrama.contracts.jobs import EpisodeStepInput, SeasonStepInput
from microdrama.persistence.db import Tx


@dataclass
class FireReport:
    fired: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    enqueued_jobs: int = 0
    actions: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "fired": self.fired,
            "skipped": self.skipped,
            "enqueued_jobs": self.enqueued_jobs,
            "actions": self.actions,
        }


def load_last_fired(tx: Tx) -> dict[str, datetime]:
    rows = tx.fetchall("SELECT schedule_id, last_fired_at FROM schedule_state")
    return {row["schedule_id"]: row["last_fired_at"] for row in rows}


def record_fired(tx: Tx, schedule_id: str, now: datetime) -> None:
    tx.execute(
        "INSERT INTO schedule_state (schedule_id, last_fired_at, fired_count) "
        "VALUES (%s, %s, 1) ON CONFLICT (schedule_id) DO UPDATE "
        "SET last_fired_at = excluded.last_fired_at, "
        "fired_count = schedule_state.fired_count + 1",
        (schedule_id, now),
    )


class TriggerScheduler:
    """Fires the due schedules of one catalog against the composed world."""

    def __init__(self, world, catalog) -> None:
        self.world = world
        self.catalog = catalog

    # --- public ---------------------------------------------------------------------------

    def fire(self, *, now: datetime | None = None, only: set[str] | None = None) -> FireReport:
        instant = now or self.world.fakes.clock.now()
        report = FireReport()
        with self.world.db.transaction(readonly=True) as tx:
            last_fired = load_last_fired(tx)
        for schedule in self.catalog.due(instant, last_fired=last_fired):
            if only is not None and schedule.schedule_id not in only:
                continue
            handler = getattr(self, f"_{schedule.schedule_id.replace('-', '_')}", None)
            if handler is None:
                report.skipped.append(schedule.schedule_id)
                continue
            handler(instant, report)
            report.fired.append(schedule.schedule_id)
            with self.world.db.transaction() as tx:
                record_fired(tx, schedule.schedule_id, instant)
        return report

    # --- enqueue helpers --------------------------------------------------------------------

    def _enqueue(
        self,
        job_type: str,
        payload,
        report: FireReport,
        *,
        semantic_key: str,
        episode_id=None,
        season_id=None,
    ) -> None:
        with self.world.db.transaction() as tx:
            result = self.world.jobs.enqueue(
                tx,
                job_type=job_type,
                semantic_key=semantic_key,
                payload=payload,
                episode_id=episode_id,
                season_id=season_id,
            )
        if result.created:
            report.enqueued_jobs += 1

    def _period(self, schedule_id: str, now: datetime) -> str:
        schedule = next(s for s in self.catalog.schedules if s.schedule_id == schedule_id)
        return self.catalog.period_key(schedule, now)

    # --- job schedules ------------------------------------------------------------------------

    def _w01_research(self, now: datetime, report: FireReport) -> None:
        with self.world.db.transaction(readonly=True) as tx:
            seasons = tx.fetchall(
                "SELECT id FROM seasons WHERE state = 'PROPOSED' ORDER BY created_at"
            )
        for season in seasons:
            self._enqueue(
                "research.collect_and_propose",
                SeasonStepInput(season_id=season["id"], trigger="scheduled"),
                report,
                semantic_key=f"{self._period('w01-research', now)}:{season['id']}",
                season_id=season["id"],
            )

    def _w02_compile_backstop(self, now: datetime, report: FireReport) -> None:
        with self.world.db.transaction(readonly=True) as tx:
            seasons = tx.fetchall(
                "SELECT s.id, s.approved_scope_version FROM seasons s "
                "WHERE s.state = 'SEASON_APPROVED' AND NOT EXISTS ("
                "  SELECT 1 FROM canon_versions c WHERE c.season_id = s.id AND c.kind = 'PLANNED')"
            )
        for season in seasons:
            self._enqueue(
                "story.compile_season",
                SeasonStepInput(season_id=season["id"], trigger="backstop"),
                report,
                semantic_key=f"{self._period('w02-compile-backstop', now)}:{season['id']}",
                season_id=season["id"],
            )

    def _w03_write(self, now: datetime, report: FireReport) -> None:
        with self.world.db.transaction(readonly=True) as tx:
            episodes = tx.fetchall(
                "SELECT e.id FROM episodes e JOIN seasons s ON s.id = e.season_id "
                "WHERE e.state = 'PLANNED' AND s.state = 'SEASON_APPROVED' "
                "AND EXISTS (SELECT 1 FROM canon_versions c "
                "  WHERE c.season_id = s.id AND c.kind = 'PLANNED') "
                "AND e.id NOT IN (SELECT episode_id FROM scripts WHERE status = 'CURRENT')"
            )
        for episode in episodes:
            self._enqueue(
                "story.write_episode",
                EpisodeStepInput(episode_id=episode["id"], trigger="cadence"),
                report,
                semantic_key=f"{self._period('w03-write', now)}:{episode['id']}",
                episode_id=episode["id"],
            )

    def _w04_references(self, now: datetime, report: FireReport) -> None:
        with self.world.db.transaction(readonly=True) as tx:
            episodes = tx.fetchall(
                "SELECT e.id FROM episodes e WHERE e.state IN ('SCRIPTING', 'REFERENCES') "
                "AND EXISTS (SELECT 1 FROM scripts s WHERE s.episode_id = e.id "
                "  AND s.status = 'CURRENT')"
            )
        for episode in episodes:
            self._enqueue(
                "references.prepare_episode",
                EpisodeStepInput(episode_id=episode["id"], trigger="scheduled"),
                report,
                semantic_key=f"{self._period('w04-references', now)}:{episode['id']}",
                episode_id=episode["id"],
            )

    def _w06_edit(self, now: datetime, report: FireReport) -> None:
        with self.world.db.transaction(readonly=True) as tx:
            assemble = tx.fetchall(
                "SELECT e.id FROM episodes e WHERE e.state = 'RENDERING' AND NOT EXISTS ("
                "  SELECT 1 FROM edit_manifests m WHERE m.episode_id = e.id "
                "  AND m.variant_key = 'main')"
            )
            variants = tx.fetchall(
                "SELECT e.id FROM episodes e WHERE e.state = 'AI_REVIEW' AND EXISTS ("
                "  SELECT 1 FROM edit_manifests m WHERE m.episode_id = e.id "
                "  AND m.variant_key = 'main' AND m.output_asset_id IS NOT NULL)"
                " AND NOT EXISTS (SELECT 1 FROM edit_manifests m2 "
                "  WHERE m2.episode_id = e.id AND m2.variant_key <> 'main')"
            )
        for episode in assemble:
            self._enqueue(
                "edit.assemble_episode",
                EpisodeStepInput(episode_id=episode["id"], trigger="scheduled"),
                report,
                semantic_key=f"{self._period('w06-edit', now)}:a:{episode['id']}",
                episode_id=episode["id"],
            )
        for episode in variants:
            self._enqueue(
                "edit.variants_and_hooks",
                EpisodeStepInput(episode_id=episode["id"], trigger="scheduled"),
                report,
                semantic_key=f"{self._period('w06-edit', now)}:v:{episode['id']}",
                episode_id=episode["id"],
            )

    def _w07_qa(self, now: datetime, report: FireReport) -> None:
        with self.world.db.transaction(readonly=True) as tx:
            episodes = tx.fetchall(
                "SELECT e.id FROM episodes e WHERE e.state = 'AI_REVIEW' AND EXISTS ("
                "  SELECT 1 FROM edit_manifests m WHERE m.episode_id = e.id "
                "  AND m.variant_key = 'main' AND m.output_asset_id IS NOT NULL) "
                "AND e.id NOT IN (SELECT episode_id FROM qa_findings)"
                " AND e.id NOT IN (SELECT episode_id FROM release_packages)"
            )
        for episode in episodes:
            self._enqueue(
                "qa.technical",
                EpisodeStepInput(episode_id=episode["id"], trigger="scheduled"),
                report,
                semantic_key=f"{self._period('w07-qa', now)}:{episode['id']}",
                episode_id=episode["id"],
            )

    def _w09_publish_poll(self, now: datetime, report: FireReport) -> None:
        from microdrama.contracts.jobs import PlatformPostRef

        with self.world.db.transaction(readonly=True) as tx:
            posts = tx.fetchall(
                "SELECT id FROM platform_posts WHERE state = 'SUBMITTED' "
                "AND updated_at <= %s ORDER BY updated_at",
                (now,),
            )
        for post in posts:
            self._enqueue(
                "publish.poll_status",
                PlatformPostRef(platform_post_id=post["id"]),
                report,
                semantic_key=f"{self._period('w09-publish-poll', now)}:{post['id']}",
            )

    def _w11_analytics(self, now: datetime, report: FireReport) -> None:
        from microdrama.contracts.jobs import MetricWindowInput

        with self.world.db.transaction(readonly=True) as tx:
            verified = tx.fetchall(
                "SELECT id FROM platform_posts WHERE state = 'PUBLISHED_VERIFIED'"
            )
        for row in verified:
            for window in self.world.analytics.due_windows(row["id"]):
                self._enqueue(
                    "analytics.snapshot",
                    MetricWindowInput(platform_post_id=row["id"], window=window.window),
                    report,
                    semantic_key=(
                        f"{self._period('w11-analytics', now)}:{row['id']}:{window.window.value}"
                    ),
                )

    # --- action schedules (never queued) --------------------------------------------------------

    def _w05_render_poll(self, now: datetime, report: FireReport) -> None:
        """Reconcile stale in-flight render operations (submit/poll/recover, T013)."""
        from microdrama.contracts.enums import PrincipalKind, ProviderOperationState
        from microdrama.contracts.principals import Principal

        monitor = Principal(principal_id="svc:schedule-render", kind=PrincipalKind.SCHEDULER)
        with self.world.db.transaction(readonly=True) as tx:
            stale = tx.fetchall(
                "SELECT id, job_id FROM provider_operations WHERE provider = 'comfy' "
                "AND state IN ('PENDING_SUBMIT', 'SUBMITTED', 'RUNNING') "
                "AND updated_at <= %s ORDER BY created_at",
                (now,),
            )
        polled = resolved = 0
        for operation in stale:
            try:
                status = self.world.comfy.poll(operation["id"])
            except Exception:  # noqa: BLE001 - ambiguous outcomes need reconcile, not death
                continue
            polled += 1
            if status.state is ProviderOperationState.SUCCEEDED and operation["job_id"]:
                self.world.jobs.resolve_reconciliation(
                    operation["job_id"],
                    actor=monitor,
                    resolution="SUCCEEDED",
                    evidence=f"scheduled poll: operation {operation['id']} succeeded",
                    now=now,
                )
                resolved += 1
        report.actions["w05"] = {"polled": polled, "resolved": resolved}

    def _w12_workers_janitor(self, now: datetime, report: FireReport) -> None:
        sweep = self.world.workers_janitor.sweep(now=now)
        report.actions["w12-workers"] = {
            "steps": len(sweep.steps),
            "failures": len(sweep.failures),
        }

    def _w12_gpu_janitor(self, now: datetime, report: FireReport) -> None:
        sweep = self.world.gpu_janitor.sweep()
        report.actions["w12-gpu"] = {
            "stopped_pods": len(sweep.stopped_pods),
            "orphan_pods": len(sweep.orphan_pods),
            "failures": len(sweep.failures),
        }


__all__ = ["FireReport", "TriggerScheduler", "load_last_fired", "record_fired"]
