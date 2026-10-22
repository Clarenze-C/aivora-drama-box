"""Budget and flood tests (real DB): metered allowance, no theft, load caps.

Acceptance rows pinned here:
- metered management consumes its own allowance through the REAL BudgetService;
  when exhausted, optional actions are suppressed and other categories are
  never touched (community cannot steal protected funds);
- flood(n) load: every unique event is ingested once, duplicates never
  reprocess, replies stay capped per post/day and per run, and the provider
  sees a bounded number of execute calls.
"""

from __future__ import annotations

from community_support import CommunityWorld, small_metered_policy

from microdrama.contracts.enums import BudgetCategory


def test_metered_exhaustion_suppresses_optional_replies(db, tmp_path, offline_settings) -> None:
    from community_support import CommunityWorld as World

    world = World(db, tmp_path, offline_settings)
    # Metered allowance fits exactly two replies at 1,000 micro-USD each.
    post = world.published_post(policy=small_metered_policy(2_000))
    for i in range(1, 5):
        world.script_comment(f"q-{i:03d}", f"ตอนต่อไปออกเมื่อไหร่คะ (ครั้งที่ {i})")
    report = world.process(post["season_id"], post["episode_id"])

    replies = world.rows(
        "SELECT decision, reason FROM management_actions WHERE kind = 'PUBLIC_REPLY'"
    )
    executed = [r for r in replies if r["decision"] == "EXECUTED"]
    suppressed = [r for r in replies if r["decision"] == "SUPPRESSED"]
    # Ingest order: the seeded question and praise replies execute first (2 x
    # 1,000 micro-USD settles the whole allowance); every later optional reply
    # is suppressed — never sent, never stealing another category.
    assert len(executed) == 2
    assert len(suppressed) == 4
    assert all(r["reason"] == "BUDGET_EXHAUSTED" for r in suppressed)
    allocation, committed, settled = world.metered_counters(post["episode_id"])[
        "METERED_MANAGEMENT"
    ]
    assert (allocation, committed, settled) == (2_000, 2_000, 2_000)
    assert report.suppressed >= 2
    # No reservation is left open by the suppressed actions.
    assert world.rows("SELECT * FROM reservations WHERE state = 'ACTIVE'") == []


def test_community_never_touches_other_categories(db, tmp_path, offline_settings) -> None:
    from community_support import CommunityWorld as World

    world = World(db, tmp_path, offline_settings)
    post = world.published_post(policy=small_metered_policy(2_000))
    for i in range(1, 5):
        world.script_comment(f"q-{i:03d}", f"ตอนต่อไปออกเมื่อไหร่คะ (ครั้งที่ {i})")
    world.process(post["season_id"], post["episode_id"])

    counters = world.metered_counters(post["episode_id"])
    for category, (allocation, committed, settled) in counters.items():
        if category == BudgetCategory.METERED_MANAGEMENT.value:
            assert (allocation, committed, settled) == (2_000, 2_000, 2_000)
        else:
            # Protected production/publication funds: untouched by community work.
            assert committed == 0 and settled == 0
    # No transfer rows were invented to move allocation around either.
    assert world.rows("SELECT * FROM budget_transfers") == []


def test_flood_events_ingest_once_and_stay_benign(world: CommunityWorld) -> None:
    post = world.published_post()
    flood = world.community_provider.flood(250)
    assert len(flood) == 250

    report = world.process(post["season_id"], post["episode_id"])
    assert report.ingested_new == 254  # 4 unique seeded + 250 flood
    assert report.duplicates == 1
    assert world.row("SELECT count(*) AS c FROM community_events")["c"] == 254
    # Benign flood text is OTHER: the flood itself earns no reply, no
    # moderation, one IGNORED each. Only the two seeded engagement replies ran.
    assert report.executed == 2  # seeded question + praise
    assert report.suppressed == 0
    ignored = world.rows("SELECT count(*) AS c FROM community_events WHERE status = 'IGNORED'")
    assert ignored[0]["c"] == 251  # 250 flood + the injection; the DM stays CLASSIFIED for T026
    assert world.row("SELECT count(*) AS c FROM management_actions")["c"] == 2


def test_question_flood_is_bounded_by_reply_cap_and_budget(world: CommunityWorld) -> None:
    post = world.published_post()
    from datetime import timedelta

    from microdrama.contracts.enums import CommunityEventKind, Platform, Provenance
    from microdrama.contracts.providers import CommunityEventIn

    base = world.clock.now()
    world.community_provider.script_events(
        CommunityEventIn(
            provider_event_id=f"fake-flood-q-{i:05d}",
            kind=CommunityEventKind.COMMENT,
            platform=Platform.YOUTUBE,
            account_ref=world.community_account,
            external_post_id="fake-post-0001",
            author_ref=f"author-flood-{i}",
            text="ตอนต่อไปออกเมื่อไหร่คะ",
            received_at=base + timedelta(seconds=i),
            provenance=Provenance.FAKE_SYNTHETIC,
        )
        for i in range(1, 251)
    )
    report = world.process(post["season_id"], post["episode_id"])

    replies = world.rows(
        "SELECT decision, reason FROM management_actions WHERE kind = 'PUBLIC_REPLY'"
    )
    executed = [r for r in replies if r["decision"] == "EXECUTED"]
    suppressed = [r for r in replies if r["decision"] == "SUPPRESSED"]
    # Two bounds bite together: the per-post daily cap stops replies at 50, and
    # the 200-action run cap ends the pass mid-flood (50 executed + 150 recorded
    # suppressions; the remaining 52 events simply stay CLASSIFIED for the next
    # scheduled pass — backpressure, not data loss).
    assert len(executed) == 50
    assert len(suppressed) == 150
    assert all(r["reason"] == "REPLY_CAP_REACHED" for r in suppressed)
    assert report.action_cap_reached is True
    execute_calls = [call for call in world.community_provider.calls if call.method == "execute"]
    assert len(execute_calls) == 50  # suppressed actions never reached the provider
    # Spend stayed bounded: 50 replies at the synthetic metered price.
    _allocation, committed, settled = world.metered_counters(post["episode_id"])[
        "METERED_MANAGEMENT"
    ]
    assert committed == settled == 50_000
    pending = world.rows(
        "SELECT count(*) AS c FROM community_events WHERE status = 'CLASSIFIED' "
        "AND kind = 'COMMENT'"
    )
    assert pending[0]["c"] == 52


def test_action_cap_bounds_a_flood_of_actionable_events(db, tmp_path, offline_settings) -> None:
    from community_support import CommunityWorld as World

    world = World(db, tmp_path, offline_settings, max_actions_per_run=100)
    post = world.published_post()
    from datetime import timedelta

    from microdrama.contracts.enums import CommunityEventKind, Platform, Provenance
    from microdrama.contracts.providers import CommunityEventIn

    base = world.clock.now()
    world.community_provider.script_events(
        CommunityEventIn(
            provider_event_id=f"cap-flood-{i:05d}",
            kind=CommunityEventKind.COMMENT,
            platform=Platform.YOUTUBE,
            account_ref=world.community_account,
            external_post_id=f"fake-post-{i:05d}",  # distinct posts: the daily cap never binds
            author_ref=f"author-cap-{i}",
            text="ตอนต่อไปออกเมื่อไหร่คะ",
            received_at=base + timedelta(seconds=i),
            provenance=Provenance.FAKE_SYNTHETIC,
        )
        for i in range(1, 251)
    )
    report = world.process(post["season_id"], post["episode_id"])
    assert report.action_cap_reached is True
    total = world.row("SELECT count(*) AS c FROM management_actions")["c"]
    assert total == 100
    execute_calls = [c for c in world.community_provider.calls if c.method == "execute"]
    assert len(execute_calls) <= 100
