# B1 design note: V3 story records, stores, prompt registry, and the B contract base

**Version 0.1 DRAFT, 14 Nov 2026. Author: GLM (design note only; one file, no code).**
Awaiting the Codex pre-code critique (phase-B §11 B1: "critiqued first"); nothing here builds until
the note is accepted and A0–A3 have shipped.

**Binding inputs:** [phase-B-spec.md](phase-B-spec.md) **v0.6 (ACCEPTED)** §0–§13, esp. §2/§2.1–§2.4,
§5.4, §7, §9, §11 (B1 row), §12 (B-T1/B-T2); [phase-A-spec.md](phase-A-spec.md) v0.3 §1–§7;
[A1-design-note.md](A1-design-note.md) v1.4 §2–§6, §9; [A2-design-note.md](A2-design-note.md) v1.3
§2.2, §4, §11 OQ-2; [A3-design-note.md](A3-design-note.md) v1.3 §1–§3, §5.2;
[phase-A0-spec.md](phase-A0-spec.md) v0.4 §5.1/§5.6; [SPEC-v3.md](SPEC-v3.md) v0.4.6 §4.1–§4.3, §15;
[DECISIONS.md](DECISIONS.md) (O-B1..O-B6 answers recorded in phase-B §13; the 12 Nov "D2 revised
again" one-neutral-voice rule). Style model: the accepted A-phase notes' chain shape.

**Citation convention (D4, C-B1):** "phase-B §x" = `phase-B-spec.md`; "A1 §x"/"A2 §x"/"A3 §x" = the
design notes; "phase-A §x" = `phase-A-spec.md`; "master §x" = `SPEC-v3.md`. Code references are
relative to `microdrama/`: `S/` = `src/microdrama/`, `M/` = `migrations/`, `X/` = `tests/`.

**Facts:** re-verified read-only on `feat/microdrama-m0-m4` @ `a34a9ff` (the applied migration tail,
the V1/V2 contract anchors, the store and runtime shapes, and every consumer module named in §4
below). Where this note cites an A-phase object that is specced but not yet merged, the citation
names the note section that defines it.

---

## 0. Scope, prerequisites, and the migration-tail re-audit

**B1 builds** (phase-B §11 B1 row): the V3 record models + `V3ProductionLimits` + vocabularies —
typed beat effects, the generation-round identity store, the seam's `reserves_growth`, and the
ledger sibling that **reuses** the existing `PayoffDebt.debt_id` (`S/contracts/v2.py:206`, nothing
added, PB5-5); `v3_story_documents` + `StoryV3Store`; `v3_episode_story_bindings` (both fence
columns); the readers + `WORKFLOW_MISMATCH` guards (C-M10); the §2.4 deltas (D2's contract code,
`V3DecisionCommand.target`; D5 registered); the B1 LLM prompt registry (PB-6); the five
`story_v3.*` job-type registrations (C-M20); the contract bump (V1/V2 artifacts byte-identical).

**B1 does not build:** any command's route/handler (B2/B5), any prompt text (B2–B5), any job handler
(B2–B5), the D5 completion seam itself (B2), the UI (B6).

**Migration-tail re-audit (phase-B §11: "B's migrations are allocated in the B1 note after
re-auditing the tail").** Verified on the branch @ `a34a9ff`:

| Fact | Evidence |
|------|----------|
| The applied tail on `feat/microdrama-m0-m4` is **0025** | `M/` ends at `0025_t045_billing_finality.sql` |
| 0026 (T031) exists only staged in the T031 worktree | `.scratch/t031-fix3-worktree/microdrama/migrations/0026_t031_benchmark_experiments.sql`; not in `M/` |
| A0 (0027) and A1–A3 (0028–0035) are **accepted but not merged here** | no `S/contracts/v3.py`, no `S/core/v3_*.py` (A1), no `story_v3/` package; A1 v1.4 header records the same tail |

**Consequence (a prerequisite, not a blocker):** phase-B §11's prerequisite — "A1–A3 shipped (gates
green, migration tail at 0035; C-N18)" — is **not yet met on this branch**; the B1 build starts only
after A0–A3 land (0026 T031 → 0027 A0 → 0028–0031 A1 → 0032–0034 A2 → 0035 A3). This note allocates
**symbolic** migrations `B-1..B-4` with **expected** real numbers 0036–0039; the builder re-audits
the tail at build time and allocates contiguously from `0036`. If A-phase allocations change first,
the B numbers shift **as a block** (order and purposes do not); applied bytes are never edited
(`S/persistence/migrate.py` checksum discipline, A1 §1).

**Deviations considered (C-N22 checklist item): none.** C-M11 is honoured — `SeasonBibleV3` wraps
the existing `SeasonBible` (`S/story/models.py:63`) and `RichBible` (`S/story/script_maker.py:206`)
for the sections they already cover, plus the master §4.2 sections, with no deviation from the
master's field list.

## 1. Migration allocation (symbolic; expected 0036–0039)

One purpose each, A1 §1 style. All four create only new objects; none touches an applied table's
bytes (the single existing-table edit B needs — none — is deliberately empty; D2 needs no DDL, §5).

| # | Expected | File | Purpose |
|---|----------|------|---------|
| **B-1** | 0036 | `0036_v3_story_documents.sql` | `v3_story_documents` + guards + the `contract_type` allowlist CHECK + the current-row partial unique index |
| **B-2** | 0037 | `0037_v3_generation_rounds.sql` | The generation-round identity store (PB-2) |
| **B-3** | 0038 | `0038_v3_llm_prompts.sql` | The B1 LLM prompt registry (PB-6) |
| **B-4** | 0039 | `0039_v3_episode_story_bindings.sql` | `v3_episode_story_bindings` with both fence columns (phase-B §5.4, PB-10) |

Ordering: B-1..B-4 are mutually independent (no forward references); they land after 0035 (A3).
Guard pattern everywhere: `md_forbid_mutation` (row DELETE + statement TRUNCATE), the
`md_forbid_non_integer_numbers`-style integer guard on INSERT OR UPDATE via the 0026-style DO loop
over the new tables, and `md_immutable_columns` on identity columns — the A1 §2 pattern; the catalog
tests (`X/integration/persistence/test_schema_catalog.py:22-37`, `relkind='r'` only) then cover every
new table automatically. `EXPECTED_TABLES` (`X/integration/persistence/test_migrations.py:32`) grows
by the four names; the fresh-create tail assertions extend to B1's last applied number.

## 2. Records: identity, vocabulary, DDL

### 2.1 The namespace and the identity convention

One namespace constant, pinned in `S/contracts/v3_story.py` (new module, §2.3):

```python
STORY_V3_NS = uuid5(NAMESPACE_URL, "https://microdrama.invalid/story/v3")
```

This matches the codebase convention verbatim — the V2 script maker's `_NS`
(`S/story/script_maker.py:64`) is `uuid5(NAMESPACE_URL, "https://microdrama.invalid/story/script-maker/v2")`
— so V3 IDs are reproducible across builds and disjoint from every V2 namespace.

**Identity (phase-B §2):** `record_id = uuid5(STORY_V3_NS, "<type>:<planning_scope_id>[:<key>]")`,
where `planning_scope_id` is the season ID or the extension ID (phase-B §8) and `<type>` is the
short slug below. Regeneration advances `version` and keeps the ID (the V2 convention,
`S/story/script_maker.py:73-75`: "revisions advance the version, not the ID").

| contract_type (slug) | record_id derivation | Model (§2.3) |
|----------------------|----------------------|--------------|
| `intake` | `intake:<scope>` | `ConceptIntakeV3` |
| `proposals` | `proposals:<scope>` | `ProposalRoundV3` (versions = all rounds ever written for the scope; the per-intake `round` field resets after a Reject — C-N7) |
| `bible` | `bible:<scope>` | `SeasonBibleV3` |
| `character` | `character:<scope>:<character_key>` | `CharacterProfile` (standalone records for **promoted** profiles, phase-B §4.2; embedded copies inside the bible are not separate rows) |
| `episode` | `episode:<scope>:<n>` | `EpisodePackV3` |
| `continuity` | `continuity:<scope>:<n>` | `ContinuityStateV3` |
| `critic` | `critic:<scope>:<n>` / `critic:<scope>:season` | `CriticReportV3` |
| `demands` | `demands:<scope>` | `SeasonDemandListV3` |
| `seam` | `seam:<scope>` | `ExtensionSeamV3` |
| `story-lock` | `story-lock:<scope>:<content_revision>` | `StoryLockBindingV3` |

The slug list is exactly the **enforced** `contract_type` CHECK vocabulary (§2.2) — one vocabulary
serves the CHECK, the uuid5 derivation, and `StoryV3Store`'s model registry (D6, §5).

**Embedded identities** (not standalone rows, but pinned here because D2 targets and later packages
reference them):

- `SeasonProposalV3.proposal_id = uuid5(STORY_V3_NS, "proposal:<scope>:<generation_round>:<slot>")`
  (PB-2: includes the generation-round identity, so IDs never repeat across intakes or retries).
- `LogicalDemand.demand_id = uuid5(STORY_V3_NS, "demand:<scope>:<kind>:<logical key>")` (phase-B
  §4.3; stable across revisions).

### 2.2 Migration B-1 — `v3_story_documents`

Mirrors `v2_contract_documents` (`M/0019…sql:4-20`) — whose class-name allowlist and
`payload->>'schema_version' = '2.0'` CHECK are exactly why V3 must not widen it (O-B6, phase-B §16) —
with slugs and the `'3.0'` schema version:

```sql
CREATE TABLE v3_story_documents (
  contract_type       text NOT NULL CHECK (contract_type IN
                        ('intake','proposals','bible','character','episode','continuity',
                         'critic','demands','seam','story-lock')),
  record_id           uuid NOT NULL,
  version             integer NOT NULL CHECK (version >= 1),
  payload             jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'
                                           AND payload->>'schema_version' = '3.0'),
  content_sha256      text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
  planning_scope_id   uuid NOT NULL,   -- the season id or the extension id; no FK: extensions
                                       -- are created later (A1 0030), and the scope-resolution
                                       -- rule is enforced in Python at write time (§8)
  current             boolean NOT NULL DEFAULT true,
  created_at          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (contract_type, record_id, version)
);
CREATE UNIQUE INDEX v3_story_documents_one_current
  ON v3_story_documents (contract_type, record_id) WHERE current;
CREATE TRIGGER v3_story_documents_identity_immutable BEFORE UPDATE ON v3_story_documents
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('contract_type','record_id','version',
                                                     'created_at');
CREATE TRIGGER v3_story_documents_no_delete BEFORE DELETE ON v3_story_documents
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
-- + statement TRUNCATE refusal and the integer-number guard via the §1 DO loop.
-- Row UPDATE is legal only for the current-flag flip and updated_at; the payload and
-- content_sha256 are frozen per (type, id, version) by the store + the immutable trigger above.
```

Differences from the V2 mirror, each pinned: (a) slugs instead of class names (§2.1); (b)
`content_sha256` (the V3 field name, phase-B §2) instead of `payload_sha256`; (c)
`planning_scope_id` explicit, so scope-keyed reads never parse it out of `record_id`; (d) no
`rights_*` columns — B owns no rights-bearing assets (rights records are C's, master §15 C row).

**`StoryV3Store`** (new, `S/story_v3/store.py`) mirrors `StoryV2Store` (`S/story/v2_store.py:17`):
`save_bundle(records)` appends a group atomically on the **caller's** transaction, refusing duplicate
`(type, id, version)`, verifying each record's canonical hash before write (`verify_v2_record_hash`
discipline, `S/contracts/v2.py:87`), enforcing **consecutive versions** (the new version must be
exactly `current.version + 1`, or `1` for a new record — checked under the caller's held scope-track
lock, §8), and flipping the predecessor's `current` flag in the same transaction; `read(type, id,
version=None)` re-validates the model **and** re-verifies the stored hash on every read, refusing a
mismatch (`S/story/v2_store.py:50-56` is the mirrored shape). The model↔slug mapping is one registry
dict; a payload whose slug is unknown to Python is refused (the CHECK is the SQL backstop).

### 2.3 The record models (`S/contracts/v3_story.py`, new)

All V3 story records extend one base mirroring `V2Record` (`S/contracts/v2.py:45-85`): `record_id`,
`version`, `content_sha256`, `created_at`/`updated_at`, `schema_version = '3.0'`, the same
seal/hash-match machinery (`seal()`, `calculated_content_sha256()`, `content_hash_matches()`), and
append-only semantics. Field-level content per record = phase-B §2/§2.1 **verbatim**; this section
pins only what that table leaves to B1:

- **`V3ProductionLimits`** (frozen config, V3 records only — the V1 `ProductionLimits`
  (`S/contracts/primitives.py:54`) is never edited, AT-19/V3C-5):

  | Rule | Value |
  |------|-------|
  | `episode_count` (intake band / LOCK band) | 20–30; a proposal's `episode_count` **must equal** the intake's `requested_episode_count` (CRITICAL otherwise, C-M15) |
  | episode length | target `120_000` ms; band `105_000–135_000` incl. recap ≤ `10_000` and CTA ≤ `5_000` |
  | distinct speakers per episode | ≤5, counting off-screen (MA19, O-12) |
  | speakers per beat | ≤2 (phase-B §1.6) |
  | main cast briefs per proposal | 3–6 |
  | active locations per episode | 3, counted as distinct `location_key` values in `scenes[]`, recap excluded (O-B1, C-M13c) |
  | `emotion` | `NEUTRAL`, `HAPPY`, `SAD`, `ANGRY`, `FEARFUL`, `SURPRISED` (O-B3; closed — out-of-enum rejected, B-T7) |

- **Typed beat effects (PB-12):** `BeatEffect` is a tagged union — `WARDROBE_CHANGE{subject_character_id,
  target_outfit_demand_id}` and `PAYOFF_SETTLEMENT{debt_id, resolving_action}`. `debt_id` values
  reference the ledger's stable `PayoffDebt.debt_id` (`S/contracts/v2.py:206`) — the sibling reuses
  it unchanged; the V3 pack's `payoff_debt` prose is display-only (PB5-5). The seam's thread
  `status` is **derived** from settlement effects, never stored as a hand-set label (C-M9); the seam
  carries `reserves_growth: bool` explicitly (PB-12).
- **`ContinuityStateV3` gains `source_pack_version` + `source_pack_sha256`** — the PB-9 pin: the
  state names the pack version that produced it. `StoryLockBindingV3` hashes each continuity record
  by `(record_id, version, content_sha256)` in episode order, and binding-time verification checks
  `continuity(n).source_pack_version == bound pack(n).version` for every *n* — a standalone
  continuity record can never sit outside the hash as an unqualified "last stored" authority, and a
  later re-write of continuity (a new version) visibly breaks the match instead of silently changing
  what a lock bound.
- **`CharacterProfile`** standalone records (promoted profiles) key on `character:<scope>:<key>`
  (§2.1) and carry the phase-B §2 field list, including the **voice descriptor** required when the
  character speaks, and `tier`.
- **Reused V2 shapes** embed as V3 models with the same validators: `SecretEntry`
  (`S/contracts/v2.py:276`), `PayoffDebt` (`:206`), `SeasonEscalation` (`:213`), `StoryTime`
  (`:284`). The V3 `validate_season_story_ledger` sibling binds the ledger to the bible + LOCK
  authority at bible time and to the packs once they exist (PB-13's population rule).
- **`EpisodePackV3`** carries phase-B §2.1 exactly: `lock_authority` (the approved proposal's
  `content_sha256` + LOCK approval event ID), logical demand IDs everywhere (no asset/voice/
  wardrobe-assignment IDs), `estimated_runtime_ms` in `105_000–135_000`, **no** `scoped_map_only`
  (R-3.1), `cta` with no `template_id`.

**Contract bump (A1 §4 loop, extended):** the new models generate under `schemas/v3` + `examples/v3`
through A1's manifest loop with `V3_STORY_VALID_BUILDERS` beside `V2_VALID_BUILDERS`
(`S/contracts/examples.py:694`); validation manifest discovery learns them; V1/V2 generated bytes are
asserted byte-identical to the accepted A-phase baseline (A1's frozen-baseline test extended to the
B1 diff — drift fails the build).

### 2.4 Migration B-2 — the generation-round identity store (PB-2)

Phase-B §2 pins the semantics (monotonic per scope, never reset, included in proposal IDs and every
B semantic key); B1 pins the storage:

```sql
CREATE TABLE v3_generation_rounds (
  planning_scope_id uuid PRIMARY KEY,
  generation_round  integer NOT NULL CHECK (generation_round >= 1),
  updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER v3_generation_rounds_scope_immutable BEFORE UPDATE ON v3_generation_rounds
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('planning_scope_id');
-- + no-delete, no-truncate, integer-number guards (§1 DO loop).
```

A **counter table, not an append-only document** — it is coordination state, not story content; the
guards make it undeletable and its number integral. Rows are created lazily (`INSERT … ON CONFLICT
DO NOTHING`, first value 1) inside the same transaction that first needs the identity.

**Advance points (binding, from phase-B §2/§5.2/§9):** (1) `replace_v3_intake` — "advances the
generation-round identity" (phase-B §9 row); (2) a **terminal-failure retry**, before enqueueing the
replacement job — this is what makes the replacement's execution-attempt key (the semantic key
including the generation-round identity, phase-B §7.1) fresh where the round number is unchanged.
**Not** advanced on: a Revise round (the round number already freshens the semantic key), transport
recovery (retains the call identity, §7.4), or repair rounds (numbered). Both advance points run
under the scope track lock FOR UPDATE (§8), so `UPDATE … SET generation_round = generation_round + 1
RETURNING` is race-free, and the returned value is stamped into the enqueued job's semantic key and
any proposal IDs the round mints.

### 2.5 Migration B-3 — the B1 LLM prompt registry (PB-6)

Asset-independent, own storage (phase-B §7.3); the V2 render `PromptManifest`
(`S/contracts/v2.py:773`) — whose validator requires shot bindings with eligible asset references —
and the V2 storage stay unchanged (B-T5, O-B6):

```sql
CREATE TABLE v3_llm_prompts (
  prompt_id      text NOT NULL CHECK (prompt_id ~ '^[a-z0-9][a-z0-9_.\-]{0,119}$'),
  version        integer NOT NULL CHECK (version >= 1),
  canonical_text text NOT NULL CHECK (canonical_text <> ''),
  text_sha256    text NOT NULL CHECK (text_sha256 ~ '^[0-9a-f]{64}$'),
  owner_package  text NOT NULL CHECK (owner_package IN ('B2','B3','B4','B5')),
  created_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (prompt_id, version)
);
CREATE TRIGGER v3_llm_prompts_append_only BEFORE UPDATE OR DELETE ON v3_llm_prompts
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
-- + statement TRUNCATE refusal and the integer-number guard (§1 DO loop).
```

**Mechanism:** each prompt is a module constant in its owning package (`S/story_v3/prompts_*.py`);
registration is an idempotent `INSERT … ON CONFLICT (prompt_id, version) DO NOTHING` followed by a
byte-compare of the conflicting row — a different text under the same `(prompt_id, version)` is a
`Conflict` (a prompt never silently changes meaning; a change is `version + 1`). Lookup:
`resolve_prompt(tx, prompt_id, version) -> (canonical_text, text_sha256)`; every `FrozenLlmCall`
B mints carries the pinned prompt ID + sha256 (A0 §5.1; phase-B §7.4), and B's tests assert the
registry contains each referenced prompt (B-T6 clause, prepared here). The `owner_package` CHECK is
advisory provenance (which package's diff introduced it), not an enforced workflow — it keeps the
registry auditable against §7.3's ownership table.

### 2.6 Migration B-4 — `v3_episode_story_bindings` (phase-B §5.4, PB-10)

```sql
CREATE TABLE v3_episode_story_bindings (
  episode_id                        uuid NOT NULL REFERENCES episodes(id),
  season_id                         uuid NOT NULL REFERENCES seasons(id),
  episode_number                    integer NOT NULL CHECK (episode_number >= 1),
  pack_record_id                    uuid NOT NULL,
  pack_version                      integer NOT NULL CHECK (pack_version >= 1),
  pack_sha256                       text NOT NULL CHECK (pack_sha256 ~ '^[0-9a-f]{64}$'),
  story_lock_approval_event_id      uuid NOT NULL REFERENCES approval_events(id),
  content_revision                  integer NOT NULL CHECK (content_revision >= 0),
  story_lock_scope_revision         integer NOT NULL CHECK (story_lock_scope_revision >= 0),
  created_at                        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (episode_id, content_revision)
);
CREATE TRIGGER v3_episode_story_bindings_append_only BEFORE UPDATE OR DELETE
  ON v3_episode_story_bindings FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
-- + statement TRUNCATE refusal and the integer-number guard (§1 DO loop).
```

The two revision columns are **distinct fences** (PB-10): `content_revision` = the episode track's
fence value at approval; `story_lock_scope_revision` = the originating STORY LOCK scope revision.
Later amendments (A4) append rows at the new `content_revision`; the current binding is the row at
the episode's current `content_revision`. Approval never reseals or modifies the approved pack — the
link lives only here. Writes happen inside the B5 STORY LOCK decision transaction (§8).

## 3. Field mapping (C-N5 obligation: every field of the three source models)

Phase-B §2.3's mapping extended to **every** field, with the verified source anchors. "Dropped"
always carries a reason. V3-new fields are omitted from these tables (they are phase-B §2/§2.1).

**V1 `EpisodePlan` (`S/contracts/season.py:313`) → `EpisodePackV3`:**

| V1 field | V3 destination |
|----------|----------------|
| `episode_id` | bound at STORY LOCK only, via `v3_episode_story_bindings` (PB-10) |
| `season_id` | `planning_scope_id` (season or extension scope, phase-B §8) |
| `approved_scope_hash` | `lock_authority` (proposal `content_sha256` + approval event ID) |
| `episode_number` | `episode_number` (identity before rows exist) |
| `title_th` / `title_en` | `titles` TH/EN |
| `synopsis` | `synopsis` |
| `target_duration_ms` (validator 180–300 s, `:333`) | `duration_target_ms = 120_000`; enforced band `estimated_runtime_ms` 105–135 s (V3 limits) |
| `featured_character_ids` | `scenes[].visible_cast[]` with framing (C-M13b extends speakers to extras roles) |
| `location_ids` (episode level) | per-scene `location` demand ID + light state |
| `planned_beats` | `scenes[].beats[]` (`beat_id`, text, effects, ≤2 speakers) |
| `planned_reveals` | `beats[].reveals[]` (secret IDs, ledger-bound) |
| `cliffhanger` | `cliffhanger_beat_id` (a beat of the last scene) |
| `canon_version` | dropped — V3 canon authority is the LOCK/STORY LOCK approval chain, not a counter |

**V1 `Script` (`S/contracts/season.py:366`) with `Scene` (`:358`) and `DialogueLine` (`:346`):**

| V1 field | V3 destination |
|----------|----------------|
| `script_id` / `version` | dropped — the pack is one append-only document; versions are the record's |
| `episode_id` / `approved_scope_hash` | as above |
| `canon_version` | dropped (as above) |
| `scenes[].scene_id` | `scenes[].scene_id` |
| `scenes[].location_id` / `summary` | location demand ID + light state / dropped (the pack's beats carry the content) |
| `scenes[].lines[]` | `lines[]` (episode-level, beat-linked) |
| `DialogueLine.line_id` / `speaker_character_id` | `line_id` / `speaker` (character **or** extras-role demand ID, C-M13b) |
| `DialogueLine.voice_id` | dropped — the writer reads no voice table (V3C-4); one neutral voice **demand** per speaker is derived (phase-B §2.2/§4.3) |
| `text_th` / `text_en` | `text_th` / `text_en` |
| — (absent in V1) | `text_zh`, `emotion`, `delivery_note`, `off_screen` — V3-new |
| `estimated_duration_ms` | `estimated_ms` (from `estimate_line_ms`, `S/story/prompts.py:367`) |
| `actual_duration_ms` | dropped from planning — measured in D/E |
| `critical_terms` | `critical_terms[]` (V1 shape, `S/contracts/season.py:339`) |
| `estimated_runtime_ms` (script-level) | `estimated_runtime_ms` (band 105–135 s) |

**V2 `EpisodePack` (`S/contracts/v2.py:353`) with `EpisodeScene` (`:310`) and `PackBeat` (`:297`):**

| V2 field | V3 destination |
|----------|----------------|
| `episode_id` / `season_id` / `approved_scope_hash` / `episode_number` | as above |
| `duration_target_ms` (validator 180–300 s, `:357`) | `duration_target_ms = 120_000` (band via `estimated_runtime_ms`) |
| `character_logic[]` | `psychology[]` (start/end states per appearing principal **or supporting** character, C-M13a) + `ContinuityStateV3` psychology |
| `promise` / `escalation` | `promise` / `escalation` |
| `payoff_debt[]` (free text, `:361`) | retained prose, **display-only**; machine-checked debt references use the ledger's `PayoffDebt.debt_id` (`:206`, PB5-5) |
| `scenes[].story_time` | `story_time` (reuses `StoryTime`, C-N10) |
| `scenes[].location_id` (asset ID) | **logical** location demand ID + light state |
| `scenes[].visible_character_ids` (`:314`) | `visible_cast[]` with framing |
| `scenes[].prop_ids` | `props[]` (demand ID + holder + state; proof-prop flag in the demand list, C-N2) |
| `scenes[].wardrobe_assignment_ids` (V2 asset rows, `M/0019…sql` `SceneWardrobeAssignment`) | **logical** outfit + appearance-state demands for every visible character (asset binding is C's `CastBinding`) |
| `scenes[].beats[]` (`PackBeat`) | `beats[]` + `effects[]` (typed, PB-12) |
| `scenes[].dependency_scene_ids` / `state_in` / `state_out` | dropped — V3 continuity is the explicit `ContinuityStateV3` chain + deterministic critics, not intra-pack state deltas |
| `scoped_map_only` (`:363`, rule `S/story/script_maker.py:818`) | **absent by design** (R-3.1: every pack is full) |
| `record_id` / `version` / `content_sha256` / validity window | the V3 append-only document envelope (§2.2), same semantics |

## 4. Readers and `WORKFLOW_MISMATCH` guards (C-M10)

**The compatibility reader** (new, `S/story_v3/reader.py`): `read_episode_story(tx, episode_id) ->
EpisodeStoryView` returns the version-tagged view — `V1(EpisodePlan, Script)`, `V2(EpisodePack)` or
`V3(EpisodePackV3)` — resolved through `episodes.season_id → seasons.workflow_version` (A1 0028),
each payload validated under **its own** schema version and hash rules; V2 pack reads reuse
`read_v1_manifest` (`S/contracts/v2.py:1041`) where it applies. A missing V3 binding/episode row is
`NotFound`; a corrupt hash is `Conflict` (the store discipline). **A V1 or V2 consumer given a V3
episode raises `WORKFLOW_MISMATCH`** (phase-A §1) — enforced at the consumer entry points below, not
inside the reader (the reader itself is version-aware by contract).

**One pinned guard site per §2.3 consumer** (phase-B §2.3 requires the B1 note to confirm the qa
trio per module and pin exactly one site each — an existing A1 guard, a dispatch guard, or a new
module guard B1 adds). All modules verified present @ `a34a9ff`:

| Consumer (phase-B §2.3) | Pinned guard site | Class |
|-------------------------|-------------------|-------|
| D: `S/story/directing.py` (`compile_episode_pack`, `:101`) | new module guard: `require_workflow(expected='v1')` at `compile_episode_pack` entry, after the caller's episode read | B1 module guard |
| D: `S/references/v2_planning.py` (+ `v2_binding.py`, `v2_dispatch_context.py`) | new module guard at the planning entry (`validate_episode_reference_state` and the `V2ReferenceRepository` read paths) | B1 module guard |
| D: `S/rendering/routing.py` (`RoutingPolicy`, `:146`) | new module guard at the routing-policy entry the D compiler calls | B1 module guard |
| D: `S/qa/continuity_sources.py` (`_verified_doc`/`_current_script`, `:38/:76`) | new module guard at the module's tx-entry readers | B1 module guard |
| E: `S/editing/service.py` (`_claim` `:638`, `_persist` `:994`, `rebuild_caption_outputs` `:226` — A1 §7 inventory) | **existing A1 refusal guards** — B1 adds nothing | existing |
| E: `S/editing/edl.py` (`build_edl`, `:102`) | new module guard at `build_edl` entry | B1 module guard |
| E: `S/editing/captions.py` (`spot_caption_track`, `:49`) | new module guard at the caption-build entry | B1 module guard |
| F: `S/review/packages.py` (`store_release_package`, `:216`) | **existing A1 refusal guard** (A1 §7 boundary table) | existing |
| F: `S/review/intake.py` progress views | **existing A1 refusal guards** (`_status`/`_phase`/`_workbench`, A1 §7 inventory) | existing |
| F: `S/community/grounding.py` (`load_facts`, `:179`) | new module guard at `load_facts` (the tx entry; `validate_claims` is pure over its facts) | B1 module guard |
| qa trio: `S/qa/coverage.py`, `S/qa/comparison.py`, `S/qa/observation.py` | **dispatch guard** — pure functions over records already loaded inside job/review execution behind A1's replay guard (`S/workers/runtime.py:216`); no module guard added (phase-B §2.3's ruling) | existing dispatch |

New module guards follow A1 §7's shape: refusal after owner access, **before** projection or
package interpretation — `WORKFLOW_MISMATCH` (409), never a filtered-away NotFound. B migrates no
consumer (phase-B §2.3): the guards make the listed D/E/F entries refuse V3 rows until each owning
phase moves them to the V3 reader.

**Shared fixture (B-T2):** the guard inventory lives in one imported module —
`X/integration/v3/guard_inventory.py` holds the entry-point table (A1's A-T5 rows + the seven B1
rows above); A1's `test_discriminator.py` and B1's `test_guard_sites.py` both **import** it. No
re-edited copy of A1's A-T5; refusals never hard-code D/E/F future state (each site asserts only
"V3 episode → `WORKFLOW_MISMATCH`; V1 episode → unchanged behaviour").

## 5. The contract-delta register (D1..D6; C-B1, first-class deliverable)

The spec assigns D1..D5 (phase-B §2.4). D6 is **this note's addition** under the standing rule
("any B identifier that crosses an A-phase enforced contract is checked against that contract's
enforced vocabulary before the B1 note is accepted") — B1 itself creates enforced vocabularies that
B2–B6 will cross, so they are registered now.

| # | Delta | Contract touched | Mechanism / vocabulary match |
|---|-------|------------------|------------------------------|
| **D1** | Step keys `step_01` = Script Maker, `step_02` = bible, `step_03` = episodes | A2's `budget_steps` CHECK (`step_01..step_10`, `launch`, `episode_production`) and `md_reservation_step_rules` (A2 §2.2) | **Adopt; no CHECK amendment.** Verified against A2 §2.2's enforced trigger: `SEASON_SETUP` accounts admit reservations under `step_01..step_04`/`step_10`/`launch` — B's three keys are inside the enforced set. Pilot calls are unmetered (`llm.subscription`): **B writes no reservation and posts no charge**; when a metered adapter ships (O-5), B's flows name these keys against the `SEASON_SETUP` account. B1 builds no admission logic |
| **D2** | Decision-target kinds `PROPOSAL`, `EPISODE_PLAN`, `BIBLE_SECTION`, `SEAM`, `TIER` | A1's `RevisionTargetKind` + validators (A1 §4, `S/contracts/v3.py`) and `V3DecisionCommand`; targets are jsonb validated in Python (A1 §2.3), never a SQL CHECK | **Contract-code delta, no SQL DDL** (see OQ-1): `RevisionTargetKind` gains the five values; `V3DecisionCommand` gains an optional typed `target: RevisionNoteTarget | None = None` — **absent for A1's existing gates**, so A1's behaviour, note and build are not reopened (phase-B §2.4). Regenerated `schemas/v3` ship in B1's contract bump. Target-ID derivations (uuid5, §2.1's namespace): `PROPOSAL` → the slot's `proposal_id`; `EPISODE_PLAN` → the pack record `uuid5(STORY_V3_NS, "episode:<scope>:<n>")`; `SEAM` → `uuid5(STORY_V3_NS, "seam:<scope>")`; `BIBLE_SECTION` → `uuid5(STORY_V3_NS, "bible-section:<scope>:<section_path>")` over the dotted section path in master §4.2 Joey order (`premise`, `thesis`, `timeline`, `era_aesthetics`, `world_rules`, `locations`, `factions`, `characters`, `relationships`, `story_engines`, `production_rules`, plus the V3 sections `camera_package`, `palette`, `lighting_language`, `pacing_rule`, `ledgers`, `initial_continuity`); `TIER` → `uuid5(STORY_V3_NS, "tier:<scope>:<character_key>")`. Validation stays A1's: every target is checked at decision time against the **activation's recomputed binding units** (A1 §4/§5) |
| **D3** | `edit_tier` command-table row | A1 §6 command format | The full row is §7 below (actor, revision owner, prerequisites, supersede/reopen via A1's `supersede_gate`/`open_gate`, replay); **ships in B5** (C-M3) with the shared internal tier-update/revalidation operation (PB-5) |
| **D4** | Citation convention | — | This note's header (phase-B §2.4 D4); swept with the note |
| **D5** | B's caller-transaction completion seam | A1/A3 job lifecycle + lock order (runtime calls the handler first, finishes after — verified `S/workers/runtime.py:245` handler call, `:259` finish; `finish` at `S/core/jobs.py:676`) | **Registered here; ships in B2** (PB5-2): proposal completion + LOCK opening, incl. the B2 commit-boundary crash case; B3 uses it for bible completion + continuation; B4/B5 add the joins. B1 creates everything the seam persists into — `logical_work_id`/`replaces_job_id` (A1 0031), the document store (§2.2), the generation-round store (§2.4) — and **no** seam code |
| **D6** (B1-added) | B1's own enforced vocabularies for B2–B6 | new: `v3_story_documents.contract_type` CHECK (§2.2); `v3_llm_prompts` identity + `owner_package` CHECK (§2.5); the five `story_v3.*` job types (§6) and their enqueue/dispatch split; `STORY_V3_NS` + the uuid5 derivations (§2.1); `V3ProductionLimits` values (§2.3) | Registered so later B packages cross **this** note's enforced vocabularies the same way B crosses A's: a B2+ identifier touching any of these is checked against it before that package's build, and a change is a new register row, not a silent edit |

**Standing-rule compliance beyond the table** (phase-B §2.4): the LOCK Approve target and Revise
note targets ride D2 (validated against the activation's binding units, A1 §5); `edit_tier`'s
close/reopen rides A1's `supersede_gate`/`open_gate`; the continuation idiom rides A1's
`replaces_job_id` validation — one `logical_work_id` per replacement link (A1 §2.4) — so the round
number scopes the **semantic key**, never the logical work ID (§6).

## 6. Jobs: the five `story_v3.*` registrations (C-M20)

**B1 registers all five job types** (enqueue-allowed; handlers land per package) so B2's Approve can
enqueue `story_v3.bible` (B3's handler) and B4's last episode can enqueue `story_v3.season_critic`
(B5's) at their own gates. Registration = `JOB_SPECS` entries (`S/contracts/jobs.py:69`, the
generated-contract registry) + the dispatch-availability rule below. Queue: the existing
**PRODUCTION** lane (`QueueName.PRODUCTION`, `S/contracts/enums.py:242`; phase A added no lanes,
phase-B §7.2).

| Job type | Input model (extends `V3ScopedStepInput`, A3 §2.2) | Extra input fields | Handler ships |
|----------|------------------------------------------------------|--------------------|---------------|
| `story_v3.propose` | `ProposeStepInput` | `round` (per intake), `generation_round`, intake record ref | B2 |
| `story_v3.bible` | `BibleStepInput` | `round`, `generation_round`, `lock_authority` | B3 |
| `story_v3.promote_profile` | `PromoteProfileStepInput` | `character_key`, `generation_round` | B3 |
| `story_v3.plan_episode` | `PlanEpisodeStepInput` | `episode_number`, `round`, `generation_round`, `lock_authority`, `bible_version` | B4 |
| `story_v3.season_critic` | `SeasonCriticStepInput` | `round`, `generation_round`, repair origin + authorized episode set (PB-4) | B5 |

All carry `expected_content_revision` (the 0035 fence CHECK enforces its presence on `track`-bearing
rows; A3 §2.1) and `track='planning'`; `paid=False` (pilot calls are unmetered `llm.subscription`;
B posts no charge — D1). Owner module `story_v3`.

**Work identity and semantic keys (phase-B §7.1, restated as the enforced formulas):**
`logical_work_id` ∈ {`propose:<scope>`, `bible:<scope>`, `plan:<scope>:<n>`,
`profile:<scope>:<character_key>`, `season-critic:<scope>`}; `jobs.semantic_key`
(`M/0001…sql:78`, UNIQUE) = work id + round + **generation-round identity** — `plan` adds
`(scope, n, lock_authority, bible_version, round, generation_round)`. A Revise's round *k+1* differs by round; a terminal-failure retry differs by the
advanced generation round (§2.4); a deliberate re-plan therefore never dedupes to a no-op (C-M1),
and replacements chain through `replaces_job_id` under the unchanged `logical_work_id`.

**Dispatch availability (the C-M20 mechanism, pinned with the runtime's real behaviour).** Verified:
a claimed job whose type has no handler in the deployment **fails** — `Failed("NO_HANDLER")`
(`S/workers/runtime.py:237-241`). Between B2 (enqueue) and B3 (handler) that would burn a round and
project `BLOCKED (failed)` on healthy work. B1 therefore adds one V3-scoped claim-boundary rule: a
job whose type is **enqueue-registered but handler-unregistered in this deployment** is **not
claimable** — skipped like a queue the deployment does not serve, left QUEUED (`run_after`
untouched) until its package's deployment arrives. The rule applies only to B1-registry types with
`track IS NOT NULL`; a V1 job with no handler keeps today's `NO_HANDLER` failure byte-identically.
(See OQ-2.)

## 7. The command rows (phase-B §9; A1 §6 format)

`TrackService`/`StoryV3` command surfaces; human commands run through `IdempotencyService.execute`
with A1's §5 preflight seam (`NOT_AVAILABLE` before any write when a dependency is unshipped).
Replay: idempotency key (human) / semantic keys (system). Activation = the package that ships the
row's effect.

| Command | Actor | Scope / revision owner | Prerequisites | Effect (edges) | Writes · jobs · events | Activation |
|---|---|---|---|---|---|---|
| `submit_v3_intake(mode, idea_line, hints, requested_count)` | Operator (human session + CSRF) | season / — (via A2's `create_v3_season`) | `mode = TITLE` only (`TREND` → `MODE_UNAVAILABLE` **before any write**, C-N12); `idea_line` 1–300; `requested_count` 20–30 (default 24, O-B2) | `ConceptIntakeV3` v1; generation-round row created (§2.4); enqueue `story_v3.propose` round 1; planning `IDEA → PROPOSED` runs **only on the scope's initial proposal completion** (PB5-3, via the D5 seam) — not in this command | W: seasons + `season_tracks` + setup account (A2's command), intake document, generation-round row · J: `story_v3.propose` · E: A1's creation events + `season.created_v3`, `track.created` | **B2** (phase-B §11 B2 "Intake + Mode A refusal"; needs A2's `create_v3_season`) |
| `replace_v3_intake(season, mode, idea_line, hints, requested_count)` | Operator (human session + CSRF; owner scope enforced, PB5-1) | season / `season_tracks.revision` | an uncancelled V3 season in `PROPOSED` whose latest concept activation was REJECTED; no open activation; no unfinished proposal work; mode/count rules; expected revision matches | appends a new `ConceptIntakeV3` version (prior decisions preserved, PB-14); **advances the generation-round identity** (§2.4); resets the displayed round; enqueues `story_v3.propose` round 1 of the new intake; scope **retains `PROPOSED`** (PB5-3) | W: intake version, generation-round advance · J: `story_v3.propose` · E: intake-replacement event | **B2** (PB-14) |
| `reopen_v3_gate(gate, scope)` | Operator (human session + CSRF; owner scope enforced, PB5-1) | season: `season_tracks.revision`; extension: `season_extensions.revision` (never the season's for an extension scope, PB5-1) | the gate's scope was rejected with its planning state (`PROPOSED` at LOCK, `PLANNED` at STORY LOCK) and required work completed; refused after Approve / during Revise regeneration; expected revision matches (a stale extension revision refused); the gate's phase handler registered; no activation already open for the (gate, scope) | opens a fresh activation over the **recomputed current binding** via A1's `open_gate`, preserving every prior decision — the re-entry path after Reject at either gate | W: `gate_activations` row · J: none · E: `gate.opened` | **B2** (LOCK gate; PB-14); the STORY LOCK gate becomes decidable with **B5**'s handler |
| `edit_tier(character_key, tier)` | Operator (human session + CSRF) | season / `season_tracks.revision` | a STORY LOCK activation is open | (standalone entry, PB-5) supersedes the activation (`supersede_gate`), runs **tier revalidation** (the shared internal operation: promotion validation, demand derivation, season critic deterministic checks), refuses V3R-4-violating demotions (a speaker losing its voice demand; a recognisable character losing its identity demand), opens a new activation (`open_gate`) | W: `gate_activation_events` SUPERSEDED + new `gate_activations` row · J: none (revalidation is deterministic) · E: `gate.superseded`, `gate.opened` | **B5** (C-M3) |
| `create_extension(season, range, calendar, amendment_id)` | Operator (human session + CSRF) | season / `season_tracks.revision` | release `RELEASING`/`COMPLETE`; contiguous range beyond the current count; **the named amendment is an approved `SEASON` amendment of this season's `SEASON` account funding the requested appended count** (phase-A §5.4, PB5-4); calendar explicit | atomically creates the **immutable extension authorization** (exact appended range + cumulative count + amendment ID + human provenance; append-only, guarded; symbolic migration `B-…` allocated in the B5 note — B1 allocates no table for it, see OQ-6) and the `season_extensions` scope (A1 0030); a creation rollback leaves neither (B-T11) | W: authorization row + `season_extensions` row · J: none · E: `extension.opened` + authorization provenance | **B5** (phase-B §11 B5; A1 §12 OQ-1 ruled "phase B") |

All five rows' transactions are audited in §8. The D5 seam's ordering rule (phase-B §2.4 D5:
scope track FOR UPDATE **before** job locks; validate fence and lease; persist outputs and
completion; evaluate the join over **persisted** members; continuation/gate creation commits
atomically; the runtime does not finish the job again) is B2's to build — B1 registers it and
creates its persistence targets only.

## 8. Transaction and lock audit (phase-A §6 order = A1 §9's table)

Normative order: **1** idempotency row → **2** `season_tracks`, then `season_extensions` →
**3** `episode_tracks` (id order) → **4** scope domain rows → **5** jobs (id order) →
**6** `provider_operations`/leases → **7** budget. Fence reads take track SHARE; amendments FOR
UPDATE (phase-A §6). Every B1-owned mutation, and every command row §7 pins for later packages:

| Mutation | Locks in order | Verdict |
|---|---|---|
| `StoryV3Store.save_bundle` (B2–B5 callers) | caller already holds **#2** scope track (FOR UPDATE in decision/command transactions; the D5 seam mandates it) → **#4** document INSERTs + predecessor current-flag UPDATE (keyed by the held scope; no new lock class) | conforms — documents are domain rows; version-consecutive check runs under the scope lock, so two writers cannot fork a version chain |
| Generation-round advance (§2.4) | inside the caller's transaction that already holds **#2** FOR UPDATE (`replace_v3_intake`; the retry path) → counter UPDATE | conforms — no separate lock; monotonicity is the held track lock |
| Generation-round lazy create | **#2** held → `INSERT … ON CONFLICT DO NOTHING` | conforms |
| Prompt registration (B2–B5, at composition/import) | own short transaction; PK-conflict-tolerant INSERT; **no** track/job/budget locks (registry rows are not scope state) | conforms — no ordering interaction; the byte-compare refusal is conflict-free under the PK |
| `v3_episode_story_bindings` insert (B5 STORY LOCK Approve) | inside the A1 decision transaction: **1** idempotency → **2** `season_tracks` → **4** seasons/approvals → episode/track INSERTs (A2's `create_v3_episodes`) → binding INSERT (a domain row) → **5** no job enqueues at Approve (step 4 is C's) → single revision advance | conforms — the binding is one more #4-class write in the audited A1/A2 chain |
| `submit_v3_intake` (B2) | **1** idempotency → A2's `create_v3_season` chain (its own audited order: track + account under **#2/#7**) → **#4** intake document + generation-round row → **5** `story_v3.propose` enqueue (fence SHARE absorbed by the held **#2** FOR UPDATE, A3 §7) | conforms |
| `replace_v3_intake` (B2) | **1** → **2** `season_tracks` FOR UPDATE (owner scope + revision check under it) → **#4** intake version append + generation-round advance → **5** enqueue round 1 | conforms |
| `reopen_v3_gate` (B2/B5) | **1** → **2** track (or extension track after `season_tracks`, A1 §6-#2 order) → A1's `open_gate` admission checks under it → activation INSERT | conforms — A1's `open_gate` row plus the preflight |
| `edit_tier` (B5) | **1** → **2** → `supersede_gate` + tier revalidation reads → `open_gate` INSERTs | conforms |
| `create_extension` (B5) | **1** → **2** `season_tracks` → **#4** seasons + authorization + `season_extensions` INSERT (A1 0030 table) | conforms |
| D5 completion seam (B2 ships) | handler's caller transaction: **#2** scope track FOR UPDATE **before** job locks → fence/lease validation → **#4** output persists → **#5** job completion write → continuation/gate creation commits atomically; runtime does not finish again (`S/workers/runtime.py:245/:259`, `S/core/jobs.py:676`) | conforms by construction (phase-B §2.4 D5); the B2 commit-boundary crash case is B-T3's |
| B1 guard/reader reads (`require_workflow`, `read_episode_story`, registry lookups) | plain reads, no locks | n/a |

No B1 mutation takes a #6/#7 lock (no provider operations, no budget writes in B1's scope). No
inversion is introduced: the store never locks a document row before the caller's track lock, and
the claim-boundary skip (§6) takes no lock at all (a candidate filter, A1 §7 class (b)).

## 9. Acceptance: what B1 gates, and what it prepares

**B1's gate rows (phase-B §11): B-T1 and B-T2.**

- **B-T1 (V3-AT-19) — migration upgrade on a populated V1+V2 database.** Fixture records named per
  C-N15: V1 seasons/episodes/approvals seeded through `S/testing/seed.py`; a V2 `EpisodePack` (and
  its `SecretLedger`/`SeasonStoryLedger`/`SceneWardrobeAssignment` companions) written through the
  committed V2 example builders (`S/contracts/examples.py:694` `V2_VALID_BUILDERS`) with historical
  values — `duration_target_ms = 240_000` (inside the frozen 180–300 s band,
  `S/contracts/v2.py:357`) and a V1 season with `expected_episode_count = 6`
  (`S/contracts/season.py:213`, inside the 1–10 rule). The test migrates that database through
  B-1..B-4 and asserts: every V1/V2 record still validates under its own schema; recomputed hashes
  byte-identical; no row deleted or rewritten; applied 0001–0035 checksums unchanged; V1/V2
  generated contracts AST-identical (committed `ast.dump` fixtures); the four new tables guarded
  and in the catalog; fresh-create tail asserts B1's numbers.
- **B-T2 — version selection + guard enumeration.** `V3ProductionLimits` rejects a V3 record at
  180_000 ms and a 10-episode V3 intake (20–30 enforced); V1/V2 validators unchanged
  (AST-identical source, as B-T1); every guarded entry point from §4 — A1's A-T5 rows **and** the
  seven new B1 module guards — enumerated through the shared `guard_inventory.py` fixture, each
  refusing a V3 episode with `WORKFLOW_MISMATCH` while V1 rows pass unchanged.

**Prepared but not gated by B1** (the clause each later package's gate exercises):

| Clause (owner) | B1's preparation |
|----------------|------------------|
| B-T3 (B2): D5 seam, LOCK decisions, intake/replacement/reopen lifecycle, PB-2 retry identity | the document store, generation-round store, D2 targets, job registration, §7 rows |
| B-T4 (B3): bible critic, tiers/promotion | `SeasonBibleV3`/`CharacterProfile` records; `character:` standalone key; prompts registry capacity |
| B-T5/B-T6 (B4): DB-role isolation; `LlmStep` per-call behaviour; registry-referenced prompts | record models free of asset/voice fields (§3 drops verified); `v3_llm_prompts` + `resolve_prompt`; `FrozenLlmCall` prompt pinning surface |
| B-T7/B-T8 (B4/B5): typed-effect findings; demand completeness | `BeatEffect` union; demand-ID derivations; ledger sibling bound to `PayoffDebt.debt_id` |
| B-T9..B-T11 (B5): STORY LOCK transaction, tier revalidation, extension authorization | `v3_episode_story_bindings` DDL (both fences); `StoryLockBindingV3` hash inputs incl. the PB-9 continuity pin; `create_extension` row |
| B-T12 (B6): tabs 1–3 | readers/records the UI projects |

## 10. Risks

| Risk | Mitigation | Owner |
|------|------------|-------|
| The A-phase builds slip, moving B's real migration numbers | symbolic B-1..B-4 with a build-time tail re-audit (§0); purposes and order fixed | orchestrator |
| A queued, handlerless `story_v3.*` job fails `NO_HANDLER` in the B2→B3 window | the claim-boundary skip (§6), V3-scoped; V1 behaviour unchanged | B1 builder |
| Slug-vs-class-name divergence from the V2 store pattern confuses later readers | one vocabulary for CHECK + uuid5 + store registry (§2.1/§2.2); OQ-5 records the alternative | B1 |
| Continuity drift between the bound packs and standalone states | `source_pack_version`/`source_pack_sha256` + binding-time verification (§2.3, PB-9) | B1 |
| Prompt registry rows drift from the code constants | append-only PK + byte-compare refusal; text changes are `version + 1` (§2.5) | B2–B5 |

## 11. Alternatives rejected (one per major choice)

| Choice | Rejected alternative | Why |
|--------|----------------------|-----|
| Four symbolic migrations, one purpose each (§1) | One `0036_v3_story` bundle | the A-phase convention (A1 §1) keeps upgrade-test attribution and guard attachment per purpose; a bundle mixes story content, coordination state and B5's fence table |
| Dedicated `v3_generation_rounds` table (§2.4) | Deriving the generation round from `ProposalRoundV3.version` counts, or a column on `season_tracks` | derivation fails for non-proposal works and retries that write no proposal version; a column on an A-owned table reopens A1's build for a B concern |
| DB-backed prompt registry (§2.5) | Code constants only, or widening V2 `PromptManifest` | PB-6 names "its own storage and symbolic migration"; the V2 manifest's validator requires shot/asset bindings (`S/contracts/v2.py:773-786`) — it cannot register an intake or bible prompt (O-B6) |
| `source_pack_version` on `ContinuityStateV3` (§2.3) | "Latest stored continuity" reads at binding time | PB-9: a mutable current state must not silently change what a prior lock bound; the pin makes the mismatch a visible refusal |
| Slugs as the `contract_type` vocabulary (§2.2) | V2-style class names | the spec's §2 table already speaks in slugs (`intake`, `proposals`, …); one vocabulary for CHECK, uuid5 and store registry beats mirroring a naming accident |
| Claim-boundary skip for handlerless V3 jobs (§6) | Letting them fail `NO_HANDLER` (today's runtime behaviour), or refusing the enqueue | a fail burns a content attempt and projects `BLOCKED (failed)` on healthy work; refusing the enqueue breaks the spec's cross-package sequencing (B2's Approve enqueues B3's handler, C-M20) |

## 12. Open questions

| # | Question | Recommendation |
|---|----------|----------------|
| OQ-1 | Phase-B §2.4 D2 says "B1 owns a migration in B's range: contract code + regenerated v3 schemas" — but targets are jsonb validated in Python (A1 §2.3), so D2 needs no SQL DDL. Reading? | Read it as: the delta lands **in B1** (contract code + regenerated `schemas/v3` artifacts) inside B's migration range, with **no** SQL object; B-1..B-4 (§1) are B1's actual migrations. If the critique reads "a migration" literally, the empty-purpose file is worse than no file — confirm at critique |
| OQ-2 | The claim-boundary skip (§6) is a runtime change in B1 — is a claim filter the right shape, vs. per-deployment queue filtering? | Ship the skip: it is V3-scoped (`track IS NOT NULL` + registry membership), keeps V1 `NO_HANDLER` byte-identical, and needs no new queue lanes. B-T2 asserts a handlerless registered job stays QUEUED and a V1 unknown-type job still fails |
| OQ-3 | Should a Revise round also advance the generation-round identity? | No (§2.4): the round number already freshens the semantic key; advancing on Revise would needlessly change proposal-ID inputs mid-intake. Advance only on `replace_v3_intake` and terminal-failure retry |
| OQ-4 | `STORY_V3_NS` value | `uuid5(NAMESPACE_URL, "https://microdrama.invalid/story/v3")` (§2.1) — the script-maker convention; a contract test asserts the constant and one derived ID for stability |
| OQ-5 | `contract_type` slugs vs V2's class-name keying | Slugs (§2.2); the store's model registry is the single translation point. Class names would double the vocabulary with no gain |
| OQ-6 | The extension authorization's table (phase-B §8) is created in B5, but `create_extension`'s atomicity is a B1-pinned row (§7). Allocation? | B5's note allocates it (first B-number after B4's needs); B1 deliberately allocates nothing for it — the authorization is meaningless before B5's eligibility machinery. Recorded so B5's note re-audits the tail the same way §0 does |
| OQ-7 | `v3_story_documents.planning_scope_id` has no FK (§2.2) — acceptable? | Yes: extensions arrive with A1 0030's table but the scope-resolution rule (season or extension, same-ownership) is Python-enforced at write time under the scope lock; an FK to two tables is not expressible, and a partial FK to `seasons` only would wrongly admit extension scopes' rows keyed to nothing |

## 13. Traceability

**Phase-B findings pinned here:** C-B1 (§5 register incl. D6); C-M10 (§4 guards + shared fixture);
C-M11/C-N22 (§0 deviations: none; the gate checklist = §5 register, §7 rows, §10/§11, §0); C-M20
(§6); C-N5 (§3 field mapping); C-N7 (§2.1); PB-1/D5 (§5, §8); PB-2 (§2.1, §2.4, §6); PB-6 (§2.5);
PB-9 (§2.3); PB-10 (§2.6); PB5-5 (§2.3); PB-14's storage side (§7); O-B1..O-B3, O-B6 (§2.2/§2.3).

**Requirement coverage (phase-B §14):** R-1.2/R-2.1/R-2.2/R-3.2/R-3.3 record shapes (§2); R-3.1
(no `scoped_map_only`, §3); R-2.3 ledger sibling (§2.3). B1 gates no R-ID end to end — the R-IDs
gate with their packages (§9's table).

— end of note —
