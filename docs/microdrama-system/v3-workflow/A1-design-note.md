# A1 design note: discriminator, gates, decision transaction, tracks

**Version 1.1, 11 Nov 2026. Author: GLM (design note only).** Requirements: [phase-A-spec.md](phase-A-spec.md) v0.3 §0–§3, §6, §10, §11 (AC-1..9, AC-22/23, AR-3/4/6 binding); master [SPEC-v3.md](SPEC-v3.md) v0.4.2 §2.1–§2.2, §10.0; A0 v0.4 §5.2/§5.5/§5.6. Facts verified on `feat/microdrama-m0-m4` @ `0851374` (migration tail 0025; 0026 = `.scratch/t031-gate-h2/` T031; 0027 = A0). `S/` = `src/microdrama/`, `M/` = `migrations/`, `X/` = `tests/`, relative to `microdrama/`.

---

## 1. Migration allocation

Prerequisite pin (spec §10): the T031 merge (0026) and A0 (0027) land first. **Applied migration bytes are never edited** — the migrator hashes file bytes and rejects changed checksums (`S/persistence/migrate.py:45`, `:51`). A1 allocates, one purpose each:

| # | File | Purpose |
|---|------|---------|
| 0028 | `0028_v3_workflow_version.sql` | Discriminator: `seasons.workflow_version`, immutability guard, episode re-parent guard |
| 0029 | `0029_v3_gate_rules.sql` | Version-aware approval constraint triggers replacing the 0002 gate/entity/action/feedback CHECKs; admits the four new gate values |
| 0030 | `0030_v3_tracks_and_gates.sql` | `season_tracks`, `episode_tracks`, `season_extensions`, `gate_activations`, `season_revision_notes` |
| 0031 | `0031_v3_job_workscope.sql` | Jobs work-scope columns, `alert_dismissals`, the `track_waits` view |

Ordering: 0029 resolves the version from 0028's column; 0031's view joins 0030's tables and A0's `jobs.defer_reason` (0027).

## 2. Guarded DDL

Guard pattern per `M/0019…sql:28-38` and `M/0026…sql:89-99` (scratch): `md_immutable_columns` for identity columns, `md_forbid_mutation` for DELETE/TRUNCATE (and full append-only), `md_forbid_non_integer_numbers` on INSERT OR UPDATE (`M/0009…sql:94`; its 0009 DO-loop only covered tables then existing — new tables attach it explicitly). The catalog tests (`X/integration/persistence/test_schema_catalog.py:22-37`, `relkind='r'` only) then cover every new table automatically; views sit outside that net.

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

Dropped constraints (PostgreSQL auto-names are deterministic from the applied 0002 bytes; the DO block fails loudly if any is missing):

| Constraint (0002 line) | Old rule |
|------------------------|----------|
| `approval_events_gate_type_check` (:184) | `gate_type IN ('SEASON_CONCEPT','EPISODE_FINAL')` |
| `approval_events_check` (:200) | `(gate_type='SEASON_CONCEPT') = (entity_type='season')` |
| `approval_events_check1` (:201) | `gate_type <> 'SEASON_CONCEPT' OR action IN ('APPROVE','REJECT')` |
| `approval_events_check2` (:202-204) | EPISODE_FINAL+APPROVE ⇒ media nonempty AND policy/scope hashes present |
| `approval_events_check3` (:205) | `action <> 'REVISE' OR jsonb_array_length(feedback) > 0` |

The `action`/`entity_type` column CHECKs (:185-186) stay. `approval_events_one_per_revision` (`M/0002…sql:208`), `md_approval_requires_human_session` (`M/0007…sql:5`) and every 0007–0021 approval guard stay **unchanged**: V3 seasons never set `seasons.approval_event_id`, so `md_season_approval_binding` (`M/0007…sql:31`) never fires for them; the human-session trigger applies to V3 rows unchanged (spec §2.8).

```sql
DO $$ BEGIN
  ALTER TABLE approval_events DROP CONSTRAINT approval_events_gate_type_check;
  ALTER TABLE approval_events DROP CONSTRAINT approval_events_check;
  ALTER TABLE approval_events DROP CONSTRAINT approval_events_check1;
  ALTER TABLE approval_events DROP CONSTRAINT approval_events_check2;
  ALTER TABLE approval_events DROP CONSTRAINT approval_events_check3;
END $$;

CREATE FUNCTION md_season_version_of(p_entity text, p_entity uuid) RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT CASE WHEN p_entity = 'season'
    THEN (SELECT workflow_version FROM seasons WHERE id = p_entity)
    ELSE (SELECT s.workflow_version FROM episodes e JOIN seasons s ON s.id = e.season_id
           WHERE e.id = p_entity) END $$;

CREATE FUNCTION md_approval_gate_rules() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v text; season_gate boolean; bound boolean;
BEGIN
  v := md_season_version_of(NEW.entity_type, NEW.entity_id);
  season_gate := NEW.gate_type IN ('SEASON_CONCEPT','STORY_LOCK','CAST_LOCK','TEASER_FINAL','LAUNCH');
  IF season_gate <> (NEW.entity_type = 'season') THEN
    RAISE EXCEPTION 'gate/entity mismatch' USING ERRCODE='check_violation'; END IF;
  bound := NEW.gate_type = 'EPISODE_FINAL' AND NEW.action = 'APPROVE'
           AND NOT (jsonb_array_length(NEW.media_hashes) > 0
                    AND NEW.management_policy_hash IS NOT NULL AND NEW.release_scope_hash IS NOT NULL);
  IF v = 'v1' OR v IS NULL THEN
    -- V1 rules reproduced EXACTLY (0002:184,200,201,202-204,205)
    IF NEW.gate_type NOT IN ('SEASON_CONCEPT','EPISODE_FINAL') THEN
      RAISE EXCEPTION 'gate_type not admitted for v1' USING ERRCODE='check_violation'; END IF;
    IF NEW.gate_type = 'SEASON_CONCEPT' AND NEW.action NOT IN ('APPROVE','REJECT') THEN
      RAISE EXCEPTION 'season concept allows APPROVE/REJECT only' USING ERRCODE='check_violation'; END IF;
    IF bound THEN
      RAISE EXCEPTION 'episode approve must bind media/policy/scope' USING ERRCODE='check_violation'; END IF;
    IF NEW.action = 'REVISE' AND jsonb_array_length(NEW.feedback) = 0 THEN
      RAISE EXCEPTION 'revise requires feedback' USING ERRCODE='check_violation'; END IF;
  ELSIF v = 'v3' THEN
    IF NEW.gate_type NOT IN ('SEASON_CONCEPT','STORY_LOCK','CAST_LOCK','TEASER_FINAL','LAUNCH',
                             'EPISODE_FINAL') THEN
      RAISE EXCEPTION 'gate_type not admitted for v3' USING ERRCODE='check_violation'; END IF;
    -- Approve/Revise/Reject on every V3 gate (master §2.1), incl. CAST_LOCK/LAUNCH Reject (AR-3).
    IF NEW.action = 'REVISE' AND jsonb_array_length(NEW.feedback) > 0 THEN
      RAISE EXCEPTION 'v3 revise uses season_revision_notes, not feedback' USING ERRCODE='check_violation';
    END IF;
    IF NEW.action <> 'REVISE' AND jsonb_array_length(NEW.feedback) > 0 THEN
      RAISE EXCEPTION 'feedback only with revise' USING ERRCODE='check_violation'; END IF;
    IF bound THEN
      RAISE EXCEPTION 'episode approve must bind media/policy/scope' USING ERRCODE='check_violation'; END IF;
  ELSE RAISE EXCEPTION 'unknown workflow version' USING ERRCODE='check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER approval_events_gate_rules BEFORE INSERT ON approval_events
  FOR EACH ROW EXECUTE FUNCTION md_approval_gate_rules();

-- Deferred (spec §2.3): a V3 season-gate REVISE carries >=1 season_revision_notes row in the
-- same committed transaction (notes are inserted after the approval row).
CREATE FUNCTION md_v3_revise_notes() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.action = 'REVISE' AND NEW.entity_type = 'season'
     AND md_season_version_of('season', NEW.entity_id) = 'v3'
     AND NOT EXISTS (SELECT 1 FROM season_revision_notes n WHERE n.approval_event_id = NEW.id) THEN
    RAISE EXCEPTION 'v3 season revise requires revision notes' USING ERRCODE='check_violation';
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER approval_events_v3_notes AFTER INSERT ON approval_events
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION md_v3_revise_notes();
```

`approval_events` stays append-only (`M/0002…sql:210`), so the BEFORE INSERT trigger replaces the dropped CHECKs on the only write path. `EPISODE_FINAL` keeps identical rules in both versions — Gate 2 binding is episode-scoped and unchanged (AC-1); V3's difference there is handler availability (§5), not SQL.

### 2.3 Migration 0030 — tracks, activations, notes

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

CREATE TABLE gate_activations (
  id                        uuid PRIMARY KEY,
  schema_version            text NOT NULL DEFAULT '1.0',
  gate_type                 text NOT NULL CHECK (gate_type IN ('SEASON_CONCEPT','STORY_LOCK','CAST_LOCK',
                                   'TEASER_FINAL','LAUNCH','EPISODE_FINAL')),
  season_id                 uuid NOT NULL REFERENCES seasons(id),
  episode_id                uuid REFERENCES episodes(id),
  binding_sha256            text NOT NULL CHECK (binding_sha256 ~ '^[0-9a-f]{64}$'),
  content_revision          integer NOT NULL CHECK (content_revision >= 0),
  decision_revision         integer NOT NULL CHECK (decision_revision >= 0),
  opened_at                 timestamptz NOT NULL DEFAULT now(),
  opened_by_job             uuid REFERENCES jobs(id),
  closed_at                 timestamptz,
  closed_by_approval_event  uuid REFERENCES approval_events(id),
  superseded_by             uuid REFERENCES gate_activations(id),
  created_at                timestamptz NOT NULL DEFAULT now(),
  CHECK ((gate_type = 'EPISODE_FINAL') = (episode_id IS NOT NULL)),
  CHECK (closed_at IS NULL OR closed_by_approval_event IS NOT NULL)
);
CREATE UNIQUE INDEX gate_activations_one_open ON gate_activations
  (gate_type, season_id, COALESCE(episode_id, '00000000-0000-0000-0000-000000000000'::uuid))
  WHERE closed_at IS NULL AND superseded_by IS NULL;
CREATE TRIGGER gate_activations_identity_immutable BEFORE UPDATE ON gate_activations
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('id','gate_type','season_id','episode_id',
    'binding_sha256','content_revision','decision_revision','opened_at','opened_by_job','created_at');
CREATE TRIGGER gate_activations_no_delete BEFORE DELETE ON gate_activations
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
```

"Open" = `closed_at IS NULL AND superseded_by IS NULL`; one open activation per (gate, scope) is index-enforced. A decision closes its activation and bumps the track revision, so the next decision needs a new activation (spec §2.2) and `approval_events_one_per_revision` arbitrates concurrent decisions.

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
```

Notes are written only by the V3 decision command, never into `feedback_events` (`S/core/approvals.py:119` keeps its episode-only writer). All five 0030 tables get the standard no-delete/no-truncate/integer triggers via the 0026-style DO loop over `ARRAY['season_tracks','episode_tracks','season_extensions','gate_activations','season_revision_notes']` (append-only tables already refuse UPDATE+DELETE; mutable ones get `_no_delete` only — `M/0026…sql:85-99`).

### 2.4 Migration 0031 — job work scope, dismissals, `track_waits`

```sql
ALTER TABLE jobs
  ADD COLUMN track           text CHECK (track IN ('planning','production','release')),
  ADD COLUMN extension_id    uuid REFERENCES season_extensions(id),
  ADD COLUMN logical_work_id text,
  ADD COLUMN replaces_job_id uuid REFERENCES jobs(id);
CREATE TRIGGER jobs_workscope_immutable BEFORE UPDATE ON jobs
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('track','extension_id','logical_work_id',
                                                     'replaces_job_id');
CREATE INDEX jobs_workscope_idx ON jobs (season_id, track) WHERE track IS NOT NULL;
CREATE INDEX jobs_logical_work_idx ON jobs (logical_work_id) WHERE logical_work_id IS NOT NULL;
```

`track` is NULL for every V1 job (and `require_workflow` refuses V3 rows on legacy paths, so no V1 writer sets it). `replaces_job_id` + `logical_work_id` are the replacement identity separate from the UNIQUE `jobs.semantic_key` (`M/0001…sql:78`, AR-4). `jobs_identity_immutable` (`M/0001…sql:104`) is untouched.

```sql
CREATE TABLE alert_dismissals (
  id                   uuid PRIMARY KEY,
  schema_version       text NOT NULL DEFAULT '1.0',
  season_id            uuid NOT NULL REFERENCES seasons(id),
  episode_id           uuid REFERENCES episodes(id),
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
  CHECK ((subject_job_id IS NULL) <> (subject_operation_id IS NULL))
);
CREATE UNIQUE INDEX alert_dismissals_one_per_subject ON alert_dismissals
  (season_id, COALESCE(episode_id,'00000000-0000-0000-0000-000000000000'::uuid), track, alert_kind,
   COALESCE(subject_job_id,'00000000-0000-0000-0000-000000000000'::uuid),
   COALESCE(subject_operation_id,'00000000-0000-0000-0000-000000000000'::uuid));
CREATE TRIGGER alert_dismissals_append_only BEFORE UPDATE OR DELETE ON alert_dismissals
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
```

`BLOCKED_OVERRUN` rows are produced by A2 (spec §5.3); the `alert_kind` CHECK admits the value now so A2 needs no migration edit. Scope-level dismissals (both subject columns NULL) are currently refused by the CHECK — see OQ-4.

`track_waits` view (full SQL; spec §3 + AR-4):

```sql
CREATE VIEW track_waits AS
WITH v3_jobs AS (
  SELECT j.id AS job_id, j.season_id, j.episode_id, j.extension_id, j.track, j.status,
         j.defer_reason, j.run_after, j.created_at, j.logical_work_id, j.input,
         st.content_revision AS season_fence, et.content_revision AS episode_fence
    FROM jobs j
    JOIN seasons s ON s.id = j.season_id AND s.workflow_version = 'v3'
    LEFT JOIN season_tracks st ON st.season_id = j.season_id
    LEFT JOIN episode_tracks et ON et.episode_id = j.episode_id
   WHERE j.track IS NOT NULL
),
stale AS (   -- a job pinned to a superseded content revision is not current authority
  SELECT job_id FROM v3_jobs
   WHERE (input->>'expected_content_revision') IS NOT NULL
     AND (input->>'expected_content_revision')::bigint < COALESCE(episode_fence, season_fence)
),
wait_rows AS (
  SELECT season_id, episode_id, extension_id, track,
         CASE j.defer_reason WHEN 'BUDGET' THEN 'WAITING_BUDGET' WHEN 'QUOTA' THEN 'WAITING_QUOTA'
                             ELSE 'WAITING_PROVIDER' END AS wait_kind,
         j.run_after AS effective_at, j.id AS job_id, NULL::uuid AS operation_id, j.defer_reason AS cause
    FROM v3_jobs j WHERE j.status = 'RETRY_WAIT' AND j.id NOT IN (SELECT job_id FROM stale)
  UNION ALL
  SELECT season_id, episode_id, extension_id, track, 'BLOCKED_RECONCILE', NULL, j.id, NULL,
         'needs_reconciliation'
    FROM v3_jobs j WHERE j.status = 'NEEDS_RECONCILIATION' AND j.id NOT IN (SELECT job_id FROM stale)
  UNION ALL
  SELECT j.season_id, j.episode_id, j.extension_id, j.track, 'BLOCKED_RECONCILE', NULL, j.id, po.id,
         'operation_unresolved'
    FROM provider_operations po JOIN jobs j ON j.id = po.job_id
    JOIN seasons s ON s.id = j.season_id AND s.workflow_version = 'v3'
   WHERE po.state IN ('PENDING_SUBMIT','SUBMITTED','RUNNING','UNKNOWN') AND j.track IS NOT NULL
  UNION ALL
  SELECT f.season_id, f.episode_id, f.extension_id, f.track, 'BLOCKED_FAILED', NULL, f.id, NULL,
         'failed_terminal'
    FROM v3_jobs f
   WHERE f.status = 'FAILED' AND f.logical_work_id IS NOT NULL
     AND f.id NOT IN (SELECT job_id FROM stale)
     AND NOT EXISTS (SELECT 1 FROM v3_jobs r WHERE r.logical_work_id = f.logical_work_id
                      AND r.status = 'SUCCEEDED' AND (r.created_at, r.id) > (f.created_at, f.id))
  UNION ALL
  SELECT st.season_id, NULL::uuid, NULL::uuid, 'planning', 'CANCELLED', st.cancelled_at, NULL, NULL,
         'season_cancelled'
    FROM season_tracks st WHERE st.cancelled_at IS NOT NULL
  UNION ALL
  SELECT e.season_id, et.episode_id, NULL::uuid, 'production', 'CANCELLED', et.cancelled_at, NULL, NULL,
         'episode_cancelled'
    FROM episode_tracks et JOIN episodes e ON e.id = et.episode_id WHERE et.cancelled_at IS NOT NULL
  UNION ALL
  SELECT e.season_id, et.episode_id, NULL::uuid, 'release', 'CANCELLED', et.cancelled_at, NULL, NULL,
         'episode_cancelled'
    FROM episode_tracks et JOIN episodes e ON e.id = et.episode_id WHERE et.cancelled_at IS NOT NULL
)
SELECT w.season_id, w.episode_id, w.extension_id, w.track, w.wait_kind, w.effective_at, w.job_id,
       w.operation_id, w.cause, (d.id IS NOT NULL) AS dismissed
  FROM wait_rows w LEFT JOIN alert_dismissals d
    ON d.season_id = w.season_id AND d.track = w.track AND d.alert_kind = w.wait_kind
   AND d.episode_id IS NOT DISTINCT FROM w.episode_id
   AND d.subject_job_id IS NOT DISTINCT FROM w.job_id
   AND d.subject_operation_id IS NOT DISTINCT FROM w.operation_id;
```

Semantics: several waits show together (one row each); one job resuming clears only its own row; unresolved operations block **without** a job-status filter (cancelled/stale jobs keep their exposure until reconciliation settles it — `S/core/jobs.py:864-871` leaves ops untouched on cancel); a dismissal only marks `dismissed=true` (the UI hides it; nothing is completed or approved). The Python reader is `S/core/v3_tracks.py: track_waits(tx, *, season_id, track, episode_id=None) -> list[TrackWait]`.

### 2.5 Catalog registration

- `X/integration/persistence/test_migrations.py:32` `EXPECTED_TABLES` += `season_tracks`, `episode_tracks`, `season_extensions`, `gate_activations`, `season_revision_notes`, `alert_dismissals`.
- Tail assertions (`:145`, `:214`, `:270` pattern) extend to `0028..0031` (A0 first extends them to `0026..0027`; A1 rebases on that).
- `X/integration/persistence/test_schema_catalog.py` needs no edit: it inspects the live catalog (`relkind='r'`), so new tables are covered when 0030/0031 land; the `track_waits` view is outside it (views are read-only and DELETE on a view fails by construction).

## 3. Ownership conflict to flag (master §10.0)

Master §10.0: "Phase A0 owns any schema additions to the jobs and provider-operation records." A1 also adds jobs columns. Precise split so nothing is added twice:

| Owner | Migration | Jobs columns | Provider-operation changes |
|-------|-----------|--------------|----------------------------|
| **A0** (v0.4 §5.2, §5.5, §5.6) | 0027 | `defer_reason` (persisted), the claim's `consumed_attempt` record | `REFUSED_PRELAUNCH` + kind-limited transitions (`ALLOWED_MOVES`, the state CHECK), `llm.subscription` in the 0016 per-kind CHECK; `llm_invocations`, `llm_invocation_attempts`, `quota_observations` |
| **A1** | 0031 | `track`, `extension_id`, `logical_work_id`, `replaces_job_id` | none |

No overlap. **Flag for the orchestrator:** amend master §10.0 to "A0 owns jobs/provider-operation schema for the LLM plumbing; phase A packages own their work-scope columns as allocated in the A1 note (AC-23)."

## 4. Contracts

- `S/contracts/enums.py:159` `GateType` += `STORY_LOCK`, `CAST_LOCK`, `TEASER_FINAL`, `LAUNCH`. `ApprovalAction` (:164) is unchanged — all three actions already exist.
- `S/contracts/states.py:122` `GATE_ACTIONS` is **unchanged** (V1). Beside it:

```python
V3_GATE_ACTIONS: Mapping[GateType, frozenset[ApprovalAction]] = {
    gate: frozenset({ApprovalAction.APPROVE, ApprovalAction.REVISE, ApprovalAction.REJECT})
    for gate in GateType  # master §2.1: Approve/Revise/Reject on every V3 gate
}
```

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
    expected_revision: Revision             # season_tracks.revision / episode_tracks.revision
    expected_content_revision: Revision     # the track's content_revision (fence display)
    binding_sha256: Sha256Hex
    idempotency_key: IdempotencyKey
    notes: list[SeasonRevisionNote] = Field(default_factory=list)
    reason: str | None = Field(default=None, max_length=2000)
    # validators: action in V3_GATE_ACTIONS[gate]; REVISE <=> notes nonempty;
    # (gate is EPISODE_FINAL) == (episode_id is not None); no timecoded feedback field exists.
```

- Targets are validated at decision time against the **activation's binding units**: the resolver (§5) recomputes the binding to compare hashes, and every target `{kind,id}` must be one of the binding's units. No `binding_units` column is persisted — the recomputation is authoritative (and doubles as the stale-page check).
- **Generated contracts:** `make contracts` regenerates, `contracts-check` fails on drift (`microdrama/Makefile:24,27`). V1 files stay byte-identical; additions are the new enum values (additive) and the new V3 schemas/examples. The negative example `gate1_revise` (`S/contracts/examples.py:2180-2193`, "Gate 1 has no Revise") **stays exactly as written**: it asserts the V1 `ApprovalCommand`, which keeps validating against the unchanged `GATE_ACTIONS` (`S/contracts/season.py:288-291`) and keeps refusing Gate-1 Revise. V3 LOCK Revise travels on `V3DecisionCommand`, a different model — V1 behaviour untouched (AC-1). New negative examples: `v3_revise_without_notes`, `v3_gate2_season_scope`, `v3_episode_gate_without_episode`.
- `X/contract/contracts/test_states_routes_jobs.py:74` `test_gate_actions` is untouched; a sibling test asserts `V3_GATE_ACTIONS` exactly (§10).

## 5. The decision transaction (spec §2.6; AC-3, AC-4)

New module `S/core/v3_gates.py`. **V1 keeps everything unchanged**: `S/core/approvals.py` is not edited — its entity lock and revision comparison (`S/core/approvals.py:64-65`) remain the V1 binding resolver; `decide_season`/`decide_episode` (`S/review/service.py:381`, `:1078`) and `_check_binding` (:1092) keep their exact behaviour, now additionally refusing V3 entities via `require_workflow` (§7).

**Binding resolver** (V3 side):

```python
@dataclass(frozen=True)
class GateBinding:
    gate: GateType; season_id: UUID; episode_id: UUID | None
    activation_id: UUID
    binding_sha256: str                      # recomputed from current content
    binding_units: tuple[RevisionNoteTarget, ...]
    content_revision: int                    # authoritative track fence
    decision_revision: int                   # authoritative track command revision

def resolve_gate_binding(tx: Tx, *, gate: GateType, season_id: UUID,
                         episode_id: UUID | None, handler: "GateHandler") -> GateBinding:
    # Caller already holds season_tracks (episode_tracks) FOR UPDATE (§6 order).
    # 1. Active activation: closed_at IS NULL AND superseded_by IS NULL; none -> GateNotReady.
    # 2. handler.binding(tx, ...) recomputes the binding hash + units from current content.
    # 3. Returns the binding with the track's authoritative revisions.
```

**Handler registry** (AC-4) — every method takes the caller's `tx`:

```python
class GateHandler(Protocol):
    gate: GateType
    def binding(self, tx, *, season_id, episode_id) -> GateBinding: ...
    def conditions(self, tx, binding) -> list[str]: ...   # blockers; empty = enabled
    def on_decision(self, tx, *, principal, command, binding, approval_event_id, now,
                    correlation_id) -> None: ...

class GateHandlerRegistry:
    def __init__(self, *, allow_test_handlers: bool = False) -> None: ...
    def register(self, handler: GateHandler, *, test_only: bool = False) -> None: ...
    def get(self, gate: GateType) -> GateHandler | None: ...
```

Registration rules: `register(..., test_only=True)` raises unless the registry was constructed with `allow_test_handlers=True`; `build_production_world` (A6) constructs it with `False`, so a test handler cannot enter production; `PipelineWorld` (test/offline, `S/pipeline/world.py:124`) constructs with `True` and gains an explicit `enable_test_gate_handlers()` seam. A missing V3 handler returns `NOT_AVAILABLE` **before any recording or callback** and **never falls back to V1**. A1 ships exactly one test-world LOCK handler (minimal binding over the proposal scope hash) for A-T2/A-T4; phase B+ replaces it with real handlers.

**Step order** (one caller-owned transaction; locks in §6 order):

1. `IdempotencyService.execute` opens the transaction and locks the idempotency row first — a replay returns the stored response before fresh validation (`S/core/idempotency.py:83-89`).
2. Lock `season_tracks` FOR UPDATE (episode gates: then `episode_tracks`).
3. `require_workflow(tx, season_id, expected='v3')`; resolve owner scope (`S/review/scope.py:64-77`, same NotFound-as-missing rule as `S/review/service.py:401-405`).
4. `registry.get(gate)` — missing → `NOT_AVAILABLE`, nothing recorded, no callback.
5. `resolve_gate_binding` (active activation, recomputed hash, authoritative revisions).
6. Compare `binding_sha256` / `expected_revision` / `expected_content_revision` → mismatch is `StaleRevision`; a concurrent second decision hits `approval_events_one_per_revision` (`M/0002…sql:208`), reported like `S/core/approvals.py:108-116`.
7. `handler.conditions(tx, binding)` → nonempty is `GateNotReady`.
8. Record: `record_v3_decision(tx, ...)` (new, `S/core/v3_approvals.py`) inserts the `approval_events` row (empty `feedback`; the existing SQL trigger judges the human session), the `season_revision_notes` rows (targets validated against `binding_units`; ≥1 note on Revise — the deferred trigger backstops), appends `approval.recorded`, **closes the activation** and bumps the track `revision`.
9. `handler.on_decision(tx, ...)` — its writes, job enqueues and events join this transaction.
10. The idempotent response is stored. Any failure at any step rolls everything back.

Human-session, CSRF and service-credential rules are the existing ones: `require_human_owner`, the route-level refusal of non-human principals (`S/review/api.py:201` `_refuse_non_human_route`), CSRF on unsafe methods. **Routes:** JSON `POST /v3/seasons/{season_id}/gates/{gate}/decision` plus a minimal HTML form under `/ui/v3` reusing the session/CSRF machinery — both needed for A-T3's JSON+HTML coverage; the full UI is A5.

## 6. The command table (spec §3; AC-6, AR-3, AR-6)

`TrackService` (new, `S/core/v3_tracks.py`). Commands where a human acts run through `IdempotencyService.execute`; gate-edge advancement proves a closed, non-superseded approval for that gate+scope at the expected revision (`v3_require_gate_approval`, the track-based sibling of `S/core/state_machine.py:93`, which stays V1-untouched).

| Command | Actor | Scope | Expected revision | Source → target | Hash-bound prerequisites | Writes / jobs / events | Replay identity | Activation |
|---|---|---|---|---|---|---|---|---|
| `create_v3_season(intake_ref)` | Operator (human session) | season | — | — → seasons(v3, PROPOSED) + `season_tracks(IDEA, NOT_SCHEDULED)` | intake ref present | season row (`workflow_version='v3'`, legacy pinned PROPOSED); track; `SEASON_SETUP` account (A2); event `v3.season.created` | idempotency key | **A2** — `NOT_AVAILABLE` in A1 |
| `create_v3_episodes(season, count)` | System (STORY LOCK handler); exposed to test handlers in A | season | season_tracks.revision | planning `PLANNED → STORY_LOCKED`, atomically with creation | STORY_LOCK APPROVE closed at that revision | episodes (legacy PLANNED) + `episode_tracks` + EPISODE/SEASON accounts (A2); event `v3.episodes.created` | (season, count, revision) semantic | **A2** |
| `open_gate(gate, scope, binding)` | System (phase-handler job) | season/episode | track revision (read) | — (no state change) | binding hash over current content; no live GPU lease in scope (§8); no open activation for the gate | `gate_activations` open row; event `gate.opened` | (gate, scope, binding_sha256) unique | **A1** |
| `supersede_gate(activation)` | System | season/episode | activation open | open → superseded | the activation is open | `superseded_by`, `closed_at`; event `gate.superseded` | idempotent by activation state | **A1** |
| `decide(gate, scope, action, …)` | Operator (human session + CSRF) | season/episode | season_tracks.revision | per §5 step 8; AR-3: Reject CAST_LOCK leaves planning `CASTING`; Reject LAUNCH leaves release `CALENDAR_PROPOSED`, planning untouched | binding hash + content revision + open activation (§5 step 6) | approval event, notes, activation closed, track revision bump, handler writes/jobs/events | idempotency key | **A1** (LOCK via test handler in tests; unshipped gates → `NOT_AVAILABLE`) |
| `advance_planning(to)` | System (phase handler) or test handler | season (or extension) | season_tracks.revision | master edges `IDEA→PROPOSED→LOCKED→BIBLE→PLANNED→STORY_LOCKED→CASTING→CAST_LOCKED`; gate edges (`PROPOSED→LOCKED`, `PLANNED→STORY_LOCKED`, `CASTING→CAST_LOCKED`) need that gate's APPROVE; every other master edge is `NOT_AVAILABLE` until its phase | gate edges: closed approval at the current revision; non-gate edges: the driving phase's prerequisites (B+) | planning_state + revision bump; event `track.advanced`; jobs per phase | (scope, from, to, revision) | **A1** (mechanism); production edge availability follows B+ |
| `reject_to(previous)` | System (inside `decide` REJECT) | season | activation's revision | **No state move** (AR-3 drops "previous planning state"): CAST_LOCK Reject → planning stays `CASTING` without cast authority; LAUNCH Reject → release stays `CALENDAR_PROPOSED` without launch authority, planning untouched | the decision transaction's checks | activation closed, revision bumped; event `gate.rejected` | part of the decision's idempotency | **A1** |
| `cancel_season` / `cancel_episode` | Operator (human session) | season/episode | track revision | terminal: `cancelled_at` on the track row(s); **legacy `seasons.state` untouched for V3** | no in-flight external operations without a reconciliation entry (A3 fence) | `cancelled_at`, revision bump; queued/waiting jobs cancelled via `JobService.cancel_in` (A3 — the transaction-owned variant of `S/core/jobs.py:864`); event `track.cancelled` | idempotency key | **A3** |
| `rewind_for_amendment(scope, to)` | System (amendment coordinator only) | season/episode | content_revision + track revision | backward planning edge inside the master §12.6 closure | impact hash + Confirm (A4) | `content_revision` bump; cancels/re-enqueues affected work (A3/A4); event `amendment.applied` | amendment id | **A3/A4** |
| `create_extension(season, range)` | Operator (human session) | season | season_tracks.revision | opens `season_extensions` (open row ⇒ `EXTENDING`) | season at `STORY_LOCKED`+; range beyond the current episode count | extension row; event `v3.extension.opened` | idempotency key | **B** (OQ-1) |

AR-6 rule: commands whose dependencies have not shipped return `NOT_AVAILABLE` **before any write**; their behavioural gates move with activation (A-T4 asserts the refusal; A2/A3 tests assert the behaviour). `content_revision` bumps only on amendments and lock decisions (spec §3): STORY LOCK and CAST LOCK APPROVE bump it; other decisions bump only `revision`.

## 7. The `require_workflow` inventory (AC-5)

New helper `S/core/workflow.py`:

```python
class WorkflowMismatch(MicrodramaError):   # HTTP 409
    code = "WORKFLOW_MISMATCH"

def require_workflow(tx: Tx, *, season_id: UUID | None = None, episode_id: UUID | None = None,
                     expected: str = "v1") -> None:
    """Resolve the season through the episode FK when needed; plain read, no lock."""
```

Two guard classes: **(a) refusal** on services/handlers/replayed jobs — a V3 row reaching a legacy path raises `WORKFLOW_MISMATCH` and is never silently processed; **(b) candidate filters** on scheduler selector queries (`AND s.workflow_version = 'v1'` / joined equivalent) so a V3 season never becomes legacy work — a filtered row never reaches the path, and the service-side guards remain as defense in depth.

| Entry point (`file:function`) | Guard |
|---|---|
| `S/research/service.py:353 _open_run` (entry `run_research`), `:878 _write_proposal` | refusal after the season row is claimed |
| `S/review/intake.py:700 _create_intake`, `:760 select`, `:880 _status`, `:971 _phase`, `:1012 handle_research_job`, `:1381 _workbench` | refusal (V3 seasons use `create_v3_season`, never intake) |
| `S/story/service.py:473 compile_season`, `:733 _claim_episode` (accepts pinned PLANNED, factmap `:752`), `:1321 _persist_success` | refusal at claim and at persist |
| `S/references/service.py:413 _claim`, `:1074 _persist`, `:1438 _change_claim` | refusal |
| `S/editing/service.py:638 _claim`, `:994 _persist` | refusal |
| `S/qa/repairs.py:508 plan_from_feedback`, `:975 execute_plan`, `:1424 _reopen_gate2` | refusal |
| `S/pipeline/packaging.py:223 prepare_and_store_package`; `S/review/packages.py:216 store_release_package` | refusal |
| `S/publishing/slots.py:117 schedule_release`; `S/publishing/service.py:341 _validate_and_begin`, `:776 _mark_publishing`, `:902 _maybe_complete_episode`, `:1072 release_view` | refusal |
| `S/analytics/qualification.py:90 _episode_facts` (covers `:200 _production_qualifies`, `:249 _management_window`) | refusal (V3 qualification is phase B+) |
| Selectors `S/scheduling/service.py`: `:169 _w01_research`, `:183 _w02_compile_backstop`, `:199 _w03_episode_cadence` (its direct INSERT at `:228` gets a refusal inside the insert transaction), `:242 _w03_write`, `:263 _w04_references`, `:279 _w06_edit`, `:333 _w07_qa`, `:538 _w09_publish_submit`, `:630 _w09_publish_poll`, `:677 _w11_analytics`, `:697 _w05_render_dispatch`, `:770 _w05_render_poll` | candidate filter on the selection SQL (`JOIN seasons s … AND s.workflow_version='v1'`; `_w05_render_poll` filters through `jobs.season_id`) |
| Replayed jobs: `S/workers/runtime.py:216 _execute` (before handler dispatch at `:236`); `S/core/jobs.py:752 resolve_reconciliation` (the `_w05_render_poll` resolution path) | refusal — a V3 job never runs a V1 handler; V3 job types are distinct and registered per phase |
| `:822 _w12_workers_janitor`, `:829 _w12_gpu_janitor` | via the adapters below |

**Per-version adapters for the shared janitors** (not blanket V1 filters — spec §1):
- Workers janitor `requeue_expired` (`S/core/jobs.py:706`): the job lifecycle is version-shared; no filter. The V3 projection is `track_waits` (a quarantined job shows `BLOCKED (reconcile)`); V1 is unchanged.
- GPU janitor `_sweep_leases`/`_cause` (`S/rendering/janitor.py:237`, `:272`): the candidate query gains a V3 arm — a live lease whose scope has an **open gate activation** is a candidate with cause `human_wait` (§8); the V1 `e.state='AWAITING_FINAL_REVIEW'` arm is untouched.
- Billing janitors: A2 (they gain the V3 scope kinds there); A1 adds no budget-janitor change.

## 8. GPU human-wait safety (AC-9)

One predicate, used by every attachment point — `S/core/workflow.py`:

```python
def v3_human_wait(tx: Tx, *, season_id: UUID, episode_id: UUID | None = None) -> bool:
    """True while any gate activation is open for the scope (episode gate: that episode;
    season gate: the season). 'Waiting for you' == an open activation (spec §2.5)."""
```

| Attachment | Where | Check |
|---|---|---|
| Gate/pick activation | `TrackService.open_gate` (§6), after the track lock | refuse `PolicyDenied` while the scope has a **live GPU lease** (episode scope: `S/rendering/leases.py:204 episode_live_lease_count`; season scope: new `season_live_lease_count`, same live predicate joined to the season's episodes) — no GPU is held while a human wait opens (master §10.5) |
| Lease admission | `S/rendering/leases.py:671 claim` (incl. `_w05_render_dispatch`'s claim at `S/scheduling/service.py:747`) | refuse `PolicyDenied` when `v3_human_wait` for the target episode's scope — a waiting scope admits no new pod |
| Heartbeat | `S/rendering/leases.py:1019 heartbeat` (join at `:1023-1027` already carries `e.state`) | an ACTIVE lease whose scope is in `v3_human_wait` behaves exactly like the V1 `HUMAN_WAIT_STATES` branch (`:1031-1039`): resurrection refused; the janitor is the cleaner |
| Claim / adoption / transfer | `S/rendering/leases.py:671 claim`, `:1319 transfer`; the T031-merged comfy claiming/adoption and `reconcile_unknown` paths (`S/rendering/comfy_jobs.py`; today `_verify_job:703`, `_load_current_prompt_manifest:572`, `_collect_outputs:914`) | same predicate before any new external submit under that scope |
| Janitor candidate + `_cause` | `S/rendering/janitor.py:237 _sweep_leases`, `:272 _cause` | candidate query adds `OR EXISTS (open activation for the lease's season/episode)`; `_cause` returns `'human_wait'`, reusing the terminal mapping in `_clean_lease` (`:302-309`: human_wait → RELEASED) — verified shutdown, accrual accounted |

`HUMAN_WAIT_STATES` (`S/rendering/leases.py:90`) and `human_wait_guard` (`:212`) stay V1-untouched; V3's pinned `PLANNED` episodes never enter that EpisodeState path, which is why the checks attach at the activation/lease layer (AC-9's point). Waits are scope-keyed (episode gate → that episode; `TEASER_FINAL`/`LAUNCH` → no episode admits new leases) so unrelated approved releases continue — publishing paths take no leases.

## 9. Lock audit (spec §6)

| # | Lock |
|---|------|
| 1 | Command idempotency row |
| 2 | `season_tracks`, then `season_extensions` |
| 3 | `episode_tracks` (id order) |
| 4 | Scope domain rows (seasons, episodes, approvals) |
| 5 | Jobs (id order) |
| 6 | `provider_operations` → leases (GPU) |
| 7 | Budget (mutex → SEASON → children → steps → categories → reservations → charges) — A2 |

Transactions A1 adds or touches:

| Transaction | Locks in order | Verdict |
|---|---|---|
| V3 decision (§5) | 1 (`S/core/idempotency.py:84-87`) → 2 `season_tracks` FOR UPDATE (→ 3 `episode_tracks` for Gate 2) → 4 seasons row (ownership+version, mirroring `S/review/service.py:401`) → approval/notes inserts → 5 job enqueues by the callback | conforms |
| `open_gate` / `supersede_gate` | 2 track lock (fence reads take SHARE per spec §6; the activation insert serializes on the track lock so the unique open-activation index arbitrates) → 6 lease-count read (guarded count, no lease row lock) | conforms |
| `advance_planning` / `reject_to` | 2 → (3 for episode-scoped edges) → 4 → 5 (only when a phase handler enqueues) | conforms |
| `create_v3_episodes` (A2 activation) | 2 → 4 seasons → episode inserts → 3 `episode_tracks` inserts → 7 budget attach (A2) | conforms; budget order fixed for A2 |
| V1 decision paths | unchanged (`S/review/service.py:401`, `:1129`; `S/core/approvals.py:64`) — V1 never locks tracks, so no cross-version cycle is possible | untouched |
| `require_workflow`, `track_waits` reads | plain reads, no locks | n/a |

**Inversions found (none introduced by A1; recorded with their owners):**
1. Worker completion takes the job lock first (`S/core/jobs.py:648` FOR SHARE in `lease_guard`, `:677` FOR
UPDATE in `finish`), while amendments take track → job. A1 adds no such transaction; this row hands A3 the required order (track before job) and A3 ships the competing-transaction test.
2. `S/budget/billing.py:1296` locks a child account/reservation before shared settlement logic (parent
later) — A2's inversion to fix (spec §5.3).
3. `_w03_episode_cadence` inserts episodes without the season row lock
(`S/scheduling/service.py:219-238`) — pre-existing V1 behaviour; V3 rows are filtered out (§7).

**Competing-transaction tests A1 ships** (`X/integration/v3/test_lock_order.py`, two connections): concurrent `decide` on one activation → exactly one commits, the other gets `StaleRevision`, the activation closes once; `decide` vs `advance_planning` on one season → serialized by the §6-#2 lock, no lost revision bump; `open_gate` vs `decide`-closing-that-activation → the unique open-activation index admits one open row.

## 10. Test plan (A-T1..A-T6, A-T16)

All offline, real runtime/composition with fakes (existing conftest / ephemeral PostgreSQL), pytest `--basetemp` under the session scratchpad.

| ID | File (new unless noted) | Cases |
|---|---|---|
| A-T1 | `X/integration/v3/test_gate_rules.py`; `X/contract/contracts/test_v3_gate_actions.py`; existing `X/contract/contracts/test_states_routes_jobs.py:74` (green, unedited) | gate values admitted for v3, refused for v1; entity/action matrix; **V1 rows keep exactly today's rules** — insert a v1 SEASON_CONCEPT REVISE, a feedback-less REVISE, an unknown gate, an unbound EPISODE_FINAL APPROVE and assert the same errors as before 0029; EPISODE_FINAL APPROVE binding identical both versions; deferred note trigger: commit without notes fails, with notes commits; `V3_GATE_ACTIONS` exact; `GATE_ACTIONS` byte-asserted unchanged; `contracts-check` green with V1 files byte-identical (`git diff --stat contracts/` empty on V1 files) |
| A-T2 (V3-AT-2) | `X/integration/v3/test_decision.py` | positive LOCK approve/revise/reject via the test handler; negatives: foreign owner (NotFound, no existence signal), service credential (refused before body), missing CSRF (403), wrong gate/scope/hash/revision/content_revision (409), stale page (revision bumped between render and post), callback failure rolls **everything** back (approval row, notes, activation closure, track revision, handler writes all absent), concurrent decisions (one wins), idempotent replay returns the stored response, notes stored with typed targets validated against binding units (a target outside the binding → 422); production registry refuses `register(test_only=True)` |
| A-T3 | `X/integration/v3/test_handler_availability.py` | STORY_LOCK/CAST_LOCK/TEASER_FINAL/LAUNCH and V3 EPISODE_FINAL → `NOT_AVAILABLE` for all three actions through JSON **and** HTML; nothing recorded (no approval row, no activation change, no event, no job); no fallback to V1 (the `GATE_ACTIONS` path unreachable for V3 scopes) |
| A-T4 | `X/integration/v3/test_commands.py` | every §6 row: allowed sources advance, refused sources raise `InvalidTransition`/`GateNotReady`; replay identity; events; later-phase edges and A2/A3-gated commands → `NOT_AVAILABLE` with no writes; `advance_planning` gate edges require the closed approval; `reject_to` per AR-3; activation closed + revision advanced per decision |
| A-T5 | `X/integration/v3/test_discriminator.py` | every §7 entry point refuses a V3 row with `WORKFLOW_MISMATCH` (services, handlers, replayed jobs incl. `resolve_reconciliation`); selectors exclude V3 rows; `workflow_version` immutable; episode re-parent refused; V1 rows still pass every guarded path (no-op for 'v1') |
| A-T6 | `X/integration/v3/test_track_waits.py` | concurrent waits show together (RETRY_WAIT quota + unresolved op); one job resuming clears only its row; terminal FAILED blocks until a later SUCCEEDED replacement shares `logical_work_id`; NEEDS_RECONCILIATION and in-flight/UNKNOWN ops block even for CANCELLED jobs; dismissal marks `dismissed` only; resume clears waits after the authoritative transition commits; GPU checks per §8: `open_gate` with a live lease refused, lease claim during an open activation refused, heartbeat/janitor candidates behave (janitor releases with cause `human_wait`) |
| A-T16 | `X/integration/persistence/test_migrations.py` (extend; upgrade test at `:122` is the pattern) | 0028–0031 apply on a **populated V1 database**: seed V1 seasons/episodes/approvals/jobs at 0027 via `S/testing/seed.py`, migrate to head, assert every V1 row intact, `workflow_version='v1'` backfilled, V1 CHECK rejections byte-equal after 0029, jobs work-scope columns NULL, `EXPECTED_TABLES` superset holds, applied 0001–0027 checksums unchanged; catalog tests green on the new tables (automatic); fresh-create tail asserts `0028..0031` |

## 11. Open questions

| # | Question | Recommendation |
|---|----------|----------------|
| OQ-1 | Which package activates `create_extension`? AR-6 names only A2 (account-backed creation) and A3 (cancellation/fencing); extensions have a B/C planning lifecycle but no account machinery of their own. | Activate with **phase B** (the first phase driving extension planning); `NOT_AVAILABLE` until then. Trivial to move if the orchestrator prefers A2. |
| OQ-2 | How is a cancelled track represented? Master §2.2 has no CANCELLED planning/release state, but spec §3 says `track_waits` includes "the track's own cancelled state". | `cancelled_at` on `season_tracks`/`episode_tracks` (0030), surfaced as the `CANCELLED` wait; keeps the enums master-verbatim. A CANCELLED enum value would touch every transition map for no gain. |
| OQ-3 | `defer_reason` vocabulary: spec §3 maps RETRY_WAIT causes to WAITING_QUOTA/PROVIDER/BUDGET, but A0 §5.2 does not enumerate the persisted reasons (one example is `GATEWAY_UNAVAILABLE`). | Agree a closed `DeferReason` enum in `contracts/enums.py` during the A0 build; the view maps BUDGET/QUOTA explicitly, everything else to WAITING_PROVIDER, carrying the raw cause. A1's view SQL is written against the enum's values, not free text. |
| OQ-4 | Scope-level waits (CANCELLED) cannot be dismissed under 0031's CHECK (exactly one subject column required). | Relax to allow both subject columns NULL = scope-level dismissal (kind+scope identity already unique). One-line CHECK change **before** 0031 is applied; if ordering has already applied it, a 0032 follow-up — never an edit. |
| OQ-5 | Does A1 ship any production (non-test) gate handler? Spec §2.7 implies none for unshipped phases, so **no V3 gate is decidable in production until B**. | Ship zero production handlers in A1; the LOCK test handler is test-world only. Keeps A-T3 honest; B's first real handler is a small diff. |
| OQ-6 | V3 Gate 2 (`EPISODE_FINAL` on a V3 episode) reuses V1 binding semantics (package hash, manifest) — desired for phase A? | Keep identical rules in both versions (0029 does); any V3 episode binding work belongs beside the phase that creates V3 episodes (B). |

## 12. Orchestrator rulings on the open questions (11 Nov, before the Codex critique)

| # | Ruling |
|---|--------|
| OQ-1 | **Accepted.** `create_extension` activates with **phase B**; it returns `NOT_AVAILABLE` until then. |
| OQ-2 | **Accepted.** `cancelled_at` on `season_tracks` and `episode_tracks`, surfaced as the `CANCELLED` wait. The master enums stay verbatim. |
| OQ-3 | **Accepted, with the enum owned by A0.** A0-D adds a closed `DeferReason` enum to `contracts/enums.py`:<ul><li>`QUOTA_5H`, `PACE_WEEK`, `QUOTA_UNREADABLE`, `CONCURRENCY` → `WAITING_QUOTA`;</li><li>`BUDGET` → `WAITING_BUDGET`;</li><li>`GATEWAY_UNAVAILABLE`, `PROVIDER_RATE_LIMITED`, and the legacy `RATE_LIMITED` → `WAITING_PROVIDER`.</li></ul>The 0031 view maps the enum values explicitly and carries the raw cause. **An unknown value fails the view's CHECK, never falls through.** |
| OQ-4 | **Accepted.** 0031 is not applied yet, so the CHECK allows a scope-level dismissal (both subject columns NULL) in 0031 itself. |
| OQ-5 | **Accepted.** A1 ships **zero** production gate handlers. |
| OQ-6 | **Accepted** for the SQL rules. Note that spec §2.7 still refuses a V3 Gate 2 with `NOT_AVAILABLE` at the command layer until phase F; identical SQL rules don't make it decidable. |

The master §10.0 ownership sentence is amended in v0.4.4 exactly as §3 of this note proposes.
