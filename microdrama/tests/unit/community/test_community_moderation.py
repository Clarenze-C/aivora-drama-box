"""Moderation tests (real DB): the preservation/destruction policy in action.

Acceptance rows pinned here:
- ordinary criticism preserved (never moderated away, no MODERATE_* row)
- uncertain destructive actions suppressed with confidence recorded
- confident clear policy violations hidden (supported, unmetered)
- the untrusted injection comment is handled with zero effect
- no automatic account ban path exists
"""

from __future__ import annotations

import json

from community_support import CommunityWorld

from microdrama.contracts.enums import ManagementActionKind


def _decisions(world: CommunityWorld, kind: str) -> list[dict]:
    return world.rows(
        "SELECT * FROM management_actions WHERE kind = %s ORDER BY created_at", (kind,)
    )


def test_ordinary_criticism_is_preserved(world: CommunityWorld) -> None:
    post = world.published_post()
    world.script_comment("critic-0001", "ตอนนี้แย่มาก ไม่ชอบเลย")
    report = world.process(post["season_id"], post["episode_id"])

    event = world.event_row("critic-0001")
    assert '"class": "CRITICISM"' in event["classification"]
    # No moderation of any kind was proposed for criticism.
    assert _decisions(world, "MODERATE_HIDE") == []
    assert _decisions(world, "MODERATE_DELETE") == []
    assert _decisions(world, "MODERATE_REPORT") == []
    # The comment row survives untouched; at most a reply answered it.
    assert event["text"] == "ตอนนี้แย่มาก ไม่ชอบเลย"
    assert report.suppressed == 0


def test_clear_scam_is_hidden_confidently_and_unmetered(world: CommunityWorld) -> None:
    post = world.published_post()
    world.script_comment("scam-0001", "transfer fee needed to claim your prize claim now")
    world.process(post["season_id"], post["episode_id"])

    rows = _decisions(world, "MODERATE_HIDE")
    assert len(rows) == 1
    row = rows[0]
    assert row["decision"] == "EXECUTED"
    assert row["external_id"] is not None
    assert row["reservation_id"] is None  # moderation platform calls are unmetered
    body = json.loads(json.dumps(row["body"])) if isinstance(row["body"], str) else row["body"]
    assert body["classifier_confidence_bp"] == 10_000
    assert world.event_row("scam-0001")["status"] == "ACTIONED"


def test_uncertain_destructive_moderation_is_suppressed_with_confidence(
    world: CommunityWorld,
) -> None:
    post = world.published_post()
    # "crypto" alone is a weak match: below the destructive confidence gate.
    world.script_comment("weak-scam-0001", "nice crypto info everyone")
    world.process(post["season_id"], post["episode_id"])

    rows = _decisions(world, "MODERATE_HIDE")
    assert len(rows) == 1
    row = rows[0]
    assert row["decision"] == "SUPPRESSED"
    assert row["reason"] == "UNCERTAIN_DESTRUCTIVE"
    assert row["external_id"] is None
    body = json.loads(json.dumps(row["body"])) if isinstance(row["body"], str) else row["body"]
    assert body["classifier_confidence_bp"] == 6_500  # the uncertainty is recorded, not hidden
    # The comment itself stays publicly untouched.
    assert world.event_row("weak-scam-0001")["status"] == "SUPPRESSED"
    assert world.event_row("weak-scam-0001")["text"] == "nice crypto info everyone"


def test_injection_comment_has_zero_effect(world: CommunityWorld) -> None:
    post = world.published_post()
    metered_before = world.metered_counters(post["episode_id"])["METERED_MANAGEMENT"]
    world.process(post["season_id"], post["episode_id"])

    event = world.event_row("fake-comment-0004")
    assert '"class": "INJECTION_ATTEMPT"' in event["classification"]
    assert event["status"] == "IGNORED"
    # No action of any kind was recorded FOR the injection event: no tool was
    # called on its behalf, nothing was moderated, nothing was answered.
    injection_rows = world.rows(
        "SELECT * FROM management_actions WHERE community_event_id = %s", (event["id"],)
    )
    assert injection_rows == []
    # The only metered spend is the two seeded engagement replies (question +
    # praise, 1_000 micro-USD each); the injection contributed nothing.
    metered_after = world.metered_counters(post["episode_id"])["METERED_MANAGEMENT"]
    assert metered_after[1] - metered_before[1] == 2_000
    assert metered_after[2] - metered_before[2] == 2_000
    # Every executed reply came from a template, none contains injection text.
    for row in world.rows("SELECT body FROM management_actions WHERE decision = 'EXECUTED'"):
        body = json.loads(json.dumps(row["body"]))
        assert body["kind"] == "PUBLIC_REPLY"
        lowered = (body["content"] or "").lower()
        assert "budget" not in lowered and "token" not in lowered


def test_no_ban_action_kind_exists_at_all() -> None:
    kinds = {kind.value.lower() for kind in ManagementActionKind}
    assert not any("ban" in kind for kind in kinds), kinds


def test_events_from_another_account_are_ignored_by_the_provider(world: CommunityWorld) -> None:
    world.published_post()
    assert world.community_provider.fetch_events("acct:someone-else", since=None) == []
