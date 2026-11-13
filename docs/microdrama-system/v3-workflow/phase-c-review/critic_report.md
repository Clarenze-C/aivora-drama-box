# Stage 7 — Critic Review Report

- **Target**: /root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-C-spec.md (v0.1 DRAFT)
- **Range**: FeatureRange lines 1–490 (entire document; no separate implementation-plan section exists)
- **Reviewers**: egm:egm-design (feature-spec-standard), egm:egm-structural (feature-spec-standard), egm:egm-style (own rubric) — run in parallel, fresh contexts
- **Goldfish context**: none (reviewers read the files the document references under /root/AIVORA/drama-box/docs/microdrama-system/ and the codebase under /root/AIVORA/drama-box)
- **Date**: 2026-11-13
- **Headless uninterrupted run** (Preset 1) — findings only, no remediation applied.

---

## A. Design Critic (egm:egm-design)

Design-critique review of /root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-C-spec.md (lines 1-490, whole document), against /root/.local/share/egm/403d888/resources/document_standards/feature-spec-standard.md. Cross-checked against SPEC-v3.md v0.4.6, phase-A/B specs, A1/A2 design notes, c-factmap.md, DECISIONS.md, REQUIREMENTS.md, the migrations and source code cited, and the ARISA lock code/file. The document was fully readable; this is a complete review, not an incomplete one.

### BLOCKER

1. [Blocker] Scope: §1.2 (lines 52-54), §4 (lines 158-173), §11 (lines 397-409), §12 package C4 (line 421). There is no trigger for initial candidate generation. The whole engine assumes 2-3 generated candidates per item (§3's projection literally multiplies by "candidates 2-3"), and the operator decision (DECISIONS step 4: "Generate 2-3 variants of each character... picked SFW-picks style") requires it. But the only work-starting actions defined are `vote` (explicitly starts nothing), `reroll` ("enqueues exactly one item's generation job" — a re-queue of an item, one attempt at a time) and `generate_next` (dependents of an already-picked parent). Nothing generates the first candidates for a FACE or LOCATION_MASTER item, and §1.2's binding rule ("Votes start no work. Generate next and Re-roll are operator actions that enqueue jobs") forecloses automatic start at step-4 entry. Failure scenario: the operator approves the setup budget on the cast overview screen and then faces an empty picks grid whose only action, Re-roll, would have to be clicked 2-3 times per item across dozens of items to materialise the grid the forecast promised. The phase spec is the normative place (master §13) and the master shares the gap, so C must resolve it. Recommendation: define the step-4 entry action explicitly (e.g. a per-item or per-category "Generate candidates" operator action, or state that after setup-budget approval a bounded initial-generation batch per item is enqueued), with its metering under step_04 and its interaction with the fairness batch parameters.

### MAJOR

2. [Major] §8 (lines 309-325) vs §7 (lines 301-305) and master §4.4.5. CAST LOCK Approve conditions omit "every speaker has a registered neutral voice clip", yet the same transaction must write a CastLockV3 whose membership and `cast_lock_hash` include "voice WAV hashes" (line 117, lines 320-322). As written, a VOICE_NEUTRAL item counts as "picked" via a `CATALOG_ENTRY` vote that "selects no asset yet" (§7, line 272), and the missing/corrupt/unapproved neutral reference is only "a typed blocker D enforces" at dispatch — i.e. after the gate. So the spec permits a lock to Approve with no voice WAVs, at which point the lock hash cannot be computed (or silently omits them), violating master §4.4.5's membership ("every pick and derived asset, and every voice WAV") and stranding every episode at D's dispatch blocker. A charitable reading ("every required item's generation work is terminal-successful" includes the voice intake job) is never stated. Recommendation: add the explicit Approve condition — every VOICE demand has a `voice_uploads` row in REGISTERED state with approved rights — and state that the VOICE item's job lifecycle is the intake job.

3. [Major] §3 (lines 141-143), §4 (lines 161-183), §8 (line 313). The rule "every required item is picked" collides with master §4.4.1's derived-asset model. §3 marks SHEET_VIEW and EXPRESSION items `required = true`, and §4 defines "picked" as "a latest vote exists" plus V3-AT-5's "lock refused until every required item is picked". But master §4.4.1 lists the required human picks as faces, outfits, appearance states, extras looks, props, location masters and base voice; sheet views, expression sets, coverage plates and the libraries are "derived assets... accepted, or re-rolled, inside the final CAST review" (master §19.2 explicitly superseded auto-accept with review-accept). Either C demands a human vote on every derived view — hundreds of votes per season, diverging from the master's operator model — or "picked" for derived kinds means the CAST-review acceptance, which is never defined. Recommendation: publish a per-`pick_kind` table stating which kinds require an explicit human vote before lock and which are auto-generated then bulk-accepted at the CAST review, and separate the `required` flag's two meanings (required-for-lock vs required-human-pick). C-T3's wording should match.

4. [Major] §2 (lines 96-108) and §8 (lines 326-328). The 12-value `pick_kind` vocabulary has no stated mapping onto the storage it must live in. Candidates are `reference_versions` rows, whose `ref_kind` CHECK allows only FACE/VOICE/WARDROBE/LOCATION/STYLE (0002:158); `identity_lock_assets.asset_kind` has the same five-value CHECK (0002:275) and requires a `reference_version_id` for every member. The spec asserts "pick kinds map to the five asset_kinds" and gives no table. PROP, EXTRAS_LOOK, SHEET_VIEW, EXPRESSION, MUSIC_LIB and SFX_LIB have no natural kind; a wrong ad-hoc mapping (e.g. props under WARDROBE or STYLE) would poison every kind-keyed reader (V1's `cast_package_assets`, D's `cast_binding`, the QA anchor logic) and make the lock membership semantically wrong. No C-1..C-8 migration extends either CHECK, so either the mapping or a version-aware CHECK extension must be planned. Recommendation: publish the mapping (which kinds land in which ref_kind, with ref_key conventions) or add the CHECK extension to the migration list, before C1 is critiqued.

5. [Major] §4 (lines 167-170) and §2 C-1 (line 98). "New versions append" for re-rolls depends on per-attempt input variation that is never specified. `reference_versions` has `UNIQUE (season_id, cache_key)` where cache_key is the hash of the full request including the seed (verified: `build_image_request` carries `spec.seed`, `/root/AIVORA/drama-box/microdrama/src/microdrama/references/generation.py:415-434`; `_insert_reference` derives `anchor_cache_key` from the spec, `service.py:890-916`). A re-roll whose request is byte-identical to a previous attempt collides on the unique constraint; the initial 2-3 candidates per item have the same problem. The spec states seed policy only for coverage plates ("fixed seed family", §6). Failure scenario: operator clicks Re-roll, the job runs, the insert fails as a duplicate, the item's candidate count never grows, and the re-roll metric in the forecast under-counts. Recommendation: state that every attempt (initial candidates and re-rolls) rotates the seed / derives a distinct cache input, and that the fake provider varies output bytes by seed so offline candidate grids are meaningful.

6. [Major] §5 (lines 197-211) and O-C5 (line 461). The cross-system lock has no inode-integrity detection. The canonical lock file is ARISA's, located inside ARISA's package directory (`Path(__file__).with_name('vertex-generation.lock')`, `/root/AIVORA/arisa/studio/sfw/recovery.py:91-106`, file present). If an ARISA deploy/upgrade replaces that file (delete + recreate), the inode changes and both systems happily hold locks on different inodes — mutual exclusion silently evaporates, which is exactly the V3-AT-15/28 property this phase is accountable for. ARISA's own docstring only says the file "must stay in place while generators are active"; nothing enforces it. Recommendation: pin the canonical `st_dev/st_ino` at qualification, `fstat` the opened descriptor on every acquisition, and raise a typed BLOCKED alert on mismatch; also state that the Drama-side bind mount of the path is a production-composition prerequisite that fails closed when absent.

7. [Major] §7 (lines 297-299) and §8 (line 327). Nothing creates `characters` table rows for a V3 season. B keeps characters only inside `SeasonBibleV3.characters[]` documents (phase-B-spec.md §2); the V1 seeder `_seed_characters` (`/root/AIVORA/drama-box/microdrama/src/microdrama/story/service.py:656-671`) runs only in the V1/V2 compile path. But C needs real rows twice: `voices.character_id` is `NOT NULL REFERENCES characters(id)` (0002:138), and lock step 4 freezes "voices/characters → LOCKED (the existing state machines)". Failure scenario: the first accepted voice upload fails on the FK; or the lock transaction's freeze finds no character rows to lock. Recommendation: specify when C seeds `characters` rows from the demand list / CharacterProfile (presumably in `derive_pick_items`), including promoted extras roles and their merge lineage.

8. [Major] [format] Whole document (Feature Spec Standard, "The Alternatives Rule"). There is no Alternatives Considered section, while phase B has one (§16) and the master has one (§17). Several single-path design choices are made with no documented rejection: reusing `identity_locks`/`identity_lock_assets` with a NOT-NULL relaxation versus a new V3 lock table; flock-on-a-shared-inode versus a Postgres advisory lock or lock service for the cross-system mutex; append-only vote rows versus a mutable selection column; zip bulk import versus single-upload only; auto-adopt at episode insert versus stamping at lock time; a new `v3_cast_documents` store versus extending B's. A few are argued inline (§8 "No second binding table", O-C5, O-C6), but the standard requires the evaluation to be explicit and specific. Recommendation: add a section in B's format; the lock-table reuse and lock-file choices especially deserve a recorded trade-off (schema surgery on a frozen V1 table vs. a clean V3 table; file lock vs. DB lock portability across containers).

9. [Major] [format] Whole document (Feature Spec Standard, "Risks & Limits"). There is no risks-and-limits section (B has §15; master §18). The risks exist and are scattered: lock starvation/arisa contention (O-C7, P0), ARISA-side adoption being a hard prerequisite for any live image work, Botnoi catalogue drift and voice disappearance, tag vocalisation leakage into Pika output, hostile upload bytes, the OPERATOR_ATTESTED legal exposure, quarantine file retention, the human-check burden while detectors are unqualified (O-2). Recommendation: consolidate with mitigations and residual owners, as B §15 does.

### NIT

10. [Nit] §2 C-4 (line 101). `UNIQUE (source, voice_name, speaker_id)` with a nullable `speaker_id`: under default Postgres semantics NULLs are distinct, so duplicate `operator_csv` rows with NULL speaker_id and the same name accumulate silently. Use `NULLS NOT DISTINCT` or a COALESCE-based unique index.

11. [Nit] §7 (lines 279-281). The zip naming key "<character_id>__neutral.wav" is undefined in C's vocabulary — B keys characters by `character_key`/demand UUID. UUID filenames are operator-hostile; pin the key (character_key) and say the UI displays the exact expected filename per character.

12. [Nit] §9 (lines 366-368). Likeness inspection runs "against the locked faces", but most candidates are generated before any face is LOCKED (locking happens at CAST LOCK). The check must target the current selected candidate set per item; fix the wording before it becomes an implementation contradiction.

13. [Nit] §1.9 and §8 (lines 331-335). The R-12.1 fix covers only the V3 creation paths; the V1 `create_episode` still sets no lock and `attach_identity_lock` remains dead for V1. R-12.1 is phrased as a general "must fix" bug. State the residual V1 limitation explicitly (and get an operator nod), since "V1/V2 never change" makes this a permanent carve-out.

14. [Nit] §3 (lines 124-127). A post-STORY-LOCK amendment that drops a demand leaves orphaned pick items with votes; specify they are archived/marked not-required so they neither block the lock nor pollute the binding hash.

15. [Nit] §3 (lines 150-156) and O-C4. The forecast's behaviour while `image_price` is unknown (pre-qualification) is undefined: dispatch is refused, but is the forecast's cash line "estimated/UNVERIFIED", zero, or does the fits-cap gate condition block? One rule needed, mirroring the "estimated" labelling already given to throughput and re-roll rate.

16. [Nit] §9 (lines 376-378). YuE2 "vocal-leakage inspection" has no owner, detector, or O-2 human-check fallback specified — it is audio, outside the OutputInspectionProvider image seam the section otherwise defines.

17. [Nit] §7 (lines 301-305). `rights_registry` ELIGIBLE requires non-empty territories; the O-11 attestation text says nothing about territories, so `route-botnoi-voice` left without a territories decision fails closed as UNKNOWN and blocks every voice. Specify the territories value (presumably WORLDWIDE) as part of the route setup.

18. [Nit] §1.3 (line 55) vs master §4.4.4. C correctly applies the DECISIONS "D2 revised again" precedence (one neutral per speaker), but master §4.4.4 items 3-4 still say "per expression" scripts and "(character, expression)" upload slots. Recommend recording a master erratum request so a fresh implementer reading the master does not build per-expression slots.

### CHECKED WITH NO FINDING

- Ownership claims match master §15.1/15.2 exactly (V3-AT-5/6/7/15/22/23/28-offline/33; R-4.1..4.11, R-12.1..12.5, R-12.9; AT-28 live half in G).
- Binding decisions 1.1-1.12 are faithful to DECISIONS (D2 chain, O-11 verbatim attestation text, two-source catalogue, community-voice default exclusion, has_v4/last_verified semantics, the 12 Nov monk-labelling correction) and to phase A/B contracts (gate registry and NOT_AVAILABLE behaviour, CASTING/CAST_LOCKED states, decision transaction and lock order, revision notes, `picks.waiting`, fence/`expected_content_revision`, admission order unit→step→child→SEASON, `approve_setup_budget` and the step_01..step_04 vocabulary, AC-13 no-paid-work-before-approval).
- Code/migration citations spot-verified true: `GenerationProvider` at providers.py:188-205; `ProviderOperation` (cost.py); the `Provenance` enum at enums.py:28 with no ProvenanceRecord anywhere; `attach_identity_lock` (service.py:285) with test-only callers; jobs.queue CHECK = production/publication/community at 0001:77; identity_locks NOT NULLs at 0002:258/261; voices at 0002:134-152; asset_lineage at 0004:41-49; ARISA's flock pattern and the lock file's existence; the Botnoi API CSV header and the header-only operator CSV.
- The demand-list hand-off, NOT_AVAILABLE panels, wardrobe resolver seam (V2 routing passes no `state_events`), the O-C2 mid-scene change escalation, budget forecast/capacity-line arithmetic, SFX qualification fail-closed rules, YuE2 assignment to step_04, and the offline acceptance table (C-T1..C-T15 covering all owned ATs plus V3R-1/2/11) are all consistent with the master and A/B specs.
- The voice one-neutral rule, casting sheet, and upload trust-boundary limits are internally coherent and correctly supersede the older per-emotion requirements.

---

## B. Structural Reviewer (egm:egm-structural)

Structural audit of /root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-C-spec.md (lines 1–490, entire document), against /root/.local/share/egm/403d888/resources/document_standards/feature-spec-standard.md, with every document the target cites under /root/AIVORA/drama-box/docs/microdrama-system/ read for verification (SPEC-v3.md, phase-A0-spec.md, phase-A-spec.md, A1/A2/A3 design notes, phase-B-spec.md, c-factmap.md, DECISIONS.md, REQUIREMENTS.md, both Botnoi CSVs).

Overall: no Blockers. The skeleton is sound (single H1, sequential H2 sections 0–15, no skipped levels, clean tables, complete §12-package/§13-test cross-check, and an accurate ownership line and R-ID trace against master §15.1–15.2). The findings below are real integrity defects that will mislead a fresh builder until fixed.

### FINDINGS

1. Severity: Major — Affected Scope: header, line 11 ("Depends on: phase-B-spec.md v0.3"). — The dependency pin is stale. phase-B-spec.md is now Version 0.4, 13 Nov 2026 (Goldfish rulings applied), not v0.3. B v0.4 added §2.4 "B contract deltas (C-B1)", a first-class deliverable governing the shared contract-package bump — the exact mechanism C's §2 ("Records (contract package, guardian-owned bump...)") also performs. Citing the superseded revision misrepresents the hand-off contract C builds against. Re-pin to v0.4 and re-verify the B citations (I checked: B §1.1, §2, §2.1, §2.2, §4.2, §4.3 all still exist at v0.4 and are represented accurately, so only the pin and the contract-delta reconciliation need attention).

2. Severity: Major — Affected Scope: §8 line 309 ("A1 §2.7") and §10 line 389 ("A3 §7.1"). — Two misattributed cross-references. The NOT_AVAILABLE-before-C-ships rule is phase-A-spec.md §2 item 7 ("The handler registry (AC-4)"); A1-design-note.md has no §2.7 (its §2 stops at §2.4), and the A1 note itself calls the rule "spec §2.7". Likewise the stale-result quarantine fence is phase-A-spec.md §7.1 ("The fence (A3)"); A3-design-note.md has no §7.1 (its §7 is "Lock audit"; quarantine lives at A3 note §3.4). Both refs point at design notes whose numbering does not contain the cited sections. Correct to "A §2.7" and "A §7.1" (or "A3 note §3.4").

3. Severity: Major — Affected Scope: §3, line 138, derivation table last row ("accepted in the CAST review (§10)"). — Wrong internal self-reference. §10 is "Jobs, fence and waits"; the CAST review screen is defined in §11 (route /v3/seasons/{id}/cast/review). The document's own convention is that a bare §n refers to this spec. Should read (§11).

4. Severity: Major — Affected Scope: §4 line 178 and §7 line 305 (both "(§12.6)"). — Dangling bare references. This document's §12 ("Build packages") has no subsection 6, and every other foreign reference is prefixed (master §, A §, B §, FM §), so a bare "§12.6" resolves to nothing. The intended target is master SPEC-v3.md §12.6 (Amendment), which exists and matches the context ("post-lock amendments"). Write "master §12.6".

5. Severity: Major — Affected Scope: §5, line 205 ("Defaults are config (O-C8)"). — Wrong open-question ID. The fairness defaults (8 images / 120 s per hold, retry_after 20 s) belong to O-C7 ("Fairness numbers"); O-C8 is the unrelated question of whether the C7 trust-boundary note should be Codex-critiqued. §5 and §14 now disagree about which open item governs the fairness config.

6. Severity: Major — [format] Affected Scope: whole document; no risks section anywhere (compare §0–§15). — The Feature Spec Standard requires the specification to explicitly call out its own constraints, failure modes and mitigations. Phase C scatters real mitigations inline (lock starvation vs fairness batches, hostile upload handling, fail-closed pricing, UNVERIFIED labels) but never consolidates them, and never points to master §18 the way the sibling convention now requires — phase-B-spec.md v0.4 §15 ("Risks and limits") was added precisely per Goldfish ruling C-M21 ("a short risks table... plus a master §18 pointer"). Add an equivalent section.

7. Severity: Major — [format] Affected Scope: whole document; §14 is the nearest partial analogue. — No consolidated "Alternatives considered/rejected" section. The standard's Alternatives Rule requires documented rejections, and B v0.4 §16 ("Alternatives rejected", also from C-M21) sets the sibling convention. §14 does contain genuine alternative comparisons (O-C1 V2-vs-V4 intake, O-C5 lock inode ownership, O-C6 pick-one-vs-pool), and master §17 rules the platform-level choices, but C's own largest commitments are single-path as written: reusing identity_locks with a version-aware relaxation trigger vs a new lock table (§1.8/C-7); v3_cast_documents mirroring StoryV3Store vs extending existing document tables (§2); an flock-based cross-process lock vs the Postgres advisory locks that exist today (§5, FM §8); CastLockV3 membership as the sole binding of record vs a binding table (§8). Add a rejected-alternatives table citing master §17 where it already rules.

8. Severity: Major — Affected Scope: §8, lock transaction step 3 ("pick kinds map to the five asset_kinds"). — A mapping is asserted but never defined anywhere in the document. §2 defines a 12-value pick_kind vocabulary (FACE, SHEET_VIEW, EXPRESSION, OUTFIT, APPEARANCE_STATE, PROP, LOCATION_MASTER, LOCATION_COVERAGE, EXTRAS_LOOK, VOICE_NEUTRAL, MUSIC_LIB, SFX_LIB), while c-factmap.md §1 records exactly five ref_kind/asset_kind values (FACE, VOICE, WARDROBE, LOCATION, STYLE). Which kind a PROP, EXTRAS_LOOK, MUSIC_LIB or SFX_LIB member maps to is unstated, and no acceptance test pins it (C-T12/C-T13 do not). A builder cannot execute lock step 3 without inventing this. Add the mapping table (§2 or §8).

9. Severity: Nit — Affected Scope: §3 heading (line 123) vs §15 trace. — The heading cites "R-3.4 consumer, R-4.11, R-12.7". R-3.4 is B-owned and properly qualified as a consumer; R-12.7 is A-owned (master §15.2, phase-A-spec §5.2) and carries no qualification, yet appears nowhere in the §15 trace. Either mark it as consumed like R-3.4 or drop it; the trace table itself is complete and correct against the Owns line.

10. Severity: Nit — Affected Scope: §15, "Findings resolved here" paragraph (lines 488–490). — The list omits V3C-20 (YuE2 music library), which §9 resolves and cites, and V3R-9 (SFX route qualification), which master §7 and §20's map explicitly assign to phase C but which is never named anywhere in this spec. N7's entry is also the only one without a section pointer.

11. Severity: Nit — Affected Scope: §1.6 vs §15 R-4.10 row. — Terminology: master §4.4.2/§10.3 and REQUIREMENTS R-4.10/Q8 all say "Nano Banana Pro"; §1.6 introduces the model id gemini-nano-banana-2.1 and the trace row says "Nano Banana Pro" with no bridge between the two names. State once that the id is the Pro model (or fix the id) so Q8/R-4.10 readers can connect them.

12. Severity: Nit — Affected Scope: §11 route table (lines 399–405). — The dynamic route /v3/seasons/{id}/cast/{category} also matches the fixed child routes /cast/wardrobe, /cast/voices and /cast/review (and R-4.11's category names include "voices"). Constrain the category segment's vocabulary, nest the picks grids (e.g. /cast/picks/{category}), or state route precedence.

13. Severity: Nit — Affected Scope: §1.3 and §7 vs master §4.4.4 items 3–4. — Phase C correctly follows DECISIONS "D2 revised again" (one neutral clip per speaker; B §2.2 confirms the supersession), but master §4.4.4 item 3 still says "Casting sheet: per expression" and item 4 "one slot per (character, expression)" (v0.4.5 changed only §6). Phase C flags the R-4.6 supersession explicitly but not this residual master text; a reader cross-checking the master sees an unexplained contradiction. Add one supersession note, as done for R-4.6.

14. Severity: Nit — Affected Scope: §1.2 line 54 ("AR-4") and §3 line 153 / §13 C-T14 ("AC-13"). — These authority tags come from the phase-A Codex critique chain; their ruling text lives in codex-a-critique.md / codex-a-recritique.md and phase-A-spec §5, none of which this document's Depends-on list includes. The inline context does carry each rule's content, so this is a provenance gap, not a content gap — expand or link once.

15. Severity: Nit — Affected Scope: §3, line 142 ("except profiles and coverage variants the plan marks optional"). — "The plan" has no antecedent at that point: profile optionality came from "profiles if the bible asks" in the table above, and the wardrobe plan is not introduced until §6. Name the artifact that marks an item optional.

### CHECKED WITH NO FINDING

- Heading hierarchy and formatting: one H1, sequential H2 §0–§15, no skipped levels, no malformed tables or unclosed code blocks; numbered binding decisions make §1.7/§1.10 self-references resolvable.
- Version pins other than B: master SPEC-v3.md v0.4.6, phase-A0-spec.md v0.4, phase-A-spec.md v0.3, A1-design-note.md v1.2 — all accurate; c-factmap.md dated 13 Nov with §1–§8 all present.
- Owns line matches master §15.1 (V3-AT-5, 6, 7, 15, 22, 23, 28 Drama-side, 33) and §15.2 (R-4.1–4.11, R-12.1–12.5, R-12.9) exactly; the §15 trace covers all 17 owned R-IDs, each mapped to sections that exist.
- §12 package table vs §13 acceptance: C-T1..C-T15 all defined and used; every owned acceptance test has a package and a test (AT-5→C-T3, AT-6→C-T13, AT-7→C-T7, AT-15→C-T5, AT-22→C-T4, AT-23→C-T8, AT-28 offline→C-T5/C-T6, AT-33→C-T12).
- Representations of referenced sources verified accurate: B §1.1 (V1/V2 frozen), B §2.1 (scenes[].wardrobe covers every visible character), B §2.2 (emotion enum, one-neutral rule), B §4.2 (tier promotion), B §4.3 (demand kinds, stable demand IDs, the two NOT_AVAILABLE panels); A §2.2 (Reject CAST_LOCK stays CASTING), A §3 track_waits, A §5.2, A §6 lock order, A §8.4 picks.waiting, A4/A5/A6c package labels, A2's approve_setup_budget and create_v3_episodes; master §3.2, §4.4.1–4.4.5 (including item 8's pilot-leak observation), §4.7, §7, §10.0 state mapping, §10.2, §10.4, §10.5, §12.1–12.3, §13, §15; FM §1–§8 (ProvenanceRecord NOT FOUND, fake-generation wiring and the unknown-price refusal, unwired wardrobe helpers and the state_events gap, the LineAudio orphan, fail-closed rights, ARISA's flock pattern incl. retry_after 20 s, the lock file path/inode).
- DECISIONS accuracy: the O-11 attestation string in §7 is verbatim; the monks 582/583 archetype correction, the Studio archetype counts (7 monk, 2 grandpa, 2 grandma, Ananda, Bow), and the 24 kHz mono T031 references all match. Both CSVs match their descriptions (API field list exact; botnoi-v4-voices.csv header-only with exactly the C-4/DECISIONS field list).
- No duplicate-or-contradictory statements found in the normative text: §1.9 vs §8 (R-12.1), §3 vs §8 (forecast-above-cap blocker), §5 vs O-C7 (fairness numbers) and §12 vs O-C8 (C7 pre-critique) repeat consistently; the two hashes in §8 (gate binding vs cast_lock_hash) are distinct by design, not a contradiction.

---

## C. Style Reviewer (egm:egm-style)

Target: /root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-C-spec.md

Overall: the document is dense but well-structured, its vocabulary is almost entirely consistent with the document family (SPEC-v3 v0.4.6, phase-A/A0/B specs, A1-A3 notes, DECISIONS, c-factmap all verified for the cited names), and its tables are readable. The problems are concentrated in cross-references: several point at the wrong section, the wrong document, or the wrong register entry, and one dependency pin is stale. No Blockers; 9 Major, 17 Nit.

### Major findings

1. [Major] Header, line 11 — stale dependency pin: "phase-B-spec.md v0.3". /root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-B-spec.md is "Version 0.4, 13 Nov 2026" — revised the same day this spec is dated. Every B citation in this document (B §1.1, §2.1, §2.2, §4.2, §4.3) actually resolves against the v0.4 text, so the pin is stale text, but a reader following the pin would read a superseded B and miss v0.4's changes (e.g. §2.4 contract deltas). Update the pin to v0.4.

2. [Major] §3, line 138 — wrong internal cross-reference "(§10)". "`MUSIC_LIB`, `SFX_LIB`, accepted in the CAST review (§10)". §10 of this document is "Jobs, fence and waits"; the CAST review is §8 (gate) and §11 (screen). A builder looking in §10 for the acceptance rule finds nothing. Point at §8/§11.

3. [Major] §5, lines 205-206 — wrong register reference "(O-C8)". "Defaults are config (O-C8); P0 measures real throughput." O-C8 (§14) is the question of whether the C7 note should be Codex-critiqued. The fairness defaults are O-C7. As written the sentence cites the wrong open question for a load-bearing default.

4. [Major] §8, line 309 — citation points at a nonexistent section: "(A1 §2.7: `NOT_AVAILABLE` before C ships)". /root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A1-design-note.md has §2.1-2.4 only. The NOT_AVAILABLE-before-phase-ships rule is phase-A-spec §2 item 7 (the handler registry); A1's own OQ-6 ruling calls it "spec §2.7". The reference should read "A §2.7" (or "phase-A-spec §2 item 7"), not "A1".

5. [Major] Lines 176 and 305 — ambiguous bare references "(§12.6)" and "after lock, §12.6". This document has its own §12 ("Build packages", no subsections), so a bare "§12.6" looks broken locally; the intended target is master §12.6 (Amendment). Everywhere else the document writes "master §n" explicitly. This is load-bearing routing (post-lock amendment behavior), so the ambiguity should be removed in both places.

6. [Major] §10 jobs table, line 387 — the merged music/SFX row gives only one logical work ID. The row "`cast_v3.music_lib` / `cast_v3.sfx_lib` | `music` / `sfx` | YuE2 / SFX ops | `music-lib:<season>:<recipe>`" supplies no work-ID pattern for the SFX job. A builder implementing `cast_v3.sfx_lib` cannot construct its logical work ID from this table. Split the row or give both patterns.

7. [Major] §3 derivation table, line 135 — LOCATION coverage items: ambiguous creation timing and undefined view names. "after the master pick, `LOCATION_COVERAGE` × (reverse, tighter) (edge `COVERAGE_OF`)" — the enclosing function `derive_pick_items(season, demand_list)` is described as deterministic and rerun-idempotent, but coverage items depend on a pick that does not exist when the demand list is derived; nothing says whether a rerun after the master pick creates them or a separate path does. Also "reverse, tighter" are not defined anywhere (reverse angle? tighter framing?), while every other row enumerates its views precisely.

8. [Major] §3 derivation table, line 131 — "`EXPRESSION` × 2" for SUPPORTING characters is underspecified. The PRINCIPAL row enumerates its expressions (neutral, signature, extreme); the SUPPORTING row says only "× 2", leaving which two expressions to generate a guess. The package content by tier is substance; enumerate the two or state where they are chosen.

9. [Major] §7 Shortlist, lines 264-266 — "Deterministic ranking" specified with an undefined verb. "gender must match exactly; then age band, accent … and style tokens score." No scale, weights, or tie-break rule are given, yet the section (and §1.11) asserts determinism. Either define the scoring rule or state explicitly that the C6 note defines it; "score" alone does not make a deterministic algorithm specifiable.

### Nit findings

10. [Nit] §4, lines 172-173 — formula garbled by code-span placement. "`parent_version_at_generation ≠ ` the parent's currently selected version" — the backticks swallow the "≠" and a trailing space, so the operator renders inside code formatting as if it were part of the column name. Close the span after the column name.

11. [Nit] §9, line 369 — reversed citation order "(§7 master, O-9)". The family convention is "master §7" (cf. line 41 "master §7, §4.7"; line 39 "master §12.2"). Leading with "§7" invites a misread as this document's own §7 (Voices).

12. [Nit] Lines 317 and 408-409 — "A §2.2" and "A §8.4" use an unstated convention. Phase-A-spec §2 and §8 contain numbered list items, not subsection headers; these references mean "section 2, item 2" and "section 8, item 4", indistinguishable from real subsection references like "A §5.2" and "A §6". Both targets verified to exist, but the convention should be stated or the references made explicit.

13. [Nit] Line 18 — range notation and parenthetical attachment. "R-4.1..R-4.11, R-12.1..R-12.5" uses ".." while the rest of the document uses en dashes ("0028–0034+", "2–3"); and "28 (offline half), 33" makes "(offline half)" read as if it might also govern the preceding items — only line 19 disambiguates.

14. [Nit] §8 step 5, line 329 — "all N exist from STORY LOCK". "N" is undefined (episode count). One word ("all episode rows exist…") fixes it.

15. [Nit] §7/§2/§10 — near-collision of revision field names. `voice_uploads.expected_revision` (C-6) and "the expected revision" in the intake paragraph (line 281 — expected revision of which record? unstated) sit alongside the job fence's `expected_content_revision` (§10, from A3). Two adjacent, undifferentiated names in one phase invite wiring mistakes.

16. [Nit] C-7, line 104 vs the §2 documents table — one record, three name renderings. "a `cast_lock` document ref in `body`" vs the record type `CastLockV3` keyed `cast-lock:<content_revision>`. State once that they are the same thing.

17. [Nit] §1.6 vs §15 R-4.10 — model name drift. §1.6/§5 say model `gemini-nano-banana-2.1` / "Nano Banana"; the trace row says "Nano Banana Pro" (matching master §10.3). Add one clause mapping the model id to the "Pro" name, or use one name.

18. [Nit] §1.6 vs §5 — two wordings of the same live-switch condition. §1.6 "a non-unknown price" vs §5 "a non-None `image_price` quote". "Non-unknown" and "non-None" are not obviously the same predicate; pick one.

19. [Nit] §9, line 366 — "a recorded human check at the picks review" vs "the CAST review" (§4, §9, §11). If these are the same review moment, use one name; if they differ, say so.

20. [Nit] §7, lines 282-284 — limit semantics and redundancy. "processing ≤ 120 s per import" does not say what happens at the limit (timeout? rejection? retry), and "per-import entry cap enforced before extraction" restates "zip entries ≤ 64" from the same sentence.

21. [Nit] §5, line 204 — "so ARISA turns interleave". Garbled; the intended meaning is that ARISA's and Drama's batches interleave. Also nearby, "waiting is visible and holds no GPU — image jobs hold no GPU lease at all" says the same thing twice.

22. [Nit] §2 table C-2, line 99 — clipped cell "a vote records only". A fragment; state what a vote records (a choice, no work).

23. [Nit] §6, line 229 — paraphrase instead of citation. "the same evidence B's 'impossible wardrobe day' critic accepts" — the rule is B §6.2 (C-M19, the impossible-wardrobe-day CRITICAL rule); cite it rather than paraphrase, since the evidence standard is load-bearing for timed changes.

24. [Nit] §7, line 292 — "the binder's byte validator". "Binder" is not defined in this document (family readers know it; a fresh builder does not). One parenthetical identifying the binder suffices.

25. [Nit] §9, line 358 — "(Botnoi, the benchmark attestation)". "The benchmark attestation" (T031) is unexplained; name the source document.

26. [Nit] §12 table, line 424 — gate vocabulary inconsistency. C7 says "Pre-critique recommended (trust boundary)" while C1/C3/C8/C9 say "Critiqued first". The recommended-vs-mandatory distinction is deliberate (O-C8) but easy to miss in a table that otherwise uses one term.

### Verified as accurate (not findings)

Header versions for SPEC-v3 (v0.4.6), phase-A0 (v0.4), phase-A (v0.3), A1 note (v1.2); B §1.1/§2 "reused shapes"/§2.1 scenes[].wardrobe/§2.2 emotion vocabulary/§4.2/§4.3 SeasonDemandListV3 and its NOT_AVAILABLE panels; A §2 item 2 (Reject CAST_LOCK → CASTING), A §3 track_waits, A §5.2, A §6, A §8 item 4 (picks.waiting); A2 0033 step vocabulary, approve_setup_budget, create_v3_episodes, US$30 default; A3 expected_content_revision fence; master §3.2, §4.4.1–4.4.5, §10.0 state mapping, §10.2, §10.4, §12.1–12.6, §13, §15.1–15.2 (C's AT and R ownership matches line 18 exactly); Q8, O-2, O-6, O-9, O-10/O-11, N7/N13/N16/N23/N30, AC-13, AR-4, MA7, MA12, V3C/V3R IDs, DECISIONS "D2 update"/"D2 revised again", monks 582/583, 24 kHz mono; "A40" (the RunPod GPU) and "guardian-owned bump" are established family terms; c-factmap §1–§8 sections exist as cited.

---

## Cross-reviewer overlap register (dedup aids for consolidation)

- **pick_kind → asset_kind mapping missing**: Design-4, Structural-8 (also Zoom-out-3, Comprehension-4).
- **Broken "A1 §2.7" citation**: Structural-2, Style-4 (also Zoom-out-4, Comprehension-1).
- **Stale B v0.3 pin**: Structural-1, Style-1.
- **"(§10)" wrong internal ref (CAST review)**: Structural-3, Style-2.
- **"(O-C8)" wrong open-question ref**: Structural-5, Style-3 (also Comprehension-2).
- **Bare "§12.6" refs**: Structural-4, Style-5.
- **Missing Risks & Limits section**: Design-9, Structural-6. **[format]**
- **Missing Alternatives section**: Design-8, Structural-7. **[format]**
- **Nano Banana Pro name drift**: Structural-11, Style-17.
- **"picks review" vs "CAST review" naming**: Style-19 (also Comprehension-8).
- **"benchmark attestation" unexplained**: Style-25 (also Comprehension-5).
- **AR-4/AC-13 provenance gap**: Structural-14 (also Comprehension-12).
- **"binder's byte validator" undefined here**: Style-24 (Zoom-out-2 goes deeper: validator has no locatable existence in the merged tree).
- **Master §4.4.4 residual contradiction**: Design-18, Structural-13.
