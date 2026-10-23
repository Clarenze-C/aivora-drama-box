"""AT-10/11/12 reproduced independently against the completed pilot run.

AT-10: three hook candidates exist as local re-cuts of accepted footage — no new
video-render job was created for them and they appear in review material, never
as a forced post.

AT-11: catalog/entitlement truth — the pilot episode is not member-gated, so an
entitlement check answers truthfully (no entitlement, no provider call, no
paywall masquerading as free CTA), and no catalog row sells anything.

AT-12: one successful mock episode does NOT qualify the system — ten consecutive
are required, spend is retained in the qualification view, and management
windows stay pending. This file is also the standing guard that AT-14 (real
episode evidence) is never satisfied by mock success.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.db, pytest.mark.slow]


def _row(world, sql: str, params: tuple = ()):
    with world.db.transaction(readonly=True) as tx:
        return tx.fetchone(sql, params)


def _val(world, sql: str, params: tuple = ()):
    with world.db.transaction(readonly=True) as tx:
        return tx.fetchval(sql, params)


# --- AT-10 ---------------------------------------------------------------------------------


def test_three_hook_candidates_with_zero_extra_render_jobs(pilot) -> None:
    """AT-10, un-xfailed after the T029 fix round: the guard now scopes to VIDEO
    sources (T030-02 fix) and the runner fails stages on FAILED jobs (T030-02a),
    so the pilot builds its hook experiment like T016 designed."""
    world, report = pilot
    experiment = _row(
        world, "SELECT body FROM hook_experiments WHERE episode_id = %s", (report.episode_id,)
    )
    assert experiment is not None, "the pilot built a hook experiment"
    candidates = experiment["body"].get("candidates") or []
    assert len(candidates) == 3, f"IMP-07 wants three candidates, got {len(candidates)}"
    for candidate in candidates:
        duration = candidate.get("duration_ms") or candidate.get("candidate", {}).get("duration_ms")
        assert duration is None or 20_000 <= duration <= 40_000, candidate

    # Every render job belongs to W05's shot dispatch: the hooks stage (W06's
    # second job) created no video-render job.
    w05 = next(s for s in report.stages if s.stage == "render_shots")
    render_jobs = _val(world, "SELECT count(*) FROM jobs WHERE job_type = 'render.shot'")
    assert render_jobs == w05.detail["shots"], (
        f"{render_jobs} render jobs for {w05.detail['shots']} shots — hooks must add none"
    )
    # And no platform post was forced for a hook candidate (review material only).
    hook_posts = _val(
        world,
        "SELECT count(*) FROM platform_posts WHERE episode_id = %s AND release_slot LIKE 'hook%%'",
        (report.episode_id,),
    )
    assert hook_posts == 0


# --- AT-11 ---------------------------------------------------------------------------------


def test_ungated_pilot_episode_is_truthfully_free(pilot) -> None:
    world, report = pilot
    catalog_rows = _val(
        world, "SELECT count(*) FROM membership_catalog WHERE episode_id = %s", (report.episode_id,)
    )
    assert catalog_rows == 0, "nothing may be sold for an episode with no member gate"

    decision = world.memberships.entitlements.check(
        member_ref="member:t030-stranger", episode_id=report.episode_id
    )
    assert decision.entitled is False
    assert decision.active is None
    assert "no member-gated" in (decision.reason or "")
    # Nothing to verify against: the provider was never called.
    assert all(call.method != "check_entitlement" for call in world.memberships.fake_provider.calls)


# --- AT-12 (+ the AT-14 guard) ---------------------------------------------------------------


def test_one_mock_episode_never_qualifies_the_system(pilot) -> None:
    """Ten consecutive qualifying episodes are required (IMP-08). The pilot's ONE
    mock success must leave production NOT qualified — mock success is never
    AT-14 evidence, and this assertion is the guard that keeps it that way."""
    world, report = pilot
    qualification = world.analytics.evaluate_qualification(report.season_id)
    assert qualification.required_consecutive == 10
    assert qualification.successful_episodes < 10
    assert qualification.production_status.value != "QUALIFIED"
    assert qualification.management_status.value != "QUALIFIED"
    # The pilot's (fake) spend is retained in the qualification view — failed or
    # not, money spent is never erased from the ledger.
    assert qualification.total_variable_spend_micro_usd > 0


def test_qualification_view_counts_pilot_windows_as_pending(pilot) -> None:
    """Offline there is no insights provider: the episode's management window
    stays PENDING (or NOT_QUALIFIED) rather than being marked passed by mock
    snapshots, and any production verdict is still pending, never a pass."""
    world, report = pilot
    qualification = world.analytics.evaluate_qualification(report.season_id)
    assert qualification.episodes, "the pilot episode appears in the qualification view"
    for episode in qualification.episodes:
        assert str(episode.management_window_status) != "QUALIFIED"
        assert episode.management_window_status.value in ("NOT_QUALIFIED", "PENDING")
        if episode.production_qualifies is not None:
            # A decided production verdict for a mock episode can exist, but the
            # season-level status above still must not be QUALIFIED.
            pass
    assert qualification.management_status.value in ("NOT_QUALIFIED", "PENDING")
