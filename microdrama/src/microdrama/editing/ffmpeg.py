"""Argument-safe FFmpeg/FFprobe invocation (T015).

Every invocation is an explicit argument list run with ``shell=False`` — never a
string, never shell interpolation — and every input/output path must live inside the
call's own temporary working directory: source bytes (and the resolved caption font)
are copied out of the object store / font directory into the workdir first, so
FFmpeg only ever touches tmp paths. Script text never reaches an argument at all;
caption content travels inside an SRT file written to the workdir.

Outputs are byte-stable where FFmpeg allows it: single-threaded encoders, bitexact
flags and stripped metadata make two runs of the same inputs produce identical bytes
on one machine (verified by test). The known exceptions are documented in
evidence/T015.md: muxer timestamps are only bit-stable for the same FFmpeg build,
and multi-threaded or hardware encoders would not be bit-stable at all.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from microdrama.contracts.errors import SchemaInvalid, ServiceUnavailable
from microdrama.contracts.media import MediaInfo

# Tokens that look like filesystem paths inside an argv element (filter graphs embed
# them after '='). Filter arithmetic fragments like "(ow-iw)/2" and rational fps
# values like 24/1 are not paths: a path's first segment must start with a letter.
_PATH_TOKEN = re.compile(r"[^\s,:;'\"()\[\]=]+")
_FRACTION = re.compile(r"^\d+(?:\.\d+)?/\d+(?:\.\d+)?$")
_PATH_FIRST_SEGMENT = re.compile(r"^/[A-Za-z]")


class FFmpegToolError(ServiceUnavailable):
    """ffmpeg/ffprobe is missing, timed out or failed; stderr is kept for diagnosis."""


def _tool(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise FFmpegToolError(f"{name} not found on PATH")
    return found


def _enforce_tmp_only(args: Sequence[str], workdir: Path) -> None:
    """Refuse any path-like argument that escapes the workdir (tmp-paths-only rule)."""
    root = workdir.resolve()
    for arg in args:
        if "/" not in arg:
            continue
        for token in _PATH_TOKEN.findall(arg):
            if "/" not in token or _FRACTION.fullmatch(token):
                continue
            if not _PATH_FIRST_SEGMENT.match(token):
                continue  # filter arithmetic like (ow-iw)/2, not a path
            candidate = Path(token)
            if not candidate.is_absolute():
                continue  # relative filter values (e.g. font names), not paths
            resolved = candidate.resolve()
            if resolved != root and root not in resolved.parents:
                raise SchemaInvalid(
                    "ffmpeg/ffprobe may only touch paths inside the temporary workdir",
                    path=str(resolved),
                    workdir=str(root),
                )


class FFmpegRunner:
    """Runs ffmpeg/ffprobe with explicit argv lists, bounded timeouts, tmp paths only."""

    def __init__(self, *, workdir: Path, timeout_ms: int) -> None:
        if timeout_ms < 1_000:
            raise SchemaInvalid("ffmpeg timeout must be at least one second")
        self._workdir = workdir
        self._timeout_s = timeout_ms / 1000
        self.invocations: list[tuple[str, ...]] = []

    @property
    def workdir(self) -> Path:
        return self._workdir

    def _run(
        self, name: str, args: Sequence[str], *, check: bool = True
    ) -> subprocess.CompletedProcess:
        if name == "ffmpeg":
            prefix = ["-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
        else:  # ffprobe has no -nostdin/-loglevel/-y options
            prefix = ["-hide_banner"]
        argv = [_tool(name), *prefix, *args]
        _enforce_tmp_only(argv[1:], self._workdir)
        self.invocations.append(tuple(argv))
        try:
            proc = subprocess.run(  # noqa: S603 - argv list, no shell
                argv,
                check=False,
                capture_output=True,
                timeout=self._timeout_s,
                cwd=self._workdir,
            )
        except subprocess.TimeoutExpired as exc:
            raise FFmpegToolError(f"{name} timed out after {self._timeout_s:.0f}s") from exc
        if check and proc.returncode != 0:
            raise FFmpegToolError(
                f"{name} failed: {proc.stderr.decode('utf-8', 'replace').strip()[:2000]}",
                returncode=proc.returncode,
            )
        return proc

    # --- probing -------------------------------------------------------------------------

    def probe(self, path: Path) -> MediaInfo:
        """Facts measured from the file (ffprobe), never from what was requested."""
        proc = self._run(
            "ffprobe",
            [
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
        )
        data: dict = json.loads(proc.stdout)
        streams = [s for s in data.get("streams", []) if isinstance(s, dict)]
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        if video is None and audio is None:
            raise FFmpegToolError("probe found no audio or video stream", path=str(path))
        fmt = data.get("format") or {}
        duration_raw = fmt.get("duration") if isinstance(fmt, dict) else None
        if duration_raw is None:
            durations = [float(s["duration"]) for s in streams if "duration" in s]
            if not durations:
                raise FFmpegToolError("probe found no duration", path=str(path))
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

    def decodes_cleanly(self, path: Path) -> bool:
        """True only if ffmpeg decodes the whole file with no error output."""
        proc = self._run("ffmpeg", ["-v", "error", "-i", str(path), "-f", "null", "-"], check=False)
        return proc.returncode == 0 and not proc.stderr.strip()

    # --- exporting -----------------------------------------------------------------------

    def export(self, args: Sequence[str], *, output: Path) -> subprocess.CompletedProcess:
        """One deterministic ffmpeg export: bitexact flags, single thread, output last."""
        if not output.is_absolute() or self._workdir.resolve() not in output.resolve().parents:
            raise SchemaInvalid("export output must live inside the workdir", output=str(output))
        full = [
            "-loglevel",
            "error",
            *args,
            "-map_metadata",
            "-1",
            "-fflags",
            "+bitexact",
            "-flags:v",
            "+bitexact",
            "-flags:a",
            "+bitexact",
            "-threads",
            "1",
            str(output),
        ]
        return self._run("ffmpeg", full)


def stage_bytes(runner: FFmpegRunner, *, name: str, data: bytes) -> Path:
    """Copy source bytes from the object store into the tmp workdir; return the path."""
    target = runner.workdir / name
    target.write_bytes(data)
    return target


def stage_file(runner: FFmpegRunner, *, name: str, source: Path) -> Path:
    """Copy a resolved file (e.g. the caption font) into the tmp workdir."""
    target = runner.workdir / name
    target.write_bytes(source.read_bytes())
    return target


__all__ = [
    "FFmpegRunner",
    "FFmpegToolError",
    "stage_bytes",
    "stage_file",
]
