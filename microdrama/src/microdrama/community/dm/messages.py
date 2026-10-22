"""MD-016 truthful DM copy for the membership lane (T026).

Every message is built ONLY from verified ``CatalogFacts`` (the current catalog
version) plus an ``EntitlementDecision``. The rules the builders enforce — and the
tests pin — are the truthfulness invariants of MD-016 / AT-11:

- A "free continuation" CTA carries the verified PUBLIC URL and never a member
  paywall link: ``free_unlock`` is the only builder that may include
  ``public_url``, and no paywall link ever appears in it.
- Paid early access is offered ONLY together with its truthful recurring price
  label AND the announced free alternative — free continuation and paid early
  access are distinguished BEFORE any checkout (``early_access_offer``).
- No entitlement (revoked or unverifiable) means NO member link: the member URL
  is entitlement enforcement, an unlisted link is not
  (``verification_unavailable``). A delay is stated honestly; the announced date
  is quoted as the original promise, never re-promised as a new fact.
- Unreleased and withdrawn episodes are said to be unavailable, with no links
  and no offer (``not_available`` / ``withdrawn``).
"""

from __future__ import annotations

from dataclasses import dataclass

from microdrama.contracts.enums import CatalogPublicState
from microdrama.memberships.catalog import CatalogFacts
from microdrama.memberships.entitlements import EntitlementDecision


@dataclass(frozen=True)
class DmMessage:
    content: str
    catalog_version: int
    kind: str  # message kind id, asserted in tests

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.content


def free_unlock(facts: CatalogFacts) -> DmMessage:
    """Free continuation: the verified public URL, never a paywall link."""
    if not facts.public_url:
        raise ValueError("a free unlock message needs the verified public URL")
    if facts.member_url and facts.member_url in facts.public_url:
        raise ValueError("public URL must not be the member paywall link")
    content = f"ตอนที่ {facts.episode_number} ปล่อยฟรีให้ทุกคนแล้ว ดูได้ที่ {facts.public_url} ขอบคุณที่ติดตามนะคะ"
    if facts.member_url is not None and facts.member_url in content:
        raise AssertionError("paywall link leaked into a free continuation message")
    return DmMessage(content=content, catalog_version=facts.catalog_version, kind="free_unlock")


def member_unlock(facts: CatalogFacts, decision: EntitlementDecision) -> DmMessage:
    """Entitled member access: only after an active=True provider check."""
    if decision.active is not True:
        raise ValueError("a member unlock requires an active entitlement check")
    if not facts.member_url:
        raise ValueError("a member unlock needs the member post URL")
    content = f"ขอบคุณที่สนับสนุนซีรีส์นะคะ สมาชิกดูตอนที่ {facts.episode_number} ได้แล้วที่ {facts.member_url}"
    return DmMessage(content=content, catalog_version=facts.catalog_version, kind="member_unlock")


def early_access_offer(facts: CatalogFacts) -> DmMessage:
    """Not entitled (yet): paid early access WITH price and free date, pre-checkout.

    MD-016: the message distinguishes free continuation from paid early access
    BEFORE checkout — both options appear, the paid one is labelled with its
    recurring price.
    """
    if not facts.member_url or not facts.price_label:
        raise ValueError("an early-access offer needs the member link and truthful price")
    if facts.free_local_text is None:
        raise ValueError("an early-access offer must state the announced free schedule")
    if facts.free_release_passed:
        # Delayed release: quote the ORIGINAL announced date as the original
        # promise; never re-promise a past date as upcoming.
        free_part = f"สำหรับทุกคนกำลังจะปล่อยฟรีตามกำหนดเดิม ({facts.free_local_text}) อยู่ในขั้นตอนสุดท้ายค่ะ"
    else:
        free_part = f"แล้วจะปล่อยฟรีให้ทุกคนในวันที่ {facts.free_local_text} ค่ะ"
    content = (
        f"ตอนที่ {facts.episode_number} เปิดให้สมาชิกดูก่อน (ราคา {facts.price_label}) "
        f"สมัคร/ดูรายละเอียดที่ {facts.member_url} {free_part}"
    )
    return DmMessage(
        content=content, catalog_version=facts.catalog_version, kind="early_access_offer"
    )


def verification_unavailable(facts: CatalogFacts) -> DmMessage:
    """Could not verify (or revoked): NO member link — an unlisted link is not access."""
    if facts.free_local_text is None or facts.free_release_passed:
        free_part = "แล้วจะปล่อยฟรีให้ทุกคนเร็ว ๆ นี้ค่ะ"
    else:
        free_part = f"แล้วจะปล่อยฟรีให้ทุกคนในวันที่ {facts.free_local_text} ค่ะ"
    content = (
        f"ขออภัยค่ะ ตอนนี้ยังไม่สามารถยืนยันสิทธิ์สมาชิกสำหรับตอนที่ {facts.episode_number} "
        f"ได้ {free_part} หากคุณเพิ่งสมัครสมาชิก ระบบจะยืนยันอีกครั้งในครั้งถัดไปค่ะ"
    )
    if facts.member_url is not None and facts.member_url in content:
        raise AssertionError("member link leaked into an unverified-entitlement message")
    return DmMessage(
        content=content, catalog_version=facts.catalog_version, kind="verification_unavailable"
    )


def not_available(facts: CatalogFacts) -> DmMessage:
    """Not released: truthful, no links, no offer, no invented date."""
    content = f"ตอนที่ {facts.episode_number} ยังไม่เปิดให้รับชมค่ะ เมื่อพร้อมจะประกาศที่นี่เป็น แหล่งข้อมูลหลักนะคะ"
    return DmMessage(content=content, catalog_version=facts.catalog_version, kind="not_available")


def withdrawn(facts: CatalogFacts) -> DmMessage:
    """Withdrawn: the offer is gone; nothing is sold or promised."""
    content = (
        f"ตอนที่ {facts.episode_number} ถูกปิดให้รับชมชั่วคราวแล้วค่ะ ขออภัยในความไม่สะดวก "
        "และขอบคุณที่สนับสนุนมานะคะ"
    )
    return DmMessage(content=content, catalog_version=facts.catalog_version, kind="withdrawn")


def message_for(facts: CatalogFacts, decision: EntitlementDecision | None) -> DmMessage:
    """The one builder the delivery service uses: catalog state decides, then entitlement."""
    if facts.state is CatalogPublicState.PUBLIC_FREE:
        return free_unlock(facts)
    if facts.state is CatalogPublicState.WITHDRAWN:
        return withdrawn(facts)
    if facts.state is CatalogPublicState.NOT_RELEASED:
        return not_available(facts)
    # EARLY_ACCESS_MEMBERS: access decisions flow only from the provider check.
    if decision is not None and decision.active is True:
        return member_unlock(facts, decision)
    if decision is not None and decision.active is False:
        return early_access_offer(facts)
    return verification_unavailable(facts)


__all__ = [
    "DmMessage",
    "early_access_offer",
    "free_unlock",
    "member_unlock",
    "message_for",
    "not_available",
    "verification_unavailable",
    "withdrawn",
]
