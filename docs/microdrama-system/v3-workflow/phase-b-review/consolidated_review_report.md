# Consolidated Review Report — phase-B-spec.md

- **Target:** `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-B-spec.md` — "Phase B: Story (Script Maker → LOCK → bible → episode packs → STORY LOCK)", v0.3, 12 Nov 2026 (562 lines)
- **Mode:** EGM Goldfish review, headless, uninterrupted (Preset 1 — all review rubrics). No findings were resolved; no file outside this artifact directory was edited.
- **Semantic split:** FeatureRange = lines 1..480 (§0–§9) · DetailedRange = lines 481..562 (§10–§13), bound at the `## 10. Build packages` work-breakdown header.
- **Date:** 2026-11-13 · **Reviewer model tier:** GLM-5.3 (session provider), fresh context per reviewer
- **Stages and artifacts (this directory):**
  - Stage 5 Initial Zoom Out — `zoom_out_report.md` (1 fresh `egm-zoom-out`)
  - Stage 6 Comprehension Test — `comprehension_report.md` (1 fresh `egm-comprehension`; paraphrase clean, 0 Blockers)
  - Stage 7 Critic Review — `critic_report.md` (fresh `egm-design` + `egm-structural` + `egm-style` on FeatureRange)
  - Stage 8 Intermediate Zoom Out — `intermediate_zoom_out_report.md` (1 fresh `egm-zoom-out`, full file, accumulated context)
  - Stage 9 Implementation Readiness — `implementation_readiness_report.md` (fresh `egm-implementation-readiness` + `egm-codebase-details` + `egm-style` on DetailedRange)

**Method note.** 75 raw findings → 45 consolidated action items. Deduplication merges findings from different stages that name the same underlying defect; the highest severity among duplicates is kept (so several Nit-rated raw findings sit inside Major items, and one Nit cluster was promoted by Stage 7's Major). `[format]` marks a finding that only asks for a section the EGM template expects, so the spec owner can triage it apart from real defects. Count reconciliation: Stage 6's count line says "7 Nits" but lists 6 Nit items (1 Major + 6 Nits = 7 findings); this report uses the listed items, hence 75 raw findings, not 76.

---

## Executive summary

**Verdict: the architecture is right and the skeleton is verified sound; the document is not ready to hand to build routing as-is, but every finding is fixable in text plus a small set of guardian-owned contract deltas — no re-architecture anywhere.**

What was verified clean (not assumed): scope matches master §15's Phase B row exactly (V3-AT-3/4/18/19; R-1.1..R-3.6; no C/D/E/F/A2/A3/A5 territory claimed); code anchors, planning states, gate semantics and the V1/V2 freeze check out against `b-factmap.md`, the live code and the A0/A/A1/A2/A3 family; gate allocation B-T1..B-T12 partitions exactly once across B1–B6; routing is linear; migration-numbering, decision-citation and §13 trace rows all resolve. The comprehension paraphrase was clean (0 Blockers): a fresh reader can reconstruct the system.

The residue has one systemic root and three shapes:

1. **One Blocker, systemic** (C-B1): B was drafted against the master while A1/A2 froze enums, SQL CHECKs and validators — B invents step keys, decision-target kinds and a command that those enforced contracts reject, and its build plan nowhere enumerates the required guardian-owned contract deltas. Stage 7's Blocker (step keys), the Approve-target/Revise-target Majors and the dangling "A2 §x" citations are all edges of this one defect. Fix: a "B contract deltas" register as a first-class, critiqued-first B1 deliverable.
2. **Four architecture-adjacent Majors from the intermediate pass** (C-M1..C-M5): B is the family's first non-linear job graph and no phase defines the fan-out/fan-in idiom its three flows need; the family-mandated command table is absent; the prompt set (the phase's actual quality instrument, pinned by §7's own rules) has no owner, package or acceptance hook; and resume semantics for a half-regenerated season are undefined.
3. **Precision gaps**: the remaining Majors are missing decision rules and untestable predicates (critic-rule scope mismatches, undefined switch/cap/counting rules, acceptance tests that name outcomes with no defined mechanism). Each is a one-line-to-one-paragraph fix, but each is also a point where a builder would guess.

**Sequencing (from Stage 9):** pin C-B1, C-M10, C-M13, C-M14, C-M15, C-M16, C-M20 plus the B1/B5-specific items **before B1 routes to build**; the rest can land with their package notes but must land before their gate runs. All findings should land before the B1/B5 design notes are drafted and before the Codex critique round, because each is a path by which a builder could implement something the family's own constraints reject.

**Counts (consolidated): 🔴 Blocker 1 · 🟡 Major 22 (1 tagged [format]) · 🟢 Nit 22 — total 45.**

---

## 🔴 Blockers

### C-B1. The frozen-contract seam: B invents vocabulary A1/A2's enforced contracts reject, and no contract-delta deliverable exists
- **Merges:** S8-1 (Blocker) · S7-B1 (Blocker) · S6-1 · S7-M11 · S5-1 · S9-M1 · S7-M9 · S6-3 · S5-9
- **Anchor:** §1.3 (61–62), §3.3 (233), §5.3 (345), §4.2 (269–275), §2 (107); §10 B1 row.
- **Defect:** One root cause behind five reported edges: (a) step keys `script_maker`/`bible`/`episodes` are refused by A2's CHECK (`step_01..step_10`, `launch`, `episode_production`) and by `md_reservation_step_rules` — the citation "(A2 §5.2)" resolves to nothing; (b) `Approve target = {kind: proposal, id}` has no carrier: A1's `V3DecisionCommand` has no target field and `RevisionTargetKind` has no proposal kind; (c) B's Revise targets (`episode:<n>`, bible sections, the seam, tiers) fit none of A1's six kinds, and no episode UUID exists before STORY LOCK; (d) `edit_tier` appears in no command-table row; (e) "A2 §5.1/§5.4", "A3 §7.1" dangle (the content lives in phase-A-spec §5.1/§5.4/§7.1). Each instance is discovered only at build or enforcement time, against a frozen artifact B does not own. Stage 5's YAGNI note (S5-9) is a disposition option inside the same fix (strike the promise, or keep it as config with no admission logic).
- **Action:** Add a **"B contract deltas" register** as a first-class, critiqued-first B1 deliverable: (1) step-key mapping — adopt `step_01..step_03` per A2's OQ-2 mapping, or record a new migration amending A2's CHECK; (2) `RevisionTargetKind`/`V3DecisionCommand` extension or a B-side binding-unit encoding for proposal/pack/bible-section/seam/tier targets, with the enum migration; (3) an A1-§6-format command-table row for `edit_tier`; (4) one citation convention for A1/A2/A3 notes vs phase-A-spec, then sweep. Rule going forward: any B-side identifier crossing an A-phase contract is checked against that contract's enforced vocabulary before the B1 note is accepted.

---

## 🟡 Majors

### C-M1. Orchestration model gap: three flows need fan-out/fan-in choreography no phase defines, written as synchronous sequences
- **Merges:** S8-2 · S7-M2 · S5-2 · S7-M5 (facet b) · S7-M6 (choreography half)
- **Anchor:** §5.2 steps 3–4 (328–335), §5.1 success clause (316–317), §5.3 Revise row (345), §4.2, §7 job table.
- **Defect:** The promote_profile → demand-list → binding → open-gate "Then:" sequence is written as one actor's consecutive steps but promotion is N async jobs (and §1.7's gate invariant makes the wait mandatory with no waiter defined); repair rounds and the Revise loop re-plan a subset with no completion detector; B never uses A1's `replaces_job_id`, and the stated semantic key `(scope, n, LOCK authority, bible version)` makes legitimate re-plans dedupe to a no-op. Each builder's invention of the choreography lands differently.
- **Action:** Define one continuation idiom once in §7 (e.g. the last job of a logical round, by per-round `logical_work_id` prefixes, enqueues the continuation job; `replaces_job_id` chains for re-plans) and apply it to the promote join, repair rounds and the Revise loop. Uses only existing A1 primitives.

### C-M2. Pre-gate repair-cascade blast radius is unbounded — no cap, no impact preview, no risk owner
- **Merges:** S5-3 · S7-M6 (breadth half)
- **Anchor:** §5.2 step 3 (328–329); §5.5 (375–384).
- **Defect:** A continuity finding at episode 3 can re-plan episodes 3–24 — up to ~44+ LLM calls per round, two rounds, through a max-concurrent-1 gateway with 5-hour quota windows — with no breadth cap, no operator checkpoint, no visibility; the pre-gate silent regeneration vs post-gate "Revise these too" asymmetry is defensible but unstated. Quota exhaustion mid-cascade leaves a half-regenerated BLOCKED season.
- **Action:** Bound the cascade (named episode + directly invalidated successors up to a cap, iterating with the critic; or an operator checkpoint when a round would re-plan more than K episodes), state the asymmetry rationale, and name the blast radius on the season-critic wait state.

### C-M3. B's family command table is missing; `edit_tier` has two overlapping flows and wrong package sequencing
- **Merges:** S8-3 · S7-M5 · S9-M12 · S7-N9
- **Anchor:** document level (§3.1, §4.2, §8); master §2.2; §10 B3 row.
- **Defect:** Master §2.2 mandates a per-phase command table; phase-B-spec.md has none (`submit_v3_intake`, `edit_tier`, `create_extension` have no rows with lock order/events/replay). `edit_tier` also overlaps the tier-targeted Revise with different effects (deterministic-only re-check + self-reopen vs season critic + §5.5 closure — undefined when no episode is noted), and it ships in B3 while everything it re-runs (demand list, season critic, activations) is B5, so B-T4's demotion case cannot pass at its own gate. Naming drift ("tier revalidation" vs "promotion validation") rides along.
- **Action:** Add a "B commands" section with A1-§6-format rows for the three commands (or delegate explicitly to the B1/B5 notes, named in §10); state which flow the tab-3 tier controls invoke; move `edit_tier` + the demotion case to B5 (or state B3 ships only the direct V3R-4 checks); unify the check's name.

### C-M4. The prompt set has no owner, no package, and no acceptance hook
- **Merges:** S8-4 (sole source)
- **Anchor:** §7 (427–431), §10 package table, §11.
- **Defect:** §7 requires every `FrozenLlmCall` to pin a manifest-registered prompt, and B needs ≥6 non-trivial prompts (proposal, bible, architect, translation, critics, promoted-profile) — but no B package builds, versions or registers them, and the fake-adapter tests never fail on prompt absence. The Joey-method fidelity and the §11 frozen-workload comparison both presuppose these prompts exist.
- **Action:** Name the prompt set and its `PromptManifest` registration in the owning package rows (B2/B3/B4/B5) and add one acceptance line: every `FrozenLlmCall` in tests references a manifest-registered prompt; the manifest ships with the package.

### C-M5. Resume semantics for a partially regenerated season are undefined
- **Merges:** S8-5 (sole source)
- **Anchor:** §5.2 step 3 + CRITICAL-remains clause (328–338), §5.5, §3.2's BLOCKED/retry, §9 "blocked" state.
- **Defect:** When a regeneration round stalls (quota window, terminal job failure), the spec never states what the operator's retry action re-runs (failed job? whole round? from the earliest regenerated episode?), whether completed packs in the round are kept, or what tab 3 shows mid-round. Master §12.6 defines this closure only post-approval.
- **Action:** One paragraph in §5.2/§5.5: rounds are the unit of retry (idempotent via round-scoped logical work IDs), completed packs are kept (stable demand/pack IDs make this safe), and the screen labels per-pack version status during a round.

### C-M6. §3.2's "no real people, brands or celebrities named" check is attributed to a module that cannot perform it
- **Merges:** S7-M1 (sole source)
- **Anchor:** §3.2 (218–220).
- **Defect:** `S/research/originality.py` is a resemblance screener against a comparator corpus; it has no real-person/brand/celebrity list. A builder wires it, believes the check exists, and ships a no-op for exactly the class of risk master §1 rule 4 covers (real enforcement is phase C's, master §12.2).
- **Action:** Specify the actual B mechanism (curated blocklist with source and on-hit behavior) or state plainly that B enforces this only via prompt constraints + originality-vs-corpus screening, with the people/brand check deferred to master §12.2 in C — labeled as residual risk.

### C-M7. Promoting an extras role creates a duplicate identity demand with no stated resolution
- **Merges:** S7-M3 (sole source)
- **Anchor:** §4.2 (260–268) vs §4.3 (283–289), §2.1 visible_cast (131).
- **Defect:** Packs reference the extras-role demand ID; promotion adds a CHARACTER demand for the same on-screen person; literal derivation lists both, so phase C would generate two different identities for one role — defeating V3R-4 and inflating image volume.
- **Action:** State the rule (on promotion the EXTRAS_ROLE demand is withdrawn/merged with lineage and pack references resolve to the CHARACTER demand) and add the case to B-T8.

### C-M8. Three §6.2 CRITICAL rules are undefined on an extension scope; one can permanently block an extension's STORY LOCK
- **Merges:** S7-M4 (sole source)
- **Anchor:** §8 (449–458) vs §6.2 (405–411).
- **Defect:** "Episode count differs from the LOCK authority", the §6.1 "final set" re-check, and "seam thread resolved in the finale" are not reinterpreted when the pack set is the extension range and the authority is a SEASON amendment — and resolving a seam thread in an extension finale is a legitimate endpoint, yet as written it is CRITICAL with no remedy.
- **Action:** Add an extension-scope reinterpretation list to §6.2 or §8 (count authority = the amendment's count over the cumulative range; re-check set = the extension's packs; seam-closed CRITICAL only when further growth was reserved).

### C-M9. B-T7's "seam closed in the finale" has no detection predicate
- **Merges:** S9-M8 (sole source)
- **Anchor:** §11 B-T7 (515); §6.2 (408); §2 `ExtensionSeamV3` (114).
- **Defect:** Threads carry only id/description/open payoffs/constraints; packs never reference seam threads and no field marks a thread resolved — the builder of the deterministic check must invent the signal.
- **Action:** Define closure mechanically (e.g. a thread is closed iff a finale pack resolves a payoff in its open-payoffs list, or a thread-status field says RESOLVED) and add the matching B-T7 fixture.

### C-M10. §2.3/B-T2's consumer-refusal guarantee has no defined guard seam, and the consumer list is incomplete
- **Merges:** S7-M8 · S9-M10 · S5-8 · S9-N8
- **Anchor:** §2.3 (183–197), B-T2 (510), §10 B1 row.
- **Defect:** Half the listed consumers are pure functions with no transaction or workflow lookup to guard (`directing.py:101` takes an already-parsed V2 record); A1's guard inventory covers services, not these modules; `qa/coverage.py`, `qa/comparison.py`, `qa/observation.py` are missing from the list; and B-T2 re-proves A1's A-T5 while hard-coding D/E/F future state. Either the test proves less than claimed or B touches D/E/F-owned code, violating "B migrates no consumer".
- **Action:** In the B1 note, pin one guard site per listed consumer (existing A1 guard / dispatch guard / new module guard B1 adds), complete the list (or state the qa trio is reachable only through guarded job paths), reword B-T2 to enumerate guarded entry points rather than modules, and make the enumeration a shared fixture instead of a re-edited copy of A-T5.

### C-M11. Master §4.2's "SeasonBibleV3 wraps the existing SeasonBible and RichBible" clause is silently dropped
- **Merges:** S5-4 (sole source)
- **Anchor:** §1.2 (52–56); §2 Reused shapes (117–121).
- **Defect:** A binding master clause is neither honored nor recorded as a deviation. B's fresh-record design is plausibly simpler, but the deviation is unrecorded anywhere.
- **Action:** One sentence — wrap the existing models, or record the deviation (folds into the B1/B5 gate checklist, C-N22).

### C-M12. `story_v3.promote_profile` is under-specified and has zero acceptance coverage
- **Merges:** S5-5 (failure-policy/storage/hash facet) · S9-M6 (coverage facet); the choreography facet sits in C-M1
- **Anchor:** §4.2 (257–275); §5.2 "Then:" (330–335); §7 job table (423); §11.
- **Defect:** The promoted-profile LLM job has no invalid-output/repair/failure policy (unlike every other B LLM job), no statement of where promoted `CharacterProfile`s persist, no rule for whether a completed profile bumps the bible record version — and so the `StoryLockBindingV3` hash — while the gate is open; and no B-T row proves one promotion → one `promote_profile` call.
- **Action:** Specify failure behavior, storage, and the binding-hash interaction; add the promotion-job acceptance case.

### C-M13. Four critic-rule scope mismatches between the record tables (§2/§4) and the critic tables (§6)
- **Merges:** S7-M12 · S7-M13 · S7-M14 · S7-M15 · S6-6 · S9-M11 · S9-M4
- **Anchor:** §2.1 (134–136) vs §6.1 (394, 400); §4.2 (259–267); §2.2 (153) vs §4.3 (287); §4.3 (279) vs §5.2 (337–338).
- **Defect:** (a) psychology entries are mandatory for principals and supporting (§2.1) but enforced only for principals (§6.1), and "appears" is undefined for off-screen speakers; (b) "every line's speaker is a known character" (CRITICAL, evaluated before promotion) collides with the "has any line" promotion trigger — §2.1 types `speaker` as a character demand ID while extras are a separate kind, so the promotion case has no constructible pack; (c) the 3-active-locations cap never says whether it counts distinct `location_key`s or (location, light-state) demands — the two readings validate different packs — and no test injects a 4th location; (d) §4.3's "after the season critic passes" contradicts §5.2's open-the-gate-when-CRITICALs-remain flow, deadlocking the Revise loop.
- **Action:** Four one-sentence alignments: extend the psychology rule (or state the narrower enforcement is deliberate) and define "appears"; define "known character" (bible profiles ∪ previously-seen extras-role IDs) and state whether an extras-role ID is a legal `speaker` value (if not, delete "has any line" from the promotion triggers); define the cap unit ("at most 3 distinct `location_key` values in `scenes[]`, recap excluded") and inject the 4-location defect in B-T7; change §4.3 to "after the season critic runs (regardless of remaining findings)".

### C-M14. O-B5's episode-critic switch has no mechanism, scope, default assertion or test
- **Merges:** S9-M3 · S7-N6
- **Anchor:** §12 O-B5 (532); §5.1 step 4 (313); §10 B4 row.
- **Defect:** "Off by default, switchable" names no flag, scope, actor or default assertion; §5.1's "optionally" says neither whose option nor the default; B-T5/B-T6/B-T7 never exercise it — nothing prevents the default shipping on.
- **Action:** One clause (e.g. a `Settings` flag `MICRODRAMA_V3_EPISODE_CRITIC`, default off, global, read at `plan_episode` dispatch) plus a default-off and a toggled-on test case.

### C-M15. O-B2's episode-count decision is half-stated: no binding to `requested_episode_count`, overstated LOCK control
- **Merges:** S9-M14 (sole source)
- **Anchor:** §12 O-B2 (529); §3.2 (219–221); §3.3 (233); B-T3.
- **Defect:** Validation never compares a proposal's `episode_count` to the requested count and Approve carries no count parameter — an operator requesting 30 can silently receive and approve 20 — while "choose 20–30 at intake and LOCK" invites a UI count override that would break the `lock_authority` binding.
- **Action:** State the binding rule (proposal `episode_count` must equal `requested_episode_count`, CRITICAL on violation), add the B-T3 case, reword O-B2 ("chooses at intake; at LOCK the choice is which approved proposal, or Revise").

### C-M16. B-T5's "query-log assertion" names a mechanism defined nowhere
- **Merges:** S9-M2 (sole source)
- **Anchor:** §11 B-T5 (513).
- **Defect:** The load-bearing clause of the V3-AT-18 test defers to a facility no document defines and no test infrastructure provides; the candidate mechanisms (restricted DB role, pg_stat_statements delta, log capture, instrumented wrapper, event trigger) each prove different things, and the choice decides whether the test stays offline.
- **Action:** B4's note pins the mechanism and proof obligations (e.g. test jobs run under a DB role with no privilege on the four table families; assert completion with no access attempted) and lists the exact table names asserted empty.

### C-M17. O-B3's closed emotion vocabulary is never enforced by any test
- **Merges:** S9-M5 (sole source)
- **Anchor:** §11 table (507–520); §2.2; §12 O-B3 (530).
- **Defect:** B-T7 checks emotion presence and B-T2 tests only 180 s / 10-episode rejection, so `emotion='ENVIOUS'` is never refused anywhere — a decided closed vocabulary with no rejecting test.
- **Action:** Add an out-of-enum emotion rejection case (B-T7 or the B4 note).

### C-M18. Non-episode STORY LOCK Revise targets: regeneration behavior left to inference, untested
- **Merges:** S9-M7 · S6-5
- **Anchor:** §5.3 Revise row (345) vs §5.5; B-T10 (518).
- **Defect:** For a bible-section or seam Revise, the spec never states which packs regenerate afterward (§5.5's machinery is defined for noted packs and continuity-invalidated dependents, and would not catch conceptual drift); B-T10 exercises only `episode:<k>`.
- **Action:** State the behavior (non-invalidated packs survive; the closure revalidation runs; drift beyond continuity is the operator's judgement at the reopened gate) and add one bible-section/seam/tier Revise case.

### C-M19. B-T7's "impossible wardrobe day" is half-defined
- **Merges:** S9-M9 (sole source)
- **Anchor:** §11 B-T7 (515); §6.2 (406); §2.1.
- **Defect:** "Without a beat or a scene break that allows it" — nothing in `EpisodePackV3` marks a beat as authorising an outfit change; the "contradicts history" half is checkable against `ContinuityStateV3`, the "allows it" half is a guess.
- **Action:** Define the allowance rule (e.g. within a scene a change is allowed only if a beat references it; across scene breaks always allowed).

### C-M20. No package is assigned to register the five `story_v3.*` job types
- **Merges:** S9-M13 (sole source)
- **Anchor:** §10 B2/B4 rows; §3.3 (233), §5.1 (317), §7.
- **Defect:** B2's Approve enqueues `story_v3.bible` (B3's job) and B4's last episode enqueues `story_v3.season_critic` (B5's job); whether B1's contract bump registers all five types (enqueue-allowed, handler-later) or each package registers its own is unstated — in the latter case B-T3's Approve fails inside the decision transaction at its own gate.
- **Action:** Add to §10: B1 registers all five `story_v3.*` job types; handlers land per package.

### C-M21. `[format]` No Risks & Limits treatment and no alternatives evaluation in the active scope
- **Merges:** S7-M7 (sole source)
- **Anchor:** document level, §0–§9 (§1 in particular).
- **Defect:** The applied feature-spec standard's two mandatory disciplines are unmet: no risks/limits section (master §18 is cited once, for the Joey licence only) and no alternatives-rejected record (master §17 is never cited), leaving single-path decisions (one-LlmStep bible, strictly serial planning, promotion after all packs, versions=rounds) without their rejected options.
- **Action:** Add a short risks table (bible output size/truncation; serial planning wall-clock and quota pauses; repair-cascade cost; single-pass ZH translation becoming the record of truth) with a master §18 pointer, plus one alternatives-rejected line per major design choice citing master §17 where it rules. *[format]: asks only for template sections — triage separately from the defect findings.*

### C-M22. Stale, internally mixed version pins and dependency list
- **Merges:** S7-M10 · S5-7 · S6-4 · S9-N9 (promoted to Major by S7-M10: the §6 voice rule O-B3 depends on is unfindable from the pin)
- **Anchor:** header lines 3, 7, 11; §2.2 line 156.
- **Defect:** Master pinned at v0.4.4 while line 3 cites v0.4.5 §6 and the live master is v0.4.6 (whose fold of the v0.1 clauses touches §4.1/§4.2, the sections B cites most); "the A2 and A3 design notes (being drafted)" is stale — both exist (v1.0, 12 Nov). Metadata defect only; content was verified to match v0.4.6.
- **Action:** Re-pin to v0.4.6, re-verify the §4.1/§4.2/§6 citations against the folded text, refresh the dependency list to the A2/A3 notes' real versions.

---

## 🟢 Nits

| ID | Finding (merged sources) | Anchor → action |
|----|--------------------------|-----------------|
| C-N1 | Dangling record references: `SeasonBibleV3` has no initial-continuity-state field that §5.1 feeds to episode 1; `cta.template_id` references a template registry no phase owns (S5-6) | §5.1/§2/§2.1 → add the field; name the CTA template owner or drop `template_id` |
| C-N2 | One-off undefined terms: "proof-prop flag", "the season plan" (S6-2) | §4.3, §5.1 → one definition each |
| C-N3 | Slot-targeted LOCK Revise with byte-identical carry exceeds master §4.1's note model — confirm the operator wants it (S5-10) | §3.3, B-T3 → confirm or simplify to whole-round |
| C-N4 | "(§12.2)" lacks the "master" qualifier and collides with the target's own §12 (S7-N1) | line 220 → "master §12.2" |
| C-N5 | Present-tense forward reference to the unwritten B1 design note (S7-N2) | §2.3 (163–164) → phrase as an obligation |
| C-N6 | Supersession attribution mismatch vs DECISIONS.md ("D2 refined" vs "D2 revised" as the superseded entry) (S7-N3) | line 158 vs DECISIONS line 242 → align |
| C-N7 | "(versions = rounds)" breaks after a Reject: a fresh intake's round-1 content must land as version k+1 (S7-N4) | §2 vs §3.3 → state reset/continue/new-ID rule |
| C-N8 | §6.1 is episode-shaped but §4.1 cites it as the bible critic's rule set (S7-N5) | §4.1/§6.1 → add the bible-specific rules or point to where they live |
| C-N9 | Retry-count phrasing drifts ("a retry … at most 2" vs "2 regenerate rounds"); B-T4's "after 2 rounds" is off-by-one ambiguous (S7-N7, S9-N2) | §3.2/§4.1/§5.1/§5.2/B-T4 → standardise "1 initial + 2 repair rounds = 3 content attempts" |
| C-N10 | `story_time` parenthetical garbled — "setting: reusing StoryTime" (S7-N8) | §2.1 line 131 → reorder the parenthetical |
| C-N11 | Two parallel TBD mechanisms (`tbd[]` vs literal `[TBD]`) with no stated relationship (S7-N10) | §2 vs §4.1/§6.1 → one linking sentence |
| C-N12 | Intake signature has no mode parameter yet TREND is "refused" (S7-N11) | §3.1 → the route accepts a mode field; only TITLE admitted |
| C-N13 | Season-critic logical work ID defined by an undefined component ("<binding inputs>") (S7-N12) | §7 line 425 → name the concrete component |
| C-N14 | Status sentence dangles ("DRAFT …, after the Codex week resets") (S7-N13) | line 5 → reword |
| C-N15 | B-T1/B-T2 reference mechanics unstated: populated-DB fixture contents; "AST-identical" has no reference mechanism (S9-N1) | B-T1/B-T2 → specify fixture records; commit `ast.dump` fixtures |
| C-N16 | B-T6's "a refusal → WAITING_QUOTA" flattens four distinct A0 refusal reasons (S9-N3) | B-T6 → name the scenario (e.g. QUOTA_5H) and the non-quota projections |
| C-N17 | B-T7 defect "injection" into an append-only, hash-verified store is unspecified (S9-N4) | B-T7 → defects come from fake-LLM scenarios or new pack versions, never row edits |
| C-N18 | "A1–A3 accepted" ambiguous between design-note acceptance and shipped (B-T1 needs the migration tail applied) (S9-N5) | §10 prerequisites → "shipped (gates green, tail at 0035)" |
| C-N19 | §13 has no trace row for the extension machinery B-T11 discharges (S9-N6) | §13 → add "R-3.7 (mechanism only; milestone in F) \| §8, B-T11" |
| C-N20 | B-T12's "one primary action per tab" contradicts §9's tab-2 cell ("none … ; Next after completion") (S9-N7) | §9/B-T12 → pick one |
| C-N21 | §10 Routing names GLM/Codex as build actors with no identification or pointer (S6-7) | §10 → pointer or footnote |
| C-N22 | Fold the skeleton repairs into one B1/B5 "critiqued first" gate checklist: contract-delta register (C-B1), command rows (C-M3), risks/alternatives (C-M21), deviations-considered list (C-M11) (S8-6) | §10 → enumerate the required artifacts at the gate |

---

## Traceability matrix (raw → consolidated)

| Raw | Raw severity | Consolidated |
|-----|--------------|--------------|
| S5-1 Revise targets vs RevisionNoteTarget | Major | C-B1 |
| S5-2 semantic-key collision on re-plan | Major | C-M1 |
| S5-3 cascade unbounded + asymmetry | Major | C-M2 |
| S5-4 master §4.2 wrap dropped | Major | C-M11 |
| S5-5 promote_profile under-specified | Major | C-M1, C-M12 |
| S5-6 dangling record refs | Nit | C-N1 |
| S5-7 stale header pins | Nit | C-M22 |
| S5-8 B-T2 duplicates A-T5 / future state | Nit | C-M10 |
| S5-9 speculative step_key plumbing | Nit | C-B1 |
| S5-10 slot-targeted Revise carry | Nit | C-N3 |
| S6-1 step keys + false citation | Major | C-B1 |
| S6-2 undefined one-off terms | Nit | C-N2 |
| S6-3 citation-key ambiguity | Nit | C-B1 |
| S6-4 stale version pins | Nit | C-M22 |
| S6-5 bible-section Revise inference | Nit | C-M18 |
| S6-6 psychology scope mismatch | Nit | C-M13 |
| S6-7 GLM/Codex unexplained | Nit | C-N21 |
| S7-B1 step keys violate A2 enum | Blocker | C-B1 |
| S7-M1 originality name check | Major | C-M6 |
| S7-M2 promote join undefined | Major | C-M1 |
| S7-M3 duplicate identity demand | Major | C-M7 |
| S7-M4 extension-scope CRITICALs | Major | C-M8 |
| S7-M5 edit_tier outside command framework | Major | C-B1 (facet a), C-M3 (facet b) |
| S7-M6 unbounded cascade | Major | C-M1 (choreography), C-M2 (breadth) |
| S7-M7 no risks/alternatives | Major | C-M21 [format] |
| S7-M8 consumer guards outside A1 inventory | Major | C-M10 |
| S7-M9 dangling A2/A3 citations | Major | C-B1 |
| S7-M10 stale mixed pins | Major | C-M22 |
| S7-M11 Approve target kinds absent | Major | C-B1 |
| S7-M12 psychology scope + "appears" | Major | C-M13 |
| S7-M13 "known character" vs promotion | Major | C-M13 |
| S7-M14 location-cap unit | Major | C-M13 |
| S7-M15 "after the critic passes" | Major | C-M13 |
| S7-N1 "(§12.2)" qualifier | Nit | C-N4 |
| S7-N2 B1-note forward reference | Nit | C-N5 |
| S7-N3 supersession attribution | Nit | C-N6 |
| S7-N4 versions=rounds after Reject | Nit | C-N7 |
| S7-N5 §6.1 as bible critic rules | Nit | C-N8 |
| S7-N6 "optionally" not a switch rule | Nit | C-M14 |
| S7-N7 retry-count phrasing | Nit | C-N9 |
| S7-N8 story_time parenthetical | Nit | C-N10 |
| S7-N9 tier-revalidation naming | Nit | C-M3 |
| S7-N10 two TBD mechanisms | Nit | C-N11 |
| S7-N11 intake mode parameter | Nit | C-N12 |
| S7-N12 work-ID component undefined | Nit | C-N13 |
| S7-N13 status sentence | Nit | C-N14 |
| S8-1 frozen-contract seam systemic | Blocker | C-B1 |
| S8-2 orchestration model gap | Major | C-M1 |
| S8-3 command table missing | Major | C-M3 |
| S8-4 prompt set homeless | Major | C-M4 |
| S8-5 resume semantics open | Major | C-M5 |
| S8-6 gate checklist | Nit | C-N22 |
| S9-M1 step keys unowned + enum | Major | C-B1 |
| S9-M2 query-log mechanism | Major | C-M16 |
| S9-M3 O-B5 switch | Major | C-M14 |
| S9-M4 O-B1 cap basis + test | Major | C-M13 |
| S9-M5 emotion enum untested | Major | C-M17 |
| S9-M6 promote_profile untested | Major | C-M12 |
| S9-M7 non-episode Revise untested | Major | C-M18 |
| S9-M8 seam-closed predicate | Major | C-M9 |
| S9-M9 wardrobe-day half-defined | Major | C-M19 |
| S9-M10 guard seam for pure functions | Major | C-M10 |
| S9-M11 "has any line" not constructible | Major | C-M13 |
| S9-M12 edit_tier B3/B5 sequencing | Major | C-M3 |
| S9-M13 job-type registration | Major | C-M20 |
| S9-M14 O-B2 count binding | Major | C-M15 |
| S9-N1 B-T1/B-T2 mechanics | Nit | C-N15 |
| S9-N2 repair-round off-by-one | Nit | C-N9 |
| S9-N3 B-T6 refusal reason | Nit | C-N16 |
| S9-N4 B-T7 injection method | Nit | C-N17 |
| S9-N5 "A1–A3 accepted" | Nit | C-N18 |
| S9-N6 §13 extension row | Nit | C-N19 |
| S9-N7 B-T12 vs §9 tab-2 | Nit | C-N20 |
| S9-N8 three qa consumers omitted | Nit | C-M10 |
| S9-N9 stale pin twice over | Nit | C-M22 |

---

## Final counts

| | Blocker | Major | Nit | Total |
|---|---------|-------|-----|-------|
| Raw (per stage) | 2 (S7, S8) | 35 (S5: 5, S6: 1, S7: 15, S8: 4, S9: 14 minus S6-count reconciliation) → 35 | 38 → see note | 75 |
| **Consolidated** | **1** | **22** (1 tagged `[format]`) | **22** | **45** |

Raw per-stage counts as reported: Stage 5 — 0/5/5 · Stage 6 — 0/1/6 listed as "7 Nits" in its count line · Stage 7 — 1/15/13 · Stage 8 — 1/4/1 · Stage 9 — 0/14/9. Raw Blocker count is 2, but S8-1 explicitly subsumes S7-B1 as the same systemic defect, so they consolidate to one.

**Recommended order of business for the spec owner:** (1) C-B1 contract-delta register — everything else depends on which keys/targets/commands it admits; (2) C-M1/C-M3 orchestration idiom + command rows (they unblock C-M2, C-M5, C-M12); (3) the B1/B5 gate checklist (C-N22) absorbing C-M4, C-M11, C-M21; (4) the one-sentence rule alignments C-M13..C-M20; (5) citation/pin sweep C-M22 + Nits. Then draft the B1/B5 notes and run the Codex critique round.
