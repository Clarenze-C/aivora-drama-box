# Goldfish Review Report

**Target:** `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-E-spec.md` (lines 1-545)

## Reviewer Status

| Reviewer | Status |
| --- | --- |
| `egm-zoom-out` | completed |

## Prioritized Findings (Blockers -> Major -> Nits)

### No Blockers

No Blocker-severity findings were reported by the reviewer. (Per the zoom-out standard: context sufficiency passes, the design solves the root problem rather than the TTS-laying symptom, no YAGNI/premature-optimization violations, and altitude is maintained at architecture/interfaces/data-flow level throughout.)

### "Reused unchanged" seam claim contradicts the spec's own extension plan - Severity: Major

* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** Lines 193-196 (§2 "Reused unchanged: ... the `S/editing` seam modules") vs lines 52-53 (§1.1), 231-235 (§3.3), 248-250 (§4), 423 (§13 E2)
* **Discrepancy Description**: Internal contradiction on a load-bearing reuse claim. §2 lists "the `S/editing` seam modules" under **"Reused unchanged"**, but §1.1 says "V3 **extends its planners** for native audio", §3.3 builds "(`plan_master`'s V3 branch)" inside the seam, §4 changes what the caption spotter's window measures, and the E2 package delivers "transitions in both exporters" — all modifications to `S/editing/{edl,export,captions}.py`. The modules are reused as the one implementation, but not unchanged.
* **Rationale & Recommendation**: A build reviewer scoping E1/E2 from §2 would wrongly conclude the seam diff is out of scope, and the contradiction undercuts the doc's own anti-fork argument (§1.1, §19.1). Reword §2 to "reused as the single implementation, extended with V3 branches; V1 plans byte-identical (asserted at every package gate)". Keep the claim testable: state which V1 planner outputs are pinned byte-identical (E-T12's `make check` + V1 `make pilot` covers behavior, but the spec should name the invariant).

### Wrong cross-reference for the per-locale caption ruling - Severity: Nit

* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** Line 294 (§6)
* **Discrepancy Description**: "(O-E1's recommendation)" is attached to hooks/variants carrying no per-locale caption tracks; that ruling is **O-E6** (line 483). O-E1 is burned-render frame sampling.
* **Rationale & Recommendation**: Fix the cross-reference; a reader chasing O-E1 would conclude hooks need an allowlist sampling contract, which is a different question.

### Divergent migration line cites for the same fact - Severity: Nit

* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** Line 180 (§2) vs line 63 (§1.2)
* **Discrepancy Description**: Line 180 cites `M/0004:73` for "`caption_tracks.locale` is unconstrained text"; the `locale` column is at 0004:75 (line 73 is `schema_version`). Line 63 cites `:75` correctly — the two cites for the same fact disagree.
* **Rationale & Recommendation**: Correct to `M/0004:75`. Trivial, but this document family trades on precise cites and the same fact is cited twice differently.

### CTA libass typesetting misstates the poster-seam rule as precedent - Severity: Nit

* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** Lines 112-114 (§1.8 CTA visuals)
* **Discrepancy Description**: "licensed-font typesetting through the existing libass path (the poster seam's rule — no live text in a filter graph beyond libass itself, FM §3)". FM §3's poster rule is stricter than stated: the poster composes **already-typeset, approved image assets** and contains no libass at all; the libass exception belongs to the caption-burn path, not the poster seam. E's CTA (libass typesetting of date-dependent copy inside the export graph) is a conscious **deviation** from the poster rule, not an application of it.
* **Rationale & Recommendation**: The design itself is defensible (deterministic, licensed fonts, C's FONT provenance applies), but citing the poster rule as precedent misstates it. Name the deviation explicitly and route it for C's §12.2 sign-off, the same way O-E1 handles the detector-allowlist contract.

### Clip/card provenance-completeness gate has no package and no test - Severity: Nit

* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** Lines 466-468 (§15) and line 478 (O-E1 recommendation "Completeness now (E2)") vs line 423 (§13 E2 row) and §14
* **Discrepancy Description**: The clip/card provenance-completeness check ("no clip/card asset enters an EDL without C inspection evidence and a ProvenanceRecord") is pinned by O-E1's recommendation to E2, but §13's E2 build list omits it, and no acceptance test asserts it — E-T8 asserts provenance refusal only for music/SFX cue sheets; E-T3 asserts binding, not provenance.
* **Rationale & Recommendation**: Add the check to the E2 build row (or wherever intended) and extend one E-T (E-T2 or E-T3) to assert a typed refusal for a clip lacking inspection evidence/provenance. A §15 gate condition with no package and no test is unenforceable at review time.

### No stated trigger for `edit_v3.assemble` - Severity: Nit

* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** Lines 369-375 (§10 job table), §3 (line 218)
* **Discrepancy Description**: No stated trigger for `edit_v3.assemble`. §10 lists lanes/waits and §2 (line 195) gives "W07-equivalent scheduling" only for `qa.technical`; nothing says what observes step-6 completion (all shots accepted/bound) and dispatches assembly. The family's answer (A6b schedule registry / production-track transitions, §9) is only half-referenced.
* **Rationale & Recommendation**: One sentence naming the scheduler/trigger (e.g. A6b W07-equivalent schedule or the production-track transition entering step 7) closes the data-flow start-point gap. Context is otherwise sufficient, so this stays a nit.

### Derivative loudness miss fails closed with no recovery verb - Severity: Nit

* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** Lines 273-275 (§5)
* **Discrepancy Description**: Loudness uses one session-wide gain computed from the clean master and applied to every export, with re-measurement per artifact. Derivatives that re-cut audio (hooks are 20-40 s windows, the 90 s preview) can have integrated LUFS diverging from the master's beyond ±1; the doc narrates remediation only for the true-peak-exceed case. A derivative LUFS miss fails closed (blocker `edit.loudness_fail`) but has no specified recovery verb — `adjust_mix` is cue-sheet-scoped, and a hook's loudness is not obviously a mix problem.
* **Rationale & Recommendation**: The simple single-gain rule is the right YAGNI call; state the fallback for a derivative miss (e.g. per-artifact supplementary gain recorded in that artifact's `LoudnessReportV3`, or an explicit "re-derive hook selection" path) so the gate never dead-ends an episode at step 7.

### Operator rebuild command vs amendment-coordinator Apply serialization unwritten - Severity: Nit

* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** Lines 390-392 (§11 `rebuild_edit_media`), §9 lines 361-364
* **Discrepancy Description**: Two triggers drive the same A4-registered rebuild handler — the operator command `rebuild_edit_media` and the amendment coordinator's Apply — and the doc does not state whether the command routes through (or serializes with) the coordinator. E7 is already flagged "Critiqued first (amendment races)", so the race is anticipated but the serialization rule is unwritten.
* **Rationale & Recommendation**: Pin in §11 that the command funnels through the same coordinator/handler queue (or reuses A §7.3 fencing), so an operator verb cannot race an in-flight Apply.

## Reviewer's Verification Notes (context for the findings)

The reviewer verified read-only against the tree that the document's reuse thesis is real, including: `edit_manifests` purpose CHECK covers FULL_EPISODE/PART/PROMO_CUT/HOOK and locale is unconstrained text (`/root/AIVORA/drama-box/microdrama/migrations/0004_media_and_qa.sql:56,75,87-89`); `TransitionKind`/`SlotKind` values (`/root/AIVORA/drama-box/microdrama/src/microdrama/contracts/enums.py:351-356,430-434`); DBR-2 overlap rule and gain bounds (`contracts/media.py:95,119-127`); per-locale cue-timing sharing (`editing/captions.py:49-139`); `caption_locales=("th-TH","en-US")` today (`editing/config.py:46`); jobs.queue CHECK (`migrations/0001_foundation.sql:77`); `budget/policy.py` and the A1 `WAITING_BUDGET`/`WAITING_PROVIDER` vocabulary. Spec citations to F-spec, B-spec, C-spec, A-spec, SPEC-v3, REQUIREMENTS, DECISIONS and e-factmap.md were spot-checked as accurate; sibling document stores (`v3_story_documents`, `v3_release_documents`, C's cast store) exist, so the E-1 mirroring claim is sound.

## Standard Sections With No Findings

- **0. Context Sufficiency**: passes — §0 states the problem (six enumerated gaps with FM evidence), what E builds, what E does not own, precedence, and the downstream F5 dependency.
- **1. Root Problem Focus**: no findings — the design solves the root switch (R-7.1 "must change": clip audio as the one dialogue/ambience source in the single seam) rather than patching the TTS-laying symptom.
- **2. Simplicity & Extensibility / YAGNI**: no violations beyond the loudness edge (Nit above) — no speculative abstractions (every `EditSessionV3` field is consumed by a pinned rebuild edge), no premature optimization, and the V1/V2-beside-V3 row risk is guarded by `require_workflow` plus E-T1 byte-identity and acknowledged in §18.
- **3. Anti-Weeds (Altitude Control)**: no findings — the document stays at architecture, interfaces, contracts, and data flow; named ffmpeg primitives are interface-level determinism commitments of the exporter seam, not implementation weeds.

## Verdict (as reported by the reviewer)

No Blockers. One Major (internal contradiction on the seam "reused unchanged" claim — a wording/scoping fix, not a design change). The design itself is judged exemplary from this altitude: maximal reuse of the one deterministic seam and its tables, minimal operator surface, derived-not-stored state, deterministic money path, and every speculative temptation explicitly rejected with verified rationale. Fix the Major and the nits in v0.2.
