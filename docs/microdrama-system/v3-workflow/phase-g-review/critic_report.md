# Stage 7 — Critic Report

**Target:** `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md` (FeatureRange, lines 1-454)
**Reviewers:** `egm-design`, `egm-structural`, `egm-style` (fresh instances) · Standards: `feature-spec-standard.md` (design, structural)
**Status:** completed — 0 Blocker / 8 Major / 13 Nit
**Run:** headless uninterrupted (Preset 1), 14 Nov 2026

All three reviewers cross-checked the spec's load-bearing citations against the actual referenced files
(master SPEC-v3.md, phase A0/A/B/C/E/F specs, A1-design-note, g-factmap, T031-R5, T031-benchmark-packet,
REQUIREMENTS, DECISIONS, and the cited code/migrations/drill lines). Raw findings: 29 (design 6, structural
8, style 15); after deduplication, 21 findings below. No reviewer reported an UNVERIFIED material claim;
the verification basis is folded into each finding.

## Reviewer Status

| Reviewer | Status |
| --- | --- |
| `egm-design` | completed |
| `egm-structural` | completed |
| `egm-style` | completed |

## Prioritized Findings (Blockers → Major → Nits)

No Blockers. All three reviewers judged the core architecture sound and consistent with the specs it
builds on (completion-check predicate, ops-document store, restore assertions, pilot discipline, lock
procedure split); the Majors are mechanism gaps and reference-integrity defects, not structural flaws.

### S7-1. "One alert per pause episode" mechanism under-specified - Severity: Major
* **Reviewer Lens:** `egm-design`
* **Affected Scope:** §4 (lines 232-254); §2.1 GD1/GD2 (lines 159-163); G-T2 claim (line 483, context)
* **Discrepancy Description**: The pause predicate is derived, never stored (AR-4), so rising-edge detection needs a durable record of the previous evaluation — the spec never names one, and attributes dedupe to "GD1's firing identity (`scheduler_firings`)", but a firing identity dedupes a single tick's effects (A §9.1.2), not an episode boundary across ticks/restarts. No recovery signal exists to close an episode: A §8.4 lists `track.wait_started`/`track.blocked` with no wait-ended event, and GD2 explicitly rules out new event names. A naive edge definition produces false episodes: A0 §5.1 clamps deferral `retry_at` to 60 s–6 h, so a `PACE_WEEK` deferral's `retry_at` expires long before the week reset; between expiry and the next refusal "any active `PACE_WEEK` deferral exists" (§4b) can read false mid-pause, creating a spurious falling/rising pair — exactly the spam G-T2 forbids. Also narrow: GD2 fixes `track='production'`, but §4 says the pause defers LLM jobs in three tracks (B planning, D directing, F prefill); a pause during planning (all of P0) or release would emit per-job waits but never the scope-level alert.
* **Rationale & Recommendation**: The outcome is tested (G-T2) but the mechanism is left to the builder; the two obvious implementations either store pause state (contradicting AR-4's spirit) or lose/duplicate episodes. In G2's design note: (a) define "active `PACE_WEEK` deferral" as a non-terminal job carrying `defer_reason=PACE_WEEK` regardless of `retry_at` (removes the retry-gap edge); (b) pin the durable edge source — e.g. each `g.quota_pause` firing durably records its evaluation as its effect intent, episode = maximal run of true evaluations, restart reconstructs the last evaluation from the firing record; (c) justify `track='production'`-only or generalize the jobless variant to the affected track.

### S7-2. Cross-profile evidence lineage for LIVE claims unspecified (pilot teardown destroys the evidence) - Severity: Major
* **Reviewer Lens:** `egm-design`
* **Affected Scope:** §2 documents table (lines 144-149), §7.1 (lines 344-350), §7.6 (lines 398-403), §10 `record_live_claim` (line 446)
* **Discrepancy Description**: The pilot runs in an isolated compose project with its own DB and volumes (decision 3, O-G1); `PilotRunV3`, the measured landing refs, and the verified-post/verification evidence behind each `LiveClaimV3` live in that pilot DB. The drill pattern the pilot profile cites (drill.sh:121-141) ends with `docker compose down -v` (drill.sh:141 — volumes destroyed). The spec never states pilot-profile retention, never says DB evidence is exported into `microdrama/evidence/pilot/`, and never says which store `record_live_claim` writes to (pilot DB or the production `v3_ops_documents`). A LIVE claim (master §16.2) whose "verified-post evidence refs" dangle after pilot teardown is a qualification artifact without durable evidence; no offline gate (G-T6/G-T7) tests retention.
* **Rationale & Recommendation**: Qualification records must outlive the profile that produced them. State explicitly: per-phase pilot evidence is exported to the committed files under `microdrama/evidence/pilot/` at each phase close (sha256-bound); `LiveClaimV3` rows are recorded in the production store and reference file artifacts plus pilot-DB identifiers as provenance; the pilot profile and its volumes are retained until the operator's §11/LIVE sign-off and only then torn down by a named runbook step.

### S7-3. P2's LIVE throughput acceptance is not operationalizable as specified - Severity: Major
* **Reviewer Lens:** `egm-design`, `egm-style`
* **Affected Scope:** §7.4 (lines 379-386); §9 (lines 431-437)
* **Discrepancy Description**: §7.4 states "sustained ≥1.25 approved episodes/day … buffer ≥3" read from F-6, but F-6/F §9 defines the sustained rate as a rolling 7-day aggregate over complete intervals, and P2 is 3 further episodes on a compressed calendar (~2-3 days of intervals, ~4 approved episodes total). Read literally, either the window is padded with pre-release zero days (making ≥1.25/day arithmetically unreachable) or it is shortened (in which case it is not the §9.4 "sustained" definition being accepted). The catch-up criterion (≥2/day × 2 consecutive days) is only "where the schedule allows" — an undersized predicate on a LIVE acceptance number: the calendar dates are operator-chosen in the same sentence, making the condition circular, while §9's signed §16.3 row ("Throughput ≥ the §9.4 SLO at cost ≤ cap", SPEC-v3.md:969) covers catch-up unconditionally. The spec never defines the pilot's measurement window.
* **Rationale & Recommendation**: Define P2's evidence explicitly: per-day approved-episode rates and the catch-up window computed over the pilot's release-interval span since LAUNCH (complete intervals only), with the window used stated in `PILOT-REPORT.md`'s throughput section and the operator signing the adaptation (master §16.3 already lets the operator confirm/adjust from P1/P2). Either require the compressed calendar to include one 2-day catch-up window or state the fallback ("catch-up recorded UNMEASURED; the §16.3 confirmation notes the exclusion").

### S7-4. §10 introduces five event identifiers outside the §2.1 crossings register - Severity: Major
* **Reviewer Lens:** `egm-structural`
* **Affected Scope:** §10 command table, Events column (lines 445-449); interacts with the §2.1 standing rule (lines 164-165)
* **Discrepancy Description**: §10 introduces `pilot.authorized`, `pilot.claim_recorded`, `pilot.thresholds_confirmed`, `ops.domain_activated`, `ops.restore_proven` — with no registration in the §2.1 crossings register, no stated storage sink, and no statement of their relation to A's enforced event contracts. A §8.4 registers bot events with payload schemas (`track.wait_started`, `slo.below`, `buffer.low`, … — none of these five); A1 note §6 defines the command-table Events column as the A1 event vocabulary; C's command table emits only registered names or "—" and registers every command-relied delta in its crossings section (C §2.2 CD3/CD4). The document's own GD2 row (§16) argues master §3.3's event list is "binding vocabulary — extend the payload, not the name".
* **Rationale & Recommendation**: Under §2.1's own standing rule ("any further G identifier crossing an A–F enforced contract joins this register before the G1 note is accepted"), these five names are exactly the case the rule was written for, yet they appear nowhere before §10, and a G1/G6/G7 builder cannot tell whether they need A-side schema registration or are internal audit appends. Either add a GD row (or rows) covering the `pilot.*`/`ops.*` event families, or state explicitly in §10 that they are command-audit appends outside A's registries and name the table/store they land in.

### S7-5. §5.1 step 2 misdescribes the cited drill lines — and hides that objects restore is new G work - Severity: Major
* **Reviewer Lens:** `egm-design`, `egm-structural`, `egm-style`
* **Affected Scope:** §5.1 step 2 (lines 266-271); related cites at §5.1 step 3 (line 271)
* **Discrepancy Description**: §5.1 says "(drill.sh:121-141: `pg_restore` with `ON_ERROR_STOP`, objects extracted, app up, health + owner login + page-read)". Verified against drill.sh:121-141: the drill restores via `psql -v ON_ERROR_STOP=1` (drill.sh:127), not `pg_restore`, and contains **no objects-extraction step at all** — the objects tar is written at backup (drill.sh:118) and never restored; g-factmap §1 describes the drill correctly, only the G spec deviates. Since §5.1 declares "the drill's steps stay", the wording hides that restoring the objects archive is new G work, and a builder extending the drill would look for a pg_restore/objects-restore step that does not exist. Second citation error: the catch-up claim ("at most the latest missed period per trigger") cites `S/scheduling/service.py:18-21`, whose lines state the firing-dedupe property ("missing state can never duplicate an effect because the semantic keys dedupe"); the at-most-latest-missed-period bound is A §9.1.4 spec behavior (A6b) not present in today's code.
* **Rationale & Recommendation**: Fix step 2's wording to match the drill and mark the delta: "(drill.sh:121-141: `psql -v ON_ERROR_STOP` the dump, app up, health + owner login + page-read — DB-only; G's extension extracts the objects archive into the fresh project)". Re-attribute the catch-up bound to A §9.1.4 (the code citation supports §5.2's no-duplicate-effects assertion, not the bound). Prevents a G3 builder from assuming existing drill/objects-restore and catch-up implementations.

### S7-6. Restore-facts citations point to FM §5 (the lock section) instead of FM §1 - Severity: Major
* **Reviewer Lens:** `egm-structural`, `egm-style`
* **Affected Scope:** §0 Problem (lines 32-33) and §1 decision 8 (lines 107-108)
* **Discrepancy Description**: Both citations read "(FM §5)" for composed-restore facts ("no composed restore proves DB + objects resume without duplicate effects"; "the T046 drill drains *before* backup"). In g-factmap.md, §5 is "Cross-system Nano Banana lock — live half (AT-28)"; the restore gap is FM §1's "Restore gap vs AT-32" block (also FM §7 gap 5), and the drains-before-backup fact (drill.sh:110-113) is in FM §1. The preamble makes FM §n a binding verification path, so these mis-point it; a G3 builder would be directed to the lock section. Note: the FM §5 citation at line 412-414 (ARISA-side adoption absent) is correct.
* **Rationale & Recommendation**: Change both to FM §1 (optionally "(FM §1; FM §7 gap 5)" at line 33).

### S7-7. Threshold sign-off cross-referenced to §7.6, which does not contain it - Severity: Major
* **Reviewer Lens:** `egm-structural`, `egm-style`
* **Affected Scope:** §7.3 (line 377) and §9 (line 437)
* **Discrepancy Description**: Both references point to §7.6 ("Per-destination LIVE claims") for threshold sign-off — "(operator-signed thresholds, §7.6)" and "is signed with the thresholds (§7.6)". §7.6 contains nothing about threshold sign-off; the flow is §7.5's close ("threshold confirmations land in `PilotRunV3`"; operator signs by a commit recording the report's sha256) plus the §10 command `confirm_live_thresholds` (line 447); the numeric thresholds themselves live in §7.4.
* **Rationale & Recommendation**: Broken internal reference on a load-bearing LIVE-acceptance obligation — an operator following it lands in the wrong section. Retarget both to §7.5 (optionally "§7.5 + the §10 `confirm_live_thresholds` command").

### S7-8. Bare "§n" master references are inconsistent and collide with the document's own sections - Severity: Major
* **Reviewer Lens:** `egm-structural`, `egm-style`
* **Affected Scope:** line 47 (§0 item 5) and section headings at lines 169 (§3: "§10.6"), 258 (§5: "§12.5 → §10.6"), 342 (§7: "§11; §16.3"), 398 (§7.6: "§16.2"), 431 (§9: "§16.3 / MA11"), 437 ("§16.3's final row"); mixed form at line 384 ("master §9.4, §16.3")
* **Discrepancy Description**: These are master (SPEC-v3) section references written bare, but the document has its own §9, §10, §11 (Build packages), §12 (Acceptance) and §16 (Alternatives, no subsections), so "§11", "§16.2/§16.3", "§10.6", "§12.5", "§9.4" cannot be resolved internally and collide with real local section numbers. The document qualifies the very same references as "master §n" in ~20 other places (e.g. lines 74, 113, 402), and sibling specs qualify consistently (phase-F/phase-E use "SPEC §n" for every master ref). Worst collisions: "§11" vs this doc's Build packages §11; "§16.3" vs this doc's Alternatives §16.
* **Rationale & Recommendation**: Cross-reference-integrity defect a fresh reader can misresolve. Prefix every master-section reference with "master" (or adopt the F-style "SPEC §n") document-wide, including the section headings.

### S7-9. AT-28 live procedure: two evidence-strength gaps - Severity: Nit
* **Reviewer Lens:** `egm-design`
* **Affected Scope:** §8 stages 1-2 (lines 417-427)
* **Discrepancy Description**: (a) The swap→typed-BLOCKED case is "proven only on the copy" — but the property at stake is topology-specific (PC5-2: a stale pinned inode served through a non-replacement-visible bind); unless the isolated copy reproduces the parent-directory bind shape, the copy proves the fstat comparison but not the aliasing failure mode C-T6 tests on the real mount. (b) Stage 2 asserts "the fairness bounds (≤8 images / ≤120 s per hold)" from one live pair; a single Drama image job exercises one hold, so the assertion is configuration conformance, not fairness behavior under contention.
* **Rationale & Recommendation**: In G7's design note: require the isolated copy to mirror the parent-directory bind topology; reword stage 2's fairness item as "configured fairness bounds active and no hold exceeded the batch limit" so the evidence claim matches what one pair can show.

### S7-10. §10 command table deviates from the format it claims, and PilotRunV3's write paths are unnamed - Severity: Nit
* **Reviewer Lens:** `egm-design`, `egm-style`
* **Affected Scope:** §10 (lines 443-449)
* **Discrepancy Description**: The table is tagged "(A1 note §6 format)" but A1 §6 (and C §11/F §12) carry a "Scope / revision owner" column, which G's table drops; master §2.2's allowed-states/transaction columns are silently folded into Prerequisites. Also, `PilotRunV3`'s phase transitions (RUNNING → SCREEN_REVIEW → PASS/FAIL/ABORTED, per §2's record shape) have no tabulated actor — who appends the measured landing refs and phase verdicts (the runner, System) is implied but unnamed.
* **Rationale & Recommendation**: Drop or correct the format tag (note the column fold); add the scope column and one System-actor row or a sentence under the table naming the pilot runner as the writer of `PilotRunV3` phase/version appends, so the record's write paths are as auditable as the operator commands.

### S7-11. Preamble binding versions are stale or un-sourced - Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** preamble (lines 6-8)
* **Discrepancy Description**: The spec binds "A1-design-note.md v1.3", but the file is v1.4 (14 Nov, round-3 applied, same day). "Accepted B v0.6 / C v0.4.1 / E v0.4" while B's own header still reads "awaiting Opus re-check" and E's reads "v0.4 DRAFT" — the acceptances may be real but are not sourced.
* **Rationale & Recommendation**: Update versions (A1 → v1.4) or cite the acceptance rulings; a stale binding on the precedence chain risks the spec not reflecting the latest applied rulings.

### S7-12. §3.5 quote attributed to master §3.1 is master §10.6's wording - Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** §3.5 (lines 222-225)
* **Discrepancy Description**: "a proven restore before domain activation" is attributed to master §3.1; that wording is master §10.6 (SPEC-v3.md:735). §3.1 says "a proven backup restore (§10.6)".
* **Rationale & Recommendation**: Cite "master §3.1/§10.6" or quote §3.1's actual wording.

### S7-13. Decision 12's hedge contradicts the unconditional rules elsewhere - Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** decision 12 (lines 118-120)
* **Discrepancy Description**: "run under `systemd-run -p CPUQuota=45%` where they load the host" — the hedge contradicts §6's unconditional "under the CPU quota" (line 337), §11's blanket rule (line 473), and E's source rule (phase-E-spec.md:793, unconditional).
* **Rationale & Recommendation**: Delete "where they load the host" (or make all three sites consistently conditional — but E's rule, which G inherits, is unconditional).

### S7-14. Mixed "authorisation/authorised" vs "authorization" spelling in G's own prose - Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** lines 149, 225-226 (in range)
* **Discrepancy Description**: British spelling appears at lines 149 and 225-226 against "authorization" in 19 in-range places. The pattern looks quasi-deliberate (British only around the master-§3.1-derived activation item), but lines 149 (ProductionCompositionV3 content) and 225 (§3.5 body) are G's own prose, not verbatim master quotes.
* **Rationale & Recommendation**: Unify G's own prose to "authorization" outside verbatim master quotes.

### S7-15. PilotRunV3 Content cell packs ~12 attributes into one table cell - Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** §2 documents table (line 146)
* **Discrepancy Description**: The `PilotRunV3` row's Content cell lists ~12 attributes in one semicolon run — not self-contained for a builder; the F spec unpacks its densest store into a subsection (F §2.1).
* **Rationale & Recommendation**: Add a bulleted field list below the table or split into per-record subsections, mirroring F's pattern.

### S7-16. Alert content spec assumes pace numbers that QUOTA_UNREADABLE does not have - Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** §4, the alert bullet (lines 247-249)
* **Discrepancy Description**: The alert fires "with the cause, the pace numbers, and `retry_at`" — pace numbers exist only for `PACE_WEEK`; a `QUOTA_UNREADABLE` pause has none.
* **Rationale & Recommendation**: Scope it: "the pace numbers where the cause is `PACE_WEEK`".

### S7-17. §6 item 3 says "per qualified destination" inside the offline suite - Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** §6 item 3 (line 322)
* **Discrepancy Description**: T032 qualification is live-only; in the offline all-gate suite the intended meaning is seeded per-destination capability records, not actual T032 qualification.
* **Rationale & Recommendation**: Reword to "per destination with a seeded capability record" (or equivalent).

### S7-18. Below-threshold → state mapping is implicit between decision 5 and §7.3 - Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** decision 5 (lines 87-90) vs §7.3 (lines 374-377)
* **Discrepancy Description**: Decision 5 says "A FAIL at screen is terminal for the pilot run"; §7.3 says below-threshold sends the run to `SCREEN_REVIEW` → operator decision, "not an automatic switch". The mapping (below-threshold enters `SCREEN_REVIEW`; `FAIL` is the operator's terminal decision within it) must be inferred.
* **Rationale & Recommendation**: State the mapping explicitly in one of the two places (one sentence in §7.3 suffices).

### S7-19. Preamble migration-allocation bounds cite an incomplete source - Severity: Nit
* **Reviewer Lens:** `egm-structural`, `egm-style`
* **Affected Scope:** preamble (lines 17-18)
* **Discrepancy Description**: "the A-line allocates 0027–0035, B from 0036 — FM §7 gap 13": FM §7 gap 13 carries only "main ends at 0025; WT A0-D claims 0027; A1 claims 0028–0031" (A1 note §1 allocates 0028-0031 only). The full bounds are true but sourced from phase-B-spec.md §2.4 (:213), not the cited FM row. The numbers are right; the citation is incomplete.
* **Rationale & Recommendation**: Cite the actual source of the 0027-0035/0036 bounds (B §2.4 / the A-line notes), or mark the bounds provisional pending the G1-note re-audit the preamble already promises.

### S7-20. Backup-timer deliverable lives only in §3.3; G3's home sections never point to it - Severity: Nit
* **Reviewer Lens:** `egm-structural`
* **Affected Scope:** §3.3 (lines 206-210) vs §5 and the §11 G3 row (line 466, context)
* **Discrepancy Description**: The backup-script/systemd-timer deliverable (a G3 obligation, O-G2) is specified only in §3.3, inside the composition-completion section; §5 (G3's home section) and the §11 G3 row ("the backup timer files") never point back to §3.3/O-G2.
* **Rationale & Recommendation**: Add one pointer — "(§3.3)" in the G3 package row, or a sentence in §5.1 step 1 referencing §3.3's timer-ready backup — so a G3 builder reading §5 alone finds the deliverable.

### S7-21. AT-28 evidence path broken mid-code-span by a hard line break - Severity: Nit
* **Reviewer Lens:** `egm-structural`
* **Affected Scope:** §8 stage 2 (lines 426-427)
* **Discrepancy Description**: The evidence path is one backtick span split across a hard line break ("`microdrama/evidence/`⏎`at28-live-<date>.md`"), unlike the identical path written unsplit at line 152; renders with a spurious break/space.
* **Rationale & Recommendation**: Rejoin the code span onto one line (hard-wrap elsewhere), matching line 152.

---

## Notes

* **Out-of-range observation (context only, not a numbered finding; lines 455-556):** the §12 G-T4 row (lines 485-488) wraps a single table row across four physical lines with hard newlines mid-cell, which splits the row and breaks the §12 table under GFM rendering.
* **Clean results worth keeping:** heading hierarchy clean (single H1; §0-§16 complete and sequential; H3 nesting without skips); decision numbering 1-14 complete and every numbered citation resolves; GD1/GD2, O-G1..O-G8, G1-G7, G-T1..G-T8 complete, non-colliding and consistent across §2/§10/§11/§12/§14; §13 traces every ID in the preamble's "G owns" line; duplication between §1 and §3-§9 is pointer-cited ("decision n"), not drift-prone; template sections the EGM standard expects are all present in the back-matter (§0 Problem/Goals/Non-Goals, §14 Open questions, §15 Risks and limits, §16 Alternatives one-per-choice).
