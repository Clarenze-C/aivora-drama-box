"""Database access: pooled connections, explicit transactions, typed errors.

Modules (core, budget, ...) issue their own SQL against the frozen schema through
``Database.transaction()``; they must not alter the schema. Every state mutation
and its outbox event belong in the same ``transaction()`` block.

PostgreSQL errors are translated into contract error types:
  unique_violation       → DuplicateSemanticKey (``details["constraint"]``)
  check/fk violation     → Conflict (``details["constraint"]``)
  insufficient_privilege → Unauthorized (e.g. approval without a human session)
  serialization/deadlock → retried by ``run_in_transaction``; else ServiceUnavailable
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime
from enum import StrEnum
from typing import Any, TypeVar
from uuid import UUID

import psycopg
from psycopg import errors as pg_errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from microdrama.contracts.errors import (
    Conflict,
    DuplicateSemanticKey,
    MicrodramaError,
    NotFound,
    SchemaInvalid,
    ServiceUnavailable,
    StaleRevision,
    Unauthorized,
)

T = TypeVar("T")
Row = dict[str, Any]


class IsolationLevel(StrEnum):
    READ_COMMITTED = "READ COMMITTED"
    REPEATABLE_READ = "REPEATABLE READ"
    SERIALIZABLE = "SERIALIZABLE"


def jsonb(value: Any) -> Jsonb:
    """Adapt a model/dict/list for a jsonb column using its JSON-mode dump."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return Jsonb(value)


def translate_db_error(exc: psycopg.Error) -> MicrodramaError:
    diag = getattr(exc, "diag", None)
    constraint = getattr(diag, "constraint_name", None) if diag else None
    message = (getattr(diag, "message_primary", None) if diag else None) or str(exc)
    details = {"constraint": constraint, "sqlstate": getattr(exc, "sqlstate", None)}
    if isinstance(exc, pg_errors.UniqueViolation | pg_errors.ExclusionViolation):
        return DuplicateSemanticKey(message, **details)
    if isinstance(exc, pg_errors.InsufficientPrivilege):
        return Unauthorized(message, **details)
    if isinstance(
        exc, pg_errors.CheckViolation | pg_errors.ForeignKeyViolation | pg_errors.NotNullViolation
    ):
        return Conflict(message, **details)
    if isinstance(
        exc,
        pg_errors.SerializationFailure | pg_errors.DeadlockDetected | pg_errors.LockNotAvailable,
    ):
        return ServiceUnavailable(message, retryable=True, **details)
    if isinstance(exc, psycopg.OperationalError):
        return ServiceUnavailable(message, **details)
    return MicrodramaError(message, **details)


def reject_float_params(params: Sequence[Any] | Mapping[str, Any] | None) -> None:
    """Refuse float bind parameters: PostgreSQL would silently round them into bigint
    money/ms columns (contract: money is integer micro-USD, time is integer ms)."""
    if params is None:
        return
    values = params.values() if isinstance(params, Mapping) else params
    for value in values:
        if isinstance(value, float):
            raise SchemaInvalid(
                "float bind parameters are not allowed (use integer micro-USD / ms)"
            )


class Tx:
    """A live transaction. Thin helper over a psycopg connection with dict rows.

    Every statement's parameters are checked by ``reject_float_params``.
    """

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def execute(self, sql: str, params: Sequence[Any] | Mapping[str, Any] | None = None) -> int:
        reject_float_params(params)
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount

    def fetchone(
        self, sql: str, params: Sequence[Any] | Mapping[str, Any] | None = None
    ) -> Row | None:
        reject_float_params(params)
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def fetchall(
        self, sql: str, params: Sequence[Any] | Mapping[str, Any] | None = None
    ) -> list[Row]:
        reject_float_params(params)
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())

    def fetchval(self, sql: str, params: Sequence[Any] | Mapping[str, Any] | None = None) -> Any:
        row = self.fetchone(sql, params)
        return None if row is None else next(iter(row.values()))

    def set_lock_timeout(self, ms: int) -> None:
        self.execute(f"SET LOCAL lock_timeout = '{int(ms)}ms'")


class Database:
    """Connection pool for the isolated microdrama database."""

    def __init__(
        self, dsn: str, *, min_size: int = 1, max_size: int = 10, timeout_s: float = 30.0
    ) -> None:
        self.dsn = dsn
        self._pool = ConnectionPool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            timeout=timeout_s,
            open=False,
            kwargs={"autocommit": False},
        )

    def open(self) -> Database:
        self._pool.open(wait=True)
        return self

    def close(self) -> None:
        self._pool.close()

    def __enter__(self) -> Database:
        return self.open()

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def transaction(
        self, *, isolation: IsolationLevel = IsolationLevel.READ_COMMITTED, readonly: bool = False
    ) -> Iterator[Tx]:
        """One DB transaction; commits on success, rolls back on any exception."""
        with self._pool.connection() as conn:
            try:
                conn.execute(
                    f"SET TRANSACTION ISOLATION LEVEL {isolation.value}"
                    + (" READ ONLY" if readonly else "")
                )
                yield Tx(conn)
                conn.commit()
            except psycopg.Error as exc:
                conn.rollback()
                raise translate_db_error(exc) from exc
            except BaseException:
                conn.rollback()
                raise

    def run_in_transaction(
        self,
        fn: Callable[[Tx], T],
        *,
        isolation: IsolationLevel = IsolationLevel.READ_COMMITTED,
        retries: int = 5,
    ) -> T:
        """Run ``fn`` in a transaction, retrying serialization/deadlock failures."""
        attempt = 0
        while True:
            try:
                with self.transaction(isolation=isolation) as tx:
                    return fn(tx)
            except ServiceUnavailable as exc:
                attempt += 1
                if not exc.details.get("retryable") or attempt > retries:
                    raise
                time.sleep(min(0.01 * (2**attempt), 0.2))


# --- small generic helpers -----------------------------------------------------------------

_IDENT_OK = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")


def _ident(name: str) -> str:
    if not name or set(name) - _IDENT_OK:
        raise ValueError(f"unsafe SQL identifier {name!r}")
    return name


def insert_row(tx: Tx, table: str, values: Mapping[str, Any], *, returning: str = "*") -> Row:
    cols = [_ident(c) for c in values]
    placeholders = ", ".join(["%s"] * len(cols))
    sql = f"INSERT INTO {_ident(table)} ({', '.join(cols)}) VALUES ({placeholders}) RETURNING {returning}"
    row = tx.fetchone(sql, [_adapt(v) for v in values.values()])
    assert row is not None
    return row


def get_row(
    tx: Tx, table: str, row_id: UUID, *, for_update: bool = False, id_column: str = "id"
) -> Row:
    sql = f"SELECT * FROM {_ident(table)} WHERE {_ident(id_column)} = %s" + (
        " FOR UPDATE" if for_update else ""
    )
    row = tx.fetchone(sql, (row_id,))
    if row is None:
        raise NotFound(f"{table} {row_id} not found")
    return row


def update_with_revision(
    tx: Tx,
    table: str,
    row_id: UUID,
    expected_revision: int,
    changes: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> Row:
    """Optimistic update: bumps ``revision``; raises StaleRevision if it moved."""
    if "revision" in changes or "id" in changes:
        raise ValueError("revision/id are managed by update_with_revision")
    assignments = [f"{_ident(c)} = %s" for c in changes]
    params: list[Any] = [_adapt(v) for v in changes.values()]
    assignments.append("revision = revision + 1")
    assignments.append("updated_at = coalesce(%s, now())")
    params.append(now)
    params.extend([row_id, expected_revision])
    sql = (
        f"UPDATE {_ident(table)} SET {', '.join(assignments)} "
        "WHERE id = %s AND revision = %s RETURNING *"
    )
    row = tx.fetchone(sql, params)
    if row is None:
        exists = tx.fetchone(f"SELECT revision FROM {_ident(table)} WHERE id = %s", (row_id,))
        if exists is None:
            raise NotFound(f"{table} {row_id} not found")
        raise StaleRevision(
            f"{table} {row_id} is at revision {exists['revision']}, expected {expected_revision}",
            current_revision=exists["revision"],
            expected_revision=expected_revision,
        )
    return row


def _adapt(value: Any) -> Any:
    if isinstance(value, BaseModel | dict | list) and not isinstance(value, Jsonb):
        return jsonb(value)
    if isinstance(value, StrEnum):
        return value.value
    return value
