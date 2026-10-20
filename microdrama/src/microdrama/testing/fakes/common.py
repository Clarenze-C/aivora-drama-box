"""Shared fake-provider machinery (T007): clock, ids, synthetic prices and receipts, gates.

Conventions every fake follows:
- Results and receipts carry ``Provenance.FAKE_SYNTHETIC`` and ``CostBasis.SYNTHETIC_FAKE``.
  They exercise accounting; they are not real money, quality or URLs.
- Every URL is ``https://<label>.invalid/...`` (RFC 2606), enforced by the contracts.
- Behaviour is deterministic: no randomness, no wall-clock sleeps, time comes from
  ``FakeClock``, identifiers from ``SequentialIds`` or hashes of client tokens.
- Each fake takes a scripted queue of scenario steps (one consumed per call, default HAPPY),
  records every call in ``calls`` and appends each first-time billing to ``ledger``.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar
from uuid import NAMESPACE_URL, UUID, uuid5

from microdrama.config import Settings
from microdrama.contracts.cost import PriceQuote, UsageReceipt
from microdrama.contracts.enums import (
    BudgetCategory,
    CostBasis,
    ExecutionMode,
    PriceSource,
    PriceUnit,
    Provenance,
    ReceiptKind,
)
from microdrama.contracts.errors import EffectDenied
from microdrama.contracts.hashing import sha256_hex

FAKE_NAMESPACE = uuid5(NAMESPACE_URL, "https://microdrama.invalid/fakes/v1")
FAKE_PRICE_TABLE_VERSION = "fake-prices-v1"
FAKE_PRICE_AS_OF = datetime(2026, 10, 20, tzinfo=UTC)

# Synthetic unit prices in integer micro-USD. Deliberately round, deliberately not a price list.
FAKE_PRICE_TABLE: Mapping[PriceUnit, int] = MappingProxyType(
    {
        PriceUnit.REQUEST: 1_000,
        PriceUnit.INPUT_TOKEN_1K: 500,
        PriceUnit.OUTPUT_TOKEN_1K: 1_500,
        PriceUnit.AUDIO_SECOND: 100,
        PriceUnit.VIDEO_SECOND: 300,
        PriceUnit.GPU_SECOND: 250,  # 900_000 micro-USD per hour, matching the pod fixture
        PriceUnit.IMAGE: 20_000,
        PriceUnit.CHARACTER_1K: 2_000,
        PriceUnit.GIGABYTE: 5_000,
    }
)


class FakeClock:
    """Deterministic UTC clock. Only ``advance``/``set`` move it; nothing sleeps."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError("FakeClock needs a timezone-aware start")
        self._now = start.astimezone(UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, *, ms: int = 0, seconds: int = 0) -> datetime:
        if ms < 0 or seconds < 0:
            raise ValueError("a fake clock never runs backwards")
        self._now = self._now + timedelta(seconds=seconds, milliseconds=ms)
        return self._now

    def set(self, instant: datetime) -> None:
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("FakeClock.set needs a timezone-aware instant")
        self._now = instant.astimezone(UTC)


class SequentialIds:
    """Deterministic ``IdGenerator``: uuid5 over a namespace and a counter."""

    def __init__(self, namespace: str = "default") -> None:
        self._namespace = uuid5(FAKE_NAMESPACE, f"ids:{namespace}")
        self._counter = 0

    def new_id(self) -> UUID:
        self._counter += 1
        return uuid5(self._namespace, str(self._counter))


def priced(unit: PriceUnit, units: int) -> int:
    """Integer micro-USD for ``units`` of ``unit`` at the synthetic table price."""
    if units < 0:
        raise ValueError("units cannot be negative")
    return units * FAKE_PRICE_TABLE[unit]


def fake_price_quote(unit: PriceUnit) -> PriceQuote:
    return PriceQuote(
        currency="USD",
        unit=unit,
        unit_price_micro_usd=FAKE_PRICE_TABLE[unit],
        source=PriceSource.FAKE_SYNTHETIC,
        price_table_version=FAKE_PRICE_TABLE_VERSION,
        as_of=FAKE_PRICE_AS_OF,
    )


def receipt_id_for(provider: str, provider_receipt_id: str) -> UUID:
    """Receipt ids depend only on the provider's dedupe key, so replays agree."""
    return uuid5(FAKE_NAMESPACE, f"receipt:{provider}:{provider_receipt_id}")


def synthetic_receipt(
    *,
    provider: str,
    provider_receipt_id: str,
    kind: ReceiptKind,
    category: BudgetCategory,
    unit: PriceUnit,
    units: int,
    amount_micro_usd: int,
    observed_at: datetime,
    reservation_id: UUID | None = None,
    job_id: UUID | None = None,
    episode_id: UUID | None = None,
    interval: tuple[datetime, datetime] | None = None,
) -> UsageReceipt:
    """Build a receipt that is labelled synthetic on both provenance and cost basis."""
    start, end = interval if interval is not None else (None, None)
    return UsageReceipt(
        receipt_id=receipt_id_for(provider, provider_receipt_id),
        provider=provider,
        provider_receipt_id=provider_receipt_id,
        kind=kind,
        cost_basis=CostBasis.SYNTHETIC_FAKE,
        reservation_id=reservation_id,
        episode_id=episode_id,
        job_id=job_id,
        category=category,
        amount_micro_usd=amount_micro_usd,
        units=units,
        unit=unit,
        interval_start=start,
        interval_end=end,
        observed_at=observed_at,
        provenance=Provenance.FAKE_SYNTHETIC,
    )


def fake_https(label: str, path: str = "") -> str:
    """A fake URL under the reserved ``.invalid`` TLD. Never a real host."""
    host = label if label.endswith(".invalid") else f"{label}.invalid"
    return f"https://{host}/{path.lstrip('/')}"


def ensure_mock_mode(settings: Settings) -> None:
    """Refuse to build fakes unless the process is in OFFLINE_MOCK."""
    if settings.execution_mode is not ExecutionMode.OFFLINE_MOCK:
        raise EffectDenied(
            "fake providers are only available in OFFLINE_MOCK; "
            f"execution_mode={settings.execution_mode.value} must use live adapters",
            execution_mode=settings.execution_mode.value,
        )


def stable_digest(*parts: str) -> str:
    """Short hex digest for deterministic external ids derived from client tokens."""
    return sha256_hex("|".join(parts).encode("utf-8"))[:16]


class ScenarioQueue:
    """One scripted step per call; the default applies once the script is exhausted."""

    def __init__(self, default: Enum, steps: Iterable[Enum] = ()) -> None:
        self._default = default
        self._steps: deque[Enum] = deque(steps)

    def push(self, *steps: Enum) -> None:
        self._steps.extend(steps)

    def next(self) -> Enum:
        return self._steps.popleft() if self._steps else self._default


@dataclass(frozen=True)
class CallRecord:
    method: str
    scenario: str
    key: str


class FakeBase:
    """Scenario queue, call log and billing ledger shared by every fake."""

    default_scenario: ClassVar[Enum]

    def __init__(
        self,
        *,
        clock: FakeClock,
        ids: SequentialIds,
        scenarios: Iterable[Enum] = (),
    ) -> None:
        self.clock = clock
        self.ids = ids
        self.calls: list[CallRecord] = []
        self.ledger: list[UsageReceipt] = []
        self._queue = ScenarioQueue(self.default_scenario, scenarios)
        self._billed: set[str] = set()

    def queue_scenarios(self, *steps: Enum) -> None:
        self._queue.push(*steps)

    def _step(self, method: str, key: str = "") -> Any:
        step = self._queue.next()
        self.calls.append(CallRecord(method=method, scenario=step.value, key=key))
        return step

    def _bill(self, receipts: Iterable[UsageReceipt]) -> None:
        """Ledger a receipt once per provider dedupe key; repeats are never double-billed."""
        for receipt in receipts:
            if receipt.provider_receipt_id not in self._billed:
                self._billed.add(receipt.provider_receipt_id)
                self.ledger.append(receipt)

    def _log_replay(self, method: str, key: str) -> None:
        """Record a call answered from cache; it consumes no scenario step and bills nothing."""
        self.calls.append(CallRecord(method=method, scenario="REPLAYED", key=key))

    def _note(self, method: str, key: str = "") -> None:
        """Record a call that does not consume scenario steps (status, reconcile, fetch)."""
        self.calls.append(CallRecord(method=method, scenario="-", key=key))


__all__ = [
    "CallRecord",
    "FAKE_NAMESPACE",
    "FAKE_PRICE_AS_OF",
    "FAKE_PRICE_TABLE",
    "FAKE_PRICE_TABLE_VERSION",
    "FakeBase",
    "FakeClock",
    "ScenarioQueue",
    "SequentialIds",
    "ensure_mock_mode",
    "fake_https",
    "fake_price_quote",
    "priced",
    "receipt_id_for",
    "stable_digest",
    "synthetic_receipt",
]
