"""Rights registry: versioned rights evidence per route and subject, fail-closed evaluation (MD-015).

Unknown, ineligible, expired, uncovered-territory and (outside OFFLINE_MOCK) fake-only rights all
block. A clear rights decision says nothing about QA or review: no later gate may waive a rights
blocker (AT-13).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from microdrama.config import Settings
from microdrama.contracts.enums import (
    DisclosureKind,
    Provenance,
    RightsStatus,
    RightsSubjectKind,
)
from microdrama.contracts.errors import Conflict, RightsUncleared, SchemaInvalid
from microdrama.contracts.infra import Clock
from microdrama.contracts.registries import RightsRecord
from microdrama.core.registry._common import (
    WORLDWIDE,
    canonical_document,
    clean_route,
    clean_subject_ref,
    clean_territories,
    ensure_provenance,
    has_real_evidence,
    label,
    require_aware,
    require_real_evidence_provenance,
)
from microdrama.persistence.db import Database, Tx, insert_row, jsonb

_SELECT_CURRENT = (
    "SELECT * FROM rights_registry WHERE rights_route_id = %s AND subject_kind = %s "
    "AND subject_ref = %s AND current"
)


class RightsDecision(BaseModel):
    """Outcome of a rights check. ``eligible`` is True only when there are no blockers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: RightsStatus
    blockers: list[str] = Field(default_factory=list)

    @property
    def eligible(self) -> bool:
        return self.status is RightsStatus.ELIGIBLE and not self.blockers


class RightsRegistry:
    """Writes rights versions and evaluates them. Every read and write uses the real database."""

    def __init__(self, db: Database, clock: Clock, settings: Settings) -> None:
        self._db = db
        self._clock = clock
        self._settings = settings

    # --- writes -------------------------------------------------------------------

    def record(self, record: RightsRecord, *, source_provenance: Provenance) -> None:
        """Insert a new version; the previous current version of the same subject is retired.

        Versions must strictly increase per (route, subject kind, subject ref). D3: a record built
        from fake-synthetic data may not name a real evidence source.
        """
        provenance = ensure_provenance(source_provenance)
        name = label(record.rights_route_id, record.subject_ref)
        require_real_evidence_provenance(provenance, record.evidence, what=f"rights {name}")
        if record.recorded_at > self._clock.now():
            raise SchemaInvalid("rights record is dated in the future")
        params = (record.rights_route_id, record.subject_kind.value, record.subject_ref)
        with self._db.transaction() as tx:
            latest = tx.fetchval(
                "SELECT max(version) FROM rights_registry "
                "WHERE rights_route_id = %s AND subject_kind = %s AND subject_ref = %s",
                params,
            )
            if latest is not None and record.version <= latest:
                raise Conflict(
                    f"rights {name}: version {record.version} must exceed {latest}",
                    current_version=latest,
                )
            tx.execute(
                "UPDATE rights_registry SET current = false "
                "WHERE rights_route_id = %s AND subject_kind = %s AND subject_ref = %s AND current",
                params,
            )
            insert_row(
                tx,
                "rights_registry",
                {
                    "id": record.record_id,
                    "rights_route_id": record.rights_route_id,
                    "version": record.version,
                    "subject_kind": record.subject_kind.value,
                    "subject_ref": record.subject_ref,
                    "territories": jsonb(canonical_document(list(record.territories))),
                    "commercial_use": record.commercial_use,
                    "output_release_allowed": record.output_release_allowed,
                    "required_disclosures": jsonb(
                        canonical_document([d.value for d in record.required_disclosures])
                    ),
                    "expires_at": record.expires_at,
                    "evidence": jsonb(canonical_document(record.evidence)),
                    "status": record.status.value,
                    "current": True,
                },
            )

    # --- reads --------------------------------------------------------------------

    def evaluate(
        self,
        *,
        rights_route_id: str,
        subjects: Iterable[tuple[RightsSubjectKind | str, str]],
        territories: Iterable[str],
        at: datetime | None = None,
    ) -> RightsDecision:
        """Check every required subject for every target territory at instant ``at``.

        Per subject, in order: no current record -> UNKNOWN; outside OFFLINE_MOCK a record without
        real evidence -> UNKNOWN; UNKNOWN/INELIGIBLE/EXPIRED status -> that status; ELIGIBLE with
        ``expires_at <= at`` -> EXPIRED; a target territory not covered (WORLDWIDE covers all),
        or commercial use / output release not confirmed -> INELIGIBLE. The overall status is
        ELIGIBLE only when there are no blockers.
        """
        route = clean_route(rights_route_id)
        wanted = _subjects(subjects)
        targets = clean_territories(territories)
        when = self._when(at)
        offline = self._settings.is_offline_mock
        statuses: list[RightsStatus] = []
        blockers: list[str] = []
        with self._db.transaction(readonly=True) as tx:
            for kind, ref in wanted:
                row = _current_row(tx, route, kind, ref)
                status, found = _judge(
                    row,
                    name=label(route, ref),
                    targets=targets,
                    when=when,
                    offline=offline,
                )
                statuses.append(status)
                blockers.extend(found)
        return RightsDecision(status=_overall(statuses), blockers=blockers)

    def required_disclosures(
        self,
        *,
        rights_route_id: str,
        subjects: Iterable[tuple[RightsSubjectKind | str, str]],
    ) -> frozenset[DisclosureKind]:
        """Disclosures the current rights records of these subjects require (MD-015).

        A destination must be able to make each of these disclosures before the route can publish.
        A subject without a current record contributes nothing here; ``evaluate`` blocks it.
        """
        route = clean_route(rights_route_id)
        found: set[DisclosureKind] = set()
        with self._db.transaction(readonly=True) as tx:
            for kind, ref in _subjects(subjects):
                row = _current_row(tx, route, kind, ref)
                if row is not None:
                    found.update(
                        DisclosureKind(value) for value in (row["required_disclosures"] or [])
                    )
        return frozenset(found)

    def require_cleared(
        self,
        *,
        rights_route_id: str,
        subjects: Iterable[tuple[RightsSubjectKind | str, str]],
        territories: Iterable[str],
        at: datetime | None = None,
    ) -> RightsDecision:
        """Return the decision when ELIGIBLE; otherwise raise ``RightsUncleared``."""
        decision = self.evaluate(
            rights_route_id=rights_route_id,
            subjects=subjects,
            territories=territories,
            at=at,
        )
        if not decision.eligible:
            raise RightsUncleared(
                f"rights not cleared for route {rights_route_id}: {decision.status.value}",
                status=decision.status.value,
                blockers=list(decision.blockers),
            )
        return decision

    def _when(self, at: datetime | None) -> datetime:
        value = self._clock.now() if at is None else at
        return require_aware(value, "at")


# --- module helpers ----------------------------------------------------------------


def _subjects(
    subjects: Iterable[tuple[RightsSubjectKind | str, str]],
) -> list[tuple[RightsSubjectKind, str]]:
    cleaned: list[tuple[RightsSubjectKind, str]] = []
    for kind, ref in subjects:
        try:
            pair = (RightsSubjectKind(kind), clean_subject_ref(ref))
        except ValueError:
            raise SchemaInvalid("unknown rights subject kind") from None
        if pair not in cleaned:
            cleaned.append(pair)
    if not cleaned:
        raise SchemaInvalid("at least one rights subject must be required")
    return cleaned


def _current_row(tx: Tx, route: str, kind: RightsSubjectKind, ref: str) -> dict[str, Any] | None:
    return tx.fetchone(_SELECT_CURRENT, (route, kind.value, ref))


def _judge(
    row: dict[str, Any] | None,
    *,
    name: str,
    targets: list[str],
    when: datetime,
    offline: bool,
) -> tuple[RightsStatus, list[str]]:
    if row is None:
        return RightsStatus.UNKNOWN, [f"rights unknown: no current record for {name}"]
    evidence = list(row["evidence"] or [])
    if not offline and not has_real_evidence(evidence):
        if evidence:
            return RightsStatus.UNKNOWN, [f"fake evidence only: {name}"]
        return RightsStatus.UNKNOWN, [f"rights unknown: no evidence for {name}"]
    status = RightsStatus(row["status"])
    if status is RightsStatus.UNKNOWN:
        return RightsStatus.UNKNOWN, [f"rights unknown: {name}"]
    if status is RightsStatus.INELIGIBLE:
        return RightsStatus.INELIGIBLE, [f"rights ineligible: {name}"]
    if status is RightsStatus.EXPIRED:
        return RightsStatus.EXPIRED, [f"rights expired: {name}"]
    expires = row["expires_at"]
    if expires is not None and expires <= when:
        return RightsStatus.EXPIRED, [f"rights expired at {expires.isoformat()}: {name}"]
    held = list(row["territories"] or [])
    missing = [] if WORLDWIDE in held else [t for t in targets if t not in held]
    problems: list[str] = []
    if missing:
        problems.append(f"territory not covered: {name} lacks {', '.join(missing)}")
    if row["commercial_use"] is not True:
        problems.append(f"commercial use not confirmed: {name}")
    if row["output_release_allowed"] is not True:
        problems.append(f"output release not confirmed: {name}")
    if problems:
        return RightsStatus.INELIGIBLE, problems
    return RightsStatus.ELIGIBLE, []


def _overall(statuses: list[RightsStatus]) -> RightsStatus:
    if all(status is RightsStatus.ELIGIBLE for status in statuses):
        return RightsStatus.ELIGIBLE
    if any(status is RightsStatus.INELIGIBLE for status in statuses):
        return RightsStatus.INELIGIBLE
    if any(status is RightsStatus.EXPIRED for status in statuses):
        return RightsStatus.EXPIRED
    return RightsStatus.UNKNOWN


__all__ = ["RightsDecision", "RightsRegistry"]
