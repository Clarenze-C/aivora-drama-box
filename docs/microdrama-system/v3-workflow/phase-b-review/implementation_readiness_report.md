# Stage 9 — Implementation Readiness Report

**Target:** `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-B-spec.md` — "Phase B: Story (Script Maker → LOCK → bible → episode packs → STORY LOCK)", v0.3, 12 Nov 2026 (562 lines)
**DetailedRange under review:** lines 481–562 (§10 Build packages, §11 Acceptance, §12 resolved open questions, §13 requirement trace)
**Date:** 2026-11-13
**Reviewers:** `egm:egm-implementation-readiness` (completed), `egm:egm-codebase-details` (completed, verified against `b-factmap.md` and the code under `/root/AIVORA/drama-box/microdrama/`), `egm:egm-style` (completed, no document standard)

## Overall readiness verdict

**Not ready as-is; ready after the listed fixes.** All three reviewers independently declined to hand §10–§13 to build routing unchanged, but the gap is precision, not structure: 0 Blockers, 14 Majors, 9 Nits, and every Major is a missing decision rule or an untestable predicate that forces a builder guess — each fixable with a one-line-to-one-paragraph spec or package-note pin, no re-architecture. What already holds up was verified, not assumed: every identifier, gate mapping, migration-numbering claim, decision citation (the 12 Nov "D2 revised again" trail) and §13 requirement-trace row resolves to real spec text or real code (checked against `b-factmap.md` and the tree, e.g. `ProductionLimits` at `src/microdrama/contracts/primitives.py:62`, the `v2_contract_documents` allowlist and `schema_version = '2.0'` CHECK at `migrations/0019_v2_contract_documents.sql:5-14`, `make check`/`make pilot` at `microdrama/Makefile:56,62`); the gate allocation B-T1..B-T12 partitions exactly once across B1–B6; routing is linear and non-circular; prerequisites match the phase-A package table. The convergent Majors (three reviewers on the O-B5 critic switch, two each on step keys, the B-T5 query log, the O-B1 cap and the O-B2 count binding) plus the B1-specific items (M1 step keys, M10 guard seam, M13 job-type registration) should be pinned before B1 routes; the remainder can land with their package notes but must land before their gate runs.

*Deduplication note: 25 raw findings → 23 items. The style reviewer's compound finding "decided behaviours with zero acceptance coverage" was decomposed into its five facets so each merges with the same defect raised independently by the other reviewers (facets d and a merge into M3 and M4).*

## Prioritized findings

### M1. Step-key plumbing promised by §1.3 is owned by no package, and its key names violate A2's closed enum — Severity: 🟡 Major
- **Anchor:** §10 builds table (lines 491–498); cross-ref §1.3 (lines 61–63)
- **Raised by:** style, codebase-details
- **Finding:** §1.3 makes "B builds the `step_key` plumbing" a B deliverable and reserves B's calls under step keys `script_maker`, `bible` and `episodes`, but no B1–B6 Builds cell mentions step keys, and those three names do not exist in A2's closed CHECK.
- **Evidence:** A2-design-note.md:140–143 — `step_key IN ('step_01'..'step_10','launch','episode_production')`; phase-A-spec.md §5.2:210 ("master steps 1–10 + `launch` + `episode_production`"). A2's `md_reservation_step_rules` refuses any V3 reservation whose step is not a budgeted step, so a builder copying §1.3's names builds plumbing A2's own trigger rejects. Codebase-details adds: `episode_production` reserves against EPISODE accounts created only at STORY LOCK (phase-A-spec.md:187–188), so where pre-LOCK planning calls would reserve is undefined even under A2's vocabulary. Phase B is unmetered in the pilot (`llm.subscription`), so nothing breaks at build time — the conflict is stored for the O-5 metered adapter.
- **Action:** correct §1.3's keys to the A2 enum (B's steps 1–3 = `step_01`–`step_03`, or a planned enum extension) and add the step-key plumbing to an explicit package's Builds cell (B1 is the natural home, beside the contract bump) — or strike the promise and move it to the O-5 adapter phase.

### M2. B-T5's "query-log assertion" names a mechanism defined nowhere — Severity: 🟡 Major
- **Anchor:** §11 B-T5 (line 513)
- **Raised by:** style, codebase-details
- **Finding:** B-T5's load-bearing clause "The V3 writer opens no such table (a query-log assertion)" defers to a facility no document defines and no test infrastructure provides. The implementer must choose between materially different mechanisms (a restricted DB role, pg_stat_statements deltas, `log_statement=all` capture, an instrumented connection wrapper, an event trigger) that each prove different things — so the test's strength, and whether it stays offline per §11's preamble, depend on an unstated design choice. Exactly the guess B-T5 exists to prevent.
- **Evidence:** corpus-wide search for query-log/query_log hits only this line; A0/A1/A2/A3 and the master define nothing; b-factmap.md §12 (real-PostgreSQL conftest, `X/unit/story/*`, `X/contract/*`) lists no query-capture mechanism.
- **Action:** B4's note pins the mechanism and proof obligations, e.g. "test jobs run under a DB role with no privilege on the asset/wardrobe-assignment/identity-lock/voice tables; the test asserts the season completes with no access attempted (role error log / pg_stat_statements snapshot diff)", and lists the exact table names asserted empty.

### M3. O-B5's episode-critic switch has no mechanism, scope, default assertion or test — Severity: 🟡 Major
- **Anchor:** §12 O-B5 (line 532); cross-ref §5.1 step 4 (line 313), §10 B4 row (line 496)
- **Raised by:** implementation-readiness, codebase-details, style
- **Finding:** "Episode critic off by default, switchable" names no flag, no scope (global Settings vs per-season), no actor, and no default assertion; B-T5/B-T6/B-T7 never exercise it. The B4 builder designs the switch themselves and nothing prevents the default shipping on.
- **Evidence:** §5.1 says only "Optionally, one LLM episode critic (O-B5)"; nothing in §10–§13 or §1–§9 says where the switch lives. Codebase-details notes a precedent to pin: the `Settings` pattern in `src/microdrama/config.py` (e.g. `Settings.llm_route` with `MICRODRAMA_LLM_ROUTE`, per a0d-build-REPORT.md:224).
- **Action:** one clause in O-B5/B4's note, e.g. "a Settings flag (`MICRODRAMA_V3_EPISODE_CRITIC`, default off, global), read at `plan_episode` dispatch", plus a default-off and a toggled-on test case.

### M4. O-B1's 3-active-locations cap has no counting basis and no test — Severity: 🟡 Major
- **Anchor:** §12 O-B1 (line 528); cross-ref §2.2 (line 153), §4.3, §6.1
- **Raised by:** implementation-readiness, style
- **Finding:** whether the cap counts distinct `location_key` (the evident intent) or distinct LOCATION demands (keyed `location_key + light_state` per §4.3 — under that reading 2 locations × 2 light states = 4 and would block STORY LOCK Approve), and whether `recap_plan` references count, are unstated; no acceptance test injects a 4th location; §6.1's catch-all "V3 limits" never enumerates which limits bind packs.
- **Action:** define the count ("at most 3 distinct `location_key` values in `scenes[]`, recap excluded") and inject the 4-location defect in B-T7.

### M5. O-B3's closed emotion vocabulary is never enforced by any test — Severity: 🟡 Major
- **Anchor:** §11 table (lines 507–520); cross-ref §2.2, §12 O-B3 (line 530)
- **Raised by:** style
- **Finding:** B-T7 checks emotion presence ("every line has … + emotion") and B-T2 tests only 180 s and 10-episode rejection, so a line with `emotion='ENVIOUS'` is never refused anywhere in §11 — a decided, closed vocabulary with no rejecting test.
- **Action:** add a case rejecting an out-of-enum emotion value (B-T7 or the B4 note).

### M6. The `story_v3.promote_profile` job has zero acceptance coverage — Severity: 🟡 Major
- **Anchor:** §11 table; cross-ref §7 job table (line 423), §4.2
- **Raised by:** style
- **Finding:** §7 lists `promote_profile` and §4.2 requires an LLM-completed profile per promoted role, but no B-T row proves one promotion → one `promote_profile` call.
- **Action:** add the case (a tier promotion triggers exactly one `promote_profile` call; the completed profile is stored).

### M7. §5.3's non-episode STORY LOCK Revise targets are untested — Severity: 🟡 Major
- **Anchor:** §11 B-T10 (line 518); cross-ref §5.3
- **Raised by:** style
- **Finding:** §5.3 allows Revise targets other than an episode (a bible section via the scoped `story_v3.bible` call, the seam, a tier); B-T10 exercises only `episode:<k>`.
- **Action:** add one bible-section (or seam/tier) Revise case to B-T10 or the B5 note.

### M8. B-T7's "a seam closed in the finale" has no detection predicate — Severity: 🟡 Major
- **Anchor:** §11 B-T7 (line 515); cross-ref §6.2 (line 408), §2 `ExtensionSeamV3` (line 114)
- **Raised by:** style
- **Finding:** the season critic must catch an injected "seam closed in the finale" and §6.2 makes it CRITICAL, but nothing defines the signal: `ExtensionSeamV3` threads carry only `thread_id`, description, open payoffs and constraints; packs never reference seam threads; no field marks a thread resolved/closed. The builder of the deterministic checks must invent the predicate — and §6.2's separate unpaid-debt rule already uses seam assignment differently.
- **Action:** define closure mechanically (e.g. "a thread is closed iff any finale pack's `payoff_debt`/escalation resolves a payoff listed in that thread's open payoffs, or a thread-status field set by the packs says RESOLVED") and add the matching fixture to B-T7.

### M9. B-T7's "impossible wardrobe day" is half-defined — Severity: 🟡 Major
- **Anchor:** §11 B-T7 (line 515); cross-ref §6.2 (line 406), §2.1 `EpisodePackV3`
- **Raised by:** style
- **Finding:** §6.2's rule ("an outfit changes within one story day without a beat or a scene break that allows it, or contradicts the wardrobe history") leaves "allows it" undefined — nothing in `EpisodePackV3` (per-scene `wardrobe[]`, beats with text and `planned_hold_ms`) marks a beat as authorising an outfit change. The "contradicts history" half is checkable against `ContinuityStateV3`; the "allows it" half is a guess.
- **Action:** define the allowance rule (e.g. within a scene a change is allowed only if a beat references it — a beat-level flag or a fixed outfit-ID convention; across scene breaks always allowed).

### M10. B-T2's WORKFLOW_MISMATCH guard has no defined seam for the pure-function consumers it enumerates — Severity: 🟡 Major
- **Anchor:** §10 B1 row (line 493) + §11 B-T2 (line 510); cross-ref §2.3 (lines 183–197)
- **Raised by:** codebase-details
- **Finding:** §2.3 says "B migrates no consumer" while B-T2 requires every listed consumer to refuse V3 input — but half the listed consumers are pure functions with no transaction, episode ID or workflow lookup to guard. The B1 builder must invent where the guard lives; either choice touches D/E/F-owned code (violating "B migrates no consumer") or makes B-T2's "enumerate these modules" unpassable as written.
- **Evidence:** `compile_episode_pack(pack: EpisodePack, *, approved_scope_hash: str, ...)` at `/root/AIVORA/drama-box/microdrama/src/microdrama/story/directing.py:101-111` takes an already-parsed V2 record — a "V3 episode" cannot even be passed to it; same for `editing/edl.py`, `editing/captions.py`, `rendering/routing.py`, `references/v2_planning.py`, `qa/continuity_sources.py` readers. A1's `require_workflow` inventory (A1-design-note.md:609–636) guards services (`references/service.py`, `editing/service.py`, `review/packages.py`, selectors, job replay), not these pure modules.
- **Action:** in the B1 note, pin one guard site per listed consumer (e.g. guard at the episode-story load boundary each consumer's caller uses; B-T2 drives the guarded entry points) and reword B-T2 to enumerate guarded entries, not modules.

### M11. B-T4's "has any line" tier-promotion trigger has no constructible pack; "known character" is undefined — Severity: 🟡 Major
- **Anchor:** §11 B-T4 (line 512); cross-ref §2.1 (line 134), §4.2 (lines 259–267), §6.1 (line 394)
- **Raised by:** codebase-details
- **Finding:** §4.2 promotes an extras role "if it … has any line" after all packs exist, but §2.1 types every line's `speaker` as a "character demand ID" (extras are a separate EXTRAS_ROLE demand kind, admissible only in `visible_cast[]`), and §6.1 makes "every line's speaker is a known character" a CRITICAL per-episode check evaluated during planning (§5.1 step 3) — before promotion ever runs. The only reading that makes N22's "an off-screen speaker is always at least SUPPORTING" meaningful (a SUPPORTING is already ≥SUPPORTING) requires extras to speak, which §2.1's typing forbids; neither this spec nor the master defines "known character" or how a new speaker emerges mid-season.
- **Action:** define "known character" (bible `CharacterProfile` ∪ previously-seen extras-role demand IDs) and state whether an extras-role demand ID is a legal `lines[].speaker` value; if yes, §6.1 must treat it as known and flag it for promotion; if no, delete "has any line" from the EXTRA→SUPPORTING triggers.

### M12. B3 ships `edit_tier` whose specified behaviour and gate depend on B5 machinery — Severity: 🟡 Major
- **Anchor:** §10 B3 row (line 495) + B-T4 (line 512); cross-ref §4.2 (lines 268–275), §4.3, §6.2, B5 row (line 497)
- **Raised by:** implementation-readiness
- **Finding:** §4.2's `edit_tier` re-runs promotion validation, demand derivation and the season critic's deterministic checks, and reopens STORY LOCK activations — the demand list (§4.3), season critic (§6.2) and activations are all B5, and promotion inputs (packs) come from the B4 job. B-T4's "refused demotion that would drop a voice or identity demand" (a §4.3 demand-list concept) cannot be tested as specified at the B3 gate.
- **Action:** move `edit_tier` plus the demotion case to B5, or state explicitly that B3 ships only the direct V3R-4 checks and B5 completes `edit_tier`.

### M13. No package is assigned to register the five `story_v3.*` job types — Severity: 🟡 Major
- **Anchor:** §10 B2/B4 rows (lines 494, 496); cross-ref §3.3 (line 233), §5.1 (line 317), §7
- **Raised by:** implementation-readiness
- **Finding:** B2's Approve effect enqueues `story_v3.bible` (B3's job) and B4's last `plan_episode` enqueues `story_v3.season_critic` (B5's job), so B-T3/B-T5 exercise job types whose phases haven't shipped. A1 note §7 says "V3 job types are distinct and registered per phase" and A3 §5.2 ties types to the generated contracts (JOB_SPECS). The builder must guess whether B1's contract bump registers all five (enqueue-allowed, handler-later) or each package registers its own — in which case B-T3's Approve fails inside the decision transaction at its own gate.
- **Action:** add to §10 that B1 registers all five `story_v3.*` job types; handlers land per package.

### M14. O-B2's episode-count decision is half-stated: no count control at LOCK, no binding to `requested_episode_count` — Severity: 🟡 Major
- **Anchor:** §12 O-B2 (line 529); cross-ref §3.2 (lines 219–221), §3.3 (line 233), B-T3 (line 511)
- **Raised by:** implementation-readiness, style
- **Finding:** (implementation-readiness) §3.2's validation chain never compares a proposal's `episode_count` to the requested count, Approve carries no count parameter, and no test covers the binding — an operator requesting 30 can silently receive and approve 20. (style) "the operator may choose 20–30 at intake and LOCK" overstates the LOCK mechanism: §3.3's Approve binds a proposal whose `episode_count` is already fixed; a UI builder reading O-B2 could add a LOCK-time count override that breaks the `lock_authority` binding.
- **Action:** state the binding rule (e.g. proposal `episode_count` must equal `requested_episode_count`, CRITICAL on violation), add the case to B-T3, and reword O-B2 to "chooses 20–30 at intake; at LOCK the choice is which approved proposal (or Revise)".

### N1. B-T1/B-T2 reference mechanics unstated — Severity: 🟢 Nit
- **Anchor:** lines 509–510
- **Raised by:** style
- **Finding:** "populated V1 + V2 database" names no fixture (which record kinds; must it contain the historical 180–300 s and 1–10 values the pass condition mentions? The A-phase precedent A-T16 covers only a populated V1 database). B-T2's "AST-identical source" has no reference mechanism anywhere in the corpus (only occurrence; the generated-contract drift check does exist at `microdrama/Makefile:33`, so B-T1's "no drift" clause is fine).
- **Action:** specify the fixture contents (V1 `EpisodePlan`/`Script` + V2 `EpisodePack` rows with 180–300 s and 1–10 values) and define the AST reference (e.g. committed `ast.dump` fixtures for the two validator modules).

### N2. B-T4 repair-round counting is off-by-one ambiguous — Severity: 🟢 Nit
- **Anchor:** line 512; cross-ref §3.2, §4.1, §5.1
- **Raised by:** style
- **Finding:** "→ repair → `BLOCKED (failed)` after 2 rounds" doesn't say whether the initial generation counts; §4.1's "at most 2 regenerate rounds" implies 3 total LLM content calls, but "after 2 rounds" can be read as 2 total. The fake-gateway scenario author must pick a number.
- **Action:** state total attempts once ("1 initial + 2 repair rounds = 3 content attempts, then `BLOCKED (failed)`") and use the same wording in §3.2, §4.1, §5.1 and B-T4.

### N3. B-T6's "a refusal → `WAITING_QUOTA`" flattens four distinct refusals — Severity: 🟢 Nit
- **Anchor:** line 514; cross-ref A0 §3.4/§5.1
- **Raised by:** style
- **Finding:** A0 defines `REFUSED` for QUOTA_UNREADABLE, QUOTA_5H, PACE_WEEK and CONCURRENCY, all with `retry_at`; only the first three are naturally quota waits. The fake scenario's refusal reason is unstated, so both the scenario and the expected track projection are guesses. (Implementation-readiness separately verified B-T6's `WAITING_QUOTA`/`retry_at` projection is consistent with A0 §5.1.)
- **Action:** name the scenario (e.g. QUOTA_5H → `WAITING_QUOTA` with its reset-time `retry_at`) and state the projection for the non-quota reasons.

### N4. B-T7 defect "injection" into an append-only, hash-verified store is unspecified — Severity: 🟢 Nit
- **Anchor:** line 515; cross-ref §2 `v3_story_documents`
- **Raised by:** style
- **Finding:** the store is append-only with hash re-verification on read, so a test cannot mutate a stored pack in place; B-T7 never says whether defects come from a fake-LLM scenario that emits the defect or from a defective pack version written through `StoryV3Store`.
- **Action:** one sentence in B-T7 — defects are produced by the fake architect/season-critic scenarios (or written as new pack versions through the store), never by editing rows.

### N5. "A1–A3 accepted" is ambiguous between acceptance and shipped — Severity: 🟢 Nit
- **Anchor:** §10 prerequisites (lines 483–486)
- **Raised by:** implementation-readiness
- **Finding:** ambiguous between design-note acceptance (the phrase's usual meaning in this workflow; the A2/A3 notes say "not yet built") and shipped — but B-T1 requires the migration tail at 0035 applied.
- **Action:** say "shipped (gates green, tail at 0035)".

### N6. §13 has no trace row for the extension machinery B-T11 discharges — Severity: 🟢 Nit
- **Anchor:** §13 (lines 535–553); cross-ref §8, B-T11 (line 519)
- **Raised by:** implementation-readiness
- **Finding:** master §15.2 assigns R-3.7 to F, matching B's Owns line, but B builds real extension machinery (`create_extension`, the extension builder) that §13 leaves untraced; a reader cannot tell which obligation B-T11 discharges.
- **Action:** add a row "R-3.7 (mechanism only; milestone in F) | §8, B-T11".

### N7. B-T12's "one primary action per tab" contradicts §9's tab-2 cell — Severity: 🟢 Nit
- **Anchor:** line 520; cross-ref §9 (line 465)
- **Raised by:** implementation-readiness
- **Finding:** §9's tab-2 cell reads "none (reviewed at STORY LOCK); Next after completion" — self-contradictory with B-T12's assertion; the B6 builder must guess what to render and assert pre-completion.
- **Action:** pick one in §9.

### N8. §2.3's consumer order omits three live story-record consumers — Severity: 🟢 Nit
- **Anchor:** §2.3 (lines 189–197), feeding B-T2
- **Raised by:** codebase-details
- **Finding:** b-factmap.md §4 lists `src/microdrama/qa/coverage.py`, `qa/comparison.py` and `qa/observation.py` as script/manifest consumers (files verified present), none of which appear in §2.3's D/E/F lists, so B-T2's "every listed V1/V2 consumer" proves less than the actual consumer set. They are likely unreachable for V3 input via A1's job-boundary refusals (A1-design-note.md:620–621), hence a Nit.
- **Action:** add them to §2.3's D row, or state they are reached only through guarded W05–W07 job paths.

### N9. Header master-version pin is stale twice over — Severity: 🟢 Nit
- **Anchor:** header pin (line 7) vs §2.2 (line 156) vs the file on disk
- **Raised by:** codebase-details
- **Finding:** line 7 pins "Master: SPEC-v3.md v0.4.4" while §2.2 cites "master v0.4.5 §6" for the one-neutral-voice rule O-B3 depends on, and the file on disk is v0.4.6, 13 Nov ("no rule changes" in v0.4.6). A builder tracing the header pin would not find the §6 rule change; O-B3 restates it inline, so nothing blocks.
- **Action:** bump the header pin to v0.4.6 (one edit).

## Verified clean (all three lenses, for routing confidence)

Gate coverage B-T1..B-T12 partitioned exactly once across B1–B6; routing linear and non-circular; prerequisites match the phase-A package table (A5 is the UI shell); B-T9's "episode rows + `episode_tracks` + accounts + bindings" matches phase-A-spec.md §3 / A2's `create_v3_episodes`; B-T3's targeted-Revise mechanism exists (A1 `season_revision_notes.targets`); B-T11's `RELEASING`/`COMPLETE` eligibility and the A1 OQ-1 `create_extension` activation match the A1 note (with `RELEASING` noted as an A1 release-track state, not today's `PodState`); B-T6's quarantine matches A3's `stale_artifacts`; `LlmStep`/`logical_call_id`/crash-refusal-defer fuses exist (A0 build, commit c25b527); migration numbering (tail 0035, B1 starts at 0036) is consistent with §10's "allocated in the B1 note after re-auditing the tail"; O-B6 is accurate against `migrations/0019_v2_contract_documents.sql`; §12's O-B1/O-B3 values match §2.2 and the DECISIONS "D2 revised (again)" trail; §13's fifteen R-IDs equal master §15.2's phase-B row, V3-AT-3/4/18/19 map to B-T7/B-T8/B-T5/B-T1, and every §13 row and every "Findings resolved here" entry (V3C-4/-5/-26/-32, MA19, V3R-4, N22) resolves to sections that contain what is claimed.

## Counts (after dedup)

**Blocker: 0 · Major: 14 · Nit: 9** (25 raw findings across three reviewers → 23 deduplicated items)
