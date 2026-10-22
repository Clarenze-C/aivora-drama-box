"""T022 duration ceiling: the documented direct-post window, enforced before creation."""

from __future__ import annotations

from microdrama.contracts.enums import Platform


def test_over_the_documented_ceiling_is_a_typed_refusal(bench) -> None:
    media = bench.media(duration_ms=900_000)  # 15 min > the documented 10 min ceiling
    result = bench.adapter.submit(bench.command(media), media)
    assert result.state.value == "FAILED"
    assert result.error_code == "DURATION_EXCEEDS_LIMIT"
    assert result.transient is False
    assert bench.transport.publish_ids == ()
    assert bench.transport.init_requests == []


def test_under_the_documented_minimum_is_a_typed_refusal(bench) -> None:
    media = bench.media(duration_ms=2_000)  # 2 s < the documented 3 s minimum
    result = bench.adapter.submit(bench.command(media), media)
    assert result.state.value == "FAILED"
    assert result.error_code == "DURATION_BELOW_MINIMUM"
    assert bench.transport.publish_ids == ()


def test_within_the_window_submits_normally(bench) -> None:
    media = bench.media(duration_ms=599_000)
    result = bench.adapter.submit(bench.command(media), media)
    assert result.state.value == "SUBMITTED"
    assert result.external_id is not None


def test_service_fails_an_over_ceiling_episode_slot_with_the_typed_code(tiktok_world) -> None:
    """FULL_EPISODE slots map to UPLOAD_FULL_VIDEO: the ceiling is enforced at submit."""
    world = tiktok_world()
    season_id = world.season()
    episode_id = world.episode(season_id)
    long_master = world.asset_with_duration(season_id, episode_id, duration_ms=900_000)
    scope = world.tiktok_scope(season_id, episode_id, long_master)
    package = world.package(
        season_id=season_id, episode_id=episode_id, scope=scope, master=long_master
    )
    approval = world.approve(season_id=season_id, episode_id=episode_id, package=package)
    world.schedule(episode_id)
    plan = next(p for p in package.release_scope if p.slot.platform is Platform.TIKTOK)
    command = world.command(plan, package=package, approval_event_id=approval)
    updated = world.service.submit_slot(command, job_id=world.submit_job(command))
    assert updated["state"] == "FAILED"
    assert updated["last_error_code"] == "DURATION_EXCEEDS_LIMIT"
    assert updated["external_id"] is None
    assert world.tiktok_transport.publish_ids == ()

    view = world.service.release_view(episode_id)
    assert view["full_release_ready"] is False
    assert view["blockers"][0]["blocker"] == "DURATION_EXCEEDS_LIMIT"
