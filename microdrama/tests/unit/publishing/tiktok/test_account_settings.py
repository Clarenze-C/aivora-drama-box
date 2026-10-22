"""T022 account truth: capability limits come from actual account settings."""

from __future__ import annotations

from tiktok_support import private_account_settings, short_account_settings

from microdrama.contracts.enums import CapabilityOperation, Platform
from microdrama.contracts.examples import ACCOUNT_TT


def test_capability_limits_carry_the_accounts_own_duration(bench) -> None:
    record = bench.adapter.capability(ACCOUNT_TT)
    assert record.limits.max_duration_ms == 600_000  # default eligible account (10 min)
    assert record.limits.min_duration_ms == 3_000  # documented minimum (3 s)
    assert record.limits.daily_post_quota is None  # quotas are not live account facts


def test_account_without_direct_post_permission_is_unsupported(tmp_path) -> None:
    from tiktok_support import AdapterBench

    bench = AdapterBench(tmp_path, account_settings={ACCOUNT_TT: private_account_settings()})
    record = bench.adapter.capability(ACCOUNT_TT)
    assert record.support(CapabilityOperation.UPLOAD_FULL_VIDEO).value == "UNSUPPORTED"
    assert record.support(CapabilityOperation.UPLOAD_SHORT).value == "UNSUPPORTED"
    # account truth, not the documented default: the record keeps doc evidence and the
    # documented ceiling, but the account's own settings refuse the unattended route.
    assert record.limits.max_duration_ms == 600_000


def test_account_without_direct_post_permission_refuses_submit(tmp_path) -> None:
    from tiktok_support import AdapterBench

    bench = AdapterBench(tmp_path, account_settings={ACCOUNT_TT: private_account_settings()})
    media = bench.media()
    result = bench.adapter.submit(bench.command(media), media)
    assert result.state.value == "FAILED"
    assert result.error_code == "DIRECT_POST_DISABLED_ON_ACCOUNT"
    assert bench.transport.publish_ids == ()
    assert bench.transport.init_requests == []


def test_tighter_account_ceiling_is_the_enforced_one(tmp_path) -> None:
    from tiktok_support import AdapterBench

    bench = AdapterBench(
        tmp_path, account_settings={ACCOUNT_TT: short_account_settings(max_video_duration_sec=120)}
    )
    media = bench.media(duration_ms=150_000)  # 2.5 min: inside the docs' 10 min, over
    # this account's actual 2-minute ceiling
    record = bench.adapter.capability(ACCOUNT_TT)
    assert record.limits.max_duration_ms == 120_000
    result = bench.adapter.submit(bench.command(media), media)
    assert result.state.value == "FAILED"
    assert result.error_code == "DURATION_EXCEEDS_LIMIT"


def test_service_holds_a_slot_whose_account_permits_no_direct_post(tiktok_world) -> None:
    world = tiktok_world(account_settings={ACCOUNT_TT: private_account_settings()})
    _s, episode_id, package, approval = world.approved_tiktok_episode()
    world.schedule(episode_id)
    plan = next(p for p in package.release_scope if p.slot.platform is Platform.TIKTOK)
    command = world.command(plan, package=package, approval_event_id=approval)
    updated = world.service.submit_slot(command, job_id=world.submit_job(command))
    assert updated["state"] == "HELD"
    assert updated["blocker"] == "CAPABILITY_UNAVAILABLE"
    assert world.tiktok_transport.publish_ids == ()
