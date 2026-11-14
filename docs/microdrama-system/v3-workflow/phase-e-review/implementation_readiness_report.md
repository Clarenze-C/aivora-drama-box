# Goldfish Review Report

**Target:** `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-E-spec.md` (lines 413–545; §13 Build packages, §14 Acceptance, §15 QA and inspection, §16 Open questions, §17 Requirement trace, §18 Risks and limits, §19 Alternatives rejected)

## Reviewer Status

| Reviewer | Status |
| --- | --- |
| `egm-implementation-readiness` | completed |
| `egm-codebase-details` | completed |
| `egm-style` | completed |

Deduplication note: two overlapping findings were merged (provenance-completeness check placement — implementation-readiness + style; E-T8 duck-depth wording — implementation-readiness + style). Raw per-reviewer counts: implementation-readiness 4 Major / 3 Nit; codebase-details 2 Major / 3 Nit (per its enumerated findings; its own summary line overcounted nits); style 5 Major / 14 Nit. Consolidated below: **0 Blocker, 10 Major, 19 Nit**.

## Prioritized Findings (Blockers -> Major -> Nits)

### Blockers

None. No reviewer reported a Blocker finding. All three reviewers additionally verified as sound: E1→E8 sequencing and dependency order, package↔test gating consistency in both directions (§13 ↔ §14), completeness of §17 against the ten E-owned requirement IDs, migration/citation accuracy against the tree (`0001_foundation.sql:77`, `0004_media_and_qa.sql` DDL and triggers, `qa/repairs.py`, `make check`/`make pilot` targets, `SPEC-v3.md:843`, `phase-F-spec.md:978-991`, REQUIREMENTS.md R-7.x/R-12.8 texts), and open questions resolved before their dependent packages (O-E2 before E3, O-E4 before E6).

### §15 QA work and §11 `adjust_mix` are assigned to no build package and covered by no acceptance test - Severity: Major

* **Reviewer Lens:** `egm-implementation-readiness`, `egm-style` (placement overlap merged)
* **Affected Scope:** Lines 420–452 (§13/§14) vs 458–465 (§15) and 478 (§16 O-E1)
* **Discrepancy Description**: Four work items appear in the plan's prose but in no E1–E8 Builds cell and in no E-T test: (a) the `qa.technical` job re-registration for V3 episodes and the ASR caption cross-check (lines 458–461); (b) the provenance-completeness check for clips/cards entering an EDL (lines 463–465, "a gap is a typed blocker") — E-T8's "missing provenance ⇒ typed refusal" covers only the music/SFX library leg; (c) O-E1's recommendation says "Completeness now (E2)" (line 478) but §13's E2 row (line 423) does not list it, and "(E2)" is a bare, unexplained pointer; (d) the §11 `adjust_mix` operator verb (line 391; the tab-7 secondary action in §12) is in no package row (E6 lists cue sheets/ducking/sfx_fill only) and no test exercises its version-append/idempotency/re-enqueue behavior.
* **Rationale & Recommendation**: Work items that no package claims surface late (E8 or QA wiring) and force the implementer to decide placement — a zero-decision violation. Name the owning package for each item (provenance-completeness → E2 per O-E1; `qa.technical` re-registration + ASR cross-check → likely E7; `adjust_mix` → E6), add it to that package's Builds cell, and extend the tests (e.g. a clip-leg provenance blocker case in E-T2 or E-T8; an `adjust_mix` case in E-T8).

### S/editing seam scope contradiction: "Reused unchanged" vs "V3 branch", with no Create/Modify/Reuse marking - Severity: Major

* **Reviewer Lens:** `egm-codebase-details`
* **Affected Scope:** Lines 422–424 (§13 E2), 442 (E-T2); contradicts §2 lines 193–196 (context, outside range)
* **Discrepancy Description**: E2 builds "transitions in both exporters" and E-T2 asserts V3 behavior of the master/variant/burned planners — i.e. `plan_master` and its siblings get a V3 branch (§1.1/§3: "V3 extends its planners", "`plan_master`'s V3 branch"). But §2 lists the `S/editing` seam modules as **Reused unchanged**. No package row marks items Create/Modify/Reuse (the family idiom used by phase-F-spec §13), so the implementer must decide whether `S/editing/{edl,export,variants,captions}.py` are modified in place or wrapped by adapters in `S/editing_v3`.
* **Rationale & Recommendation**: The choice changes the V1-regression surface that E-T1's byte-identity gate must cover, so leaving it open is a zero-decision-rule violation with a test-design consequence. Mark each package row's items Create/Modify/Reuse and reconcile §2's "reused unchanged" with §1.1/§3's "extends"/"V3 branch" wording.

### E-T10 covers only 2 of the 5 pinned A4 rebuild edges - Severity: Major

* **Reviewer Lens:** `egm-implementation-readiness`
* **Affected Scope:** Line 450 (E-T10); edges pinned in §1.13 lines 142–149 (context)
* **Discrepancy Description**: §1.13 pins five A4 rebuild edges — predecessor approval → recap, calendar revision → CTA, source shot asset/ShotPlanV3 revision → assembly, music/SFX library revision → cue sheets, caption source text revision → tracks — and this pinned contract is the whole PF-10 obligation F8 waits on. E-T10 tests only the first two. E-T7's Revise-payload test (line 447) is the operator path, not the dependency edges.
* **Rationale & Recommendation**: Three of five registered rebuild edges have no acceptance test, so E7's PF-10 delivery can pass its gate unproven. Extend E-T10 (or add E-T10b) to drive each of the five registered edges and assert new-version rebuild plus stale-result quarantine.

### Positive readiness → production-track transition path is untested - Severity: Major

* **Reviewer Lens:** `egm-implementation-readiness`
* **Affected Scope:** Line 428 (E7 row) vs 445/447/450 (E-T5/E-T7/E-T10)
* **Discrepancy Description**: E7 builds "readiness + production-track transition" (§9: empty blockers ⇒ step-7-closing transition through A's API, episode available to F step 8), but no test proves the positive completion path. E-T5 proves only the negative (readiness blocks on a failing loudness report); E-T7/E-T10 prove other E7 items.
* **Rationale & Recommendation**: This is the phase-exit criterion and it is unasserted. Add to E-T7 or E-T10: a fixture episode with zero blockers ⇒ transition recorded through A's transition API and the episode visible to F's step 8 (state names as pinned in the E1 note).

### O-E4 fallback is underspecified if C does not pin the library manifest before E6 - Severity: Major

* **Reviewer Lens:** `egm-implementation-readiness`
* **Affected Scope:** Line 481 (§16 O-E4)
* **Discrepancy Description**: The fallback — "E6's cue proposal reads asset descriptors only and marks mood-matching `UNVERIFIED`" — leaves three things open: which descriptor fields exist today is exactly the unpinned thing; `UNVERIFIED` is defined nowhere as a runtime state (it is the author's fact-marker, while TechnicalChecks use PASS/FAIL/UNKNOWN with unknown ≠ PASS), so whether an `UNVERIFIED` mood-match blocks readiness or is informational is undecided; and the deterministic mood-less cue-selection algorithm is unstated.
* **Rationale & Recommendation**: The question is tracked with an actionable recommendation and a pre-E6 deadline, so E1–E5 are unblocked — but as written, E6's core deliverable is partially undefined if C does not answer. Pin the fallback: the descriptor fields read, the check state used (presumably UNKNOWN), its blocking semantics, and the mood-less selection rule.

### §18 mitigation cites a "≥2-day buffer rule (F §6.3)" that does not exist as such - Severity: Major

* **Reviewer Lens:** `egm-codebase-details`
* **Affected Scope:** Lines 514–516 (§18, recap serialization)
* **Discrepancy Description**: F §6.3 (phase-F-spec.md:527–539) enforces buffer at LAUNCH as **≥5 approved episodes** (also V3-AT-12, SPEC-v3.md:903) and only **monitors** during RELEASING with an **alert below 2 days** (target ≥3 days, phase-F-spec.md:916). There is no enforced ≥2-day floor; 2 days is an alert threshold. "With the ≥2-day buffer rule (F §6.3) this is safe" cites a rule that exists under neither that name nor that number. (The residual-behavior half of the sentence — zero-buffer seasons see visible `edit.recap_pending` blockers — remains correct.)
* **Rationale & Recommendation**: A risk mitigation grounded in a misread rule gives false safety. Restate as "the LAUNCH ≥5-approved gate plus the <2-day buffer alert (F §6.3)".

### `EditV3Store` is introduced in §13 but defined nowhere - Severity: Major

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Line 422 (§13 E1 Builds cell); §2 lines 168–176 (context)
* **Discrepancy Description**: §2 defines the store solely as the `v3_edit_documents` table; `EditV3Store` appears exactly once in the document — in the build contract. A builder cannot tell whether it is a new store accessor class over `v3_edit_documents`, a rename, or a second object.
* **Rationale & Recommendation**: §2.1's standing rule is that every E identifier is pinned before E1 is accepted; §13 introduces one that is not. Define it once in §2 ("store accessor `EditV3Store` over `v3_edit_documents`") or reuse §2's vocabulary in the cell.

### O-E2 names F5's surface `upload_captions`; the contract and §1 call it `deliver_captions` - Severity: Major

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Line 479 (§16 O-E2); §1 line 88 and ED4 line 208 (context)
* **Discrepancy Description**: Per phase-F-spec.md:931, `release_v3.deliver_captions` is the F5 surface and `upload_captions` is the YouTube sub-operation inside it. O-E2 is a build-gating action item ("confirm … before E3") pointing at a differently named surface than the one ED4 says E's contract pins.
* **Rationale & Recommendation**: A confirmation step aimed at the wrong-named surface can confirm the wrong thing. Use one name consistently, or write "F5's `release_v3.deliver_captions` (YouTube `upload_captions` leg)".

### §15 findings-routing sentence is undecodable alone - Severity: Major

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Line 470 (§15, findings routing)
* **Discrepancy Description**: "audio-side findings route to D/QA repair (`qa/repairs.py` → E rebuild, FM §9)" compresses three parties, an undefined slash-pair ("D/QA": D and QA? D via QA? D or QA?), and an arrow of unclear direction into one line. §8 (line 336) says these findings go to D as QA findings; §15 does not contradict that but cannot be decoded on its own.
* **Rationale & Recommendation**: Routing prose a builder cannot parse becomes wiring a builder guesses. Rewrite: "audio-side findings route back to D as QA findings (`qa/repairs.py`); a completed repair triggers an E rebuild."

### "N−1-style rebuild churn" (§19 item 3) is unparseable - Severity: Major

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Line 534 (§19, alternative 3)
* **Discrepancy Description**: "every pre-publication re-approval of N−1 would force N−1-style rebuild churn across all successors": "N−1-style" modifies nothing defined; a reader can plausibly settle on "same-episode churn" rather than the intended cascade through every successor.
* **Rationale & Recommendation**: The rejected-alternative rationale must carry its own weight. Rewrite: "…would force rebuild churn cascading through every successor of N−1."

### §13 prerequisites paragraph is dense and partially verbless - Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Lines 415–417 (§13 prerequisites)
* **Discrepancy Description**: The D-accepted parenthetical stacks a condition, a cross-reference, and a constraint in one breath; "Real migration numbers allocated in the E1 note after re-auditing the tail" has no verb. Both parse only at the cost of a second reading.
* **Rationale & Recommendation**: Split into two or three sentences.

### §13 drops F's own condition on the F5/F8 unblock - Severity: Nit

* **Reviewer Lens:** `egm-codebase-details`
* **Affected Scope:** Lines 415–416 (§13 prerequisites)
* **Discrepancy Description**: "F v0.4's F5/F8 unblock when E is accepted (F §13)" omits that F §13 (phase-F-spec.md:986–991) blocks F5 "until E is accepted **and its export/caption contract is pinned**" and keeps F8's PF-10 edges "BLOCKED until E **pins it**" — and the rebuild contract is pinned by E7, not at spec acceptance.
* **Rationale & Recommendation**: Mirror F's exact wording so the cross-phase dependency timing is not understated.

### "hard rule 5" cites no source list - Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Line 432 (§13 routing note)
* **Discrepancy Description**: "hard rule 5" resolves to SPEC-v3 §1 hard rule 5 ("Offline first", SPEC-v3.md:101), but WEEKEND-GLM-RUNBOOK.md:27 also has a numbered "Hard rules" list, so a fresh reader must guess the list and count.
* **Rationale & Recommendation**: Write "(SPEC §1 hard rule 5)".

### E-T1 "byte-identical" lacks a comparator; verbless clause chains - Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Line 441 (E-T1)
* **Discrepancy Description**: "byte-identical" never states before-vs-after what (the E migrations is implied); "rows … byte-identical and still refusing" and "generated contracts zero drift" are verbless chains.
* **Rationale & Recommendation**: Add "unchanged by the E migrations" and give the clauses verbs.

### "short-measured shot" is a coined, undefined compound - Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Line 443 (E-T3)
* **Discrepancy Description**: Ambiguous between "measured duration below the plan's requirement" and "a failed measurement".
* **Rationale & Recommendation**: Define the term or spell out the intended case.

### "(TH-mastered)" collides with the render vocabulary - Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Line 444 (E-T4)
* **Discrepancy Description**: The document's "master" vocabulary is clean master / burned master / master encode; "(TH-mastered)" is neither. Intended meaning: TH is the timing master (§4).
* **Rationale & Recommendation**: Write "(TH is the timing master)".

### E-T6 "hash-bound to its effective approval" has an ambiguous antecedent - Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Line 446 (E-T6)
* **Discrepancy Description**: "its" can attach to the recap or to the predecessor; only the predecessor has an effective approval.
* **Rationale & Recommendation**: Say "the predecessor's effective approval".

### E-T8 duck-depth assertion: garden-path wording and ambiguous source value - Severity: Nit

* **Reviewer Lens:** `egm-implementation-readiness`, `egm-style` (merged)
* **Affected Scope:** Line 448 (E-T8); §2 line 189 (context)
* **Discrepancy Description**: "music never overlaps dialogue above the configured duck depth" reads as a single config-owned depth, but §2 defines a per-cue "duck profile (depth/ramp)" — so the assertion's source value is ambiguous. The sentence is also a garden path: intended is "wherever music overlaps dialogue, its gain is at or below the configured duck depth".
* **Rationale & Recommendation**: State whether the bound is the config default or each cue's profile depth, and reword so the Pass criterion needs no re-parsing.

### §14 tag/bold/delimiter conventions are inconsistent - Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Lines 442, 443, 444, 445, 446, 447 (§14) vs 495 (§17)
* **Discrepancy Description**: E-T3 and E-T5 are traced in §17 (V3-AT-25, V3-AT-10) but untagged/unbolded in §14, while E-T2/E-T4/E-T6/E-T7 are bold+tagged; ID delimiters alternate between "/" ("R-12.8/R-7.7") and "," ("V3-AT-10, audio half").
* **Rationale & Recommendation**: Tag all traced tests or none; pick one delimiter.

### Crash-replay idempotency is tested only for `sfx_fill` - Severity: Nit

* **Reviewer Lens:** `egm-implementation-readiness`
* **Affected Scope:** Line 449 (E-T9) vs §1.15 lines 157–162 (context)
* **Discrepancy Description**: §1.15's restart-never-re-renders rule is asserted only for `sfx_fill` (E-T9). The V3 branch changes the EDL hash inputs (adds the audio-source binding), which the existing V1 replay tests do not cover.
* **Rationale & Recommendation**: Add an E-T2 case: restart after a stored V3 outcome replays without re-render.

### E-T11 "preview cards match Gate 2's" is not executable at the E8 gate - Severity: Nit

* **Reviewer Lens:** `egm-implementation-readiness`
* **Affected Scope:** Line 451 (E-T11)
* **Discrepancy Description**: F's Gate 2 V3 page is F4, which builds after E is accepted (phase-F-spec.md:986–987), so there is nothing to match against when E-T11 runs.
* **Rationale & Recommendation**: Pin the proxy assertion now: the tab-7 previews render from the same document/render path F will consume (per §12 "same data, no second render", ED4).

### "Unknown ≠ PASS everywhere" mis-parses - Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Line 461 (§15)
* **Discrepancy Description**: Reads as "≠ (PASS everywhere)"; intended: the rule applies everywhere.
* **Rationale & Recommendation**: Write "the rule Unknown ≠ PASS applies to every check".

### D-side clip-acceptance inspection evidence asserted without an UNVERIFIED marker - Severity: Nit

* **Reviewer Lens:** `egm-codebase-details`
* **Affected Scope:** Line 462 (§15)
* **Discrepancy Description**: "(every source clip carries inspection evidence at acceptance)" is asserted as a given D-side fact, but no phase-D spec exists (verified: no phase-D-spec.md in the v3-workflow directory) and nothing in today's tree records clip-acceptance inspection evidence. The claim is load-bearing: it justifies E not re-running §12.2 detection on source pixels.
* **Rationale & Recommendation**: State it as an ED5 requirement on D, or mark it `UNVERIFIED` until D's spec pins it.

### §15 C/D accountability division is never stated - Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Lines 462–465 (§15) with 544 (§19 item 7)
* **Discrepancy Description**: The §12.2 bullet head says "phase C accountable", the same bullet attributes inspected pixels to D, and §19 item 7 says evidence "from D"; the C-owns-the-seam / D-ran-it division is never stated. Also "without C inspection evidence" (line 464) wants "C-side".
* **Rationale & Recommendation**: One clause — "detection is C's seam, run on D's clips" — settles it.

### "T032" used without a gloss - Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Line 479 (§16 O-E2)
* **Discrepancy Description**: T032 is defined only outside the document (HANDOFF.md, REQUIREMENTS.md: live-publishing qualification task).
* **Rationale & Recommendation**: Add "(T032, live-publishing qualification)".

### O-E5 "rename" is used intransitively - Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Line 482 (§16 O-E5)
* **Discrepancy Description**: "E's placement records rename without design change" — rename to what is left implicit.
* **Rationale & Recommendation**: "can be renamed without design change".

### §17 column header mislabels the AT rows' source - Severity: Nit

* **Reviewer Lens:** `egm-codebase-details`
* **Affected Scope:** Lines 487–500 (§17 header and last two rows)
* **Discrepancy Description**: The column header "Requirement (REQUIREMENTS.md)" covers V3-AT-10/V3-AT-25, which are defined in SPEC-v3.md:901/:916, not in REQUIREMENTS.md (verified: REQUIREMENTS.md carries only R-7.x and R-12.8, whose texts the trace rows reproduce accurately).
* **Rationale & Recommendation**: Relabel the column or split the AT rows.

### §17 V3-AT-25 row omits §6 from "Where" - Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Line 500 (§17)
* **Discrepancy Description**: "Where" lists §8 only, but §6 (line 299) explicitly carries the V3-AT-25 derivation checks; the trace omits half the mapping.
* **Rationale & Recommendation**: Add §6.

### F §8.2 quote range cited inconsistently - Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** Line 539 (§19 item 5) vs line 111 (§1 decision 8, context)
* **Discrepancy Description**: The same quote is cited as `phase-F-spec.md:785-786` here and `785-788` in §1 (quoted words sit at 785–786; the sentence runs to 788).
* **Rationale & Recommendation**: Use one range.
