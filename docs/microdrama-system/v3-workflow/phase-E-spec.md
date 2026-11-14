# Phase E: Edit — native-audio assembly, derivatives, captions, loudness, the edit gate (v0.3 DRAFT)

Status: **v0.3 DRAFT**, 14 Nov 2026, GLM (weekend runbook). v0.2 → v0.3 applies the Codex round-1
critique ([codex-phase-e-critique.md](codex-phase-e-critique.md): PE-1..13 — seven BLOCKING
(PE-1..6, PE-8), six SHOULD-FIX (PE-7, PE-9..13); **all 13 ACCEPTED**) per
[phase-e-critique-rulings.md](phase-e-critique-rulings.md), each finding integrated individually per
its Replacement paragraph — the persistence/job-contract sufficiency of the second-key design is the
through-line (decision 15); no acceptance row was weakened (PE-12 redistributes two assertions to the
package that can actually prove them — E-T7/E-T10 — and labels the V3-AT-10/25 rows partial until
then). v0.1 → v0.2 applied the Goldfish consolidated review (1 Blocker / 21 Major / 43 Nit, all
ACCEPTED — every ruling a GLM ruling, Opus re-check Mon) per
[phase-e-goldfish-rulings.md](phase-e-goldfish-rulings.md). Chain: builds on **D** (no phase-D spec exists yet — verified, FM §8); feeds **F**
(`phase-F-spec.md` v0.4 §13 names E as its blocked prerequisite, `phase-F-spec.md:985-991`).
Precedence: `DECISIONS.md` > `REQUIREMENTS.md` > `SPEC-v3.md` v0.4.6 > accepted phase specs
(A0 v0.4, A v0.3, B v0.6, C v0.4.1) > this draft. Conflicts with any of those are open questions
(§16), never silent. Code facts cite today's tree (`feat/microdrama-m0-m4`) as `FM §n`
([e-factmap.md](e-factmap.md)) or `file:line`; anything this spec could not verify is `UNVERIFIED`.
Path shorthand: `S/<path>` = `microdrama/src/microdrama/<path>`; `M/00NN` =
`microdrama/migrations/00NN_*.sql` (so `M/0004:75` is line 75 of `0004_media_and_qa.sql`).

**E owns (SPEC §15.1/§15.2):** V3-AT-10, V3-AT-25 (`SPEC-v3.md:882`); R-7.1–R-7.7, R-12.8
(`SPEC-v3.md:934`; definitions `REQUIREMENTS.md:133-139,187`).

---

## 0. Scope

**Problem.** V3 episodes end step 6 with accepted native-render clips and nowhere to go: today's
editor **discards the clips' embedded audio** and lays separate TTS line assets plus a whole-timeline
generated room tone (FM §1); recap and CTA segments do not exist (FM §3); loudness is unmeasured
(FM §5); transitions are schema-only (FM §10); there is no `zh-CN` caption locale (FM §10); and F5 — the
teaser and the YouTube caption delivery — is blocked on exactly this phase's export/caption contract
(`phase-F-spec.md:985-991`).

**Phase E builds step 7 (tab 7, SPEC §4.7) for V3:**

1. **Native-audio EDL + caption remap** (R-7.1, R-7.5): clip audio as the one dialogue/ambience
   source, utterance-aligned cues, Thai burn + `th-TH`/`en-US`/`zh-CN` tracks.
2. **Transitions** (R-7.2): fade/xfade rendered in both exporters on a synchronised timeline.
3. **Recap binding** (R-12.8) and **CTA resolution** (R-7.7, V3R-6): duration-checked segments,
   each bound to its own authority — recap to the predecessor's effective approval, CTA to the
   calendar revision.
4. **Music placement + ducking** (R-7.3) and **SFX placement** (R-7.4), from C's accepted season
   libraries; per-episode SFX gap fills are E's only paid work.
5. **Loudness** (SPEC §4.7 mix line): target −14 LUFS integrated ±1 LU, true peak ≤ −1 dBTP —
   measured, evidenced, gated.
6. **The edit gate**: typed readiness blockers consumed by Gate 2 (F §4), and the pinned rebuild
   contract that F8's amendment closure waits on (PF-10, `phase-F-spec.md:776-791`).
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
   episode master's EDL**, not separate manifests; `locale` is unconstrained text (`M/0004:75`), so `zh-CN`
   needs no migration. V3 rows are written only by `S/editing_v3`; no V1/V2 row is touched
   (E-T1 asserts byte-identity).
3. **Native audio, end to end (V3C-15, R-7.1; SPEC §4.7:454-458).** Every placed clip contributes
   its embedded audio at its trimmed span — synchronised A/V trims (`in/out` identical for both
   streams). **No separate dialogue audio assets are created or laid** (today's
   `ref_id_for("line-audio", …)` path, FM §1, is V1-only), and **no synthesised replacement
   dialogue** exists anywhere in E. Ambience comes from the clips; the V1 whole-timeline `room.main`
   generated tone is **not used**. Generated room tone survives only as **inter-clip gap fill**
   (never under a clip — that would duplicate ambience), gain/config-owned, hashed into the session.
4. **Utterance alignment owns cue timing (SPEC §4.7:455, 457).** Thai cues are timed from
   **measured utterance windows inside the placed clip audio** — never whole-clip spans and never
   script estimates. **The alignment source is D's clip-QA word timings, a hard ED5 requirement** (a
   mandatory `ClipQaResult` field): SPEC §4.6 already makes Thai ASR word match a required per-shot
   check in D's clip QA (`SPEC-v3.md:439`, threshold `:964`), so the timings are a byproduct D
   computes for every accepted clip. E's `UtteranceAligner` seam shrinks to the **offline fake**
   that drives deterministic fixtures — no live aligner, no G qualification track (M-8). ED5 pins
   the **full line-addressable observation contract** (PE-7, §2.1): source-audio identity, observed
   text, speaker/line association, measured source-relative utterance/word spans and coverage — not
   word timestamps alone. Today's spotter keys on `dialogue_line_ids[0]` and caches the observation
   by audio SHA (`S/editing/captions.py:76-86`); a multi-line two-speaker clip cannot use that
   unchanged model — it stays V1, and V3's mapping is §4's. The
   field's exact shape is `UNVERIFIED` until D's spec pins it (no phase-D spec yet — ED5, §13
   prerequisites). All locales share the Thai windows (V3-AT-10 "ZH/EN tracks share the TH cue
   timing", `SPEC-v3.md:901`) — today's per-locale tracks already share `timeline_in_ms` by
   construction (`spot_caption_track`, `S/editing/captions.py:49-140`, spot-checked); E changes
   what the window measures, not the sharing rule. `timing_source` stays
   `ACTUAL_AUDIO_ALIGNMENT`; `derived_from_audio_sha256` binds the **clip audio** hashes. The
   speech-observation mismatch rule is unchanged: a cue carries what was actually spoken + a
   CRITICAL finding (`caption.audio_content_mismatch`, FM §4). **On mismatch the observed spoken
   text goes into every locale's cue — including `en-US`/`zh-CN`**; there is no per-locale
   carve-out, and E never invents a translation of wrong audio (today's rule, FM §4; mirrored in
   E-T4).
5. **Captions and the O-8 shape (R-7.5; SPEC §4.7:473).** One burned render, Thai only: `burn_locale`
   is config-owned and validated against `caption_locales` (FM §3) — V3 pins `th-TH`. CURRENT tracks for
   `th-TH`, `en-US`, `zh-CN`, each with its deterministic SRT asset (`srt_bytes`, FM §3). **No
   burned-in per-language variants** — excluded by the operator's O-8 ruling (F §1.9,
   `phase-F-spec.md:140-151`); F's `deliver_captions` binds these exact track assets for YouTube.
   `en-US`/`zh-CN` display text comes from B's packs (B §2.1); E never translates.
6. **Loudness is measured, normalised and gated (SPEC §4.7:473).** Target **−14 LUFS integrated
   ±1 LU, true peak ≤ −1 dBTP** on every audio-bearing released artifact — the five E-produced
   kinds (clean master, burned master, platform variants, hooks, episode-one preview; the canonical
   set is named once in §5). The PROMO_CUT teaser is the one audio-bearing released artifact E does
   not produce; its loudness owner is pinned in ED4 (F's `release_v3.teaser_cut` reuses E's
   `ebur128`/`LoudnessReportV3` seam), so the "every artifact" claim holds family-wide. Measurement:
   `ebur128` analysis pass per output. Normalisation: a **deterministic measured-gain stage**
   (`volume=<computed dB>` pre-encode), computed **per artifact** (§5) — never single-pass
   `loudnorm` (its dynamic mode is not reproducible across runs; §19 rejects it). Evidence: one
   `LoudnessReportV3` document per artifact (pre/post measurements, tool, streams, pass/fail),
   hash-sealed. **A failing report is a typed readiness blocker** (§9) — no Gate 2, no F.
7. **Recap: approval-bound, source-cut (R-12.8; SPEC §4.7:459; V3-AT-10).** A ≤10 000 ms (≤10 s)
   leading segment
   assembled from the **predecessor episode's packaged source shots** selected by B's `recap_plan`
   (`phase-B-spec.md:140`) — the same accepted shot assets the predecessor's master was built from,
   never a re-encode of its encoded master (§19). Binding = the predecessor's **effective Gate 2
   approval** (A §7.2 `effective_approval`) + the exact source asset id/sha set + the recap beat
   refs. Episode 1 has none (`recap_plan` empty, B §2.1). If the approval does not exist when the
   episode assembles, the session completes **without** the recap leg (typed blocker
   `edit.recap_pending`) and the recap splices in — a new manifest version under the same EDL
   discipline — once it does. All recap clips pass the same production binding path (§8).
8. **CTA: calendar-resolved, deterministic (R-7.7, V3R-6; SPEC §4.7:460-461).** A ≤5 000 ms (≤5 s)
   end card. Copy is **template-resolved Thai text** from the current calendar revision (proposed
   before editing, SPEC §9.2 item 1 `SPEC-v3.md:590-593`) + B's `cta` intent line
   (`phase-B-spec.md:145`): next-air-time, confirmed continuation (only when the extension decision
   exists), or finale follow — **never a promise of an unapproved extension**. No LLM writes copy
   (§19): F's rebuild handler for date-bearing content is deterministic by contract
   (`phase-F-spec.md:785-786`), so E's CTA must be too. Visuals: accepted image/title assets +
   licensed-font typesetting through the existing libass path. This is a **conscious deviation**
   from the poster seam's rule — the poster composes pre-typeset images with no live text in the
   filter graph, while the caption burn already uses libass (FM §3); C's §12.2 sign-off on the
   libass text surface is therefore requested in the crossing register (§15, O-E1's allowlist
   question). Audio: music tail from the cue sheet, no speech. Missing calendar ⇒ typed blocker
   `edit.cta_unresolved`.
9. **Transitions render (R-7.2; SPEC §4.7:462).** `TransitionKind` CUT/CROSSFADE/FADE_FROM_BLACK/
   FADE_TO_BLACK (`S/contracts/enums.py:351-356`; today never rendered, FM §10) renders via
   `xfade`/`fade` + paired `afade` **in both exporters** (master and variant/burned planners) on one
   synchronised timeline, honouring the DBR-2 overlap rule (`S/contracts/media.py:119-127`).
   **Selection is reconstructible (one precedence rule, M-5):** the per-boundary kind comes from
   D's `ShotPlanV3` when the boundary carries one (that is also where R-7.2's "where motivated"
   gets decided — motivation is D's plan choice), else the E config default pinned in the session's
   `transition defaults` digest. Cut and trim boundaries are **speech-safe**: no boundary lands
   inside an aligned utterance window (SPEC §4.5:422-423 "Edit may trim at measured, speech-safe
   boundaries"; the edit-side half of V3-AT-9's no-mid-word rule).
10. **Music/SFX placement consumes C's libraries (R-7.3, R-7.4; SPEC §4.7:463-472).** Cue sheets
    (`MusicCue`, `SfxAsset` — master §13 names them, `SPEC-v3.md:843`; B/C claim neither — E claims
    them, O-E5) place accepted library assets (MUSIC_LIB/SFX_LIB picks, C §0 item 7) on the episode
    timeline. **Ducking is deterministic**: a volume envelope computed from the EDL's dialogue/
    utterance windows — no dynamic compressor state, reproducible bit-for-bit from the session.
    Per-episode SFX **gap fills** ride C's qualified SFX route seam (§7 audio providers,
    `SPEC-v3.md:555-570`) as E's **only paid work**: SPEC §10.5 generation units, reserved against
    the episode's `step_07` budget (A §5.2 order), unknown price ⇒ refused (C §1.7 rule).
11. **E makes no LLM calls** (the C §1.11 pattern): assembly, alignment, cue sheets, recap/CTA
    resolution, loudness and checks are deterministic. Nothing in SPEC §4.7 requires an LLM in
    step 7 — A0's `LlmStep` is therefore not on E's path at all.
12. **Step 7 has no gate of its own; "the edit gate" is E's readiness computation, consumed by
    Gate 2** (SPEC §2 tab table, `SPEC-v3.md:116`). The human decision is Gate 2 (F). E computes
    **typed readiness blockers** (§9) and supplies recap/CTA previews into the Gate 2 page
    (F §4 item (d), `phase-F-spec.md:370-371`). Gate 2 **Revise on edit content** routes through A's amendment path
    (F §4: "targeting content routes to the owning phase's amendment path",
    `phase-F-spec.md:377-379`): E registers the deterministic timecode→shot/segment mapping and its
    rebuild handler rebuilds **only the noted units** (V3-AT-2, `SPEC-v3.md:893`). No `GateType`
    value is added; no new decision surface.
13. **The pinned rebuild contract (PF-10).** F8 registers E-owned edges "BLOCKED until E pins it"
    (`phase-F-spec.md:788-791`). E pins them here: A4 `DependencyProvider` edges (A4 = A §7.3's
    dependency-closure registry, [phase-A-spec.md](phase-A-spec.md) §7.3) + the `edit_v3.rebuild`
    handler for these edges: predecessor approval → successor recap; predecessor pack text revision
    → successor recap captions (M-3's guard); calendar revision → CTA copy/media; source shot
    asset / `ShotPlanV3` revision → assembly; music/SFX library revision → cue sheets; caption
    source text revision → tracks. Rebuild = deterministic reassembly producing
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
15. **Crash-resume is replay of a durably recorded outcome, not regeneration (SPEC §10.5:720-728)
    — and the execution identity covers the mix and every output-changing input (B-1; PE-1..PE-4).**
    V3 assembly identity is the **execution identity**:
    - the **V3 layout hash** — one hash over the episode's layout decisions: ordered source
      bindings (`clip_id`, `source_asset_id`, the native-audio binding), source spans (`in/out`),
      timeline placement, crops, output format and **transition kind and duration** per boundary
      (PE-4). This supersedes V1's narrower per-clip EDL-hash list, which omits timeline placement,
      crops and transition duration (`S/editing/edl.py:234-253`; the variant hash likewise omits
      transitions, `S/editing/variants.py:237-243`). Music/SFX placement is **outside** the layout
      hash by design: mix decisions live in the immutable cue sheets (§2) and are covered by the
      mix digest. The layout hash stays **pure** (same session inputs ⇒ same hash, §3).
    - the **mix digest** — a `canonical_hash` over the music cue-sheet version, the SFX cue-sheet
      version, the gap-fill config **and the loudness/normalisation configuration** (PE-4) —
      **replaces V1's `line_sha`** (which mapped V1's separate line-audio assets; V3 creates none).
    - **applicable artifact recipe inputs** (PE-4): the caption/burn recipe (text source,
      alignment, style, font inputs) for burned renders; the crop/variant spec for variants; the
      hook window spec for hooks. Caption/burn recipes are covered by the burned artifact's own
      identity, not by the layout hash.
    - the **tool recipe** (the pinned ffmpeg build and its filter/encoder arguments, phase G's
      composition) is part of the execution identity (PE-4): tool drift is a **new execution
      identity**, never a silent replay under the old one.

    **Output identities derive from the execution identity (PE-1).** V3 manifest execution IDs,
    output asset IDs and object keys distinguish `(layout hash, mix digest)` and the applicable
    artifact recipe inputs — they never collide across a mix-only change the way V1's do
    (`master_asset_id_for` depends only on the EDL hash, `S/editing/edl.py:39-41`; burned IDs add
    only the caption hash, `:43-45`; object keys hash only the EDL, `S/editing/service.py:1069-1072`;
    and persistence reuses an existing manifest ID for changed bytes, `S/editing/service.py:1155-1179`).
    **A changed mix appends a manifest version and preserves prior outputs** — prior versions stay
    intact and replayable under their own execution identity. **V1 identity functions remain
    unchanged**; V3 derives its own IDs in `S/editing_v3`. A cue-sheet-only `adjust_mix` bumps the
    mix digest and produces **new outputs, never a replay** (asserted in E-T2), while mix inputs
    never leak into the layout hash (no ordering hazard). The **measured loudness gain is a function
    of rendered bytes, not session inputs**: it is computed per artifact at export and recorded
    **inside the replayed outcome** (the `LoudnessReportV3` document), never in any key.

    **The replayed outcome is a durable record, not a reconstruction (PE-3).** An immutable
    **`AssemblyOutcomeV3`** (§2) is persisted — indexed by its complete execution identity and
    written **atomically with canonical artifact installation** — naming the exact manifest,
    asset, caption-track and report versions plus the recorded checks/findings. Replay verifies
    those references and current authority; it **never substitutes arbitrary CURRENT tracks or
    clears findings** (V1's `_replay_outcome` reconstructs from the latest matching manifest,
    *current* caption tracks and lineage and returns empty findings/checks,
    `S/editing/service.py:1340-1395` — that behavior stays V1). Plus content-addressed
    `register_asset` idempotency (FM §7) — a restart never re-renders a stored outcome, and a
    crashed export leaves nothing registered (registration happens only after decode/stream/
    duration checks pass, FM §9). SFX fills follow SPEC §10.5 fully (immutable inputs, semantic
    attempt id, reservation, reconcile before resubmit). **This decision is pinned in the E2 note
    before build** (E2 is critiqued first; PE-12 retains that pin).

---

## 2. Records (contract package, guardian-owned bump; symbolic migrations `E-1…`)

V3 edit documents live in one new append-only, versioned, hash-sealed store **`v3_edit_documents`**
(`E-1`), mirroring B/C/F's stores, accessed through the store accessor **`EditV3Store`** (§13's
build contract names this accessor over `v3_edit_documents` — not a second object or a rename): PK
`(contract_type, record_id, version)`, one `current` row, hash re-verified on read,
`contract_type` allowlist CHECK, standard guards,
`record_id = uuid5(EDIT_V3_NS, "<type>:<season_id>:<episode_id>[:<key>]")`. `v2_contract_documents`,
`v3_story_documents`, `v3_cast_documents`, `v3_release_documents` are not touched.

| Migration | Object | Decisive columns / rules |
|---|---|---|
| `E-1` | **`v3_edit_documents`** | the edit document store above; guarded |
| `E-2` | lane + queue plumbing | `jobs.queue` CHECK gains `edit` (`M/0001:77` today: `production/publication/community` + A/B/C/F additions — re-audit the tail at E1); `reservations.queue` carries the same closed CHECK and is **not** grown — safe only because edit-lane jobs never reserve (decision 14; the one reserving E job rides C's `media` lane), an invariant asserted in E-T1; reservations/charges ownership for `step_07`; worker set; generated contracts (A §4 checklist) |

No other migration. Verified in particular: `edit_manifests.purpose` needs no new value (recap/CTA
are embedded clips, decision 2); `caption_tracks.locale` is unconstrained text (`M/0004:75`);
`SlotKind` already carries `PROMO_CUT`/`HOOK` for F's teaser and E's hooks (`S/contracts/enums.py:430-434`).

**Documents in `v3_edit_documents`:**

| Record | Key | Content |
|---|---|---|
| `EditSessionV3` | `session` (one current per episode) | the episode's edit session: `shot_plan_ref` (D's `ShotPlanV3` version) + the **shot→asset binding map** (shot_id → {asset_id, sha256, measured duration} — the production binding path's inputs, FM §7); script/manifest refs; the predecessor recap binding (approval event ref + source asset set + beat refs + **the predecessor pack hash**, M-3) or `recap_pending`; `music_lib_revision`/`sfx_lib_revision`; `calendar_revision` for CTA; the V3 edit config digest (locales, gap-fill gain, loudness targets, transition defaults); state is **derived, never stored** (AR-4 — phase-A-spec's architecture-rule appendix: side states are derived, never stored) |
| `CtaResolutionV3` | `cta:<episode_number>` | kind (`NEXT_AIR_TIME` \| `CONFIRMED_CONTINUATION` \| `FINALE_FOLLOW`), the resolved copy (Thai), the calendar revision + hash it depends on, the accepted image/title asset refs, duration_ms (≤5 000, validator), font/provenance refs |
| `MusicCueSheetV3` | `music:<episode_number>` | `MusicCue[]`: library asset ref (id/version/sha), timeline in/out, loop/duration target, gain_millibel (bounds `S/contracts/media.py:95`), duck profile (depth/ramp), derivation of the duck envelope; the sheet's **version is an input to the mix digest** (decision 15) |
| `SfxCueSheetV3` | `sfx:<episode_number>` | `SfxAsset[]`: library-or-filled asset ref, timeline point/span, gain, the gap key (for fills: the generation-unit reference with attempt id + receipt ref); the sheet's **version is an input to the mix digest** (decision 15) |
| `LoudnessReportV3` | `loudness:<artifact asset_id>` | artifact kind + asset ref, measured integrated LUFS + true peak (pre), applied gain dB, measured post values, analyser tool + version, streams analysed, pass/fail vs targets |
| `AssemblyOutcomeV3` | `outcome:<layout hash>:<mix digest>` | the complete durable assembly outcome (decision 15, PE-3), written **atomically with canonical artifact installation**: exact manifest id/version, output asset ids + shas (clean, burned, variants, hooks, preview), caption-track ids + body hashes per locale, loudness report ids, the recorded `TechnicalCheck`s and findings, the job id; indexed by the complete execution identity. Replay reads this record and verifies every named reference (asset sha, track body hash) and current authority — it never substitutes arbitrary CURRENT tracks or clears findings |

**Reused as the single implementation, extended (M-1):** `edit_manifests`, `caption_tracks`,
`assets` + `asset_lineage` (append-only, FM §7), `hook_experiments` (FM §3), `FFmpegRunner`
(FM §1), `gate2_blockers`' caption conditions (F consumes, FM §2), and the `S/editing` seam
modules — **reused as the single implementation, extended in place with V3 branches beside the
unchanged V1 paths; V1 planner outputs stay byte-identical, asserted at every package gate
(E-T1)**. Marking (the phase-F §13 idiom, applied per package in §13): seam modules
`S/editing/{edl,export,variants,hooks,captions}.py` = **Modify** (V3 branches added in place, never
forked into a parallel implementation). `hooks.py` and the cropped exporter are Modify specifically
because their V1 contracts are **incompatible with native audio** (PE-6): `build_hook_edl` requires
a continuous room bed, slices video arbitrarily, drops boundary dialogue separately and
reconstructs dialogue tracks (`S/editing/hooks.py:245-339`), and the cropped exporter requires room
tone (`S/editing/variants.py:433`) — the V3 branches (§6) sit beside the **unchanged V1 branches**.
V3-only code = **Create** in `S/editing_v3/`; the tables
above = **Reuse** (no schema change — decision 2).

**Re-registered for V3 (not unchanged):** the QA `qa.technical` job — today it runs at pipeline
stage W07 on the master (`S/pipeline/runner.py:500-524`, FM §9); E7 re-registers it for V3
episodes through A's job system with its contract unchanged, plus the ASR caption cross-check
(§15).

### 2.1 E contract crossings (the C-B1 pattern, C §2.2 / F §2.2)

Every E identifier crossing an A/B/C/D/F-enforced contract, checked **before the E1 note is
accepted**; declared rows are requests to the owning phase's register, not edits to their specs:

| # | Delta | Contract touched | Mechanism |
|---|---|---|---|
| ED1 | Queue lane `edit` | A0/A3's `jobs.queue` CHECK | `E-2` grows the CHECK; ownership/worker/contracts land with E1 (mirrors C's CD1 / F's FD2) |
| ED2 | E consumes `EpisodePackV3` fields (`recap_plan`, `cta`, line text per locale, beat vocabulary) read-only; **for recap captions only, also the predecessor episode's pack line text per locale, keyed by the recap beats' `line_ids`** (read-only B crossing, M-3) | B §2.1/§2.3's field mapping and consumer order (`phase-B-spec.md:133-210`) | declared for B: E is added to B §2.3's reader order; E validates against B's published validators, adds none; the predecessor pack hash is recorded in the recap binding and a predecessor pack text revision is a registered rebuild edge (decision 13), so a post-approval revision of N−1's pack cannot leave N's recap cues silently stale |
| ED3 | E consumes C's accepted music/SFX libraries and, for gap fills, C's qualified SFX route seam + `media` lane | C §0 item 7, C §10 (`phase-C-spec.md:698-699`), C §2 pick kinds | declared for C: E needs a **library manifest shape** (per-cue mood/duration/loop metadata) — O-E4; E's `sfx_fill` jobs ride C's `media` lane with E-owned `step_07` metering |
| ED4 | F embeds E's outputs: recap/CTA previews + readiness blockers on the Gate 2 page; `deliver_captions` binds E's exact track assets; F8's BLOCKED edges unblock; **the teaser's loudness owner is pinned (M-7): F's `release_v3.teaser_cut` reuses E's `ebur128`/`LoudnessReportV3` measurement pattern, declared as a reusable seam — `phase-F-spec.md` v0.4 contains no loudness content (verified), so without this pin the PROMO_CUT teaser is the one released audio-bearing artifact with no loudness owner** | F §4 item (d), F §1.9, F §10 `deliver_captions` (`phase-F-spec.md:931`), F §8.2 PF-10 | declared for F: E pins the track-asset contract (locale tags, SRT bytes, CURRENT state, `derived_from_audio_sha256`), the readiness-blocker vocabulary, and the teaser-loudness seam reuse (a 30–60 s multi-episode re-cut measures its own integrated LUFS — §5's per-artifact rule); F's F5/F8 wire their side |
| ED5 | E consumes D's `ShotPlanV3`, the shot→asset binding evidence, and clip-QA utterance/word timings | D's contracts (no phase-D spec yet — FM §8) | declared for D: E requires per-shot binding evidence {asset_id, sha256, duration, speaker count 0/1/2} plus **D's exact shot/render acceptance correspondence** — which accepted render belongs to which shot, its source SHA and its required media streams (the native audio stream above all; PE-11) — and, **before E1** (PE-7), the full **line-addressable observation contract** (M-8, decision 4 — not "ideally"): per clip, source-audio identity, observed text, speaker/line association, measured **source-relative** utterance/word spans and coverage — word timings alone do not establish timestamp capability or line association — since SPEC §4.6:439 already requires Thai ASR word match per shot. E validates defensively and blocks with a typed blocker (`edit.binding_incomplete` / `edit.alignment_missing`, §9) on any gap — it never guesses a binding and never falls back to script timing |

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
   still/clip segment; transition events between clips (per-boundary kind by decision 9's
   precedence: D's `ShotPlanV3` when the boundary carries one, else the E config default);
   music/SFX cue events attached to timeline spans (their content and placement are **outside** the
   layout hash — mix decisions live in the immutable cue sheets, decision 15). The **V3 layout
   hash** covers ordered source bindings, source/timeline spans, crops, output format and
   transition kind/duration per boundary (decision 15, PE-4), so any change to the clips, their
   audio binding, their placement, their crops or their transitions is a new layout — no silent
   re-cut. The hash stays **pure** (B-1): cue-sheet content, gains, placement, gap-fill and
   normalisation config are outside it by design — they key the **mix digest**, the execution
   identity's second component (decision 15) — so a mix-only change produces new outputs under the
   same layout hash: **a new manifest version with prior outputs preserved** (PE-1), never a silent
   no-op and never a silent remix.
3. **Export graph** (`plan_master`'s V3 branch): video trims/scale/pad/fps/format + transitions →
   concat; audio = per-clip `[i:a]atrim…,adelay=…` sources (replacing V1's per-line dialogue
   sources, FM §1) + gap-fill tone spans + music bus (cue sheet envelope applied as `volume`
   expressions) + SFX bus; `amix=inputs=N:normalize=0:duration=longest` (the existing mix rule,
   `S/editing/export.py:118`) followed by the loudness gain stage (§5). Master encode unchanged in
   shape (`libx264`/`aac`, FM §1) — **source assets are never re-encoded into intermediates**.
   **Export discipline (PE-9):** analysis/pre-measurement runs on immutable source bytes; the
   final **normalised** export encodes each artifact's audio **once**; the burned render **copies
   the clean master's finalised audio stream** into its video re-encode (`-c:a copy`, FM §1).
   Variants/hooks/preview are cropped re-encodes — today's cropped exporter already encodes AAC
   independently (`S/editing/variants.py:497-538`) — so each carries its **own** final audio
   encode, measurement and gain (§5). E pins, per artifact kind in the session, whether it copies
   the master's finalised audio or encodes its own; no artifact's audio provenance is implicit.
4. **Caption tracks** (§4) and **derivatives** (§6/§8) from the same EDL.

**Determinism:** same session inputs ⇒ same layout hash ⇒ same bytes (seeded generators only — the
gap fill reuses the seeded `anoisesrc` pattern, FM §1). The **mix digest** — a `canonical_hash`
over the music cue-sheet version, the SFX cue-sheet version, the gap-fill config and the
normalisation configuration (PE-4) — is the execution identity's second component (decision 15):
the pair (layout hash, mix digest) plus the applicable recipes identifies one complete stored mix,
and the measured loudness gain rides inside the stored outcome, never in a key. CPU: ffmpeg runs are
the heaviest E work; the production composition runs the E worker under the workspace CPU quota
(phase G — the SPEC §15 phase that completes and qualifies the production composition and its live
switches, `SPEC-v3.md:871`; offline tests use small fixtures — §14 build constraints).

---

## 4. Captions (R-7.5; V3-AT-10)

- **Timing:** utterance windows from the placed clip audio (decision 4). E maps **every included
  utterance** of each clip — line-addressable, not the first line only (today's spotter keys on
  `dialogue_line_ids[0]` and caches by audio SHA, `S/editing/captions.py:76-86`; V1 keeps that
  model) — through trims and transitions into Thai master cues, then **copies those windows** to
  `en-US`/`zh-CN`. Repeated placements of one line and predecessor (recap) line ids get **distinct
  cue-id namespaces** (PE-7). Simultaneous speech in a two-speaker clip: each utterance keeps its
  own measured span and its own cue — overlapping cues overlap; they are never merged and never
  dropped (exact serialization pinned in the E3 note). Missing alignment for any included
  utterance **blocks** with the typed blocker `edit.alignment_missing` (§9) — E never falls back
  to script timing (PE-7). The existing spotter's floor/clamp rules (`min_cue_ms`, tail pad,
  clamp-to-next; FM §4) apply **within** the aligned window. Thai is the master timing;
  `en-US`/`zh-CN` tracks reuse the identical windows.
- **Text:** `th-TH` = B's Thai line text; `en-US`/`zh-CN` = B's pack text verbatim. **Mismatch
  carve-out (decision 4, M-4):** when the Thai observation mismatches, **every** locale's cue —
  including `en-US`/`zh-CN` — carries the observed spoken text plus the CRITICAL finding
  (`caption.audio_content_mismatch`, FM §4 — today's rule; there is no per-locale carve-out, and E
  never invents a translation of wrong audio). E adds no text of its own except the burned style.
- **Locales:** V3 config `caption_locales=("th-TH","en-US","zh-CN")` (V1 config is untouched,
  `S/editing/config.py:46`). The exact delivery tag (`zh-CN` vs `zh-Hans`) is O-E2
  (recommendation `zh-CN`).
- **Deliverables:** per locale one CURRENT `caption_tracks` row with its SRT asset (content-addressed,
  FM §3) — this is **the exact-bound set F's `deliver_captions` binds** (ED4). The burn uses
  `th-TH` only (`burn_in_caption_track_id`, `e-factmap.md:128` context note). No burned `en-US`/
  `zh-CN` variants (O-8).
- **Staleness/rebuild:** the existing line-sha staleness rule (T019, FM §4) extends to the V3
  sources: a cue is stale if its clip audio sha or line text changed — handled by the rebuild
  contract (decision 13), never by editing a track in place (`caption_tracks` body is immutable,
  `M/0004:88-89`).

---

## 5. Loudness (SPEC §4.7:473; V3-AT-10)

The canonical artifact set (decision 6): **clean master, burned master, each platform variant,
each hook, the episode-one preview** — the five E-produced kinds; the PROMO_CUT teaser is F's and
is pinned in ED4.

- **Measure:** `ebur128` analysis per audio-bearing output of that set — integrated LUFS and true
  peak, both persisted in `LoudnessReportV3`. Today nothing measures loudness (FM §5: only peak dB
  and static gains exist).
- **Normalise (per artifact, M-2):** compute the gain in dB from **that artifact's own measured
  bytes** (target −14 LUFS integrated), clamp (config-owned bound), apply as the final `volume=`
  stage before the encoder in that artifact's export; re-measure each output. Integrated LUFS over
  a re-cut sub-span is not the episode's integrated LUFS, so the 20–40 s hooks and the preview
  carry **their own measured gain**. Copy versus encode is explicit per kind (PE-9, §3): the
  burned master copies the clean master's **finalised** audio stream and therefore its
  post-normalisation measurement; independently encoded artifacts (variants, hooks, preview —
  cropped re-encodes, `S/editing/variants.py:497-538`) normalise on their **own** measured gain.
  Still deterministic — a pure function of the measured bytes. A true peak above −1 dBTP after the
  gain clamp fails typed (blocker `edit.loudness_fail` with measurements) rather than silently
  limiting.
- **Recovery (the gate never dead-ends an episode at step 7; PE-8):** a per-artifact gain removes
  the systemic mis-targeting; a residual fail after the clamp exposes a **pre-Gate-2 recovery
  through `rebuild_edit_media`/A4** (§11): amend the affected cut, mix or source shot, then
  regenerate the dependent artifacts and reports — new versions (decision 13), never in-place
  edits. Gate 2 Revise uses the same path once the episode reaches Gate 2 (a loudness failure
  blocks readiness, so the episode cannot reach Gate 2 to Revise from — Revise is never the only
  route out of step 7). Configuration changes (the clamp bound, the targets) are **versioned
  dependencies**: they change the mix digest (normalisation config, decision 15) and produce new
  outputs. Raising a gain clamp cannot in general satisfy integrated loudness and true peak
  simultaneously for high-crest-factor audio — a derivative still outside the limits after the
  permitted scalar gain fails typed and recovers through content amendment, never through a bigger
  clamp.
- **Gate:** readiness requires every artifact's report PASS (−14 LUFS integrated ±1 LU, true peak
  ≤ −1 dBTP). The report is the evidence F/phase G can audit later; nothing is asserted without it.
- **Determinism:** analysis and gain are pure functions of the audio bytes; no dynamic normaliser
  state; the ffmpeg build is pinned by the composition (phase G), recorded in the report.

---

## 6. Derivatives: recap, CTA, variants, hooks, teaser input (R-7.6, R-7.7, R-12.8)

- **Recap** (decision 7): clips from the predecessor's packaged source shots per `recap_plan`
  beats; ≤10 000 ms enforced by contract validator + config constant (FM §6: rule absent in code
  today); native speech of the selected shots is kept (a recap line's cue uses the same alignment
  path); all sources pass the binding validator with the predecessor's package hash recorded.
  **The recap consumes the pack, alignment and source set bound to the predecessor's *effective
  approved package*** (A §7.2 `effective_approval`; PE-11) — never a newly-current, unapproved
  predecessor pack, which would pair unapproved text with old approved speech.
  **Caption provenance (M-3):** recap cues' text comes from the **predecessor pack's line text per
  locale, keyed by the recap beats' `line_ids`** (ED2 — the current episode's pack holds beats with
  estimated durations, not the predecessor's dialogue text, so this crossing is what makes recap
  cues producible without tripping the mismatch rule). Three guards ship with it: (a) the
  predecessor pack hash is recorded in the recap binding; (b) "predecessor pack text revision →
  successor recap captions" is a registered rebuild edge (decision 13); (c) **supersession
  invalidates the binding** (PE-11): a post-approval revision of N−1's pack supersedes the approval
  N's recap is bound to — until a replacement approval is effective, N's recap shows
  `edit.recap_pending` (binding invalidated, never silently stale and never rebound to unapproved
  text); once the replacement approval is effective, the registered edge rebuilds N's recap
  captions from the new approved package.
- **CTA** (decision 8): ≤5 000 ms enforced; copy/visuals deterministic from `CtaResolutionV3`;
  date-bearing ⇒ the calendar revision is part of its hash.
- **Variants/covers/hooks/preview** (R-7.6): the existing derivative machinery (FM §3) re-runs on
  the V3 EDL through V3 adapters — variants re-frame without touching audio placement
  (`build_variant_edl`'s rule, FM §3), hooks keep the 20–40 s payoff-window rules, the preview keeps
  `PREVIEW_MAX_MS` (FM §6). **V3 hook/preview cuts (PE-6): measured speech-safe windows, not
  arbitrary slices** — each selected clip's **embedded audio is retained exactly once**, every
  included utterance/cue is remapped onto the new timeline, and boundary transitions are preserved
  or recomputed. Today's `build_hook_edl` cannot do this: it requires a continuous room bed, slices
  video arbitrarily, drops boundary dialogue separately and reconstructs dialogue tracks
  (`S/editing/hooks.py:245-339`), and the cropped exporter requires room tone
  (`S/editing/variants.py:433`) — both are **Modify** with unchanged V1 branches (§2); a source cut
  that would bisect speech is refused (speech-safe boundaries, decision 9). Each re-encoded output
  gets a loudness report (§5). Hooks/variants burn Thai; they carry **no** per-locale tracks
  (O-E6's ruling).
- **Teaser input for F (PROMO_CUT):** E produces no teaser. E's contract to F5 (ED4) is that every
  approved episode exposes, at clip granularity: its EDL (source bindings + speech-safe boundaries +
  utterance windows) and its accepted assets — exactly what `release_v3.teaser_cut` assembles from
  (`phase-F-spec.md:447-452`). E guarantees addressability; F guarantees the cut — and, per ED4,
  F's cut carries the loudness obligation through E's measurement seam (M-7).
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
  (`adjust_mix`, §11) — edits are new document versions, hashed, and never touch the library.
- **Ducking:** envelope from utterance windows (music gain dips under dialogue, ramps
  config-owned); computed, stored in the cue sheet, applied in the export graph — reproducible.
- **Gap fills:** SFX needs the library does not cover ride `edit_v3.sfx_fill` on C's `media` lane
  (ED3): one SPEC §10.5 generation unit per gap (immutable inputs, semantic attempt id,
  reservation against `step_07`/EPISODE, provider op through C's qualified seam, reconcile before
  resubmit). The adapter is the offline fake; live needs the C-qualified route and price — unknown
  price ⇒ refused, never zero-priced (C §1.7).

---

## 8. Binding and synchronization (V3-AT-25; `SPEC-v3.md:916`)

- **The binding path is the existing one, made authoritative (PE-11).** Today's `_shot_sources`
  checks kind/state/duration only (`S/editing/service.py:556-578`) — it cannot tell an *unrelated*
  accepted VIDEO from the shot's own render. V3 validates each mapping against **D's exact
  shot/render acceptance evidence** (ED5): the asset must be the render D accepted **for that
  shot**, its source SHA must match, and its required media streams (the native audio stream) must
  be present; sha recorded, layout hash covers the binding. E's acceptance drives
  **zero-, one- and two-speaker** clips through it — D supplies the binding evidence (ED5); E
  validates and blocks with a typed blocker (`edit.binding_incomplete`) on any gap. Recap sources
  add the predecessor-package binding (§6, PE-11).
- **Synchronization invariants, checked at assembly and per derivative:** A/V trims identical per
  clip; cue windows inside measured utterance windows; derivation checks (§6); recap/CTA included
  (they are clips/cards on the same timeline). A violation is a CRITICAL finding blocking readiness.
- **What E records for D and F (SPEC §12.2 consumers):** for D — binding-validation outcomes and
  audio-side findings (mismatch, silence, alignment gaps) routed back as QA findings for repair;
  for F — the readiness blocker vocabulary, recap/CTA previews, track assets, loudness reports, and
  the rebuild edges (ED4).

---

## 9. The edit gate: readiness, Gate 2, Revise, rebuild (PF-10)

- **Readiness** (`edit_readiness(episode)`, derived, never stored — AR-4): typed blockers, each
  with its evidence ref, named by their typed constants: `edit.binding_incomplete` (§8);
  `edit.recap_pending` (decision 7 — covers a missing predecessor approval, an unbound recap and a
  **superseded/invalidated binding** (PE-11); "unbound" is not a separate state);
  `edit.cta_unresolved` (decision 8); `edit.alignment_missing` (§4, PE-7);
  `edit.duration_out_of_band` — the operand is the **assembled master total** (story body + recap +
  CTA, net of transition overlaps) against B §2.1's episode band (`phase-B-spec.md:149,159`), with
  recap/CTA caps (§6) and the export ceiling (FM §6) as their own checks; any open CRITICAL finding
  (caption mismatch, decode, streams); `edit.loudness_fail` (§5); `edit.caption_track_missing` (no
  CURRENT track for any locale); `edit.derivation_failed` (§6); `edit.provenance_incomplete`
  (§15). **Readiness resolves an explicit required artifact/check inventory (PE-10):** for the
  current session and authority — the complete §5 master/derivative set, a loudness report for
  every required output, CURRENT caption tracks for every locale, and the completed required
  technical/ASR checks. **Missing, stale, UNKNOWN or incomplete artifacts, reports and required
  checks block** ("every report passes" is never vacuously true before the reports exist), and
  **caption IDs, loudness reports and derivation evidence must match the installed assembly** —
  presence of a CURRENT track alone does not prove it belongs to the current execution identity.
  **Empty ⇒ step 7 done:** E claims, through A's transition API, the production-track
  transition that closes step 7 (exact state names pinned in the E1 note against A's vocabulary),
  and the episode becomes available to F's step 8. **Data-flow endpoints (N-1):** A's scheduler
  (A6b, `phase-A-spec.md:448`) observes step-6 closure and dispatches `edit_v3.assemble` onto the
  `edit` lane; `edit_readiness` is re-evaluated whenever an E job completes, and again when Gate 2
  packages the episode — derived blockers materialize as typed conditions in that Gate 2 review
  package (F §4).
- **Gate 2 relationship:** F's V3 Gate 2 runs through A's decision transaction (F §4) and consumes
  E's readiness through the Gate 2 review package (the review bundle F assembles — the caption
  conditions already in `gate2_blockers`, FM §2, plus F's V3 additions; not a §13 build package).
  E registers no gate, adds no `GateType`, and never approves content.
- **Revise (V3-AT-2 "Revise regenerates only the noted units"):** Gate 2 EPISODE_FINAL Revise keeps
  A's timecoded-feedback contract (F §4/PF-9); E registers the deterministic map timecode →
  shot/segment/cue-sheet unit. Targeting edit content routes through A's amendment coordinator
  (`phase-F-spec.md:377-379`); the coordinator's Apply fences affected E jobs (A §7.3), and the
  operator's `rebuild_edit_media` command (§11) funnels through that same coordinator queue — never
  a side channel beside it (N-5). E's rebuild handler re-derives **only** the noted units' inputs
  (e.g. one shot's re-edit leg), leaving untouched units' manifest versions byte-identical —
  asserted in E-T7.
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

- **Job identity (PE-2):** each assembly payload **freezes** the session reference/version, the
  layout-hash inputs (EDL), the cue-sheet versions (mix) and the authority references
  (`expected_content_revision`, the calendar revision, the predecessor approval ref). The
  **semantic key** distinguishes execution inputs and content authority — a changed mix is a new
  semantic key, never a conflict — while `logical_work_id`
  (`edit-assemble:<season>:<episode>`) stays **stable across replacements**. **Retries preserve
  payload/key/scope** (A1 §2.4's replay check compares the complete work scope, so re-use of a
  semantic key for different input or scope raises `IdempotencyConflict` through real
  `JobService.enqueue`, `S/core/jobs.py:429-440`). **Deliberate replacement records
  `replaces_job_id`** (A §3): an already-successful assembly is never re-run for changed inputs —
  the change enqueues a new job under the same `logical_work_id`. Asserted in E-T2.
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
| `adjust_mix(episode, cue edits, expected revision)` | Operator (human session + CSRF) | session current; validators pass | an **effective mix change enters A4's scoped amendment path** (PE-5): appends `MusicCueSheetV3`/`SfxCueSheetV3` versions, and the coordinator's Apply **freezes the replacement inputs** (the new cue-sheet versions + mix digest), **fences the affected E work and invalidates dependent unpublished authority atomically** — published media remains immutable (A §7.3) — after which `edit_v3.assemble` is enqueued with the new execution identity: a cue-sheet-only change bumps the **mix digest**, not the layout hash, and produces new outputs, never a replay (decision 15, B-1; asserted in E-T2/E-T8). "Session current; validators pass" alone is **not** a side channel: an adjustment touching approved content routes through the same amendment path (supersession), never beside it (N-5) | `edit.mix_adjusted` | idempotency key |
| `rebuild_edit_media(episode, cause, expected revision)` | Operator (human session + CSRF) | readiness or Gate 2 Revise noted the units | funnels through A's amendment-coordinator queue (A §7.3 fencing — §9); runs the §9 rebuild handler for the noted cause/units only | `edit.rebuilt` | idempotency key |

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

Prerequisites: A0–A6 accepted, and B and C accepted. **D accepted** — or, before that, the D seams
E validates against pinned by D's spec (ED5); E1 may not start before that contract exists. F
v0.4's F5/F8 unblock only when E is accepted **and its export/caption contract is pinned** — and
the PF-10 edges are pinned by E7's registration, not at acceptance (F §13,
`phase-F-spec.md:985-991`). Real migration numbers are allocated in the E1 note after re-auditing
the migration tail; **applied migration bytes are never edited**.

Items are marked **Create / Modify / Reuse** (the phase-F §13 idiom; the seam-level rule is §2's).

| Package | Builds | Gate | Design note |
|---|---|---|---|
| **E1** | **Create**: `E-1`/`E-2` migrations, the `EditV3Store` accessor (§2), contracts bump (documents, readiness-blocker vocabulary), the §2.1 crossing register delivered, `require_workflow` guards on the V3 branch. **Reuse**: A §4's queue-checklist plumbing | E-T1 | **Critiqued first** (migrations + crossings) |
| **E2** | Native-audio EDL + export graph. **Modify**: the `S/editing` seam planners in place (`edl`/`export` — V3 branches beside unchanged V1 paths; V1 outputs byte-identical, asserted at every gate). **Create**: `S/editing_v3` adapters, clip-audio sources, synchronised trims, gap fill, transitions in both exporters, the `UtteranceAligner` offline fake, session/binding validation, the execution identity (layout hash + mix digest, decision 15), the durable `AssemblyOutcomeV3` replay record (§2, PE-3), the frozen-payload/job-identity rules (§10, PE-2), the provenance-completeness gate (§15 — O-E1's recommendation, now assigned) | E-T2, E-T3 | **Critiqued first** (the deterministic core; decision 15 pinned in the note before build) |
| **E3** | Captions V3. **Modify**: `S/editing/captions.py` in place (window source; V1 byte-identical). **Create**: the `zh-CN` locale wiring and the mismatch carve-out (decision 4). **Reuse**: `caption_tracks` + the SRT asset path; staleness rules | E-T4 | With the diff |
| **E4** | Loudness. **Create**: measurement, `LoudnessReportV3`, the `edit.loudness_fail` blocker wiring; **normalisation/report generation is proven on supplied fixture artifacts at this gate — complete every-artifact coverage and readiness are proven at E7** (PE-12). **Modify**: the V3 export branch (the per-artifact gain stage, §5) | E-T5 | With the diff |
| **E5** | Recap + CTA. **Create**: bindings (predecessor pack hash + line text via ED2), templates, calendar dependency, duration validators, previews — recap **binding/rendering** is proven here; its registered rebuild edge is proven at E7 (PE-12) | E-T6 | With the diff |
| **E6** | Music/SFX cue sheets, ducking, `sfx_fill` on C's seam. **Create**: the `adjust_mix` command (§11) — the **command→enqueue→new-output path** is proven here (PE-12); the second-key behavior itself is already proven at E2 with immutable cue-sheet fixtures | E-T8, E-T9 | **Critiqued first** (money) |
| **E7** | Derivation checks, variants/hooks V3 wiring (hooks.py + the cropped exporter, PE-6), readiness — **the complete required artifact/check inventory (§9, PE-10)** — + production-track transition, A4 edge registration + `edit_v3.rebuild` (PF-10). **Re-register**: the `qa.technical` job for V3 + the ASR caption cross-check (§15) | E-T7, E-T10 | **Critiqued first** (amendment races) |
| **E8** | **Create**: tab 7 UI | E-T11 | With the diff |

**Routing:** GLM builds each package (`ai-route build -w` — the note/critique loop of
[A1-design-note.md](A1-design-note.md) §6); Codex critiques the E1/E2/E6/E7 notes and reviews every
diff; one package at a time. All offline/mock (SPEC §1 hard rule 5 — offline first): the aligner
and SFX-route fakes; no network in tests.

---

## 14. Acceptance (offline; real PostgreSQL for every transaction test)

**Partial labels (PE-12):** the V3-AT-10 / V3-AT-25 tags on E-T2/E-T4/E-T5/E-T6 are **partial at
their own gates** — each row's phase-level assertion completes only when the combined E7 assertions
(E-T7/E-T10) pass.

| Test | Package | Proves |
|---|---|---|
| E-T1 | E1 | `E-1`/`E-2` apply on a populated V1+V2 database; V1 `edit_manifests`/`caption_tracks` rows and their triggers are byte-identical **before and after the E migrations** and still refuse V3 rows through the legacy path (`WORKFLOW_MISMATCH`); `reservations.queue`'s CHECK is untouched and edit-lane jobs never reserve (the E-2 invariant); V3 documents roundtrip through the store with hash re-verification; generated contracts show zero drift |
| **E-T2 (V3-AT-10, audio half)** | E2 | A two-speaker episode assembles with **clip audio only**: the export plan contains per-clip audio sources and **no** dialogue-line audio assets; no whole-timeline room tone (gap fill only, never under a clip); transitions render in master **and** variant/burned planners with paired A/V timing; a mid-word trim boundary is refused; **execution identity (decision 15)**: a restart mid-export replays on (layout hash, mix digest) and never re-renders a stored outcome — the replay returns the **stored `AssemblyOutcomeV3`** with its recorded findings/checks and report references, never substituted CURRENT tracks (PE-3); a crash **before installation** leaves nothing registered, and a crash **after installation / before job finish** replays the stored complete outcome without re-render (PE-3); a mix change driven by **immutable cue-sheet fixtures** (the E6 command is not required at this gate — PE-12) — cue-sheet version bumped, layout hash unchanged — produces **new outputs under a new manifest version with prior outputs preserved, never a replay** (PE-1); **job identity (PE-2)**: changed input under the same semantic key is refused through real `JobService.enqueue` (`IdempotencyConflict`), and replacing an already-successful assembly enqueues a new job with the same `logical_work_id` recording `replaces_job_id` |
| **E-T3 (V3-AT-25)** | E2 | Binding: every plan shot is bound to an accepted asset (sha + duration recorded); a missing or rejected shot, or one whose measured duration is shorter than the plan requires, ⇒ typed `edit.binding_incomplete`; **correspondence (PE-11)**: an unrelated accepted VIDEO offered for a shot, and a source whose SHA differs from D's acceptance evidence, each ⇒ typed refusal; zero- and one-speaker clips pass the same path; provenance completeness: a clip or card asset without C-side inspection evidence + `ProvenanceRecord` ⇒ typed `edit.provenance_incomplete`, **and an E-created output (master/derivative/SRT/card/gap fill) registered without its own complete `ProvenanceRecord` ⇒ typed `edit.provenance_incomplete`** (§15, PE-13) |
| **E-T4 (V3-AT-10, caption half)** | E3 | `th-TH`/`en-US`/`zh-CN` CURRENT tracks with identical cue windows (Thai is the timing master); cues inside measured utterance windows; **line-addressable mapping (PE-7)**: a two-speaker clip with several lines yields per-utterance cues through trims/transitions (not the first line only), repeated placements and predecessor recap lines carry distinct cue-id namespaces, simultaneous utterances keep separate spans, and missing alignment for an included utterance ⇒ typed `edit.alignment_missing` — never script timing; SRT assets content-addressed; the mismatch case carries the observed spoken text in **every** locale's cue — including `en-US`/`zh-CN` — plus the CRITICAL finding (decision 4); burned render is Thai-only; **no** burned `en-US`/`zh-CN` variant exists |
| **E-T5 (V3-AT-10)** | E4 | **Normalisation/report generation on supplied fixture artifacts (PE-12)**: a fixture master measuring −17 LUFS normalises to −14 LUFS integrated ±1 LU with the persisted gain; a hook fixture normalises on **its own** measured gain (per-artifact rule, §5); a peak-clamping case — a derivative that remains outside peak/loudness limits after the permitted scalar gain — fails typed with measurements (never silently limited, never a bigger clamp: PE-8) and the recorded failure exposes the pre-Gate-2 recovery verb; every supplied artifact carries its own post-export measurement and report (the readiness-blocking half of this proof completes at E7 — E-T7) |
| **E-T6 (R-7.7, R-12.8)** | E5 | **Recap binding/rendering (PE-12)**: recap ≤10 000 ms sourced from the predecessor's packaged shots, hash-bound to **the predecessor's** effective approval, with the predecessor pack hash recorded and recap cues carrying the predecessor pack's line text per locale (ED2); **a predecessor pack text revision before a replacement approval supersedes the binding ⇒ `edit.recap_pending` — the recap is never rebound to unapproved text (PE-11); under an effective replacement approval the recap rebinds to the new approved package** (the registered rebuild edge's end-to-end firing is asserted at E7 — E-T10, PE-12); episode 1 has no recap; `recap_pending` resolves by splicing a new manifest version; CTA ≤5 000 ms resolves next-air-time/continuation/finale from the calendar revision and **refuses** to promise an extension without a decision record; missing calendar ⇒ typed blocker; **render coverage (M-9)**: the assembled master containing the recap prefix and the composited CTA decodes with correct streams, duration and A/V alignment |
| **E-T7 (V3-AT-25)** | E7 | Derivatives: variant/hook/burned/preview derivation checks pass (constant-offset spans, shifted cues, same burn body); **hooks/preview native audio (PE-6)**: decoded source audio is retained exactly once per selected clip, cue timing survives reordered windows and crossfades, and a source cut that would bisect speech is refused; an injected desync ⇒ CRITICAL finding; a Gate 2 Revise timecode payload maps to exactly the noted units — untouched units' manifest versions and asset hashes byte-identical after rebuild; **readiness inventory (PE-10)**: readiness resolves the complete required artifact/check inventory for the installed assembly — a missing/stale artifact or report, caption IDs not matching the installed assembly, an UNKNOWN/incomplete required check and a failing loudness report each block (the readiness half of E-T5 completes here — PE-12) |
| **E-T8 (R-7.3, R-7.4)** | E6 | Cue sheets place accepted library assets only (missing provenance ⇒ typed refusal); ducking envelope reproducible from the session; music never rises above the duck bound under dialogue — the per-cue profile depth when the cue sheet sets one, else the config default (`MusicCueSheetV3`, §2); **`adjust_mix` proves the command→enqueue→new-output path (PE-12)**: it appends a cue-sheet version through A4's amendment path (PE-5), enqueues `edit_v3.assemble` exactly once (idempotency key) under a new execution identity, and the new outputs install; **an older worker completing after the mix change is quarantined by the fence (stale result never installed), and an adjustment against approved content routes through the amendment path (supersession), never a side channel (PE-5)**; a repeated identical edit is a no-op |
| **E-T9 (R-7.4)** | E6 | `sfx_fill`: SPEC §10.5 unit discipline (crash between submit/result/receipt ⇒ resume, no duplicate exposure, no regenerated success); reservation through `step_07`/EPISODE in A §5.2 order; unknown price ⇒ refused |
| E-T10 | E7 | A4 closure drives **each registered edge of decision 13** — predecessor approval → successor recap; predecessor pack text → successor recap captions; calendar revision → CTA; source shot asset / `ShotPlanV3` revision → assembly; music/SFX library revision → cue sheets; caption source text revision → tracks — asserting new-version rebuild and stale-result quarantine per edge (unpublished episodes only), published media untouched; **positive path (M-11)**: a fixture episode with zero blockers executes the production-track transition closing step 7 (state names per the E1 note) and becomes visible to F's step 8 |
| E-T11 | E8 | Tab 7: every §12 surface renders per SPEC §3.2 states; one primary action; typed blockers visible; preview cards render through the same document/render path F's Gate 2 page will consume (§12, ED4) — the executable proxy at the E8 gate, since F4 builds after E |
| E-T12 | all | `make check` + V1 `make pilot` green at every package gate; no test touches the network |

---

## 15. QA and inspection on edited artifacts (SPEC §12.2)

- **E's own checks** (the existing layers, FM §9, re-registered for V3 — E7, §13): in-assembly
  `TechnicalCheck`s (tiling, continuity, cue bounds, duration, streams, decode, burn) extended with
  the derivation checks (§6) and loudness (§5); the `qa.technical` job on the master; the ASR
  caption cross-check. The rule Unknown ≠ PASS applies to every check.
- **§12.2 (phase C accountable):** E **does not re-run detection** on pixels D already had
  inspected. The accountability split: C owns the §12.2 output-inspection seam; D executes it on
  D's clips. "Every source clip carries inspection evidence at acceptance" is an **ED5 requirement**
  (declared for D — `UNVERIFIED` in code until D's spec lands; no phase-D spec exists, FM §8). E
  runs a **provenance-completeness check on both directions (PE-13)**: no clip or card asset enters
  an EDL without C-side inspection evidence and a `ProvenanceRecord`; a gap is a typed blocker
  (`edit.provenance_incomplete`, E-T3). **And every E-created asset — masters, burned renders,
  variants, hooks, preview, SRT assets, the CTA card, gap-fill audio — receives a complete
  `ProvenanceRecord` atomically with its registration** (C §9's same-transaction rule), with exact
  source/font/route lineage as applicable; a missing output record is the same typed blocker
  (E-T3). Source inspection evidence is reused where valid; a deterministic typeset card is
  **not** required to carry a fabricated generation-inspection record (PE-13). E-added pixels are
  typeset text (libass) from licensed
  fonts — C's FONT provenance applies. Whether E additionally samples burned-render frames through
  C's seam with an expected-text allowlist is O-E1 (recommended: yes, as hardening before live, not
  in E's offline gate).
- **Findings routing:** CRITICAL findings block readiness and Gate 2 (the existing feed, FM §9);
  audio-side findings route back to D as QA findings (`qa/repairs.py`); a completed repair triggers
  an E rebuild (FM §9).

---

## 16. Open questions (each with a recommendation)

| # | Question | Recommendation |
|---|---|---|
| O-E1 | Does E sample burned-render frames through C's §12.2 seam (expected-text allowlist: captions/CTA/title text E itself placed), or is provenance-completeness enough? | **Completeness is applied** (inputs since v0.2; **extended to every E-created output in v0.3**, PE-13 — E2's gate, §13; `edit.provenance_incomplete`, E-T3). Still open: allowlist sampling of the burned render as hardening before live — the detector must never flag E's intentional text, so the allowlist contract needs C's sign-off |
| O-E2 | Exact `zh-CN` vs `zh-Hans` locale tag for delivery — YouTube's caption language matching | `zh-CN` (BCP-47, matches B pack locale keys); confirm with F5's `release_v3.deliver_captions` surface (the YouTube `upload_captions` leg, `phase-F-spec.md:931`) and T032 evidence (the live platform-qualification task, `phase-F-spec.md:57,142`) before E3 |
| O-E3 | Utterance-alignment source: does D's `ClipQaResult` carry word timings (Thai ASR word match already runs per shot, SPEC §4.6)? **UNVERIFIED** — no phase-D spec | **Resolved by the v0.2 ruling (M-8)**: word timings are a hard ED5 requirement — a mandatory `ClipQaResult` field (decision 4, ED5), so D's always-run ASR output is the single source; E's `UtteranceAligner` shrinks to the offline fake driving fixtures; **no G forced-aligner qualification track**. **v0.3 (PE-7)**: the requirement is the full line-addressable observation contract — source-audio identity, observed text, speaker/line association, source-relative utterance/word spans, coverage — word timings alone do not establish line association. Residual `UNVERIFIED`: the field's exact shape until D's spec pins it (§13 prerequisites) |
| O-E4 | C's library manifest shape (per-cue mood/duration/loop metadata) is not pinned anywhere in C v0.4.1 | Request a C-side manifest document (or descriptor fields on the accepted assets) as the ED3 crossing before E6. **Fallback pinned (M-12):** until the manifest exists, E6's cue proposal reads these asset descriptor fields only — {asset id/version/sha, duration_ms, loop capability, kind, mood (optional)}; when mood is absent the cue sheet records `mood: UNKNOWN` — proposal metadata, **not** a `TechnicalCheck`, so the Unknown ≠ PASS rule does not fire and readiness is unaffected; selection is the deterministic mood-less rule: kind-eligible assets sorted by (duration fit, asset id). |
| O-E5 | `MusicCue`/`SfxAsset` (master §13, `SPEC-v3.md:843`) are claimed by no accepted phase; E claims both as placement records | E owns them as §2 documents; flag to the orchestrator — if C was meant to own library-side records, E's placement records can be renamed without design change |
| O-E6 | Do hooks/variants need per-locale caption tracks? O-8 covers only full-episode posts | No — Thai burn only (today's variant treatment, FM §3); revisit only if a hook ships to YouTube as a standalone post with required languages |

---

## 17. Requirement trace

| R-ID | Requirement (REQUIREMENTS.md; the V3-AT rows are `SPEC-v3.md:901,916`) | Where | Test |
|---|---|---|---|
| R-7.1 | Assemble with Pika-generated audio | §1.3, §3 | E-T2 |
| R-7.2 | Transitions rendered where motivated (motivation decided in D's plan — decision 9's precedence) | §1.9, §3 | E-T2 |
| R-7.3 | Music ducked under dialogue, rights recorded | §1.10, §7 | E-T8 |
| R-7.4 | SFX source + placement | §1.10, §7 | E-T8, E-T9 |
| R-7.5 | Thai burned, timed to actual speech; tracks per language | §1.4/§1.5, §4 | E-T4 |
| R-7.6 | Variants, covers, three hooks | §6 | E-T7 |
| R-7.7 | End card with CTA | §1.8, §6 | E-T6 |
| R-12.8 | Recap opener (episode 2+) | §1.7, §6 | E-T6 |
| V3-AT-10 | Native audio; recap/CTA caps; loudness; shared timing | §3–§6 | E-T2, E-T4, E-T5, E-T6 |
| V3-AT-25 | Binding path 0/1/2 speakers; derivative sync | §6, §8 | E-T3, E-T7 |

---

## 18. Risks and limits

- **Thai utterance alignment quality** drives caption timing; timings now ride D's per-shot Thai
  ASR word match (a required SPEC §4.6 check, threshold `SPEC-v3.md:964`), so the residual risk is
  D's ASR quality, surfaced as D-side findings; E has no script fallback (by design). Mitigation:
  the word-match threshold + findings routing (§15); no separate E-side aligner exists to qualify
  (O-E3 resolved).
- **Pika native-audio variance** (levels, ambience, artifacts) is D's output, not E's; E can only
  measure, gate and report — repair loops back to D. Expect loudness spread across clips.
- **ffmpeg determinism/version drift** (filters, encoder) — the **tool recipe is part of the
  execution identity** (decision 15, PE-4), pinned by the composition and recorded per report, so
  drift produces a **new execution identity and new outputs** — never a silent replay under the old
  identity, and never an automatic layout-hash change (the layout hash covers layout decisions
  only).
- **Host CPU**: E's exports are the heaviest local compute in the pipeline; the production
  composition must run the `edit` worker under the workspace CPU quota or renders starve the host.
- **Recap serialization**: requiring the predecessor's effective approval couples episode N's
  readiness to N−1's Gate 2. With F's LAUNCH gate (≥5 approved episodes) plus the RELEASING buffer
  monitor (alert below 2 days, target ≥3 — F §6.3) this is safe; a zero-buffer season sees
  `edit.recap_pending` blockers — visible, not silent.
- **edit_manifests reuse**: V3 rows beside V1 rows in one table — guarded by `require_workflow` and
  E-T1's byte-identity assertions; the residual risk is a future V1 writer bypassing the guard
  (A §1's inventory test covers the entry points).
- **`zh-CN` translation quality** is B's pack text consumed verbatim; E's mismatch finding cannot
  fire for `en-US`/`zh-CN` (observation is Thai) — their correctness rides B's translation and
  Gate 2 review.

---

## 19. Alternatives rejected (one per major choice)

1. **New V3 edit tables** instead of reusing `edit_manifests`/`caption_tracks`: rejected — the seam
   is the one implementation F5 already assembles from (F §5), and a parallel store would drift from
   the gate conditions that already read these tables (FM §2).
2. **Recap cut from the predecessor's encoded master**: rejected — a re-encode of already-encoded
   audio (violates the no-re-encode rule), and it would bind the recap to a derivative rather than
   the production binding path V3-AT-25 names.
3. **Recap bound to the predecessor's current edit** (rebuild on any change) instead of its effective
   approval: rejected — every pre-publication re-approval of N−1 would force rebuild churn cascading
   through every successor of N−1; the approval is the honest dependency and matches the package
   validator's derivative rule (FM §2).
4. **Burned-in `en-US`/`zh-CN` variants**: excluded by O-8 (F §1.9) — no per-language video variants.
5. **LLM-written CTA copy**: rejected — date-bearing content must rebuild deterministically from a
   calendar revision (F §8.2's handler is "deterministic from the new revision; no LLM",
   `phase-F-spec.md:785-786`), and an unapproved-extension promise is exactly the risk a template
   with a hard guard eliminates.
6. **Single-pass `loudnorm`**: rejected — dynamic normalisation is not reproducible; measured-gain is
   a pure function of the measured bytes (§5).
7. **Full §12.2 re-inspection of edited frames**: rejected — source frames carry inspection evidence
   from D; E adds the provenance-completeness check, and optional allowlisted sampling is O-E1.
