# Stage 7 — Critic Report

**Target:** `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-B-spec.md` — "Phase B: Story (Script Maker → LOCK → bible → episode packs → STORY LOCK)", v0.3, 12 Nov 2026
**Active scope:** lines 1–480 (§0 Scope through §9 UI); lines 481–562 read for context only
**Date:** 2026-11-13
**Reviewer types used:** `egm:egm-design` (architecture and design critic, feature-spec standard applied), `egm:egm-structural` (document structure reviewer, feature-spec standard applied), `egm:egm-style` (technical writing reviewer, no standard). All three completed. Cross-checks performed against SPEC-v3.md (v0.4.6), phase-A0-spec.md (v0.4), phase-A-spec.md (v0.3), A1-design-note.md (v1.2), A2-design-note.md (v1.0), A3-design-note.md (v1.0), b-factmap.md, DECISIONS.md, REQUIREMENTS.md, joey-digest.md, and code under `/root/AIVORA/drama-box/microdrama/src/microdrama/`.

**Severity rubric:** 🔴 Blocker (must fix before build) / 🟡 Major (significant gap a builder could get wrong) / 🟢 Nit (polish). Findings are deduplicated across reviewers; the highest severity among duplicates is kept.

---

## 🔴 Blockers

### B-1. Step keys `script_maker`/`bible`/`episodes` do not exist in the enforced step-key vocabulary; the citation "(A2 §5.2)" is false as written — Severity: 🔴 Blocker

- **Anchor:** §1.3, lines 61–62
- **Finding:** The spec says: "When a metered LLM adapter ships (O-5), B's calls reserve under the step keys `script_maker`, `bible` and `episodes` (A2 §5.2). B builds the `step_key` plumbing." The enforced vocabulary admits none of these keys, and the cited section does not contain them.
- **Evidence:** A2-design-note.md §2.2 (migration 0033) fixes `budget_steps.step_key` by CHECK to exactly `('step_01'..'step_10', 'launch', 'episode_production')`, and `md_reservation_step_rules` requires a V3 reservation's `step_key` to reference an existing `budget_steps` row of the right account kind (setup-scope steps 1–4 for season-scope work). phase-A-spec.md §5.2 defines the keys as "master steps 1–10". A reservation with `step_key='script_maker'` would fail both the CHECK and the rule linkage. The citation "(A2 §5.2)" resolves to nothing usable: A2-design-note §5 has no subsection §5.2 (its step-key mapping is §2.2/OQ-2), and phase-A-spec §5.2 names none of these keys. Additionally, only three keys are named for five jobs: nothing says which key covers `story_v3.season_critic`, `story_v3.promote_profile`, or the translation call inside `plan_episode`. A builder wiring "the step_key plumbing" from this sentence implements keys the schema rejects, discovered only post-O-5, exactly when reservations start being enforced; if B1/B4 emit these keys into reservation-shaped records it is directly blocking.
- **Reviewers:** Design (Major), Structural (Major), Style (Blocker)
- **Action:** Name the keys exactly as admitted (`step_01` Script Maker, `step_02` bible, `step_03` episode builder, per the master step numbering A2 maps), assign every B job's `LlmStep` to one of them, and fix the citation to the specific document and section — or record an explicit A2 vocabulary-extension decision (a new migration amending the CHECK and `budget_steps`) as part of the O-5 adapter package.

---

## 🟡 Majors

### M-1. §3.2's "no real people, brands or celebrities named" check is attributed to a module that cannot perform it — Severity: 🟡 Major

- **Anchor:** §3.2, lines 218–220
- **Finding:** "The name check is deterministic, against the existing originality helpers (`S/research/originality.py`)" — that module cannot perform a real-person/brand/celebrity name check.
- **Evidence:** `S/research/originality.py` (read directly) is a resemblance screener against a supplied comparator corpus of similar works — persona-trait overlap and shared word n-grams — with "an unavailable comparator corpus yields UNKNOWN". It contains no real-person/brand/celebrity name list, and nothing in the codebase or b-factmap provides one. Master SPEC-v3 §1 rule 4 makes this a hard content rule and assigns real enforcement to phase C output inspection (§12.2), which the target itself acknowledges in the same sentence. A B builder reading §3.2 will wire originality.py, believe the check exists, and ship a no-op for exactly the class of risk the hard rule covers.
- **Reviewers:** Design
- **Action:** Either specify the actual B mechanism (a curated name/blocklist with a defined source and update path, plus what happens on a hit: repair round vs BLOCKED) or state plainly that B enforces this only via prompt constraints and deterministic originality-vs-corpus screening, with the people/brand check deferred to master §12.2 in C — and label the residual risk.

### M-2. The promote_profile → demand-list → open-gate sequence has no defined join; §5.2 and §7 give two incompatible descriptions of where promotion runs — Severity: 🟡 Major

- **Anchor:** §5.2 steps 4.1–4.5 (lines 330–335) vs §4.2 (lines 266–268) and §7 job table (line 423)
- **Finding:** §5.2 orders "1. tier promotion (§4.2); 2. the demand list (§4.3); 3. `StoryLockBindingV3`; 4. `open_gate(STORY_LOCK…)`; 5. `BIBLE → PLANNED`" as if one actor performs them consecutively. But §4.2 says a promoted extras role gets its profile "through one `LlmStep` per promoted role", and §7 defines `story_v3.promote_profile` as its own queued job (logical work ID `profile:<scope>:<character_key>`).
- **Evidence:** A job cannot synchronously run another job's LlmSteps. The demand list (CHARACTER demands carry tier; identity coverage) and `StoryLockBindingV3` (which hashes the tier table, §5.4) both depend on the promoted profiles existing. §1.7's invariant ("a gate is never open while that step's jobs are queued or running") makes the wait mandatory. The spec never says who waits for the promote_profile jobs, what the last one does, or how a promote_profile failure (BLOCKED) affects the season critic's completion. A builder reading §5.2 alone puts the LLM calls inside the season critic job, contradicting §7's job/queue/logical-work-ID table; each invention of the choreography lands differently.
- **Reviewers:** Design, Style
- **Action:** Spell out the orchestration explicitly — e.g., the season critic enqueues N `promote_profile` jobs and a named continuation/finalizer job that, only when all promotion jobs are terminal-successful, re-validates tiers, derives the demand list, writes `StoryLockBindingV3`, opens the gate and advances planning — and define the blocked-promotion path.

### M-3. Promoting an extras role creates a duplicate identity demand with no stated resolution — Severity: 🟡 Major

- **Anchor:** §4.2 (lines 260–268) vs §4.3 (lines 283–289) and §2.1 visible_cast (line 131)
- **Finding:** Packs reference visible cast as "character demand ID or extras-role demand ID"; promotion turns an ExtrasRole into a CharacterProfile "after all packs exist". But §4.3 derives the demand list "from the bible + all packs" with both a CHARACTER demand (keyed `character_key`, "identity coverage required" for PRINCIPAL/SUPPORTING) and an EXTRAS_ROLE demand (keyed `role_key`) — and nothing says derivation substitutes the CHARACTER demand for the role's existing EXTRAS_ROLE demand, reinterprets pack references, or keeps both. Since packs still reference the extras-role ID, a literal derivation lists both.
- **Evidence:** As quoted; phase C would then generate an extras look package (2–4 looks, no continuity, no identity) and a supporting-character face-lock package for the same on-screen person — two different generated identities for one role, defeating V3R-4 identity coverage and inflating the image volume.
- **Reviewers:** Design
- **Action:** State the rule — on promotion, the EXTRAS_ROLE demand is withdrawn (or merged with lineage) and all pack references resolve to the CHARACTER demand; add the case to B-T8's expectations.

### M-4. Three season-critic CRITICAL rules are undefined on an extension scope; one can permanently block an extension's STORY LOCK — Severity: 🟡 Major

- **Anchor:** §8 (lines 449–458) vs §6.2 (lines 405–411)
- **Finding:** §8 runs "the same builder" on an extension scope ("`plan_episode` for the new range, then the season critic, then STORY LOCK for the new packs only", with count authority being "an approved `SEASON` amendment"), but §6.2's CRITICAL rules are not reinterpreted for that scope.
- **Evidence:** Undefined on an extension: (a) "the episode count differs from the LOCK authority" — on an extension the pack set is the new range and the authority is the amendment, not the original LOCK; (b) "every pack satisfies §6.1 (a re-check against the final set)" — is the "final set" the extension's N packs or the season's 1..N?; (c) "a seam thread is resolved or closed in the finale" — for an extension whose declared purpose is to grow and often resolve seam threads, resolving one in the new finale is a legitimate creative endpoint, yet as written it is CRITICAL, and §5.2/§5.3 make an open CRITICAL permanently fail Approve. As written the rules either false-positive (blocking extension approval with no remedy) or force the builder to guess. B owns the extension builder and B-T11.
- **Reviewers:** Design
- **Action:** Add a short "extension-scope reinterpretation" list to §6.2 or §8: count authority = the approved SEASON amendment's count over the cumulative range; the §6.1 re-check set = the extension's packs; seam-closed-in-finale is CRITICAL only if the extension leaves zero open threads while the operator's extension decision reserved further growth (or scope that rule to non-extension seasons).

### M-5. `edit_tier` sits outside the A1 command/decision framework, and it overlaps the tier-targeted Revise flow with different effects — Severity: 🟡 Major

- **Anchor:** §4.2 (lines 269–275) vs §5.3 (line 345) and A1-design-note §4–§6
- **Finding:** Two facets of one defect. (a) `edit_tier` "closes the open STORY LOCK activation … re-runs promotion validation, demand derivation and the season critic's deterministic checks … opens a new activation", qualified only by "(human session)" — it appears nowhere in A1's command framework. (b) §5.3 defines a tier-targeted Revise with different effects: "the closure revalidation (§5.5) and the season critic run, and the gate reopens with a new binding". Same operation, two flows.
- **Evidence:** A1-design-note §5–§6 requires every command that mutates track/gate state to run through IdempotencyService with the preflight seam, the §6 lock order, an expected revision, replay identity and a command-table row; `edit_tier` appears in none of that. It is also the only non-decision path that closes and reopens an activation with a recomputed binding hash. Concurrent edit_tier vs a STORY LOCK decision, replay of a double-click, and stale-page tier edits are exactly the races A1 built the framework to kill — reintroduced at the gate that creates all episode rows. On facet (b): `edit_tier` runs only deterministic checks and reopens the activation itself; the Revise path also runs the (LLM) season critic and the §5.5 pack-closure revalidation, which for a tier-only note is undefined ("Regenerate the noted packs … from the earliest regenerated episode" — there is none). A builder must guess which flow the tab-3 "tier controls" invoke.
- **Reviewers:** Design (facet a), Style (facet b)
- **Action:** Give `edit_tier` a command-table row (idempotency key, expected track revision + binding hash, lock order, what the new activation's binding is, its event; note it in the B1/B5 design notes for critique), and state that `edit_tier` is the handler for a tier-targeted Revise (dropping one flow) or define when each applies — including what §5.5 means when no episode is noted.

### M-6. Pre-gate season-critic repair cascades have unbounded blast radius with no operator visibility, cap, or risk owner — Severity: 🟡 Major

- **Anchor:** §5.2 step 3 (lines 328–329)
- **Finding:** "A repair round re-plans the earliest named episode and every later episode whose continuity input changed (§5.5)." On a 24-episode season, a wardrobe-day finding at episode 3 re-plans episodes 3–24 — each with its own architect + translation LlmSteps and 2-regeneration budget — with no cap, no impact preview and no checkpoint.
- **Evidence:** Up to ~44+ LLM calls per round, at most two rounds, through a gateway with max_concurrent 1 and 5-hour quota windows. O-B5 caps critic passes, not cascade breadth. Contrast §5.5.4 (lines 381–384): post-gate invalid dependents "are not regenerated silently" but listed for an explicit "Revise these too" action, and master §12.6/A4 require an impact hash and cost-first Confirm for far smaller regenerations. The asymmetry is unexplained. The operator can watch days of unplanned quota consumption triggered by one deterministic finding; if quota runs out mid-cascade the season sits in BLOCKED with a half-regenerated pack set. No risk owner is named anywhere in scope.
- **Reviewers:** Design, Structural (in part)
- **Action:** Bound the cascade (e.g., a repair round regenerates the named episode plus directly invalidated successors up to a stated cap, iterating with the critic), or define an operator checkpoint when a round would re-plan more than K episodes, and state the expected blast radius on the season-critic wait state.

### M-7. No Risks & Limits section and no alternatives evaluation in the active scope — the applied feature-spec standard's two mandatory disciplines are unmet — Severity: 🟡 Major

- **Anchor:** §0–§9 document level (§1 lines 43–78 in particular)
- **Finding:** The standard requires an explicit "Risks & Limits" treatment (failure modes, mitigations) and a mandatory evaluation of alternatives with documented rejections. Within lines 1–480 there is no risks/limits section at all (master §18 "Risks and limits" is cited exactly once, line 247, for the Joey licence only), and alternatives appear only as parameter choices recorded out-of-scope in §12 (O-B1..O-B6) — master §17 "Alternatives considered" exists and is never cited.
- **Evidence:** Phase-local single-path decisions with no rejected alternative on record: (a) §4.1 line 244 — the entire `SeasonBibleV3` + `ExtensionSeamV3` (3–6 full Joey-density character profiles plus two ledgers) is produced by ONE LlmStep with no stated output-size bound, no split strategy (the promotion path at §4.2 already shows the per-unit pattern), and whole-bible regeneration as the only repair granularity when any render-required [TBD] fails; (b) §5.1 — strictly serial per-episode planning (inherent to the continuity chain, but the wall-clock/quota-pacing consequence for a 24–30 episode season under a 1-concurrent gateway is never stated as a risk even though master §11 makes planning wall-clock a pilot metric); (c) tier promotion only after all packs (§4.2); demand-list derivation only after the season critic (§4.3); bible reviewed only at STORY LOCK (§4.1 line 254); (d) the "versions = rounds" record modeling (§2). None is wrong; all are undocumented single paths with unrecorded rejected options.
- **Reviewers:** Design, Structural
- **Action:** Add a short risks table (bible output size/truncation → retry-then-BLOCKED semantics; serial planning wall-clock and quota pauses; repair-cascade cost; single-Sonnet-pass ZH translation quality that becomes the record of truth at LOCK) with a master §18 pointer, and one line of alternatives-rejected per major design choice (or an "Alternatives considered" subsection citing master §17 where it rules).

### M-8. §2.3's consumer-refusal guarantee cites modules outside A1's installed guard inventory, with no owner for the missing guards — Severity: 🟡 Major

- **Anchor:** §2.3 (lines 189–197)
- **Finding:** "A B test enumerates these modules and proves that each refuses V3 input until its phase registers a V3 path" — but the listed consumers include modules that sit outside A1's installed `require_workflow` guard inventory.
- **Evidence:** The listed consumers include `S/story/directing.py:101`, `S/references/v2_planning.py` and its binding/dispatch modules, `S/rendering/routing.py`, `S/qa/continuity_sources.py`, `S/editing/edl.py`, `S/editing/captions.py` and `S/community/grounding.py`. A1-design-note §7 (including its N1-14 boundary table) installs guards on research, review/intake, story/service, references/service, editing/service, qa/repairs, packaging, publishing, analytics, the scheduling selectors, replayed-job dispatch and a few boundary recorders — none of directing.py, the v2_planning/binding/dispatch modules, routing.py, continuity_sources.py, edl.py, captions.py, or community/grounding.py (grounding.py appears in no inventory anywhere). Most are presumably covered indirectly by the job-dispatch guard and selector filters, but "each refuses V3 input" as a module-level property is stronger than what A1 installed, and the spec does not say B1 adds the missing module guards. B-T2 is written as a proof of refusal; if the guards are only at dispatch seams the test proves less than claimed, and any directly-routed consumer (community grounding is the plausible one) is an unguarded V1 reader of story data for public replies.
- **Reviewers:** Design
- **Action:** In §2.3, name the enforcement point per listed consumer (existing A1 guard, dispatch guard, or a new `require_workflow` module guard added in B1), and list the modules whose guards B1 itself adds.

### M-9. Four "A2 §x" / "A3 §x" citations do not resolve; the shorthand is ambiguous between the design notes and the phase-A spec — Severity: 🟡 Major

- **Anchor:** lines 62, 344, 437, 448–450
- **Finding:** "(A2 §5.2)" (line 62), "(A2 §5.1: …)" (line 344), "(A3 §7.1)" (line 437), "(A2 §5.4)" (line 448/450) — A2-design-note.md §5 (Cap amendments) and A3-design-note.md §7 (Lock audit) have no subsections, so under the family convention (the A2/A3 notes themselves cite "(A1 §5)", "(A1 §2.4)") these read as design-note refs and dangle.
- **Evidence:** The content actually lives in phase-A-spec.md §5.1/§5.4/§7.1 (line 344's parenthetical matches phase-A §5.1's STORY LOCK mutex list near-verbatim; line 450 matches §5.4 "Episode-count changes and extensions are SEASON amendments"; line 437 matches §7.1 "The fence (A3)"). Meanwhile "A1 note §6" (line 235) uses the design note — one shorthand form for two documents. With A2-design-note.md and A3-design-note.md now real files, a reader resolving "A2 §5.2" lands on a nonexistent section of the wrong file. Blocker B-1 shows this is not hypothetical.
- **Reviewers:** Structural, Style
- **Action:** Adopt one convention (e.g. "phase A spec §5.2" vs "A2 note §2.2") and sweep the citations, or add the subsections to the notes.

### M-10. Stale, internally mixed version pins in the header (v0.4.4 vs v0.4.5 vs actual v0.4.6; "being drafted" for shipped A2/A3 notes) — Severity: 🟡 Major

- **Anchor:** header, lines 3, 7, 11
- **Finding:** Line 7 pins "Master: SPEC-v3.md v0.4.4" while line 3 itself relies on "master v0.4.5 §6" (the neutral-voice change that §2.2/line 156 depends on), and the actual master file is v0.4.6 (13 Nov), whose fold of the v0.1 clauses into §4.1/§4.2 touches the very sections the target's §2 record table (lines 107–108) cites. Line 11 says the A2 and A3 design notes are "being drafted"; both exist (v1.0, 12 Nov). Anyone verifying against the pin finds the §6 voice rule missing, and the "being drafted" line misdirects readers away from two documents the spec cites as authorities.
- **Evidence:** As quoted; spot-checks by two reviewers confirmed the target's content matches v0.4.6, so this is a metadata defect, not a content divergence.
- **Reviewers:** Structural (Major), Style (Major), Design (Nit)
- **Action:** Re-pin to v0.4.6, re-verify the §4.1/§4.2/§6 citations against the folded text, and update the dependency line to the A2/A3 notes' real versions.

### M-11. B's decision tables use target kinds that do not exist in the A1 decision contract, and Approve has no field to carry its target — Severity: 🟡 Major

- **Anchor:** §3.3 line 233 and §5.3 line 345 vs A1-design-note §4
- **Finding:** "**Approve** `target = {kind: proposal, id}`" (§3.3); Revise targets "`episode:<n>`, a bible section, the seam, or a tier" (§5.3). A1-design-note §4 defines `RevisionTargetKind` as exactly EPISODE, CHARACTER, VOICE, REFERENCE, STORY_UNIT, NOTE, and its validator ("season gates: REVISE <=> notes nonempty AND feedback empty") forces notes empty on Approve.
- **Evidence:** The LOCK handler must know which proposal was approved to compute "LOCK authority = the proposal's `content_sha256` + the event ID", but A1's `V3DecisionCommand` has no target field and its enum has no proposal/bible-section/seam/tier kinds. Implementing §3.3 as written requires either bypassing the A1 command contract or silently extending a frozen contract — neither is stated.
- **Reviewers:** Style
- **Action:** State explicitly that B extends `V3DecisionCommand`/`RevisionTargetKind` (a guardian-owned contract change, with the enum migration in B1), or re-map the tables onto A1's existing kinds.

### M-12. The psychology rule and its enforcement disagree on scope; "appears" is undefined — Severity: 🟡 Major

- **Anchor:** §2.1 line 136 vs §6.1 line 400
- **Finding:** §2.1: "`psychology[]` | for each principal or supporting character who appears: start state + end state"; §6.1: "missing psychology entry for an appearing principal | MAJOR".
- **Evidence:** A missing supporting-character psychology entry violates §2.1 but triggers no critic finding at any severity, so the rule is unenforceable as tabulated. "Appears" is also undefined — §4.2 makes off-screen speakers at least SUPPORTING, and it is unclear whether an off-screen speaker "appears" for psychology purposes.
- **Reviewers:** Style
- **Action:** Extend the §6.1 row to "an appearing principal or supporting character" (or state the narrower enforcement is deliberate), and define "appears" (in `visible_cast[]` vs speaking off-screen).

### M-13. §6.1's per-episode "known character" rule can forbid the promotion path §4.2 depends on — Severity: 🟡 Major

- **Anchor:** §6.1 line 394 vs §4.2 lines 261–266
- **Finding:** §6.1: "every line's speaker is a known character, with TH/EN/ZH text and an emotion | CRITICAL"; §4.2 promotion ("after all packs exist") triggers when a non-principal "has any line", and "a promoted extras role becomes a `CharacterProfile`".
- **Evidence:** The deterministic episode critic runs inside `plan_episode(n)` (§5.1 step 3), i.e. before promotion. If "known character" means a bible `CharacterProfile`, then any line given to an EXTRA-tier role is CRITICAL and gets repaired away — exactly the situation §4.2's "has any line" promotion rule exists to accommodate. Both readings are available; each breaks the other section.
- **Reviewers:** Style
- **Action:** Define "known character" at episode-critic time to include extras roles (with promotion converting speakers to profiles afterwards), or exempt not-yet-promoted speakers from this check until the season-level pass.

### M-14. The active-locations cap's unit of counting is undefined — Severity: 🟡 Major

- **Anchor:** §2.2 line 153 vs §4.3 line 287
- **Finding:** "Active locations per episode | **3** (O-B1)" and the LOCATION demand key is "`location_key` + `light_state`"; §6.1 makes "schema, V3 limits" CRITICAL, so the cap is enforced.
- **Evidence:** One location used under two light states yields either one or two demand rows. The spec never says whether the cap counts distinct `location_key`s or distinct (location, light-state) demands, and the two readings validate different packs.
- **Reviewers:** Style
- **Action:** One sentence, e.g. "distinct `location_key`s per episode, regardless of light state".

### M-15. §4.3 "after the season critic passes" contradicts §5.2's flow when CRITICAL findings remain — Severity: 🟡 Major

- **Anchor:** §4.3 line 279 vs §5.2 lines 337–338 and §5.3 line 352
- **Finding:** §4.3: demand list "Derived from the bible + all packs after the season critic passes"; §5.2: "If CRITICAL findings remain after repair, the gate still opens" (and steps 4.1–4.5 still run: promotion, demand list, binding, open gate); the STORY LOCK screen shows "the demand counts" (§5.3).
- **Evidence:** When CRITICALs remain, the screen must show demand counts, but §4.3's wording ("passes") withholds the demand list until findings clear — which would deadlock the Revise loop the open gate exists for.
- **Reviewers:** Style
- **Action:** Change to "after the season critic runs (regardless of remaining findings)".

---

## 🟢 Nits

### N-1. "(§12.2)" lacks the "master" qualifier and collides with the target's own §12 — Severity: 🟢 Nit

- **Anchor:** line 220 (§3.2)
- **Evidence:** "output inspection proper is phase C's (§12.2)" — the target's own §12 (Open questions) has no §12.2; the intended referent is master §12.2 "Output inspection (phase C accountable)". Sole bare cross-doc numeric ref in the target.
- **Reviewers:** Structural, Style
- **Action:** Write "master §12.2" (every other master reference in scope carries the qualifier).

### N-2. Present-tense forward reference to the B1 design note, which does not exist — Severity: 🟢 Nit

- **Anchor:** lines 163–164 (§2.3)
- **Evidence:** "the B1 design note extends this to every field…" — the note is unwritten; §10 itself says migration numbers "are allocated in the B1 note after re-auditing the tail". V3C-5's field-by-field mapping completeness is deferred to an unwritten artifact.
- **Reviewers:** Structural
- **Action:** Phrase it as an obligation ("the B1 note will extend this") and keep B-T2's coverage claim gated on it.

### N-3. Supersession attribution mismatch vs DECISIONS.md — Severity: 🟢 Nit

- **Anchor:** line 158 vs DECISIONS.md line 242
- **Evidence:** The target says "D2 revised again" "supersedes the per-(speaker, emotion) uploads of 'D2 refined'"; DECISIONS says it "supersedes 'D2 revised''s per-emotion variants and V3R-3's variant selection". Both labels exist as headings; the named superseded entry differs between documents.
- **Reviewers:** Structural
- **Action:** Align with DECISIONS' own sentence or correct DECISIONS.

### N-4. The "(versions = rounds)" convention breaks after a Reject — Severity: 🟢 Nit

- **Anchor:** §2 line 106 vs §3.3 line 235
- **Evidence:** §3.3: Reject leaves planning at PROPOSED and "the operator may submit a new intake or Revise later". A fresh intake after a Reject starts a semantically round-1 proposal set, but the `ProposalRoundV3` record already has versions 1..k, so the new round-1 content must land as version k+1.
- **Reviewers:** Design
- **Action:** State whether a fresh intake resets rounds, continues the version sequence, or mints a new record ID variant.

### N-5. §6.1 is episode-shaped but is cited as the bible critic's rule set — Severity: 🟢 Nit

- **Anchor:** §4.1 line 249 vs §6.1 line 392
- **Evidence:** §4.1 step 2 says "The deterministic bible critic (§6.1)", but §6.1's table is almost entirely episode-shaped (runtime band, recap, CTA, speakers per beat); only the schema/limits and [TBD] rows apply to the bible.
- **Reviewers:** Design
- **Action:** Add the bible-specific deterministic rules (Joey section order present, ledger validators, `tbd[]` shape) to §6.1, or point to where they live (§2/§4.1) so the B3 builder knows the bible critic's actual rule set.

### N-6. "Optionally, one LLM episode critic" is not a switch rule — Severity: 🟢 Nit

- **Anchor:** §5.1 line 313
- **Evidence:** O-B5's decision is "off by default, switchable"; "optionally" says neither whose option nor the default, and §7's table says only "(+ critic)".
- **Reviewers:** Style
- **Action:** "one LLM episode critic when the episode-critic switch is on (off by default; O-B5)".

### N-7. Retry-count phrasing drifts across sections — Severity: 🟢 Nit

- **Anchor:** §3.2 line 221 vs §4.1 line 249, §5.1 line 314, §5.2 line 328, B-T4
- **Evidence:** "a retry with a new `logical_call_id`, at most 2" (§3.2) vs "at most 2 regenerate rounds" (§4.1), "at most 2 regenerations" (§5.1), "at most 2 rounds" (§5.2), "after 2 rounds" (B-T4). "At most 2" attached to "a retry" reads as 2 retries (3 calls total); the rest imply initial + 2 repairs.
- **Reviewers:** Style
- **Action:** Standardise on "the initial attempt plus at most 2 repair rounds" everywhere.

### N-8. The `story_time` parenthetical is garbled — Severity: 🟢 Nit

- **Anchor:** §2.1 line 131
- **Evidence:** "`story_time` (story day, local time `HH:MM`, setting: reusing `StoryTime`, `S/contracts/v2.py:284`)" reads as if "reusing StoryTime" were the value of `setting`. The code (verified at contracts/v2.py:284–288) has fields story_day, local_time, setting, timezone; master §4.3 writes it cleanly.
- **Reviewers:** Style
- **Action:** "`story_time` (reusing `StoryTime`: story day, local time `HH:MM`, setting; `S/contracts/v2.py:284`)".

### N-9. "the tier revalidation passed" vs "promotion validation": two names for one check — Severity: 🟢 Nit

- **Anchor:** §5.3 line 344 vs §4.2 line 273
- **Evidence:** §5.3 Approve conditions include "the tier revalidation passed"; §4.2 calls the same check "promotion validation".
- **Reviewers:** Style
- **Action:** Pick one term and use it in both sections (see also M-5).

### N-10. Two parallel TBD mechanisms with no stated relationship — Severity: 🟢 Nit

- **Anchor:** §2 line 108 vs §4.1 line 250 / §6.1 line 397
- **Evidence:** The bible carries "`tbd[]` (field path + reason)" and the critics flag "a `[TBD]` in a render-required field". Must a literal `[TBD]` also appear in `tbd[]`? Does a `tbd[]` entry without literal text trigger the CRITICAL?
- **Reviewers:** Style
- **Action:** One linking sentence, e.g. "`tbd[]` is the structured record of every deferred field; the critic flags any render-required field whose content is `[TBD]`; the two must agree."

### N-11. The intake signature has no mode parameter, yet TREND is "refused" — Severity: 🟢 Nit

- **Anchor:** §3.1 lines 203–209
- **Evidence:** "`submit_v3_intake(idea_line, hints, requested_count)`" … "A `TREND` intake is refused with `MODE_UNAVAILABLE` before any write." If the command takes no mode there is nothing to refuse; the refusal implies the route accepts a mode.
- **Reviewers:** Style
- **Action:** Add "(the route accepts a mode field; only `TITLE` is admitted)".

### N-12. The season critic's logical work ID is defined by an undefined component — Severity: 🟢 Nit

- **Anchor:** §7 line 425
- **Evidence:** "`season-critic:<scope>:<binding inputs>`" — every other row uses a concrete component (`<round>`, `<lock authority>`, `<n>`, `<character_key>`); "binding inputs" names no field or hash.
- **Reviewers:** Style
- **Action:** Name it, e.g. the `StoryLockBindingV3` candidate hash for the round.

### N-13. The status sentence dangles — Severity: 🟢 Nit

- **Anchor:** line 5
- **Evidence:** "**Status: DRAFT for Codex critique (round 1),** after the Codex week resets (13 Nov 10:30Z)."
- **Reviewers:** Style
- **Action:** "Status: DRAFT; queued for Codex critique round 1 after the Codex week reset (13 Nov 10:30Z)."

---

## Verdict

Phase B spec v0.3 is a dense, largely verifiable document whose internal skeleton is sound: its code anchors, requirement ownership (V3-AT-3/4/18/19; R-1.1..R-3.6 match master §15 row for row), gate semantics, planning states, V1/V2 preservation rules, limits tables and traceability spine all check out against the fact map, the code and the A0/A/A1/A2/A3 family documents; all three reviewers agree no redesign is needed. The weaknesses concentrate where phase B meets its dependencies' exact vocabularies and contracts, and at the orchestration seams: one Blocker (step keys the A2 schema refuses, cited to a section that does not exist — raised independently by all three reviewers), two cross-document claims wrong as written (the A2 step-key citation, the originality-helper "name check"), undefined choreography at the season-critic finish (the promote_profile join, the extension-scope reinterpretation of CRITICAL rules), identity/command discipline gaps (promoted-extras duplicate demands, `edit_tier` outside the A1 command framework, Approve's missing target carrier), enforcement rules whose scope differs between the record tables and the critic tables (psychology, "known character", the location cap unit, "after the critic passes"), unbounded pre-gate repair cascades with no risk owner, and the feature-spec standard's two mandatory disciplines (risks/limits, alternatives) absent from the active scope. None of this is unfixable; almost all of it is one-paragraph clarification, corrected citations, or two named extensions to guardian-owned contracts — but it must be fixed before the B1/B5 design notes are drafted and before the Codex critique round, because each is a path by which a builder could implement something the family's own constraints reject.

**Counts after dedup:** 🔴 Blockers: **1** · 🟡 Majors: **15** · 🟢 Nits: **13** (total 29)
