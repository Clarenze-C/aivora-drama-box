"""Append-only V2 artifact persistence/replay for the story lane (T039)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar
from uuid import UUID

from microdrama.contracts.errors import Conflict
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.v2 import V2Record, verify_v2_record_hash
from microdrama.persistence.db import Database, Tx, insert_row, jsonb

_R = TypeVar("_R", bound=V2Record)


class StoryV2Store:
    """Persist immutable revisions in ``v2_contract_documents`` and verify every read."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def save_bundle(self, records: Sequence[V2Record]) -> None:
        """Atomically append a group of V2 records, replaying identical revisions."""
        ordered = sorted(records, key=lambda record: (type(record).__name__, str(record.record_id)))
        if len({(type(r).__name__, r.record_id, r.version) for r in ordered}) != len(ordered):
            raise Conflict("V2 artifact bundle contains duplicate type/id/version")
        for record in ordered:
            verify_v2_record_hash(record)
        with self._db.transaction() as tx:
            for record in ordered:
                self._save_one(tx, record)

    def read(
        self, record_type: type[_R], record_id: UUID, *, version: int | None = None
    ) -> _R | None:
        with self._db.transaction(readonly=True) as tx:
            if version is None:
                row = tx.fetchone(
                    "SELECT payload, payload_sha256 FROM v2_contract_documents "
                    "WHERE contract_type = %s AND record_id = %s AND current = true",
                    (record_type.__name__, record_id),
                )
            else:
                row = tx.fetchone(
                    "SELECT payload, payload_sha256 FROM v2_contract_documents "
                    "WHERE contract_type = %s AND record_id = %s AND version = %s",
                    (record_type.__name__, record_id, version),
                )
        if row is None:
            return None
        record = record_type.model_validate(row["payload"])
        verify_v2_record_hash(record)
        if canonical_hash(record) != row["payload_sha256"]:
            raise Conflict(
                "stored V2 artifact payload hash is invalid",
                contract_type=record_type.__name__,
                record_id=str(record_id),
            )
        return record

    def _save_one(self, tx: Tx, record: V2Record) -> None:
        contract_type = type(record).__name__
        tx.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"story-v2:{contract_type}:{record.record_id}",),
        )
        rows = tx.fetchall(
            "SELECT version, payload_sha256 FROM v2_contract_documents "
            "WHERE contract_type = %s AND record_id = %s ORDER BY version FOR UPDATE",
            (contract_type, record.record_id),
        )
        existing = next((row for row in rows if row["version"] == record.version), None)
        payload_hash = canonical_hash(record)
        if existing is not None:
            if existing["payload_sha256"] != payload_hash:
                raise Conflict(
                    "V2 artifact version already exists with different content",
                    contract_type=contract_type,
                    record_id=str(record.record_id),
                    version=record.version,
                )
            return
        latest_version = int(rows[-1]["version"]) if rows else 0
        if record.version != latest_version + 1:
            raise Conflict(
                "V2 artifact revisions must be appended consecutively",
                contract_type=contract_type,
                record_id=str(record.record_id),
                latest_version=latest_version,
                requested_version=record.version,
            )
        tx.execute(
            "UPDATE v2_contract_documents SET current = false "
            "WHERE contract_type = %s AND record_id = %s AND current = true",
            (contract_type, record.record_id),
        )
        rights = getattr(record, "rights", None)
        insert_row(
            tx,
            "v2_contract_documents",
            {
                "contract_type": contract_type,
                "record_id": record.record_id,
                "version": record.version,
                "payload": jsonb(record.model_dump(mode="json")),
                "payload_sha256": payload_hash,
                "rights_route_id": getattr(rights, "rights_route_id", None),
                "rights_version": getattr(rights, "rights_version", None),
                "valid_from": record.valid_from,
                "valid_until": record.valid_until,
                "current": True,
                "created_at": record.created_at,
            },
        )
