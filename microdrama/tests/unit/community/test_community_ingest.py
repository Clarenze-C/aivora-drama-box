"""Ingest tests (real DB): at-least-once delivery ingested exactly once.

The fake provider's seeded feed contains an exact duplicate delivery (same
``provider_event_id``); every duplicate is counted, never reprocessed, and no
policy action ever runs twice for one provider event.
"""

from __future__ import annotations

from community_support import CommunityWorld

from microdrama.contracts.enums import Platform


def test_duplicate_delivery_is_ingested_once(world: CommunityWorld) -> None:
    post = world.published_post()
    report = world.community.ingest(Platform.YOUTUBE, world.community_account)

    assert report.duplicates == 1  # the seeded exact duplicate delivery
    assert len(report.new_event_ids) == 4  # 0001 question, 0002 praise, 0003 dm, 0004 injection
    rows = world.rows("SELECT provider_event_id FROM community_events")
    assert len(rows) == 4
    assert world.row("SELECT count(*) AS c FROM community_events")["c"] == 4

    # A full replay of the feed ingests nothing new.
    replay = world.community.ingest(Platform.YOUTUBE, world.community_account)
    assert replay.new_event_ids == []
    assert replay.duplicates == 5  # every delivery, duplicates included
    assert world.row("SELECT count(*) AS c FROM community_events")["c"] == 4
    assert post["state"] == "PUBLISHED_VERIFIED"


def test_new_events_are_classified_with_evidence(world: CommunityWorld) -> None:
    world.community.ingest(Platform.YOUTUBE, world.community_account)
    for provider_event_id, expected_class in (
        ("fake-comment-0001", "QUESTION"),
        ("fake-reply-0002", "PRAISE"),
        ("fake-dm-0003", "OTHER"),
        ("fake-comment-0004", "INJECTION_ATTEMPT"),
    ):
        row = world.event_row(provider_event_id)
        assert row["status"] == "CLASSIFIED"
        assert f'"class": "{expected_class}"' in row["classification"]


def test_process_replay_takes_no_new_actions(world: CommunityWorld) -> None:
    post = world.published_post()
    first = world.process(post["season_id"], post["episode_id"])
    assert first.executed >= 1
    executed_first = world.row("SELECT count(*) AS c FROM management_actions")["c"]

    second = world.process(post["season_id"], post["episode_id"])
    assert second.ingested_new == 0
    assert second.executed == 0
    assert world.row("SELECT count(*) AS c FROM management_actions")["c"] == executed_first


def test_event_links_to_a_matching_published_post(world: CommunityWorld) -> None:
    post = world.published_post()
    # A comment that names the real external id links to the real post row.
    world.script_comment("link-0001", "ตอนหน้าเมื่อไหร่", external_post_id=post["external_id"])
    world.community.ingest(Platform.YOUTUBE, world.community_account)
    linked = world.event_row("link-0001")
    assert str(linked["platform_post_id"]) == str(post["id"])
    # The seeded fixture id matches no real post: the link stays null.
    unlinked = world.event_row("fake-comment-0001")
    assert unlinked["platform_post_id"] is None


def test_event_content_is_immutable_once_ingested(world: CommunityWorld) -> None:
    from microdrama.contracts.errors import MicrodramaError

    world.community.ingest(Platform.YOUTUBE, world.community_account)
    row = world.event_row("fake-comment-0001")
    try:
        with world.db.transaction() as tx:
            tx.execute("UPDATE community_events SET text = 'rewritten' WHERE id = %s", (row["id"],))
    except MicrodramaError as exc:
        assert "immutable" in exc.message
    else:  # pragma: no cover - the trigger must fire
        raise AssertionError("untrusted event text was writable after ingest")
