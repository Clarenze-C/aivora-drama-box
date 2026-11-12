# A3 design note: revision fence, cancellation, stale quarantine, per-queue workers

**Version 1.0, 12 Nov 2026. Author: GLM (design note only; one file, no code).** Requirements:
[phase-A-spec.md](phase-A-spec.md) v0.3 §0, §1, **§4**, **§6**, **§7.1, §7.4** (§7.2–§7.3 read for API
fit), §10 (A3 row + AR-6 activation), §11 (A-T8, A-T12a, A-T18); AC-7, AC-15, AC-16, AC-23
replacement wording in [codex-a-critique.md](codex-a-critique.md) (binding per §0) plus its
reader/writer inventory; AR-4, AR-6 in [codex-a-recritique.md](codex-a-recritique.md) (binding);
[A1-design-note.md](A1-design-note.md) v1.2 §1/§2.3/§2.4/§6/§9;
[A2-design-note.md](A2-design-note.md) v1.0 §1/§8; [phase-A0-spec.md](phase-A0-spec.md) v0.4 §5
(the runtime contract A3 consumes — `Deferred`, `defer_reason`, `refund_attempt`, the signal
translation, `REFUSED_PRELAUNCH`, §5.3 LLM reconciliation; §5.4 cancellation forwarding); master
[SPEC-v3.md](SPEC-v3.md) §10.0 (one persisted lifecycle; the state-mapping table), §12.6
(amendment). Facts re-verified read-only on `feat/microdrama-m0-m4` @ `69c4096` (applied tail
0025; 0026 = T031 in `.scratch/t031-gate-h2/`; 0027 = A0, 0028–0031 = A1, 0032–0034 = A2 —
prerequisites, not yet built). `S/` = `src/microdrama/`, `M/` = `migrations/`, `X/` = `tests/`.

**A3 builds** the spec §10 A3 row: the fence, `cancel_in`, stale quarantine, cancelled-operation
reconciliation, per-queue workers — consuming A0's runtime with **no second variant** (spec §4) —
and **activates `cancel_season` / `cancel_episode` and `rewind_for_amendment`** (AR-6; A1 §6
shipped them returning `NOT_AVAILABLE`).

---

## 1. Migration allocation

Prerequisite pin: T031 (0026) + A0 (0027) + A1 (0028–0031) + A2 (0032–0034) land first. A2's last
number is 0034 (A2 §1), so **A3 starts at 0035**. Applied migration bytes are never edited — the
migrator hashes file bytes and rejects changed checksums (`S/persistence/migrate.py:51`, `:95`).
A3 allocates exactly one migration, one purpose:

| # | File | Purpose |
|---|------|---------|
| 0035 | `0035_v3_fence_quarantine.sql` | The `jobs` fence-input CHECK (V3 jobs must carry `expected_content_revision`) and the `stale_artifacts` evidence table with its guards |

No other migration is needed: the lease columns A3 relies on already exist
(`jobs.lease_owner/lease_expires_at/heartbeat_at`, `M/0001…sql:87-89`), cancel reasons live in the
existing `jobs.outcome` jsonb (`M/0001…sql:91`), and **phase A adds no queue lanes** (spec §4), so
the queue CHECKs on jobs (`M/0001…sql:77`) and reservations (`M/0003…sql:71`) stay byte-identical.

## 2. Guarded DDL

Guard pattern per A1 §2 / A2 §2: `md_forbid_mutation` for row DELETE + statement TRUNCATE,
`md_non_integer_numbers`-style integer guard via the 0026-style DO loop
(`.scratch/t031-gate-h2/M/0026…sql:94-99`). The catalog tests inspect the live catalog
(`X/integration/persistence/test_schema_catalog.py:22-37`, `relkind='r'` only), so every new table
is covered automatically, TRUNCATE (`:57`) and integer-numbers (`:65`) included.

### 2.1 Where `expected_content_revision` lives, and its CHECK

It lives **in the job input payload** (`jobs.input` jsonb), exactly where A1's `track_waits` view
already reads it (`(input->>'expected_content_revision')`, A1 §2.4). A jobs column would duplicate
that and fight `jobs_identity_immutable` (`M/0001…sql:104-105`, which already freezes `input`).
A3 adds the SQL backstop A1's Python validation lacked:

Changed CHECK beside the old one — the only constraint A3 touches on an existing table:

```sql
-- OLD (M/0001_foundation.sql:72-105): no constraint between work scope and input.
--      A1's 0031 added track/extension_id/logical_work_id/replaces_job_id with CHECKs
--      binding them to each other, but nothing binds a V3 job's input to a fence value.
-- NEW (0035):
ALTER TABLE jobs
  ADD CONSTRAINT jobs_v3_fence_input CHECK (
    track IS NULL
    OR (input->>'expected_content_revision') ~ '^[0-9]+$'
  );
```

- `track IS NULL` is every V1 job (A1 §2.4): the constraint passes trivially for all existing
  rows — the A-T16 upgrade test asserts it on a populated V1 database.
- Range and scope correctness are validated in Python at enqueue (§3.2): the CHECK is the
  write-boundary backstop that a V3 row can never exist without a fence value, mirroring A0's
  0027 `defer_reason` CHECK pattern (A1 §3, ruling 2).
- No index is added: the fence resolves its track row through existing unique keys
  (`season_tracks.season_id UNIQUE`, `episode_tracks.episode_id UNIQUE` — A1 0030;
  `season_extensions` PK), one point lookup per validated job.

### 2.2 Migration 0035 — `stale_artifacts`

```sql
CREATE TABLE stale_artifacts (
  id                        uuid PRIMARY KEY,
  schema_version            text NOT NULL DEFAULT '1.0',
  job_id                    uuid NOT NULL REFERENCES jobs(id),
  operation_id              uuid REFERENCES provider_operations(id),
  season_id                 uuid NOT NULL REFERENCES seasons(id),
  episode_id                uuid REFERENCES episodes(id),
  extension_id              uuid REFERENCES season_extensions(id),
  track                     text NOT NULL CHECK (track IN ('planning','production','release')),
  artifact_refs             jsonb NOT NULL DEFAULT '[]',  -- [{kind,id,object_key,sha256}] evidence
  receipt_refs              jsonb NOT NULL DEFAULT '[]',  -- [{kind,id}] reservation/charge refs
  expected_content_revision integer NOT NULL CHECK (expected_content_revision >= 0),
  actual_content_revision   integer NOT NULL CHECK (actual_content_revision >= 0),
  CHECK (actual_content_revision > expected_content_revision),   -- evidence of staleness itself
  reason                    text NOT NULL CHECK (reason <> ''),
  created_at                timestamptz NOT NULL DEFAULT now()
);
-- One evidence row per (job, operation): a replayed collector must not duplicate it.
CREATE UNIQUE INDEX stale_artifacts_one_per_job_operation ON stale_artifacts
  (job_id, COALESCE(operation_id, '00000000-0000-0000-0000-000000000000'::uuid));
CREATE TRIGGER stale_artifacts_append_only BEFORE UPDATE OR DELETE ON stale_artifacts
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
-- 0026-style DO loop over ARRAY['stale_artifacts']: statement TRUNCATE refusal +
-- INSERT/UPDATE integer-number guard (catalog tests then cover it automatically).
```

Semantics: append-only evidence, never current content (spec §7.1 "quarantined evidence: job,
operation, artifact refs, expected vs actual revision"). `receipt_refs` makes the money trail
queryable from the same row (money is accounted normally, §3.4). The scope columns mirror the
job's work scope so A5's recovery screens can group by season/episode/extension without joining
`jobs.input`.

**Catalog and contract updates** (AC-23):
- `X/integration/persistence/test_migrations.py` `EXPECTED_TABLES` += `stale_artifacts` (the check
  is a `<=` superset, factmap §10); the fresh-create tail assertions extend to `0035` (A0 extends
  to 0027, A1 to 0031, A2 to 0034 — A3 rebases on theirs).
- `S/contracts/v3.py` (A1 §4) gains the shared V3 input base so every later phase's job input
  carries the fence uniformly:

```python
class V3ScopedStepInput(VersionedPayload):
    season_id: UUID
    episode_id: UUID | None = None
    extension_id: UUID | None = None
    track: Literal["planning", "production", "release"]
    expected_content_revision: int = Field(ge=0)
```

  It generates under `schemas/v3` + `examples/v3` through A1's manifest loop; the drift check
  (`Makefile` contracts-check) stays green. Events registered with payload schemas (AC-19 naming:
  dotted segments start with a letter, `S/contracts/events.py:21`): `track.cancelled`
  `{season_id, episode_id?, extension_id?, track, actor_owner_id, reason, revision}` and
  `track.rewound` `{scope, from, to, content_revision_before, content_revision_after,
  amendment_ref}`.

## 3. The fence

### 3.1 Scope resolution and the single helper

One helper, in `S/core/v3_tracks.py` beside A1's `TrackService` (module functions — `JobService`
calls them without a service dependency):

```python
class StaleContentRevision(MicrodramaError):      # HTTP 409
    code = "STALE_CONTENT_REVISION"

@dataclass(frozen=True)
class FenceScope:
    season_id: UUID
    episode_id: UUID | None
    extension_id: UUID | None
    track: str

def resolve_fence_scope(job_row: Mapping) -> FenceScope | None:
    """None for V1 rows (track IS NULL). Extension > episode > season resolution,
    exactly the COALESCE order of A1's track_waits fence column."""

def fence(tx: Tx, scope: FenceScope, *, expected: int) -> int:
    """SELECT ... FROM <resolved track row> WHERE <scope key> FOR SHARE; compare
    content_revision. Returns the current revision when current == expected.
    Raises StaleContentRevision when actual > expected (stale) — the caller takes
    the quarantine path — and Conflict when actual < expected (a fence value from
    the future: corruption, refuse). The SHARE lock is held by the caller's
    transaction through its canonical mutation."""

def current_revision(tx: Tx, scope: FenceScope) -> int:
    """Plain unlocked read — admission checks only, never a guarantee (§7)."""

def record_stale(tx: Tx, *, job_row, operation_id: UUID | None, artifact_refs: list,
                 receipt_refs: list, expected: int, actual: int, reason: str,
                 now: datetime) -> UUID:
    """Append the stale_artifacts row; idempotent on (job_id, operation_id)."""
```

**Why SHARE (spec §6: "fence reads take a SHARE lock on the track (2/3); amendments take FOR
UPDATE"):** an ordinary re-read can observe revision N, then an amendment commits N+1 before the
worker writes (AC-15's exact objection). The SHARE lock blocks the amendment's `FOR UPDATE`
bump — and therefore its whole apply transaction — until the mutation's transaction commits, so
the read-validate-write is atomic against every amendment. Two fence readers never block each
other. **Invariant: `fence()` is the first lock a canonical-mutation transaction takes** (§7
audits every call site against it).

### 3.2 Every call site

| `file:function` | Placement |
|---|---|
| `S/core/jobs.py:enqueue` (`:353-438`) | **Enqueue — the front door.** A1's N1-9 work-scope validation branch gains: `track` set → `expected = payload.expected_content_revision` (missing/malformed → `SchemaInvalid`; the 0035 CHECK is the SQL backstop) → `fence(tx, scope, expected)` **before** the INSERT (`:389-414`), SHARE held through it. Every continuation reaches the fence through this one seam, because every enqueue does: `rendering/routing.py:725`, `:944`; `review/service.py:464`, `:1267`, `:1321`; `review/intake.py:740`, `:852`; `qa/repairs.py:1259`, `:1304`, `:1439`; `core/api.py:119`; `pipeline/runner.py:186`; the scheduler's `_enqueue`. Inside an A1 decision transaction the SHARE lands on a row the transaction already holds FOR UPDATE — a no-op in one transaction, order preserved |
| `S/core/jobs.py:claim` (`:478-550`) | **Admission.** After the in-flight quarantine checks (`:503-506` for RETRY_WAIT, `:520-523` for QUEUED) and before the RUNNING move (`:525-537`): for a V3 candidate, `current_revision` (plain read, §7) — `actual > expected` → the job is finished `CANCELLED` with `error_code='STALE_CONTENT'`, `outcome={kind:'CANCELLED', reason:'stale_content_revision', expected, actual}` via `_move` (the map admits QUEUED→CANCELLED and RETRY_WAIT→CANCELLED, `S/contracts/states.py:102`, `:115`), and the next candidate is considered — the handler never runs. Already-terminal rows (an amendment's `cancel_in` won the race) are skipped silently. **WAITING_EXTERNAL candidates lease normally** (`:512-514`): polling *is* reconciliation of in-flight operations; its result is fenced at collection |
| V3 submit / `begin` | The V3 submit step fences **in the same transaction as `provider_ops.begin`, under `lease_guard`** — A0's pattern (§5.1: every operation write under the guard), the V1 shape being `rendering/comfy_jobs.py:611-623`. Order inside the transaction: `fence()` SHARE (#2/3) → `lease_guard` job SHARE (`S/core/jobs.py:648`) → `begin` INSERT (#6). Stale → no `begin`, no provider call, no money; the job finishes `CANCELLED`/`STALE_CONTENT` |
| Collectors | The V3 collect path fences in the transaction that records the provider result — the V1 shape is `record_result(SUCCEEDED)` at `rendering/comfy_jobs.py:899-910`. Current → outputs register **and** are installed/accepted as current content. Stale → outputs still register (the bytes were paid for; §3.4) plus `record_stale(...)` in the same transaction, and installation/acceptance is skipped. `_collect_outputs` (`:913-935`) runs either way. Money settlement (`_settle_if_needed`, `:965-1070`) runs either way |
| Acceptance | V1 `_accept_asset` (`S/pipeline/handlers.py:82-85`, called at `:186-189`) is **untouched**. V3 acceptance exists only inside the fenced collector transaction above — a V3 asset never becomes `ACCEPTED` outside a `fence()`-held SHARE |
| Continuations | Covered by the `enqueue` seam: the finishing handler stamps the continuation's `expected_content_revision` with the fence value it validated under its own held lock, and the enqueue fence re-validates it (SHARE → INSERT) in the continuation's own transaction |
| Reconciliation adoption | `S/core/jobs.py:resolve_reconciliation` (`:752-862`): for V3 rows, `fence()` SHARE is taken **before** `_lock` (`:784`) — track before job (§7). RESUME (`:796-810`) is allowed for stale jobs (operations must settle; A1 §3 keeps them blocking `track_waits` until they do). The SUCCEEDED resolution (`:811-843`) on a stale job still certifies the operations (they are recorded successes) but records `outcome.quarantined=true` and `record_stale(...)` instead of granting content authority. The A0 auto-reconciler (A0 §5.3) adopts results through the same rule: settle first, fence the installation |
| Amendment consumers (A4) | `rewind_for_amendment`'s sweep and A4's apply call `cancel_in` per job, id order, under their already-held track FOR UPDATE (§4, §7) |

Admission is deliberately a **plain read**, not a SHARE lock: the claim transaction already holds
the job row FOR UPDATE (`:498`, `:511`), so a track lock there would order #5 before #2/3 — the
exact inversion the spec's lock table forbids ("a worker completion that needs both track and job
locks takes the track first", §6). Correctness does not depend on the admission read: READ
COMMITTED sees either N or N+1, never torn; a job admitted at N that goes stale before its first
mutation is caught by that mutation's `fence()`, and A-T12a's race test proves no stale write ever
lands as current content. (Moving the SHARE into `claim` would also deadlock an amendment's
track→job chain against the claim's job→track chain — rejected.)

### 3.3 Season-scope and episode-scope work

The fence resolves exactly one track row per job — the same COALESCE order as A1's `track_waits`
fence column (`A1 §2.4`: extension fence for extension jobs, else episode fence, else season
fence):

| Job shape | Fence row | Lock |
|---|---|---|
| `extension_id` set (planning work on an extension scope) | `season_extensions.content_revision` | FOR SHARE (#2) |
| `episode_id` set (production/release work on an episode) | `episode_tracks.content_revision` | FOR SHARE (#3) |
| season only (planning/release work on the season) | `season_tracks.content_revision` | FOR SHARE (#2) |

**An episode job never fences on the season track.** A season-scope bump alone leaves episode
work current by design: an amendment that affects an episode bumps that episode's track inside its
closure (A4 §7.3 step 1), and one that does not must not stop unrelated in-flight work — the same
scoped-invalidation principle as AR-3/AR-4 (preserve unrelated approved releases). The
corollary obligation sits with A4: **an amendment's computed closure must bump every episode
track whose work it invalidates.** Flagged as OQ-1.

### 3.4 Quarantine while money accounts normally

A stale result is never installed as current content (spec §7.1), but nothing about it is
discarded or left unaccounted:

1. **Outputs register** (assets/rows with hashes and object keys) — they are evidence, and the
   provenance chain stays intact.
2. **`stale_artifacts` row appends** in the same transaction, with `artifact_refs`,
   `receipt_refs`, expected vs actual revision (§2.2).
3. **Money is still accounted normally.** Settlement and receipt posting are not canonical
   content mutations and run unconditionally: GPU-style `_settle_if_needed`
   (`rendering/comfy_jobs.py:965-1070`), `_post_charge`/`check_overrun` under A2's hierarchy
   locks (A2 §3.3), LLM evidence in `llm_invocations` (unmetered — no charge, A0 §5.5.5).
   Reservation release keeps its existing rule — refused while operations are in flight
   (`S/budget/service.py:526-539`) — so exposure is retained until reconciliation settles.
4. **No continuation is enqueued from quarantined work** (the continuation seam re-fences anyway,
   but the stale collector simply does not enqueue).
5. `track_waits` (A1 §2.4) already treats a stale job as non-authority: its `stale` CTE excludes
   it from every wait/block projection, and its unresolved operations keep blocking through the
   operation branch "even for cancelled or stale jobs, until reconciliation settles them".

## 4. `JobService.cancel_in(tx, job_id, reason)`

```python
def cancel_in(self, tx: Tx, job_id: UUID, *, reason: str, now: datetime | None = None) -> Job:
    """cancel() on the caller's transaction (spec §7.4), so cancelling joins the
    amendment / cancel-season transaction. Identical semantics to cancel()."""
```

**API beside `cancel()`** (`S/core/jobs.py:864-888`): the existing method becomes a three-line
wrapper — `with self._db.transaction() as tx: return self.cancel_in(tx, job_id, reason=reason,
now=now)` — byte-identical behaviour for every existing caller. `cancel_in` runs on the caller's
transaction: `_lock` FOR UPDATE (`:297-303`, #5) → `_check_transition` through `_move`
(`:320-349`). The transition map refuses terminal states and **NEEDS_RECONCILIATION**
(`S/contracts/states.py:116`): a quarantined job is never cancelled — its operations still need
the authorised reconciliation path, and A1's `track_waits` keeps them blocking until settled
(AR-4). Amendment sweeps (A4 §7.3 step 3, §6 `cancel_season`) skip those rows.

**Lease revocation and the stale worker.** `_move` clears `lease_owner`, `lease_expires_at` and
`heartbeat_at` (`:333-338`), so a RUNNING holder loses its lease in the same commit that cancels
the job. The stale worker stops under the existing lease guard: its next `_holds_lease` check
(`:621-627`) fails because the row is no longer RUNNING — `lease_guard` (FOR SHARE, `:648`)
raises `Conflict("lease lost")`, and `finish` (`:677-679`) and `heartbeat` (`:605-606`) likewise.
Under A0's contract that Conflict is `LlmLeaseLost` semantics: the worker stops all guarded
writes and does not call `finish()` (A0 §5.1); its durable operation stays in flight. A provider
call already in flight cannot be recalled — that is exactly what reconciliation is for:

**External operations go to the authorised reconciliation path** (spec §7.4): `llm.subscription`
operations through A0 §5.3 (auto-reconciler or the audited operator command on
`resolve_reconciliation`), paid kinds through the existing paths (`resolve_reconciliation`
`S/core/jobs.py:752-862`; render's UNKNOWN handling `rendering/comfy_jobs.py:803-862`). Exposure
and receipts are retained — `cancel_in` touches no `provider_operations` row, no reservation, no
charge.

**LLM cancellation forwarding (A0 §5.4).** A0 extends `cancel()` so the cancel transaction sets
`llm_invocations.cancel_requested_at_ms` and emits `llm.cancel_requested` for in-flight
`llm.subscription` operations; A3's `cancel_in` extracts that into one private helper
(`_forward_llm_cancellation(tx, row)`) used by both entry points, so an amendment-driven cancel
requests the gateway cancel too — appended in the caller's transaction, posted by the outbox
consumer after commit. `CANCELLED` is still recorded on the operation only after the gateway
confirms (A0 §5.4); until then the job shows the cancelling state.

## 5. Per-queue workers

### 5.1 CLI and the process set

`api/worker.py` gains two flags; everything else about the entry point (migrations, OFFLINE_MOCK
guard `:70-72`, `--once`/`--janitor-only`, janitor cadence `:95-97`, SIGTERM handling) is
unchanged:

```
python -m microdrama.api.worker --queues production[,publication,community] [--name worker-production]
```

- `--queues` (CSV, default: all three in declaration order — today's behaviour,
  `S/pipeline/world.py:204-206`). Validated against `QueueName` (`S/contracts/enums.py:242-245`);
  an unknown name exits 2. The composed deployment is built with `QueueSlots` filtered to the
  chosen queues, so the idle computation (`api/worker.py:98`) follows the same set.
- `--name` (worker identity → `lease_owner` via `WorkerDeployment.name`,
  `S/workers/runtime.py:103-119`). Default `worker-<queues joined by '+'>`; names must be unique
  per process — two processes with one name would fight leases for the same identity.
- **The production process set** (spec §4; A6c runs it under `--composition production`): one
  process per lane — `--queues production`, `--queues publication`, `--queues community` — each
  with the lane's slot count from the composed deployment. `claim` is FOR UPDATE SKIP LOCKED
  (`S/core/jobs.py:500`, `:514`), so extra community processes scale safely.
- **A-T8's isolation proof:** today one process visits every queue in declaration order
  (`S/workers/runtime.py:185-197`), so a 60 s production handler delays the publication claim of
  the same cycle. Separate processes are structurally independent — the acceptance test
  (§9) measures a publication job completing while the production process sleeps.

### 5.2 The lane checklist (spec §4; phase A adds no lanes)

One checklist for every later phase adding a lane (`image`, `voice_intake`, `sfx`, `music` —
master §10.0):

1. **Queue SQL CHECKs** on jobs (`M/0001…sql:77`) and reservations (`M/0003…sql:71`): one guarded
   migration replacing each CHECK with a list that admits the old values (V1 rows unaffected);
   `QueueName` (`S/contracts/enums.py:242`) grows the value.
2. **`budget/policy.py` ownership**: `_OWNED_CATEGORIES` (`:35-39`) + `check_queue_may_reserve`
   (`:42-49`) gain the lane's category ownership; an unowned lane refuses to reserve.
3. **The worker process set**: the composed `QueueSlots` (`S/pipeline/world.py:201-211`) gains the
   lane, and the deployment runs one more per-queue process; `PROVIDER_BOUND_TYPES`
   (`S/workers/runtime.py:84-94`) binding if the lane's types are provider-bound.
4. **The generated contracts**: `JOB_SPECS` (`S/contracts/jobs.py:69`) queue values, v1/v3
   schemas + examples regeneration, drift check green.

## 6. The command table (A3 rows; A1 §6 columns)

`TrackService` (`S/core/v3_tracks.py`), human commands through `IdempotencyService.execute` with
A1's §5 preflight seam; AR-6 activation: these rows return `NOT_AVAILABLE` before A3 lands
(A-T4 already asserts that refusal), real behaviour from A3.

| Command | Actor | Scope / revision owner | Prerequisites | Writes | Jobs | Events | Replay identity |
|---|---|---|---|---|---|---|---|
| `cancel_season(season, expected_revision, reason)` | Operator (human session + CSRF) | season / `season_tracks.revision` | `require_workflow('v3')` (A1 §7); track not already cancelled; revision match (`StaleRevision` on mismatch) | `season_tracks.cancelled_at` (terminal, OQ-2); **every** `episode_tracks.cancelled_at` under the season (id order); `cancel_in` on every non-terminal V3 job in the season scope (id order, all tracks) | none enqueued | `track.cancelled` (season + per episode) + each job's own `job.cancelled` (from `_move`, `S/core/jobs.py:348`) | idempotency key |
| `cancel_episode(episode, expected_revision, reason)` | Operator (human session + CSRF) | episode / `episode_tracks.revision` | v3; track not cancelled; revision match | `episode_tracks.cancelled_at`; `cancel_in` on the episode's non-terminal V3 jobs (production + release); season-track jobs untouched | none | `track.cancelled` + `job.cancelled` per job | idempotency key |
| `rewind_for_amendment(scope, to, amendment_ref)` | **System — amendment coordinator only** (A4; no route in A3, internal API, test-world drives A3's tests) | season or episode / `content_revision` + `revision` | coordinator context (A4 Confirm's revalidated impact hash); `to` inside the master §12.6 backward closure for the scope | backward planning edge on the scope's track; `content_revision` bump; **fence the affected work**: `cancel_in` sweep of the scope's queued/waiting V3 jobs and queued continuations (id order) | none | `track.rewound`; `job.cancelled` per cancelled job | semantic `(scope, from, to, content_revision)` + `amendment_ref` |

Internal, not a command: the **admission self-fence** (§3.2, `claim`) — a system mechanism with no
actor. Both cancel commands are terminal (OQ-2 ruling: `cancelled_at`, surfaced as the CANCELLED
wait); the legacy `seasons.state` is never written for V3 (A1 §1). Money: nothing is released —
exposure and receipts stay until reconciliation (§4).

## 7. Lock audit (spec §6; A1 §9 hands over one open row)

The §6 table (A1 §9) governs. A1 §9 item 1 recorded the handed-over inversion: *"Worker
completion takes the job lock first (`lease_guard` `:648` FOR SHARE, `finish` `:677` FOR UPDATE),
while amendments take track → job. … this row hands A3 the required order (track before job)."*
**A3's resolution is structural: no A3 path ever takes a job lock and then a track lock.**
`finish`, `heartbeat`, `defer`, `requeue_expired` keep job-only lock sets; the paths that need
both take `fence()` (track SHARE) **first**. Transactions A3 adds or touches:

| Transaction | Locks in order | Verdict |
|---|---|---|
| V3 `enqueue` (incl. every continuation seam) | (#1 idempotency when command-driven) → **#2/#3 fence SHARE** → #5 job INSERT (`:389`) | conforms — track before job; inside an A1 decision transaction the SHARE is absorbed by the already-held #2 FOR UPDATE |
| `claim`, V3 admission arm | #5 job FOR UPDATE SKIP LOCKED (`:498`, `:511`) → plain track read (no lock) → status write | conforms — no track lock at admission (§3.2); correctness anchored at the mutation fence |
| Fenced submit | **#2/#3 fence SHARE** → #5 job SHARE (`lease_guard`, `:648`) → #6 `begin` INSERT | conforms — fence is the transaction's first lock |
| Fenced collector / acceptance | **#2/#3 fence SHARE** → #5 job SHARE (`lease_guard`) → #6 operation UPDATE (`record_result`) + asset/stale inserts | conforms |
| `resolve_reconciliation`, V3 rows | **#2/#3 fence SHARE** (added before the existing #5 `_lock` `:784`) → #5 job FOR UPDATE → status move | **order fixed** — track before job; competing test below |
| `cancel_in` (from `cancel()`) | #5 job FOR UPDATE (`:297`) → status write; no track lock, no operation lock | unchanged for V1; V3 callers arrive with #2/#3 already held (next rows) |
| `cancel_in` inside an amendment / `rewind_for_amendment` sweep | #2 (→ #3) FOR UPDATE already held → #5 jobs FOR UPDATE **id order** | conforms — the §6 order exactly |
| `cancel_season` / `cancel_episode` | #1 idempotency → #2 `season_tracks` FOR UPDATE → #3 `episode_tracks` id order → #5 jobs id order (`cancel_in`) → evidence/event inserts | conforms |
| `record_stale` | inside the caller's fenced transaction (already #2/#3 SHARE, #5 SHARE) → append-only insert | conforms |
| V1 paths (`enqueue`, `claim`, `finish`, `cancel`, `resolve_reconciliation` on `track IS NULL` rows; `api/worker.py` without `--queues`) | unchanged — every added branch is gated on the V3 work-scope columns / `workflow_version` | untouched |

Provider-operation advisory locks: the three `pg_try_advisory_xact_lock` sites are budget-side
(A2 §8, `S/budget/service.py:611`/`:729`/`:761`, #6-class before #7); A3 adds none, and its fenced
submit takes #2/#3 before #6, so no new class crossing exists.

**Competing-transaction tests** (two connections, real PostgreSQL; each proves one row above —
`X/integration/v3/test_lock_order.py`, extended by A3):

1. **enqueue vs amendment:** A enqueues a V3 job (holds fence SHARE); B's amendment (track FOR
   UPDATE) waits; A commits; B bumps `content_revision` and its sweep cancels the job → job row
   CANCELLED, `outcome.reason` from `cancel_in`. Reversed start: B holds the track; A's enqueue
   waits, then raises `StaleContentRevision` after B commits; no job row exists.
2. **fenced mutation vs amendment (the A-T12a core):** A's collector transaction takes the fence
   SHARE and writes; B's amendment waits; A commits at N; B's bump to N+1 and its closure see A's
   committed writes (invalidation computed under the FOR UPDATE granted after A's SHARE
   released). Then the reverse interleaving: B commits first; A's next fenced mutation
   quarantines. **No intermediate write ever lands as current at N+1.**
3. **`resolve_reconciliation` vs amendment:** A resolves SUCCEEDED (fence SHARE → job FOR UPDATE);
   B amends/cancels (track FOR UPDATE → job FOR UPDATE). Both orders complete without deadlock;
   if B won, A's resolution records `outcome.quarantined=true` + `stale_artifacts`.
4. **`cancel_in` vs a live worker:** A cancels (track → job → CANCELLED, lease cleared); the
   worker's next `lease_guard`/`finish`/`heartbeat` raises `Conflict`; the operation row and its
   reservation are untouched; `track_waits` keeps the operation blocking until reconciliation.
5. **claim vs amendment:** a stale QUEUED job claimed concurrently with a committing amendment →
   admission `CANCELLED`/`STALE_CONTENT`, never leased; a current job leases normally.

## 8. V1 unchanged

Every V1 path A3 touches, and how its behaviour and tests stay identical:

- **`JobService.cancel`** — wrapper over `cancel_in` in its own transaction; identical lock set,
  transition checks, events. Existing job tests (`X/unit/core/`, `X/contract/`) run unedited.
- **`JobService.enqueue`** — the fence branch executes only when `track` is set (A1 0031); V1
  callers pass none of the work-scope kwargs (all default NULL, A1 §2.4) and their payloads never
  carry the field; the 0035 CHECK passes trivially (`track IS NULL`). INSERT bytes and the
  semantic-key replay path (`:429-439`) unchanged.
- **`claim` / `finish` / `defer` / `heartbeat` / `lease_guard` / `requeue_expired` /
  `resolve_reconciliation`** — V3-only branches gated on the work-scope columns; V1 rows take
  byte-identical paths. `defer`'s `Deferred`/`refund_attempt` extension is A0's (A0 §5.2); A3
  adds no second variant (spec §4) and its tests assert consumption, not modification.
- **`api/worker.py`** — without `--queues`, today's loop, report, janitor cadence, OFFLINE_MOCK
  guard; the V1 `make pilot` and pipeline tests are unaffected.
- **Budget/queue surface** — `budget/policy.py`, the jobs/reservations queue CHECKs, `JOB_SPECS`:
  untouched (no lanes, §5.2). Quarantined money flows through the existing ledger paths.
- **Catalog/tests** — `EXPECTED_TABLES` grows (superset check); upgrade test (A-T16 A3 part)
  asserts a populated V1 database migrates through 0035 with every existing row and applied
  checksum unchanged; the catalog guard tests cover `stale_artifacts` automatically.

## 9. Test plan (A-T8, A-T12a, A-T18; real PostgreSQL; spec §11 negatives included)

All offline, ephemeral PostgreSQL via the existing conftest, real runtime/composition with fakes,
pytest `--basetemp` under the session scratchpad; `make check` + V1 `make pilot` stay green.

| ID | File (new unless noted) | Cases |
|---|---|---|
| A-T8 | `X/integration/v3/test_runtime_lanes.py` | **per-queue isolation:** two real worker subprocesses (`python -m microdrama.api.worker --queues production --name w-prod`, `--queues publication --name w-pub`) against the test database; a production handler sleeping 60 s (test-registered, fake) while a publication job is due at t₀ → the publication job completes ≪ 60 s; without `--queues` the loop serves all three queues (today's behaviour asserted); `--queues` validation (unknown name exits 2); duplicate `--name` refused; janitor sweeps from both processes are idempotent (SKIP LOCKED). **A0 runtime consumed:** a V3 job whose handler returns each translated signal — `Deferred("BUDGET")` → RETRY_WAIT + persisted `defer_reason` + attempt refunded only when the claim consumed it (`refund_attempt`/`consumed_attempt`, A0 §5.2); `WaitExternal` → WAITING_EXTERNAL; `LlmBlocked` → `Failed("LLM_BLOCKED")`; `REFUSED_PRELAUNCH` re-arm through `resubmit_allowed()`; the outcome union matches A0's extension exactly (no A3 variant) |
| A-T12a | `X/integration/v3/test_fence.py` (+ `X/integration/v3/test_lock_order.py` extended with §7's five competing tests) | **fence race:** amendment vs mutation under the locks in both orders (§7.2); **intermediate writes:** partial writes at N are all-or-nothing against the bump — nothing lands as current at N+1, and the amendment's closure sees committed N-writes; **season-scope work:** a season planning job fenced on `season_tracks`, an extension job on `season_extensions`, an episode job on `episode_tracks`; **stale results quarantined:** collector completes after the bump → `stale_artifacts` row (job, operation, artifact refs, expected vs actual), assets registered but NOT accepted/installed, no continuation enqueued, settlement + charges posted (money normal), reservation retained until settlement; **enqueue fence:** stale `expected` → `StaleContentRevision`, no job row; V1 enqueue without the field → unchanged; **admission:** stale QUEUED/RETRY_WAIT job → `CANCELLED`/`STALE_CONTENT` at claim, handler never runs; stale WAITING_EXTERNAL still leases and its result quarantines; **cancelled-operation reconciliation:** `cancel_in` mid-flight → lease revoked, worker `Conflict` on guard/finish, operation untouched → later SUCCEEDED through the authorised path (`resolve_reconciliation` / A0 auto-reconciler) → job SUCCEEDED `outcome.quarantined=true` when stale, money accounted, `track_waits` block cleared; **commands:** `cancel_season`/`cancel_episode` positive, foreign owner, service credential, missing CSRF, revision mismatch (`StaleRevision`), replay identity, episode-vs-season scope separation; `rewind_for_amendment` from a non-coordinator caller refused |
| A-T18 (V3-AT-20) | `X/integration/v3/test_paid_unit_recovery.py` | a **generic paid unit** through a test-registered V3 job type driving a fake `GenerationProvider` via `ProviderOperation` (reserve → `begin` → submit → poll → collect → settle). **Crash at each boundary, with at least one real process death:** a child worker process (own DB connection, claims under its own `--name`) dies via `os._exit(1)` — and in one case SIGKILL from the parent — at (1) after the intent/`begin` commit, before submit; (2) after the provider accepted, before `record_result(SUBMITTED)`; (3) after the result, before the receipt/settle; (4) after the receipt, before job finish. After each: the durable operation decides recovery — stable request identity (`client_token`, `M/0001…sql:187`) means the resumed path never blind-resubmits (the fake provider counts submits: exactly one per attempt); UNKNOWN without a recoverable external ID stays UNKNOWN for the operator with exposure held; no lease revival (`requeue_expired` semantics, `:706-750`); **cancel plus late success:** `cancel_in` mid-flight, the provider completes afterwards, reconciliation adopts, money accounted, quarantined when stale, no exposure release before settlement |
| A-T16 (A3 part) | `X/integration/persistence/test_migrations.py` (extend; `:122` pattern) | 0035 applies on a populated V1 database at the 0034 head: every existing row unchanged, applied 0001–0034 checksums unchanged, the fence CHECK satisfied on all V1 rows (`track IS NULL`), `stale_artifacts` in `EXPECTED_TABLES` and covered by the catalog guard tests; fresh-create tail asserts `0035` |
| contracts | `X/contract/contracts/test_v3_runtime_contracts.py` | `V3ScopedStepInput` example + schema generation under `schemas/v3`; `track.cancelled` / `track.rewound` payload schemas registered and valid (AC-19 naming); generated-contract drift check green |

## 10. Open questions

| # | Question | Recommendation |
|---|----------|----------------|
| OQ-1 | Episode jobs fence on the episode track only; a season-scope bump alone does not stale them. Correct only if A4's closure bumps every episode track whose work an amendment invalidates. | Keep the single resolved fence (matches A1's `track_waits` `stale` CTE; scoped invalidation preserves unrelated work, AR-3/AR-4). Record the A4 obligation in its note; A-T12b tests it from the coordinator side. |
| OQ-2 | Admission uses a plain read, not a SHARE lock, so a job admitted at N may start a handler that goes stale mid-run. | Keep: correctness is anchored at the mutation fence (A-T12a race test); a SHARE at claim would order #5 before #2/3 and deadlock against amendments — the inversion the spec forbids. |
| OQ-3 | Terminal status for a stale job whose reconciliation adopted a successful result: `SUCCEEDED` with `outcome.quarantined=true`, or `CANCELLED`? | `SUCCEEDED` + `quarantined` + `stale_artifacts`: the operation genuinely completed and its money is accounted; `track_waits` already ignores stale rows, so neither choice blocks anything. |
| OQ-4 | `rewind_for_amendment` exposure in A3: it is the A4 coordinator's primitive with no production caller yet. | Internal API only — no route, no command surface; A3's tests drive it through the test world. A1 §6's "only through the amendment coordinator" is enforced by refusing every non-coordinator caller. |
| OQ-5 | Does `cancel_season` also mark every `episode_tracks.cancelled_at` under the season? | Yes (recommended reading of "terminal" + OQ-2's CANCELLED wait): a cancelled season has no live episode work; the episode marks ride in the same transaction (§6 order #3). |
| OQ-6 | Worker identity uniqueness (`lease_owner`) across per-queue processes. | Explicit `--name` with default `worker-<queues joined>`; A6c's compose sets distinct names. Two processes with one name mis-share leases — validated at startup (refuse a duplicate live `lease_owner` heartbeat? no: names are not registered — document and assert distinct names in A6c's composition tests). |
| OQ-7 | `stale_artifacts` refs as jsonb vs a typed child table. | jsonb refs + the integer-number guard now (evidence is read by scope, not joined per-artifact); promote to a typed table in a later migration only if A5 needs per-artifact joins. Applied 0035 bytes are never edited either way. |
| OQ-8 | Should `api/worker.py` gain `--composition` in A3 (spec §9.2 assigns production selection to A6c)? | No: A3 ships `--queues`/`--name` only; the OFFLINE_MOCK guard stays. A6c adds composition selection and the fail-closed dependency checks on top. |

— end of note —
