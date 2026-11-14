# Phase E fact map — today's edit/derivative/caption/loudness code (14 Nov 2026)

Paths: `S/` = `microdrama/src/microdrama/`, `M/` = `microdrama/migrations/`, `X/` = `microdrama/tests/`. All line cites read today on `feat/microdrama-m0-m4` (main checkout). Migrations 0026 (`t031_benchmark_experiments`), 0027 (`a0_llm_gateway`) exist only under `.scratch/a0d-gate/microdrama/migrations/` and are not editing-related.

## 1. Editing/assembly today (T015 lineage)

| Fact | Cite |
|---|---|
| Pipeline jobs: `edit.assemble_episode` ("EDL → FFmpeg master, mix, caption tracks") then `edit.variants_and_hooks` ("Platform variants, covers, three hook candidates from accepted footage") | `S/contracts/jobs.py:112-118`, `:120-126` |
| Handler wiring: `handlers["edit.assemble_episode"] = edit_assemble_episode`; calls `world.editing.assemble_episode(payload.episode_id, shot_assets=shot_assets)` | `S/pipeline/handlers.py:204-222` |
| Entry: `def assemble_episode(self, episode_id, *, shot_assets: Mapping[str, UUID]) -> AssemblyOutcome` — loads script + manifest, builds line/shot sources, builds EDL, checks duration ceiling, replays on same hash, then claims and executes | `S/editing/service.py:582-635` |
| Core assembly: `build_edl(*, episode_id, manifest, script, shot_sources, line_sources, room_asset_id, config, prompt_digest) -> EditDecisionList` — "Deterministically lay the episode's shots, dialogue and room tone on a timeline" | `S/editing/edl.py:101-186` |
| Video: shots in `sequence` order, `length = min(source.duration_ms, shot.target_duration_ms)`, tiling `[0, total]` exactly | `S/editing/edl.py:124-125` |
| Dialogue: `_place_dialogue(shot, script, line_sources, timeline_ms, length, config)` — lines placed sequentially from shot start with `dialogue_lead_in_ms=200`, `inter_line_gap_ms=150` | `S/editing/edl.py:133` + `S/editing/config.py:42-43` |
| Ambience: one `room.main` clip spanning the whole timeline with `gain_millibel=config.room_gain_millibel`; room tone is generated in-process, not from source clips: `render_room_tone` = "Deterministic room-tone WAV (seeded noise)" via `anoisesrc=color=pink:seed={config.room_seed}` | `S/editing/edl.py:136-146`, `S/editing/export.py:137-162`, `S/editing/config.py:37-39` |
| EDL id/hash: `canonical_hash({episode_id, prompt_digest, clips:[[clip_id, source_asset_id, in, out]…], output:[w,h,fps]})`; `purpose=SlotKind.FULL_EPISODE` | `S/editing/edl.py:154-170` |
| Export filter graph: `plan_master` — video trims + scale/pad/fps/format, `concat=n=…:v=1:a=0[vcut]`; dialogue `[i:a]atrim…,adelay=…`; room same; `amix=inputs=N:normalize=0:duration=longest…[aout]` | `S/editing/export.py:51-121` (quote `:113` `amix=inputs={len(audio_labels)}:normalize=0:duration=longest,`) |
| Master encode: `-c:v libx264 -preset veryfast -crf 35 … -c:a aac -b:a 64k` | `S/editing/export.py:165-206` |
| **"Native clip audio" in today's path:** the render clips' own embedded audio is **not** used — `MasterPlan.video_map="[vcut]"` maps video only; all audio comes from per-line dialogue assets + generated room tone. Dialogue audio assets are created by the references step (T011), deterministic id `ref_id_for("line-audio", f"{episode_id}:{line.line_id}:{canonical_hash(line.text_th)[:12]}")`, must exist with measured duration or assembly raises Conflict | `S/editing/export.py:41-48` + `:84-87`; `S/editing/service.py:522-553` (quote `:525` `"line audio has no measured duration; the references step must run before assembly"`) |
| Replay/idempotency: `_replay_outcome(episode_id, edl_hash, line_sha)` returns the stored outcome for an unchanged EDL+audio | `S/editing/service.py:617-621`, `:1339-1395` |
| Persistence: `edit_manifests` table — `edl jsonb`, `edl_hash`, `output_asset_id`, `state CHECK IN ('PLANNED','RENDERED','FAILED','INVALIDATED','SUPERSEDED')`, `UNIQUE (episode_id, purpose, variant_key, version)`, EDL columns immutable trigger | `M/0004_media_and_qa.sql:52-69` |
| Outcome contract `AssemblyOutcome`: `status ASSEMBLED\|REPLAYED`, `clean_asset_id/clean_sha256`, `burned_*`, `caption_track_ids`, `findings`, `checks`, `invalidated_cue_ids`, `settled_micro_usd`, `uncertainty_notes` | `S/editing/models.py:105-124`, `:33-37` |
| FFmpeg seam: `FFmpegRunner` with `probe` (ffprobe→`MediaInfo`), `decodes_cleanly`, `export`; timeout `ffmpeg_timeout_ms=120_000` | `S/editing/ffmpeg.py:70-185`, `S/editing/config.py:56` |
| Burned export: `run_burned_export` re-encodes master with `plan_burn`'s `subtitles=filename=…:fontsdir=.:force_style='…'` (libass, Thai style `Alignment=2,MarginV=40`), `-c:a copy` | `S/editing/export.py:209-234`, `:124-134` |
| Unit tests: `X/unit/editing/test_editing_{edl,export,captions,service,invalidation,fonts,ffmpeg_safety}.py`, `test_hooks_{candidates,pure}.py`, `test_variants_*.py`, `test_covers_derivation.py`, `test_creative_derivatives.py`; contracts `X/contract/editing/test_{editing,variants}_contract.py` | `X/unit/editing/`, `X/contract/editing/` |

## 2. The edit gate (between edit and release)

| Fact | Cite |
|---|---|
| The human gates live in `review/`: "``ReviewService``: owner-scoped Gate 1 (season concept) and Gate 2 (episode final) decisions" | `S/review/__init__.py:1-4` |
| What Gate 2 reviews: `ReleasePackage` — "What Gate 2 reviews. ``package_hash`` covers every immutable field": `media: list[MediaRef]` (asset_id+sha256), `caption_track_ids`, `hook_experiment_id`, `creative_derivatives`, `release_scope`, `management_policy_hash`, `qa: QASummary`, `gate_blockers` | `S/contracts/release.py:265-287` |
| Package validator binds hashes: "release slot references media outside the package", "derivative source hash differs from accepted package media" | `S/contracts/release.py:298-332` |
| Gate-2 enablement: `gate2_blockers(...)` — "Every reason Gate 2 APPROVE is disabled … (empty = enabled)": episode must be `AWAITING_FINAL_REVIEW`, package READY + current, QA findings non-blocking, every packaged asset's stored `sha256` equals the package hash and passes persisted-object verification, management-policy hash matches approved scope, GPU pod leases released, caption tracks `CURRENT` with `timing_source = ACTUAL_AUDIO_ALIGNMENT` ("estimated from script; only actual-audio captions are releasable") | `S/review/gate_conditions.py:117-224` (caption quotes `:208-210`, `:216-219`) |
| Decision recording: `decide_episode(principal, episode_id, command)` → `require_human_owner(principal)`, idempotency scope, `_gate2_action`; binding check "Every hash the reviewer saw must still be the current package's (else 409)" (`command.package_hash != stored.package_hash` → `StaleRevision`) | `S/review/service.py:1078-1089`, `:1092-1102` |
| Package storage/status machine: `store_release_package` / `current_package` / `PackageStatus` / `record_package_decision` in `S/review/packages.py` | `S/review/packages.py` (symbols) |
| Edit artifacts reach the package via `VariantsService.final_review_media` → `FinalReviewMedia` ("What the ordinary final-review package (T020/Gate 2) embeds for this episode"): `media`, `caption_track_ids`, `hook_experiment_id`, `variant_keys`, `hook_candidate_ids`, `creative_derivatives` | `S/editing/variants_service.py:2018-2110`, `:231-241` |
| Episode state machine schedules W06 edit before `AWAITING_FINAL_REVIEW` | `S/scheduling/service.py:279`, `:433` |

## 3. Derivatives that exist today (and NOT FOUNDs)

| Derivative | Status | Facts |
|---|---|---|
| Platform variants (crop per destination) | EXISTS | `VariantSpec` — "ratio + frame + caption treatment" (`platform`, `account_ref`, `variant_key`, `ratio`, `width/height`, `burn_locale`, `cover`) `S/editing/variants.py:120-131`; `build_variant_edl` — "Re-cut the accepted main EDL into one variant EDL (same timeline, new frame)… dialogue and ambience placement is untouched" `S/editing/variants.py:272-305`; service `build_variants` `S/editing/variants_service.py:505-607`, burned variant rebuild `:828-961` |
| Covers (thumbnail-ish stills per variant) | EXISTS | `plan_cover_specs` / `run_cover_extract` `S/editing/covers.py:60`, `:112` |
| Hooks (IMP-07, teaser-like) | EXISTS | `plan_hook_candidates` — "Plan exactly three distinct candidates from the accepted main EDL"; treatments `payoff_first_cold_open`, `chronological_tease`, `punch_in_reaction`; payoff window "must survive every hook" or candidate refused; `HOOK_MIN_MS = 20_000`, `HOOK_MAX_MS = 40_000` | `S/editing/hooks.py:386-452`, `:52-56`, `:66-67`, `:50-51` |
| Hook contract | EXISTS | `HookExperiment` — "Three candidates from accepted footage; no fresh video renders"; `new_video_render_job_ids` max_length 0; `HookAssignment` exposure ledger (organic-only, "initial paid-ad budget is zero") | `S/contracts/media.py:258-269`, `:237-255`; tables `M/0004_media_and_qa.sql:91-110` |
| Poster | EXISTS | `run_poster_export` — "Compose approved character/title/CTA image assets into a still poster… Title and CTA are already typeset, approved image assets" (no live text in the filter graph) | `S/editing/creative_derivatives.py:181-230` |
| Episode-one preview | EXISTS | `run_preview_export` reuses `run_cropped_export` with `PREVIEW_MAX_MS = 90_000` | `S/editing/creative_derivatives.py:233-250`, `:29` |
| Caption files (SRT) | EXISTS | `srt_bytes(track) -> bytes` — "Deterministic UTF-8 SubRip serialization"; stored content-addressed, linked via `caption_tracks.asset_id` ("rendered subtitle file") | `S/editing/captions.py:152-165`; `M/0004_media_and_qa.sql:80` |
| Burned-in captions | EXISTS, TH only | `burn_locale: str = "th-TH"`; validator `burn_locale must be one of caption_locales` | `S/editing/config.py:48-51` |
| **Recap segment** | **NOT FOUND** | `rg -i "recap" src/` → zero hits. SPEC requires it: "**Recap:** ≤10 s, bound to the preceding approved episode version; rebuilt if that version changes" (`docs/microdrama-system/v3-workflow/SPEC-v3.md:459`) |
| **CTA video segment** | **NOT FOUND** (image only) | CTA exists only as an approved image asset composed into posters (`CreativeSource.cta`, role `"CTA"`); no CTA video cut. SPEC: "**CTA (V3R-6):** resolved from the calendar revision…" (`SPEC-v3.md:460-461`; `S/contracts/release.py:136`, `S/editing/creative_derivatives.py:70`) |
| **Per-language audio tracks** | **NOT FOUND** | single stereo mix only; `rg -i "audio_track|per.language|language_track" src/` → only YT metadata localizations (`S/publishing/youtube/transport.py:65`) |
| Season teaser (30–60 s) | NOT FOUND (phase F owns it) | SPEC §4.10 `SPEC-v3.md:502-508`; phase-F F5 row `docs/…/phase-F-spec.md:1000` |

## 4. Cue timing today

| Fact | Cite |
|---|---|
| Timing source is EDL audio placement, never script: "Timing is always the measured audio placement from the EDL — never the script's estimates." `start = clip.timeline_in_ms`, `end = start + clip.duration_ms + tail_pad_ms` (120 ms), floored at `min_cue_ms` (500), clamped to next cue `end = min(end, next_start - 1)` | `S/editing/captions.py:66-67`, `:106-113`; `S/editing/config.py:45-46` |
| Caption provenance enum: `ACTUAL_AUDIO_ALIGNMENT` / `ESTIMATED_FROM_SCRIPT  # never releasable`; `CaptionTrack.releasable` property returns True only for ACTUAL | `S/contracts/enums.py:358-360`; `S/contracts/media.py:216-218` |
| Track binds to the audio it was derived from: `derived_from_audio_sha256` ("Actual audio the timing was aligned to"); validator: "actual-audio timing must name the audio it was aligned to" | `S/contracts/media.py:196-213` |
| Speech observation (ASR/fixture, never script): `SpeechObserver.observe(audio_sha256) -> ObservedSpeech | None`; on mismatch every locale's cue carries what was actually spoken + CRITICAL finding `caption.audio_content_mismatch` | `S/editing/captions.py:38-41`, `:78-95`; `S/editing/models.py:40-55` |
| Per-locale tracks built from the same EDL dialogue clips → th-TH/en-US share timing **by construction** (same `timeline_in_ms`); no separate timing-transfer mechanism exists | `S/editing/captions.py:71-73`, `S/editing/config.py:47` `caption_locales=("th-TH","en-US")` |
| **Word timings: NOT FOUND** — `CaptionCue` fields are `cue_id/start_ms/end_ms/text/line_id` only; `rg -i "word_timing|word_time|phoneme"` → no timing structures | `S/contracts/media.py:176-187` |
| Staleness + rebuild: `stale_caption_cues` (line sha changed since CURRENT track derived, T019); `rebuild_caption_outputs` — "every named CURRENT track gets its subtitle (SRT) artifact… the burned master derivative is re-burned… with the stale burned asset superseded. Honest skips, never silent ones" | `S/editing/service.py:211-220`, `:226-246`; `S/editing/models.py:90-102` |

## 5. Loudness / audio normalization — NOT FOUND

- `rg -i "lufs|loudnorm|loudness|ebur128" src/ tests/` → **zero hits**.
- What exists instead: per-clip `gain_millibel` (contract bounds −6000…1200, `S/contracts/media.py:95`), `room_gain_millibel=-1_800` (`S/editing/config.py:39`), ffmpeg `volume=`/`adelay=`/`amix=normalize=0` (`S/editing/export.py:88-118`), QA peak-only `measure_peak_db` (`S/qa/technical.py:180`).
- The −14 LUFS / −1 dBTP requirement is SPEC text only: "**Mix:** −14 LUFS integrated, −1 dBTP. Thai captions burned in; EN and ZH as tracks delivered per §9" (`SPEC-v3.md:473`; also V3-AT-10 `SPEC-v3.md:901`).

## 6. Duration rules in code

| Rule | Value | Cite |
|---|---|---|
| Export ceiling (CPU bound) | `max_export_duration_ms = 320_000`; assembly raises "EDL duration exceeds the configured export ceiling (CPU bound)" | `S/editing/config.py:55-57`; `S/editing/service.py:622-627`; also `variants_service.py:414-420` |
| Hook candidates | 20 000–40 000 ms, enforced in contract validator ("IMP-07: hook candidates must be 20-40 seconds") and constants | `S/contracts/media.py:231-234`; `S/editing/hooks.py:50-51` |
| Episode-one preview | `PREVIEW_MAX_MS = 90_000` | `S/editing/creative_derivatives.py:29` |
| Shot unit | "shot exceeds the supported 15-second unit" | `S/contracts/season.py:426-427` |
| Recap ≤10 s / CTA ≤5 s | **NOT FOUND in code** — SPEC-only (`SPEC-v3.md:459,901`) | — |

## 7. Production binding (clip → source shot/render; V3-AT-25)

| Fact | Cite |
|---|---|
| Caller passes `shot_assets: Mapping[shot_id → asset_id]`; `_shot_sources` requires the asset row, `AssetKind.VIDEO`, state in `("ACCEPTED","LOCKED")` (`_ACCEPTED_ASSET_STATES`), and a measured `descriptor.media.duration_ms`; records `asset_sha256` | `S/editing/service.py:555-578`, `:105` |
| Pipeline gate before edit: W05 "only {accepted}/{shots} shot assets accepted" counting `object_key LIKE 'renders/%' AND state='ACCEPTED'` | `S/pipeline/runner.py:455-461` |
| Binding into the artifact: EDL hash covers `[clip_id, source_asset_id, source_in_ms, source_out_ms]` per clip | `S/editing/edl.py:155-162` |
| Output registration is content-addressed with lineage: `register_asset(tx, descriptor, *, generation_key)` — "Insert an asset row and its lineage edges. Idempotent for an identical descriptor."; `asset_lineage(asset_id, source_asset_id, relation DEFAULT 'derived_from')` is append-only (trigger `md_forbid_mutation`) | `S/persistence/assets.py:21-27`; `M/0004_media_and_qa.sql:41-50`; register calls `S/editing/service.py:359, :489, :1051` |
| `edit_manifests` binds episode/purpose/variant_key/version → `output_asset_id`; unique per `(episode_id, purpose, variant_key, version)` | `M/0004_media_and_qa.sql:52-67` |
| V3-AT-25 verbatim: "Native zero-, one- and two-speaker clips pass the production binding path; all derivatives retain speech/audio/caption synchronization." (E's, "D supplies the binding evidence") | `SPEC-v3.md:916`, `:882` |

## 8. What D feeds E; what F consumes from E

- **Closest shot-plan structure today** = `Shot` + `ShotManifest` (built by `S/story/compiler.py`). `Shot` — "One generated unit. Carries every directing-playbook/routing field (SPEC §7)": `shot_pattern_id`, `coverage_role`, `dramatic_importance: Level`, `dialogue_complexity` (validated against speaker count, ≤2 speakers), `temporal_risk`, `required_identity_controls`, `preferred_render_tier`, `fallback_edit`, `reference_lock_version`, `line_ids/speaker_ids/voice_ids`, `target_duration_ms`, `framing`, `eyelines`, `sound`, `acceptance_criteria`, `depends_on_shot_ids`. `ShotManifest` is a `VersionedPayload` with `identity_lock_id`, `shots: list[Shot]`. | `S/contracts/season.py:392-468` |
- **ShotPlanV3: NOT FOUND** — `rg -i "ShotPlanV3|shot_plan" src/` → zero hits (matches phase-F §13: "no phase-D spec exists yet").
- **F consumes from E** (phase-F-spec.md v0.4 §13, read-only): "**Phase E** supplies the edit artifacts the teaser assembles and the caption tracks Gate 2 checks; no phase-E spec exists yet (verified 13 Nov 2026) — **package F5 is blocked until E is accepted and its export/caption contract is pinned; F1–F4 build and test offline with seeded caption tracks** (the `teaser_cut` job reuses the existing deterministic `S/editing` seam, §5, but its V3 input contract is E's). **E is also the declared owner of the pinned rebuild contract for E-owned recap/CTA media and captions inside the A4-registered amendment closure (§8.2 — PF-10): those edges are registered but BLOCKED until E pins it**" | `docs/microdrama-system/v3-workflow/phase-F-spec.md:985-991`, F5 row `:1000` |

## 9. QA / inspection on edited artifacts

| Layer | Facts | Cite |
|---|---|---|
| In-assembly `TechnicalCheck`s | `edit.video_tiling` (gap ranges), `edit.room_continuity`, `caption.cue_bounds`, `export.duration` (probed vs EDL, tolerance `frame_ms + probe_tolerance_ms`), `export.streams`, `export.decode`, `burn.rendered` (UNKNOWN when no Thai font — "a check that could not run … is ``UNKNOWN``, never ``PASS``") | `S/editing/service.py:902-989`; `S/editing/models.py:58-67` |
| Findings (stable codes) | `caption.audio_content_mismatch`, `edit.duration_drift`, `font.thai_unavailable` ("the burn is skipped, not faked") | `S/editing/models.py:40-55` |
| Post-assembly job `qa.technical` | "Decode/streams/black/freeze/silence/peak/caption checks + ASR": `gather_facts`, `detect_black_windows`, `detect_frozen_windows`, `detect_silence_windows`, `measure_peak_db`, `extract_embedded_captions`, `technical_findings` | `S/contracts/jobs.py:128-134`; `S/qa/technical.py:118,162,180,195,243`; runs at W07 on the master (`S/pipeline/runner.py:500-524`) |
| ASR cross-check of captions | `as_speech_observer`, `speech_findings`, `caption_speech_findings`, `align_lines` | `S/qa/audio.py:203,259,384,229` |
| §12.2 output inspection (forbidden on-frame text/brand/likeness) | "phase C accountable; consumed by D and F" — findings flow into QA/repair + Gate 2; `qa/visual.py` exists (5.5K) | `SPEC-v3.md:793-797` |
| Repair → rebuild | `qa/repairs.py` calls editing rebuild; `DerivedOutputsRebuild` records new/superseded asset ids | `S/qa/repairs.py`; `S/editing/models.py:90-102` |
| Gate-2 blocker feed | QA findings in package + per-episode findings block APPROVE | `S/review/gate_conditions.py:142-158` |

## 10. Gaps phase E will need (do not exist today)

| Gap | Evidence |
|---|---|
| Recap generator (≤10 s, bound to preceding approved episode version, rebuilt on change) | `rg -i "recap" src/` → zero hits; SPEC `:459` |
| CTA segment resolution (next air time / continuation / finale follow, ≤5 s) | only poster CTA images; SPEC `:460-461` |
| −14 LUFS ±1 / −1 dBTP measurement + normalization | zero grep hits; only peak dB + static gains |
| ZH caption locale | `caption_locales=("th-TH","en-US")`; `rg "zh" src/microdrama/editing/ src/microdrama/publishing/metadata.py` → zero hits; V3-AT-10 requires "ZH/EN tracks share the TH cue timing" (`:901`) |
| Transitions (fade/xfade "in both exporters with a synchronised timeline", SPEC `:462`) | `TransitionKind` contract values CUT/CROSSFADE/FADE_FROM_BLACK/FADE_TO_BLACK + DBR-2 overlap rule exist (`S/contracts/enums.py:351-356`, `S/contracts/media.py:119-127`), but `rg "xfade|afade|fade" S/editing/*.py` → zero hits: `plan_master` emits plain `concat`, transition fields are never rendered |
| Per-language audio/dub tracks | single mix only (§3) |
| Word-level timing for cue alignment | cue-level only (§4) |
| `ShotPlanV3` (D's V3 directing output E validates against, V3-AT-9 `:900`) | zero hits |
| Teaser (30–60 s, `TEASER_FINAL`, spoiler authority) | F5's, blocked on E (`phase-F-spec.md:1000`) |

Context notes for the spec writer (facts, not design): today's caption deliverable model is already "tracks + one burned render" (`EditDecisionList.caption_track_ids` + `burn_in_caption_track_id`, `S/contracts/media.py:148-149`); generation-unit contract (immutable inputs, semantic attempt id, reservation, replay) is already honored by assembly replay + `register_asset` idempotency (SPEC §10.5, `:720-728`); music (YuE2) and voices (Botnoi, operator-made Web Studio V4 uploads, `basis = OPERATOR_ATTESTED`) are owned by C/D per `DECISIONS.md:64,70-103,131` — E consumes them as assets.
