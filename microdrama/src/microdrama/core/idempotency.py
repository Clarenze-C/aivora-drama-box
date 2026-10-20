"""Command idempotency: run an action once per ``(scope, key)`` and replay its stored response.

``execute`` runs one transaction that inserts the ``idempotency_records`` row, performs the action,
and stores the response before commit. Consequences:
- a retry after success returns the stored response (``replayed=True``);
- the same key with different request content raises ``IdempotencyConflict`` (HTTP 409);
- an action that raises leaves no record, so a retry runs it again cleanly;
- two concurrent executions with one key serialise on the unique index: the loser waits, then
  replays the winner's stored response. The action runs exactly once.

Keys are scoped to the principal that first used them: another principal reusing the key gets 409.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from microdrama.contracts.errors import (
    Conflict,
    DuplicateSemanticKey,
    IdempotencyConflict,
    SchemaInvalid,
    ServiceUnavailable,
)
from microdrama.persistence.db import Database, Tx, jsonb

_KEY_CONSTRAINT = "idempotency_records_scope_idempotency_key_key"
_RACE_ATTEMPTS = 5


@dataclass(frozen=True)
class CommandResult:
    status_code: int
    body: dict[str, Any]
    replayed: bool


class IdempotencyService:
    def __init__(self, db: Database) -> None:
        self._db = db

    def execute(
        self,
        *,
        scope: str,
        key: str,
        principal_id: str,
        request_hash: str,
        action: Callable[[Tx], tuple[int, dict[str, Any]]],
    ) -> CommandResult:
        if not scope or not key or not principal_id:
            raise SchemaInvalid("scope, key and principal_id are required")
        if not isinstance(request_hash, str) or len(request_hash) != 64:
            raise SchemaInvalid("request_hash must be a 64-character SHA-256 hex digest")
        for _ in range(_RACE_ATTEMPTS):
            try:
                return self._first_execution(scope, key, principal_id, request_hash, action)
            except DuplicateSemanticKey as exc:
                if exc.details.get("constraint") != _KEY_CONSTRAINT:
                    raise
            # A concurrent execution with this key committed. Replay its stored response.
            replay = self._stored(scope, key, principal_id, request_hash)
            if replay is not None:
                return replay
            # The concurrent execution rolled back (its action failed); try again from scratch.
        raise ServiceUnavailable(
            "idempotent command is contended; retry",
            retryable=True,
            scope=scope,
        )

    def _first_execution(
        self,
        scope: str,
        key: str,
        principal_id: str,
        request_hash: str,
        action: Callable[[Tx], tuple[int, dict[str, Any]]],
    ) -> CommandResult:
        with self._db.transaction() as tx:
            existing = tx.fetchone(
                "SELECT * FROM idempotency_records WHERE scope = %s AND idempotency_key = %s FOR UPDATE",
                (scope, key),
            )
            if existing is not None:
                return _replay_or_conflict(existing, principal_id, request_hash)
            record_id = uuid.uuid4()
            tx.execute(
                "INSERT INTO idempotency_records (id, scope, idempotency_key, principal_id, request_hash) "
                "VALUES (%s, %s, %s, %s, %s)",
                (record_id, scope, key, principal_id, request_hash),
            )
            status_code, body = action(tx)
            if not isinstance(status_code, int) or not 200 <= status_code <= 299:
                raise SchemaInvalid("an idempotent command must succeed with a 2xx status")
            if not isinstance(body, dict):
                raise SchemaInvalid("an idempotent command must return a JSON object")
            tx.execute(
                "UPDATE idempotency_records SET response_status = %s, response_body = %s, "
                "completed_at = now() WHERE id = %s",
                (status_code, jsonb(body), record_id),
            )
            return CommandResult(status_code=status_code, body=body, replayed=False)

    def _stored(
        self, scope: str, key: str, principal_id: str, request_hash: str
    ) -> CommandResult | None:
        with self._db.transaction() as tx:
            existing = tx.fetchone(
                "SELECT * FROM idempotency_records WHERE scope = %s AND idempotency_key = %s",
                (scope, key),
            )
        if existing is None:
            return None
        return _replay_or_conflict(existing, principal_id, request_hash)


def _replay_or_conflict(row: dict[str, Any], principal_id: str, request_hash: str) -> CommandResult:
    if row["principal_id"] != principal_id:
        raise IdempotencyConflict("idempotency key was already used by another principal")
    if row["request_hash"] != request_hash:
        raise IdempotencyConflict("idempotency key was reused with different request content")
    if row["response_status"] is None:
        raise Conflict("the command with this idempotency key is still in progress")
    return CommandResult(
        status_code=row["response_status"],
        body=dict(row["response_body"] or {}),
        replayed=True,
    )


__all__ = ["CommandResult", "IdempotencyService"]
