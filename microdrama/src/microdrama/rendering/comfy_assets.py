"""Fetch, verify and durably register ComfyUI outputs (T013).

Completeness is proven from the bytes themselves — never from an ``executed`` progress
event or the mere existence of a history row: the container structure must be whole
(RIFF size honesty for WAV, moov/mdat bounds for MP4), ffprobe must read streams from
the actual file, and the SHA-256 checksum is recorded with the asset and re-verified in
durable storage. ffmpeg/ffprobe are only ever invoked with argument arrays over local
temporary paths.

Registration is idempotent under recovery: the asset id is derived from the render
attempt, the object key is fixed, and the store is write-once, so a crash between the
fetch and the register simply repeats both with the same result.
"""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any
from uuid import UUID, uuid5

from microdrama.contracts.cost import RenderRequest
from microdrama.contracts.enums import AssetKind, AssetState, Provenance
from microdrama.contracts.errors import Conflict, ProviderError, ServiceUnavailable
from microdrama.contracts.hashing import sha256_hex
from microdrama.contracts.infra import ObjectStore
from microdrama.contracts.media import AssetDescriptor, MediaInfo
from microdrama.contracts.providers import ComfyClient, ComfyOutputFile
from microdrama.persistence.assets import register_asset, verify_persisted
from microdrama.persistence.db import Tx
from microdrama.rendering.leases import RENDERING_NAMESPACE

MEDIA_KIND_TO_ASSET: Mapping[str, AssetKind] = MappingProxyType(
    {"video": AssetKind.VIDEO, "audio": AssetKind.AUDIO, "image": AssetKind.IMAGE}
)

MEDIA_TYPES: Mapping[str, str] = MappingProxyType(
    {"video": "video/mp4", "audio": "audio/wav", "image": "image/png"}
)


# --- container completeness (pure byte checks) ---------------------------------------------


def _riff_complete(data: bytes) -> bool:
    """A RIFF/WAVE file is complete when its declared sizes fit the actual bytes."""
    if len(data) < 12 or data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        return False
    declared = struct.unpack_from("<I", data, 4)[0]
    return len(data) >= 8 + declared


def _mp4_complete(data: bytes) -> bool:
    """An MP4 is complete when every atom fits the file and moov and mdat are present."""
    if len(data) < 8:
        return False
    position = 0
    kinds: set[bytes] = set()
    while position + 8 <= len(data):
        size = int.from_bytes(data[position : position + 4], "big")
        kind = data[position + 4 : position + 8]
        if size == 0:  # "to end of file" atom
            size = len(data) - position
        if size < 8 or position + size > len(data):
            return False
        kinds.add(kind)
        position += size
    return b"moov" in kinds and b"mdat" in kinds


def verify_complete_bytes(data: bytes, *, media_kind: str) -> None:
    """Typed refusal when fetched output bytes are not a complete media container.

    Sampler progress or an ``executed`` event never reaches this function: only fetched
    file bytes do, and they must stand on their own.
    """
    if media_kind not in MEDIA_TYPES:
        raise ProviderError(
            "server produced an output media kind this pipeline cannot verify",
            media_kind=media_kind,
        )
    if not data:
        raise ProviderError("server returned an empty output file", media_kind=media_kind)
    if media_kind == "video":
        whole = _mp4_complete(data)
    elif media_kind == "audio":
        whole = _riff_complete(data)
    else:
        whole = True  # images: presence plus the probe below
    if not whole:
        raise ProviderError(
            "output file is truncated/incomplete: the container does not hold together",
            media_kind=media_kind,
            size_bytes=len(data),
        )


# --- probing (ffprobe through argument arrays) ----------------------------------------------


def _tool(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise ServiceUnavailable(f"{name} not found on PATH; cannot verify output media")
    return found


def probe_media(data: bytes, *, suffix: str) -> MediaInfo:
    """Facts measured from the actual bytes (ffprobe), never from what was requested."""
    with tempfile.TemporaryDirectory(prefix="comfy-verify-") as tmp:
        path = Path(tmp) / f"output{suffix}"
        path.write_bytes(data)
        cmd = [
            _tool("ffprobe"),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
        proc = subprocess.run(cmd, check=False, capture_output=True)  # noqa: S603 - argv list
        if proc.returncode != 0:
            raise ProviderError(
                "output does not probe as complete media",
                detail=proc.stderr.decode("utf-8", "replace")[:500],
            )
        payload: dict[str, Any] = json.loads(proc.stdout)
    return _media_info(payload)


def _media_info(payload: dict[str, Any]) -> MediaInfo:
    streams = [s for s in payload.get("streams", []) if isinstance(s, dict)]
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None and audio is None:
        raise ProviderError("no audio or video stream in the output")
    fmt = payload.get("format") or {}
    duration_raw = fmt.get("duration") if isinstance(fmt, dict) else None
    if duration_raw is None:
        durations = [float(s["duration"]) for s in streams if "duration" in s]
        if not durations:
            raise ProviderError("no duration reported for the output")
        duration_raw = max(durations)
    fps_num = fps_den = None
    if video is not None and video.get("r_frame_rate") not in (None, "0/0"):
        num, den = str(video["r_frame_rate"]).split("/")
        fps_num, fps_den = int(num), int(den)
    return MediaInfo(
        duration_ms=round(float(duration_raw) * 1000),
        has_video=video is not None,
        has_audio=audio is not None,
        width=video.get("width") if video else None,
        height=video.get("height") if video else None,
        fps_num=fps_num,
        fps_den=fps_den,
        video_codec=video.get("codec_name") if video else None,
        audio_codec=audio.get("codec_name") if audio else None,
        sample_rate_hz=(int(audio["sample_rate"]) if audio and "sample_rate" in audio else None),
        channels=audio.get("channels") if audio else None,
    )


# --- fetch and durable registration ----------------------------------------------------------


def output_suffix(output: ComfyOutputFile) -> str:
    suffix = Path(output.filename).suffix
    return suffix if suffix.startswith(".") else ".bin"


def asset_id_for(render_id: UUID, node_id: str) -> UUID:
    """Deterministic asset id: recovery re-registers the same asset, never a twin."""
    return uuid5(RENDERING_NAMESPACE, f"render-asset:{render_id}:{node_id}")


def object_key_for(request: RenderRequest, output: ComfyOutputFile) -> str:
    return (
        f"renders/{request.episode_id}/{request.shot_id}/a{request.attempt_number}/"
        f"{output.node_id}{output_suffix(output)}"
    )


@dataclass(frozen=True)
class PreparedOutput:
    """One fetched, verified and probed output, ready to persist (no DB work yet)."""

    output: ComfyOutputFile
    data: bytes
    media: MediaInfo
    checksum: str


def prepare_output(client: ComfyClient, output: ComfyOutputFile) -> PreparedOutput:
    """Fetch and verify one output outside any transaction.

    Typed failures (``NotFound`` fetch, incomplete container, probe failure) mean the
    provider did not hand over complete media, whatever the progress events said.
    """
    data = client.fetch_output(output)
    verify_complete_bytes(data, media_kind=output.media_kind)
    media = probe_media(data, suffix=output_suffix(output))
    return PreparedOutput(output=output, data=data, media=media, checksum=sha256_hex(data))


def persist_output(
    tx: Tx,
    store: ObjectStore,
    prepared: PreparedOutput,
    *,
    request: RenderRequest,
    request_hash: str,
    provenance: Provenance,
    now: datetime,
) -> AssetDescriptor:
    """Store and register one prepared output; idempotent under recovery.

    The asset id and object key are derived from the attempt, so a replay of the same
    completed job re-puts identical bytes (write-once store) and re-reads the same asset
    row instead of creating a second one. A different file under the same identity is a
    ``Conflict``, never a silent overwrite.
    """
    output = prepared.output
    kind = MEDIA_KIND_TO_ASSET.get(output.media_kind)
    if kind is None:
        raise ProviderError(
            "server produced an output media kind this pipeline cannot register",
            media_kind=output.media_kind,
        )
    asset_id = asset_id_for(request.render_id, output.node_id)
    existing = tx.fetchone("SELECT descriptor FROM assets WHERE id = %s", (asset_id,))
    if existing is not None:
        if existing["descriptor"]["sha256"] != prepared.checksum:
            raise Conflict(
                "this render attempt already registered a different file for the same output node",
                asset_id=str(asset_id),
                node_id=output.node_id,
            )
        return AssetDescriptor.model_validate(existing["descriptor"])
    key = object_key_for(request, output)
    stored = store.put_bytes(key, prepared.data, media_type=MEDIA_TYPES[output.media_kind])
    descriptor = AssetDescriptor(
        asset_id=asset_id,
        asset_kind=kind,
        object_key=stored.key,
        sha256=prepared.checksum,
        size_bytes=len(prepared.data),
        media_type=MEDIA_TYPES[output.media_kind],
        media=prepared.media,
        state=AssetState.PROVISIONAL,
        provenance=provenance,
        episode_id=request.episode_id,
        season_id=None,
        version=1,
        lineage=list(request.reference_asset_ids),
        license_refs=[],
        created_at=now,
    )
    register_asset(tx, descriptor, generation_key=request_hash)
    if not verify_persisted(tx, store, asset_id, now=now):
        raise Conflict(
            "stored object does not match its checksum after registration",
            asset_id=str(asset_id),
        )
    return descriptor


def fetch_output_bytes(client: ComfyClient, output: ComfyOutputFile) -> bytes:
    """Fetch one output; typed ``NotFound`` from the provider propagates unchanged."""
    return client.fetch_output(output)


__all__ = [
    "MEDIA_KIND_TO_ASSET",
    "MEDIA_TYPES",
    "PreparedOutput",
    "asset_id_for",
    "fetch_output_bytes",
    "object_key_for",
    "output_suffix",
    "persist_output",
    "prepare_output",
    "probe_media",
    "verify_complete_bytes",
]
