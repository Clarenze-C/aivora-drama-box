"""Helpers shared by the registry modules: evidence classes, identifiers, time and provenance.

Two evidence rules apply everywhere in this package:

- D3 (COMPATIBILITY.md): the database cannot tell a fixture mislabelled as a real benchmark from
  a real one, so a registry writer refuses any non-fake evidence source on a record built from
  ``Provenance.FAKE_SYNTHETIC`` data.
- V-4: outside OFFLINE_MOCK, a registry row backed only by FAKE_FIXTURE evidence (or by no
  evidence at all) is treated as UNKNOWN / disabled. Migration 0008 enforces the same rule in
  any live database.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from microdrama.contracts.enums import EvidenceSource, Provenance
from microdrama.contracts.errors import PolicyDenied, SchemaInvalid
from microdrama.contracts.hashing import canonical_json
from microdrama.contracts.primitives import EvidenceRef

REGISTRY_NAMESPACE = uuid5(NAMESPACE_URL, "https://microdrama.invalid/registry/v1")

REAL_EVIDENCE_SOURCES: frozenset[EvidenceSource] = frozenset(
    {
        EvidenceSource.OFFICIAL_DOCUMENTATION,
        EvidenceSource.CONTROLLED_ACCOUNT_TEST,
        EvidenceSource.MEASURED_BENCHMARK,
        EvidenceSource.LICENSE_DOCUMENT,
    }
)
_REAL_VALUES: frozenset[str] = frozenset(source.value for source in REAL_EVIDENCE_SOURCES)

ROUTE_ID = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,119}$")
ACCOUNT_REF = re.compile(r"^acct:[a-z0-9][a-z0-9._\-]{1,120}$")
TERRITORY = re.compile(r"^[A-Z]{2}$")
WORLDWIDE = "WORLDWIDE"


def canonical_document(value: Any) -> Any:
    """The contract's canonical JSON form as plain Python values.

    Registries store this form, not pydantic's JSON dump, so ``canonical_hash`` of a stored
    document equals ``canonical_hash`` of the contract model (datetimes use the canonical
    ``...%fZ`` spelling).
    """
    return json.loads(canonical_json(value))


def ensure_provenance(value: object) -> Provenance:
    try:
        return Provenance(value)
    except ValueError:
        raise SchemaInvalid("unknown provenance") from None


def evidence_sources(evidence: Iterable[EvidenceRef | Mapping[str, Any]]) -> list[str]:
    """Source name of each evidence item, from contract objects or stored JSON objects.

    A malformed item yields ``""`` so it can never count as real evidence.
    """
    names: list[str] = []
    for item in evidence:
        if isinstance(item, EvidenceRef):
            names.append(item.source.value)
        elif isinstance(item, Mapping) and isinstance(item.get("source"), str):
            names.append(item["source"])
        else:
            names.append("")
    return names


def has_real_evidence(evidence: Iterable[EvidenceRef | Mapping[str, Any]]) -> bool:
    """True when at least one item names a real (non-fixture) source."""
    return any(name in _REAL_VALUES for name in evidence_sources(evidence))


def refuse_real_evidence_on_fake(
    provenance: Provenance, evidence: Iterable[EvidenceRef], *, what: str
) -> None:
    """D3: fake-synthetic data may never be recorded with a real evidence source."""
    if provenance is not Provenance.FAKE_SYNTHETIC:
        return
    claimed = sorted({name for name in evidence_sources(evidence) if name in _REAL_VALUES})
    if claimed:
        raise PolicyDenied(
            f"{what}: fake-synthetic data cannot carry real evidence ({', '.join(claimed)})",
            evidence_sources=claimed,
        )


def require_aware(value: object, what: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise SchemaInvalid(f"{what} must be a timezone-aware datetime")
    return value


def clean_route(value: object) -> str:
    if not isinstance(value, str) or not ROUTE_ID.fullmatch(value):
        raise SchemaInvalid("rights_route_id or preset/route identifier is malformed")
    return value


def clean_account(value: object) -> str:
    if not isinstance(value, str) or not ACCOUNT_REF.fullmatch(value):
        raise SchemaInvalid("account_ref is malformed")
    return value


def clean_subject_ref(value: object) -> str:
    if not isinstance(value, str) or not (1 <= len(value) <= 500) or "\n" in value:
        raise SchemaInvalid("subject_ref must be 1..500 characters on one line")
    return value


def clean_territories(values: Iterable[object]) -> list[str]:
    """Territories a caller needs covered; ISO 3166-1 alpha-2 codes or WORLDWIDE, non-empty."""
    cleaned: list[str] = []
    for value in values:
        if not isinstance(value, str) or not (value == WORLDWIDE or TERRITORY.fullmatch(value)):
            raise SchemaInvalid("territory must be an ISO alpha-2 code or WORLDWIDE")
        if value not in cleaned:
            cleaned.append(value)
    if not cleaned:
        raise SchemaInvalid("at least one territory must be named")
    return cleaned


def deterministic_uuid(*parts: str) -> UUID:
    """Row identifiers derived from business keys, so replays produce the same row id."""
    return uuid5(REGISTRY_NAMESPACE, "|".join(parts))


def label(route: str, ref: str) -> str:
    return f"{route}/{ref}"


__all__ = [
    "REAL_EVIDENCE_SOURCES",
    "REGISTRY_NAMESPACE",
    "WORLDWIDE",
    "canonical_document",
    "clean_account",
    "clean_route",
    "clean_subject_ref",
    "clean_territories",
    "deterministic_uuid",
    "ensure_provenance",
    "evidence_sources",
    "has_real_evidence",
    "label",
    "refuse_real_evidence_on_fake",
    "require_aware",
]
