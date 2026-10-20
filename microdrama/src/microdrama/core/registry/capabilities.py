"""Account/provider capability registry: tested operations, disclosures and enabled state.

A route is usable for a destination only when its current record is enabled, every required
operation is SUPPORTED_TESTED (documentation alone is not enough), every required disclosure is
supported, and (outside OFFLINE_MOCK) it has real evidence. Research-date claims never count.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from microdrama.config import Settings
from microdrama.contracts.enums import (
    CapabilityOperation,
    CapabilitySupport,
    DisclosureKind,
    EvidenceSource,
    Platform,
    Provenance,
)
from microdrama.contracts.errors import CapabilityUnavailable, Conflict, SchemaInvalid
from microdrama.contracts.infra import Clock
from microdrama.contracts.release import CapabilityRecord
from microdrama.core.registry._common import (
    canonical_document,
    clean_account,
    clean_route,
    deterministic_uuid,
    ensure_provenance,
    has_real_evidence,
    has_source,
    require_real_evidence_provenance,
)
from microdrama.persistence.db import Database, Tx, insert_row, jsonb

# Blocking words for every operation that is not SUPPORTED_TESTED. Each is distinct so a
# reviewer can tell documentation-only support from a refusal or from missing knowledge.
_SUPPORT_TEXT: dict[CapabilitySupport, str] = {
    CapabilitySupport.SUPPORTED_DOCUMENTED: "documented only, not tested",
    CapabilitySupport.UNSUPPORTED: "unsupported",
    CapabilitySupport.UNKNOWN: "unknown",
}


class CapabilityDecision(BaseModel):
    """Outcome of a capability check. ``record_version`` is None when no record exists."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    available: bool
    blockers: list[str] = Field(default_factory=list)
    record_version: int | None = None


class CapabilityRegistry:
    """Writes capability versions and evaluates them against a required operation set."""

    def __init__(self, db: Database, clock: Clock, settings: Settings) -> None:
        self._db = db
        self._clock = clock
        self._settings = settings

    # --- writes -------------------------------------------------------------------

    def record(self, record: CapabilityRecord, *, source_provenance: Provenance) -> None:
        """Insert a new version and retire the current version of the same provider route.

        Versions must strictly increase per ``capability_id``. D3 applies: fake-synthetic data
        may not name a real evidence source.
        """
        provenance = ensure_provenance(source_provenance)
        name = f"{record.platform.value}/{record.account_ref}/{record.provider_route}"
        require_real_evidence_provenance(provenance, record.evidence, what=f"capability {name}")
        if record.verified_at is not None and record.verified_at > self._clock.now():
            raise SchemaInvalid("capability verified_at is in the future")
        with self._db.transaction() as tx:
            latest = tx.fetchval(
                "SELECT max(version) FROM capability_registry WHERE capability_id = %s",
                (record.capability_id,),
            )
            if latest is not None and record.version <= latest:
                raise Conflict(
                    f"capability {name}: version {record.version} must exceed {latest}",
                    current_version=latest,
                )
            tx.execute(
                "UPDATE capability_registry SET current = false "
                "WHERE platform = %s AND account_ref = %s AND provider_route = %s AND current",
                (record.platform.value, record.account_ref, record.provider_route),
            )
            insert_row(
                tx,
                "capability_registry",
                {
                    "id": deterministic_uuid(
                        "capability", str(record.capability_id), str(record.version)
                    ),
                    "capability_id": record.capability_id,
                    "version": record.version,
                    "platform": record.platform.value,
                    "provider_route": record.provider_route,
                    "account_ref": record.account_ref,
                    "record": jsonb(canonical_document(record)),
                    "enabled": record.enabled,
                    "evidence_sources": jsonb(canonical_document(record.evidence)),
                    "verified_at": record.verified_at,
                    "current": True,
                },
            )

    # --- reads --------------------------------------------------------------------

    def current(
        self, platform: Platform | str, account_ref: str, *, provider_route: str | None = None
    ) -> CapabilityRecord | None:
        """The current record for an account. Two current routes need ``provider_route``."""
        with self._db.transaction(readonly=True) as tx:
            rows = _current_rows(tx, platform, account_ref, provider_route)
        if not rows:
            return None
        if len(rows) > 1:
            raise Conflict(
                f"{len(rows)} provider routes are current for this account; name provider_route",
                routes=[row["provider_route"] for row in rows],
            )
        stored = _stored_record(rows[0])
        if stored is None:
            raise Conflict(
                "stored capability record fails contract validation; reconcile before use",
                version=rows[0]["version"],
            )
        return stored

    def evaluate(
        self,
        *,
        platform: Platform | str,
        account_ref: str,
        required: Iterable[CapabilityOperation | str],
        disclosures: Iterable[DisclosureKind | str] = frozenset(),
        provider_route: str | None = None,
    ) -> CapabilityDecision:
        """Check one route. Blocks on: no record, disabled, a required operation that is not
        SUPPORTED_TESTED, an unsupported required disclosure, or fake-only evidence outside
        OFFLINE_MOCK. Several current routes without ``provider_route`` block as ambiguous."""
        plat = _enum(Platform, platform, "platform")
        account = clean_account(account_ref)
        ops = sorted(
            {_enum(CapabilityOperation, op, "capability operation") for op in required},
            key=lambda op: op.value,
        )
        wanted = sorted(
            {_enum(DisclosureKind, d, "disclosure") for d in disclosures},
            key=lambda d: d.value,
        )
        if not ops:
            # An empty requirement would pass any enabled route; that is a caller bug, not clearance.
            raise SchemaInvalid("at least one capability operation must be required")
        with self._db.transaction(readonly=True) as tx:
            rows = _current_rows(tx, plat, account, provider_route)
        scope = f"capability {plat.value}/{account}"
        if not rows:
            return CapabilityDecision(available=False, blockers=[f"{scope}: no current record"])
        if len(rows) > 1:
            return CapabilityDecision(
                available=False,
                blockers=[f"{scope}: {len(rows)} provider routes are current; name provider_route"],
            )
        row = rows[0]
        record = _stored_record(row)
        if record is None:
            # A tampered or corrupt row fails closed: it is a blocker, never an exception.
            return CapabilityDecision(
                available=False,
                blockers=[
                    f"{scope}: stored record fails contract validation; reconcile before use"
                ],
                record_version=row["version"],
            )
        offline = self._settings.is_offline_mock
        name = f"{scope} ({record.provider_route} v{record.version})"
        blockers: list[str] = []
        if not row["enabled"]:
            blockers.append(f"{name}: disabled")
        if not offline and not has_real_evidence(record.evidence):
            blockers.append(f"fake evidence only: {record.provider_route}/{account}")
        for op in ops:
            support = record.support(op)
            if support is not CapabilitySupport.SUPPORTED_TESTED:
                blockers.append(f"{name}: {op.value} blocked, support is {_SUPPORT_TEXT[support]}")
            elif not offline and not has_source(
                record.evidence, EvidenceSource.CONTROLLED_ACCOUNT_TEST
            ):
                # V-10: SUPPORTED_TESTED is only a label unless a controlled account tested it.
                blockers.append(
                    f"{name}: {op.value} blocked, SUPPORTED_TESTED lacks controlled-account evidence"
                )
        for kind in wanted:
            if kind not in record.supported_disclosures:
                blockers.append(f"{name}: disclosure {kind.value} is not supported")
        return CapabilityDecision(
            available=not blockers,
            blockers=blockers,
            record_version=record.version,
        )

    def require(
        self,
        *,
        platform: Platform | str,
        account_ref: str,
        required: Iterable[CapabilityOperation | str],
        disclosures: Iterable[DisclosureKind | str] = frozenset(),
        provider_route: str | None = None,
    ) -> CapabilityDecision:
        """Return the decision when available; otherwise raise ``CapabilityUnavailable``."""
        decision = self.evaluate(
            platform=platform,
            account_ref=account_ref,
            required=required,
            disclosures=disclosures,
            provider_route=provider_route,
        )
        if not decision.available:
            raise CapabilityUnavailable(
                f"capability unavailable for {_enum(Platform, platform, 'platform').value}: "
                f"{len(decision.blockers)} blocker(s)",
                blockers=list(decision.blockers),
                record_version=decision.record_version,
            )
        return decision


def _stored_record(row: dict[str, Any]) -> CapabilityRecord | None:
    """The stored contract record, or None when the row no longer validates (tamper or damage)."""
    try:
        return CapabilityRecord.model_validate(row["record"])
    except ValidationError:
        return None


def _enum[E: StrEnum](kind: type[E], value: object, what: str) -> E:
    try:
        return kind(value)
    except ValueError:
        raise SchemaInvalid(f"unknown {what}") from None


def _current_rows(
    tx: Tx, platform: Platform | str, account_ref: str, provider_route: str | None
) -> list[dict[str, Any]]:
    plat = _enum(Platform, platform, "platform")
    account = clean_account(account_ref)
    if provider_route is None:
        return tx.fetchall(
            "SELECT * FROM capability_registry WHERE platform = %s AND account_ref = %s "
            "AND current ORDER BY provider_route",
            (plat.value, account),
        )
    return tx.fetchall(
        "SELECT * FROM capability_registry WHERE platform = %s AND account_ref = %s "
        "AND provider_route = %s AND current",
        (plat.value, account, clean_route(provider_route)),
    )


__all__ = ["CapabilityDecision", "CapabilityRegistry"]
