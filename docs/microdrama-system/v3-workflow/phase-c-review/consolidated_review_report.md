# Consolidated Review Report — phase-C-spec.md (v0.1 DRAFT)

- **Target**: /root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-C-spec.md (490 lines)
- **Run**: EGM Goldfish review, headless uninterrupted flow (Preset 1), 2026-11-13
- **Semantic split**: no `## Detailed Implementation Plan` boundary header exists; FeatureRange = 1–490, DetailedRange = N/A (Stage 9 ran on the full document with §12 "Build packages", line 411, as the build-plan anchor)
- **Goldfish context**: none supplied; every reviewer read the documents the spec references and verified claims against the codebase (/root/AIVORA/drama-box, /root/AIVORA/arisa)
- **Stage reports** (same directory): `zoom_out_report.md`, `comprehension_report.md`, `critic_report.md`, `intermediate_zoom_out_report.md`, `implementation_readiness_report.md`
- **Remediation**: none applied — this is a findings report. Do not edit from this report directly without re-running the relevant stage (per EGM convergence rules).

## Verdict

Not ready to build as-is. The spec's fact base is unusually accurate (the codebase-details reviewer found **no false statements about current code**; nearly every line anchor, CHECK constraint and DECISIONS citation checks out), and its reuse instincts are right (identity_locks reuse, picks-as-votes, no second job system). But two defects each make the very first package (C1, critiqued-first migrations) unbuildable without inventing load-bearing design, and roughly a dozen more Majors would force builders of C2–C9 to invent design the spec owes them. All findings below are fixable by spec edits; none requires re-architecting — the Stage 8 zoom-out confirms the architecture survives review intact.

## Counts

| | Blocker | Major | Nit | Total |
|---|---|---|---|---|
| Raw findings (5 stages, 11 reviewers) | 2 | 52 | 71 | 125 |
| **Consolidated action items (deduplicated)** | **2** | **27** | **46** | **75** |

Of the 27 Majors, **2 are `[format]`** items (missing template sections only: Alternatives Considered, Risks & Limits). Everything else is a real defect.

Severity reconciliation: where stages disagreed, the consolidated severity is the one carried by the strongest verified rationale — BLK-2 was rated Blocker by implementation-readiness (address space of the phase; unrecoverable if chosen wrong) against Major elsewhere; the C-4 unique-key issue was upgraded Nit→Major on codebase evidence (C-T9 depends on the key); the GenerationAdapter item merges a Major (seed/cache-key collision) with three Nits (reuse unstated).

---

## 🔴 Blockers

### BLK-1 — No trigger for initial candidate generation; the step-4 entry flow is undefined
**Sources**: Critic/design-1 (Blocker); IR-2 (Major); Style9-6 (Major); Stage-8 steering IZ-1. **Scope**: §1.2 (52-54), §3 (123-156), §4 (158-173), §10 job table (382-388), §11, §12 C4.

The only work-starting actions defined are `vote` (starts nothing), `reroll` (re-queues one item, one attempt) and `generate_next` (dependents of a picked parent). Nothing generates the first candidates for root items (FACE, LOCATION_MASTER), and §1.2's "Votes start no work" rule forecloses automatic start. The operator would face an empty picks grid after approving the setup budget. The same hole is wider than the grid: nothing triggers `derive_pick_items`, no package claims the STORY_LOCKED→CASTING transition (A1's command table leaves it to the owning phase), and "candidates 2-3" is never pinned to 2 or 3 despite driving forecast and metering. Per-job cardinality is also undefined ("one item, one attempt" + "1 image op per candidate" — does one job emit the item's whole candidate set or one candidate?), and the `cast-gen:<…>:<attempt>` segment collides with the jobs system's retry-attempt vocabulary.

**Remedy steering (Stage 8)**: fix with a bounded initial-generation batch enqueued at setup-budget approval — N ordinary `cast_v3.generate` job rows, no fourth operator verb, no batch-orchestration component; fairness batching already bounds dispatch. Pin the candidate count per item and per job, and rename the work-ID segment (e.g. `<gen_seq>`). One sentence in §1.2/§4 plus a C-T3 clause.

### BLK-2 — The pick-kind → ref_kind/asset_kind mapping is undefined: the address space of the whole phase
**Sources**: IR-1 (Blocker); zoom-out-3, design-4, structural-8, codebase-1 (Major); comprehension-4 (Nit); Stage-8 steering IZ-2. **Scope**: §2 C-1 (98), §2 pick_kind vocabulary (96-108), §4 Candidates (161-163), §8 lock step 3 (325-327); code: migrations 0002:158 and 0002:275, contracts/enums.py:312.

The spec defines twelve pick kinds; `reference_versions.ref_kind` and `identity_lock_assets.asset_kind` are hard CHECKs over exactly five values (FACE/VOICE/WARDROBE/LOCATION/STYLE), and `identity_lock_assets` requires a reference_versions row per member. The spec asserts "pick kinds map to the five asset_kinds" and never gives the mapping, the ref_key naming scheme, or a decision to extend the CHECKs. PROP, EXTRAS_LOOK, MUSIC_LIB and SFX_LIB have no plausible existing kind. Candidate queries (C4), lock membership and `cast_lock_hash` inputs (C9), and D's future binding all inherit whatever the C1 builder invents — and the choice is not recoverable without re-running migrations and re-hashing locks. Two builders would choose differently; C-T1's "no drift" and C-T3's hash test would surface the divergence late.

**Remedy steering (Stage 8)**: prefer B v0.4's C-B1 pattern — map only where semantics are true (FACE→FACE, OUTFIT/APPEARANCE_STATE→WARDROBE, LOCATION_MASTER/COVERAGE→LOCATION, VOICE_NEUTRAL→VOICE) and extend the two CHECKs with honest values for the rest, using the version-aware constraint pattern C-7 already establishes, so V1 rows/writers stay on the five-kind vocabulary. Whichever way is chosen, also pin ref_key namespacing: if SHEET_VIEW and the character's FACE both land on ref_kind FACE with the same ref_key, their candidate sets silently merge (§4 defines candidates per `(target_ref_kind, target_ref_key)`). Also resolve the "candidates are reference_versions rows" vs C-2's `candidate_kind ASSET` inconsistency for library items.

---

## 🟡 Majors

Real defects, ordered roughly by build-sequence impact. `[format]` marks template-section-only items.

| ID | Finding (consolidated) | Scope | Sources |
|---|---|---|---|
| MAJ-1 | CAST LOCK Approve conditions omit "every speaker has a registered, rights-approved neutral voice clip", yet the same transaction must hash "voice WAV hashes" into `cast_lock_hash`. As written a lock can Approve with no voice WAVs — the hash cannot be computed or silently omits them, stranding every episode at D's dispatch blocker. Add the explicit Approve condition (`voice_uploads` REGISTERED + rights) and state the VOICE item's job lifecycle is the intake job. | §8 (309-325) vs §7 (301-305); master §4.4.5 | design-2 |
| MAJ-2 | "Every required item is picked" collides with master §4.4.1's derived-asset model: §3 marks SHEET_VIEW/EXPRESSION `required=true` and §4 defines picked as "a latest vote exists", but the master lists sheet views, expression sets, coverage plates and libraries as derived assets accepted/re-rolled at the CAST review (master §19.2 superseded auto-accept). Either hundreds of extra human votes per season or an undefined "acceptance". Publish a per-pick_kind table (human-pick vs derived) and split the `required` flag's two meanings; align C-T3. **Steering (Stage 8)**: implement acceptance as a bulk operator action appending ordinary session-marked `cast_pick_votes` rows — one mechanism, two policies; no second state machine. | §3 (141-143), §4 (161-183), §8 (313) | design-3, IZ-5 |
| MAJ-3 | Generation adapter reuse and seed policy are unstated, and the omission breaks re-rolls: `reference_versions` has `UNIQUE (season_id, cache_key)` where cache_key hashes the full request including the seed (generation.py:415-434, service.py:890-916). A byte-identical re-roll (or initial candidate) collides and the insert fails — the candidate count never grows. State that every attempt rotates the seed / derives a distinct cache input, that the fake provider varies bytes by seed, and that C3 wraps/extends `GenerationAdapter` (episode→season/step_04 scope) reusing `check_rights`/`build_image_request` — never weaken the UNIQUE constraint (it is the duplicate guard). | §4 (167-170), §5 (185-211), C-1; code generation.py:202+, 231-246 | design-5, zoom-out-7, IZ-4, codebase-6 |
| MAJ-4 | The cross-system lock has no inode-integrity detection. The canonical lock file is ARISA's, inside ARISA's package directory; an ARISA deploy that replaces the file (delete+recreate) changes the inode and both systems then hold locks on different inodes — mutual exclusion silently evaporates (the exact V3-AT-15/28 property). Pin `st_dev/st_ino`, `fstat` the descriptor on every acquisition, raise a typed BLOCKED on mismatch. **Steering (Stage 8)**: house the pinned inode in A's existing `provider_qualifications` (qualify/expiry cadence), not a new lock-integrity record; skip watchdogs (a mid-hold swap overlaps at most one ≤120 s batch). | §5 (197-211), O-C5 | design-6, IZ-6 |
| MAJ-5 | Nothing creates `characters` table rows for a V3 season: B keeps characters only inside `SeasonBibleV3.characters[]`; `voices.character_id` is NOT NULL REFERENCES characters (0002:138); lock step 4 freezes "voices/characters". The first accepted voice upload fails on the FK, or the freeze finds nothing to lock. **Steering (Stage 8)**: `derive_pick_items` (C2) upserts characters keyed by character demand ID (§1.10 discipline); reference B's promotion facts, don't duplicate them into a lineage table. | §7 (296-299), §8 step 4 (328) | design-7, IR-5, IZ-7 |
| MAJ-6 | Migration C-3 (`cast_dependency_edges`) is a second persisted representation of a single-parent graph already fully encoded in `cast_pick_items` (both edge kinds derivable from `parent_pick_id` + `pick_kind`, both already C-1 columns); §4's staleness rule already computes dependency state from stored columns. Phase-A §7.3's DependencyProvider wants a computed closure, not addressable edge rows. Drop C-3, or justify why A4's registry cannot take a computed closure — otherwise a migration, table and registration path exist only to drift. | §2 C-3 (98-100), §3 (141), §4 (176) | zoom-out-1, IZ-R1 |
| MAJ-7 | "Must pass the binder's byte validator" (§7:292, C-T11:447) has no locatable existence in the merged tree: the binder's binding module lives only in the unmerged T031 experiment tree; no WAV byte validator exists in `microdrama/rendering/`. The right primitive exists (`references/media.py`: `wav_media_info`, `verify_generated`). Anchor the validator to a real seam (stating it lands with D's T031 merge) or declare C's own profile check — extending references/media.py — the validator of record; name the ffmpeg runner as the isolated-decode subprocess. | §7 (292), §13 C-T11 (447) | zoom-out-2, style-24 |
| MAJ-8 | Stale dependency pin "phase-B-spec.md v0.3" (B is v0.4, 13 Nov — every B citation actually resolves against v0.4), and behind it a governance gap: B v0.4 §2.4 establishes the C-B1 contract-delta register (any identifier crossing an A-enforced contract is checked against that contract's enforced vocabulary before the phase's first note is accepted). C crosses at least three A-enforced contracts (jobs.queue CHECK via C-8, identity_locks NOT NULLs via C-7, whatever BLK-2 lands on) and never enumerates them. Re-pin to v0.4 and add a C-B1-style crossing register to §2. | header (11), §2 (88), §12 C1 | structural-1, style-1, IR-11, IZ-3 |
| MAJ-9 | Misattributed cross-references plus an unstated convention: "A1 §2.7" (A1 note has no §2.7 — the rule is phase-A-spec §2 item 7), "A3 §7.1" (A3 note has no §7.1 — the fence is phase-A §7.1 / A3 note §3.4), and "A §2.2"/"A §8.4" meaning section-item pairs indistinguishable from real subsection refs. The family convention (prefix = owning package; "§x.y" may mean item y of section x) is never explained and collides with the document actually named A1. Fix the two misattributions and state the convention once. | §8 (309), §10 (389), (317, 408-409), (49) | structural-2, style-4, style-12, comprehension-1, zoom-out-4, IR-10 |
| MAJ-10 | Wrong internal reference sweep: §3:138 "(§10)" for the CAST review (that's §8/§11 — §10 is jobs/fence); §5:205 "(O-C8)" for fairness defaults (that's O-C7; O-C8 is the C7-critique question); bare "§12.6" at 176 and 305 resolves to nothing in this document (intended: master §12.6 Amendment) — load-bearing post-lock routing. | §3 (138), §5 (205), §4 (176), §7 (305) | structural-3/4/5, style-2/3/5, comprehension-2, IR-10 |
| MAJ-11 | Acceptance tests gate packages where their clauses cannot pass: C-T3/C-T4 (lock refusal, lock hash, stale freeze) are C4's gate but the CAST_LOCK handler, Approve conditions and hash arrive in C9, and C9's own gates (C-T12/C-T13) don't cover them — V3-AT-5's clauses have no package at which they can pass. C-T14 is one row gating C2+C3+C8 with package-specific clauses unlabeled (formally unpassable at C2/C3). C-T12's "provenance half"/"inspection half" split exists only in §12 while §13 has one merged row, and the inspection half depends on C10 which lands after C9's gate. Split or label all three (C-T12 was already split once — do the same). | §12 (419-427), §13 (437-451) | IR-3, IR-12, style9-1, style9-2 |
| MAJ-12 | No command table (master §2.2 makes it mandatory; B §9 has one): C's operator actions (vote, reroll, generate_next, wardrobe edit, audition, upload, import_cast) lack allowed states, prerequisites, events, replay identity — reroll/generate_next/import_cast have no replay semantics at all. Plus two unregistered A-contract deltas: CAST Revise targets `{kind: pick}` but A1's RevisionTargetKind has no "pick" value; lock-busy must surface as WAITING_PROVIDER but the flock-busy deferral's DeferReason value (or enum growth) is unstated. | whole document; §8 (317); §5 (203) | IR-4 |
| MAJ-13 | Voice-upload quarantine storage is unspecified: where untrusted bytes persist between HTTP request and the async `cast_v3.voice_intake` job (bucket/prefix vs local scratch), which column references them (C-6 has no object-key column), and what happens to a QUARANTINED row after restart. This is the phase's only untrusted-bytes surface and C7 is the pre-critique package — the trust-boundary note cannot be written without it. | §7 (280-289), C-6 (103) | IR-6 |
| MAJ-14 | The YuE2 music library (C8) is a one-line brief for a new subsystem: no YuE2 code exists in drama-box, R-7.3 records "YuE2 runs elsewhere; no Drama Box hookup", and the spec never says what the Drama-owned job runs on, what the pinned recipe is pinned to, or the library composition (track count, durations, loop targets). The fake adapter, the forecast's music line and C-T14's eligibility clause all need those unit counts. The C8 builder would be designing, not implementing. | §9 (375-378), §3 (150) | IR-7 |
| MAJ-15 | Pick-screen "activation" lifecycle is undefined: C-T15 asserts "picks.waiting emitted once per activation" but nothing defines what an activation is (per item/category/season), what opens or closes it, and A1's gate_activations CHECK admits only the six gate types — how pick screens register as "waiting for you" is left to the C4/C11 builder. | §11 (407-409), C-T15 (451) | IR-8, style9-11 |
| MAJ-16 | The voice shortlist's "deterministic ranking" names no algorithm: no weights, no normalisation across free-text style fields, no tie-break, no 2-vs-3 rule, no flagging cutoff — yet §1.11 asserts determinism and C-T9 checks shape only, so any invented formula passes review while producing different operator-visible suggestions per builder. Pin the rule or explicitly delegate it to the C6 note. | §7 (261-268), §1.11 | style-9, IR-9 |
| MAJ-17 | O-C6 presents as open a decision the document has already made (§3's derivation row: "2–4 candidate looks → pick one"; master §4.4.1 lists extras looks as human picks), and its operative verb "others are discarded at lock" is undefined against an append-only-everywhere design — a builder could physically delete or skip registering losing candidates. Record the decision as made and define the term (losing looks stay as candidate versions, excluded from lock membership, nothing deleted). | §14 O-C6 (462) vs §3 (137) | style9-7, codebase-8 |
| MAJ-18 | `[format]` No Alternatives Considered section (B §16 and master §17 set the convention; the standard's Alternatives Rule requires documented rejections). Single-path choices with no recorded rejection: identity_locks reuse vs new table; flock-on-shared-inode vs Postgres advisory lock; append-only votes vs mutable selection column; zip import vs single upload; auto-adopt vs stamp-at-lock; new v3_cast_documents store vs extending B's. A few are argued inline (§8, O-C5, O-C6); consolidate in B's format, citing master §17 where it already rules. | whole document | design-8, structural-7 |
| MAJ-19 | `[format]` No Risks & Limits section (B §15 / master §18 convention; added to B per Goldfish ruling C-M21). Real risks exist and are scattered: lock starvation/ARISA contention, ARISA-side adoption as prerequisite for live images, Botnoi catalogue drift, tag vocalisation leakage, hostile upload bytes, OPERATOR_ATTESTED legal exposure, quarantine retention, human-check burden while detectors are unqualified (O-2). Consolidate with mitigations and residual owners plus a master §18 pointer. | whole document | design-9, structural-6 |
| MAJ-20 | C-4's `UNIQUE (source, voice_name, speaker_id)` with nullable `speaker_id` is a no-op for operator/Studio rows under default Postgres NULLs-are-distinct semantics — exactly the rows §7 says are never deleted or overwritten, so they can duplicate indefinitely, and the merge semantics + C-T9 depend on this key. Use `NULLS NOT DISTINCT` (PG15+), a sentinel, or NOT NULL with a documented convention. | §2 C-4 (101), §7 | design-10, codebase-2 |
| MAJ-21 | The R-12.1 fix says `create_v3_episodes` "auto-adopts the season's current lock at insert time — `attach_identity_lock` becomes the production helper", but the helper raises typed `IdentityLockRequired` when no lock exists (service.py:293-299) — and all V3 episodes are created at STORY LOCK, before any lock exists. Verbatim reuse fails every episode creation. State the adopt-if-present semantics (initial episodes stamped later by §8 step 5; only extension episodes adopt at insert). | §1.9, §8 (331-335); code service.py:285-308 | codebase-3 |
| MAJ-22 | C-7's trigger predicate "required when `schema_version = '1.0'`" names no such column on `identity_locks` and mismatches the real discriminator (A1 migration 0028: `seasons.workflow_version` CHECK `IN ('v1','v3')`); `schema_version DEFAULT '1.0'` lives on A's new tables. Guessing wrong either breaks V1 preservation (C-T1) or rejects every V3 insert. Rewrite against `workflow_version = 'v1'` with the lookup path, and state what schema_version V3 lock rows carry. | §2 C-7 (104) | style9-3, IR-13 |
| MAJ-23 | The `cast_lock_hash` preimage is field-enumerated only for picks; "derived assets" and "voice WAV hashes" have no field list (asset id? content hash? upload id? `normalised_sha256`?), and "the STORY binding hash" names no source (B's `StoryLockBindingV3` vs A's `gate_activations.binding_sha256`). C-T3 varies only picked versions, so two different ad-hoc preimages for the other classes would still pass while producing hashes D cannot reproduce. Give the exact preimage per member class and name the read source. | §8 step 1 (320-322) | style9-4 |
| MAJ-24 | "profiles if the bible asks" has no defined home: B's `CharacterProfile` carries visual-lock prose and a voice descriptor but no field requesting profile sheet views; nothing else expresses the ask. A C2 builder cannot determine where to read the flag, and C-T2's "tier-correct packages" inherits the gap. Name the field or define a deterministic extraction rule. | §3 (130) | style9-5 |
| MAJ-25 | LOCATION coverage items: ambiguous creation timing and undefined view names — `derive_pick_items` is deterministic and rerun-idempotent, but coverage items depend on a master pick that does not exist at derivation; nothing says a rerun creates them or a separate path does. "reverse, tighter" are defined nowhere while every other row enumerates its views. | §3 (135) | style-7 |
| MAJ-26 | "`EXPRESSION` × 2" for SUPPORTING characters is underspecified: the PRINCIPAL row enumerates (neutral, signature, extreme); the SUPPORTING row says only "× 2", leaving which two a guess. Enumerate them or state where they are chosen. | §3 (131) | style-8 |
| MAJ-27 | The merged §10 music/SFX job row gives only one logical work ID (`music-lib:<season>:<recipe>`); `cast_v3.sfx_lib` has no pattern, so a builder cannot construct its work ID. Split the row or give both patterns. | §10 (387) | style-6 |

---

## 🟢 Nits

Grouped thematically; sources in brackets (stage reports carry full detail).

**Cross-references, names, provenance**
1. Line-anchor drift: `service.py:284` vs actual 285 (twice), voices `134-152` vs 134-151, and several stale c-factmap anchors (fakes generation.py:54 not :48; identity_lock.py:91/107/142; LineAudio models.py:70-78). [zoom-out-4, codebase-4]
2. Bridge `gemini-nano-banana-2.1` ↔ "Nano Banana Pro" once (§1.6 vs §15 R-4.10, master §10.3). [structural-11, style-17]
3. "picks review" vs "CAST review" screen naming (§9:366 vs §11). [style-19, comprehension-8]
4. "the benchmark attestation" (T031) unexplained; name the source document. [style-25, comprehension-5]
5. AR-4 / AC-13 ruling tags never linked to their codex-a-critique source. [structural-14, comprehension-12]
6. Master §4.4.4 items 3-4 still say "per expression" — add a supersession note / erratum request as done for R-4.6. [design-18, structural-13]
7. DECISIONS.md and REQUIREMENTS.md cited bare throughout, never linked in the header (both sit in the same directory). [comprehension-10]
8. "front-headless" defined nowhere (dropped from the master for the same reason). [comprehension-3]
9. "Joey's skills" referent never introduced; joey-digest.md not linked. [comprehension-6]
10. provenance_records "entitlement (… separate from plan upgrades)" unexplained. [comprehension-7]
11. YuE2 "canonical holds/recovery/finality" compressed jargon, no pointer. [comprehension-11]
12. T031 "S05/S06" sub-IDs never expanded or linked. [comprehension-9]

**Wording and consistency**
13. Code-span garble: backticks swallow "≠" in the staleness formula (§4:172-173). [style-10]
14. "(§7 master, O-9)" reversed citation order (§9:369). [style-11]
15. ".." vs en-dash ranges; "(offline half)" attachment ambiguity (line 18-19). [style-13]
16. "all N exist from STORY LOCK" — N undefined (§8:329). [style-14]
17. `voice_uploads.expected_revision` vs "the expected revision" (which record?) vs `expected_content_revision` — adjacent undifferentiated names. [style-15]
18. `cast_lock` document ref / `CastLockV3` / `cast-lock:<content_revision>` — one record, three renderings. [style-16]
19. "a non-unknown price" (§1.6) vs "a non-None `image_price`" (§5) — pick one predicate. [style-18]
20. Upload limit semantics: what happens at "processing ≤ 120 s per import" (timeout? rejection? retry); entry-cap clause restates "zip entries ≤ 64". [style-20]
21. "so ARISA turns interleave" garbled; duplicated no-GPU-lease clause nearby. [style-21]
22. Clipped table cell "a vote records only" (C-2 row). [style-22]
23. Wardrobe evidence paraphrase — cite B §6.2 (C-M19) instead. [style-23]
24. C7's critique status stated three inconsistent ways (§12 Routing omits C7; gate cell "Pre-critique recommended"; O-C8 unresolved) — a C7 builder can't tell if pre-critique is in their definition of done. [style-26, style9-8]

**Design/behavior gaps (nit level)**
25. OCR/branding and YuE2 vocal-leakage checks lack the qualified-detector fallback rule likeness correctly has ("recorded human check until a detector exists", O-2); no OCR/audio detectors exist today — don't build detector plumbing with no detectors. [zoom-out-5, design-16, IZ-8]
26. `import_cast` (season-2 only, R-12.5) rides in C9 with the lock transaction and R-12.1 fix — split into a trailing package to shrink the riskiest package's critique surface. [zoom-out-6]
27. O-C1 (neutral-source intake) is a DECISIONS "decide before phase C" item still open at spec time; record the operator's choice before C6/C7 build. [zoom-out-8, codebase-8]
28. §3 heading cites R-12.7 (A-owned) with no consumer qualification and absent from the §15 trace. [structural-9]
29. §15 trace omissions: V3C-20 resolved here but unlisted; V3R-9 assigned to C by master §7/§20 but never named; N7's entry lacks a section pointer; R-12.3 (extras pool) row missing. [structural-10, IR-15]
30. Dynamic `/cast/{category}` route collides with fixed children (/cast/wardrobe, /cast/voices, /cast/review); constrain vocabulary, nest, or state precedence. [structural-12]
31. "except profiles and coverage variants the plan marks optional" — "the plan" has no antecedent at §3:142. [structural-15]
32. Zip naming key "<character_id>__neutral.wav" undefined in C's vocabulary (B keys by character_key/demand UUID); UUID filenames are operator-hostile — pin the key and show the expected filename in the UI. [design-11]
33. Likeness inspection "against the locked faces" — most candidates are generated before any face is locked; target the current selected candidate set. [design-12]
34. R-12.1 fix covers only V3 paths; V1 `create_episode` still sets no lock and the attach helper stays dead for V1 — state the permanent carve-out and get the operator's nod. [design-13]
35. Post-STORY-LOCK amendment dropping a demand leaves orphaned pick items with votes — specify archive/not-required so they neither block the lock nor pollute the binding hash. [design-14]
36. Forecast behaviour while `image_price` is unknown (pre-qualification): estimated/UNVERIFIED, zero, or gate-blocked — one rule needed (O-C4). [design-15]
37. Rights territories: O-11 attestation says nothing about territories; without a value (presumably WORLDWIDE) the route fails closed as UNKNOWN and blocks every voice. [design-17]
38. C-T9's "shortlist = 2–3" assumes ≥2 survive the gender-exact filter; state the fewer-than-2 rule (flag? allow 1? block?). [style9-10]
39. C-T1's "generated contracts show no drift" names no baseline (committed generated code? snapshot? regen diff?). [style9-9]
40. `botnoi-refresh:<date>` — which date, what granularity, what happens on a same-day second run (logical_work_id replacement semantics). [style9-12]
41. "emit `gate.waiting`-family events" — A defines exact event names, no "family"; list the exact events the C9 handler emits (after Approve, no activations are open). [style9-13]
42. The four queue lanes are C's choice, not master-mandated (master §10.2 names no lanes); music and sfx each carry ~1 job/season — justify their separation in one sentence or collapse into one lane. [IZ-9]
43. Missing/unreadable canonical lock file → unhandled FileNotFoundError on every image job; define the typed outcome (WAITING_PROVIDER with operator visibility). Also clarify hold span (per POST vs submit+polling). [IR-16]
44. Three co-equal "Primary action" entries on the picks grid vs the one-primary-action rule (master §3.2 N18, C-T15) — name Pick, demote the rest. [IR-14]
45. "StateEvent intervals effective across episode boundaries": frozen V2 StateEvent is episode-scoped — per-episode events with resolver continuity, or a new V3 season-level wrapper? C5 is not critiqued first; pre-make the shape. [codebase-5]
46. Botnoi API CSV field list omits the leading `source` column that the actual header carries ("fields verified" claim). [codebase-7]

---

## Traceability matrix (raw finding → consolidated item)

Stage 5 `zoom_out_report.md` (ZO): 1→MAJ-6 · 2→MAJ-7 · 3→BLK-2 · 4→MAJ-9 + NIT-1 · 5→NIT-25 · 6→NIT-26 · 7→MAJ-3 · 8→NIT-27
Stage 6 `comprehension_report.md` (CO): 1→MAJ-9 · 2→MAJ-10 · 3→NIT-8 · 4→BLK-2 · 5→NIT-4 · 6→NIT-9 · 7→NIT-10 · 8→NIT-3 · 9→NIT-12 · 10→NIT-7 · 11→NIT-11 · 12→NIT-5
Stage 7 `critic_report.md` — design (DE): 1→BLK-1 · 2→MAJ-1 · 3→MAJ-2 · 4→BLK-2 · 5→MAJ-3 · 6→MAJ-4 · 7→MAJ-5 · 8→MAJ-18 · 9→MAJ-19 · 10→MAJ-20 · 11→NIT-32 · 12→NIT-33 · 13→NIT-34 · 14→NIT-35 · 15→NIT-36 · 16→NIT-25 · 17→NIT-37 · 18→NIT-6
Stage 7 — structural (ST): 1→MAJ-8 · 2→MAJ-9 · 3→MAJ-10 · 4→MAJ-10 · 5→MAJ-10 · 6→MAJ-19 · 7→MAJ-18 · 8→BLK-2 · 9→NIT-28 · 10→NIT-29 · 11→NIT-2 · 12→NIT-30 · 13→NIT-6 · 14→NIT-5 · 15→NIT-31
Stage 7 — style (SY): 1→MAJ-8 · 2→MAJ-10 · 3→MAJ-10 · 4→MAJ-9 · 5→MAJ-10 · 6→MAJ-27 · 7→MAJ-25 · 8→MAJ-26 · 9→MAJ-16 · 10→NIT-13 · 11→NIT-14 · 12→MAJ-9 · 13→NIT-15 · 14→NIT-16 · 15→NIT-17 · 16→NIT-18 · 17→NIT-2 · 18→NIT-19 · 19→NIT-3 · 20→NIT-20 · 21→NIT-21 · 22→NIT-22 · 23→NIT-23 · 24→MAJ-7 · 25→NIT-4 · 26→NIT-24
Stage 8 `intermediate_zoom_out_report.md` (IZ): R1→MAJ-6 · 1→BLK-1 · 2→BLK-2 · 3→MAJ-8 · 4→MAJ-3 · 5→MAJ-2 · 6→MAJ-4 · 7→MAJ-5 · 8→NIT-25 · 9→NIT-42
Stage 9 `implementation_readiness_report.md` — IR: 1→BLK-2 · 2→BLK-1 · 3→MAJ-11 · 4→MAJ-12 · 5→MAJ-5 · 6→MAJ-13 · 7→MAJ-14 · 8→MAJ-15 · 9→MAJ-16 · 10→MAJ-9 + MAJ-10 · 11→MAJ-8 · 12→MAJ-11 · 13→MAJ-22 · 14→NIT-44 · 15→NIT-29 · 16→NIT-43
Stage 9 — codebase (CB): 1→BLK-2 · 2→MAJ-20 · 3→MAJ-21 · 4→NIT-1 · 5→NIT-45 · 6→MAJ-3 · 7→NIT-46 · 8→NIT-27 + MAJ-17
Stage 9 — style (S9): 1→MAJ-11 · 2→MAJ-11 · 3→MAJ-22 · 4→MAJ-23 · 5→MAJ-24 · 6→BLK-1 · 7→MAJ-17 · 8→NIT-24 · 9→NIT-39 · 10→NIT-38 · 11→MAJ-15 · 12→NIT-40 · 13→NIT-41

(ZO-4 splits into its two defects — the A1 §2.7 citation and the line-anchor drift; IR-10 similarly covers MAJ-9 and MAJ-10 items; CB-8's O-C1 half → NIT-27, O-C6 half → MAJ-17.)

## Suggested triage order for the spec owner

1. **Before the C1 note is critiqued**: BLK-2 (address space), MAJ-22 (C-7 predicate), MAJ-20 (C-4 key), MAJ-6 (drop or justify C-3), MAJ-8 (re-pin B v0.4 + C-B1 register).
2. **Before package routing starts**: BLK-1 (entry flow + initial generation), MAJ-2 (derived-asset acceptance), MAJ-5 (characters seeding), MAJ-11 (test/package gate alignment), MAJ-12 (command table).
3. **With the C6-C9 notes**: MAJ-1, MAJ-3, MAJ-4, MAJ-13, MAJ-15, MAJ-16, MAJ-21, MAJ-23, MAJ-24.
4. **Reference sweep (mechanical)**: MAJ-9, MAJ-10, all cross-reference/name nits (1-12).
5. **Template sections**: MAJ-18, MAJ-19 `[format]` — follow B v0.4 §15/§16 conventions; cite master §17/§18 where they already rule.

## Methodology

Eleven fresh-context reviewers across five sequential stages (zoom-out, comprehension, design+structural+style critics, intermediate zoom-out, implementation-readiness+codebase-details+style), each spawned as a registered EGM plugin agent with read-only tools; no reviewer saw another's output except the Stage 8 zoom-out, which received all three prior reports by design. The main context (this orchestrator) collected, deduplicated and consolidated; no findings were resolved and the target document was not modified. Consolidation merges findings that name the same underlying defect (cross-stage duplicates counted once); severity is the strongest verified rating with the rationale preserved in the stage reports. `[format]` marks items that only ask for a section the EGM feature-spec template expects.
