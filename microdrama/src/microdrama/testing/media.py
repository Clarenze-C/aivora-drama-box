"""Original synthetic media, seeded defects and fixture truth for offline tests (T007).

Everything here is generated at test time from ``lavfi`` sources and pure Python. No
copyrighted footage, no real customer media, no committed binaries. Speech is stood in
for by tone bursts: a ``FixtureTruth`` declares what the fixture *contains* (spoken lines,
visible identities, caption/on-screen text, video defects) and the fakes report that
truth, never the intended script.

ffmpeg/ffprobe are only ever invoked with argument lists (``shell=False``) and local paths.
Fixtures are labelled ``ORIGINAL_FIXTURE`` and ``synthetic``; their truth is not a
measured quality claim.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import struct
import subprocess
import tempfile
import wave
import zlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from microdrama.contracts.enums import CaptionTimingSource, Provenance
from microdrama.contracts.examples import script
from microdrama.contracts.hashing import canonical_hash, file_sha256
from microdrama.contracts.media import CaptionCue, CaptionTrack, MediaInfo

MAX_CLIP_MS = 5_000
MAX_CLIP_SIDE = 640
SUITE_DURATION_MS = 5_000
_FPS = 24
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class MediaToolError(RuntimeError):
    """ffmpeg/ffprobe is missing or refused the request; stderr is kept for diagnosis."""


class MediaProbeError(MediaToolError):
    """ffprobe could not read the file as media (missing moov atom, not media, ...)."""


# --- tool invocation ---------------------------------------------------------------


def _tool(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise MediaToolError(f"{name} not found on PATH")
    return found


def _sec(ms: int) -> str:
    return f"{ms / 1000:.3f}"


def _run_ffmpeg(args: Sequence[str]) -> None:
    cmd = [_tool("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *args]
    try:
        subprocess.run(cmd, check=True, capture_output=True)  # noqa: S603 - argv list, no shell
    except subprocess.CalledProcessError as exc:
        raise MediaToolError(exc.stderr.decode("utf-8", "replace").strip()) from exc


def _analyze(path: Path, filter_args: Sequence[str]) -> str:
    """Run an ffmpeg analysis filter and return its (info-level) stderr for parsing."""
    cmd = [
        _tool("ffmpeg"),
        "-hide_banner",
        "-nostdin",
        "-nostats",
        "-i",
        str(path),
        *filter_args,
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, check=False, capture_output=True)  # noqa: S603
    return proc.stderr.decode("utf-8", "replace")


def decodes_cleanly(path: Path) -> bool:
    """True only if ffmpeg decodes the whole file with no error output."""
    cmd = [_tool("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error", "-i", str(path)]
    proc = subprocess.run([*cmd, "-f", "null", "-"], check=False, capture_output=True)  # noqa: S603
    return proc.returncode == 0 and not proc.stderr.strip()


# --- synthetic clips ----------------------------------------------------------------


def _between(ranges: Iterable[tuple[int, int]]) -> str:
    return "+".join(f"between(t,{_sec(a)},{_sec(b)})" for a, b in ranges)


def _validate_ranges(name: str, ranges: Sequence[tuple[int, int]], duration_ms: int) -> None:
    for start, end in ranges:
        if not 0 <= start < end <= duration_ms:
            raise ValueError(
                f"{name} range {(start, end)} must satisfy 0 <= start < end <= duration"
            )


def make_clip(
    path: Path | str,
    *,
    duration_ms: int,
    width: int = 360,
    height: int = 640,
    fps: int = _FPS,
    with_audio: bool = True,
    tone_hz: int = 440,
    black_ranges: Sequence[tuple[int, int]] = (),
    freeze_ranges: Sequence[tuple[int, int]] = (),
    silence_ranges: Sequence[tuple[int, int]] = (),
    comment: str | None = None,
) -> Path:
    """Write a tiny H.264/AAC MP4 with real black, frozen and silent segments.

    Black: ``drawbox`` with a timeline ``enable``. Freeze: ``freezeframes`` replaces each
    frame of the range with a frame just before it. Silence: ``volume=0`` on the tone.
    All three are detectable by ffmpeg's ``blackdetect``/``freezedetect``/``silencedetect``.
    ``comment`` is stored as a container tag (used to give each declared fixture its own
    bytes). Output bytes are reproducible (bitexact muxing, no other metadata).
    """
    if not 0 < duration_ms <= MAX_CLIP_MS:
        raise ValueError(f"duration_ms must be in (0, {MAX_CLIP_MS}]")
    if not (16 <= width <= MAX_CLIP_SIDE and 16 <= height <= MAX_CLIP_SIDE):
        raise ValueError(f"frame size must be within 16..{MAX_CLIP_SIDE} px per side")
    if width % 2 or height % 2 or not 1 <= fps <= 60:
        raise ValueError("width/height must be even and fps in 1..60")
    for name, ranges in (
        ("black", black_ranges),
        ("freeze", freeze_ranges),
        ("silence", silence_ranges),
    ):
        _validate_ranges(name, ranges, duration_ms)

    total_frames = round(duration_ms * fps / 1000)
    args: list[str] = [
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size={width}x{height}:rate={fps}:duration={_sec(duration_ms)}",
    ]
    graph: list[str] = []
    label = "[0:v]"
    if black_ranges:
        graph.append(
            f"{label}drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:"
            f"enable='{_between(black_ranges)}'[vblack]"
        )
        label = "[vblack]"
    for index, (start, end) in enumerate(freeze_ranges):
        first = round(start * fps / 1000)
        last = round(end * fps / 1000) - 1
        replace = first - 1 if first >= 1 else last + 1
        if not 0 <= replace < total_frames or first > last:
            raise ValueError(f"freeze range {(start, end)} cannot be expressed at {fps} fps")
        graph.append(f"{label}split=2[fsrc{index}][frep{index}]")
        graph.append(
            f"[fsrc{index}][frep{index}]freezeframes=first={first}:last={last}:"
            f"replace={replace}[vfz{index}]"
        )
        label = f"[vfz{index}]"
    graph.append(f"{label}null[vout]")

    if with_audio:
        args += [
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={tone_hz}:sample_rate=48000:duration={_sec(duration_ms)}",
        ]
        if silence_ranges:
            graph.append(f"[1:a]volume=0:enable='{_between(silence_ranges)}'[aout]")
        else:
            graph.append("[1:a]anull[aout]")

    out_args = ["-filter_complex", ";".join(graph), "-map", "[vout]"]
    if with_audio:
        out_args += ["-map", "[aout]", "-c:a", "aac", "-b:a", "64k"]
    else:
        out_args += ["-an"]
    out_args += [
        "-map_metadata", "-1",
        *(["-metadata", f"comment={comment}"] if comment else []),
        "-fflags", "+bitexact",
        "-flags:v", "+bitexact",
        "-flags:a", "+bitexact",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "35",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-t", _sec(duration_ms),
    ]  # fmt: skip
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg([*args, *out_args, str(target)])
    return target


def render_clip_bytes(duration_ms: int, *, with_audio: bool = True) -> bytes:
    """Bytes of a small deterministic clip, rendered into a temporary directory."""
    with tempfile.TemporaryDirectory(prefix="fixture-clip-") as tmp:
        return make_clip(
            Path(tmp) / "clip.mp4", duration_ms=duration_ms, with_audio=with_audio
        ).read_bytes()


# --- probing and detectors ------------------------------------------------------------


def _ffprobe_json(path: Path) -> dict[str, object]:
    cmd = [
        _tool("ffprobe"),
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]  # fmt: skip
    proc = subprocess.run(cmd, check=False, capture_output=True)  # noqa: S603
    if proc.returncode != 0:
        raise MediaProbeError(proc.stderr.decode("utf-8", "replace").strip() or "ffprobe failed")
    data: dict[str, object] = json.loads(proc.stdout)
    return data


def probe(path: Path | str) -> MediaInfo:
    """Facts measured from the file itself (ffprobe), never from what was requested."""
    data = _ffprobe_json(Path(path))
    streams = [s for s in data.get("streams", []) if isinstance(s, dict)]  # type: ignore[union-attr]
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None and audio is None:
        raise MediaProbeError("no audio or video stream")
    fmt = data.get("format") or {}
    duration_raw = fmt.get("duration") if isinstance(fmt, dict) else None  # type: ignore[union-attr]
    if duration_raw is None:
        durations = [float(s["duration"]) for s in streams if "duration" in s]
        if not durations:
            raise MediaProbeError("no duration reported")
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
        sample_rate_hz=int(audio["sample_rate"]) if audio and "sample_rate" in audio else None,
        channels=audio.get("channels") if audio else None,
    )


_NUM = r"(\d+(?:\.\d+)?)"
_BLACK = re.compile(rf"black_start:{_NUM}\s+black_end:{_NUM}")
_FREEZE_START = re.compile(rf"freeze_start:\s*{_NUM}")
_FREEZE_END = re.compile(rf"freeze_end:\s*{_NUM}")
_SILENCE_START = re.compile(rf"silence_start:\s*{_NUM}")
_SILENCE_END = re.compile(rf"silence_end:\s*{_NUM}")


def detect_black(path: Path | str, *, min_ms: int = 200) -> list[tuple[float, float]]:
    """(start, end) seconds of near-black intervals, reported by ffmpeg ``blackdetect``."""
    text = _analyze(Path(path), ["-vf", f"blackdetect=d={min_ms / 1000:.3f}:pix_th=0.10", "-an"])
    return [(float(a), float(b)) for a, b in _BLACK.findall(text)]


def detect_frozen(path: Path | str, *, min_ms: int = 300) -> list[tuple[float, float]]:
    """(start, end) seconds of frozen video, reported by ffmpeg ``freezedetect``."""
    # -40dB: the strict -60dB threshold misses the first frames after x264 quantisation.
    text = _analyze(Path(path), ["-vf", f"freezedetect=n=-40dB:d={min_ms / 1000:.3f}", "-an"])
    starts = [float(s) for s in _FREEZE_START.findall(text)]
    ends = [float(e) for e in _FREEZE_END.findall(text)]
    return list(zip(starts, ends, strict=False))


def detect_silence(path: Path | str, *, min_ms: int = 200) -> list[tuple[float, float]]:
    """(start, end) seconds of silence, reported by ffmpeg ``silencedetect``."""
    text = _analyze(Path(path), ["-af", f"silencedetect=noise=-50dB:d={min_ms / 1000:.3f}", "-vn"])
    starts = [float(s) for s in _SILENCE_START.findall(text)]
    ends = [float(e) for e in _SILENCE_END.findall(text)]
    return list(zip(starts, ends, strict=False))


# --- audio, image and damaged-output helpers ----------------------------------------------


def _tone_frames(duration_ms: int, tone_hz: int, sample_rate: int) -> bytes:
    count = duration_ms * sample_rate // 1000
    amplitude = 0.25 * 32767
    samples = [
        round(amplitude * math.sin(2 * math.pi * tone_hz * i / sample_rate)) for i in range(count)
    ]
    return struct.pack(f"<{count}h", *samples)


def make_wav_bytes(duration_ms: int, tone_hz: int = 440, *, sample_rate: int = 16_000) -> bytes:
    """Mono 16-bit PCM WAV written with the standard ``wave`` module (deterministic)."""
    if duration_ms <= 0:
        raise ValueError("duration_ms must be positive")
    buf = BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(_tone_frames(duration_ms, tone_hz, sample_rate))
    return buf.getvalue()


def make_wav(path: Path | str, duration_ms: int, tone_hz: int = 440) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(make_wav_bytes(duration_ms, tone_hz))
    return target


def make_png_bytes(width: int, height: int) -> bytes:
    """Small RGB PNG with a deterministic gradient, built with zlib and struct."""
    if not (1 <= width <= 256 and 1 <= height <= 256):
        raise ValueError("PNG fixtures are limited to 256 px per side")
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type: none
        for x in range(width):
            raw += bytes((x * 255 // max(width - 1, 1), y * 255 // max(height - 1, 1), 128))

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def truncate_file(path: Path | str, keep_ratio: float) -> Path:
    """Cut a file in place to its first ``keep_ratio`` of bytes (partial/corrupt output)."""
    if not 0 < keep_ratio < 1:
        raise ValueError("keep_ratio must be between 0 and 1 (exclusive)")
    target = Path(path)
    data = target.read_bytes()
    target.write_bytes(data[: int(len(data) * keep_ratio)])
    return target


def _srt_time(ms: int) -> str:
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def mux_mov_text(src: Path, cues: Sequence[CaptionCue], dst: Path) -> Path:
    """Copy ``src`` into ``dst`` with an embedded ``mov_text`` (Thai) caption track."""
    with tempfile.TemporaryDirectory(prefix="fixture-srt-") as tmp:
        srt = Path(tmp) / "cues.srt"
        blocks = [
            f"{i}\n{_srt_time(c.start_ms)} --> {_srt_time(c.end_ms)}\n{c.text}\n"
            for i, c in enumerate(cues, start=1)
        ]
        srt.write_text("\n".join(blocks), encoding="utf-8")
        _run_ffmpeg(
            [
                "-i", str(src),
                "-i", str(srt),
                "-map", "0",
                "-map", "1",
                "-c", "copy",
                "-c:s", "mov_text",
                "-metadata:s:s:0", "language=tha",
                "-fflags", "+bitexact",
                "-flags:v", "+bitexact",
                "-flags:a", "+bitexact",
                str(dst),
            ]
        )  # fmt: skip
    return dst


# --- fixture truth (declares what a fixture actually contains) ------------------------------


class _Span(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> _Span:
        if self.end_ms <= self.start_ms:
            raise ValueError("span end must be after start")
        return self


class SpokenTruth(_Span):
    text_th: str = Field(min_length=1, max_length=2000)
    speaker_id: str = Field(min_length=1, max_length=120)


class IdentityTruth(_Span):
    character_id: str = Field(min_length=1, max_length=120)


class TextTruth(_Span):
    """Caption (embedded subtitle) or on-screen text. Text may run past the media end."""

    kind: Literal["caption", "on_screen"]
    text: str = Field(min_length=1, max_length=500)


class VideoDefectTruth(_Span):
    kind: Literal["black", "frozen"]


class FixtureTruth(BaseModel):
    """What a fixture actually contains. Synthetic and unmeasured; never a quality claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fixture_id: str = Field(min_length=1, max_length=120)
    duration_ms: int = Field(gt=0)
    has_audio: bool
    has_video: bool
    spoken: tuple[SpokenTruth, ...] = ()
    identities: tuple[IdentityTruth, ...] = ()
    text_items: tuple[TextTruth, ...] = ()
    video_defects: tuple[VideoDefectTruth, ...] = ()
    covered_ranges_ms: tuple[tuple[int, int], ...]
    provenance: Literal[Provenance.ORIGINAL_FIXTURE] = Provenance.ORIGINAL_FIXTURE
    synthetic: Literal[True] = True
    measured_quality: Literal[False] = False

    @model_validator(mode="after")
    def _consistent(self) -> FixtureTruth:
        previous_end = -1
        for start, end in self.covered_ranges_ms:
            if not (0 <= start < end <= self.duration_ms) or start < previous_end:
                raise ValueError("covered ranges must be ordered, disjoint and inside the media")
            previous_end = end
        for span in (*self.spoken, *self.identities, *self.video_defects):
            if span.end_ms > self.duration_ms:
                raise ValueError("speech, identity and video defects must lie inside the media")
        return self


class FixtureTruthRegistry:
    """Maps a file's sha256 to its declared truth. Re-registering with other truth is an error."""

    def __init__(self) -> None:
        self._by_sha: dict[str, FixtureTruth] = {}

    def register(self, sha256: str, truth: FixtureTruth) -> None:
        if not _SHA_RE.fullmatch(sha256):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        existing = self._by_sha.get(sha256)
        if existing is not None and existing != truth:
            raise ValueError(f"conflicting truth already registered for {sha256[:12]}")
        self._by_sha[sha256] = truth

    def get(self, sha256: str) -> FixtureTruth | None:
        return self._by_sha.get(sha256)

    def __contains__(self, sha256: object) -> bool:
        return sha256 in self._by_sha

    def __len__(self) -> int:
        return len(self._by_sha)


# --- seeded defect suite -------------------------------------------------------------------


@dataclass(frozen=True)
class SeededDefect:
    """One generated fixture. ``expected_check_ids`` are the checks it is designed to trip.

    ``complete`` is False for partial outputs; ``media_kind`` is video, audio or caption.
    """

    kind: str
    path: Path
    sha256: str
    media_kind: Literal["video", "audio", "caption"]
    expected_check_ids: tuple[str, ...]
    complete: bool
    truth: FixtureTruth


_LINES = {line.line_id: line for scene in script().scenes for line in scene.lines}
_WINDOWS = {"s1-l1": (100, 2_100), "s1-l2": (2_300, 3_700), "s2-l1": (3_900, 4_900)}
_CAST_NS = uuid5(NAMESPACE_URL, "https://microdrama.invalid/fixtures/suite")


@dataclass(frozen=True)
class _Plan:
    kind: str
    spoken: tuple[SpokenTruth, ...]
    identities: tuple[IdentityTruth, ...]
    captions: tuple[TextTruth, ...]
    expected: tuple[str, ...]
    has_audio: bool = True
    black: tuple[tuple[int, int], ...] = ()
    freeze: tuple[tuple[int, int], ...] = ()
    video_defects: tuple[VideoDefectTruth, ...] = ()
    complete: bool = True
    covered: tuple[tuple[int, int], ...] | None = None


def _default_spoken(*, drop: set[str] = frozenset(), text: dict[str, str] | None = None,
                    speaker: dict[str, str] | None = None) -> tuple[SpokenTruth, ...]:  # fmt: skip
    text = text or {}
    speaker = speaker or {}
    out = []
    for line_id, (start, end) in _WINDOWS.items():
        if line_id in drop:
            continue
        line = _LINES[line_id]
        out.append(
            SpokenTruth(
                start_ms=start,
                end_ms=end,
                text_th=text.get(line_id, line.text_th),
                speaker_id=speaker.get(line_id, line.speaker_character_id),
            )
        )
    return tuple(out)


def _default_identities(*, override: dict[str, str] | None = None) -> tuple[IdentityTruth, ...]:
    override = override or {}
    return tuple(
        IdentityTruth(
            start_ms=start,
            end_ms=end,
            character_id=override.get(line_id, _LINES[line_id].speaker_character_id),
        )
        for line_id, (start, end) in _WINDOWS.items()
    )


def _default_captions(*, text: dict[str, str] | None = None) -> tuple[TextTruth, ...]:
    text = text or {}
    return tuple(
        TextTruth(
            start_ms=start,
            end_ms=end,
            kind="caption",
            text=text.get(line_id, _LINES[line_id].text_th),
        )
        for line_id, (start, end) in _WINDOWS.items()
    )


def _complement(windows: Sequence[tuple[int, int]], duration_ms: int) -> list[tuple[int, int]]:
    gaps: list[tuple[int, int]] = []
    cursor = 0
    for start, end in sorted(windows):
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration_ms:
        gaps.append((cursor, duration_ms))
    return gaps


def _amount_swap(text: str) -> str:
    return text.replace("ห้าหมื่นบาท", "ห้าพันบาท")


def _suite_plans() -> list[_Plan]:
    clean_spoken = _default_spoken()
    clean_ids = _default_identities()
    clean_caps = _default_captions()
    cta = _default_captions()[:2] + (
        TextTruth(start_ms=3_900, end_ms=5_000, kind="caption", text="EP2 ดูได้แล้วตอนนี้"),
    )
    return [
        _Plan("clean", clean_spoken, clean_ids, clean_caps, expected=()),
        _Plan(
            "wrong_amount",
            _default_spoken(text={"s1-l1": _amount_swap(_LINES["s1-l1"].text_th)}),
            clean_ids,
            clean_caps,
            expected=("asr.critical_term_match",),
        ),
        _Plan(
            "wrong_speaker",
            _default_spoken(speaker={"s1-l2": "fon"}),
            clean_ids,
            clean_caps,
            expected=("asr.speaker_match",),
        ),
        _Plan(
            "identity_swap",
            clean_spoken,
            _default_identities(override={"s1-l1": "lek"}),
            clean_caps,
            expected=("visual_identity.match",),
        ),
        _Plan(
            "missing_audio",
            (),
            clean_ids,
            clean_caps,
            expected=("technical.audio_present",),
            has_audio=False,
        ),
        _Plan(
            "silence_gap",
            _default_spoken(drop={"s1-l2"}),
            clean_ids,
            clean_caps,
            expected=("asr.line_present",),
        ),
        _Plan(
            "black_frames",
            clean_spoken,
            clean_ids,
            clean_caps,
            expected=("temporal.black_frames",),
            black=((2_500, 3_300),),
            video_defects=(VideoDefectTruth(start_ms=2_500, end_ms=3_300, kind="black"),),
        ),
        _Plan(
            "frozen_frames",
            clean_spoken,
            clean_ids,
            clean_caps,
            expected=("temporal.frozen_frames",),
            freeze=((1_000, 1_800),),
            video_defects=(VideoDefectTruth(start_ms=1_000, end_ms=1_800, kind="frozen"),),
        ),
        _Plan(
            "bad_caption",
            clean_spoken,
            clean_ids,
            _default_captions(text={"s1-l1": _amount_swap(_LINES["s1-l1"].text_th)}),
            expected=("caption.critical_term_match",),
        ),
        _Plan(
            "wrong_cta",
            clean_spoken,
            clean_ids,
            cta,
            expected=("caption.release_claim",),
        ),
        _Plan(
            "truncated_output",
            clean_spoken,
            clean_ids,
            clean_caps,
            expected=("technical.decode",),
            complete=False,
            covered=(),
        ),
    ]


def _build_av(root: Path, plan: _Plan) -> tuple[Path, FixtureTruth]:
    covered = plan.covered if plan.covered is not None else ((0, SUITE_DURATION_MS),)
    truth = FixtureTruth(
        fixture_id=plan.kind,
        duration_ms=SUITE_DURATION_MS,
        has_audio=plan.has_audio,
        has_video=True,
        spoken=plan.spoken,
        identities=plan.identities,
        text_items=plan.captions,
        video_defects=plan.video_defects,
        covered_ranges_ms=covered,
    )
    # Speaker and identity are not rendered into the tone carrier, so the file embeds a digest
    # of its declared truth. Each declared fixture therefore has its own bytes and sha256.
    tag = f"microdrama-fixture:{plan.kind}:{canonical_hash(truth)[:32]}"
    windows = [(s.start_ms, s.end_ms) for s in plan.spoken]
    base = root / f"{plan.kind}.base.mp4"
    make_clip(
        base,
        duration_ms=SUITE_DURATION_MS,
        with_audio=plan.has_audio,
        black_ranges=plan.black,
        freeze_ranges=plan.freeze,
        silence_ranges=_complement(windows, SUITE_DURATION_MS) if plan.has_audio else (),
        comment=tag,
    )
    final = root / f"{plan.kind}.mp4"
    if plan.captions:
        cues = [
            CaptionCue(cue_id=f"c{i}", start_ms=c.start_ms, end_ms=c.end_ms, text=c.text)
            for i, c in enumerate(plan.captions, start=1)
        ]
        mux_mov_text(base, cues, final)
        base.unlink()
    else:
        base.replace(final)
    if not plan.complete:
        truncate_file(final, 0.6)
    return final, truth


def _build_caption_track(root: Path) -> tuple[Path, FixtureTruth]:
    """Caption sidecar whose last cue ends after the 5 s media (contract model, not a video)."""
    track = CaptionTrack(
        track_id=uuid5(_CAST_NS, "caption-out-of-bounds"),
        episode_id=uuid5(_CAST_NS, "episode-1"),
        version=1,
        locale="th-TH",
        timing_source=CaptionTimingSource.ESTIMATED_FROM_SCRIPT,
        cues=[
            CaptionCue(
                cue_id="c1",
                start_ms=0,
                end_ms=2_000,
                text=_LINES["s1-l1"].text_th,
            ),
            CaptionCue(
                cue_id="c2",
                start_ms=4_500,
                end_ms=6_200,
                text=_LINES["s2-l1"].text_th,
            ),
        ],
    )
    path = root / "caption_out_of_bounds.captions.json"
    path.write_text(
        json.dumps(track.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    truth = FixtureTruth(
        fixture_id="caption_out_of_bounds",
        duration_ms=SUITE_DURATION_MS,
        has_audio=False,
        has_video=False,
        text_items=(
            TextTruth(start_ms=0, end_ms=2_000, kind="caption", text=_LINES["s1-l1"].text_th),
            TextTruth(start_ms=4_500, end_ms=6_200, kind="caption", text=_LINES["s2-l1"].text_th),
        ),
        covered_ranges_ms=((0, SUITE_DURATION_MS),),
    )
    return path, truth


def seeded_defect_suite(
    tmp_dir: Path | str, registry: FixtureTruthRegistry
) -> dict[str, SeededDefect]:
    """Generate every named defect into ``tmp_dir`` and register each file's truth.

    Names: clean, wrong_amount, wrong_speaker, identity_swap, missing_audio, silence_gap,
    black_frames, frozen_frames, bad_caption, caption_out_of_bounds, wrong_cta,
    truncated_output. The intended script is ``contracts.examples.script()``.
    """
    root = Path(tmp_dir)
    root.mkdir(parents=True, exist_ok=True)
    built: dict[str, SeededDefect] = {}

    def record(kind: str, path: Path, truth: FixtureTruth, media_kind: str,
               expected: tuple[str, ...], complete: bool) -> None:  # fmt: skip
        sha = file_sha256(str(path))
        registry.register(sha, truth)
        built[kind] = SeededDefect(
            kind=kind,
            path=path,
            sha256=sha,
            media_kind=media_kind,  # type: ignore[arg-type]
            expected_check_ids=expected,
            complete=complete,
            truth=truth,
        )

    for plan in _suite_plans():
        path, truth = _build_av(root, plan)
        record(plan.kind, path, truth, "video", plan.expected, plan.complete)

    path, truth = _build_caption_track(root)
    record(
        "caption_out_of_bounds",
        path,
        truth,
        "caption",
        ("caption.cue_within_media",),
        True,
    )
    return built


__all__ = [
    "FixtureTruth",
    "FixtureTruthRegistry",
    "IdentityTruth",
    "MediaProbeError",
    "MediaToolError",
    "SeededDefect",
    "SpokenTruth",
    "TextTruth",
    "VideoDefectTruth",
    "decodes_cleanly",
    "detect_black",
    "detect_frozen",
    "detect_silence",
    "make_clip",
    "make_png_bytes",
    "make_wav",
    "make_wav_bytes",
    "mux_mov_text",
    "probe",
    "render_clip_bytes",
    "seeded_defect_suite",
    "truncate_file",
]
