"""Domain events (outbox). Delivery is at least once; consumers must be idempotent."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from microdrama.contracts.hashing import canonical_json_bytes
from microdrama.contracts.primitives import (
    MAX_EVENT_PAYLOAD_BYTES,
    PositiveInt,
    UtcDateTime,
    VersionedPayload,
)


class DomainEvent(VersionedPayload):
    event_id: UUID
    event_type: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$", max_length=120)
    aggregate_type: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=60)
    aggregate_id: UUID
    sequence: PositiveInt = Field(description="Monotonic per aggregate")
    correlation_id: UUID
    causation_id: UUID | None = None
    occurred_at: UtcDateTime
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _bounded(self) -> DomainEvent:
        size = len(canonical_json_bytes(self.payload))
        if size > MAX_EVENT_PAYLOAD_BYTES:
            raise ValueError(
                f"event payload {size} bytes exceeds {MAX_EVENT_PAYLOAD_BYTES}; store large data privately"
            )
        return self
