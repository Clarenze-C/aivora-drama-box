`phase-E-spec.md` **v0.1 DRAFT** written (546 lines), Goldfish→Codex ready. Key decisions:

1. **Reuse, not fork:** V3 edit code in `S/editing_v3/`, but the deterministic seam (`S/editing/{edl,export,ffmpeg,captions}.py`) and its tables (`edit_manifests`, `caption_tracks`) are the one persistence — only 2 migrations (`E-1` store, `E-2` `edit` lane); recap/CTA are embedded EDL clips, zh-CN rides the free-text locale column.
2. **Native audio end to end:** clip-audio sources replace TTS line assets; room tone only as gap fill; utterance-aligned TH cue windows shared by all locales; transitions finally render (xfade/afade, both exporters).
3. **Loudness:** deterministic measured-gain (never single-pass loudnorm), `LoudnessReportV3` per artifact, −14 LUFS ±1/−1 dBTP as a typed readiness blocker.
4. **Recap binds to the predecessor's effective Gate-2 approval** (source-asset cut, ≤10 s, `recap_pending` two-leg splice); **CTA is template-deterministic from the calendar revision** (≤5 s, never promises an unapproved extension).
5. **The edit gate is readiness, not a gate:** typed blockers feed F's Gate 2; Revise routes through A's amendment path rebuilding only noted units; the PF-10 rebuild contract (predecessor→recap, calendar→CTA, sources→assembly) is pinned for F8.
6. **E's only paid work:** SFX gap fills on C's qualified route (`step_07`); no LLM calls anywhere in E.

Open questions (§16): O-E1 §12.2 burned-frame sampling (rec: allowlist, as hardening), O-E2 zh tag (`zh-CN`), O-E3 alignment source (D word timings **UNVERIFIED**), O-E4 C library manifest shape, O-E5 `MusicCue`/`SfxAsset` home, O-E6 no tracks for hooks/variants.

File: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-E-spec.md`
