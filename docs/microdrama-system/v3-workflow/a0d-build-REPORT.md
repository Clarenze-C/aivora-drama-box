# A0-D: ALL PACKAGES DONE

# A0-D build report — LLM gateway, `LlmStep`, migration 0027

Build: GLM (A0-D brief, 12–13 Nov 2026). Base `0cda424` (T031 accepted; A0 = migration **0027**).
Worktree `drama-box/.scratch/a0d-gateway`, branch `feat/a0d-gateway`. Spec: `phase-A0-spec.md` **v0.4**
(all three Codex rounds folded in; A0S-1/A0S-2 verified below).

**Session honesty note.** This session **resumed a context-lost build**: D1 and D2 were already
committed (`365bff9`, `2352e73`) but the report was stale at "D1 building", and D3 existed only as
uncommitted files with 5 red tests. D1/D2 sections below are reconstructed from their commits and
**re-verified green this session** (fresh green lines listed). D3's original red-run-against-base was
made by the lost session and is not reconstructible; what is recorded here is this session's honest
state: the 5 reds found on arrival, their resolutions, and one genuine implementation gap found
red and closed green (§5.4 confirmation adoption).

## Packages

| Pkg | Scope | Status | Commit |
|-----|-------|--------|--------|
| D1 | Migration 0027, §5.5 contract changes, §5.2 runtime support | **done** | `365bff9` |
| D2 | `microdrama/deployment/llm-gateway/` (§4) + install files | **done** | `2352e73` |
| D3 | `LlmStep` + reconciler + cancellation + gate + fakes (§5.1/5.3/5.4/5.7/5.8) | **done** | `c25b527` |

Branch tip: `c25b527`. Working tree clean except `microdrama/.venv` (symlink, never staged) and this
`docs/` directory (untracked by design on this branch).

---

## D1 — migration 0027 and the LLM subscription contract layer

### Red lines (against base `0cda424`, recorded by the lost session)

- `tests/unit/core/test_core_a0_llm_transitions.py`, `test_core_a0_defer.py`,
  `tests/integration/persistence/test_migration_0027_llm.py`, updated `test_core_provider_ops.py`
  matrix + unmetered list, updated outcome-union test: **27 failed, 24 passed**
  (`ImportError: DeferReason`, `ProviderOperationState has no REFUSED_PRELAUNCH`, migration 0027
  missing, union without `Deferred`). Transcripts: `/tmp/a0d-red-d1.txt`, `/tmp/a0d-red-d1b.txt`
  (temporary; not preserved).

### What was built

- `contracts/enums.py`: `ProviderOperationState.REFUSED_PRELAUNCH`; the closed `DeferReason` enum
  (8 values per A1 ruling OQ-3: `QUOTA_UNREADABLE`, `QUOTA_5H`, `PACE_WEEK`, `CONCURRENCY`,
  `BUDGET`, `GATEWAY_UNAVAILABLE`, `PROVIDER_RATE_LIMITED`, `RATE_LIMITED`).
- `contracts/cost.py`: `UNMETERED_OPERATION_KINDS += llm.subscription`;
  `ProviderOperationResult.launched/refusal_reason` admission-evidence fields (model validator:
  REFUSED_PRELAUNCH ⇒ launched=false + refusal_reason).
- `core/provider_ops.py`: `ALLOWED_MOVES` with the two A0 edges (PENDING_SUBMIT→CANCELLED,
  *→REFUSED_PRELAUNCH, both llm.subscription-only with launched=false evidence in
  `record_result`); `resubmit_allowed` re-arms REFUSED_PRELAUNCH (llm-kind + durable
  last_result evidence) and keeps NOT_FOUND unchanged; `begin` blocks new tokens on a
  REFUSED_PRELAUNCH op like NOT_FOUND.
- `core/jobs.py`: `Deferred` outcome (union extended); all six §5.1/§5.2 signals
  (`LlmWait/LlmDeferred/LlmBlocked/LlmCancelled/LlmNeedsReconciliation/LlmLeaseLost`);
  `defer(refund_attempt)` with claim-aware refund via the persisted `consumed_attempt`; deferral
  refused (quarantined) while a linked op is in flight; claim records `consumed_attempt` and clears
  `defer_reason`; `cancel()` persists `llm_invocations.cancel_requested_at_ms` and emits
  `llm.cancel_requested` in the cancel transaction (§5.4).
- `workers/runtime.py`: signal translation before generic exception handling (`LlmWait`→
  `WaitExternal`, `LlmDeferred`→`Deferred`, `LlmBlocked`→`Failed("LLM_BLOCKED")`,
  `LlmCancelled`→`Failed("CANCELLED")`, `LlmNeedsReconciliation`→`NeedsReconciliation`,
  `LlmLeaseLost`→ no finish, RunReport LEASE_LOST).
- Migration `0027_a0_llm_gateway.sql`: jobs `defer_reason` (closed-vocabulary CHECK) +
  `consumed_attempt`; provider_operations state CHECK + per-kind linkage CHECK with
  `llm.subscription`; `llm_invocations` (incl. `frozen_call_text/sha256`,
  `structured_output_text/sha256`, `transport_failures`), `llm_invocation_attempts` (append-only),
  `quota_observations` (append-only, exclusivity CHECKs) with house guards.
- Contracts regenerated (2.17.0 / v1 schema set 1.16.0); COMPATIBILITY.md entry.

### Green (re-verified this session)

- `test_core_a0_llm_transitions.py + test_core_a0_defer.py + test_core_provider_ops.py`:
  **100 passed**.
- `test_migration_0027_llm.py + tests/contract` (full contract suite): **471 passed**.

### Judgement calls (D1, preserved)

- `defer()` keeps `error_code='RATE_LIMITED'` and the V1 `RATE_DEFERRED` outcome payload for every
  reason (V1 behaviour unchanged); the truth lives in `defer_reason` and the event payload
  (`attempt_refunded` replaces the unconditional `attempt_restored`).
- A REFUSED_PRELAUNCH operation blocks a *new token* on the same job (mirrors NOT_FOUND).
- The CANCELLED-from-PENDING_SUBMIT evidence check lives in `record_result` (state-dependent); the
  REFUSED_PRELAUNCH evidence check additionally fails at result construction (model validator).
- `transport_failures` (the §5.1 ten-strike counter) is persisted on `llm_invocations` — §5.1 needs
  "10 **consecutive** failures" to survive process restarts; §5.6 does not enumerate it (addition,
  guarded `>= 0`).

---

## D2 — the `dramabox-llm-gateway` host service (§4)

### What was built (commit `2352e73`)

- `microdrama/deployment/llm-gateway/gateway.py` (1041 lines, stdlib only): HTTP over the Unix
  socket (`/v1/invocations`, `.../readmit` with `expected_prior_attempt`, `GET .../{id}`,
  `.../cancel`, `/v1/health`); the `Ledger` (one directory per invocation, `atomic_write`
  tmp→fsync→rename→fsync-dir after **each** state write); the argv-per-property `systemd-run`
  launcher (A0R-6) with the §4.3 sandbox properties, precreated write paths, fixed environment;
  the full §4.3 restart-recovery table (unit `ActiveState` via `systemctl show`, absent = not
  loaded) incl. **persistent `deactivating` → unresolved + health red + never relaunch** (A0S-5);
  FIFO queue with max 1 running attempt; retention (payloads 30 d, tombstones 400 d; tombstones
  block a re-run after pruning); `--crash-after` test seam that dies hard (`os._exit(17)`) at exact
  ledger boundaries; per-invocation `executions.txt` proving "no second execution".
- `install/`: `INSTALL.md`, `dramabox-llm-gateway.service`, `dramabox-llm-gateway.tmpfiles.conf`
  (group 64010, `/run/dramabox-llm/` 0750 root:64010, `gw.sock` 0660, `/var/lib/dramabox-llm/`
  0700). **The operator installs these; tests never touch the production paths.**
- Tests (`tests/integration/llm_gateway/`): the fake **ai-route shim** (`ai_route_shim.py` — never
  real ai-route or `claude`), `gw_helpers` (test gateway process, `dramabox-llm-test-*` unit prefix,
  `stop_test_units` cleanup), `unprivileged_client.py` (setpriv), API/recovery/containment/
  launch-argv/socket-perms suites. Temporary socket dir + store + group under
  `/run/a0d-llm-gwtest-<pid>/` (never `/tmp`: units run `PrivateTmp=yes`, so a /tmp store could not
  be a ReadWritePath).

### Green (re-verified this session; real transient systemd units)

- `test_gateway_api.py`: **11 passed** (idempotency: concurrent duplicate POSTs → one attempt;
  same id + same hash → current record; different hash → 409; hash = SHA-256 of exact text;
  readmit after refusal exactly once; readmit of a launched attempt refused; queued cancel never
  launches; FIFO max-1; 404; isolation violation → health red; tombstones block a re-run).
- `test_gateway_recovery.py + test_gateway_containment.py`: **14 passed** (matrix below; A0-4:
  `setsid` grandchild ignoring TERM dies with the cgroup on deadline and cancel; SIGKILL of the
  gateway and of the shim separately).
- `test_gateway_launch_argv.py + test_gateway_socket_perms.py`: **5 passed** (every property one
  argv element in the documented order; the fixed environment exactly; sandbox mask; UID 10001
  with/without GID via setpriv; **reconnect after a gateway restart** — A0-11).
- No `dramabox-llm-test-*` units left loaded after the runs (`systemctl list-units` empty).

### §4.3 recovery-table test matrix

| §4.3 row (ledger / unit / result) | Recovers to | Test |
|---|---|---|
| `ACCEPTED` (no intent) / — / — | `ACCEPTED`, re-queued FIFO | `test_crash_after_accept_recovers_to_queued_and_runs_once` |
| `LAUNCH_INTENT`/`RUNNING` / `activating`/`active`/`reloading` / — | `RUNNING` (re-attach) | `test_crash_after_spawn_before_running_reattaches_without_a_second_execution` (ledger at LAUNCH_INTENT, unit live); `test_gateway_sigkill_while_running_reattaches_the_live_unit` (ledger RUNNING, unit live); `test_recovery_is_a_no_op_for_an_already_running_observation` (restart while live: never re-submitted, never relaunched, exactly one execution) |
| `CANCEL_REQUESTED` / live / — | stays; stop re-issued + verified | `test_crash_during_cancel_requested_preserves_intent_and_completes_the_cancel` (intent durable before the response; recovery re-issues stop, verifies, then `CANCELLED`) |
| any / `deactivating` (still, at `TimeoutStopSec + 5 s`) | unresolved, health red, **never relaunch** (A0S-5) | `test_persistent_deactivating_at_the_bound_is_unresolved_and_red` (systemd query stubbed to `deactivating`; the real deactivating path is exercised by the cancel tests) |
| `CANCEL_REQUESTED` / absent/inactive/failed / either | `CANCELLED` (result kept for metering) | `test_crash_during_cancel_requested…` + `test_cancel_of_a_running_unit_settles_only_after_the_unit_is_not_active` (CANCELLED only after the unit is confirmed not active; TERM-ignoring grandchild gone) |
| `LAUNCH_INTENT`/`RUNNING` / absent/inactive/failed / present | `DONE`/`REFUSED` per outcome | `test_crash_after_the_result_before_done_adopts_the_result` (also the **unit-garbage-collected-with-result** row); `test_shim_sigkill_after_the_result_settles_done` |
| `LAUNCH_INTENT`/`RUNNING` / absent/inactive/failed / absent or invalid | **`UNKNOWN`**, never relaunched | `test_crash_after_launch_intent_before_systemd_run` (no unit was ever spawned); `test_shim_killed_without_a_result_is_unknown_and_never_relaunched` (UNKNOWN survives a restart, one execution) |

---

## D3 — `LlmStep`, the auto-reconciler, cancellation forwarding, the gate, the fakes

### State on arrival (red)

Uncommitted `microdrama/src/microdrama/llm/` + `testing/fakes/llm_gateway.py` +
`tests/unit/llm/` + `config.py`/`pipeline/world.py` edits; **5 failed, 28 passed**:

1. `test_llm_gate.py::test_offline_mock_never_authorizes_the_route` — `Settings` itself refuses
   `paid_requests_enabled=true` in OFFLINE_MOCK (pydantic validator), so the test's settings could
   not even be constructed.
2. `test_llm_cancellation.py::test_the_outbox_delivers_the_cancel_and_only_then_may_the_op_settle`
   — `dispatch_pending() == 7`: the existing `OutboxDispatcher` drains **every** pending event
   through one publish callable (transport is only a label); the test's `== 1` assumed a
   type-filtered dispatcher.
3. + 4. `test_reconciler_settles_a_done_result…` and `test_reconciler_takes_cancelled…` — after the
   reconciler settles the op and the janitor requeues the job, `run_cycle()` left it QUEUED: the
   requeue keeps the stale `run_after` from the last `WaitExternal` (5 s out), and `claim()` only
   takes jobs with `run_after <= now`.
5. `test_forced_lease_loss_mid_step…` expected `SUBMITTED_WAIT`; §5.3 says op `SUBMITTED` +
   gateway running-record → `RUNNING` if not already → `RUNNING_WAIT` (the passing sibling test
   `test_reconciler_resumes_submitted_to_running_and_waits` asserts exactly that for the same
   shape). Test-expectation bug.

Resolutions: (1) restructured to prove **both** the Settings validator (paid flags unconstructible
in OFFLINE_MOCK) and `require_effect`'s `EffectDenied` on a well-formed OFFLINE_MOCK composition;
(2) re-anchored the assertion to what §5.4 actually requires — the cancel event is delivered to the
gateway and marked dispatched under transport `llm_gateway_cancel`, a second pass dispatches
nothing; (3)+(4) advance past the stale `run_after` before the claim (documented in the test: the
ordinary requeue path keeps the next poll boundary); (5) expectation corrected to `RUNNING_WAIT`.

### A genuine gap found red → closed green (§5.4)

The cancellation test's last stage assumed "a later poll records the operation state" — impossible:
`jobs.cancel()` makes the job CANCELLED (terminal), and `claim()` never leases a terminal job, so
no worker poll can adopt the confirmation. §5.4 says "`CANCELLED` is recorded only after the
gateway confirms" — the confirmation arrives at the **outbox consumer**, so the consumer owns the
adoption. Red: op stayed `SUBMITTED`. Green: `adopt_confirmed_cancels(db, client, clock)` — for
every persisted cancel intent whose op is still in flight, GET the gateway and record CANCELLED
only on confirmation (idempotent; unreachable gateway retried next pass; `PENDING_SUBMIT →
CANCELLED` only with all-attempts-`launched=false` evidence per §5.5(4), a launched attempt is left
to reconciliation). Test now proves adopt-once + idempotence.

### What was built (commit `c25b527`)

- `microdrama/llm/step.py` — `LlmStep.ensure`, the §5.1 state table: `begin` under `lease_guard`
  with fresh time (A0R-1), `invocation_id = uuid5(LLM_NS, logical_call_id)` (transport recovery
  reuses it); PENDING_SUBMIT submit (POST; a REFUSED record → readmit with
  `expected_prior_attempt`) → SUBMITTED → `LlmWait`; connect-level failure → NOT_FOUND +
  `TRANSPORT_NOT_SENT` + `Deferred(GATEWAY_UNAVAILABLE, 60 s)`, 10 consecutive → `LlmBlocked`
  (counter persisted); after-send failure → one bounded GET (found → SUBMITTED; 404 → NOT_FOUND +
  defer; unreachable → leave PENDING_SUBMIT + `NeedsReconciliation`); NOT_FOUND/REFUSED_PRELAUNCH
  rearm via `resubmit_allowed` (attempt+1, fresh deadline); poll rows (RUNNING once; DONE+
  SUCCEEDED → LlmDone with byte-exact `structured_output_text`; DONE+CAP_EXCEEDED/CLI_ERROR/
  PARSE_ERROR/DEADLINE/invalid → settled FAILED + `LlmCallFailed`; ISOLATION_* → **settled FAILED
  first**, then `LlmBlocked` (A0R-4); REFUSED → REFUSED_PRELAUNCH evidence + defer with
  clamp(retry_at − now, 60 s, 6 h); CANCEL_REQUESTED → wait; CANCELLED → CANCELLED +
  `Failed("CANCELLED")`; UNKNOWN → UNKNOWN + NeedsReconciliation); terminal replay loads only;
  §5.7 `require_llm_route` (paid effect + route + health + policy identity) at every dispatch;
  `mirror_invocation_result` (§5.6 records) shared with the reconciler.
- `microdrama/llm/reconciler.py` — **§5.3 / A0S-1 / A0S-2**: acts on NEEDS_RECONCILIATION jobs
  whose in-flight ops are all `llm.subscription` (UNKNOWN ops are the operator's row — never
  touched); **probes the gateway before resuming** (unreachable → no change, no lease, no loop
  with the janitor); takes the job through audited `RESUME` under its own SCHEDULER principal,
  worker id and short (2 s) lease; reconciles **only through legal `ALLOWED_MOVES`** — an
  observation identical to the current state is a no-op, never repeats SUBMITTED, never moves
  RUNNING back; PENDING_SUBMIT + record → SUBMITTED → WaitExternal; PENDING_SUBMIT + 404 →
  NOT_FOUND (settled → the janitor's ordinary requeue resumes the handler); SUBMITTED/RUNNING +
  accepted/running → RUNNING if not already → WaitExternal; + DONE/REFUSED/CANCELLED → the
  matching terminal/REFUSED_PRELAUNCH/CANCELLED transition (mirror kept); + 404 → **UNKNOWN,
  never NOT_FOUND** (A0S-2), left for the operator; **never finishes a job to the queue while an
  op is in flight** (A0S-1) — settled work is left RUNNING under the short lease for the janitor's
  ordinary requeue (`requeue_expired` quarantines, never requeues, in-flight work). CLI entry
  point `python -m microdrama.llm.reconciler`.
- `microdrama/llm/cancel_outbox.py` — §5.4 (above): `route_llm_cancel` publish wrapper on the
  existing `OutboxDispatcher` (a raise keeps the event pending → retried until acknowledged) +
  `adopt_confirmed_cancels`.
- `microdrama/llm/gateway_client.py` — the §4.2 client (5 s connect / 10 s read) whose one
  correctness contract is the transport split: `GatewayTransportError.not_sent` only for
  connect-level failures; everything after the request may have been sent is ambiguous.
- `microdrama/testing/fakes/llm_gateway.py` — §5.8: the scriptable `FakeLlmGatewayClient`
  (script/transport/calls seams) and the health-only `StaticLlmGatewayHealth`.
- `Settings.llm_route` (`legacy|subscription`, env `MICRODRAMA_LLM_ROUTE`) and
  `build_pipeline_world` refusing the subscription route in the OFFLINE_MOCK composition (§5.5(6)).
- `tests/unit/llm/` — the real JobService + real WorkerRuntime + a real test V3 handler against
  real PostgreSQL; shared world in `llm_world.py` (a bare `from conftest import …` is
  collection-order dependent when several suites run in one invocation — found when
  `tests/unit/pipeline tests/unit/llm` collided; the split fixes both orders).

### Green

- `tests/unit/llm`: **33 passed**.
- Order-independence: `tests/unit/pipeline tests/unit/llm …` and the reverse: **133 passed** both.
- Neighbour sweep `tests/unit/core + tests/unit/workers + tests/unit/pipeline + tests/unit/llm`:
  **634 passed** (after fixing the world-test Settings stub, which lacked the new `llm_route`
  attribute).
- `make lint` clean immediately before the commit (one import-order fix and three unused imports
  removed; `ruff format` applied to the touched files).

---

## Acceptance rows → evidence

| Row | Evidence |
|-----|----------|
| **A0-1** (= V3-AT-27) | `test_llm_step_rows.py` (11 tests): happy path (records: one invocation row, one attempt row, byte-exact fractional texts, **no charge**), terminal replay (one SUCCEEDED transition), connect-failure NOT_FOUND/defer/ten-strike block, after-send trichotomy (found→SUBMITTED / 404→NOT_FOUND+defer / unreachable→PENDING_SUBMIT+NeedsReconciliation), refusal→defer→rearm→readmit→success round trip (incl. clamp window and no-refund-on-polling-claim), readmit replay of a lost acknowledgement, isolation violation settled before `LLM_BLOCKED`, attempt-failure outcomes, invalid output, gateway CANCELLED → `Failed("CANCELLED")`, gateway UNKNOWN → NeedsReconciliation |
| **A0-6** | D1: defer/refund tests (`test_core_a0_defer.py` — initial vs polling claim), admission-refusal evidence; D3: readmit round trip + lost-ack replay (above); D2: `test_readmit_after_refusal_creates_exactly_one_new_attempt`, `test_readmit_of_a_launched_attempt_is_refused` |
| **A0-9** | `test_llm_reconciler.py` (12 tests): every §5.3 row (RESUME→RUNNING_WAIT with no repeated observation, DONE_SETTLED + handler adoption, REFUSED_PRELAUNCH_SETTLED, CANCELLED_SETTLED + handler replay, VANISHED_UNKNOWN never NOT_FOUND, SUBMITTED_WAIT, NOT_FOUND_SETTLED, UNREACHABLE no-change-no-resume, UNKNOWN skipped, SCHEDULER principal, 300 s lease → WAITING_EXTERNAL no lease + late result adopted, forced lease loss → no guarded write, no finish, janitor quarantines, reconciler resolves under its own lease) |
| **A0-10** | D1: `test_migration_0027_llm.py` + `test_core_a0_llm_transitions.py` (Python + SQL enforcement, paid kinds refused); D3: the happy-path records assertions (fractional schema/output byte-exact as TEXT; `charges` empty) |
| **A0-12** | `test_llm_cancellation.py` (3 tests): intent persisted + event emitted in the cancel transaction; outbox delivers → gateway cancel → **op CANCELLED only after confirmation** (adopt pass; idempotent); delivery failure stays pending and retries after the outage |
| **A0-4** | D2 containment + recovery suites (above): cgroup kill incl. TERM-ignoring `setsid` grandchild; SIGKILL of gateway and of the shim separately; recovery per §4.3 |
| **A0-7** | D2 API suite (above) |
| **A0-8** | D2 recovery suite — every §4.3 boundary incl. `CANCEL_REQUESTED` and unit-GC-with-result (matrix above), `executions.txt` proves no second execution |
| **A0-11** | D2 socket-perms suite: real UID 10001 with/without GID (setpriv), reconnect after a gateway restart |
| **A0-13** | Contract suite **471 passed** (V1 outcomes unchanged — the union extension is deliberate and tested in D1); ai-route role snapshots are A0-R1's (separate report); **`make check` + `make pilot` are the orchestrator's** per the brief — not run here |

## Transaction inventory (function → locks in order → writes)

Drama Box side (real PostgreSQL; `lease_guard` = jobs row FOR SHARE under the worker lease):

| Function | Locks / order | Writes |
|---|---|---|
| `LlmStep._begin_under_lease` | jobs[id] (lease_guard) → provider_operations insert → llm_invocations select/insert | INSERT provider_operations + event; INSERT llm_invocations (frozen call, sha) |
| `LlmStep._rearm_under_lease` | jobs[id] (lease_guard) → provider_operations update | op → PENDING_SUBMIT (attempt+1, fresh deadline) + event |
| `LlmStep._record_under_lease` | jobs[id] (lease_guard) → provider_operations update → llm_invocations update → llm_invocation_attempts upsert | op state/last_result + event; §5.6 mirror (usage, cost, output text + sha, attempt row) |
| `LlmStep._bump/_reset_transport_failures` | llm_invocations row only (operational counter, no lease) | UPDATE transport_failures |
| `LlmReconciler._reconcile_one` | gateway GET **before any write** → jobs[id] FOR UPDATE (`resolve_reconciliation` RESUME) → provider_operations update (`record_result`) → jobs[id] FOR UPDATE (`finish`) | NEEDS_RECONCILIATION→RUNNING + reconciler lease + audit event; op transition + event (+ mirror on DONE); → WAITING_EXTERNAL or back to NEEDS_RECONCILIATION |
| `adopt_confirmed_cancels` | gateway GET → provider_operations update (`record_result`) | op → CANCELLED + event (no jobs lock: the job is terminal; the write is gateway-evidenced) |
| `JobService.cancel` (D1) | jobs[id] FOR UPDATE → llm_invocations update → domain_events insert | job CANCELLED; `cancel_requested_at_ms`; `llm.cancel_requested` |
| `JobService.defer` (D1) | jobs[id] FOR UPDATE → linked ops read (in-flight refusal → quarantine) | RETRY_WAIT + `defer_reason` + claim-aware attempt refund |

Host gateway (§4.3; file ledger, `atomic_write` = tmp→fsync→rename→fsync-dir, one invocation
directory, no cross-invocation lock; the queue pump is single-threaded FIFO max-1):

| Step | Writes in order |
|---|---|
| accept | `request.json` (immutable, first attempt) → state `ACCEPTED` |
| launch | state `LAUNCH_INTENT{n}` → `systemd-run` (argv-per-property, precreated write paths) → state `RUNNING` |
| settle | shim writes the result file (§3.5 order) → state `DONE`/`REFUSED` + attempt patch → `reset-failed` if needed |
| cancel | state `CANCEL_REQUESTED` **persisted before anything else** → `systemctl stop` → confirm not active → state `CANCELLED` (queued → CANCELLED with launched=false) |
| recovery (startup scan) | classify every ledger directory per the §4.3 table; persistent `deactivating` at the bound → health red, unresolved, never relaunch |
| retention | payloads pruned at 30 d; tombstone (invocation_id, request_hash, final state, attempts) kept 400 d and blocks re-runs |

## Judgement calls (D3)

- **The consumer adopts the cancellation confirmation** (`adopt_confirmed_cancels`): a cancelled
  job is terminal and never claimed, so no poll can record the op — §5.4's "recorded only after
  the gateway confirms" can only execute where the confirmation arrives (the consumer).
- `PENDING_SUBMIT → CANCELLED` from the adopt pass only when every gateway attempt shows
  `launched=false` (§5.5(4) evidence); a launched attempt under a PENDING_SUBMIT op is left to
  reconciliation instead of forcing an illegal edge.
- The reconciler's short (2 s) lease + "settled work stays RUNNING for the janitor's ordinary
  requeue" implements "resume the handler" for the PENDING_SUBMIT+404 and terminal rows without
  ever queueing a job with an op in flight (A0S-1); the DONE/CANCELLED tests demonstrate the full
  path (requeue → ordinary claim → handler adopts/replays).
- The stale `run_after` left by a janitor requeue (up to one poll interval, 5 s) is pre-existing
  janitor behaviour, accepted rather than changed: the reconciler never writes `run_after`.
- Submit is POST-first, readmit-on-REFUSED: §4.2's POST is idempotent (same id + hash → the
  current record), so a REFUSED record readmits with `expected_prior_attempt` in the same claim —
  one round trip either way, the same readmit contract as the explicit rearm path.
- The `OFFLINE_MOCK` gate test proves both layers: Settings refuses the paid flags at construction
  (the staging guard), and `require_effect` refuses a well-formed OFFLINE_MOCK composition.
- `transport_failures` persisted on `llm_invocations` (see D1 judgement calls).
- The lease-loss reconciler row expects `RUNNING_WAIT` (op SUBMITTED + gateway running-record →
  RUNNING "if not already"), consistent with §5.3 and the sibling test.

## Anything stopped at red

Nothing. All packages are green on the recorded lines.

## A0S-1 / A0S-2 verification pointers (for the build's Codex review)

- **A0S-1** (RESUME under the reconciler's own lease; never re-queued with an op in flight):
  `test_forced_lease_loss_mid_step_writes_nothing_and_finishes_nothing` (lease loss → no guarded
  write, no finish → janitor quarantines → reconciler resumes under its own lease → RUNNING_WAIT →
  WAITING_EXTERNAL), `test_an_unreachable_gateway_changes_nothing_and_never_resumes` (probe before
  resume; no lease, no queue change), `reconciler.py` `_reconcile_one` (probe → RESUME → legal
  transition → WaitExternal/NeedsReconciliation only).
- **A0S-2** (state-dependent, legal moves only; vanished accepted work → UNKNOWN):
  `test_reconciler_resumes_submitted_to_running_and_waits` (identical observation is a no-op;
  exactly one RUNNING transition), `test_vanished_accepted_work_becomes_unknown_never_not_found`
  (UNKNOWN, stays for the operator, later passes untouched), the `SUBMITTED_WAIT` /
  `NOT_FOUND_SETTLED` pair for PENDING_SUBMIT.

## Resume here

Nothing to resume in A0-D. For the orchestrator: run `make check` + `make pilot`, then the Codex
diff review (explicitly verify A0S-1/A0S-2 — pointers above). Live qualification (§7) remains
operator-gated and out of this build.
