"""Truthful membership catalog transitions (T026, MD-016).

The catalog is the ONLY source of truth for what a buyer can be told: every public
route resolves from verified catalog state, and an unlisted link is never
entitlement enforcement. Transitions are versioned rows in ``membership_catalog``
(``UNIQUE (episode_id, catalog_version)``, at most one ``current`` row per episode,
content columns immutable once written — a transition always inserts a new version
and flips the ``current`` flag of the previous one).

State machine and its truthfulness rules:

- ``NOT_RELEASED`` — the initial version. Nothing may be offered or linked.
- ``EARLY_ACCESS_MEMBERS`` — only when the episode's media is finished AND a real
  Gate 2 (``EPISODE_FINAL``) APPROVE approval event exists for THIS episode, a
  provider is selected, a truthful recurring price (> 0) is configured and the
  announced free-release instant is recorded. The contract validator enforces the
  field shape; this service verifies the approval event against the database, so a
  caller-asserted "approved" flag is not enough.
- ``PUBLIC_FREE`` — only with a public URL that matches a ``PUBLISHED_VERIFIED``
  platform post of the same episode (a verified public URL, never an unlisted or
  promised one). Content already released free can never return to paid early
  access.
- ``WITHDRAWN`` — an owner cancellation; honest "no longer available" state.

Free-date truth (SPEC §10): the ORIGINAL announced free-release instant can never
silently move. Every later version preserves it exactly (the frozen
``ScheduleInstant`` — DST changes and expired windows cannot alter it). An attempt
to move it raises ``PolicyDenied``; only an explicit owner decision
(``owner_decision=FreeDateOwnerDecision``) records a new instant, as a new version
plus an append-only ``membership.free_date_changed`` domain event. Going free
BEFORE the announced date is a date move in the earlier direction and follows the
same rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from microdrama.contracts.catalog import MemberPrice, MembershipCatalogEntry
from microdrama.contracts.enums import CatalogPublicState, Provenance
from microdrama.contracts.errors import Conflict, NotFound, PolicyDenied, SchemaInvalid
from microdrama.contracts.hashing import sha256_hex
from microdrama.contracts.infra import Clock, IdGenerator
from microdrama.contracts.primitives import ScheduleInstant, ShortText
from microdrama.contracts.providers import MembershipProvider
from microdrama.core.events import append_event
from microdrama.persistence.db import Database, Tx, insert_row, jsonb

FAKE = Provenance.FAKE_SYNTHETIC
_AGGREGATE = "membership_catalog"

#: Transitions allowed between public states (a re-open after withdrawal is an
#: owner-visible new version; FREE -> PAID would break the free promise).
_ALLOWED: dict[CatalogPublicState, frozenset[CatalogPublicState]] = {
    CatalogPublicState.NOT_RELEASED: frozenset(
        {CatalogPublicState.EARLY_ACCESS_MEMBERS, CatalogPublicState.PUBLIC_FREE}
    ),
    CatalogPublicState.EARLY_ACCESS_MEMBERS: frozenset(
        {
            CatalogPublicState.EARLY_ACCESS_MEMBERS,
            CatalogPublicState.PUBLIC_FREE,
            CatalogPublicState.WITHDRAWN,
        }
    ),
    CatalogPublicState.PUBLIC_FREE: frozenset(
        {CatalogPublicState.PUBLIC_FREE, CatalogPublicState.WITHDRAWN}
    ),
    CatalogPublicState.WITHDRAWN: frozenset(
        {CatalogPublicState.EARLY_ACCESS_MEMBERS, CatalogPublicState.PUBLIC_FREE}
    ),
}


@dataclass(frozen=True)
class FreeDateOwnerDecision:
    """An explicit, recorded owner decision to move the announced free date."""

    reason: ShortText
    decided_by: str = "owner"


def _instant(now: datetime) -> ScheduleInstant:
    """A UTC ScheduleInstant for an instant taken from the injected clock."""
    return ScheduleInstant(
        iana_zone="UTC",
        local_time=now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
        utc_instant=now,
    )


def price_text(price: MemberPrice) -> str:
    """Truthful price label derived with integer math (never float money)."""
    dollars, cents = divmod(price.amount_micro_usd, 1_000_000)
    cents //= 10_000  # micro-USD -> hundredths of a dollar
    return f"${dollars}.{cents:02d}/{price.interval}"


@dataclass(frozen=True)
class CatalogFacts:
    """What a message may truthfully claim about an episode right now."""

    episode_id: UUID
    episode_number: int
    state: CatalogPublicState
    catalog_version: int
    public_url: str | None = None
    member_url: str | None = None
    member_price: MemberPrice | None = None
    free_release: ScheduleInstant | None = None
    free_release_passed: bool = False
    entry: MembershipCatalogEntry | None = None

    @property
    def free_local_text(self) -> str | None:
        """The announced free date as a local wall-clock string in its own zone."""
        if self.free_release is None:
            return None
        return f"{self.free_release.local_time} ({self.free_release.iana_zone})"

    @property
    def price_label(self) -> str | None:
        return price_text(self.member_price) if self.member_price else None


class MembershipCatalogService:
    """Versioned, truthful catalog transitions over the frozen tables."""

    def __init__(self, db: Database, clock: Clock, ids: IdGenerator) -> None:
        self._db = db
        self._clock = clock
        self._ids = ids

    # --- reads ---------------------------------------------------------------------------

    def current_entry(self, episode_id: UUID) -> MembershipCatalogEntry | None:
        with self._db.transaction(readonly=True) as tx:
            row = self._current_row(tx, episode_id)
        return self._entry(row) if row is not None else None

    def facts(self, episode_id: UUID) -> CatalogFacts:
        """CatalogFacts for messaging. No entry yet == not released (truthful)."""
        entry = self.current_entry(episode_id)
        if entry is None:
            return CatalogFacts(
                episode_id=episode_id,
                episode_number=0,
                state=CatalogPublicState.NOT_RELEASED,
                catalog_version=0,
            )
        now = self._clock.now()
        passed = entry.free_release is not None and now >= entry.free_release.utc_instant
        return CatalogFacts(
            episode_id=entry.episode_id,
            episode_number=entry.episode_number,
            state=entry.public_state,
            catalog_version=entry.catalog_version,
            public_url=entry.public_url,
            member_url=entry.member_url,
            member_price=entry.member_price,
            free_release=entry.free_release,
            free_release_passed=passed,
            entry=entry,
        )

    # --- writes --------------------------------------------------------------------------

    def record_not_released(
        self, *, season_id: UUID, episode_id: UUID, episode_number: int
    ) -> MembershipCatalogEntry:
        """Create the initial NOT_RELEASED version (idempotent for one episode)."""
        with self._db.transaction() as tx:
            self._require_episode(tx, season_id, episode_id, episode_number)
            row = self._current_row(tx, episode_id)
            if row is not None:
                raise Conflict(
                    "episode already has a catalog entry; it cannot return to NOT_RELEASED",
                    episode_id=str(episode_id),
                    current_state=row["public_state"],
                )
            entry = MembershipCatalogEntry(
                entry_id=self._ids.new_id(),
                season_id=season_id,
                episode_id=episode_id,
                episode_number=episode_number,
                catalog_version=1,
                public_state=CatalogPublicState.NOT_RELEASED,
                media_finished_and_approved=False,
                provenance=FAKE,
            )
            self._insert(tx, entry)
            return entry

    def publish_early_access(
        self,
        *,
        season_id: UUID,
        episode_id: UUID,
        episode_number: int,
        provider: MembershipProvider,
        media_path: Path,
        approval_event_id: UUID,
        price: MemberPrice,
        free_release: ScheduleInstant,
        owner_decision: FreeDateOwnerDecision | None = None,
    ) -> MembershipCatalogEntry:
        """Open paid member early access. Nothing unfinished or unapproved is sold.

        Truthfulness gates, in order: episode identity; a real Gate 2 APPROVE for
        this episode; a positive recurring price; free-date immutability; the state
        machine; then the provider publishes the member post (accepted only for
        EARLY_ACCESS entries) and the resulting member post id/URL are recorded in
        a new catalog version.
        """
        if price.amount_micro_usd <= 0:
            raise PolicyDenied(
                "early access needs a truthful recurring price above zero",
                amount_micro_usd=price.amount_micro_usd,
            )
        with self._db.transaction() as tx:
            self._require_episode(tx, season_id, episode_id, episode_number)
            self._require_final_approval(tx, episode_id, approval_event_id)
            current = self._current_row(tx, episode_id)
            if current is not None:
                current_entry = self._entry(current)
                self._require_transition(
                    current_entry.public_state, CatalogPublicState.EARLY_ACCESS_MEMBERS
                )
                replay = self._early_access_replay(
                    current_entry, provider, price, free_release, approval_event_id
                )
            else:
                replay = None
            announced = self._announced_free_release(tx, episode_id)
            self._check_free_date(announced, free_release, owner_decision)
            version = self._next_version(tx, episode_id)

        if replay is not None:
            return replay  # idempotent re-open with identical terms: no new version

        draft = MembershipCatalogEntry(
            entry_id=self._ids.new_id(),
            season_id=season_id,
            episode_id=episode_id,
            episode_number=episode_number,
            catalog_version=version,
            public_state=CatalogPublicState.EARLY_ACCESS_MEMBERS,
            media_finished_and_approved=True,
            approval_event_id=approval_event_id,
            member_provider=provider.kind,
            member_price=price,
            free_release=free_release,
            provenance=FAKE,
        )
        # Provider call outside the write transaction (offline fixture; a live route
        # at T032 must go through the outbox before any resubmission).
        post = provider.publish_early_access(draft, media_path)
        final = draft.model_copy(
            update={"member_post_id": post.member_post_id, "member_url": post.member_url}
        )
        with self._db.transaction() as tx:
            self._flip_current(tx, episode_id)
            self._insert(tx, final)
            self._record_free_date_change(
                tx, episode_id, owner_decision, announced, final.free_release
            )
            self._event(
                tx,
                episode_id,
                "membership.early_access_opened",
                {
                    "catalog_version": final.catalog_version,
                    "provider": final.member_provider.value if final.member_provider else None,
                    "member_post_id": final.member_post_id,
                    "price_micro_usd": final.member_price.amount_micro_usd
                    if final.member_price
                    else None,
                    "free_release_utc": final.free_release.utc_instant.isoformat()
                    if final.free_release
                    else None,
                },
            )
        return final

    def mark_public_free(
        self,
        *,
        episode_id: UUID,
        public_url: str,
        owner_decision: FreeDateOwnerDecision | None = None,
    ) -> MembershipCatalogEntry:
        """Transition to PUBLIC_FREE with a VERIFIED public URL (MD-016 truth).

        The URL must match a ``PUBLISHED_VERIFIED`` platform post of this episode:
        a promised, unlisted or unverified link can never back a "free now" claim.
        The announced free date is preserved; going free before it is a date move
        that needs the explicit owner decision.
        """
        with self._db.transaction() as tx:
            current = self._current_row(tx, episode_id)
            if current is None:
                raise NotFound("episode has no catalog entry", episode_id=str(episode_id))
            current_entry = self._entry(current)
            if (
                current_entry.public_state is CatalogPublicState.PUBLIC_FREE
                and current_entry.public_url == public_url
            ):
                return current_entry  # idempotent replay
            self._require_transition(current_entry.public_state, CatalogPublicState.PUBLIC_FREE)
            verified = tx.fetchone(
                "SELECT id FROM platform_posts WHERE episode_id = %s "
                "AND state = 'PUBLISHED_VERIFIED' AND url = %s LIMIT 1",
                (episode_id, public_url),
            )
            if verified is None:
                raise PolicyDenied(
                    "a public-free entry needs the URL of a PUBLISHED_VERIFIED post of this "
                    "episode; an unverified or unlisted link is not a free release",
                    episode_id=str(episode_id),
                )
            announced = self._announced_free_release(tx, episode_id)
            now = self._clock.now()
            if announced is None:
                free_release: ScheduleInstant | None = _instant(now)
            elif now < announced.utc_instant:
                # Going free before the announced date moves the promise earlier.
                self._check_free_date(announced, _instant(now), owner_decision)
                free_release = _instant(now)
            else:
                free_release = announced
            version = self._next_version(tx, episode_id)
            final = current_entry.model_copy(
                update={
                    "entry_id": self._ids.new_id(),
                    "catalog_version": version,
                    "public_state": CatalogPublicState.PUBLIC_FREE,
                    "public_url": public_url,
                    "free_release": free_release,
                }
            )
            self._flip_current(tx, episode_id)
            self._insert(tx, final)
            self._record_free_date_change(
                tx, episode_id, owner_decision, announced, final.free_release
            )
            self._event(
                tx,
                episode_id,
                "membership.public_free",
                {"catalog_version": version, "public_url": public_url},
            )
        return final

    def withdraw(self, *, episode_id: UUID, reason: ShortText) -> MembershipCatalogEntry:
        """Owner cancellation: the episode stops being offered (truthful, recorded)."""
        with self._db.transaction() as tx:
            current = self._current_row(tx, episode_id)
            if current is None:
                raise NotFound("episode has no catalog entry", episode_id=str(episode_id))
            current_entry = self._entry(current)
            if current_entry.public_state is CatalogPublicState.WITHDRAWN:
                return current_entry  # idempotent replay
            self._require_transition(current_entry.public_state, CatalogPublicState.WITHDRAWN)
            version = self._next_version(tx, episode_id)
            final = current_entry.model_copy(
                update={
                    "entry_id": self._ids.new_id(),
                    "catalog_version": version,
                    "public_state": CatalogPublicState.WITHDRAWN,
                }
            )
            self._flip_current(tx, episode_id)
            self._insert(tx, final)
            self._event(
                tx,
                episode_id,
                "membership.withdrawn",
                {"catalog_version": version, "reason": reason},
            )
        return final

    # --- internals ------------------------------------------------------------------------

    @staticmethod
    def _entry(row) -> MembershipCatalogEntry:
        return MembershipCatalogEntry.model_validate(row["body"])

    @staticmethod
    def _current_row(tx: Tx, episode_id: UUID):
        return tx.fetchone(
            "SELECT * FROM membership_catalog WHERE episode_id = %s AND current", (episode_id,)
        )

    @staticmethod
    def _require_episode(tx: Tx, season_id: UUID, episode_id: UUID, episode_number: int) -> None:
        row = tx.fetchone(
            "SELECT season_id, episode_number FROM episodes WHERE id = %s", (episode_id,)
        )
        if row is None:
            raise NotFound("episode not found", episode_id=str(episode_id))
        if row["season_id"] != season_id:
            raise Conflict("episode belongs to a different season", episode_id=str(episode_id))
        if row["episode_number"] != episode_number:
            raise SchemaInvalid(
                "episode number does not match the catalog entry",
                expected=episode_number,
                actual=row["episode_number"],
            )

    @staticmethod
    def _require_final_approval(tx: Tx, episode_id: UUID, approval_event_id: UUID) -> None:
        """Only a real Gate 2 APPROVE for THIS episode can make media 'approved'."""
        row = tx.fetchone(
            "SELECT gate_type, action, entity_id FROM approval_events WHERE id = %s",
            (approval_event_id,),
        )
        if row is None:
            raise PolicyDenied(
                "cannot sell early access: approval event not found",
                approval_event_id=str(approval_event_id),
            )
        if (
            row["gate_type"] != "EPISODE_FINAL"
            or row["action"] != "APPROVE"
            or row["entity_id"] != episode_id
        ):
            raise PolicyDenied(
                "cannot sell early access: media is not finished-and-approved by Gate 2 "
                "for this episode",
                approval_event_id=str(approval_event_id),
                gate_type=row["gate_type"],
                entity_id=str(row["entity_id"]),
            )

    def _announced_free_release(self, tx: Tx, episode_id: UUID) -> ScheduleInstant | None:
        """The ORIGINAL announced free date: the earliest version that carries one."""
        row = tx.fetchone(
            "SELECT body FROM membership_catalog WHERE episode_id = %s "
            "AND free_release_utc IS NOT NULL ORDER BY catalog_version LIMIT 1",
            (episode_id,),
        )
        if row is None:
            return None
        free = MembershipCatalogEntry.model_validate(row["body"]).free_release
        return free

    @staticmethod
    def _check_free_date(
        announced: ScheduleInstant | None,
        proposed: ScheduleInstant,
        owner_decision: FreeDateOwnerDecision | None,
    ) -> None:
        """The announced free date never silently moves (SPEC §10).

        An identical proposal is free. A different one raises unless an explicit
        owner decision was given — and that decision is always appended to the
        outbox as a visible ``membership.free_date_changed`` event by
        ``_record_free_date_change`` in the same transaction as the new version.
        """
        if announced is None or announced == proposed:
            return
        if owner_decision is None:
            raise PolicyDenied(
                "the announced free release date cannot silently move; record an explicit "
                "owner decision to change it",
                announced_utc=announced.utc_instant.isoformat(),
                proposed_utc=proposed.utc_instant.isoformat(),
            )

    def _record_free_date_change(
        self,
        tx: Tx,
        episode_id: UUID,
        decision: FreeDateOwnerDecision | None,
        announced: ScheduleInstant | None,
        final_release: ScheduleInstant | None,
    ) -> None:
        if decision is None or announced is None or final_release is None:
            return
        if announced == final_release:
            return
        append_event(
            tx,
            aggregate_type=_AGGREGATE,
            aggregate_id=episode_id,
            event_type="membership.free_date_changed",
            payload={
                "announced_utc": announced.utc_instant.isoformat(),
                "new_utc": final_release.utc_instant.isoformat(),
                "reason": decision.reason,
                "decided_by": decision.decided_by,
            },
            correlation_id=self._ids.new_id(),
            occurred_at=self._clock.now(),
        )

    def _next_version(self, tx: Tx, episode_id: UUID) -> int:
        row = tx.fetchone(
            "SELECT coalesce(max(catalog_version), 0) AS v FROM membership_catalog "
            "WHERE episode_id = %s",
            (episode_id,),
        )
        return int(row["v"]) + 1

    @staticmethod
    def _early_access_replay(
        current: MembershipCatalogEntry,
        provider: MembershipProvider,
        price: MemberPrice,
        free_release: ScheduleInstant,
        approval_event_id: UUID,
    ) -> MembershipCatalogEntry | None:
        """An identical re-open returns the current entry: one version, no re-publish."""
        if current.public_state is not CatalogPublicState.EARLY_ACCESS_MEMBERS:
            return None
        if (
            current.member_provider is provider.kind
            and current.member_price == price
            and current.free_release == free_release
            and current.approval_event_id == approval_event_id
            and current.member_post_id is not None
        ):
            return current
        return None

    @staticmethod
    def _require_transition(current: CatalogPublicState, target: CatalogPublicState) -> None:
        if target not in _ALLOWED[current]:
            raise PolicyDenied(
                "catalog transition is not truthful",
                current_state=current.value,
                target_state=target.value,
            )

    def _flip_current(self, tx: Tx, episode_id: UUID) -> None:
        tx.execute(
            "UPDATE membership_catalog SET current = false WHERE episode_id = %s AND current",
            (episode_id,),
        )

    def _insert(self, tx: Tx, entry: MembershipCatalogEntry) -> None:
        insert_row(
            tx,
            "membership_catalog",
            {
                "id": entry.entry_id,
                "season_id": entry.season_id,
                "episode_id": entry.episode_id,
                "catalog_version": entry.catalog_version,
                "public_state": entry.public_state.value,
                "media_finished_and_approved": entry.media_finished_and_approved,
                "approval_event_id": entry.approval_event_id,
                "member_provider": entry.member_provider.value if entry.member_provider else None,
                "member_post_id": entry.member_post_id,
                "member_price_micro_usd": entry.member_price.amount_micro_usd
                if entry.member_price
                else None,
                "free_release_utc": entry.free_release.utc_instant if entry.free_release else None,
                "free_release_zone": entry.free_release.iana_zone if entry.free_release else None,
                "public_url": entry.public_url,
                "member_url": entry.member_url,
                "body": jsonb(entry),
                "current": True,
            },
        )

    def _event(self, tx: Tx, episode_id: UUID, event_type: str, payload: dict) -> None:
        append_event(
            tx,
            aggregate_type=_AGGREGATE,
            aggregate_id=episode_id,
            event_type=event_type,
            payload=payload,
            correlation_id=self._ids.new_id(),
            occurred_at=self._clock.now(),
        )


def member_ref_hash(member_ref: str) -> str:
    """Privacy-preserving member identifier (the table stores ONLY this hash)."""
    return sha256_hex(member_ref.encode("utf-8"))


__all__ = [
    "CatalogFacts",
    "FreeDateOwnerDecision",
    "MembershipCatalogService",
    "member_ref_hash",
    "price_text",
]
