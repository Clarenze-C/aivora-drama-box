# Consolidated Review Report — phase-G-spec.md

**Target:** `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md` (v0.1 DRAFT, 14 Nov 2026, 556 lines)
**Mode:** headless uninterrupted (Preset 1) — Stages 5→6→7→8→9 run sequentially, fresh reviewer instances per stage
**Semantic split:** FeatureRange = lines 1-454 (§0-§10) · DetailedRange = lines 455-556 (§11-§16; boundary header `## 11. Build packages` at line 455)
**Run:** 14 Nov 2026 · Stage reports in this directory (stale 2026-11-14-morning partials from the 429-killed run were overwritten)

## Stage Status

| Stage | Report | Reviewers | Status | Raw findings |
| --- | --- | --- | --- | --- |
| 5 — Initial Zoom Out | `zoom_out_report.md` | egm-zoom-out | completed | 0 B / 2 M / 6 N |
| 6 — Comprehension Test | `comprehension_report.md` | egm-comprehension | completed | 0 B / 2 M / 10 N |
| 7 — Critic Review | `critic_report.md` | egm-design, egm-structural, egm-style | all completed | 0 B / 8 M / 13 N |
| 8 — Intermediate Zoom Out | `intermediate_zoom_out_report.md` | egm-zoom-out (2 instances, aggregated) | completed | 0 B / 3 M / 7 N |
| 9 — Implementation Readiness | `implementation_readiness_report.md` | egm-implementation-readiness, egm-codebase-details, egm-style | all completed | 0 B / 7 M / 16 N |

**Consolidated totals: 0 Blocker / 19 Major / 42 Nit** (61 consolidated action items from 74 raw findings; mapping in the Traceability Matrix below).

**[format] findings: none.** Every template section the EGM standard expects is present and well formed (§0 Problem/Goals/Non-Goals, §14 Open questions, §15 Risks and limits, §16 Alternatives — confirmed by the Stage 7 structural pass and re-checked at Stage 8). No finding merely asks for a missing template section; S8-Z-3 explicitly asks for *content* within the existing risk sections, not the sections themselves, and is therefore not tagged.

## Overall verdict

Both zoom-out passes independently judge the design **right-scoped, not over-complex, holding together** — the obligation set (AT-14/17/32/34, AT-28 live half, LIVE §16.3, R-11.1/R-12.10/R-12.11/R-12.13) is master-assigned and fully traced (§13); the simplicity discipline is verified against the tree (one migration, no new job types/lanes/state machines, no second quota table, zero new throughput counters, AT-34 bounded, pilot reuses the composition factory / drill pattern / T031 discipline); no reinvention was found beyond M2's alert-hosting choice and M4's backup-fork risk. Stage 9 calls the detailed range "near-ready and unusually accurate against the tree" (Makefile targets, migration tail, port 8094, drill anchors, and every checked R/AT/FM/N/O- citation resolved). **No Blockers: every Major below is addressable with architectural sentences, table edits, or G-note content — none requires re-scoping or redesign.**

Four systemic threads run through the Majors; fixing the thread fixes several findings at once:

1. **Evidence durability is unscoped** (M3, feeding M4 and N-items on retention/export): decision 9 states the invariant — durable records must survive ephemeral databases — but applies it to one artifact only. Qualification records and real-world side effects (LIVE claims, restore proofs, calibration results, pilot provenance) originate in homes designed to be destroyed (`docker compose down -v`).
2. **The AT-14 alert mechanism is the design's only new runtime behavior and is incomplete at the spec level** (M1, M2, M11, M14, N19): the placement (a new 60 s always-on poller) was made silently, and the episode semantics (durable edge, recovery signal, false-edge hazard, track scope, alert content, Home surface) are left to the builder.
3. **Proof cadence/kind is conflated** (M4): §5.1's unclean-world procedure is defined on a test profile while O-G2 demands proofs on production timer backups — with a real duplicate-Telegram-delivery risk if the sender resumes outside a fake transport.
4. **Reference-integrity discipline lapses exactly where a builder reads** (M7-M10, M16-M18, many nits): FM §5/§1 mis-points, bare "§n" master refs colliding with the doc's own §11/§16, a broken §7.6 threshold-sign-off pointer, drill misdescription, and overloaded acceptance cells.

---

## Prioritized Consolidated Findings

Severity rule: a deduplicated item keeps the highest severity any stage assigned (severity disagreement is recorded). Sources list the raw finding IDs (traceability).

### Majors (19)

**M1. AT-14 "one alert per pause episode" mechanism under-specified — durable episode state, recovery signal, false edges, track scope.**
Scope: §4, GD1/GD2 (lines 158-165, 232-254), G-T2 (:483). The pause predicate is "derived, never stored" (AR-4), but rising-edge detection needs durable memory of the previous evaluation across ticks and restarts — `scheduler_firings` dedupes one tick's effects, not an episode boundary. No recovery signal exists to close an episode (A §8.4 has no wait-ended event; GD2 rules out new names). A0 §5.1's `retry_at` clamp (60 s–6 h) makes "any active PACE_WEEK deferral exists" read false mid-pause (spurious falling/rising pair — exactly the spam G-T2 forbids). GD2 fixes `track='production'` while the pause defers LLM jobs in three tracks. Also: the predicate reads the stored latest quota observation while enforcement is the dispatch gate's live health check (two sources that can disagree), and the un-pause reader is unstated. Fix in §4 + the G2 note: define "active deferral" as non-terminal `defer_reason=PACE_WEEK` regardless of `retry_at`; pin the durable edge source (e.g., each firing durably records its evaluation; episode = maximal run of true evaluations, reconstructed on restart); state the un-pause reader (A0 §5.7 gate re-evaluated on deferred retries); justify or generalize the track scope.
Sources: S5-Z-1, S7-1.

**M2. GD1's permanent 60 s always-on poller is an unrecorded architecture choice — and the source of the durable-edge problem.**
Scope: GD1 (:159-163), §4, decision 1, §10 schedules (:451), §11 G2 (:465). The 60 s cadence is 3-5× faster than anything in the schedule catalog (verified: fastest existing interval is 5 minutes, `registry.py:129/:135`), introduces a new cadence class, requires the GD1 crossing, and then creates M1's durable-episode problem. The edge it polls for is already known at the moment the A0 §5.7 dispatch gate engages the route pause — that refusal *is* the rising edge — and an episode-keyed idempotent GD2 event emitted there (carried by the outbox's at-least-once/dedupe semantics) would delete the schedule, the crossing, the restart reconstruction, and M1's retry-gap hazard in one choice. A genuine architectural trade (many workers vs one scheduler singleton; alert latency bounded by A0's ~+10 min retry either way) — but the spec makes it silently and §16 has no rejected-alternative row. Either adopt the event-driven shape or keep the poller with a recorded justification; resolve M1's track-scope question here either way.
Sources: S8-Z-2.

**M3. No authoritative home for G's durable records — the "survive the ephemeral profile" invariant is stated once (decision 9) and never generalized.**
Scope: §2 (:130-155), decisions 3/9, §7.1, §7.2 item 1, §10 `record_live_claim` (:446). The four document types have three plausible database homes and only `ProductionCompositionV3`'s is unambiguous: `PilotRunV3` and its measured landing refs live in a pilot DB following a drill pattern that ends `down -v` (drill.sh:141, verified); `RestoreProofV3` is written from a fresh scratch project (also `down -v`); the spec never says which store `record_live_claim` writes to, never states pilot-evidence export into `microdrama/evidence/pilot/` (named with no writer or cadence), and P0's calibration results "feed C's forecast config" (a pilot-DB measurement feeding a production config with no bridge). A LIVE claim whose evidence refs dangle after teardown is a qualification artifact without durable evidence; no offline gate tests retention. Fix: one rule in §2 (records produced in ephemeral profiles reference committed sha256-bound file artifacts; the authoritative `v3_ops_documents` for LIVE claims and activation is the production store), a named export-at-phase-close step, and retention-then-teardown in the runbook (teardown only after the §11/LIVE sign-off).
Sources: S7-2, S8-Z-1.

**M4. Restore-proof cadence/kind matrix underdetermined — test-profile proofs vs production timer backups, plus a backup code-path fork.**
Scope: §3.3 (:204-210), §3.5 (:219-229), §5.1 (:260-267), O-G2 (:519), §11 G3 (:466). §3.3 says every backup writes `RestoreProofV3` point fields and "the §5 proof completes the record"; §3.5 requires a PASS within 7 days; but §5.1's procedure is defined on a *seeded unclean test-profile world*, while O-G2 demands "proof per §5 on each timer window's set" — on production backups where unclean state cannot be injected. As written, either production rows can never complete (activation always fails) or the nightly proof silently runs a procedure defined only for the test profile — operationally dangerous: a nightly proof that resumes the sender in a fresh project must use the fake transport, or per §5.4's own at-least-once admission it can deliver real duplicate Telegram messages. Structural edge: the drill's backup is inline shell (drill.sh:115-119) while §3.3 ships a standalone timer script — two implementations means O-G2's proof validates whatever the timer runs while the drill exercises the drill's path (proof/production divergence in the one artifact AT-32 rests on). Fix: an explicit matrix (nightly timer = clean restore+resume control proof, fake-transport composition; unclean-world proof in the test profile or on live sets with the natural-unclean-state argument made; activation accepts the freshest PASS of either kind within the window); one backup entrypoint shared by drill and timer.
Sources: S5-Z-2, S8-Z-4.

**M5. P2's LIVE throughput acceptance is not operationalizable as specified.**
Scope: §7.4 (:379-386), §9 (:431-437). "Sustained ≥1.25 approved episodes/day" read from F-6 — but F-6/F §9 defines the sustained rate as a rolling 7-day aggregate over complete intervals, and P2 is ~4 approved episodes on a compressed calendar (~2-3 days). Read literally, the window is padded with pre-release zero days (arithmetically unreachable) or shortened (not the §9.4 "sustained" definition being accepted). The catch-up criterion (≥2/day × 2 days) is qualified "where the schedule allows" while the calendar dates are operator-chosen in the same sentence — circular — and §9's signed row covers catch-up unconditionally. The pilot's measurement window is never defined. Fix: define P2's evidence (per-day rates and catch-up over the release-interval span since LAUNCH, complete intervals only), state the window in the report's throughput section, and either require one 2-day catch-up window in the compressed calendar or record catch-up UNMEASURED with the operator signing the adaptation.
Sources: S7-3.

**M6. §10 introduces five event identifiers outside the §2.1 crossings register — violating the document's own standing rule.**
Scope: §10 Events column (:445-449) vs the §2.1 standing rule (:164-165). `pilot.authorized`, `pilot.claim_recorded`, `pilot.thresholds_confirmed`, `ops.domain_activated`, `ops.restore_proven` appear nowhere before §10, with no registration, no storage sink, and no statement of their relation to A's enforced event contracts (A §8.4 registers bot events; C's command table emits only registered names; G's own §16 GD2 row argues "extend the payload, not the name"). A G1/G6/G7 builder cannot tell whether these need A-side registration or are internal audit appends. Fix: add GD rows covering the `pilot.*`/`ops.*` families, or declare them command-audit appends outside A's registries and name the sink.
Sources: S7-4.

**M7. §5.1 step 2 misdescribes the cited drill lines — and hides that objects restore is new G work; the catch-up bound is miscited to code.**
Scope: §5.1 step 2-3 (:266-271). Verified: the drill restores via `psql -v ON_ERROR_STOP=1` (drill.sh:127), not `pg_restore`, and contains **no objects-extraction step at all** (the objects tar is written at :118 and never restored). Since §5.1 declares "the drill's steps stay", the wording hides that restoring the objects archive is new G work — a builder would look for a step that does not exist. Second error: "at most the latest missed period per trigger" cites `S/scheduling/service.py:18-21`, whose lines state the firing-dedupe property; the bound is A §9.1.4 (A6b) spec behavior not present in today's code. Fix step 2's wording to match the drill and mark the delta; re-attribute the catch-up bound (the code cite supports §5.2's no-duplicate-effects assertion).
Sources: S7-5, S5-Z-4.

**M8. Two restore-facts citations point to FM §5 (the lock section) instead of FM §1.**
Scope: §0 (:32-33) and decision 8 (:107-108). Both facts ("no composed restore proves DB + objects resume…"; "the T046 drill drains before backup") live in g-factmap §1 ("Restore gap vs AT-32"; also FM §7 gap 5). The preamble makes FM §n a binding verification path; a G3 builder following either cite lands in the lock section. (FM §5 at :412-414 is correct.) Stage 5 rated this Nit, Stage 7 Major; kept Major because the pointer is load-bearing for the G3 build.
Sources: S7-6, S5-Z-3.

**M9. Threshold sign-off cross-referenced twice to §7.6, which does not contain it.**
Scope: §7.3 (:377) and §9 (:437). §7.6 is per-destination LIVE claims; the sign-off flow is §7.5's close plus the §10 `confirm_live_thresholds` command (threshold numbers in §7.4). Broken internal reference on a load-bearing LIVE-acceptance obligation — an operator following it lands in the wrong section. Retarget both to §7.5 (+ the §10 command).
Sources: S7-7.

**M10. Bare "§n" master references collide with the document's own sections — and the "master" alias is never declared.**
Scope: FeatureRange headings/lines (:47, :169, :258, :342, :398, :431, :437, :384) and DetailedRange (:490, :524, :551 bare "§11"; :493, :510, :535 "§16.x"). Master (SPEC-v3) section refs written bare cannot be resolved internally and collide with real local sections — worst: "§11" (master's pilot-report contents vs this doc's Build packages) and "§16.3" (master's LIVE thresholds vs this doc's Alternatives §16). Lines 1-454 qualify ~20 other refs as "master §n"; the detailed range drops the qualifier exactly where the local §11 exists. Compounding for a naive reader: the "master" alias itself is never declared (comprehension finding — inferred by matching section numbers). Fix: qualify every master ref document-wide (headings included) and declare the alias once in the preamble.
Sources: S7-8, S9-4, S6-C-3.

**M11. Binding decision 6's "both raise one bot alert per pause episode" is ambiguous about the alert causes.**
Scope: decision 6 (:95-97). The sentence lists three refusal kinds (PACE_WEEK, QUOTA_5H/CONCURRENCY, QUOTA_UNREADABLE), then "both" — which can be read as QUOTA_5H/CONCURRENCY also raising a scope alert (contradicted by §4, GD2, G-T2), while PACE_WEEK (which *is* an alert cause) is the subject of neither clause. The binding-decisions summary cannot be paraphrased correctly from §1 alone. Fix: name the two alert causes (`QUOTA_UNREADABLE`, `PACE_WEEK`) explicitly.
Sources: S6-C-1.

**M12. The P1 below-threshold path's "pre-agreed contingency (split coverage at speech-safe boundaries)" is explained nowhere and carries no anchor.**
Scope: §7.3 (:374-376). This is the decision option the operator faces at `SCREEN_REVIEW`, with projected clip/cost impact — load-bearing for the pilot's terminal branch — yet what split coverage does is defined nowhere in the document and the pre-agreement (presumably T031 lineage) is not linked. A naive reader's paraphrase is a guess. Fix: one-line description plus an explicit pointer to where it is pre-agreed.
Sources: S6-C-2.

**M13. §11's prerequisite sentence is self-contradictory ("A0–F accepted" vs "D's spec pending") and hides which packages are D-independent.**
Scope: §11 preamble (:457-460). "A0–F accepted" literally includes D; the parenthetical states D is not accepted (header :10-12 confirms no D spec exists). No package-level differentiation: G1-G3 (store, pause/alert, restore) are D-free and could build ahead; G4 (fake render adapter), G5 (render qualification), G6 (P1 runbooks) are D-pinned. A builder gating G1 cannot tell whether D blocks every package. Fix: "A0, A, B, C, E, F accepted; D's spec pending — its render/QA contracts are pinned prerequisites; D acceptance gates the render-live legs, not G1-G3."
Sources: S9-1, S8-Z-7.

**M14. G2's "Home surface" deliverable is unspecified and unasserted.**
Scope: §11 G2 (:465); G-T2 (:483). The scope-level pause is jobless (GD2), but the only existing Home wait surface derives from per-job rows (A1's `track_waits` is built exclusively from `jobs` where status='RETRY_WAIT', A1-design-note.md:498-537). "Home surface" for a route-level pause therefore requires a new read path and UI element whose content, derivation (event-sourced vs derived read), and dismissal semantics (A1's `alert_dismissals` supports scope alerts) are nowhere pinned — and G-T2 contains no Home assertion, so whatever ships is unverifiable as written. Fix: pin the surface in G2 and add a G-T2 assertion, or delete the item if per-job surfacing is judged sufficient.
Sources: S9-2.

**M15. §11 never marks which artifacts Create vs Modify existing files.**
Scope: §11 table (:462-470). G3 modifies the existing guarded `deployment/staging/drill.sh` (verified present, 149 lines; steps 5-7 are what's extended); G4 modifies the existing `microdrama/Makefile` (verified; no allgates target); G2/G5 edit existing registries/composition code (A §9.1/§9.2 territory); G1/G6/G7 artifacts are new. A fresh builder cannot tell from §11 alone that drill.sh and the Makefile are edits to live operator tooling. Fix: a Create/Modify column or per-row marks.
Sources: S9-3.

**M16. G-T2 and G-T4 "Proves" cells are overloaded multi-assertion prose (≈8 and ≈11 assertions), and the G-T4 row breaks the §12 table.**
Scope: G-T2 (:483); G-T4 (:485-488). Semicolon-chained cells with nested parentheses and mid-cell bold; G-T4 additionally wraps one row across four physical lines with hard newlines mid-cell, splitting the row and breaking the table under GFM. These cells are the load-bearing acceptance contract for the two biggest gates and cannot be ticked off assertion-by-assertion (the F-spec review already flagged this exact cell style). Fix: one summary sentence per row + enumerated one-observable-per-bullet sub-list; rejoin the row.
Sources: S9-5, S7 out-of-range note (§12 G-T4 row).

**M17. G-T2's test-setup seam is ambiguous against §3.1's own fail-closed rule.**
Scope: G-T2 (:483) vs §3.1 (:177-195). "Through the production composition with A0's fake-gateway scenarios" — but §3.1 says the production composition refuses `OFFLINE_MOCK` and LLM live-enablement requires gateway health + a current live qualification. How an offline test stages "the production composition" against a fake gateway (seeded qualification rows? A0's test handler at the real socket?) is unstated, and a builder could read it as licensing a second test composition, which §3.1 forbids. Fix: one clause naming the actual seam.
Sources: S9-6.

**M18. G-T5's "refuses startup or dispatch" is not one observable, and "each enabled provider missing switch" is self-contradictory phrasing.**
Scope: G-T5 (:489) vs §3.1 (:177-181). For each missing piece (switch/qualification/rights/price), is the required refusal at startup, at dispatch, or both? §3.1 describes checks at both surfaces with per-provider disablement — not necessarily whole-composition startup refusal. And a provider missing its switch is by definition not enabled; the intent is "each provider enabled in configuration but missing…". Fix: state the startup-vs-dispatch matrix and rephrase.
Sources: S9-7.

**M19. §14/§15/§16 omit the biggest risks the design itself creates — the register faces outward while the doc's own seams go unregistered.**
Scope: §14 (:514-527), §15 (:529-541), §16 (:545-556). Explicitly *not* a template-section request (all sections exist and are well formed) — the gap is content. Every §15 row is outward-facing (quota, spend, T032, ARISA, CPU, drift). Absent: (a) the alert-episode mechanism's durable state (M1); (b) pilot/restore evidence retention across teardown (M3) — for a phase whose deliverable IS durable evidence; (c) P2's window definability (M5); (d) upstream-line volatility (A0-D FIX-REQUIRED/unmerged, phase-D spec nonexistent, T031-fix3 unmerged) as a gating risk. §16 has no row for the alert placement (M2) or the record home (M3). Fix: one §15 row each for (a)-(d) + a prerequisite-volatility row; two §16 rows; optionally one §14 question for record home/retention (or resolve per M3 and cite).
Sources: S8-Z-3.

### Nits (42)

| # | Finding | Sources |
| --- | --- | --- |
| N1 | Code-line drift in two inherited cites: at-least-once/dedupe is `S/core/events.py:8-10` (not :5-7); scheduler sentence at `S/scheduling/service.py:21-22` (not :18-21) | S5-Z-5 |
| N2 | Preamble conventions under-explained: the unnamed "runbook's draft queue" (three runbooks in play), undefined "A-line", unexplained 0026 gap, and migration-tail attribution incomplete (full bounds sourced from phase-B-spec.md:213, not FM §7 gap 13) | S6-C-4, S5-Z-6, S7-19 |
| N3 | Pilot critical path is ARISA-blocked end to end (cast + every P1/P2 episode), not just at calibration; say planning steps 1-3 + voices may run ahead with O-C7 defaults as interim forecast | S5-Z-7, S8-Z-5 |
| N4 | Header binding versions stale/asymmetric: A1-design-note is v1.4 not v1.3; B/C/E pending re-checks flagged only for F; acceptances unsourced | S5-Z-8, S7-11 |
| N5 | "YuE2" appears only in quota enumerations with no definition or link (inferable as the music provider only from §3.1's "SFX / music" pairing) | S6-C-5 |
| N6 | `dramabox-llm` never gets a one-line identity (service? role? branch?) — assembled from three scattered facts | S6-C-6 |
| N7 | "Home" (operator dashboard) never defined; used at :252, :304, :465 (cross-ref M14) | S6-C-7 |
| N8 | "V1 `make pilot`" and "populated V1+V2+V3 database" are inherited conventions stated nowhere | S6-C-8 |
| N9 | §10 operator commands' invocation surface (admin UI? console? endpoint?) unstated; "human session + CSRF" assumes the A1 convention | S6-C-9 |
| N10 | B's planning step numbering assumed ("steps 1-3", "reduced step 4" — the four-step split recoverable only from a parenthetical) | S6-C-10 |
| N11 | Residual bare external IDs without gloss or link: O-11, AR-4, T031's S05/S06 (most other IDs are properly glossed) | S6-C-11 |
| N12 | `A0-LIVE-REPORT.md` cited as current but nonexistent and unpathed (prospective A0 §7 artifact — say so); drill.sh cited by bare filename throughout §3.3/§5.1 | S6-C-12 |
| N13 | AT-28 evidence-strength gaps: the isolated copy must mirror the parent-directory bind topology for the swap→BLOCKED proof to mean anything; stage 2's "fairness bounds" from one live pair is configuration conformance, not behavior under contention — reword | S7-9 |
| N14 | §10 table deviates from the A1 §6 format it claims (drops the Scope/revision-owner column); `PilotRunV3` phase/version appends have no tabulated writer (name the runner) | S7-10 |
| N15 | §3.5's "a proven restore before domain activation" is master §10.6's wording attributed to master §3.1 | S7-12 |
| N16 | Decision 12's "where they load the host" hedge contradicts §6/§11's unconditional CPU-quota rules and E's source rule (unconditional) | S7-13 |
| N17 | Mixed "authorisation/authorised" vs "authorization" in G's own prose (:149, :225-226) | S7-14 |
| N18 | `PilotRunV3` Content cell packs ~12 attributes into one semicolon run — unpack like F §2.1 | S7-15 |
| N19 | Alert spec assumes "pace numbers" that a `QUOTA_UNREADABLE` pause does not have — scope to PACE_WEEK (cross-ref M1) | S7-16 |
| N20 | §6 item 3 "per qualified destination" inside the offline suite — T032 qualification is live-only; mean "seeded capability record" | S7-17 |
| N21 | Below-threshold → state mapping implicit between decision 5 ("FAIL is terminal") and §7.3 (`SCREEN_REVIEW` → operator decision); state that FAIL is the operator's terminal decision within SCREEN_REVIEW (cross-ref M12) | S7-18 |
| N22 | Backup-timer deliverable specified only in §3.3; §5 and the G3 row never point back — a G3 builder reading §5 alone misses it (cross-ref M4) | S7-20 |
| N23 | AT-28 evidence path broken mid-code-span by a hard line break (:426-427); rejoin like :152 | S7-21 |
| N24 | Test-then-rotate keeps the chat-exposed bot token in live use for the whole multi-day pilot; rotate before P1 (costs nothing) or record why the old token must be used | S8-Z-6 |
| N25 | Fifth sealed document store: G's §16 rationale never acknowledges the family-level consolidation question it makes five-deep (merged tree today: one store, many types — M/0019); record it as a master-level decision and reuse the existing sealing implementation in the G1 note | S8-Z-8 |
| N26 | G-T3 on "every package gate" is the heaviest test on the heaviest schedule, and G-T8's cadence (`make check` + `make pilot` + allgates at G4/pre-live) never includes G-T3 — scope it to G3's gate + pre-live rerun, or state where the test lives and accept the cost | S8-Z-9, S9-9 |
| N27 | Pilot output's product status unstated: published posts and 4-5 episodes are evidence, not launch product; decide and name their disposition at sign-off (cross-ref M3) | S8-Z-10 |
| N28 | G-T4 asserts "the runtime bound held" while §6 calls ≤15 min "a target, not a promise" and §15 calls it a gate — state the assertion form (hard fail with tolerance vs report-and-tune) | S9-8 |
| N29 | §16's "five tables" underivable: master §11 names no tables and decision 2 enumerates six metering tables — name the five or drop the count | S9-10 |
| N30 | G-T6 "records both roles' usage" contradicts the 4-role × 2-model harness (O-G5, §7.5) — "each role's usage under both models" | S9-11 |
| N31 | Ungated §11 items and unpinned operator-installed paths: G5's CPU-quota units and G3's timer files have no G-T5/G-T3 assertion; G7's runbooks have no location; `confirm_live_thresholds` has no explicit gate row | S9-12 |
| N32 | G-T7's offline dry choreography never says what plays the ARISA side — state it drives C-T6's simulated-competitor harness | S9-13 |
| N33 | §13's R-12.13 row omits "+ LIVE" (the requirement completes only through operator execution; AT-17 and §16.3/MA11 rows carry it correctly) | S9-14 |
| N34 | O-G6 "at gates and pre-live" drifts from G-T8's "at G4 and before any live qualification" — align | S9-15 |
| N35 | §13's last row breaks the column contract ("§16.3 / MA11" as a key under "R-ID / AT"; Where column mixes sections and test ids) | S9-16 |
| N36 | Bolding keys unstated and inconsistent between §11 (packages + "Critiqued first") and §12 (G-T2/T3/T4 + LIVE but not G-T6/T7) | S9-17 |
| N37 | G-T3 clause chain parses two ways ("retried once and flagged then dead-lettered or delivered") — write "retried at most once, flagged `possible_duplicate`, then delivered or dead-lettered" | S9-18 |
| N38 | §15's "24×2 calls × roles" — the ×2 multiplier appears nowhere in lines 1-454; state what it counts or drop it | S9-19 |
| N39 | O-G5's role list ("director") drifts from the step names ("directing") and never says why these four roles carry frozen workloads | S9-20 |
| N40 | §16 introduces a third casing for the quota table (`QuotaObservation` vs `quota_observations`) | S9-21 |
| N41 | LIVE row: "these rows" has no plural antecedent (one row); Package column mixes sentinels ("all" vs "execution") | S9-22 |
| N42 | G-T1's "guards + catalog present" leaves "catalog" undefined (inherited opaque from F-T1) | S9-23 |

---

## Traceability Matrix (raw finding → consolidated item)

| Raw | Consolidated | Raw | Consolidated | Raw | Consolidated |
| --- | --- | --- | --- | --- | --- |
| S5-Z-1 | M1 | S7-6 | M8 | S9-4 | M10 |
| S5-Z-2 | M4 | S7-7 | M9 | S9-5 | M16 |
| S5-Z-3 | M8 | S7-8 | M10 | S9-6 | M17 |
| S5-Z-4 | M7 | S7-9 | N13 | S9-7 | M18 |
| S5-Z-5 | N1 | S7-10 | N14 | S9-8 | N28 |
| S5-Z-6 | N2 | S7-11 | N4 | S9-9 | N26 |
| S5-Z-7 | N3 | S7-12 | N15 | S9-10 | N29 |
| S5-Z-8 | N4 | S7-13 | N16 | S9-11 | N30 |
| S6-C-1 | M11 | S7-14 | N17 | S9-12 | N31 |
| S6-C-2 | M12 | S7-15 | N18 | S9-13 | N32 |
| S6-C-3 | M10 | S7-16 | N19 | S9-14 | N33 |
| S6-C-4 | N2 | S7-17 | N20 | S9-15 | N34 |
| S6-C-5 | N5 | S7-18 | N21 | S9-16 | N35 |
| S6-C-6 | N6 | S7-19 | N2 | S9-17 | N36 |
| S6-C-7 | N7 | S7-20 | N22 | S9-18 | N37 |
| S6-C-8 | N8 | S7-21 | N23 | S9-19 | N38 |
| S6-C-9 | N9 | S8-Z-1 | M3 | S9-20 | N39 |
| S6-C-10 | N10 | S8-Z-2 | M2 | S9-21 | N40 |
| S6-C-11 | N11 | S8-Z-3 | M19 | S9-22 | N41 |
| S6-C-12 | N12 | S8-Z-4 | M4 | S9-23 | N42 |
| S7-1 | M1 | S8-Z-5 | N3 | S7 note (§12 G-T4 GFM break) | M16 |
| S7-2 | M3 | S8-Z-6 | N24 | | |
| S7-3 | M5 | S8-Z-7 | M13 | | |
| S7-4 | M6 | S8-Z-8 | N25 | | |
| S7-5 | M7 | S8-Z-9 | N26 | | |
| — | — | S8-Z-10 | N27 | | |
| S9-1 | M13 | | | | |

Raw coverage: 74 numbered findings + 1 Stage-7 out-of-range note → 61 consolidated items (19 Major, 42 Nit). No raw finding was dropped.

## Suggested triage order for the spec owner

1. **M3 + M4** (evidence durability + proof matrix) — the strongest whole-holds-together seams; both touch §2/§3.3/§5 and the G3 note, and M19's risk rows depend on them.
2. **M1 + M2 + M11 + M14 + N19** (the AT-14 alert family) — one design decision (poller vs event-driven at pause engagement) resolves M2 and most of M1; M11/M14/N19 are one-clause completions of the same mechanism.
3. **M7 + M8 + M9 + M10** (reference integrity) — mechanical, builder-facing, cheap; do them together in one editing pass (they share the "master §n" qualification fix).
4. **M13 + M15 + M16 + M17 + M18** (§11/§12 actionability) — the DetailedRange package; M16's enumerated assertions naturally absorb M17/M18 and the N-items on those cells.
5. **M5 + M6 + M12 + M19** — remaining design completions (P2 window, event registration, contingency anchor, risk register).
6. Nits in any order; N3/N24/N27 carry schedule/security/product decisions and deserve a look before the mechanical prose nits.
