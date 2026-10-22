"""T022 inbox-route rule: an inbox upload is NEVER an unattended publication.

The documented inbox upload (``post_mode=inbox_upload``) lands the video in the user's
inbox/drafts where a human must act. This lane refuses to label that route unattended
at BOTH layers: the capability record never advertises the unattended upload
operations (so the service holds the slot before any adapter call), and a direct
adapter submit is a typed ``INBOX_REQUIRES_HUMAN`` failure that creates nothing.
"""

from __future__ import annotations

from microdrama.contracts.enums import CapabilityOperation, Platform
from microdrama.publishing.tiktok.capabilities import TikTokRoute


def _inbox_bench(tmp_path):
    from tiktok_support import AdapterBench

    return AdapterBench(tmp_path, route=TikTokRoute.INBOX_UPLOAD)


def test_inbox_route_refuses_unattended_submit(tmp_path) -> None:
    bench = _inbox_bench(tmp_path)
    media = bench.media()
    result = bench.adapter.submit(bench.command(media), media)
    assert result.state.value == "FAILED"
    assert result.error_code == "INBOX_REQUIRES_HUMAN"
    assert result.transient is False
    # nothing reached the platform
    assert bench.transport.publish_ids == ()
    assert bench.transport.init_requests == []


def test_inbox_capability_never_advertises_unattended_uploads(tmp_path) -> None:
    bench = _inbox_bench(tmp_path)
    record = bench.adapter.capability("acct:tiktok-main")
    assert record.provider_route == "tiktok-inbox-upload"
    assert record.support(CapabilityOperation.UPLOAD_FULL_VIDEO).value == "UNSUPPORTED"
    assert record.support(CapabilityOperation.UPLOAD_SHORT).value == "UNSUPPORTED"
    # the fixture inbox record is enabled, yet it still never clears the slot flow
    assert record.enabled is True


def test_service_holds_an_inbox_route_slot_before_any_adapter_call(tiktok_world) -> None:
    """The mislabel freeze: an inbox-route slot can never submit unattended."""
    world = tiktok_world(route=TikTokRoute.INBOX_UPLOAD)
    _s, episode_id, package, approval = world.approved_tiktok_episode()
    world.schedule(episode_id)
    plan = next(p for p in package.release_scope if p.slot.platform is Platform.TIKTOK)
    command = world.command(plan, package=package, approval_event_id=approval)
    updated = world.service.submit_slot(command, job_id=world.submit_job(command))

    assert updated["state"] == "HELD"
    assert updated["blocker"] == "CAPABILITY_UNAVAILABLE"
    assert updated["external_id"] is None
    # nothing was created at the platform and no replay can push it out unattended
    assert world.tiktok_transport.publish_ids == ()

    view = world.service.release_view(episode_id)
    assert view["full_release_ready"] is False
    assert view["blockers"][0]["blocker"] == "CAPABILITY_UNAVAILABLE"
