"""Bounded knobs for the references lane (T011).

Prices are configuration, never hardcoded model facts: a missing price means the
step cannot dispatch (typed NOT_DISPATCHED, zero spend), because an unknown price
blocks paid dispatch (SPEC §6). The one forced pairing this build inherits from the
frozen T007 fake and T005 policy: image-anchor receipts arrive in category
GPU_GENERATION, and GPU_GENERATION reservations must be priced per GPU_SECOND
(policy V-21), so an image anchor's *reservation* is bounded by its timeout at the
GPU-second price while the settled amount comes from the provider's own IMAGE-unit
receipt. See evidence/T011.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from microdrama.contracts.cost import PriceQuote


@dataclass(frozen=True)
class ReferencesConfig:
    image_model_config_ref: str = "ref-anchor-image-v1"
    voice_model_config_ref: str = "ref-voice-th-v1"
    image_rights_route_id: str = "route-ref-image"
    voice_rights_route_id: str = "route-ref-voice-th"

    # Reservation prices. None means "unknown": every paid dispatch is refused typed.
    image_price: PriceQuote | None = None  # GPU_SECOND quote bounding the anchor timeout
    voice_price: PriceQuote | None = None  # CHARACTER_1K quote bounding one synthesis

    generation_timeout_ms: int = 120_000
    max_status_polls: int = 5
    transport_attempts: int = 2
    reservation_ttl_ms: int = 900_000

    anchor_width: int = 64
    anchor_height: int = 64
    outfits_per_character: int = 1  # the story lane emits no outfit ids yet (T010)
    max_line_characters: int = 1000

    def __post_init__(self) -> None:
        if self.max_status_polls < 1 or self.transport_attempts < 1:
            raise ValueError("poll/transport attempts must be >= 1")
        if self.generation_timeout_ms < 1_000:
            raise ValueError("generation timeout must be at least one second")
        if self.outfits_per_character < 1 or self.outfits_per_character > 3:
            raise ValueError("1..3 outfits per character")
        if not 1 <= self.max_line_characters <= 1000:
            raise ValueError("max_line_characters must be within 1..1000 (contract bound)")

    @property
    def prices_configured(self) -> bool:
        return self.image_price is not None and self.voice_price is not None

    @property
    def anchor_dimensions(self) -> tuple[int, int]:
        return self.anchor_width, self.anchor_height


__all__ = ["ReferencesConfig"]
