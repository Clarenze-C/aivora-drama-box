"""Module-local payloads for the references lane (T011).

Contracts are frozen at 1.5.0 and this module adds no cross-module schema: everything
here extends ``ContractModel`` the same way the story lane's payloads do (promotion
proposal recorded in evidence/T011.md if a later lane needs them cross-module).
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field

from microdrama.contracts.enums import IdentityAssetKind
from microdrama.contracts.primitives import (
    ContractModel,
    Count,
    Identifier,
    MicroUSD,
    PositiveInt,
    PositiveMs,
    Sha256Hex,
    ShortText,
)

RefKind = IdentityAssetKind


class PrepareStatus(StrEnum):
    """Typed outcome of one ``prepare_episode`` call (never a silent failure)."""

    CURRENT = "CURRENT"  # new anchors/lines produced and the script/manifest were filled
    REPLAYED = "REPLAYED"  # the current script/manifest are already filled; nothing dispatched
    NOT_DISPATCHED = "NOT_DISPATCHED"  # a typed unknown (no price/route) blocked paid dispatch


class AnchorSpec(ContractModel):
    """One reusable identity anchor to ensure (face/wardrobe/location/style/voice)."""

    ref_kind: RefKind
    ref_key: ShortText
    character_key: Identifier | None = None
    location_id: Identifier | None = None
    prompt: str = Field(min_length=1, max_length=4000)
    width: PositiveInt
    height: PositiveInt
    seed: Count
    lineage_asset_ids: list[UUID] = Field(default_factory=list)

    @property
    def is_voice(self) -> bool:
        return self.ref_kind is RefKind.VOICE


class AnchorView(ContractModel):
    """One reference version as ``prepare_episode`` resolved it."""

    ref_kind: RefKind
    ref_key: ShortText
    version: PositiveInt
    asset_id: UUID
    content_sha256: Sha256Hex
    state: ShortText
    cache_key: Sha256Hex
    reused: bool = Field(description="True when no paid generation ran for this resolution")
    voice_id: Identifier | None = None


class LineAudio(ContractModel):
    """One synthesized dialogue line with its measured (actual) duration."""

    line_id: Identifier
    speaker_character_id: Identifier
    voice_id: Identifier
    asset_id: UUID
    sha256: Sha256Hex
    actual_duration_ms: PositiveMs


class PrepareOutcome(ContractModel):
    episode_id: UUID
    season_id: UUID
    status: PrepareStatus
    settled_micro_usd: MicroUSD = 0
    anchors: list[AnchorView] = Field(default_factory=list)
    lines: list[LineAudio] = Field(default_factory=list)
    script_version: PositiveInt | None = None
    manifest_version: PositiveInt | None = None
    reference_lock_version: Count | None = None
    identity_lock_id: UUID | None = None
    uncertainty_notes: list[str] = Field(default_factory=list)


class ChangeOutcome(ContractModel):
    """Result of an explicit reference change (versions references; Gate 2 stays ordinary)."""

    season_id: UUID
    episode_id: UUID
    ref_kind: RefKind
    ref_key: ShortText
    superseded_version: PositiveInt
    new_version: PositiveInt | None = None
    new_asset_id: UUID | None = None
    invalidated_ref_keys: list[ShortText] = Field(default_factory=list)
    invalidated_asset_ids: list[UUID] = Field(default_factory=list)


class LockMember(ContractModel):
    ref_kind: RefKind
    ref_key: ShortText
    version: PositiveInt
    asset_id: UUID
    content_sha256: Sha256Hex
    state: ShortText
    character_key: Identifier | None = None


class LockView(ContractModel):
    lock_id: UUID
    season_id: UUID
    source_episode_id: UUID
    version: PositiveInt
    approval_event_id: UUID
    release_package_hash: Sha256Hex
    created_at: str
    members: list[LockMember] = Field(default_factory=list)


class RenderBindings(ContractModel):
    """What a later-episode render attempt must use (IMP-01: no render before the lock)."""

    episode_id: UUID
    episode_number: PositiveInt
    lock_id: UUID | None
    lock_version: Count | None
    manifest_id: UUID
    reference_asset_ids: list[UUID] = Field(default_factory=list)
    locked_ref_keys: list[ShortText] = Field(default_factory=list)
    provisional_ref_keys: list[ShortText] = Field(default_factory=list)


__all__ = [
    "AnchorSpec",
    "AnchorView",
    "ChangeOutcome",
    "LineAudio",
    "LockMember",
    "LockView",
    "PrepareOutcome",
    "PrepareStatus",
    "RefKind",
    "RenderBindings",
]
