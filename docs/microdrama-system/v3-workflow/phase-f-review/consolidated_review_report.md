# Consolidated Goldfish Review Report — phase-F-spec.md

**Target:** `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-F-spec.md` — "Phase F spec — release: metadata, Gate 2, teaser, calendar, slots, amendment integration (v0.1 DRAFT)", 567 lines, 13 Nov 2026.

**Run:** uninterrupted (Preset 1: consolidated report with all review rubrics), headless, 13 Nov 2026. GoldfishContext: none — reviewers still read every file the document references (SPEC-v3.md, DECISIONS.md, REQUIREMENTS.md, phase-A/A0/B/C specs, f-factmap.md, and the cited code/migrations under `microdrama/`).

**Artifact directory:** `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-f-review/` — stage reports: `zoom_out_report.md` (S5), `comprehension_report.md` (S6), `critic_report.md` (S7), `intermediate_zoom_out_report.md` (S8), `implementation_readiness_report.md` (S9); this file consolidates them.

**Semantic split (auto-discovered):** the document has no `## Detailed Implementation Plan` header; the work-breakdown portion begins at `## 13. Build packages` (line 497). FeatureRange = lines 1-496, DetailedRange = lines 497-567 (§13 packages, §14 acceptance, §15 open questions, §16 trace).

**Sibling-file note:** `phase-f-spec-final.md` exists in the same directory; verified to be a 2.1K completion note describing this v0.1 draft, not a later spec revision. This review covers `phase-F-spec.md` v0.1 DRAFT only.

**Severity policy:** where stages disagreed on severity, this report keeps the highest severity and notes the split; the spec owner may downgrade. Findings tagged **[format]** only ask for a section the EGM feature-spec template expects (Alternatives, Risks & Limits, Problem Statement) — triage them apart from real defects.

## Reviewer Status (10 reviewer instances, 5 stages)

| Stage | Reviewer(s) | Status | Raw counts |
| --- | --- | --- | --- |
| S5 Initial Zoom Out | `egm-zoom-out` | completed | 1 Blocker / 2 Major / 5 Nit |
| S6 Comprehension | `egm-comprehension` | completed (paraphrase: coherent, no Blocker) | 0 / 4 / 5 |
| S7 Critic | `egm-design`, `egm-structural`, `egm-style` | completed | 2 / 21 / 31 (after in-stage dedup) |
| S8 Intermediate Zoom Out | `egm-zoom-out` | completed | 0 / 1 / 2 (new findings only) |
| S9 Implementation Readiness | `egm-implementation-readiness`, `egm-codebase-details`, `egm-style` | completed; readiness verdict **ready-after-fixes** | 2 / 10 / 15 (after in-stage dedup) |

Raw findings across stages: **101**. Consolidated after cross-stage deduplication: **73** (4 Blocker / 33 Major / 36 Nit).

## Executive Summary

The Stage-8 altitude verdict frames everything: **the root architecture is sound** — admission-time row creation on stable slot identities under a two-part (content + calendar) authority, maximal reuse of the publishing service, A's decision transaction, C's pick pattern, derived-not-stored failure states. Every spot-checked code anchor held except one (the date-immutability claim). The defects cluster in four families:

1. **Two record-model impossibilities** (CON-B1, CON-B2): the reschedule recovery path cannot create a second `platform_posts` row for the same stable identity (UNIQUE walls + one-way cancel), and season-scoped posts (teaser, corrective) cannot satisfy three NOT NULL columns of the table the spec freezes as "reused unchanged". Stage 8 judges both fixable inside the architecture: in-place date UPDATE on un-submitted rows, and a synthetic carrier episode/package — but both must be decided in the spec text, not the build notes.
2. **The plan is not startable as written** (CON-B3, CON-B4): F5 is gated on an operator ruling (O-8) the plan itself says is still open, and the §13 gate column gives several packages checkpoints that cannot pass at their own step (F3 has none).
3. **The spec's verified-fact discipline broke in a few places** (CON-M1 false trigger claim; CON-M13 capability-record fields that don't exist; CON-M18 mis-attributed citations) — notable in a document whose method is line-anchored verification.
4. **Cross-reference and naming drift** (CON-M8…CON-M11, CON-M19…CON-M22 and the nit families): §14/§15 off-by-one, "(F-2)" mislabels, wrong test id, bare external §refs that resolve to wrong local targets — mechanical to fix, hazardous if they reach the builders.

The comprehension test passed with no Blockers: the document paraphrases coherently end to end.

## Prioritized Findings

### 🔴 Blockers (4)

#### CON-B1. Reschedule cancel + re-admission is structurally impossible against the schema and the spec's own invariants
* **Sources:** S7-K-1 (`egm-design`, Blocker); S5-zoom finding 1 (`egm-zoom-out`, Blocker); S8 finding 3 folded in (no acceptance test pins the row-mutation policy).
* **Scope:** §8.1 (386-394) vs §1.4 (57-64), §1.11, F-4 (137); cascades to §7.3 push, §7.4 MISSED recovery, §5 teaser recovery 2, §8.3 corrective posts.
* **Gap:** §8.1's apply cancels dispatched-not-published V3 posts and clears `platform_post_id` "for re-admission under the new revision" — but `cancel_slot` is one-way (`service.py:1045-1058`, no DELETE path exists), the cancelled row permanently occupies `dedupe_key UNIQUE` (`M/0005:42`) and the slot-identity UNIQUE (`M/0005:72`) on stable, never-deleted identities (§6.1), no CANCELLED→SCHEDULED transition exists (`retry_held_slot` lifts HELD only), re-creating would collide on INSERT, and rewriting `client_token` is trigger-forbidden (`M/0005:80`) — contradicting §1.4's "no V3 row is ever rescheduled, rewritten or re-created" and F-4's `platform_post_id` "set once". §8.1 also says cancel reaches "dispatched-not-published" rows while `cancel_slot` refuses once `external_id` is set (§8.5 itself limits cancellation to SCHEDULED). The fixed `corrective` slot name hits the same wall for a second corrective post.
* **Fix (Stage-8 resolution):** keep the root, delete the corollary — reschedule's apply transaction UPDATEs the date columns in place on V3 rows it can lock in SCHEDULED (dates are ordinary updatable columns, see CON-M1; published rows immutable; past-`begin` rows settle per §8.5). Rewrite §1.4's absolutist sentence and F-4's "set once" to match; make §8.1/§8.5 agree on reachable states; add the matching assertion to F-T3/F-T9 ("reschedule updates only date columns on un-submitted V3 rows; identity/package/token columns byte-identical; exactly one row per identity across two reschedules").

#### CON-B2. Season-scoped posts (teaser PROMO_CUT, N11 corrective) cannot exist in the reused `platform_posts` table
* **Sources:** S7-K-2 (`egm-design`, Blocker); S5-zoom finding 2 (`egm-zoom-out`, Major — severity split noted; consolidated at Blocker because F5/F7 cannot write the rows their designs require at all).
* **Scope:** §5 (240-255), §8.3 (406-412), §6.1 (270-276), F-4 (137), against §2's "Reused unchanged: `platform_posts` + the publishing service" (153-157).
* **Gap:** `platform_posts.episode_id` is NOT NULL REFERENCES episodes(id) (`M/0005:36`) — the teaser is season-scoped (episode_number 0, no episodes row); `release_package_id` NOT NULL (`:45`) — no teaser package concept exists (packages are per-episode, `slots.py:110-152`); `approval_event_id` NOT NULL (`:46`); and live submit requires the slot's package + full manifest binding (`service.py:368-455`), which `TEASER_FINAL` approves none of. §7.1's admission checks (steps 2-4) are phrased only for episodes — the teaser's content-authority path is unstated.
* **Fix (Stage-8 resolution):** an unmade carrier decision, not a wrong design — decide in the spec: (a) synthetic carrier episode + season-scoped teaser release package riding the ordinary path (recommended — zero new machinery), (b) parallel season-posts table (second state machine — violates §1.14), or (c) guarded V3 migration relaxing/typing the constraints (touches a shared V1/V2 table — needs its own §1.1 compatibility argument). Write the teaser's admission checks and add an acceptance test.

#### CON-B3. The plan gates F5 on an undecided operator ruling (O-F1 / O-8)
* **Sources:** S9-R-1 (`egm-implementation-readiness`, Blocker).
* **Scope:** §15 O-F1 (542); §0.7 (32); §1.9 (83-88); §13 F5 (509); §16 R-8.2 (559).
* **Gap:** "Operator decision required before F5" with only a recommendation recorded ("(d) now, (a) when T032 qualifies it"); SPEC-v3:1013 confirms O-8 is a real master-spec open item. F5 and the R-8.2 delivery route cannot be built first-attempt without guessing — a direct Zero-Decision Rule violation with the external gate named by the plan itself.
* **Fix:** obtain the operator's O-8 ruling before F work starts and write it into §1.9 as binding text (the recommendation is fully specified: YouTube caption tracks post-publish via `upload_captions`, TT/FB TH-only until qualified, flip per destination by config — but note CON-M14: the "by config" surface is undefined). Otherwise state F5 is conditionally blocked and F1-F4 may proceed.

#### CON-B4. Gate-to-package sequencing: several §13 checkpoints are unpassable at their own step
* **Sources:** S9-R-2 (`egm-implementation-readiness`, Blocker).
* **Scope:** §13 gate column (505-514) vs §14 (525-531).
* **Gap:** F3's only gate F-T5 proves F4 functionality (no independently passable gate); F2's gate F-T3 asserts reschedule behavior built in F7; F5's F-T6 "both approved paths work" needs reschedule (F7); F6's F-T8 scenarios recover via push/reschedule (F7) with the execution scope unstated; F-T2 needs seeded Gate 2 approvals (V3 Gate 2 is F4) without saying so. Violates "make check + pilot green at every gate".
* **Fix:** re-map the gate column — F3 gets its own drafts/thumbnails/staleness test (or F-T5 moves to F4 with F3 gated on make check + a named unit gate); the reschedule-dependent assertions move to F7/F-T9 or split into staged assertions; seeding requirements stated for F-T2/F-T3.

### 🟡 Major (33 — of which 3 tagged [format])

#### CON-M1. §1.4's "dates … trigger-immutable" premise is false; O-F2 must be re-run on the true constraints
* **Sources:** S7-K-3 (`egm-design`, Major); S5-zoom finding 4 (Nit); S9-R-19 (`egm-codebase-details`, Nit) — three stages, one fact.
* **Scope:** §1.4 (57-60); O-F2 (543).
* **Gap:** the immutability trigger (`M/0005:77-80`) pins identity columns only; `scheduled_utc`/`local_time`/`iana_zone` are ordinary updatable columns pinned by service-layer convention. The UNIQUE argument for admission-time creation survives; the immutability argument does not — and the viable alternative (create at LAUNCH, UPDATE dates on reschedule) is never evaluated (also the clean fix for CON-B1). The header's "every FM fact verified" promise broke here.
* **Fix:** correct the premise; add and reject (or adopt) the update-dates alternative on real grounds; owe §1.2's two-part authority one alternatives paragraph too.

#### CON-M2. No re-bind actor after reschedule; "LAUNCH binding current" unsatisfiable for extension identities
* **Sources:** S7-K-4 (`egm-design`).
* **Scope:** §1.12, §8.1 apply list, §7.1 check 3, §6.1, §8.4.
* **Gap:** bindings are written only by LAUNCH (never re-run) or Gate 2; already-approved episodes 6+ have no writer when a mid-season reschedule bumps the revision (§8.1's enumeration omits the re-bind write §6.1 implies) — after one reschedule every not-yet-admitted identity refuses admission with no recovery. §7.1(3) can never hold for extension episodes; no actor allocates extension identities.
* **Fix:** §8.1's apply re-binds all not-yet-admitted identities; §7.1(3) rewritten as "bound by the latest binding authority (LAUNCH or extension approval) and equal to the current revision"; §8.4 assigns extension-identity allocation to the extension approval handler.

#### CON-M3. The O-F10/§8.2 "cosmetic CTA rebuild + metadata-policy edit" default is unimplementable for unpublished slots
* **Sources:** S7-K-5 (`egm-design`); S9-R-15 corroborates (promote the viable default to binding).
* **Scope:** §8.2 (396-404); §7.1 check 4; O-F10 (551).
* **Gap:** metadata policy edits require an existing `platform_posts` row (`platform_post_id NOT NULL`, `M/0005:85`); pre-submit, live-binding equality refuses any drift from the sealed manifest, and only Gate 2 APPROVE can rebind a manifest — so the spec's "exception" (scoped Gate 2 re-approval) is the only actual path for sealed-but-unaired episodes.
* **Fix:** make the metadata-delta Gate 2 re-approval the stated default for unaired sealed episodes; restrict policy-edit/N11 to published slots; update O-F10.

#### CON-M4. Admission forks `schedule_release`'s invariant-dense row creation without an inventory
* **Sources:** S7-K-4's sibling S7-K-6 (`egm-design`).
* **Scope:** §7.1 (330-335) vs §1.1/§1.14.
* **Gap:** "schedule_release-equivalent fields" creates a second implementation of the most invariant-dense insert: episode FOR UPDATE lock, scope-DAG revalidation, RELEASE_APPROVED refusal, deterministic ids/tokens, `platform_post.scheduled` outbox events, episode state transition. Which of these admission replicates is unspecified; missing the transition or outbox event silently breaks W09, completion and bot consumers.
* **Fix:** enumerate which invariants admission replicates and which function owns them; name the fork and accept it, or expose a per-slot variant of `schedule_release`.

#### CON-M5. Operational risks of the new runtime pieces are unnamed
* **Sources:** S7-K-7 (`egm-design`). (Section-shape aspect separated into CON-M32 [format].)
* **Scope:** §7.1 (313-317), F-5, §7.2; document-level.
* **Gap:** four failure modes a fresh engineer cannot infer from §8.5: (a) `w13-release-admission` as a new single point on the publication critical path — no availability/catch-up/lateness statement; (b) F-5 REFUSED-row and alert growth — a persistently-held due slot re-refuses every 5 minutes unboundedly; (c) no mid-RELEASING abort/rollback story (A's cancel_season never referenced); (d) lead time vs predecessor verification latency — episode N's admission hostage to N−1's poll/reconcile finishing inside the window.
* **Fix:** add a short risks treatment covering the four with mitigations.

#### CON-M6. F-3 reinvents phase C's picks engine
* **Sources:** S8 finding 1 (`egm-zoom-out`, Major — new in Stage 8).
* **Scope:** F-3 (136), §3.2 (185-198), §1.8, §5 (240); vs phase-C-spec §2/§4 (`cast_pick_items`/`cast_pick_votes`, `candidate_kind` incl. ASSET).
* **Gap:** `thumbnail_candidates` + `thumbnail_votes` copy C's vote semantics verbatim ("the C-2 pattern") instead of extending C's domain-generic mechanism — permanent duplication (two append-only vote tables, two staleness computations, two UI pick patterns); the teaser becomes a third consumer.
* **Fix:** extend C's pick items/votes (pick_kind THUMBNAIL, episode/teaser scope, ASSET refs + `inspection_ref`), or record why parallel tables are cheaper. Decide in the spec, not the F1 note.

#### CON-M7. Teaser metering: SEASON account takes no reservations; `step_10` missing from §10
* **Sources:** S5-zoom finding 3 (`egm-zoom-out`, Major); S7-K-22 (`egm-style`, Major).
* **Scope:** §1.15 (118-122); §10 table (455-460).
* **Gap:** A §5.1 defines the SEASON account as "None; aggregate-only" for reservations and SPEC §12.3 puts the teaser in the season-setup sub-budget — charging teaser key art to SEASON is refused by design. Separately, §1.15's `step_10` never appears in §10's metering column (`teaser_cut` says "none").
* **Fix:** charge teaser key art to SEASON_SETUP (or define a reservation-bearing season-release step budget); restate §1.15; complete the §10 mapping.

#### CON-M8. Wrong test id: "the 30-episode simulation (F-T5)"
* **Sources:** S6-comprehension finding 1 (Major); S7-K-10 (structural + style, Major).
* **Scope:** line 380 (§7.5).
* **Gap:** F-T5 is the drafts/manifest/pick test (528); the 30-episode simulation is F-T8 (531, V3-AT-29), as §16 and line 451 correctly say.
* **Fix:** change F-T5 → F-T8 at line 380.

#### CON-M9. All eight "§14 O-Fn" references are off by one (O-F items live in §15)
* **Sources:** S7-K-8 (`egm-structural`, Major).
* **Scope:** lines 32, 85, 166, 179, 241, 281, 372, 404.
* **Gap:** §14 is "Acceptance"; the O-F table is §15 "Open questions" — numbering drifted when a section was inserted; the load-bearing O-8 decision pointer (§1.9) lands on the wrong table.
* **Fix:** re-point all eight sites to §15 (or renumber); add a section-drift lint before the Codex critique.

#### CON-M10. "(F-2)" mislabels; F1/F-1/F-T namespaces one glyph apart
* **Sources:** S7-K-9 (structural + style); S9-R-11 (`egm-style`); corroborated by S9 codebase finding re line 239.
* **Scope:** lines 51, 237/239 vs §2 table (132-135); §16 sigil-less refs (562, 564, 566-567); §15 "before F5" (542).
* **Gap:** `ReleaseCalendarV3` and `SeasonTeaserPlanV3` are labeled "(F-2)" but are records of the F-1 store (F-2 is `metadata_drafts`); build packages F1..F10 vs migrations F-1..F-8 vs tests F-T1..F-T13 — package F2 and migration F-2 are unrelated objects one hyphen apart, and §16/§15 cite packages without a namespace marker.
* **Fix:** correct both labels to F-1; qualify package refs at first use in-range ("package F2") or rename packages (FP1..FP10).

#### CON-M11. Bare external section references collide with the document's own numbering
* **Sources:** S7-K-11 (structural + style, Major); S6-comprehension finding 7 (Nit); S9-R-13 (Nit, the F10/F-T13 inheritance).
* **Scope:** line 481 ("§3.2's state set" — internal §3.2 is Thumbnails), line 451 ("§16.3" — no subsections), bare SPEC §4.8-4.10/§9.1-9.3/§9.2 items/§12.6/§9.4 at ~16 sites.
* **Gap:** 50/50 prefix convention; two refs actively resolve to wrong or nonexistent internal targets, and F-T13's "every state in §11" inherits the dangling pointer.
* **Fix:** apply "SPEC §n" uniformly to master-spec references; use the doc-letter convention for sibling specs.

#### CON-M12. Prerequisites not verifiable; phase-E contract undefined; existing `S/editing` seam unnamed
* **Sources:** S9-R-5 (readiness + codebase, merged); S6-comprehension finding 9 (Nit).
* **Scope:** §13 prerequisites (499-500); F5 (509); §5 (246-247); §0 (35).
* **Gap:** no phase-D-spec.md / phase-E-spec.md exists (verified by listing) — "B, C, E accepted" cannot be checked and E's export/caption-track schema (F5's input) is defined nowhere; meanwhile deterministic EDL/export/FFmpeg assembly already exists (`S/editing/{edl,export,ffmpeg}.py`, T015) as the obvious reuse seam the spec never names.
* **Fix:** cite the acceptance artifact per prerequisite; pin E's export/caption contract or state F5 is blocked-until-E-accepted; name `S/editing` as the `teaser_cut` reuse target.

#### CON-M13. O-F7's recommendation depends on capability-record fields that do not exist
* **Sources:** S9-R-6 (`egm-codebase-details`, Major); absorbs S7-K-47 (dual hashtag caps).
* **Scope:** §15 O-F7 (548); §3.1 (165-167).
* **Gap:** `CapabilityLimits` (`S/contracts/release.py:470-476`) carries no title-length or hashtag-count fields (YouTube's 100-char limit exists only in an EvidenceRef note string); the only structured caps are the platform-agnostic contract caps (title ≤200, hashtags ≤30) — looser than YouTube's documented limit, and the effective cap (min) is unstated.
* **Fix:** state that `CapabilityLimits` gains title/hashtag limit fields and which package adds them (or name the alternative source); resolve the 200-vs-100 conflict for the prefill lint.

#### CON-M14. The O-8 caption-route record has no storage home
* **Sources:** S9-R-4 (readiness, Major); S7-K-28 (design, Nit — escalated by the Zero-Decision Rule).
* **Scope:** §1.9 (88); §7.1 item 5 (327); F2; F-T4 (527); O-F1 "by config" (542).
* **Gap:** "recorded per destination and enforced at admission" — but F-1..F-8, `v3_release_documents` contract types, config keys and capability pins contain no such record; admission check 5 and F-T4's typed refusal depend on it.
* **Fix:** add the record to §2 (contract type or capability-pin column) and name it in F1/F2's Builds.

#### CON-M15. F-2's versions-table choice left open inside F1's build list; the "reuse" option is non-viable
* **Sources:** S9-R-3 (readiness, Major); S7-K-29 (design, Nit); the open-decision part of S7-K-37.
* **Scope:** §2 F-2 (135); §13 F1 (505).
* **Gap:** "`metadata_draft_versions` (or reuse the `metadata_versions` pattern — decided in the F1 note)" — a design choice deferred to the implementer; and `metadata_versions.platform_post_id` is NOT NULL, so the reuse option cannot work anyway.
* **Fix:** commit to `metadata_draft_versions` in the spec, with decisive columns stated.

#### CON-M16. "Explicitly closed out" is an undefined mechanism blocking COMPLETE
* **Sources:** S6-comprehension finding 4 (Major); S9-R-17 (Nit).
* **Scope:** §6.2 (302); §12 command table.
* **Gap:** no close-out command exists in §12 or phase A; with MISSED's only recovery being reschedule, the reader cannot tell how a permanently unairable episode is retired so the season reaches COMPLETE.
* **Fix:** add the close-out command (actor, prerequisites, effect) or state closure rides an existing operator decision.

#### CON-M17. CONTINUED/RESUMED extension calendar modes never defined
* **Sources:** S6-comprehension finding 2 (Major); S7-K-31 (design, Nit).
* **Scope:** `ReleaseCalendarV3` (147); §8.4 (418-421).
* **Gap:** the operator decision surface ("continued vs resumed") rests on a distinction defined nowhere in this file or any sibling; whether resumed ranges gap, re-date or re-map is unpinned.
* **Fix:** define both modes before F1/F8 build the air-instant map.

#### CON-M18. Binding-input citations mis-attributed to DECISIONS.md
* **Sources:** S6-comprehension finding 3 (Major); S7-K-24 (design + structural, Nit — split noted).
* **Scope:** header line 5.
* **Gap:** only Q6 is in DECISIONS.md (line 61); V3C-26, O-8, N35, N11 are anchored in SPEC-v3.md (§4.3:305, §15:1012-1013, §9.2:602). A reader verifying the binding decisions against the named file cannot find three of four.
* **Fix:** attribute each ID to the file that defines it, matching the precision already used at line 283.

#### CON-M19. §16 trace gaps: V3-AT-2 dead-ends; V3-AT-5, V3R-6, AR-4 untraced
* **Sources:** S9-R-12 (style, Major); S7-K-34 (structural, Nit).
* **Scope:** §4 heading (209) vs §16 (553-567).
* **Gap:** §4 claims V3-AT-2 for F but no trace row and no F-T annotation carries it (mis-trace or heading over-claim — the reader can't tell); V3-AT-5, V3R-6 and AR-4 also appear in body/headings without trace rows, and AR-4's home is never named.
* **Fix:** add the rows (or correct the §4 heading); name AR-4's provenance once.

#### CON-M20. §16 line 565: positional slash-zip carries five mappings
* **Sources:** S9-R-8 (`egm-style`, Major).
* **Scope:** line 565.
* **Gap:** "V3-AT-11 / 12 / 29 / 30 / 31 | F-T5 / F-T2, F-T6 / F-T8 / F-T10 / F-T10" — the reader must count and align five segments; "/" simultaneously means ID separator, mapping delimiter, pair ("F2/F6") and enumeration ("F1/F2/F4/F7/F8"). Mapping itself verified consistent; notation is at fault.
* **Fix:** one row per ID.

#### CON-M21. §13 Builds cells: telegraphic fragments, no section anchors, no Create/Modify markers, F1/F2 attribution overlap
* **Sources:** S9-R-7 (`egm-codebase-details`) + S9 style finding (`egm-style`) — merged.
* **Scope:** lines 503-514.
* **Gap:** "seal = drafts", "recovery" (one word for §5's two-path design), "staleness"; artifacts mixed with assertions; F1 builds all migrations F-1..F-8 yet F2 also lists "`publication_admissions`" and the "Calendar document" without Create/Modify/Reuse markers — which package creates which object is a guess.
* **Fix:** expand to verb phrases with §-anchors; add per-object markers; disambiguate F2's mentions as logic over F1's tables.

#### CON-M22. §14 Proves cells are not decidable pass conditions
* **Sources:** S9 style finding (`egm-style`, Major).
* **Scope:** lines 520-536.
* **Gap:** outcome nouns without stimulus or verb ("guards + catalog", "successors hold" with no injected failure, "below 2" with the unit dropped); only F-T2 has stimulus⇒response form.
* **Fix:** uniform stimulus ⇒ expected grammar with units; seed scenarios for F-T7/F-T9.

#### CON-M23. "Admission" named four ways for one transaction — S7-K-15 (`egm-style`); lines 50, 57, 103, 138, 312. Pick "release admission". §1.2's "one place" claim demands one name.

#### CON-M24. §7.4 table mixes units — S7-K-16 (`egm-style`); lines 360-368. HELD/MISSED are per-destination; PARTIAL is a cross-destination aggregate under a "per-destination" header. Split or retitle.

#### CON-M25. "The bound revision" ambiguous in the §3.3 staleness rule — S7-K-17 (`egm-style`); line 204. Pre-LAUNCH drafts reference nothing bound; state the referent (current calendar revision in force). This rule gates Gate 2 APPROVE.

#### CON-M26. Missing "that" makes a guarantee ambiguous — S7-K-18 (`egm-style`); line 425. "guarantees stale results …" vs "guarantees [that] … cannot release". Insert "that".

#### CON-M27. LAUNCH condition 5 is a non-condition as written — S7-K-19 (`egm-style`, Major) + S5-zoom finding 7 (Nit). Lines 294-297: condition, exception, cross-ref and rationale in one sentence with undefined "required route", "matrix decision", "per-run one"; "does not block LAUNCH" under "all must hold". Rewrite as a testable invariant + separate exception/rationale.

#### CON-M28. Admission horizon: "e.g. 10 min" then renamed "the horizon" — S7-K-20 (`egm-style`); lines 314-315 vs 353. A binding threshold left as an example, then referenced under a second undefined name. Give it a config name and default.

#### CON-M29. `approved_episodes` defined twice, differently — S7-K-21 (`egm-style`); line 139 (per content revision) vs 444 (per episode). The throughput SLO reads this counter; align.

#### CON-M30. "Slot" overloaded across three objects — S7-K-23 (`egm-style`); §7 uses bare "slot" for both the identity (pre-admission) and the publish slot (post-admission). Use "slot identity" vs "post/publish slot".

#### CON-M31. [format] No Alternatives Considered section — S7-K-12 (`egm-structural`, Major). The standard's Alternatives Rule is mandatory and the family has the vehicle (B §16, master §17). Four heaviest decisions are single-path in the whole file: the single `v3_release_documents` store, `publication_admissions` vs reusing `approval_events`, `w13` vs extending W09 (asserted, not argued), calendar-as-versioned-document. Partial documentation exists (§1.4 rationale; §15 option analyses framed as open questions) — which is why this is [format]+content rather than an unconditional Blocker; the structural reviewer notes it escalates to Blocker if the Alternatives Rule is applied to the letter.

#### CON-M32. [format] No Risks & Mitigations roll-up — S7-K-13 (`egm-structural`, Major). Failure-mode handling is real but distributed (§5, §7.3, §7.5, §8.5); the roll-up/map-table and a security note for the three new operator-facing surfaces (caption route, N11 corrective posts, extension screen) are the missing template section. The substantive risk content is separate: see CON-M5.

#### CON-M33. [format] No problem statement in §0 — S7-K-14 (`egm-structural`, Major). §0 enumerates deliverables but never states the business/user problem; sibling specs share the shape (family convention would drop this to Nit), but judged against the standard alone it is a required area.

### 🟢 Nit (36)

| ID | Finding | Sources | Scope |
| --- | --- | --- | --- |
| CON-N1 | Prefill lane left UNVERIFIED though binding input B §7.2 states it ("existing PRODUCTION queue") | S5-zoom-5 | §1.14, §10 (457) |
| CON-N2 | Gate 2 Revise channel vs A's timecoded-feedback rule for episode gates (`season_revision_notes` carries season_id) | S5-zoom-6 | §4(e) (228-229) |
| CON-N3 | F-6 + `w13b` precompute derivable counters; stored rolling aggregates duplicate state (AR-4 tension); justify or derive on read | S5-zoom-8, S8-2 | F-6 (139), §9, O-F6 |
| CON-N4 | Teaser repair deadline ignores composition latency (re-cut + gate + admission lead + verify before premiere) | S7-K-30 | §5 (258-261) |
| CON-N5 | §1.3's "(§1.5)" wrong pointer — date-pinning decision is §1.4 | S7-K-32 | line 56 |
| CON-N6 | `reschedule_calendar` used but never defined (defined: `propose_`/`confirm_reschedule`); §12 row shape implies Confirm==Apply unstated | S7-K-33 | 55, 263 vs 386, 492 |
| CON-N7 | §1 items pre-empt detail at drifting granularity (§1.13's 4 checks vs §7.1's 6; `buffer_days` defined 3×) | S7-K-35 | §1.12-13, §6.3, §9 |
| CON-N8 | §10 omits F's two new schedules (`w13`, `w13b`) | S7-K-36 | §10 vs 314, 443 |
| CON-N9 | Teaser key shape undecided in F-2/F-3 (nullable episode_id + sentinel? key column?) — teaser drafts/candidates unrepresentable as tabulated | S7-K-25, S9-R-18 | F-2, F-3 (135-136) |
| CON-N10 | §7.1 check 1's fence comparator undefined for a schedule (bound approval's revision vs current track revision) | S7-K-26 | §7.1 (319) |
| CON-N11 | Derived states not exhaustive: admitted-past-air unverified in RETRY_WAIT/NEEDS_RECONCILIATION is neither HELD/MISSED/PARTIAL | S7-K-27 | §7.4 |
| CON-N12 | F-2 cell packs schema + projection rule + UNIQUE + open decision + unexplained SUPERSEDED (~130 words) | S7-K-37 | §2 (135) |
| CON-N13 | Bare decision IDs with no resolvable pointer: O-7, O-3 (SPEC §19.1), N21, V3R-6 (nowhere), N35 (header only, unused) | S6-comp-5 | 5, 68, 195, 266 |
| CON-N14 | "CSF" vs "CSRF" for the same protection | S6-comp-6, S7-K-38 | 219 vs 390, 487 |
| CON-N15 | Single-use/unexplained terms: "weekend runbook", "the tail", EDL, "date-stamp", "guardian-owned bump", "closed out", agent/tool names (GLM, Codex, ai-route) | S7-K-45, S6-comp-8 | 3, 10, 37, 99, 124, 302, 516 |
| CON-N16 | Casing/enum drift: W09 vs w13; CONTINUED vs "continued"; `PROMO_CUT` backticked vs bare; "verified" lowercase; CAST LOCK vs cast-lock | S7-K-39 | multiple |
| CON-N17 | Unit style: "− 3 d" vs "− 3 days"; "incl."; unit-less "below 2" | S7-K-40, S9-R-25 | 23, 148, 241, 525, 533, 535, 544 |
| CON-N18 | Bold/emphasis conventions inconsistent (normative bold, process labels, row IDs, answer keywords; migration rule plain at 12, bolded at 501) | S7-K-41, S9-R-22 | §1, §13-15 |
| CON-N19 | Actor-hiding passives in binding rules ("money accounted", §1.13, §6.3, §8.5) — name the enforcing schedule/handler | S7-K-42 | 88, 108-109, 306, 435 |
| CON-N20 | Density sentences (~5 clauses): §1.13, §8.1, §8.4 | S7-K-43 | 103-111, 386-390, 422-423 |
| CON-N21 | "vote records only" parses as a noun phrase; "appends a vote; starts no work" is the clear form | S7-K-44 | 80, 136, 193 vs 491 |
| CON-N22 | "In flight" used for admission vs submit; MISSED predicate needs the enumerated post/job states | S7-K-46, S9-R-16 | 367, 437; §7.4 |
| CON-N23 | Episode-range naming wobble: "eps 1–5" / "episodes 1–5" / "first five consecutive"; meta-aside in a normative sentence | S7-K-48 | 67-68, 73, 149, 185-187, 291, 293, 306 |
| CON-N24 | Launch-tab refusal shorthand "(buffer, teaser, staleness)" doesn't match §6.2's five conditions | S7-K-49 | 478 |
| CON-N25 | HELD/MISSED/PARTIAL derivation inputs differ (§1.10: two; §7.4: three, + admissions) | S7-K-50 | 89-90 vs 362 |
| CON-N26 | Informal register in normative text: "cheap", "legal only while", "bumps" | S7-K-51 | 99, 173, 261, 403 |
| CON-N27 | Fence triad named twice differently (§0 vs §8.5 heading) | S7-K-52 | 27-28 vs 431 |
| CON-N28 | `launch:<content_revision>` key — which revision (season? release track?) undefined | S7-K-53 | 149 |
| CON-N29 | Cells hiding rules: §8.5 race-table cells, "when applicable" | S7-K-54 | 433-439, 147 |
| CON-N30 | Phase D's status unstated in prerequisites (supplier but not in the accepted list) | S9-R-20 | 499 |
| CON-N31 | `w13b`'s wall-clock daily instant exceeds today's registry shape (needs A6b calendar triggers; ordering after 19:00 release unstated) | S9-R-21 | F9 (513), §9 (443) |
| CON-N32 | F1-note deferrals (migration numbers, lane name, step keys): pin the lookup source so no interpretation is needed | S9-R-14 | 10-11, 117, 120-121, 457, 500-501 |
| CON-N33 | §15 Question column mixes grammar; O-F1's cell is a ~90-word memo with embedded options | S9-R-23 | 540-551 |
| CON-N34 | O-F9's revisit trigger undecidable; "P0" appears nowhere else | S9-R-24 | 550 |
| CON-N35 | "Transaction test" taxonomy introduced in the §14 heading but never marked (F-T12/F-T13 included?) | S9-R-26 | 520 |
| CON-N36 | §16 "Section" column mixes namespaces; "§7.1.5" reads as a nonexistent subsection; "Master §12.6" vs "SPEC §12.6" | S9-R-27 | 555-566 |

## Traceability Matrix (raw → consolidated)

Raw IDs: S5-zoom-1..8 = `zoom_out_report.md` findings in order; S6-comp-1..9 = `comprehension_report.md`; S7-K-1..54 = `critic_report.md`; S8-1..3 = `intermediate_zoom_out_report.md`; S9-R-1..27 = `implementation_readiness_report.md`.

| Raw | Consolidated | Raw | Consolidated | Raw | Consolidated |
| --- | --- | --- | --- | --- | --- |
| S5-zoom-1 | CON-B1 | S7-K-7 | CON-M5 | S7-K-38 | CON-N14 |
| S5-zoom-2 | CON-B2 | S7-K-8 | CON-M9 | S7-K-39 | CON-N16 |
| S5-zoom-3 | CON-M7 | S7-K-9 | CON-M10 | S7-K-40 | CON-N17 |
| S5-zoom-4 | CON-M1 | S7-K-10 | CON-M8 | S7-K-41 | CON-N18 |
| S5-zoom-5 | CON-N1 | S7-K-11 | CON-M11 | S7-K-42 | CON-N19 |
| S5-zoom-6 | CON-N2 | S7-K-12 | CON-M31 [format] | S7-K-43 | CON-N20 |
| S5-zoom-7 | CON-M27 | S7-K-13 | CON-M32 [format] | S7-K-44 | CON-N21 |
| S5-zoom-8 | CON-N3 | S7-K-14 | CON-M33 [format] | S7-K-45 | CON-N15 |
| S6-comp-1 | CON-M8 | S7-K-15 | CON-M23 | S7-K-46 | CON-N22 |
| S6-comp-2 | CON-M17 | S7-K-16 | CON-M24 | S7-K-47 | CON-M13 |
| S6-comp-3 | CON-M18 | S7-K-17 | CON-M25 | S7-K-48 | CON-N23 |
| S6-comp-4 | CON-M16 | S7-K-18 | CON-M26 | S7-K-49 | CON-N24 |
| S6-comp-5 | CON-N13 | S7-K-19 | CON-M27 | S7-K-50 | CON-N25 |
| S6-comp-6 | CON-N14 | S7-K-20 | CON-M28 | S7-K-51 | CON-N26 |
| S6-comp-7 | CON-M11 | S7-K-21 | CON-M29 | S7-K-52 | CON-N27 |
| S6-comp-8 | CON-N15 | S7-K-22 | CON-M7 | S7-K-53 | CON-N28 |
| S6-comp-9 | CON-M12 | S7-K-23 | CON-M30 | S7-K-54 | CON-N29 |
| S7-K-1 | CON-B1 | S7-K-24 | CON-M18 | S8-1 | CON-M6 |
| S7-K-2 | CON-B2 | S7-K-25 | CON-N9 | S8-2 | CON-N3 |
| S7-K-3 | CON-M1 | S7-K-26 | CON-N10 | S8-3 | CON-B1 (folded into fix) |
| S7-K-4 | CON-M2 | S7-K-27 | CON-N11 | S9-R-1 | CON-B3 |
| S7-K-5 | CON-M3 | S7-K-28 | CON-M14 | S9-R-2 | CON-B4 |
| S7-K-6 | CON-M4 | S7-K-29 | CON-M15 | S9-R-3 | CON-M15 |
| (cont.) | | S7-K-30 | CON-N4 | S9-R-4 | CON-M14 |
| S7-K-31 | CON-M17 | S7-K-31 | CON-M17 | S9-R-5 | CON-M12 |
| S7-K-32 | CON-N5 | S7-K-33 | CON-N6 | S9-R-6 | CON-M13 |
| S7-K-34 | CON-M19 | S7-K-35 | CON-N7 | S9-R-7 | CON-M21 |
| S7-K-36 | CON-N8 | S7-K-37 | CON-M15 + CON-N12 | S9-R-8 | CON-M20 |
| S9-R-9 | CON-M21 | S9-R-10 | CON-M22 | S9-R-11 | CON-M10 |
| S9-R-12 | CON-M19 | S9-R-13 | CON-M11 | S9-R-14 | CON-N32 (+ lane: CON-N1) |
| S9-R-15 | CON-M3 | S9-R-16 | CON-N22 | S9-R-17 | CON-M16 |
| S9-R-18 | CON-N9 | S9-R-19 | CON-M1 | S9-R-20 | CON-N30 |
| S9-R-21 | CON-N31 | S9-R-22 | CON-N18 | S9-R-23 | CON-N33 |
| S9-R-24 | CON-N34 | S9-R-25 | CON-N17 | S9-R-26 | CON-N35 |
| S9-R-27 | CON-N36 | | | | |

## Counts

* **Blocker: 4** (CON-B1…B4)
* **Major: 33** — 30 substantive + 3 **[format]** (CON-M31 Alternatives, CON-M32 Risks & Limits roll-up, CON-M33 Problem statement)
* **Nit: 36** (CON-N1…N36)

Raw findings reviewed: 101 (S5: 8, S6: 9, S7: 54, S8: 3, S9: 27). No reviewer failed or returned "not run"; the only stated limitation was the Stage-7 style reviewer not reading sibling docs (cross-doc terminology left to the structural lens, which did read them).

## Suggested Triage Order for the Spec Owner

1. CON-B1 + CON-M1 + CON-B2 (one editing pass over §1.4/§8.1/F-4/§2 with the Stage-8 resolutions — in-place date UPDATE; carrier decision for season-scoped posts; premise correction).
2. CON-B3 (obtain the O-8 ruling; write §1.9 binding; also resolves CON-M14's config surface) and CON-B4 (re-map the §13 gate column).
3. CON-M2/3/4 (admission/reschedule mechanics: re-bind actor, Gate-2-re-approval default, `schedule_release` inventory) — these three gate F2/F4/F7 correctness.
4. The mechanical reference family in one sweep: CON-M8, CON-M9, CON-M10, CON-M11, CON-M18, CON-M19, CON-M20, CON-M22.
5. CON-M5/6/7/12/13 (risk statements, picks-engine reuse, metering, E-contract, capability fields) before the F1/F2 notes are written.
6. The [format] trio (CON-M31/32/33) and the nits at the owner's discretion.
