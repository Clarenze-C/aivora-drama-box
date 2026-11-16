# T031 Pika H3 Flex offline integration and durable benchmark design

Version 0.2 — 6 November 2026 — **DESIGN REVIEWED; NATIVE CODEX BUILD IN PROGRESS**.
Scope authorized by the operator: steps 1–3 (canary-night review, real-model
image/binding, shared-budget 24-sample runner with recovery). Paid inference,
RunPod resources, public registry pushes, production migrations and publishing
remain outside this authorization. The operator explicitly overrode ai-route/GLM routing on 6 November: use native
Codex for Goldfish, implementation and independent review. Fresh reviewers get no
conversation history; the author does not review its own implementation.

## 1. Problem and outcome

The existing canary exercised real provider lifecycle with fake sampler nodes.
Its runner accepts at most three submit attempts globally and cannot run the
24-sample quality matrix. The existing `PresetBenchmarkTool.run` is deliberately
offline-only, uses fake provenance, and must stay that way. Neither path may be
relabelled as real H3 qualification.

Add an explicitly separate paid-benchmark composition for the operator-selected
**Pika H3 Flex Ref2VA six-step workflow with native audio**. It must reuse the
canonical budget/job/provider/lease/billing services, accept the existing eight
shots × three repeats, preserve evidence and spend across restarts, and remain
disabled until a separately signed executable authorization exists. Software
acceptance demonstrates offline correctness only; A40 generation/Thai quality
requires the later paid screen.

### Feature summary and user experience

An operator can prepare a frozen configuration, inspect a no-effect preflight,
and later execute three screening samples under a single experiment envelope.
The process shuts down the GPU before waiting for screening review. A continuation
must bind that same experiment and its verified results; it cannot replenish funds
or reset sample identities. Normal runtime season/final-episode gates are unchanged.

## 2. Current facts and dependencies

- Application base: `0851374`; contracts 2.15.0; migrations through 0025.
- [Canary-night review](T031-canary-night-review.md): R1 billing-atom conservation
  and R2 diagnostic redaction require fixes. Focused existing suite: 150 passed;
  the new counterexamples are not covered by those existing tests.
- [Benchmark packet](T031-benchmark-packet.md): one Ref2VA 480p configuration,
  three screening samples included in 24, proposed $8 new exposure / four GPU
  hours; the envelope is unsigned and may not fit remaining account allowance.
- Exact model/workflow source revisions and published file hashes:
  [source-pins.json](t031-benchmark/source-pins.json). The five selected Comfy
  components total 42,030,014,463 bytes. No weights have been downloaded.
- Host disk check on 6 November: approximately **34 GB available**, less than the
  42 GB model files alone. No weights/caches may be downloaded here until required
  peak disk headroom is available. Do not clear other workstreams' files to make
  room. A no-weights runtime image is the intended local build artifact.
- No CUDA GPU on this host; CPU import/schema/graph checks cannot prove A40 fit.
- The user selected H3 Flex with built-in speech. External TTS, lip-sync add-ons,
  Wan substitution and hosted Pika services are not part of this implementation.

## 3. Scope, ownership and compatibility

Three sequential implementation slices, one build at a time:

1. R1/R2 regression tests and narrow transport fixes. Re-review the fixed findings.
2. Real-model image recipe, immutable component manifest, native-audio binder and
   upload/schema verification. No preset enabled for production.
3. Experiment schema/repository, shared admission, CLI and composed recovery tests.

Use an isolated branch/worktree from the frozen base; preserve the current dirty
documentation and untracked canary receipts. No commits/pushes from this session
without separate authorization. Record the base commit and an immutable content snapshot manifest for every
reviewed modified/new implementation file, including untracked files. Snapshot
entries contain relative path, byte length and SHA-256; archive those exact bytes
under `.scratch/keep/t031-native-review/`. A changed file invalidates its review. Existing template/preset identity hashes, canary
authorization semantics, offline benchmark provenance and approved task state
must remain backward compatible.

The primary Codex agent is the integration owner: it alone coordinates contracts,
migration order, budget integration and dependency locks. A different native
Codex reviewer supplies contract-guardian review before any public canonical
payload change: document fields, compatibility, schema version and generated
examples, then obtain that review before implementation. Internal module models
and additive persistence do not create a new external human approval. These roles
implement SPEC §4 and task_breakdown §2; do not silently extend public models.
Prefer module-local experiment inputs where no canonical payload change is needed.
Migration 0026 is the next available slot **at this inspected base**; recheck before
writing it. Never edit an applied migration or run it on the live canary database.

The selected approach shares existing lifecycle services but adds a separate
experiment coordinator. Extending the canary with a generic policy switch could
reuse more runner code, but would widen a reviewed three-attempt contract and
make restart identity/budget ownership depend on mode. A separate coordinator
keeps that compatibility boundary and explicit experiment state, at the cost of
a small orchestration layer; extract common lifecycle helpers rather than copy
provider effects. §9 records excluded alternatives and residual risks.

A software admission ceiling does not guarantee externally billed maximum cost.
A provider outage can extend storage beyond its funded 72-hour tail. Before paid
execution, establish a provider-enforced resource/account bound or separately
record the residual exposure, explicit operator acceptance and named recovery
owner. No such acceptance is inferred here; finite reserves and a janitor alone
cannot certify a hard provider spending limit.

## Detailed Implementation Plan

The normative [implementation contract](T031-integration-contract.md) fixes the
remaining schema, API, accounting, authorization, upload and transition decisions.
Where the earlier descriptive detail below is less specific, that contract governs.
It includes the additive VOICE role proposal for independent contract review;
there is no unresolved choice delegated to the builder about multi-audio mapping.


## 4. Real-model runtime and graph binding

### 4.1 Image and model manifest

Create `microdrama/deployment/pika-h3-flex/`, separate from `canary-image/`.
Build a real ComfyUI runtime from revision
`63e5bf594339f676b4b15e072529873e3448409e` and a digest-pinned CUDA/PyTorch base:
`pytorch/pytorch:2.9.1-cuda12.8-cudnn9-runtime@sha256:7b324d212a4450795b49edba9949b7cdc72429148a64e974334bfe5774d51385`
(public tag metadata verified 6 November; amd64). Resolve a transitive dependency
lock against this base before building;
upstream unbounded `torch` and other requirements are not an acceptable lock.
Do not reuse Comfy v0.3.77 or copy its fake-loader patches/stub nodes.

The image contains code and a weight manifest, not the 42 GB weights or secrets.
Model provisioning is a distinct, explicit command, disabled during normal startup
and preflight. Downloads use immutable revisions, write temporary files, verify
size/SHA before atomic promotion, and reuse only verified complete files. Refuse
if remaining free space cannot cover temporary + final bytes and configured
headroom. Do not auto-fetch alternate checkpoints, optional prompt enhancement,
tokenizers or dependencies from mutable branches. Inventory every additional
runtime file needed by loaders; add provenance/checksums before claiming offline
provisioning is complete. A failed verification never becomes a loader input.

Pin the five files under `Comfy-Org/MiniMax-H3` revision
`54472221d27c695fca9621b0c3ed52f06c4af707`. The repack adapter is the file the
official graph names; it is not byte-identical to Pika's original BF16 export.
Native NVFP4 hardware is not assumed required: the official repack card says the
encoder can be used without Blackwell, but A40 kernel/offload behavior still needs
measurement. No A100/H100 or automatic fallback hardware.

The local no-weights check must report what was tested: dependency/import health,
real H3 node registration and request schema without fake samplers. If the real
runtime cannot expose schema on a driverless CPU host, record that blocker and
use a separately labelled schema-fixture test; do not patch in fabricated live
schema or claim runtime image readiness. CPU import limitations are not grounds
to downgrade to the old stub image.

### 4.2 Fixed API graph

Derive an explicit allowlisted API-format graph from the byte-preserved official
Ref2VA UI graph; do not implement a generic arbitrary-UI-graph executor. Remove
UI-only primitives/notes by resolving their values into typed API inputs.

The graph must include the real loader → Pika LoRA → BasicGuider → custom sampler
path, `MiniMaxH3ReferenceToVideo`, video/audio VAE decoding, and **both** decoded
streams wired into `CreateVideo` → `SaveVideo`. Use `lcm`, LoRA strength 1.0 and
sigmas `1,0.972973,0.923077,0.8,0.571429,0.333333,0`. Preserve the pinned release's
numeric behavior; do not invent a generic six-step Euler approximation.

Freeze exact portrait pixel bucket, actual frames and duration in configuration.
The saved source's five-second formula yields **124 frames at 24 fps**, about
5.167 seconds; reporting exactly five rendered seconds is inaccurate. Retained
duration is measured after editing, not invented from the requested integer.
Any 480p portrait adaptation is a new tested configuration, not the original
1344×768 UI template. Obtain the exact supported bucket from pinned runtime code
and test it before freezing the execution manifest.

Bind ordered, role-labeled image and audio references to explicit dynamic Ref2VA
ports, including speaker identity. Preserve every required character, active
wardrobe, set/prop and voice source hash; unsupported combinations fail before
HTTP. Audio refs are optional for an explicitly unconditioned-voice experiment,
but such an experiment cannot certify recurring voice identity. No invented
voice-profile control or simultaneous FL2VA endpoint-frame support.

Existing `RenderRequest.audio_asset_id` represents one audio source and cannot
silently represent several ordered reference voices. Add the reviewed VOICE role
to V2 bindings and the explicit ordered module-local port map specified in the
implementation contract; use family-dispatched binding and verification. Keep
RenderRequest unchanged; independent contract review precedes schema mutation.
Resolve bytes only from verified private assets, stage them on the owned pod using
a reservation-scoped transport method, checksum uploads, and persist their remote
locator mapping. Do not insert host object-store paths into remote `LoadImage`.
Upload timeout/uncertainty must not trigger prompt submission with unknown inputs.

Hash the final bound API graph plus input-role receipts using existing canonical
hashing conventions. Preserve old V1 template hashes. Compare the **actual mapped
input/output schemas** from `/object_info` against the frozen runtime attestation;
the current canary `node_schema_digest` hashes its mapping, not live schema. Merely
checking node names is insufficient for this new route. Tests mutate required
ports, schema types and audio wiring and must fail before `/prompt`.

Fetch real `SaveVideo` output metadata and verify MP4 completeness, video stream,
required native audio, duration, dimensions and checksums before durable completion.
Missing/silent/corrupt audio fails the applicable sample; it is not filled by TTS.
Persist fetch/restart state through the existing provider operation and object
store metadata. No extra GPU job for exports or hook variants.

## 5. Durable experiment and canonical budget integration

### 5.1 Durable state

Add versioned experiment, sample and lease/reservation linkage records in the
application PostgreSQL. No second SQLite/JSON business-state store. Evidence JSON
and CSV are exports of durable state, never the authority for dispatch.

- Experiment: stable ID, owning existing episode/account, immutable plan/runtime/
  input hashes, operator authorization hash, hard stop, aggregate GPU-ms limit,
  max new exposure, max 24 samples, max one attempt per sample, shutdown/storage
  reserves and state/revision.
- Sample: unique `(experiment_id, sample_id)`, fixed seed/shot/config/input hash,
  current durable job/operation/reservation links, terminal result, observed
  output hashes, critical QA coverage and accepted retained duration.
- Acquisition: experiment link to each existing lease, compute-window bounds,
  shutdown/storage finality and exact canonical reservation/billing identifiers.
  Repeated cold starts consume the same remaining experiment allowance.
- Screening decision: references this exact experiment, its three current output
  hashes, coverage and rubric version; actor/decision timestamp and input hash.
  It is a one-time experimental continuation record, not an application gate or
  simulated episode approval. Missing/UNKNOWN critical screening coverage blocks
  continuation. Preserve rejected/failed screening outcomes.

Experiment states: PREPARED → SCREEN_RUNNING → SCREEN_REVIEW → FULL_RUNNING →
COMPUTE_COMPLETE → AWAITING_BILLING → COMPLETE. Side states FAILED, CANCELLED,
EXHAUSTED and NEEDS_RECONCILIATION stop new dispatch but permit cleanup/readback.
Sample states distinguish PLANNED, CLAIMED, SUBMITTING, SUBMITTED, OUTPUT_DURABLE,
SUCCEEDED, FAILED and UNKNOWN. Technical output completion is not quality PASS.

### 5.2 One economic ceiling

Reuse the existing episode BudgetService for all actual reservations/charges and
its $10 hard cap. Never create a new episode or budget to evade previous spending.
The experiment's proposed $8 is an additional **sub-limit**, not a replacement
account, and approval is required before it becomes executable configuration.

Implement experiment admission and canonical `BudgetService.reserve` in the same
database transaction/lock ordering. Use a transaction-capable reserve operation
owned by the budget integrator, not an outer pre-check followed by a separately
committed reserve. Lock episode/account then experiment consistently; atomically
claim the sample/lease, check immutable input and remaining allowance, reserve
canonical exposure and insert linkage. Concurrent workers must not both pass
the final affordable claim. Roll back all these changes together on refusal.

At admission, sum canonical linked settled/unbilled/in-flight exposure plus newly
requested worst case, remaining uncovered storage exposure and mandatory cleanup
reserve. Count each reservation once; credits/adjustments never replenish the
experiment authorization or episode allowance. Preserve reservation expiry/hold
semantics and the existing cleanup exception: dispatch can be blocked while
shutdown/reconciliation remains possible. Do not reserve a parent $8 hold and then
reserve the same child cost again. If an alternative parent/child escrow design
is chosen, it requires an explicit reviewed canonical transfer design first.

Lease-covered prompt holds still settle at zero; actual GPU charge comes once
through the lease billing ledger, including rejected samples and idle/download
time. Recalculate affordability for the actual maximum **simultaneously active**
holds; do not multiply 24 prompt holds if only one sequential prompt can exist.
Similarly, do not call prompt holds actual cost or allocate a full lease invoice
to each of its samples. Sample allocations plus explicit experiment overhead reconcile to canonical
usage. Startup, idle and tail stay in the overhead category unless explicitly
allocated by a deterministic basis; never duplicate those costs across samples.

Compute time is aggregated across all acquisition windows, including cold start
and cleanup; pause time with pods off is excluded. A process restart cannot renew
absolute hard stops or reset used GPU-ms. Project sufficient remaining shutdown
headroom before admission; a timed-out provider request must not permit more work.
Fresh quotes bind subsequent acquisitions, while aggregate budget/plan stay fixed.
Reserving a next lease must account for prior pending billing at worst exposure.

### 5.3 Resume and ambiguity

Unique semantic keys include experiment + sample + fixed attempt. Persist the
job/provider-operation intent before external effects. A worker uses exclusive
durable job leases and provider-operation arbitration. Resume reuses the committed
reservation/request hash and polls existing prompt IDs; it never issues a fresh
prompt because a local CSV lacks a result. An unknown submission stays UNKNOWN
until positively reconciled; absence from a queue is not proof of non-submission.

For create-before-pod-ID persistence, retain durable create intent and owned-name
reconciliation. Bind the provider ID as soon as trustworthy ownership is known,
including failure paths; never weaken the cleanup guard to act on names alone.
Reconcile and record any extra owned resource before dispatch; never acquire a
second pod to bypass an unresolved first creation.

Before waiting for screening, shut down/terminate and durably verify the owned
pod and storage outcome. A screening decision may permit a later acquisition
only within remaining authorized exposure/time; it does not zero pending bills.
SIGINT/SIGTERM, deadline, failed output, rights expiry, overspend or invalid schema
all stop new dispatch and enter the same cleanup path. The independent janitor
operates from existing durable leases and account ownership, even after the CLI
crashes. COMPLETE requires sample outcomes, no unknown effects, verified cleanup
and required invoice finality; COMPUTE_COMPLETE may retain pending billing.

## 6. CLI, authorization and effect boundaries

Add a separate `python -m microdrama.pipeline.benchmark` entrypoint with
`prepare --plan <json> --experiment-id <uuid>`, `preflight`, `execute --phase screen`,
`status`, `resume`, `record-screening`, `execute --phase full`, `sweep` and `export`
operations. Every non-prepare operation names `--experiment-id`; effectful
execution also requires `--authorization` and `--authorization-sha256`. Keep old
canary JSON/CLI semantics unchanged, including its
three-attempt global cap. Do not wrap eight independently funded canaries.

`prepare` creates PREPARED experiment and its 24 immutable sample rows in one
loopback PostgreSQL transaction, with no provider call, budget reservation,
provider job, human approval or eligibility change. It is permitted in offline
preparation mode under this task authorization. The supplied UUID plus canonical
plan hash is its idempotency key: same UUID/hash replays, changed contents conflict;
a different UUID does not duplicate an already registered canonical plan on the
same episode/configuration. `seal` binds verified assets/runtime to a separate
immutable execution manifest as specified in the implementation contract. Actual
references may be unresolved at preparation;
that state must fail executable preflight. Preparation freezes planned work,
not permission to spend.

Preflight reads the authoritative loopback database through the existing guarded
DSN; “no network” here means no external provider HTTP, not a ban on that local
SQL connection. It creates no experiment/sample rows or reservations and resolves
no provider credential values. It validates local pinned configuration, ownership/account scope, rights,
prices, current remaining episode allowance, experiment caps, schema/input
attestation presence and durable plan consistency. It resolves no secret values,
performs no external HTTP, creates no paid reservation/pod and writes no fake approval.
Print explicit not-ready reasons and the exact canonical authorization hash.
Execute repeats the authoritative budget, account, quote, plan and rights checks
in the admission transaction; a previous preflight is not a stale permission slip.

Any execute/resume path that admits new generation or acquisition requires the
current authorization and effect flags. Cleanup-only resume and sweep remain
available after quote/rights/authorization expiry, without new dispatch; they
retain the existing ownership/cleanup exception. Execute requires PAID_BENCHMARK, explicit effect flags, current operator authorization file and verified SHA-256, FILE credential refs, actual rights route/evidence, verified asset bytes,
runtime/image/schema pins, current quote, absolute object-store path and loopback
database safeguards. Offline/mock mode fails before network or credential access.
No fixture rights registry seed, fabricated preset measurements or default prices.
Local automated tests use connected scripted transports with synthetic provenance
clearly labelled; no real credentials or paid/public destinations.

## 7. Files, interfaces and bounded build slices

Inspected source anchors (at `0851374`; rebase line locations before briefing):

| Slice | Existing files/symbols | New owned paths |
|---|---|---|
| Review fixes | `rendering/runpod_transport.py:225–261,596–625`; `rendering/comfy_transport.py:53–89`; matching transport/billing tests | Small shared sanitizer if needed, scoped regression tests |
| Graph | `rendering/workflows/templates.py:18–48,101–134`; `binding.py:132–164`; `v2_binding.py:39–320`; `comfy_jobs.py:499–570`; `comfy_transport.py:92–326` | `rendering/workflows/pika_h3_flex.py`; pinned API graph fixtures/schema; real-model image directory |
| Experiment | `pipeline/canary_authorization.py:56–218` as compatibility reference only; `canary.py:698–1195` cleanup patterns; `budget/service.py:323–482`; lease/comfy services | `pipeline/benchmark.py`, `pipeline/benchmark_authorization.py`, `rendering/benchmark_experiments.py`, integrator-owned additive migration and scoped tests |

Do not ask a headless builder to discover arbitrary relevant code. Each actual
brief must include exact pinned symbols/line ranges, API signatures, tests and
out-of-scope paths. Do not send credentials or private canary evidence to routed
workers. Keep unrelated story/release/UI/provider services out of scope.

## 8. Acceptance and fault tests

1. R1 conserves rounded total across components and retains malformed-row disputes;
   R2 redacts supplied synthetic secrets through exception/record/CLI sinks.
   For R1, preserve the original raw decimals and distinguish representation noise
   from inconsistent billing. Proposed maximum raw-sum tolerance is `0.000000000001`
   USD (one millionth of a micro-USD), calculated with Decimal and recorded as
   normalization policy. It is a reviewable policy proposal, not a provider promise.
   Test actual run-14 floating encodings, exact identities, both sides of this
   tolerance, ties and positive/negative integer rounding residuals; a real mismatch
   must still enter the existing dispute path.
2. API graph is validated against the pinned actual/schema fixture; all required
   refs, Thai lines, seed, 124-frame grid where applicable, sampler/sigmas and
   **decoded native audio** survive binding. A changed role/order/hash, missing
   dynamic port, missing audio or changed schema refuses before submission.
3. Provisioning refuses missing space/hash mismatch/partial files; no network in
   normal preflight/startup and no mutable model fallback. CPU/runtime registration
   checks are distinguished from a mere JSON fixture or GPU inference proof.
4. A composed scripted 24-sample experiment enforces one shared sub-limit through
   canonical per-effect reservations, with no duplicate parent hold and with
   only the three frozen screening samples initially dispatched. Failure/UNKNOWN
   coverage blocks the other 21 and shuts down the pod before a human wait.
5. Kill/restart before reserve, after committed reserve, around create, before/after
   prompt-ID persistence, during output copy and before finality. Assert stable
   experiment/sample/job identity, retained charges, no duplicate prompt, no budget
   reset, no blind retry on uncertainty and exactly one allocation per source.
6. Race two workers for the same sample and for different samples at the final
   affordable boundary. Only one affordable committed effect may pass. Test a
   concurrent ordinary job on the same episode; canonical $10 cap still holds.
7. Exhaust spend, aggregate time, storage tail or attempt count; further dispatch
   refuses, but owned-resource cleanup remains possible and foreign pods stay
   untouched. Test price/schema/rights changes at reacquisition and replay.
8. Billing revision/invoice mismatch keeps holds; matched invoices finalize once;
   repeated sweeps are idempotent. Component rounding fix must not rewrite history.
9. OFFLINE_MOCK/private staging cannot become paid mode via benchmark command;
   all denied paths make zero provider/resolver calls. No hidden hosted Pika calls.
10. Focused tests first, then `make check` and `make pilot` once at the final tree
    under CPUQuota=45% with isolated `--basetemp`. Budget full-suite host time and
    disk; preserve failures honestly. Run a single image build separately from
    heavy tests. Independent review covers the final immutable patch using a different native
    Codex reviewer from its implementer; unreviewed code remains unmerged.

## 9. Alternatives and risks

Rejected: increasing `CanaryCaps.max_attempts`, relabelling the fake benchmark,
external TTS as the default, arbitrary graph execution, new disposable episode
accounts, JSON-only state, or manual pod/model runs presented as integration.
They bypass compatibility, controls, durable spend or the selected native route.

Main residual risks are A40 fit/precision fidelity, CPU-only schema availability,
disk capacity, exact Thai performance and release rights. None permits inventing
qualification. Model choice remains fixed; a failing route produces a measured
failure and a new operator decision, not an automatic substitute.

## 10. Review and rollout status

The former GLM quota gate was superseded by the operator's explicit direction:
"use codex for everything, do not go through ai-route/". Use the installed native
EGM Goldfish workflow with fresh-context Codex reviewers, then native Codex builds
and a different reviewer for the implementation. No ai-route calls are permitted
for this work. The paid execution boundary remains unchanged.

After at most two scoped review rounds, unresolved rulings return to the operator
per project policy. Once software passes, present one concrete paid screen with
current quote, exact image/schema/input hashes and budget. That paid approval is
separate from steps 1–3. No production registry enable, model download to this
space-constrained host, deployment or public action follows from software tests.
