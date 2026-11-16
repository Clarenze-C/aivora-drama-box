# T031 H-2 — Benchmark recovery and reconciliation spec (v3, BUILD)

Author: Opus orchestrator, 10 Nov 2026. Status: **v3, approved for build by the operator
(10 Nov)**. Size: Large (money path).

v3 folds in Codex's round-2 replacement wording verbatim:
- R1–R8 and SC2-1..SC2-3, from
  [codex-h2-spec-recritique.md](T031-fix-round/codex-h2-spec-recritique.md);
- the test extensions in §9.3.

The operator approved building v3 without a third critique round. Codex's review of the
build checks it against v3.

- Supersedes the H-2 implementation in `628fe5b` (CN3-1..CN3-5, see
  [rulings](T031-fix-round/rulings-canary-night.md)).
- v1 was critiqued REWORK in [codex-h2-spec-critique.md](T031-fix-round/codex-h2-spec-critique.md).
  v2 accepts SC-1..SC-14; §12 maps each finding to its section.
- Facts: [h2-codemap.md](T031-fix-round/h2-codemap.md), a verified map of `628fe5b`.
  "Map §n" below refers to it.
- Contract: [T031-integration-contract.md](T031-integration-contract.md), §A, §C, §E,
  §F, §G.

## 1. Goal and non-goals

**Goal.** Any interruption converges, through public entry points run in fresh
processes, to a state where:
- every provider effect is known, or durably held as uncertain for an audited operator
  decision;
- canonical exposure is retained until liability is final;
- no second pod, prompt or upload is ever sent to "find out";
- the run continues only when funds, time and eligibility allow.

All of this holds after the quote, authorization or rights deadline (§C).

**Non-goals:**
- changing contract package 2.16.0 or migrations 0001–0025;
- automatic resolution of anything not positively proven;
- changing the experiment's sample-failure policy (§7.4 keeps fail-fast);
- performance work.

**Permitted canonical edits** (each covered by the existing canonical and canary
suites, which must stay green):
- the lock order in `BillingRepository.resolve_podless_create` (§6.1);
- an expired-reservation recovery-read exception scoped to benchmark RECOVERY (§3.3).

## 2. Invariants

- **I1, one effect.** At most one pod create per acquisition intent, one upload POST
  per upload intent, and one prompt POST per sample operation, across crash, restart,
  takeover or race. The right to the first send belongs only to the original admission
  or dispatch, and replay never transfers it.
- **I2, no absence-proof.** A list, queue or history miss never proves "not sent".
  Never-sent proof is only:
  - a durable pre-dispatch refusal, or
  - a dispatch fence that makes a later send impossible, or
  - an audited operator resolution.

  `PENDING_SUBMIT` or a null `submitted_at` alone is not proof.
- **I3, gate before work.** No code path:
  - writes `SCREEN_RUNNING`/`FULL_RUNNING`,
  - admits an acquisition,
  - claims a sample, or
  - dispatches an upload or prompt

  while a blocking unresolved item (§4) exists. The check is serialised with the
  writers of the rows it inspects (§6.1).
- **I4, liability keeps exposure.** Unresolved liability keeps its canonical exposure,
  through ACTIVE protection or canonical EXPIRED/accrued accounting, until final
  settlement. Recovery never renews or reactivates a hold, and never places a
  replacement STORAGE hold. Each acquisition's single original STORAGE hold is
  released only in sweep finalization, under §6.3.
- **I5, recovery never spends.** RECOVERY and CLEANUP may only:
  - read;
  - adopt;
  - verify uploaded input by checksum readback;
  - persist outputs;
  - stop and terminate;
  - take the canonical cleanup grant.

  They refuse create, upload POST, prompt POST and any other reservation.
- **I6, replay converges.** Re-running any command after a crash at any boundary
  (transaction commit, external-effect acceptance, object persistence) yields the same
  durable end state, with no duplicate holds, settlements, audit rows, assets or effects.
- **I7, honest outcome.**
  - The outcome is set once.
  - `NEEDS_RECONCILIATION` is cleared only by `reconcile`.
  - A failed fixed sample fails the experiment (§7.4), however the failure was observed.
  - A reopened liability after an operator attestation is reported as an incident,
    never as uninterrupted protection.

## 3. World modes, provenance, binding

### 3.1 Modes

Replace `cleanup_only: bool` with `mode ∈ {EXECUTE, RECOVERY, CLEANUP}`.

| Mode | Built from | Eligibility | Permitted |
|------|------------|-------------|-----------|
| EXECUTE | supplied authorization file (byte SHA) + current quote + seal | all current checks (map §5) | all effects |
| RECOVERY | durable records only (§3.2), per acquisition | identity only, no expiry/rights/quote-freshness checks (§C "existing attested world") | I5 set |
| CLEANUP | as RECOVERY | identity only | stop/terminate/readback, finality, billing |

- RECOVERY and CLEANUP refuse create, upload POST, prompt POST and new reservations
  (except the canonical cleanup grant) with `EffectDenied`. The refusal must sit at
  three layers: the composition guard, the request guard and the transport-call guard.
  Reuse `experimental_world.py:815/845/443/922/937`.
- **Every mode** requires a non-null durable object store, or construction fails.
- The CLI builds the filesystem store for every command, including `reconcile` and
  `resolve` (map §5).
- **One world per acquisition.** The Comfy client refuses rebinding, so recovery
  composes a separate RECOVERY world, with its own client, per acquisition it touches.

### 3.2 Authorization and quote provenance (SC-8)

Additive columns in migration 0026, edited in place: it has never been applied outside
test DBs.

- `benchmark_authorizations`: add `source_bytes BYTEA NOT NULL` and keep
  `authorization_sha256` = SHA-256 of those exact bytes.
- At accepted execution, persist the validated file's exact bytes, the byte SHA and the
  parsed payload in one row.
- `benchmark_acquisitions`: add `authorization_sha256 TEXT NOT NULL`, the authorization
  accepted for this acquisition, set at admission. Each acquisition already records its
  quote.
- RECOVERY for an acquisition:
  1. Load that acquisition's authorization row.
  2. Verify `sha256(source_bytes) == authorization_sha256`.
  3. Verify that parsing `source_bytes` equals the stored payload.
  4. Use that acquisition's recorded quote.

  Never select "latest by timestamp".
- No legacy rows exist. If a row lacks `source_bytes`, RECOVERY refuses and requires the
  original file (`--authorization` with matching byte SHA).
- **No acquisition yet:** RECOVERY needs no quote. Status, reconciliation and cleanup
  of a sample-less, acquisition-less experiment are no-effect operations.

### 3.3 Expired reservations during recovery (SC-6)

`BudgetService.expire_stale()` may legitimately move a hold to EXPIRED with its
exposure retained (§A). In benchmark RECOVERY only, the Comfy request guard
(`live_world.py:334`, today ACTIVE-only) accepts an EXPIRED reservation when all of the
following hold:

- its exposure is retained, i.e. not settled or released;
- it is linked to this experiment, job, operation and pod;
- the request is a recovery read (`/queue`, `/history`, `/view`) or an output persistence.

**R4:** the linkage that must be proved depends on the read:

- **Output and history recovery:** prove the exact experiment, acquisition,
  reservation, job, operation and pod linkage.
- **Checksum input readback before a prompt operation exists:** prove the exact
  experiment, acquisition, reservation, job, pod and durable upload-intent linkage
  instead.

This exception authorises only scoped recovery GETs and durable output persistence. It
never authorises operation creation, pod creation, upload POST or prompt POST. It does
not weaken the mode or transport guards, which must be implemented independently of
whether a reservation state is accepted.

All other guards are unchanged. Terminal finalization settles ACTIVE and EXPIRED
liability through the canonical path. The early return in `_settle_if_needed` for
non-ACTIVE reservations must handle EXPIRED-with-exposure correctly. Never reactivate
a hold.

### 3.4 Recovery binding (SC-13)

`world.bind_for_recovery(acquisition_id) -> BOUND | VERIFIED_SOURCE_GONE | INDETERMINATE`:

| Result | Condition |
|--------|-----------|
| `VERIFIED_SOURCE_GONE` | The lease has no `pod_id` and its create intent is resolved; or the pod's termination is verified (`terminate_verified_at`); or the owned GET positively reports the pod absent after verified termination. |
| `BOUND` | The pod is running with an endpoint, and `bind_pod_endpoint(pod_id, endpoint_url)` succeeded. |
| `INDETERMINATE` | Everything else: manager errors, a running pod without an endpoint, temporary unreachability, or a podless lease with an unresolved create. |

It never calls `ensure_pod`.

## 4. Unresolved items and the gate

### 4.1 Definition (SC-2, SC-3, SC-10, SC-11)

Items are derived from **canonical** lease, reservation, operation and upload records,
through immutable linkage: the acquisition's compute/storage reservation and lease, and
each sample's fixed `:a1` reservation and its job and operation. They are not derived
from benchmark labels alone.

| Kind | Predicate | Blocks |
|------|-----------|--------|
| **U1** create uncertain | A lease linked to an experiment acquisition has a committed create intent, no `pod_id`, and no resolution (positive adoption or audited `NO_CREATE_PROVEN`). This is independent of the acquisition label. | admission, claims, dispatch |
| **U2** cleanup owed | An acquisition for which shutdown has begun or cleanup is required, and whose benchmark finalization (§6.3) is incomplete. That covers: `CLEANUP_PENDING`; a passed recovery deadline **while an ambiguity on that acquisition remains unresolved** (SC2-2); an outcome set; or a terminal canonical lease. **A healthy ACTIVE acquisition inside its execution window is not U2**, even though its cleanup and storage invoice are in the future. A successfully recovered episode's historical deadline does not, by itself, block or terminate later healthy work. **R1:** U2 also includes an acquisition in `NO_CREATE_PROVEN` whose sweep finalization is incomplete. Its exclusion from the partial unique index does not authorise the next acquisition: admission must reject this U2 under lock until the original STORAGE reservation is canonically finalised. Sweep must process these rows for finalization, including rows whose resolution is later contradicted (today sweep skips them, `benchmark_service.py:507`). | admission of the **next** acquisition, and any dispatch on that acquisition |
| **U3** submit uncertain | A sample's fixed reservation links to an operation in `UNKNOWN`, or in `PENDING_SUBMIT` with no durable pre-dispatch refusal (§5.2). Reached through the reservation even if `sample.operation_id` is null. | claims, dispatch |
| **U3p** in flight (R2) | A sample's fixed reservation links to an operation in `SUBMITTED` or `RUNNING`, including when `sample.operation_id` is null. Recovery adopts the existing linkage and polls that operation before allowing another sample or acquisition. It never submits again. | fresh acquisition and sample admission, until recovered and finalised |
| **U3u** upload uncertain | An upload intent in `INTENT`/`UNKNOWN` without checksum-verified readback (§5.3). **Acquisition-scoped (R2):** it blocks every dependent sample. It stops blocking only after checksum verification, or after cleanup or an audited resolution has durably fenced its send right and finalised the affected sample and its liability. | every dependent sample; cleanup is allowed |
| **U4** terminal not finalized | A sample-linked operation that is terminal, but whose settlement/release is incomplete, or whose sample is not projected, or whose slot is still occupied | claims |
| **U6** materialization incomplete | Acquisition intent and holds committed without job/lease links; or a sample claim and hold committed without a job or operation. These are local-only states (§F `ADMITTED_WITHOUT_JOB`). | the effect on that item until replayed |
| **U5** reopened liability | An acquisition whose podless-create resolution has been contradicted (a pod was bound later), and whose discovered resource is not yet finalized (terminate verified, ownership closed, billing final). Historical `contradicted_at` alone does not block after finalization. | admission, claims, dispatch |

- **Blocking scopes (R2):**
  - U1, uncertain U3/U3u and U5 block fresh acquisition admission and new generation
    across the whole experiment.
  - U3p and U4 block fresh acquisition and sample admission until the existing work is
    recovered and finalised.
  - Local materialization, scoped recovery reads, settlement and cleanup stay
    permitted. This keeps §A's "Provider uncertainty blocks new work."
- **First-send right (SC2-1):** for each effect (create, upload, prompt), distinguish the
  original first-send invocation from recovery of a pre-existing intent.
  - The original invocation may use its exclusive first-send right once, while its
    original ownership token remains valid. Its own newly committed intent
    (`PENDING_SUBMIT`, upload `INTENT`, create intent) does not block that exact send.
  - Every other blocking item still applies.
  - Replay and takeover never acquire this right.
- **U6 (SC2-1):**
  - U6 permits local materialization.
  - Once canonical sample job and hold ownership exist, the absence of a prompt
    operation alone does not prohibit original input staging.
  - A prompt POST still requires the canonical operation to have been begun.
  - After ownership is lost, existing intents are reconciliation-only.
- One repository function, `unresolved_items(tx, experiment_id) -> list[Item]`, is used
  by every caller.
- U6 is **not** an uncertain external effect. Recovery replays the exact §F request and
  adopts the existing reservation without a new hold. If an expired pre-effect intent
  cannot be materialised, it closes only positively unused liability through canonical
  handling.

### 4.2 Gate placement (SC-7)

- **CLI `resume` order:**
  1. Run identity-checked RECOVERY from durable records, **before** validating any
     new-generation argument, flag, authorization file or quote. Today `benchmark.py:115`
     validates them first, and that ordering is removed for this stage.
  2. If blocking items remain, return reconciliation status and dispatch nothing.
  3. If none remain but current authorization, flags, rights or quote do not permit new
     work, return the recovered durable status plus an **admission blocker**, and
     dispatch nothing.
  4. Only then run execute-style admission. Derive the phase from durable state: a
     current screening PASS means `full`, otherwise `screen`. The CLI default `screen`
     never overrides a durable PASS.
- **`execute`:** call `unresolved_items` under the §6.1 lock order. Refuse if anything
  blocks. Predicate the state write on its source:
  - from `PREPARED`;
  - from `SCREEN_REVIEW` (full phase, with a current PASS);
  - from `SCREEN_RUNNING`/`FULL_RUNNING` (same phase).

  Never from `NEEDS_RECONCILIATION`.
- **`_acquisition`, `_claim_sample` and the dispatch step** re-evaluate the relevant
  items inside their own locked transactions and refuse.
- **`reconcile`** is the only writer of `NEEDS_RECONCILIATION` → running, and only with
  zero blocking items under lock. Remove the shortcut write from `resolve_create`.

## 5. Ambiguity at run time

### 5.1 Classification (SC-3)

Under the §6.1 order (E before A):

- **Create ambiguity:** acquisition → `UNKNOWN` (U1 holds regardless of the label).
- **Upload ambiguity:** the upload intent stays `INTENT`/`UNKNOWN` (U3u). No prompt
  operation is invented.
- **Submit or poll ambiguity:** the operation is `UNKNOWN` per §5.2. The acquisition
  stays `ACTIVE`.

In every case, the experiment moves to `NEEDS_RECONCILIATION` in the same transaction.

### 5.2 Pending submit (SC-4)

On recovery takeover (the coordinator token has expired, or the stale coordinator is
fenced), an existing `PENDING_SUBMIT` operation without durable pre-dispatch-refusal
proof is moved to `UNKNOWN` under the operation lock. Recovery then:

1. Looks it up by deterministic client identity or recorded prompt ID via `/queue` and
   `/history`.
2. On no match, keeps it `UNKNOWN` with its exposure.
3. On **more than one** matching prompt ID, keeps it `UNKNOWN` and reports a conflict.
   It never adopts the first match.
4. **Never POSTs it again.**

An empty but reachable history stays ambiguous. A live coordinator holding a valid
token is never preempted.

### 5.3 Upload intents (SC-3)

Existing upload intents reconcile **only** by checksum-verified input readback
(`/view?type=input`).

- Verified: mark the intent done.
- Unverifiable: the sample cannot dispatch. The item stays U3u until cleanup or an
  audited resolution (the sample is FAILED under §7.4).
- Never a second upload POST.

### 5.4 Durable recovery grace (SC-5)

Applies to submit and poll ambiguity on a live, `BOUND` pod.

- **Persist before entering grace,** on the acquisition (additive 0026 columns):
  - `recovery_started_at`;
  - `recovery_deadline` = the **earliest** of:
    - first ambiguity + 600 s (module constant `RECOVERY_GRACE_MAX_S`);
    - `hard_stop − shutdown_margin`;
    - the acquisition's funded-work deadline (compute hold runtime from
      `create_intent_at`);
    - the remaining aggregate GPU allowance.
- **R3, absolute timestamps only.** Every operand of `recovery_deadline` is an absolute
  timestamp.
  - The funded-work deadline is defined with its shutdown allowance already excluded.
  - The aggregate GPU deadline is the earliest timestamp at which the sum of all
    durable acquisition windows (including reopened windows) plus reserved shutdown GPU
    time reaches the effective GPU limit.
  - Never compare a remaining duration directly with timestamps.
- **Restart, takeover and janitor reuse the persisted deadline.** No one grants a fresh
  grace. They may *shorten* the deadline when newly discovered liability exhausts the
  remaining allowance; they never extend it.
- **SC2-2, deadline scope:**
  - The deadline condition and deadline-driven cleanup apply only while an ambiguity
    on that acquisition remains unresolved.
  - Successful terminal recovery closes that recovery episode.
  - The persisted deadline is kept. A later ambiguity on the same acquisition reuses
    it, and starts cleanup immediately if it has already elapsed.
  - Ordinary funded-runtime, aggregate-GPU and hard-stop limits stay independently
    enforceable.
- **R3, deadline fence.** At deadline exhaustion, sweep or the janitor first commits a
  cleanup fence under the §6.1 lock order:
  1. Revoke the acquisition's coordinator token and the matching dispatch-slot token.
  2. Prevent further execution on that acquisition.

  This is an explicit exception to "never preempt a valid coordinator". Cleanup then
  runs outside the transaction. Every later coordinator control write and first-send
  authorisation checks the matching token in its own transaction. Revoking the token
  does not prove that an already-authorised external send never happened: such effects
  stay subject to reconciliation and get no replacement send right.
- **During grace:**
  - accrue canonical lease usage;
  - heartbeat the owned lease without extending its expiry, reservation or GPU window;
  - bound every nested recovery HTTP request by the time left before
    `recovery_deadline`.
- **At the deadline,** cleanup **starts** even if an intermediate call failed. Cleanup
  requests stay usable after the deadline. Provider failure can delay verified
  termination past the hard stop, and that overrun is recorded as liability, never
  declared impossible.
- **Coordinator death during grace:** an independently invoked `sweep`/janitor reads
  `recovery_deadline` and finishes cleanup at or after it. A stale coordinator that
  returns is fenced by the dispatch-slot token: it may not dispatch, and its writes are
  predicated on the token.
- **Grace succeeds:** run terminal finalization (§7.1). `reconcile` clears
  `NEEDS_RECONCILIATION`, and the run continues if no blocking item remains.
- **Grace expires:** cleanup terminates the pod. The operation stays `UNKNOWN` with
  exposure retained (I4). It closes only by audited resolution (§7.3).

Create ambiguity gets no grace. Sweep and the janitor reconcile it by token, under U1.

## 6. Locking, create resolution, contradiction

### 6.1 Shared lock order (SC-9)

Every **modified** benchmark transaction, and every transaction the gate must serialise
with, acquires locks in this order:

1. **account**
2. **categories**
3. **E**
4. **A** rows, by id
5. billing advisory lock, then **L** rows, in deterministic lease-id order
6. **D**
7. **S** rows, by id
8. **R** (reservation) rows, by id

No network call is made while these locks are held.

Required changes:

- **`BillingRepository.resolve_podless_create`** (canonical wrapper): acquire account
  and categories **before** its advisory lock and L. Expose
  `resolve_podless_create_in_tx(tx, …)`; the caller has already taken locks 1–5.
- **Ambiguity handling:** lock E before updating A (today it writes A, then E).
- **`_observe` projection:** lock D before S (today it writes S, then D).
- **Sweep finalization:** move its lease read (today unlocked, `:533`) into the locked
  finalization decision (§6.3).
- **`reserve_linked` and `_claim_sample`:** acquire any needed L locks before D. Never
  take an L lock after D, S or R.
- **Every gate decision** reads its rows under the locks above. Holding E alone is
  insufficient.
- **R5, extended order:**
  - After the R rows: the existing provider job/reservation advisory locks where
    needed, then **O** (provider-operation) rows by id, then **upload** rows by their
    immutable key.
  - Gate decisions lock the relevant existing operation and upload rows.
  - Benchmark operation and upload insertion must also serialise through the
    corresponding locked reservation/acquisition ownership row, so that a query for an
    absent row cannot race a new intent into existence.
  - Canonical operation-only result transactions may keep their suffix-only locking,
    but must not take earlier-order benchmark or budget locks afterwards.
  - Operator terminal-transition transactions commit before invoking financial
    finalization.
- Add a module docstring with the transaction inventory (function → locks → writes),
  and keep it accurate. **R5:** the inventory must explicitly distinguish canonical
  suffix-only transactions from the full-order benchmark transactions.

### 6.2 Operator create resolution (SC-1, CN3-3)

`resolve_create` is **one transaction** in the §6.1 order.

0. **Replay first (SC2-3).** Under the same locks, and before any unresolved-state
   precondition, look for an existing uncontradicted no-create resolution with an
   identical actor, reason and evidence SHA.
   - **Found:** return a successful replay, with no new audit or settlement, and let
     the pending sweep finalization complete.
   - **Different attestation data, a bound pod, or a contradicted resolution:**
     `Conflict`.

   The preconditions below apply only to a **first** resolution.
1. Under lock, re-check all of these; on any failure, refuse with `Conflict` naming
   the reason and write nothing:
   - A is `UNKNOWN`, or its U1 predicate holds;
   - `L.pod_id IS NULL`;
   - the resolution is not contradicted;
   - `create_requested_at` is as captured.
2. Call `resolve_podless_create_in_tx`: audit, window end, zero-BILLED **compute**
   settlement.
3. Write `NO_CREATE_PROVEN` and end the acquisition window.
4. **Do not release the STORAGE hold.** It is released only by sweep finalization
   (§6.3). With nothing to delete, that finalization can run immediately after
   resolution, in a later sweep.

### 6.3 Storage-hold release (SC-1)

Only the **sweep finalization transaction**, in §6.1 order, may release an
acquisition's single original STORAGE hold. It must re-check, under lock:

- durable proof that no storage exists (`NO_CREATE_PROVEN`, not contradicted), **or**
  verified deletion/termination;
- canonical disk-allocation invoice finality for that acquisition;
- no U5 for it.

A historical `pod_id` does not prevent finalization. Recovery never creates a
replacement STORAGE reservation.

### 6.4 Late contradiction: incident path (SC-10)

The janitor's late adoption already binds `pod_id` and marks the resolution
contradicted in one L-locked transaction (map §6). That pair **is** the reopened
obligation, derived as U5. No benchmark row is rewritten by the canonical janitor.

- **Never reopen the old acquisition row into the partial unique index.** It stays
  `NO_CREATE_PROVEN`, with U5 derived. If a newer acquisition holds the slot, U5 still
  blocks all further dispatch on the experiment.
- U5 resolves through cleanup of the discovered pod: terminate verified, ownership
  closed, billing final.
- **GPU accounting:** `gpu_ms()` includes a contradicted acquisition from its original
  `create_intent_at` through verified termination of the discovered pod. It ignores
  the disproved no-create window end, and gives no new allowance at discovery.
- **Admission (Q3):** `_acquisition` locks every prior lease of the experiment (step 5)
  before evaluating U1/U5. This serialises with **already-visible** adoption only. A
  pod that appears after admission commits is handled by this incident path: blocking
  U5, cleanup, a status/export incident record naming the attestation and actor, and
  the reopened liability reported. No locking can promise that a pod never appears
  after an operator's no-create attestation. The spec promises correct handling, not
  impossibility.

## 7. Terminal recovery and operator sample resolution

### 7.1 Terminal finalization (SC-11)

`finalize_terminal(operation)` is network-free and idempotent:

1. Complete canonical settlement or release for ACTIVE or EXPIRED-with-exposure
   reservations.
2. Load the existing durable assets.
3. Project the sample.
4. Clear the matching dispatch slot.

Steps 3–4 run in one transaction (D before S).

**R6, atomic fail-fast.** After canonical financial finalization, the following commit in
**one transaction**:

- projecting an eligible failed fixed sample;
- setting `execution_outcome=FAILED` if unset;
- stopping generation;
- clearing its matching dispatch slot.

Lock order: **E before D before S**, with any required earlier locks taken first.
Before projection completes, U4 blocks fresh work. Replay repairs the same failure
outcome idempotently. Replay repeats all stages.
`reconcile` calls it for every U4 item. Grace success and normal poll completion call
it too.

### 7.2 Mapping and monotonic projection (SC-11)

| Canonical | Sample |
|-----------|--------|
| `SUCCEEDED` | `SUCCEEDED` |
| `FAILED`, `CANCELLED`, `NOT_FOUND` | `FAILED` (original reason kept) |

- `NOT_FOUND` never enables benchmark resubmission.
- Add `CANCELLED`/`NOT_FOUND` handling to `_observe` slot clearing.
- Projection under D/S locks is **monotonic**: a stale nonterminal observation never
  overwrites a terminal sample.

### 7.3 Operator resolution (SC-13, CN3-5)

- **Atomicity:** the audit event and the operation's terminal transition (`FAILED`,
  operator reason) commit together under the O lock. Today they are separate
  (`comfy_jobs.py:1045/1093`). Then `finalize_terminal`.
- **Replay before any live check:** if the operation is already terminal with an
  operator audit of the same actor, reason and evidence SHA, return success and run
  `finalize_terminal`. A different attestation → `Conflict`. An operation that is
  terminal **without** an operator audit → `Conflict` (terminal provenance);
  `reconcile` handles it by ordinary terminal replay.
- **Live-source rule (R7, precedence):**
  - Ordinary resolution requires `bind_for_recovery = VERIFIED_SOURCE_GONE`.
  - `BOUND` with **positively recoverable work or usable output** requires
    reconciliation and refuses operator resolution, **even with force**.
  - Reachability alone is not recoverability: empty, missing, conflicting or unusable
    history stays ambiguous.
  - Reachable-but-unrecoverable cases, and `INDETERMINATE` cases, require
    `--force-unrecoverable` plus the recorded attestation. The override is recorded in
    the audit.
  - Identical-attestation replay is accepted before any live-source check.

### 7.4 Outcome policy (SC-12)

Keep the current fail-fast rule. Any eligible fixed sample finalised `FAILED` (including
mapped `CANCELLED`/`NOT_FOUND`) sets the experiment outcome `FAILED` once and stops new
generation. This applies equally when the failure arrives through normal polling,
`reconcile` or operator resolution. `reconcile`/`resolve` still complete financial
finalization, clear slots and run cleanup through to billing closure.

Continuing evidence collection after a sample failure would be a separate future
policy. It is out of scope.

## 8. Persistence additions (migration 0026, edited in place)

Additive only:

- `benchmark_authorizations.source_bytes`;
- `benchmark_acquisitions.authorization_sha256`;
- `benchmark_acquisitions.recovery_started_at` / `recovery_deadline`;
- any index needed by `unresolved_items`.

Every 0026 guard (no-delete/no-truncate/integer-only) applies to new and changed tables.
Update the migration and schema-catalog test expectations.

## 9. Acceptance tests

### 9.1 Rules

- Drive **public** entry points: `BenchmarkService.execute/resume/reconcile/
  resolve_create/resolve_sample/sweep` and the CLI `main()`. **Exception:** AT-10
  deliberately calls private admission helpers.
- **Fresh objects every step.** Each step gets new service objects and a new world.
- **Real PostgreSQL connections** for every lock and race test (two or more
  connections, barrier-driven).
- **At least one real subprocess-death test:** the CLI runs in a subprocess, is killed
  with SIGKILL at an injected point, and is restarted.
- **Crash injection** happens around:
  - transaction commits;
  - external-effect acceptance (after the POST is accepted, before the result commits);
  - object persistence.

  It bypasses ordinary exception cleanup (`os._exit` in the subprocess, or a
  `BaseException` subclass not caught by handlers).
- **Clients and transports:** the real `PikaHttpClient`/`ComfyHttpClient` with
  `urlopen` faked, and the scripted Runpod transport.
- **The fake ComfyUI server lives only as long as its fake pod.** Termination makes it
  unreachable.
- **Cleanup fixture:** require `terminate_verified_at` and canonical billing readiness.
  Restore the two dropped unconditional assertions (map §8,
  `test_benchmark_experiments.py:255–268`).
- **Never call `_advance` directly.**

### 9.2 Tests

| ID | Scenario | Proves |
|----|----------|--------|
| AT-0 | A healthy ACTIVE acquisition claims its first and later samples | U2 doesn't block normal execution (SC-2) |
| AT-1 | Prompt POST times out; history shows the prompt within the grace | Recovered, zero resubmit, output persisted, run continues (I1, I6) |
| AT-2 | Prompt POST times out; history never shows it | Pod terminated at `recovery_deadline`; op UNKNOWN, exposure retained; fresh `resume` makes no state write; `resolve --sample-id` → sample FAILED → experiment **FAILED** (§7.4); cleanup and billing reach closure; no further dispatch (I2, I4, I7) |
| AT-3 | Worker SIGKILLed mid-poll, pod alive; fresh-process CLI `reconcile` | `bind_for_recovery` = BOUND from the durable lease; output into the CLI-built store; zero POSTs (I5) |
| AT-4 | `reconcile`/`sweep`/`resume` after the authorization, quote and rights deadlines, with no generation arguments | Recovery works through the CLI; `resume` returns status plus an admission blocker; any create/upload/prompt → `EffectDenied` at all 3 guards; zero sends (I5, §C) |
| AT-5 | `resume` with an acquisition in `CLEANUP_PENDING` and a released lease | No `acquire()` on a terminal lease; no spurious FAILED; next acquisition admitted only after finalization (I3) |
| AT-6 | `resolve_create` racing janitor late adoption at every boundary (parametrised) | Before finality: resolution refuses, or the contradiction becomes U5 with STORAGE still held (resolution never releases it). After a later contradiction: incident path (I4, SC-10) |
| AT-7 | Late adoption **after** a newer admission commits; then cleanup and replay | No index collision; U5 blocks dispatch then clears after finalization; GPU time counted from the original intent (SC-10) |
| AT-8 | Crash between the operator-resolution commit and finalization | Replayed `resolve` succeeds idempotently; `reconcile` runs `finalize_terminal`; one settlement, one audit row (I6) |
| AT-9 | Crash at **every** boundary of `reconcile`, `resolve_create`, `resolve_sample`, the ambiguity handler and sweep finalization (parametrised over the transaction inventory) | Converges; table counts show no duplicates (I1, I6) |
| AT-10 | Private `_acquisition`/`_claim_sample` while each of U1–U6 exists | Refused inside the locked transaction (I3) |
| AT-11 | `resume` phase derivation, with and without a durable PASS, while the CLI passes `screen` | PASS → `full` (§4.2) |
| AT-12 | Money projection after the scenarios above | **R8:** exposure equals canonical accrued plus settled counters, plus `max(reserved − accrued, 0)` only for ACTIVE reservations, plus distinct linked unreserved non-CREDIT usage. EXPIRED reservations contribute their canonical accrued/settled counters and zero open remainder; expired exposure is never added twice (§A). Also covers late adjustments and §G evidence dedup on replay (I4) |
| AT-13 | Canonical create intent committed, crash before A → UNKNOWN | U1 detected without the label |
| AT-14 | Claim and hold committed, no job/operation; before and after hold expiry | U6 replay adopts without a second hold; after expiry, only unused liability is closed (§F) |
| AT-15 | `PENDING_SUBMIT` (a) crash before POST, (b) POST accepted before the result commit; identical durable state | Both become UNKNOWN on takeover; no resubmit; (b) is adopted via client id; (a) stays UNKNOWN → audited (I2) |
| AT-16 | `SUBMITTED`/`RUNNING` operation, crash before `sample.operation_id` is written | Found via the reservation linkage; finalised (SC-3) |
| AT-17 | Upload POST ambiguity, no prompt operation | Checksum readback verifies or blocks; no second upload; no invented prompt op (§5.3) |
| AT-18 | Grace near the compute, GPU and hard-stop limits, with a slow nested request | Deadline = earliest limit; nested requests bounded; cleanup starts by the deadline (SC-5) |
| AT-19 | Process death during grace; janitor/sweep takeover; the stale worker returns | Persisted deadline reused; stale worker fenced from dispatch (SC-5) |
| AT-20 | `expire_stale()` during UNKNOWN recovery | EXPIRED liability stays in the projection, is readable under §3.3, and is finalised by canonical settlement (SC-6) |
| AT-21 | Lock races: billing wrapper vs `resolve_create`; `_claim_sample` vs `_observe`; ambiguity vs admission; sweep vs resolution | No deadlock (bounded `lock_timeout` in tests), no unsafe release (SC-9) |
| AT-22 | Terminal commit before settlement; output persisted before the terminal commit | Financial and asset recovery converge (SC-11) |
| AT-23 | Authorization file with non-canonical formatting; two acquisitions under different authorizations | Byte SHA verified from the stored bytes; each acquisition recovers with its own authorization and quote (SC-8) |
| AT-24 | Experiment with no acquisition: `reconcile`, `sweep`, `resume` after expiry | No quote needed; no effects (SC-3) |
| AT-25 | Client-id lookup returns two prompt IDs | Stays UNKNOWN; conflict reported; nothing adopted (§5.2) |
| AT-26 | Canary and canonical suites (`test_t045_*`, canary composed) after the §6.1 billing-wrapper change | Still green |

### 9.3 Required test extensions (from round-2 critique)

| Extend | Must also prove |
|--------|-----------------|
| AT-0 / AT-10 | Drive the real first create, upload and prompt sequence through all the guards. The original sends succeed once; replay and takeover sends fail (SC2-1). |
| AT-6 / AT-9 | Resolve no-create without adoption. Admission stays blocked until STORAGE finalization (R1). Replay identical and different attestations, before and after sweep (SC2-3). |
| AT-16 / AT-17 / AT-20 | A known in-flight operation with missing sample linkage (U3p); acquisition-scoped upload blockers; EXPIRED input readback with no prompt operation (R4); wrong owner, wrong mode, and POST refusals. |
| AT-18 / AT-19 | Recover successfully, continue past the historical grace deadline, then hit another ambiguity (SC2-2). Fence a still-valid coordinator token, and assert that stale **control writes** fail as well as stale dispatch (R3). |
| AT-9 / AT-22 | A crash between failed-operation settlement and the failed-sample/outcome/slot projection, for each of FAILED, CANCELLED and NOT_FOUND (R6). |
| AT-21 | Race the gate evaluation with operation transitions and upload-intent insertion, including rows that are initially absent (R5). |
| AT-8 / AT-25 | The binding × recoverability × force matrix, and identical replay before live checks (R7). |

**Death harness:** a `BaseException` subclass does **not** bypass cleanup, because
`_advance_owned` catches `BaseException` (`benchmark_service.py:364`). Use SIGKILL or
`os._exit` in a subprocess, or demonstrate that each alternative injection escapes
cleanup. Fake provider state and send counters must survive the killed process, e.g.
in a file or the database, not process memory.

## 10. Build constraints and done criteria

- Build on `feat/t031-fix3` at `82135d4`, which includes the Luna WIP for H-3..H-9
  (under separate GLM review). Replace the `628fe5b` H-2 implementation wherever this
  spec differs; keep everything else.
- Offline only. The hard limits of `T031-fix-round/fix3-brief.md` apply. No contract
  package change. 0026 is edited in place per §8.
- Tests-first: record the red run per AT before implementing.
- Done when:
  1. AT-0..AT-26, the touched suites, `make lint` and `make contracts-check` pass.
  2. The transaction-inventory docstring is written.
  3. The report covers: red/green per AT; the inventory table; the lock order per
     touched transaction; and every place the builder had to choose, with the reason.
  4. The orchestrator's full `make check` + `make pilot` pass.
  5. Codex reviews the build diff. Codex didn't write this code; GLM builds it.

## 11. Decisions on v1's open questions

- **Q1:** keep 600 s as a documented maximum constant. The effective deadline is the
  durable earliest-of from §5.4. No authorization field.
- **Q2:** keep the original STORAGE hold. Release it only in sweep finalization (§6.3).
  No replacement hold.
- **Q3:** lock the handful of prior leases at admission, and keep the §6.4 incident path
  for adoption after admission.

## 12. Finding → section map

| Finding | Section |
|---------|---------|
| SC-1 | §2 I4, §6.2, §6.3 |
| SC-2 | §4.1 U2, AT-0 |
| SC-3 | §4.1 U1/U3/U3u/U6, §5.1, §5.3, AT-13/14/16/17/24 |
| SC-4 | §2 I2, §5.2, AT-15 |
| SC-5 | §5.4, AT-18/19 |
| SC-6 | §2 I4, §3.3, AT-20 |
| SC-7 | §4.2, AT-4 |
| SC-8 | §3.2, §8, AT-23 |
| SC-9 | §6.1, AT-21 |
| SC-10 | §4.1 U5, §6.4, AT-6/7 |
| SC-11 | §7.1, §7.2, AT-8/22 |
| SC-12 | §7.4, AT-2 |
| SC-13 | §3.4, §7.3, AT-25 |
| SC-14 | §9.1, AT-0..AT-26 |
