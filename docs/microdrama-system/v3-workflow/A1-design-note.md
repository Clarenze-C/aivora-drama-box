# A1 design note: discriminator, gates, decision transaction, tracks

**Version 1.4, 14 Nov 2026. Author: GLM (design note only).** Round-3 findings applied
(GLM); operator-authorized R4 verification follows. v1.4 folds every Replacement from
[codex-a1-r3.md](codex-a1-r3.md) (verdict REWORK: N1R3-1/2 BLOCKING, N1R3-3..6 SHOULD-FIX): the
workflow-resolved approval-identity partition — V1 identity columns refused, V3 `activation_id`
required, ancestry validated before either uniqueness index accepts a row (N1R3-1, §2.3); the
Comfy submit ordering corrected to the real commit-before-HTTP sequence at
`comfy_jobs.py:611-639`, matching A3 §9 A-T18 (N1R3-2, §8/§9); one canonical per-transaction lock
order — scope → job → provider-operation serialization/rows → lease rows → budget locks — with
`ensure_pod`'s create-request / pod-binding / activation transactions enumerated separately
(N1R3-3, §8/§9); the complete work-scope replay comparison scoped to resolved V3 work only, the
V1 type/input-hash rule preserved (N1R3-4, §2.4); V1 scope compatibility evaluated with the
original `gate_type='SEASON_CONCEPT'` equivalence and legacy failure precedence preserved, the
expanded season-gate set V3-only (N1R3-5, §2.2); and the concurrent-decision expectation corrected
to `GateNotReady` for the closed activation (N1R3-6, §5/§9); §13.0 maps each. v1.3 (14 Nov)
applied [codex-a1-note-recritique.md](codex-a1-note-recritique.md) in full (N1R-1..N1R-12;
§13.1 maps each); v1.2 (11 Nov) applied [codex-a1-note-critique.md](codex-a1-note-critique.md)
N1-1..N1-18 in full (verdict REWORK; every "Replace" binding) plus the rulings on N1-5/N1-7/N1-10.
Requirements: [phase-A-spec.md](phase-A-spec.md) v0.3 §0–§3, §6, §10, §11 (AC-1..9, AC-22/23,
AR-3/4/6 binding); master [SPEC-v3.md](SPEC-v3.md) v0.4.4 §2.1–§2.2, §4.3, §10.0, §10.5; A0 v0.4
§5.2/§5.5/§5.6; [A2-design-note.md](A2-design-note.md) v1.3 and [A3-design-note.md](A3-design-note.md)
v1.3 (lock-order and GPU-audit statements stay mutually consistent). Facts re-verified on
`feat/microdrama-m0-m4` @ `39e5319`; v1.3 re-verifies its cited sites at `81b783f` — including the
committed `schemas/v1/ApprovalCommand.schema.json` bytes (N1R-2); v1.4 re-verifies its round-3
sites at `0607f41` (`comfy_jobs.py:611-639`, `leases.py:901-970`, `jobs.py:429-434`,
`M/0002…sql:184-208`) — (tail 0025; 0026 = `.scratch/t031-gate-h2/` T031; 0027 = A0, **not yet
built**). `S/` = `src/microdrama/`, `M/` = `migrations/`, `X/` = `tests/`.

---

## 1. Migration allocation

Prerequisite pin (spec §10): the T031 merge (0026) and A0 (0027) land first. **Applied migration bytes are never edited** — the migrator hashes file bytes and rejects changed checksums (`S/persistence/migrate.py:45`, `:51`). A1 allocates, one purpose each:

| # | File | Purpose |
|---|------|---------|
| 0028 | `0028_v3_workflow_version.sql` | Discriminator: `seasons.workflow_version`, immutability guard, episode re-parent guard |
| 0029 | `0029_v3_gate_rules.sql` | Version-aware approval constraint trigger replacing the 0002 gate/entity/action/feedback CHECKs; admits the four new gate values. Creates only objects referencing pre-existing tables |
| 0030 | `0030_v3_tracks_and_gates.sql` | `season_tracks`, `episode_tracks`, `season_extensions`, `gate_activations`, `gate_activation_events`, `season_revision_notes`; **and the deferred V3-revise-notes constraint trigger** — it references `season_revision_notes`, so it must be installed here, not in 0029 (N1-1: an intermediate 0029-only deployment stays writable); **and the V3 approval-decision identity** (N1R-3): `approval_events.activation_id`/`extension_id`, the scope-linkage constraint trigger and the uniqueness restructure — `activation_id` references `gate_activations`, so it lands here, after that table's creation |
| 0031 | `0031_v3_job_workscope.sql` | Jobs work-scope columns, `alert_dismissals` (with extension scope), the `track_waits` view |

Ordering: 0029 resolves the version from 0028's column; 0030's notes trigger needs 0030's own table,
and 0030's approval identity columns need 0030's `gate_activations`; 0031's view joins 0030's tables
and A0's `jobs.defer_reason` (0027).

## 2. Guarded DDL

Guard pattern per `M/0019…sql:28-38` and `M/0026…sql:89-99` (scratch): `md_immutable_columns` for identity columns, `md_forbid_mutation` for row DELETE and statement TRUNCATE, `md_forbid_non_integer_numbers` on INSERT OR UPDATE (`M/0009…sql:94`; its 0009 DO-loop only covered tables then existing — new tables attach it explicitly). The catalog tests (`X/integration/persistence/test_schema_catalog.py:22-37`, `relkind='r'` only) then cover every new table automatically — including the TRUNCATE (`:57`) and integer-numbers (`:65`) tests N1-4 flagged; views sit outside that net.

### 2.1 Migration 0028 — discriminator

```sql
ALTER TABLE seasons
  ADD COLUMN workflow_version text NOT NULL DEFAULT 'v1'
    CHECK (workflow_version IN ('v1','v3'));
-- Default backfills every existing row to 'v1'. Episodes and jobs derive the version
-- through episodes.season_id / jobs.season_id — no second column (spec §1).
CREATE TRIGGER seasons_workflow_version_immutable BEFORE UPDATE ON seasons
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('workflow_version');
-- AC-5: episodes can never be re-parented.
CREATE TRIGGER episodes_season_immutable BEFORE UPDATE ON episodes
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('season_id');
```

Neither `seasons` (`M/0002…sql:4-22`) nor `episodes` (`M/0002…sql:58-81`) had an immutability trigger, so this is a pure tightening. No current writer re-parents episodes (creation sites: seed inserts and `S/scheduling/service.py:228`); `approved_scope_hash` already ties an episode to its season.

### 2.2 Migration 0029 — version-aware gate rules (AC-1, AC-2)

Dropped constraints — PostgreSQL auto-names are deterministic from the applied 0002 bytes, and the DO block fails loudly if any is missing: `approval_events_gate_type_check` (:184, the two-gate IN list), `approval_events_check` (:200, season gate ⇔ season entity), `approval_events_check1` (:201, SEASON_CONCEPT actions), `approval_events_check2` (:202-204, Gate-2 APPROVE binding), `approval_events_check3` (:205, Revise needs feedback). The V1 branch below reproduces each rule exactly. The `action`/`entity_type` column CHECKs (:185-186) stay. `md_approval_requires_human_session` (`M/0007…sql:5`) and every 0007–0021 approval guard stay **unchanged**: V3 seasons never set `seasons.approval_event_id`, so `md_season_approval_binding` (`M/0007…sql:31`) never fires for them; the human-session trigger applies to V3 rows unchanged (spec §2.8). The one exception is `approval_events_one_per_revision` (`M/0002…sql:208`): 0030 restructures it — atomically, in the same migration transaction — into its partial V1 form beside the V3 identity indexes (N1R-3, §2.3), preserving its rule for V1 rows exactly.

```sql
DO $$ BEGIN
  ALTER TABLE approval_events DROP CONSTRAINT approval_events_gate_type_check;
  ALTER TABLE approval_events DROP CONSTRAINT approval_events_check;
  ALTER TABLE approval_events DROP CONSTRAINT approval_events_check1;
  ALTER TABLE approval_events DROP CONSTRAINT approval_events_check2;
  ALTER TABLE approval_events DROP CONSTRAINT approval_events_check3;
END $$;

-- N1-1: two distinct parameter names; entity type and id travel together.
CREATE FUNCTION md_season_version_of(p_entity_type text, p_entity_id uuid) RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT CASE WHEN p_entity_type = 'season'
    THEN (SELECT workflow_version FROM seasons WHERE id = p_entity_id)
    ELSE (SELECT s.workflow_version FROM episodes e JOIN seasons s ON s.id = e.season_id
           WHERE e.id = p_entity_id) END $$;

CREATE FUNCTION md_approval_gate_rules() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v text; season_gate boolean; bound boolean;
BEGIN
  v := md_season_version_of(NEW.entity_type, NEW.entity_id);
  bound := NEW.gate_type = 'EPISODE_FINAL' AND NEW.action = 'APPROVE'
           AND NOT (jsonb_array_length(NEW.media_hashes) > 0
                    AND NEW.management_policy_hash IS NOT NULL AND NEW.release_scope_hash IS NOT NULL);
  IF v = 'v1' OR v IS NULL THEN
    -- V1 rules reproduced EXACTLY (0002:184,200,201,202-204,205), each raise emitting the
    -- dropped CHECK's original SQLSTATE, constraint name and primary message (N1R-11).
    -- N1R3-5: scope compatibility is evaluated with the ORIGINAL 0002:200 equivalence
    -- ((gate_type = 'SEASON_CONCEPT') = (entity_type = 'season')) and FIRST, preserving
    -- legacy failure precedence -- a new gate value on a season entity fails
    -- approval_events_check (0002:200: (false) = (true) is false), while on an episode
    -- entity the original scope rule passes ((false) = (false)) and the gate-type
    -- membership raise (0002:184) reports instead. The expanded season-gate set exists
    -- only in the V3 branch below.
    IF (NEW.gate_type = 'SEASON_CONCEPT') <> (NEW.entity_type = 'season') THEN
      RAISE EXCEPTION 'new row for relation "approval_events" violates check constraint "approval_events_check"'
        USING ERRCODE='check_violation', CONSTRAINT='approval_events_check'; END IF;
    IF NEW.gate_type NOT IN ('SEASON_CONCEPT','EPISODE_FINAL') THEN
      RAISE EXCEPTION 'new row for relation "approval_events" violates check constraint "approval_events_gate_type_check"'
        USING ERRCODE='check_violation', CONSTRAINT='approval_events_gate_type_check'; END IF;
    IF NEW.gate_type = 'SEASON_CONCEPT' AND NEW.action NOT IN ('APPROVE','REJECT') THEN
      RAISE EXCEPTION 'new row for relation "approval_events" violates check constraint "approval_events_check1"'
        USING ERRCODE='check_violation', CONSTRAINT='approval_events_check1'; END IF;
    IF bound THEN
      RAISE EXCEPTION 'new row for relation "approval_events" violates check constraint "approval_events_check2"'
        USING ERRCODE='check_violation', CONSTRAINT='approval_events_check2'; END IF;
    IF NEW.action = 'REVISE' AND jsonb_array_length(NEW.feedback) = 0 THEN
      RAISE EXCEPTION 'new row for relation "approval_events" violates check constraint "approval_events_check3"'
        USING ERRCODE='check_violation', CONSTRAINT='approval_events_check3'; END IF;
  ELSIF v = 'v3' THEN
    IF NEW.gate_type NOT IN ('SEASON_CONCEPT','STORY_LOCK','CAST_LOCK','TEASER_FINAL','LAUNCH',
                             'EPISODE_FINAL') THEN
      RAISE EXCEPTION 'gate_type not admitted for v3'
        USING ERRCODE='check_violation', CONSTRAINT='approval_events_v3_gate_type'; END IF;
    -- N1R3-5: the expanded season-gate set applies to V3 ONLY (new constraint name; V1
    -- diagnostics are untouched by it).
    season_gate := NEW.gate_type IN ('SEASON_CONCEPT','STORY_LOCK','CAST_LOCK','TEASER_FINAL','LAUNCH');
    IF season_gate <> (NEW.entity_type = 'season') THEN
      RAISE EXCEPTION 'v3 gate scope does not match entity type'
        USING ERRCODE='check_violation', CONSTRAINT='approval_events_v3_scope'; END IF;
    -- N1-2: feedback validation branches by gate (spec §2.3).
    IF NEW.gate_type = 'EPISODE_FINAL' THEN
      -- Gate 2 keeps its timecoded feedback rules in BOTH versions, unchanged — including
      -- the original constraint name for the verbatim-V1 rule (N1R-11).
      IF NEW.action = 'REVISE' AND jsonb_array_length(NEW.feedback) = 0 THEN
        RAISE EXCEPTION 'new row for relation "approval_events" violates check constraint "approval_events_check3"'
          USING ERRCODE='check_violation', CONSTRAINT='approval_events_check3'; END IF;
      IF NEW.action <> 'REVISE' AND jsonb_array_length(NEW.feedback) > 0 THEN
        RAISE EXCEPTION 'feedback only with revise'
          USING ERRCODE='check_violation', CONSTRAINT='approval_events_v3_feedback_revise_only'; END IF;
    ELSE
      -- V3 season gates: Revise carries season revision notes, never feedback.
      IF NEW.action = 'REVISE' AND jsonb_array_length(NEW.feedback) > 0 THEN
        RAISE EXCEPTION 'v3 season revise uses season_revision_notes, not feedback'
          USING ERRCODE='check_violation', CONSTRAINT='approval_events_v3_season_revise_notes'; END IF;
      IF NEW.action <> 'REVISE' AND jsonb_array_length(NEW.feedback) > 0 THEN
        RAISE EXCEPTION 'feedback only with revise'
          USING ERRCODE='check_violation', CONSTRAINT='approval_events_v3_feedback_revise_only'; END IF;
    END IF;
    IF bound THEN
      RAISE EXCEPTION 'new row for relation "approval_events" violates check constraint "approval_events_check2"'
        USING ERRCODE='check_violation', CONSTRAINT='approval_events_check2'; END IF;
  ELSE RAISE EXCEPTION 'unknown workflow version'
    USING ERRCODE='check_violation', CONSTRAINT='approval_events_v3_unknown_version';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER approval_events_gate_rules BEFORE INSERT ON approval_events
  FOR EACH ROW EXECUTE FUNCTION md_approval_gate_rules();
```

`approval_events` stays append-only (`M/0002…sql:210`), so the BEFORE INSERT trigger replaces the dropped CHECKs on the only write path. Gate 2 rules — binding and feedback — are identical in both versions (AC-1, spec §2.3); V3's difference there is handler availability (§5), not SQL. The deferred notes trigger (a V3 **season-gate** REVISE must carry ≥1 matching `season_revision_notes` row in the same committed transaction) is created in **0030**, after its referenced table exists — see §2.3.

**Preserved V1 diagnostic contract (N1R-11).** A CHECK's observable diagnostics are its SQLSTATE
(23514), constraint name and primary message — exactly the stable fields `translate_db_error`
surfaces (`S/persistence/db.py:77`). Every V1-branch raise therefore emits the dropped CHECK's
original name in `USING CONSTRAINT` and reproduces PostgreSQL's check-violation primary-message
template verbatim, so a V1 row violating a reproduced rule sees the same SQLSTATE, constraint name
and primary message before and after 0029. V3 rows raise the new `approval_events_v3_*` names,
except where the rule is verbatim V1 (`approval_events_check2`/`check3` on Gate 2), which keep the
original names for uniform diagnostics. A-T16 compares these stable fields across the upgrade —
never the pre-0029 raw messages against different custom raises (§10).

**Legacy failure precedence preserved (N1R3-5).** Scope compatibility is evaluated per version,
never by a shared predicate: the V1 branch evaluates the **original** `0002:200` equivalence
(`(gate_type = 'SEASON_CONCEPT') = (entity_type = 'season')`) first, and the expanded five-gate
season set exists only in the V3 branch (new name `approval_events_v3_scope`). The raise order
inside the V1 branch therefore reproduces legacy precedence — a new gate value on a **season**
entity fails `approval_events_check` (as `0002:200` did: `(false) = (true)` is false), while on an
**episode** entity the original scope rule passes (`(false) = (false)`) and the gate-type
membership raise reports `approval_events_gate_type_check` — the exact diagnostic reversal the v1.3
shared predicate produced is eliminated. A-T1 tests the new gate values on both V1 entity types
with exactly these original diagnostics.

### 2.3 Migration 0030 — tracks, activations, activation events, notes

```sql
CREATE TABLE season_tracks (
  id               uuid PRIMARY KEY,
  schema_version   text NOT NULL DEFAULT '1.0',
  season_id        uuid NOT NULL UNIQUE REFERENCES seasons(id),
  planning_state   text NOT NULL CHECK (planning_state IN ('IDEA','PROPOSED','LOCKED','BIBLE','PLANNED',
                                   'STORY_LOCKED','CASTING','CAST_LOCKED')),
  release_state    text NOT NULL CHECK (release_state IN ('NOT_SCHEDULED','CALENDAR_PROPOSED',
                                   'LAUNCH_APPROVED','RELEASING','COMPLETE')),
  content_revision integer NOT NULL DEFAULT 0 CHECK (content_revision >= 0),  -- the amendment fence
  cancelled_at     timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  revision         integer NOT NULL DEFAULT 0 CHECK (revision >= 0)
);
CREATE TRIGGER season_tracks_identity_immutable BEFORE UPDATE ON season_tracks
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('id','season_id','created_at');

CREATE TABLE episode_tracks (
  id               uuid PRIMARY KEY,
  schema_version   text NOT NULL DEFAULT '1.0',
  episode_id       uuid NOT NULL UNIQUE REFERENCES episodes(id),
  production_state text NOT NULL CHECK (production_state IN ('PLANNED','DIRECTED','RENDERING','EDITING',
                                   'DRAFTING','AWAITING_REVIEW','APPROVED')),
  release_state    text NOT NULL CHECK (release_state IN ('UNSCHEDULED','SCHEDULED','PUBLISHING',
                                   'PUBLISHED_VERIFIED')),
  content_revision integer NOT NULL DEFAULT 0 CHECK (content_revision >= 0),
  cancelled_at     timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  revision         integer NOT NULL DEFAULT 0 CHECK (revision >= 0)
);
CREATE TRIGGER episode_tracks_identity_immutable BEFORE UPDATE ON episode_tracks
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('id','episode_id','created_at');
```

State sets are master §2.2 verbatim. `HELD`/`MISSED`/`PARTIAL` are per-destination release states (master §2.2, N43) and stay on `platform_posts` (`M/0005…sql:51`), not the episode track. `EXTENDING` is derived ("an open `season_extensions` row exists"), never stored.

```sql
CREATE TABLE season_extensions (
  id               uuid PRIMARY KEY,
  schema_version   text NOT NULL DEFAULT '1.0',
  season_id        uuid NOT NULL REFERENCES seasons(id),
  planning_state   text NOT NULL CHECK (planning_state IN ('IDEA','PROPOSED','LOCKED','BIBLE','PLANNED',
                                   'STORY_LOCKED','CASTING','CAST_LOCKED')),
  episode_start    integer NOT NULL CHECK (episode_start >= 1),
  episode_end      integer NOT NULL CHECK (episode_end >= 1),
  content_revision integer NOT NULL DEFAULT 0 CHECK (content_revision >= 0),
  closed_at        timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  revision         integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  CHECK (episode_end >= episode_start)
);
CREATE UNIQUE INDEX season_extensions_one_open ON season_extensions (season_id) WHERE closed_at IS NULL;
CREATE TRIGGER season_extensions_identity_immutable BEFORE UPDATE ON season_extensions
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('id','season_id','episode_start','episode_end',
                                                     'created_at');
```

Extension **eligibility** is master §4.3, enforced by `create_extension` (§6): the season's release track is `RELEASING` or `COMPLETE` with an explicit continued-or-resumed calendar — not `STORY_LOCKED+` (N1-16). Extension identity travels with planning commands, activations, decisions, bindings, waits and dismissals; prior season approvals are never touched.

**Gate activations are immutable facts (N1-5, orchestrator ruling 1; spec §2.5 append-only).** An
activation row is never updated or deleted; decisions and supersessions are appended as rows of
`gate_activation_events`, and openness is derived. Spec §2.5's `superseded_by` is realised as the
`SUPERSEDED` event's `successor_activation_id` — an appended fact, not a mutable column.

```sql
CREATE TABLE gate_activations (
  id                uuid PRIMARY KEY,
  schema_version    text NOT NULL DEFAULT '1.0',
  gate_type         text NOT NULL CHECK (gate_type IN ('SEASON_CONCEPT','STORY_LOCK','CAST_LOCK',
                                   'TEASER_FINAL','LAUNCH','EPISODE_FINAL')),
  season_id         uuid NOT NULL REFERENCES seasons(id),
  episode_id        uuid REFERENCES episodes(id),
  extension_id      uuid REFERENCES season_extensions(id),          -- N1-16: extension identity
  binding_sha256    text NOT NULL CHECK (binding_sha256 ~ '^[0-9a-f]{64}$'),
  content_revision  integer NOT NULL CHECK (content_revision >= 0),
  decision_revision integer NOT NULL CHECK (decision_revision >= 0),
  opened_at         timestamptz NOT NULL DEFAULT now(),
  opened_by_job     uuid REFERENCES jobs(id),
  created_at        timestamptz NOT NULL DEFAULT now(),
  CHECK ((gate_type = 'EPISODE_FINAL') = (episode_id IS NOT NULL)),
  CHECK (episode_id IS NULL OR extension_id IS NULL)
);
CREATE INDEX gate_activations_scope_idx ON gate_activations
  (gate_type, season_id, COALESCE(episode_id, '00000000-0000-0000-0000-000000000000'::uuid),
   COALESCE(extension_id, '00000000-0000-0000-0000-000000000000'::uuid));
CREATE TRIGGER gate_activations_append_only BEFORE UPDATE OR DELETE ON gate_activations
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();

CREATE TABLE gate_activation_events (
  id                      uuid PRIMARY KEY,
  schema_version          text NOT NULL DEFAULT '1.0',
  activation_id           uuid NOT NULL REFERENCES gate_activations(id),
  kind                    text NOT NULL CHECK (kind IN ('DECIDED','SUPERSEDED')),
  approval_event_id       uuid REFERENCES approval_events(id),     -- required iff DECIDED
  successor_activation_id uuid REFERENCES gate_activations(id),    -- optional; SUPERSEDED only
  created_at              timestamptz NOT NULL DEFAULT now(),
  CHECK ((kind = 'DECIDED') = (approval_event_id IS NOT NULL))
);
CREATE UNIQUE INDEX gate_activation_events_one_per_activation
  ON gate_activation_events (activation_id);
CREATE TRIGGER gate_activation_events_append_only BEFORE UPDATE OR DELETE ON gate_activation_events
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
```

Semantics:

- **Open** = no `gate_activation_events` row. A `DECIDED` event closes the activation with its approval; a `SUPERSEDED` event closes it with no fabricated approval (N1-5).
- `UNIQUE (activation_id)` makes double closure impossible; nothing can be undone or rebound — there is no lifecycle column to clear or rebind.
- **One open activation per (gate, scope)** (season, episode or extension) is enforced **under the §6-#2 track lock**: `open_gate` (insert) and `decide` (append the closing event) both hold the scope's track row FOR UPDATE first and re-check openness there; the scope index serves the existence probe.
- A deliberate new activation may open over unchanged content after a decision — no `(gate, scope, hash)` uniqueness (N1-15); retries replay through the command's idempotency key.

**V3 approval-decision identity (N1R-3).** `approval_events_one_per_revision`
(`M/0002…sql:208`) keys `(gate_type, entity_id, expected_revision)`, but an extension decision is
recorded against the **same season entity** as the season's own gate rows, and an extension's
`revision` counter restarts at 0 — an extension repeating a gate at a previously used revision
would collide with preserved season history. V3 approval rows therefore persist their immutable
activation and extension identity (append-only rows: immutability is the existing
`approval_events_append_only` trigger, `M/0002…sql:210`), and uniqueness is restructured in the
**same 0030 transaction** — no window exists in which any row is unconstrained:

```sql
-- After gate_activations/season_extensions exist (0030 order): decision identity columns.
ALTER TABLE approval_events
  ADD COLUMN activation_id uuid REFERENCES gate_activations(id),
  ADD COLUMN extension_id  uuid REFERENCES season_extensions(id);

-- Partition discipline is workflow-resolved, never guessed from a nullable column (N1R3-1):
-- the workflow is resolved from the approval entity itself; V1 rows must carry NULL
-- activation_id AND NULL extension_id (else they would sit in the V3 index partition and
-- escape the preserved 0002:208 rule), and V3 rows must carry a non-NULL activation_id (else
-- they would sit in the V1 partition and share scope/revision with preserved V1 history across
-- the two indexes). With identity present, the activation's workflow and complete
-- season/episode/extension ancestry are validated against the approval before either index
-- partition accepts the row (deferred: the DECIDED event and notes join the transaction).
CREATE FUNCTION md_v3_approval_identity() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v text; a record;
BEGIN
  v := md_season_version_of(NEW.entity_type, NEW.entity_id);
  IF v = 'v1' OR v IS NULL THEN
    IF NEW.activation_id IS NOT NULL OR NEW.extension_id IS NOT NULL THEN
      RAISE EXCEPTION 'v1 approval cannot carry v3 decision identity'
        USING ERRCODE='check_violation', CONSTRAINT='approval_events_v3_identity'; END IF;
    RETURN NULL;
  END IF;
  IF NEW.activation_id IS NULL THEN
    RAISE EXCEPTION 'v3 approval requires its gate activation identity'
      USING ERRCODE='check_violation', CONSTRAINT='approval_events_v3_identity'; END IF;
  SELECT * INTO a FROM gate_activations WHERE id = NEW.activation_id;
  IF a.id IS NULL OR a.gate_type <> NEW.gate_type
     OR (a.gate_type = 'EPISODE_FINAL'
         AND (a.episode_id <> NEW.entity_id
              OR a.season_id <> (SELECT season_id FROM episodes WHERE id = NEW.entity_id)))
     OR (a.gate_type <> 'EPISODE_FINAL' AND a.season_id <> NEW.entity_id)
     OR a.extension_id IS DISTINCT FROM NEW.extension_id
     OR (NEW.extension_id IS NOT NULL
         AND a.season_id <> (SELECT season_id FROM season_extensions WHERE id = NEW.extension_id))
     OR a.decision_revision <> NEW.expected_revision THEN
    RAISE EXCEPTION 'approval does not match its activation scope'
      USING ERRCODE='check_violation', CONSTRAINT='approval_events_v3_identity'; END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER approval_events_v3_identity_trigger AFTER INSERT ON approval_events
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION md_v3_approval_identity();

-- Uniqueness: legacy rule preserved for V1; V3 keyed by full scope/revision and per activation.
-- Partitions are workflow-resolved by md_v3_approval_identity (N1R3-1) — never by the nullable
-- column alone.
DROP INDEX approval_events_one_per_revision;
CREATE UNIQUE INDEX approval_events_one_per_revision ON approval_events
  (gate_type, entity_id, expected_revision) WHERE activation_id IS NULL;
CREATE UNIQUE INDEX approval_events_v3_one_per_revision ON approval_events
  (gate_type, entity_id, COALESCE(extension_id,'00000000-0000-0000-0000-000000000000'::uuid),
   expected_revision) WHERE activation_id IS NOT NULL;
CREATE UNIQUE INDEX approval_events_one_decision_per_activation ON approval_events
  (activation_id) WHERE activation_id IS NOT NULL;
```

Semantics: **partition membership is workflow-resolved and enforced, never assumed (N1R3-1)** —
the deferred trigger refuses a V1 row carrying `activation_id`/`extension_id` (restoring the full
strength of the preserved `0002:208` rule, which a nullable-column guess weakened) and a V3 row
without `activation_id` (which would otherwise select the V1 partition and share scope/revision
with preserved V1 history across the two indexes); neither uniqueness partition is reachable by
choice of a nullable value. The untouched V1 recorder (§5) never sets either column, so the partial
index preserves the V1 rule **exactly** — dropping and recreating it inside 0030 is not an edit of
applied 0002 bytes. A second decision on one activation violates
`approval_events_one_decision_per_activation` **and** `gate_activation_events`' `UNIQUE (activation_id)`
— either reports the conflict. Because every decision advances its scope's `revision`
(§5 step 9), two activations over unchanged content still decide at distinct `expected_revision`
values, so full-scope/revision uniqueness holds without fabricating collisions. The decision
command carries the `activation_id` it resolves (N1R-4, §4/§5), so the recorded identity is the
command's own scope proof, never a server-side guess.

```sql
CREATE TABLE season_revision_notes (
  id                uuid PRIMARY KEY,
  schema_version    text NOT NULL DEFAULT '1.0',
  approval_event_id uuid NOT NULL REFERENCES approval_events(id),
  season_id         uuid NOT NULL REFERENCES seasons(id),
  gate_type         text NOT NULL CHECK (gate_type IN
    ('SEASON_CONCEPT','STORY_LOCK','CAST_LOCK','TEASER_FINAL','LAUNCH')),
  note_key          text NOT NULL CHECK (note_key <> ''),
  body              text NOT NULL CHECK (body <> ''),
  targets           jsonb NOT NULL DEFAULT '[]',   -- [{kind,id}] typed refs; kinds validated in Python
  created_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (approval_event_id, note_key)
);
CREATE TRIGGER season_revision_notes_append_only BEFORE UPDATE OR DELETE ON season_revision_notes
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();

-- Deferred (spec §2.3): a V3 season-gate REVISE carries >=1 matching note in the same committed
-- transaction (notes are inserted after the approval row). Installed HERE, in 0030 (N1-1).
CREATE FUNCTION md_v3_revise_notes() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.action = 'REVISE' AND NEW.entity_type = 'season'
     AND md_season_version_of('season', NEW.entity_id) = 'v3'
     AND NOT EXISTS (SELECT 1 FROM season_revision_notes n
                      WHERE n.approval_event_id = NEW.id
                        AND n.season_id = NEW.entity_id AND n.gate_type = NEW.gate_type) THEN
    RAISE EXCEPTION 'v3 season revise requires revision notes' USING ERRCODE='check_violation';
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER approval_events_v3_notes AFTER INSERT ON approval_events
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION md_v3_revise_notes();
```

Notes are written only by the V3 decision command, never into `feedback_events` (`S/core/approvals.py:119` keeps its episode-only writer). All six 0030 tables get the standard no-truncate/integer-number guards via the 0026-style DO loop over `ARRAY['season_tracks','episode_tracks','season_extensions','gate_activations','gate_activation_events','season_revision_notes']` (append-only tables already refuse UPDATE+DELETE; mutable ones get `_no_delete` only — `M/0026…sql:85-99`).

### 2.4 Migration 0031 — job work scope, dismissals, `track_waits`

```sql
ALTER TABLE jobs
  ADD COLUMN track           text CHECK (track IN ('planning','production','release')),
  ADD COLUMN extension_id    uuid REFERENCES season_extensions(id),
  ADD COLUMN logical_work_id text,
  ADD COLUMN replaces_job_id uuid REFERENCES jobs(id),
  ADD CHECK ((track IS NULL) = (logical_work_id IS NULL)),
  ADD CHECK (replaces_job_id IS NULL OR track IS NOT NULL),
  ADD CHECK (extension_id IS NULL OR track IS NOT NULL);
CREATE TRIGGER jobs_workscope_immutable BEFORE UPDATE ON jobs
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('track','extension_id','logical_work_id',
                                                     'replaces_job_id');
-- N1R-5: season/episode scope is immutable for V3 jobs; V1 UPDATE paths are unaffected.
CREATE FUNCTION md_v3_job_scope_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.track IS NOT NULL
     AND (NEW.season_id IS DISTINCT FROM OLD.season_id
          OR NEW.episode_id IS DISTINCT FROM OLD.episode_id) THEN
    RAISE EXCEPTION 'v3 job season/episode scope is immutable'
      USING ERRCODE='check_violation', CONSTRAINT='jobs_v3_scope_immutable'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER jobs_v3_scope_immutable BEFORE UPDATE ON jobs
  FOR EACH ROW EXECUTE FUNCTION md_v3_job_scope_immutable();
CREATE INDEX jobs_workscope_idx ON jobs (season_id, track) WHERE track IS NOT NULL;
CREATE INDEX jobs_logical_work_idx ON jobs (logical_work_id) WHERE logical_work_id IS NOT NULL;
```

`track` is NULL for every V1 job (and `require_workflow` refuses V3 rows on legacy paths, so no V1 writer sets it). `replaces_job_id` + `logical_work_id` are the replacement identity separate from the UNIQUE `jobs.semantic_key` (`M/0001…sql:78`, AR-4). `jobs_identity_immutable` (`M/0001…sql:104`) is untouched — and neither it nor the trigger above guarded `season_id`/`episode_id`, which is why the V3-conditional scope guard is added beside them (N1R-5): V3 work-scope identity cannot be re-pointed after insert, while every V1 UPDATE path (including episode back-fill on INSERT, which is not an UPDATE) keeps its exact behaviour.

**Typed enqueue/work-scope changes (N1-9, N1R-5).** `JobService.enqueue` (`S/core/jobs.py:353`; INSERT at `:389`) gains keyword-only `track`, `extension_id`, `logical_work_id`, `replaces_job_id`, persisted by the same INSERT, and the typed row plumbing carries them end to end: `Job` (`S/core/jobs.py:95`) and the `_job` mapper (`:136`) gain all four work-scope fields, so no caller reads scope off the raw row. Validated inside the caller's transaction: a V3 job is discriminated by the **resolved season's `workflow_version`** — `track` set requires the resolved season to be `'v3'` and a `'v1'` season refuses a tracked job; `track` set requires `season_id`; an `episode_id` resolves its season and a mismatch is refused (today an episode job may persist without `season_id` — `S/core/jobs.py:385` back-fills only the episode); `extension_id` must belong to the same season with `track='planning'`; `replaces_job_id` must name an older job of the same scope, track and `logical_work_id`; every V3 payload carries `expected_content_revision` for its resolved fence. **Replay comparison (N1R-5, N1R3-4):** the semantic-key replay check (`S/core/jobs.py:429-434`)
currently compares job type and input hash only. The **complete work-scope comparison**
(`season_id`, `episode_id`, `extension_id`, `track`, `logical_work_id`, `replaces_job_id`) applies
to **resolved V3 work only** (`track` set / resolved season `'v3'`): the same semantic key re-used
for a different V3 work scope raises `IdempotencyConflict` exactly as a different input does. The
**V1 rule is preserved unchanged** — V1 replay keeps comparing job type and input hash only, so a
V1 replay whose explicit `season_id`/`episode_id` argument differs against the same semantic key is
never newly refused (the v1.3 unconditional extension is withdrawn). The immutability triggers protect scope identity after insert; V1 call sites are unchanged (all four params default to NULL).

```sql
CREATE TABLE alert_dismissals (
  id                   uuid PRIMARY KEY,
  schema_version       text NOT NULL DEFAULT '1.0',
  season_id            uuid NOT NULL REFERENCES seasons(id),
  episode_id           uuid REFERENCES episodes(id),
  extension_id         uuid REFERENCES season_extensions(id),
  track                text NOT NULL CHECK (track IN ('planning','production','release')),
  alert_kind           text NOT NULL CHECK (alert_kind IN ('BLOCKED_RECONCILE','BLOCKED_FAILED',
                                   'BLOCKED_OVERRUN','WAITING_QUOTA','WAITING_PROVIDER','WAITING_BUDGET',
                                   'CANCELLED')),
  subject_job_id       uuid,
  subject_operation_id uuid,
  actor_owner_id       uuid NOT NULL REFERENCES owners(id),
  actor_session_id     uuid NOT NULL REFERENCES human_sessions(id),
  reason               text,
  created_at           timestamptz NOT NULL DEFAULT now(),
  -- N1-11/N1R-6: one canonical subject representation — scope alert (both NULL), job alert
  -- (job only), or operation alert (operation set and job ALWAYS NULL: display context is
  -- derived through provider_operations, never stored).
  CHECK ( (subject_job_id IS NULL AND subject_operation_id IS NULL)
       OR (subject_job_id IS NOT NULL AND subject_operation_id IS NULL)
       OR (subject_operation_id IS NOT NULL AND subject_job_id IS NULL) )
);
CREATE UNIQUE INDEX alert_dismissals_one_per_subject ON alert_dismissals
  (season_id, COALESCE(episode_id,'00000000-0000-0000-0000-000000000000'::uuid),
   COALESCE(extension_id,'00000000-0000-0000-0000-000000000000'::uuid), track, alert_kind,
   COALESCE(subject_job_id,'00000000-0000-0000-0000-000000000000'::uuid),
   COALESCE(subject_operation_id,'00000000-0000-0000-0000-000000000000'::uuid));
CREATE TRIGGER alert_dismissals_append_only BEFORE UPDATE OR DELETE ON alert_dismissals
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
-- N1-4: the last new table gets the same catalog guards as the others — a 0026-style
-- DO loop over ARRAY['alert_dismissals'] adds the statement TRUNCATE refusal and the
-- INSERT/UPDATE integer-number guard.
```

`BLOCKED_OVERRUN` rows are produced by A2 (spec §5.3); the `alert_kind` CHECK admits the value now so A2 needs no migration edit. Dismissal identity follows the **canonical** subject representation (N1-11/N1R-6): job alerts key on the job; operation alerts key on the operation **with `subject_job_id` always NULL** — the CHECK refuses a stored job context, the dismissal writer drops any supplied context instead of persisting it, and the unique identity is therefore deterministic (no duplicate operation dismissals differing only in stored context); scope alerts key on neither; extension scope is part of every key. Job display context for an operation alert is derived by the Python reader through `provider_operations` (the view's operation rows already project `operation_id` only, so the `subject_job_id IS NOT DISTINCT FROM w.job_id` join matches the canonical NULL). A dismissal only flips visibility; nothing is completed or approved (AR-4).

`track_waits` view (full SQL; spec §3 + AR-4, fixes N1-1/N1-9/N1-10/N1-11):

```sql
CREATE VIEW track_waits AS
-- N1R-1: RECURSIVE is required — the repl CTE references itself; every wait_rows branch
-- projects the same nine columns (season, episode, extension, track, kind, effective_at,
-- job, operation, cause).
WITH RECURSIVE v3_jobs AS (
  SELECT j.id AS job_id, j.season_id, j.episode_id, j.extension_id, j.track, j.status,
         j.defer_reason, j.run_after, j.created_at, j.logical_work_id, j.replaces_job_id, j.input,
         COALESCE(x.content_revision, et.content_revision, st.content_revision) AS fence
    FROM jobs j
    JOIN seasons s ON s.id = j.season_id AND s.workflow_version = 'v3'
    LEFT JOIN season_extensions x ON x.id = j.extension_id    -- extension jobs use the extension fence
    LEFT JOIN episode_tracks et ON et.episode_id = j.episode_id
    LEFT JOIN season_tracks st ON st.season_id = j.season_id
   WHERE j.track IS NOT NULL
),
stale AS (   -- a job pinned below its scope's current fence is not current authority
  SELECT job_id FROM v3_jobs
   WHERE (input->>'expected_content_revision') IS NOT NULL
     AND (input->>'expected_content_revision')::bigint < fence
),
repl(root_id, job_id) AS (   -- transitive replacement chain per logical work (validated links)
  SELECT f.job_id, r.job_id FROM v3_jobs f JOIN v3_jobs r ON r.replaces_job_id = f.job_id
   WHERE f.logical_work_id IS NOT NULL
  UNION ALL
  SELECT p.root_id, r.job_id FROM repl p JOIN v3_jobs r ON r.replaces_job_id = p.job_id
),
wait_rows AS (
  SELECT season_id, episode_id, extension_id, track,
         CASE defer_reason
           WHEN 'QUOTA_5H' THEN 'WAITING_QUOTA'  WHEN 'PACE_WEEK' THEN 'WAITING_QUOTA'
           WHEN 'QUOTA_UNREADABLE' THEN 'WAITING_QUOTA' WHEN 'CONCURRENCY' THEN 'WAITING_QUOTA'
           WHEN 'BUDGET' THEN 'WAITING_BUDGET'
           WHEN 'GATEWAY_UNAVAILABLE' THEN 'WAITING_PROVIDER'
           WHEN 'PROVIDER_RATE_LIMITED' THEN 'WAITING_PROVIDER'
           WHEN 'RATE_LIMITED' THEN 'WAITING_PROVIDER' END AS wait_kind,
         run_after AS effective_at, job_id, NULL::uuid AS operation_id, defer_reason AS cause
    FROM v3_jobs
   WHERE status = 'RETRY_WAIT' AND defer_reason IS NOT NULL
     AND defer_reason IN ('QUOTA_5H','PACE_WEEK','QUOTA_UNREADABLE','CONCURRENCY','BUDGET',
                          'GATEWAY_UNAVAILABLE','PROVIDER_RATE_LIMITED','RATE_LIMITED')
     AND job_id NOT IN (SELECT job_id FROM stale)
  UNION ALL
  SELECT season_id, episode_id, extension_id, track, 'BLOCKED_RECONCILE', NULL, job_id, NULL,
         'needs_reconciliation'
    FROM v3_jobs WHERE status = 'NEEDS_RECONCILIATION' AND job_id NOT IN (SELECT job_id FROM stale)
  UNION ALL
  -- Operation alerts key on operation identity only (N1-11); job context is display data.
  SELECT j.season_id, j.episode_id, j.extension_id, j.track, 'BLOCKED_RECONCILE', NULL,
         NULL::uuid, po.id, 'operation_unresolved'
    FROM provider_operations po JOIN jobs j ON j.id = po.job_id
    JOIN seasons s ON s.id = j.season_id AND s.workflow_version = 'v3'
   WHERE po.state IN ('PENDING_SUBMIT','SUBMITTED','RUNNING','UNKNOWN') AND j.track IS NOT NULL
  UNION ALL
  SELECT f.season_id, f.episode_id, f.extension_id, f.track, 'BLOCKED_FAILED', NULL, f.job_id, NULL,
         'failed_terminal'
    FROM v3_jobs f
   WHERE f.status = 'FAILED' AND f.logical_work_id IS NOT NULL
     AND f.job_id NOT IN (SELECT job_id FROM stale)
     AND NOT EXISTS (SELECT 1 FROM repl p JOIN v3_jobs r ON r.job_id = p.job_id
                      WHERE p.root_id = f.job_id AND r.status = 'SUCCEEDED'
                        AND r.season_id = f.season_id
                        AND r.episode_id IS NOT DISTINCT FROM f.episode_id
                        AND r.extension_id IS NOT DISTINCT FROM f.extension_id
                        AND r.track = f.track
                        AND (r.input->>'expected_content_revision')::bigint
                            >= COALESCE((f.input->>'expected_content_revision')::bigint, 0))
  UNION ALL
  SELECT st.season_id, NULL::uuid, NULL::uuid, 'planning', 'CANCELLED', st.cancelled_at, NULL, NULL,
         'season_cancelled'
    FROM season_tracks st WHERE st.cancelled_at IS NOT NULL
  UNION ALL
  SELECT e.season_id, et.episode_id, NULL::uuid, t.track, 'CANCELLED', et.cancelled_at, NULL, NULL,
         'episode_cancelled'
    FROM episode_tracks et JOIN episodes e ON e.id = et.episode_id
    CROSS JOIN (VALUES ('production'),('release')) AS t(track)
   WHERE et.cancelled_at IS NOT NULL
)
SELECT w.season_id, w.episode_id, w.extension_id, w.track, w.wait_kind, w.effective_at, w.job_id,
       w.operation_id, w.cause, (d.id IS NOT NULL) AS dismissed
  FROM wait_rows w
  LEFT JOIN alert_dismissals d
    ON d.season_id = w.season_id AND d.track = w.track AND d.alert_kind = w.wait_kind
   AND d.episode_id IS NOT DISTINCT FROM w.episode_id
   AND d.extension_id IS NOT DISTINCT FROM w.extension_id
   AND d.subject_job_id IS NOT DISTINCT FROM w.job_id
   AND d.subject_operation_id IS NOT DISTINCT FROM w.operation_id;
```

Semantics: several waits show together (one row each); one job resuming clears only its own row; unresolved operations block **without** a job-status filter (cancelled/stale jobs keep their exposure until reconciliation settles it — `S/core/jobs.py:864-871` leaves ops untouched on cancel); operation rows carry `operation_id` only — the Python reader (`S/core/v3_tracks.py: track_waits(tx, *, season_id, track, episode_id=None, extension_id=None)`; N1-9 adds `extension_id`) joins the operation's job for display; a dismissal only marks `dismissed=true`. **`defer_reason IS NULL` on a `RETRY_WAIT` job is an ordinary bounded transport retry**: it projects no side-state wait and the UI shows the job as retrying (ruling 2). Every enum value maps explicitly; there is no fall-through and no read-time CHECK on the view — the closed `DeferReason` vocabulary is enforced at the **jobs table write boundary by A0's 0027** (§3; N1-10). A successful replacement clears a failure only through validated `replaces_job_id` links, within the same scope, track and applicable content authority — a stale success cannot clear a current failure (N1-9). Replacement chains are acyclic by construction: links are immutable and validated to point at older jobs.

**Catalog registration:** `X/integration/persistence/test_migrations.py:32` `EXPECTED_TABLES` += all seven new tables; the tail assertions (`:145`, `:214`, `:270` pattern) extend to `0028..0031` (A0 first extends them to `0026..0027`; A1 rebases). `X/integration/persistence/test_schema_catalog.py` needs no edit: it inspects the live catalog (`relkind='r'`), so every new table — `alert_dismissals` included, through its explicit guards — is covered when 0030/0031 land; the `track_waits` view is outside it (views are read-only and DELETE on a view fails by construction).

## 3. Ownership conflict to flag (master §10.0)

Master §10.0 v0.4.4 already carries the amendment this note proposed in v1.1 ("the phase A packages own their work-scope columns as allocated in the A1 design note"). Precise split so nothing is added twice:

| Owner | Migration | Jobs columns | Provider-operation changes |
|-------|-----------|--------------|----------------------------|
| **A0** (v0.4 §5.2, §5.5, §5.6) | 0027 | `defer_reason` (persisted) **under a CHECK enforcing the closed `DeferReason` vocabulary at the jobs write boundary** (ruling 2 / N1-10 — 0027 is not yet built, so **A0-D adds this CHECK**), the claim's `consumed_attempt` record | `REFUSED_PRELAUNCH` + kind-limited transitions (`ALLOWED_MOVES`, the state CHECK), `llm.subscription` in the 0016 per-kind CHECK; `llm_invocations`, `llm_invocation_attempts`, `quota_observations` |
| **A1** | 0031 | `track`, `extension_id`, `logical_work_id`, `replaces_job_id` | none |

No overlap. The `DeferReason` enum itself lives in `contracts/enums.py` (A0-D); A1's view consumes it read-only.

## 4. Contracts

- `S/contracts/enums.py:159` `GateType` += `STORY_LOCK`, `CAST_LOCK`, `TEASER_FINAL`, `LAUNCH`. `ApprovalAction` (:164) is unchanged — all three actions already exist.
- `S/contracts/states.py:122` `GATE_ACTIONS` is **unchanged** (V1). Beside it:

```python
V3_GATE_ACTIONS: Mapping[GateType, frozenset[ApprovalAction]] = {
    gate: frozenset({ApprovalAction.APPROVE, ApprovalAction.REVISE, ApprovalAction.REJECT})
    for gate in GateType  # master §2.1: Approve/Revise/Reject on every V3 gate
}
```

- **V1 gate schema and typed rejection preserved despite the expanded internal enum (N1-3, N1R-2).**
  `ApprovalCommand.gate` (`S/contracts/season.py:272`) is the only V1 contract field over `GateType`.
  Two coordinated changes keep V1 bytes and behaviour intact:
  1. **Explicit V1 schema adapter (N1R-2).** The committed `schemas/v1/ApprovalCommand.schema.json`
     (re-verified at `81b783f`) has `properties.gate = {"$ref": "#/$defs/GateType"}` and
     `$defs.GateType.enum` = exactly `["SEASON_CONCEPT","EPISODE_FINAL"]`. A field-level
     `json_schema_extra={"enum": …}` pin is **wrong on both counts**: it rewrites the field inline and
     leaves `$defs.GateType` expanded to all six values. `S/contracts/build.py` instead pins the
     published v1 model through an explicit adapter that preserves the original two-value
     `$defs.GateType` and the original field `$ref` **exactly** — byte-identical output — while the
     runtime `GateType` enum carries all six values and the runtime membership guard below rejects
     V3 values on the V1 command.
  2. Typed rejection: `_gate_rules` (`S/contracts/season.py:288-291`) gains a membership guard before
     the `GATE_ACTIONS[self.gate]` lookup — a command naming a V3 gate gets the existing `ValueError`,
     never a `KeyError`.
- **Explicit V3 schema/example registration — generation and validation discovery (N1-3, N1R-2).**
  `S/contracts/build.py` `_schema_generation` (:41-44) currently classifies everything non-v2 as v1,
  and the manifest loop (:139) covers only `("v1","v2")`. A1 extends both **sides**: models in
  `.contracts.v3` generate under `schemas/v3` + `examples/v3` with their own manifest, the v3
  directory joins the generation loop, **and validation manifest discovery learns `v3`** so v3
  examples are validated against their manifest, not merely emitted. V3
  examples register through a `V3_VALID_BUILDERS` map beside `VALID_BUILDERS`/`V2_VALID_BUILDERS`
  (`S/contracts/examples.py:694`, `:1988`). **Frozen baseline:** the committed
  `schemas/v1/**` + `examples/v1/**` bytes are asserted equal to the accepted prerequisite baseline
  commit (A0 merge) in A-T1 — drift fails the build, not just `contracts-check` (`Makefile:30,34`);
  the new V1 rejection probes stay **outside** the frozen generated `examples/v1/**` tree (they live
  in the contract test module), so adding them cannot drift the baseline (N1R-2).
- New module `S/contracts/v3.py` (keeps `season.py` V1-clean):

```python
class RevisionTargetKind(StrEnum):
    EPISODE = "episode"; CHARACTER = "character"; VOICE = "voice"
    REFERENCE = "reference"; STORY_UNIT = "story_unit"; NOTE = "note"

class RevisionNoteTarget(ContractModel):
    kind: RevisionTargetKind
    id: UUID

class SeasonRevisionNote(ContractModel):
    note_key: str = Field(min_length=1, max_length=80)
    body: str = Field(min_length=1, max_length=2000)
    targets: list[RevisionNoteTarget] = Field(default_factory=list)  # empty = free-text note

class V3DecisionCommand(VersionedPayload):
    gate: GateType
    action: ApprovalAction
    season_id: UUID
    episode_id: UUID | None = None          # required iff gate is EPISODE_FINAL
    extension_id: UUID | None = None        # N1-16: extension-scope decisions name it
    activation_id: UUID                     # N1R-4: the exact activation this decision closes —
                                            # resolved, required open and scope-matched in §5 step 5;
                                            # displayed forms and the command hash carry it
    expected_revision: Revision             # season_tracks/episode_tracks/season_extensions .revision
    expected_content_revision: Revision     # the scope's content_revision (fence display)
    binding_sha256: Sha256Hex
    idempotency_key: IdempotencyKey
    notes: list[SeasonRevisionNote] = Field(default_factory=list)
    feedback: list[TimecodedFeedback] = Field(default_factory=list)  # EPISODE_FINAL only (N1-2)
    reason: str | None = Field(default=None, max_length=2000)
    # validators: action in V3_GATE_ACTIONS[gate]; (gate is EPISODE_FINAL) == (episode_id is not None);
    # extension_id only with season-scope gates; EPISODE_FINAL: REVISE <=> feedback nonempty, notes
    # empty; season gates: REVISE <=> notes nonempty AND feedback empty; non-REVISE (incl. REJECT):
    # feedback empty — Reject records its explanation in reason (N1R-7), as V1 Gate-2 Reject already
    # does (S/review/service.py:1364); only Revise requires feedback or revision notes.
```

- Targets are validated at decision time against the **activation's binding units**: the resolver (§5) recomputes the binding, and every target `{kind,id}` must be one of its units. No `binding_units` column is persisted — the recomputation is authoritative (and doubles as the stale-page check).
- The negative example `gate1_revise` (`S/contracts/examples.py:2180-2193`) **stays exactly as written** — it asserts the V1 `ApprovalCommand`, which keeps rejecting Gate-1 Revise through the unchanged `GATE_ACTIONS`. New negatives: `v3_revise_without_notes`, `v3_season_revise_with_feedback`, `v3_gate2_revise_without_feedback`, `v3_gate2_season_scope`, `v3_episode_gate_without_episode`, `ApprovalCommand__v3_gate_on_v1_command` (typed rejection, no `KeyError`).
- `X/contract/contracts/test_states_routes_jobs.py:76` `test_gate_actions` is untouched; a sibling test asserts `V3_GATE_ACTIONS` exactly (§10).

## 5. The decision transaction (spec §2.6; AC-3, AC-4)

New module `S/core/v3_gates.py`. **V1 keeps everything unchanged**: `S/core/approvals.py` is not edited beyond §4's typed-rejection guard — its entity lock and revision comparison (`S/core/approvals.py:64-65`) remain the V1 binding resolver; `decide_season`/`decide_episode` (`S/review/service.py:381`, `:1078`) and `_check_binding` (:1092) keep their exact behaviour, now additionally refusing V3 entities via `require_workflow` (§7).

**Revision plan (N1-7, ruling 3 — one transaction-owned plan):** validate at revision *r*, record the approval at *r*, apply authorised handler transitions using that decision context, then advance the decision revision exactly once. The recorder never bumps the revision and the event is never revalidated against *r+1*.

**Binding resolver** (V3 side):

```python
@dataclass(frozen=True)
class GateBinding:
    gate: GateType; season_id: UUID; episode_id: UUID | None; extension_id: UUID | None
    activation_id: UUID
    binding_sha256: str                      # recomputed from current content
    binding_units: tuple[RevisionNoteTarget, ...]
    content_revision: int                    # authoritative scope fence
    decision_revision: int                   # authoritative scope command revision

def resolve_gate_binding(tx: Tx, *, gate: GateType, season_id: UUID,
                         episode_id: UUID | None, extension_id: UUID | None,
                         activation_id: UUID, handler: "GateHandler") -> GateBinding:
    # Caller already holds the scope track lock FOR UPDATE (§6 order).
    # 1. Ancestry proof (N1-6): episode.season_id = season_id; extension.season_id = season_id;
    #    an extension-scoped episode gate must fall inside the extension's episode range.
    # 2. The command's exact activation (N1R-4): it must exist, be open (no
    #    gate_activation_events row) and match the complete scope (gate, season, episode,
    #    extension); anything else -> GateNotReady — a superseded or already-decided
    #    activation is refused even over unchanged content with no revision bump.
    # 3. handler.binding(tx, ...) recomputes the binding hash + units from current content.
    # 4. Returns the binding with the scope's authoritative revisions.
```

**Handler registry** (AC-4) — every method takes the caller's `tx`:

```python
class GateHandler(Protocol):
    gate: GateType
    is_test_handler: bool = False            # intrinsic provenance (N1-13), not a register flag
    def binding(self, tx, *, season_id, episode_id, extension_id) -> GateBinding: ...
    def conditions(self, tx, binding) -> list[str]: ...   # blockers; empty = enabled
    def on_decision(self, tx, *, principal, command, binding, approval_event_id, now,
                    correlation_id) -> None: ...

class GateHandlerRegistry:
    def __init__(self, *, for_testing: bool = False) -> None: ...
    def register(self, handler: GateHandler) -> None: ...
    def get(self, gate: GateType) -> GateHandler | None: ...
```

Registration rules (N1-13, N1R-12): test handlers carry intrinsic provenance — the class attribute is set at definition in the test module, not passed to `register`; `register` refuses an intrinsically-test handler unless the registry itself was constructed `for_testing=True`. **A1 ships the normal-composition validation boundary itself** — `GateHandlerRegistry.validate_for_production()` raises unless the registry was constructed `for_testing=False` **and** no registered handler carries intrinsic test provenance, so production rejects intrinsically-test handlers *and* test-enabled registries regardless of any caller's flag. A1's own normal composition (the factory wiring the V3 decision service into the application) calls it at wiring time: registration alone is not a boundary, because a `for_testing=True` registry could still be handed to normal composition, and `build_production_world` does not exist in current code (it is A6) — so the boundary may not be assigned there; **A6 must reuse `validate_for_production()`** rather than grow a parallel check. A missing V3 handler returns `NOT_AVAILABLE` **before any recording or callback** and **never falls back to V1**. A1 ships exactly one test-world LOCK handler (minimal binding over the proposal scope hash) for A-T2/A-T4; B+ replaces it with real handlers.

**Step order** (one caller-owned transaction; locks in §6 order):

1. `IdempotencyService.execute` opens the transaction and locks the idempotency row first — a replay returns the stored response before fresh validation (`S/core/idempotency.py:83-89`). **Preflight seam (N1-12):** a `preflight` callable (registry lookup for the gate) runs after the replay lookup and **before the idempotency-record INSERT** (`:91-95`) — an unavailable command raises `NOT_AVAILABLE` with no idempotency write, no approval, no job, no event.
2. Lock the scope track FOR UPDATE (episode gates: `season_tracks` then `episode_tracks`; extension scopes: `season_tracks` then `season_extensions`).
3. **Owner scope first** (N1-6): `scoped_owner_id` (`S/review/scope.py:64`) with the NotFound-as-missing rule of `S/review/service.py:401-404` — a foreign scope answers like a missing one before any workflow/state error is exposed.
4. `require_workflow(tx, season_id, expected='v3')`; then the resolver's ancestry proof (episode → season, extension → season).
5. `resolve_gate_binding` resolves the **command's exact `activation_id`** (N1R-4) — it must exist, be the scope's **open** activation, and match the complete scope (gate, season, episode, extension) **before** any comparison; then the **three-way comparison under the locks (N1-6)** — activation's stored `binding_sha256` = recomputed hash = command's hash; activation's `decision_revision` = track `revision` = command's `expected_revision`; activation's `content_revision` = track `content_revision` = command's `expected_content_revision`. A mismatch is `StaleRevision` (command vs authority) or `GateNotReady` (activation vs authority — changed authority requires a fresh activation: supersede, reopen). **A concurrent second decision re-checks openness under the track lock first and is refused `GateNotReady` for the already-closed activation (N1R3-6); the §2.3 partial indexes (`approval_events_one_decision_per_activation` / `approval_events_v3_one_per_revision`) remain the commit-time backstop** — V1 rows keep the preserved partial `approval_events_one_per_revision` (`M/0002…sql:208`) — reported like `S/core/approvals.py:108-116`.
6. `handler.conditions(tx, binding)` → nonempty is `GateNotReady`.
7. **Record at r**: `record_v3_decision(tx, ...)` (new, `S/core/v3_approvals.py`) inserts the `approval_events` row at revision *r* **persisting the command's `activation_id` and `extension_id` — the immutable decision identity whose workflow-resolved partition and scope linkage the deferred §2.3 trigger validates at commit (N1R-3, N1R3-1)** (EPISODE_FINAL REVISE carries timecoded feedback, persisted to `feedback_events` exactly as V1 does; season-gate REVISE carries ≥1 typed notes row and empty feedback — the deferred trigger backstops; every Reject carries empty feedback with its explanation in `reason`, N1R-7), appends `approval.recorded`, and appends the **`DECIDED` activation event** closing the activation.
8. `handler.on_decision(tx, ...)` with the decision context (revision *r*, binding, approval id): its writes, job enqueues, events and **authorised track transitions** join this transaction (e.g. STORY_LOCK APPROVE moves planning `PLANNED → STORY_LOCKED` here — §6).
9. **Advance once:** the transaction bumps the scope's `revision` *r → r+1* as its final track write. Neither the recorder nor the handler bumps it.
10. The idempotent response is stored. Any failure at any step rolls everything back.

Human-session, CSRF and service-credential rules are the existing ones: `require_human_owner`, the route-level refusal of non-human principals (`S/review/api.py:201`), CSRF on unsafe methods. **Routes:** JSON `POST /v3/seasons/{season_id}/gates/{gate}/decision` plus a minimal HTML form under `/ui/v3` reusing the session/CSRF machinery (both needed for A-T3's JSON+HTML coverage; the full UI is A5). Gate 2 command availability stays deferred until F (OQ-6 ruling).

## 6. The command table (spec §3; AC-6, AR-3, AR-6)

`TrackService` (new, `S/core/v3_tracks.py`). Commands where a human acts run through `IdempotencyService.execute` **with the §5 preflight seam**; gate-edge advancement that runs outside a decision transaction proves the gate's `DECIDED` event is the scope's latest terminal activation fact (`v3_require_gate_approval`, the track-based sibling of `S/core/state_machine.py:93`, which stays V1-untouched).

| Command | Actor | Scope / revision owner | Edges and effect | Writes · jobs · events | Activation |
|---|---|---|---|---|---|
| `create_v3_season(intake_ref)` | Operator (human session) | season / — | — → seasons(v3, PROPOSED) + `season_tracks(IDEA, NOT_SCHEDULED)` + `SEASON_SETUP` account | W: seasons row, `season_tracks` row, SEASON_SETUP account · J: none · E: `season.created_v3`, `track.created` | **A2** — `NOT_AVAILABLE` in A1 |
| `create_v3_episodes(season, count)` | System (STORY LOCK handler); exposed to test handlers in A | season / `season_tracks.revision` | planning `PLANNED → STORY_LOCKED`, atomically with episode creation (legacy PLANNED) + `episode_tracks` + accounts | W: episode rows, `episode_tracks` rows, accounts · J: none in the command itself (the handler may enqueue per §5 step 8) · E: `episode.created` + `track.created` per episode | **A2** |
| `open_gate(gate, scope, binding)` | System (phase-handler job) | season/episode/extension / read under track lock | `gate_activations` row; §8 admission checks (zero live exposure, verified pod resolution, no open activation — N1R-9); idempotent under the track lock — an already-open activation for the (gate, scope) is returned | W: `gate_activations` row · J: none · E: `gate.opened` | **A1** |
| `supersede_gate(activation, successor?)` | System | season/episode/extension / activation open | appends a `SUPERSEDED` event (+ optional successor link); **no approval fabricated** (N1-5); idempotent by the event's `UNIQUE(activation_id)` | W: `gate_activation_events` row · J: none · E: `gate.superseded` | **A1** |
| `decide(gate, scope, activation, action, …)` | Operator (human session + CSRF) | season/episode/extension / scope `revision` | §5 — the command names its exact `activation_id` (N1R-4); transitions run inside the decision; Reject results per the table below (AR-3) | W: `approval_events` row (with `activation_id`/`extension_id`, N1R-3) + notes or `feedback_events` + `gate_activation_events` DECIDED row + one track `revision` advance (+ `content_revision` on lock approvals) · J: handler callback enqueues only · E: `approval.recorded`, `gate.decided`, `track.advanced` | **A1** (LOCK via test handler in tests; unshipped gates → `NOT_AVAILABLE`) |
| `advance_planning(to)` | System (phase handler) or test handler | season: `season_tracks.revision`; **extension: `season_extensions.revision`** (N1-15) | master edges `IDEA→PROPOSED→LOCKED→BIBLE→PLANNED→STORY_LOCKED→CASTING→CAST_LOCKED`; gate edges (`PROPOSED→LOCKED`, `PLANNED→STORY_LOCKED`, `CASTING→CAST_LOCKED`) are authorised **inside the deciding transaction** (§5 step 8); a standalone gate-edge advance proves the `DECIDED` event as above; every other master edge is `NOT_AVAILABLE` until its phase | W: `season_tracks`/`season_extensions` update · J: phase-handler enqueues in the same transaction (§9 row) · E: `track.advanced` | **A1** (mechanism); edge availability follows B+ |
| `advance_production(to)` | System (phase handler) | episode / `episode_tracks.revision` | `PLANNED→DIRECTED→RENDERING→EDITING→DRAFTING→AWAITING_REVIEW`; `AWAITING_REVIEW→APPROVED` only inside an EPISODE_FINAL APPROVE (F); each edge `NOT_AVAILABLE` until its phase (B/C/D/E) | W: `episode_tracks` update · J: phase-handler enqueues · E: `track.advanced` | mechanism **A1**; edges B+ |
| `advance_release(to)` | System (calendar/publish admission) | season / `season_tracks.revision`; episode / `episode_tracks.revision` | season: `NOT_SCHEDULED→CALENDAR_PROPOSED` (operator calendar), `→LAUNCH_APPROVED` (LAUNCH APPROVE, in the decision), `→RELEASING`, `→COMPLETE`; episode: `UNSCHEDULED→SCHEDULED`, `SCHEDULED→PUBLISHING` (publish admission), `PUBLISHING→PUBLISHED_VERIFIED`; `HELD/MISSED/PARTIAL` stay per-destination on `platform_posts` (`M/0005…sql:51`) | W: `season_tracks`/`episode_tracks` update · J: publish-admission jobs (F) · E: `track.advanced` | mechanism **A1**; edges F |
| `cancel_season` / `cancel_episode` | Operator (human session) | season/episode / track revision | terminal: `cancelled_at`; legacy `seasons.state` untouched for V3; jobs cancelled via `cancel_in` (A3) | W: track `cancelled_at` · J: cancellation through `cancel_in` (A3) · E: `track.cancelled` | **A3** |
| `rewind_for_amendment(scope, to)` | System (amendment coordinator only) | season/episode / `content_revision` + revision | backward planning edge inside the master §12.6 closure; impact hash + Confirm (A4) | W: planning track rewind + `content_revision` bump (A4) · J: re-planning jobs (A4) · E: A4's amendment events | **A3/A4** |
| `create_extension(season, range, calendar)` | Operator (human session) | season / `season_tracks.revision` | opens `season_extensions` (open row ⇒ `EXTENDING`) with an explicit continued/resumed calendar; **eligibility master §4.3: season release in `RELEASING` or `COMPLETE`** (N1-16); range beyond the current episode count; prior season approvals preserved | W: `season_extensions` row + calendar · J: none · E: `extension.opened` | **B** (OQ-1) |

The `Writes · jobs · events` column is the A1 event vocabulary (`track.*`, `gate.*`, `season.*`, `extension.*` appends beside the existing `approval.recorded`); every command appends its events inside its own transaction, and no command's jobs escape its transaction except where the row says so (`cancel_in` is A3's).

**Reject result, every gate (AR-3; N1-15, N1R-7).** No Reject moves a state and none bumps `content_revision`; the activation closes (`DECIDED` event) and the scope revision advances once. Only Revise requires feedback or revision notes — **Reject carries empty timecoded feedback on every gate and records its explanation in `reason`** (N1R-7), exactly as V1 Gate-2 Reject already uses `reason` (`S/review/service.py:1364`); the state consequences below are unchanged.

| Gate | Reject consequence |
|------|--------------------|
| `SEASON_CONCEPT` | no concept authority; planning stays `PROPOSED` |
| `STORY_LOCK` | no episode-creation authority; planning stays `PLANNED` |
| `CAST_LOCK` | planning stays `CASTING` **without cast authority** |
| `TEASER_FINAL` | no teaser authority; release track untouched |
| `LAUNCH` | release stays `CALENDAR_PROPOSED` **without launch authority**; planning untouched |
| `EPISODE_FINAL` | episode stays `AWAITING_REVIEW`; no approval binding; explanation in `reason`, feedback empty (N1R-7) |

**Identity and replay (N1-15, N1R-4).** Activation replay identity is the activation row plus the decision's idempotency key — retries replay; a deliberate new activation may reuse unchanged content (no `(gate, scope, hash)` key). `V3DecisionCommand` hashing includes `activation_id`, and every displayed decision form (JSON, HTML, the A5 UI) names the activation it decides — an old page can never match a replacement activation over unchanged content. Command replay identities: human commands — idempotency key; system commands — semantic `(scope, from, to, revision)` keys.

AR-6: commands whose dependencies have not shipped return `NOT_AVAILABLE` **before any write** (§5 step 1 preflight); their behavioural gates move with activation (A-T4 asserts the refusal; A2/A3 tests the behaviour). `content_revision` bumps only on amendments and lock decisions (spec §3) — STORY LOCK and CAST LOCK APPROVE bump it; other decisions bump only `revision`.

## 7. The `require_workflow` inventory (AC-5)

New helper `S/core/workflow.py`:

```python
class WorkflowMismatch(MicrodramaError):   # HTTP 409
    code = "WORKFLOW_MISMATCH"

def require_workflow(tx: Tx, *, season_id: UUID | None = None, episode_id: UUID | None = None,
                     expected: str = "v1") -> None:
    """Resolve the season through the episode FK when needed; plain read, no lock."""
```

Two guard classes, applied by call shape (N1-14, N1R-10): **(a) refusal** — after owner access, `require_workflow(..., expected='v1')` at every **direct** legacy read and decidability boundary (`season_view`, `episode_review`, `episode_page`, direct progress calls), **before projection or package interpretation**: a V3 row reaching a legacy direct read raises `WORKFLOW_MISMATCH` (409) — never silently processed, and never a filtered-away NotFound, which would hide the version conflict the spec names; **(b) candidate filters** — applied **only to enumeration** (scheduler selectors and listing queries: `AND s.workflow_version = 'v1'` / joined equivalent) so a V3 season never becomes legacy work and never surfaces in a V1 listing. **Direct callers are guarded as well as routed jobs; shared owner-access helpers stay untouched** (spec §1: no blanket filters); until versioned adapters exist, **unsupported V3 execution refuses before any effect** (N1-14).

| Entry point (`file:function`) | Guard |
|---|---|
| `S/research/service.py:353 _open_run` (entry `run_research`), `:878 _write_proposal` | refusal after the season row is claimed |
| `S/review/intake.py:700 _create_intake`, `:760 select`, `:880 _status`, `:971 _phase`, `:1012 handle_research_job`, `:1381 _workbench` | refusal (V3 seasons use `create_v3_season`, never intake) |
| `S/story/service.py:473 compile_season`, `:733 _claim_episode` (accepts pinned PLANNED, factmap `:752`), `:1321 _persist_success`, `:911 clear_write_claim` (recovery) | refusal at claim, persist and recovery |
| `S/references/service.py:413 _claim`, `:1074 _persist`, `:1438 _change_claim` | refusal |
| `S/editing/service.py:638 _claim`, `:994 _persist`, `:226 rebuild_caption_outputs` | refusal |
| `S/qa/repairs.py:508 plan_from_feedback`, `:975 execute_plan`, `:1424 _reopen_gate2` | refusal |
| `S/pipeline/packaging.py:223 prepare_and_store_package`; `S/review/packages.py:216 store_release_package` | refusal |
| `S/publishing/slots.py:117 schedule_release`; `S/publishing/service.py:341 _validate_and_begin`, `:776 _mark_publishing`, `:902 _maybe_complete_episode`, `:1072 release_view` | refusal |
| `S/analytics/qualification.py:90 _episode_facts` (covers `:200 _production_qualifies`, `:249 _management_window`) | refusal (V3 qualification is phase B+) |
| Selectors `S/scheduling/service.py`: `:169 _w01_research`, `:183 _w02_compile_backstop`, `:199 _w03_episode_cadence` (its direct INSERT at `:228` gets a refusal inside the insert transaction), `:242 _w03_write`, `:263 _w04_references`, `:279 _w06_edit`, `:333 _w07_qa`, `:538 _w09_publish_submit`, `:630 _w09_publish_poll`, `:677 _w11_analytics`, `:697 _w05_render_dispatch`, `:770 _w05_render_poll` | candidate filter on the selection SQL (`JOIN seasons s … AND s.workflow_version='v1'`; `_w05_render_poll` filters through `jobs.season_id`) |
| Replayed jobs: `S/workers/runtime.py:216 _execute` (before handler dispatch at `:236`); `S/core/jobs.py:752 resolve_reconciliation` (the `_w05_render_poll` resolution path) | refusal — a V3 job never runs a V1 handler; V3 job types are distinct and registered per phase |
| `:822 _w12_workers_janitor`, `:829 _w12_gpu_janitor` | via the adapters below |

**Boundaries added in v1.2 (N1-14 — every checklist row, compact):**

| Boundary | Sites | Guard |
|---|---|---|
| Direct approval recorder; legacy state/approval authority | `S/core/approvals.py:50`; `S/core/state_machine.py:93,153,233,322,395` | refusal — V1-only; a V3 entity raises `WORKFLOW_MISMATCH` |
| Review summaries and listings (enumeration only) | `S/review/service.py:330,348,1228` + their JSON/HTML routes and templates | candidate filter at the callers; shared owner-access helpers untouched |
| Direct season/episode views, page enablement, decidability | `S/review/service.py:363 season_view`, `:547`, `:582 episode_review`, `:621 episode_page` + their routes/templates | refusal — `require_workflow(expected='v1')` after owner access, before projection (N1R-10) |
| Progress and V1 listing selection | `S/review/service.py:710,717`; `S/review/progress.py:527,580`; V1 callers of `S/review/scope.py:136 owner_season_rows` | direct progress reads: refusal after owner access (N1R-10); listing selection: filter at the callers |
| Metadata preparation and package decision writers | `S/review/service.py:731,955,992,1014`; `S/review/packages.py:62,97,309` | refusal |
| Identity authority, review marking, attachment | `S/references/identity_lock.py:82,275,309`; `S/references/service.py:212,240,266,285,310` | refusal |
| Approved publication metadata; post recovery/mutations | `S/publishing/metadata.py:173 approved_live_binding`; `S/publishing/service.py:793,947,1045,1060` | refusal |
| Membership approval authority | `S/memberships/catalog.py:397,413` (public mutation paths) | refusal |
| Repair paths bypassing the listed methods | `S/qa/repairs.py:444,1149`; `S/editing/service.py:226`; story recovery `S/story/service.py:911` | refusal |
| Fixture/mock assumptions; direct episode creation | `S/pipeline/runner.py:290 create_episode` (V1-only workflow contract) | refusal before effects |

A4's future `effective_approval` reader (spec §7.2) does **not** substitute for this isolation — it changes authority reads, not execution admission (N1-14).

**Per-version adapters for the shared janitors** (not blanket V1 filters — spec §1): workers janitor `requeue_expired` (`S/core/jobs.py:706`) — the job lifecycle is version-shared, no filter, the V3 projection being `track_waits` (a quarantined job shows `BLOCKED (reconcile)`); GPU janitor `_sweep_leases`/`_cause` (`S/rendering/janitor.py:237`, `:272`) — the candidate query gains a V3 arm: a live lease whose scope has an **open gate activation** is a candidate with cause `human_wait` (§8), the V1 `e.state='AWAITING_FINAL_REVIEW'` arm untouched; billing janitors — A2 (V3 scope kinds land there), A1 adds no budget-janitor change.

## 8. GPU human-wait safety (AC-9; N1-8, N1R-8, N1R-9)

One admission protocol, not scattered predicates. **Every gate/pick activation and every lease
insertion, admission, adoption and transfer mutation takes the scope's track lock (§6 #2/#3) FOR
UPDATE first — before any lease, job or budget lock — and re-checks the counterpart predicate under
it. Owning transaction, mode and order are named per mutation (N1R-8): the track row FOR UPDATE is
the ancestor lock, and where the pre-existing code commits separately (the reservation-then-insert
pattern; `ensure_pod`'s create-request/pod-binding/activation chain), **each committed mutation
re-takes the scope lock inside its own transaction and re-checks under it** — no lock is "already
held" across separately committed operations. One canonical sequence per transaction (N1R3-3):
scope track (#2/#3) → job (#5, where the path already takes `lease_guard`) → provider-operation
serialization/advisory and rows (#6) → lease row/pod writes (#6) → budget/reservation locks
(#7, where applicable) — a transaction never takes a budget lock ahead of its lease rows, and the
v1.3 "#6 → #7 → lease writes" listing is withdrawn. The pod path's separately committed
transactions are enumerated individually in §9 — create-request, pod-binding and activation — each
naming its scope-lock reacquisition and the intervening provider call (N1R3-3;
`S/rendering/leases.py:901-913`, `:919`, `:943`, `:970`).**

| Attachment | Where | Rule under the scope lock |
|---|---|---|
| Gate/pick activation | `TrackService.open_gate` (§6); pick activation (C) reuses it | **admission predicate (N1R-9): refuse while any live lease exists in scope** (episode: `S/rendering/leases.py:204 episode_live_lease_count`; season: new `season_live_lease_count`) **and until every prior lease in scope is resolved**, where resolved means exactly one of: (i) a verified shutdown of its own (`record_terminate_verified`, `S/rendering/leases.py:468`); (ii) **transferred away** — its compute window closed at the transfer instant and it deliberately has no verified stop of its own (`:1376`, T045 R8/G16); ownership of termination follows the transfer chain to its **final holder**, whose stop must be verified; (iii) **durably proven no-create** — no pod was ever requested or recorded for it. Only an *unverified shutdown of a potentially created pod* blocks; transferred history and proven no-create never do. A wait is exposed only after zero live exposure plus full resolution — no GPU is held while a human wait opens (master §10.5) |
| Lease admission | `claim` (`S/rendering/leases.py:671`, incl. `_w05_render_dispatch`'s claim at `S/scheduling/service.py:747`; insert at `:789`) | refuse when an open activation exists for the scope. The reservation-then-insert two-transaction pattern (`:674-676`) stays; **owning transactions (N1R-8): the reservation transaction and the lease-insert transaction each take the scope track row FOR UPDATE first and re-check the activation predicate before their INSERT (#7 reservation tx; #6 lease tx)** — the activation race is closed inside both committed mutations, not by a lock held across them |
| Pod acquisition / reactivation | `ensure_pod` (`:876`; `_record_create_request:940`, `_record_pod_id:916`, `_activate:968`) | same check, re-taken in **each of the three separately committed transactions** (N1R3-3) — create-request (`:940`), pod-binding (`:916`) and activation (`:968`) each reacquire the scope track lock FOR UPDATE, re-check admission, then take the lease row FOR UPDATE before their write; the provider create call (`acquire_or_reconcile:902`) intervenes between create-request and pod-binding under **no** held data lock, before any new external submit under that scope |
| Actual Comfy dispatch / adoption | begin/dispatch boundary: `_submit_bound_graph` (`S/rendering/comfy_jobs.py:600`): the guarded begin transaction (`:611-623`) **commits the durable operation intent first**; only then is the graph submitted over HTTP (`queue_prompt`, `:630`), and the submission outcome is persisted by a **separate** transaction (`record_result(SUBMITTED, external_id)` at `:639`; `_fail_without_dispatch`/`_mark_unknown` on the failure paths). `_load_current_prompt_manifest:572` is a preceding locator read; `_verify_job:703`/`_collect_outputs:914` and the `reconcile_unknown` paths are adoption/reconciliation | **the real order is preserved, not inverted (N1R3-2): the guarded begin/rearm transaction commits before submission.** Its sequence: scope track FOR UPDATE (#2/#3) → re-check admission → `lease_guard` job SHARE (#5, `S/core/jobs.py:648`) → `provider_ops.begin`'s serialization (`pg_advisory_xact_lock` per job then per reservation, `S/core/provider_ops.py:121`; begin's reservation FOR SHARE precedes for V1 callers, preserved verbatim) → operation INSERT → **commit**. Dispatch then **reacquires the ordered scope/job/operation/lease/reservation guards and revalidates admission against the already-durable operation** before the external submit — the provider is never accepted against an operation that can still roll back (A3 §9 A-T18 boundary (1)). The outcome persists separately (`:639`), and an ambiguous submission retains its durable reconciliation identity — the committed operation row drives recovery, never a resubmit guess. The V3 composition's full begin/rearm chain (#6 before #7, eligibility first) is specified and tested in A3 §7; this row supplies the admission predicate A3's composition re-checks under the scope lock |
| Transfer | `transfer` (`:1319`; final transaction `:1361`) | destination scope's track lock first; refuse when the destination has an open activation. **Owning transactions (N1R-8): the reservation (`:1357`, `_reserve_for_lease`, its own transaction) and the final transfer transaction (`:1361`: destination scope FOR UPDATE → old lease FOR UPDATE `:1362` → release + new-lease insert) each re-take the destination scope lock and re-check the activation predicate before committing** |
| Heartbeat | `heartbeat` (`:1019`) | the existing human-wait branch (`:1031-1039`) fires only for a **non-ACTIVE** lease; V3 adds an explicit refusal for an **ACTIVE** lease whose scope has an open activation — an ACTIVE V3 lease cannot be kept alive through a wait; the janitor is the cleaner |
| Janitor candidate + `_cause` | `S/rendering/janitor.py:237 _sweep_leases`, `:272 _cause` | candidate query adds `OR EXISTS (open activation for the lease's season/episode/extension)`; `_cause` returns `'human_wait'`, reusing the terminal mapping in `_clean_lease` (`:302-309`) — verified shutdown, accrual accounted |

**Season/extension-owned GPU work (N1-8):** none exists until F (teaser rendering). Ownership is defined now — season-owned work admits against the same season track lock and season-scope wait predicate; extension-owned work against the extension's scope (season + extension identity, extension fence). F registers its work types under this rule; A1 ships the helper (`S/core/workflow.py`):

```python
def v3_human_wait(tx: Tx, *, season_id: UUID, episode_id: UUID | None = None,
                  extension_id: UUID | None = None) -> bool:
    """True while any gate activation is open for the scope (episode gate: that episode;
    season gate: the season; extension: the extension scope) — 'waiting for you' (spec §2.5)."""
```

`HUMAN_WAIT_STATES` (`S/rendering/leases.py:90`) and `human_wait_guard` (`:212`) stay V1-untouched; V3's pinned `PLANNED` episodes never enter that EpisodeState path, which is why the checks attach at the activation/lease layer (AC-9's point). Waits are scope-keyed (episode gate → that episode; `TEASER_FINAL`/`LAUNCH` → no episode admits new leases **anywhere in the season**, episode admission included, N1R-8) so unrelated approved releases continue — publishing paths take no leases.

## 9. Lock audit (spec §6; N1-17)

| # | Lock |
|---|------|
| 1 | Command idempotency row |
| 2 | `season_tracks`, then `season_extensions` |
| 3 | `episode_tracks` (id order) |
| 4 | Scope domain rows (seasons, episodes, approvals) |
| 5 | Jobs (id order) |
| 6 | `provider_operations` → leases (GPU) |
| 7 | Budget (mutex → SEASON → children → steps → categories → reservations → charges) — A2 |

Transactions A1 adds or touches, including every GPU transaction the §8 protocol now enters:

| Transaction | Locks in order | Verdict |
|---|---|---|
| V3 decision (§5) | 1 (`S/core/idempotency.py:84-87`) → 2 `season_tracks` FOR UPDATE (→ 3 `episode_tracks` for Gate 2; → 2 `season_extensions` for extension scopes) → 4 seasons row (ownership+version, mirroring `S/review/service.py:401`) → approval/notes/`DECIDED`-event inserts → 5 job enqueues by the callback → single revision advance | conforms |
| `open_gate` / `supersede_gate` | 2 track lock → 6 live-lease count + resolution reads (verified stop / transferred-with-verified-final-holder / durably proven no-create, N1R-9; guarded counts, no lease row lock) → activation/event insert | conforms |
| Lease admission, V3 arm of `claim` | **two committed mutations, each owning its locks (N1R-8):** reservation tx = 2/3 scope track FOR UPDATE → re-check → 7 reservation INSERT; lease tx = 2/3 scope track FOR UPDATE → re-check → 6 lease INSERT (`S/rendering/leases.py:789`). The pre-existing two-transaction pattern (`:674-676`) is unchanged; the scope lock is **re-taken inside each transaction**, never held across commits — the v1.2 "already-held scope lock" phrasing is withdrawn | conforms |
| Comfy dispatch (V3 admission arm) | **begin/rearm transaction, committed before submission (N1R3-2):** 2/3 scope track FOR UPDATE (§8 admission) → 5 job SHARE (`lease_guard`, `S/core/jobs.py:648`) → 6 provider-operation xact advisories — per job, then per reservation (`_lock_linked`, `S/core/provider_ops.py:121`) → 6 operation INSERT (`_submit_bound_graph`'s `begin`, `S/rendering/comfy_jobs.py:611-623`) → **commit** — then the HTTP submit (`:630`) under the reacquired ordered guards, its outcome persisted by a separate transaction (`:639`) | conforms — **durable intent is committed before the external submit (the real `comfy_jobs.py` sequence and A3 §9 A-T18 boundary (1)); the v1.3 "operation INSERT / queue submit → commit" listing is withdrawn (N1R3-2)**; V1 `begin` keeps its verbatim shape (reservation FOR SHARE before the advisories; A3 §7 asserts it unchanged for V1 callers); the V3 composition's #6-before-#7 order with eligibility validated first is A3 §7's audited and separately tested chain — this row adds only the #2/#3 admission prefix and predicate |
| `ensure_pod` path — three separately committed transactions (N1R3-3) | **create-request tx**: 2/3 scope track FOR UPDATE → re-check → 6 lease row FOR UPDATE → `create_requested_at` write (`:940`) → commit; **provider create call** (`acquire_or_reconcile:902`, no data locks held); **pod-binding tx**: 2/3 → re-check → 6 lease row FOR UPDATE → `pod_id` write (`:916`); **activation tx**: 2/3 → re-check → 6 lease row FOR UPDATE → ACTIVATE write (`:968`) | conforms — each transaction reacquires the scope lock and re-checks admission under it; the provider call never runs under a held data lock; the v1.3 single-row compression ("2/3 → 6 lease row → provider call → 6 activation write") is withdrawn |
| `transfer` | **two committed mutations, each re-taking the destination scope lock (N1R-8):** reservation tx = 2/3 destination FOR UPDATE → re-check → 7 reservation (`:1357`); final tx = 2/3 destination FOR UPDATE → re-check → 6 old lease FOR UPDATE (`:1362`) → 6 new-lease insert (`:1361`) | conforms |
| `advance_planning` / `advance_production` / `advance_release` | 2 (→ 3 for episode-scoped edges) → 4 → 5 (only when a phase handler enqueues) | conforms |
| `create_v3_episodes` (A2 activation) | 2 → 4 seasons → episode INSERTs → 3 `episode_tracks` INSERTs → 7 budget attach (A2) | justified: the "#3" step is an insert of rows that do not yet exist, not a row lock; inserts serialise under #2/#4 and the `episode_id` unique index — the v1.1 row's literal `2 → 4 → 3` was an ordering of effects, not locks |
| V1 decision paths | unchanged (`S/review/service.py:401`, `:1129`; `S/core/approvals.py:64`) — V1 never locks tracks, so no cross-version cycle is possible | untouched |
| `require_workflow`, `track_waits` reads | plain reads, no locks | n/a |

**Provider advisory locks are real and audited (N1R-8; v1.2's "none in these paths" claim is
withdrawn).** `_lock_linked` (`S/core/provider_ops.py:121`) takes blocking `pg_advisory_xact_lock`
per job, then per reservation, inside `begin`/`resubmit_allowed`; `begin` additionally takes the
linked reservation row FOR SHARE first (its verbatim V1 shape). The Comfy dispatch transaction
enters this chain at `_submit_bound_graph` (`S/rendering/comfy_jobs.py:600`), so the §8 admission
protocol composes with it as audited above; A3 §7 owns the full begin/rearm chain audit and its
separate tests (V1 shape preserved; V3 order #6 → #7 with eligibility first). The scheduler
singleton's `pg_try_advisory_lock` remains A6 (spec §9.1).

**Recorded separately, not A1 inversions (N1-17):**
1. Worker completion takes the job lock first (`S/core/jobs.py:648` FOR SHARE in `lease_guard`, `:677` `_lock` FOR UPDATE in `finish`), while amendments take track → job. A1 adds no such transaction; this row hands A3 the required order (track before job) and A3 ships the competing-transaction test.
2. `S/budget/billing.py:1296` locks a child account/reservation before shared settlement logic (parent later) — A2's inversion to fix (spec §5.3).
3. `_w03_episode_cadence` inserts episodes without the season row lock (`S/scheduling/service.py:219-238`) — a **pre-existing V1 serialization gap**, not itself a demonstrated inversion; V3 rows are filtered out (§7). Recorded for the V1 hardening backlog, owner: orchestrator.

**Competing-transaction tests A1 ships** (`X/integration/v3/test_lock_order.py`, two connections): concurrent distinct-key `decide` on one activation → one commits; the loser re-checks openness under the track lock and receives `GateNotReady` for the closed activation (N1R3-6 — the v1.3 `StaleRevision` expectation is withdrawn; §5 step 5 checks openness first), same-key replay returns the stored response, one `DECIDED` event; `decide` vs `advance_planning` → serialized by §6-#2, no lost bump; `open_gate` vs `open_gate` → one open activation; **`open_gate` vs lease claim/adoption/transfer on one scope** (N1-8/17) → the mutation either precedes (activation refused until verified resolution, N1R-9) or follows (admission refused), never both live; **season-gate `open_gate` vs episode lease admission in the same season** (N1R-8) → admission refused while the season gate is open, an unrelated season unaffected; **transfer followed by verified stop of the final holder** (N1R-9) → `open_gate` admitted — a transferred-away prior lease with no stop of its own no longer blocks.

## 10. Test plan (A-T1..A-T6, A-T16; N1-18)

All offline, real runtime/composition with fakes (existing conftest / ephemeral PostgreSQL), pytest `--basetemp` under the session scratchpad. Acceptance keeps `make check` and the V1 `make pilot` green (spec §10).

| ID | File (new unless noted) | Cases |
|---|---|---|
| A-T1 | `X/integration/v3/test_gate_rules.py`; `X/contract/contracts/test_v3_gate_actions.py`; existing `X/contract/contracts/test_states_routes_jobs.py:76` (green, unedited) | **complete V1 acceptance/rejection matrix** — every gate × action × version: v1 admits SEASON_CONCEPT APPROVE/REJECT and EPISODE_FINAL APPROVE/REVISE/REJECT, refuses the four new gates — **each new gate value tested on both V1 entity types with the original diagnostics under legacy failure precedence (N1R3-5): `approval_events_check` on a season entity, `approval_events_gate_type_check` on an episode entity**; v3 admits all six × three actions; EPISODE_FINAL rules identical both versions (binding **and** timecoded feedback); **retained 0007–0021 approval-guard cases on V1 rows**; deferred note trigger (season-gate commit without notes fails, with matching notes commits); Gate-2 V3 REVISE with feedback commits, without fails; **N1R-3/N1R3-1 uniqueness and partition: an extension decision reusing a season-used revision commits; a second decision on one activation and a same-scope/revision double-decision both conflict; the identity trigger refuses a V1 row carrying `activation_id`/`extension_id`, refuses a V3 row without `activation_id`, and refuses an activation whose workflow or season/episode/extension ancestry misses the approval**; `V3_GATE_ACTIONS` exact; `GATE_ACTIONS` byte-asserted unchanged; `ApprovalCommand` with a V3 gate → `ValueError`, no `KeyError`; **frozen V1 bytes (N1R-2)**: committed `schemas/v1/**` + `examples/v1/**` equal the accepted prerequisite baseline, the adapter's v1 `ApprovalCommand` output byte-identical (field `$ref` + two-value `$defs.GateType`), v3 examples **validated** by manifest discovery, and the new V1 rejection probes asserted outside the generated tree; `contracts-check` green (`Makefile:30,34`) |
| A-T2 (V3-AT-2) | `X/integration/v3/test_decision.py` | positive LOCK approve/revise/reject via the test handler; negatives: foreign owner (NotFound, no existence signal, **before workflow/state errors**), service credential, missing CSRF, wrong gate/scope/hash/revision/content_revision (each three-way mismatch distinct), stale page, superseded activation (GateNotReady; a fresh activation over unchanged content **is** decidable — reopening/binding per N1-5/N1-15); **activation identity (N1R-4): a wrong or already-decided `activation_id` → GateNotReady, and an old page naming a superseded activation never matches its replacement over unchanged content (no revision bump needed)**; callback failure rolls **everything** back — approval row, notes, `DECIDED` event, track revision, handler writes, **enqueued jobs and idempotency state**; concurrent decisions (one wins; the distinct-key loser receives `GateNotReady` for the closed activation, same-key replay returns the stored response — N1R3-6); idempotent replay returns the stored response; `NOT_AVAILABLE` preflight leaves **no idempotency record**; notes typed against binding units (target outside the binding → 422); **real test-handler injection through A1's normal-composition boundary refused** — `validate_for_production()` rejects an intrinsically-test handler and a `for_testing=True` registry both (N1R-12); **A6 reuses this boundary, so the test composes the registry exactly as the A1 factory does** |
| A-T3 | `X/integration/v3/test_handler_availability.py` | STORY_LOCK/CAST_LOCK/TEASER_FINAL/LAUNCH and V3 EPISODE_FINAL → `NOT_AVAILABLE` for all three actions through JSON **and** HTML; nothing recorded — no approval row, no activation change, no event, no job, **no idempotency write**; no fallback to V1 |
| A-T4 | `X/integration/v3/test_commands.py` | every §6 row incl. `advance_production`/`advance_release` unavailable edges; allowed sources advance, refused sources raise `InvalidTransition`/`GateNotReady`; replay identity, **incl. enqueue replay: the same semantic key re-used for a different V3 work scope → `IdempotencyConflict` (N1R-5), while V1 replay keeps the existing type/input-hash rule — a V1 semantic key replayed with a changed explicit season/episode argument still replays (N1R3-4)**; events (the §6 `Writes · jobs · events` column, per command); **every gate's Reject result** (§6 table — Reject feedback empty, explanation in `reason`, N1R-7); extension-scope advancement consumes `season_extensions.revision`; gate-edge advance proves the `DECIDED` event; A2/A3-gated commands → `NOT_AVAILABLE` with no writes |
| A-T5 | `X/integration/v3/test_discriminator.py` | every §7 entry point — v1.1 inventory **and the N1-14 boundary table** — refuses a V3 row with `WORKFLOW_MISMATCH` (services, direct callers, replayed jobs incl. `resolve_reconciliation`); **direct reads (N1R-10): `season_view`, `episode_review`, `episode_page` and direct progress calls raise `WORKFLOW_MISMATCH` after owner access — never a filtered-away NotFound — while enumeration listings still exclude V3 rows**; selectors/listings exclude V3 rows while shared owner-access helpers still serve V1; `workflow_version` immutable; episode re-parent refused; V1 rows still pass every guarded path |
| A-T6 | `X/integration/v3/test_track_waits.py` | concurrent waits show together (RETRY_WAIT quota + unresolved op); **every quota reason** maps (QUOTA_5H/PACE_WEEK/QUOTA_UNREADABLE/CONCURRENCY → QUOTA; BUDGET; provider trio → PROVIDER); **`defer_reason IS NULL` projects no wait** (retrying); one job resuming clears only its row; terminal FAILED blocks until a later SUCCEEDED replacement through validated `replaces_job_id` links — **a stale successful replacement does not clear a current failure**; chained replacements resolve (the recursive view, N1R-1); extension-fenced jobs use the extension fence; operation alerts dismiss by operation identity — **a stored job context on an operation dismissal is refused by the CHECK (canonical form, N1R-6)**; scope-level dismissal works; NEEDS_RECONCILIATION and in-flight/UNKNOWN ops block even for CANCELLED jobs; dismissal marks `dismissed` only; GPU per §8: `open_gate` with a live lease, or with an **unverified shutdown of a potentially created pod**, refused (N1R-9); **a transferred-away prior lease does not block once the final holder's stop is verified, and a durably proven no-create lease never blocks (N1R-9)**; lease claim during an open activation refused — **including an episode claim while a season-scope gate is open (N1R-8)**; **ACTIVE V3 heartbeat during a wait refused**; janitor releases with cause `human_wait` after verified shutdown |
| A-T16 | `X/integration/persistence/test_migrations.py` (extend; upgrade test at `:122` is the pattern) | 0028–0031 apply on a **populated, accepted-0027 V1 database**: seed V1 seasons/episodes/approvals/jobs at 0027 via `S/testing/seed.py`, migrate to head, **compare every existing row** and assert applied 0001–0027 checksums unchanged, `workflow_version='v1'` backfilled, **the preserved V1 diagnostic contract held after 0029 (N1R-11): every reproduced rule raises the original SQLSTATE, constraint name and primary message — the stable fields `translate_db_error` exposes (`S/persistence/db.py:77`) — with legacy failure precedence intact for the new gate values on both V1 entity types (N1R3-5), and V3-only rules raise the new `approval_events_v3_*` names; old raw messages are never asserted against different custom raises**, jobs work-scope columns **and `approval_events.activation_id`/`extension_id`** NULL on every pre-existing row, `EXPECTED_TABLES` superset holds; catalog tests green on all seven new tables (TRUNCATE + integer guards included — `test_schema_catalog.py:57,65`); fresh-create tail asserts `0028..0031` |


## 11. Open questions

| # | Question | Recommendation |
|---|----------|----------------|
| OQ-1 | Which package activates `create_extension`? AR-6 names only A2 (account-backed creation) and A3 (cancellation/fencing); extensions have a B/C planning lifecycle but no account machinery of their own. | Activate with **phase B** (the first phase driving extension planning); `NOT_AVAILABLE` until then. Ruled accepted (§12). |
| OQ-2 | How is a cancelled track represented? Master §2.2 has no CANCELLED planning/release state, but spec §3 says `track_waits` includes "the track's own cancelled state". | `cancelled_at` on `season_tracks`/`episode_tracks` (0030), surfaced as the `CANCELLED` wait; keeps the enums master-verbatim. Ruled accepted (§12). |
| OQ-3 | `defer_reason` vocabulary: spec §3 maps RETRY_WAIT causes to WAITING_QUOTA/PROVIDER/BUDGET, but A0 §5.2 does not enumerate the persisted reasons (one example is `GATEWAY_UNAVAILABLE`). | Resolved by ruling 2 (§12): A0's 0027 CHECK enforces the closed enum at the jobs write boundary; the view maps every value explicitly; NULL = transport retry, no wait row. |
| OQ-4 | Scope-level waits (CANCELLED) cannot be dismissed under a single-subject CHECK. | Resolved by the N1-11 subject representation (§2.4): scope alerts (both NULL), job alerts, operation alerts (operation identity only — job context derived for display, never stored; canonical per N1R-6); dismissal keys match the projection exactly, extension included. |
| OQ-5 | Does A1 ship any production (non-test) gate handler? Spec §2.7 implies none for unshipped phases, so **no V3 gate is decidable in production until B**. | Ship zero production handlers in A1; the LOCK test handler is test-world only. Ruled accepted (§12). |
| OQ-6 | V3 Gate 2 (`EPISODE_FINAL` on a V3 episode) reuses V1 binding semantics (package hash, manifest) — desired for phase A? | Keep identical SQL rules in both versions, feedback included (0029, N1-2); command availability is `NOT_AVAILABLE` until F. Ruled accepted (§12). |

## 12. Orchestrator rulings on the open questions (11 Nov, before the Codex critique)

| # | Ruling |
|---|--------|
| OQ-1 | **Accepted.** `create_extension` activates with **phase B**; it returns `NOT_AVAILABLE` until then. |
| OQ-2 | **Accepted.** `cancelled_at` on `season_tracks` and `episode_tracks`, surfaced as the `CANCELLED` wait. The master enums stay verbatim. |
| OQ-3 | **Accepted, with the enum owned by A0 and enforced at the write boundary (ruling 2, revised for N1-10).** A0-D adds a closed `DeferReason` enum to `contracts/enums.py`, and 0027 (not yet built) persists `jobs.defer_reason` under a CHECK for that closed vocabulary at the jobs table write boundary. `QUOTA_5H`, `PACE_WEEK`, `QUOTA_UNREADABLE`, `CONCURRENCY` → `WAITING_QUOTA`; `BUDGET` → `WAITING_BUDGET`; `GATEWAY_UNAVAILABLE`, `PROVIDER_RATE_LIMITED`, and the legacy `RATE_LIMITED` → `WAITING_PROVIDER`. The 0031 view maps every enum value explicitly and carries the raw cause; there is no fall-through and **no read-time CHECK on the view** (the v1.1 claim is withdrawn). **`defer_reason IS NULL` on a `RETRY_WAIT` job is an ordinary bounded transport retry: it projects no side-state wait; the UI shows it as retrying.** |
| OQ-4 | **Accepted.** 0031 is not applied yet, so its CHECK implements the scope-level dismissal (both subject columns NULL) directly — now as part of the N1-11 three-form subject representation. |
| OQ-5 | **Accepted.** A1 ships **zero** production gate handlers. |
| OQ-6 | **Accepted** for the SQL rules. Note that spec §2.7 still refuses a V3 Gate 2 with `NOT_AVAILABLE` at the command layer until phase F; identical SQL rules don't make it decidable. |

The master §10.0 ownership sentence is amended in v0.4.4 exactly as §3 proposed. The rulings stand;
N1-5/N1-7/N1-10 were re-ruled during this revision (immutable activations; validate–record–
transition–advance once; write-boundary enum enforcement) and are applied throughout.

## 13. Finding → resolution

### 13.0 Round 3 (codex-a1-r3.md, verdict REWORK — v1.4, all folded)

| Finding | Resolved in |
|---------|-------------|
| N1R3-1 (BLOCKING — approval identity can select either uniqueness partition) | §2.3 (`md_v3_approval_identity` resolves the workflow from the approval entity: V1 rows must carry NULL `activation_id`/`extension_id`, V3 rows a non-NULL `activation_id`, and the activation's workflow plus complete season/episode/extension ancestry validate against the approval before either index partition accepts the row — the nullable-column guess and the un-prohibited V1 activation identity are gone); §2.3 semantics paragraph; §5 step 7; §10 A-T1 |
| N1R3-2 (BLOCKING — Comfy queue submission precedes durable intent) | §8 dispatch row + §9 Comfy row (the guarded begin/rearm transaction commits before submission, matching the real `comfy_jobs.py:611-623`/`:630`/`:639` sequence and A3 §9 A-T18 boundary (1); dispatch reacquires the ordered scope/job/operation/lease/reservation guards and revalidates admission against the already-durable operation; the outcome persists separately; an ambiguous submission keeps its durable reconciliation identity) |
| N1R3-3 (lock audit contains incompatible sequences) | §8 opening (one canonical per-transaction order — scope → job → provider-operation serialization/rows → lease rows → budget locks; the "#6 → #7 → lease writes" listing withdrawn) + §8 pod row + §9 `ensure_pod` row (create-request, pod-binding and activation transactions enumerated separately, each naming its scope-lock reacquisition and the intervening provider call) |
| N1R3-4 (complete-scope replay comparison must be V3-only) | §2.4 (complete work-scope replay comparison applies to resolved V3 work only; V1 keeps the existing type/input-hash rule, `S/core/jobs.py:429-434`); §10 A-T4 |
| N1R3-5 (V1 diagnostic identity changes on new gate values) | §2.2 (V1 scope compatibility evaluated with the original `gate_type='SEASON_CONCEPT'` equivalence, first, preserving legacy failure precedence; the expanded season-gate set is V3-only under `approval_events_v3_scope`) + the precedence paragraph; §10 A-T1/A-T16 |
| N1R3-6 (concurrent-decision test expects the wrong refusal) | §5 step 5 (openness re-check under the track lock first; partial indexes as commit-time backstop) + §9 competing tests + §10 A-T2 (distinct-key loser receives `GateNotReady` for the closed activation; same-key replay returns the stored response) |

### 13.1 Round 2 (codex-a1-note-recritique.md, verdict REWORK — v1.3, all folded)

| Finding | Resolved in |
|---------|-------------|
| N1R-1 (BLOCKING — view cannot compile: no `WITH RECURSIVE`; episode-cancellation branch 8 columns) | §2.4 (`WITH RECURSIVE v3_jobs`; every `wait_rows` branch nine columns — the episode branch begins `SELECT e.season_id, et.episode_id, NULL::uuid, t.track, …`); §10 A-T6 (chained replacements) |
| N1R-2 (BLOCKING — schema pin does not preserve bytes) | §4 (explicit V1 schema adapter preserving the two-value `$defs.GateType` and field `$ref` exactly; runtime membership guard retained; V3 **validation** manifest discovery; V1 rejection probes outside frozen generated examples); §10 A-T1 |
| N1R-3 (BLOCKING — extension approvals collide with prior season approvals) | §2.3 (`approval_events.activation_id`/`extension_id` + scope-linkage trigger + partial legacy index, full-scope/revision and per-activation V3 uniqueness, allocated in 0030); §2.2 (index-restructure note); §5 steps 5/7; §10 A-T1/A-T16 |
| N1R-4 (commands cannot identify a superseded activation) | §4 (`V3DecisionCommand.activation_id`); §5 step 5 + resolver (exact activation, open, complete scope match before the three-way comparison); §6 (`decide` names the activation; hashing and displayed forms carry it); §10 A-T2 |
| N1R-5 (work-scope identity mutable and incompletely plumbed) | §2.4 (V3-conditional `season_id`/`episode_id` immutability trigger; `Job`/`_job` gain all work-scope fields; replay compares the complete work scope; the resolved season's `workflow_version` is the discriminator, not `track` alone); §10 A-T4 |
| N1R-6 (optional operation job context breaks dismissal matching) | §2.4 (canonical operation dismissals store NULL `subject_job_id` — CHECK, unique identity and writer enforce it; display context derived through `provider_operations`); §10 A-T6 |
| N1R-7 (Gate-2 Reject feedback contradiction) | §4 validators + §5 step 7 + §6 (Reject: empty feedback, explanation in `reason`, as V1 `S/review/service.py:1364`; only Revise requires feedback/notes; Reject state consequences preserved); §10 A-T4 |
| N1R-8 (GPU transaction ownership and lock audit incomplete) | §8 (owning transaction, lock mode and ancestor-before-leaf order at every final admission mutation — reservation/lease insertion, begin, dispatch at `comfy_jobs.py:600`, transfer; each committed mutation re-takes the scope lock; season-gate-vs-episode-admission coverage); §9 (corrected GPU rows; provider advisory locks at `provider_ops.py:121` audited, "none" claim withdrawn; two new races); §10 A-T6 |
| N1R-9 (shutdown predicate permanently blocks valid waits) | §8 (zero live exposure + verified resolution of any potentially created pod; transfer chains followed to the final holder — `leases.py:1376`; transferred history and durably proven no-create distinguished from unverified shutdown); §9/§10 A-T6 (transfer → verified stop → gate opens) |
| N1R-10 (point reads assigned listing filters) | §7 (filters only for enumeration; `require_workflow(expected='v1')` refusal at every direct read/decidability boundary after owner access, before projection — `WORKFLOW_MISMATCH`, never NotFound); §10 A-T5 |
| N1R-11 (upgrade test demands diagnostics the DDL changes) | §2.2 (preserved V1 diagnostic contract: original SQLSTATE, constraint name and primary message emitted via `USING CONSTRAINT`); §10 A-T16 (stable fields compared; old messages never asserted against custom raises) |
| N1R-12 (A1's production-injection test depends on an A6 boundary) | §5 (`GateHandlerRegistry.validate_for_production()` — A1's normal-composition boundary rejecting test-enabled registries and intrinsically-test handlers; A6 must reuse it); §10 A-T2 (injection exercised through that boundary) |

The round-2 build-readiness note also asked for the command table's per-command writes/jobs/events: §6's `Writes · jobs · events` column makes them explicit.

### 13.2 Round 1 (codex-a1-note-critique.md, all accepted — v1.2)

| Finding | Resolved in |
|---------|-------------|
| N1-1 (SQL will not compile) | §2.2 (`p_entity_type text, p_entity_id uuid`); §2.4 (`job_id` used consistently in every `v3_jobs` consumer; operation branch keyed on `po.id`); §1/§2.3 (deferred notes trigger installed in 0030) |
| N1-2 (Gate 2 Revise loses timecoded feedback) | §2.2 (feedback branches by gate; EPISODE_FINAL identical both versions); §4 (`V3DecisionCommand.feedback`, validators, examples); §10 A-T1/A-T2 |
| N1-3 (V1 byte-equality cannot hold) | §4 (schema pin + typed membership guard + explicit v3 generation + frozen-baseline test); §10 A-T1 |
| N1-4 (`alert_dismissals` catalog guards) | §2.4 (TRUNCATE + integer guards via the 0031 DO loop; catalog registration covers all seven new tables) |
| N1-5 (supersession vs CHECK; mutability) | §2.3 (immutable `gate_activations` + `gate_activation_events`; derived openness; `UNIQUE(activation_id)`; supersession needs no approval; ruling 1) |
| N1-6 (resolver binding incomplete) | §5 steps 3–5 (owner access first; ancestry proof; three-way comparison under the locks; changed authority ⇒ fresh activation) |
| N1-7 (revision advancement conflict) | §5 revision plan + steps 7–9 (validate at r, record at r, transitions in the decision context, advance once); §6 (`DECIDED`-event proof) |
| N1-8 (GPU admission race; heartbeat claim) | §8 (common scope-lock protocol across activation/claim/adoption/transfer/pod/reactivation; ACTIVE V3 heartbeat refused; verified resolution before a wait — predicate reworked by N1R-9, §8; season/extension work ownership); §9 (GPU transactions audited); §10 A-T6 |
| N1-9 (work-scope plumbing incomplete) | §2.4 (typed `enqueue` changes with ancestry/scope validation; extension fence; validated replacement links incl. authority; `extension_id` reader argument) |
| N1-10 (quota mapping unimplemented; no view CHECK) | §2.4 (every enum value mapped; NULL = transport retry, excluded); §3 (0027 CHECK requirement, A0-D); §12 OQ-3 (read-time CHECK claim withdrawn); §10 A-T6 |
| N1-11 (operation dismissals impossible) | §2.4 (three-form subject CHECK; operation identity with **no stored job context** — canonical per N1R-6; extension scope in row, unique index and join) |
| N1-12 (`NOT_AVAILABLE` after idempotency insert) | §5 step 1 (transaction-owned preflight seam after replay lookup, before the INSERT); §10 A-T2/A-T3 |
| N1-13 (test-handler flag reliance) | §5 registry (intrinsic provenance; `for_testing` registry; production rejects both; injection tested at the production boundary) |
| N1-14 (legacy inventory incomplete) | §7 boundary table (all nine missing boundaries) + closing rules; §10 A-T5 |
| N1-15 (command table incomplete) | §6 (`advance_production`/`advance_release` rows; every gate's Reject; extension revision owner; activation/decision identity) |
| N1-16 (extension eligibility contradicts master) | §2.3 + §6 `create_extension` (master §4.3 `RELEASING`/`COMPLETE` + calendar choice; extension identity through commands, activations, decisions, bindings, waits, dismissals) |
| N1-17 (lock audit overclaims) | §9 (GPU/advisory/transfer transactions audited; insert-order justified; worker fencing → A3; settlement → A2; cadence recorded as a V1 gap; new two-connection races) |
| N1-18 (test plan gaps) | §10 (all listed cases: V1 matrix, retained guards, frozen bytes, no-`KeyError`, supersession/reopening, extension + stale-replacement isolation, operation dismissals, every quota reason, unavailable-command write tracing, real injection, activation-vs-claim/adoption/transfer, rollback incl. jobs + idempotency, populated accepted-0027 upgrade with checksums, `make check` + V1 `make pilot`) |
