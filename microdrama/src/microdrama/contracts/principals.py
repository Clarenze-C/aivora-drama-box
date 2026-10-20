"""Authenticated principals. Identity comes from authentication, never from a payload."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field, model_validator

from microdrama.contracts.enums import PrincipalKind, RuntimeRole
from microdrama.contracts.primitives import ContractModel, ShortText, SortedStrSet


class Principal(ContractModel):
    """Who is acting. Only HUMAN_OWNER principals carry a human session.

    Approval events require a HUMAN_OWNER principal with a live human session;
    worker, model, webhook and scheduler principals can never produce them.
    """

    principal_id: ShortText
    kind: PrincipalKind
    session_id: UUID | None = Field(default=None, description="Human review session (humans only)")
    runtime_role: RuntimeRole | None = None
    scopes: SortedStrSet = frozenset()

    @model_validator(mode="after")
    def _shape(self) -> Principal:
        if self.kind is PrincipalKind.HUMAN_OWNER:
            if self.session_id is None:
                raise ValueError("human principals require an authenticated session_id")
            if self.runtime_role is not None:
                raise ValueError("human principals have no runtime role")
        else:
            if self.session_id is not None:
                raise ValueError("non-human principals cannot carry a human session")
        if self.kind is PrincipalKind.RUNTIME_MODEL and self.runtime_role is None:
            raise ValueError("runtime model principals must declare their runtime_role")
        return self

    @property
    def is_human_owner(self) -> bool:
        return self.kind is PrincipalKind.HUMAN_OWNER
