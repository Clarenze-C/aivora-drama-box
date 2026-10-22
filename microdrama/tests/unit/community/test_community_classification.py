"""Classification tests (pure rules; no database).

Pins the moderation/engagement labels, the confidence ladder (certain phrase vs
weak word) and the injection label. Untrusted text is only ever matched here —
these tests double as the proof that the injection fixture is inert data.
"""

from __future__ import annotations

import pytest

from microdrama.community.classification import (
    CERTAIN_BP,
    WEAK_BP,
    Classification,
    CommentClass,
    classify_comment,
)
from microdrama.community.service import classification_from_text, classification_to_text
from microdrama.testing.fakes.community import INJECTION_COMMENT


def test_ordinary_criticism_is_criticism_never_moderation() -> None:
    for text in (
        "ตอนนี้แย่มาก ไม่ชอบเลย",
        "boring episode, too slow",
        "not good at all",
    ):
        result = classify_comment(text)
        assert result.comment_class is CommentClass.CRITICISM, text
        assert not result.moderation_class  # criticism is never a moderation class


def test_clear_spam_scam_threat_are_certain() -> None:
    assert classify_comment("send bitcoin to claim your prize claim now").comment_class in (
        CommentClass.SCAM,
    )
    assert classify_comment("i will find you and kill you").comment_class is CommentClass.THREAT
    assert classify_comment("ติดต่อโปรโมทไลน์ ขายผู้ติดตาม").comment_class is CommentClass.SPAM
    for text in ("send bitcoin to claim your prize claim now", "i will find you and kill you"):
        assert classify_comment(text).confidence_bp == CERTAIN_BP


def test_weak_matches_stay_below_the_destructive_threshold() -> None:
    # A single weak word is not enough to destroy: confidence sits below 9000 bp.
    result = classify_comment("nice crypto info")
    assert result.comment_class is CommentClass.SCAM
    assert result.confidence_bp == WEAK_BP
    assert WEAK_BP < 9_000


def test_injection_attempt_is_labelled_and_inert() -> None:
    result = classify_comment(INJECTION_COMMENT)
    assert result.comment_class is CommentClass.INJECTION_ATTEMPT
    assert result.confidence_bp == CERTAIN_BP
    # The label is data: it changes nothing about other texts.
    assert classify_comment("ขอบคุณค่ะ").comment_class is CommentClass.PRAISE


def test_benign_flood_text_is_other() -> None:
    assert classify_comment("fixture flood message 42").comment_class is CommentClass.OTHER
    assert classify_comment("fixture flood message 42").confidence_bp == 0


def test_moderation_outranks_engagement_when_both_match() -> None:
    result = classify_comment("thank you but transfer fee prize claim needed")
    assert result.moderation_class


def test_empty_text_is_other() -> None:
    assert classify_comment("").comment_class is CommentClass.OTHER


def test_classification_round_trip_through_the_stored_text_form() -> None:
    original = Classification(
        comment_class=CommentClass.THREAT,
        confidence_bp=9_500,
        matched_rules=("kill you",),
    )
    assert classification_from_text(classification_to_text(original)) == original
    assert classification_from_text(None) is None
    assert classification_from_text("not json") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ตอนหน้ามาเมื่อไหร่คะ", CommentClass.QUESTION),
        ("ขอบคุณค่ะ", CommentClass.PRAISE),
        ("เมื่อไหร่จะออกตอนต่อไป", CommentClass.QUESTION),
    ],
)
def test_seeded_fixture_texts_classify_as_expected(text: str, expected: CommentClass) -> None:
    assert classify_comment(text).comment_class is expected
