"""Organic-management policy gates (T025): MD-018, destructive confidence, caps.

Pure checks the community service applies BEFORE any reservation or provider
call. Policy truth implemented here:

- **MD-018**: organic management accepts no contracts, invents no sponsorships,
  issues no refunds, never raises budgets and never does cold outreach. Content
  carrying forbidden commitment language is suppressed with a recorded reason.
- **Destructive moderation needs confidence**: MODERATE_HIDE/MODERATE_DELETE/
  MODERATE_REPORT execute only at or above ``DESTRUCTIVE_MIN_CONFIDENCE_BP``;
  below it the action is SUPPRESSED (never executed) with the classifier
  confidence recorded on the durable action row.
- **Ordinary criticism is preserved**: no moderation class covers CRITICISM,
  and ``criticism_moderation_blocked`` is a hard guard the service honours.
- **No automatic account bans**: the ManagementActionKind enum has no ban kind
  and ``ManagementPolicy`` refuses ``automatic_account_bans=True``; nothing in
  this lane may synthesize one.
"""

from __future__ import annotations

import re

from microdrama.contracts.enums import ManagementActionKind
from microdrama.contracts.release import DESTRUCTIVE_ACTIONS
from microdrama.contracts.season import ManagementPolicy

#: Confidence (basis points) a destructive moderation action needs to execute.
DESTRUCTIVE_MIN_CONFIDENCE_BP = 9_000

#: Moderation kinds gated by the confidence rule (REPORT rides the same rule as
#: DELETE/HIDE: an external accusation is never made on a hunch).
CONFIDENCE_GATED_KINDS = frozenset({*DESTRUCTIVE_ACTIONS, ManagementActionKind.MODERATE_REPORT})

_FORBIDDEN_CONTENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"คืนเงิน|เงินคืน"),
    re.compile(r"refund", re.IGNORECASE),
    re.compile(r"สปอนเซอร์|sponsor(ship)?ed?", re.IGNORECASE),
    re.compile(r"สัญญา(จ้าง|ร่วมมือ)?"),
    re.compile(r"\bcontract\b", re.IGNORECASE),
    re.compile(r"ลดราคา|ส่วนลด"),
    re.compile(r"discount", re.IGNORECASE),
    re.compile(r"โปรโมชั่นพิเศษ|ข้อเสนอพิเศษ"),
    re.compile(r"(raise|increase|lift)\s+the\s+(budget|cap|spending)", re.IGNORECASE),
    re.compile(r"เพิ่ม(งบ|เพดาน)"),
    re.compile(r"โอนเงิน(ให้|ไปที่)|send (money|bitcoin|crypto)", re.IGNORECASE),
)


def action_kind_allowed(policy: ManagementPolicy, kind: ManagementActionKind) -> bool:
    """True when the approved season policy lists this action kind (Gate-2-bound scope)."""
    return kind in policy.allowed_actions


def destructive_gate(
    kind: ManagementActionKind, confidence_bp: int | None
) -> tuple[bool, str | None]:
    """(may_execute, reason). Confidence-gated kinds need a confident classification.

    ``reason`` is set exactly when the action must be suppressed:
    ``UNCERTAIN_DESTRUCTIVE`` below the threshold (or without any confidence),
    never a silent pass. Uncertainty never becomes a destructive action.
    """
    if kind not in CONFIDENCE_GATED_KINDS:
        return True, None
    if confidence_bp is not None and confidence_bp >= DESTRUCTIVE_MIN_CONFIDENCE_BP:
        return True, None
    return False, "UNCERTAIN_DESTRUCTIVE"


def criticism_moderation_blocked() -> bool:
    """Ordinary criticism is never moderated by this automation (hard policy)."""
    return True


def md018_content_violation(content: str | None) -> str | None:
    """The first MD-018 forbidden-commitment match in outbound content, or None.

    Applies to replies, DM content and proposed metadata text alike: organic
    management cannot accept contracts, invent sponsorships, issue refunds,
    promise discounts or move money. The match text is the reason, so a
    suppressed action states what it almost said.
    """
    if not content:
        return None
    for pattern in _FORBIDDEN_CONTENT_PATTERNS:
        match = pattern.search(content)
        if match:
            return f"MD018_FORBIDDEN_CONTENT:{match.group(0)}"
    return None


def is_cold_outreach(*, kind: ManagementActionKind, linked_inbound_dm: bool) -> str | None:
    """A suppression reason when a DM_SEND is outbound-only, else None.

    DMs answer an inbound conversation inside its messaging window; a public
    comment is never blanket permission for follow-up, and a DM action with no
    linked inbound DM event is cold outreach (outside organic scope). Keyword
    and entitlement logic is T026's lane; this gate only refuses DMs that
    answer nothing.
    """
    if kind is not ManagementActionKind.DM_SEND:
        return None
    if not linked_inbound_dm:
        return "COLD_OUTREACH_NO_INBOUND_DM"
    return None


def reply_cap_reason(*, executed_replies_last_24h: int, policy: ManagementPolicy) -> str | None:
    """A suppression reason when the per-post daily reply cap is reached, else None."""
    if executed_replies_last_24h >= policy.max_replies_per_post_per_day:
        return "REPLY_CAP_REACHED"
    return None


def dm_cap_reason(*, executed_dms_in_conversation: int, policy: ManagementPolicy) -> str | None:
    """A suppression reason when the per-conversation DM cap is reached, else None."""
    if executed_dms_in_conversation >= policy.max_dms_per_conversation:
        return "DM_CAP_REACHED"
    return None


__all__ = [
    "CONFIDENCE_GATED_KINDS",
    "DESTRUCTIVE_MIN_CONFIDENCE_BP",
    "action_kind_allowed",
    "criticism_moderation_blocked",
    "destructive_gate",
    "dm_cap_reason",
    "is_cold_outreach",
    "md018_content_violation",
    "reply_cap_reason",
]
