"""Deterministic grounded public replies (T025).

Public replies address ordinary questions, praise and criticism in the series'
own voice. Every template is fixed text plus facts from ``GroundingFacts``:
an unannounced schedule is answered as unannounced, never guessed, and no
template makes promises, offers refunds, mentions sponsors or claims a real
human actor (MD-012/MD-018). The grounding validator in ``community.grounding``
re-checks the produced text before it is ever executed — a future model-drafted
reply must pass the same gate, so the templates are not the only defence.
"""

from __future__ import annotations

from microdrama.community.classification import CommentClass
from microdrama.community.grounding import GroundingFacts, thai_date, validate_claims

#: Hard length bound for any public reply (contract allows 5000; we stay far below).
REPLY_MAX_CHARS = 500

_REPLY_NOT_ANNOUNCED = "วันออกของตอนถัดไปยังไม่ได้ประกาศนะคะ ติดตามประกาศที่ช่องได้เลย ขอบคุณที่ถามนะคะ"
_REPLY_PRAISE = "ขอบคุณมากนะคะที่ติดตามดูซีรีส์และอยู่เคียงข้างกัน แล้วพบกันตอนหน้านะคะ"
_REPLY_CRITICISM = "ขอบคุณสำหรับความคิดเห็นค่ะ เราบันทึกคำติชบไว้เพื่อนำไปพิจารณาแล้วนะคะ ขอบคุณที่ติดตามมาถึงตรงนี้"


def draft_reply(
    comment_class: CommentClass, facts: GroundingFacts, *, text: str = ""
) -> str | None:
    """Draft a grounded reply for an engagement-class comment, or None for no reply.

    ``text`` (the untrusted incoming comment) is accepted only so callers can
    pass it for audit symmetry; it is never interpolated into the reply and
    never interpreted. INJECTION_ATTEMPT/SPAM/SCAM/THREAT/OTHER get no reply at
    all — the channel does not engage with hostile or machine text.
    """
    _ = text  # untrusted data; deliberately unused — replies quote only facts
    if comment_class is CommentClass.QUESTION:
        if facts.announced_next is not None:
            number, instant = facts.announced_next
            return (
                f"ตอนที่ {number} กำหนดออกวันที่ {thai_date(instant)} ตามตารางที่ประกาศไว้นะคะ "
                "ขอบคุณที่ถามนะคะ"
            )
        return _REPLY_NOT_ANNOUNCED
    if comment_class is CommentClass.PRAISE:
        return _REPLY_PRAISE
    if comment_class is CommentClass.CRITICISM:
        return _REPLY_CRITICISM
    return None


def grounded_reply(
    comment_class: CommentClass, facts: GroundingFacts, *, text: str = ""
) -> tuple[str | None, list[str]]:
    """Draft a reply and re-validate it against the facts before anyone executes it.

    Returns ``(reply, violations)``; a non-empty violations list means the draft
    is NOT grounded and must be suppressed (never sent). Templates are grounded
    by construction, so a violation here would mean a template regressed — the
    gate exists so model-drafted replies face the identical check.
    """
    reply = draft_reply(comment_class, facts, text=text)
    if reply is None:
        return None, []
    violations = validate_claims(reply, facts)
    if len(reply) > REPLY_MAX_CHARS:
        return reply, [*violations, f"REPLY_TOO_LONG:{len(reply)}"]
    return reply, violations


__all__ = ["REPLY_MAX_CHARS", "draft_reply", "grounded_reply"]
