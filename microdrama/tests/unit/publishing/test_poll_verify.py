"""T020 poll and verification: status progression, readback gate, episode completion."""

from __future__ import annotations

import pytest
from publishing_support import PublishingWorld

from microdrama.contracts.enums import Platform, SlotKind
from microdrama.publishing.service import REQUIRED_VERIFY_FIELDS


def _submitted(world: PublishingWorld):
    season_id, episode_id, package, approval = world.approved_episode()
    world.schedule(episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    job_id = world.submit_job(command)
    world.service.submit_slot(command, job_id=job_id)
    post = world.row("SELECT * FROM platform_posts WHERE episode_id = %s", (episode_id,))
    return episode_id, command, post["id"]


def test_status_progresses_submitted_to_processing(world: PublishingWorld) -> None:
    _e, _c, post_id = _submitted(world)
    updated = world.service.poll_status(post_id)
    assert updated["state"] == "PROCESSING"


def test_verified_publication_completes_the_episode(world: PublishingWorld) -> None:
    episode_id, _c, post_id = _submitted(world)
    world.service.poll_status(post_id)  # -> PROCESSING
    updated = world.service.poll_status(post_id)  # announced published + readback gate

    assert updated["state"] == "PUBLISHED_VERIFIED"
    assert updated["verified_at"] is not None
    assert updated["external_id"] is not None
    assert list(updated["verified_fields"]) == list(REQUIRED_VERIFY_FIELDS)
    assert world.episode_state(episode_id) == "PUBLISHED_VERIFIED"
    op = world.row(
        "SELECT state FROM provider_operations WHERE operation_kind = 'publish.submit_slot'"
    )
    assert op["state"] == "SUCCEEDED"
    # the DB CHECK holds: verified rows always carry external id + verified_at
    row = world.post_row(post_id)
    assert row["external_id"] is not None and row["verified_at"] is not None


def test_unknown_readback_is_a_gap_not_a_verification(world: PublishingWorld, monkeypatch) -> None:
    _e, _c, post_id = _submitted(world)
    world.service.poll_status(post_id)  # PROCESSING
    adapter = world.adapters[Platform.YOUTUBE]
    original = adapter.readback

    def blind_readback(account_ref, external_id):
        result = original(account_ref, external_id)
        return result.model_copy(
            update={
                "visible": None,  # the provider could not confirm visibility
                "unverified_fields": ["visibility", "disclosures"],
            }
        )

    monkeypatch.setattr(adapter, "readback", blind_readback)
    updated = world.service.poll_status(post_id)
    assert updated["state"] == "PROCESSING"  # never verified on an unknown readback
    assert "visibility" in updated["unverified_fields"]
    assert world.episode_state(_e) == "PUBLISHING"

    # once the readback can prove it, the same poll verifies
    monkeypatch.setattr(adapter, "readback", original)
    updated = world.service.poll_status(post_id)
    assert updated["state"] == "PUBLISHED_VERIFIED"


def test_partial_disclosure_readback_does_not_verify(world: PublishingWorld, monkeypatch) -> None:
    _e, _c, post_id = _submitted(world)
    world.service.poll_status(post_id)
    adapter = world.adapters[Platform.YOUTUBE]
    original = adapter.readback

    def partial_readback(account_ref, external_id):
        result = original(account_ref, external_id)
        return result.model_copy(update={"disclosures_visible": []})  # none visible

    monkeypatch.setattr(adapter, "readback", partial_readback)
    updated = world.service.poll_status(post_id)
    assert updated["state"] == "PROCESSING"
    assert updated["verified_at"] is None


def test_poll_on_unsubmitted_slot_is_refused(world: PublishingWorld) -> None:
    season_id, episode_id, package, approval = world.approved_episode()
    post_ids = world.schedule(episode_id)
    with pytest.raises(Exception):  # noqa: B017 - Conflict: nothing to poll
        world.service.poll_status(post_ids[0])


def test_episode_completes_only_after_every_required_slot(world: PublishingWorld) -> None:
    def scope(season_id, episode_id, master):
        yt = world.slot_plan(season_id=season_id, episode_id=episode_id, asset=master, slot="full")
        tt = world.slot_plan(
            season_id=season_id,
            episode_id=episode_id,
            asset=master,
            slot="full-tt",
            platform=Platform.TIKTOK,
            account_ref="acct:tiktok-main",
            required=True,
        )
        promo = world.slot_plan(
            season_id=season_id,
            episode_id=episode_id,
            asset=master,
            slot="promo",
            slot_kind=SlotKind.PROMO_CUT,
            required=False,
            platform=Platform.TIKTOK,
            account_ref="acct:tiktok-main",
        )
        return [yt, tt, promo]

    _s, episode_id, package, approval = world.approved_episode(scope_builder=scope)
    world.schedule(episode_id)

    # verify the YouTube slot fully
    yt_command = world.command(
        package.release_scope[0], package=package, approval_event_id=approval
    )
    world.service.submit_slot(yt_command, job_id=world.submit_job(yt_command))
    yt_post = world.post_by_slot("full", episode_id)
    world.service.poll_status(yt_post["id"])
    world.service.poll_status(yt_post["id"])
    assert world.episode_state(episode_id) == "PUBLISHING"  # TikTok required still open

    # verify the TikTok required slot: now the episode completes (promo optional)
    tt_command = world.command(
        package.release_scope[1], package=package, approval_event_id=approval
    )
    world.service.submit_slot(tt_command, job_id=world.submit_job(tt_command))
    tt_post = world.post_by_slot("full-tt", episode_id)
    world.service.poll_status(tt_post["id"])
    world.service.poll_status(tt_post["id"])
    assert world.episode_state(episode_id) == "PUBLISHED_VERIFIED"

    # the optional promo may still submit afterwards (content waterfall)
    promo_command = world.command(
        package.release_scope[2], package=package, approval_event_id=approval
    )
    updated = world.service.submit_slot(promo_command, job_id=world.submit_job(promo_command))
    assert updated["state"] == "SUBMITTED"
