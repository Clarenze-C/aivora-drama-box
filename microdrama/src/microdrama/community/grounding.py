"""Grounding facts for community answers and metadata (T025).

Community workers ground every public answer and every metadata edit in the
released catalog, the approved schedule and approved offers (SPEC §10):
no fabricated episode/price/persona claims. The facts are loaded from the
durable ledger — episodes with verified posts (released), scheduled future
slots (announced next release), the approved season scope (characters, genre
tags, management policy) and the live posts' current metadata (hashtags,
catalog version). Anything not present here is UNKNOWN and may only be
answered as unknown, never invented.

``validate_claims`` is the policy gate every outbound text (reply, DM content,
proposed metadata) must pass: episode-number claims, date claims and price
claims must be backed by the facts, and real-actor persona claims are always
ungrounded (MD-012: no fake real-actor persona).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from microdrama.contracts.enums import ReleaseState
from microdrama.contracts.release import PostMetadata
from microdrama.persistence.db import Tx

THAI_MONTHS = (
    "มกราคม",
    "กุมภาพันธ์",
    "มีนาคม",
    "เมษายน",
    "พฤษภาคม",
    "มิถุนายน",
    "กรกฎาคม",
    "สิงหาคม",
    "กันยายน",
    "ตุลาคม",
    "พฤศจิกายน",
    "ธันวาคม",
)

_EPISODE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ตอนที่\s*(\d+)"),
    re.compile(r"ตอน\s*(\d+)"),
    re.compile(r"\bEP\s*(\d+)", re.IGNORECASE),
    re.compile(r"\bEpisode\s*(\d+)", re.IGNORECASE),
)
#: Thai weekday names indexed by ``date.weekday()`` (พฤหัส has two spellings).
_THAI_WEEKDAYS: tuple[tuple[str, ...], ...] = (
    ("จันทร์",),
    ("อังคาร",),
    ("พุธ",),
    ("พฤหัสบดี", "พฤหัส"),
    ("ศุกร์",),
    ("เสาร์",),
    ("อาทิตย์",),
)
_THAI_DATE_PREFIX = re.compile(r"^วันที่\s*")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_LONG_DATE = re.compile(r"\d{1,2}\s+\S+\s+\d{4}")
_THAI_DAY_MONTH = re.compile(r"วันที่\s*\d{1,2}(?!\d)(?:\s+\S+){0,2}")
_THAI_WEEKDAY = re.compile(r"วัน(จันทร์|อังคาร|พุธ|พฤหัสบดี|พฤหัส|ศุกร์|เสาร์|อาทิตย์)")
_PRICE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"฿\s*\d[\d,]*"),
    re.compile(r"\$\s*\d[\d,]*"),
    re.compile(r"\d[\d,]*\s*บาท"),
)
_PERSONA_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"นักแสดง(ตัว)?จริง"),
    re.compile(r"เราเป็น(คน|นักแสดง)จริง"),
    re.compile(r"real (life )?(actor|person)", re.IGNORECASE),
    re.compile(r"i am (a )?real (actor|person)", re.IGNORECASE),
)


def thai_date(instant: datetime) -> str:
    """The Thai long-form date of an instant (the one form replies may quote)."""
    return f"{instant.day} {THAI_MONTHS[instant.month - 1]} {instant.year}"


@dataclass(frozen=True)
class GroundingFacts:
    """Everything a public answer may truthfully reference. Absent = unknown."""

    season_id: UUID
    series_title: str
    catalog_version: int
    released_episode_numbers: frozenset[int] = frozenset()
    #: (episode_number, scheduled_utc) of the earliest future SCHEDULED slot, or None.
    announced_next: tuple[int, datetime] | None = None
    #: Approved offer claims (e.g. membership price strings); empty = no offers in scope.
    offers: Mapping[str, str] = field(default_factory=dict)
    approved_hashtags: frozenset[str] = frozenset()
    character_names: frozenset[str] = frozenset()
    #: The persona is the fictional series channel; it is never a real human actor.
    persona_is_fictional: bool = True

    def acceptable_dates(self) -> frozenset[str]:
        """Date strings a grounded text may contain (only the announced one, if any)."""
        if self.announced_next is None:
            return frozenset()
        instant = self.announced_next[1]
        return frozenset({instant.strftime("%Y-%m-%d"), thai_date(instant)})

    def mentionable_episode_numbers(self) -> frozenset[int]:
        numbers = set(self.released_episode_numbers)
        if self.announced_next is not None:
            numbers.add(self.announced_next[0])
        return frozenset(numbers)


def _date_grounded(claim: str, facts: GroundingFacts) -> bool:
    """True when one date-shaped claim is the announced release date.

    The "วันที่" (on date ...) prefix is stripped before comparing, so the Thai
    long form ``3 พฤศจิกายน 2026`` and its ISO form are the only grounded date
    claims. A weekday claim is grounded only when it is the announced weekday.
    """
    announced = facts.announced_next
    if announced is None:
        return False
    instant = announced[1]
    stripped = _THAI_DATE_PREFIX.sub("", claim).strip()
    for allowed in facts.acceptable_dates():
        if stripped == allowed or allowed in stripped or stripped in allowed:
            return True
    weekday = _THAI_WEEKDAY.search(claim)
    if weekday and weekday.group(1) in _THAI_WEEKDAYS[instant.weekday()]:
        return True
    return False


def _date_claims(text: str) -> list[str]:
    """Date-shaped claims, longest first, with claims contained in a longer claim dropped."""
    found: list[str] = []
    for pattern in (_ISO_DATE, _LONG_DATE, _THAI_DAY_MONTH, _THAI_WEEKDAY):
        found.extend(match.group(0) for match in pattern.finditer(text))
    claims: list[str] = []
    for claim in sorted(set(found), key=len, reverse=True):
        if not any(claim != longer and claim in longer for longer in claims):
            claims.append(claim)
    return claims


def validate_claims(text: str, facts: GroundingFacts) -> list[str]:
    """Return every reason ``text`` is NOT grounded in the facts (empty = grounded).

    Checked claim kinds: episode numbers (must be released or announced-next),
    dates (only the announced release date, in its exact generated forms, or its
    weekday), prices (only approved offer strings) and real-actor persona claims
    (never grounded). When nothing is announced, ANY date-shaped claim violates.
    """
    violations: list[str] = []
    for pattern in _PERSONA_PATTERNS:
        if pattern.search(text):
            violations.append("REAL_ACTOR_PERSONA")
            break
    for pattern in _EPISODE_PATTERNS:
        for match in pattern.finditer(text):
            number = int(match.group(1))
            if number not in facts.mentionable_episode_numbers():
                violations.append(f"EPISODE_NOT_IN_CATALOG:{number}")
    for claim in _date_claims(text):
        if not _date_grounded(claim, facts):
            violations.append(f"DATE_NOT_ANNOUNCED:{claim}")
    approved_prices = set(facts.offers.values())
    for pattern in _PRICE_PATTERNS:
        for match in pattern.finditer(text):
            if not any(
                price in match.group(0) or match.group(0) in price for price in approved_prices
            ):
                violations.append(f"PRICE_NOT_APPROVED:{match.group(0)}")
    return violations


def load_facts(tx: Tx, season_id: UUID, *, now: datetime) -> GroundingFacts:
    """Build the grounding facts from the durable ledger. Missing data stays unknown.

    Released = episodes of this season with at least one PUBLISHED_VERIFIED post.
    Announced next = the earliest future SCHEDULED slot of the season (its episode
    number and scheduled instant). Hashtags and the catalog version come from the
    live posts' current metadata plus the approved scope's genre tags; characters
    come from the approved scope. Membership offers belong to T026's catalog and
    are empty here until that lane supplies them through its own tables.
    """
    season = tx.fetchone("SELECT title_th FROM seasons WHERE id = %s", (season_id,))
    if season is None:
        from microdrama.contracts.errors import NotFound

        raise NotFound(f"season {season_id} not found")
    released = tx.fetchall(
        "SELECT DISTINCT e.episode_number FROM episodes e JOIN platform_posts p "
        "ON p.episode_id = e.id WHERE e.season_id = %s AND p.state = %s",
        (season_id, ReleaseState.PUBLISHED_VERIFIED.value),
    )
    announced = tx.fetchone(
        "SELECT e.episode_number, p.scheduled_utc FROM episodes e JOIN platform_posts p "
        "ON p.episode_id = e.id WHERE e.season_id = %s AND p.state = %s "
        "AND p.scheduled_utc > %s ORDER BY p.scheduled_utc, p.id LIMIT 1",
        (season_id, ReleaseState.SCHEDULED.value, now),
    )
    current_meta = tx.fetchall(
        "SELECT mv.metadata FROM metadata_versions mv JOIN platform_posts p "
        "ON p.current_metadata_version_id = mv.id WHERE p.series_id = %s",
        (season_id,),
    )
    hashtags: set[str] = set()
    catalog_version = 1
    for row in current_meta:
        metadata = PostMetadata.model_validate(row["metadata"])
        hashtags.update(metadata.hashtags)
        catalog_version = max(catalog_version, metadata.catalog_version)
    scope_characters, genre_tags = _scope_facts(tx, season_id)
    hashtags.update(f"#{tag}" for tag in genre_tags)
    return GroundingFacts(
        season_id=season_id,
        series_title=season["title_th"],
        catalog_version=catalog_version,
        released_episode_numbers=frozenset(int(row["episode_number"]) for row in released),
        announced_next=(
            (int(announced["episode_number"]), announced["scheduled_utc"])
            if announced is not None
            else None
        ),
        approved_hashtags=frozenset(hashtags),
        character_names=scope_characters,
    )


def _scope_facts(tx: Tx, season_id: UUID) -> tuple[frozenset[str], tuple[str, ...]]:
    """Character names and genre tags from the approved season scope (read-only)."""
    from microdrama.contracts.season import SeasonScope

    season = tx.fetchone("SELECT approved_scope_hash FROM seasons WHERE id = %s", (season_id,))
    if season is None or season["approved_scope_hash"] is None:
        return frozenset(), ()
    proposal = tx.fetchone(
        "SELECT scope FROM season_proposals WHERE season_id = %s AND scope_hash = %s "
        "ORDER BY scope_version DESC LIMIT 1",
        (season_id, season["approved_scope_hash"]),
    )
    if proposal is None:
        return frozenset(), ()
    scope = SeasonScope.model_validate(proposal["scope"])
    return (
        frozenset(character.name_en for character in scope.characters),
        tuple(scope.genre_tags),
    )


__all__ = ["GroundingFacts", "load_facts", "thai_date", "validate_claims"]
