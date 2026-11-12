# A6b design note: the V3 scheduler — singleton, durable periods, calendar triggers

**Version 1.0, 12 Nov 2026. Author: GLM (design note only; no code).** Requirements:
[phase-A-spec.md](phase-A-spec.md) v0.3 §0, §1, §6, §9.1, §9.2 (scheduler startup only), §10 (A6b
row), §11 (A-T14); binding wording AC-20 ([codex-a-critique.md](codex-a-critique.md)) and **AR-5**
([codex-a-recritique.md](codex-a-recritique.md)); master [SPEC-v3.md](SPEC-v3.md) v0.4.4 §1, §2.2,
§3.3, §9.4; [A1-design-note.md](A1-design-note.md) v1.2 §1 (migrations 0028–0031), §7, §9.
Facts re-verified on `feat/microdrama-m0-m4` @ `1df41d7` (migration tail **0025**). `S/` =
`microdrama/src/microdrama/`, `M/` = `microdrama/migrations/`, `X/` = `microdrama/tests/`.

**Scope:** A6b changes scheduler *behaviour* only — the singleton tick, durable firing periods and
effect intents, calendar triggers, catch-up, and the metric definitions. Production composition
selection, role dependencies and qualifications are **A6c** (spec §10; AC-21). A6b keeps
`scheduling/__main__.py` building the offline world exactly as today (`S/scheduling/__main__.py:40`).

---

## 1. Migration allocation

One migration, one purpose; its number is assigned at build time after re-auditing the tail (A1
allocated 0028–0031; A2–A6a take the numbers in between; spec §10). **Applied migration bytes are
never edited** — the migrator hashes file bytes and rejects changed checksums (`S/persistence/migrate.py:45`,
`:51`).

| # | File | Purpose |
|---|------|---------|
| A6b-1 | `A6b-1_v3_scheduler_periods.sql` | `scheduler_ticks`, `scheduler_firings` (the durable `(trigger, period_key)` identity, spec §9.1.2), `scheduler_effect_intents` — all guarded |

No other migration. Catalog updates (`EXPECTED_TABLES`, `X/integration/persistence/test_migrations.py`)
are code/test changes riding with the package (A-T16 pattern; the catalog guard tests
`X/integration/persistence/test_schema_catalog.py:22-37` then cover the three new tables
automatically, TRUNCATE `:57` and integer-numbers `:65` included).

## 2. Guarded DDL

Guard pattern per `M/0017_schedule_state.sql:11-18` (the table this replaces as the firing source of
truth): `md_immutable_columns` for identity columns, `md_forbid_mutation` on DELETE and TRUNCATE,
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
  errors         jsonb NOT NULL DEFAULT '[]'::jsonb,   -- per-trigger errors ("errors per tick")
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
CREATE TABLE scheduler_firings (
  id             uuid PRIMARY KEY,
  schema_version text NOT NULL DEFAULT '1.0',
  trigger_id     text NOT NULL CHECK (trigger_id ~ '^[a-z0-9][a-z0-9._\-]{1,80}$'),
  trigger_kind   text NOT NULL CHECK (trigger_kind IN ('interval','calendar')),
  period_key     text NOT NULL CHECK (period_key ~ '^([0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]+)$'),
  period_start   timestamptz NOT NULL,                  -- bucket start / local midnight (§5)
  fired_at       timestamptz NOT NULL,
  tick_id        uuid NOT NULL REFERENCES scheduler_ticks(id),
  effect_mode    text NOT NULL CHECK (effect_mode IN ('ATOMIC','INTENTS')),
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
migration per phase. `scheduler_firings` is fully immutable — a firing is a fact; corrections are
new rows. **`schedule_state` (M/0017) is no longer written or read by the new fire path** (§4); the
table and its guards remain untouched history. Its only other reader today is the contract test
(`X/contract/pipeline/test_scheduling_contract.py:32`), which the build adapts.

## 3. The singleton (AR-5)

**Key.** One fixed session-advisory key, in the existing named-constant style:

```python
_SCHEDULER_LOCK_KEY = 0x6D645F7363686564  # "md_sched" (64-bit, top byte 0x6D)
```

Registered alongside the other fixed keys — `0x6D6472616D61 "mdrama"` (migrator,
`S/persistence/migrate.py:25`), `0x6D645F6F7574 "md_out"` (outbox dispatcher,
`S/core/events.py:172`) — and disjoint from every `hashtextextended` seed in use
(e.g. `S/budget/billing.py:256`, `:297`, `:496`, `:828`; `S/review/intake.py:459`;
`S/rendering/keyframe_preflight.py:1118`), which hash to the full 64-bit space from small seed
constants. A fixed constant is deterministic across processes and restarts and readable in
`pg_locks` when diagnosing a stuck holder.

**Acquisition — a new `Database` helper beside the existing precedent** (`advisory_lock`,
`S/persistence/db.py:228-258`, already opens a *dedicated* short-lived connection —
`psycopg.connect(self.dsn, autocommit=True)` at `:243` — unlocks in `finally` at `:256-257`,
closes at `:258`):

```python
@contextmanager
def try_advisory_lock(self, key: int) -> Iterator[bool]:
    """pg_try_advisory_lock on a dedicated connection; yields True iff acquired.
    Never blocks. Released in finally only if acquired; connection always closed."""
```

- **Dedicated connection, outside the pool** — for the same reason the existing helper gives: work
  transactions keep the whole pool (`S/persistence/db.py:231-233`). One connection per tick: opened
  at tick start, closed at tick end.
- `SELECT pg_try_advisory_lock(%s)` — **false → skip the tick**: return immediately, write nothing
  (the caller owns nothing; a skip means another instance *is* ticking, so health is unaffected,
  §6). Never `pg_advisory_lock`, never a timeout — `try` cannot block (AR-5's exact objection to
  the blocking form).
- `finally`: `SELECT pg_advisory_unlock(%s)` **only if acquired**, then close — release cannot be
  skipped on any exception path.
- **A crash releases the lock**: the session ends with the TCP connection and PostgreSQL drops
  session-level advisory locks — the documented behaviour of the existing helper
  (`S/persistence/db.py:233`). No code runs; no stale lock survives a dead process.

**Lost ownership.** The lock can only be lost if the dedicated connection dies or an administrator
forces it. Detection is a check executed *on the dedicated connection itself* — success proves the
session is alive, and the row proves the lock is still held by this backend (64-bit advisory keys
appear in `pg_locks` split into 32-bit halves):

```sql
SELECT EXISTS (
  SELECT 1 FROM pg_locks
  WHERE locktype = 'advisory'
    AND classid = (%s::bigint >> 32)
    AND objid   = (%s::bigint & 4294967295)
    AND pid = pg_backend_pid())
```

A `TickOwnership` object (injectable for tests, §9) wraps the connection and exposes
`still_held() -> bool`; a raised connection error counts as False. **Checked before starting each
due trigger and before each direct sweep.** On False, the scheduler **stops starting new actions**:
the tick ends with status `ABORTED_LOST_OWNERSHIP`, recording what already fired; no further
triggers fire and no sweep starts. An action already in flight is allowed to finish — every step is
a short self-contained transaction, and the sweeps were designed concurrency-safe before any
singleton existed (`S/scheduling/service.py:4-5` documents `fire` as safe to call concurrently);
per-step heartbeat instrumentation inside the janitors is therefore unnecessary (OQ-6).

**The tick** — `TriggerScheduler.fire(*, now=None, only=None)` keeps its signature and return type
(`S/scheduling/service.py:113`, `:39-54`):

1. `with db.try_advisory_lock(_SCHEDULER_LOCK_KEY) as acquired:` — not acquired → return an empty
   report marked skipped; **no DB writes**.
2. One transaction inserts the `scheduler_ticks` row (`RUNNING`).
3. Read-only: the last claimed `period_key` per trigger from `scheduler_firings`; compute due
   candidates (§5).
4. For each due trigger in catalog order (today's declaration order, `S/scheduling/service.py:118`):
   `still_held()` or abort; then fire per its mode (§4). One trigger's failure still never kills
   the tick (`S/scheduling/service.py:126-133`) — the error is recorded on the tick row.
5. Close the tick: `SUCCEEDED` (ran to completion; per-trigger errors live in `errors`),
   `FAILED` (tick-level exception), or `ABORTED_LOST_OWNERSHIP`; `report` =
   `FireReport.as_dict()` (`S/scheduling/service.py:47-54`).
6. `finally` releases the lock (§3 acquisition helper).

The `only=` filter stays (test seam, `S/scheduling/service.py:119-120`). `__main__.py` stays
one-shot per host-timer invocation (`S/scheduling/__main__.py:3-5`, `:40-42`); the lock lives and
dies within one `fire()` call. **Startup dependencies (spec §9.2, scheduler role only):** the
database reachable and migrations at the expected head — exactly what `__main__` already does
(`migrate(dsn)` at `S/scheduling/__main__.py:31`) — and nothing else: no object store, no gateway,
and **never the scheduler's own freshness** (spec §9.2.2). Role-specific production dependencies
and fail-closed exits are A6c's.

## 4. Periods and effects

**Claim rule (every trigger):** the firing transaction inserts the `scheduler_firings` row with
`INSERT … ON CONFLICT (trigger_id, period_key) DO NOTHING RETURNING id`. **No row returned → the
period is already claimed → skip** (a crash-restart race after lock release settles here: the loser
skips; the winner's effects are already committed). `load_last_fired`/`record_fired`
(`S/scheduling/service.py:57-69`) leave the fire path; `schedule_state` is retired as the source of
truth (OQ-1).

| Trigger (`registry` id) | Kind | Mode | Committed **with** the firing row |
|---|---|---|---|
| `w01-research` … `w11-analytics` (all enqueue schedules: `w01`, `w02`, `w03-write`, `w04`, `w06`, `w07`, `w09-publish-submit`, `w09-publish-poll`, `w11`) | interval | **ATOMIC** | The handler's selection runs read-only (as today, e.g. `S/scheduling/service.py:549`), then **one transaction**: firing claim + every job enqueue of the period (`world.jobs.enqueue(tx, …)`, `S/scheduling/service.py:152-159`; semantic keys dedupe, `M/0001:78`, `S/scheduling/registry.py:10-13`). Today's per-enqueue transactions (`S/scheduling/service.py:151`) collapse into this one. |
| `w03-episode-cadence` | interval | **ATOMIC** | Firing claim + the direct episode INSERT(s) — the insert at `S/scheduling/service.py:219-238` moves **into** the firing transaction, A1's V3 refusal guard inside it (A1 §7 row). Single transaction, so the cadence effect is atomic with its period identity. |
| `w05-render-dispatch` | interval | **INTENTS** | Claim + intent `render_dispatch`, committed first; then the existing multi-transaction flow runs unchanged (read-only manifest scan `:720-732`, pod-lease claim `:747-753`, `ensure_pod` `:755`, per-shot router dispatch). |
| `w05-render-poll` | interval | **INTENTS** | Claim + intent `render_poll`; then the existing reconciliation flow. |
| `w12-workers-janitor` | interval | **INTENTS** | Claim + intent `workers_janitor_sweep`; then `WorkersJanitor.sweep` — each step its own transaction (`S/workers/janitor.py:91-133`; `requeue_expired` `S/core/jobs.py:706`, `expire_stale`, telemetry read, evidence write). |
| `w12-gpu-janitor` | interval | **INTENTS** | Claim + intent `gpu_janitor_sweep`; then `Janitor.sweep` — per-lease cleans and evidence events, each its own transaction (`S/rendering/janitor.py:183-193`, `:236-269`, `:166-179`). |
| `v3-daily-summary` (new) | calendar 09:00 | **ATOMIC** | Firing claim + `summary.daily` event (and `buffer.low` / `slo.below` when breaching) via `append_event` in the same transaction (`S/core/events.py:69-144`) — event emission is a database effect, so it is atomic with the period identity. |

**Intent lifecycle:** `PENDING` when claimed → `COMPLETED` (sweep finished; counts in `summary`) /
`FAILED` (sweep raised) — written by the tick after the sweep; `SUPERSEDED` — set by the *next*
period's claim transaction for the same `(trigger_id, effect)` when it finds a `PENDING` intent
from an earlier `period_key`. A stale intent is superseded, never deleted, never re-run as such.

**Unfinished effects stay recoverable independently of any firing marker (AR-5):** the intent rows
are the durable *record* tying a firing to its started effects; recoverability itself comes from
the canonical identities each direct action already keeps — the workers janitor re-discovers expired
claims and stale holds from durable rows (`S/core/jobs.py:706`); the GPU janitor's candidate query
re-finds non-terminal leases (`S/rendering/janitor.py:236-246`) and its evidence events dedupe on a
deterministic `uuid5` aggregate (`:169`); render dispatch dedupes the pod lease by semantic key
(`pod.lease:{episode}:render`, `S/scheduling/service.py:750`) and rediscovers un-dispatched shots via
`attempts_used` (`:738`), with provider operations carrying their own request/recovery identity
(A0 §5.3, V3-AT-20 discipline). So a killed sweep leaves at most unfinished-but-idempotent work:
the next period's sweep re-scans and completes it, and **crash replay of a direct action is a
no-op** (A-T14). No marker is consulted on that path — the marker exists for observability and the
supersede bookkeeping, not for recovery correctness.

## 5. Calendar triggers

```python
@dataclass(frozen=True)
class CalendarTrigger:
    local_time: time                  # the schedule's wall-clock firing time
    tz: str = "Asia/Bangkok"          # ICT, UTC+07:00 — no DST transitions in the IANA data
```

- **`period_key` = the local date** (`YYYY-MM-DD`) of `now` in `tz` (spec §9.1.3). Interval
  triggers keep a bucket integer (`period_key = floor(epoch(now)/interval)`, evolving
  `S/scheduling/registry.py:56-59`).
- **Scheduled instant of a period** = `datetime.combine(local_date, local_time,
  ZoneInfo(tz))` as UTC — 09:00 Bangkok is 02:00 UTC. All persisted instants remain `timestamptz`
  (UTC), per the event contract's `UtcDateTime` (`S/contracts/events.py:27`); no naive datetimes
  anywhere in period math. Bangkok is DST-free, so local dates map stably onto instants; `zoneinfo`
  would handle transitions anyway (a hypothetical tz change re-derives cleanly from the local date).
- **Due rule, uniform for both kinds:** the candidate period is the **latest period whose
  scheduled instant ≤ now** (interval: the current bucket, whose start is by definition past;
  calendar: today if the local time has passed, else yesterday). Fire iff that period has no
  `scheduler_firings` row. **At most one firing per trigger per tick**, and **at most the latest
  missed period** is ever fired (spec §9.1.4): after a first run or any downtime, older missed
  periods are skipped forever — there is no backlog storm.
  - Down Mon–Wed, resumed Wed 10:00 Bangkok → fires **Wed** (09:00 passed); resumed Wed 08:00 →
    fires **Tue** (the latest missed); Mon never replays. First run ever → fires the current
    latest-due period once.
- **The 09:00 summary and the SLO checks are one trigger**, `v3-daily-summary`: one period, one
  `summary.daily` event, plus `buffer.low` / `slo.below` only while breaching (definitions §6) —
  at most one of each per period, guaranteed by the firing claim in the same transaction. Event
  names follow the dotted-letter rule (`S/contracts/events.py:21`); payload schemas are registered
  by **A6a**, which ships first (spec §10, §8.4) — A6b emits with these fields (OQ-5):
  `date` (local), `releases` (published/failed/held per destination, yesterday),
  `buffer_days` + `slo` (`rate`, `required`, `window_days`, `catchup`), `health`
  (`last_succeeded_tick_age_s`, `errors_24h`), `spend` (committed vs season cap, phase-A shape).
- **Registry:** `Schedule(schedule_id, workflow, interval_or_trigger, description)` accepts a
  `timedelta` (coerced to `IntervalTrigger`) so existing constructions keep working
  (`X/integration/pipeline/test_scheduler_driven_path.py:57-59`); `ScheduleCatalog.due` /
  `period_key` (`S/scheduling/registry.py:47-59`) delegate to the trigger object;
  `default_catalog()` gains `Schedule("v3-daily-summary", "V3", CalendarTrigger(time(9, 0)), …)`;
  `SCHEDULES_VERSION` bumps `"1"` → `"2"` (`S/scheduling/registry.py:25`).
- **Interval due-ness becomes bucket-anchored** (today: elapsed-since-last-fired,
  `S/scheduling/registry.py:52`; A6b: current bucket unclaimed) — same one-fire-per-period
  guarantee, without per-tick drift. V1 acceptance (`make check`, V1 `make pilot`) must stay green
  (spec §10); only pinned elapsed-behaviour tests adapt (`X/contract/pipeline/test_scheduling_contract.py`).

## 6. Definitions as queries

Plain parameterised SQL in a new `S/scheduling/metrics.py` — no new schema objects, one definition
shared by the summary trigger, serve readiness (A6c) and tests. Every query filters
`seasons.workflow_version = 'v3'` (A1 §7 discipline).

**SLO window — rolling 7 days (spec §9.1.5; master §9.4).** "Approved episode" = a V3
`EPISODE_FINAL` `APPROVE` decision:

```sql
SELECT count(*) FROM approval_events ae
JOIN episodes e ON e.id = ae.entity_id
JOIN seasons s ON s.id = e.season_id
WHERE ae.gate_type = 'EPISODE_FINAL' AND ae.action = 'APPROVE'
  AND s.workflow_version = 'v3'
  AND ae.created_at >= now() - interval '7 days';
```

`slo.rate = count / 7.0`; **below SLO** iff a V3 season has `season_tracks.release_state =
'RELEASING'` and `rate < 1.25` (master §9.4: the requirement applies "while RELEASING").
Catch-up capacity (≥ 2/day on 2 consecutive days) is computed over the last 2 days and **reported,
never alerted on**. `slo.below` carries `rate`, `required_per_day`, `window_days`.

**Buffer (spec §9.1.5; master §9.4).** Approved, unpublished, scheduled episodes ahead of today —
measured in days:

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
  AND (p.scheduled_utc AT TIME ZONE 'Asia/Bangkok')::date
      > (now() AT TIME ZONE 'Asia/Bangkok')::date;
```

Target ≥ 3 days; **`buffer.low` when < 2** (master §9.4). Slots are read from today's
`platform_posts` shape (`M/0005_distribution_and_analytics.sql:32`; `scheduled_utc` at `:57`);
phase F owns V3
slot semantics and adapts the query if slots move. Evaluated only while a V3 season's release track
is `LAUNCH_APPROVED` or `RELEASING` (OQ-4).

**Health (spec §9.1.5).** `SELECT max(finished_at) FROM scheduler_ticks WHERE status='SUCCEEDED'`;
**healthy iff that tick finished within 3 × the tick interval** (default 60 s — the host timer's
cadence, `S/scheduling/__main__.py:3-5`; the value is a composition parameter, OQ-2). Errors per
tick: `errors` on the last 24 h of `scheduler_ticks` rows. Lock-skips write no row (§3) — a skip
implies another live ticker. The scheduler itself **never** depends on scheduler freshness
(spec §9.2.2); serve readiness (A6c) and the summary consume it.

## 7. V1 coexistence

The legacy selectors stay, for V1 seasons only, under A1's guards — A6b changes *when* they fire
(durable periods, singleton), not *what* they select. Every selector and its guard, consistent with
A1 note §7:

| Selector (`S/scheduling/service.py`) | Guard (A1 §7 ships; A6b preserves) |
|---|---|
| `_w01_research` `:168`, `_w02_compile_backstop` `:182`, `_w03_episode_cadence` `:198` (+ refusal inside the insert transaction `:228`), `_w03_write` `:241`, `_w04_references` `:262`, `_w06_edit` `:278`, `_w07_qa` `:332`, `_w09_publish_submit` `:537`, `_w09_publish_poll` `:629`, `_w11_analytics` `:676`, `_w05_render_dispatch` `:696`, `_w05_render_poll` `:769` | candidate filter on the selection SQL (`JOIN seasons s … AND s.workflow_version='v1'`; `_w05_render_poll` filters through `jobs.season_id`) |
| `_w12_workers_janitor` `:821`, `_w12_gpu_janitor` `:828` | version-shared adapters, not blanket filters (A1 §7: `requeue_expired` unfiltered — the job lifecycle is version-shared; the GPU janitor's V3 arm keys on open gate activations; budget janitors are A2's) |

**No V3 job bypasses STORY LOCK or CAST LOCK (master §2.2):** phase A has **no V3 production
selector at all** — phases B+ replace the selectors per phase and must take track authority into
account; A6b's only V3 trigger (`v3-daily-summary`) enqueues nothing and starts no production work,
it reads metrics and appends events. Every legacy selector refuses or filters V3 rows (table
above), replayed V3 jobs never reach V1 handlers (A1 §7 replay row), and `require_workflow`
refusals (A1 §7) sit unchanged inside the moved transactions (e.g. the cadence insert).

## 8. Lock audit (spec §6)

The scheduler owns these transactions; the §6 table numbers are A1 §9's. Locks in order taken:

| # | Transaction | Locks, in order | Verdict |
|---|---|---|---|
| 0 | Singleton advisory lock | session-level `pg_try_advisory_lock` on a **dedicated connection** (§3) — outermost guard spanning every transaction below; **not** a §6 row lock and never taken inside a row-lock transaction, so it cannot participate in a §6 cycle | n/a (by construction) |
| 1 | Tick open / tick close (`scheduler_ticks` insert, then update) | single-table insert / update of the tick's own row; no §6 locks | conforms |
| 2 | Due-read | read-only scan of `scheduler_firings`; no locks | conforms |
| 3 | ATOMIC firing tx | firing-row claim (unique index `(trigger_id, period_key)`) **first**, then: job INSERTs (semantic-key unique index, `M/0001:78`) / episode + `episode_tracks` INSERTs (`w03` cadence) / event INSERTs via `append_event` (`aggregate_sequences` row then `domain_events`, `S/core/events.py:126-144`). No track, domain, lease or budget locks — the scheduler only proposes work (`S/scheduling/service.py:24-25`) | conforms |
| 4 | INTENT claim tx | firing-row claim → intent INSERTs → supersede UPDATE (same table, `scheduler_effect_intents_pending` index); nothing else | conforms |
| 5 | Sweep transactions (janitors, render dispatch/poll) | **unchanged, owned by their components** — audited in A1 §9 (lease admission `2/3 → 7 → 6`; pod activation; transfer) and pre-existing V1 paths; A6b adds no lock around them, only the §3 heartbeat between them | unchanged |
| 6 | Summary firing tx | firing-row claim → `append_event` (`aggregate_sequences` → `domain_events`) | conforms |

Competing transactions: two schedulers serialise on #0; after a crash the lock is gone (§3) and any
claim race is settled by #3/#4's `ON CONFLICT DO NOTHING` — the loser skips the period with no
effects. The outbox dispatcher's transaction-scoped advisory lock (`S/core/events.py:208`) is never
taken by the scheduler. Known pre-existing gap, unchanged and V1-only: the cadence insert takes no
season row lock (`S/scheduling/service.py:219-238`; A1 §9 item 3 records it for the V1 hardening
backlog).

## 9. Test plan (A-T14 → concrete files)

All offline, real runtime/composition with fakes, ephemeral PostgreSQL via the standard fixtures
(`X/conftest.py:41-95`; loopback stays open under the network guard, `X/conftest.py:13-15`);
pytest `--basetemp` under the session scratchpad. `make check` and V1 `make pilot` stay green.

| ID | File | Cases |
|----|------|-------|
| S1 | `X/integration/v3/test_scheduler_singleton.py` | **concurrent ticks**: two `Database` pools, two schedulers, one slow test trigger (~2 s) — exactly one tick row `SUCCEEDED` with firings; the other returns **without blocking** (returns well inside the first's hold, no writes, skipped report). **lost ownership**: injected `TickOwnership` flipping `still_held()` False after the first trigger → remaining due triggers fire nothing (no firing rows), tick `ABORTED_LOST_OWNERSHIP`. **claim race after release**: lock released without recording, two ticks race one period → one claims, other skips, effects once. **ATOMIC rollback**: a failing enqueue mid-list → no firing row, no partial jobs. |
| S2 | `X/integration/v3/test_scheduler_singleton.py` (process module) | **real process death releases the lock**: a subprocess acquires through `Database.try_advisory_lock` and sleeps; `SIGKILL` it (no unlock ran); an in-process acquirer gets the lock within a bounded wait. **real process death mid-tick**: a subprocess runs the real `fire()` with a test world whose `w12-gpu-janitor` sweep blocks on a file event; kill it after the intent row is visible → firing row + `PENDING` intent exist and nothing else is running; a fresh process fires the next period → old intent `SUPERSEDED`, sweep re-runs, **canonical effects exactly once** (lease cleaned once — one evidence event on the janitor aggregate; no duplicate provider operation). |
| S3 | `X/integration/v3/test_scheduler_recovery.py` | **unfinished effect recovered without the marker**: seed an expired lease + a hand-written `PENDING` intent + firing row for a past period (exactly what a killed process leaves) → next firing supersedes and completes the clean; re-firing the claimed period is refused by the unique key. **crash replay of a direct action is a no-op**: run `w05-render-dispatch` for a period against fakes, then replay the sweep through the recovery path → `attempts_used` finds every shot (`S/scheduling/service.py:738`), no second provider operation, no second lease (semantic key `:750`). |
| S4 | `X/integration/v3/test_scheduler_calendar.py` | **period_key = Bangkok local date**: instants around 02:00 UTC — the date flips at 09:00 ICT, not 09:00 UTC; `period_start` = local midnight. **due-ness**: 08:59 local with yesterday claimed → not due; 09:01 → due. **catch-up fires only the latest missed period**: calendar — 3-day downtime → exactly one new firing (the latest missed; older days never fire); interval — multi-bucket jump → one firing; first run → one firing. **summary once per period**: re-fire the same day → no second `summary.daily`, no second firing row; breaching seeds → `buffer.low`/`slo.below` present, exactly once; non-breaching → absent. |
| S5 | `X/integration/v3/test_scheduler_metrics.py` | SLO window excludes approvals older than 7 days; 1.25/day boundary both sides; rate only alerts while a V3 season is `RELEASING`. Buffer: distinct future Bangkok dates, not post counts; `< 2` alerts, `≥ 3` silent. Health: `SUCCEEDED` within 3 × interval passes; stale fails; `errors` counts per tick. All against seeded V3 rows (A1 test handlers + `platform_posts`/`approval_events` seeds). |
| S6 | `X/integration/persistence/test_migrations.py` (extend; A-T16 pattern) | A6b-1 applies on the populated phase-A-head database; three new tables in `EXPECTED_TABLES`; applied-below-A6b checksums unchanged; catalog guard tests green on all three tables (TRUNCATE + integer included, `X/integration/persistence/test_schema_catalog.py:57`, `:65`). |
| S7 | `X/contract/pipeline/test_scheduling_contract.py` (extend) | Registry v2 pure-function cases: `CalendarTrigger` period keys across the ICT boundary; interval bucket math; `SCHEDULES_VERSION = "2"`; existing V1 registry cases stay green (the `schedule_state` read at `:32` adapts to `scheduler_firings`). |

## 10. Open questions

| # | Question | Recommendation |
|---|----------|----------------|
| OQ-1 | Retire `schedule_state` (M/0017) now that `scheduler_firings` is the source of truth? Its writers/`load_last_fired`/`record_fired` have no callers outside the fire path (`S/scheduling/service.py:57-69`; the contract test reads it directly, `X/contract/pipeline/test_scheduling_contract.py:32`). | Yes: stop writing in A6b, keep the table and guards as history, migrate the one test. Cheaper than dual-writing two truths — AC-20's objection was exactly split firing state. |
| OQ-2 | Where does the health "interval" (3 × rule) come from? | A composition parameter with default 60 s (the host timer's documented cadence, `S/scheduling/__main__.py:3-5`); carried into `Settings` when A6c lands. Until then the health query takes it as an argument. |
| OQ-3 | Should lock-skipped ticks be recorded? | No DB row — stdout only. A skip proves another live ticker (health is fine by definition); recording it would need a transaction the skipper has no right to write. |
| OQ-4 | Buffer/SLO evaluation scope before any V3 season reaches release (phases B–E pilots) — alerts would fire on an empty pipeline. | Evaluate buffer only while a V3 season's release track is `LAUNCH_APPROVED`/`RELEASING`, SLO only while `RELEASING` (master §9.4's own wording); otherwise the summary reports `n/a` and no alert fires. Orchestrator to confirm the buffer gating, which is this note's reading. |
| OQ-5 | Exact `summary.daily`/`buffer.low`/`slo.below` payload schemas are A6a's registration (spec §8.4); A6a ships first. | Emit with §5's field list; reconcile the two notes at the A6a review so registry and emission agree field-for-field. |
| OQ-6 | Heartbeat granularity: per trigger + per sweep (this note) vs per step inside the janitors. | Keep per trigger + per sweep: the sweeps were concurrency-safe before the singleton existed (`S/scheduling/service.py:4-5`), so a mid-sweep ownership loss is no worse than today's documented concurrent invocations; instrumenting the janitors adds a callback parameter through components A6b doesn't otherwise touch. Revisit only if the Codex critique insists. |
| OQ-7 | One scheduler process for V1 interval triggers and the V3 calendar trigger, or separate lock namespaces per workflow? | One process, one lock, one tick, catalog order (V1 schedules first, `v3-daily-summary` last). Two namespaces would allow a V1 tick and a V3 tick concurrently for no benefit and would split health into two stories. |
