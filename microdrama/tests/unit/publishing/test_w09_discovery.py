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

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace

import pytest
from publishing_support import PublishingWorld

from microdrama.contracts.enums import Platform
from microdrama.contracts.errors import Conflict
from microdrama.contracts.examples import v2_owner_approved_release_approval_manifest
from microdrama.contracts.release import PublicationCommand
from microdrama.contracts.v2 import ApprovedSlotMetadata, ReleaseApprovalManifest
from microdrama.publishing import metadata as metadata_versions
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
    return TriggerScheduler(
        SimpleNamespace(db=world.db, jobs=world.jobs, settings=world.settings), catalog
    )


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


def test_concurrent_timers_dedupe_the_same_due_submit(world: PublishingWorld) -> None:
    _season, episode, _package, _approval = world.approved_episode()
    world.schedule(episode)
    post = world.row("SELECT * FROM platform_posts WHERE episode_id = %s", (episode,))
    instant = world.clock.now()

    def fire_once():
        return _scheduler(world).fire(now=instant, only={"w09-publish-submit"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        reports = list(pool.map(lambda _index: fire_once(), range(2)))

    assert all(report.errors == [] for report in reports)
    assert sum(report.enqueued_jobs for report in reports) == 1
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
            allow_mock_metadata=True,
        )
        assert command.slot.dedupe_key == post["dedupe_key"], (
            "the command must carry THIS post's slot key, not the first name match"
        )


def test_absent_rearmed_slot_is_discovered_once_with_current_metadata(
    world: PublishingWorld,
) -> None:
    _season, episode, package, approval = world.approved_episode()
    world.adapters[Platform.YOUTUBE].queue_scenarios(PublishScenario.TIMEOUT_NOT_CREATED)
    world.schedule(episode)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    first_job = world.submit_job(command)
    world.service.submit_slot(command, job_id=first_job)
    with world.db.transaction() as tx:
        tx.execute("UPDATE jobs SET status = 'SUCCEEDED' WHERE id = %s", (first_job,))
    post = world.row("SELECT * FROM platform_posts WHERE episode_id = %s", (episode,))
    world.clock.advance(seconds=301)
    world.service.reconcile_slot(post["id"])
    assert world.post_row(post["id"])["state"] == "SUBMITTED"
    with world.db.transaction(readonly=True) as tx:
        current = metadata_versions.current_metadata(tx, post["id"])
    assert current is not None

    scheduler = _scheduler(world)
    first = scheduler.fire(now=world.clock.now(), only={"w09-publish-submit"})
    assert first.errors == []
    assert first.enqueued_jobs == 1
    submit_job = world.row(
        "SELECT id, input FROM jobs WHERE job_type = 'publish.submit_slot' "
        "AND input -> 'slot' ->> 'episode_id' = %s::text "
        "AND status = 'QUEUED' ORDER BY created_at DESC LIMIT 1",
        (str(episode),),
    )
    payload = submit_job["input"]
    assert payload["metadata_version_id"] == str(current[0])
    assert payload["metadata"] == current[1].model_dump(mode="json")

    # A fresh scheduler instance after the simulated restart sees the pending
    # proposal and cannot stack another submit. Executing that proposal uses the
    # persisted metadata, then normal provider readback verifies visibility.
    resumed_scheduler = _scheduler(world)
    world.clock.advance(seconds=2)
    again = resumed_scheduler.fire(now=world.clock.now(), only={"w09-publish-submit"})
    assert again.errors == []
    assert again.enqueued_jobs == 0
    retry_command = PublicationCommand.model_validate(payload)
    submitted = world.service.submit_slot(retry_command, job_id=submit_job["id"])
    assert submitted["state"] == "SUBMITTED"
    assert submitted["external_id"] is not None
    world.service.poll_status(post["id"])
    verified = world.service.poll_status(post["id"])
    assert verified["state"] == "PUBLISHED_VERIFIED"

    assert _submit_count(world, post) == 2  # first ambiguous operation + one rearm proposal


def test_command_builder_refuses_implicit_mock_metadata(world: PublishingWorld) -> None:
    _season, episode, package, approval = world.approved_episode()
    world.schedule(episode)
    post = world.row("SELECT * FROM platform_posts WHERE episode_id = %s", (episode,))
    from microdrama.publishing.commands import publication_command_for_post

    with pytest.raises(Conflict, match="approved slot metadata is missing"):
        publication_command_for_post(
            None,
            post=dict(post),
            package_body=package.model_dump(mode="json"),
            approval_event_id=approval,
        )


def test_fresh_live_command_projects_canonical_slot_metadata_and_initial_version(
    world: PublishingWorld,
) -> None:
    _season, episode, package, approval = world.approved_episode()
    world.schedule(episode)
    post = world.row("SELECT * FROM platform_posts WHERE episode_id = %s", (episode,))
    source = v2_owner_approved_release_approval_manifest()
    slot_fields = source.slots[0].model_dump(mode="python")
    slot_fields.update(
        release_package_id=package.package_id,
        release_package_hash=package.package_hash,
        slot_id=f"slot-{post['dedupe_key']}",
    )
    approved_slot = ApprovedSlotMetadata.seal(**slot_fields)
    manifest_fields = source.model_dump(mode="python")
    manifest_fields.update(
        release_package_id=package.package_id,
        release_package_hash=package.package_hash,
        slots=[approved_slot],
    )
    manifest = ReleaseApprovalManifest.seal(**manifest_fields)

    from microdrama.publishing.commands import publication_command_for_post

    command = publication_command_for_post(
        None,
        post=dict(post),
        package_body=package.model_dump(mode="json"),
        approval_event_id=approval,
        metadata=None,
        metadata_version_id=None,
        release_manifest=manifest,
        approved_slot_metadata=approved_slot,
    )
    assert command.metadata.title == approved_slot.title
    assert command.metadata.cover_asset_id == approved_slot.cover_asset_id
    assert command.metadata.cover_asset_version == approved_slot.cover_asset_version
    assert command.metadata.cover_asset_sha256 == approved_slot.cover_asset_sha256
    assert command.metadata.cta_text == approved_slot.cta_text
    assert command.metadata_version_id == metadata_versions.initial_metadata_version_id(
        post["dedupe_key"]
    )
    assert command.approved_metadata_version == approved_slot.metadata_version
    assert command.approved_metadata_sha256 == approved_slot.content_sha256


def test_live_command_builder_rejects_mock_labeled_supplied_metadata(
    world: PublishingWorld,
) -> None:
    _season, episode, package, approval = world.approved_episode()
    world.schedule(episode)
    post = world.row("SELECT * FROM platform_posts WHERE episode_id = %s", (episode,))
    from microdrama.publishing.commands import publication_command_for_post

    with pytest.raises(Conflict, match="mock-labeled publication metadata"):
        publication_command_for_post(
            None,
            post=dict(post),
            package_body=package.model_dump(mode="json"),
            approval_event_id=approval,
            metadata=world.metadata(title="Pilot episode (mock)"),
        )


def test_live_command_builder_accepts_ordinary_words_containing_test(
    world: PublishingWorld,
) -> None:
    _season, episode, package, approval = world.approved_episode()
    world.schedule(episode)
    post = world.row("SELECT * FROM platform_posts WHERE episode_id = %s", (episode,))
    from microdrama.publishing.commands import publication_command_for_post

    command = publication_command_for_post(
        None,
        post=dict(post),
        package_body=package.model_dump(mode="json"),
        approval_event_id=approval,
        metadata=world.metadata(title="Contest of promises"),
    )
    assert command.metadata.title == "Contest of promises"
