# A6b design note: the V3 scheduler — singleton, durable periods, calendar triggers

**Version 1.1, 13 Nov 2026. Author: GLM (design note only; no code).** Revision 1 applies the
round-1 critique [codex-a6b-note-critique.md](codex-a6b-note-critique.md) (verdict REWORK;
N6-1..6 BLOCKING, N6-7..12 SHOULD-FIX) per [a6b-critique-rulings.md](a6b-critique-rulings.md)
— every ruled finding ACCEPTED, replacement wording binding. §11 maps each finding to its
section. Requirements: [phase-A-spec.md](phase-A-spec.md) v0.3 §0, §1, §6, §9.1, §9.2
(scheduler startup only), §10 (A6b row), §11 (A-T14); binding wording AC-20
([codex-a-critique.md](codex-a-critique.md)) and **AR-5**
([codex-a-recritique.md](codex-a-recritique.md)); master [SPEC-v3.md](SPEC-v3.md) v0.4.6 §1,
§2.2, §3.3, §9.4 (scheduler sections unchanged since v0.4.4); [A1-design-note.md](A1-design-note.md)
v1.2 §1 (migrations 0028–0031), §7, §9; [phase-A0-spec.md](phase-A0-spec.md) v0.4 §5.3 (the
two-minute LLM reconciler). Facts re-verified on `feat/microdrama-m0-m4` @ `7427100` (code tree
unchanged since `1df41d7`; migration tail **0025**; the advisory-lock inventory re-audited for
§3/§8). `S/` = `microdrama/src/microdrama/`, `M/` = `microdrama/migrations/`, `X/` =
`microdrama/tests/`.

**Scope:** A6b changes scheduler *behaviour* only — the singleton tick, durable firing periods and
effect intents, calendar triggers, catch-up, the two-minute LLM reconciliation trigger, and the
metric definitions. Production composition selection, role dependencies and qualifications are
**A6c** (spec §10; AC-21). A6b keeps `scheduling/__main__.py` building the offline world exactly
as today (`S/scheduling/__main__.py:40`).

---

## 1. Migration allocation

One migration, one purpose; its number is assigned at build time after re-auditing the tail (A1
allocated 0028–0031; A2–A6a take the numbers in between; spec §10). **Applied migration bytes are
never edited** — the migrator hashes file bytes and rejects changed checksums (`S/persistence/migrate.py:45`,
`:51`).

| # | File | Purpose |
|---|------|---------|
| A6b-1 | `A6b-1_v3_scheduler_periods.sql` | `scheduler_ticks`, `scheduler_firings` (the durable `(trigger, period_key)` identity, spec §9.1.2), `scheduler_effect_intents` — all guarded |

No other migration. The one-time `schedule_state` cutover (§5) is **runtime** logic riding with
the package — buckets are registry-derived (Python knows the intervals; SQL does not) — and it
writes no `schedule_state` row. Catalog updates (`EXPECTED_TABLES`,
`X/integration/persistence/test_migrations.py`) are code/test changes riding with the package
(A-T16 pattern; the catalog guard tests `X/integration/persistence/test_schema_catalog.py:22-37`
then cover the three new tables automatically, TRUNCATE `:57` and integer-numbers `:65` included).

## 2. Guarded DDL

Guard pattern per `M/0017_schedule_state.sql:11-18` (the table this replaces as the firing source
of truth): `md_immutable_columns` for identity columns, `md_forbid_mutation` on DELETE and TRUNCATE,
`md_forbid_non_integer_numbers` on INSERT OR UPDATE.

```sql
-- One row per executed tick (ownership skips write nothing; §3). Health reads this (§6).
CREATE TABLE scheduler_ticks (
  id             uuid PRIMARY KEY,
  schema_version text NOT NULL DEFAULT '1.0',
  started_at     timestamptz NOT NULL,
  finished_at    timestamptz,
  host           text NOT NULL CHECK (host ~ '^[a-z0-9][a-z0-9._\-]{0,80}$'),
  pid            integer NOT NULL CHECK (pid > 0),
  status         text NOT NULL CHECK (status IN ('RUNNING','SUCCEEDED','FAILED','ABORTED_LOST_OWNERSHIP')),
  fired          jsonb NOT NULL DEFAULT '[]'::jsonb,   -- trigger ids fired this tick
  errors         jsonb NOT NULL DEFAULT '[]'::jsonb,   -- per-trigger AND per-sweep-item errors
  report         jsonb                                   -- FireReport.as_dict() (S/scheduling/service.py:47)
);
CREATE TRIGGER scheduler_ticks_identity_immutable BEFORE UPDATE ON scheduler_ticks
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('id','started_at','host','pid');
CREATE TRIGGER scheduler_ticks_no_delete BEFORE DELETE ON scheduler_ticks
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER scheduler_ticks_no_truncate BEFORE TRUNCATE ON scheduler_ticks
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER scheduler_ticks_integer_numbers BEFORE INSERT OR UPDATE ON scheduler_ticks
  FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers();

-- The durable period identity (spec §9.1.2). Append-only: a claimed period is never rewritten.
-- period_key stores the RAW period token (§5): a bucket integer for interval triggers, the
-- scheduled local date YYYY-MM-DD for calendar triggers. The sched:{id}: prefix stays in job
-- semantic keys only (N6-3).
CREATE TABLE scheduler_firings (
  id             uuid PRIMARY KEY,
  schema_version text NOT NULL DEFAULT '1.0',
  trigger_id     text NOT NULL CHECK (trigger_id ~ '^[a-z0-9][a-z0-9._\-]{1,80}$'),
  trigger_kind   text NOT NULL CHECK (trigger_kind IN ('interval','calendar')),
  period_key     text NOT NULL CHECK (period_key ~ '^([0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]+)$'),
  period_start   timestamptz NOT NULL,                  -- bucket start / local midnight (§5)
  fired_at       timestamptz NOT NULL,
  tick_id        uuid NOT NULL REFERENCES scheduler_ticks(id),
  effect_mode    text NOT NULL CHECK (effect_mode IN ('ATOMIC','INTENTS','CUTOVER')),
  UNIQUE (trigger_id, period_key)
);
CREATE TRIGGER scheduler_firings_identity_immutable BEFORE UPDATE ON scheduler_firings
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns(
    'id','trigger_id','trigger_kind','period_key','period_start','fired_at','tick_id','effect_mode');
CREATE TRIGGER scheduler_firings_no_delete BEFORE DELETE ON scheduler_firings
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER scheduler_firings_no_truncate BEFORE TRUNCATE ON scheduler_firings
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER scheduler_firings_integer_numbers BEFORE INSERT OR UPDATE ON scheduler_firings
  FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers();

-- Durable effect intents for multi-transaction direct actions (§4). State is the only
-- mutable part: PENDING -> COMPLETED | FAILED | SUPERSEDED. Never deleted.
CREATE TABLE scheduler_effect_intents (
  id             uuid PRIMARY KEY,
  schema_version text NOT NULL DEFAULT '1.0',
  trigger_id     text NOT NULL CHECK (trigger_id ~ '^[a-z0-9][a-z0-9._\-]{1,80}$'),
  period_key     text NOT NULL,
  effect         text NOT NULL CHECK (effect ~ '^[a-z][a-z0-9_]{2,60}$'),  -- open pattern: new
                                                                -- effects arrive per phase (§4)
  state          text NOT NULL CHECK (state IN ('PENDING','COMPLETED','SUPERSEDED','FAILED')),
  failure_kind   text CHECK (failure_kind IN ('RETRYABLE','TERMINAL')),   -- set when FAILED (§4)
  started_at     timestamptz NOT NULL,
  finished_at    timestamptz,
  tick_id        uuid NOT NULL REFERENCES scheduler_ticks(id),
  summary        jsonb,
  UNIQUE (trigger_id, period_key, effect)
);
CREATE TRIGGER scheduler_effect_intents_identity_immutable BEFORE UPDATE ON scheduler_effect_intents
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns(
    'id','trigger_id','period_key','effect','started_at','tick_id');
CREATE TRIGGER scheduler_effect_intents_no_delete BEFORE DELETE ON scheduler_effect_intents
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER scheduler_effect_intents_no_truncate BEFORE TRUNCATE ON scheduler_effect_intents
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER scheduler_effect_intents_integer_numbers BEFORE INSERT OR UPDATE ON scheduler_effect_intents
  FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers();
CREATE INDEX scheduler_effect_intents_pending ON scheduler_effect_intents (trigger_id, effect)
  WHERE state = 'PENDING';
```

`effect` uses an open shape CHECK, not a closed enum: phase B+ schedules add effects without a
migration per phase. `effect_mode = 'CUTOVER'` exists only for the provenance rows §5 writes —
a period claimed by the cutover, never by an executed effect. `scheduler_firings` is fully
immutable — a firing is a fact; corrections are new rows. **`schedule_state` (M/0017) is retired
as the source of truth by the one-time cutover (§5): after it completes, the new fire path never
reads or writes the table again (OQ-1); the table, its rows and its guards remain untouched
history.** Its only other reader today is the contract test
(`X/contract/pipeline/test_scheduling_contract.py:32`), which swaps that state-source read to
`scheduler_firings` with **identical assertion values** — no timing or eligibility assertion
changes anywhere (N6-4; `X/unit/pipeline/test_scheduling_registry.py` stays byte-identical).

## 3. The singleton (AR-5)

**Key — the two-integer advisory namespace (N6-7).** The single-bigint advisory key space is
crowded and cannot be partitioned by convention: every `hashtextextended` caller hashes to the
**full 64-bit space** from a small seed, so a full-width hash can equal *any* fixed constant —
different seeds do not make disjoint namespaces. The two-key form
`pg_try_advisory_lock(key1 int, key2 int)` is a **separate key space by construction**
([PostgreSQL advisory-lock functions](https://www.postgresql.org/docs/18/functions-admin.html#FUNCTIONS-ADVISORY-LOCKS));
in `pg_locks` the two-key form is encoded as `classid = key1`, `objid = key2`, `objsubid = 2`,
while the bigint form splits into 32-bit halves with `objsubid = 1`
([pg_locks](https://www.postgresql.org/docs/18/view-pg-locks.html)). The scheduler reserves one
key there:

```python
_SCHEDULER_LOCK_KEY = (0x6D645F73, 0x63686564)  # "md_s" + "ched" = "md_sched" (two-int form)
```

**Complete lock inventory** (re-audited @ `7427100`; the §8 audit references this table):

| Key | Form | Owner |
|---|---|---|
| `(0x6D645F73, 0x63686564)` | two-int, session-level, dedicated connection | **scheduler singleton (A6b)** |
| `0x6D6472616D61` `"mdrama"` | fixed bigint, transaction-scoped | migrator (`S/persistence/migrate.py:25`, `:86`) |
| `0x6D645F6F7574` `"md_out"` | fixed bigint, transaction-scoped | outbox dispatcher (`S/core/events.py:171-172`, `:208`) |
| `sha256("microdrama:first-boot-seed")[:8]` signed | fixed bigint, first-boot mutual exclusion | `FIRST_BOOT_SEED_LOCK_KEY` (`S/pipeline/world.py:102-105`, DB-10) |
| `hashtextextended(%, 0)` | full-width hash, transaction-scoped | provider-operation arbitration (`S/core/provider_ops.py:121-124`), intake claim (`S/review/intake.py:459`), story v2 store (`S/story/v2_store.py:65`) |
| `hashtextextended(%, 451045..451049)` | full-width hash, transaction-scoped | budget serialisation (`S/budget/billing.py:256`, `:297`; `S/budget/service.py:611`, `:729`, `:761`) |
| `hashtextextended(%, 451050)` | full-width hash, transaction-scoped | preflight evidence (`S/rendering/keyframe_preflight.py:74`, `:1118`) **and** billing (`S/budget/billing.py:496`) — one seed, two callers, disjoint inputs: the concrete demonstration that seeds do not partition the bigint space |

The scheduler never takes any lock in the rows below its own. A fixed two-int constant is
deterministic across processes and restarts and readable in `pg_locks` when diagnosing a stuck
holder.

**Acquisition — a new `Database` helper beside the existing precedent** (`advisory_lock`,
`S/persistence/db.py:228-258`, already opens a *dedicated* short-lived connection —
`psycopg.connect(self.dsn, autocommit=True)` at `:243` — unlocks in `finally` at `:256-257`,
closes at `:258`):

```python
@contextmanager
def try_advisory_lock(self, key1: int, key2: int) -> Iterator[TickOwnership]:
    """pg_try_advisory_lock(key1, key2) on a dedicated connection; yields an ownership
    handle exposing acquisition state and still_held(). Never blocks. Released in
    finally only if acquired; the connection is closed even if unlock fails."""
```

- **Dedicated connection, outside the pool** — for the same reason the existing helper gives: work
  transactions keep the whole pool (`S/persistence/db.py:231-233`). One connection per tick: opened
  at tick start, closed at tick end.
- `TickOwnership` (not `Iterator[bool]` — N6-7: a boolean supplies no handle) carries
  `acquired: bool` and `still_held() -> bool`; injectable for tests (§9). A raised connection
  error inside `still_held()` counts as False.
- `SELECT pg_try_advisory_lock(%s, %s)` — **not acquired → skip the tick**: return immediately,
  write nothing (OQ-3; a skip neither refreshes nor overrides health, §6). Never
  `pg_advisory_lock`, never a timeout — `try` cannot block (AR-5's exact objection to the
  blocking form).
- `finally`: `SELECT pg_advisory_unlock(%s, %s)` **only if acquired**, then close — release cannot
  be skipped on any exception path, and **the connection is closed even if the unlock call fails**
  (a dying connection releases the session lock anyway, next bullet).
- **A crash releases the lock**: the session ends with the TCP connection and PostgreSQL drops
  session-level advisory locks — the documented behaviour of the existing helper
  (`S/persistence/db.py:233`). No code runs; no stale lock survives a dead process.

**Lost ownership.** The lock can only be lost if the dedicated connection dies (including an
administrator terminating its backend) or an administrator forces the lock. Detection is a check
executed *on the dedicated connection itself* — success proves the session is alive, and the row
proves the lock is still held **in the same key form** this tick acquired (two-int encoding,
exclusive mode, granted, this backend; N6-7):

```sql
SELECT EXISTS (
  SELECT 1 FROM pg_locks
  WHERE locktype = 'advisory'
    AND classid = %s AND objid = %s AND objsubid = 2
    AND mode = 'ExclusiveLock' AND granted
    AND pid = pg_backend_pid())
```

**Ownership is checked before each independently started action within the whole tick (N6-1,
OQ-6):** before starting each due trigger, and — inside every multi-transaction sweep — before
each lease/pod action, each shot dispatch, each janitor item and each reconciliation action. Loss
**stops subsequent actions**: no further trigger fires, no sweep starts, and the sweep in progress
starts nothing new; the tick ends with status `ABORTED_LOST_OWNERSHIP`, recording what already
fired. Only an operation **already started** may finish — through its canonical recovery path
(§4), never by silently continuing as owner. **Recovered dispatch reuses the original
operation/attempt identity** (N6-1): a re-entered dispatch resolves to the attempt identity the
started dispatch minted — the `(episode, shot, attempt n)` key bound to its provider operation —
and never recomputes `attempts_used + 1` from a racy read (`S/scheduling/service.py:758-765` is
exactly the double-paid-attempt window this closes; with the singleton plus per-action checks,
overlapping dispatchers cannot both mint the next attempt).

**The tick** — `TriggerScheduler.fire(*, now=None, only=None)` keeps its signature and return type
(`S/scheduling/service.py:113`, `:39-54`):

1. `with db.try_advisory_lock(*_SCHEDULER_LOCK_KEY) as ownership:` —
   `not ownership.acquired` → return an empty report marked skipped; **no DB writes** (OQ-3).
2. One transaction inserts the `scheduler_ticks` row (`RUNNING`) **and closes orphaned `RUNNING`
   rows from dead holders (N6-11): under the singleton, any `RUNNING` row whose tick is not this
   one has no live holder by construction** — it is set `ABORTED_LOST_OWNERSHIP` with
   `finished_at = now` and an error entry naming it.
3. Read-only: per trigger, the **durable watermark** — its latest claimed period and that row's
   `fired_at` — from `scheduler_firings`; compute due candidates (§5).
4. For each due trigger in catalog order (today's declaration order, `S/scheduling/service.py:118`):
   `still_held()` or abort; then fire per its mode (§4). One trigger's failure still never kills
   the tick (`S/scheduling/service.py:126-133`) — but it is recorded on the tick row and **counts
   against success** (step 5). Sweep-item failures (a janitor item, one shot's dispatch, one
   reconcile action) propagate into `errors` individually, never buried in an action summary
   (N6-11).
5. Close the tick with an explicit success definition (N6-11): **`SUCCEEDED` iff the tick ran to
   completion with no trigger failure and no sweep-item failure.** Any trigger failure, any
   sweep-item failure, or a tick-level exception → `FAILED`, with every failure in `errors`. A
   tick in which every trigger fails is therefore never successful. `report` =
   `FireReport.as_dict()` (`S/scheduling/service.py:47-54`).
6. `finally` releases the lock; the connection closes even if unlock fails (§3 acquisition
   helper).

The `only=` filter stays (test seam, `S/scheduling/service.py:119-120`). `__main__.py` stays
one-shot per host-timer invocation (`S/scheduling/__main__.py:3-5`, `:40-42`); the lock lives and
dies within one `fire()` call. **Startup dependencies (spec §9.2, scheduler role only):** the
database reachable and migrations at the expected head — exactly what `__main__` already does
(`migrate(dsn)` at `S/scheduling/__main__.py:31`) — and nothing else: no object store, no gateway,
and **never the scheduler's own freshness** (spec §9.2.2). Role-specific production dependencies
and fail-closed exits are A6c's.

## 4. Periods and effects

**Claim rule (every trigger):** the firing transaction inserts the `scheduler_firings` row with
`INSERT … ON CONFLICT (trigger_id, period_key) DO NOTHING RETURNING id` — `period_key` is the raw
token (§5). **No row returned → the period is already claimed → skip** (a crash-restart race after
lock release settles here: the loser skips; the winner's effects are already committed).
`load_last_fired`/`record_fired` (`S/scheduling/service.py:57-69`) leave the fire path after the
§5 cutover retires `schedule_state` (OQ-1).

| Trigger (`registry` id) | Kind | Mode | Committed **with** the firing row |
|---|---|---|---|
| `w01-research` … `w11-analytics` (all enqueue schedules: `w01`, `w02`, `w03-write`, `w04`, `w06`, `w07`, `w09-publish-submit`, `w09-publish-poll`, `w11`) | interval | **ATOMIC** | The handler's selection runs read-only (as today, e.g. `S/scheduling/service.py:549`), then **one transaction**: firing claim + every job enqueue of the period (`world.jobs.enqueue(tx, …)`; today's per-enqueue transactions at `S/scheduling/service.py:151` collapse into this one). **Job semantic keys keep today's exact form `sched:{schedule_id}:{bucket}:…`** (N6-3) — `ScheduleCatalog.period_key` continues to return the prefixed key for enqueueing (`:56-59`, used by `_period` `:163-165`, e.g. publish-submit/poll keys at `:624`, `:667`), so different triggers' keys over the same bucket stay namespaced and never `IdempotencyConflict`; the firing row alone stores the raw token. |
| `w03-episode-cadence` | interval | **ATOMIC** | Firing claim + the direct episode INSERT(s) — the insert at `S/scheduling/service.py:219-238` moves **into** the firing transaction, A1's V3 refusal guard inside it (A1 §7 row). Single transaction, so the cadence effect is atomic with its period identity. The V1 cadence inserts **episodes only — no V3 tracks** (N6-10); `episode_tracks` creation is V3 `create_v3_episodes` (A1 §3, activated in A2). |
| `w05-render-dispatch` | interval | **INTENTS** | Claim + intent `render_dispatch`, committed first; then the existing multi-transaction flow runs (read-only manifest scan `:720-732`, pod-lease claim `:747-753`, `ensure_pod` `:755`, per-shot router dispatch), with `still_held()` before each independently started action (§3). |
| `w05-render-poll` | interval | **INTENTS** | Claim + intent `render_poll`; then the existing reconciliation flow, ownership-checked per action. |
| `w12-workers-janitor` | interval | **INTENTS** | Claim + intent `workers_janitor_sweep`; then `WorkersJanitor.sweep` — each step its own transaction (`S/workers/janitor.py:91-133`; `requeue_expired` `S/core/jobs.py:706`, `expire_stale`, telemetry read, evidence write). |
| `w12-gpu-janitor` | interval | **INTENTS** | Claim + intent `gpu_janitor_sweep`; then `Janitor.sweep` — per-lease cleans and evidence events, each its own transaction (`S/rendering/janitor.py:183-193`, `:236-269`, `:166-179`), evidence deduplicated by deterministic `event_id` (§4). |
| `llm-reconciler` (new, N6-6) | interval (120 s, bucket eligibility) | **INTENTS** | Claim + intent `llm_reconcile`; then `LlmReconciler.reconcile_due()` (A0 §5.3; scratch A0 ships `S/llm/reconciler.py:76`, `:126`) under A0's audited contract: RESUME under **its own worker identity and lease** (A0S-1), never requeueing a job whose linked operation is in flight, reconciling only through legal `ALLOWED_MOVES` (A0S-2), `UNKNOWN`/vanished work left to the operator (A0's boundary table), and **A3's fence validating `expected_content_revision` before any adopted result is installed** (spec §7.1 names reconciliation adoption). Cleanup and accounting for stale work stay recoverable through the ordinary job/operation paths. Each per-job reconcile action is independently started → ownership-checked (§3). |
| `v3-daily-summary` (new) | calendar 09:00 | **ATOMIC** | Firing claim + `summary.daily` event (and `buffer.low` / `slo.below` when breaching) via `append_event` **on the same caller transaction** (`S/core/events.py:69-144`) — event emission is a database effect, so it is atomic with the period identity. Payloads are A6a's registered schemas, integer-only (§6; N6-5). |

**Intent lifecycle (N6-2).** `PENDING` when claimed → `COMPLETED` (sweep finished; counts in
`summary`) / `FAILED` (sweep raised; `failure_kind` records **RETRYABLE** — the canonical recovery
path can make progress unattended next period — or **TERMINAL** — an operator decision is
required, e.g. an `UNKNOWN` provider operation; terminal intents are never blindly re-run, they
surface in tick errors and, where a job backs them, as `BLOCKED (reconcile)` in `track_waits`) /
`SUPERSEDED` — written **only when a successor period's sweep has durably covered the unfinished
work**: the recurring recovery pass marks the earlier intent `SUPERSEDED` (`summary.covered_by` =
the covering period) after the obligation is actually finished, never at claim time. A stale
intent is superseded, never deleted, never re-run as such.

**Recoverability is independent of any firing marker (AR-5, N6-2).** Every INTENTS effect names
its canonical recovery identity and path at each interruption boundary:

| Effect | Canonical recovery identity | Path at each boundary | Failure kinds |
|---|---|---|---|
| `render_dispatch` | pod-lease semantic key `pod.lease:{episode}:render` (`S/scheduling/service.py:750`); per-shot attempt identity `(episode, shot, attempt n)` bound to its provider operation | killed before dispatch → the next sweep rediscovers un-dispatched shots (`attempts_used`, `:738`) and re-enters **at the original attempt identity** (§3, N6-1); killed mid-dispatch → the provider operation's request/recovery identity (A0 §5.3, A-T18 discipline); after completion → no-op | pod/gateway transient → RETRYABLE; `UNKNOWN` operation → TERMINAL (operator) |
| `render_poll` | the polled provider operations and job states | killed anywhere → next period re-polls from the operation's current state; no replay of missed periods needed (coalesced) | transient → RETRYABLE; `UNKNOWN` → TERMINAL |
| `workers_janitor_sweep` | durable job rows (expired claims/holds) re-found by `requeue_expired` (`S/core/jobs.py:706`) | each step its own transaction; killed mid-sweep → next period re-scans and finishes | RETRYABLE (durable rows); none terminal |
| `gpu_janitor_sweep` | non-terminal leases re-found by the candidate query (`S/rendering/janitor.py:236-246`); **evidence events keyed by a deterministic `event_id = uuid5(NAMESPACE, f"janitor:{subject}:{action}")` passed to `append_event`** | killed mid-clean → next sweep re-finds the lease; a replayed evidence append is a **primary-key no-op** (`domain_events.event_id` is the PK, `M/0001:116`) — today `_evidence` omits `event_id` so `append_event` mints a fresh UUID (`S/core/events.py:87`) and the `uuid5` aggregate at `S/rendering/janitor.py:169` only keys the sequence: **aggregate identity alone is not effect deduplication** (N6-2) | transient → RETRYABLE; `UNKNOWN` provider state → TERMINAL (operator) |
| `llm_reconcile` | the job's `NEEDS_RECONCILIATION` state + its linked `llm.subscription` operation id | killed anywhere → the job (or its in-flight operation) is exactly as A0 left it; the next 2-minute period re-finds it (A0S-1: never requeued while in flight) | gateway unreachable → RETRYABLE (no change, next tick); `UNKNOWN`/vanished → TERMINAL (operator, A0's table) |

So a killed sweep leaves at most unfinished-but-idempotent work: the recurring sweep **coalesces
recovery** — one re-scan of unfinished obligations — **without replaying every missed period**
(N6-2), and **crash replay of a direct action is a no-op** (A-T14). The marker exists for
observability and the supersede bookkeeping, not for recovery correctness.

**Command/effect contract (N6-10).** Every trigger's effect, as rows:

| Effect | Actor / scope owner | Allowed states & prerequisites | Transaction & locks | Events / jobs | Replay result |
|---|---|---|---|---|---|
| V1 enqueues (`w01`…`w11`) | scheduler system principal; scope = V1 candidate selection (read-only) | due per eligibility + unclaimed raw period + watermark pass (§5) | **one** ATOMIC firing tx: claim first, then every enqueue on the **caller's transaction** (no handler opens its own inside it); §8 #3 | jobs with keys `sched:{schedule_id}:{bucket}:…`, byte-identical to today | `ON CONFLICT` → period already claimed, nothing re-enqueued |
| `w03` cadence insert | scheduler; scope = V1 seasons only (refusal guard inside the tx, A1 §7) | V1 candidate present; interval elapsed | same ATOMIC firing tx | episode INSERTs only (no V3 tracks) | claimed period → no-op |
| INTENTS sweeps | scheduler; scope = the components' own (leases, jobs, providers) | claim + intent committed first; each subsequent action independently started and ownership-checked (§3) | claim tx (§8 #4), then the components' existing transactions, unchanged (§8 #5) | janitor evidence with deterministic `event_id` | canonical recovery only (table above) |
| `llm_reconcile` | A0's reconciler identity (own worker, own lease) | jobs in `NEEDS_RECONCILIATION` blocked only by `llm.subscription` (A0 §5.3) | A0's audited RESUME/adoption transactions (§8 #6) | no direct events; job/operation transitions per A0 | next period re-finds; in-flight never requeued |
| `v3-daily-summary` | scheduler; scope = all V3 seasons (metrics §6) | calendar candidate due + watermark + activation gating (§6) | one ATOMIC firing tx: claim → `append_event` on the caller tx (§8 #7) | `summary.daily` (+ `buffer.low`/`slo.below` breaching only), A6a schemas, integer payloads | claimed period → no second emission |

Binding rows for everything above (N6-10): the caller's transaction is passed **through** the
atomic handlers (`enqueue`, `append_event`) — the summary and enqueue paths never open their own
transaction inside the firing transaction; **any V3 enqueue or adoption path (phase B+ selectors
and the reconciler's adoption included) routes through A3's fence — `expected_content_revision`
validated under the track SHARE lock **before** job locks — and STORY/CAST authority (gate
activations) is never bypassed by scheduler-driven work**; the V1 cadence inserts no V3 tracks.
**Event emission is transactional only**: `append_event` inside the firing transaction, delivery
exclusively through A6a's dispatcher → sender chain (no inline dispatch); A6a's payload schemas
are pinned against this note **before A6b code starts** (OQ-5 — integer representations, scope,
timestamps, deep links).

## 5. Calendar triggers, eligibility and the cutover

```python
@dataclass(frozen=True)
class CalendarTrigger:
    local_time: time                  # the schedule's wall-clock firing time
    tz: str = "Asia/Bangkok"          # ICT, UTC+07:00 — no DST transitions in the IANA data
```

- **The raw period token vs the enqueue-key prefix (N6-3).** `scheduler_firings.period_key`
  stores the **raw token**; `ScheduleCatalog.period_key()` **keeps returning
  `sched:{schedule_id}:{token}`** for job semantic keys (existing callers, e.g.
  `S/scheduling/service.py:624`, `:667`, keep byte-identical keys); the catalog gains
  `raw_period(schedule, now) -> str` for the firing row. **Every new key includes its trigger
  namespace** — the prefix is mandatory on every enqueue key, new triggers included.
- **Candidate derivation (N6-8).** All period math uses the **injected, aware `now`** (the
  `fire(now=…)` parameter) — including SQL: metric queries take parameterised timestamps, never
  `now()`. The calendar candidate is the **latest period whose scheduled instant ≤ injected now**;
  **its `period_key` is that candidate's scheduled local date** — before 09:00 the candidate is
  *yesterday's* date. The date changes at midnight; the latest-due summary period advances at
  09:00. Scheduled instant = `datetime.combine(local_date, local_time, ZoneInfo(tz))` as UTC —
  09:00 Bangkok = 02:00 UTC. All persisted instants remain `timestamptz` (UTC), per the event
  contract's `UtcDateTime` (`S/contracts/events.py:27`); no naive datetimes anywhere. Bangkok is
  DST-free, so local dates map stably onto instants.
- **Execution time ≠ claimed date (N6-8).** `fired_at` records when the tick ran; the payload's
  `date` is the **claimed summary date** (the period's local date), and its reporting day is the
  claimed date's previous calendar day — a catch-up run on Wednesday 10:00 for Tuesday's period
  reports Monday's releases, bounded measurement windows computed **from the claimed date**, never
  from execution time.
- **Watermark (N6-8).** Per trigger, the durable watermark is its latest claimed period. **A
  candidate older than the watermark never fires** — clock rollback cannot resurrect an older
  period "skipped forever", for either kind: calendar candidates compare as dates, interval
  candidates as bucket integers.
- **Due rule:** fire iff the candidate period passes eligibility, is unclaimed and is not older
  than the watermark. **At most one firing per trigger per tick, and at most the latest missed
  period is ever fired** (spec §9.1.4): after a first run or any downtime, older missed periods
  are skipped forever — there is no backlog storm. Down Mon–Wed, resumed Wed 10:00 Bangkok →
  fires **Wed** (09:00 passed); resumed Wed 08:00 → fires **Tue** (the latest missed); Mon never
  replays. First run ever (no watermark) → fires the current latest-due period once. **A6b
  catch-up is never permission to publish missed or held slots** — release slots and teaser
  scheduling are phase F obligations (teaser date = the premiere's Bangkok date minus three days,
  under approved calendar/content authority; slot evenings run 19:00 Bangkok = 12:00 UTC).
- **Eligibility (N6-4).** **V1 schedules keep exactly today's elapsed-interval eligibility** —
  due iff a full interval has elapsed since the last durable firing — now computed from
  `scheduler_firings.fired_at` (the cutover below transfers it exactly) instead of
  `schedule_state`. **Explicit bucket eligibility is introduced for new schedules only**: an
  interval trigger declares `eligibility='elapsed'` (the default — every existing construction
  and test keeps its behaviour) or `'bucket'` (due iff the current bucket is unclaimed);
  `v3-daily-summary` is calendar; `llm-reconciler` is bucket-eligible (a 120 s bucket bounds its
  own cadence). The pinned V1 timing tests are **unchanged** — `X/unit/pipeline/test_scheduling_registry.py:34-41`
  (elapsed eligibility, refusal of backward-clock firing) stays byte-identical, and the contract
  test's assertion values are untouched (§2).
- **One-time cutover from `schedule_state` (N6-4, OQ-1).** Ignoring `schedule_state` at upgrade
  would replay every period immediately (another cadence episode included). Instead, the
  **first scheduler start after the upgrade** performs, under the singleton lock inside its first
  tick, a one-time provenance-preserving transfer: for each `schedule_state` row whose
  `schedule_id` is in the live registry, insert a `scheduler_firings` row with
  `effect_mode='CUTOVER'`, `period_key` = the schedule's raw bucket at `last_fired_at`,
  `period_start` = that bucket's start, `fired_at` = `last_fired_at` **exactly** (elapsed
  eligibility continues from V1's real last firing, not a bucket-rounded one), `tick_id` = the
  running tick. `ON CONFLICT DO NOTHING` makes it idempotent; the presence of a firing row for a
  schedule marks its cutover leg done. Existing semantic keys are retained untouched (no job key
  changes; N6-3). Schedules absent from `schedule_state` have never fired and start with no
  watermark — due immediately, exactly as today's `due()` treats a missing `last_fired`. After
  the cutover, `schedule_state` is never read or written again; its rows and guards stay as
  history.
- **The 09:00 summary and the SLO checks are one trigger**, `v3-daily-summary`: one period, one
  `summary.daily` event, plus `buffer.low` / `slo.below` only while breaching (definitions §6) —
  at most one of each per period, guaranteed by the firing claim in the same transaction. Event
  names follow the dotted-letter rule (`S/contracts/events.py:21`); payload schemas are registered
  by **A6a**, pinned against this note before A6b code (OQ-5).
- **Registry:** `Schedule(schedule_id, workflow, interval_or_trigger, description)` accepts a
  `timedelta` (coerced to `IntervalTrigger`, eligibility `'elapsed'`) so existing constructions
  keep working (`X/integration/pipeline/test_scheduler_driven_path.py:57-59`);
  `ScheduleCatalog.due` / `period_key` (`S/scheduling/registry.py:47-59`) keep their signatures —
  `due` branches on the declared eligibility, `period_key` keeps the prefixed return — and the
  catalog gains `raw_period`; `default_catalog()` gains `Schedule("v3-daily-summary", "V3",
  CalendarTrigger(time(9, 0)), …)` and `Schedule("llm-reconciler", "V3",
  IntervalTrigger(timedelta(seconds=120), eligibility="bucket"), …)`; `SCHEDULES_VERSION` bumps
  `"1"` → `"2"` (`S/scheduling/registry.py:25`). V1 acceptance (`make check`, V1 `make pilot`)
  stays green (spec §10) with **no** V1 timing test adapted.

## 6. Definitions as queries

Plain parameterised SQL in a new `S/scheduling/metrics.py` — no new schema objects, one definition
shared by the summary trigger, serve readiness (A6c) and tests. Every query filters
`seasons.workflow_version = 'v3'` (A1 §7 discipline) and takes **parameterised, aware timestamps
derived from the injected clock and the claimed summary date — never SQL `now()`** (N6-8).

**SLO window — rolling 7 days (spec §9.1.5; master §9.4), integer-only (N6-5).** "Approved
episode" = an episode with **current effective approval authority** — its latest `EPISODE_FINAL`
`APPROVE` decision not superseded (A4's `effective_approval`, spec §7.2; N6-9). Distinct episodes
are counted, so reapproving one episode never counts it twice and superseded approvals drop out:

```sql
SELECT count(DISTINCT e.id) FROM episodes e
JOIN seasons s ON s.id = e.season_id
WHERE s.workflow_version = 'v3'
  AND EXISTS (SELECT 1 FROM approval_events ae
              WHERE ae.entity_type = 'episode' AND ae.entity_id = e.id
                AND ae.gate_type = 'EPISODE_FINAL' AND ae.action = 'APPROVE'
                AND ae.created_at >= %s AND ae.created_at < %s      -- window bounds, injected
                AND NOT EXISTS (SELECT 1 FROM approval_supersessions sup
                                WHERE sup.approval_event_id = ae.id));
```

**Rates are persisted as integers, never floats** (N6-5: canonical JSON and the persistence
guards reject non-integers, `S/contracts/hashing.py:44-45`, `S/persistence/db.py:65-74`): the
payload carries `approved_count`, `window_days`, `required_numerator = 5`,
`required_denominator = 4`; **below SLO iff `4 × approved_count < 5 × window_days`** (master
§9.4's 1.25/day, cross-multiplied — no division anywhere). Decimal rates (1.25, the computed
rate) are rendered for display only. `slo.below` carries `approved_count`, `window_days`,
`required_numerator`, `required_denominator`, `catchup` (integer counts over the last
`catchup_window_days = 2`). Catch-up capacity is **reported, never alerted on**.

**Buffer (spec §9.1.5; master §9.4).** Current **approved full-episode obligations** ahead of
today, measured in days: distinct future Bangkok dates of scheduled posts bound to a full-episode
release obligation that is under current approval authority — superseded authority excluded,
**unrelated slot kinds excluded** (promo/hook/teaser slots never inflate the buffer; until phase F
defines V3 slot kinds, only posts carrying a full-episode publish obligation count), **cancelled
scopes excluded** (a cancelled season's or episode's scheduled posts stop counting from the
cancellation, the reporting scope being non-cancelled V3 scopes):

```sql
SELECT count(DISTINCT (p.scheduled_utc AT TIME ZONE 'Asia/Bangkok')::date)
FROM platform_posts p
JOIN episodes e ON e.id = p.episode_id
JOIN seasons s ON s.id = e.season_id
JOIN episode_tracks et ON et.episode_id = e.id
WHERE s.workflow_version = 'v3'
  AND et.production_state = 'APPROVED'
  AND et.release_state IN ('UNSCHEDULED','SCHEDULED')
  AND p.state IN ('RELEASE_APPROVED','SCHEDULED')
  AND p.slot_kind = 'FULL_EPISODE'             -- promo/hook/parts never inflate the buffer (N6-9;
                                               -- M/0005:43 slot kinds; phase F owns V3 slot semantics)
  AND (p.scheduled_utc AT TIME ZONE 'Asia/Bangkok')::date > %s   -- injected local today
  AND NOT EXISTS (SELECT 1 FROM approval_supersessions sup        -- current authority only
                  JOIN approval_events ae ON ae.id = sup.approval_event_id
                  WHERE ae.entity_type = 'episode' AND ae.entity_id = e.id);
```

Target ≥ 3 days; **`buffer.low` when < 2** (master §9.4). Slots are read from today's
`platform_posts` shape (`M/0005_distribution_and_analytics.sql:32`; `scheduled_utc` at `:57`);
phase F owns V3 slot semantics and adapts the query if slots move.

**Activation gating (OQ-4).** Buffer is evaluated only while some V3 season's release track is
`LAUNCH_APPROVED` or `RELEASING`; throughput (the SLO) only while `RELEASING` (master §9.4: the
requirement applies "while RELEASING"). Outside the gate the summary reports the metric
**unavailable** and no alert fires — the scope is the same non-cancelled V3 scope for both
metrics.

**Health (spec §9.1.5; N6-11).** `SELECT max(finished_at) FROM scheduler_ticks WHERE
status='SUCCEEDED'`; **healthy iff that timestamp exists, is not in the future, and lies within
3 × the configured timer interval** of the injected now — a positive composition parameter,
default 60 s (the host timer's cadence, `S/scheduling/__main__.py:3-5`; OQ-2), **injected into
the health query now** (`health(now, interval_s)`), carried into `Settings` when A6c lands.
**Skips confer nothing** (OQ-3): a lock-skip writes no row, is reported on stdout only, and
neither refreshes nor overrides health — a hung or repeatedly-failing holder therefore shows as
unhealthy (no successful tick within the window) rather than being excused by a skip. Errors per
tick: `errors` on the last 24 h of `scheduler_ticks` rows (parameterised window), where trigger
**and sweep-item** failures propagate (§3). Orphaned `RUNNING` rows are closed at the next tick's
open (§3 step 2). The scheduler itself **never** depends on scheduler freshness (spec §9.2.2);
serve readiness (A6c) and the summary consume it.

## 7. V1 coexistence

The legacy selectors stay, for V1 seasons only, under A1's guards — A6b changes *when* they fire
(durable periods, singleton), not *what* they select, and their **job keys keep today's exact
bytes** (N6-3). Every selector and its guard, consistent with A1 note §7:

| Selector (`S/scheduling/service.py`) | Guard (A1 §7 ships; A6b preserves) |
|---|---|
| `_w01_research` `:168`, `_w02_compile_backstop` `:182`, `_w03_episode_cadence` `:198` (+ refusal inside the insert transaction `:228`), `_w03_write` `:241`, `_w04_references` `:262`, `_w06_edit` `:278`, `_w07_qa` `:332`, `_w09_publish_submit` `:537`, `_w09_publish_poll` `:629`, `_w11_analytics` `:676`, `_w05_render_dispatch` `:696`, `_w05_render_poll` `:769` | candidate filter on the selection SQL (`JOIN seasons s … AND s.workflow_version='v1'`; `_w05_render_poll` filters through `jobs.season_id`) |
| `_w12_workers_janitor` `:821`, `_w12_gpu_janitor` `:828`, `llm-reconciler` (new) | version-shared adapters, not blanket filters (A1 §7: `requeue_expired` unfiltered — the job lifecycle is version-shared; the GPU janitor's V3 arm keys on open gate activations; the LLM reconciler acts on `NEEDS_RECONCILIATION` jobs of both versions under A0's own-worker contract; budget janitors are A2's) |

**No V3 job bypasses STORY LOCK or CAST LOCK (master §2.2):** phase A has **no V3 production
selector at all** — phases B+ replace the selectors per phase and must take track authority into
account, routing V3 enqueue/adoption through A3's fence before job locks (N6-10); A6b's V3
triggers (`v3-daily-summary`, `llm-reconciler`) enqueue nothing and start no production work —
one reads metrics and appends events, the other runs A0's audited reconciliation. Every legacy
selector refuses or filters V3 rows (table above), replayed V3 jobs never reach V1 handlers (A1 §7
replay row), and `require_workflow` refusals (A1 §7) sit unchanged inside the moved transactions
(e.g. the cadence insert).

## 8. Lock audit (spec §6)

The scheduler owns these transactions; the §6 table numbers are A1 §9's. Locks in order taken;
the complete advisory-lock inventory is registered in §3.

| # | Transaction | Locks, in order | Verdict |
|---|---|---|---|
| 0 | Singleton advisory lock | session-level `pg_try_advisory_lock(key1, key2)` in the **two-integer namespace** (§3) on a **dedicated connection** — outermost guard spanning every transaction below; **not** a §6 row lock and never taken inside a row-lock transaction, so it cannot participate in a §6 cycle | n/a (by construction; separate key space from every bigint caller, §3 table) |
| 1 | Tick open / orphan close / tick close (`scheduler_ticks` insert + orphan update, then final update) | single-table insert / update of tick rows only; no §6 locks | conforms |
| 2 | Due-read | read-only scan of `scheduler_firings` (watermark) + eligibility math; no locks | conforms |
| 3 | ATOMIC firing tx | firing-row claim (unique index `(trigger_id, period_key)` on the **raw token**) **first**, then: job INSERTs (semantic-key unique index, `M/0001:78`, keys keep the `sched:{id}:{bucket}` prefix) / episode INSERTs (`w03` cadence — **V1 rows only, no V3 tracks**, N6-10; `episode_tracks` creation is V3 `create_v3_episodes`, A1 §3/A2) / event INSERTs via `append_event` on the caller tx (`aggregate_sequences` row then `domain_events`, `S/core/events.py:126-144`). No track, domain, lease or budget locks — the scheduler only proposes work (`S/scheduling/service.py:24-25`) | conforms |
| 4 | INTENT claim tx | firing-row claim → intent INSERTs → (deferred) supersede UPDATE after durable cover (same table, `scheduler_effect_intents_pending` index); nothing else | conforms |
| 5 | Sweep transactions (janitors, render dispatch/poll) | **unchanged, owned by their components** — audited in A1 §9 (lease admission `2/3 → 7 → 6`; pod activation; transfer) and pre-existing V1 paths; A6b adds no lock around them, only the §3 ownership check before each independently started action | unchanged |
| 6 | `llm_reconcile` sweep (new) | A0's audited RESUME/adoption transactions (provider-operation xact locks, spec §6 #6; `S/core/provider_ops.py:121-124`); adoption order per A3's fence (track SHARE lock, `expected_content_revision`) before job locks; A6b adds only the trigger and the §3 checks | A0/A3's audits cover it |
| 7 | Summary firing tx | firing-row claim → `append_event` on the caller tx (`aggregate_sequences` → `domain_events`); delivery exclusively downstream (A6a dispatcher → sender), never inline | conforms |

Competing transactions: two schedulers serialise on #0; after a crash the lock is gone (§3) and any
claim race is settled by #3/#4's `ON CONFLICT DO NOTHING` — the loser skips the period with no
effects. The outbox dispatcher's transaction-scoped advisory lock (`S/core/events.py:208`) is
never taken by the scheduler; the first-boot seed lock (`S/pipeline/world.py:102-105`) is taken
only by world construction, never by a tick. Known pre-existing gap, unchanged and V1-only: the
cadence insert takes no season row lock (`S/scheduling/service.py:219-238`; A1 §9 item 3 records
it for the V1 hardening backlog).

## 9. Test plan (A-T14 → concrete files)

All offline, real runtime/composition with fakes, ephemeral PostgreSQL via the standard fixtures
(`X/conftest.py:41-95`; loopback stays open under the network guard, `X/conftest.py:13-15`);
pytest `--basetemp` under the session scratchpad. `make check` and V1 `make pilot` stay green;
**no V1 timing test is adapted** (N6-4).

| ID | File | Cases |
|----|------|-------|
| S1 | `X/integration/v3/test_scheduler_singleton.py` | **concurrent ticks**: two `Database` pools, two schedulers, one slow test trigger (~2 s) — exactly one tick row `SUCCEEDED` with firings; the other returns **without blocking** (returns well inside the first's hold, no writes, skipped report). **lost ownership mid-sweep (N6-1)**: `still_held()` flips False after the sweep's first lease action → no subsequent lease/pod action and no shot dispatch starts; the started action finishes via canonical recovery; the tick is `ABORTED_LOST_OWNERSHIP`. **no double-paid attempt**: seed a pending shot, lose ownership during dispatch, re-enter through recovery → the **original attempt identity** is reused (one provider operation, `attempt n` once — `attempts_used + 1` at `S/scheduling/service.py:758-765` never mints `n+1` twice). **claim race after release**: lock released without recording, two ticks race one period → one claims, other skips, effects once. **ATOMIC rollback**: a failing enqueue mid-list → no firing row, no partial jobs. **success definition (N6-11)**: one trigger failing → tick `FAILED` with the error; a sweep-item failure → `FAILED` with the item error; all green → `SUCCEEDED`. |
| S2 | `X/integration/v3/test_scheduler_singleton.py` (process module) | **real process death releases the lock**: a subprocess acquires through `Database.try_advisory_lock` and sleeps; `SIGKILL` it (no unlock ran); an in-process acquirer gets the lock within a bounded wait. **real holder-backend death, scheduler alive (N6-12)**: terminate the dedicated lock connection's backend (`pg_terminate_backend`) mid-sweep while the scheduler process lives → `still_held()` False → no subsequent sweep item starts. **kill before/after canonical effects and before intent completion (N6-12)**: `SIGKILL` a subprocess running the real `fire()` with a test world whose `w12-gpu-janitor` sweep blocks on a file event — kill before the intent commits, after the claim, after the first canonical effect, and mid-dispatch; recover **within the same period and after rollover**; assert stable operation identities via **counters/evidence surviving subprocess death** (deterministic `event_id`, `attempts_used`, lease semantic keys): firing row + intent states exact, **canonical effects exactly once** (lease cleaned once — one evidence event; no duplicate provider operation). |
| S3 | `X/integration/v3/test_scheduler_recovery.py` | **unfinished effect recovered without the marker**: seed an expired lease + a hand-written `PENDING` intent + firing row for a past period → next sweep's recovery pass completes the clean **and only then** marks the intent `SUPERSEDED` (`summary.covered_by`); re-firing the claimed period is refused by the unique key. **independent of period claims (N6-2)**: an obligation whose period is already claimed is still recovered by the recurring sweep. **retryable vs terminal**: a transient sweep failure → intent `FAILED`/`RETRYABLE`, recovered next period; an `UNKNOWN` operation → `FAILED`/`TERMINAL`, never re-run, surfaced in tick errors. **evidence dedup by `event_id` (N6-2)**: replay the GPU janitor's clean → the deterministic `event_id` collides with the PK (`M/0001:116`) → exactly one evidence event. **crash replay of a direct action is a no-op**: replay `w05-render-dispatch` through the recovery path → `attempts_used` finds every shot (`S/scheduling/service.py:738`), no second provider operation, no second lease (semantic key `:750`). |
| S4 | `X/integration/v3/test_scheduler_calendar.py` | **period_key = the candidate's scheduled local date (N6-8)**: before 09:00 the candidate is *yesterday's* date; the date flips at midnight Bangkok, the summary period advances at 09:00 (02:00 UTC); `period_start` = local midnight. **boundaries**: 08:59 local with yesterday claimed → not due; 09:00:00 → due; midnight rollover → new candidate date. **execution ≠ claim (N6-8)**: a catch-up run on Wed 10:00 for Tue's period reports Tue's date and Mon's releases (window bounded by the claimed date, injected timestamps only — no SQL `now()`). **backward clock (N6-8/N6-12)**: clock rolled back below the watermark → candidate rejected, no resurrection of skipped periods (calendar and interval). **catch-up fires only the latest missed period**: 3-day downtime → exactly one new firing; interval multi-bucket jump → one firing; first run → one firing. **semantic-key collision (N6-3/N6-12)**: same bucket across `w09-publish-submit` and `w09-publish-poll` → keys stay `sched:{id}:{bucket}:{post}` — namespaced, no `IdempotencyConflict`. **V1 cutover (N6-4/N6-12)**: seeded `schedule_state` → first start transfers watermarks exactly (`fired_at` verbatim, `effect_mode='CUTOVER'`) → no immediate replay, **no extra cadence episode**, `schedule_state` untouched afterwards, job keys unchanged; a schedule absent from `schedule_state` fires as today. **summary once per period**: re-fire the same day → no second `summary.daily`; breaching seeds → `buffer.low`/`slo.below` exactly once; non-breaching → absent. |
| S5 | `X/integration/v3/test_scheduler_metrics.py` | **authority (N6-9)**: SLO counts distinct episodes under effective approval — reapproval counts once; a superseded approval is excluded; a cancelled scope is excluded; multiple seasons aggregate. **buffer scope (N6-9)**: distinct future Bangkok dates, not post counts; promo/hook (non-full-episode) slot kinds excluded; superseded authority excluded; cancelled scopes excluded; `< 2` alerts, `≥ 3` silent. **gating (OQ-4)**: buffer reported only under `LAUNCH_APPROVED`/`RELEASING`, SLO only under `RELEASING`; otherwise unavailable, no alert. **integers (N6-5)**: payloads carry `approved_count`, `window_days`, `required_numerator=5`, `required_denominator=4`; the 1.25/day boundary both sides via `4 × approved_count < 5 × window_days`; every emitted payload passes canonical JSON and the persistence guards (no float survives). **health (N6-11)**: `SUCCEEDED` within 3 × the injected interval passes; stale fails; a **future** timestamp fails; a skip neither refreshes nor overrides; orphaned `RUNNING` closed at the next tick's open; `errors` counts per tick, trigger and sweep-item failures included. All against seeded V3 rows (A1 test handlers + `platform_posts`/`approval_events` seeds). |
| S6 | `X/integration/persistence/test_migrations.py` (extend; A-T16 pattern) | A6b-1 applies on the populated phase-A-head database; three new tables in `EXPECTED_TABLES`; applied-below-A6b checksums unchanged; catalog guard tests green on all three tables (TRUNCATE + integer included, `X/integration/persistence/test_schema_catalog.py:57`, `:65`); `failure_kind` and the `'CUTOVER'` `effect_mode` guarded by the same checks. |
| S7 | `X/contract/pipeline/test_scheduling_contract.py` (extend) | Registry v2 pure-function cases: `CalendarTrigger` period keys across the ICT boundary; **`raw_period` vs prefixed `period_key`** (raw token for firings, prefix preserved for job keys); interval bucket math; **elapsed eligibility for V1 constructions, bucket eligibility only for explicitly-declared new ones**; `SCHEDULES_VERSION = "2"`; existing V1 registry cases stay green (the `schedule_state` read at `:32` swaps to `scheduler_firings`, assertion values unchanged). **fence race (N6-12)**: reconciler adoption vs an amendment that bumps `content_revision` → the adopted result is quarantined under A3's fence, never installed. **A6a fan-out/rollback (N6-12)**: the summary event is atomic with the firing claim (rollback → no event, no firing); once committed, A6a's dispatcher delivers the fan-out exactly once (`notification_intents` unique per `(event_id, channel)`). |

## 10. Open questions — resolved in round 1

| # | Question (v1.0) | Resolution ([critique](codex-a6b-note-critique.md) OQ table + [rulings](a6b-critique-rulings.md)) |
|---|----------|----------------|
| OQ-1 | Retire `schedule_state` (M/0017)? | **Yes — after the explicit §5 cutover** (not immediately): the one-time transfer preserves the last eligible firing and semantic keys; historical rows and guards retained. |
| OQ-2 | Source of the health interval (3 × rule)? | **A positive composition parameter for the host timer cadence, default 60 seconds, injected into the health queries now**; carried into `Settings` when A6c lands. |
| OQ-3 | Record lock-skipped ticks? | **No tick row for skips.** Reported separately (stdout); they confer **no freshness or health** — a skip neither refreshes nor overrides health (§6). |
| OQ-4 | Buffer/SLO scope before any V3 season reaches release? | **Activation gating accepted:** buffer during `LAUNCH_APPROVED`/`RELEASING`, throughput during `RELEASING`; otherwise report unavailable. Scope applied consistently (§6). |
| OQ-5 | `summary.daily`/`buffer.low`/`slo.below` payload schemas are A6a's. | **Resolved before A6b code**, against accepted A6a schemas — integer representations, scope, timestamps and deep links (§4, §6). |
| OQ-6 | Heartbeat granularity: per trigger + per sweep (v1.0) vs per step inside janitors? | **Recommendation rejected.** Ownership is checked before **each individually newly started action inside sweeps** (N6-1); in-flight operations keep their canonical recovery (§3). |
| OQ-7 | One scheduler process for V1 and V3, or separate lock namespaces per workflow? | **One lock and one catalog is appropriate, with bounded actions.** V1 and V3 do not need separate singleton namespaces (§3, §8). |

## 11. Finding → resolution (round 1)

| Finding | Section |
|---------|---------|
| N6-1 ownership before each action in a sweep; original attempt identity | §3 (lost ownership), §4 (`render_dispatch` row), S1/S2 |
| N6-2 recovery identities, supersession on durable cover, retryable/terminal, event_id dedup, coalesced recovery | §4 (intent lifecycle + recovery table), §2 (`failure_kind`), S2/S3 |
| N6-3 raw period token vs enqueue-key prefix; V1 keys preserved | §5 (first bullet), §4 (enqueue row), §2 (period_key comment), S4 |
| N6-4 V1 elapsed eligibility preserved; bucket/calendar for new schedules; one-time cutover; V1 tests unchanged | §5 (eligibility + cutover), §2 (schedule_state paragraph), S4, S7 |
| N6-5 integer-only payloads; rational rates; A6a aligned | §6 (SLO), §4 (summary row), S5 |
| N6-6 two-minute LLM reconciliation trigger with execution/recovery contract | §4 (trigger row + recovery row), §7, §8 #6, S7 (fence race) |
| N6-7 complete lock inventory; two-integer namespace; ownership handle; objsubid/mode/backend matched; connection always closed | §3 (inventory table, key, helper, check SQL), §8 #0 |
| N6-8 candidate's scheduled local date; injected clock everywhere; bounded windows; execution ≠ claim; watermark; boundary tests | §5 (candidate, execution, watermark), §6 (parameterised SQL), S4/S5 |
| N6-9 distinct episodes under effective approval; scope/cancellation policy; buffer = approved full-episode obligations | §6 (SLO, buffer, gating), S5 |
| N6-10 command/effect rows; caller tx through handlers; fence before job locks; no V3 tracks from V1 cadence; A6a schemas pinned; transactional emission only | §4 (contract table + binding rows), §8 (#3, #7), S7 |
| N6-11 skips ≠ health; explicit success; failures propagate; non-future timestamp within 3 intervals; orphaned RUNNING recovery | §3 (steps 2, 4, 5), §6 (health), S1/S5 |
| N6-12 A-T14 beyond interruption-before-effects: backend death with scheduler alive, kills around effects and intent completion, same-period and rollover recovery, stable identities, collision/cutover/backward-clock/fence-race/fan-out cases | §9 S1–S7 |

*The rulings table rules N6-1..N6-11 (all ACCEPTED); N6-12 — the critique's test-plan expansion —
carries no separate ruling row and is applied here as the test obligation of the accepted findings
(N6-1/2/3/4/8 are untestable without it). The symbolic A6b-1 allocation and the A6c deferral stand;
A6b-1's numeric filename is resolved at build time after the accepted upstream tail, preserving
A1's 0028–0031 allocation and all applied bytes.*
