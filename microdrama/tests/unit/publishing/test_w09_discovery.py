"""W09 publication discovery pins (build-review F01 follow-ups).

The submit/poll schedules are discovery-only, but discovery must be
single-flight and complete: a submit proposal still pending must not be joined
by a second one from a later period (the stale sibling would execute against
the slot the first job moved — HELD, PROCESSING — and die on Conflict), and a
slot parked by an ambiguous submit must get its ``publish.reconcile_slot``
proposal so the publication lane clears its own ambiguity. No runner method
supplies either.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from publishing_support import PublishingWorld

from microdrama.contracts.enums import Platform
from microdrama.scheduling import Schedule, ScheduleCatalog, TriggerScheduler
from microdrama.testing.fakes.publishing import PublishScenario

ALWAYS = timedelta(milliseconds=1)


def _scheduler(world: PublishingWorld) -> TriggerScheduler:
    catalog = ScheduleCatalog(
        tuple(
            Schedule(schedule_id, "W", ALWAYS, f"test cadence for {schedule_id}")
            for schedule_id in ("w09-publish-submit", "w09-publish-poll")
        )
    )
    # The W09 handlers touch only the durable job surface; the full pipeline
    # world is not needed to pin their discovery SQL.
    return TriggerScheduler(SimpleNamespace(db=world.db, jobs=world.jobs), catalog)


def _count_jobs(world: PublishingWorld, sql: str, params: tuple) -> int:
    return int(world.row(sql, params)["n"])


_SUBMITS_FOR_SLOT = (
    "SELECT count(*) AS n FROM jobs WHERE job_type = 'publish.submit_slot' "
    "AND input -> 'slot' ->> 'episode_id' = %s::text "
    "AND input -> 'slot' ->> 'release_slot' = %s "
    "AND input -> 'slot' ->> 'platform' = %s "
    "AND input -> 'slot' ->> 'account_ref' = %s"
)


def _submit_count(world: PublishingWorld, post: dict) -> int:
    return _count_jobs(
        world,
        _SUBMITS_FOR_SLOT,
        (post["episode_id"], post["release_slot"], post["platform"], post["account_ref"]),
    )


def test_a_pending_submit_proposal_is_never_stacked_by_a_later_period(
    world: PublishingWorld,
) -> None:
    _season, episode, package, approval = world.approved_episode()
    world.schedule(episode)
    post = world.row("SELECT * FROM platform_posts WHERE episode_id = %s", (episode,))
    scheduler = _scheduler(world)

    first = scheduler.fire(now=world.clock.now(), only={"w09-publish-submit"})
    assert first.errors == []
    assert first.enqueued_jobs == 1, "a due scheduled slot with no pending submit is proposed"
    assert _submit_count(world, post) == 1

    # The proposal is still queued (no worker has run it) and the slot is
    # still SCHEDULED, so a naive later period would stack a second proposal
    # under a fresh period key. The pending-job guard must hold it back.
    world.clock.advance(seconds=2)
    second = scheduler.fire(now=world.clock.now(), only={"w09-publish-submit"})
    assert second.errors == []
    assert second.enqueued_jobs == 0, "one submit proposal per slot in flight, ever"
    assert _submit_count(world, post) == 1


def test_an_ambiguous_submit_gets_a_reconcile_proposal_not_a_poll(
    world: PublishingWorld,
) -> None:
    _season, episode, package, approval = world.approved_episode()
    world.adapters[Platform.YOUTUBE].queue_scenarios(PublishScenario.TIMEOUT_NOT_CREATED)
    world.schedule(episode)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    updated = world.service.submit_slot(command, job_id=world.submit_job(command))
    assert updated["state"] == "NEEDS_RECONCILIATION"
    post = world.row("SELECT * FROM platform_posts WHERE episode_id = %s", (episode,))
    assert post["external_id"] is None
    scheduler = _scheduler(world)

    report = scheduler.fire(now=world.clock.now(), only={"w09-publish-poll"})
    assert report.errors == []
    assert (
        _count_jobs(
            world,
            "SELECT count(*) AS n FROM jobs WHERE job_type = 'publish.reconcile_slot' "
            "AND input ->> 'platform_post_id' = %s",
            (str(post["id"]),),
        )
        == 1
    ), "the ambiguous slot gets exactly one reconcile proposal"
    assert world.rows("SELECT id FROM jobs WHERE job_type = 'publish.poll_status'") == [], (
        "a slot without an external id is reconcile work, never poll work"
    )

    # Single-flight: the pending reconcile holds the next period too.
    world.clock.advance(seconds=2)
    again = scheduler.fire(now=world.clock.now(), only={"w09-publish-poll"})
    assert again.errors == []
    assert (
        _count_jobs(
            world,
            "SELECT count(*) AS n FROM jobs WHERE job_type = 'publish.reconcile_slot' "
            "AND input ->> 'platform_post_id' = %s",
            (str(post["id"]),),
        )
        == 1
    )


def test_a_submitted_slot_whose_outcome_is_unknown_is_reconcile_work(
    world: PublishingWorld,
) -> None:
    # The crash-between-sent-and-recorded shape: the slot says SUBMITTED but
    # carries no external id and its operation went UNKNOWN. Polling it can
    # only fail; discovery must propose the reconcile instead.
    _season, episode, package, approval = world.approved_episode()
    world.schedule(episode)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    world.service.submit_slot(command, job_id=world.submit_job(command))
    post = world.row("SELECT * FROM platform_posts WHERE episode_id = %s", (episode,))
    assert post["external_id"] is not None
    with world.db.transaction() as tx:
        tx.execute("UPDATE platform_posts SET external_id = NULL WHERE id = %s", (post["id"],))
        tx.execute(
            "UPDATE provider_operations SET state = 'UNKNOWN' WHERE id = %s",
            (post["provider_operation_id"],),
        )

    report = _scheduler(world).fire(now=world.clock.now(), only={"w09-publish-poll"})
    assert report.errors == []
    assert (
        _count_jobs(
            world,
            "SELECT count(*) AS n FROM jobs WHERE job_type = 'publish.reconcile_slot' "
            "AND input ->> 'platform_post_id' = %s",
            (str(post["id"]),),
        )
        == 1
    )
    assert world.rows("SELECT id FROM jobs WHERE job_type = 'publish.poll_status'") == []


def test_a_command_targets_its_slot_by_dedupe_key_not_by_name(world: PublishingWorld) -> None:
    # release_slot names repeat across platforms inside one scope (the composed
    # scope ships "full"/"short" on every destination). A name-matched command
    # carried another slot's dedupe key: submit locked and moved THAT slot's
    # post while this one waited forever.
    def same_name_on_two_platforms(season_id, episode_id, master):
        return [
            world.slot_plan(
                season_id=season_id,
                episode_id=episode_id,
                asset=master,
                slot="short",
                platform=Platform.TIKTOK,
                account_ref="acct:tiktok-main",
            ),
            world.slot_plan(
                season_id=season_id,
                episode_id=episode_id,
                asset=master,
                slot="short",
                platform=Platform.INSTAGRAM,
                account_ref="acct:ig-main",
            ),
        ]

    _season, episode, package, approval = world.approved_episode(
        scope_builder=same_name_on_two_platforms
    )
    world.schedule(episode)
    posts = world.rows("SELECT * FROM platform_posts WHERE episode_id = %s", (episode,))
    assert len(posts) == 2 and {p["platform"] for p in posts} == {"TIKTOK", "INSTAGRAM"}

    from microdrama.publishing.commands import publication_command_for_post

    for post in posts:
        command = publication_command_for_post(
            None,
            post=dict(post),
            package_body=package.model_dump(mode="json"),
            approval_event_id=approval,
        )
        assert command.slot.dedupe_key == post["dedupe_key"], (
            "the command must carry THIS post's slot key, not the first name match"
        )
