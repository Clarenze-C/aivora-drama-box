"""EDL, FFmpeg, mix and captioning (T015).

Public surface:
- ``EditingService`` / ``build_editing_service``: ``assemble_episode`` (deterministic
  EDL from the current script/manifest + measured assets, clean and burned exports,
  actual-audio caption spotting with the no-fake-correction guard, invalidation of
  cues whose line audio was replaced) plus the read surface ``script``/``manifest``/
  ``captions``/``edit_manifest``/``stale_caption_cues`` that T016/T017/T019 consume.
- ``EditingConfig``: bounded knobs; the CPU/storage/transfer budget hook is off by
  default (local FFmpeg exports are free) and plays the full reservation discipline
  the moment a price is configured.
- ``SpeechObserver``: the actual-speech observation seam (fixture truth offline,
  ASR with T017). The wrong-audio guard compares through it and never lets the
  intended line overwrite what was actually spoken.
- T016 owns ``variants*``/``hooks*``/``covers*`` submodules; this wave creates none.

Module-local payloads extend ``ContractModel`` inside ``editing/`` only (promotion
proposal in evidence/T015.md).
"""

from microdrama.editing.captions import (
    MISMATCH_CODE,
    UNAVAILABLE_NOTE,
    SpeechObserver,
    spot_caption_track,
    srt_bytes,
    stale_cues,
    track_body_hash,
)
from microdrama.editing.config import THAI_FONT_CANDIDATES, EditingConfig
from microdrama.editing.edl import (
    EDITING_NAMESPACE,
    LineSource,
    ShotSource,
    build_edl,
    edl_semantic_hash,
    shot_prompt_digest,
)
from microdrama.editing.ffmpeg import FFmpegRunner, FFmpegToolError
from microdrama.editing.fonts import resolve_caption_font
from microdrama.editing.models import (
    AssemblyOutcome,
    AssemblyStatus,
    EditingFinding,
    FontResolution,
    ObservedSpeech,
    TechnicalCheck,
)
from microdrama.editing.service import (
    TRANSFER_OPERATION,
    EditingService,
    build_editing_service,
)

__all__ = [
    "AssemblyOutcome",
    "AssemblyStatus",
    "EDITING_NAMESPACE",
    "EditingConfig",
    "EditingFinding",
    "EditingService",
    "FFmpegRunner",
    "FFmpegToolError",
    "FontResolution",
    "LineSource",
    "MISMATCH_CODE",
    "ObservedSpeech",
    "ShotSource",
    "SpeechObserver",
    "THAI_FONT_CANDIDATES",
    "TRANSFER_OPERATION",
    "TechnicalCheck",
    "UNAVAILABLE_NOTE",
    "build_edl",
    "build_editing_service",
    "edl_semantic_hash",
    "resolve_caption_font",
    "shot_prompt_digest",
    "srt_bytes",
    "spot_caption_track",
    "stale_cues",
    "track_body_hash",
]
