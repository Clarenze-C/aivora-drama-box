# Stage 9 — Implementation Readiness Report

**Target:** `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md` (DetailedRange, lines 455-556)
**Reviewers:** `egm-implementation-readiness`, `egm-codebase-details`, `egm-style` (fresh instances) · Standards: `implementation-readiness-standard.md` (readiness, codebase-details)
**Status:** completed — 0 Blocker / 7 Major / 16 Nit
**Run:** headless uninterrupted (Preset 1), 14 Nov 2026

## Reviewer Status

| Reviewer | Status |
| --- | --- |
| `egm-implementation-readiness` | completed |
| `egm-codebase-details` | completed |
| `egm-style` | completed |

All three reviewers report the detailed range as near-ready: every Makefile target, migration-tail claim, port, R-ID/AT id, note id (N12/N36, FM §1/§5, A0 §3.1/§5.8, O-C4, V3C-1), and cross-spec citation checked resolved correctly against the tree (`make check`/`make pilot` exist, `make v3-allgates` genuinely absent, M/ tail at `0025_t045_billing_finality.sql`, port 8094 unused, drill.sh anchors exact, `ai-route build -w` real). Findings below are actionability, precision, and trace-complete gaps — no blockers.

## Prioritized Findings (Blockers → Major → Nits)

### S9-1. §11 prerequisites sentence is self-contradictory ("A0–F accepted" vs "D's spec pending") - Severity: Major
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** lines 457-458 (§11 preamble)
* **Discrepancy Description**: "Prerequisites: **A0–F accepted** (D's spec pending at this draft…)" — "A0–F accepted" literally includes D; the parenthetical then states D is not accepted (the document header, lines 10-12, confirms no phase-D spec exists). A builder gating G1 cannot tell whether D's acceptance blocks every G package or only the render-live legs (§7.3 pins P1; G4's all-gate suite runs a fake render adapter per §6). The master's phase table (SPEC-v3.md:871, "A0-F (P0 needs A0-C)") does not resolve the local contradiction.
* **Rationale & Recommendation**: A build-blocking ambiguity in the entry condition of the whole section. Reword, e.g.: "A0, A, B, C, E, F accepted; D's spec pending at this draft — its render/QA contracts are pinned prerequisites (§7.3); D acceptance gates the render-live legs, not G1-G3."

### S9-2. G2's "Home surface" deliverable is unspecified and untested - Severity: Major
* **Reviewer Lens:** `egm-implementation-readiness`
* **Affected Scope:** line 465 (§11, G2 row); line 483 (§12, G-T2)
* **Discrepancy Description**: The scope-level pause is jobless (GD2, line 162), but the only existing Home wait surface derives from per-job rows: A1's `track_waits` view is built exclusively from `jobs` where status='RETRY_WAIT' (A1-design-note.md:498-537), and A's bot handler routes events to Telegram, not Home. "Home surface" for a route-level pause therefore requires a new read path and UI element whose content (fields shown — cause/pace numbers/retry_at), derivation (event-sourced vs derived read of the pause predicate), and dismissal semantics (A1's `alert_dismissals` already supports scope alerts, A1-design-note.md:493) are nowhere pinned. Compounding it, G-T2 (line 483) contains no Home assertion — deferrals, alert dedupe, no-fallback, recovery, and non-LLM tracks are asserted, but whatever "Home surface" ships is unverifiable as written.
* **Rationale & Recommendation**: A package deliverable with no pinned design and no acceptance assertion violates the zero-decision rule. Pin the surface in G2 (e.g., a season-scope paused entry derived from the GD2 event/pause predicate with cause, pace numbers, retry_at; state the read path and dismissal via scope alerts) and add a G-T2 assertion — or delete the item if existing per-job surfacing is judged sufficient.

### S9-3. §11 build-packages table never marks which artifacts Create vs Modify existing files - Severity: Major
* **Reviewer Lens:** `egm-codebase-details`
* **Affected Scope:** lines 462-470 (§11 table), esp. line 466 (G3) and line 467 (G4)
* **Discrepancy Description**: Two rows modify existing, guarded files without saying so: G3's "the drill extension (unclean seed, resume steps)" modifies the existing `microdrama/deployment/staging/drill.sh` (verified present, 149 lines; its steps 5-7 are the drain/backup/restore being extended), and G4's `make v3-allgates` modifies the existing `microdrama/Makefile` (verified present with `check`/`pilot`; no allgates target). G2's schedule + Home surface and G5's composition checks likewise edit existing registries/composition code (phase-A §9.1/§9.2 territory), while G1/G6/G7 artifacts are new. Per the standard's Target Scope requirement the plan must state which files are created vs modified; a fresh builder cannot tell from §11 alone that drill.sh and the Makefile are edits to live operator tooling rather than new files.
* **Rationale & Recommendation**: Add a Create/Modify column or per-row marks: Modify — drill.sh (G3), Makefile (G4), composition/serve startup + schedule registry + Home views (G2/G5); Create — v3_ops_documents migration + OpsV3Store, backup timer units, deployment/pilot/, pilot CLI, report generator, evidence writers, AT-28 procedure docs.

### S9-4. Unqualified "§11" / "§16.x" references inside the detailed range collide with this document's own sections - Severity: Major
* **Reviewer Lens:** `egm-style`, `egm-implementation-readiness`
* **Affected Scope:** lines 490, 524, 551 (bare "§11"); lines 493, 510, 535 ("§16.2"/"§16.3")
* **Discrepancy Description**: G-T6's "produces every §11 section" (line 490), O-G7's "where the §11 decision is read" (line 524), and §16's "§11 demands measured numbers" (line 551) all refer to SPEC-v3.md §11 (verified at SPEC-v3.md:740-773, the cost/quota meter and pilot-report contents), not to the local §11 "Build packages" (lines 455-473). Bare "§n" elsewhere in §12 resolves inside this document (G-T3 "the §5 procedure", G-T4 "the §6 suite"), so the local reading is the default one a builder will apply. Same drift with "§16.3 thresholds confirmed" (line 493), "§16.3 / MA11" (line 510), and "§16.2 per-destination claims" (line 535) — resolvable only because the local §16 has no subsections. Lines 1-454 consistently qualify the master ("master §11" at lines 75, 353, 388); the detailed range drops the qualifier exactly where the local §11 exists.
* **Rationale & Recommendation**: An acceptance criterion should not require cross-document inference to decode. Restore "master §11" / "master §16.2" / "master §16.3" in the detailed range (G-T6 could cite "master §11 report contents, §7.5 here").

### S9-5. G-T2 and G-T4 "Proves" cells are overloaded multi-assertion prose - Severity: Major
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** line 483 (G-T2); lines 485-488 (G-T4)
* **Discrepancy Description**: G-T2 packs at least eight independently checkable assertions into one semicolon-chained cell (PACE_WEEK defer with retry_at; QUOTA_UNREADABLE route pause holding dispatch; alert exactly-once per pause episode across ticks/restarts; QUOTA_5H stays per-job; exactly one live LLM route; API-adapter enablement refused; recovery; non-LLM continuation), with nested parentheses and mid-cell bold. G-T4 packs at least eleven (per-gate approval through the real decision transaction; stale-hash refusal at each gate; chain consistency; dual-authority dispatch; amendment fencing with stale quarantine; reschedule rebuild scope; published-media immutability; five episodes PUBLISHED_VERIFIED; season COMPLETE; close_out_episode exercise; evidence artifact; runtime bound), wrapped mid-clause across four physical lines. A reviewer cannot tick these off individually; the prior F-spec review already flagged this exact cell style as uncheckable outcome-noun prose (phase-f-review/implementation_readiness_report.md:86).
* **Rationale & Recommendation**: These cells are the load-bearing acceptance contract for the two biggest gates. Keep one summary sentence per row and enumerate the assertions as a bulleted sub-list (one observable per bullet).

### S9-6. G-T2's test-setup seam is ambiguous against §3.1's own fail-closed rule - Severity: Major
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** line 483 (G-T2); interacts with §3.1 (lines 177-195)
* **Discrepancy Description**: "Through the production composition with A0's fake-gateway scenarios" — §3.1 (lines 193-195, 182-183) says the production composition refuses OFFLINE_MOCK and that LLM live-enablement requires gateway health plus a current A0 §7 live qualification (A0-LIVE-REPORT.md). How an offline acceptance test stages "the production composition" against a fake gateway (seeded qualification rows? A0's test V3 handler at the real socket, per A0-1's "real test V3 handler"?) is unstated, and a builder could read it as licensing a second test composition — which §3.1 explicitly forbids ("no second composition entry point"). The exact seam is UNVERIFIED from this document alone.
* **Rationale & Recommendation**: One clause naming the seam removes the guess, e.g. "qualification rows seeded; A0 §6's test handler serves the gateway socket" (adjust to the actual A0 mechanism).

### S9-7. G-T5's "refuses startup or dispatch" is not a single observable, and "each enabled provider missing switch" is self-contradictory phrasing - Severity: Major
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** line 489 (G-T5); interacts with §3.1 (lines 177-181)
* **Discrepancy Description**: "each enabled provider missing switch/qualification/rights/price refuses startup or dispatch (typed)" — for each missing piece, is the required refusal at startup, at dispatch, or both? §3.1 (lines 177-181) says the checks run "at startup and dispatch" and that a missing piece "keeps the provider disabled", which is per-provider disablement, not necessarily whole-composition startup refusal. Also, a provider missing its switch is by definition not enabled; the intended meaning is "each provider enabled in the configuration but missing…".
* **Rationale & Recommendation**: State the matrix — which missing piece refuses composition startup versus refuses job dispatch — matching §3.1's two surfaces, and fix the "enabled… missing switch" phrasing.

### S9-8. G-T4's "the runtime bound held" conflicts with §6's "a target, not a promise" - Severity: Nit
* **Reviewer Lens:** `egm-implementation-readiness`, `egm-style`
* **Affected Scope:** lines 485-488 (G-T4); cross-refs §6 lines 337-338, §15 line 538
* **Discrepancy Description**: §6 says the ≤15 min bound is "a target, not a promise" (lines 337-338); §15 says "the suite's runtime bound is a gate" (line 538); G-T4 asserts "the runtime bound held". The T031-R5 §4 convention cited is explicitly non-assertive (T031-run-readiness-spec.md:289-298: "an upper bound conditional on…, not a promise"). A builder must decide whether a >15-min run under CPUQuota fails G-T4 or is recorded/reported.
* **Rationale & Recommendation**: State the assertion form: hard fail at a threshold with tolerance, or report-and-tune per §6's fixture-tuning clause (e.g. "the ≤15 min bound held under the CPU quota (fixtures tuned per §6)").

### S9-9. §15 claims "G-T3 runs at every package gate" but no section establishes that cadence - Severity: Nit
* **Reviewer Lens:** `egm-implementation-readiness`, `egm-style`
* **Affected Scope:** line 537 (§15); cross-refs line 492 (G-T8), line 484 (G-T3)
* **Discrepancy Description**: The per-gate check defined in §11's preamble and G-T8 (line 492) is `make check` + V1 `make pilot`, plus `make v3-allgates` at G4 and pre-live — neither includes G-T3. The claim holds only if G-T3's drill test joins the standard pytest tree that `make check` runs — a placement decision never stated, and one in visible tension with O-G6's CPU-driven exclusion of the all-gates suite from `make check`. Whether it does is UNVERIFIED from this document.
* **Rationale & Recommendation**: State where the G-T3 test lives and that it runs per gate (e.g., "G-T3's drill test joins test-integration, hence every `make check`"), or drop the cadence claim — otherwise §15's mitigation premise is false.

### S9-10. "five tables" in §16 is an unexplained, underivable count - Severity: Nit
* **Reviewer Lens:** `egm-codebase-details`, `egm-style` (also noted by `egm-implementation-readiness`)
* **Affected Scope:** line 551 (§16, PILOT-REPORT row)
* **Discrepancy Description**: "§11 demands measured numbers from five tables" — master §11 (SPEC-v3.md:740-773) lists report contents but names no tables, and the target's own decision 2 (lines 67-70) enumerates six metering tables (charges, cost_allocations, llm_invocations, quota_observations, pod_usage_intervals, release_throughput_observations), with Botnoi points as operator attestation besides. §7.4-§7.5 imply yet another set. Which five is not derivable from any of the enumerations.
* **Rationale & Recommendation**: Name the five tables or drop the count ("from the metering tables").

### S9-11. G-T6's "records both roles' usage" contradicts the 4-role × 2-model harness - Severity: Nit
* **Reviewer Lens:** `egm-implementation-readiness`
* **Affected Scope:** line 490 (G-T6); cross-ref O-G5 line 522, §7.5 line 395
* **Discrepancy Description**: The frozen-workload harness is 4 roles × 2 models (O-G5: bible, architect, director, metadata; §7.5: "k frozen workloads per role run under both Opus and Sonnet"). "Both roles" matches neither — there are four roles and "both" refers to the models. A literal reading yields a two-role harness.
* **Rationale & Recommendation**: "records each role's usage under both models (Opus and Sonnet)".

### S9-12. Several §11 build items have no matching gate assertion, and operator-installed file paths are unpinned - Severity: Nit
* **Reviewer Lens:** `egm-implementation-readiness`
* **Affected Scope:** lines 466, 468, 470 (§11 G3/G5/G7 rows); cross-refs lines 484, 489 (G-T3/G-T5)
* **Discrepancy Description**: G5's "CPU-quota deployment units" (line 468) — G-T5 (line 489) asserts completion checks, expiry, activation checklist, staging guards, nothing about the unit files. G3's "the backup timer files" (line 466) — G-T3 (line 484) asserts the restore/resume proof only. G7's "P0–P2 runbooks" (line 470) — G-T7 verifies their dry-run modes but no location is pinned (G5's units have the A0 §4.1 precedent, `deployment/llm-gateway/install/`; G3's timer and G7's runbooks have none). Also §10's `confirm_live_thresholds` flow has no explicit gate row (G-T6's report test only implicitly touches the sign-off block).
* **Rationale & Recommendation**: Add presence/content assertions for operator-installed files and pin their paths.

### S9-13. G-T7's offline dry choreography does not say what plays the ARISA side - Severity: Nit
* **Reviewer Lens:** `egm-implementation-readiness`
* **Affected Scope:** line 491 (G-T7); cross-ref §8 lines 419-421
* **Discrepancy Description**: Live stage 1 uses "both real containers"; the offline gate runs "an isolated copy" with "real-inode holds coordinated in the runbook". In an offline pytest run the competing holder must be simulated — C's accepted convention is exactly that ("C's offline acceptance simulates the competitor", C-T5/C-T6, phase-C-spec.md:414), but the G7 builder must infer the reuse.
* **Rationale & Recommendation**: State that G-T7's isolated-copy choreography drives C-T6's simulated-competitor harness.

### S9-14. §13's R-12.13 row omits the LIVE completion link - Severity: Nit
* **Reviewer Lens:** `egm-implementation-readiness`
* **Affected Scope:** line 504 (§13)
* **Discrepancy Description**: R-12.13 ("cost/quota meter + pilot before pace", REQUIREMENTS.md:24-27) completes only through the operator-gated execution; V3-AT-17 (line 506) and §16.3/MA11 (line 510) correctly carry "+ LIVE" while R-12.13 maps to "§7 (superseded-for-pilot per V3C-1, §1.13); G-T6" only.
* **Rationale & Recommendation**: Add "+ LIVE" to the row so the trace reflects where the requirement actually completes.

### S9-15. O-G6's "at gates and pre-live" drifts from G-T8's "at G4 and before any live qualification" - Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** line 523 (O-G6); cross-ref line 492 (G-T8), §6 line 311
* **Discrepancy Description**: "At gates" (plural) reads as every package gate; G-T8 pins the target to G4 onward (necessarily — the target lands in G4), and §6 says "not in every `make check` run".
* **Rationale & Recommendation**: Align O-G6 to G-T8's wording ("at G4 and before any live qualification").

### S9-16. §13's last row breaks the table's column contract - Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** lines 499, 510 (§13 header and last row)
* **Discrepancy Description**: The header is "R-ID / AT"; every row key is an R-id or V3-AT id except "§16.3 / MA11", a master section plus MA id. The "Where" column also mixes section refs and test ids in one cell ("§3.5, §10; G-T5"); F's trace table separates Section from Package(s) (phase-F-spec.md:1045-1049).
* **Rationale & Recommendation**: Rename the key column ("R-ID / AT / master ref") or split the Where column.

### S9-17. Bolding keys are unstated and differ between §11 and §12 - Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** lines 464-470 (§11); lines 483-486, 492-493 (§12)
* **Discrepancy Description**: §11 bolds package ids and "**Critiqued first**" but not "With the diff" (bold = the critiqued-first subset — verified consistent with the routing paragraph's G1/G3/G6/G7, lines 472-473). §12 bolds G-T2/T3/T4 and "LIVE" but not G-T6 (AT-17's generator) or G-T7 (AT-28's dry half), so the implied key (bold = directly proves a master AT offline) is never stated and does not cover the LIVE row's bolding. Mirrors the partial bolding in F's §14 (phase-F-spec.md:1022-1024) — a sibling-consistent habit, but the rule is written nowhere.
* **Rationale & Recommendation**: Add a one-line key under each table or bold uniformly.

### S9-18. G-T3's clause chain parses two ways - Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** line 484 (G-T3)
* **Discrepancy Description**: "the ambiguous notification retried once and flagged then dead-lettered or delivered" — the missing comma yields "flagged-then-dead-lettered" or "delivered" as competing readings. Intended per §5.1 step 3 and §5.2: retried at most once, flagged `possible_duplicate`, then either delivered or dead-lettered.
* **Rationale & Recommendation**: Write it that way ("retried at most once, flagged `possible_duplicate`, then delivered or dead-lettered").

### S9-19. §15's "24×2 calls × roles" is unexplained arithmetic - Severity: Nit
* **Reviewer Lens:** `egm-style` (also UNVERIFIED per `egm-implementation-readiness`)
* **Affected Scope:** line 533 (§15 first risk row)
* **Discrepancy Description**: §7.2 defines 24 episodes through steps 1-3; no ×2 multiplier appears anywhere in lines 1-454. The risk's magnitude depends on it.
* **Rationale & Recommendation**: State what ×2 counts (two calls per episode per role?) or drop it.

### S9-20. O-G5's role list drifts from the pilot's step names and hides the selection rationale - Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** line 522 (O-G5)
* **Discrepancy Description**: "(bible, architect, director, metadata)" — the document elsewhere says "directing" (§7.3 line 370; §4 line 242), and §7.2 adds season critic and translation as LLM roles. Why these four roles carry frozen workloads and the others do not is unstated.
* **Rationale & Recommendation**: Use the §7.2-§7.3 step names and add one clause on the selection.

### S9-21. §16 introduces a third casing for the quota table - Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** line 550 (§16 quota row)
* **Discrepancy Description**: "A second (non-LLM) `QuotaObservation` table" — the existing table is `quota_observations` (line 70); `QuotaObservation` in code format reads like a distinct class.
* **Rationale & Recommendation**: "a second `quota_observations`-shaped table for non-LLM providers". (The Choice column is otherwise well formed: every row names the chosen option in column 1 and the rejected one in column 2 — verified parallel across all eight rows.)

### S9-22. LIVE row's "these rows" has no plural antecedent; Package column mixes sentinels - Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** line 493 (LIVE row); cross-ref line 492 (G-T8)
* **Discrepancy Description**: Only one LIVE row exists, so "these rows pass outside the build" should be "this row". The Package column holds "all" (G-T8) and "execution" (LIVE) — two different non-package values.
* **Rationale & Recommendation**: Fix the antecedent; consider one sentinel convention for non-package rows.

### S9-23. G-T1's "guards + catalog present" leaves "catalog" undefined - Severity: Nit
* **Reviewer Lens:** `egm-style`
* **Affected Scope:** line 482 (G-T1)
* **Discrepancy Description**: §2 defines the guards and the allowlist CHECK but no catalog. The phrase is inherited verbatim from F-T1 (phase-F-spec.md:1015), where the F review already flagged it as an outcome noun without stimulus (phase-f-review/implementation_readiness_report.md:86). Consistent with the sibling, opaque standalone.
* **Rationale & Recommendation**: Name the object ("migration catalog present" or equivalent).

## Verification Summary (all three reviewers)

Verified correct, among much else: G-T1..G-T7 map one-to-one to G1..G7 and §11's Gate column matches §12's Test ids; routing paragraph matches the four "Critiqued first" rows and the accepted sibling convention; `make check` (Makefile:56) and `make pilot` (Makefile:62, the V1 demo, `microdrama.pipeline.demo`) exist and `make v3-allgates` is genuinely absent; migration tail at `0025_t045_billing_finality.sql`; `OpsV3Store` follows the real B/C/E/F store lineage and the guard/hash/allowlist idiom exists in M/0019; drill.sh drain/backup/restore anchors (drill.sh:110-141) exact; port 8094 unused (8091-8093 occupied); O-G2 = DOMAIN-RUNBOOK.md:33-35 unexecuted restic step; O-G3 = phase-C-spec.md:813 (O-C4); O-G4 = FM §5; O-G5's bound = phase-A0-spec.md:70; all §13 R-IDs/AT ids resolve with matching meanings (REQUIREMENTS.md:24-27, 169, 189-190; SPEC-v3.md:884, 905-969); N12/N36, V3C-1, MA11, master §18 all real; §16's eight rows all consistent with decisions 1-14.

UNVERIFIED (flagged, not counted as findings): `feat/t031-fix3` current merge status (prerequisite framing, consistent with FM); whether a QUOTA_5H fake-gateway scenario already exists in A0/B (if absent, G2 must add one — small, in scope); T032 records for publication-live legs (external); runtime availability of port 8094; the exact fake-gateway seam G-T2 assumes (see S9-6); whether G-T3 joins `make check` (see S9-9); the ×2 multiplier (see S9-19); which five tables §16 means (see S9-10).
