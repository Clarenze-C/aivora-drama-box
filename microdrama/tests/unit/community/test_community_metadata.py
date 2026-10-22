"""Metadata worker tests (real DB): versioning, cooldown, edit cap, rollback.

Acceptance rows pinned here: metadata version history + rollback, the proposed
24h cooldown between substantive edits, at most two substantive edits in the
first seven days (the third is suppressed with a reason), grounding of proposed
metadata (no fabricated claims, no unapproved hashtags), policy-scoped kinds,
and no edits on posts that are not live.
"""

from __future__ import annotations

import pytest
from community_support import CommunityWorld

from microdrama.community.metadata_worker import (
    cover_assets_for_post,
    propose_cover_change,
    propose_hashtag_optimization,
)
from microdrama.community.service import METERED_ACTION_COST_MICRO_USD
from microdrama.contracts.errors import PolicyDenied
from microdrama.contracts.release import PostMetadata


def _versions(world: CommunityWorld, post_id) -> list[dict]:
    return world.rows(
        "SELECT * FROM metadata_versions WHERE platform_post_id = %s ORDER BY version",
        (post_id,),
    )


def _current(world: CommunityWorld, post_id) -> PostMetadata:
    current = world.current_metadata(post_id)
    assert current is not None
    return current[1]


def test_hashtag_optimization_versions_and_settles(world: CommunityWorld) -> None:
    post = world.published_post()
    current = _current(world, post["id"])
    assert current.hashtags == ["#thaidrama", "#shortseries"]

    facts = _facts(world, post)
    proposed = propose_hashtag_optimization(current, facts)
    assert proposed.hashtags == ["#drama", "#family", "#shortseries", "#thaidrama"]

    row = world.community.apply_metadata_edit(post["id"], proposed)
    assert row["decision"] == "EXECUTED"
    assert row["kind"] == "HASHTAG_EDIT"
    assert row["platform_post_id"] == post["id"]
    assert row["reservation_id"] is not None  # optimization is metered

    versions = _versions(world, post["id"])
    assert [v["version"] for v in versions] == [1, 2]
    assert versions[1]["substantive"] is True
    assert _current(world, post["id"]).hashtags == proposed.hashtags
    _allocation, committed, settled = world.metered_counters(post["episode_id"])[
        "METERED_MANAGEMENT"
    ]
    assert committed == settled == METERED_ACTION_COST_MICRO_USD


def _facts(world: CommunityWorld, post: dict):
    from microdrama.community.grounding import load_facts

    with world.db.transaction(readonly=True) as tx:
        return load_facts(tx, post["season_id"], now=world.clock.now())


def test_cooldown_blocks_a_second_substantive_edit_within_24h(world: CommunityWorld) -> None:
    post = world.published_post()
    first = _current(world, post["id"]).model_copy(update={"title": "ตอนที่ 2 หนี้ที่แม่ซ่อนไว้"})
    assert world.community.apply_metadata_edit(post["id"], first)["decision"] == "EXECUTED"

    second = first.model_copy(update={"title": "ตอนที่ 2 หนี้ที่แม่ซ่อนไว้ (ซับไทย)"})
    row = world.community.apply_metadata_edit(post["id"], second)
    assert row["decision"] == "SUPPRESSED"
    assert row["reason"] == "METADATA_COOLDOWN"
    assert len(_versions(world, post["id"])) == 2  # no version row was created


def test_two_edits_fit_then_the_third_in_7_days_is_capped(world: CommunityWorld) -> None:
    post = world.published_post()
    v2 = _current(world, post["id"]).model_copy(update={"title": "หนี้ที่แม่ซ่อนไว้ 2"})
    assert world.community.apply_metadata_edit(post["id"], v2)["decision"] == "EXECUTED"

    world.clock.advance(seconds=25 * 3600)
    v3 = v2.model_copy(update={"title": "หนี้ที่แม่ซ่อนไว้ 2 ตอนพิเศษ"})
    assert world.community.apply_metadata_edit(post["id"], v3)["decision"] == "EXECUTED"

    # A third substantive edit inside the first 7 days is suppressed with a reason.
    world.clock.advance(seconds=25 * 3600)
    v4 = v3.model_copy(update={"title": "หนี้ที่แม่ซ่อนไว้ 2 ฉบับปรับปรุง"})
    row = world.community.apply_metadata_edit(post["id"], v4)
    assert row["decision"] == "SUPPRESSED"
    assert row["reason"] == "SUBSTANTIVE_EDIT_CAP"
    assert [v["version"] for v in _versions(world, post["id"])] == [1, 2, 3]


def test_rollback_restores_previous_content_and_is_exempt_from_cooldown(
    world: CommunityWorld,
) -> None:
    post = world.published_post()
    original = _current(world, post["id"])
    edited = original.model_copy(update={"title": "หนี้ที่แม่ซ่อนไว้ 2"})
    assert world.community.apply_metadata_edit(post["id"], edited)["decision"] == "EXECUTED"

    # Immediately (inside the cooldown) a rollback to version 1 is allowed: it
    # restores content that was already public and cannot introduce new claims.
    versions = _versions(world, post["id"])
    row = world.community.rollback_metadata(post["id"], versions[0]["id"])
    assert row["decision"] == "EXECUTED"
    assert row["reservation_id"] is None  # rollbacks are unmetered
    assert _current(world, post["id"]) == original
    rolled = _versions(world, post["id"])[-1]
    assert rolled["version"] == 3
    assert str(rolled["rollback_of"]) == str(versions[0]["id"])

    # A forward edit right after the rollback still honours the cooldown clock
    # of the last substantive non-rollback edit (version 2).
    again = original.model_copy(update={"title": "หนี้ที่แม่ซ่อนไว้ 2 กลับมา"})
    blocked = world.community.apply_metadata_edit(post["id"], again)
    assert blocked["decision"] == "SUPPRESSED"
    assert blocked["reason"] == "METADATA_COOLDOWN"


def test_ungrounded_metadata_is_suppressed_never_applied(world: CommunityWorld) -> None:
    post = world.published_post()
    fabricated = _current(world, post["id"]).model_copy(
        update={"title": "ตอนที่ 9 ออกวันที่ 25 ธันวาคม 2026 ดูก่อนใคร"}
    )
    row = world.community.apply_metadata_edit(post["id"], fabricated)
    assert row["decision"] == "SUPPRESSED"
    assert row["reason"].startswith("UNGROUNDED_CLAIM")
    assert "EPISODE_NOT_IN_CATALOG:9" in row["reason"]
    assert len(_versions(world, post["id"])) == 1


def test_kind_outside_the_approved_policy_is_suppressed(world: CommunityWorld) -> None:
    post = world.published_post()
    # The example approved policy allows TITLE/CAPTION/HASHTAG edits — not DESCRIPTION.
    described = _current(world, post["id"]).model_copy(update={"description": "ซีรีส์ต้นฉบับเรื่องใหม่"})
    row = world.community.apply_metadata_edit(post["id"], described)
    assert row["decision"] == "SUPPRESSED"
    assert row["reason"] == "NOT_ALLOWED_BY_POLICY:description"
    assert len(_versions(world, post["id"])) == 1


def test_unapproved_hashtag_is_suppressed(world: CommunityWorld) -> None:
    post = world.published_post()
    spammed = _current(world, post["id"]).model_copy(
        update={"hashtags": ["#follow4follow", "#thaidrama"]}
    )
    row = world.community.apply_metadata_edit(post["id"], spammed)
    assert row["decision"] == "SUPPRESSED"
    assert "#follow4follow" in row["reason"]
    assert len(_versions(world, post["id"])) == 1


def test_edit_on_a_post_that_is_not_live_is_refused(world: CommunityWorld) -> None:
    post = world.published_post(promo=True)
    promo = world.row("SELECT * FROM platform_posts WHERE release_slot = 'promo'")
    with pytest.raises(PolicyDenied) as exc:
        world.community.apply_metadata_edit(promo["id"], _current(world, post["id"]))
    assert "only to published posts" in exc.value.message


def test_unchanged_metadata_is_a_caller_error(world: CommunityWorld) -> None:
    post = world.published_post()
    with pytest.raises(PolicyDenied):
        world.community.apply_metadata_edit(post["id"], _current(world, post["id"]))


def test_cover_selection_only_from_approved_package_covers(world: CommunityWorld) -> None:
    post = world.published_post(cover=True)  # the package ships one approved cover
    with world.db.transaction(readonly=True) as tx:
        covers = cover_assets_for_post(tx, post["id"])
    assert len(covers) == 1
    approved_cover = next(iter(covers))

    current = _current(world, post["id"])
    # A cover outside the approved package is refused by the worker itself.
    import uuid

    with pytest.raises(PolicyDenied):
        propose_cover_change(current, uuid.uuid4(), allowed_cover_asset_ids=covers)
    # The approved cover proposes cleanly...
    proposed = propose_cover_change(current, approved_cover, allowed_cover_asset_ids=covers)
    assert proposed.cover_asset_id == approved_cover
    # ...and applying it is policy-gated: the example approved scope does not
    # allow COVER_CHANGE, so the edit is suppressed, never applied.
    row = world.community.apply_metadata_edit(post["id"], proposed)
    assert row["decision"] == "SUPPRESSED"
    assert row["reason"] == "NOT_ALLOWED_BY_POLICY:cover_asset_id"
    assert len(_versions(world, post["id"])) == 1
