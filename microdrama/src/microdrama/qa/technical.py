"""Technical QA detectors over the actual media (T017).

Every fact here is measured from the media file itself through argument-safe
ffmpeg/ffprobe: decode, streams, duration, audio presence, silence runs, peak level,
black frames, frozen frames, embedded caption extraction and caption bounds. T015's
``FFmpegRunner`` is reused by import for probe/decode/extraction (tmp paths only,
explicit argv, no shell); the black/freeze/silence/peak filters report through
info-level stderr, so this module runs them with the house analysis pattern — the
same explicit-argv, tmp-path, bounded-timeout invocation T007 established — and keeps
its own detectors' thresholds and outcomes in this lane.

Nothing in this module reads the script: expected values arrive as arguments and
observed values come out of the media. A media file that cannot be probed or decoded
produces a BLOCKED decode finding and typed UNAVAILABLE coverage for everything that
never ran — never a green claim.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from microdrama.contracts.enums import (
    AssetKind,
    CheckFamily,
    CoverageStatus,
    EvidenceSource,
    Provenance,
    QAOutcome,
    RepairTarget,
    Severity,
)
from microdrama.contracts.errors import SchemaInvalid
from microdrama.contracts.media import AssetDescriptor, CaptionCue, MediaInfo
from microdrama.contracts.qa import CoverageWindow, QAFinding
from microdrama.contracts.season import Script
from microdrama.editing.ffmpeg import FFmpegRunner, FFmpegToolError
from microdrama.qa.config import QAConfig
from microdrama.qa.coverage import partition_coverage
from microdrama.qa.models import build_finding

_NUM = r"(\d+(?:\.\d+)?)"
_BLACK = re.compile(rf"black_start:{_NUM}\s+black_end:{_NUM}")
_FREEZE_START = re.compile(rf"freeze_start:\s*{_NUM}")
_FREEZE_END = re.compile(rf"freeze_end:\s*{_NUM}")
_SILENCE_START = re.compile(rf"silence_start:\s*{_NUM}")
_SILENCE_END = re.compile(rf"silence_end:\s*{_NUM}(?:\s\|.*)?")
_MAX_VOLUME = re.compile(rf"max_volume:\s*(-?{_NUM})\s*dB")
_SRT_TIME = re.compile(r"^(\d+):(\d+):(\d+)[,.](\d+)$")

EVIDENCE_NOTE = "local ffmpeg measurement of the actual media (not a quality claim)"


class MediaAnalysisError(RuntimeError):
    """A detector invocation failed outright (missing tool, timeout). Typed upstream."""


def _tool(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise MediaAnalysisError(f"{name} not found on PATH")
    return found


def _assert_inside(path: Path, workdir: Path) -> None:
    resolved = path.resolve()
    root = workdir.resolve()
    if resolved != root and root not in resolved.parents:
        raise SchemaInvalid(
            "qa analysis may only touch paths inside the temporary workdir",
            path=str(resolved),
            workdir=str(root),
        )


def _analyze(workdir: Path, path: Path, args: Sequence[str], *, timeout_s: float) -> str:
    """Run one ffmpeg analysis filter and return its (info-level) stderr for parsing."""
    _assert_inside(path, workdir)
    argv = [
        _tool("ffmpeg"),
        "-hide_banner",
        "-nostdin",
        "-nostats",
        "-i",
        str(path),
        *args,
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(  # noqa: S603 - explicit argv list, no shell
            argv, check=False, capture_output=True, timeout=timeout_s
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaAnalysisError(f"ffmpeg analysis timed out after {timeout_s:.0f}s") from exc
    return proc.stderr.decode("utf-8", "replace")


# --- measured facts ----------------------------------------------------------------------


@dataclass(frozen=True)
class MediaFacts:
    """What the actual media file measured as (probe + full decode)."""

    duration_ms: int
    media: MediaInfo | None
    decode_ok: bool
    probe_error: str | None


def gather_facts(runner: FFmpegRunner, staged: Path, descriptor: AssetDescriptor) -> MediaFacts:
    """Probe and fully decode the staged media; a probe failure is data, not a crash."""
    declared = descriptor.media.duration_ms if descriptor.media else 0
    try:
        media = runner.probe(staged)
    except FFmpegToolError as exc:
        detail = str(exc).splitlines()[0][:300]
        return MediaFacts(duration_ms=declared, media=None, decode_ok=False, probe_error=detail)
    decode_ok = runner.decodes_cleanly(staged)
    return MediaFacts(
        duration_ms=media.duration_ms, media=media, decode_ok=decode_ok, probe_error=None
    )


def detect_black_windows(workdir: Path, path: Path, config: QAConfig) -> list[tuple[float, float]]:
    text = _analyze(
        workdir,
        path,
        [
            "-vf",
            f"blackdetect=d={config.black_min_ms / 1000:.3f}:pix_th={config.black_pix_th:.2f}",
            "-an",
        ],
        timeout_s=config.ffmpeg_timeout_ms / 1000,
    )
    return [(float(a), float(b)) for a, b in _BLACK.findall(text)]


def detect_frozen_windows(workdir: Path, path: Path, config: QAConfig) -> list[tuple[float, float]]:
    text = _analyze(
        workdir,
        path,
        [
            "-vf",
            f"freezedetect=n={config.freeze_noise_db}dB:d={config.freeze_min_ms / 1000:.3f}",
            "-an",
        ],
        timeout_s=config.ffmpeg_timeout_ms / 1000,
    )
    starts = [float(s) for s in _FREEZE_START.findall(text)]
    ends = [float(e) for e in _FREEZE_END.findall(text)]
    return list(zip(starts, ends, strict=False))


def detect_silence_windows(
    workdir: Path, path: Path, config: QAConfig
) -> list[tuple[float, float]]:
    text = _analyze(
        workdir,
        path,
        [
            "-af",
            f"silencedetect=noise={config.silence_noise_db}dB:d={config.silence_min_ms / 1000:.3f}",
            "-vn",
        ],
        timeout_s=config.ffmpeg_timeout_ms / 1000,
    )
    starts = [float(s) for s in _SILENCE_START.findall(text)]
    ends = [float(e) for e in _SILENCE_END.findall(text)]
    return list(zip(starts, ends, strict=False))


def measure_peak_db(workdir: Path, path: Path, config: QAConfig) -> float | None:
    """Maximum sample level in dB (volumedetect), or None when it cannot be measured."""
    text = _analyze(
        workdir,
        path,
        ["-af", "volumedetect", "-vn"],
        timeout_s=config.ffmpeg_timeout_ms / 1000,
    )
    match = _MAX_VOLUME.search(text)
    return float(match.group(1)) if match else None


# --- embedded captions -------------------------------------------------------------------


def extract_embedded_captions(runner: FFmpegRunner, staged: Path) -> list[CaptionCue] | None:
    """Pull the embedded subtitle track out of the actual media. None = no track."""
    output = runner.workdir / "embedded-captions.srt"
    try:
        runner.export(["-i", str(staged), "-map", "0:s:0", "-c:s", "srt"], output=output)
    except FFmpegToolError:
        return None
    if not output.exists() or not output.read_bytes().strip():
        return None
    return parse_srt(output.read_bytes())


def _srt_ms(stamp: str) -> int | None:
    match = _SRT_TIME.fullmatch(stamp.strip())
    if match is None:
        return None
    hours, minutes, seconds, millis = (int(part) for part in match.groups())
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def parse_srt(data: bytes) -> list[CaptionCue]:
    """Deterministic SubRip parse; malformed blocks are skipped, never invented."""
    cues: list[CaptionCue] = []
    blocks = data.decode("utf-8", "replace").replace("\r\n", "\n").split("\n\n")
    for block in blocks:
        lines = [line for line in block.split("\n") if line.strip()]
        timing_index = next((i for i, line in enumerate(lines) if " --> " in line), None)
        if timing_index is None or timing_index + 1 >= len(lines):
            continue
        start_raw, end_raw = lines[timing_index].split("-->", 1)
        start_ms, end_ms = _srt_ms(start_raw), _srt_ms(end_raw)
        text = "\n".join(lines[timing_index + 1 :]).strip()
        if start_ms is None or end_ms is None or not text or end_ms <= start_ms:
            continue
        cues.append(
            CaptionCue(
                cue_id=f"embedded-{len(cues) + 1}",
                start_ms=start_ms,
                end_ms=end_ms,
                text=text[:500],
            )
        )
    return cues


# --- finding builders --------------------------------------------------------------------


def technical_findings(
    *,
    run_key: str,
    episode_id: UUID,
    descriptor: AssetDescriptor,
    facts: MediaFacts,
    config: QAConfig,
    black: list[tuple[float, float]] | None,
    frozen: list[tuple[float, float]] | None,
    silence: list[tuple[float, float]] | None,
    peak_db: float | None,
) -> list[QAFinding]:
    """Findings for decode/streams/audio-presence/duration/silence/peaks/temporal.

    Detector inputs are None when the detector could not run (no audio stream, media
    did not decode): those become typed UNAVAILABLE/UNKNOWN findings, never PASS.
    """
    asset_id = descriptor.asset_id
    sha = descriptor.sha256[:16]
    out: list[QAFinding] = []

    def add(**kwargs: object) -> None:
        out.append(
            build_finding(
                run_key=run_key,
                episode_id=episode_id,
                asset_id=asset_id,
                evidence_source=EvidenceSource.MEASURED_BENCHMARK,
                evidence_ref=f"ffmpeg:{kwargs['check_id']}:{sha}",
                evidence_note=EVIDENCE_NOTE,
                provenance=Provenance.DERIVED_LOCAL,
                **kwargs,  # type: ignore[arg-type]
            )
        )

    duration = facts.duration_ms
    if facts.media is None:
        add(
            check_id="technical.decode",
            family=CheckFamily.TECHNICAL,
            start_ms=0,
            end_ms=duration,
            severity=Severity.CRITICAL,
            outcome=QAOutcome.BLOCKED,
            coverage=CoverageStatus.CHECKED,
            expected="media probes and decodes cleanly",
            observed=facts.probe_error,
        )
        for check_id, family, note in (
            ("technical.streams", CheckFamily.TECHNICAL, "probe failed; streams not inspected"),
            (
                "technical.audio_present",
                CheckFamily.TECHNICAL,
                "probe failed; audio presence not inspected",
            ),
            ("technical.duration", CheckFamily.TECHNICAL, "probe failed; duration not measured"),
            ("audio.silence", CheckFamily.AUDIO, "probe failed; audio not analyzed"),
            ("audio.peaks", CheckFamily.AUDIO, "probe failed; audio not analyzed"),
            ("temporal.black_frames", CheckFamily.TEMPORAL, "probe failed; scan not run"),
            ("temporal.frozen_frames", CheckFamily.TEMPORAL, "probe failed; scan not run"),
            (
                "temporal.lip_sync",
                CheckFamily.TEMPORAL,
                "no lip-sync detector configured; dense local review required",
            ),
        ):
            add(
                check_id=check_id,
                family=family,
                start_ms=0,
                end_ms=duration,
                severity=Severity.MAJOR,
                outcome=QAOutcome.UNKNOWN,
                coverage=CoverageStatus.UNAVAILABLE,
                expected=None,
                observed=note,
            )
        return out

    # Decode / streams / duration / audio presence.
    add(
        check_id="technical.decode",
        family=CheckFamily.TECHNICAL,
        start_ms=0,
        end_ms=duration,
        severity=Severity.INFO,
        outcome=QAOutcome.PASS if facts.decode_ok else QAOutcome.BLOCKED,
        coverage=CoverageStatus.CHECKED,
        expected="decodes end-to-end with no error output",
        observed="clean decode" if facts.decode_ok else "decode errors in error output",
    )
    media = facts.media
    streams_ok = media.has_video and media.has_audio
    add(
        check_id="technical.streams",
        family=CheckFamily.TECHNICAL,
        start_ms=0,
        end_ms=duration,
        severity=Severity.INFO if streams_ok else Severity.MAJOR,
        outcome=QAOutcome.PASS if streams_ok else QAOutcome.REPAIRABLE,
        coverage=CoverageStatus.CHECKED,
        expected="video and audio streams present",
        observed=f"video={media.has_video} audio={media.has_audio} "
        f"{media.width}x{media.height}@{media.fps_num}/{media.fps_den} "
        f"{media.sample_rate_hz}Hz {media.channels}ch",
        repair_targets=None if streams_ok else [RepairTarget.EDIT],
    )
    declared = descriptor.media.duration_ms if descriptor.media else duration
    drift = abs(duration - declared)
    duration_ok = drift <= config.duration_tolerance_ms
    add(
        check_id="technical.duration",
        family=CheckFamily.TECHNICAL,
        start_ms=0,
        end_ms=duration,
        severity=Severity.INFO if duration_ok else Severity.MAJOR,
        outcome=QAOutcome.PASS if duration_ok else QAOutcome.REPAIRABLE,
        coverage=CoverageStatus.CHECKED,
        expected=f"probed duration within {config.duration_tolerance_ms} ms of "
        f"registered {declared} ms",
        observed=f"probed {duration} ms (drift {drift} ms)",
        repair_targets=None if duration_ok else [RepairTarget.EDIT],
    )
    if media.has_audio:
        add(
            check_id="technical.audio_present",
            family=CheckFamily.TECHNICAL,
            start_ms=0,
            end_ms=duration,
            severity=Severity.INFO,
            outcome=QAOutcome.PASS,
            coverage=CoverageStatus.CHECKED,
            expected="audio stream present",
            observed=f"{media.audio_codec} stream present",
        )
    else:
        add(
            check_id="technical.audio_present",
            family=CheckFamily.TECHNICAL,
            start_ms=0,
            end_ms=duration,
            severity=Severity.CRITICAL,
            outcome=QAOutcome.REPAIRABLE,
            coverage=CoverageStatus.CHECKED,
            expected="audio stream present",
            observed="no audio stream in the exported media",
            repair_targets=[RepairTarget.AUDIO_MIX],
        )

    # Audio-level checks (silence runs, peaks).
    if not media.has_audio:
        for check_id in ("audio.silence", "audio.peaks"):
            add(
                check_id=check_id,
                family=CheckFamily.AUDIO,
                start_ms=0,
                end_ms=duration,
                severity=Severity.MAJOR,
                outcome=QAOutcome.UNKNOWN,
                coverage=CoverageStatus.UNAVAILABLE,
                expected=None,
                observed="no audio stream; audio not analyzable",
            )
    else:
        if silence is not None:
            over = [
                (start, end)
                for start, end in silence
                if (end - start) * 1000 >= config.max_silence_ms
            ]
            observed = "; ".join(f"{start:.2f}-{end:.2f}s" for start, end in silence[:8])
            add(
                check_id="audio.silence",
                family=CheckFamily.AUDIO,
                start_ms=0,
                end_ms=duration,
                severity=Severity.INFO if not over else Severity.MAJOR,
                outcome=QAOutcome.PASS if not over else QAOutcome.REPAIRABLE,
                coverage=CoverageStatus.CHECKED,
                expected=f"no contiguous silence >= {config.max_silence_ms} ms",
                observed=observed or f"no silence >= {config.silence_min_ms} ms detected",
                repair_targets=None if not over else [RepairTarget.AUDIO_MIX],
            )
        else:
            add(
                check_id="audio.silence",
                family=CheckFamily.AUDIO,
                start_ms=0,
                end_ms=duration,
                severity=Severity.MAJOR,
                outcome=QAOutcome.UNKNOWN,
                coverage=CoverageStatus.UNAVAILABLE,
                expected=None,
                observed="silence detector did not run",
            )
        if peak_db is not None:
            clipped = peak_db > config.peak_max_db
            add(
                check_id="audio.peaks",
                family=CheckFamily.AUDIO,
                start_ms=0,
                end_ms=duration,
                severity=Severity.MAJOR if clipped else Severity.INFO,
                outcome=QAOutcome.REPAIRABLE if clipped else QAOutcome.PASS,
                coverage=CoverageStatus.CHECKED,
                expected=f"max sample level <= {config.peak_max_db} dB",
                observed=f"max_volume {peak_db:.1f} dB",
                repair_targets=[RepairTarget.AUDIO_MIX] if clipped else None,
            )
        else:
            add(
                check_id="audio.peaks",
                family=CheckFamily.AUDIO,
                start_ms=0,
                end_ms=duration,
                severity=Severity.MAJOR,
                outcome=QAOutcome.UNKNOWN,
                coverage=CoverageStatus.UNAVAILABLE,
                expected=None,
                observed="peak level could not be measured",
            )

    # Temporal detectors (a detected defect is one timecoded finding per range).
    _temporal_family_findings(
        add, "temporal.black_frames", black, duration, config.black_min_ms, "black frames"
    )
    _temporal_family_findings(
        add, "temporal.frozen_frames", frozen, duration, config.freeze_min_ms, "frozen frames"
    )
    add(
        check_id="temporal.lip_sync",
        family=CheckFamily.TEMPORAL,
        start_ms=0,
        end_ms=duration,
        severity=Severity.MAJOR,
        outcome=QAOutcome.UNKNOWN,
        coverage=CoverageStatus.UNAVAILABLE,
        expected=None,
        observed="no lip-sync detector configured; dense local review required "
        "(a sparse scan cannot certify lip-sync)",
    )
    return out


def _temporal_family_findings(
    add: Callable[..., None],
    check_id: str,
    ranges: list[tuple[float, float]] | None,
    duration: int,
    min_ms: int,
    label: str,
) -> None:
    if ranges is None:
        return  # the detector never ran; the probe-failure branch already reported it
    for start, end in ranges:
        add(
            check_id=check_id,
            family=CheckFamily.TEMPORAL,
            start_ms=int(start * 1000),
            end_ms=max(int(start * 1000) + 1, min(duration, int(end * 1000))),
            severity=Severity.MAJOR,
            outcome=QAOutcome.REPAIRABLE,
            coverage=CoverageStatus.CHECKED,
            expected=f"no unintended {label}",
            observed=f"{label} {start:.2f}-{end:.2f}s",
            repair_targets=[RepairTarget.EDIT],
        )
    if not ranges:
        add(
            check_id=check_id,
            family=CheckFamily.TEMPORAL,
            start_ms=0,
            end_ms=duration,
            severity=Severity.INFO,
            outcome=QAOutcome.PASS,
            coverage=CoverageStatus.CHECKED,
            expected=f"no {label} interval >= {min_ms} ms",
            observed="none detected",
        )


def caption_findings(
    *,
    run_key: str,
    episode_id: UUID,
    asset_id: UUID,
    asset_sha256: str,
    cues: list[CaptionCue],
    duration_ms: int,
    script: Script,
    config: QAConfig,
    source_label: str,
) -> list[QAFinding]:
    """Bounds/order/critical-term/release-claim checks over observed caption cues.

    The cues are what the media actually carries (embedded track extracted through
    ffmpeg, or the CURRENT caption track from the editing lane). Critical terms come
    from the script — the expected side — and are only ever compared against observed
    cue text: a correct script can never make this check green by itself.
    """
    from microdrama.qa.audio import align_best

    out: list[QAFinding] = []

    def add(**kwargs: object) -> None:
        out.append(
            build_finding(
                run_key=run_key,
                episode_id=episode_id,
                asset_id=asset_id,
                evidence_source=EvidenceSource.MEASURED_BENCHMARK,
                evidence_ref=f"captions:{asset_sha256[:16]}",
                evidence_note=f"caption text observed in the actual media ({source_label})",
                provenance=Provenance.DERIVED_LOCAL,
                **kwargs,  # type: ignore[arg-type]
            )
        )

    ordered = all(a.end_ms <= b.start_ms for a, b in zip(cues, cues[1:], strict=False))
    add(
        check_id="caption.cue_bounds",
        family=CheckFamily.CAPTION,
        start_ms=0,
        end_ms=duration_ms,
        severity=Severity.INFO if ordered else Severity.MAJOR,
        outcome=QAOutcome.PASS if ordered else QAOutcome.REPAIRABLE,
        coverage=CoverageStatus.CHECKED,
        expected="cues ordered and non-overlapping",
        observed=f"{len(cues)} cues, ordered={ordered}",
        repair_targets=None if ordered else [RepairTarget.CAPTION],
    )
    violations = [cue for cue in cues if cue.end_ms > duration_ms or cue.start_ms >= duration_ms]
    for cue in violations:
        add(
            check_id="caption.cue_within_media",
            family=CheckFamily.CAPTION,
            start_ms=cue.start_ms,
            end_ms=cue.end_ms,
            severity=Severity.MAJOR,
            outcome=QAOutcome.REPAIRABLE,
            coverage=CoverageStatus.CHECKED,
            expected=f"cue inside [0, {duration_ms} ms]",
            observed=f"cue '{cue.text[:40]}' spans {cue.start_ms}-{cue.end_ms} ms",
            repair_targets=[RepairTarget.CAPTION],
        )
    if cues and not violations:
        add(
            check_id="caption.cue_within_media",
            family=CheckFamily.CAPTION,
            start_ms=0,
            end_ms=duration_ms,
            severity=Severity.INFO,
            outcome=QAOutcome.PASS,
            coverage=CoverageStatus.CHECKED,
            expected=f"every cue inside [0, {duration_ms} ms]",
            observed=f"{len(cues)} cues within the media",
        )
    lines = [line for scene in script.scenes for line in scene.lines]
    for cue in cues:
        # Release-claim scan runs over EVERY cue: an unaligned cue (a CTA card that
        # matches no script line) is exactly where an illicit claim can hide.
        for phrase in config.unreleased_claim_phrases:
            if phrase and phrase in cue.text:
                add(
                    check_id="caption.release_claim",
                    family=CheckFamily.CAPTION,
                    start_ms=cue.start_ms,
                    end_ms=cue.end_ms,
                    severity=Severity.CRITICAL,
                    outcome=QAOutcome.REPAIRABLE,
                    coverage=CoverageStatus.CHECKED,
                    expected="no claim about an unreleased episode",
                    observed=f"cue claims '{phrase}'",
                    repair_targets=[RepairTarget.CAPTION],
                )
        line, ratio = align_best(lines, cue.text, key=lambda line: line.text_th)
        if line is None or ratio < config.align_min_ratio:
            continue
        for term in line.critical_terms:
            present = _norm(term.value_th) in _norm(cue.text)
            expected = (
                term.value_th if term.value_en is None else f"{term.value_th} ({term.value_en})"
            )
            add(
                check_id="caption.critical_term_match",
                family=CheckFamily.CAPTION,
                start_ms=cue.start_ms,
                end_ms=cue.end_ms,
                severity=Severity.INFO if present else Severity.CRITICAL,
                outcome=QAOutcome.PASS if present else QAOutcome.REPAIRABLE,
                coverage=CoverageStatus.CHECKED,
                expected=expected,
                observed=term.value_th if present else cue.text,
                repair_targets=None if present else [RepairTarget.CAPTION],
            )
    claims = [finding for finding in out if finding.check_id == "caption.release_claim"]
    if config.unreleased_claim_phrases and cues and not claims:
        add(
            check_id="caption.release_claim",
            family=CheckFamily.CAPTION,
            start_ms=0,
            end_ms=duration_ms,
            severity=Severity.INFO,
            outcome=QAOutcome.PASS,
            coverage=CoverageStatus.CHECKED,
            expected=(
                f"none of the {len(config.unreleased_claim_phrases)} configured "
                "unreleased claims appear"
            ),
            observed=f"{len(cues)} cues scanned",
        )
    elif not config.unreleased_claim_phrases:
        add(
            check_id="caption.release_claim",
            family=CheckFamily.CAPTION,
            start_ms=0,
            end_ms=duration_ms,
            severity=Severity.MAJOR,
            outcome=QAOutcome.UNKNOWN,
            coverage=CoverageStatus.UNAVAILABLE,
            expected=None,
            observed="no unreleased-claim phrases configured; release claims not checked",
        )
    return out


def technical_coverage(
    asset_id: UUID, facts: MediaFacts, descriptor: AssetDescriptor
) -> dict[CheckFamily, list[CoverageWindow]]:
    """Coverage windows for the technical/temporal/audio families from real facts."""
    duration = facts.duration_ms or (descriptor.media.duration_ms if descriptor.media else 0)
    if facts.media is None:
        note = "media does not probe; detectors did not run"
        return {
            family: partition_coverage(
                asset_id, family, duration, (), outside=CoverageStatus.UNAVAILABLE, note=note
            )
            for family in (CheckFamily.TECHNICAL, CheckFamily.AUDIO, CheckFamily.TEMPORAL)
        }
    technical = partition_coverage(asset_id, CheckFamily.TECHNICAL, duration, ((0, duration),))
    audio_ranges = ((0, duration),) if facts.media.has_audio else ()
    audio = partition_coverage(
        asset_id,
        CheckFamily.AUDIO,
        duration,
        audio_ranges,
        outside=CoverageStatus.UNAVAILABLE,
        note="no audio stream",
    )
    temporal = partition_coverage(
        asset_id,
        CheckFamily.TEMPORAL,
        duration,
        ((0, duration),) if facts.media.has_video else (),
        outside=CoverageStatus.UNAVAILABLE,
        note="no video stream",
    )
    return {
        CheckFamily.TECHNICAL: technical,
        CheckFamily.AUDIO: audio,
        CheckFamily.TEMPORAL: temporal,
    }


def ensure_video_asset(descriptor: AssetDescriptor) -> None:
    if descriptor.asset_kind is not AssetKind.VIDEO:
        raise SchemaInvalid(
            "technical QA runs on video assets (the assembled export)",
            asset_kind=descriptor.asset_kind.value,
        )


def _norm(text: str) -> str:
    return "".join(text.split())


__all__ = [
    "EVIDENCE_NOTE",
    "MediaAnalysisError",
    "MediaFacts",
    "caption_findings",
    "detect_black_windows",
    "detect_frozen_windows",
    "detect_silence_windows",
    "ensure_video_asset",
    "extract_embedded_captions",
    "gather_facts",
    "measure_peak_db",
    "parse_srt",
    "technical_coverage",
    "technical_findings",
]
