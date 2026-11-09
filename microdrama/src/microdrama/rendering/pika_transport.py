"""Scoped Pika schema and exact input-byte transport, separate from money JSON."""

from __future__ import annotations

import hashlib
import io
import json
import re
import wave
from typing import Any
from uuid import UUID

from microdrama.contracts.enums import EffectKind
from microdrama.contracts.errors import EffectDenied, NeedsReconciliation, SchemaInvalid
from microdrama.rendering.comfy_transport import ComfyHttpClient

MAX_INPUT_BYTES = 32 * 1024 * 1024
_UI_KEYS = {"tooltip", "description", "display_name", "displayName"}


def _schema_value(value):
    if isinstance(value, dict):
        return {k: _schema_value(v) for k, v in value.items() if k not in _UI_KEYS}
    if isinstance(value, (list, tuple)):
        return [_schema_value(v) for v in value]
    return value


def mapped_schema_sha256(raw: dict[str, Any], classes) -> str:
    """Hash complete mapped definitions and order; unrelated classes/UI text excluded."""
    result = {}
    for name in sorted(classes):
        node = raw.get(name)
        if (
            not isinstance(node, dict)
            or not isinstance(node.get("input"), dict)
            or not isinstance(node.get("output"), list)
        ):
            raise SchemaInvalid("missing or malformed mapped node schema", class_type=name)
        inputs = node["input"]
        if not isinstance(inputs.get("required", {}), dict) or not isinstance(
            inputs.get("optional", {}), dict
        ):
            raise SchemaInvalid("malformed mapped inputs")
        result[name] = {
            "input": _schema_value(inputs),
            "input_order": node.get(
                "input_order", {k: list(v) for k, v in inputs.items() if isinstance(v, dict)}
            ),
            "output": node["output"],
            "output_is_list": node.get("output_is_list", [False] * len(node["output"])),
        }
    try:
        encoded = json.dumps(
            result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    except (TypeError, ValueError) as exc:
        raise SchemaInvalid("runtime schema contains nonfinite or unsupported values") from exc
    return hashlib.sha256(encoded).hexdigest()


def upload_key_for(
    experiment_id: UUID, acquisition_id: UUID, asset_sha256: str, media_kind: str
) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", asset_sha256) or media_kind not in {"image", "audio"}:
        raise SchemaInvalid("unsupported input hash/media kind")
    return f"t031/{experiment_id}/{acquisition_id}/{asset_sha256}.{'png' if media_kind == 'image' else 'wav'}"


def validate_input_bytes(data: bytes, media_kind: str, expected_sha256: str):
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_INPUT_BYTES:
        raise SchemaInvalid("Pika upload bytes exceed bound or are empty")
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise SchemaInvalid("Pika upload source hash differs")
    if media_kind == "image":
        import struct
        import zlib

        try:
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("PNG signature required")
            offset = 8
            kinds = []
            compressed = []
            while offset < len(data):
                size = int.from_bytes(data[offset : offset + 4], "big")
                kind = data[offset + 4 : offset + 8]
                payload = data[offset + 8 : offset + 8 + size]
                crc = data[offset + 8 + size : offset + 12 + size]
                if len(crc) != 4 or int.from_bytes(crc, "big") != zlib.crc32(kind + payload):
                    raise ValueError("PNG chunk checksum differs")
                if kind == b"IHDR":
                    width, height = struct.unpack(">II", payload[:8])
                    if not width or not height or width * height > 32_000_000 or size != 13:
                        raise ValueError("PNG dimensions exceed bound")
                if kind == b"IDAT":
                    compressed.append(payload)
                kinds.append(kind)
                offset += size + 12
            if (
                not kinds
                or kinds[0] != b"IHDR"
                or kinds[-1] != b"IEND"
                or not compressed
                or offset != len(data)
            ):
                raise ValueError("incomplete PNG")
            decoder = zlib.decompressobj()
            decoded = decoder.decompress(b"".join(compressed), 128 * 1024 * 1024 + 1)
            if len(decoded) > 128 * 1024 * 1024 or not decoder.eof:
                raise ValueError("PNG decoded size exceeds bound")
        except Exception as exc:
            raise SchemaInvalid("Pika image input must be valid bounded PNG") from exc
    elif media_kind == "audio":
        try:
            with wave.open(io.BytesIO(data), "rb") as wav:
                if (
                    wav.getnframes() <= 0
                    or wav.getcomptype() != "NONE"
                    or len(wav.readframes(wav.getnframes()))
                    != wav.getnframes() * wav.getnchannels() * wav.getsampwidth()
                ):
                    raise ValueError("nonempty PCM required")
        except Exception as exc:
            raise SchemaInvalid("Pika audio input must be nonempty PCM WAV") from exc
    else:
        raise SchemaInvalid("Pika only supports PNG and WAV inputs")


class PikaHttpClient(ComfyHttpClient):
    """Existing durable scope guards additionally authorize each acquisition upload key."""

    def __init__(self, *args, schema_sha256: str, **kwargs):
        super().__init__(*args, **kwargs)
        if not re.fullmatch(r"[0-9a-f]{64}", schema_sha256):
            raise SchemaInvalid("Pika requires an exact runtime schema pin")
        self._schema_sha256 = schema_sha256

    def attest_schema(self):
        from microdrama.rendering.workflows.templates import PIKA_TEMPLATE

        raw = self.raw_object_info()
        if mapped_schema_sha256(raw, PIKA_TEMPLATE.node_classes) != self._schema_sha256:
            raise SchemaInvalid("actual mapped runtime schema differs before input/dispatch")
        return raw

    def queue_prompt(self, graph, *, client_id):
        self.attest_schema()
        return super().queue_prompt(graph, client_id=client_id)

    def history(self, prompt_id):
        # PreviewVideo reports images plus animated=[true], which is UI metadata.
        from microdrama.contracts.enums import Provenance
        from microdrama.contracts.providers import ComfyHistoryEntry, ComfyOutputFile

        payload = json.loads(
            self._request("GET", f"/history/{prompt_id}", authorization_key=prompt_id)
        )
        entry = payload.get(prompt_id)
        if entry is None:
            return None
        outputs = []
        for item in entry.get("outputs", {}).get("save_video", {}).get("images", []):
            if (
                not isinstance(item, dict)
                or not str(item.get("filename", "")).endswith(".mp4")
                or item.get("type", "output") != "output"
            ):
                raise SchemaInvalid("native SaveVideo returned an invalid MP4 locator")
            outputs.append(
                ComfyOutputFile(
                    node_id="save_video",
                    filename=item["filename"],
                    subfolder=item.get("subfolder", ""),
                    folder_type="output",
                    media_kind="video",
                )
            )
        status = entry.get("status", {})
        return ComfyHistoryEntry(
            prompt_id=prompt_id,
            completed=bool(status.get("completed")),
            status_str=str(status.get("status_str", "unknown")),
            outputs=outputs,
            provenance=Provenance.LIVE_PROVIDER,
        )

    def fetch_output(self, output):
        if (
            output.node_id != "save_video"
            or output.media_kind != "video"
            or not output.filename.endswith(".mp4")
        ):
            raise SchemaInvalid("Pika requires the allowlisted SaveVideo MP4 output")
        data = super().fetch_output(output)
        verify_native_output(data)
        return data

    def raw_object_info(self):
        if self._bound_pod_id is None:
            raise EffectDenied("Pika schema requires an owned pod endpoint")
        value = json.loads(self._request("GET", "/object_info"))
        if not isinstance(value, dict):
            raise SchemaInvalid("raw object_info must be an object")
        return value

    def _input_key(self, upload_key):
        if not re.fullmatch(
            r"t031/[0-9a-f-]{36}/[0-9a-f-]{36}/[0-9a-f]{64}\.(png|wav)", upload_key
        ):
            raise SchemaInvalid("input locator is not a deterministic acquisition key")
        return upload_key.rsplit("/", 1)

    def reconcile_input(self, *, expected_sha256: str, upload_key: str) -> str:
        subfolder, filename = self._input_key(upload_key)
        if self._bound_pod_id is None:
            raise EffectDenied("Pika input readback requires an owned pod")
        data = self._request(
            "GET",
            "/view",
            query={"filename": filename, "subfolder": subfolder, "type": "input"},
            authorization_key=upload_key,
        )
        if len(data) > MAX_INPUT_BYTES or hashlib.sha256(data).hexdigest() != expected_sha256:
            raise NeedsReconciliation("Pika input readback is absent, unverifiable or differs")
        return upload_key

    def upload_input(
        self, data: bytes, media_kind: str, expected_sha256: str, upload_key: str
    ) -> str:
        validate_input_bytes(data, media_kind, expected_sha256)
        subfolder, filename = self._input_key(upload_key)
        suffix = "png" if media_kind == "image" else "wav"
        if not upload_key.endswith(f"/{expected_sha256}.{suffix}"):
            raise SchemaInvalid("Pika key differs from uploaded bytes/media")
        self._settings.require_effect(EffectKind.PAID_REQUEST, what="Pika input upload")
        auth = self._authorization.get()
        if self._endpoint is None or self._bound_pod_id is None or auth is None:
            raise EffectDenied("Pika upload requires owned pod and durable authorization scope")
        self.attest_schema()
        self._request_guard("/upload/image", upload_key, auth)
        boundary = "t031_" + hashlib.sha256(upload_key.encode()).hexdigest()
        parts = []
        for name, value in (("subfolder", subfolder), ("type", "input"), ("overwrite", "false")):
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
            )
        mime = "image/png" if media_kind == "image" else "audio/wav"
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode()
            + data
            + f"\r\n--{boundary}--\r\n".encode()
        )
        headers = self._headers()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        try:
            response = json.loads(
                self._transport.request(
                    "POST", self._endpoint + "/upload/image", headers=headers, body=b"".join(parts)
                )
            )
            if (response.get("name"), response.get("subfolder"), response.get("type")) != (
                filename,
                subfolder,
                "input",
            ):
                raise NeedsReconciliation("Pika upload returned a different locator")
            return self.reconcile_input(expected_sha256=expected_sha256, upload_key=upload_key)
        except NeedsReconciliation:
            raise
        except Exception:
            raise NeedsReconciliation(
                "Pika upload outcome UNKNOWN; reconcile deterministic input before submit"
            ) from None


def verify_native_output(data: bytes):
    """Technical stream evidence only; Thai/voice quality still needs evaluators."""
    import array
    import subprocess
    import tempfile
    from pathlib import Path

    from microdrama.rendering.comfy_assets import probe_media, verify_complete_bytes

    verify_complete_bytes(data, media_kind="video")
    media = probe_media(data, suffix=".mp4")
    if (
        not media.has_video
        or not media.has_audio
        or (media.width, media.height, media.sample_rate_hz, media.channels) != (480, 832, 32000, 2)
        or not 5100 <= media.duration_ms <= 5250
        or (media.fps_num, media.fps_den) != (24, 1)
    ):
        raise SchemaInvalid("Pika output lacks exact native audio/video stream shape")
    with tempfile.TemporaryDirectory(prefix="t031-audio-") as tmp:
        path = Path(tmp) / "output.mp4"
        path.write_bytes(data)
        proc = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(path),
                "-map",
                "0:a:0",
                "-t",
                "6",
                "-f",
                "s16le",
                "-acodec",
                "pcm_s16le",
                "-",
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )  # noqa: S603,S607
    samples = array.array("h")
    samples.frombytes(proc.stdout)
    if proc.returncode or not samples or not any(samples):
        raise SchemaInvalid("Pika native audio is empty, silent or undecodable")
    return media
