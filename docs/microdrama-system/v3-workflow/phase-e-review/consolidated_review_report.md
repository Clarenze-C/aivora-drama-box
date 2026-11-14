# Consolidated Review Report — phase-E-spec.md (v0.1 DRAFT)

**Target:** `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-E-spec.md` (545 lines)
**Mode:** Headless uninterrupted run (Preset 1 — consolidated report with all review rubrics), 14 Nov 2026.
**Semantic split:** Boundary discovered at line 413 (`## 13. Build packages` — the work-breakdown pivot). FeatureRange 1..412 (§0–§12), DetailedRange 413..545 (§13–§19).
**Artifacts:** all reports in `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-e-review/`. The target document was not modified; no findings were resolved.

## Reviewer Status (all stages)

| Stage | Reviewer | Status |
| --- | --- | --- |
| 5 Initial Zoom Out | `egm-zoom-out` | completed |
| 6 Comprehension | `egm-comprehension` | completed |
| 7 Critic | `egm-design`, `egm-structural`, `egm-style` | completed |
| 8 Intermediate Zoom Out | `egm-zoom-out` | completed |
| 9 Implementation Readiness | `egm-implementation-readiness`, `egm-codebase-details`, `egm-style` | completed |

## Severity Summary

| | 🔴 Blocker | 🟡 Major | 🟢 Nit |
| --- | --- | --- | --- |
| Raw per-stage totals | 1 | 23 | 51 |
| **Consolidated (deduplicated)** | **1** | **21** | **43** |

Plus 1 uncounted guidance note (Stage 8: guards required when shipping the M2 recap fix — annexed to consolidated item M-3). Ten raw findings merged into other items (log below).

**[format]-tagged findings: 0.** No finding merely asks for a section the EGM template expects — §18 Risks & Limits and §19 Alternatives exist and are populated, and no reviewer reported a missing template section. Every finding below is a content defect, an internal contradiction, or a build-blocking ambiguity.

**What held up (per reviewer verification notes):** the document's file:line citations were independently re-verified against the tree by four reviewers and found overwhelmingly accurate (three stale/wrong cites below); E1→E8 sequencing, package↔test gating in both directions, and §17 trace completeness against the ten E-owned requirement IDs were verified sound; the reuse thesis (the `S/editing` seam, `edit_manifests`/`caption_tracks`, migration CHECK coverage) was verified real against code and migrations.

---

## 🔴 Blockers

### B-1 — EDL-hash replay identity does not cover mix inputs; an `adjust_mix`-only change can be silently dropped
* **Sources:** CR7-B1 (Blocker) · ZO8-M4 (Major — fix-shape constraint, merged)
* **Scope:** §3 lines 227–229, 239–241 · §1 decision 15 lines 157–162 · §11 line 391 · §2 lines 189–190
* **Defect:** The EDL hash is pinned to per-clip `[clip_id, source_asset_id, in, out]` + audio binding — matching today's formula, which omits cue-sheet content, gains, and placement. Replay idempotency is pinned to today's `_replay_outcome(episode_id, edl_hash, line_sha)` with no V3 replacement for `line_sha` defined. A cue-sheet-only change (the primary `adjust_mix` case) changes none of the hashed fields, so §11's claimed "enqueue `edit_v3.assemble` (new EDL hash)" is not derivable from the spec's own hash definition: replay would return the stored outcome and the operator's mix adjustment would be a silent no-op — the exact "silent remix" failure §3 forbids. Gap-fill gain and the loudness gain stage are likewise outside the stated replay identity.
* **Fix constraint (from Stage 8 re-check):** the fix must NOT take critic B1's "fold into EDL hash" arm as written — the measured loudness gain is a function of rendered bytes, not session inputs, so folding it in breaks "same session inputs ⇒ same EDL hash" (§3 line 239) and creates an ordering hazard. Take the second-key arm: keep the EDL hash pure, define a mix digest (cue-sheet versions + gap-fill config) as the replay key replacing `line_sha`, record the measured gain inside the replayed outcome, and add a test asserting an `adjust_mix`-only change produces new outputs, never a replay. Pin in the E2 note ("critiqued first") before build.

---

## 🟡 Majors

### M-1 — `S/editing` seam listed "Reused unchanged" while E2 modifies it; no Create/Modify/Reuse marking
* **Sources:** ZO5-1 (Major) · IR9-M2 (Major) · CR7-N14 (Nit, merged)
* **Scope:** §2 lines 193–196 vs §1.1 line 52–53, §3.3 lines 231–235, §4, §13 E2 line 423
* **Defect:** §2 lists the `S/editing` seam modules as "Reused unchanged", but §1.1 says V3 "extends its planners", §3.3 builds `plan_master`'s V3 branch, §4 changes what the caption window measures, and E2 delivers "transitions in both exporters". The `qa.technical` job also rides in the "unchanged" list with an embedded E-side re-registration. No package row marks items Create/Modify/Reuse (the family idiom, phase-F-spec §13), so the implementer must guess whether `S/editing/{edl,export,variants,captions}.py` are modified in place or wrapped in `S/editing_v3` — a choice that changes the V1-regression surface E-T1's byte-identity gate must cover.
* **Action:** Reword §2 ("reused as the single implementation, extended with V3 branches; V1 planner outputs byte-identical, asserted at every package gate" — name the pinned invariant), split the `qa.technical` entry out ("re-registered for V3, contract unchanged"), and mark each E-package row's items Create/Modify/Reuse.

### M-2 — One master-derived loudness gain for all artifacts is unbacked; a derivative miss has no recovery verb
* **Sources:** CR7-M1 (Major) · ZO5-7 (Nit, merged)
* **Scope:** §1 decision 6 lines 90–96 · §5 lines 271–274 · §9 lines 348–349
* **Defect:** §5 computes one gain from the clean-master measurement and applies it to every export, then requires every artifact — including 20–40 s hooks and the 90 s preview — to pass −14 ±1 LUFS. Integrated LUFS over a re-cut sub-span is not the episode's integrated LUFS, so a hook built on a quiet stretch can land outside ±1 with no remediation except `edit.loudness_fail`, which blocks the whole episode's readiness. Burned master and variants are safe (identical audio / `-c:a copy`); the exposure is hooks and the preview.
* **Action:** Compute the gain per artifact class (still deterministic — a pure function of that artifact's measured bytes, consistent with §5's own argument), or document that hooks/preview use their own measured gain; state the recovery path so the gate never dead-ends an episode at step 7.

### M-3 — Recap caption text provenance unpinned; E's declared inputs cannot produce recap cues
* **Sources:** CR7-M2 (Major) · ZO8 guidance note (annexed)
* **Scope:** §6 lines 285–287 · §4 lines 251–253 · §2 line 187 · ED2 line 206
* **Defect:** Recap clips speak the predecessor's dialogue lines, but the only text E is declared to consume is the current episode's pack, whose `recap_plan` holds beats with estimated durations — not dialogue text. Producing TH/EN/ZH cues for recap speech requires either reading the predecessor episode's pack (an undeclared B crossing) or using beat prose, which would trip the CRITICAL mismatch rule on every recap cue. No option is pinned.
* **Action:** Add the predecessor pack's line text (per locale, keyed by the recap beats' line_ids) to ED2 as a declared read-only B crossing. Ship with the three guards from the Stage-8 guidance note: (a) the predecessor pack hash in the recap binding, (b) a rebuild edge "predecessor pack text revision → successor recap captions", (c) a fence on that revision — otherwise a post-approval revision of N−1's pack leaves N's recap cues silently stale, the same failure class as B-1.

### M-4 — Contradiction on mismatch-path EN/ZH cue text
* **Sources:** CR7-M3
* **Scope:** §1 decision 4 lines 81–83 vs §4 lines 251–253
* **Defect:** Decision 4 keeps the mismatch rule "unchanged" (in code, observed Thai text goes into every locale's cue on mismatch), while §4 reads as EN/ZH always carrying pack text verbatim with no carve-out. The two readings give implementers different SRT bytes for the same input — and ED4 pins those exact bytes as the contract F uploads to YouTube.
* **Action:** State explicitly what an en-US/zh-CN cue contains when the TH observation mismatches, and mirror it in E-T4.

### M-5 — Transition-selection decision source is not reconstructible
* **Sources:** CP6-2
* **Scope:** §1.9 lines 116–122 · §3.2 line 227 · §2 line 187 · R-7.2 line 492
* **Defect:** The spec pins how transitions render but never which input decides the `TransitionKind` at a given boundary. "From the plan/config" points simultaneously at D's `ShotPlanV3` (a code zero-hit, no phase-D spec) and at E's config "transition defaults", with no precedence rule; R-7.2's "where motivated" has no owner. E-T2 is then only testable against fixtures whose transition choices have no stated source.
* **Action:** State the owning input and precedence (e.g. per-boundary kind from `ShotPlanV3` when present, else the E config default), or move the question into the ED5 register as O-E3 does for word timings.

### M-6 — §15 QA work and §11 `adjust_mix` are assigned to no build package and no acceptance test
* **Sources:** IR9-M1 (Major) · ZO5-5 (Nit, merged)
* **Scope:** §13/§14 lines 420–452 vs §15 lines 458–465, §16 line 478, §11 line 391
* **Defect:** Four work items exist only in prose: (a) the `qa.technical` re-registration and ASR caption cross-check; (b) the clip/card provenance-completeness gate ("a gap is a typed blocker") — E-T8's provenance refusal covers only the music/SFX leg; (c) O-E1's recommendation says "Completeness now (E2)" but §13's E2 row omits it and "(E2)" is a bare pointer; (d) `adjust_mix` is in no package row and no test exercises its version-append/idempotency/re-enqueue behavior. Unclaimed work surfaces late and forces the implementer to decide placement.
* **Action:** Name the owning package for each item (provenance-completeness → E2 per O-E1; `qa.technical` re-registration + ASR cross-check → E7 unless re-scoped; `adjust_mix` → E6), add each to that package's Builds cell, and extend the tests (clip-leg provenance blocker case; `adjust_mix` case).

### M-7 — Teaser loudness has no owner anywhere in the phase family
* **Sources:** ZO8-M1
* **Scope:** §0 item 5 line 34 · decision 6 lines 90–96 · §6 lines 295–298 · ED4 line 208
* **Defect:** The teaser is the one released, audio-bearing artifact with no loudness owner. E claims "every audio-bearing released artifact" then enumerates only its own five kinds; the PROMO_CUT teaser is assembled by F's `release_v3.teaser_cut` from E's outputs, and phase-F-spec.md contains zero loudness/LUFS/ebur128 content (verified). The re-cut-sub-span measurement problem from M-2 applies even more strongly to a 30–60 s multi-episode re-cut.
* **Action:** Add an ED4 row pinning ownership: either F's `teaser_cut` runs E's ebur128/LoudnessReportV3 pattern (declared as a reusable seam) or the obligation is explicitly F's to spec — either way the "every artifact" claim becomes true family-wide.

### M-8 — Redundant second utterance-alignment capability vs a hard ED5 requirement
* **Sources:** ZO8-M2
* **Scope:** §1 decision 4 lines 73–76 · ED5 line 209 · O-E3 line 480 · §3 line 241 · §18 lines 506–507
* **Defect:** SPEC-v3 §4.6 already makes "Thai ASR word match" a required per-shot check in D's clip QA, so word timings are a byproduct D computes for every accepted clip. E nonetheless plans its own `UtteranceAligner` seam, a G-phase "qualified live Thai forced aligner" track, and precedence rules between the two — while ED5 asks for timings only "ideally". The fallback exists for a scenario D's own required check makes near-impossible, and its cost is concrete (a G qualification track listed as an §18 mitigation).
* **Action:** Make word timings a hard ED5 requirement (mandatory `ClipQaResult` field, not "ideally"); the aligner then shrinks to the offline fake with no G track. If the hedge is kept, O-E3 must say why D's always-run ASR output cannot be the single source.

### M-9 — Brand-new render surfaces have no acceptance coverage of the render itself
* **Sources:** ZO8-M3
* **Scope:** §1 decisions 7–8 lines 97–115 · §3 step 2 line 224–227 · §13 E5 line 426 · E-T2/E-T6 lines 442/446
* **Defect:** Today's export graph has no still/overlay/compositing capability (verified — the only non-clip primitive is `anoisesrc`), so the composited CTA card and the recap prefix with foreign-episode native audio are new machinery. E-T6 proves copy resolution, caps, bindings and refusals — never that either segment renders, decodes, and lands with correct streams/duration in the assembled master; E-T2's fixture is a plain two-speaker episode.
* **Action:** Extend E-T6 (or make E-T2's fixture an episode-2 with both segments) to assert the assembled master containing the recap prefix and composited CTA decodes with correct streams, duration, and A/V alignment.

### M-10 — E-T10 covers only 2 of the 5 pinned A4 rebuild edges
* **Sources:** IR9-M3
* **Scope:** E-T10 line 450; edges pinned at §1.13 lines 142–149
* **Defect:** Five rebuild edges are pinned as the PF-10 obligation F8 waits on; E-T10 drives only predecessor-approval→recap and calendar→CTA. Three registered edges (source shot asset/`ShotPlanV3` revision → assembly; library revision → cue sheets; caption text revision → tracks) have no acceptance test, so E7's delivery can pass its gate unproven.
* **Action:** Extend E-T10 (or add E-T10b) to drive each of the five registered edges and assert new-version rebuild plus stale-result quarantine.

### M-11 — The positive readiness → production-track transition path is untested
* **Sources:** IR9-M4
* **Scope:** §13 E7 line 428 vs E-T5/E-T7/E-T10
* **Defect:** E7 builds "readiness + production-track transition" — the phase-exit criterion — but no test proves the positive completion path (zero blockers ⇒ step-7-closing transition through A's API, episode visible to F's step 8). E-T5 proves only the negative loudness case.
* **Action:** Add to E-T7 or E-T10 a fixture episode with zero blockers asserting the transition and F-step-8 visibility, with state names as pinned in the E1 note.

### M-12 — O-E4's fallback is underspecified if C does not pin the library manifest before E6
* **Sources:** IR9-M5
* **Scope:** §16 O-E4 line 481
* **Defect:** The fallback ("reads asset descriptors only and marks mood-matching `UNVERIFIED`") leaves open: which descriptor fields exist (the unpinned thing itself); `UNVERIFIED` is the author's fact-marker, not a runtime state — TechnicalChecks use PASS/FAIL/UNKNOWN, so whether an unverified mood-match blocks readiness is undecided; and the mood-less selection algorithm is unstated.
* **Action:** Pin the fallback: descriptor fields read, check state used (presumably UNKNOWN) and its blocking semantics, and the deterministic mood-less selection rule.

### M-13 — "G" is used as owner of load-bearing deferrals but never identified
* **Sources:** CP6-1
* **Scope:** lines 241, 278, 480, 240, 512–513
* **Defect:** G is cited as responsible for the ffmpeg build pinning (§5 determinism), the Thai forced-aligner qualification (caption timing), and the production CPU quota — yet is never introduced; it is defined only in SPEC-v3.md §15's phase table, which this document never cites, and is not in the precedence chain (lines 3–6).
* **Action:** One clause at first use, e.g. "phase G (the SPEC §15 phase that completes and qualifies the production composition and live switches)".

### M-14 — §18 mitigation cites a "≥2-day buffer rule (F §6.3)" that does not exist as such
* **Sources:** IR9-M6
* **Scope:** §18 lines 514–516
* **Defect:** F §6.3 enforces buffer at LAUNCH as ≥5 approved episodes (also V3-AT-12) and only monitors during RELEASING with an alert below 2 days (target ≥3). There is no enforced ≥2-day floor; 2 days is an alert threshold. A risk mitigation grounded in a misread rule gives false safety.
* **Action:** Restate as "the LAUNCH ≥5-approved gate plus the <2-day buffer alert (F §6.3)".

### M-15 — `EditV3Store` is introduced in §13 but defined nowhere
* **Sources:** IR9-M7
* **Scope:** §13 E1 line 422; §2 lines 168–176
* **Defect:** §2 defines the store solely as the `v3_edit_documents` table; `EditV3Store` appears exactly once — in the build contract. A builder cannot tell whether it is a store accessor class, a rename, or a second object. §2.1's standing rule says every E identifier is pinned before E1 is accepted.
* **Action:** Define it once in §2 ("store accessor `EditV3Store` over `v3_edit_documents`") or reuse §2's vocabulary in the cell.

### M-16 — O-E2 names F5's surface `upload_captions`; the contract calls it `deliver_captions`
* **Sources:** IR9-M8
* **Scope:** §16 O-E2 line 479; §1 line 88, ED4 line 208
* **Defect:** Per phase-F-spec.md:931, `release_v3.deliver_captions` is the F5 surface and `upload_captions` is the YouTube sub-operation inside it. A build-gating action item ("confirm before E3") aimed at a differently named surface can confirm the wrong thing.
* **Action:** Use one name, or "F5's `release_v3.deliver_captions` (YouTube `upload_captions` leg)".

### M-17 — Wrong migration cite `M/0004:73` under "Verified in particular", contradicting the document's own correct cite
* **Sources:** CR7-M4 (severity split: style Major; design/structural Nit — highest recorded) · ZO5-3 (Nit, merged)
* **Scope:** line 180 vs lines 63–64
* **Defect:** Line 180 cites `M/0004:73` for the `locale` fact; line 73 of the migration is `schema_version`, the `locale` column is line 75 — which line 63 cites correctly. The duplicate pointer sits under "Verified in particular" while contradicting the document's own earlier citation, with wording drift ("free text" vs "unconstrained text"). The authority model rests on precise cites read on today's tree.
* **Action:** Correct to `M/0004:75` and use one term in both places.

### M-18 — Self-negating headline: "The edit gate is readiness, not a gate."
* **Sources:** CR7-M5
* **Scope:** line 134 (§1 decision 12 headline)
* **Defect:** The document names its headline deliverable "the edit gate" (title, §0 item 6, §9 heading) and then defines the name as its own negation; the bolded headline is the scannable layer a fresh reader hits first.
* **Action:** Reword, e.g. "Step 7 has no gate of its own; 'the edit gate' is E's readiness computation, consumed by Gate 2".

### M-19 — Garbled sentence defining the gap-fill trigger (E's only paid job)
* **Sources:** CR7-M6
* **Scope:** §7 lines 319–320
* **Defect:** "SFX needs the library lacks ride `edit_v3.sfx_fill` …" — a center-embedded relative with no relativizer; on first pass it scans as a typo. This sentence defines the trigger for the phase's only paid work and must parse on first read.
* **Action:** "SFX needs absent from the library ride `edit_v3.sfx_fill`…" or "Library gaps (SFX needs the library does not cover) ride…".

### M-20 — §15 findings-routing sentence is undecodable alone
* **Sources:** IR9-M9
* **Scope:** line 470
* **Defect:** "audio-side findings route to D/QA repair (`qa/repairs.py` → E rebuild, FM §9)" compresses three parties, an undefined slash-pair, and an arrow of unclear direction into one line; §8 line 336 has the real routing but §15 cannot be decoded standalone.
* **Action:** "audio-side findings route back to D as QA findings (`qa/repairs.py`); a completed repair triggers an E rebuild."

### M-21 — "N−1-style rebuild churn" (§19 item 3) is unparseable
* **Sources:** IR9-M10
* **Scope:** line 534
* **Defect:** "N−1-style" modifies nothing defined; a reader can settle on "same-episode churn" rather than the intended cascade through every successor.
* **Action:** "…would force rebuild churn cascading through every successor of N−1."

---

## 🟢 Nits (43)

### Spec-mechanics gaps

| ID | Scope | Defect → Action | Source |
| --- | --- | --- | --- |
| N-1 | §10 lines 369–375; §9 lines 345–354 | Data-flow endpoints unspecified: nothing states what observes step-6 completion and dispatches `edit_v3.assemble`; likewise when `edit_readiness(episode)` is evaluated and how derived blockers materialize into package conditions → name the trigger/evaluator at both ends (A6b schedule or the production-track transition) | ZO5-6 + ZO8-N2 |
| N-2 | §9 lines 346–347 | Duration-band check operand undefined (story body vs assembled total incl. recap/CTA/transition overlap) → pin the operand | ZO8-N1 |
| N-3 | §9 lines 345–349 | Readiness blockers enumerated descriptively while typed names live at their definitions; "unbound" appears nowhere else → consolidate typed names in §9, define or drop "unbound" | CR7-N13 |
| N-4 | §2 E-2 line 177 | E-2 grows only `jobs.queue`; `reservations.queue` carries the same closed CHECK — safe only because edit-lane jobs never reserve (stated nowhere) → record the invariant in E-2 | CR7-N6 |
| N-5 | §11 lines 390–392; §9 lines 361–364 | Operator `rebuild_edit_media` vs amendment-coordinator Apply serialization unwritten (E7 flagged "amendment races") → pin that the command funnels through the coordinator queue / A §7.3 fencing | ZO5-8 |
| N-6 | §15 line 462 | "(every source clip carries inspection evidence at acceptance)" asserted as a D-side given with no phase-D spec and nothing in the tree recording it → state as an ED5 requirement or mark `UNVERIFIED` | IR9-N13 |
| N-7 | §15 lines 462–465; §19 line 544 | C/D accountability division (C owns the seam, D ran it) never stated; "without C inspection evidence" wants "C-side" → one clause settles it | IR9-N14 |
| N-8 | §1.8 lines 112–114 | CTA libass typesetting cites the poster-seam rule as precedent, but the poster composes pre-typeset images with no libass; the libass exception is the caption-burn path → name the conscious deviation and route for C's §12.2 sign-off | ZO5-4 + CR7-N4 |

### Citations & cross-references

| ID | Scope | Defect → Action | Source |
| --- | --- | --- | --- |
| N-9 | line 294 | "(O-E1's recommendation)" attached to the no-per-locale-hooks ruling is O-E6's, not O-E1's → fix the xref | ZO5-2 |
| N-10 | line 234; line 79 | `amix` rule is at `export.py:118` today, not `:113` (stale from e-factmap §1); `captions.py:48-139` spans 49–140 → re-point so "cites read today" holds | CR7-N1 |
| N-11 | line 258 | "FM context note §128" collides with the `FM §n` section convention (e-factmap has §1–§10) → cite "e-factmap.md:128 (context note)" | CR7-N2 |
| N-12 | lines 129, 161, 321 | Bare "§10.5" breaks the bare-§n = this-document convention (this §10 has no .5) → qualify as "SPEC §10.5" | CR7-N3 |
| N-13 | lines 317–318 | `adjust_mix` referenced to §12 (UI) but defined in §11 → point at §11 | CR7-N5 |
| N-14 | §13 lines 415–416 | "F5/F8 unblock when E is accepted" understates F's own condition ("until E is accepted **and its export/caption contract is pinned**"; PF-10 edges pinned by E7, not at acceptance) → mirror F §13's wording | IR9-N2 |
| N-15 | line 539 vs line 111 | Same F §8.2 quote cited as `785-786` and `785-788` → pick one range | IR9-N19 |
| N-16 | §17 lines 487–500 | Column header "Requirement (REQUIREMENTS.md)" mislabels V3-AT-10/25, defined in SPEC-v3.md:901/:916 → relabel or split the AT rows | IR9-N17 |

### Conventions & terminology

| ID | Scope | Defect → Action | Source |
| --- | --- | --- | --- |
| N-17 | line 8 + throughout | `S/` and `M/` path shorthand and the "0001:77" migration-line form never defined → extend the line-8 conventions sentence with the two roots | CP6-4 |
| N-18 | lines 187, 479, 432 + softer cases | Unanchored labels: AR-4, "T032 evidence", "hard rule 5" (no source list — SPEC §1 vs runbook); softer: V3C-15, V3R-6, DBR-2, T015, T019, "W07-equivalent" → gloss or link at first use | CP6-3 + IR9-N3 + IR9-N15 |
| N-19 | ~12 lines | Locale/language shorthand drift ("TH"/"Thai"/"th-TH"; "ZH" vs "zh-CN") → BCP-47 for identifiers, one prose form | CR7-N7 |
| N-20 | lines 97/106 vs 188/285/288 | Duration caps in two units ("≤10 s" vs "≤10 000 ms"; validators are ms) → pick ms (or dual at first mention) | CR7-N8 |
| N-21 | lines 34, 91–92, 275–276 | Loudness tolerance in three notations; only one states the ≤ ceiling relation → one canonical form | CR7-N9 |
| N-22 | lines 76 vs 322 | "fake offline" vs "Offline fake adapter" → pick one | CR7-N11 |
| N-23 | lines 91–92 vs 268–269 | Loudness artifact list named two ways → name the canonical set once in §5 | CR7-N12 |
| N-24 | lines 127 vs 122/250/317; 209 vs 331; 392 vs 355 | "utter spans" clipping; speaker-count forms; "Gate-2" vs "Gate 2" → normalize to dominant forms | CR7-N17 |
| N-25 | line 332 vs 209 | "refuses typed on any gap" vs "blocks (typed)" → "blocks with a typed blocker (`edit.binding_incomplete`)" in both | CR7-N10 |
| N-26 | line 119 | "synchronised … honoring" British/American mixture → "honouring" | CR7-N15 |
| N-27 | line 8 | Only first-person clause in the document ("anything I could not verify") → impersonal form like phase-F-spec | CR7-N16 |
| N-28 | §13 lines 415–431; §9 line 353 | Note/critique build loop ("the E1 note", "A1 note §6 format", "Critiqued first", `ai-route build -w`) assumed; "package" at 353 is a third sense → one clause + link to A1-design-note.md §6; disambiguate "the Gate 2 review package" | CP6-5 |
| N-29 | lines 143–144, 361, 375, 428, 450 | "A4 DependencyProvider" / "A4 closure" never glossed or linked at any of five uses → link phase-A-spec.md at first use | CP6-6 |

### Sentence-level parseability

| ID | Scope | Defect → Action | Source |
| --- | --- | --- | --- |
| N-30 | lines 35–36, 143–144, 273–274, 350–351 | Four stacked/compressed constructions ("the pinned rebuild contract F8's amendment closure waits on"; odd dash after "for"; "exceed" as noun; "production-track transition closing step 7" noun stack) → unpack | CR7-N18 |
| N-31 | lines 30–31 | §0 item 3 reads as both segments binding both authorities → "each bound to its own authority (recap → approval; CTA → calendar)" | CR7-N19 |
| N-32 | lines 415–417 | §13 prerequisites parenthetical stacks condition + xref + constraint; "Real migration numbers allocated…" verbless → split into 2–3 sentences | IR9-N1 |
| N-33 | line 461 | "Unknown ≠ PASS everywhere" mis-parses as "≠ (PASS everywhere)" → "the rule Unknown ≠ PASS applies to every check" | IR9-N12 |
| N-34 | line 482 | O-E5 "rename" used intransitively → "can be renamed without design change" | IR9-N16 |

### Acceptance-table precision

| ID | Scope | Defect → Action | Source |
| --- | --- | --- | --- |
| N-35 | line 441 | E-T1 "byte-identical" lacks a comparator (before/after what?); verbless clause chains → "unchanged by the E migrations" + verbs | IR9-N4 |
| N-36 | line 443 | "short-measured shot" coined, ambiguous (below plan requirement vs failed measurement) → define or spell out | IR9-N5 |
| N-37 | line 444 | "(TH-mastered)" collides with clean/burned-master vocabulary → "(TH is the timing master)" | IR9-N6 |
| N-38 | line 446 | E-T6 "hash-bound to its effective approval" — "its" attaches to recap or predecessor → "the predecessor's effective approval" | IR9-N7 |
| N-39 | line 448 | E-T8 duck-depth assertion is a garden path and ambiguous between config default and per-cue profile depth (§2 line 189) → state the bound's source, reword the Pass criterion | IR9-N8 |
| N-40 | lines 442–447 vs 495 | §14 tagging/bold/delimiter conventions inconsistent (E-T3/E-T5 untagged; "/" vs "," delimiters) → tag all traced tests or none; one delimiter | IR9-N9 |
| N-41 | line 449 vs §1.15 | Crash-replay idempotency asserted only for `sfx_fill`; the V3 EDL-hash input change is uncovered by existing V1 replay tests → add an E-T2 restart-replay case | IR9-N10 |
| N-42 | line 451 | E-T11 "preview cards match Gate 2's" is unexecutable at the E8 gate (F4 builds after E) → pin the proxy: same document/render path F will consume (§12, ED4) | IR9-N11 |
| N-43 | line 500 | §17 V3-AT-25 row omits §6, which explicitly carries the derivation checks → add §6 | IR9-N18 |

---

## Traceability Matrix (raw → consolidated)

Raw IDs: **ZO5-n** = `zoom_out_report.md` findings in order (1 Major + 7 Nits); **CP6-n** = `comprehension_report.md` findings 1–6; **CR7-Bn/Mn/Nn** = `critic_report.md` labels; **ZO8-n** = `intermediate_zoom_out_report.md` findings in order (4 Majors + 2 Nits; **ZO8-G** = its uncounted guidance note); **IR9-Mn/Nn** = `implementation_readiness_report.md` findings in positional order (labels are positional — that report's headings are unlabeled).

| Raw | Raw sev | → Item | Final sev | Disposition |
| --- | --- | --- | --- | --- |
| ZO5-1 seam "reused unchanged" | Major | M-1 | Major | merged with IR9-M2, CR7-N14 |
| ZO5-2 O-E1→O-E6 xref | Nit | N-9 | Nit | kept |
| ZO5-3 M/0004:73 vs :75 | Nit | M-17 | Major | merged into CR7-M4 (highest sev) |
| ZO5-4 libass/poster rule | Nit | N-8 | Nit | merged with CR7-N4 |
| ZO5-5 provenance gate unplaced | Nit | M-6 | Major | merged into IR9-M1 |
| ZO5-6 assemble trigger | Nit | N-1 | Nit | merged with ZO8-N2 (same gap class) |
| ZO5-7 loudness recovery verb | Nit | M-2 | Major | merged into CR7-M1 |
| ZO5-8 rebuild vs Apply serialization | Nit | N-5 | Nit | kept |
| CP6-1 "G" unidentified | Major | M-13 | Major | kept |
| CP6-2 transition decision source | Major | M-5 | Major | kept |
| CP6-3 unanchored labels | Nit | N-18 | Nit | umbrella for IR9-N3, IR9-N15 |
| CP6-4 S//M/ shorthand | Nit | N-17 | Nit | kept |
| CP6-5 note workflow assumed | Nit | N-28 | Nit | kept |
| CP6-6 A4 unglossed | Nit | N-29 | Nit | kept |
| CR7-B1 replay identity | Blocker | B-1 | Blocker | merged with ZO8-M4 (fix constraint) |
| CR7-M1 single loudness gain | Major | M-2 | Major | absorbs ZO5-7 |
| CR7-M2 recap caption text | Major | M-3 | Major | annexes ZO8-G guards |
| CR7-M3 EN/ZH mismatch text | Major | M-4 | Major | kept |
| CR7-M4 M/0004:73 cite | Major | M-17 | Major | absorbs ZO5-3 |
| CR7-M5 self-negating headline | Major | M-18 | Major | kept |
| CR7-M6 garbled gap-fill | Major | M-19 | Major | kept |
| CR7-N1 stale export.py cite | Nit | N-10 | Nit | kept |
| CR7-N2 FM §128 format | Nit | N-11 | Nit | kept |
| CR7-N3 bare §10.5 | Nit | N-12 | Nit | kept |
| CR7-N4 poster-seam attribution | Nit | N-8 | Nit | merged with ZO5-4 |
| CR7-N5 adjust_mix §12→§11 | Nit | N-13 | Nit | kept |
| CR7-N6 reservations.queue | Nit | N-4 | Nit | kept |
| CR7-N7 locale shorthand | Nit | N-19 | Nit | kept |
| CR7-N8 duration units | Nit | N-20 | Nit | kept |
| CR7-N9 loudness notation | Nit | N-21 | Nit | kept |
| CR7-N10 refuses-typed | Nit | N-25 | Nit | kept |
| CR7-N11 fake adapter naming | Nit | N-22 | Nit | kept |
| CR7-N12 artifact list drift | Nit | N-23 | Nit | kept |
| CR7-N13 §9 descriptive blockers | Nit | N-3 | Nit | kept |
| CR7-N14 change in "unchanged" list | Nit | M-1 | Major | merged into seam item |
| CR7-N15 orthography | Nit | N-26 | Nit | kept |
| CR7-N16 first person | Nit | N-27 | Nit | kept |
| CR7-N17 terminology drift | Nit | N-24 | Nit | kept |
| CR7-N18 stacked constructions | Nit | N-30 | Nit | kept |
| CR7-N19 §0 item 3 dual binding | Nit | N-31 | Nit | kept |
| ZO8-M1 teaser loudness owner | Major | M-7 | Major | kept |
| ZO8-M2 redundant aligner | Major | M-8 | Major | kept |
| ZO8-M3 render coverage | Major | M-9 | Major | kept |
| ZO8-M4 B1 fix-shape hazard | Major | B-1 | Blocker | merged into B-1 as fix constraint |
| ZO8-N1 duration-band operand | Nit | N-2 | Nit | kept |
| ZO8-N2 readiness point | Nit | N-1 | Nit | merged with ZO5-6 |
| ZO8-G M2-fix guards (uncounted) | guidance | M-3 annex | — | annexed, not counted |
| IR9-M1 unassigned §15/§11 work | Major | M-6 | Major | absorbs ZO5-5 |
| IR9-M2 seam contradiction + C/M/R | Major | M-1 | Major | merged with ZO5-1, CR7-N14 |
| IR9-M3 E-T10 2/5 edges | Major | M-10 | Major | kept |
| IR9-M4 positive transition untested | Major | M-11 | Major | kept |
| IR9-M5 O-E4 fallback | Major | M-12 | Major | kept |
| IR9-M6 ≥2-day buffer misread | Major | M-14 | Major | kept |
| IR9-M7 EditV3Store undefined | Major | M-15 | Major | kept |
| IR9-M8 upload_captions name | Major | M-16 | Major | kept |
| IR9-M9 findings-routing sentence | Major | M-20 | Major | kept |
| IR9-M10 "N−1-style churn" | Major | M-21 | Major | kept |
| IR9-N1 prerequisites dense | Nit | N-32 | Nit | kept |
| IR9-N2 F condition dropped | Nit | N-14 | Nit | kept |
| IR9-N3 hard rule 5 source | Nit | N-18 | Nit | merged into CP6-3 umbrella |
| IR9-N4 E-T1 comparator | Nit | N-35 | Nit | kept |
| IR9-N5 short-measured | Nit | N-36 | Nit | kept |
| IR9-N6 TH-mastered | Nit | N-37 | Nit | kept |
| IR9-N7 E-T6 antecedent | Nit | N-38 | Nit | kept |
| IR9-N8 duck depth | Nit | N-39 | Nit | kept |
| IR9-N9 §14 tagging | Nit | N-40 | Nit | kept |
| IR9-N10 crash replay coverage | Nit | N-41 | Nit | kept |
| IR9-N11 E-T11 executable | Nit | N-42 | Nit | kept |
| IR9-N12 Unknown ≠ PASS | Nit | N-33 | Nit | kept |
| IR9-N13 D-side evidence unmarked | Nit | N-6 | Nit | kept |
| IR9-N14 C/D division | Nit | N-7 | Nit | kept |
| IR9-N15 T032 gloss | Nit | N-18 | Nit | merged into CP6-3 umbrella |
| IR9-N16 rename intransitive | Nit | N-34 | Nit | kept |
| IR9-N17 §17 header | Nit | N-16 | Nit | kept |
| IR9-N18 V3-AT-25 §6 | Nit | N-43 | Nit | kept |
| IR9-N19 F §8.2 range | Nit | N-15 | Nit | kept |

**Dedup decisions (10 reductions, 75 counted raw → 65 consolidated):** ZO5-1+IR9-M2+CR7-N14 → M-1; ZO8-M4 → B-1; ZO5-3 → CR7-M4 (M-17); ZO5-4+CR7-N4 → N-8; ZO5-5 → IR9-M1 (M-6); ZO5-7 → CR7-M1 (M-2); ZO5-6+ZO8-N2 → N-1; IR9-N3 and IR9-N15 → CP6-3 (N-18). Severity on merged items takes the highest recorded severity (per the Stage 7 synthesizer's convention).

## Reading Order for the Spec Owner

1. **B-1** sits in the E2 deterministic core (already "critiqued first") and must be pinned in the E2 note, taking the second-key arm, before build.
2. **M-1 through M-5** are the remaining design-level contradictions/gaps in the same critiqued-first packages (E2/E3/E5); M-3 ships with its guard annex.
3. **M-6 through M-12** are plan-completeness defects in §13/§14 (unassigned work, untested edges/transitions/render surfaces, O-E4 fallback) — fix in the E-package rows and E-T rows before the E1 note is accepted.
4. **M-13 through M-21** and the nits are v0.2 editorial fixes (identification of G, misread F rule, undefined identifier, wrong surface name, citation and parseability repairs).
