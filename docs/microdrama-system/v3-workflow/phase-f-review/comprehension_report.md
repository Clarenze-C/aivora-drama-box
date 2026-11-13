# Comprehension Report (Stage 6 — Comprehension Test)

**Target:** `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-F-spec.md` (FeatureRange lines 1-496, DetailedRange lines 497-567)

**Mode:** uninterrupted (Preset 1), headless. Reviewer: `egm-comprehension`, no document standard (self-containment test).

## Reviewer Status

| Reviewer | Status |
| --- | --- |
| `egm-comprehension` | completed |

Persona loaded from `/root/.local/share/egm/403d888/agents/comprehension.md`. All referenced sibling docs were read/searchable except phase-D/E specs, which do not exist as cited documents (finding 9); nothing blocked the review.

## What this proposes

Phase F is the "release" phase of a V3 workflow for a short-form drama ("microdrama") production-and-publishing system. It adds three workflow tabs (8: metadata/thumbnail drafts, 9: Gate 2 release approval, 10: season teaser) plus a Launch tab, implementing: per-destination episode metadata drafts with LLM prefill and operator editing; 2-3 thumbnail candidates with an operator pick; a Gate 2 approval that seals the edited drafts into a manifest; a teaser with its own gate (TEASER_FINAL) airing 3 days before the premiere and gating it; a versioned release calendar whose revision is bound by a LAUNCH decision; dispatch through an admission check requiring both content authority (effective approval) and calendar authority (LAUNCH); derived HELD/MISSED/PARTIAL per-destination states with operator-approved recoveries (repair/swap/push, reschedule, N11 corrective posts); amendment/extension fences; and throughput monitoring with SLO alerts. All V3 code is additive (new S/release_v3/ modules, new tables/migrations) and V1/V2 behavior is byte-preserved.

## How the existing system works, per this document

The existing system already publishes posts: platform_posts rows with dates pinned at insert and trigger-immutable, unique slot-identity columns, unique external ids, idempotent client tokens, a crash-safe 3-phase submit, and reconcile that adopts by external id and re-arms only proven-absent slots; destination problems hold a slot (HeldSlot) rather than fail the episode. Gate 2 approvals are bound to exact metadata versions via release_approval_manifests, and post-approval edits go through metadata_versions/ApprovedMetadataPolicy. Phase A of V3 contributed the decision-transaction gate pattern, the job/queue/budget system, and track state models that F builds on. V1/V2 pin post dates at schedule_release time; V3 instead creates the post row only at dispatch admission, when both authorities hold, so no V3 row is ever rescheduled, rewritten, or re-created.

## Findings

### Wrong internal cross-reference to the 30-episode simulation — Severity: Major

* **Reviewer Lens:** `egm-comprehension`
* **Affected Scope:** §7.5 "Never duplicated; proven absence re-arms", line 380
* **Discrepancy Description & Rationale:** Wrong internal cross-reference. Line 380 cites "the 30-episode simulation (F-T5)", but section 14 defines the 30-episode release simulation as F-T8 (line 531); F-T5 (line 528) is the drafts/manifest/thumbnail-pick test. Section 16 and SPEC-v3.md section 15 both map the simulation to V3-AT-29/F-T8. A reader following the pointer from 7.5 lands on the wrong acceptance test.

### CONTINUED/RESUMED extension modes never defined — Severity: Major

* **Reviewer Lens:** `egm-comprehension`
* **Affected Scope:** ReleaseCalendarV3 record, line 147; §8.4 "Extension", lines 419-421
* **Discrepancy Description & Rationale:** The extension calendar modes CONTINUED/RESUMED are named (calendar field line 147; "the operator picks continued vs resumed" line 419; ExtensionDecisionV3 stores the choice) but never defined — nothing states what distinguishes continuing from resuming (e.g., cadence gap vs no gap). A search of every sibling doc in /root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/ finds the pair only in this file, so the operator decision surface in 8.4 rests on an undefined distinction.

### Binding-input citations mis-attributed to DECISIONS.md — Severity: Major

* **Reviewer Lens:** `egm-comprehension`
* **Affected Scope:** Header "Binding inputs", lines 4-6
* **Discrepancy Description & Rationale:** Mis-attributed authority citations. The header says DECISIONS.md (V3C-26, Q6, O-8/N35, N11), but DECISIONS.md contains none of V3C-26, O-8, N35, or N11 (searched; only Q6 is there, line 61). V3C-26 and O-8 are in SPEC-v3.md (sections 4.3 and 19.1 respectively; N11 is glossed in SPEC-v3 section 9.2). A reader verifying the binding decisions against the named file cannot find three of the four items.

### "Explicitly closed out" is an undefined mechanism blocking COMPLETE — Severity: Major

* **Reviewer Lens:** `egm-comprehension`
* **Affected Scope:** §6.2, line 302 ("COMPLETE when every in-scope episode is verified or explicitly closed out on every destination")
* **Discrepancy Description & Rationale:** "Explicitly closed out" is an undefined mechanism. The Section 12 command table contains no close-out command, and phase-A-spec.md defines no such operation (searched). Since MISSED episodes' only stated recovery is reschedule, the reader cannot tell how a permanently unairable episode is ever retired so the season can reach COMPLETE.

### Bare decision/ruling IDs with no resolvable pointer — Severity: Nit

* **Reviewer Lens:** `egm-comprehension`
* **Affected Scope:** O-7 (lines 68, 291), O-3 (line 195), N21 (line 71), N35 (line 5), V3R-6 (line 266 heading)
* **Discrepancy Description & Rationale:** These IDs are cited as authorities with no inline gloss and no pointer the reader can follow. O-7 and O-3 resolve in SPEC-v3.md section 19.1 (outside the SPEC sections the header cites); N21, N35, and V3R-6 match no document in the workflow directory (N35 appears only in the header and is never used again). The rules themselves are stated inline in each case, so only the citations dangle. (N43 and N11 are handled: N11 is defined by apposition in 8.3; the doc itself discloses N43's absence in O-F8.)

### "CSF" vs "CSRF" inconsistency — Severity: Nit

* **Reviewer Lens:** `egm-comprehension`
* **Affected Scope:** Line 221, §4 ("the human-session/CSF rules")
* **Discrepancy Description & Rationale:** "CSF" is undefined and inconsistent with "CSRF" used at lines 390 and 487 for the same human-session protection. Apparent typo; a naive reader cannot rule out a distinct "CSF" concept.

### Unprefixed external section references collide with local numbering — Severity: Nit

* **Reviewer Lens:** `egm-comprehension`
* **Affected Scope:** §11 line 481 ("section 3.2's state set and one-primary-action rule"); §9 line 450 ("section 16.3, G"); §§0-1 SPEC references (4.8-4.10, 9.1-9.3, 9.2 item n, 12.6)
* **Discrepancy Description & Rationale:** Unprefixed external section references collide with this document's own numbering. Its 3.2 is "Thumbnails" (the rule lives in SPEC-v3 section 3.2, per phase-B-spec's "master 3.2 N18"); its 16 is the trace table with no 16.3 (SPEC-v3 16.3 is meant); and the SPEC 4.x/9.x/12.6 references share numbers with local sections 4, 9, 12. Elsewhere the doc consistently writes "SPEC n"; doing so here would remove the ambiguity.

### Team workflow agents/tooling named without identification — Severity: Nit

* **Reviewer Lens:** `egm-comprehension`
* **Affected Scope:** Status lines 3-4 ("GLM (weekend runbook)", "Goldfish (phase-f-review/)", "Codex critique"); §13 line 516 ("ai-route build -w")
* **Discrepancy Description & Rationale:** Team workflow agents and tooling are named without identification or pointer. The project's own phase-B review flagged the same issue ("GLM/Codex unexplained"), so the convention exists but is not applied here.

### Phases D and E are load-bearing but never cited as documents — Severity: Nit

* **Reviewer Lens:** `egm-comprehension`
* **Affected Scope:** §0 lines 34-37; §13 lines 499-500 (phases D and E)
* **Discrepancy Description & Rationale:** Phases D and E are load-bearing (E supplies the EDL/export artifacts the teaser assembles and the caption timing Gate 2 checks; "B, C, E accepted" is a build prerequisite) yet, unlike A/B/A0/C, no phase-D-spec or phase-E-spec filename or version is ever cited, so "E accepted" cannot be verified from this document.

## Stage Verdict

No Blockers: every section, including the DetailedRange (§§13-16: build packages F1-F10 with per-package gates, offline acceptance tests F-T1-F-T13, ten open questions with recommendations, and the requirement trace), paraphrases coherently. 0 Blocker, 4 Major, 5 Nit.
