# T031 implementation contract — native Codex

This addendum resolves the Stage9 implementation decisions in the integration
spec. Internal API/data names below are normative. No paid authorization is issued.

## A. Canonical reservation extension and sub-limit

Extract `BudgetService.reserve_in_transaction(tx: Tx, request:
BudgetReservationRequest) -> Reservation` from the existing complete reserve body.
`reserve(request)` remains its transaction-owning wrapper. Preserve every existing
queue, price, shutdown, recovery-exposure, account/category, replay, expiry and
spill guard. Do not duplicate a reduced implementation in the benchmark module.

Use `ExperimentBudgetService(BudgetService)` as the budget instance injected into
the existing lease/render composition. Its `reserve` opens one transaction, locks
account then categories (existing category order), experiment, acquisition slot,
dispatch slot, sample, then reservation rows ordered by UUID. It invokes canonical
`reserve_in_transaction`, inserts unique reservation linkage, then checks the
post-insertion exposure projection (candidate included exactly once) and commits
together. A refusal rolls back both reservation and linkage.
Outside ordinary jobs still take the canonical account lock and enforce the same
$10 account cap. `prepare` never creates a new account or replenishes one.

For each unique linked canonical reservation, exposure is exactly
`r.accrued + r.settled + r.open_remaining`; `open_remaining` is the existing
`ReservationRow` rule: ACTIVE => max(original_reserved - accrued,0), otherwise0.
Never sum historical ACCRUAL receipts with a final SETTLEMENT: settlement replaces
accrual in the canonical counters. Canonical CREDIT records do not reduce those
counters. Add linked unreserved settled usage exactly once, excluding CREDIT, by
its canonical charge/allocation identity. Do not maintain independently mutable
money counters in experiment/sample records.

Examples in micro-USD:

- Reserve1000 => exposure1000. Accrue300 => remaining700 + accrued300 =1000.
- Settle at400 => remaining0 + accrued0 + settled400 =400; unused600 becomes
  available, but an actual credit100 remains separately reported and restores0.
- Later positive adjustment50 => settled450; replay of its receipt adds0.
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
The finite storage tail is not a provider-enforced hard spend guarantee.

## B. Additive persistence, no mutable JSON authority

Migration `0026_t031_benchmark_experiments.sql` (recheck slot before writing):

- `benchmark_experiments`: experiment_id UUID PK; episode_id/account_id FKs;
  plan_sha256 and plan JSONB immutable; UNIQUE(episode_id,plan_sha256);
  sealed_sha256 nullable; execution_state TEXT; execution_outcome nullable TEXT;
  cleanup_state TEXT; billing_state TEXT; cap_micro_usd BIGINT <=10000000;
  gpu_limit_ms BIGINT>0; absolute hard_stop TIMESTAMPTZ nullable until seal;
  revision INTEGER>=0; created_at/updated_at TIMESTAMPTZ.
- `benchmark_samples`: experiment_id FK + sample_id TEXT composite PK; shot_id,
  repeat INTEGER1..3, seed BIGINT; immutable input JSONB/hash; state TEXT;
  job_id FK nullable; operation_id FK nullable; reservation_id FK nullable;
  acquisition_id UUID nullable; output JSONB and coverage JSONB nullable;
  UNIQUE(experiment_id,shot_id,repeat). Sample attempt is fixed1; the existing
  render contract's per-shot maximum3 is unchanged.
- `benchmark_seals`: experiment_id PK/FK; sealed manifest JSONB and SHA256;
  created_at; append-only trigger. Same seal hash replays, different hash conflicts.
- `benchmark_authorizations`: experiment_id FK + authorization_sha256 composite
  PK; canonical payload JSONB; authorized_at; append-only. No private key or
  cryptographic-signature claim: explicit operator file/hash convention only.
- `benchmark_acquisitions`: acquisition_id UUID PK; experiment_id FK; generation
  INTEGER; immutable quote JSONB/hash; intent/job/lease UUID links; state TEXT;
  create_intent_at, compute_window_start/end TIMESTAMPTZ; coordinator token UUID,
  coordinator lease_until TIMESTAMPTZ; UNIQUE(experiment_id,generation).
  Partial UNIQUE(experiment_id) WHERE state NOT IN ('CLOSED','NO_CREATE_PROVEN').
  UNKNOWN create keeps this slot occupied. Storage pending keeps it occupied.
- `benchmark_dispatch_slots`: experiment_id PK/FK; sample_id nullable; coordinator
  token/lease_until; revision. One active sample per experiment, even with funds
  for more. Lock this row before selecting a pending sample.
- `benchmark_reservation_links`: reservation_id PK/FK; experiment_id FK;
  acquisition_id FK nullable; sample_id nullable; purpose CHECK
  ('COMPUTE','PROMPT','STORAGE','CLEANUP'). Immutable ownership.
- `benchmark_uploads`: acquisition_id FK + asset_sha256 + media_kind + role +
  subject_id composite PK; destination_slot TEXT; upload_key; locator JSONB;
  state CHECK('INTENT','UNKNOWN','VERIFIED'); verified_readback_sha256 nullable;
  immutable source hash and destination identity. Only VERIFIED is bindable.
- `benchmark_screenings`: experiment_id FK + decision_sha256 composite PK;
  decision JSONB; sealed_sha256; actor_ref; observed_at; append-only. Decision
  binds all three output hashes, coverage/rubric and PASS/FAIL, never an ApprovalEvent.

Use existing immutable/append-only trigger helpers, hash/check constraints and
FKs. Keep execution outcome separate from closure: a FAILED experiment may later
have cleanup VERIFIED and billing BILLED; it never becomes a successful run.
Expose overall completed-with-failure honestly. JSONB stores immutable input and
receipts, not a competing mutable state machine. Canonical jobs/leases remain
source of effect truth; linkage rows only coordinate them.

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

## D. Experimental profile and native audio integration

Add `ReferenceRole.VOICE` keyed by speaker subject, **one anchor per speaker**.
No arbitrary list-position voice meaning or multiple distinct anchors per speaker
in this version. Contract guardian proposal: additive role, backwards-readable V2
payloads, contract package2.16.0, generated schemas/examples and compatibility
checks; no new RenderRequest field. Primary integrator owns generation and the
independent codebase reviewer must accept this proposal before schema mutation.
Existing required identity/outfit/location roles remain mandatory.

Create an explicit ordered module-local `PikaPortMap` inside the sealed manifest:
(role,subject_id,asset_uuid/version/hash,media_kind,destination_slot). Images map
to `ref_images.ref_image_N`, VOICE to `ref_audios.ref_audio_N`; order is explicit
and hashed, never inferred from sorted UUIDs. Reject duplicate destinations,
non-contiguous ordinals, over-limit inputs and unsupported endpoint-frame roles.

Register allowlisted template `pika-h3-flex-ref2va-benchmark-v1`, family
`pika_h3_flex_ref2va`, in PRESET_TEMPLATES. Keep its PresetRecord disabled,
measured=None, supports_thai_dialogue=None. No fake benchmark measurements.
Add `ExperimentalPresetPolicy` module-local object validated against the sealed
authorization and current disabled registry version. Refactor world assembly into
shared guarded primitives: old build_live_benchmark_world retains its existing
production eligibility validation; new `build_experiment_world` uses the narrow
experimental policy and exactly the same budget/provider/job/lease/cleanup
services. Never add a generic `skip_validation` boolean.

Dispatch `bind_v2_workflow` and `verify_bound_v2_workflow` by family BEFORE legacy
sampler/LoadImage assumptions. Old families execute old code unchanged. New
Pika builder/verifier receives the explicit port map, pinned runtime graph config,
PromptManifest and VERIFIED upload receipts, recomputes the graph and compares
all receipts/hash/inputs. Extend WorkflowTemplate with optional
configuration_sha256; include it in template/semantic hashing only when present,
so all existing V1/V2 hashes stay byte-identical. New family hash pins graph
config, model files, audio/video decode topology, native audio and port map.
`submit_v2` continues existing job/reservation/operation/recovery logic and calls
the dispatched verifier; no parallel prompt submission engine.

Add `ComfyHttpClient.raw_object_info()` via existing guarded GET, leaving current
object_info() output unchanged. Normalize/hash only mapped classes' complete
required/optional input definitions, dynamic-input definitions, output types and
ordering, output_is_list, enum options and numeric/string constraints. Exclude
UI display labels/descriptions and unrelated node classes. Use sorted JSON with
finite numeric values deterministically encoded; runtime schema hashes are
separate from strict money-contract JSON hashing. Compare actual schema before
uploads/prompt. Changed mapped schema fails closed; fixture hashes are labelled
OFFLINE_FIXTURE_ONLY and cannot seal an executable LIVE schema attestation.

Uploads use `upload_input(bytes, media_kind, expected_sha256, upload_key)` under
the same scoped reservation/operation request guard. Only image PNG and WAV audio
are supported initially; reject other MIME/types before network. Build bounded
multipart bytes rather than passing them to the JSON `_request` serializer.
Deterministic key: experiment/acquisition/asset-hash + safe suffix. Remote locator
is acquisition/pod scoped and never a local host path. Read back via guarded
`/view` with type=input and checksum the exact uploaded bytes before VERIFIED.
On upload timeout mark UNKNOWN; reconcile by deterministic locator/readback.
Identical verified bytes can be adopted; absent/unverifiable readback blocks
submission and permits cleanup, not a prompt retry with missing inputs.
The new request_guard explicitly admits these upload/readback routes only when
linked to this acquisition's active reservation/job and allowed key. No caller
may upload arbitrary files or use an unscoped client. New pod => new upload rows.

Pika output keeps VAEDecodeAudio + VAEDecode => CreateVideo => SaveVideo. Required
output includes one playable video stream and native nonempty stereo32kHz audio;
unknown/silent/wrong audio coverage never yields quality PASS. Actual schema and
stream shape are checked; no TTS substitution. Exact portrait bucket is resolved
from pinned source; if CPU import/schema check cannot verify it, mark runtime
readiness blocked while preserving passing graph fixtures as offline evidence.

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
