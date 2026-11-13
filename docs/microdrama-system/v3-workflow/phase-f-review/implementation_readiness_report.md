# Implementation Readiness Report (Stage 9)

**Target:** `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-F-spec.md` (DetailedRange lines 497-567; FeatureRange lines 1-496 read as context)

**Mode:** uninterrupted (Preset 1), headless. Reviewers: `egm-implementation-readiness`, `egm-codebase-details` (standard: `implementation-readiness-standard.md`), `egm-style` (no standard). Deduplicated by the orchestrator; merged findings credit all lenses.

## Reviewer Status

| Reviewer | Status |
| --- | --- |
| `egm-implementation-readiness` | completed (2 Blocker / 3 Major / 6 Nit) — verdict: **ready-after-fixes** |
| `egm-codebase-details` | completed (0 Blocker / 3 Major / 3 Nit) |
| `egm-style` | completed (0 Blocker / 5 Major / 6 Nit) |

After in-stage deduplication (one merge: prerequisites/E-absence findings from readiness + codebase-details): **2 Blocker / 10 Major / 15 Nit** (finding IDs R-1…R-27).

## Prioritized Findings (Blockers -> Major -> Nits)

### R-1. The plan gates F5 on an undecided operator ruling (O-F1/O-8) — Severity: Blocker

* **Reviewer Lens:** `egm-implementation-readiness`
* **Affected Scope:** §15 O-F1 (542); §0 item 7 (32); §1.9 (83-88); §13 F5 row (509); §16 R-8.2 trace (559)
* **Discrepancy Description:** O-F1 states "Operator decision required before F5", and §0.7 says "the decision itself stays open". The recommendation "(d) now, (a) when T032 qualifies it" is a recommendation, not an adopted decision. F5 (teaser, PROMO_CUT identities) and the R-8.2 delivery route cannot be built first-attempt without the implementer guessing or stopping. SPEC-v3:1013 confirms O-8 is a genuine master-spec open item ("The operator decides in phase F") — not resolvable inside the F build.
* **Rationale & Recommendation:** Direct Zero-Decision Rule violation with an explicit external gate named by the plan. Obtain the operator's O-8 ruling before F work starts and write it into §1.9 as binding text (the recommendation is already fully specified: YouTube real caption tracks post-publish via `upload_captions`, TT/FB TH-only until their route is qualified, flip per destination by config). If the ruling cannot be obtained now, the plan must state that F5 is conditionally blocked and F1-F4 may proceed.

### R-2. Gate-to-package sequencing: several §13 checkpoints are unpassable at their own step — Severity: Blocker

* **Reviewer Lens:** `egm-implementation-readiness`
* **Affected Scope:** §13 gate column (505-514) vs §14 tests (525-531)
* **Discrepancy Description:** Violates "make check + pilot green at every gate" (497) and the Phasing & Checkpoints requirement: (1) F3 (507) lists F-T5 as its ONLY gate, but F-T5 (528) proves Gate 2 V3 behavior built in F4 — F3 has no independently passable gate; (2) F2's gate F-T3 (526) includes "reschedule never rewrites a `platform_posts` row" — reschedule is built in F7; (3) F5's gate F-T6 (529) requires "both approved paths work" — recovery path 2 is reschedule (F7 functionality); (4) F6 gates on F-T8 (531) whose late-teaser/rejected-episode scenarios recover via push/reschedule — F7 functionality, and the plan does not say whether F-T8 at F6 executes those recoveries or only asserts the options are offered; (5) F2's gate F-T2 (525) requires five current Gate 2 approvals, but V3 Gate 2 is F4 — the test must seed approval rows, and unlike F-T12 ("seeded", 535) F-T2 does not say so.
* **Rationale & Recommendation:** A competent engineer reaching these gates must invent a re-mapping — independent decisions. Re-map the gate column: give F3 its own drafts/thumbnails/staleness test (or move F-T5 to F4 and gate F3 on make check plus a named unit gate); move the F-T3 reschedule clause and F-T6/F-T8 reschedule-recovery assertions to F7/F-T9 or split them into staged assertions; state the seeding requirement for F-T2/F-T3 explicitly.

### R-3. F-2's versions-table design choice is left open inside F1's own build list — Severity: Major

* **Reviewer Lens:** `egm-implementation-readiness` (corroborates Stage-7 K-29, K-37)
* **Affected Scope:** §2 record F-2 (135); §13 F1 (505)
* **Discrepancy Description:** "append-only versions via `metadata_draft_versions` (or reuse the `metadata_versions` pattern — decided in the F1 note)". Two named alternatives, no selection criteria in the plan — a Zero-Decision violation inside F1's build list, where the engineer authors the migration and must pick the table design. (Stage-7 evidence: the reuse option is non-viable anyway — `metadata_versions.platform_post_id` is NOT NULL, `M/0005:85`.)
* **Rationale & Recommendation:** Pre-decide in the spec (mirror the B `StoryV3Store` / C `CastV3Store` house pattern) and state the decisive columns.

### R-4. The per-destination caption-route record has no storage home — Severity: Major

* **Reviewer Lens:** `egm-implementation-readiness` (escalates Stage-7 K-28 from Nit)
* **Affected Scope:** §1.9 (88); §7.1 item 5 (327); §13 F2 (506); §14 F-T4 (527); O-F1 "by config" (542)
* **Discrepancy Description:** The route is "recorded per destination and enforced at admission", but §2's records F-1..F-8 contain no table, `v3_release_documents` contract type, config key, or capability-record field for it; §10's inventory neither. O-F1's recommendation says "by config" without naming the config surface.
* **Rationale & Recommendation:** F2's admission check item 5 and F-T4's "caption route unavailable" refusal depend on this record existing with a defined shape. Add it to §2 (e.g., a `caption_route` contract type or a column on the destination capability pin) and name it in F1/F2's Builds.

### R-5. Prerequisites not verifiable; phase-E contract undefined; the existing `S/editing` seam goes unnamed — Severity: Major

* **Reviewer Lens:** `egm-implementation-readiness` + `egm-codebase-details` (merged; corroborates Stage-6 comprehension finding 9)
* **Affected Scope:** §13 prerequisites (499-500); F5 (509); §5 (246-247); §0 (35)
* **Discrepancy Description:** "Prerequisites: A0–A6 accepted; B, C, E accepted" is not verifiable: the v3-workflow directory contains A/A0/B/C specs and artifacts, but no phase-D-spec.md or phase-E-spec.md exists (verified by listing). F5's teaser_cut is "deterministic assembly from the source episodes' approved edit artifacts (E's EDL/export outputs)" and Gate 2 relies on E's caption-track binding — the input contracts are defined nowhere readable. Meanwhile deterministic EDL construction, content-addressed export and FFmpeg assembly already exist in the main tree (`S/editing/edl.py` "T015", plus `export.py`, `ffmpeg.py`) — a concrete reuse target the spec does not name. The plan also cites no acceptance ledger for any prerequisite.
* **Rationale & Recommendation:** F5's assembler cannot be written without E's export/EDL output schema — a forced design choice. Cite the acceptance artifact per prerequisite; either pin E's export/caption-track contract (paths + shapes) in the F spec or state explicitly that F1-F4 may start but F5 is blocked until the E spec lands and is accepted. Name `S/editing` as the reuse target for `release_v3.teaser_cut` (or justify a separate assembler).

### R-6. O-F7's recommendation depends on capability-record fields that do not exist — Severity: Major

* **Reviewer Lens:** `egm-codebase-details` (absorbs Stage-7 K-47's cap-min question)
* **Affected Scope:** §15 O-F7 (548); load-bearing for §3.1 (165)
* **Discrepancy Description:** O-F7 recommends the pinned capability record as source of truth for per-platform hashtag/title limits, claiming it "already carries platform constraints". It does not: `CapabilityLimits` (`S/contracts/release.py:470-476`) has only max/min duration, file bytes, codecs, aspect ratios, daily quota — no title-length or hashtag-count/length field (grep for `max_title`/`hashtag_limit`: zero hits). YouTube's 100-char title limit exists only inside an EvidenceRef note string (`S/publishing/youtube/capabilities.py:77-78`). The only structured caps are the platform-agnostic contract caps (title ≤200, caption/description ≤5000, hashtags ≤30, `release.py:364-367`) — looser than YouTube's documented 100.
* **Rationale & Recommendation:** The implementer must design the `CapabilityLimits` extension themselves — a zero-decision failure. State in O-F7 (or F1's "contracts bump") that `CapabilityLimits` gains title/hashtag limit fields and which package adds them, or name the alternative source; resolve the contract-cap-200 vs YouTube-100 conflict the prefill lint must handle (effective cap = min of the two).

### R-7. §13 Builds column: no Create/Modify markers; objects appear in two packages — Severity: Major

* **Reviewer Lens:** `egm-codebase-details`
* **Affected Scope:** §13 Builds column (505-514; concrete instance 505-506)
* **Discrepancy Description:** The Builds column mixes migrations and logic without Create/Modify markers, and objects appear in two packages: F1 builds "migrations F-1..F-8" (all eight, including F-5 `publication_admissions` and the F-1 document store), yet F2's Builds also lists "`publication_admissions`" and the "Calendar document" (a `v3_release_documents` record type) — whether F2's mention means the table, the append logic, or the document type is left to the reader. Corroborating drift outside the range: §5 line 239 labels `SeasonTeaserPlanV3` "(F-2)" although §2 homes it in the F-1 store.
* **Rationale & Recommendation:** A fresh implementer cannot tell which package creates which object without guessing. Add a Create/Modify/Reuse marker per object, disambiguate F2's "publication_admissions" as admission logic (table created in F1), and fix the "(F-2)" cross-reference at line 239.

### R-8. §16 trace row line 565: positional slash-zip carries five mappings — Severity: Major

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** line 565
* **Discrepancy Description:** "V3-AT-11 / 12 / 29 / 30 / 31 | F-T5 / F-T2, F-T6 / F-T8 / F-T10 / F-T10": "/" does two jobs (left-cell ID separator; right-cell mapping delimiter) while "," groups two tests inside one mapping; the reader must count five segments and align positionally to recover AT-12 → F-T2 + F-T6. The same slash also means pair ("F2/F6" 562) and 5-item enumeration ("F1/F2/F4/F7/F8" 516).
* **Rationale & Recommendation:** Positional compression defeats lookup; trace tables are read in isolation. Split to one row per ID. (Mapping verified consistent with §14 annotations today; only notation is at fault.)

### R-9. §13 Builds cells are telegraphic noun-chains with no section anchors — Severity: Major

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** lines 503-514
* **Discrepancy Description:** Elided verbs and no anchors: "seal = drafts", "Revise targets" (508), "premiere gating, recovery" (509 — one word covers §5's entire two-path repair/reschedule design), "buffer rule" (506), "near-air bot options + retry/swap/push wiring" (510), "staleness" (507). Cells mix artifacts with assertions ("V1/V2 byte-identity", 505). §13 is the only package-scope statement in the document.
* **Rationale & Recommendation:** A builder cannot reconstruct scope from "recovery" without §4/§5. Expand fragments to verb phrases or append section anchors (e.g., "recovery paths (§5: repair + reschedule)"); keep assertions out of the Builds column.

### R-10. §14 Proves cells are not decidable as written — Severity: Major

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** lines 520-536
* **Discrepancy Description:** Assertion granularity uneven; several cells are not checkable pass conditions: F-T2 (525) gives stimulus/response, but most cells give outcome nouns without stimulus or verb: "guards + catalog" (524), "successors hold" (530, no injected failure), "buffer alert fires below 2" (535, unit "days" dropped).
* **Rationale & Recommendation:** Adopt uniform stimulus ⇒ expected grammar with units (e.g., "buffer_days < 2 ⇒ alert emitted"); restore the unit on 535; seed scenarios for F-T7/F-T9.

### R-11. Three namespaces one glyph apart: F1..F10 vs F-1..F-8 vs F-T1..F-T13 — Severity: Major

* **Reviewer Lens:** `egm-style` (extends Stage-7 K-9)
* **Affected Scope:** lines 505, 542, 562, 564, 566-567
* **Discrepancy Description:** Line 505 uses "F1" and "F-1..F-8" in one row; §16 cites sigil-less package refs ("F2/F6", "F8", "F9"); §15 "before F5". No exact collision, but package F2 (calendar/LAUNCH/admission) vs migration F-2 (`metadata_drafts`) are unrelated objects one hyphen apart, and package refs carry no namespace marker while neighbors in the same column do (§, F-T, O-F).
* **Rationale & Recommendation:** The conventions paragraph (9-12) declares the scheme, but tables are read alone. Qualify package refs at first use in-range ("package F2") or rename packages (FP1..FP10).

### R-12. §16 has no V3-AT-2 row although §4's heading claims it — Severity: Major

* **Reviewer Lens:** `egm-style` (extends Stage-7 K-34)
* **Affected Scope:** lines 553-567 vs §4 heading (209)
* **Discrepancy Description:** §4's heading claims "(R-9.1; V3-AT-2)" for phase F, but §16 has no V3-AT-2 row and no F-T test carries a V3-AT-2 annotation; all other body-claimed ATs trace on line 565. The citation dead-ends at the trace table — the reader cannot tell mis-trace from heading over-claim.
* **Rationale & Recommendation:** Add the row and covering test, or correct the §4 heading. (Stage-7 K-34 additionally lists V3-AT-5, V3R-6, AR-4 as untraced.)

### R-13. "§3.2's state set" reference is dangling — Severity: Nit

* **Reviewer Lens:** `egm-implementation-readiness` (also flagged by Stages 6/7)
* **Affected Scope:** §11 (481); F10/F-T13 inherit it
* **Discrepancy Description & Rationale:** F's §3.2 is "Thumbnails" and defines no state set or one-primary-action rule; presumably the A5 shell/SPEC UI rules are meant. F-T13's "every state in §11" inherits an unresolvable pointer. Correct the cross-reference.

### R-14. Mechanical facts deferred to the F1 note — Severity: Nit

* **Reviewer Lens:** `egm-implementation-readiness`
* **Affected Scope:** lines 10-11, 117, 120-121, 457, 500-501
* **Discrepancy Description & Rationale:** Real migration numbers, B's LLM lane name (UNVERIFIED), final step-key vocabulary — each has a stated lookup procedure (the tail audit matches: migrations end at 0025), so borderline-acceptable process deferrals; but pin the lookup source so no interpretation is needed.

### R-15. O-F10's default should be promoted to binding — Severity: Nit

* **Reviewer Lens:** `egm-implementation-readiness` (relates to Stage-7 K-5, which shows the default's unpublished-leg is unimplementable)
* **Affected Scope:** §15 O-F10 (551); §8.2 (400-404); F7 (511)
* **Discrepancy Description & Rationale:** A complete default exists; leaving the whole boundary open for the F7 critique keeps F7 actionable but under-specified. Promote the viable parts into §8.2 as binding; leave only the override knob to the F7 note.

### R-16. "In flight" undefined in the MISSED predicate — Severity: Nit

* **Reviewer Lens:** `egm-implementation-readiness`
* **Affected Scope:** §7.4 (367); F6 (510); F-T7 (530)
* **Discrepancy Description & Rationale:** MISSED requires "no admission in flight" — which post/job states count (SCHEDULED/SUBMITTED/PROCESSING post? enqueued `publish.submit_slot` job? both?) is unstated, though F6 must implement exactly this predicate. Enumerate the states in §7.4.

### R-17. No close-out command exists for COMPLETE — Severity: Nit

* **Reviewer Lens:** `egm-implementation-readiness` (same defect as Stage-6 comprehension Major 4)
* **Affected Scope:** §6.2 (302); §12 command table (485-495)
* **Discrepancy Description & Rationale:** COMPLETE requires episodes "verified or explicitly closed out", but no close-out command/action exists; the operation performing explicit closure is unnamed. Add it (actor, prerequisites, effect).

### R-18. F-3 teaser-key column shape undecided — Severity: Nit

* **Reviewer Lens:** `egm-implementation-readiness` (extends Stage-7 K-25)
* **Affected Scope:** §2 record F-3 (136)
* **Discrepancy Description & Rationale:** "`episode_id` (or `teaser` key)" leaves the column modeling undecided (nullable episode_id + sentinel? separate key column?). State the shape so the F1 migration and F5's teaser-thumbnail queries are deterministic.

### R-19. Date immutability is service-layer convention, not a DB guard — Severity: Nit

* **Reviewer Lens:** `egm-codebase-details` (corroborates Stage-5 Z-4 / Stage-7 K-3)
* **Affected Scope:** §15 O-F2 (543); §1.4 (59-60)
* **Discrepancy Description & Rationale:** Within `M/0005:32-78` the UNIQUEs are real, but the immutability trigger's column list excludes `scheduled_utc`/`local_time` — dates are pinned only by convention (no code path updates them; the only rollback is `cancel_slot`). The F2 critique should rest the argument on the UNIQUEs and identity immutability, not on "dates are trigger-immune".

### R-20. Phase D's status in the prerequisites is unstated — Severity: Nit

* **Reviewer Lens:** `egm-codebase-details`
* **Affected Scope:** line 499
* **Discrepancy Description & Rationale:** D is named as a supplier but excluded from the accepted list, so whether F may build before D is accepted must be inferred. State "D is not a prerequisite for F's offline packages; its renders/QA enter via fixtures, and live/G needs D".

### R-21. `w13b`'s wall-clock daily instant exceeds today's registry shape — Severity: Nit

* **Reviewer Lens:** `egm-codebase-details`
* **Affected Scope:** F9 (513); schedule defined at §9 (443)
* **Discrepancy Description & Rationale:** "daily at 19:05 Asia/Bangkok" cannot be expressed by today's `Schedule` (fixed interval + `last_fired`, `S/scheduling/registry.py:30-60`); it needs A6b's planned calendar triggers (`phase-A-spec.md:448`), and the must-fire-after-the-19:00-release ordering is unstated. Note the dependency in F9, or the implementer must choose between interval approximation and the A6b surface themselves.

### R-22. Bold/emphasis overloaded across §13-§15 — Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** lines 505-512, 525-533, 542, 544-545, 549
* **Discrepancy Description & Rationale:** Bold signals process labels, emphasized content (only 4 of 13 Proves cells), emphasized row IDs (only F-T8/F-T10, O-F1/O-F8), answer keywords, and an unexplained bolded prerequisite "E" (499). Pick one rule and apply uniformly.

### R-23. §15 Question column mixes grammar; O-F1's cell is a 90-word memo — Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** lines 540-551
* **Discrepancy Description & Rationale:** Interrogative (O-F3), topic noun phrases (O-F5, O-F7), declarative statements (O-F1, O-F2, O-F8, O-F10); O-F1's Question cell embeds four lettered options. Standardize to one question (or rename "Issue"); move O-F1's options to their own column or footnote.

### R-24. O-F9's revisit trigger is undecidable; "P0" undefined — Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** line 550
* **Discrepancy Description & Rationale:** "per-slot split only if prefill quality demands it (revisit after P0)" names no signal, and "P0" appears nowhere else. Name the milestone in this document's vocabulary and a concrete quality signal.

### R-25. Unit/abbreviation inconsistency inside tables — Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** lines 525, 533, 535, 544
* **Discrepancy Description & Rationale:** "premiere − 3 d" vs "3 days earlier"; "incl."; unit-less "below 2". Standardize on "days"/"including" in tables.

### R-26. "Transaction test" taxonomy introduced but never marked — Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** §14 heading (520)
* **Discrepancy Description & Rationale:** "real PostgreSQL for every transaction test" — unclear whether F-T12/F-T13 (surfaces/UI) are included. Write "every test" or mark which rows are transaction tests.

### R-27. §16 "Section" column mixes namespaces and one-off citation forms — Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** lines 555-566
* **Discrepancy Description & Rationale:** Column carries § refs, packages (F8), tests (F-T5), open questions (O-F1), phase refs "(B/E)"; "§7.1.5" (559) reads as a nonexistent subsection (document convention is "§X.Y item N"); "Master §12.6" (566) vs "SPEC §12.6" elsewhere. Rename column "Covered by"; use the document's own forms.

## Evidence Base (codebase-details reviewer, verified accurate — no finding)

- Migration tail: `microdrama/migrations/` ends at `0025_t045_billing_finality.sql`; `0026_t031_benchmark_experiments.sql` and `0027_a0_llm_gateway.sql` live at `/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/migrations/`. `/root/.scratch/` does not exist. The line 9-10 convention and F1-note re-audit advice are correct.
- "Today's 14 schedules": `S/scheduling/registry.py:65-156` default_catalog has exactly 14; `w13-release-admission` at 5-min interval fits the current `Schedule` shape; W09 and its `publish.submit_slot` job type exist unchanged (`S/scheduling/service.py:566,621`).
- All reused objects exist at cited anchors: `release_approval_manifests` (M/0021:20), `md_gate2_manifest_binding` (M/0021:50,79), `approved_slot_metadata` (M/0021:7), `performance_snapshots` with H24/H72/D7 (M/0005:204-226, CHECK at :212), `retry_held_slot` (service.py:1060-1068), `cancel_slot` (:1045-1058), `upload_captions` "NOT part of submit" (youtube/adapter.py:250-258), `HeldSlot` (:101-102), dependency wait (:654-668), reconcile adopt/re-arm (:947-980), `SUBSTANTIVE_FIELDS` without cta_text (metadata.py:29-37), `gate2_blockers` (gate_conditions.py:118+), caption-alignment guard (M/0008:24-34), `SlotKind` incl. PROMO_CUT (enums.py:430-434), MD-015 validator (release.py:93-101), hashtags cap 30 (:367), cover triple (v2.py:857-860), `validate_live_release_metadata` (v2.py:940+), `jobs.queue` CHECK for F-8's `release` lane (M/0001:77).
- `make check` (Makefile:56) and `make pilot` (Makefile:62-63) exist; contracts-check (Makefile:33-34) backs F-T1's "no generated-contract drift".
- F-T1..F-T13 all defined; every ID referenced by exactly one §13 gate row — no dangling gates.
- O-F1 adapter facts accurate (TT/FB `subtitles_present` readback-unverified: tiktok/adapter.py:379-389, facebook/adapter.py:354-362; YouTube proves via `captions.list`).
- O-F8 accurate: N43 absent from REQUIREMENTS.md and DECISIONS.md (only cited at SPEC-v3.md:144).
- §16 IDs all exist; AT→test mapping matches §14 tags; F-T12 SLO numbers match SPEC-v3 §9.4:618-620; "T032 gates only live publishing" matches SPEC-v3:870.
- No duplication: zero hits for `release_v3`/`ReleaseV3`/`LaunchBinding`/`metadata_drafts`/`thumbnail_candidates`/`release_slot_identities`/`publication_admissions`/`corrective_posts`/`v3_release_documents`/`propose_calendar` anywhere in src — F9's throughput counters are genuinely new.
- Limitations stated: read-only (did not run make/pilot or apply migrations); "accepted" status of A/B/C/E is orchestration state, not verifiable from code (B/C objects confirmed absent from the main tree, i.e. genuinely future work); `ai-route build -w` is an external convention, not repo-verifiable. Note: sibling file `phase-f-spec-final.md` exists in the same directory — verified by the orchestrator to be a 2.1K completion note about this v0.1 draft, not a later spec revision.

## Stage Verdict

**2 Blocker / 10 Major / 15 Nit.** The §13 plan is close to executable — its factual base is solid (every spot-checked anchor held) — but it is not startable as written: (1) the O-F1 operator ruling must be obtained and written in as binding before F5 (ideally before F2, whose admission check item 5 consumes the route record); (2) the gate column must be re-mapped so every package has a passable checkpoint at its own step; (3) the unspecified record designs (draft-versions table, caption-route storage) must be pinned. E's absence is acceptable only if the plan states F5 is blocked until E's spec exists and is accepted.
