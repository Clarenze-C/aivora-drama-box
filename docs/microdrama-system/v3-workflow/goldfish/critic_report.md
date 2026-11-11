# Stage 7 — Critic Review

- **Target:** /root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/SPEC-v3.md (857 lines)
- **Scope:** FeatureRange, lines 1–739
- **Reviewers:** egm-design (feature-spec-standard), egm-structural (feature-spec-standard), egm-style (no standard)
- **Mode:** REVIEW, headless (uninterrupted preset)
- **Date:** 2026-11-11

---

## Reviewer 1 — egm-design (Architecture and Design Critic)

Design Critic audit of /root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/SPEC-v3.md, lines 1-739 (master spec, v0.3), against /root/.local/share/egm/403d888/resources/document_standards/feature-spec-standard.md.

Basis: full target range read; pinned baseline SPEC-v3-v0.1.md, DECISIONS.md, REQUIREMENTS.md, factmap.md, joey-digest.md, codex-spec-critique.md (V3C-1..34), codex-spec-recritique.md (V3R-1..12) and ../T031-fix-round/pipeline-map.md all read in full. Code grounding spot-checked: contracts/providers.py:152 (LLMProvider protocol exists — §4.2 reuse claim accurate), contracts/v2.py:733 (light_states is the real field — §5 correction accurate), contracts/enums.py:159-161 (GateType holds only SEASON_CONCEPT/EPISODE_FINAL — the §13 "+=" claims accurate). The spec's §14-anchored code claims (identity-lock SQL, resolver one-sheet rule, plan_master clip audio, exporter fades, scheduler absent from compose, OFFLINE_MOCK refusal) all match factmap/pipeline-map. Caveat: the sha256 of the pinned v0.1 baseline could not be re-verified in this read-only run (no execution); the file exists and was read.

Overall: this is a strong master spec. The two critique rounds are genuinely applied (I spot-checked the §19 map against the V3C/V3R texts; resolutions are faithful, including the operator overrides on V3R-3 and V3R-11). The findings below are residual gaps, mostly at the seams the critique process does not cover: the standard's alternatives mandate, cap-enforcement semantics, and throughput economics.

### FINDINGS

1. Severity: Major (strictly, a failure of the standard's mandatory Alternatives Rule — flagged for your weighing)
   Affected scope: whole FeatureRange; §1 lines 33-64.
   Finding: The feature-spec standard requires a mandatory evaluation of alternatives with documented rejection reasons; the spec has no such section. Provider-level choices are actually well covered — voice source (ElevenLabs/Chatterbox rejected for Botnoi, reason: V4 expressions are web-only, §4.4/§7), Botnoi API vs manual upload, SFX reseller comparison with eligibility rules (§7), LLM subscription-vs-API with a comparison pilot (§10.1), Facebook Reel-vs-video deferred to T032 (§9). But the load-bearing architecture commitments are asserted single-path with no acknowledged alternative anywhere in the document or its binding inputs: the two-track state model (§2.2), the in-app durable LlmService queue vs an external queue (§10.1), the calendar-authority design (§9, adopted verbatim from V3R-6), the pinned Pika H3 render route, Nano Banana Pro despite a known shared quota (only the lock is mitigated, §10.2), and the stepper-vs-board UI. Rejection rationale for several of these exists only implicitly in the linked critique files, which a fresh engineer reading this master would not synthesize.
   Recommendation: Add an "Alternatives considered" section (or a per-section block) consolidating: for each of the above, the viable alternative, and the specific reason it was rejected (complexity/cost/quota/scalability). Much of the content already exists in DECISIONS.md and the critique trail; it needs surfacing into the spec that phase specs treat as non-contradictable authority.

2. Severity: Major
   Affected scope: §11 lines 658-688 (esp. 667-668); §12.3 lines 703-708; §4.4 line 396.
   Finding: Budget-cap enforcement semantics are ambiguous where shared costs meet per-episode caps. §11 says each UsageRecord stores "its share of shared setup cost (allocated, never double-counted)" — a reporting rule. §12.3 makes step 4 and season setup sub-budgets inside the season cap and says "concurrency-safe enforcement: hold before effect", but never states which ledger each cap binds: does an allocated share of season-setup spend (cast images, YuE2 music library, SFX library) count against an episode's US$10 cap? If yes, heavy setup allocation can exhaust episode caps before the first render; if no, the per-episode cap binds only per-episode-attributable spend and the season cap is the sole real constraint. v0.1 §12.3 said "a hard stop at the cap"; that sentence was dropped in v0.3 without a replacement statement of hard-stop behavior per level (unit / episode / sub-budget / season). Phase A owns "enforcement" (AT-21) but cannot resolve this consistently without a master-level rule; divergent phase interpretations here cause rework of the money path.
   Recommendation: Fix in the master: define the enforcement ledger — which account each reservation charges, whether allocated shares count against episode caps (recommend: no; episode caps bind per-episode-attributable spend, shared setup binds its own sub-budget, season cap binds the sum), and the hard-stop behavior at each level.

3. Severity: Major
   Affected scope: §10.2 lines 627-637; §4.4 lines 317-332; §11 line 679 (P0).
   Finding: The Nano Banana shared exclusive lock serializes the entire step-4 image workload across ARISA and Drama Box, and the spec neither sizes that workload nor bounds its wall-clock. A representative 24-episode season's demand list (principals + supporting + extras looks, outfits per story day, appearance states, props per state, locations per light state plus coverage plates — each at 3 candidates plus re-rolls and derived sheet views) plausibly reaches hundreds to over a thousand paid images, all through one process at a time on a quota shared with another project. The queue policy is delegated to phase C with no required sizing, fairness rule versus ARISA, or throughput projection; and P0's step 4 is deliberately reduced (2 characters, 2 locations, 1 voice each), so the pilot cannot measure full-season serialization. This is the single most likely source of multi-day stalls in casting.
   Recommendation: Mandate in phase C: a step-4 image-count and wall-clock projection under the lock derived from the STORY-locked demand list (the forecast input already exists), a queue/fairness policy versus ARISA, and a P0 measurement of lock throughput (images/hour) so the full-season step-4 duration is a computed, operator-visible number before CAST LOCK generation starts.

4. Severity: Major
   Affected scope: §9 line 587 (buffer); §4.6 lines 434-436; §4.5 lines 404-407.
   Finding: No minimum sustained production rate is derived from the release model. The system must publish 1 episode/day, keep a 3-day produced-and-approved buffer, and recover from HELD slots — but the spec sets no required throughput (episodes/day steady-state, plus catch-up rate after failures) anywhere, and acceptance requires A40 render+QA throughput to be "measured", not bounded. A factory averaging 0.8 episodes/day passes every stated acceptance item while structurally guaranteeing buffer decay and held premieres. Related tension: the over-budget reference rule (§6) resolves blocked shots by splitting them, which raises clip count against a fixed episode cap and duration window; nothing couples the split decision to projected cost.
   Recommendation: State the derived SLO in the master (e.g., sustained >= 1.2-1.5 episodes/day at measured per-episode cost, and a defined catch-up rate), make the LIVE acceptance criterion "throughput >= required rate at cost <= cap" rather than "measured", and have directing-time validation report projected clip count against the episode's remaining budget when a split is chosen.

5. Severity: Major
   Affected scope: §6 lines 514-527; §4.4 lines 369-371.
   Finding: The operator's dominant-emotion decision (one CAST-locked voice variant per speaker per shot; per-line expression directed only in prompt text) rests on an unverified generation capability: that Pika H3 can render an audible/visible expression change within one 5.17 s clip while conditioned on a single-expression reference. The spec's pilot observation covers tag vocalisation leakage from the reference, not intra-shot emotional switching. Critically, the rejected alternative from round 2 — splitting or restructuring coverage at speech-safe boundaries so each shot carries one expression — is not retained anywhere as a documented fallback; §6 replaced it wholesale. If P1 quality fails on mixed-emotion shots, there is no decision point, and switching late ripples into clip counts, cost (finding 4) and duration validation.
   Recommendation: Add an explicit P1 exit criterion for mixed-emotion shots (Thai-delivery/expression QA threshold), with the pre-agreed fallback: directing splits at speech-safe boundaries per speaker (the V3R-3 original recommendation), recorded as the contingency so it is an operator decision point rather than a redesign.

6. Severity: Nit
   Affected scope: §9 lines 565-579; §12.6 line 716.
   Finding: An approved reschedule after publication makes already-published CTAs factually wrong ("next episode tomorrow 19:00"), and published media is immutable. The amendment-impact screen shows invalidated approvals and episodes, not published-date staleness, so the operator approves a reschedule without seeing the wrong-date exposure.
   Recommendation: Surface published-CTA staleness on the reschedule decision screen and fix a policy (accept staleness / prefer date-light CTA wording near schedule uncertainty / correction post).

7. Severity: Nit
   Affected scope: §11 lines 675-688.
   Finding: P0 runs representative full-season planning through a subscription lane that is single-slot, orchestration-first, and pauses on quota; its wall-clock is therefore unbounded across 5-hour windows. The pilot report lists cost, quota, throughput (render) and quality — but not planning wall-clock, window pacing and pause counts, which the operator needs to decide "the pace" (a stated pilot output).
   Recommendation: Add planning wall-clock, quota-pause counts and window-pacing to PILOT-REPORT.md's required contents.

8. Severity: Nit
   Affected scope: §4.4 lines 327-331.
   Finding: The operator-curated Botnoi V4 voice catalogue is seeded once with no freshness policy. Botnoi's catalogue and per-voice V4 availability can change; a stale catalogue suggests voices that lack V4, which surfaces only later as a blocked dispatch (missing required variant, §6).
   Recommendation: Add a catalogue freshness field (seeded date / source) and a re-check step before each new season or extension.

9. Severity: Nit
   Affected scope: §4.4 line 286.
   Finding: Required-pick item 4 reads "extras looks (EXTRA tier) and the face locks of SUPPORTING characters (in step 1, alongside principals)" — "step 1" here means pick-category 1 (face locks), but in a document whose §2 numbers workflow steps 1-10 it will be misread as Script Maker.
   Recommendation: Reword to "pick category 1 above".

10. Severity: Nit
    Affected scope: §1 lines 35-41.
    Finding: No product-level success criteria for a season (all slots PUBLISHED_VERIFIED on schedule or approved-rescheduled; cost within cap; quality thresholds). Process acceptance (V3-AT-1..32) is strong, and LIVE quality is "representative" but unquantified and unowned as a season-level bar.
    Recommendation: Add 2-3 season-level success criteria to §1 so the pilot and G-phase live qualification judge against a stated bar rather than judgment alone.

    Notes for completeness: V3R-4 tier integrity, V3R-1 upload quarantine, V3R-2 normalisation profile, V3R-10 isolation proof and the V3R-6 calendar model are all correctly and coherently applied in-range; I found no contradiction with DECISIONS.md in the FeatureRange, and the numbering crosswalk (§2), the EXTENDING-as-flag fix (§2.2) and the O-11 OPERATOR_ATTESTED basis (§4.4 step 6) match the binding decision record.

---

## Reviewer 2 — egm-structural (Document Structure Critic)

REVIEW (Document Audit) — egm-structural vs feature-spec-standard.md. Target: SPEC-v3.md, FeatureRange lines 1–739 (§ header–§14). All referenced inputs were read. One limitation: no execution tools, so the sha256 pin on the v0.1 baseline (line 29) could not be hash-verified; the file exists and every "as v0.1 §x" incorporation (§3.2, §4.1, §4.2, §4.3, §4.8, §4.9, §5, §14) resolves to a real section in it.

### FINDINGS (no Blockers)

1. Severity: Major — Affected scope: entire FeatureRange; most acute in §1, §2.2, §4.3, §4.4, §10.1.
   The Alternatives Rule is not structurally satisfied: there is no "Alternatives Considered" section anywhere in lines 1–739. The feature-spec-standard makes an evaluation of alternatives with documented rejection reasons mandatory, and its core principle requires a fresh reader to confirm design trade-offs from the spec itself. The substance exists but lives outside the document: operator option choices in DECISIONS.md (D2 ElevenLabs vs Chatterbox vs Botnoi; SFX resellers), and the two Codex critique files that proposed and rejected designs. Inside the FeatureRange there are only outcome statements plus provenance tags (V3C-x/V3R-x) — e.g., why the two-track state model, why logical demand IDs replace asset IDs, why a season-scoped CAST LOCK replaces the per-episode identity lock are each one sentence at most. Fix: a compact "Alternatives considered" table (decision → options → rejected because → pointer to the DECISIONS/critique entry), which the finding-map machinery in §19 already makes cheap to build.

2. Severity: Major — Affected scope: §4.4 (lines 277–397), specifically lines 309–316 and the two CAST LOCK blocks at lines 293 and 383–392.
   §4.4 is the structural dumping ground of the FeatureRange (~120 lines, roughly 4x the next-largest H3) and mixes at least seven concerns: staged picks, tier asset packages, the pick state machine, the voice intake pipeline (including a security trust boundary, V3R-1, and a normalisation profile, V3R-2), wardrobe fixes, the CAST LOCK migration, season-2 reuse, and cost. Two placement defects stand out. (a) The "Generation-unit contract (V3C-9), shared by every paid generation in v3" (lines 309–316) is a doc-wide contract — consumed by §10.1 (line 594 points back to "§4.4 contract") and §12.3, and owned by phase A0 per §15, i.e., it must be built before any step-4 work exists — yet it is normatively defined inside a step section. (b) The CAST LOCK contract is split into two blocks ~90 lines apart: hash coverage at line 293, the migration/atomicity contract at 383. Both harm discoverability at master altitude. Fix: promote the generation-unit contract to §10 or §12 and subdivide §4.4 with H4s (picks / packages / voice intake / lock / cost).

3. Severity: Major — Affected scope: header lines 16–19 vs 28–31; §5 (lines 493–497) and the other v0.1 incorporations (§4.1, §4.8, §4.9, §14).
   The binding-input precedence ladder (operator instruction → DECISIONS → REQUIREMENTS) omits the pinned v0.1 baseline, which the very next paragraph declares binding ("acceptance definitions remain binding except where explicitly superseded here"). The baseline therefore has no rank, and supersession is not tracked per incorporation. At least one live, unlisted conflict remains: v0.1 §5's table routes wardrobe continuity to "clip QA (vision on flags)" (SPEC-v3-v0.1.md line 401), while §4.6 line 429 mandates continuity "on every shot, not just on flags" — §5's correction list (light_states rename, setting ID, wardrobe history, appearance composition) does not declare this superseded. Secondary example: v0.1 §3.3's "range 20–30; up to 40 with extension" (v0.1 line 143) vs §4.1's "no hidden 40 ceiling". A fresh reader cannot resolve master-vs-baseline conflicts mechanically. Fix: add the pinned baseline to the ladder with an explicit rank, and list superseded v0.1 clauses per incorporated section.

4. Severity: Nit — Affected scope: lines 3–4 (header).
   Self-contradictory lifecycle metadata: the version line says "the final master after Codex round 2 ... every V3R item is applied", while the Status field two lines down still reads "for Goldfish review, then Codex re-critique (round 2 of 2)" — a stale pre-round-2 status. Round 2 exists (codex-spec-recritique.md) and DECISIONS.md line 147 declares the master final at v0.3. The bold span also breaks across a hard newline mid-sentence.

5. Severity: Nit — Affected scope: §18 rows at lines 800–801, target of FeatureRange forward references O-12 (line 227) and O-11 (line 366).
   The open-items table runs O-1..O-10, then O-12, then O-11 — out of numeric order (paste artifact). Both forward references resolve, but ID-based scanning is impaired; reorder the two "Resolved 11 Nov" rows.

6. Severity: Nit — Affected scope: line 128 (§3.1).
   Bare parenthetical "(DOMAIN-RUNBOOK)" with no link or path. The pinned v0.1 §3.1 carried the full relative path (deployment/staging/DOMAIN-RUNBOOK.md); this master dropped it, making the reference unresolvable from the document set.

7. Severity: Nit — Affected scope: line 618 (§10.1).
   "Persisted before completion is acknowledged, and deduplicated by a durable invocation ID." is indented as a continuation of the last bullet ("the session ID, outcome and timing."), so in rendered Markdown it attaches to that bullet rather than to the machine-result interface block it governs. Make it its own bullet or fold it into the block lead-in.

8. Severity: Nit — Affected scope: line 286 (§4.4, required human picks, item 4).
   "(in step 1, alongside principals)" — the numbered list items are introduced as "picks", never "steps", so "step 1" collides with the workflow's Step 1: Script Maker (§4.1). It presumably means pick item 1 (face lock). Rename to "in pick 1".

9. Severity: Nit — Affected scope: §7 (lines 532–541), §10.3 (line 641), §18 O-9 (line 798).
   The SFX route policy is stated three times with drift: §7 and O-9 define "cheapest eligible route" with preflight, ineligibility-on-unknown, and block-if-none; §10.3 compresses it to "cheaper route", silently dropping the eligibility/block semantics — a stale simplification of a normative rule inside the adapter catalogue. Keep §7 as the single normative home and reduce the others to pointers.

10. Severity: Nit — Affected scope: FeatureRange-wide (§1 hard rules, §4.4 trust boundary, §10.1 isolation, §10.4 fail-closed); residual register at §18.
    Risks and mitigations are pervasive and strong but never consolidated; the standard asks for explicit constraints/failure modes and the nearest artifact, §18 "Open items", sits outside the FeatureRange and carries no risk framing. A short risks index (risk → where mitigated → residual owner) would close the discoverability gap without moving content.

### VERIFIED CLEAN (structural checks that passed)

- Heading hierarchy: H1 → H2 (§1–§14) → H3 (§2.1–2.2, §3.1–3.3, §4.1–4.10, §10.1–10.4); no skipped levels; all section and subsection numbers sequential.
- Cross-reference integrity: every internal §-reference in lines 1–739 resolves (§12.1/12.2/12.3/12.6 correctly address the numbered list items in §12); all 8 file links resolve on disk; all 8 v0.1 incorporation references resolve in the pinned baseline.
- Finding maps: §19 V3C-1..34 and V3R-1..12 rows were each spot-checked against the two critique files — complete, and every mapped section actually contains the promised content (e.g., V3R-1 → §4.4 item 5, V3R-2 → §4.4 item 6, V3R-3 → §6, V3R-10 → §10.1, V3R-12 → §1).
- The header's "(68 R-IDs)" claim is accurate against REQUIREMENTS.md (68 distinct R-IDs; note REQUIREMENTS itself skips R-12.12 — a hygiene issue in that file, not the target).
- Tables (§2, §4.2 tiers, §4.4 packages, §11 pilots) are well-formed with consistent borders; no unclosed code fences; bullet style uniform.
- Internal consistency: gate count (5 content gates + LAUNCH) agrees across §1/§2/§13; the tab 8/9 numbering crosswalk is properly placed and explained at the point of use (§2, V3C-28); §4.x phase tags (B/B/B/C/D/D/E/F/F/F) agree with the §15 phase table; speaking-cap (5/episode, 2/shot) consistent across §4.2, §4.6 and O-12; buffer numbers agree across §9 and O-7.

Overall: the FeatureRange is structurally sound at the mechanical level (hierarchy, numbering, tables, links, traceability) and the critique-driven provenance discipline is genuinely good. The material defects are architectural rather than mechanical: no consolidated alternatives treatment (against the standard's mandatory rule), one overloaded step section carrying doc-wide contracts, and an unranked pinned baseline with untracked supersessions.

---

## Reviewer 3 — egm-style (Technical Writing Critic)

Style Goldfish audit of SPEC-v3.md, FeatureRange lines 1–739 (§1–§14). References consulted: DECISIONS.md, REQUIREMENTS.md, SPEC-v3-v0.1.md, codex-spec-critique.md, codex-spec-recritique.md (same directory).

OVERALL: The spec is dry, factual, and free of marketing fluff, filler, and subjective claims; its honest uncertainty language ("flagged as possibly duplicated", "Unknown ≠ PASS", "An OpenRouter equivalent is unverified") is exemplary. The defects run toward over-compression: a self-contradictory status header, two divergent wordings of one normative cap, terminology drift across sections, and undefined jargon.

### BLOCKER

1. Header, lines 3–4. "the final master after Codex round 2 … every V3R item is applied (§19)" contradicts "Status: for Goldfish review, then Codex re-critique (round 2 of 2)". Line 3 says round 2 happened and its findings are applied; the Status says the same round is still pending. DECISIONS.md confirms the spec is final at v0.3, so the Status line is stale. A downstream author cannot tell whether the text is authoritative. Fix the status before this becomes the binding master.

### MAJOR

2. §4.2, lines 226–233. One cap, two incompatible formulations: "the per-episode FEATURED speaking-character cap rises … to 5" vs "Phase B counts ALL distinct dialogue speakers, INCLUDING OFF-SCREEN speakers, toward five per episode" (O-12 in §18 uses a third phrasing). "Featured" implies a subset and undercuts the V3R-4 rule it sits beside; phase B could implement either. Delete "featured"; define the term once.
3. §10.3 line 641 vs §7 line 532. "cheaper route" (§10.3) drops the load-bearing qualifier from §7's "cheapest ELIGIBLE route" (V3R-9: unknown capability/terms/price makes a route ineligible, never zero-priced). The compressed form reads as pure price comparison and contradicts the rule's defining condition.
4. "Step" used with three conflicting referents: §4.x headings number by tab ("Step 8: Metadata", "Step 9: Gate 2") while §2's "Operator's step (DECISIONS)" column numbers 8/9 the other way; and §4.4 line 286 "(in step 1, alongside principals)" means neither — it refers to pick-list item 1 (face lock), which must be inferred from the adjacent list. State the numbering convention once and rewrite the parenthetical as "during face-lock picks, alongside principals".

### NIT (grouped)

5. §2/§13: gate exists as LOCK / `SEASON_CONCEPT` / "Gate 1" (and Gate 2 / `EPISODE_FINAL`) with the equivalence never stated in one place; §13's "Gate 1 Revise" never says Gate 1 is LOCK. Add a one-line mapping in §2.1.
6. §4.4 lines 374–376: "this is fixed" is tense-ambiguous (reads as "is correct today"; means "V3 fixes this").
7. Subjectless sentences: §10.1 line 618 "Persisted before completion is acknowledged…" (no subject) and §4.7 line 464 "Generated as a season library…" (orphaned participle detached from the Music bullet block).
8. Undefined jargon/external tags without gloss or link: "T045 and the H-2 spec" (line 53), bare "(DOMAIN-RUNBOOK)" (line 128), "crowd walla" (302), "the qualified production binder"/"the binder's byte validator" (355–357), "at both binding stages" (417), "the spoiler/reveal authority" (483), "guardian-owned"/"the full guards" (732–733). v0.1 carried full paths and the expanded guards wording.
9. §3.2 line 148: "exactly one primary action, or none" cancels itself — the rule is "at most one".
10. §2 lines 83–84: crosswalk sentence is a puzzle ("tabs 8 and 9 swap the operator's 8 and 9") and "nothing is renamed on them" is garbled. Suggested: "Tab 8 performs the operator's step 9 and tab 9 the operator's step 8 (D3: drafts before Gate 2). The UI keeps the operator's numbering; only execution order changes."
11. §4.1 line 195: "no hidden 40 ceiling" imputes concealment; write "no extension ceiling of 40".
12. §6 line 511 "Over the budget" → "Over budget"; §4.9 lines 478–479 "For episodes after LAUNCH" is ambiguous — use §9 item 4's "Later episodes".
13. §4.2 line 209 "Every on-screen person belongs to one tier" vs lines 231–232 counting off-screen speakers: tier assignment for off-screen-only speakers is implicit.
14. §4.4 line 306: GENERATE_NEXT is defined as an action but appears inside the state chain; line 340 "names like `<character_id>__<expression>.wav`" weakens a machine-parsed naming contract — make it "named exactly".
15. §12.3 lines 704–705: "US$10" then "× $10" — inconsistent currency style on adjacent lines.
16. §8 (lines 546–549) is a two-sentence stub whose content is a pointer to §4.6; fold it in or give it content.
17. Register: contractions "what's" (159), "don't" (672); vague "The pilot may compare them." (625); "You/Auto" in the §2 table vs "the operator" in prose.
18. §1 lines 35–36 "slower and cinematic" drops v0.1's measurable pacing anchor (average shot 4–5 s); §4.2 keeps only "a slower pacing rule". Carry the measurable form or cite v0.1 §4.2 explicitly.
19. Densest single-sentence schema dumps hurt scanability: lines 258–261 (pack content), 450–453 (CTA), 694–696 (Joey rights). Bullet them.
20. Normative voice: no declared keyword convention; mixes bold declaratives, "must" (line 432), "needs" (§1 rule 5), "never", "cannot". One header sentence declaring the convention would let phase authors quote the force unambiguously.
