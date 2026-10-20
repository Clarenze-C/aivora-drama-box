"""Infrastructure interfaces: clock, IDs, private object store, queue transport, rate limiter.

A Redis queue transport carries job IDs only; it does not enforce business
idempotency or budgets — the durable job/budget tables do. Media bytes live in
the object store, never in Redis, n8n payloads or events.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import Field

from microdrama.contracts.enums import QueueName
from microdrama.contracts.primitives import (
    ContractModel,
    Count,
    DurationMs,
    ObjectKey,
    Sha256Hex,
    ShortText,
)


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """Current timezone-aware UTC time."""
        ...


@runtime_checkable
class IdGenerator(Protocol):
    def new_id(self) -> UUID: ...


class StoredObject(ContractModel):
    key: ObjectKey
    sha256: Sha256Hex
    size_bytes: Count
    media_type: ShortText


@runtime_checkable
class ObjectStore(Protocol):
    """Private store. Keys are relative and validated; no public URLs are produced."""

    def put_bytes(self, key: str, data: bytes, *, media_type: str) -> StoredObject: ...

    def put_file(self, key: str, source: Path, *, media_type: str) -> StoredObject: ...

    def get_bytes(self, key: str) -> bytes: ...

    def local_path(self, key: str) -> Path:
        """Readable local path for FFmpeg/ffprobe (filesystem store) or a cached copy."""
        ...

    def head(self, key: str) -> StoredObject | None: ...

    def verify(self, key: str, sha256: str) -> bool:
        """True only if the object exists and its content hash matches."""
        ...


@runtime_checkable
class QueueTransport(Protocol):
    def enqueue(self, queue: QueueName, job_id: UUID) -> None: ...

    def dequeue(self, queue: QueueName, *, timeout_ms: int) -> UUID | None: ...

    def ack(self, queue: QueueName, job_id: UUID) -> None: ...

    def depth(self, queue: QueueName) -> int: ...


class RateDecision(ContractModel):
    allowed: bool
    retry_after_ms: DurationMs = 0
    limiter_key: ShortText
    remaining: Count | None = Field(default=None)


@runtime_checkable
class RateLimiter(Protocol):
    """Shared provider/account limiter used by every queue (retries included)."""

    def try_acquire(self, key: str, *, cost: int = 1) -> RateDecision: ...


@runtime_checkable
class CredentialResolver(Protocol):
    """Resolves a ``credref:`` name to a secret at the edge. Never log the result."""

    def resolve(self, ref: str) -> str: ...
