"""Byte-level verification of generated reference media (no subprocess, no network).

Anchors and dialogue audio must stand on their own bytes: a provider's ``executed``/
SUCCEEDED state never reaches these functions. PNG anchors are checked structurally;
WAV dialogue is parsed for its RIFF chunk layout and its duration is *measured* from
the actual byte rate and data-chunk size — the number the script's
``actual_duration_ms`` is filled with (SPEC §7: use actual audio timing).
"""

from __future__ import annotations

import struct

from microdrama.contracts.enums import AssetKind
from microdrama.contracts.errors import ProviderError
from microdrama.contracts.media import MediaInfo

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def verify_png_bytes(data: bytes) -> None:
    """Typed refusal unless the bytes are a structurally whole PNG with an IHDR/IEND."""
    if len(data) < 8 + 25 or not data.startswith(_PNG_MAGIC):
        raise ProviderError("anchor output is not a PNG file", size_bytes=len(data))
    if data[12:16] != b"IHDR":
        raise ProviderError("anchor PNG has no IHDR chunk")
    end = data.rfind(b"IEND")
    if end == -1 or end + 8 > len(data):
        raise ProviderError("anchor PNG is missing its IEND chunk (truncated)")


def _chunk(data: bytes, kind: bytes) -> bytes | None:
    """Walk RIFF chunks; None when absent. Raises on a layout that outruns the bytes."""
    if len(data) < 12 or data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ProviderError("voice output is not a RIFF/WAVE file", size_bytes=len(data))
    declared = struct.unpack_from("<I", data, 4)[0]
    if len(data) < 8 + declared:
        raise ProviderError(
            "voice output is truncated: the RIFF container does not hold together",
            size_bytes=len(data),
        )
    position = 12
    while position + 8 <= len(data):
        size = struct.unpack_from("<I", data, position + 4)[0]
        body = position + 8
        if body + size > len(data):
            raise ProviderError("voice output has a chunk that outruns the file")
        if data[position : position + 4] == kind:
            return data[body : body + size]
        position = body + size + (size & 1)  # chunks are word-aligned
    return None


def wav_media_info(data: bytes) -> MediaInfo:
    """Measured facts of a PCM WAV: duration from byte rate and data size, never estimated."""
    fmt = _chunk(data, b"fmt ")
    payload = _chunk(data, b"data")
    if fmt is None or len(fmt) < 16 or payload is None:
        raise ProviderError("voice output lacks a usable fmt/data chunk pair")
    channels, sample_rate, byte_rate = struct.unpack_from("<HII", fmt, 2)
    if byte_rate <= 0:
        raise ProviderError("voice output reports a zero byte rate")
    duration_ms = round(len(payload) * 1000 / byte_rate)
    if duration_ms <= 0:
        raise ProviderError("voice output measures to a non-positive duration")
    return MediaInfo(
        duration_ms=duration_ms,
        has_video=False,
        has_audio=True,
        sample_rate_hz=sample_rate,
        channels=channels,
        audio_codec="pcm_s16le",
    )


def verify_generated(data: bytes, *, kind: AssetKind) -> MediaInfo | None:
    """Verify one fetched provider output by its bytes; returns measured media info."""
    if kind is AssetKind.IMAGE:
        verify_png_bytes(data)
        return None
    if kind is AssetKind.AUDIO:
        return wav_media_info(data)
    raise ProviderError("unsupported reference output media kind", kind=kind.value)


__all__ = ["verify_generated", "verify_png_bytes", "wav_media_info"]
