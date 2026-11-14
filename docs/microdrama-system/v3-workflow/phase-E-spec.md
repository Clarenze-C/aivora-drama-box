# Phase E: Edit — native-audio assembly, derivatives, captions, loudness, the edit gate (v0.1 DRAFT)

Status: **v0.1 DRAFT**, 14 Nov 2026, GLM (weekend runbook). Chain: builds on **D** (no phase-D spec
exists yet — verified, FM §8); feeds **F** (`phase-F-spec.md` v0.4 §13 names E as its blocked
prerequisite, `phase-F-spec.md:985-991`). Precedence: `DECISIONS.md` > `REQUIREMENTS.md` >
`SPEC-v3.md` v0.4.6 > accepted phase specs (A0 v0.4, A v0.3, B v0.6, C v0.4.1) > this draft.
Conflicts with any of those are open questions (§16), never silent. Code facts cite today's tree
(`feat/microdrama-m0-m4`) as `FM §n` ([e-factmap.md](e-factmap.md)) or `file:line`; anything I could
not verify is `UNVERIFIED`.

**E owns (SPEC §15.1/§15.2):** V3-AT-10, V3-AT-25 (`SPEC-v3.md:882`); R-7.1–R-7.7, R-12.8
(`SPEC-v3.md:934`; definitions `REQUIREMENTS.md:133-139,187`).

---

## 0. Scope

**Problem.** V3 episodes end step 6 with accepted native-render clips and nowhere to go: today's
editor **discards the clips' embedded audio** and lays separate TTS line assets plus a whole-timeline
generated room tone (FM §1); recap and CTA segments do not exist (FM §3); loudness is unmeasured
(FM §5); transitions are schema-only (FM §10); there is no ZH caption locale (FM §10); and F5 — the
teaser and the YouTube caption delivery — is blocked on exactly this phase's export/caption contract
(`phase-F-spec.md:985-991`).

**Phase E builds step 7 (tab 7, SPEC §4.7) for V3:**

1. **Native-audio EDL + caption remap** (R-7.1, R-7.5): clip audio as the one dialogue/ambience
   source, utterance-aligned cues, TH burn + th-TH/en-US/zh-CN tracks.
2. **Transitions** (R-7.2): fade/xfade rendered in both exporters on a synchronised timeline.
3. **Recap binding** (R-12.8) and **CTA resolution** (R-7.7, V3R-6): duration-checked segments bound
   to the predecessor's approval and the calendar revision.
4. **Music placement + ducking** (R-7.3) and **SFX placement** (R-7.4), from C's accepted season
   libraries; per-episode SFX gap fills are E's only paid work.
5. **Loudness** (SPEC §4.7 mix line): −14 LUFS ±1 / −1 dBTP, measured, evidenced, gated.
6. **The edit gate**: typed readiness blockers consumed by Gate 2 (F §4), and the pinned rebuild
   contract F8's amendment closure waits on (PF-10, `phase-F-spec.md:776-791`).
7. **Derivative synchronization** (V3-AT-25): binding checks and derivation checks across every
   E-produced artifact.

**Not in E:** voices and the voice catalogue (C §7; E consumes registered clips as Pika-render
inputs' provenance, `DECISIONS.md:92-103`); the music/SFX **libraries** themselves (C §0 item 7,
`phase-C-spec.md:63-64`); shot compilation, render and clip QA (D — E consumes `ShotPlanV3` and
accepted shot assets); metadata drafts, thumbnails, Gate 2 mechanics, teaser cut execution, calendar
authority, caption **delivery** (F — E produces the tracks F delivers, F §1.9
`phase-F-spec.md:140-151`); the V1/V2 editing pipeline (frozen).

---

## 1. Binding decisions

1. **V1/V2 never change** (B §1.1 / C §1.1 / F §1.1 rule). V3 edit code lives in new modules
   `S/editing_v3/`. The deterministic seam — `S/editing/{edl,export,ffmpeg,captions}.py`
   (T015 lineage, FM §1) — is **the one implementation**: V3 extends its planners for native audio
   (§3) and calls them through V3 adapters. F already reuses this seam for `teaser_cut`
   (`phase-F-spec.md:447-452`), so E must not fork it. The V1 `EditingService` and its pipeline
   handlers refuse V3 rows through A §1's `require_workflow` ("editing" is in A's inventory,
   `phase-A-spec.md:44`); E registers `edit_v3.*` handlers beside them.
2. **The seam's tables are the persistence of record** for V3 EDLs and captions: `edit_manifests`
   (immutable EDL, hash, `output_asset_id`, `UNIQUE (episode_id, purpose, variant_key, version)`,
   `M/0004_media_and_qa.sql:52-69`) and `caption_tracks` (one CURRENT per (episode, locale),
   `M/0004_media_and_qa.sql:71-89`). Verified: `purpose` CHECK already covers E's needs
   (`FULL_EPISODE/PART/PROMO_CUT/HOOK`, `M/0004:56`) — the recap and CTA are **embedded clips in the
   episode master's EDL**, not separate manifests; `locale` is free text (`M/0004:75`), so `zh-CN`
   needs no migration. V3 rows are written only by `S/editing_v3`; no V1/V2 row is touched
   (E-T1 asserts byte-identity).
3. **Native audio, end to end (V3C-15, R-7.1; SPEC §4.7:454-458).** Every placed clip contributes
   its embedded audio at its trimmed span — synchronised A/V trims (`in/out` identical for both
   streams). **No separate dialogue audio assets are created or laid** (today's
   `ref_id_for("line-audio", …)` path, FM §1, is V1-only), and **no synthesised replacement
   dialogue** exists anywhere in E. Ambience comes from the clips; the V1 whole-timeline `room.main`
   generated tone is **not used**. Generated room tone survives only as **inter-clip gap fill**
   (never under a clip — that would duplicate ambience), gain/config-owned, hashed into the session.
4. **Utterance alignment owns cue timing (SPEC §4.7:455, 457).** TH cues are timed from **measured
   utterance windows inside the placed clip audio** — never whole-clip spans and never script
   estimates. The alignment source is D's clip-QA word timings when the `ClipQaResult` carries them
   (**UNVERIFIED** — no phase-D spec; O-E3), else E's `UtteranceAligner` seam (fake offline, deterministic
   fixtures). All locales share the TH windows (V3-AT-10 "ZH/EN tracks share the TH cue timing",
   `SPEC-v3.md:901`) — today's per-locale tracks already share `timeline_in_ms` by construction
   (`spot_caption_track`, `S/editing/captions.py:48-139`, spot-checked); E changes what the window
   measures, not the sharing rule. `timing_source` stays `ACTUAL_AUDIO_ALIGNMENT`;
   `derived_from_audio_sha256` binds the **clip audio** hashes. The speech-observation mismatch rule
   is unchanged: a cue carries what was actually spoken + a CRITICAL finding
   (`caption.audio_content_mismatch`, FM §4).
5. **Captions and the O-8 shape (R-7.5; SPEC §4.7:473).** One burned render, Thai only: `burn_locale`
   is config-owned and validated against `caption_locales` (FM §3) — V3 pins `th-TH`. CURRENT tracks for
   `th-TH`, `en-US`, `zh-CN`, each with its deterministic SRT asset (`srt_bytes`, FM §3). **No
   burned-in per-language variants** — excluded by the operator's O-8 ruling (F §1.9,
   `phase-F-spec.md:140-151`); F's `deliver_captions` binds these exact track assets for YouTube.
   EN/ZH display text comes from B's packs (B §2.1); E never translates.
6. **Loudness is measured, normalised and gated (SPEC §4.7:473).** Target **−14 LUFS integrated
   ±1, −1 dBTP true peak** on every audio-bearing released artifact (clean master, burned master,
   platform variants, hooks, episode-one preview). Measurement: `ebur128` analysis pass per output.
   Normalisation: a **deterministic measured-gain stage** (`volume=<computed dB>` pre-encode) —
   never single-pass `loudnorm` (its dynamic mode is not reproducible across runs; §19 rejects it).
   Evidence: one `LoudnessReportV3` document per artifact (pre/post measurements, tool, streams,
   pass/fail), hash-sealed. **A failing report is a typed readiness blocker** (§9) — no Gate 2, no F.
7. **Recap: approval-bound, source-cut (R-12.8; SPEC §4.7:459; V3-AT-10).** A ≤10 s leading segment
   assembled from the **predecessor episode's packaged source shots** selected by B's `recap_plan`
   (`phase-B-spec.md:140`) — the same accepted shot assets the predecessor's master was built from,
   never a re-encode of its encoded master (§19). Binding = the predecessor's **effective Gate 2
   approval** (A §7.2 `effective_approval`) + the exact source asset id/sha set + the recap beat
   refs. Episode 1 has none (`recap_plan` empty, B §2.1). If the approval does not exist when the
   episode assembles, the session completes **without** the recap leg (typed blocker
   `edit.recap_pending`) and the recap splices in — a new manifest version under the same EDL
   discipline — once it does. All recap clips pass the same production binding path (§8).
8. **CTA: calendar-resolved, deterministic (R-7.7, V3R-6; SPEC §4.7:460-461).** A ≤5 s end card.
   Copy is **template-resolved TH text** from the current calendar revision (proposed before
   editing, SPEC §9.2 item 1 `SPEC-v3.md:590-593`) + B's `cta` intent line (`phase-B-spec.md:145`):
   next-air-time, confirmed continuation (only when the extension decision exists), or finale
   follow — **never a promise of an unapproved extension**. No LLM writes copy (§19): F's rebuild
   handler for date-bearing content is deterministic by contract (`phase-F-spec.md:785-788`), so
   E's CTA must be too. Visuals: accepted image/title assets + licensed-font typesetting through the
   existing libass path (the poster seam's rule — no live text in a filter graph beyond libass
   itself, FM §3); audio: music tail from the cue sheet, no speech. Missing calendar ⇒ typed blocker
   `edit.cta_unresolved`.
9. **Transitions render (R-7.2; SPEC §4.7:462).** `TransitionKind` CUT/CROSSFADE/FADE_FROM_BLACK/
   FADE_TO_BLACK (`S/contracts/enums.py:351-356`; today never rendered, FM §10) renders via
   `xfade`/`fade` + paired `afade` **in both exporters** (master and variant/burned planners) on one
   synchronised timeline, honoring the DBR-2 overlap rule (`S/contracts/media.py:119-127`). Cut and
   trim boundaries are **speech-safe**: no boundary lands inside an aligned utterance window
   (SPEC §4.5:422-423 "Edit may trim at measured, speech-safe boundaries"; the edit-side half of
   V3-AT-9's no-mid-word rule).
10. **Music/SFX placement consumes C's libraries (R-7.3, R-7.4; SPEC §4.7:463-472).** Cue sheets
    (`MusicCue`, `SfxAsset` — master §13 names them, `SPEC-v3.md:843`; B/C claim neither — E claims
    them, O-E5) place accepted library assets (MUSIC_LIB/SFX_LIB picks, C §0 item 7) on the episode
    timeline. **Ducking is deterministic**: a volume envelope computed from the EDL's dialogue/utter
    spans — no dynamic compressor state, reproducible bit-for-bit from the session. Per-episode SFX
    **gap fills** ride C's qualified SFX route seam (§7 audio providers, `SPEC-v3.md:555-570`) as
    E's **only paid work**: §10.5 generation units, reserved against the episode's `step_07` budget
    (A §5.2 order), unknown price ⇒ refused (C §1.7 rule).
11. **E makes no LLM calls** (the C §1.11 pattern): assembly, alignment, cue sheets, recap/CTA
    resolution, loudness and checks are deterministic. Nothing in SPEC §4.7 requires an LLM in
    step 7 — A0's `LlmStep` is therefore not on E's path at all.
12. **The edit gate is readiness, not a gate.** Step 7 has no gate of its own (SPEC §2 tab table,
    `SPEC-v3.md:116`); the human decision is Gate 2 (F). E computes **typed readiness blockers**
    (§9) and supplies recap/CTA previews into the Gate 2 page (F §4 item (d),
    `phase-F-spec.md:370-371`). Gate 2 **Revise on edit content** routes through A's amendment path
    (F §4: "targeting content routes to the owning phase's amendment path",
    `phase-F-spec.md:377-379`): E registers the deterministic timecode→shot/segment mapping and its
    rebuild handler rebuilds **only the noted units** (V3-AT-2, `SPEC-v3.md:893`). No `GateType`
    value is added; no new decision surface.
13. **The pinned rebuild contract (PF-10).** F8 registers E-owned edges "BLOCKED until E pins it"
    (`phase-F-spec.md:788-791`). E pins them here: A4 `DependencyProvider` edges + the
    `edit_v3.rebuild` handler for — predecessor approval → successor recap; calendar revision → CTA
    copy/media; source shot asset / `ShotPlanV3` revision → assembly; music/SFX library revision →
    cue sheets; caption source text revision → tracks. Rebuild = deterministic reassembly producing
    **new manifest versions and assets** (nothing rewritten); published media is never touched
    (SPEC §12.6 item 5); renewed authority installs through F's rebinding (`phase-F-spec.md:793-827`),
    which is F's, not E's.
14. **One lane, four-point checklist, no reservations for determinism (SPEC §10.0).** E adds the
    `edit` queue lane through A §4's checklist (queue CHECKs, `budget/policy.py` ownership, worker
    set, generated contracts — ED1). Deterministic E jobs carry **no provider operation and no
    reservation**; only `edit_v3.sfx_fill` reserves (through C's `media` lane seam, ED3). Every job
    carries A §3 `work_scope` (`track='production'`, `logical_work_id`,
    `expected_content_revision`); date-bearing work (CTA) also carries the calendar revision and is
    fenced on it.
15. **Crash-resume is replay, not regeneration (SPEC §10.5:720-728).** Assembly idempotency is the
    existing EDL-hash replay (`_replay_outcome`, FM §1) + content-addressed `register_asset`
    idempotency (FM §7) — a restart never re-renders a stored outcome, and a crashed export leaves
    nothing registered (registration happens only after decode/stream/duration checks pass, FM §9).
    SFX fills follow §10.5 fully (immutable inputs, semantic attempt id, reservation, reconcile
    before resubmit).

---

## 2. Records (contract package, guardian-owned bump; symbolic migrations `E-1…`)

V3 edit documents live in one new append-only, versioned, hash-sealed store **`v3_edit_documents`**
(`E-1`), mirroring B/C/F's stores: PK `(contract_type, record_id, version)`, one `current` row, hash
re-verified on read, `contract_type` allowlist CHECK, standard guards,
`record_id = uuid5(EDIT_V3_NS, "<type>:<season_id>:<episode_id>[:<key>]")`. `v2_contract_documents`,
`v3_story_documents`, `v3_cast_documents`, `v3_release_documents` are not touched.

| Migration | Object | Decisive columns / rules |
|---|---|---|
| `E-1` | **`v3_edit_documents`** | the edit document store above; guarded |
| `E-2` | lane + queue plumbing | `jobs.queue` CHECK gains `edit` (0001:77 today: `production/publication/community` + A/B/C/F additions — re-audit the tail at E1); reservations/charges ownership for `step_07`; worker set; generated contracts (A §4 checklist) |

No other migration. Verified in particular: `edit_manifests.purpose` needs no new value (recap/CTA
are embedded clips, decision 2); `caption_tracks.locale` is unconstrained text (`M/0004:73`);
`SlotKind` already carries `PROMO_CUT`/`HOOK` for F's teaser and E's hooks (`S/contracts/enums.py:430-434`).

**Documents in `v3_edit_documents`:**

| Record | Key | Content |
|---|---|---|
| `EditSessionV3` | `session` (one current per episode) | the episode's edit session: `shot_plan_ref` (D's `ShotPlanV3` version) + the **shot→asset binding map** (shot_id → {asset_id, sha256, measured duration} — the production binding path's inputs, FM §7); script/manifest refs; the predecessor recap binding (approval event ref + source asset set + beat refs) or `recap_pending`; `music_lib_revision`/`sfx_lib_revision`; `calendar_revision` for CTA; the V3 edit config digest (locales, gap-fill gain, loudness targets, transition defaults); state is **derived, never stored** (AR-4) |
| `CtaResolutionV3` | `cta:<episode_number>` | kind (`NEXT_AIR_TIME` \| `CONFIRMED_CONTINUATION` \| `FINALE_FOLLOW`), the resolved copy (TH), the calendar revision + hash it depends on, the accepted image/title asset refs, duration_ms (≤5 000, validator), font/provenance refs |
| `MusicCueSheetV3` | `music:<episode_number>` | `MusicCue[]`: library asset ref (id/version/sha), timeline in/out, loop/duration target, gain_millibel (bounds `S/contracts/media.py:95`), duck profile (depth/ramp), derivation of the duck envelope |
| `SfxCueSheetV3` | `sfx:<episode_number>` | `SfxAsset[]`: library-or-filled asset ref, timeline point/span, gain, the gap key (for fills: the generation-unit reference with attempt id + receipt ref) |
| `LoudnessReportV3` | `loudness:<artifact asset_id>` | artifact kind + asset ref, measured integrated LUFS + true peak (pre), applied gain dB, measured post values, analyser tool + version, streams analysed, pass/fail vs targets |

**Reused unchanged:** `edit_manifests`, `caption_tracks`, `assets` + `asset_lineage` (append-only,
FM §7), `hook_experiments` (FM §3), the `S/editing` seam modules, `FFmpegRunner` (FM §1), the QA
`qa.technical` job at W07-equivalent scheduling for V3 (E re-registers it for V3 episodes through
A's job system, same contract, FM §9), `gate2_blockers`' caption conditions (F consumes, FM §2).

### 2.1 E contract crossings (the C-B1 pattern, C §2.2 / F §2.2)

Every E identifier crossing an A/B/C/D/F-enforced contract, checked **before the E1 note is
accepted**; declared rows are requests to the owning phase's register, not edits to their specs:

| # | Delta | Contract touched | Mechanism |
|---|---|---|---|
| ED1 | Queue lane `edit` | A0/A3's `jobs.queue` CHECK | `E-2` grows the CHECK; ownership/worker/contracts land with E1 (mirrors C's CD1 / F's FD2) |
| ED2 | E consumes `EpisodePackV3` fields (`recap_plan`, `cta`, line text per locale, beat vocabulary) read-only | B §2.1/§2.3's field mapping and consumer order (`phase-B-spec.md:133-210`) | declared for B: E is added to B §2.3's reader order; E validates against B's published validators, adds none |
| ED3 | E consumes C's accepted music/SFX libraries and, for gap fills, C's qualified SFX route seam + `media` lane | C §0 item 7, C §10 (`phase-C-spec.md:698-699`), C §2 pick kinds | declared for C: E needs a **library manifest shape** (per-cue mood/duration/loop metadata) — O-E4; E's `sfx_fill` jobs ride C's `media` lane with E-owned `step_07` metering |
| ED4 | F embeds E's outputs: recap/CTA previews + readiness blockers on the Gate 2 page; `deliver_captions` binds E's exact track assets; F8's BLOCKED edges unblock | F §4 item (d), F §1.9, F §10 `deliver_captions` (`phase-F-spec.md:931`), F §8.2 PF-10 | declared for F: E pins the track-asset contract (locale tags, SRT bytes, CURRENT state, `derived_from_audio_sha256`) and the readiness-blocker vocabulary; F's F5/F8 wire their side |
| ED5 | E consumes D's `ShotPlanV3`, the shot→asset binding evidence, and clip-QA utterance/word timings | D's contracts (no phase-D spec yet — FM §8) | declared for D: E requires per-shot binding evidence {asset_id, sha256, duration, speaker count 0/1/2} and, ideally, word timings (O-E3). E validates defensively and blocks (typed) on any gap — it never guesses a binding |

**Standing rule:** any further E identifier crossing an enforced contract (enum, CHECK, trigger,
validator) joins this register before the E1 note is accepted.

---

## 3. Assembly: the native-audio EDL and the mix (R-7.1, R-7.2)

**Session assembly** (`edit_v3.assemble`) builds, in order:

1. **Binding validation** (§8): every `ShotPlanV3` shot resolves to an accepted/locked VIDEO asset
   with measured duration (the `_shot_sources` rules, FM §7); speaker counts and dialogue complexity
   are consistent with the plan; missing/rejected clips block (SPEC §4.6:449-450).
2. **EDL build** — the deterministic layout (FM §1) extended: shots in `sequence` order, video and
   audio trimmed together (`source_in_ms/out_ms` apply to both streams); recap clips (when bound)
   prefixed as leading clips with their own native audio; the CTA card appended as a composited
   still/clip segment; transition events between clips from the plan/config; music/SFX cue events
   attached to timeline spans. The EDL hash covers, per clip, `[clip_id, source_asset_id, in, out]`
   (unchanged, FM §7) plus the audio-source binding, so **any audio-affecting input change is a new
   EDL** — no silent remix.
3. **Export graph** (`plan_master`'s V3 branch): video trims/scale/pad/fps/format + transitions →
   concat; audio = per-clip `[i:a]atrim…,adelay=…` sources (replacing V1's per-line dialogue
   sources, FM §1) + gap-fill tone spans + music bus (cue sheet envelope applied as `volume`
   expressions) + SFX bus; `amix=inputs=N:normalize=0:duration=longest` (the existing mix rule,
   `S/editing/export.py:113`) followed by the loudness gain stage (§5). Master encode unchanged in
   shape (`libx264`/`aac`, FM §1) — **source assets are never re-encoded into intermediates**;
   every artifact is one export pass from the EDL; the burned render keeps `-c:a copy` (FM §1).
4. **Caption tracks** (§4) and **derivatives** (§6/§8) from the same EDL.

**Determinism:** same session inputs ⇒ same EDL hash ⇒ same bytes (seeded generators only — the gap
fill reuses the seeded `anoisesrc` pattern, FM §1). CPU: ffmpeg runs are the heaviest E work; the
production composition runs the E worker under the workspace CPU quota (G's concern; offline tests
use small fixtures — §14 build constraints).

---

## 4. Captions (R-7.5; V3-AT-10)

- **Timing:** utterance windows from the placed clip audio (decision 4). The existing
  spotter's floor/clamp rules (`min_cue_ms`, tail pad, clamp-to-next; FM §4) apply **within** the
  aligned window. TH is the master timing; `en-US`/`zh-CN` tracks reuse the identical windows.
- **Text:** TH = B's line text (or the observed-spoken text on mismatch, with the CRITICAL finding —
  unchanged rule, FM §4); EN/ZH = B's pack text verbatim. E adds no text of its own except the
  burned style.
- **Locales:** V3 config `caption_locales=("th-TH","en-US","zh-CN")` (V1 config is untouched,
  `S/editing/config.py:46`). Exact ZH tag for delivery is O-E2 (recommendation `zh-CN`).
- **Deliverables:** per locale one CURRENT `caption_tracks` row with its SRT asset (content-addressed,
  FM §3) — this is **the exact-bound set F's `deliver_captions` binds** (ED4). The burn uses `th-TH`
  only (`burn_in_caption_track_id`, FM context note §128). No burned EN/ZH variants (O-8).
- **Staleness/rebuild:** the existing line-sha staleness rule (T019, FM §4) extends to the V3
  sources: a cue is stale if its clip audio sha or line text changed — handled by the rebuild
  contract (decision 13), never by editing a track in place (`caption_tracks` body is immutable,
  `M/0004:88-89`).

---

## 5. Loudness (SPEC §4.7:473; V3-AT-10)

- **Measure:** `ebur128` analysis per audio-bearing output (clean master, burned master, each
  variant, each hook, the preview) — integrated LUFS and true peak, both persisted in
  `LoudnessReportV3`. Today nothing measures loudness (FM §5: only peak dB and static gains exist).
- **Normalise:** compute one gain in dB from the clean-master measurement
  (target −14 LUFS), clamp (config-owned bound), apply as the final `volume=` stage before the
  encoder in **every** export of that session; re-measure each output; a true-peak exceed after
  gain clamp fails (blocker `edit.loudness_fail` with measurements) rather than silently limiting.
- **Gate:** readiness requires every artifact's report PASS (−14 ±1 LUFS, ≤ −1 dBTP). The report is
  the evidence F/G can audit later; nothing is asserted without it.
- **Determinism:** analysis and gain are pure functions of the audio bytes; no dynamic normaliser
  state; the ffmpeg build is pinned by the composition (G), recorded in the report.

---

## 6. Derivatives: recap, CTA, variants, hooks, teaser input (R-7.6, R-7.7, R-12.8)

- **Recap** (decision 7): clips from the predecessor's packaged source shots per `recap_plan`
  beats; ≤10 000 ms enforced by contract validator + config constant (FM §6: rule absent in code
  today); native speech of the selected shots is kept (a recap line's cue uses the same alignment
  path); all sources pass the binding validator with the predecessor's package hash recorded.
- **CTA** (decision 8): ≤5 000 ms enforced; copy/visuals deterministic from `CtaResolutionV3`;
  date-bearing ⇒ the calendar revision is part of its hash.
- **Variants/covers/hooks/preview** (R-7.6): the existing derivative machinery (FM §3) re-runs on
  the V3 EDL through V3 adapters — variants re-frame without touching audio placement
  (`build_variant_edl`'s rule, FM §3), hooks keep the 20–40 s payoff-window rules, the preview keeps
  `PREVIEW_MAX_MS` (FM §6). Each re-encoded output gets a loudness report (§5). Hooks/variants burn
  TH; they carry **no** per-locale tracks (O-E1's recommendation).
- **Teaser input for F (PROMO_CUT):** E produces no teaser. E's contract to F5 (ED4) is that every
  approved episode exposes, at clip granularity: its EDL (source bindings + speech-safe boundaries +
  utterance windows) and its accepted assets — exactly what `release_v3.teaser_cut` assembles from
  (`phase-F-spec.md:447-452`). E guarantees addressability; F guarantees the cut.
- **Derivation checks (V3-AT-25 "all derivatives retain speech/audio/caption synchronization"):**
  for each derivative, per dialogue clip: the derivative's audio span equals the master's span plus
  a constant offset (re-cuts shift, never stretch); every cue's window shifts by the same offset;
  burned text renders from the same track body hash. Recorded in the session as `TechnicalCheck`s
  (the existing check model, FM §9) — UNKNOWN when a derivative type has no comparable surface, and
  UNKNOWN is never PASS (SPEC §4.6 rule).

---

## 7. Music and SFX placement (R-7.3, R-7.4)

- **Sources:** the season music library (YuE2 job, C's; generated in step 4's job graph inside the
  setup sub-budget, `SPEC-v3.md:471`) and the SFX library (ElevenLabs via C's qualified route,
  `SPEC-v3.md:559-568`, `DECISIONS.md:64`) — **accepted library assets only**, each with a
  `ProvenanceRecord` (C §9; E checks presence, never waives).
- **Cue sheets:** `MusicCueSheetV3`/`SfxCueSheetV3` (§2) are deterministic proposals from the
  episode pack's scene/mood vocabulary; the operator may adjust placement/gains pre-Gate 2
  (`adjust_mix`, §12) — edits are new document versions, hashed, and never touch the library.
- **Ducking:** envelope from utterance spans (music gain dips under dialogue, ramps config-owned);
  computed, stored in the cue sheet, applied in the export graph — reproducible.
- **Gap fills:** SFX needs the library lacks ride `edit_v3.sfx_fill` on C's `media` lane (ED3):
  one §10.5 generation unit per gap (immutable inputs, semantic attempt id, reservation against
  `step_07`/EPISODE, provider op through C's qualified seam, reconcile before resubmit). Offline
  fake adapter; live needs the C-qualified route and price — unknown price ⇒ refused, never
  zero-priced (C §1.7).

---

## 8. Binding and synchronization (V3-AT-25; `SPEC-v3.md:916`)

- **The binding path is the existing one** (FM §7): caller-supplied `shot_assets`, accepted/locked
  VIDEO with measured duration, sha recorded, EDL hash covers the binding. E's acceptance drives
  **zero-, one- and two-speaker** clips through it — D supplies the binding evidence (ED5); E
  validates and refuses typed on any gap (`edit.binding_incomplete`).
- **Synchronization invariants, checked at assembly and per derivative:** A/V trims identical per
  clip; cue windows inside measured utterance windows; derivation checks (§6); recap/CTA included
  (they are clips/cards on the same timeline). A violation is a CRITICAL finding blocking readiness.
- **What E records for D and F (SPEC §12.2 consumers):** for D — binding-validation outcomes and
  audio-side findings (mismatch, silence, alignment gaps) routed back as QA findings for repair;
  for F — the readiness blocker vocabulary, recap/CTA previews, track assets, loudness reports, and
  the rebuild edges (ED4).

---

## 9. The edit gate: readiness, Gate 2, Revise, rebuild (PF-10)

- **Readiness** (`edit_readiness(episode)`, derived, never stored — AR-4): typed blockers, each with
  its evidence ref: binding incomplete; recap pending/unbound; CTA unresolved; duration out of band
  (episode band from B §2.1 `phase-B-spec.md:149,159`; recap/CTA caps §6; export ceiling FM §6);
  any CRITICAL finding open (caption mismatch, decode, streams); loudness fail; a missing CURRENT
  track for any locale; derivative derivation-check failure. **Empty ⇒ step 7 done:** E claims the
  episode production-track transition closing step 7 through A's transition API (exact state names
  pinned in the E1 note against A's vocabulary), and the episode becomes available to F's step 8.
- **Gate 2 relationship:** F's V3 Gate 2 runs through A's decision transaction (F §4) and consumes
  E's readiness through the package path (the caption conditions already in `gate2_blockers`, FM §2,
  plus F's V3 additions). E registers no gate, adds no `GateType`, and never approves content.
- **Revise (V3-AT-2 "Revise regenerates only the noted units"):** Gate 2 EPISODE_FINAL Revise keeps
  A's timecoded-feedback contract (F §4/PF-9); E registers the deterministic map timecode →
  shot/segment/cue-sheet unit. Targeting edit content routes through A's amendment coordinator
  (`phase-F-spec.md:377-379`); the coordinator's Apply fences affected E jobs (A §7.3) and E's
  rebuild handler re-derives **only** the noted units' inputs (e.g. one shot's re-edit leg), leaving
  untouched units' manifest versions byte-identical — asserted in E-T7.
- **The rebuild contract (decision 13):** edges and handler as registered with A4. Bounds: rebuilds
  produce new versions; they never mutate applied migrations, published media, or stored outcomes;
  a rebuild of episode N's recap fires only while N is unpublished (published ⇒ F's corrective
  paths, `phase-F-spec.md:824-827`).

---

## 10. Jobs, fence, waits

| Job | Queue/lane | Provider ops | Metering / logical work ID |
|---|---|---|---|
| `edit_v3.assemble` | `edit` | none (local deterministic export) | none; `edit-assemble:<season>:<episode>` |
| `edit_v3.variants_and_hooks` | `edit` | none | none; `edit-variants:<season>:<episode>` |
| `edit_v3.sfx_fill` (one unit per gap) | C's `media` lane (ED3) | 1 SFX op (C's qualified seam) | `step_07`/EPISODE reservation; `sfx-fill:<season>:<episode>:<gap_key>` |
| `edit_v3.rebuild` (A4-registered handler) | `edit` | none (fans out to the jobs above) | none; `edit-rebuild:<season>:<episode>:<cause>` |

- **Fence:** every E job input carries `expected_content_revision` (A §7.1); CTA/recap-touching work
  also carries the calendar revision / predecessor approval ref and revalidates before each mutation.
  Stale results are quarantined, never installed (A §7.1).
- **Waits:** budget (`sfx_fill`) → `WAITING_BUDGET`; C-route unavailability → `WAITING_PROVIDER`;
  reconcile → `BLOCKED (reconcile)`; recap's missing predecessor approval → the readiness blocker
  (a content wait shown in the UI, not a job retry loop). All project through A's `track_waits`.
- **Crash/restart:** replay model (decision 15); no GPU is held; no human wait holds a lease.

---

## 11. E commands (A1 note §6 format)

| Command | Actor | Prerequisites | Effect | Events | Replay identity |
|---|---|---|---|---|---|
| `adjust_mix(episode, cue edits, expected revision)` | Operator (human session + CSRF) | session current; validators pass | appends `MusicCueSheetV3`/`SfxCueSheetV3` versions; enqueue `edit_v3.assemble` (new EDL hash) | `edit.mix_adjusted` | idempotency key |
| `rebuild_edit_media(episode, cause, expected revision)` | Operator (human session + CSRF) | readiness or Gate-2 Revise noted the units | runs the §9 rebuild handler for the noted cause/units only | `edit.rebuilt` | idempotency key |

No other operator verb: assembly is system-run; CTA copy is not operator-editable (determinism,
decision 8) — feedback goes through Gate 2 Revise.

---

## 12. UI (tab 7, built into the phase A shell, A5)

| Screen | Route | Primary action |
|---|---|---|
| Edit session | `/v3/seasons/{id}/episodes/{n}/edit` | **Rebuild** (only operator verb; secondary: adjust mix) |

Carries: binding status (shots accepted n/N), recap binding state (with predecessor approval ref),
CTA card preview + calendar revision, caption track table per locale (CURRENT/asset/timing source),
loudness panel (per-artifact measured/target/pass), derivative status, readiness blockers typed.
States per SPEC §3.2; one primary action; bot alerts link here. Recap/CTA previews surface again on
F's Gate 2 page (F §4 item (d)) — same data, no second render.

---

## 13. Build packages (in order; `make check` + V1 `make pilot` green at every gate)

Prerequisites: A0–A6 accepted; B, C accepted; **D accepted** (or the D seams E validates against are
pinned by D's spec — ED5; E1 may not start before that contract exists). F v0.4's F5/F8 unblock when
E is accepted (F §13). Real migration numbers allocated in the E1 note after re-auditing the tail.
**Applied migration bytes are never edited.**

| Package | Builds | Gate | Design note |
|---|---|---|---|
| **E1** | `E-1`/`E-2` migrations, `EditV3Store`, contracts bump (documents, readiness-blocker vocabulary), the §2.1 crossing register delivered, `require_workflow` guards on the V3 branch | E-T1 | **Critiqued first** (migrations + crossings) |
| **E2** | Native-audio EDL + export graph: clip-audio sources, synchronised trims, gap fill, transitions in both exporters, the `UtteranceAligner` seam + fake, session/binding validation | E-T2, E-T3 | **Critiqued first** (the deterministic core) |
| **E3** | Captions V3: zh-CN locale, alignment-driven windows, SRT assets, O-8 delivery shape, staleness rules | E-T4 | With the diff |
| **E4** | Loudness: measurement, gain stage, `LoudnessReportV3`, readiness wiring | E-T5 | With the diff |
| **E5** | Recap + CTA: bindings, templates, calendar dependency, duration validators, previews | E-T6 | With the diff |
| **E6** | Music/SFX cue sheets, ducking, `sfx_fill` on C's seam | E-T8, E-T9 | **Critiqued first** (money) |
| **E7** | Derivation checks, variants/hooks V3 wiring, readiness + production-track transition, A4 edge registration + `edit_v3.rebuild` (PF-10) | E-T7, E-T10 | **Critiqued first** (amendment races) |
| **E8** | Tab 7 UI | E-T11 | With the diff |

**Routing:** GLM builds each package (`ai-route build -w`); Codex critiques the E1/E2/E6/E7 notes and
reviews every diff; one package at a time. All offline/mock (hard rule 5): fakes for the aligner and
the SFX route; no network in tests.

---

## 14. Acceptance (offline; real PostgreSQL for every transaction test)

| Test | Package | Proves |
|---|---|---|
| E-T1 | E1 | `E-1`/`E-2` apply on a populated V1+V2 database; V1 `edit_manifests`/`caption_tracks` rows and their triggers byte-identical and still refusing V3 rows through the legacy path (`WORKFLOW_MISMATCH`); V3 documents roundtrip through the store with hash re-verification; generated contracts zero drift |
| **E-T2 (V3-AT-10, audio half)** | E2 | A two-speaker episode assembles with **clip audio only**: the export plan contains per-clip audio sources and **no** dialogue-line audio assets; no whole-timeline room tone (gap fill only, never under a clip); transitions render in master **and** variant/burned planners with paired A/V timing; a mid-word trim boundary is refused |
| E-T3 | E2 | Binding: every plan shot bound to an accepted asset (sha + duration recorded); a missing/rejected/short-measured shot ⇒ typed `edit.binding_incomplete`; zero- and one-speaker clips pass the same path |
| **E-T4 (V3-AT-10, caption half)** | E3 | th-TH/en-US/zh-CN CURRENT tracks with identical cue windows (TH-mastered); cues inside measured utterance windows; SRT assets content-addressed; the mismatch case carries observed text + CRITICAL finding; burned render is TH-only; **no** burned EN/ZH variant exists |
| E-T5 | E4 | A fixture master measuring −17 LUFS normalises to −14 ±1 with the persisted gain; a peak-clamping case fails typed with measurements (never silently limited); every artifact carries a report; readiness blocks on a failing report |
| **E-T6 (R-12.8/R-7.7)** | E5 | Recap ≤10 s sourced from the predecessor's packaged shots, hash-bound to its effective approval; episode 1 has none; `recap_pending` resolves by splicing a new manifest version; CTA ≤5 s resolves next-air-time/continuation/finale from the calendar revision and **refuses** to promise an extension without a decision record; missing calendar ⇒ typed blocker |
| **E-T7 (V3-AT-25)** | E7 | Derivatives: variant/hook/burned/preview derivation checks pass (constant-offset spans, shifted cues, same burn body); an injected desync ⇒ CRITICAL finding; a Gate 2 Revise timecode payload maps to exactly the noted units — untouched units' manifest versions and asset hashes byte-identical after rebuild |
| E-T8 | E6 | Cue sheets place accepted library assets only (missing provenance ⇒ typed refusal); ducking envelope reproducible from the session; music never overlaps dialogue above the configured duck depth |
| E-T9 | E6 | `sfx_fill`: §10.5 unit discipline (crash between submit/result/receipt ⇒ resume, no duplicate exposure, no regenerated success); reservation through `step_07`/EPISODE in A §5.2 order; unknown price ⇒ refused |
| E-T10 | E7 | A4 closure: predecessor approval change ⇒ successor recap rebuild registered and executed (unpublished only); calendar revision change ⇒ CTA rebuild; stale fenced results quarantined; published media untouched |
| E-T11 | E8 | Tab 7: every §12 surface renders per SPEC §3.2 states; one primary action; typed blockers visible; preview cards match Gate 2's |
| E-T12 | all | `make check` + V1 `make pilot` green at every package gate; no test touches the network |

---

## 15. QA and inspection on edited artifacts (SPEC §12.2)

- **E's own checks** (the existing layers, FM §9, re-registered for V3): in-assembly
  `TechnicalCheck`s (tiling, continuity, cue bounds, duration, streams, decode, burn) extended with
  the derivation checks (§6) and loudness (§5); the `qa.technical` job on the master; ASR
  cross-check of captions. Unknown ≠ PASS everywhere.
- **§12.2 (phase C accountable):** E **does not re-run detection** on pixels D already had inspected
  (every source clip carries inspection evidence at acceptance). E runs a **provenance-completeness
  check**: no clip/card asset enters an EDL without C inspection evidence and a `ProvenanceRecord`;
  a gap is a typed blocker. E-added pixels are typeset text (libass) from licensed fonts — C's FONT
  provenance applies. Whether E additionally samples burned-render frames through C's seam with an
  expected-text allowlist is O-E1 (recommended: yes, as hardening before live, not in E's offline
  gate).
- **Findings routing:** CRITICAL findings block readiness and Gate 2 (the existing feed, FM §9);
  audio-side findings route to D/QA repair (`qa/repairs.py` → E rebuild, FM §9).

---

## 16. Open questions (each with a recommendation)

| # | Question | Recommendation |
|---|---|---|
| O-E1 | Does E sample burned-render frames through C's §12.2 seam (expected-text allowlist: captions/CTA/title text E itself placed), or is provenance-completeness enough? | Completeness now (E2); add allowlist sampling of the burned render as hardening before live — the detector must never flag E's intentional text, so the allowlist contract needs C's sign-off |
| O-E2 | Exact ZH locale tag for delivery (`zh-CN` vs `zh-Hans`) — YouTube's caption language matching | `zh-CN` (BCP-47, matches B pack locale keys); confirm with F5's `upload_captions` surface and T032 evidence before E3 |
| O-E3 | Utterance-alignment source: does D's `ClipQaResult` carry word timings (Thai ASR word match already runs per shot, SPEC §4.6)? **UNVERIFIED** — no phase-D spec | Consume D's timings when present (ED5); E's `UtteranceAligner` fake drives offline tests; a Thai forced aligner is qualified before any live episode (G), never silently estimated |
| O-E4 | C's library manifest shape (per-cue mood/duration/loop metadata) is not pinned anywhere in C v0.4.1 | Request a C-side manifest document (or descriptor fields on the accepted assets) as the ED3 crossing before E6; until then E6's cue proposal reads asset descriptors only and marks mood-matching `UNVERIFIED` |
| O-E5 | `MusicCue`/`SfxAsset` (master §13, `SPEC-v3.md:843`) are claimed by no accepted phase; E claims both as placement records | E owns them as §2 documents; flag to the orchestrator — if C was meant to own library-side records, E's placement records rename without design change |
| O-E6 | Do hooks/variants need per-locale caption tracks? O-8 covers only full-episode posts | No — TH burn only (today's variant treatment, FM §3); revisit only if a hook ships to YouTube as a standalone post with required languages |

---

## 17. Requirement trace

| R-ID | Requirement (REQUIREMENTS.md) | Where | Test |
|---|---|---|---|
| R-7.1 | Assemble with Pika-generated audio | §1.3, §3 | E-T2 |
| R-7.2 | Transitions rendered where motivated | §1.9, §3 | E-T2 |
| R-7.3 | Music ducked under dialogue, rights recorded | §1.10, §7 | E-T8 |
| R-7.4 | SFX source + placement | §1.10, §7 | E-T8, E-T9 |
| R-7.5 | TH burned, timed to actual speech; tracks per language | §1.4/§1.5, §4 | E-T4 |
| R-7.6 | Variants, covers, three hooks | §6 | E-T7 |
| R-7.7 | End card with CTA | §1.8, §6 | E-T6 |
| R-12.8 | Recap opener (episode 2+) | §1.7, §6 | E-T6 |
| V3-AT-10 | Native audio; recap/CTA caps; loudness; shared timing | §3–§6 | E-T2, E-T4, E-T5, E-T6 |
| V3-AT-25 | Binding path 0/1/2 speakers; derivative sync | §8 | E-T3, E-T7 |

---

## 18. Risks and limits

- **Thai utterance alignment quality** drives caption timing; a poor aligner mis-times cues with no
  script fallback (by design). Mitigation: O-E3's qualification gate; findings surface mismatches.
- **Pika native-audio variance** (levels, ambience, artifacts) is D's output, not E's; E can only
  measure, gate and report — repair loops back to D. Expect loudness spread across clips.
- **ffmpeg determinism/version drift** (filters, encoder) — pinned build in the composition, recorded
  per report; replay compares hashes, so drift shows as a new EDL/output hash, never silent.
- **Host CPU**: E's exports are the heaviest local compute in the pipeline; the production
  composition must run the `edit` worker under the workspace CPU quota or renders starve the host.
- **Recap serialization**: requiring the predecessor's effective approval couples episode N's
  readiness to N−1's Gate 2. With the ≥2-day buffer rule (F §6.3) this is safe; a zero-buffer season
  sees `edit.recap_pending` blockers — visible, not silent.
- **edit_manifests reuse**: V3 rows beside V1 rows in one table — guarded by `require_workflow` and
  E-T1's byte-identity assertions; the residual risk is a future V1 writer bypassing the guard
  (A §1's inventory test covers the entry points).
- **zh translation quality** is B's pack text consumed verbatim; E's mismatch finding cannot fire for
  EN/ZH (observation is Thai) — EN/ZH correctness rides B's translation and Gate 2 review.

---

## 19. Alternatives rejected (one per major choice)

1. **New V3 edit tables** instead of reusing `edit_manifests`/`caption_tracks`: rejected — the seam
   is the one implementation F5 already assembles from (F §5), and a parallel store would drift from
   the gate conditions that already read these tables (FM §2).
2. **Recap cut from the predecessor's encoded master**: rejected — a re-encode of already-encoded
   audio (violates the no-re-encode rule), and it would bind the recap to a derivative rather than
   the production binding path V3-AT-25 names.
3. **Recap bound to the predecessor's current edit** (rebuild on any change) instead of its effective
   approval: rejected — every pre-publication re-approval of N−1 would force N−1-style rebuild churn
   across all successors; the approval is the honest dependency and matches the package validator's
   derivative rule (FM §2).
4. **Burned-in EN/ZH variants**: excluded by O-8 (F §1.9) — no per-language video variants.
5. **LLM-written CTA copy**: rejected — date-bearing content must rebuild deterministically from a
   calendar revision (F §8.2's handler is "deterministic from the new revision; no LLM",
   `phase-F-spec.md:785-786`), and an unapproved-extension promise is exactly the risk a template
   with a hard guard eliminates.
6. **Single-pass `loudnorm`**: rejected — dynamic normalisation is not reproducible; measured-gain is
   a pure function of the measured bytes (§5).
7. **Full §12.2 re-inspection of edited frames**: rejected — source frames carry inspection evidence
   from D; E adds the provenance-completeness check, and optional allowlisted sampling is O-E1.
