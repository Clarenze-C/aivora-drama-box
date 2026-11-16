Verified checkout: `628fe5b40ab19c6d5d1befb8539f3b6a90c2204a`. Read-only inspection; no tests or network calls.

Source references below are relative to `microdrama/src/microdrama/`, except paths explicitly starting with `tests/`, `migrations/`, or `/root/`.

**1. Contract text, verbatim**

From `/root/AIVORA/drama-box/docs/microdrama-system/T031-integration-contract.md`. §A excerpts concern expiry/finality; §§C, E, F and G are reproduced below.

§A heading at line 6; clauses at lines 39–59:

```text
## A. Canonical reservation extension and sub-limit

- Expiry follows canonical expired-accrual policy, not a benchmark-specific release.
  Unknown provider liability cannot be discharged because a worker lease expired.

Create a separate canonical CPU_STORAGE_TRANSFER hold for each acquisition's
attested worst storage exposure, before create. Use one bounded allocation REQUEST
quote whose unit price is that attested exposure ceiling (actual quote provenance,
USD; operation `benchmark.storage_exposure`), one unit, no provider effect.
This is a financial hold, not a storage charge. The existing billing allocations
charge actual disk cost once. Release this unused protective hold only after
verified storage deletion and the acquisition's disk allocations reach invoice
finality, in the same finalization transaction. While pending, including both
actual accrued liability and the protective hold is deliberately conservative;
never present the hold as actual spend. No extra parent $8 hold exists.

New admission checks the post-insertion canonical linked exposure plus the
mandatory cleanup floor <= experiment cap and canonical episode allowance. The
candidate is already in that projection and MUST NOT be added again. An idempotent
reservation replay likewise has one linkage and contributes exactly once. The
canonical shutdown floor is counted once, using `max(canonical_floor,
experiment_floor)` rather than their sum. Provider uncertainty blocks new work;
cleanup retains the existing exception and may record an overrun truthfully.
```

§C, lines 110–165:

```text
## C. Logical preparation, sealing and authorization

`BenchmarkPlan` module-local Pydantic model: schema_version1, experiment UUID,
episode UUID, model/config ID,8 shot definitions with exact Thai/English data,
24 sample IDs/seeds,3 screen sample IDs, logical reference slots, candidate
runtime-profile hash, maximum sample count24, attempts_per_sample1,
max_new_exposure_micro_usd<=8000000, max_gpu_ms<=14400000. All integer money/time;
reject unknown fields, duplicate IDs/seeds/slots and altered matrix.
Canonical plan hash excludes the supplied experiment UUID and includes every other
plan field, including explicit experiment_nonce (default empty string), episode,
configuration, scripts, logical slots, sample IDs/seeds and caps. Same UUID plus
same hash replays; same UUID plus different hash conflicts. Another UUID plus
same (episode,canonical_plan_hash) returns the existing experiment and creates no
new samples or allowance. Intentional repeat requires a changed nonce and fresh
authorization, still charged to the same unreplenished account. Acceptance tests
must separately cover all three replay/conflict/alias cases. A repeat of
an identical failed experiment is not silently allowed: same episode/plan key
replays; a deliberate new experiment requires a changed explicit experiment_nonce
inside the hashed plan and a fresh authorization, without replenishing its account.

`prepare --plan --experiment-id` atomically creates logical plan+samples, no
reservation/effect. Unresolved slots are represented by role/subject strings,
not fabricated hashes. `seal --experiment-id --manifest` atomically inserts one
immutable `BenchmarkSeal`: plan hash, exact asset UUID/version/byte hashes, role
map, runtime profile, image digest, actual node-schema attestation/hash, exact
pixel bucket/frame grid/fps, rights evidence/territories/expiry, evaluator policy,
absolute deadline. Sealing is local data preparation, not permission to spend.
Missing runtime/assets => NOT_READY; no fake production readiness record.

`BenchmarkAuthorization` is a module-local JSON object: schema_version1,
operator/change_ref, experiment_id, plan_sha256, sealed_sha256, episode_id,
provider_account_ref, max_new_exposure_micro_usd, max_gpu_ms, max_samples24,
max_attempts_per_sample1, hard_stop_utc, allowed_gpu_types, minimum_host_ram_gb,
max_hourly_micro_usd, max_storage_exposure_micro_usd, container_disk_gb,
persistent_volume_gb, shutdown_reserve_micro_usd, namespace, FILE credrefs and
rights_evidence_hash. Reuse canary validation rules for credential syntax, USD,
full image digest and loopback-only DSN without altering CanaryAuthorization.
The operator supplies its byte SHA256 on execution. No cryptographic signature
is invented. Validate exact seal/plan/account and cap <= proposed envelope.

`AcquisitionQuote` is append-only per new acquisition, separate from that
immutable authorization: quote_id, captured/expires_at, currencyUSD, exact GPU ID,
host RAM, compute unit/rate, storage rates/sizes, maximum runtime/storage exposure
and source evidence hash. Quote must fit authorization hardware/rate/storage
ceilings, absolute deadline and remaining aggregate funds/time at admission.
Refreshing a quote never changes the experiment or grants a fresh envelope.

Commands: `prepare`, `seal`, read-only `preflight`, `status`,
`execute --phase screen|full`, `resume`, `record-screening`, `sweep`, `export`.
Preflight may read guarded loopback PostgreSQL but makes no external HTTP or
provider secret resolution. Any execute/resume path admitting new generation or
acquisition requires current authorization+flags+rights+quote. Resume may instead
perform only status/reconciliation/cleanup with the existing attested world after
quote/auth/rights expiry; it cannot dispatch. `sweep` never acquires/submits work
and must stay usable after expiry. No new spending approval is needed to stop an
owned resource. If account/ownership cannot be proven, refuse foreign actions.
```

§E, lines 235–270:

```text
## E. Transition and recovery ownership

| Durable state | Owner/transaction | Permitted next effect / recovery |
|---|---|---|
| Logical PREPARED | prepare repository | Local seal only; no effects |
| Sealed, authorized, no acquisition | admission locks account/categories/experiment/slots | Persist acquisition intent + canonical holds/linkage atomically; materialize/replay canonical job/lease by §F; then create |
| Intent+holds committed, canonical links missing | coordinator recovery | Materialize/replay fixed job/lease and adopt the existing reservation before effects |
| Intent committed, no pod ID | lease/operation reconciler | Find by durable owned token; UNKNOWN occupies slot; never create again from absence |
| Owned pod ID known | lease service persists before verify | Verify own pod/image/rate; cleanup on failure; do not activate missing inputs |
| Acquisition active, no sample | coordinator + dispatch slot | Claim next eligible fixed sample; sample workers never acquire pods |
| Sample claim+hold+job committed | dispatch coordinator | Begin operation and submit once through ComfyRenderService |
| SUBMITTING without prompt ID | provider-operation reconciler | UNKNOWN; no blind resubmit or next sample |
| SUBMITTED with ID | existing Comfy poll | Poll/fetch/checksum; resumable copy to durable objects |
| Output durable, sample not final | sample repository | Adopt exact object hashes and finalize technical outcome idempotently; no new render |
| Screen3 terminal | coordinator cleanup | Stop/terminate/delete, record closure; then SCREEN_REVIEW with no live GPU |
| Screen PASS current hashes | explicit screening record | Next acquisition only after admission with remaining funds/time; no renewed envelope |
| Failure/cancel/exhaustion | coordinator sets execution_outcome once | Stop new work; cleanup/readback/billing continue, outcome preserved |
| Compute closed, pending invoice | billing/janitor | Hold exposure, reconcile revisions; no claim BILLED from buckets |
| Final invoices+cleanup verified | finalization transaction | Closure COMPLETE; retain original success/failure outcome and all rejected costs |

Partial unique acquisition index plus dispatch slot enforces one pod and one
prompt even for workers with different samples and ample funds. Coordinator token
expiry permits reconciliation takeover, never clearing an unresolved resource.
Sample success/failure does not by itself free either slot before operation
terminal/unknown status is reconciled.

GPU-ms is sum of durable acquisition windows. Start conservatively at committed
create_intent_at; end only at verified termination (or durable proven no-create).
An open window contributes now-start and prevents a restart from renewing time.
Include startup and cleanup; stopped human-review time contributes0. Every new
acquisition reserves its remaining bounded window against aggregate GPU limit.

Cost exports reconcile `sample allocations + explicit experiment overhead` to
canonical experiment usage. Startup, idle and tail costs stay overhead unless a
predeclared deterministic basis allocates them; never duplicate them per sample.
Separate billed, provider-reported, pending liabilities and prospective holds.
```

§F, lines 272–303:

```text
## F. Reservation adoption and effect-service boundaries

Preparation does not enqueue canonical provider jobs. Admission first atomically
writes the experiment's acquisition/sample intent, immutable semantic keys,
canonical reservation and linkage. Subsequent canonical job/lease materialization
is an idempotent recovery step, not part of that first transaction. It completes
before any provider effect. This explicitly permits the intermediate state
ADMITTED_WITHOUT_JOB; resume reconstructs the same job/input/hash and adopts the
same reservation. Never take a second hold merely because a job row is absent.

Use fixed keys `benchmark:{experiment_id}:acq:{generation}` for acquisition and
`benchmark:{experiment_id}:sample:{sample_id}:a1` for samples. Derive job/render/
request UUIDs with the existing rendering namespace. Persist the exact request,
including reservation expiry, before calling a committing service, so restart
does not reconstruct a different request hash from a new wall clock.

Add `LeaseService.claim_pre_reserved(request, reservation_id)` and
`ComfyRenderService.adopt_reserved_attempt(request, reservation_id)` as internal
methods that verify canonical reservation account, provider, operation kind,
semantic key, job/sample ownership, size and ACTIVE state, then create or replay
the existing canonical lease/job links without reserve again. Factor their common
validation with the existing adoption code; preserve all public defaults.
No effect is allowed until both durable job and effect-service ownership row are
present and linked. A pre-reserved request refused before any effect records a
terminal outcome and safely closes only its own positively unused hold; UNKNOWN
create/submit retains the existing liability path.

Update recovery table's first admitted row accordingly: atomic intent+holds first;
materialize/replay canonical job/lease links next; then external create. The
canonical provider-operation service still owns submit intent and prompt-ID
persistence. This resolves the old service transaction boundary without calling
transaction-owning enqueue/claim methods from inside an unrelated open transaction.
```

§G, lines 306–317:

```text
## G. Raw billing evidence for new experiments

Phase1 retains exact provider amount strings in the internal transport record and
commits them by hash in new mapped observations. This does not make the raw strings
reconstructible from existing canonical bucket rows; do not claim otherwise.
For new benchmark acquisitions, store the nonsecret original amount strings,
pod/interval identity, normalization policy/discrepancy and raw commit hash in an
append-only `benchmark_billing_evidence` record before normalization is used for
allocation. Link experiment/acquisition and observation identity; replay dedupes
by that hash. No headers, credentials or arbitrary provider-body text are stored.
This internal evidence table supplements existing canonical financial records,
not their budget authority. Old bucket payloads are never rewritten.
```

**2. State machines**

The benchmark experiment, acquisition and sample state columns are `TEXT` without enumerated-state CHECK constraints; dispatch slots have nullable sample/token fields, not a state column (`migrations/0026_t031_benchmark_experiments.sql:6`, `:17`, `:36`, `:43`). The following are current code writes, including their actual predicates.

| Entity | State/transition and writer |
|---|---|
| Experiment | Creation → `PREPARED`: `BenchmarkRepository.prepare`, `rendering/benchmark_experiments.py:240`, using migration default at `0026…sql:6`. |
| Experiment | Any current state with nonterminal outcome accepted by execute → `SCREEN_RUNNING`/`FULL_RUNNING`: `execute`, `pipeline/benchmark_service.py:187`. No source-state predicate on UPDATE. |
| Experiment | → `NEEDS_RECONCILIATION`: `_advance_owned` ambiguity handler, `pipeline/benchmark_service.py:360`; same transaction sets acquisition `UNKNOWN`. |
| Experiment | → `SCREEN_REVIEW`/`COMPUTE_COMPLETE`: `_finish_phase`, `pipeline/benchmark_service.py:463`, after sweep reports cleanup `VERIFIED`, if outcome is null. Full completion also sets outcome `SUCCEEDED`. |
| Experiment | → supplied outcome string: `BenchmarkRepository.outcome`, `rendering/benchmark_experiments.py:335`; coordinator supplies `FAILED` at `benchmark_service.py:350`, `:365`. Existing outcome is preserved with `COALESCE`. |
| Experiment | `SCREEN_REVIEW` → `FAILED`: `screening` on FAIL, `rendering/benchmark_experiments.py:378`; screening record and outcome/state share transaction. PASS inserts evidence without changing execution state. |
| Experiment | `NEEDS_RECONCILIATION` → `FULL_RUNNING` if screening PASS exists, otherwise `SCREEN_RUNNING`: `reconcile`, `pipeline/benchmark_service.py:638`; requires no UNKNOWN acquisition, no detected UNKNOWN slot operation, null outcome. |
| Experiment | `NEEDS_RECONCILIATION` → `SCREEN_RUNNING`: `resolve_create`, `pipeline/benchmark_service.py:822`, when no UNKNOWN acquisition remains; no sample-operation or screening-PASS predicate here. |
| Acquisition | Creation → `ADMITTED_WITHOUT_JOB`: `_acquisition`, `pipeline/benchmark_service.py:230`; intent, quote, compute/storage holds and links commit together. |
| Acquisition | → `ACTIVE`: `_advance_owned` after `world.acquire`, `pipeline/benchmark_service.py:328`; `_reconcile_acquisition` after successful acquire, `:671`. Neither UPDATE predicates the prior state. |
| Acquisition | → `UNKNOWN`: `_advance_owned` catches `NeedsReconciliation`, `pipeline/benchmark_service.py:356`; applies to create, staging, submit or poll ambiguity inside its try block. |
| Acquisition | → `UNKNOWN` if previously UNKNOWN and lease remains podless; otherwise → `CLOSED` if cleanup verified and storage final, else `CLEANUP_PENDING`: `sweep`, `pipeline/benchmark_service.py:562`. Window end and any storage-hold release share this transaction. |
| Acquisition | `UNKNOWN` checked in initial transaction → `NO_CREATE_PROVEN` in later transaction: `resolve_create`, `pipeline/benchmark_service.py:759`, `:793`; storage release shares final transaction. |
| Acquisition slot | Partial unique index permits only one acquisition whose state is outside `CLOSED`,`NO_CREATE_PROVEN`: `migrations/0026…sql:40`. There is no separate acquisition-slot table. |
| Sample | Creation → `PLANNED`: `prepare`, `rendering/benchmark_experiments.py:255`, using migration default `0026…sql:17`. |
| Sample | `PLANNED` → `CLAIMED`: `_claim_sample`, `pipeline/benchmark_service.py:392`, `:406`; prompt reservation, immutable request/acquisition link and dispatch-slot assignment share transaction. Existing occupied slot returns its sample unchanged. |
| Sample | Current state → `result.state`: `_observe`, `pipeline/benchmark_service.py:439`; also writes operation ID, output and default UNKNOWN quality coverage. Typical results are `SUBMITTED`,`RUNNING`,`SUCCEEDED`,`FAILED`; method also accepts `PENDING_SUBMIT`,`UNKNOWN`,`CANCELLED`,`NOT_FOUND` from the operation-state enum. |
| Sample terminal handling | `_observe` clears slot for `SUCCEEDED`,`FAILED`,`CANCELLED` (`benchmark_service.py:449`); phase-completion `TERMINAL_SAMPLES` contains only `SUCCEEDED`,`FAILED` (`rendering/benchmark_experiments.py:18`). |
| Dispatch slot | Creation → empty: `prepare`, `rendering/benchmark_experiments.py:267`. |
| Dispatch slot | Coordinator absent/expired → new token plus one-hour lease: `_advance`, `pipeline/benchmark_service.py:277`; existing unexpired token returns status. |
| Dispatch slot | Matching coordinator token → token/lease cleared: `_advance` finally, `pipeline/benchmark_service.py:285`; does not clear sample. |
| Dispatch slot | Empty → sample ID: `_claim_sample`, `pipeline/benchmark_service.py:416`; matching sample ID → empty: `_observe`, `:451`. Both increment revision and share their sample-write transaction. |

Provider-operation enum states are `PENDING_SUBMIT`, `SUBMITTED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`, `UNKNOWN`, `NOT_FOUND` (`contracts/enums.py:126`). Canonical allowed transitions, enforced by `record_result`, are:

| From | Allowed next states |
|---|---|
| `PENDING_SUBMIT` | `SUBMITTED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `UNKNOWN`, `NOT_FOUND` |
| `SUBMITTED` | `RUNNING`, `SUCCEEDED`, `FAILED`, `UNKNOWN`, `CANCELLED` |
| `RUNNING` | `RUNNING`, `SUCCEEDED`, `FAILED`, `UNKNOWN`, `CANCELLED` |
| `UNKNOWN` | `NOT_FOUND`, `SUBMITTED`, `RUNNING`, `SUCCEEDED`, `FAILED` |
| `SUCCEEDED`,`FAILED`,`CANCELLED`,`NOT_FOUND` | No `record_result` exits |

Definition: `core/provider_ops.py:41`; actual state UPDATE: `record_result`, `:323`. Separately, canonical `resubmit_allowed` can reset `NOT_FOUND` → `PENDING_SUBMIT` (`:378`); the benchmark recovery methods do not call it.

Benchmark Comfy writers: creation → `PENDING_SUBMIT` via `begin` (`core/provider_ops.py:247`, caller `rendering/comfy_jobs.py:658`); → `SUBMITTED` after prompt POST (`comfy_jobs.py:686`) or UNKNOWN prompt adoption (`:1001`); `SUBMITTED` → `RUNNING` on progress (`:882`); pending/submitted/running → `UNKNOWN` (`:823`); → `SUCCEEDED` after durable output (`:952`); pending → `FAILED` on pre-dispatch refusal (`:791`); nonterminal → `FAILED` on output/execution/operator failure (`:1100`). No benchmark writer emits `CANCELLED` or `NOT_FOUND`.

Lease states: live `CLAIMED`,`ACTIVE`,`TRANSFERRING`; terminal `RELEASED`,`EXPIRED`,`ORPHANED` (`rendering/leases.py:86`).

- Creation → `CLAIMED`: `_insert_claim`, `rendering/leases.py:935`.
- Live → `ACTIVE`: `_activate`, `rendering/leases.py:1141`/`:1149`; benchmark reaches it through `ensure_pod` and shutdown adoption.
- Live → `RELEASED`: `shutdown`, `rendering/leases.py:1331`/`:1337`; podless close also writes `RELEASED`, `:1373`/`:1379`.
- `begin_shutdown` changes `pod_state` to `RELEASING`, not `lease_state` (`rendering/leases.py:1258`).
- Independent janitor: `_attach_stray` → `ACTIVE` (`rendering/janitor.py:434`/`:444`); `_clean_lease` → `ORPHANED` for heartbeat expiry/stop failure, `EXPIRED` for lease expiry, `RELEASED` for human wait (`:304`, `:344`); `_close_without_compute` → `RELEASED` (`:391`).
- Janitor late adoption preserves terminal lease state (`rendering/janitor.py:519`). Benchmark has no transfer call or writer of `TRANSFERRING`.

**3. Call graph and provider effects**

`pipeline/benchmark.py:83` constructs `BenchmarkService` with the default world factory; command dispatch is at `:186`–`:233`.

- `execute` (`benchmark.py:191`) → `BenchmarkService.execute:143` → `preflight` → `_world` → authorization/state persistence → `_advance:260` → `_advance_owned:289`.
- Normal `resume` (`benchmark.py:199`) → `resume:472` → `execute:486`; cleanup-only resume → `sweep:483`. CLI always supplies its phase default, `screen` (`benchmark.py:53`, `:204`).
- `_advance_owned` → conditional `reconcile:294` → `_acquisition:304` → `world.materialize_acquisition:318` → `LeaseService.claim_pre_reserved` → `world.acquire:325`.
- `CanonicalExperimentWorld.acquire` (`experimental_world.py:144`) → `leases.ensure_pod` → manager create/reconcile/get/verify → manager GET → Comfy endpoint binding.
- `ensure_pod` first commits create intent; first request calls `PodManager.acquire_or_reconcile`; subsequent requests only `reconcile_by_token` (`rendering/leases.py:1040`).
- Pod effects: owned-list **GET `/pods`**, detail **GET `/pods/{id}`**, create **POST `/pods`**, stop **POST `/pods/{id}/action`**, terminate **DELETE `/pods/{id}`** (`rendering/runpod_transport.py:393`, `:460`, `:477`, `:519`, `:534`). Stop/terminate include readback GETs; manager stop can escalate to terminate (`rendering/pods.py:262`).
- Sample loop → `_claim_sample` → `world.materialize_sample` → canonical job enqueue plus pre-reserved-attempt adoption (`experimental_world.py:174`).
- No sample operation ID → `world.stage_inputs` → `_SealedNativeInputs.stage:561`: schema **GET `/object_info`**, input **POST `/upload/image`**, checksum readback **GET `/view?…type=input`**. Existing upload intent takes readback-only path (`experimental_world.py:595`; `pika_transport.py:218`, `:259`).
- `world.submit` → native binding → `ComfyRenderService.submit_v2` → `_submit_bound_graph` → durable operation begin → schema **GET `/object_info`** → prompt **POST `/prompt`** → durable prompt-ID recording (`experimental_world.py:191`; `comfy_jobs.py:646`; `pika_transport.py:147`; `comfy_transport.py:248`).
- Existing operation ID → `world.poll` → Comfy `poll`: history **GET `/history/{prompt_id}`**, missing-history queue **GET `/queue`**, output **GET `/view`**, output persistence → terminal operation/settlement → `_observe` (`comfy_jobs.py:836`, `:895`, `:900`, `:1071`; `comfy_transport.py:350`). HTTP `progress_events` returns `[]` (`comfy_transport.py:340`).
- `reconcile` (`benchmark.py:208`) → `reconcile:586` → UNKNOWN acquisitions: token-list GET, durable bind/open ownership, `world.acquire`; then UNKNOWN occupied sample: `comfy.reconcile_unknown` → deterministic-client **GET `/queue`**, then **GET `/history`** if needed → prompt-ID adoption → normal poll/output GETs (`comfy_transport.py:321`, `:329`). No prompt POST in this path.
- `resolve --acquisition-id` → `resolve_create:718` → `BillingRepository.resolve_podless_create`; database/ledger effects only.
- `resolve --sample-id` → `resolve_sample:829` → cleanup-world composition → `comfy.resolve_unknown_operation` → audit event → FAILED/settlement → `_observe`; no provider call.
- `sweep` (`benchmark.py:233`) → `sweep:494` → optional local lease materialization → `world.cleanup` → `leases.shutdown` → token lookup if podless → stop/terminate/readback → finality; no create/upload/prompt submission.
- `preflight` (`benchmark.py:187`) → `preflight:62` → repository status and authorization validation; no world construction or provider effects.

**4. Transaction boundaries**

`E/A/D/S/R/L/O` below mean experiment/acquisition/dispatch-slot/sample/reservation/lease/provider-operation rows. “No explicit lock” means no `SELECT … FOR UPDATE` in that block; UPDATEs still take PostgreSQL write locks.

| Function/block | Explicit locks, writes and intervening effects |
|---|---|
| `execute`, `benchmark_service.py:165` | Read-only full-phase screening lookup; no locks/writes. |
| `execute`, `:173` | Locks E through `experiment_row(lock=True)`; inserts/replays authorization, writes running state/revision. World construction precedes this block; `_advance` follows commit. |
| `resume`, `:472` | No own transaction; status uses repository read transaction; delegates to sweep or execute. |
| `_advance`, `:262` | Locks account, categories, E, D; writes coordinator token/one-hour expiry/revision. `_advance_owned` and all its effects run after commit. |
| `_advance` finally, `:283` | No explicit SELECT lock; clears coordinator token/expiry only where token matches. |
| `_advance_owned`, `:305` | No explicit SELECT lock; writes A coordinator token/expiry. |
| `_advance_owned`, `:312` | Read-only compute-reservation lookup; no lock. Local `materialize_acquisition` follows. |
| `_advance_owned`, `:319` | No explicit SELECT lock; writes A lease link. Provider acquire follows commit. |
| `_advance_owned`, `:326` | No explicit SELECT lock; writes A ACTIVE after acquire. Sample work follows commit. |
| `_acquisition`, `:194` | Locks account/categories/E and existing nonclosed A; `reserve_linked` additionally locks D and linked Rs. Inserts A intent/quote and compute/storage reservations/links atomically. No provider call inside. |
| `_claim_sample`, `:373` | Locks account/categories/E/A/D and occupied or next PLANNED S; reserve helper also locks linked Rs. Prompt hold/link, CLAIMED/request/acquisition link and D sample assignment share transaction. |
| `world.materialize_sample`, `experimental_world.py:176` | No explicit SELECT lock in wrapper; canonical job enqueue and S job link share transaction. `adopt_reserved_attempt` runs afterward as read-only validation. |
| `_observe`, `benchmark_service.py:437` | No explicit SELECT lock; S state/operation/output/coverage and terminal D clearing share transaction. No provider call. |
| `_finish_phase`, `:459` | After sweep, locks E; writes SCREEN_REVIEW or COMPUTE_COMPLETE/outcome if outcome null. |
| Ambiguity handler, `:354` | No explicit SELECT lock; A UNKNOWN and E NEEDS_RECONCILIATION commit together; then calls sweep, including destructive cleanup. |
| General exception handler, `:364` | `repo.outcome` owns separate transaction at `benchmark_experiments.py:333`, no explicit SELECT lock; FAILED write precedes attempted sweep. |
| `reconcile`, `:618` | After acquisition/sample recovery and a separate slot read, locks E only; counts UNKNOWN acquisitions/screen PASS and may write running state. Does not lock D/S/L/O here. |
| `_reconcile_acquisition`, `:655` | Read-only L read; no lock. Token GET, `_record_pod_id`, ownership open and `world.acquire` follow outside this transaction. |
| `_reconcile_acquisition`, `:669` | No explicit SELECT lock; writes A ACTIVE after acquire. |
| `_slot_sample_unknown`, `:682` | Read-only D/S/O join; no lock; detects only O state UNKNOWN. Called before and after recovery. |
| `_reconcile_slot_sample`, `:695` | Read-only occupied S and O-by-reservation reads; no locks. Comfy reconciliation follows outside; `_observe` is a later transaction. Returns without projection unless O is UNKNOWN (`:710`). |
| `resolve_create`, `:748` | Locks E/A/L; checks A UNKNOWN and L podless, captures create-request timestamp. Early NO_CREATE_PROVEN replay returns status. |
| `resolve_create`, between blocks | If create was requested, calls billing resolution at `:779`; that commits its own resolution/zero-settlement transaction. No provider call. |
| `resolve_create`, `:786` | Locks E/A, active STORAGE Rs; writes NO_CREATE_PROVEN/window end, releases storage through canonical ledger, may write SCREEN_RUNNING. Does not reread/lock L or contradiction record here. |
| `resolve_sample`, `:846` | Read-only S and fallback O-by-reservation lookup; no lock. Then composes world and invokes operation resolution. |
| Prompt resolution, `comfy_jobs.py:1045` | No explicit SELECT lock; appends operator audit event only. UNKNOWN check was an earlier read at `:1038`. |
| Prompt failure, `comfy_jobs.py:1093` | Locks O; writes FAILED/result/event if nonterminal. Settlement follows in another transaction; benchmark `_observe` follows afterward. |
| `sweep`, `benchmark_service.py:511` | Read-only compute-link lookup if L missing; local materialization follows. |
| `sweep`, `:518` | No explicit SELECT lock; writes A lease link; `world.cleanup` follows commit. |
| `sweep`, `:533` | Read-only L pod-ID lookup after cleanup; no lock; computes `unresolved` outside finalization transaction. |
| `sweep`, `:540` | Locks account/categories/E/A; when eligible, STORAGE Rs ordered by ID. Storage release, A state and window end share transaction. |
| `sweep`, `:575` | No explicit SELECT lock; writes aggregate cleanup/billing status. No execution-state/outcome change. |

Canonical transactions reached by these paths:

- `reserve_linked(tx,…)` uses caller transaction; lock order account/categories/E/nonclosed As/D/optional S/linked Rs, then canonical reservation and linkage (`rendering/benchmark_experiments.py:125`).
- Lease materialization inserts CLAIMED/event in `leases.py:934`; create intent locks L at `:1100`; **create/list/get effects occur after commit**. POST-accept recorder locks token-matched L and binds pod plus opens storage ownership together (`:210`, `:248`).
- `_record_pod_id` locks L (`leases.py:1071`); ownership open is separate (`:477`); `_activate` locks L and writes ACTIVE/event (`:1127`), then ownership-open replay occurs separately.
- Shutdown accrues first, then locks L for release-start/pod-state (`leases.py:1241`); **stop/terminate effects follow**. Terminate timestamp locks L in `:544`; ownership close is separate at `:527`; final RELEASED/window/event transaction locks L at `:1328`.
- Comfy submit begins O at `comfy_jobs.py:657`: canonical begin uses R `FOR SHARE` and job/reservation advisory locks (`core/provider_ops.py:195`, `:215`). **Prompt POST occurs between this and result transaction `comfy_jobs.py:685`**.
- Every `record_result` locks O (`core/provider_ops.py:301`). UNKNOWN marking (`comfy_jobs.py:811`), RUNNING (`:881`), adopted SUBMITTED (`:1000`) and SUCCEEDED (`:951`) each commit independently.
- Output **GET/fetch/verify precedes** `_collect_outputs` transaction `comfy_jobs.py:1074`; that persists objects/assets, with no explicit SELECT lock in its wrapper. SUCCEEDED recording, settlement and benchmark projection are subsequent commits.
- Billing podless resolution uses `db.run_in_transaction` (`budget/billing.py:913`): advisory lock by lease, L `FOR UPDATE`, resolution/window/event and canonical zero settlement together (`:826`–`:911`).
- Final billed settlement owns `budget/billing.py:1283`: account then R `FOR UPDATE`; readiness, amount and settlement share transaction. Pending/reset retry bookkeeping has separate L-locking transactions (`rendering/finality.py:191`, `:214`).
- Canonical release locks account/categories/R and checks accrued usage, attached Runpod lease and in-flight operations (`budget/service.py:504`); it participates in caller transaction when `release_in_transaction` is used.

**5. World composition**

| Mode | Current composition and requirements |
|---|---|
| Execute/normal resume | `_world` creates `ExperimentBudgetService` from supplied authorization caps/deadline/floor, then factory (`benchmark_service.py:124`). `build_experiment_world` requires durable seal plus supplied authorization/quote; automatic reload is confined to cleanup-only (`experimental_world.py:737`). |
| `cleanup_only=True` | Missing authorization reloads latest recorded payload; missing quote reloads latest acquisition quote (`experimental_world.py:742`, `:748`). Immutable experiment/episode/plan/seal identity checks remain. Requires private PAID_BENCHMARK and cloud-resource permission; skips current-generation policy validation and the composition-level paid-request gate (`:764`–`:787`). |
| Reconcile | If UNKNOWN A or detected UNKNOWN slot operation exists, constructs `_world(...cleanup_only=False)` (`benchmark_service.py:611`). Therefore supplied authorization/quote and current policy are required on this default path. With neither UNKNOWN condition, no world is constructed. |

- Normal policy validates authorization expiry against `min(authorization.hard_stop_utc, seal.eligible_until)`, authorization deadline ≤ seal deadline, current quote capture/expiry, hardware/rate/storage limits, matching rights hash and LIVE_PROVIDER schema (`benchmark_authorization.py:366`).
- It also validates exact current disabled/unmeasured preset, workflow/config/grid/schema pins, model rights and exact accepted/locked reference assets/current grants (`experimental_world.py:232`, `:280`, `:360`).
- Shared composition is `RunpodRestProvider` → `PodManager` → `LeaseService` with `RunpodInvoiceFinality`; real `PikaHttpClient` → `ComfyRenderService(lease_covered=True)`; `JobService`; native request/binding/staging helpers (`experimental_world.py:872`–`:979`). Construction performs no HTTP or credential resolution.
- Cleanup attestation sets `activation_enabled=False`; create guard refuses cleanup-only; native `current()` refuses new work; request guard refuses input staging and `/prompt` in cleanup-only (`experimental_world.py:815`, `:845`, `:443`, `:922`, `:937`).
- Comfy guard requires exact sample/job/reservation/acquisition pod, namespace/account and the client’s bound pod ID; canonical guard requires ACTIVE prompt reservation and matching nonterminal operation for noncatalog reads (`experimental_world.py:900`; `pipeline/live_world.py:334`).
- Fresh client begins with `_endpoint=None`, `_bound_pod_id=None` (`comfy_transport.py:113`). Binding occurs only in `world.acquire`: ensure lease/pod, manager GET, then `bind_pod_endpoint(pod_id, endpoint_url)` (`experimental_world.py:145`–`:155`). Accepted URL is exactly `https://<pod_id>-8188.proxy.runpod.net`; rebinding to another pod is refused (`comfy_transport.py:124`).
- Fresh CLI has settings, durable DB records and newly constructed services. It has no previous client binding or in-memory adapter. Default reconcile directly calls Comfy recovery without `world.acquire` for its sample (`benchmark_service.py:713`).
- CLI constructs filesystem store only for `execute`,`resume`,`sweep` (`benchmark.py:159`); default `reconcile` and `resolve` receive `store=None`. Factory passes that value to Comfy and native helpers without a construction-time non-null check (`experimental_world.py:956`, `:966`). Staging reads source bytes; output collection persists through the store.

**6. Existing canonical recovery primitives**

Each line gives signature, preconditions, locking and effects. Janitor adoption is in `rendering/janitor.py`; podless resolution is in `budget/billing.py`, rather than `leases.py`.

- `LeaseService.claim_pre_reserved(request, reservation_id) -> LeaseHandle` (`rendering/leases.py:786`): validates exact hold identity/size/ownership; existing bound lease replays, otherwise requires ACTIVE/unexpired hold; read-only checks then claim insertion transaction; no reserve/create.
- `durable_created_pod_recorder(db, now) -> Callable[[str,str],None]` (`rendering/leases.py:195`): token must identify lease; locks matching L; refuses conflicting pod, binds ID/create timestamps and opens ownership atomically; unknown token is no-op.
- `open_storage_ownership(db, lease_id, pod_id)` / `open_storage_ownership_in_tx(tx,…)` (`rendering/leases.py:470`, `:481`): existing lease; no explicit SELECT row locks in helper; idempotently inserts root-episode interval from create time; wrapper owns transaction.
- `close_storage_ownership(db, provider, pod_id, instant)` (`rendering/leases.py:520`): updates open intervals only; no explicit SELECT lock; set-once end is `max(instant, valid_from+1µs)`.
- Ownership healing: `ensure_pod` and `shutdown` call open before verification/cleanup (`rendering/leases.py:1028`, `:1298`); janitor bound-pod cleanup does likewise (`rendering/janitor.py:324`); `_sweep_open_ownership(now,report)` closes surviving open rows using persisted terminate time (`:195`).
- `Janitor._attach_stray(lease_id,pod,now)` (`rendering/janitor.py:429`): pod found for live podless lease; locks L; writes pod/ACTIVE/event, then separately opens ownership; cleanup continues.
- `Janitor._adopt_late_pod(pod,lease_id,now,report)` (`rendering/janitor.py:506`): terminal podless lease matched by token/namespaced name (`:484`); locks L, rechecks podless, binds pod and marks resolution contradicted atomically; preserves terminal state; then opens ownership and stops/terminates/verifies.
- `BillingRepository.resolve_podless_create(lease_id,*,actor_ref,reason,evidence_sha256,now=None)` (`budget/billing.py:786`): nonempty actor/reason, lowercase SHA256, budget service, sent create and no attached pod; advisory+L lock; replay-stable audit/window/zero BILLED settlement atomically; no provider effect.
- `PodManager.reconcile_by_token(client_token) -> PodInfo|None` (`rendering/pods.py:149`): owned-tag filtered listing; no DB locking; zero returns None, one returns pod, multiple raises Conflict; GET only, no bind/create.
- `ComfyRenderService.reconcile_unknown(operation_id) -> ComfyAttemptStatus` (`rendering/comfy_jobs.py:966`): durable operation/job/request; needs endpoint-bound client, credential/request scope and output store for successful output recovery; finder GETs adopt missing prompt ID under O lock, then poll; never POSTs; missing match raises NeedsReconciliation.
- Canary operator evidence path: `run_invoice(*,settings,db,provider_account_ref,pod_id,period_start,period_end,amount_micro_usd,evidence_path,source,…actor_ref,reason)` (`pipeline/canary.py:1291`): hashes local evidence, delegates to `verify_invoice_period` with canonical budget service; no provider call; billing helper owns transactions. CLI commands are only `preflight`,`execute`,`sweep`,`invoice` (`:1500`); there is no podless-create resolve command in this file.
- `run_sweep(authorization_path,*,expected_sha256,settings,db,store,…)` (`pipeline/canary.py:1349`): verifies authorization bytes, mode/flags, loopback/pinned episode; builds independently callable janitor without live eligibility revalidation; performs owned-resource cleanup, billing ingestion/finality; no Comfy calls.

**7. Holds and money**

| Hold | Placement, retention and closure |
|---|---|
| Acquisition COMPUTE | `world.acquisition_requests` builds GPU_GENERATION `pod.lease` hold for quote runtime plus 60-second shutdown margin; amount = rounded-up seconds × quote-derived integer GPU-second price (`experimental_world.py:90`, `:827`). `_acquisition` places and links it atomically with A at `benchmark_service.py:242`; lease materialization adopts it. |
| Acquisition STORAGE | CPU_STORAGE_TRANSFER `benchmark.storage_exposure`, one REQUEST at quote’s full storage-exposure ceiling; expires experiment hard stop +72h (`experimental_world.py:109`–`:133`); placed alongside compute at `benchmark_service.py:248`. It is a protective hold, separate from actual disk allocations. |
| Sample PROMPT | GPU_GENERATION `comfy.queue_prompt`, fixed sample `:a1` key; default 600,000ms exposure, expiry now+timeout (`experimental_world.py:158`; `comfy_jobs.py:346`). `_claim_sample` places/links it before CLAIMED/slot assignment (`benchmark_service.py:397`). Materialization adopts it without reserving again. |
| Cleanup grant | Best-effort GPU_GENERATION `pod.stop`, deterministic lease key, shutdown-margin exposure/expiry, `is_shutdown_or_cleanup=True` (`leases.py:1405`–`:1435`). `ExperimentBudgetService.reserve_linked` labels it CLEANUP and infers current nonclosed acquisition; no sample link is supplied (`benchmark_experiments.py:168`). Refusal records event and does not prevent cleanup. |
| Cleanup floor | Admission adds `max(account.shutdown_reserve, authorization.shutdown_reserve_micro_usd)` once; this floor is not a separate reservation (`benchmark_experiments.py:192`). No parent experiment-cap hold is created. |

- Compute is accrued through lease accounting; Runpod finality retains it until BILLED, schedules pending retry, then settles canonical billed usage (`leases.py:1221`, `:1353`; `finality.py:176`; `budget/billing.py:1269`). Shutdown on RELEASED returns recorded state without rerunning finality (`leases.py:1272`).
- Positively unused compute with neither create request nor pod releases through `RunpodInvoiceFinality.settle_lease` (`finality.py:150`). Sent-but-podless ambiguity retains exposure pending resolution.
- `resolve_create` calls zero BILLED compute settlement only when `create_requested_at` is non-null (`benchmark_service.py:773`); billing resolution settles at `budget/billing.py:911`. The no-create-request branch does not directly release compute.
- STORAGE remains during unresolved podless ambiguity. Sweep releases ACTIVE STORAGE only when cleanup verified, storage final and `unresolved=False`, in the same A-finalization transaction (`benchmark_service.py:549`–`:562`).
- `resolve_create` separately releases ACTIVE STORAGE in its final transaction (`benchmark_service.py:800`–`:815`), after billing resolution; that final transaction does not recheck lease binding/contradiction.
- UNKNOWN prompt retains its hold; `_mark_unknown` does not release (`comfy_jobs.py:810`). Terminal lease-covered attempts settle at zero when `submitted_at` exists (`:1145`, `:1166`); compute charges remain on lease.
- Pre-dispatch refusal releases its unused prompt hold (`comfy_jobs.py:723`, `:803`). Any terminal operation with null `submitted_at` also takes release path (`:1135`), including operator-resolved UNKNOWN with no adopted prompt ID.
- Prompt operator resolution commits audit → FAILED → settlement/release → benchmark sample/slot projection separately (`comfy_jobs.py:1045`, `:1093`, `:1112`; `benchmark_service.py:868`).
- Cleanup grant releases after successful finality call (`leases.py:1356`, `:1451`); failures can leave it for expiry/janitor stale-hold release (`rendering/janitor.py:859`).
- Canonical expiry retains exposure as spent until settlement (`budget/service.py:553`). Experiment exposure sums canonical accrued+settled+ACTIVE remainder plus distinct unreserved noncredit allocations; credits do not replenish this projection (`benchmark_experiments.py:51`).

**8. Tests**

Inspection only. `A` means calls benchmark `_advance` directly; `F` means the composed benchmark uses a separate fake Comfy server retained across pod cleanup. Canonical service tests below do not call benchmark `_advance`; their Comfy fakes are independent of pod lifecycle unless otherwise stated.

Benchmark tests under `microdrama/tests/unit/`:

- `rendering/test_benchmark_experiments.py::test_composed_24_samples_use_actual_jobs_holds_leases_and_comfy_recovery` (`:272`): three-screen/24-total submissions, durable jobs/holds, all samples succeeded, UNKNOWN quality; new service objects reuse adapter; **A,F**.
- `rendering/test_benchmark_experiments.py::test_unknown_create_with_late_pod_is_found_and_the_experiment_resumes` (`:535`): cleanup finds/binds/terminates pod, reconcile returns SCREEN_RUNNING, screen finishes, ownership closes; **A,F**; listing fixture creates pod inside `find_pods` (`:452`).
- `rendering/test_benchmark_experiments.py::test_unknown_create_without_pod_is_operator_resolved_and_resumes` (`:582`): absence retains UNKNOWN; audited resolution records one row/NO_CREATE_PROVEN; later acquisition finishes screen; **A,F**.
- `rendering/test_benchmark_experiments.py::test_prompt_submit_timeout_is_reconciled_by_client_id_without_resubmit` (`:637`): UNKNOWN occupies slot; client-ID recovery yields SUCCEEDED; screen totals three submissions; **A,F**.
- `rendering/test_benchmark_experiments.py::test_operator_resolves_an_unfindable_prompt_and_frees_the_slot` (`:696`): absent prompt remains ambiguous; operator resolution yields FAILED, clears slot; reconcile returns SCREEN_RUNNING; **A,F**.
- `rendering/test_benchmark_experiments.py::test_pre_reserved_lease_adoption_never_takes_second_hold` (`:172`): lease adoption reuses reservation; no second hold; neither A nor Comfy cleanup.
- `rendering/test_benchmark_experiments.py::test_failed_outcome_survives_later_cleanup_and_closure` (`:234`): FAILED remains after manually updated cleanup/billing closure; neither A nor provider recovery.
- `pipeline/test_benchmark_authorization.py::test_cli_resolve_requires_an_audited_attestation_and_one_target` (`:231`): missing attestation/zero or two targets refuse before service construction; no provider/fake cleanup.
- `pipeline/test_benchmark_world_composition.py::test_default_factory_acquire_binds_the_pika_client_with_the_real_signature` (`:216`): real Pika client binds exact pod URL through scripted Runpod transport; policy validation monkeypatched; no A or recovery-after-cleanup.
- `pipeline/test_benchmark_world_composition.py::test_acquire_fails_loudly_when_the_client_cannot_bind` (`:252`): missing binding method raises; small stand-ins, no A.

Comfy recovery tests, `microdrama/tests/unit/rendering/`:

- `test_comfy_recover.py::test_reconnect_does_not_rerender_an_existing_completed_job` (`:130`): fresh connection reuses server memory, one prompt/asset/settlement; no pod cleanup.
- `test_comfy_recover.py::test_crash_between_queue_and_persist_is_never_blindly_resubmitted` (`:149`): manually begun/lost-ID operation becomes UNKNOWN; submit replay refuses; no extra prompt.
- `test_comfy_recover.py::test_deadline_while_running_needs_reconciliation_and_holds_exposure` (`:194`): deadline yields UNKNOWN with ACTIVE hold.
- `test_comfy_recover.py::test_settlement_replays_after_a_crash_between_success_and_settle` (`:216`): injected settlement crash leaves SUCCEEDED/ACTIVE hold; later poll posts exactly one settlement.
- `test_comfy_recover.py::test_asset_save_boundary_recovery_registers_exactly_one_asset` (`:261`): replay returns identical asset and one charge; re-polls already completed operation.
- `test_comfy_recover.py::test_terminal_status_replay_does_not_touch_the_server` (`:276`): terminal replay adds zero client calls.
- `test_comfy_recover.py::test_reconcile_unknown_adopts_the_prompt_by_deterministic_client_id` (`:376`): manually seeded UNKNOWN/lost-ID submit becomes SUCCEEDED, one submission.
- `test_comfy_recover.py::test_reconcile_unknown_stays_ambiguous_when_nothing_is_visible` (`:398`): evicted fake prompt leaves UNKNOWN and raises NeedsReconciliation.
- `test_comfy_recover.py::test_poll_unknown_with_durable_prompt_id_recovers_from_history` (`:416`): deadline UNKNOWN later completes from same prompt ID, one submission.
- `test_comfy_recover.py::test_operator_resolution_records_terminal_failure_and_settles` (`:442`): FAILED plus one actor audit event; repeat resolution Conflict; malformed actor SchemaInvalid.

Canonical pod/lease tests, same test directory:

- `test_pods_filters.py::test_reconcile_by_token_only_sees_owned_pods` (`:147`): owned match returned; foreign/absent tokens return None; fake provider, no A.
- `test_pods_filters.py::test_reconcile_by_token_refuses_ambiguous_duplicates` (`:158`): duplicate token matches raise Conflict; fake provider.
- `test_pods_filters.py::test_ambiguous_create_that_created_adopts_without_second_create` (`:172`): one create/owned pod; fake provider.
- `test_pods_filters.py::test_ambiguous_create_without_visible_pod_stays_unknown_without_retry` (`:182`): one create, no visible owned pod; fake provider.
- `test_lease_lifecycle.py::test_ambiguous_create_timeout_that_created_is_adopted` (`:80`): ACTIVE lease bound to sole token-matched pod; fake provider.
- `test_lease_lifecycle.py::test_ambiguous_create_timeout_that_did_not_create_stays_unknown` (`:92`): one create, CLAIMED/REQUESTED podless lease; fake provider.
- `test_lease_lifecycle.py::test_create_then_verify_502_then_list_miss_makes_exactly_one_pod` (`:108`): durable ID survives verification failure; retry uses same pod; cleanup stops it; fake provider.
- `test_lease_lifecycle.py::test_recorded_create_request_makes_retries_reconciliation_only` (`:139`): repeated ensure/list absence never causes second create; fake provider.
- `test_lease_lifecycle.py::test_crash_after_create_is_recovered_from_durable_state` (`:162`): out-of-band created pod adopted once; cold-start/running accrual retained; fake provider.

Billing/storage tests under `microdrama/tests/unit/`; none call benchmark `_advance` or recover Comfy output after cleanup:

- `budget/test_t045_finality.py::test_finality_survives_a_restart_readback` (`:616`): reopened DB reports BILLED and one settlement; durable billing fixture.
- `budget/test_t045_finality.py::test_podless_create_resolution_bills_zero_and_releases` (`:652`): pending → BILLED zero, hold SETTLED, one resolution/settlement; seeded lease.
- `budget/test_t045_finality.py::test_podless_resolution_is_refused_once_a_pod_is_attached` (`:680`): refusal leaves no resolution; seeded lease.
- `budget/test_t045_finality.py::test_podless_resolution_requires_actor_and_reason` (`:698`): empty actor/reason refused; seeded lease.
- `budget/test_t045_finality.py::test_replaying_a_podless_resolution_is_a_noop` (`:715`): one resolution/settlement after replay; seeded lease.
- `budget/test_t045_finality.py::test_a_budgetless_repository_refuses_a_podless_resolution_without_writing_it` (`:768`): no window-end/resolution/settlement writes.
- `rendering/test_t045_storage_ownership.py::test_a_crash_before_the_ownership_write_is_healed_by_a_re_ensure` (`:118`): missing interval healed once for correct owner; fake provider.
- `rendering/test_t045_storage_ownership.py::test_a_crash_after_the_terminate_write_is_closed_by_the_janitor_at_the_persisted_instant` (`:149`): ownership closes at stored terminate timestamp; Runpod fixture.
- `rendering/test_t045_storage_ownership.py::test_worker_death_right_after_post_accept_keeps_storage_attributed` (`:174`): binding already owns storage; janitor terminates/closes same interval; Runpod fixture.
- `rendering/test_t045_storage_ownership.py::test_janitor_bound_pod_cleanup_heals_a_missing_ownership_row` (`:228`): cleanup inserts correct interval and closes at verified termination; Runpod fixture.
- `rendering/test_t045_billing_ingestion.py::test_a_late_pod_after_a_podless_resolution_is_adopted_terminated_and_billed` (`:840`): late bind/DELETE, 400,000 adjustment and 500,000 total after invoice; scripted transport.
- `rendering/test_t045_billing_ingestion.py::test_a_contradicted_resolution_no_longer_reads_billed_zero` (`:902`): contradiction names pod; reopened readiness reports actual 400,000 billed; scripted transport.
- `rendering/test_t045_billing_ingestion.py::test_a_second_sweep_after_the_late_pod_adoption_adds_nothing` (`:957`): second sweep preserves table counts; scripted transport.
- `rendering/test_t045_billing_ingestion.py::test_a_failed_terminate_is_retried_to_verified_closed_and_billed` (`:992`): first failure retains ownership/deferred ingestion; retry closes/bills; subsequent sweep idempotent; scripted transport.
- `rendering/test_t045_billing_ingestion.py::test_an_ambiguous_terminate_completes_by_absence_never_a_second_delete` (`:1106`): one DELETE, later absence verifies termination, ownership closes and billing settles; scripted transport.

The benchmark composed cleanup fixture accepts `stop_verified_at OR terminate_verified_at` and synthesizes BILLED/storage-final from that (`test_benchmark_experiments.py:255`–`:268`); production adapter requires `terminate_verified_at` and canonical billing readiness (`experimental_world.py:207`). No benchmark test found calls `BenchmarkService.resume()` or exercises successful CLI `resume`/`reconcile`; the resume-labelled scenarios above call `_advance` directly.

