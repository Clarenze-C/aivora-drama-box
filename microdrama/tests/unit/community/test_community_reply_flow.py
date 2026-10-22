"""Reply flow tests (real DB): grounded execution, caps, metering per action.

Acceptance rows pinned here: reply limits (per post per day, per run), grounded
answer content (announced vs honestly-unannounced), the metered
reserve→execute→settle cycle through the REAL budget service, and duplicate
action dedupe.
"""

from __future__ import annotations

import json

from community_support import CommunityWorld

from microdrama.community.grounding import load_facts, thai_date
from microdrama.community.service import METERED_ACTION_COST_MICRO_USD
from microdrama.contracts.enums import ManagementActionKind, Platform
from microdrama.review.gate_conditions import approved_policy_hash


def _reply_rows(world: CommunityWorld) -> list[dict]:
    return world.rows(
        "SELECT * FROM management_actions WHERE kind = 'PUBLIC_REPLY' ORDER BY created_at, id"
    )


def _body(row: dict) -> dict:
    return json.loads(json.dumps(row["body"]))


def test_question_without_announcement_gets_a_truthful_unknown_reply(world: CommunityWorld) -> None:
    post = world.published_post()  # no future SCHEDULED slot: nothing announced
    report = world.process(post["season_id"], post["episode_id"])

    assert report.executed >= 1
    row = world.event_row("fake-comment-0001")
    assert row["status"] == "ACTIONED"
    executed = [r for r in _reply_rows(world) if r["decision"] == "EXECUTED"]
    question_reply = [r for r in executed if _body(r)["community_event_id"] == str(row["id"])][0]
    content = _body(question_reply)["content"]
    assert "ยังไม่ได้ประกาศ" in content  # unknown is answered as unknown, never invented
    assert question_reply["external_id"] is not None


def test_question_with_announcement_quotes_the_scheduled_date(world: CommunityWorld) -> None:
    post = world.published_post(promo=True)  # promo slot stays SCHEDULED in the future
    promo = world.row(
        "SELECT scheduled_utc, episode_id FROM platform_posts WHERE release_slot = 'promo'"
    )
    world.process(post["season_id"], post["episode_id"])

    executed = [r for r in _reply_rows(world) if r["decision"] == "EXECUTED"]
    question = [
        r
        for r in executed
        if _body(r)["community_event_id"] == str(world.event_row("fake-comment-0001")["id"])
    ][0]
    content = _body(question)["content"]
    assert thai_date(promo["scheduled_utc"]) in content


def test_reply_reserves_and_settles_metered_management(world: CommunityWorld) -> None:
    post = world.published_post()
    world.process(post["season_id"], post["episode_id"])

    executed = [r for r in _reply_rows(world) if r["decision"] == "EXECUTED"]
    assert executed, "the seeded question and praise must have been answered"
    allocation, committed, settled = world.metered_counters(post["episode_id"])[
        "METERED_MANAGEMENT"
    ]
    assert allocation == 1_000_000
    assert committed == settled == len(executed) * METERED_ACTION_COST_MICRO_USD
    # Every executed metered row is reservation-bound (the contract requires it).
    for row in executed:
        assert row["reservation_id"] is not None
    # And the reservations were fully settled, not left open.
    open_reservations = world.rows(
        "SELECT * FROM reservations WHERE state = 'ACTIVE' AND category = 'METERED_MANAGEMENT'"
    )
    assert open_reservations == []


def test_per_post_daily_reply_cap_is_enforced(world: CommunityWorld) -> None:
    post = world.published_post()
    for i in range(1, 61):
        world.script_comment(f"q-{i:03d}", f"ตอนต่อไปออกเมื่อไหร่คะ (ครั้งที่ {i})")
    report = world.process(post["season_id"], post["episode_id"])

    executed = [r for r in _reply_rows(world) if r["decision"] == "EXECUTED"]
    suppressed = [r for r in _reply_rows(world) if r["decision"] == "SUPPRESSED"]
    # Policy cap is 50 replies per post per day; every event targets fake-post-0001.
    assert len(executed) == 50
    assert all(r["reason"] == "REPLY_CAP_REACHED" for r in suppressed)
    assert (
        len(suppressed) == 12
    )  # 62 reply-eligible events (60 scripted + seeded question/praise) - 50 sent
    assert report.suppressed >= 10


def test_run_action_cap_stops_the_pass(db, tmp_path, offline_settings) -> None:
    from community_support import CommunityWorld as World

    capped = World(db, tmp_path, offline_settings, max_actions_per_run=5)
    post = capped.published_post()
    for i in range(1, 11):
        capped.script_comment(f"q-{i:03d}", f"ตอนต่อไปออกเมื่อไหร่คะ (ครั้งที่ {i})")
    report = capped.process(post["season_id"], post["episode_id"])

    assert report.action_cap_reached is True
    total_actions = capped.row("SELECT count(*) AS c FROM management_actions")["c"]
    assert total_actions == 5
    # The unprocessed questions stay CLASSIFIED for the next pass; the DM also
    # stays CLASSIFIED (T026's lane), and the injection was IGNORED (no action).
    pending = capped.rows(
        "SELECT status, kind FROM community_events WHERE status = 'CLASSIFIED' AND kind = 'COMMENT'"
    )
    assert len(pending) == 7  # q-004..q-010


def test_replayed_action_never_executes_twice(world: CommunityWorld) -> None:
    post = world.published_post()
    world.community.ingest(Platform.YOUTUBE, world.community_account)
    event = world.event_row("fake-comment-0001")

    with world.db.transaction(readonly=True) as tx:
        _hash, policy = approved_policy_hash(tx, post["season_id"])
        facts = load_facts(tx, post["season_id"], now=world.clock.now())
    action = world.community._build_action(
        kind=ManagementActionKind.PUBLIC_REPLY,
        platform=Platform.YOUTUBE,
        account_ref=world.community_account,
        event_row=event,
        policy=policy,
        facts=facts,
        content="ขอบคุณที่ถามนะคะ",
    )
    first = world.community.execute_action(
        action, season_id=post["season_id"], episode_id=post["episode_id"], event_row=event
    )
    assert first["decision"] == "EXECUTED"
    # A duplicate dispatch of the same dedupe key replays the stored outcome:
    # one provider execute, one settlement, never a second public reply.
    again = world.community.execute_action(
        action, season_id=post["season_id"], episode_id=post["episode_id"], event_row=event
    )
    assert again["id"] == first["id"]
    assert again["decision"] == "EXECUTED"
    execute_calls = [call for call in world.community_provider.calls if call.method == "execute"]
    assert len(execute_calls) == 1
    settled = world.metered_counters(post["episode_id"])["METERED_MANAGEMENT"][2]
    assert settled == METERED_ACTION_COST_MICRO_USD
