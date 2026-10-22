"""Adapter-level rules (T021): response matrix, routing, schedule model, disclosures.

Drives ``YouTubeAdapter`` directly (the service is not involved) against the
fixture transport: the frozen scenario matrix, replay dedupe by client token,
long-form vs Shorts routing from the slot kind, the documented
private-until-publishAt schedule model, disclosure refusal, media integrity,
metadata updates and the readback/captions surface.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from youtube_support import YouTubeWorld

from microdrama.contracts.enums import (
    CapabilityOperation,
    CapabilitySupport,
    Provenance,
    ReleaseState,
    SlotKind,
)
from microdrama.contracts.errors import NeedsReconciliation, NotFound, RateLimited
from microdrama.contracts.examples import ACCOUNT_YT
from microdrama.publishing.youtube import YouTubeScenario
from microdrama.publishing.youtube.adapter import ROUTE_LONG_FORM, ROUTE_SHORTS
from microdrama.publishing.youtube.transport import (
    CaptionUploadRequest,
    youtube_external_id,
)


def _single_plan(world: YouTubeWorld, **plan_kwargs) -> tuple:
    """One approved YouTube slot; returns (package, approval, plan)."""
    _s, _e, package, approval = world.approved_episode(
        scope_builder=lambda season_id, episode_id, master: [
            world.slot_plan(season_id=season_id, episode_id=episode_id, asset=master, **plan_kwargs)
        ]
    )
    return package, approval, package.release_scope[0]


def _command_for(world: YouTubeWorld, package, approval, plan):
    return world.command(plan, package=package, approval_event_id=approval)


@pytest.mark.parametrize(
    ("scenario", "expected_state", "error_code"),
    [
        (YouTubeScenario.ACCEPTED, ReleaseState.SUBMITTED, None),
        (YouTubeScenario.DENIED_PERMISSION, ReleaseState.FAILED, "PERMISSION_DENIED"),
        (YouTubeScenario.TOKEN_EXPIRED, ReleaseState.FAILED, "TOKEN_EXPIRED"),
    ],
)
def test_submit_matrix_maps_documented_responses(
    world: YouTubeWorld, scenario: YouTubeScenario, expected_state: ReleaseState, error_code
) -> None:
    package, approval, plan = _single_plan(world)
    command = _command_for(world, package, approval, plan)
    world.youtube.queue_scenarios(scenario)
    result = world.youtube.submit(command, world.media_path(plan.asset_id))

    assert result.state is expected_state
    assert result.error_code == error_code
    assert result.provenance is Provenance.FAKE_SYNTHETIC
    if scenario is YouTubeScenario.ACCEPTED:
        assert result.external_id == youtube_external_id(command.client_token)
        assert result.url is None  # nothing is public yet at submit
    else:
        assert world.youtube.transport.lookup_video(command.client_token) is None


def test_rate_limited_raises_with_retry_hint(world: YouTubeWorld) -> None:
    package, approval, plan = _single_plan(world)
    command = _command_for(world, package, approval, plan)
    world.youtube.queue_scenarios(YouTubeScenario.RATE_LIMITED)
    with pytest.raises(RateLimited) as err:
        world.youtube.submit(command, world.media_path(plan.asset_id))
    assert int(err.value.details["retry_after_ms"]) > 0
    assert world.youtube.transport.lookup_video(command.client_token) is None


def test_timeout_not_created_leaves_nothing_to_reconcile(world: YouTubeWorld) -> None:
    package, approval, plan = _single_plan(world)
    command = _command_for(world, package, approval, plan)
    world.youtube.queue_scenarios(YouTubeScenario.TIMEOUT_NOT_CREATED)
    with pytest.raises(NeedsReconciliation):
        world.youtube.submit(command, world.media_path(plan.asset_id))
    assert world.youtube.reconcile(command).found is False


def test_timeout_created_is_reconcilable_by_client_token(world: YouTubeWorld) -> None:
    package, approval, plan = _single_plan(world)
    command = _command_for(world, package, approval, plan)
    world.youtube.queue_scenarios(YouTubeScenario.TIMEOUT_CREATED)
    with pytest.raises(NeedsReconciliation):
        world.youtube.submit(command, world.media_path(plan.asset_id))

    outcome = world.youtube.reconcile(command)
    assert outcome.found is True
    assert outcome.result is not None
    assert outcome.result.external_id == youtube_external_id(command.client_token)
    assert outcome.result.state is ReleaseState.SUBMITTED


def test_replayed_submit_returns_the_same_post_without_consuming_a_scenario(
    world: YouTubeWorld,
) -> None:
    package, approval, plan = _single_plan(world)
    command = _command_for(world, package, approval, plan)
    world.youtube.queue_scenarios(YouTubeScenario.ACCEPTED, YouTubeScenario.DENIED_PERMISSION)
    media = world.media_path(plan.asset_id)
    first = world.youtube.submit(command, media)
    second = world.youtube.submit(command, media)  # the job ran twice

    assert first.state is ReleaseState.SUBMITTED
    assert second.external_id == first.external_id  # dedupe by client token
    assert second.state is ReleaseState.SUBMITTED
    assert world.youtube.transport.video_count() == 1


def test_long_form_and_shorts_route_from_slot_kind(world: YouTubeWorld) -> None:
    _s, _e, package, approval = world.approved_episode(
        scope_builder=lambda season_id, episode_id, master: [
            world.slot_plan(
                season_id=season_id,
                episode_id=episode_id,
                asset=master,
                slot="full",
                slot_kind=SlotKind.FULL_EPISODE,
            ),
            world.slot_plan(
                season_id=season_id,
                episode_id=episode_id,
                asset=master,
                slot="hook",
                slot_kind=SlotKind.HOOK,
                required=False,
            ),
        ]
    )
    media = world.media_path(package.release_scope[0].asset_id)
    routes = {}
    for plan in package.release_scope:
        command = _command_for(world, package, approval, plan)
        result = world.youtube.submit(command, media)
        assert result.state is ReleaseState.SUBMITTED
        routes[plan.slot_kind] = world.youtube.transport.route_of(result.external_id)

    assert routes[SlotKind.FULL_EPISODE] == ROUTE_LONG_FORM
    assert routes[SlotKind.HOOK] == ROUTE_SHORTS


def test_unsupported_route_operation_refuses_that_route_only(world: YouTubeWorld) -> None:
    world.youtube._operations[CapabilityOperation.UPLOAD_SHORT] = CapabilitySupport.UNSUPPORTED
    _s, _e, package, approval = world.approved_episode(
        scope_builder=lambda season_id, episode_id, master: [
            world.slot_plan(
                season_id=season_id,
                episode_id=episode_id,
                asset=master,
                slot="hook",
                slot_kind=SlotKind.HOOK,
                required=True,
            )
        ]
    )
    plan = package.release_scope[0]
    command = _command_for(world, package, approval, plan)
    result = world.youtube.submit(command, world.media_path(plan.asset_id))

    assert result.state is ReleaseState.FAILED
    assert result.error_code == "UPLOAD_SHORT_UNSUPPORTED"
    assert world.youtube.reconcile(command).found is False


def test_future_schedule_uses_private_publishat_then_turns_public(
    world: YouTubeWorld,
) -> None:
    package, approval, plan = _single_plan(world, schedule=world.future_schedule())
    command = _command_for(world, package, approval, plan)
    result = world.youtube.submit(command, world.media_path(plan.asset_id))
    assert result.state is ReleaseState.SUBMITTED

    external_id = result.external_id
    created = world.youtube.transport.videos_list(external_id)
    assert created.status.privacy_status == "private"  # documented schedule-ahead model
    assert created.status.publish_at == command.schedule.utc_instant
    assert created.status.contain_synthetic_media is True  # disclosure field is set

    assert world.youtube.status(command, external_id).state is ReleaseState.PROCESSING
    scheduled = world.youtube.status(command, external_id)
    assert scheduled.state is ReleaseState.PROCESSING  # processed but still private

    world.clock.set(command.schedule.utc_instant + timedelta(minutes=1))
    public = world.youtube.status(command, external_id)
    assert public.state is ReleaseState.PUBLISHED_VERIFIED
    assert public.url is not None

    readback = world.youtube.readback(ACCOUNT_YT, external_id)
    assert readback.visible is True
    assert readback.privacy == "public"
    assert "AI_GENERATED_CONTENT" in readback.disclosures_visible


def test_future_schedule_without_schedule_support_is_refused(world: YouTubeWorld) -> None:
    world.youtube._operations[CapabilityOperation.SCHEDULE] = CapabilitySupport.UNSUPPORTED
    package, approval, plan = _single_plan(world, schedule=world.future_schedule())
    command = _command_for(world, package, approval, plan)
    result = world.youtube.submit(command, world.media_path(plan.asset_id))

    assert result.state is ReleaseState.FAILED
    assert result.error_code == "SCHEDULE_UNSUPPORTED"
    assert world.youtube.transport.lookup_video(command.client_token) is None


def test_unsupported_disclosure_is_refused_before_any_upload(world: YouTubeWorld) -> None:
    world.youtube._operations[CapabilityOperation.AI_DISCLOSURE] = CapabilitySupport.UNSUPPORTED
    package, approval, plan = _single_plan(world)
    command = _command_for(world, package, approval, plan)
    result = world.youtube.submit(command, world.media_path(plan.asset_id))

    assert result.state is ReleaseState.FAILED
    assert result.error_code == "UNSUPPORTED_DISCLOSURE"
    assert world.youtube.transport.lookup_video(command.client_token) is None


def test_media_hash_mismatch_fails_closed(world: YouTubeWorld, tmp_path) -> None:
    package, approval, plan = _single_plan(world)
    command = _command_for(world, package, approval, plan)
    wrong = tmp_path / "wrong.mp4"
    wrong.write_bytes(b"not the pinned media")
    result = world.youtube.submit(command, wrong)

    assert result.state is ReleaseState.FAILED
    assert result.error_code == "ASSET_HASH_MISMATCH"
    assert world.youtube.transport.lookup_video(command.client_token) is None


def test_missing_media_file_raises_not_found(world: YouTubeWorld, tmp_path) -> None:
    package, approval, plan = _single_plan(world)
    command = _command_for(world, package, approval, plan)
    with pytest.raises(NotFound):
        world.youtube.submit(command, tmp_path / "absent.mp4")


def _published(world: YouTubeWorld):
    package, approval, plan = _single_plan(world)
    command = _command_for(world, package, approval, plan)
    world.youtube.queue_scenarios(YouTubeScenario.ACCEPTED)
    result = world.youtube.submit(command, world.media_path(plan.asset_id))
    external_id = result.external_id
    world.youtube.status(command, external_id)  # uploaded -> processing
    published = world.youtube.status(command, external_id)  # processing -> processed
    assert published.state is ReleaseState.PUBLISHED_VERIFIED
    return command, external_id


def test_status_progression_is_submitted_processing_verified(world: YouTubeWorld) -> None:
    package, approval, plan = _single_plan(world)
    command = _command_for(world, package, approval, plan)
    world.youtube.queue_scenarios(YouTubeScenario.ACCEPTED)
    submitted = world.youtube.submit(command, world.media_path(plan.asset_id))
    assert submitted.state is ReleaseState.SUBMITTED
    external_id = submitted.external_id

    first = world.youtube.status(command, external_id)
    assert first.state is ReleaseState.PROCESSING
    second = world.youtube.status(command, external_id)
    assert second.state is ReleaseState.PUBLISHED_VERIFIED
    assert second.url is not None
    assert "visibility" in second.verified_fields


def test_update_metadata_rewrites_the_documented_snippet(world: YouTubeWorld) -> None:
    _command, external_id = _published(world)
    metadata = YouTubeWorld.metadata(title="ตอนที่ ๒ – แก้ไขชื่อ")

    result = world.youtube.update_metadata(ACCOUNT_YT, external_id, metadata)
    assert result.state is ReleaseState.PUBLISHED_VERIFIED
    assert "title" in result.unverified_fields

    video = world.youtube.transport.videos_list(external_id)
    assert video.snippet.title == metadata.title
    assert video.snippet.description == metadata.description


def test_readback_reports_captions_only_through_the_documented_surface(
    world: YouTubeWorld,
) -> None:
    """Submit never fabricates caption uploads (T029/T025 integration point)."""
    _command, external_id = _published(world)

    before = world.youtube.readback(ACCOUNT_YT, external_id)
    assert before.subtitles_present is None  # no captions were uploaded by submit

    world.youtube.upload_captions(
        CaptionUploadRequest(
            video_id=external_id,
            language="th-TH",
            body_text="1\n00:00:00,000 --> 00:00:01,000\nทดสอบ",
        )
    )
    after = world.youtube.readback(ACCOUNT_YT, external_id)
    assert after.subtitles_present is True


def test_status_and_readback_of_an_unknown_video_raise(world: YouTubeWorld) -> None:
    package, approval, plan = _single_plan(world)
    command = _command_for(world, package, approval, plan)
    with pytest.raises(NotFound):
        world.youtube.status(command, "yt-doesnotexist")
    with pytest.raises(NotFound):
        world.youtube.readback(ACCOUNT_YT, "yt-doesnotexist")


def test_capability_record_from_the_adapter_is_the_enabled_fixture_variant(
    world: YouTubeWorld,
) -> None:
    record = world.youtube.capability(ACCOUNT_YT)
    assert record.enabled is True
    assert record.account_ref == ACCOUNT_YT
    assert record.verified_at is not None
    assert CapabilitySupport.SUPPORTED_TESTED not in record.operations.values()
