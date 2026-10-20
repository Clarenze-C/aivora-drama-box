"""Extension points run inside the caller's transaction.

- ``TransitionGuard``: consulted before a state transition is written. A guard that raises
  (for example ``IdentityLockRequired`` or ``RightsUncleared``) aborts the transition and the
  transaction. Guards are supplied by the owning module; core has no built-in bypass.
- ``ApprovalHook``: notified after a human approval event is inserted, in the same transaction
  (for example the identity-lock creator in T011). A hook that raises rolls the approval back.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from microdrama.contracts.enums import EpisodeState
from microdrama.contracts.principals import Principal
from microdrama.contracts.season import ApprovalCommand
from microdrama.persistence.db import Tx


@runtime_checkable
class TransitionGuard(Protocol):
    def __call__(self, tx: Tx, entity_row: dict[str, Any], target: EpisodeState) -> None:
        """Raise a contract error to refuse the transition; return None to allow it."""
        ...


@runtime_checkable
class ApprovalHook(Protocol):
    def on_recorded(
        self,
        tx: Tx,
        *,
        approval_event_id: UUID,
        command: ApprovalCommand,
        principal: Principal,
    ) -> None:
        """Runs inside the approval transaction after the decision row is inserted."""
        ...


__all__ = ["ApprovalHook", "TransitionGuard"]
