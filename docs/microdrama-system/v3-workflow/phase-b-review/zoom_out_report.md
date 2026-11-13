# Stage 5 — Initial Zoom Out Report

**Target:** `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-B-spec.md` — "Phase B: Story (Script Maker → LOCK → bible → episode packs → STORY LOCK)", version 0.3, 12 Nov 2026 (full file, 562 lines).

**Date:** 2026-11-13

**Reviewer type used:** `egm:egm-zoom-out` (one fresh reviewer instance; completed).

**Verification basis (reviewer's own):** read the target in full plus SPEC-v3.md (v0.4.6), phase-A0-spec.md, phase-A-spec.md, A1-design-note.md, A2/A3 design-note section maps, b-factmap.md, DECISIONS.md, joey-digest.md, REQUIREMENTS.md; spot-checked code citations against live source (`script_maker.py:818` and `prompts.py:367` exact; `IdentityLockRequired` actually raises at `story/service.py:790`, the spec cites `:788`). The requirement trace checks out: master §15.2's R-1.1..R-3.6 all map in §13, and V3-AT-3/4/18/19 map to B-T7/B-T8/B-T5/B-T1; no territory of C/D/E/F/A2/A3/A5 is claimed.

---

## Findings (Blockers → Majors → Nits)

No Blocker findings were reported.

### 1. STORY LOCK / LOCK Revise targets do not fit A1's revision-note contract — Severity: 🟡 Major

* **Anchor:** §5.3 Revise row (line 345); §3.3 Revise row (line 234); §2.1 (lines 123–128).
* **Finding:** The Revise note targets B uses — `episode:<n>`, bible sections, the seam, tiers — do not fit the revision-note target contract phase A1 defines.
* **Evidence:** A1-design-note §4 defines `RevisionNoteTarget` as `{kind: EPISODE|CHARACTER|VOICE|REFERENCE|STORY_UNIT|NOTE, id: UUID}`, validated against the gate's binding units. B targets `episode:<n>` (no episode UUID exists before STORY LOCK — §2.1 defers `episode_id` binding to STORY LOCK), bible sections, the seam, and tiers (`character_key` is a string); there is also no PROPOSAL kind for LOCK Revise. Partially expressible via pack/seam/bible record_ids (UUIDs), but the spec never says so and section/tier granularity has no encoding.
* **Why it matters:** the A1 validator rejects every typed STORY LOCK note, or the builder invents the encoding ad hoc.
* **Recommended action:** specify the B-side binding-unit encoding, or widen A1's target shape before acceptance.

### 2. Re-plan jobs collide with the stated semantic key — Severity: 🟡 Major

* **Anchor:** §5.1 crash-and-replay clause "(semantic key per `(scope, n, LOCK authority, bible version)`)" (line 321) vs §5.2 step 3 (lines 328–329) and §5.5 (lines 375–384).
* **Finding:** Repair rounds and STORY LOCK Revise legitimately re-plan the same `(scope, n, LOCK authority, bible version)`; taken literally, the key makes the re-plan enqueue dedupe to a no-op.
* **Evidence:** A1's 0031 `logical_work_id` + `replaces_job_id` exists exactly for replacement outside `jobs.semantic_key` uniqueness, and B never says re-plans use it.
* **Recommended action:** state the re-plan keying (include the revision-note ID / repair round in the key; carry `replaces_job_id`).

### 3. Season-critic repair cascade unbounded; pre/post-gate asymmetry unexplained — Severity: 🟡 Major

* **Anchor:** §5.2 step 3 (lines 328–329); §5.5 (lines 375–384).
* **Finding:** The repair cascade has no breadth cap, and the spec leaves an unexplained asymmetry between pre-gate and post-gate handling of invalid dependents.
* **Evidence:** A continuity change near episode 3 can cascade into re-planning ~27 episodes × (Opus + Sonnet) × up to 2 rounds, with no breadth cap, wall-clock or quota guard (master §11/N12 makes planning wall-clock a measured pilot metric). Also: before the gate opens, invalid dependents regenerate silently (§5.2); after, §5.5 refuses silent regeneration ("Revise these too") — defensible (pre- vs post-approval) but unstated.
* **Recommended action:** cap or surface the cascade (e.g., max width → `BLOCKED` with projected call count); state the asymmetry rationale.

### 4. Master §4.2's "SeasonBibleV3 wrapping the existing SeasonBible and RichBible" is silently dropped — Severity: 🟡 Major

* **Anchor:** §1.2 (lines 52–56); §2 "Reused shapes" (lines 117–121, ledgers only).
* **Finding:** A binding clause of the master spec is neither honored nor recorded as a deviation.
* **Evidence:** Master §4.2 says `SeasonBibleV3` wraps the existing `SeasonBible` and `RichBible`; B defines a fresh record set and §1.2 reads as barring more than pure-function reuse. B's design is plausibly simpler (the Joey section order doesn't match the V1 bible shape) but the deviation is not recorded anywhere.
* **Recommended action:** one sentence — wrap the existing models, or record the deviation.

### 5. `story_v3.promote_profile` is under-specified in the lock-hash path — Severity: 🟡 Major

* **Anchor:** §4.2 (lines 257–275); §5.2 "Then:" sequence (lines 330–335); §7 job table (line 423).
* **Finding:** The promoted-profile LLM job lacks the failure, sequencing and storage specification every other B LLM job gets.
* **Evidence:** (a) No invalid-output/repair/failure policy, unlike every other LLM job (§3.2, §4.1, §5.1); (b) no acceptance coverage (B-T4 tests the promotion rules, not the job); (c) §5.2's sequence reads as synchronous but promotion enqueues async LLM jobs — does the season critic wait, and does a completed promoted profile bump the bible record version (and so the `StoryLockBindingV3` hash, which covers the bible's record ID/version/sha) while the gate is open? Where promoted `CharacterProfile`s persist is unspecified.
* **Recommended action:** specify failure behavior, sequencing vs the binding hash, and storage.

### 6. Dangling references in the normative record table — Severity: 🟢 Nit

* **Anchor:** §5.1 (line 306, "the bible's initial state for episode 1"); §2 `SeasonBibleV3` content (line 108); §2.1 `cta` (line 135).
* **Finding:** Two references in the record tables point at fields/owners that do not exist.
* **Evidence:** §5.1 feeds episode 1 "the bible's initial state" but the `SeasonBibleV3` content list has no initial-continuity-state field; `cta.template_id` references a template registry no phase owns (master §13 has none; E resolves CTA from the calendar).
* **Recommended action:** add the initial-state field; name the CTA template owner or drop `template_id`.

### 7. Stale header pins — Severity: 🟢 Nit

* **Anchor:** Header (lines 3–11): master pinned at v0.4.4 (line 7); "A2 and A3 design notes (being drafted)" (line 11); §2.2 cites "master v0.4.5 §6" (line 156).
* **Finding:** The traceability pins in the header are behind the live documents.
* **Evidence:** B's own v0.3 note cites v0.4.5 §6 and the live master is v0.4.6 (which folded the v0.1 clauses into §4.1/§4.2, the sections B cites most); both A2 and A3 design notes now exist. Low risk (v0.4.6 = no rule changes) but the pin is the traceability contract.
* **Recommended action:** re-pin to v0.4.6 and refresh the dependency list.

### 8. B-T2 duplicates A1's A-T5 guard coverage and encodes D/E/F's future state — Severity: 🟢 Nit

* **Anchor:** §2.3 consumer order (lines 189–197); §11 B-T2 (line 510).
* **Finding:** The consumer-enumeration test must be re-edited in each later phase.
* **Evidence:** B-T2 re-proves the `WORKFLOW_MISMATCH` refusal already guarded by A1's A-T5, and its module enumeration hard-codes which D/E/F modules refuse V3 until their phase ships.
* **Recommended action:** shrink to story-module consumers or make it a shared fixture.

### 9. Speculative `step_key` plumbing — Severity: 🟢 Nit

* **Anchor:** §1.3 (lines 61–62).
* **Finding:** B's calls are unmetered and reserve nothing; the `script_maker`/`bible`/`episodes` step keys only matter if a metered adapter ships after the O-5 decision.
* **Evidence:** §1.3 itself states pilot calls use the unmetered `llm.subscription` kind and phase B "makes no reservation and posts no charge."
* **Recommended action:** YAGNI but cheap — keep it a config constant; no admission logic in B.

### 10. Slot-targeted LOCK Revise with byte-identical carry — Severity: 🟢 Nit

* **Anchor:** §3.3 Revise row (line 234); B-T3 (line 511).
* **Finding:** Slot-level targeting exceeds master §4.1's "notes → a new proposal revision"; whole-round regeneration is nearly as cheap and would delete the carry/id-stability machinery.
* **Evidence:** §3.3 specifies that a targeted note regenerates only the targeted proposal slots while the others are carried byte-identical, with B-T3 asserting the byte-identical carry.
* **Recommended action:** operator-valuable, so confirm rather than delete — confirm the operator wants slot-level targeting.

---

## Verdict

The document's altitude is right: its scope matches master §15's Phase B row and §15.2's R-ID assignment exactly, nothing owned by C/D/E/F/A2/A3/A5 is claimed (forecasts, image volume, shots, cast binding, decision screen, calendar, published-canon source are all handed off with `NOT_AVAILABLE` placeholders), the level of abstraction is correct for a spec family where record content is normative in the phase spec, and nothing is missing at the top level. The residue is seam closure against A1 (Majors 1, 2, 5), an unbounded repair cascade (Major 3), one silent master deviation (Major 4), and small YAGNI/staleness items — all fixable in text before the B1/B5 notes.

**Counts:** 🔴 Blockers: 0 · 🟡 Majors: 5 · 🟢 Nits: 5
