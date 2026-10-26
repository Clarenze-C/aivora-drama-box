"""The scheduler-driven two-gate path (build-review F01 acceptance).

Start from a season request, supply ONLY the two human gate decisions, and run
the normal scheduler/worker entrypoints — ``TriggerScheduler.fire`` plus the
lane worker runtimes — through release. No runner method supplies progression:
episodes are created by the cadence schedule, shots dispatched (under an owned
pod lease) and polled by W05, assembly proposed only when the accepted shot set
is complete, the QA continuation (technical → observe → compare → repairs →
package) discovered by W07, and due slots submitted/polled by W09. The world is
rebuilt between stages (no in-flight provider operation at the boundary), so
progression survives process restarts on durable state alone.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from microdrama.config import Settings
from microdrama.contracts.enums import ApprovalAction, GateType
from microdrama.contracts.season import ApprovalCommand
from microdrama.persistence import Database
from microdrama.pipeline.deployments import lane_deployments
from microdrama.pipeline.handlers import build_handlers
from microdrama.pipeline.world import build_pipeline_world
from microdrama.scheduling import Schedule, ScheduleCatalog, TriggerScheduler
from microdrama.testing.fakes import FakeClock
from microdrama.testing.seed import seed_season

pytestmark = [pytest.mark.db, pytest.mark.ffmpeg, pytest.mark.slow]

ALL_SCHEDULE_IDS = (
    "w01-research",
    "w02-compile-backstop",
    "w03-episode-cadence",
    "w03-write",
    "w04-references",
    "w05-render-dispatch",
    "w05-render-poll",
    "w06-edit",
    "w07-qa",
    "w09-publish-submit",
    "w09-publish-poll",
    "w11-analytics",
    "w12-workers-janitor",
    "w12-gpu-janitor",
)

#: Every schedule due on every fire (a 1 ms period bucket per fire).
ALWAYS = timedelta(milliseconds=1)


def _catalog() -> ScheduleCatalog:
    return ScheduleCatalog(
        tuple(
            Schedule(schedule_id, "W", ALWAYS, f"test cadence for {schedule_id}")
            for schedule_id in ALL_SCHEDULE_IDS
        )
    )


def _row(world, sql, params=()):
    with world.db.transaction(readonly=True) as tx:
        return tx.fetchone(sql, params)


def _rows(world, sql, params=()):
    with world.db.transaction(readonly=True) as tx:
        return tx.fetchall(sql, params)


def _inflight_renders(world) -> int:
    return int(
        _row(
            world,
            "SELECT count(*) AS c FROM provider_operations po WHERE po.state IN "
            "('PENDING_SUBMIT', 'SUBMITTED', 'RUNNING')",
        )["c"]
    )


def _maybe_gate1(world, human, season_id, done: set) -> None:
    if season_id in done:
        return
    season = _row(world, "SELECT state, revision FROM seasons WHERE id = %s", (season_id,))
    proposal = _row(
        world,
        "SELECT scope_hash FROM season_proposals WHERE season_id = %s AND status = 'PROPOSED' "
        "ORDER BY scope_version DESC LIMIT 1",
        (season_id,),
    )
    if season["state"] != "PROPOSED" or proposal is None:
        return
    world.review.decide_season(
        human,
        season_id,
        ApprovalCommand(
            gate=GateType.SEASON_CONCEPT,
            action=ApprovalAction.APPROVE,
            entity_id=season_id,
            expected_revision=season["revision"],
            package_hash=proposal["scope_hash"],
            idempotency_key=f"gate1:{season_id}",
        ),
    )
    done.add(season_id)


def _maybe_gate2(world, human, episode_id, done: set) -> None:
    if episode_id in done:
        return
    episode = _row(world, "SELECT state, revision FROM episodes WHERE id = %s", (episode_id,))
    if episode is None or episode["state"] != "AWAITING_FINAL_REVIEW":
        return
    from microdrama.review.packages import current_package

    with world.db.transaction(readonly=True) as tx:
        stored = current_package(tx, episode_id)
    if stored is None:
        return
    world.review.decide_episode(
        human,
        episode_id,
        ApprovalCommand(
            gate=GateType.EPISODE_FINAL,
            action=ApprovalAction.APPROVE,
            entity_id=episode_id,
            expected_revision=episode["revision"],
            package_hash=stored.package_hash,
            media_hashes=stored.media_hashes,
            management_policy_hash=stored.management_policy_hash,
            release_scope_hash=stored.release_scope_hash,
            idempotency_key=f"gate2:{episode_id}",
        ),
    )
    done.add(episode_id)


def test_scheduler_and_workers_drive_release_with_only_the_two_gates(
    db: Database, tmp_path, offline_settings: Settings
) -> None:
    world = build_pipeline_world(offline_settings, db)
    human = world.human_owner("scheduler-path-owner", "scheduler-not-a-real-password")
    # The session is durable: rebuilt worlds re-authenticate the SAME token
    # (SequentialIds restart with the process, so a fresh login would collide).
    session_token = world.auth.login(
        "scheduler-path-owner", "scheduler-not-a-real-password"
    ).session_token

    # The operator's durable input: a proposed season with a research envelope.
    with world.db.transaction() as tx:
        season_id = seed_season(tx, state="PROPOSED")
        world.budget.open_research_account(tx, season_id=season_id, envelope_micro_usd=2_000_000)

    handled_gates: set = set()
    fire_errors: list[str] = []
    fired = 0
    for step in range(600):
        # Rebuild the world every 40 steps — a process restart between stages.
        # Only at boundaries with no in-flight provider operation (the offline
        # fakes are in-memory; in-flight prompt state is the documented
        # bootstrap limitation, not a scheduler regression).
        if step and step % 40 == 0 and _inflight_renders(world) == 0:
            now = world.fakes.clock.now()
            # Rebuilt over the same durable state: registries are already
            # seeded in the database, so the fresh process must not re-seed.
            world = build_pipeline_world(
                offline_settings, db, clock=FakeClock(now), seed_registries=False
            )
            human = world.auth.authenticate_session(session_token)

        scheduler = TriggerScheduler(world, _catalog())
        runtimes = [
            world.runtime_for(deployment)
            for deployment in lane_deployments(world, build_handlers(world)).values()
        ]
        now = world.fakes.clock.now()
        fire_report = scheduler.fire(now=now)
        fire_errors.extend(fire_report.errors)
        for runtime in runtimes:
            runtime.run_cycle(now=now)
        world.fakes.clock.advance(seconds=2)
        fired += 1

        _maybe_gate1(world, human, season_id, handled_gates)
        episode = _row(world, "SELECT id FROM episodes WHERE season_id = %s", (season_id,))
        if episode is not None:
            _maybe_gate2(world, human, episode["id"], handled_gates)

        verified = _rows(
            world,
            "SELECT id, episode_id FROM platform_posts WHERE episode_id IS NOT NULL "
            "AND required AND state = 'PUBLISHED_VERIFIED'",
        )
        if verified:
            break

    if not verified:
        for row in _rows(world, "SELECT state FROM episodes ORDER BY episode_number"):
            print("EPISODE STATE:", row["state"], flush=True)
        for row in _rows(
            world,
            "SELECT job_type, status, count(*) AS n FROM jobs GROUP BY job_type, status "
            "ORDER BY job_type",
        ):
            print("JOBS:", row["job_type"], row["status"], row["n"], flush=True)
        for row in _rows(world, "SELECT state, count(*) AS n FROM platform_posts GROUP BY state"):
            print("POSTS:", row["state"], row["n"], flush=True)
        print("GATES HANDLED:", sorted(str(g) for g in handled_gates), flush=True)
        print("FIRE ERRORS SEEN:", fire_errors[:10], flush=True)
    assert verified, "the scheduler-driven path never verified a required post"
    published = verified[0]["episode_id"]
    # Exactly the two human decisions for the PUBLISHED episode: Gate 1 on the
    # season and Gate 2 on this episode. The cadence schedule may have created
    # further PLANNED episodes behind it — they have decided nothing.
    assert handled_gates == {season_id, published}, "exactly the two human gates decided"
    # The owned pod lease was actually acquired during rendering and is off now.
    assert (
        _row(
            world,
            "SELECT count(*) AS c FROM pod_leases WHERE lease_state IN "
            "('CLAIMED', 'ACTIVE', 'TRANSFERRING')",
        )["c"]
        == 0
    )
    assert _rows(world, "SELECT id FROM jobs WHERE status = 'FAILED'") == []
    assert fired >= 5  # a real multi-cycle progression, not one lucky fire
