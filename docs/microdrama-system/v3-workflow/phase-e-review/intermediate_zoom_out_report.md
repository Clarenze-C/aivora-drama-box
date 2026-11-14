# Goldfish Review Report

**Target:** `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-E-spec.md` (`1-545`)

Stage 8 — Intermediate Zoom Out (re-examination after Stages 5/6/7). The reviewer read the
three earlier-stage reports and reports NEW findings only; nothing recorded in
`zoom_out_report.md`, `comprehension_report.md`, or `critic_report.md` is restated here.

## Reviewer Status

| Reviewer | Status |
| --- | --- |
| `egm-zoom-out` | completed |

## Prioritized Findings (Blockers -> Major -> Nits)

### No New Blockers

No new Blocker-severity findings in this pass. Explicitly: zero (0) Blocker findings.

---

### Teaser loudness has no owner in the phase family - Severity: 🟡 Major

* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** Lines 34 (S0 item 5), 90-96 (S1 decision 6), 295-298 (S6 teaser input), 208 (ED4)
* **Discrepancy Description**: The teaser is the one released, audio-bearing artifact with no loudness owner anywhere in the phase family. E claims "-14 LUFS +/-1 / -1 dBTP, measured, evidenced, gated" for "every audio-bearing released artifact", then enumerates only its own five artifact kinds. The PROMO_CUT teaser (30-60 s, published at premiere-3 days per destination, gates the premiere) is assembled by F's `release_v3.teaser_cut` from E's EDL/export outputs — and `phase-F-spec.md` contains zero loudness/LUFS/ebur128 content (verified by search; F's job table at phase-F-spec.md:928 lists no measurement op). The re-cut-sub-span measurement problem critic M1 raised for hooks applies even more strongly to a 30-60 s multi-episode re-cut, so "F will inherit it" is not automatic.
* **Rationale & Recommendation**: E builds the family's only loudness capability, so this hole is visible only from this document's altitude, and each earlier stage missed it (M1 covered E's own derivatives only). Add one ED4 row pinning ownership: either F's `teaser_cut` must run E's ebur128/LoudnessReportV3 pattern (declared as a reusable seam, mirroring the `S/editing` seam reuse), or the obligation is explicitly F's to spec — either way the "every audio-bearing released artifact" claim becomes true family-wide.

### Redundant second utterance-alignment capability - Severity: 🟡 Major

* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** Lines 73-76 (S1 decision 4), 209 (ED5 "ideally, word timings"), 480 (O-E3), 241 (S3, G-qualification), 506-507 (S18 mitigation)
* **Discrepancy Description**: E plans a redundant second utterance-alignment capability. SPEC-v3.md S4.6 (line 439) makes "Thai ASR word match" a required per-shot check in D's Clip QA — every accepted clip has already passed a Thai ASR pass, so word timings are a byproduct D already computes. E nonetheless builds (a) its own UtteranceAligner seam, (b) a live "Thai forced aligner qualified before any live episode" deferred to G, and (c) precedence rules between the two sources — while ED5 asks for timings only "ideally".
* **Rationale & Recommendation**: YAGNI/reuse: the fallback exists for a scenario (an accepted clip lacking word timings) that D's own required check makes near-impossible, and its cost is concrete — a G-phase qualification track listed as an S18 mitigation. Make word timings a hard ED5 requirement (mandatory ClipQaResult field, not "ideally"); the aligner then needs no qualified live implementation at all and shrinks to the offline fake. One capability, one owner, no G track. If the hedge is kept anyway, O-E3 should say why D's always-run ASR output cannot be the single source.

### Brand-new render surfaces lack acceptance coverage of the render - Severity: 🟡 Major

* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** Lines 97-115 (S1 decisions 7-8), 224-227 (S3 step 2 "composited still/clip segment"), 426 (S13 E5), 442/446 (E-T2/E-T6)
* **Discrepancy Description**: The two brand-new render surfaces have no acceptance coverage of their actual render. Verified: today's export graph (`microdrama/src/microdrama/editing/export.py`) has no still/overlay/compositing capability (the only non-clip primitive is anoisesrc at line 143), so the composited CTA card (still segment + libass typesetting + music-tail audio bus inside the episode export graph) is new machinery, as is prefixing another episode's source assets with their native audio. E-T6 proves copy resolution, duration caps, approval binding and refusals — never that either segment renders, decodes, and lands with correct streams/duration in the assembled master; E-T2's fixture is a plain two-speaker episode (recap needs episode >= 2; CTA presence unasserted).
* **Rationale & Recommendation**: S13/S14 are the document's definition of done, and the newest machinery is exactly what they do not prove; S15's runtime TechnicalChecks would catch gross failures only at first live integration. Extend E-T6 (or make E-T2's fixture an episode-2 with both segments) to assert the assembled master containing the recap prefix and the composited CTA card decodes with correct streams, duration, and A/V alignment.

### Critic B1 "fold into EDL hash" arm would break the determinism chain - Severity: 🟡 Major

* **Reviewer Lens:** `egm-zoom-out` (re-check of an earlier stage's proposed mitigation)
* **Affected Scope:** Concerns the fix for critic B1 (lines 227-229, 271-274, 389-392) against S3 line 239 and S5 line 277
* **Discrepancy Description**: Critic B1's recommendation offers two arms — "fold MusicCueSheetV3/SfxCueSheetV3 document versions (+ gap-fill config, + loudness gain) into the EDL hash", or a second replay key. The fold arm, as written, would break S3's own determinism chain: the measured loudness gain is a pure function of the rendered audio bytes (S5 line 277 says exactly this), not of session inputs, so "same session inputs => same EDL hash" (line 239) stops holding, and an ordering hazard appears (the hash is needed at outcome registration; the gain exists only after an analysis pass of a mix the EDL itself defines).
* **Rationale & Recommendation**: When resolving B1, take the second-key arm: keep the EDL hash a pure function of the EDL/session, and define the mix digest (cue-sheet versions + gap-fill config) as the replay key replacing `line_sha`, with the measured gain recorded inside the replayed outcome. State this choice in the E2 note so the Blocker fix does not write a new contradiction into the deterministic core.

---

### Duration-band check operand undefined - Severity: 🟢 Nit

* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** Lines 346-347 (S9 duration check)
* **Discrepancy Description**: "Duration out of band (episode band from B S2.1; recap/CTA caps S6; export ceiling FM S6)" never states whether B's episode band is checked against the story body or the assembled total including the <=10 s recap, the <=5 s CTA, and transitions' overlap shortening. Two readings give different readiness outcomes for the same episode.
* **Rationale & Recommendation**: One clause pins the operand (e.g. "band applies to the assembled timeline including recap/CTA"); this is the one readiness check whose input is currently undefined.

### Readiness evaluation and consumption point unspecified - Severity: 🟢 Nit

* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** Lines 345-354 (S9), 351-353 (package path), vs S12 line 407
* **Discrepancy Description**: The consumption end of readiness is as unspecified as the production end Stage 5 flagged for assemble. Readiness is "derived, never stored" (AR-4), yet F "consumes E's readiness through the package path" and tab 7 displays typed blockers — nothing states when `edit_readiness(episode)` is evaluated (after each E job? at Gate 2 package assembly? at UI read?) or how derived blockers materialize into package conditions, given today's gate2_blockers read stored caption conditions (FM S2).
* **Rationale & Recommendation**: Same data-flow gap class as Stage 5's assemble-trigger nit, at the other end of the flow. One sentence naming the evaluator and evaluation point closes it.

---

## Guidance Note (not counted as a finding)

**Guards required when shipping the Critic M2 fix.** The Critic's M2 remedy ("add the
predecessor episode's pack line text to ED2") introduces a cross-episode document dependency
without the three guards the document's own model requires: the recap binding in
EditSessionV3 (line 187) records only approval ref + source asset set + beat refs, not the
predecessor pack's version; decision 13's "caption source text revision -> tracks" edge covers
only the current episode; and S10's fence carries expected_content_revision only for the
episode's own inputs. A post-approval revision of N-1's pack text would leave N's recap cues
stale with no edge and no fence — the same silent-staleness class B1 condemns. Ship the M2 fix
together with (a) the predecessor pack hash in the recap binding, (b) a rebuild edge
"predecessor pack text revision -> successor recap captions", and (c) a fence on that revision.

## Verification Basis (reviewer, read-only)

`/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-F-spec.md` (lines 42, 267,
393-401, 447-452, 928, 988, 1000; zero matches for loudness/LUFS/ebur128),
`/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/SPEC-v3.md` (S4.6 lines 435-450,
S4.7 lines 452-473), `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-A-spec.md`
(S5.2 lines 208-218 — confirmed step_07 fits the step_key vocabulary, so no new crossing
finding there), and `/root/AIVORA/drama-box/microdrama/src/microdrama/editing/export.py`
(no still/overlay compositing capability today).

## Severity Summary

| Severity | Count |
| --- | --- |
| 🔴 Blocker | 0 |
| 🟡 Major | 4 |
| 🟢 Nit | 2 |

Plus 1 uncounted guidance note (guards for the M2 fix). All findings are additive to the
settled Stage 5/6/7 findings; none restate them.
