# A3 design note: revision fence, cancellation, stale quarantine, per-queue workers

**Version 1.3, 14 Nov 2026. Author: GLM (design note only; one file, no code).**
v1.3 — round-2 integration completed + round-3 blockers folded (GLM); operator-authorized R4
follows. v1.2's round-2 apply was PARTIAL (the apply job was quota-killed mid-edit); this version
completes, in the body, every integration round 3 flagged partial and folds the round-3 report —
[codex-a3-r3.md](codex-a3-r3.md) (N3R3-1/N3R3-2 BLOCKING, N3R3-3/N3R3-4 SHOULD-FIX, verdict
REWORK) — per its Replacement wording: recovery classification now reaches every caller (§3.2
collector and reconciliation rows, §4.1 discovery, the §7 recovery rows, §9 — N3R2-2/N3R3-1); the
V3 paid begin/rearm lock order (#6 serialization/operation locks before #7 reservation locks,
eligibility validated first) is audited **separately** with separate tests (§7 —
N3R2-3/N3R3-2); the worker incarnation fence lands in §5.1 (N3R2-6/N3R3-3); and the A-T8/A-T12a
assertions are corrected in the test rows themselves — real A0 signals raised with translated
outcomes asserted separately, both admission/amendment interleavings synchronized, graceful
SIGTERM distinguished from forced death (N3R2-7/N3R3-4). v1.2 (14 Nov) applied the round-2
recritique — [codex-a3-note-recritique.md](codex-a3-note-recritique.md)
(N3R2-1..7: four BLOCKING, three SHOULD-FIX, verdict REWORK) — exactly as ruled in
[a3-recritique-rulings.md](a3-recritique-rulings.md) (**all 7 ACCEPTED**, each folded per its
Replacement paragraph; round 3 closed N3R2-1/4/5 — the other four are completed here).
Replacement wording wins; no acceptance test is weakened. v1.1 (13 Nov) applied the round-1
critique —
[codex-a3-note-critique.md](codex-a3-note-critique.md) (N3-1..N3-10, verdict REWORK) — exactly
as ruled in [a3-critique-rulings.md](a3-critique-rulings.md) (**all 10 ACCEPTED; directions
binding**; A-T12a's expectation *corrected* to the reachable path per N3-2, and A-T8/A-T18
strengthened per N3-9/N3-10). Requirements:
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
prerequisites, not yet built); v1.1 additionally re-verified the A0-D integration points named
below against the current tree @ `8623eef`, including the gateway snapshot **`G/` =
`.scratch/a0d-gateway/microdrama/src/microdrama/`** (`llm/step.py` `ensure` / `_begin_under_lease`
/ `_rearm_under_lease` / `_guarded`, `llm/reconciler.py` `_candidates`, `llm/cancel_outbox.py`
`adopt_confirmed_cancels` — which already owns the A0-D fix1 AD-11 completion race).
`S/` = `src/microdrama/`, `M/` = `migrations/`, `X/` = `tests/`.

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
| 0035 | `0035_v3_fence_quarantine.sql` | The `jobs` fence-input CHECK (V3 jobs must carry a well-formed `expected_content_revision`) and the `stale_artifacts` evidence table with its guards |

No other migration is needed: the lease columns A3 relies on already exist
(`jobs.lease_owner/lease_expires_at/heartbeat_at`, `M/0001…sql:87-89`), cancel reasons live in the
existing `jobs.outcome` jsonb (`M/0001…sql:91`), **phase A adds no queue lanes** (spec §4), so
the queue CHECKs on jobs (`M/0001…sql:77`) and reservations (`M/0003…sql:71`) stay byte-identical,
and worker-name ownership (§5.1, N3-9) is a session advisory lock — no DDL.

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
A3 adds the SQL backstop A1's Python validation lacked.

Changed CHECK beside the old one — the only constraint A3 touches on an existing table (N3-1;
the v1.0 regex form accepted digit strings, JSON nulls and unbounded integers):

```sql
-- OLD (M/0001_foundation.sql:72-105): no constraint between work scope and input.
--      A1's 0031 added track/extension_id/logical_work_id/replaces_job_id with CHECKs
--      binding them to each other, but nothing binds a V3 job's input to a fence value.
-- NEW (0035) — for V3 rows: a present, non-null JSON *number* in integer form, within
--      the track revision's supported range (int4 — the domain of every track's
--      content_revision column). Every malformed shape evaluates to FALSE explicitly,
--      never to SQL NULL (a NULL CHECK result passes):
ALTER TABLE jobs
  ADD CONSTRAINT jobs_v3_fence_input CHECK (
    track IS NULL                                            -- V1 branch, unconditional
    OR (
      input IS NOT NULL
      AND input ? 'expected_content_revision'                -- missing key   -> FALSE
      AND jsonb_typeof(input -> 'expected_content_revision') = 'number'
                                                             -- JSON null / string / boolean -> FALSE
      AND (input ->> 'expected_content_revision') ~ '^[0-9]+$'
                                                             -- fractional / negative forms -> FALSE
      AND (input ->> 'expected_content_revision')::numeric <= 2147483647
                                                             -- overflow past int4 -> FALSE
    )
  );
```

- `track IS NULL` is every V1 job (A1 §2.4): the constraint passes trivially for all existing
  rows — the A-T16 upgrade test asserts it on a populated V1 database.
- The int4 bound also protects A1's `track_waits` reads (`(input->>'…')::bigint`, A1 §2.4): every
  admitted value fits both int4 and bigint. Booleans and strings are rejected by `jsonb_typeof`
  even when their text form looks numeric; jsonb normalises exponent forms (`1e2` → `100`) so an
  integer-valued number in any JSON spelling is admitted, fractional-valued ones never.
- Range and scope correctness are still validated in Python at enqueue (§3.2, pydantic `int`) —
  the CHECK is the write-boundary backstop that a V3 row can never exist without a well-formed
  fence value, mirroring A0's 0027 `defer_reason` CHECK pattern (A1 §3, ruling 2).
- **Direct-SQL rejection tests** (N3-1, binding): INSERT/UPDATE attempts on `track`-bearing rows
  are refused for **missing, JSON null, string (including digit strings), boolean, fractional,
  negative and overflowing** values — see the A-T16 row in §9.
- No index is added: the fence resolves its track rows through existing unique keys
  (`season_tracks.season_id UNIQUE`, `episode_tracks.episode_id UNIQUE` — A1 0030;
  `season_extensions` PK), one point lookup per validated job (plus the one ancestor-row lock
  §3.1 adds for episode/extension scopes).

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
  -- N3-4: the v1.0 CHECK (actual > expected) could not represent a cancelled result whose
  -- expected and actual revisions are EQUAL -- a result that must not be installed because
  -- its scope was cancelled, at unchanged revision. Equality rows exist only for that
  -- cancellation path; strict inequality remains the stale-work evidence.
  CHECK (actual_content_revision >= expected_content_revision),
  CHECK (actual_content_revision > expected_content_revision
         OR reason = 'cancelled_operation_result'),
  reason                    text NOT NULL CHECK (reason IN ('stale_content_revision',
                                   'cancelled_operation_result')),
  created_at                timestamptz NOT NULL DEFAULT now()
);
-- One evidence row per (job, operation): a replayed collector must not duplicate it.
CREATE UNIQUE INDEX stale_artifacts_one_per_job_operation ON stale_artifacts
  (job_id, COALESCE(operation_id, '00000000-0000-0000-000000000000'::uuid));
CREATE TRIGGER stale_artifacts_append_only BEFORE UPDATE OR DELETE ON stale_artifacts
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
-- 0026-style DO loop over ARRAY['stale_artifacts']: statement TRUNCATE refusal +
-- INSERT/UPDATE integer-number guard (catalog tests then cover it automatically).
```

Semantics: append-only evidence, never current content (spec §7.1 "quarantined evidence: job,
operation, artifact refs, expected vs actual revision"). `reason` distinguishes the two cases the
table now carries: `stale_content_revision` (actual > expected — the result lost the revision
race) and `cancelled_operation_result` (the scope was cancelled while the operation ran; the
revisions may be equal — §4.1). `receipt_refs` makes the money trail queryable from the same row
(money is accounted normally, §3.4). The scope columns mirror the job's work scope so A5's
recovery screens can group by season/episode/extension without joining `jobs.input`.

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
class StaleContentRevision(Conflict):                # N3-8: Conflict -> HTTP 409 (S/contracts/errors.py:89)
    code = "STALE_CONTENT_REVISION"

class ScopeCancelled(Conflict):                      # N3-4: also 409; cancellation, not staleness
    code = "SCOPE_CANCELLED"

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
    """Lock the ancestor chain in the §6 order — #2 season_tracks SHARE first, then
    the resolved fence row (#3 episode_tracks, or #2 season_extensions) SHARE — and
    hold it through the caller's canonical mutation. Rejects a cancelled scope or
    ancestor (cancelled_at set on any locked row) with ScopeCancelled, INDEPENDENTLY
    of revision equality (N3-4: cancellation sets no revision bump, so revision
    equality alone cannot close admission). Then compares content_revision on the
    fence row: returns the current revision when current == expected; raises
    StaleContentRevision when actual > expected (stale — the caller takes the
    quarantine path) and Conflict when actual < expected (a fence value from the
    future: corruption, refuse)."""

def fence_classify(tx: Tx, scope: FenceScope, *, expected: int) -> str:
    """N3R2-2: the recovery arm of the same ordered lock take. Locks the identical
    ancestor chain in the identical §6 order and CLASSIFIES instead of raising —
    'current' (actual == expected), 'stale' (actual > expected) or 'cancelled'
    (cancelled_at on the scope or any ancestor) — because recovery must settle
    exactly the stale/cancelled conditions fence() rejects: the recovery paths
    (§3.2 settle row, §4.1) can never go through the throwing helper. Authority
    inspection only, separated from admission rejection: the classification
    commits evidence and accounting; only current execution may install content."""

def scope_cancelled(tx: Tx, scope: FenceScope) -> bool:
    """Plain unlocked read of the same cancelled_at chain — admission checks only,
    never a guarantee (§7)."""

def current_revision(tx: Tx, scope: FenceScope) -> int:
    """Plain unlocked read — admission checks only, never a guarantee (§7)."""

def record_stale(tx: Tx, *, job_row, operation_id: UUID | None, artifact_refs: list,
                 receipt_refs: list, expected: int, actual: int, reason: str,
                 now: datetime) -> UUID:
    """Append the stale_artifacts row; idempotent on (job_id, operation_id).
    reason is 'stale_content_revision' (actual > expected) or
    'cancelled_operation_result' (the cancellation path, actual >= expected — §4.1)."""
```

**Why SHARE (spec §6: "fence reads take a SHARE lock on the track (2/3); amendments take FOR
UPDATE"):** an ordinary re-read can observe revision N, then an amendment commits N+1 before the
worker writes (AC-15's exact objection). The SHARE lock blocks the amendment's `FOR UPDATE`
bump — and therefore its whole apply transaction — until the mutation's transaction commits, so
the read-validate-write is atomic against every amendment. The same lock now also serialises
against `cancel_season`/`cancel_episode` (their §6 chain takes the track rows FOR UPDATE): a
fence holder cannot interleave with a cancellation sweep, which is what makes the
cancellation check race-free (N3-4). Two fence readers never block each other. **Invariant:
`fence()` is the first lock a canonical-mutation transaction takes** (§7 audits every call site
against it).

### 3.2 Every call site — admission vs observation/settlement (N3-3)

N3-3's split governs this whole table: **observation/settlement of an existing operation** is a
different permission from **admission of new work**. Stale or cancelled recovery may observe,
record legal results, preserve evidence and settle accounting; it may **never** create, rearm or
submit work, install content, or enqueue continuations. The permission is a property of the entry
point used, not of a runtime flag.

| `file:function` | Placement |
|---|---|
| `S/core/jobs.py:enqueue` (`:353-438`) | **Enqueue — the front door (admission).** A1's N1-9 work-scope validation branch gains: `track` set → `expected = payload.expected_content_revision` (missing/malformed → `SchemaInvalid`; the 0035 CHECK is the SQL backstop) → `fence(tx, scope, expected)` **before** the INSERT (`:389-414`), SHARE held through it. `fence` here also rejects a cancelled scope or ancestor (`ScopeCancelled`) — a concurrent enqueue after a cancellation sweep cannot pass on revision equality (N3-4). Every continuation reaches the fence through this one seam, because every enqueue does: `rendering/routing.py:725`, `:944`; `review/service.py:464`, `:1267`, `:1321`; `review/intake.py:740`, `:852`; `qa/repairs.py:1259`, `:1304`, `:1439`; `core/api.py:119`; `pipeline/runner.py:186`; the scheduler's `_enqueue`. Inside an A1 decision transaction the SHARE lands on a row the transaction already holds FOR UPDATE — a no-op in one transaction, order preserved |
| `S/core/jobs.py:claim` (`:478-550`) | **Admission.** After the in-flight quarantine checks (`:503-506` for RETRY_WAIT, `:520-523` for QUEUED) and before the RUNNING move (`:525-537`): for a V3 candidate, the plain-read pre-checks (§7 — never a lock): `scope_cancelled` → the job is finished `CANCELLED` with `error_code='SCOPE_CANCELLED'`, `outcome={kind:'CANCELLED', reason:'scope_cancelled'}` via `_move`; `current_revision` — `actual > expected` → the job is finished `CANCELLED` with `error_code='STALE_CONTENT'`, `outcome={kind:'CANCELLED', reason:'stale_content_revision', expected, actual}` (the map admits QUEUED→CANCELLED and RETRY_WAIT→CANCELLED, `S/contracts/states.py:102`, `:115`); either way the next candidate is considered — the handler never runs. Already-terminal rows (an amendment's `cancel_in` won the race) are skipped silently. **WAITING_EXTERNAL candidates lease normally** (`:512-514`): polling *is* observation of in-flight operations; its result is fenced at collection |
| V3 LLM submit — `LlmStep` admission seam | `G/llm/step.py` `ensure` always enters `_begin_under_lease` before inspecting operation state, and its normal path rearms NOT_FOUND/REFUSED_PRELAUNCH through `_rearm_under_lease` — both create/rearm work. A3 therefore gives `LlmStep` an **injected admission callable** (the V3 composition passes `fence`): invoked *inside* `_begin_under_lease`'s and `_rearm_under_lease`'s own transactions — at the top, **before `_guarded`** — so the two exact integration points are these transactions' entry, with `provider_ops.begin` / `provider_ops.resubmit_allowed` still under the guard (A0R-1 unchanged). Fence SHARE (#2/3 incl. ancestor) → `_guarded` job SHARE (`lease_guard`) → begin/rearm. Stale → `StaleContentRevision` before any provider call, no `begin`, no money; cancelled scope → `ScopeCancelled`; either way the job finishes `CANCELLED` (`STALE_CONTENT` / `SCOPE_CANCELLED`) — never a generic Failed. **Routing is decided before this seam (N3R2-2):** a job already known cancelled or stale-recovering is routed to the settle row below and never enters `ensure`'s admission call |
| V3 LLM recovery — `LlmStep.settle_under_recovery` (new, settlement-only; N3R2-2) | The **observation/settlement entry** N3-3 requires: drives the same state dispatch as `ensure` for SUBMITTED/RUNNING (poll), SUCCEEDED/FAILED/CANCELLED (record + evidence), UNKNOWN (surface for the operator) — but **never through `_guarded`**: that guard requires a RUNNING job with a live lease (`G/llm/step.py:439-444`; `S/core/jobs.py:621-654`), which a CANCELLED job can never satisfy and a stale NEEDS_RECONCILIATION job cannot either (its RESUME is refused, next-but-one row, while A0 reaches reconciliation authority through RESUME, `G/llm/reconciler.py:171-179`). Instead **ordered scope locking and authority inspection are separated from admission rejection**: the settle arm locks and revalidates the job/operation **under an audited recovery principal** — not the cancelled worker's lease, never restoring content authority — classifying the scope through `fence_classify` (§3.1), not the throwing `fence()`, whose rejections are exactly the conditions recovery must settle. The collector commits evidence and accounting from the resulting current/stale/cancelled classification; **only current execution may install content** — and this path is never current execution. Structurally never calls `_begin_under_lease`, `_rearm_under_lease` or `_submit`: a NOT_FOUND operation in recovery is recorded and left, never rearmed (N3R2-1). Used by §4.1's cancelled-job recovery and by stale-job settlement; its transaction shape is audited in §7 |
| V3 paid submit | The paid submit step (the V1 shape is `rendering/comfy_jobs.py:611-623`) fences **in the same transaction as its operation begin, under `lease_guard`** — A0's pattern (§5.1: every operation write under the guard). Order inside the transaction (N3R2-3): `fence()` SHARE (#2/3) → `lease_guard` job SHARE (`S/core/jobs.py:648`) → **the V3 transaction-taking begin/rearm path: #6 serialization/operation locks precede #7 reservation locks, and reservation eligibility is validated atomically before the admission commits** (the spec's single order includes provider advisories, `phase-A-spec.md` §6 — see the §7 audit, which covers begin and rearm separately). V1 entry points are preserved: `provider_ops.begin`/`resubmit_allowed` keep their shape for V1 callers; the V3 composition drives its own begin/rearm path — **rearm does not inherit `begin`'s reservation SHARE/validation chain** (`resubmit_allowed` re-enters only the advisory serialization and the operation lock, `S/core/provider_ops.py:345`, `:354-360`, unlike `begin`'s `:195-215`), so the V3 rearm path establishes its own #6→#7 order **and** its own reservation-eligibility validation before the rearm commits. Stale/cancelled → no begin, no provider call, no money; the job finishes `CANCELLED`/`STALE_CONTENT` or `/SCOPE_CANCELLED` |
| **The V3 collector** — `S/core/v3_collect.py` `collect_paid_result(...)` (new, N3-6) | One named collector with **one caller-owned transaction**. Provider bytes are prepared **outside** it (fetch + verify, the `_collect_outputs` discipline, `S/rendering/comfy_jobs.py:913-935`); the transaction itself is entered through **ordered `fence_classify` locking, never the throwing `fence()` (N3R3-1)** — a stale or cancelled result is the collector's *normal input*, so the entry lock classifies it instead of rejecting it before quarantine can commit. A single transaction: `fence_classify` SHARE on the identical §6-ordered ancestor chain (§3.1) → **branch on the classification** — **current worker execution** then validates its lease (`lease_guard` job SHARE); **recovery** (a stale or cancelled job, or a caller that is not the live worker) revalidates the job/operation under the **audited recovery principal** under the same locks, **without requiring a worker lease** — then `record_result` (operation UPDATE) → asset registration through the existing transaction-taking seam `rendering/comfy_assets.persist_output(tx, …)` → and, fenced on the same read, either installation/acceptance (**current worker execution only**) or `record_stale(...)` (stale or cancelled scope — quarantine and accounting committed **without installation**) — all inside it. **Acceptance lives only here**: a V3 asset never becomes `ACCEPTED` outside this transaction (V1 `_accept_asset`, `S/pipeline/handlers.py:82-85`, is untouched). Money settlement (`_settle_if_needed` semantics, `:965-1070`) is invoked with the recorded result after commit and is idempotent — **crash recovery between result persistence and settlement** re-derives settlement from the committed operation state on the next poll/recovery pass (exactly-once per canonical receipt, A2 §3); §4.1's discovery includes exactly this terminal-but-unsettled operation (N3R2-4). A crash before the transaction commits leaves the operation SUBMITTED/RUNNING — the next poll re-fetches and re-collects. V1's three-transaction orchestration (collect-outputs tx `:923`, result tx `:899`, acceptance tx `handlers.py:82`) is preserved unchanged; V3 composes the same helpers inside its one transaction |
| Continuations | Covered by the `enqueue` seam: the finishing handler stamps the continuation's `expected_content_revision` with the fence value it validated under its own held lock, and the enqueue fence re-validates it (SHARE → INSERT) in the continuation's own transaction. A quarantined or cancelled collector never enqueues (§3.4) |
| Reconciliation adoption — `resolve_reconciliation` (`S/core/jobs.py:752-862`) | Transitions unchanged (NEEDS_RECONCILIATION only, `:785`; RUNNING/SUCCEEDED/FAILED, `S/contracts/states.py:117`). **Discovery is NOT inherited from A0's in-flight-only candidate scan (`G/llm/reconciler.py:126-128` excludes terminal operations): the §4.1 recovery pass independently discovers stale NEEDS_RECONCILIATION jobs with unresolved operations or terminal operations whose required evidence, accounting or job resolution remains incomplete (N3R4-1).** For V3 rows the ordered scope lock is **`fence_classify` SHARE, never the throwing `fence()` (N3R3-1)** — a stale job is reconciliation's *normal input*, and the throwing helper would reject it before the resolution could record anything — taken **before** `_lock` (`:784`), track before job (§7), under the audited recovery principal (no worker lease). **Stale NEEDS_RECONCILIATION operations are routed into the §4.1 recovery arm before RESUME/admission (N3R3-1):** the SUCCEEDED resolution (`:811-843`) on a **stale** job certifies the operations (recorded successes) and commits quarantine and accounting **without installation** — `outcome.quarantined=true` and `record_stale(...)` instead of granting content authority — taking the **existing NEEDS_RECONCILIATION→SUCCEEDED transition** (legal, `S/contracts/states.py:117`; OQ-3). **RESUME (`:796-810`) is not offered to stale jobs** (N3-3: a resumed stale handler could only re-hit the fence at its first mutation — admission in disguise); a stale job's work continues, when justified, through a **replacement job** enqueued at the current revision (A1 `replaces_job_id`), which passes its own admission fence. Current (non-stale) NEEDS_RECONCILIATION jobs RESUME exactly as V1. The A0 auto-reconciler adopts results through the same rule: settle first, classify at the ordered lock, install only when current |
| Cancelled-job recovery (§4.1) | The authorised V3 path for operations still unresolved on CANCELLED jobs — settlement-only (N3-2/N3-3), spelled out in §4.1 |
| Amendment consumers (A4) | `rewind_for_amendment`'s sweep and A4's apply call `cancel_in` per job, id order, over the **enumerated cancellable statuses** (§6.1), under their already-held track FOR UPDATE (§4, §7) |

Admission is deliberately a **plain read**, not a SHARE lock: the claim transaction already holds
the job row FOR UPDATE (`:498`, `:511`), so a track lock there would order #5 before #2/3 — the
exact inversion the spec's lock table forbids ("a worker completion that needs both track and job
locks takes the track first", §6). Correctness does not depend on the admission read: READ
COMMITTED sees either N or N+1, never torn; a job admitted at N that goes stale (or whose scope
is cancelled) before its first mutation is caught by that mutation's `fence()`, and A-T12a's race
test proves no stale write ever lands as current content. (Moving the SHARE into `claim` would
also deadlock an amendment's track→job chain against the claim's job→track chain — rejected.)

### 3.3 Season-scope and episode-scope work

The fence resolves exactly one track row per job — the same COALESCE order as A1's `track_waits`
fence column (`A1 §2.4`: extension fence for extension jobs, else episode fence, else season
fence) — and locks the **ancestor chain** in §6 order so the cancellation check (N3-4) is taken
under the same locks that serialise it against `cancel_season`:

| Job shape | Fence row | Locks taken (in order) |
|---|---|---|
| `extension_id` set (planning work on an extension scope) | `season_extensions.content_revision` | #2 `season_tracks` SHARE (ancestor) → #2 `season_extensions` SHARE |
| `episode_id` set (production/release work on an episode) | `episode_tracks.content_revision` | #2 `season_tracks` SHARE (ancestor) → #3 `episode_tracks` SHARE |
| season only (planning/release work on the season) | `season_tracks.content_revision` | #2 `season_tracks` SHARE |

**An episode job never fences on the season track for its *revision*** — the ancestor lock is
taken for the cancellation check only; the revision compared is always the resolved fence row's.
A season-scope bump alone leaves episode work current by design: an amendment that affects an
episode bumps that episode's track inside its closure (A4 §7.3 step 1), and one that does not
must not stop unrelated in-flight work — the same scoped-invalidation principle as AR-3/AR-4
(preserve unrelated approved releases). The corollary obligation sits with A4: **an amendment's
computed closure must bump every episode track whose work it invalidates.** Flagged as OQ-1.

### 3.4 Quarantine while money accounts normally

A stale (or cancelled-scope) result is never installed as current content (spec §7.1), but nothing
about it is discarded or left unaccounted:

1. **Outputs register** (assets/rows with hashes and object keys) — they are evidence, and the
   provenance chain stays intact.
2. **A `stale_artifacts` row appends** in the same transaction, with `artifact_refs`,
   `receipt_refs`, expected vs actual revision and the distinguishing `reason` (§2.2): strict
   inequality for the revision race, `cancelled_operation_result` — revisions possibly equal —
   for the cancellation path (§4.1).
3. **Money is still accounted normally.** Settlement and receipt posting are not canonical
   content mutations and run unconditionally: GPU-style `_settle_if_needed`
   (`rendering/comfy_jobs.py:965-1070`), `_post_charge`/`check_overrun` under A2's hierarchy
   locks (A2 §3.3), LLM evidence in `llm_invocations` (unmetered — no charge, A0 §5.5.5).
   Reservation release keeps its existing rule — refused while operations are in flight
   (`S/budget/service.py:526-539`) — so exposure is retained until reconciliation settles.
4. **No continuation is enqueued from quarantined or cancelled work** (the continuation seam
   re-fences anyway, but the collector simply does not enqueue).
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
(AR-4). Amendment sweeps (A4 §7.3 step 3, §6 `cancel_season`) skip those rows; the sweeps
enumerate exactly the cancellable statuses (§6.1).

**Lease revocation and the stale worker.** `_move` clears `lease_owner`, `lease_expires_at` and
`heartbeat_at` (`:333-338`), so a RUNNING holder loses its lease in the same commit that cancels
the job. The stale worker stops under the existing lease guard: its next `_holds_lease` check
(`:621-627`) fails because the row is no longer RUNNING — `lease_guard` (FOR SHARE, `:648`)
raises `Conflict("lease lost")`, and `finish` (`:677-679`) and `heartbeat` (`:605-606`) likewise.

**How each V3 path converts that into control flow (N3-8, N3R2-5).** A raw `Conflict` is **not**
automatically `LlmLeaseLost`: A0 performs that conversion inside `G/llm/step.py` `_guarded`
(`lease_guard` Conflict → `LlmLeaseLost`), so LLM steps stop without a subsequent ordinary
`finish` — the worker's guarded writes end and its durable operation stays in flight. The V3
**paid** collector and submit perform the same conversion at their own `lease_guard`/`finish`
call sites: lease loss → stop, no finish, no further provider call. This conversion must happen
**inside the V3 handlers**, because the generic runtime arm (`S/workers/runtime.py` `_execute`,
`Failed(error_code=type(error).__name__)` at `:249` + finish) would otherwise turn the Conflict
into an ordinary Failed — exactly the "finish after ownership loss" A0 forbids. **Handler guards
alone cannot close the window (N3R2-5):** A0's runtime calls `_finish` *after* the handler
exception block (`G/workers/runtime.py:298`), so a cancellation landing between handler return
and runtime completion escapes handler-local conversion — and ordinary `finish` has no CANCELLED
outcome at all (`S/core/jobs.py:214-263`). V3 lease-loss handling is therefore specified **at
the runtime completion/defer boundaries as well as the handler guards**: the boundary re-checks
ownership and takes the same stop-without-finish path on loss — never converting it to `Failed`,
never finishing what it no longer owns. Equally, stale detection inside a collector **never
aborts the evidence transaction**: the collector commits registration + `record_stale` first,
then finishes the job `CANCELLED`/`STALE_CONTENT` through the legal transition — the quarantine
evidence survives the control-flow change. **Self-cancellation** (the worker's own scope was
cancelled through `cancel_in`) uses `cancel_in`, then the **existing stop-without-finish control
flow**: **quarantine evidence is committed before stopping**, and **no other outcome variant is
introduced** — observation only, §4.1 settles.

A provider call already in flight cannot be recalled — that is what reconciliation is for:

**External operations go to the authorised reconciliation path** (spec §7.4): `llm.subscription`
operations through A0 §5.3 — the auto-reconciler (NEEDS_RECONCILIATION jobs) **and the cancel
outbox's `adopt_confirmed_cancels`** (`G/llm/cancel_outbox.py`), which already owns the
completion race (A0-D fix1 AD-11: a gateway answering the cancel with a terminal state settles
the operation to what actually happened, job stays cancelled, metering kept); paid kinds through
`resolve_reconciliation` (`S/core/jobs.py:752-862`) for NEEDS_RECONCILIATION jobs and through
§4.1 for CANCELLED jobs; render's UNKNOWN handling `rendering/comfy_jobs.py:803-862`. Exposure
and receipts are retained — `cancel_in` touches no `provider_operations` row, no reservation, no
charge.

**LLM cancellation forwarding (A0 §5.4).** A0 extends `cancel()` so the cancel transaction sets
`llm_invocations.cancel_requested_at_ms` and emits `llm.cancel_requested` for in-flight
`llm.subscription` operations; A3's `cancel_in` extracts that into one private helper
(`_forward_llm_cancellation(tx, row)`) used by both entry points, so an amendment-driven cancel
requests the gateway cancel too — appended in the caller's transaction, posted by the outbox
consumer after commit. `CANCELLED` is still recorded on the operation only after the gateway
confirms (A0 §5.4); until then the job shows the cancelling state.

### 4.1 Cancelled-operation recovery — the authorised V3 path (N3-2)

v1.0 implied recovery moves a CANCELLED job to SUCCEEDED. That path does not exist —
`resolve_reconciliation` requires NEEDS_RECONCILIATION (`S/core/jobs.py:785`), the A0 reconciler
selects only that status (`G/llm/reconciler.py` `_candidates`), and CANCELLED has no outgoing
transition (`S/contracts/states.py:119`). A3 therefore adds an **explicit V3 recovery dispatcher
over existing operations**, with per-kind legal transitions and provider evidence (N3R2-1),
instead of widening any transition:

- **Discovery (N3R2-4).** A V3-only sweep — `track IS NOT NULL` jobs with status CANCELLED that
  still own `provider_operations` that are **unresolved** (PENDING_SUBMIT / SUBMITTED / RUNNING /
  UNKNOWN — the same states `track_waits`'s operation branch counts) **or terminal with an
  incomplete aftermath**: discovery also includes terminal operations whose required evidence,
  accounting settlement or cancellation annotation is incomplete. The **durable completion
  predicate** — operation terminal AND its `stale_artifacts` evidence row present when the
  result is not installed AND settlement complete AND `outcome.settled_after_cancel` recorded —
  is defined on the operation row itself, and the pass retries it idempotently. This closes the
  crash case v1.1 could not see: a worker dying immediately after the result transaction commits
  a terminal operation that no in-flight-only scan (this dispatcher's v1.1 form, and A0's
  adopter, `G/llm/cancel_outbox.py:90-160`) would ever select again — and the terminal job can
  never be re-claimed, so this pass is its only discoverer. Driven by the same audited
  operator-command surface as `resolve_reconciliation` and by the recovery pass; V1 rows are
  never selected. **Not CANCELLED-only (N3R3-1):** the dispatcher also serves **stale
  NEEDS_RECONCILIATION operations routed in by §3.2's reconciliation row before
  RESUME/admission** — same recovery arm, same audited principal, same `fence_classify` entry.
  A successful stale reconciliation takes the existing NEEDS_RECONCILIATION→SUCCEEDED transition
  with `outcome.quarantined=true` (OQ-3); a CANCELLED job's settlement keeps the stays-CANCELLED
  rule below. **Completion predicates are defined separately (N3R4-1):** a CANCELLED job's
  operation completes with `settled_after_cancel`; a **stale NEEDS_RECONCILIATION** operation
  completes with quarantine/accounting completion **and its legal job resolution** — the
  `settled_after_cancel` predicate never describes stale reconciliation. **The recovery pass
  discovers both populations independently — it does not depend on routing or on A0's
  in-flight-only candidate scan — and a test exercises automatic rediscovery after a crash between
  result commit and aftermath completion.**
- **Authority (N3R2-2).** Recovery never runs under `_guarded` — that guard requires a RUNNING
  job with a live lease (`G/llm/step.py:439-444`; `S/core/jobs.py:621-654`), which a CANCELLED
  job cannot satisfy, and a stale NEEDS_RECONCILIATION job cannot either (its RESUME is refused
  in §3.2's reconciliation row, while A0 reaches reconciliation authority through RESUME,
  `G/llm/reconciler.py:171-179`). **Ordered scope locking and authority inspection are
  separated from admission rejection:** the dispatcher locks and revalidates the job/operation
  **under an audited recovery principal** — without the cancelled worker's lease, never
  restoring content authority — classifying the scope through `fence_classify` (§3.1) rather
  than the throwing `fence()`, whose rejections are exactly the conditions recovery must settle.
  The collector commits evidence and accounting from the resulting current/stale/cancelled
  classification; **only current execution may install content** — and this path is never
  current execution. **Routing into this path is defined before `ensure`'s admission call**
  (§3.2): a job already known cancelled never enters an admission arm, and a stale
  NEEDS_RECONCILIATION job is routed in **before RESUME** (§3.2's reconciliation row) — no
  recovery caller (collection, reconciliation adoption, this dispatcher) is ever rejected by the
  throwing `fence()`, whose rejections are exactly the conditions this arm settles.
- **Per-kind legal transitions (N3R2-1) — evidence-backed only, through `record_result`.**
  - **Paid kinds** — the dispatcher's settlement arm
    (**`JobService.settle_cancelled_operations(tx, …)`**: an explicit settlement body over
    provider evidence, *not* a lift from `resolve_reconciliation`, which only checks recorded
    operations and changes job status, `S/core/jobs.py:790-862`). SUBMITTED / RUNNING →
    SUCCEEDED / FAILED / CANCELLED per the provider's authoritative answer. **PENDING_SUBMIT
    uses NOT_FOUND only with authoritative no-execution evidence; work the provider found
    records its actual state** — the paid `PENDING_SUBMIT→CANCELLED` edge v1.1 permitted is not
    legal: A0 restricts it to `llm.subscription` (`G/core/provider_ops.py:364-370`). UNKNOWN
    without recoverable external evidence stays UNKNOWN for the operator, exposure held.
  - **`llm.subscription`** — A0's `adopt_confirmed_cancels` (above), **extended with V3
    evidence hooks and the missing recovery branches**: as-is it selects only in-flight states,
    skipping PENDING_SUBMIT with DONE/REFUSED, missing gateway records and UNKNOWN
    (`G/llm/cancel_outbox.py:90-160`), and its completion-race branch keeps metering but
    discards the structured output, creating none of A3's promised quarantine evidence. The
    extension adds those branches and, on the completion race, preserves the AD-11 settlement
    (metering kept, job stays cancelled) **and appends the `stale_artifacts` evidence row**
    (`cancelled_operation_result`) for the uninstalled result instead of discarding it.
  - Both arms **preserve CANCELLED**: the job stays CANCELLED, the settlement written to
    `outcome.settled_after_cancel = {state, at}` — settlement metadata recorded, no status
    transition, so no V1 terminal transition is widened and `J.CANCELLED`'s empty transition set
    stands — and both arms **never rearm or submit**.
- **Permission (N3-3).** The path is observation/settlement only: it records legal results,
  preserves evidence, settles accounting — it never creates, rearms or submits work, never
  installs content, never enqueues continuations. On the LLM side it drives
  `LlmStep.settle_under_recovery` (§3.2), never `ensure`'s admission arms.
- **Evidence and settlement.** Outputs register, receipts post exactly-once
  (`_settle_if_needed` semantics), and a result that is not installed — the scope is cancelled,
  stale, or both — appends `record_stale(reason='cancelled_operation_result', …)`; the 0035 CHECK
  extension (§2.2) exists exactly for its equal-revision case. Operation success never restores
  content authority: `track_waits`'s stale CTE and the scope's CANCELLED wait keep describing
  the scope; once the operation settles, the BLOCKED (reconcile) row clears and the CANCELLED
  wait remains the visible truth.

**A-T12a's corrected expectation** (§9): cancel mid-flight → lease revoked, worker stops without
finishing, operation untouched → the operation later settles through this path (the V3-extended
`adopt_confirmed_cancels` for `llm.subscription`, `settle_cancelled_operations` for paid kinds)
→ **job stays CANCELLED** with `outcome.settled_after_cancel`, evidence rows for uninstalled
results, money accounted, `track_waits` block cleared. (The SUCCEEDED+`outcome.quarantined=true`
outcome remains the correct expectation only for *stale NEEDS_RECONCILIATION* jobs, whose
transition is legal — OQ-3.)

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
  `S/workers/runtime.py:103-119`). Default `worker-<queues joined by '+'>`.
- **Enforced name ownership and the incarnation fence (N3-9, N3R3-3).** The configured worker
  **name** (`WorkerDeployment.name`) is separated from a **process-unique lease identity** — an
  incarnation token minted at startup and recorded with every lease the process holds: `claim`,
  `lease_guard`, `heartbeat`, `finish` and `defer` validate **that incarnation**, not the
  reusable worker string (today `_holds_lease` authenticates only `lease_owner == worker` and
  expiry, `S/core/jobs.py:621-626`), so a disconnected old process can never act on its
  same-name replacement's lease. When `--queues` or `--name` is passed, the worker opens one
  dedicated session connection and takes
  `pg_try_advisory_lock(hashtextextended('md-worker-name:' || <name>, 0))`; on failure it exits 2
  naming the holder. The lock is held for the process lifetime and released by disconnect (crash
  included), so a replacement process with the same name starts as soon as the old one is dead —
  and because a blocked handler can outlive the dedicated connection while the replacement
  acquires the name, **ownership-loss checks run before every new claim and every guarded
  write**, not only on the janitor cadence: on a failed check the worker exits non-zero rather
  than run unowned (the A6b ownership-loss discipline, applied to the name lock). With the fence
  in place **two live processes can never act on one `lease_owner`'s leases** — duplicate-name
  refusal is enforced by A3 itself, not promised through A6c configuration checks. No DDL is
  needed (§1).
  **Without either flag the entry point is byte-identical to today** — name `staging-worker`
  (`S/api/worker.py:78`), no lock: the documented no-flag V1 behaviour is preserved.
- **The production process set** (spec §4; A6c runs it under `--composition production`): one
  process per lane — `--queues production`, `--queues publication`, `--queues community` — each
  with the lane's slot count from the composed deployment. Scaling a lane adds processes with
  **distinct names** (`--name worker-community-2`, …): the per-name lock makes a shared identity
  impossible, and `claim` is FOR UPDATE SKIP LOCKED (`S/core/jobs.py:500`, `:514`), so same-lane
  processes are safe against each other anyway.
- **A-T8's isolation proof:** today one process visits every queue in declaration order
  (`S/workers/runtime.py:185-197`), so a 60 s production handler delays the publication claim of
  the same cycle. Separate processes are structurally independent — the acceptance test
  (§9) measures a publication job completing while the production process sleeps.
- **Test-only child bootstrap (N3-10).** The bare CLI composes fixed handlers
  (`S/api/worker.py:76-78`), so parent-process fake registration cannot reach CLI subprocesses.
  A3 adds a guarded test seam: `api/worker.py` accepts a world factory through
  `MICRODRAMA_TEST_WORKER_WORLD` (a `module:attr` reference), honoured only when the offline/test
  settings admit test worlds — the same explicit test-world injection `build_production_world`
  refuses (spec §2.7); production never reads it. Children booted this way run the **real**
  argument parsing, name lock, runtime loop, janitor and SIGTERM handling against the shared test
  database. The fake provider's journal (submits, results) is persisted by the fixture inside the
  test database, so provider state — including submit counts — survives `os._exit(1)`/SIGKILL of
  a child. This bootstrap exists for A-T8/A-T18; it registers no production handler.

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
| `cancel_season(season, expected_revision, reason)` | Operator (human session + CSRF) | season / `season_tracks.revision` | `require_workflow('v3')` (A1 §7); track not already cancelled; revision match (`StaleRevision` on mismatch) | `season_tracks.cancelled_at` (terminal, OQ-2); **every** `episode_tracks.cancelled_at` under the season (id order); `cancel_in` on every V3 job in the season scope **in a cancellable status** (§6.1, id order, all tracks) | none enqueued | `track.cancelled` (season + per episode) + each job's own `job.cancelled` (from `_move`, `S/core/jobs.py:348`) | idempotency key |
| `cancel_episode(episode, expected_revision, reason)` | Operator (human session + CSRF) | episode / `episode_tracks.revision` | v3; track not cancelled; revision match | `episode_tracks.cancelled_at`; `cancel_in` on the episode's V3 jobs **in a cancellable status** (§6.1; production + release); season-track jobs untouched | none | `track.cancelled` + `job.cancelled` per job | idempotency key |
| `rewind_for_amendment(scope, to, amendment_ref)` | **System — amendment coordinator only** (A4; no route in A3, internal API, test-world drives A3's tests) | season or episode / `content_revision` + `revision` | coordinator context (A4 Confirm's revalidated impact hash); `to` a **legal backward edge for the scope** (§6.1 enumeration) — unsupported targets are rejected `NOT_AVAILABLE` before any write | the scope-specific backward edge of §6.1 (the actual state column named there); display `revision` +1 once per changed scope; `content_revision` bump only where the amendment's closure invalidates work in that scope; **fence the affected work**: `cancel_in` sweep of the scope's V3 jobs in cancellable statuses (§6.1) and queued continuations (id order) | none | `track.rewound`; `job.cancelled` per cancelled job | semantic `(scope, from, to, content_revision)` + `amendment_ref` |

Internal, not a command: the **admission self-fence** (§3.2, `claim`) — a system mechanism with no
actor. Both cancel commands are terminal (OQ-2 ruling: `cancelled_at`, surfaced as the CANCELLED
wait); the legacy `seasons.state` is never written for V3 (A1 §1). Money: nothing is released —
exposure and receipts stay until reconciliation (§4, §4.1).

### 6.1 `rewind_for_amendment` — scope-specific edges and the sweep (N3-7)

v1.0 said "backward planning edge on the scope's track" for season **or episode** scope — but an
episode track has no planning column (A1 §2.3: `episode_tracks` carries `production_state` and
`release_state` only). The command moves exactly one state column per scope, one legal backward
edge; **every other target is rejected `NOT_AVAILABLE` before any write** (A1 §5 step-1 preflight
shape):

| Scope | Column changed | Legal backward edges | Explicitly rejected |
|---|---|---|---|
| season (planning) | `season_tracks.planning_state` | `CAST_LOCKED→CASTING`, `CASTING→STORY_LOCKED`, `STORY_LOCKED→PLANNED`, `PLANNED→BIBLE`, `BIBLE→LOCKED`, `LOCKED→PROPOSED`, `PROPOSED→IDEA` | every forward target; every cross-chain target |
| season (release) | `season_tracks.release_state` | `LAUNCH_APPROVED→CALENDAR_PROPOSED`, `CALENDAR_PROPOSED→NOT_SCHEDULED` | anything at or past `RELEASING`/`COMPLETE` — published media is immutable (master §12.6.5) |
| episode (production) | `episode_tracks.production_state` | `AWAITING_REVIEW→DRAFTING`, `DRAFTING→EDITING`, `EDITING→RENDERING`, `RENDERING→DIRECTED`, `DIRECTED→PLANNED` | `APPROVED` as a target — approval invalidation is A4 supersession (`approval_supersessions`), never a rewind edge |
| episode (release) | `episode_tracks.release_state` | `PUBLISHING→SCHEDULED`, `SCHEDULED→UNSCHEDULED` | `PUBLISHED_VERIFIED` — published media is immutable |
| extension | `season_extensions.planning_state` | the season planning chain above | re-opening a closed extension (`closed_at` is never cleared by a rewind); episode-scoped targets on an extension scope |

An episode-scoped **planning** rewind is rejected outright (no such column), not silently mapped
onto the production column.

**Revisions.** Every changed scope's display `revision` advances exactly once, in the same
transaction. `content_revision` bumps **only where the amendment's computed closure invalidates
work in that scope** — A4 passes the closure and A3's primitive bumps the fence exactly on the
scopes A4 marks; an administrative edge that changes no content authority bumps no fence. A
scope in the closure that is not rewound still gets its `content_revision` bump through the same
primitive when A4 marks it (spec §7.3 step 1).

**The cancellation sweep.** `rewind_for_amendment` and both cancel commands sweep exactly the
**cancellable statuses — QUEUED, RUNNING, WAITING_EXTERNAL, RETRY_WAIT** (the statuses whose
`JOB_TRANSITIONS` set admits CANCELLED, `S/contracts/states.py:102-116`), in id order. Jobs in
NEEDS_RECONCILIATION are excluded: their recovery intent is durable, their operations keep
blocking `track_waits`, and §4.1 settles them observation-only. No A3 path calls `cancel_in` on
a broader, "every non-terminal" enumeration.

## 7. Lock audit (spec §6; A1 §9 hands over one open row)

The §6 table (A1 §9) governs. A1 §9 item 1 recorded the handed-over inversion: *"Worker
completion takes the job lock first (`lease_guard` `:648` FOR SHARE, `finish` `:677` FOR UPDATE),
while amendments take track → job. … this row hands A3 the required order (track before job)."*
**A3's resolution is structural: no A3 path ever takes a job lock and then a track lock.**
`finish`, `heartbeat`, `defer`, `requeue_expired` keep job-only lock sets; the paths that need
both take `fence()` (track SHARE) **first**.

**The provider-operation locks are real and are audited (N3-5).** v1.0 located advisory locks
"only in budget code" — wrong. `provider_ops.begin` (`S/core/provider_ops.py`) first locks a
linked reservation **FOR SHARE** (`:195-197` — #7-class, serialising begin with budget release),
then `_lock_linked` (`:121-125`) takes **blocking** `pg_advisory_xact_lock` per job then per
reservation (#6-class, serialising begins with each other), and only then inserts/reads the
operation (`:215`). `resubmit_allowed` (`:345`, `:354-360`) re-enters **only the advisory
serialization and the operation lock — it takes no reservation SHARE/ACTIVE-validation chain of
its own** (unlike `begin`, `:195-215`), so the V3 rearm path must establish its own
reservation-eligibility check before it commits (rows below). The claim that A3 "adds no
advisory locks and no class crossing exists" is withdrawn; the audit below covers the real
chains — and, for the V3 paths, corrects them (#6 before #7, N3R3-2).

Transactions A3 adds or touches:

| Transaction | Locks in order | Verdict |
|---|---|---|
| V3 `enqueue` (incl. every continuation seam) | (#1 idempotency when command-driven) → **#2 `season_tracks` SHARE (ancestor) → #2/#3 fence SHARE** → #5 job INSERT (`:389`) | conforms — track before job; cancellation checked under the same locks (N3-4); inside an A1 decision transaction the SHARE is absorbed by the already-held #2 FOR UPDATE |
| `claim`, V3 admission arm | #5 job FOR UPDATE SKIP LOCKED (`:498`, `:511`) → plain track reads, no lock (`scope_cancelled`, `current_revision`) → status write | conforms — no track lock at admission (§3.2); correctness anchored at the mutation fence |
| Fenced LLM submit (`LlmStep` admission seam, §3.2) | **#2/#3 fence SHARE (ancestor chain)** → #5 job SHARE (`_guarded`/`lease_guard`, `S/core/jobs.py:648`) → #6 job xact advisory (`_lock_linked`; LLM is unmetered — no reservation) → #6 operation INSERT / rearm UPDATE | conforms — fence is the transaction's first lock; every later lock is #5/#6-class |
| Fenced V3 paid submit — **begin** (§3.2; N3R3-2) | **#2/#3 fence SHARE (ancestor chain)** → #5 job SHARE (`lease_guard`) → **#6 job/reservation xact advisories (`_lock_linked`-class serialization) → #6 operation INSERT → #7 reservation locks, reservation eligibility validated atomically before the admission commits** | conforms — the V3 transaction-taking begin path puts #6 serialization/operation locks **before** #7 reservation locks (`phase-A-spec.md` §6:279-291, the single order incl. provider advisories); scope locks precede job authority, which precedes both |
| Fenced V3 paid submit — **rearm** (**NOT_FOUND-only** re-entry for paid operations — REFUSED_PRELAUNCH rearm is `llm.subscription`-only per A0 §5.5:369-376 and `S/core/provider_ops.py:429-443` (N3R4-2); audited separately per N3R3-2) | **#2/#3 fence SHARE (ancestor chain)** → #5 job SHARE (`lease_guard`) → **#6 serialization/operation locks → #7 reservation locks with reservation eligibility validated before the rearm commits** — rearm takes its **own** chain: `resubmit_allowed` (`S/core/provider_ops.py:345`, `:354-360`) does **not** re-enter `begin`'s reservation SHARE/ACTIVE-validation chain (`:195-215`), so the V3 rearm path carries its own eligibility check | conforms — same #6→#7 order as begin, audited and tested separately (N3R3-2: begin and rearm are distinct transactions, never conflated) |
| `provider_ops.begin` / `resubmit_allowed` themselves (V1 entry points, preserved verbatim) | `begin`: (#7 reservation FOR SHARE when a reservation is linked) → #6 job xact advisory → #6 reservation xact advisory → #6 operation row. `resubmit_allowed`: #6 advisories + operation lock only — **no reservation chain** | **pre-existing V1 shape, byte-identical for V1 callers**: the #7-before-#6 ordering is V1 semantics — the reservation SHARE serialises begin against budget release (#7 paths), the advisories serialise begins against each other. **No V3 path takes the #7→#6 order**: the V3 rows above specify #6 before #7 with eligibility first (N3R3-2); V3 only prefixes #2/#3 and #5 in its own compositions |
| V3 collector (`v3_collect.collect_paid_result`, §3.2; N3R3-1) | **#2/#3 `fence_classify` SHARE (ancestor chain)** → current worker execution: #5 job SHARE (`lease_guard`) → #6 operation `_lock` UPDATE (`record_result`) → #4-…-class asset/stale inserts (new rows, no prior locks); recovery arm: job/operation revalidated under the **audited recovery principal under the same locks — no worker lease** | conforms — classification at the ordered lock replaces the throwing fence (stale collection no longer rejects before quarantine); installation only on 'current' with a live lease; quarantine and accounting committed without installation otherwise |
| `settle_cancelled_operations` / `LlmStep.settle_under_recovery` (§4.1 recovery arm's settlement entries; N3R3-1) | **#2/#3 `fence_classify` SHARE** → #5 job FOR UPDATE (id order) **under the audited recovery principal — no worker lease** → #6 operation UPDATE → evidence/settlement writes | conforms — observation/settlement only (N3-3): no begin/rearm/submit, so no admission advisory chain at all; `settle_under_recovery` is the connected LLM entry for **every** recovery caller (§3.2 collector/reconciliation rows, the §4.1 dispatcher) |
| `resolve_reconciliation`, V3 rows | **#2/#3 `fence_classify` SHARE** (added before the existing #5 `_lock` `:784`) under the audited recovery principal → #5 job FOR UPDATE → status move; **stale operations routed into the §4.1 recovery arm before RESUME** (N3R3-1) | **order fixed** — track before job, classify-not-reject at the scope lock; a successful stale resolution takes the existing NEEDS_RECONCILIATION→SUCCEEDED transition; competing test below |
| `cancel_in` (from `cancel()`) | #5 job FOR UPDATE (`:297`) → status write; no track lock, no operation lock | unchanged for V1; V3 callers arrive with #2/#3 already held (next rows) |
| `cancel_in` inside an amendment / `rewind_for_amendment` sweep | #2 (→ #3) FOR UPDATE already held → #5 jobs FOR UPDATE **id order** | conforms — the §6 order exactly |
| `cancel_season` / `cancel_episode` | #1 idempotency → #2 `season_tracks` FOR UPDATE → #3 `episode_tracks` id order → #5 jobs id order (`cancel_in`) → evidence/event inserts | conforms |
| `record_stale` | inside the caller's fenced transaction (already #2/#3 SHARE, #5 SHARE) → append-only insert | conforms |
| Worker name lock + incarnation fence (§5.1, N3R3-3) | session-level `pg_try_advisory_lock` on a **dedicated connection held outside every other transaction**; the incarnation token is validated inside the existing #5 job-lock transactions (claim/guard/heartbeat/finish/defer) | no ordering interaction — the advisory lock is never held inside a data transaction, and the incarnation validation adds no new lock class or order |
| V1 paths (`enqueue`, `claim`, `finish`, `cancel`, `resolve_reconciliation` on `track IS NULL` rows; `api/worker.py` without `--queues`/`--name`; `provider_ops.begin`/`resubmit_allowed` as called today) | unchanged — every added branch is gated on the V3 work-scope columns / `workflow_version` / the new flags | untouched |

A2's three `pg_try_advisory_xact_lock` sites (`S/budget/service.py:611`/`:729`/`:761`) remain
budget-side #6/#7-class facts, covered by A2 §8; A3 adds no try-locks of its own.

**A1 §9's handed-over row stays open until this audit passes** — it closes with A3's landing of
the full audit above plus the competing tests below (N3-5), not at note time.

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
   worker's next `lease_guard`/`finish`/`heartbeat` raises `Conflict`; the V3 handler converts it
   to stop-without-finish (N3-8 — asserted, not just tolerated); the operation row and its
   reservation are untouched; `track_waits` keeps the operation blocking until §4.1 settles it.
5. **claim vs amendment (both synchronized orders — N3R3-4):** **amendment-first** — the
   amendment commits before the claim's plain reads → admission `CANCELLED`/`STALE_CONTENT`, the
   job **never leased**, the handler never runs; **admission-first** — the claim's plain reads
   win, the job **leases and the handler may run, but no stale canonical effect ever lands**: its
   first fenced mutation raises `StaleContentRevision` → quarantine evidence, job CANCELLED; a
   current job leases normally in both orders. **claim vs cancel_season** (N3-4), the same two
   synchronized orders: sweep-first → admission `CANCELLED`/`SCOPE_CANCELLED`; admission-first →
   the job's first fenced mutation raises `ScopeCancelled` — never a write.
6. **fenced begin vs fenced begin, and rearm vs rearm (N3-5, N3R3-2):** two connections begin
   operations on one job (LLM: advisory-serialised; paid: one job + one reservation) — exactly
   one INSERT, the other replays the existing `client_token` row; no duplicate operation; the
   same one-writer proof repeated for two concurrent **rearms** of one NOT_FOUND operation —
   exactly one rearm commits.
7. **V3 paid begin/rearm vs release and settlement (N3R3-2, replacing the v1.2 old-shape test):**
   begin and rearm tested **separately**, each in **both synchronized interleavings** against two
   opponents — (a) **budget release**: the #7 reservation lock inside the V3 begin/rearm path
   (taken after #6) serialises against a concurrent release's #7 chain; both orders
   deadlock-free; whichever wins, the loser sees the committed state and refuses (closed
   reservation / recorded operation) — release is never lost and an ineligible reservation never
   begins or rearms (eligibility validated before the commit); (b) **settlement**: a committed
   begin/rearm's operation settles exactly-once against a concurrent collector/recovery
   settlement — both orders deadlock-free, no double settlement, no settle-then-rearm of the
   same operation. The V1 `provider_ops.begin` #7→#6 shape is asserted **unchanged for V1 callers
   only** (no V3 path takes it — audit rows above).

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
- **`provider_ops.begin` / `resubmit_allowed`** — byte-identical (§7): the admission seam is
  injected by V3 compositions only; V1 callers pass none, and their lock chains are the audited
  pre-existing shape.
- **`api/worker.py`** — without `--queues`/`--name`, today's loop, report, janitor cadence,
  OFFLINE_MOCK guard and `staging-worker` identity, no name lock (§5.1); the V1 `make pilot` and
  pipeline tests are unaffected.
- **Budget/queue surface** — `budget/policy.py`, the jobs/reservations queue CHECKs, `JOB_SPECS`:
  untouched (no lanes, §5.2). Quarantined money flows through the existing ledger paths.
- **Catalog/tests** — `EXPECTED_TABLES` grows (superset check); upgrade test (A-T16 A3 part)
  asserts a populated V1 database migrates through 0035 with every existing row and applied
  checksum unchanged; the catalog guard tests cover `stale_artifacts` automatically.

## 9. Test plan (A-T8, A-T12a, A-T18; real PostgreSQL; spec §11 negatives included)

All offline, ephemeral PostgreSQL via the existing conftest, real runtime/composition with fakes,
pytest `--basetemp` under the session scratchpad; `make check` + V1 `make pilot` stay green.
Subprocess cases boot through the §5.1 test-only child bootstrap (real CLI/runtime, shared test
database, fake-provider journal persisted in it).

| ID | File (new unless noted) | Cases |
|---|---|---|
| A-T8 | `X/integration/v3/test_runtime_lanes.py` | **per-queue isolation:** two real worker subprocesses (`python -m microdrama.api.worker --queues production --name w-prod`, `--queues publication --name w-pub`) against the test database; a production handler sleeping 60 s (test-registered, fake) while a publication job is due at t₀ → the publication job completes ≪ 60 s; without `--queues` the loop serves all three queues (today's behaviour asserted); `--queues` validation (unknown name exits 2); **duplicate `--name` refused** (§5.1 lock: second live process exits 2; after the first dies — `os._exit` — a same-name replacement starts); **incarnation fence (N3R3-3):** the name-lock connection is dropped during a blocked (sleeping) handler, a same-name replacement starts and claims work — the old process's next claim/guarded write fails the incarnation validation and exits non-zero; it never runs on, or finishes, a job under the replacement's lease; janitor sweeps from both processes are idempotent (SKIP LOCKED); **SIGTERM coverage (N3R3-4 — graceful, distinct from forced death):** today's CLI lets the synchronous handler finish before the loop observes `_STOP` (`S/api/worker.py:88-104`), so a signalled child with an in-flight handler completes that job normally and exits cleanly; forced-death recovery (no finish, job left for `requeue_expired`) is asserted by A-T18's process-death cases — the two are never conflated. **A0 runtime consumed — the actual signal classes are *raised*, translated outcomes asserted separately (N3-10, N3R3-4):** a V3 job whose handler raises each real A0 signal (`G/workers/runtime.py:257-262`) — `LlmDeferred` → outcome `Deferred` → RETRY_WAIT + persisted `defer_reason` + attempt refunded only when the claim consumed it (`refund_attempt`/`consumed_attempt`, A0 §5.2); `LlmWait` → outcome `WaitExternal` → WAITING_EXTERNAL; `LlmBlocked` → `Failed("LLM_BLOCKED")`; `LlmCancelled` → `Failed("CANCELLED")`; `LlmNeedsReconciliation` → NEEDS_RECONCILIATION; `LlmLeaseLost` → the worker stops and **`finish` is never called after ownership loss** (asserted); REFUSED_PRELAUNCH re-arm through `resubmit_allowed()` stays a *state* path, not a runtime signal; `Deferred`/`WaitExternal` are outcomes and are never raised; the outcome union matches A0's extension exactly (no A3 variant) |
| A-T12a | `X/integration/v3/test_fence.py` (+ `X/integration/v3/test_lock_order.py` extended with §7's seven competing tests) | **fence race:** amendment vs mutation under the locks in both orders (§7.2), **interleavings synchronized explicitly** (barriers on the two connections — no unsynchronized windows), no stale canonical effect; **intermediate writes:** partial writes at N are all-or-nothing against the bump — nothing lands as current at N+1, and the amendment's closure sees committed N-writes; **season-scope work:** a season planning job fenced on `season_tracks`, an extension job on `season_extensions`, an episode job on `episode_tracks`; **cancellation fencing (N3-4):** enqueue after a committed cancellation sweep → `ScopeCancelled`, no job row; admission of a cancelled-scope candidate → `CANCELLED`/`SCOPE_CANCELLED`, handler never runs; a job admitted pre-cancel → its first fenced mutation raises `ScopeCancelled`, never a write; NEEDS_RECONCILIATION jobs skipped by the sweep still settle observation-only; **stale results quarantined:** collector completes after the bump → `stale_artifacts` row (job, operation, artifact refs, expected vs actual), assets registered but NOT accepted/installed, no continuation enqueued, settlement + charges posted (money normal), reservation retained until settlement; **collector transaction (N3-6):** registration, result, quarantine and acceptance provably in one transaction — an injected mid-transaction failure rolls all of them back; crash between result persistence and settlement → settlement re-derived exactly-once on the next pass; **permission split (N3-3) and recovery reach (N3R3-1):** every `LlmStep.ensure` branch — NOT_FOUND, REFUSED_PRELAUNCH, PENDING_SUBMIT, SUBMITTED/RUNNING, SUCCEEDED, FAILED, CANCELLED, UNKNOWN — tested under admission (fence seam active) and under recovery (`settle_under_recovery`: observation/settlement only; NOT_FOUND recorded, never rearmed; no begin/submit/install/enqueue from recovery); **every recovery caller — the collector, reconciliation adoption and the §4.1 dispatcher — enters through `fence_classify`, never the throwing `fence()`**: a stale result is collected into quarantine (no reject-before-quarantine), a stale NEEDS_RECONCILIATION job resolves through the recovery arm before RESUME (NEEDS_RECONCILIATION→SUCCEEDED + `outcome.quarantined=true` + `stale_artifacts`, no installation), and a CANCELLED job settles stays-CANCELLED (§4.1); **cancelled-operation reconciliation (N3-2, corrected):** `cancel_in` mid-flight → lease revoked, worker `Conflict` on guard/finish converted to stop-without-finish, operation untouched → later settlement through the authorised path (A0 `adopt_confirmed_cancels` for llm.subscription incl. the AD-11 completion race; `settle_cancelled_operations` for paid kinds) → **job stays CANCELLED** with `outcome.settled_after_cancel`, evidence row with `reason='cancelled_operation_result'` (equal-revision case admitted by the extended CHECK), money accounted, `track_waits` block cleared; **commands:** `cancel_season`/`cancel_episode` positive, foreign owner, service credential, missing CSRF, revision mismatch (`StaleRevision`), replay identity, episode-vs-season scope separation, sweep-status enumeration (NEEDS_RECONCILIATION never cancelled); `rewind_for_amendment` from a non-coordinator caller refused; every §6.1 edge accepted, every rejected target `NOT_AVAILABLE` with no write (incl. episode planning, past-published release, closed extension) |
| A-T18 (V3-AT-20) | `X/integration/v3/test_paid_unit_recovery.py` | a **generic paid unit** through a test-registered V3 job type driving a fake `GenerationProvider` via `ProviderOperation` (reserve → `begin` → submit → poll → collect → settle); the fake provider's journal persists in the test database, so submit counts and results survive child death. **Crash at each boundary, with at least one real process death:** a child worker process (own DB connection, claims under its own `--name`, booted through the §5.1 child bootstrap) dies via `os._exit(1)` — and in one case SIGKILL from the parent — at (1) after the intent/`begin` commit, before submit; (2) after the provider accepted, before `record_result(SUBMITTED)`; (3) after the result, before the receipt/settle; (4) after the receipt, before job finish. **Zero submits vs one accepted submission (N3-10):** at boundary (1) the journal proves zero submits — recovery reconciles the durable operation against provider evidence first (a provider that never saw the request answers not-found) and only then admits exactly one submit (PENDING_SUBMIT submit or NOT_FOUND rearm per the reconciled state); at boundaries (2)–(4) exactly one accepted submission existed and the durable operation decides recovery — the stable request identity (`client_token`, `M/0001…sql:187`) plus **provider reconciliation evidence** (never safety inferred from the stable token alone) means no blind resubmit; UNKNOWN without a recoverable external ID stays UNKNOWN for the operator with exposure held; no lease revival (`requeue_expired` semantics, `:706-750`); **cancel plus late success:** `cancel_in` mid-flight, the provider completes afterwards, §4.1 adopts — job stays CANCELLED, operation settles to its true state, money accounted, evidence recorded, no exposure release before settlement |
| A-T16 (A3 part) | `X/integration/persistence/test_migrations.py` (extend; `:122` pattern) | 0035 applies on a populated V1 database at the 0034 head: every existing row unchanged, applied 0001–0034 checksums unchanged, the fence CHECK satisfied on all V1 rows (`track IS NULL`), `stale_artifacts` in `EXPECTED_TABLES` and covered by the catalog guard tests; fresh-create tail asserts `0035`; **direct-SQL rejection tests (N3-1):** `track`-bearing rows refused for missing, JSON null, string (incl. digit strings), boolean, fractional, negative and overflowing (> int4) `expected_content_revision`; **CHECK semantics (N3-4):** `stale_artifacts` rejects `actual < expected`, rejects equality with `reason='stale_content_revision'`, admits equality with `reason='cancelled_operation_result'` |
| contracts | `X/contract/contracts/test_v3_runtime_contracts.py` | `V3ScopedStepInput` example + schema generation under `schemas/v3`; `track.cancelled` / `track.rewound` payload schemas registered and valid (AC-19 naming); generated-contract drift check green |

## 10. Open questions

| # | Question | Recommendation |
|---|----------|----------------|
| OQ-1 | Episode jobs fence on the episode track only; a season-scope bump alone does not stale them. Correct only if A4's closure bumps every episode track whose work an amendment invalidates. | Keep the single resolved fence (matches A1's `track_waits` `stale` CTE; scoped invalidation preserves unrelated work, AR-3/AR-4). Record the A4 obligation in its note; A-T12b tests it from the coordinator side. |
| OQ-2 | Admission uses a plain read, not a SHARE lock, so a job admitted at N may start a handler that goes stale mid-run — and a cancelled scope may admit a job in the window before the sweep commits. | Keep: correctness is anchored at the mutation fence (fence + `ScopeCancelled` there), with the admission pre-checks (§3.2) shrinking the window only; a SHARE at claim would order #5 before #2/3 and deadlock against amendments — the inversion the spec forbids. A-T12a proves both admission-race closures. |
| OQ-3 | Terminal status for a job whose recovery adopted a successful result. | Two distinct cases (N3-2/N3-3): a **stale NEEDS_RECONCILIATION** job → `SUCCEEDED` + `outcome.quarantined=true` + `stale_artifacts` (legal transition, the operation genuinely completed, money accounted; `track_waits` ignores stale rows); a **CANCELLED** job → **stays CANCELLED** with `outcome.settled_after_cancel` (§4.1) — operation success never restores content authority and no terminal transition is widened. |
| OQ-4 | `rewind_for_amendment` exposure in A3: it is the A4 coordinator's primitive with no production caller yet. | Internal API only — no route, no command surface; A3's tests drive it through the test world. A1 §6's "only through the amendment coordinator" is enforced by refusing every non-coordinator caller. |
| OQ-5 | Does `cancel_season` also mark every `episode_tracks.cancelled_at` under the season? | Yes (recommended reading of "terminal" + OQ-2's CANCELLED wait): a cancelled season has no live episode work; the episode marks ride in the same transaction (§6 order #3). |
| OQ-6 | Worker identity uniqueness (`lease_owner`) across per-queue processes. | **Resolved by ruling N3-9: enforced name ownership in A3** — the §5.1 session advisory lock refuses a duplicate live name at startup (exit 2) and self-releases on death. **Completed by N3R3-3: the §5.1 incarnation fence** separates the configured name from a process-unique lease identity (validated by claim/guard/heartbeat/finish/defer), so a disconnected survivor cannot act on a same-name replacement's lease; ownership-loss is checked before every new claim and guarded write. A6c's compose simply sets distinct names; no startup-refusal promise is deferred to A6c. Scaling a lane = more processes, distinct names. |
| OQ-7 | `stale_artifacts` refs as jsonb vs a typed child table. | jsonb refs + the integer-number guard now (evidence is read by scope, not joined per-artifact); promote to a typed table in a later migration only if A5 needs per-artifact joins. Applied 0035 bytes are never edited either way. The 0035 CHECK extension (N3-4) and the `reason` vocabulary are part of the shipped bytes. |
| OQ-8 | Should `api/worker.py` gain `--composition` in A3 (spec §9.2 assigns production selection to A6c)? | No: A3 ships `--queues`/`--name` plus the §5.1 name lock and the guarded test-world bootstrap; the OFFLINE_MOCK guard stays. A6c adds composition selection and the fail-closed dependency checks on top. |

— end of note —
