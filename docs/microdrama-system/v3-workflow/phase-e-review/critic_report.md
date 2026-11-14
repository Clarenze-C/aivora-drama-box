# Goldfish Review Report — Critic Stage (Stage 7)

**Target:** `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-E-spec.md` (lines 1-412, §0 Scope – §12 UI)

Scope note: lines 413-545 (build sequencing, acceptance tests, QA, open questions, trace, risks, alternatives) belong to a later stage and were not reviewed; their content's absence from lines 1..412 is not reported. Findings below are deduplicated across reviewers with line references normalized; where reviewers assigned different severities to the same defect, the highest severity is recorded and the split is noted inline.

## Reviewer Status

| Reviewer | Status |
| --- | --- |
| `egm-design` | completed |
| `egm-structural` | completed |
| `egm-style` | completed |

Severity totals: 1 Blocker, 6 Major, 19 Nit.

Verification context (for the record): both code-verifying reviewers independently confirmed that the overwhelming majority of the document's file:line citations against `SPEC-v3.md`, `phase-A/B/C/F-spec.md`, `REQUIREMENTS.md`, `DECISIONS.md`, the migrations, and the `S/contracts` / `S/editing` modules are accurate, and that the in-range structure conforms to the sibling phase-spec template and the feature-spec standard's in-scope requirements. The Blocker and Majors below are design/content contradictions, not missing sections.

## Prioritized Findings (Blockers -> Major -> Nits)

### B1 — EDL-hash replay identity does not cover mix inputs; `adjust_mix` can be silently dropped — Severity: Blocker
* **Reviewer Lens:** `egm-design`
* **Affected Scope:** Lines 227-229 (§3 step 2, hash definition), 239-241 (§3 determinism chain), 157-162 (§1 decision 15), 389-392 (§11 `adjust_mix`), 71-72 (gap-fill hashing)
* **Discrepancy Description**: §3 pins the EDL hash to per-clip `[clip_id, source_asset_id, in, out]` "plus the audio-source binding" — matching today's formula (`S/editing/edl.py:157-172`), which also omits `gain_millibel` and timeline placement. Decision 15 pins idempotency to "the existing EDL-hash replay (`_replay_outcome`, FM §1)", whose signature today is `(episode_id, edl_hash, line_sha)` (`S/editing/service.py:1340-1352`), and the spec defines no V3 replacement for `line_sha`. A cue-sheet-only change — the primary `adjust_mix` case (§7 lines 314-318; §2 lines 189-190) — changes none of the hashed fields, so the EDL hash is unchanged and §11's claimed effect "enqueue `edit_v3.assemble` (new EDL hash)" is not derivable from the spec's own hash definition. As specified, replay would return the stored outcome and the operator's mix adjustment would be a silent no-op — the exact "silent remix" failure §3 line 229 forbids. Gap-fill gain and the measured loudness gain stage are likewise outside the stated replay identity.
* **Rationale & Recommendation**: This sits in the deterministic core (E2, designated "critiqued first") and must be pinned before that note. Extend the spec to state exactly what the V3 replay identity covers: either fold `MusicCueSheetV3`/`SfxCueSheetV3` document versions (+ gap-fill config, + loudness gain) into the EDL hash, or define the second replay key replacing `line_sha` (e.g. a mix digest), and assert in a test that an `adjust_mix`-only change produces new outputs, never a replay.

### M1 — One master-derived loudness gain for all artifacts is an unbacked assumption for short-form derivatives — Severity: Major
* **Reviewer Lens:** `egm-design`
* **Affected Scope:** Lines 90-96 (§1 decision 6), 271-274 (§5 Normalise), 348-349 (§9 readiness on loudness fail)
* **Discrepancy Description**: §5 computes a single gain from the clean-master measurement and applies it to "every export of that session", then requires every artifact — including 20-40 s hooks and the 90 s episode-one preview — to pass −14 ±1 LUFS. Integrated LUFS over a re-cut sub-span (a hook built on a quiet stretch) is not the episode's integrated LUFS; applying the master's gain can land the hook outside ±1 with no remediation in the design except `edit.loudness_fail`, which blocks the whole episode's step 7 readiness. The spec asserts one gain suffices without justification and offers no per-artifact repair path short of a full re-render.
* **Rationale & Recommendation**: Either compute the gain per artifact class (still deterministic — a pure function of that artifact's measured bytes, consistent with §5's own determinism argument), or explicitly document that hooks/preview use their own measured gain. Burned master and variants are safe (identical audio / `-c:a copy`); the exposure is specifically hooks and the preview.

### M2 — Recap caption text provenance is unpinned; E's declared inputs cannot produce recap cues — Severity: Major
* **Reviewer Lens:** `egm-design`
* **Affected Scope:** Lines 285-287 (§6 recap), 251-253 (§4 caption text sources), 187 (§2 recap binding records only "beat refs"), 206 (ED2)
* **Discrepancy Description**: Recap clips speak the predecessor's dialogue lines, but the only text E is declared to consume is the current episode's pack — whose `recap_plan` holds beats with estimated durations, not dialogue text (`phase-B-spec.md:140`). Producing TH/EN/ZH cues for recap speech requires either reading the predecessor episode's pack (an undeclared B crossing) or using beat text — which is prose, not the spoken line, and would trip the CRITICAL mismatch rule (decision 4) on every recap cue. No option is pinned.
* **Rationale & Recommendation**: Add the predecessor pack's line text (per locale, keyed by the recap beat's line_ids) to ED2 as a declared read-only B crossing, and state that recap cues resolve text through it. Without this, E3/E5 cannot implement recap captions and V3-AT-10's "ZH/EN tracks share the TH cue timing" has no text to time.

### M3 — Contradiction on mismatch-path EN/ZH cue text — Severity: Major
* **Reviewer Lens:** `egm-design`
* **Affected Scope:** Lines 81-83 (§1 decision 4) vs 251-253 (§4)
* **Discrepancy Description**: Decision 4 says the mismatch rule is "unchanged" — in code (`S/editing/captions.py:86-103`) the observed Thai text goes into every locale's cue on mismatch — while §4 reads as EN/ZH always carrying pack text ("EN/ZH = B's pack text verbatim", no carve-out). The two statements give implementers different SRT bytes for the same input, and ED4 (line 208) pins "the exact track assets"/SRT bytes as the contract F's `deliver_captions` uploads to YouTube — this must be single-valued.
* **Rationale & Recommendation**: State explicitly what an en-US/zh-CN cue contains when the TH observation mismatches (observed Thai text per the unchanged rule, or pack text with the CRITICAL finding blocking release anyway), and mirror it in the E-T4 acceptance row.

### M4 — Wrong migration cite `M/0004:73` for the locale fact, contradicting the document's own correct cite under "Verified in particular" — Severity: Major
* **Reviewer Lens:** `egm-design`, `egm-structural`, `egm-style` (severity split: style rated Major; design and structural rated Nit — highest recorded)
* **Affected Scope:** Line 180 (vs lines 63-64)
* **Discrepancy Description**: Line 180 cites `M/0004:73` for "`caption_tracks.locale` is unconstrained text"; line 73 of `0004_media_and_qa.sql` is `schema_version`, the `locale` column is line 75 — which the document itself cites correctly at line 63. The duplicate pointer sits under the "Verified in particular" heading (line 179) while contradicting the document's own earlier citation, and the wording drifts ("free text" vs "unconstrained text"). The document's authority model rests on precise file:line cites read on today's tree (lines 7-9), so an internally contradictory "Verified" cite erodes the citation apparatus as a whole.
* **Rationale & Recommendation**: Correct `M/0004:73` to `M/0004:75` and use one term for the fact in both places.

### M5 — Self-negating headline: "The edit gate is readiness, not a gate." — Severity: Major
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Line 134 (§1 decision 12 headline)
* **Discrepancy Description**: The document names its headline deliverable "the edit gate" (title line 1, §0 item 6 line 35, §9 heading line 343) and then defines the name as its own negation. §0 item 6 already frames it correctly ("typed readiness blockers consumed by Gate 2"); the bolded headline is the scannable layer a fresh reader hits first, and a self-negating definition of the phase's central concept forces a re-read.
* **Rationale & Recommendation**: Reword, e.g. "Step 7 has no gate of its own; 'the edit gate' is E's readiness computation, consumed by Gate 2" — keeping the clarifying body text as is.

### M6 — Garbled sentence defining the gap-fill trigger — Severity: Major
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Lines 319-320 (§7 Gap fills)
* **Discrepancy Description**: "SFX needs the library lacks ride `edit_v3.sfx_fill` on C's `media` lane (ED3): …" — a center-embedded object relative with no relativizer ("SFX needs [that] the library lacks") followed by the main verb "ride"; on first pass it scans as a typo. This sentence defines the trigger for E's only paid job, so it must parse on first read. The equivalent in §1 decision 10 (line 129, "Per-episode SFX gap fills ride C's qualified SFX route seam") is clear.
* **Rationale & Recommendation**: "SFX needs absent from the library ride `edit_v3.sfx_fill`…" or "Library gaps (SFX needs the library does not cover) ride…".

### N1 — Stale code citation `S/editing/export.py:113` for the amix mix rule — Severity: Nit
* **Reviewer Lens:** `egm-design`, `egm-structural`
* **Affected Scope:** Line 234 (related: line 79 `S/editing/captions.py:48-139`)
* **Discrepancy Description**: The `amix=inputs=N:normalize=0:duration=longest` expression is at `export.py:118` in today's tree (line 113 is inside the room-tone filter block); the stale number is inherited from `e-factmap.md` §1, which quotes the same `:113`. Related off-by-one: the function cited as `captions.py:48-139` spans 49-140 — tolerable, but worth aligning in the same pass.
* **Rationale & Recommendation**: Re-point to `S/editing/export.py:117-121` (or `:118`) and optionally align `:48-139` to `:49-140`, so the factmap convention ("cites read today") holds.

### N2 — "FM context note §128" citation format collides with the `FM §n` section convention — Severity: Nit
* **Reviewer Lens:** `egm-structural` (egm-style verified the referent is real, so this is format ambiguity, not a broken reference)
* **Affected Scope:** Line 258
* **Discrepancy Description**: The declared convention (lines 7-9) is `FM §n` = section n of `e-factmap.md`, which has sections §1-§10 only; "§128" is actually line 128 of `e-factmap.md` (the trailing unnumbered "Context notes for the spec writer" block mentioning `burn_in_caption_track_id`). The form reads as a nonexistent FM section.
* **Rationale & Recommendation**: Cite as "e-factmap.md:128 (context note)".

### N3 — Bare "§10.5" breaks the cross-reference convention — Severity: Nit
* **Reviewer Lens:** `egm-structural`
* **Affected Scope:** Lines 129, 161, 321
* **Discrepancy Description**: Bare "§10.5" means SPEC-v3 §10.5 (the generation-unit contract), but the document's otherwise-uniform convention is bare §n = this document — and this document's §10 ("Jobs, fence, waits") has no §10.5, so the bare reference is unresolvable under the document's own rule. Line 157 shows the fully qualified form ("SPEC §10.5:720-728") four lines before line 161's bare one.
* **Rationale & Recommendation**: Qualify as "SPEC §10.5" at all three sites — the fix is mechanical.

### N4 — Decision 8 misattributes the poster seam's rule — Severity: Nit
* **Reviewer Lens:** `egm-design`
* **Affected Scope:** Lines 112-114
* **Discrepancy Description**: "licensed-font typesetting through the existing libass path (the poster seam's rule — no live text in a filter graph beyond libass itself, FM §3)". FM §3's poster seam carries no live text at all — title/CTA are pre-typeset into approved image assets; the libass path is the caption-burn seam (FM §1), not the poster seam. The design choice (libass CTA typesetting under C's font provenance) is defensible, but the cited precedent is characterized inaccurately.
* **Rationale & Recommendation**: Correct the attribution so the C-side sign-off (O-E1's allowlist contract) references the right rule.

### N5 — Wrong section cross-reference for `adjust_mix` — Severity: Nit
* **Reviewer Lens:** `egm-design`
* **Affected Scope:** Lines 317-318
* **Discrepancy Description**: "(the operator may adjust placement/gains pre-Gate 2 (`adjust_mix`, §12))" — `adjust_mix` is defined in §11 (commands, line 391); §12 is the UI table, which only surfaces it as a secondary action.
* **Rationale & Recommendation**: Point the reference at §11.

### N6 — E-2 omits the second queue CHECK — Severity: Nit
* **Reviewer Lens:** `egm-design`
* **Affected Scope:** Line 177
* **Discrepancy Description**: E-2 grows only `jobs.queue` (0001:77). `reservations.queue` (`0003_budget_and_compute.sql:71`) carries the same closed three-value CHECK. This is safe only because decision 14 pins that `edit`-lane jobs never reserve (only `edit_v3.sfx_fill` reserves, on C's `media` lane) — an invariant stated nowhere in E-2.
* **Rationale & Recommendation**: Add one sentence to E-2 recording that invariant, so a future reserving edit-lane job does not trip the reservations CHECK unnoticed.

### N7 — Locale/language shorthand drift — Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Lines 21, 28, 74, 78, 84-89, 108, 188, 250-255, 258, 293
* **Discrepancy Description**: "TH" (74, 78, 108, 188, 250, 293), "Thai" (84), "th-TH" (28, 85, 254, 258), "ZH"/"EN/ZH" (21, 89, 253, 255) vs full tags "en-US"/"zh-CN"; line 28 mixes conventions in a single line ("TH burn + th-TH/en-US/zh-CN tracks").
* **Rationale & Recommendation**: Keep BCP-47 tags for identifiers/config and one prose form ("Thai", "EN/ZH" defined once) elsewhere.

### N8 — Duration caps written in two units — Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Lines 97, 106 vs 188, 285, 288
* **Discrepancy Description**: The same caps appear as "≤10 s"/"≤5 s" (decisions 7-8) and "≤10 000 ms"/"≤5 000 ms" (§2 `CtaResolutionV3`, §6); the validators are ms (`duration_ms`).
* **Rationale & Recommendation**: Pick ms (or "10 s (10 000 ms)" at first mention).

### N9 — Loudness tolerance notation varies — Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Lines 34, 91-92, 275-276
* **Discrepancy Description**: Three forms: "−14 LUFS ±1 / −1 dBTP", "−14 LUFS integrated ±1, −1 dBTP true peak", "(−14 ±1 LUFS, ≤ −1 dBTP)". Value/unit/tolerance order differs and only the third states the ceiling relation (≤).
* **Rationale & Recommendation**: Use one canonical form, e.g. "−14 LUFS integrated (±1) and ≤ −1 dBTP true peak".

### N10 — "E validates and refuses typed on any gap" vs ED5's "blocks (typed) on any gap" — Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Line 332 vs line 209
* **Discrepancy Description**: Same concept, two phrasings; "refuses typed" is ungrammatical compression.
* **Rationale & Recommendation**: Use "blocks with a typed blocker (`edit.binding_incomplete`)" in both places.

### N11 — "fake offline" vs "Offline fake adapter" — Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Lines 76 vs 322
* **Discrepancy Description**: The same fixture concept appears with flipped word order in the two mentions.
* **Rationale & Recommendation**: Pick "offline fake adapter".

### N12 — Loudness artifact list drift — Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Lines 91-92 vs 268-269
* **Discrepancy Description**: "(clean master, burned master, platform variants, hooks, episode-one preview)" vs "(clean master, burned master, each variant, each hook, the preview)" — same set, inconsistent naming.
* **Rationale & Recommendation**: Name the canonical set once (§5) and reference it from decision 6.

### N13 — §9 readiness blockers enumerated descriptively while the typed names live elsewhere; "unbound" undefined — Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Lines 345-349 (typed identifiers defined at lines 104, 115, 274, 332)
* **Discrepancy Description**: §9 — the section that defines readiness — lists blockers descriptively ("binding incomplete; recap pending/unbound; CTA unresolved; … loudness fail; …") while the typed identifiers live at their definitions, and "unbound" (line 347) appears nowhere else in the document.
* **Rationale & Recommendation**: Consolidate the typed names in §9 and define or drop "unbound".

### N14 — A change riding in the "Reused unchanged:" list — Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Lines 193-196
* **Discrepancy Description**: The "Reused unchanged:" list includes the `qa.technical` job with an embedded E-side action ("E re-registers it for V3 episodes through A's job system") — a wording contradiction, since a change is not "unchanged".
* **Rationale & Recommendation**: Split into "reused as-is" vs "re-registered for V3, contract unchanged".

### N15 — Orthography mixture: "synchronised … honoring" — Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Line 119
* **Discrepancy Description**: British/American mixture in one sentence; the document is otherwise British ("normalised" 90, "Normalise" 271, "normaliser" 277, "analysed/analyser" 191) and so is the family ("honoured", `phase-B-spec.md:113`).
* **Rationale & Recommendation**: Use "honouring".

### N16 — Only first-person clause in the document — Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Line 8
* **Discrepancy Description**: "anything I could not verify is `UNVERIFIED`" is the only first-person clause; the sibling spec phrases the same promise impersonally ("every FM fact relied on below was verified in code unless marked `UNVERIFIED`", `phase-F-spec.md:15-17`).
* **Rationale & Recommendation**: Use "anything the author could not verify".

### N17 — "utter spans" clipping and related terminology micro-drift — Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Lines 127 vs 122/250/317; 209 vs 331; 392 vs 355
* **Discrepancy Description**: "dialogue/utter spans" (127) clips "utterance" — elsewhere "utterance windows/spans" (122, 250, 317). Related drift: "speaker count 0/1/2" (209) vs "zero-, one- and two-speaker" (331); "Gate-2 Revise" (392) vs "Gate 2 Revise" (355 and ~12 unhyphenated uses).
* **Rationale & Recommendation**: Normalize to the dominant forms ("utterance spans", one speaker-count form, "Gate 2 Revise").

### N18 — Four stacked/compressed constructions that tax first-pass parsing — Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Lines 35-36, 143-144, 273-274, 350-351
* **Discrepancy Description**: (a) "the pinned rebuild contract F8's amendment closure waits on"; (b) "the `edit_v3.rebuild` handler for — predecessor approval → successor recap; …" (odd dash after "for"); (c) "a true-peak exceed after gain clamp fails … rather than silently limiting" ("exceed" as noun; the trailing comparison dangles); (d) "E claims the episode production-track transition closing step 7" (noun stack).
* **Rationale & Recommendation**: Prefer a colon or "covering the edges:" in (b); "exceedance" and a complete comparison in (c); "the production-track transition that closes step 7" in (d); unpack (a) similarly.

### N19 — §0 item 3 reads as both segments binding both authorities — Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Lines 30-31
* **Discrepancy Description**: "Recap binding … and CTA resolution …: duration-checked segments bound to the predecessor's approval and the calendar revision" reads as both segments binding both authorities; per decisions 7-8, recap binds the approval and CTA binds the calendar.
* **Rationale & Recommendation**: Prefer "each bound to its own authority (recap → predecessor approval; CTA → calendar revision)".

---

All three severity levels are non-empty: 1 Blocker, 6 Major, 19 Nit. The Blocker and the first three Majors all sit in the deterministic core (E2) and the caption/derivative contracts (E3/E5/E7) — the packages already marked "critiqued first" — so they can be resolved in those design notes without re-scoping the phase.
