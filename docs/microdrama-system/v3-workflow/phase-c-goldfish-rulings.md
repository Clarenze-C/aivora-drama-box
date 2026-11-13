# Phase C Goldfish rulings — GLM (13 Nov 2026)

Input: `phase-c-review/consolidated_review_report.md` (2 Blocker / 27 Major / 46 Nit) against
`phase-C-spec.md` v0.1. Every ruling is a **GLM ruling, Opus re-check Mon**. Nothing below changes
`SPEC-v3.md`, `DECISIONS.md` or an operator decision; the two items that need the operator are marked
and queued. No acceptance row is weakened.

## Blockers

- **BLK-1 — ACCEPT, with Stage-8 steering.** Initial candidate generation = a bounded batch of ordinary
  `cast_v3.generate` job rows enqueued at **setup-budget approval** (no fourth operator verb, no batch
  orchestrator; fairness batching bounds dispatch). Pin: **3 candidates per root item** (master §4.4
  "2–3" resolved to 3 for forecast/metering stability); **one job emits one candidate**; the work-ID
  retry segment is renamed `<gen_seq>` (no collision with the jobs retry vocabulary). `derive_pick_items`
  and the STORY_LOCKED→CASTING transition are claimed by C2/C4 and named in §1.2/§4 + a C-T3 clause.
- **BLK-2 — ACCEPT, with Stage-8 steering (the C-B1 pattern).** Map where semantics are true:
  FACE→FACE, OUTFIT/APPEARANCE_STATE→WARDROBE, LOCATION_MASTER/COVERAGE→LOCATION,
  VOICE_NEUTRAL→VOICE. Extend the two CHECKs (`reference_versions.ref_kind`,
  `identity_lock_assets.asset_kind`) with honest values for the rest (PROP, EXTRAS_LOOK, MUSIC_LIB,
  SFX_LIB, and SHEET_VIEW/EXPRESSION stay on FACE per the mapping table the spec must now carry), via
  C-7's version-aware constraint pattern so V1 rows/writers keep the five-kind vocabulary. Pin
  ref_key namespacing (`face:<char>`, `sheet:<char>:<view>`, …) so same-ref_kind candidate sets never
  silently merge. Library items are **reference_versions rows** (drop C-2's `candidate_kind ASSET`
  inconsistency); their asset linkage is by content hash at lock.

## Majors

| ID | Ruling | Direction |
|---|---|---|
| MAJ-1 | ACCEPT | Add the Approve condition: every speaker has a REGISTERED, rights-approved neutral clip; VOICE item lifecycle = the intake job. |
| MAJ-2 | ACCEPT (Stage-8 steering) | Per-pick_kind human-pick vs derived table; derived acceptance = bulk operator action appending session-marked `cast_pick_votes` rows (one mechanism, two policies); split the `required` flag's meanings; align C-T3. |
| MAJ-3 | ACCEPT | Every attempt rotates the seed → distinct cache input; fake provider varies bytes by seed; C3 wraps `GenerationAdapter` (season/step_04 scope) reusing `check_rights`/`build_image_request`; the UNIQUE stays. |
| MAJ-4 | ACCEPT (Stage-8 steering) | Pin `st_dev/st_ino`, fstat on every acquisition, typed BLOCKED on mismatch; inode pinned in A's `provider_qualifications`; no watchdog. |
| MAJ-5 | ACCEPT (Stage-8 steering) | `derive_pick_items` (C2) upserts `characters` keyed by character demand ID; reference B's promotion facts, no lineage table. |
| MAJ-6 | ACCEPT — drop C-3 | Dependency edges are a computed closure over `cast_pick_items` (delivered to A4's DependencyProvider); no new table/migration. |
| MAJ-7 | ACCEPT | Voice byte validation = C's own profile check extending `references/media.py` (`wav_media_info`, `verify_generated`), ffmpeg as the isolated-decode subprocess; note that the binder's validator lands with D's T031 merge and must agree. |
| MAJ-8 | ACCEPT | Re-pin B to v0.4; add a C-B1-style contract-crossing register (jobs.queue CHECK via C-8, identity_locks NOT NULLs via C-7, the BLK-2 CHECK growth). |
| MAJ-9 | ACCEPT | Fix the two misattributions (phase-A-spec §2 item 7; phase-A §7.1 / A3 note §3.4); state the naming convention once. |
| MAJ-10 | ACCEPT | Mechanical ref sweep: §3→§8/§11, O-C7, master §12.6 named explicitly. |
| MAJ-11 | ACCEPT | Re-gate: C-T3/C-T4 clauses move to C9 (V3-AT-5 clauses pass at C9); C-T14 split per package; C-T12 split provenance/inspection halves (inspection half gated at C10). |
| MAJ-12 | ACCEPT | Add the command table (allowed states, prerequisites, events, replay identity for vote/reroll/generate_next/wardrobe edit/audition/upload/import_cast); register the two A-contract deltas (`pick` RevisionTargetKind growth; lock-busy DeferReason). |
| MAJ-13 | ACCEPT | Specify quarantine storage (bucket prefix + object-key column on C-6; QUARANTINED rows survive restart and are re-scanned). |
| MAJ-14 | ACCEPT — C8 gets a design note | C8 (YuE2 library) is routed **pre-critique note first**; the note pins the recipe, host, composition (track counts/durations/loop targets) and the fake adapter's unit counts. Spec keeps a placeholder that cites the note. |
| MAJ-15 | ACCEPT | Define pick-screen activation (season-scoped, per category, opened by CASTING entry, closed at lock/review); state how it registers as "waiting for you" against A1's six gate types (pick screens are not gate_activations). |
| MAJ-16 | ACCEPT | Deterministic ranking pinned: normalized tag-overlap score + stable tie-break (id); 2-vs-3 = top-3 with a flag if score gap < ε; the formula lives in the C6 note. |
| MAJ-17 | ACCEPT | O-C6 recorded as decided; "discarded at lock" = losing candidates stay as versions, excluded from lock membership, nothing deleted. |
| MAJ-18 | ACCEPT `[format]` | Add Alternatives Considered per B §16 (the six single-path choices listed by the reviewer). |
| MAJ-19 | ACCEPT `[format]` | Add Risks & Limits per B §15 with the reviewer's risk list + mitigations + master §18 pointer. |
| MAJ-20 | ACCEPT | `NULLS NOT DISTINCT` on C-4's unique key (PG15+ is the deployed floor). |
| MAJ-21 | ACCEPT | Adopt-if-present semantics: episodes created at STORY LOCK are stamped by §8 step 5; only extension episodes adopt at insert; the typed `IdentityLockRequired` path stays for V1. |
| MAJ-22 | ACCEPT | C-7 predicate rewritten against `seasons.workflow_version = 'v1'` (A1 0028); state the schema_version V3 lock rows carry. |
| MAJ-23 | ACCEPT | Exact preimage per member class (picks: as today; derived: asset content hashes + kind; voice: `normalised_sha256`); STORY binding source named (B's `StoryLockBindingV3`). |
| MAJ-24 | ACCEPT | Named field: B's `CharacterProfile.visual_lock.sheet_views` (add to B's contract via the C-B1 register if missing) with a deterministic extraction fallback. |
| MAJ-25 | ACCEPT | Coverage items created by a rerun-safe second pass after their master pick exists (idempotent); view names enumerated (reverse, tighter defined). |
| MAJ-26 | ACCEPT | SUPPORTING expressions = (neutral, signature) enumerated. |
| MAJ-27 | ACCEPT | Split the §10 row; both work-ID patterns given. |

## Nits (grouped)

- **N1–12 (references/names/provenance): ACCEPT** — mechanical sweep in v0.2 (anchors, bridges,
  naming, links, erratum request for master §4.4.4 items 3-4 routed to Opus Monday, not edited by GLM).
- **N13–24 (wording/consistency): ACCEPT** — mechanical.
- **N25: ACCEPT** — human-check fallback rule applies to OCR/branding and vocal-leakage too (no detector
  plumbing before detectors exist).
- **N26: ACCEPT** — `import_cast` split into a trailing C10-adjacent package (after C9), shrinking C9.
- **N27 + O-C1: ACCEPT — operator item.** Neutral-source intake is a DECISIONS "decide before phase C"
  item still open → **OPERATOR QUEUE** (needed before C6/C7 build).
- **N28–31: ACCEPT** — trace-table completions; route vocabulary constrained (nest under /cast/).
- **N32: ACCEPT** — zip key pinned to B's character demand key; UI shows the expected filename.
- **N33: ACCEPT** — likeness inspection targets the current selected candidate set.
- **N34: ACCEPT — operator nod needed.** V1 `create_episode` keeps no lock (permanent carve-out) →
  recorded in OPERATOR QUEUE for the operator/Opus Monday.
- **N35–38: ACCEPT** — orphaned pick items archived not-required; forecast = gate-blocked while
  `image_price` unknown (O-C4 resolved: block, don't estimate); territories default WORLDWIDE for O-11
  attestation; fewer-than-2 shortlist = flag + allow 1.
- **N39–43: ACCEPT** — C-T1 baseline = committed generated code regen diff; `botnoi-refresh:<date>` =
  calendar day (Asia/Bangkok), same-day rerun replaces by logical_work_id; exact event names listed;
  music+sfx collapse to one lane with a one-sentence justification retained; missing lock file =
  typed WAITING_PROVIDER with operator visibility; hold span = submit through final poll.
- **N44: ACCEPT** — Pick is the single primary action on the picks grid.
- **N45: ACCEPT** — StateEvent stays per-episode with resolver continuity (no season wrapper); shape
  pre-made in the C5 note.
- **N46: ACCEPT** — CSV field list corrected (leading `source` column).

## Apply

Fold into **phase-C-spec.md v0.2** (job `dramabox:c-spec-v02`, docs only, launches when a GLM slot
frees): both Blockers with their steering, all 27 Majors, the grouped Nits. Two new open questions are
operator items and must NOT be resolved in the spec (O-C1 neutral-source intake; V1 lock carve-out) —
listed as OPEN (OPERATOR). The C8 note-first routing goes into §12's package table.
