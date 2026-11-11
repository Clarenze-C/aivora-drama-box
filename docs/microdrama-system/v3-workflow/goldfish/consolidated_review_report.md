# Consolidated Review Report — Drama Box v3 MASTER SPEC (SPEC-v3.md)

- **Target:** /root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/SPEC-v3.md (v0.3, 857 lines)
- **Preset:** Uninterrupted full flow (Preset 1), headless — Stages 5, 6, 7, 8, 9 run sequentially, no checkpoints
- **Semantic split:** no literal "Detailed Implementation Plan" header; boundary taken at `## 15. Phases` (line 740) → **FeatureRange 1–739** (§ header–§14), **DetailedRange 740–857** (§15–19)
- **Goldfish context:** none supplied; reviewers read the files the document references (DECISIONS.md, REQUIREMENTS.md, SPEC-v3-v0.1.md, factmap.md, joey-digest.md, codex-spec-critique.md, codex-spec-recritique.md, ../T031-fix-round/pipeline-map.md) and grounded claims in the codebase under /root/AIVORA/drama-box
- **Reviewers (9 fresh agents):** egm-zoom-out ×2 (Stages 5, 8), egm-comprehension (Stage 6), egm-design + egm-structural + egm-style (Stage 7), egm-implementation-readiness + egm-codebase-details + egm-style (Stage 9)
- **Date:** 2026-11-11

**Stage artifacts:** `zoom_out_report.md` (S5) · `comprehension_report.md` (S6) · `critic_report.md` (S7) · `intermediate_zoom_out_report.md` (S8) · `implementation_readiness_report.md` (S9) — all in this directory.

**[format] convention:** findings tagged `[format]` only ask for a section the EGM document template expects (here: *Alternatives considered* and a consolidated *Risks & Limits* index). They are template-compliance asks, not defects in the design itself; the spec owner can triage them separately from the real findings.

---

## Severity summary

| Severity | Count | Notes |
|---|---|---|
| 🔴 Blocker | **1** | B1 |
| 🟡 Major | **27** | MA1–MA25 (real defects) + MF1–MF2 (`[format]`) |
| 🟢 Nit | **44** | N1–N44 |

---

## Executive summary

The reviewers converge on one picture: **a disciplined, genuinely master-level spec whose two Codex critique rounds are traceably applied** (all V3C-1..34 and V3R-1..12 resolutions verified against the critique texts; AT-1..32 each have exactly one accountable phase; the §19 maps resolve). The naive reader paraphrased the whole document without a Blocker, and the codebase reviewers confirmed nearly every factual claim about the existing system (GateType contents, identity-lock SQL, ReleaseSlotPlan, ai-route env inheritance, OFFLINE_MOCK refusal, wardrobe setting-ID mismatch, 124-frame math, 68 R-IDs).

Stage 9's verdict on the implementation plan: **not ready as a whole — phases A0 and A are startable now**; the defects bite at E/F/G spec time, at phase C's external edge, and at acceptance time.

Three systemic weaknesses carry most of the Major weight:

1. **Asymmetric reuse discipline (MA1–MA4).** The spec names exact existing components to reuse for story/review/render (LLMProvider, review/api.py rules, T031 primitives) but commissions its own new infrastructure — the LlmService queue, the GenerationUnit/UsageRecord records, the provider adapter surfaces — without one mention of the existing machinery that already provides most of those guarantees (core/jobs.py JobService, contracts/cost.py ProviderOperation + UsageReceipt + `charges`/`cost_allocations`, contracts/providers.py GenerationProvider/ASRProvider/MediaReviewProvider). Grep across all 857 lines returns zero hits for any of those symbols. Stage 8 showed this gap is actively generating structural redundancy (four parallel state vocabularies; a second costs UI).
2. **The §15 traceability machinery has drifted against itself (MA5–MA7, MA23–MA24).** The phase table's obligation column and the acceptance-ownership table disagree exactly where V3R-8 moved things (E/AT-25, F/AT-30, G); §17 promises an R-ID assignment that §15 does not contain; V3C-33 (rights/provenance/output inspection) has no accountable phase; "live analytics" is introduced only in an ownership cell.
3. **Unbounded external couplings and money-path ambiguity (MA8–MA12, MA15).** LIVE sign-off is monolithically coupled to the TODO task T032; the Nano Banana shared lock serializes the entire step-4 image workload with no sizing or ARISA fairness rule and a P0 too reduced to measure it; no production-throughput SLO is derived from 1/day + 3-day buffer; budget-cap enforcement does not say which ledger each cap binds (and whether allocated shared setup counts against episode caps); phase C's AT-28 silently requires ARISA-side lock adoption.

One Blocker: the header says the document is the final master with round 2 applied while the Status line says round 2 is still pending — fix before this becomes the binding master. Stage 8 re-audited the full file and confirmed **no prior-stage finding is wrong or overstated, and none is mitigated in-document**.

---

## 🔴 Blockers

### B1. Self-contradictory status header
**Scope:** header, lines 3–4. **Sources:** ST7-1 (Blocker), S7-4, C6-4; confirmed unchanged in Stage 8.
Line 3: "the final master after Codex round 2 … every V3R item is applied (§19)". Line 4: "Status: **for Goldfish review, then Codex re-critique (round 2 of 2)**". Both cannot be true; DECISIONS.md (line 147) declares the master final at v0.3, so the Status line is stale. A downstream phase-spec author cannot tell whether the text is authoritative. **Fix:** restate the status to match reality (e.g. "round-2 findings applied; Goldfish review + one verification pass remain") before the document becomes binding.

---

## 🟡 Majors — real defects

### MA1. LlmService/GenerationUnit duplicate the existing durable job machinery, unstated
**Scope:** §10.1, §4.4 (lines 309–316), §13, §15 rows A0/A. **Sources:** Z5-1, CB9-1, CB9-2; confirmed Z8.
The codebase already has a durable queue with the exact stated guarantees: `core/jobs.py` JobService (idempotent semantic-key enqueue, leased claims, bounded attempts, restart never regenerates successes, never-blind-requeue reconciliation), `contracts/cost.py:711–726` ProviderOperation (durable record of one external call: submit → status → reconcile, with request hash, client token, attempt, reservation, external ID, deadline), JobStatus mapping 1:1 to the spec's queued/running/succeeded/retryable/unknown/failed. §13 declares GenerationUnit "New" and §15 A0 commissions it greenfield; "a phase spec may not contradict this document" then forces the implementer to duplicate or contradict the master. LlmService's genuinely new semantics (deadlines, cancellation, process cleanup, quota admission, LLM lane in QueueName) are an extension, not a second system. **Fix:** one master-level paragraph binding LlmService/GenerationUnit persistence and recovery to the existing jobs table/ProviderOperation contract, adding only the new semantics.

### MA2. UsageRecord + new Costs page duplicate the existing receipt ledger
**Scope:** §11, §13, §15 row A. **Sources:** Z5-2, CB9-1; confirmed Z8 (worse than first reported).
`UsageReceipt` (contracts/cost.py:194–235; measured-only, estimates rejected) persisted in `charges`, with shared-cost allocation via `cost_allocations` (budget/reports.py:19–31, 65–75) already implements §11's "share of shared setup cost (allocated, never double-counted)", and budget/reports.py already renders per-episode receipt/category/amount/basis views. §15 A builds a second ledger and a second Costs page over it with no stated relationship — the exact double-accounting hazard §11 forbids. **Fix:** pin UsageRecord to the existing ledger as the single source, adding the new quota/exposure dimensions to it.

### MA3. New provider protocol names not mapped to existing protocols
**Scope:** §10.3, §4.4, §4.6. **Sources:** Z5-3; confirmed Z8; related CB9-1.
ImageGenProvider, SfxProvider, MusicProvider, ClipQaProvider are introduced as new surfaces with no sentence saying whether they implement the existing GenerationProvider/ASRProvider/MediaReviewProvider protocols (contracts/providers.py:188/340/369), whose submit/status/reconcile/fetch_output + reservation_id shape already covers them. Unstated, phase C/D specs will duplicate those semantics a second time. **Fix:** one sentence at §10.3.

### MA4. One paid-work lifecycle, four state vocabularies, no authority
**Scope:** §4.4 (lines 306–316), §2.2 (114–117), §15 rows A0/A/C. **Source:** Z8-1.
Pick-item states (QUEUED→…→ACCEPTED + REROLL_REQUESTED/FAILED_RETRYABLE/UNKNOWN/FAILED), generation-unit statuses (queued/running/…), common side states (WAITING_QUOTA/WAITING_PROVIDER/BLOCKED/CANCELLED) — three new vocabularies for one underlying work item, on top of the codebase's job outcome union, with no mapping table and no statement of which is authoritative (FAILED_RETRYABLE↔retryable↔RetryLater; UNKNOWN↔unknown↔NeedsReconciliation). Phase C will invent the cross-mappings the master never fixed; each unmapped pair is a future reconciliation bug in the money path. **Fix:** declare the generation unit (ideally the existing jobs table) the single persisted lifecycle; reduce pick states to vote/UI states; map side states onto the job outcome vocabulary.

### MA5. §15's two obligation ledgers disagree (V3R-8 regression)
**Scope:** §15, lines 742–768. **Sources:** Z8-2, IR9-1, ST9-M1.
Phase table "must define" column vs the acceptance-ownership table: E's row lists only AT-10 while E owns AT-25 (D's row still lists it — the exact change V3R-8 ordered); F's row omits AT-30 and the unnumbered live-evidence obligations it owns; G's row is the placeholder "V3C-23; LIVE AT" while G owns AT-14/17/32 + the all-gate e2e test + the partial rule. Since the master's own contract says each phase spec carries "the tests listed in §15", an E/F/G author receives an incomplete obligation set — the obligations-disappearing-between-phases failure V3R-8 was written to prevent, reproduced inside §15. **Fix:** make the ownership table the single ledger; mirror it exactly in the must-define column or reduce that column to a pointer.

### MA6. §17 promises an R-ID assignment that does not exist
**Scope:** §17 (781–784), §16 line 778, note at 767–768. **Sources:** IR9-2, ST9-M4.
"Coverage gaps named by the critique (R-1.1–R-12.13 table) are assigned in §15" — §15 assigns zero R-IDs (the spec's only concrete R-ID mention is R-12.1 at line 391). The partition of the 68 R-IDs is left to serial discovery by phase-spec authors, with gaps surfacing only at final acceptance — the failure mode the critique's coverage table documented. Trap: R-3.7 and R-12.13 exist only in REQUIREMENTS.md's preamble, so table-based enumeration undercounts. "R-1.1–R-12.13" is also an invented range-name. **Fix:** add a per-phase R-ID assignment to §15 (or restate §17 truthfully), and name the combined-matrix deliverable and its assembler.

### MA7. V3C-33 (rights/provenance + output inspection) has no accountable phase
**Scope:** §15 rows, §16, §13, §12.1–12.2. **Sources:** IR9-3, ST9-N7 (V3C-32 part).
The rights/provenance obligations (Joey prompt basis, detector weights, fonts, every generated asset; OPERATOR_ATTESTED voice rights; music/SFX rights) and the output-inspection contract appear in no phase's must-define column, no AT exercises them, and §13 lists no provenance/rights record entity — four phases (B/C/D/F) can build four incompatible record shapes or defer them. Secondary: V3C-32 (Mode A visibly disabled) is in B's content column but not its must-define column. **Fix:** assign the provenance/rights record schema and output-inspection contract to one accountable phase (C is natural; B/D/F named consumers); add V3C-32 to B's list.

### MA8. LIVE acceptance monolithically coupled to unbounded T032, no partial path
**Scope:** §16 LIVE (775–777), §15 row F, §18 O-4. **Sources:** Z8-3, IR9-4.
"Caption and disclosure delivery verified through T032-controlled publication" is a monolithic LIVE criterion; T032 is a TODO sibling task (its entire definition lives outside this spec — see MA16). Unlike Mode A, which gets an explicit partial-acceptance rule via G, nothing says LIVE may be granted per destination while T032-held destinations stay HELD. The whole program's live sign-off can stall indefinitely on work outside this plan's control. **Fix:** one sentence mirroring the Mode A rule — LIVE qualification is claimed per destination; T032-held destinations stay HELD and are excluded from the claim.

### MA9. Budget-cap enforcement ledger ambiguous; hard-stop semantics dropped
**Scope:** §11 (667–668), §12.3 (703–708), §4.4 line 396. **Source:** D7-2; corroborated Z8.
Which ledger does each cap bind? Does an allocated share of season-setup spend count against an episode's $10 cap (if yes, heavy setup can exhaust episode caps before the first render)? v0.1's "a hard stop at the cap" sentence was dropped without a per-level replacement (unit / episode / sub-budget / season). Phase A owns enforcement (AT-21) but cannot resolve this without a master rule; divergent phase interpretations rework the money path. **Fix:** define the enforcement ledger per level (reviewers suggest: episode caps bind per-episode-attributable spend; shared setup binds its own sub-budget; season cap binds the sum) and the hard-stop behavior at each level.

### MA10. Nano Banana shared lock serialization unsized
**Scope:** §10.2, §4.4 (317–332), §11 P0. **Source:** D7-3; confirmed Z8 (not overstated).
The shared exclusive lock serializes the entire step-4 image workload (plausibly hundreds to 1000+ paid images per season: candidates, re-rolls, derived views) across ARISA and Drama Box, one process at a time. Phase C gets only inode/lifetime/crash-release/queue-policy; no sizing, no wall-clock projection, no ARISA fairness rule; P0's step 4 (2 characters/2 locations) cannot measure full-season serialization. Most likely source of multi-day stalls in casting. **Fix:** mandate in phase C a step-4 image-count and wall-clock projection from the STORY-locked demand list, a fairness policy vs ARISA, and a P0 lock-throughput measurement (images/hour) made operator-visible before CAST LOCK generation starts.

### MA11. No production-throughput SLO derived from the release model
**Scope:** §9 line 587, §4.6, §4.5, §16. **Source:** D7-4; confirmed Z8.
1 episode/day + 3-day buffer + HELD recovery implies a required sustained rate (plus catch-up rate), but §16 only requires A40 throughput to be "measured". A factory averaging 0.8 episodes/day passes every stated acceptance item while structurally guaranteeing buffer decay and held premieres. Related: §6's split-shot resolution raises clip count against a fixed cap with nothing coupling the split decision to projected cost. **Fix:** state the SLO in the master (e.g. sustained ≥1.2–1.5 episodes/day at cost ≤ cap, defined catch-up rate); make LIVE acceptance "throughput ≥ required rate at cost ≤ cap"; have directing validation report projected clip count vs remaining budget on a split.

### MA12. Mixed-emotion capability unverified; no fallback decision point
**Scope:** §6 (514–527), §4.4 (369–371). **Source:** D7-5; confirmed Z8.
The operator's dominant-emotion decision rests on Pika H3 rendering an audible/visible expression change within one 5.17 s clip conditioned on a single-expression reference — unverified (the pilot observation covers only tag-vocalisation leakage). The round-2 alternative (splitting coverage at speech-safe boundaries so each shot carries one expression) was replaced wholesale and retained nowhere as a fallback; a late failure ripples into clip counts, cost and duration validation with no decision point. **Fix:** add an explicit P1 exit criterion for mixed-emotion shots (Thai-delivery/expression QA threshold) with the pre-agreed fallback recorded as a contingency.

### MA13. §4.4 overloaded; doc-wide contract misplaced; CAST LOCK split
**Scope:** §4.4 (277–397). **Source:** S7-2; compounded Z8.
~120 lines mixing ≥7 concerns. The generation-unit contract (V3C-9) is doc-wide (consumed by §10.1/§12.3, owned by A0) but normatively defined inside a step section; the CAST LOCK contract is split into two blocks ~90 lines apart (hash coverage at 293, migration/atomicity at 383). **Fix:** promote the generation-unit contract to §10 or §12; subdivide §4.4 with H4s (picks / packages / voice intake / lock / cost).

### MA14. Pinned v0.1 baseline unranked; supersessions untracked (live conflicts)
**Scope:** header (16–19 vs 28–31), §5, §4.1, §4.8, §4.9, §14. **Source:** S7-3; confirmed Z8.
The precedence ladder (operator → DECISIONS → REQUIREMENTS) omits the pinned baseline that the next paragraph declares binding, and supersession is not tracked per incorporation. Live conflicts: v0.1 §5 routes wardrobe continuity to "clip QA (vision on flags)" vs §4.6's "every shot, not just on flags" (not declared superseded); v0.1 §3.3's "up to 40 with extension" vs §4.1's "no hidden 40 ceiling". **Fix:** give the baseline an explicit rank in the ladder; list superseded v0.1 clauses per incorporated section.

### MA15. Phase C's AT-28 silently requires ARISA-side work
**Scope:** §15 row C, §10.2, AT-28. **Source:** IR9-5.
C depends only on "A, B", but AT-28's honest pass requires ARISA-side adoption of the shared lock — external coordination with no schedule, dependency entry or fallback. The C author must guess whether AT-28 passes with a simulated competing process or needs the real ARISA change inside C's window. **Fix:** add the ARISA-side adoption to C's prerequisites and split AT-28's proof (Drama-side lock in C; cross-system guarantee at live qualification).

### MA16. Undefined external task IDs used normatively (T031/T032/T045/H-2)
**Scope:** §1 line 53, §4.4, §4.6, §9, §15 rows D/F, §16, §18 O-4. **Sources:** C6-1; confirmed Z8; ST7-8 part.
T032 gates slot behavior, phase F live dependency and LIVE acceptance, yet the spec never says what it is (definitions live in the unlinked task ledger: T031 = live render/rights/cost qualification, IN_PROGRESS; T032 = controlled publication tests, TODO; T045 = live provider composition). "As hardened in T045 and the H-2 spec" is equally opaque. **Fix:** one-line glosses in the Facts block, or link the task ledger.

### MA17. ARISA (and SPECTRE) never identified
**Scope:** §3.2 line 163, §10.2 (629–637), §10.3. **Source:** C6-2; confirmed Z8.
The spec makes normative cross-system commitments ("every Nano Banana entry point in both ARISA and Drama Box", "coordinated with the ARISA owner session") and cites "the ARISA SFW pattern" without ever saying ARISA is the sibling project sharing this host and the Nano Banana quota. **Fix:** one identifying sentence at first use.

### MA18. "Binder"/"byte validator"/"acquisition-scoped" undefined
**Scope:** §4.4 step 6 (354–357), §4.6. **Source:** C6-3; confirmed Z8.
"The T031 binder" and "the binder's byte validator" are normative media-format acceptance criteria, but "binder" appears nowhere in the linked docs' surface — its only gloss is incidental wording inside critique finding V3C-14. **Fix:** inline definition ("the T031 render pipeline's upload-binding component, which seals and validates the PikaBindingContext") instead of reliance on the critique.

### MA19. Speaking-cap: "featured" vs "all speakers incl. off-screen"
**Scope:** §4.2 (226–233), §18 O-12. **Source:** ST7-2.
One cap, incompatible formulations ("per-episode FEATURED speaking-character cap … 5" vs "Phase B counts ALL distinct dialogue speakers, INCLUDING OFF-SCREEN speakers"; O-12 uses a third phrasing). "Featured" implies a subset and undercuts the V3R-4 rule it sits beside; phase B could implement either. **Fix:** delete "featured"; define once.

### MA20. SFX route rule drift: "cheapest eligible" vs "cheaper route"
**Scope:** §10.3 line 641 vs §7 line 532; also §18 O-9. **Sources:** ST7-3, S7-9.
§7's "cheapest ELIGIBLE route" (V3R-9: unknown capability/terms/price makes a route ineligible, never zero-priced; block if none) is compressed in §10.3 to "cheaper route", dropping the load-bearing eligibility/block semantics — a normative rule restated three times with drift. **Fix:** keep §7 the single normative home; reduce the others to pointers.

### MA21. "Step" used with three conflicting referents
**Scope:** §4.x headings, §2 table, §4.4 line 286. **Sources:** ST7-4, D7-9, S7-8.
§4.x headings number by tab (Step 8: Metadata; Step 9: Gate 2) while §2's DECISIONS column numbers 8/9 the other way; §4.4's "(in step 1, alongside principals)" means neither — it refers to pick-list item 1 (face lock). **Fix:** state the numbering convention once; rewrite the parenthetical ("during face-lock picks, alongside principals").

### MA22. Gate naming: LOCK / `SEASON_CONCEPT` / "Gate 1" never equated
**Scope:** §2 vs §4.1/§13/§15. **Sources:** ST9-M2, C6-9, ST7-5.
§2 names the first gate "LOCK (`SEASON_CONCEPT`; adds Revise)"; §4.1/§13/§15 use "Gate 1 Revise", undefined in this spec (v0.1 vocabulary; the doc half-adopts numbering — "Gate 2" is defined, "Gate 1" is not). Two names, one gate, one document; phase authors quoting "Gate 1 Revise" have no in-spec definition. **Fix:** a one-line gate-name mapping in §2.1.

### MA23. §16 ambiguities: possible duplicate acceptance items; trace-scope ambiguity
**Scope:** §16 (772–779). **Source:** ST9-M3.
(a) "Plus an end-to-end V3 composition test … and a 30-episode release simulation" — AT-29 already is the 30-release simulation and G owns the all-gate e2e test, so the bullet may restate or add a second, unowned simulation; (b) "all 68 R-IDs across the phases" is ambiguous between all-68-per-phase and union-equals-68; (c) "wildcard families" is critique vocabulary undefined in-doc. **Fix:** disambiguate all three.

### MA24. "live analytics" defined nowhere, owned by F
**Scope:** §15 ownership row F (line 764); §4.3. **Source:** ST9-M6.
F's ownership cell introduces "live analytics" — "analytics" appears nowhere in §1–§14 (the body says "viewership windows"). The cell is the only survivor of the analytics half of V3C-26, and §19 maps V3C-26 → §4.3 alone, which defines the decision screen but no analytics source. A phase-F author cannot quote a definition that does not exist. **Fix:** define the analytics source/contract (or fold it into the viewership-window language) and fix the V3C-26 map.

### MA25. LIVE "representative quality" names no judge, threshold, artifact or record
**Scope:** §16 LIVE bullet (775–777); G's "final live qualification" (765). **Source:** ST9-M7.
"Representative Thai speech/identity/lipsync/continuity quality" is unverifiable at gate time, unlike its measurable neighbors — same circularity as G's "final live qualification". **Fix:** tie to PILOT-REPORT.md quality flags (§11) with thresholds and records.

---

## 🟡 Majors — `[format]` (template-section asks)

### MF1. `[format]` Missing "Alternatives considered" section
**Scope:** whole FeatureRange; most acute §1, §2.2, §4.3, §4.4, §10.1. **Sources:** D7-1, S7-1.
The feature-spec standard mandates an alternatives evaluation with documented rejection reasons; the spec has none. Provider-level choices are well covered in prose, but the load-bearing single-path commitments (two-track state model, in-app LlmService queue, calendar-authority design, pinned Pika H3 route, stepper UI) carry only provenance tags. Tagged `[format]` because the fix is the template section itself and the rejection rationale already exists in DECISIONS.md and the critique trail — it needs surfacing, not new analysis. Note the underlying single-path concerns overlap MA1–MA3 (the in-app queue especially). **Fix:** a compact "Alternatives considered" table (decision → options → rejected because → pointer to DECISIONS/critique entry).

### MF2. `[format]` No consolidated Risks & Limits index
**Scope:** FeatureRange-wide; residual register at §18. **Source:** S7-10.
Risks and mitigations are pervasive and strong but never consolidated; §18 "Open items" is the nearest artifact and carries no risk framing. **Fix:** a short risks index (risk → where mitigated → residual owner).

---

## 🟢 Nits

| # | Finding | Sources |
|---|---|---|
| N1 | Three LLM adapters built in A0 while O-5 says subscription-only for the pilot; defer API/OpenAI-compatible adapters to the post-pilot decision | Z5-4 |
| N2 | Runbook detail at master altitude: §3.3 bot token paths/0600/rotation/chat-id/"test message delivered"; §4.4 zip naming example and V4 tag mappings — move to phase specs/runbook | Z5-5 |
| N3 | §14 reuse map points at the stale v0.1 §14 table (still lists ElevenLabs voice design, no SFX resellers/LlmService/A0/lock); extension screen can reuse analytics snapshots.py windows | Z5-6 |
| N4 | §18 O-register out of numeric order (O-10, O-12, O-11) — paste artifact; impairs completeness scanning (note: stage-9 style rated this Major; four other reviewers rated it Nit) | C6-11, S7-5, IR9-7, CB9-6, ST9-M5 |
| N5 | "guardian-owned"/"the full guards" (§13) undefined anywhere | C6-5, ST7-8 part |
| N6 | `ai-route` needs a one-line gloss at first use in §1 (definition lives only in the pinned baseline) | C6-6 |
| N7 | §6: "proof props", "headless sheet", and the provenance of the 9-image/≤3-audio reference budget are undefined | C6-7 |
| N8 | §4.3/§4.10: "planned-terminal"/"canon" and "the spoiler/reveal authority" undefined | C6-8 |
| N9 | §15 heading jargon: "phase spec → critique → GLM build → Codex review → full gate" assumes team-workflow knowledge; "full gate" occurs nowhere else; "GLM build" collides with GLM the adapter model class; column header "Phase spec must define" actually holds obligation IDs | C6-10, ST9-N3 |
| N10 | §15 row F "Gate 2 extensions" ambiguous (flow extensions vs episode extensions; the row also lists "extension flow") | C6-12 |
| N11 | Approved reschedule makes already-published CTAs factually wrong; published-date staleness not surfaced on the reschedule decision screen; no policy | D7-6 |
| N12 | PILOT-REPORT.md lacks planning wall-clock, quota-pause counts and window pacing — needed for the operator's pace decision | D7-7 |
| N13 | Operator-curated Botnoi V4 catalogue has no freshness field or re-check step; staleness surfaces later as blocked dispatch | D7-8 |
| N14 | No season-level success criteria in §1 (slots PUBLISHED_VERIFIED on schedule; cost within cap; quality bar) | D7-10 |
| N15 | Bare "(DOMAIN-RUNBOOK)" parenthetical (§3.1); v0.1 carried the full path | S7-6, ST7-8 part |
| N16 | Subjectless/orphaned sentences: §10.1 line 618 "Persisted before completion…" (also mis-attached as bullet continuation), §4.7 line 464 "Generated as a season library…" | S7-7, ST7-7 |
| N17 | Remaining undefined jargon beyond the Majors: "crowd walla" (302), "at both binding stages" (417) | ST7-8 leftovers |
| N18 | §3.2 "exactly one primary action, or none" cancels itself — the rule is "at most one" | ST7-9 |
| N19 | §2 tab 8/9 crosswalk sentence is a puzzle; suggested rewrite provided by reviewer | ST7-10 |
| N20 | §4.1 "no hidden 40 ceiling" imputes concealment → "no extension ceiling of 40" | ST7-11 |
| N21 | §6 "Over the budget" → "Over budget"; §4.9 "For episodes after LAUNCH" ambiguous → use §9's "Later episodes" | ST7-12 |
| N22 | Tier assignment for off-screen-only speakers implicit ("every on-screen person belongs to one tier" vs off-screen speaker counting) | ST7-13 |
| N23 | GENERATE_NEXT (an action) appears inside the pick state chain; "names like `<character_id>__<expression>.wav`" weakens a machine-parsed contract → "named exactly" | ST7-14 |
| N24 | Currency style drift: "US$10" then "× $10" on adjacent lines (§12.3) | ST7-15 |
| N25 | §8 is a two-sentence stub pointing at §4.6 — fold it in or give it content | ST7-16 |
| N26 | Register: contractions ("what's", "don't"); vague "The pilot may compare them."; "You/Auto" in the §2 table vs "the operator" in prose | ST7-17 |
| N27 | "Slower and cinematic" drops v0.1's measurable pacing anchor (average shot 4–5 s); §4.2 keeps only "a slower pacing rule" | ST7-18 |
| N28 | Dense single-sentence schema dumps (§4.3 pack content, §4.7 CTA, §12.1 Joey rights) — bullet them | ST7-19 |
| N29 | No declared normative-keyword convention (bold declaratives vs must/needs/never/cannot) — one header sentence would fix quoting force | ST7-20 |
| N30 | §4.4 "this is fixed" tense-ambiguous (reads as "is correct today"; means "V3 fixes this") | ST7-6 |
| N31 | §17 stub duplicates §16's trace bullet — fold into §16 | Z8-4 |
| N32 | §6 "or use a qualified composite": mechanism named once, owned by no phase, no contract — give it an owner or delete | Z8-5 |
| N33 | Baseline AT-16 "sends exactly once" is superseded by §3.3's honest-duplicate delivery but never annotated as superseded | IR9-6 |
| N34 | §19 maps V3C-19 → §4.7; the content (shared lock) is in §10.2 — one wrong pointer in an otherwise verified map | IR9-8 |
| N35 | O-8's fallback names no decision-maker or default; D's "T031 qualified" names no releasing artifact | IR9-9 |
| N36 | T031 symbols (PikaBindingContext, pika_transport, benchmark controller) exist only in the unmerged `feat/t031-fix3` worktree — D's dependency should also require the merge | CB9-3 |
| N37 | §15 must-define omissions: row C omits V3R-1/V3R-2 (trust boundary, normalisation); row B omits V3R-4 and the extension seam | CB9-4 |
| N38 | Phase A's amendment coordinator should locate the invalidation machinery it must subsume (targeted_invalidation, invalidated_shot_ids, Gate-2 Revise targeted repair) | CB9-5 |
| N39 | AT vs V3-AT shorthand inconsistent between §15 and §16/header | ST9-N1 |
| N40 | §18 "Default" column misdescribes resolved rows; resolved rows duplicate DECISIONS.md (divergence risk) → "Default / resolution" + pointer | ST9-N2 |
| N41 | §19's two tables use different headers for the same concept; V3R cells mix locations with operator decisions | ST9-N4 |
| N42 | §15 closing sentence passive, no actor/timing, refers to future R-ID matrices | ST9-N5 |
| N43 | Two senses of "partial" in adjacent §15 rows (release state vs Mode A label) | ST9-N6 |
| N44 | V3C-1/V3C-2 have no §15 phase cell; one sentence naming which findings need no phase owner would close it | ST9-N7 (V3C-32 part → MA7) |

---

## Traceability matrix (raw finding → consolidated ID)

| Raw | Consolidated | Raw | Consolidated | Raw | Consolidated |
|---|---|---|---|---|---|
| Z5-1 | MA1 | D7-6 | N11 | ST7-12 | N21 |
| Z5-2 | MA2 | D7-7 | N12 | ST7-13 | N22 |
| Z5-3 | MA3 | D7-8 | N13 | ST7-14 | N23 |
| Z5-4 | N1 | D7-9 | MA21 | ST7-15 | N24 |
| Z5-5 | N2 | D7-10 | N14 | ST7-16 | N25 |
| Z5-6 | N3 | S7-1 | MF1 | ST7-17 | N26 |
| C6-1 | MA16 | S7-2 | MA13 | ST7-18 | N27 |
| C6-2 | MA17 | S7-3 | MA14 | ST7-19 | N28 |
| C6-3 | MA18 | S7-4 | B1 | ST7-20 | N29 |
| C6-4 | B1 | S7-5 | N4 | Z8-1 | MA4 |
| C6-5 | N5 | S7-6 | N15 | Z8-2 | MA5 |
| C6-6 | N6 | S7-7 | N16 | Z8-3 | MA8 |
| C6-7 | N7 | S7-8 | MA21 | Z8-4 | N31 |
| C6-8 | N8 | S7-9 | MA20 | Z8-5 | N32 |
| C6-9 | MA22 | S7-10 | MF2 | IR9-1 | MA5 |
| C6-10 | N9 | ST7-1 | B1 | IR9-2 | MA6 |
| C6-11 | N4 | ST7-2 | MA19 | IR9-3 | MA7 |
| C6-12 | N10 | ST7-3 | MA20 | IR9-4 | MA8 |
| D7-1 | MF1 | ST7-4 | MA21 | IR9-5 | MA15 |
| D7-2 | MA9 | ST7-5 | MA22 | IR9-6 | N33 |
| D7-3 | MA10 | ST7-6 | N30 | IR9-7 | N4 |
| D7-4 | MA11 | ST7-7 | N16 | IR9-8 | N34 |
| D7-5 | MA12 | ST7-8 | split: T045/H-2→MA16; DOMAIN-RUNBOOK→N15; binder→MA18; guardian→N5; walla/binding-stages→N17 | IR9-9 | N35 |
| — | — | ST7-9 | N18 | CB9-1 | split: →MA1, MA2, MA3 |
| — | — | ST7-10 | N19 | CB9-2 | MA1 |
| — | — | ST7-11 | N20 | CB9-3 | N36 |
| — | — | — | — | CB9-4 | N37 |
| — | — | — | — | CB9-5 | N38 |
| — | — | — | — | CB9-6 | N4 |
| — | — | — | — | ST9-M1 | MA5 |
| — | — | — | — | ST9-M2 | MA22 |
| — | — | — | — | ST9-M3 | MA23 |
| — | — | — | — | ST9-M4 | MA6 |
| — | — | — | — | ST9-M5 | N4 |
| — | — | — | — | ST9-M6 | MA24 |
| — | — | — | — | ST9-M7 | MA25 |
| — | — | — | — | ST9-N1..N7 | N39, N40, N9, N41, N42, N43, N44 |

Key: Z5 = Stage 5 zoom-out (1–6) · C6 = Stage 6 comprehension (1–12) · D7/S7/ST7 = Stage 7 design/structural/style · Z8 = Stage 8 new findings (1–5; its verdict pass confirmed all prior findings, no mitigations) · IR9/CB9/ST9 = Stage 9 implementation-readiness / codebase-details / style.

---

## What verified clean (for the record)

- Both critique rounds traceably applied: §19's 34 + 12 rows spot-checked against the critique files; every mapped section contains the promised content; the §15 ownership table implements every V3R-8 correction and covers AT-1..32 with exactly one accountable phase each.
- The comprehension paraphrase succeeded across the whole document (self-containment is good; the Majors are gloss/definition gaps, not structural incomprehensibility).
- Factual accuracy of codebase claims: GateType contents, identity-lock SQL fields, ReleaseSlotPlan schedule requirement, ai-route env/MCP behavior, OFFLINE_MOCK refusal, missing scheduler in staging compose, wardrobe setting-ID mismatch, light_states field name, LLMProvider reuse, 124 frames @ 24 fps, 68 R-IDs, T031 binder/benchmark claims (in the worktree). Genuinely-new items confirmed absent: picks engine, stepper, outbox/bot, season critic, teaser dependency.
- Phase A0 and A are startable now: rows internally consistent, normative hooks sufficient (§10.1, §2.2, §4.4 contract); dependency chain and pilot gating coherent.

*Headless EGM review; no findings were resolved and the target document was not modified. Findings tagged `[format]` (MF1, MF2) are template-section asks only.*
