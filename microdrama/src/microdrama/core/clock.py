"""Production clock and id generator (implement the contract ``infra`` protocols).

Tests inject ``testing.fakes.FakeClock`` / ``SequentialIds`` instead; runtime code receives
these through its constructor so nothing in ``core`` reads the wall clock implicitly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from microdrama.contracts.infra import Clock, IdGenerator


class SystemClock:
    """Timezone-aware UTC wall clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class UuidIds:
    """Random (uuid4) identifiers."""

    def new_id(self) -> uuid.UUID:
        return uuid.uuid4()


# Structural checks: a missing method fails at import time, not at the first request.
_CLOCK_CHECK: Clock = SystemClock()
_IDS_CHECK: IdGenerator = UuidIds()

__all__ = ["SystemClock", "UuidIds"]
