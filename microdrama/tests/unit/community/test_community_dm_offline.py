"""DM execution seam and offline-mode tests (T025's boundary with T026).

This lane builds NO keyword/eligibility logic (T026 owns it). What is pinned
here: ``execute_action`` will run a HANDED-IN DM_SEND action only inside the
inbound DM's messaging window, under the per-conversation cap, never as cold
outreach, and never with MD-018 content. Plus the offline guards: the factory
refuses every non-mock mode and the live provider is a named T032 refusal.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from community_support import CommunityWorld

from microdrama.community import LiveCommunityProvider, build_community_service
from microdrama.community.service import METERED_ACTION_COST_MICRO_USD
from microdrama.config import Settings
from microdrama.contracts.enums import (
    CommunityEventKind,
    ExecutionMode,
    ManagementActionKind,
    Platform,
    Provenance,
)
from microdrama.contracts.errors import EffectDenied, PolicyDenied
from microdrama.contracts.providers import CommunityEventIn
from microdrama.contracts.release import ManagementAction
from microdrama.testing.fakes.common import FakeClock, SequentialIds

DM_TEXT = "ขอบคุณที่สนใจนะคะ รายละเอียดประกาศที่ช่องนะคะ"


def _dm_action(world: CommunityWorld, event_id, *, dedupe: str, content: str = DM_TEXT):
    return ManagementAction(
        action_id=world.ids.new_id(),
        kind=ManagementActionKind.DM_SEND,
        platform=Platform.YOUTUBE,
        account_ref=world.community_account,
        community_event_id=event_id,
        content=content,
        catalog_version=1,
        management_policy_hash="0" * 64,  # replaced by the resolved approved hash
        dedupe_key=dedupe,
        estimated_cost_micro_usd=METERED_ACTION_COST_MICRO_USD,
    )


def _script_dm(world: CommunityWorld, provider_event_id: str, *, author: str):
    world.community_provider.script_events(
        [
            CommunityEventIn(
                provider_event_id=provider_event_id,
                kind=CommunityEventKind.DIRECT_MESSAGE,
                platform=Platform.YOUTUBE,
                account_ref=world.community_account,
                author_ref=author,
                text="สนใจครับ",
                received_at=world.clock.now() + timedelta(seconds=1),
                dm_window_expires_at=world.clock.now() + timedelta(hours=24),
                provenance=Provenance.FAKE_SYNTHETIC,
            )
        ]
    )


def test_handed_dm_inside_the_window_executes_metered(world: CommunityWorld) -> None:
    post = world.published_post()
    _script_dm(world, "dm-window-0001", author="author-dm-1")
    world.community.ingest(Platform.YOUTUBE, world.community_account)
    event = world.event_row("dm-window-0001")

    row = world.community.execute_action(
        _dm_action(world, event["id"], dedupe="dm:YOUTUBE:dm-window-0001"),
        season_id=post["season_id"],
        episode_id=post["episode_id"],
    )
    assert row["decision"] == "EXECUTED"
    assert row["external_id"] is not None
    assert row["reservation_id"] is not None
    _allocation, committed, settled = world.metered_counters(post["episode_id"])[
        "METERED_MANAGEMENT"
    ]
    assert committed == settled >= METERED_ACTION_COST_MICRO_USD


def test_dm_past_the_window_is_suppressed(world: CommunityWorld) -> None:
    post = world.published_post()
    _script_dm(world, "dm-late-0001", author="author-dm-2")
    world.community.ingest(Platform.YOUTUBE, world.community_account)
    event = world.event_row("dm-late-0001")
    world.clock.advance(seconds=25 * 3600)  # past dm_window_expires_at

    row = world.community.execute_action(
        _dm_action(world, event["id"], dedupe="dm:YOUTUBE:dm-late-0001"),
        season_id=post["season_id"],
        episode_id=post["episode_id"],
    )
    assert row["decision"] == "SUPPRESSED"
    assert row["reason"] == "DM_WINDOW_CLOSED"
    # Nothing was spent on the refused message.
    assert row["reservation_id"] is None


def test_dm_without_an_inbound_event_is_cold_outreach(world: CommunityWorld) -> None:
    post = world.published_post()
    row = world.community.execute_action(
        _dm_action(world, None, dedupe="dm:YOUTUBE:cold-0001"),
        season_id=post["season_id"],
        episode_id=post["episode_id"],
    )
    assert row["decision"] == "SUPPRESSED"
    assert row["reason"] == "COLD_OUTREACH_NO_INBOUND_DM"


def test_dm_cap_per_conversation(world: CommunityWorld) -> None:
    post = world.published_post()
    for i in range(1, 5):
        _script_dm(world, f"dm-cap-000{i}", author="author-dm-3")
    world.community.ingest(Platform.YOUTUBE, world.community_account)

    decisions = []
    for i in range(1, 5):
        event = world.event_row(f"dm-cap-000{i}")
        row = world.community.execute_action(
            _dm_action(world, event["id"], dedupe=f"dm:YOUTUBE:dm-cap-000{i}"),
            season_id=post["season_id"],
            episode_id=post["episode_id"],
        )
        decisions.append(row["decision"])
    assert decisions == ["EXECUTED", "EXECUTED", "EXECUTED", "SUPPRESSED"]
    capped = world.row(
        "SELECT * FROM management_actions WHERE decision = 'SUPPRESSED' AND kind = 'DM_SEND'"
    )
    assert capped["reason"] == "DM_CAP_REACHED"  # max_dms_per_conversation = 3


def test_dm_with_md018_content_is_suppressed(world: CommunityWorld) -> None:
    post = world.published_post()
    _script_dm(world, "dm-refund-0001", author="author-dm-4")
    world.community.ingest(Platform.YOUTUBE, world.community_account)
    event = world.event_row("dm-refund-0001")

    row = world.community.execute_action(
        _dm_action(
            world,
            event["id"],
            dedupe="dm:YOUTUBE:dm-refund-0001",
            content="ขออภัยด้วยนะคะ เราคืนเงินให้ได้ค่ะ",
        ),
        season_id=post["season_id"],
        episode_id=post["episode_id"],
    )
    assert row["decision"] == "SUPPRESSED"
    assert row["reason"].startswith("MD018_FORBIDDEN_CONTENT")


def test_inbound_dm_is_left_classified_for_the_t026_lane(world: CommunityWorld) -> None:
    post = world.published_post()
    report = world.process(post["season_id"], post["episode_id"])
    event = world.event_row("fake-dm-0003")
    assert event["kind"] == "DIRECT_MESSAGE"
    assert event["status"] == "CLASSIFIED"  # this lane deliberately does not act on DMs
    dm_actions = world.rows("SELECT * FROM management_actions WHERE kind = 'DM_SEND'")
    assert dm_actions == []
    assert report.no_action >= 1


def test_factory_refuses_every_non_mock_mode(db, tmp_path, offline_settings) -> None:
    controlled = Settings(execution_mode=ExecutionMode.CONTROLLED_ACCOUNT_TEST)
    with pytest.raises(EffectDenied):
        build_community_service(
            controlled,
            db,
            FakeClock(datetime.now(UTC)),
            SequentialIds("x"),
            {},
            None,
        )


def test_live_community_provider_is_a_named_t032_refusal() -> None:
    with pytest.raises(PolicyDenied) as exc:
        LiveCommunityProvider()
    assert "live community actions disabled until T032" in exc.value.message
