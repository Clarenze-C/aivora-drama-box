"""Static poster and optional episode-one preview derivation (T043).

This module is deliberately independent of publication and generation services. It
validates accepted-source lineage and creates deterministic local FFmpeg plans; a
consumer can add the resulting immutable records to its existing Gate 2 package.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from microdrama.contracts.enums import AssetKind, AssetState, Platform, Provenance
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.media import AssetDescriptor, CropSpec, EditDecisionList
from microdrama.contracts.primitives import (
    ContractModel,
    Identifier,
    Sha256Hex,
    ShortText,
    UtcDateTime,
)
from microdrama.contracts.v2 import RightsGrant
from microdrama.editing.ffmpeg import FFmpegRunner
from microdrama.editing.variants import center_crop, variant_frame

PREVIEW_MAX_MS = 90_000


class CreativeSource(ContractModel):
    """An exact, accepted source version with release rights."""

    asset: AssetDescriptor
    rights: RightsGrant

    @model_validator(mode="after")
    def accepted_and_licensed(self):
        if self.asset.state not in (AssetState.ACCEPTED, AssetState.LOCKED):
            raise ValueError("creative source must be accepted or locked")
        if self.asset.provenance is Provenance.DERIVED_LOCAL and not self.asset.lineage:
            raise ValueError("derived creative source must retain its source lineage")
        return self


class SafeZone(ContractModel):
    """Normalized rectangle that must remain clear of platform UI overlays."""

    left: int = Field(ge=0, le=10_000, strict=True)
    top: int = Field(ge=0, le=10_000, strict=True)
    right: int = Field(ge=0, le=10_000, strict=True)
    bottom: int = Field(ge=0, le=10_000, strict=True)

    @model_validator(mode="after")
    def ordered(self):
        if self.left >= self.right or self.top >= self.bottom:
            raise ValueError("safe zone must have positive area")
        return self


class PosterPlan(ContractModel):
    kind: Literal["POSTER"] = "POSTER"
    episode_id: UUID
    approved_reveal_episode: int = Field(ge=1)
    platform: Platform
    variant_key: Identifier
    character: CreativeSource
    title: CreativeSource
    cta: CreativeSource
    title_text: ShortText
    cta_text: ShortText
    approved_cta_texts: list[ShortText] = Field(min_length=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    safe_zone: SafeZone
    title_box: SafeZone
    cta_box: SafeZone
    readability_check: Literal["PASS"]
    readability_evidence_sha256: Sha256Hex
    rights_as_of: UtcDateTime
    source_hashes: dict[str, Sha256Hex]
    package_hash: Sha256Hex
    downstream_lineage: list[UUID]

    @model_validator(mode="after")
    def complete_and_safe(self):
        if self.cta_text not in self.approved_cta_texts:
            raise ValueError("poster CTA is not an approved truthful CTA")
        if self.character.asset.asset_kind is not AssetKind.IMAGE:
            raise ValueError("poster character source must be an image")
        if (
            self.title.asset.asset_kind is not AssetKind.IMAGE
            or self.cta.asset.asset_kind is not AssetKind.IMAGE
        ):
            raise ValueError("poster title and CTA must be approved rendered image assets")
        for label, box in (("title", self.title_box), ("CTA", self.cta_box)):
            if (
                box.left < self.safe_zone.left
                or box.top < self.safe_zone.top
                or box.right > self.safe_zone.right
                or box.bottom > self.safe_zone.bottom
            ):
                raise ValueError(f"poster {label} box falls outside the mobile safe zone")
        sources = {"character": self.character, "title": self.title, "cta": self.cta}
        if any(
            source.rights.expires_at is not None and self.rights_as_of >= source.rights.expires_at
            for source in sources.values()
        ):
            raise ValueError("poster source rights are expired at derivation time")
        if self.source_hashes != {k: v.asset.sha256 for k, v in sources.items()}:
            raise ValueError("poster source hashes do not match exact source versions")
        if self.downstream_lineage != [s.asset.asset_id for s in sources.values()]:
            raise ValueError("poster lineage must list its exact character/title/CTA assets")
        body = self.model_dump(mode="json", exclude={"package_hash"})
        if canonical_hash(body) != self.package_hash:
            raise ValueError("poster package hash does not cover the exact plan")
        return self


class PreviewPlan(ContractModel):
    kind: Literal["EPISODE_ONE_PREVIEW"] = "EPISODE_ONE_PREVIEW"
    platform: Platform
    variant_key: Identifier
    approved_reveal_episode: Literal[1] = 1
    source_edl: EditDecisionList
    sources: list[CreativeSource] = Field(min_length=1)
    source_hashes: dict[str, Sha256Hex]
    rights_as_of: UtcDateTime
    reveal_boundary_ms: int = Field(ge=0)
    source_ranges_ms: list[tuple[int, int]] = Field(min_length=1)
    safe_zone: SafeZone
    cta_box: SafeZone
    cta_text: ShortText
    approved_cta_texts: list[ShortText] = Field(min_length=1)
    package_hash: Sha256Hex
    downstream_lineage: list[UUID]
    release_obligation: Literal[False] = False

    @model_validator(mode="after")
    def valid_slice(self):
        if self.source_edl.duration_ms > PREVIEW_MAX_MS:
            raise ValueError("episode-one preview cannot exceed 90 seconds")
        if self.cta_text not in self.approved_cta_texts:
            raise ValueError("preview CTA is not an approved truthful CTA")
        ids = {c.source_asset_id for c in self.source_edl.clips}
        if not ids or ids != set(self.downstream_lineage):
            raise ValueError("preview lineage must exactly cover every EDL input")
        if set(self.source_hashes) != {str(i) for i in ids}:
            raise ValueError("preview must bind a hash for every exact EDL input")
        source_by_id = {str(source.asset.asset_id): source for source in self.sources}
        if set(source_by_id) != {str(i) for i in ids}:
            raise ValueError("preview source records must exactly cover source footage")
        if self.source_hashes != {key: source.asset.sha256 for key, source in source_by_id.items()}:
            raise ValueError("preview source hashes do not match accepted exact source versions")
        if any(
            source.rights.expires_at is not None and self.rights_as_of >= source.rights.expires_at
            for source in self.sources
        ):
            raise ValueError("preview source rights are expired at derivation time")
        intervals = [(c.source_in_ms, c.source_out_ms) for c in self.source_edl.clips]
        if any(a < 0 for a, _ in intervals):
            raise ValueError("preview source ranges cannot start before zero")
        if any(
            clip.track.value == "VIDEO" and clip.source_out_ms > self.reveal_boundary_ms
            for clip in self.source_edl.clips
        ):
            raise ValueError("preview source range crosses the reveal boundary")
        if sorted(self.source_ranges_ms) != sorted(intervals):
            raise ValueError("preview source ranges must exactly match every EDL input")
        body = self.model_dump(mode="json", exclude={"package_hash"})
        if canonical_hash(body) != self.package_hash:
            raise ValueError("preview package hash does not cover the exact plan")
        return self


def platform_poster_frame(width: int, height: int, ratio: str) -> tuple[int, int, CropSpec | None]:
    """Resolve a tested platform ratio into output dimensions and crop."""
    return (*variant_frame(width, height, ratio), center_crop(width, height, ratio))


def run_poster_export(
    runner: FFmpegRunner,
    *,
    source_names: dict[UUID, str],
    plan: PosterPlan,
    output: str,
) -> None:
    """Compose approved character/title/CTA image assets into a still poster.

    Title and CTA are already typeset, approved image assets. This avoids sending
    arbitrary script/CTA text through a filter graph and preserves Thai shaping.
    """
    inputs = [plan.character.asset.asset_id, plan.title.asset.asset_id, plan.cta.asset.asset_id]
    if any(asset_id not in source_names for asset_id in inputs):
        raise ValueError("poster export is missing a staged accepted source")
    title_w = round(plan.width * (plan.title_box.right - plan.title_box.left) / 10_000)
    title_h = round(plan.height * (plan.title_box.bottom - plan.title_box.top) / 10_000)
    cta_w = round(plan.width * (plan.cta_box.right - plan.cta_box.left) / 10_000)
    cta_h = round(plan.height * (plan.cta_box.bottom - plan.cta_box.top) / 10_000)
    tx = round(plan.width * plan.title_box.left / 10_000)
    ty = round(plan.height * plan.title_box.top / 10_000)
    cx = round(plan.width * plan.cta_box.left / 10_000)
    cy = round(plan.height * plan.cta_box.top / 10_000)
    graph = (
        f"[0:v]scale={plan.width}:{plan.height}:force_original_aspect_ratio=increase,"
        f"crop={plan.width}:{plan.height},setsar=1[bg];"
        f"[1:v]scale={title_w}:{title_h}:force_original_aspect_ratio=decrease,"
        f"format=rgba[title];[2:v]scale={cta_w}:{cta_h}:force_original_aspect_ratio=decrease,"
        f"format=rgba[cta];[bg][title]overlay={tx}:{ty}[withtitle];"
        f"[withtitle][cta]overlay={cx}:{cy},format=yuvj420p[out]"
    )
    runner.export(
        [
            "-i",
            source_names[inputs[0]],
            "-i",
            source_names[inputs[1]],
            "-i",
            source_names[inputs[2]],
            "-filter_complex",
            graph,
            "-map",
            "[out]",
            "-frames:v",
            "1",
            "-q:v",
            "2",
        ],
        output=runner.workdir / output,
    )


def run_preview_export(
    runner: FFmpegRunner,
    *,
    source_names: dict[UUID, str],
    plan: PreviewPlan,
    output: str,
) -> None:
    """Export an already-authorized preview EDL using existing safe concat export."""
    from microdrama.editing.config import EditingConfig
    from microdrama.editing.variants import run_cropped_export

    run_cropped_export(
        runner,
        edl=plan.source_edl,
        config=EditingConfig(max_export_duration_ms=PREVIEW_MAX_MS),
        names=source_names,
        output=output,
    )


__all__ = [
    "CreativeSource",
    "PosterPlan",
    "PreviewPlan",
    "SafeZone",
    "platform_poster_frame",
    "run_poster_export",
    "run_preview_export",
]
