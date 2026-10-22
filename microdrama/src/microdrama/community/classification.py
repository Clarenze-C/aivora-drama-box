"""Deterministic moderation/engagement classification of untrusted community text.

The classifier is pure rules over the raw text. Untrusted comment text is DATA:
nothing in this module (or its callers) parses it as instructions, tool calls,
policy overrides or configuration. An injection attempt is merely one more class
with no privilege: it never changes another event's classification, never alters
budget/policy state, and can never trigger a privileged tool.

Policy truth implemented here (SPEC §10, task T025):

- Ordinary **criticism is preserved**: a CRITICISM classification never proposes
  moderation, regardless of confidence.
- Spam/scam/threat classes only reach moderation when the match is confident;
  weak/partial matches stay below the destructive threshold and are left alone
  (uncertain ⇒ no destructive action, decided in ``policy``).
- Confidence is basis points (0..10000) and is recorded on every moderation
  action so a suppressed destructive decision is auditable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class CommentClass(StrEnum):
    """What the untrusted text looks like. A label, never an instruction."""

    QUESTION = "QUESTION"
    PRAISE = "PRAISE"
    CRITICISM = "CRITICISM"
    SPAM = "SPAM"
    SCAM = "SCAM"
    THREAT = "THREAT"
    INJECTION_ATTEMPT = "INJECTION_ATTEMPT"
    OTHER = "OTHER"


#: Confidence a full-phrase rule match carries (certain, basis points).
CERTAIN_BP = 10_000
#: Confidence a weak single-word/partial match carries (below any destructive gate).
WEAK_BP = 6_500
#: Confidence for engagement classes (no destructive consequence either way).
ENGAGEMENT_BP = 9_000

# High-precision phrases first; weak single words only lower confidence to partial.
_RULES: tuple[tuple[CommentClass, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        CommentClass.INJECTION_ATTEMPT,
        (
            "ignore previous instructions",
            "disregard your instructions",
            "raise the budget",
            "admin token",
            "system prompt",
            "you are now",
            "execute this command",
        ),
        ("instructions",),
    ),
    (
        CommentClass.THREAT,
        ("kill you", "i will find you", "จะทำร้าย", "ข่มขู่ว่าจะทำร้าย"),
        ("threat", "ข่มขู่"),
    ),
    (
        CommentClass.SCAM,
        (
            "transfer fee",
            "send bitcoin",
            "crypto giveaway",
            "prize claim",
            "ค่าธรรมเนียมล่วงหน้า",
            "ของรางวัลฟรี",
            "ลุ้นรางวัลแค่โอนเงิน",
        ),
        ("giveaway", "prize", "crypto", "รางวัล"),
    ),
    (
        CommentClass.SPAM,
        (
            "buy followers",
            "dm for promo",
            "ติดต่อโปรโมทไลน์",
            "ขายผู้ติดตาม",
            "ติดตามกลับทุกคน",
        ),
        ("promo", "followers", "โปรโมท"),
    ),
    (
        CommentClass.QUESTION,
        (
            "ตอนหน้า",
            "เมื่อไหร่",
            "ตอนต่อไป",
            "when is the next",
            "next episode",
            "what time",
        ),
        ("?", "กี่โมง", "schedule", "ตาราง"),
    ),
    (
        CommentClass.PRAISE,
        ("ขอบคุณ", "ชอบมาก", "สนุกมาก", "เรื่องนี้ดี", "thank you", "love this", "great episode"),
        ("nice", "good", "ดีมาก"),
    ),
    (
        CommentClass.CRITICISM,
        ("ไม่ชอบ", "น่าเบื่อมาก", "ตอนนี้แย่มาก", "boring episode", "too slow", "not good at all"),
        ("boring", "แย่", "ไม่ชอบ", "slow"),
    ),
)

# Moderation classes take precedence over engagement classes when both match.
_MODERATION_CLASSES = frozenset(
    {CommentClass.SPAM, CommentClass.SCAM, CommentClass.THREAT, CommentClass.INJECTION_ATTEMPT}
)


@dataclass(frozen=True)
class Classification:
    """Result of classifying one untrusted text. ``matched_rules`` names the evidence."""

    comment_class: CommentClass
    confidence_bp: int
    matched_rules: tuple[str, ...]

    @property
    def moderation_class(self) -> bool:
        return self.comment_class in _MODERATION_CLASSES


def classify_comment(text: str) -> Classification:
    """Classify untrusted text with deterministic keyword rules.

    The text is lowercased and matched only; it is never evaluated, parsed as
    instructions, or allowed to reach any tool. Moderation classes win over
    engagement classes; within a class a full-phrase hit is certain (10_000 bp)
    while a weak single-word hit alone stays at 6_500 bp — deliberately below
    the destructive-action gate in ``community.policy``.
    """
    haystack = (text or "").lower()
    best: Classification | None = None
    for comment_class, certain, weak in _RULES:
        hits = tuple(rule for rule in certain if rule in haystack)
        weak_hits = tuple(rule for rule in weak if rule in haystack)
        if not hits and not weak_hits:
            continue
        confidence = CERTAIN_BP if hits else WEAK_BP
        evidence = hits or weak_hits
        candidate = Classification(
            comment_class=comment_class, confidence_bp=confidence, matched_rules=evidence
        )
        if best is None:
            best = candidate
            continue
        # A moderation label outranks an engagement label; otherwise keep the first
        # (rules are ordered by severity) and prefer the more confident one.
        if candidate.moderation_class and not best.moderation_class:
            best = candidate
        elif candidate.moderation_class == best.moderation_class and (
            candidate.confidence_bp > best.confidence_bp
        ):
            best = candidate
    if best is None:
        return Classification(comment_class=CommentClass.OTHER, confidence_bp=0, matched_rules=())
    return best


#: Patterns that look like instruction-injection even outside the seeded fixture;
#: used only to label, never to act on, the text.
INJECTION_MARKERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore (all )?(previous|prior) instructions", re.IGNORECASE),
    re.compile(r"(raise|increase|lift) the (budget|spending|cap)", re.IGNORECASE),
    re.compile(r"(admin|api|secret|access) (token|key|password)", re.IGNORECASE),
)


__all__ = [
    "CERTAIN_BP",
    "Classification",
    "CommentClass",
    "ENGAGEMENT_BP",
    "INJECTION_MARKERS",
    "WEAK_BP",
    "classify_comment",
]
