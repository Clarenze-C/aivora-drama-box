# GLM independent review — T031 native H3 Flex harness (048cc05 scope)

Reviewer: GLM-5.3 (independent; Codex wrote the code). Date: 2026-11-10.
Scope: the 81 files of `048cc05`, read at worktree HEAD `d971435`. The CN-1..CN-6
fix diffs (`9197c52..d971435`) and the migration-guard commits (`c6e19e0`, `2ceb341`)
were treated as reviewed elsewhere; anything they missed in the surrounding harness
is reported below. No test suites were run (orchestrator holds `make check`); small
in-memory probes were used (config-hash pin, hash-function compatibility, fixture
mapping).

Verdict up front: **FIX-REQUIRED** — 2 BLOCKING, 4 SHOULD-FIX, 3 NIT.

---

## Findings

### H-1 · BLOCKING — default live path crashes in `acquire()`: one-arg `bind_pod_endpoint(pod)` call

- **Where:** `microdrama/src/microdrama/pipeline/experimental_world.py:150` (call),
  `microdrama/src/microdrama/rendering/comfy_transport.py:124` (definition;
  requires `pod_id: str, endpoint_url: str | None`), correct form for contrast at
  `microdrama/src/microdrama/pipeline/canary.py:1019`.
- **Scenario:** Any default-composition execution — `benchmark execute|resume`
  (non-cleanup) → `build_experiment_world` → `PikaHttpClient` (inherits
  `bind_pod_endpoint`, so the `hasattr` guard at line 146 passes) →
  `_advance_owned` → `world.acquire()` → `bind_pod_endpoint(pod)` with a single
  `PodInfo` argument → `TypeError: missing 1 required positional argument
  'endpoint_url'`. This happens **after** `ensure_pod` created/verified/activated
  the paid pod. `except BaseException` in `_advance_owned`
  (`benchmark_service.py:358`) then sets `execution_outcome='FAILED'` (set-once →
  terminal), sweeps the pod, and re-raises; every later `execute`/`resume` refuses
  with "experiment outcome is terminal". Net effect: every live run burns one pod
  create/shutdown cycle and permanently fails the experiment.
- **Why the 124-test fixture missed it:** the composed fixture's Comfy client
  (`comfy_support.ComfyWorld`) has no `bind_pod_endpoint` attribute, so the
  `hasattr` branch is skipped entirely; only the live `PikaHttpClient` inherits the
  two-argument method.
- **Fix:** `self.comfy._client.bind_pod_endpoint(pod.pod_id, pod.endpoint_url)`
  (mirroring canary.py:1019), plus a default-factory composition test that
  constructs `build_experiment_world` with a `PikaHttpClient` and a scripted
  transport so this signature drift can never again hide behind `hasattr`.
- **Confidence:** high (signature mismatch verified directly at HEAD; no other
  `bind_pod_endpoint` override exists — grep-confirmed).

### H-2 · BLOCKING — no reconciliation path for UNKNOWN effects; one ambiguity strands the experiment permanently

- **Where:** `microdrama/src/microdrama/rendering/comfy_jobs.py:849-853` (`poll`
  raises on UNKNOWN forever, without re-checking `/history` even when
  `external_id` is persisted), `microdrama/src/microdrama/pipeline/benchmark_service.py:347-357`
  (NeedsReconciliation → acquisition UNKNOWN + experiment NEEDS_RECONCILIATION →
  sweep), `benchmark_service.py:541-549` (sweep unconditionally rewrites
  acquisition state to CLOSED/CLEANUP_PENDING, discarding the UNKNOWN marker), and
  the CLI (`pipeline/benchmark.py:29-55`: prepare/seal/preflight/status/execute/
  resume/record-screening/sweep/export — none reconciles).
- **Scenario:** one prompt POST timeout during `submit` → `_mark_unknown` → the
  sample keeps a UNKNOWN `provider_operations` row and the dispatch slot keeps the
  sample (`_observe` never ran). Every later `resume` → `execute` → `_advance_owned`
  → `_claim_sample` returns the same stuck sample → `world.poll` raises
  NeedsReconciliation → loop repeats forever. Same for an ambiguous pod create:
  `NO_CREATE_PROVEN` exists in the schema and every state filter but **nothing ever
  sets it**; `_close_claim_without_pod` never sets `terminate_verified_at`, so a
  create-timeout resolved as "no pod visible" leaves the acquisition in
  CLEANUP_PENDING, which the partial unique index
  (`0026:40`) treats as occupying the slot — no new acquisition is ever possible.
  The integration contract §E explicitly assigns this state to a
  "provider-operation reconciler"; none exists in the harness.
- **Money impact:** none — holds are retained, exposure keeps counting them, sweep
  still stops owned pods. But the $8 one-shot experiment becomes unresumable by any
  in-repo path after a single ambiguity (only direct SQL could clear it).
- **Fix:** a reconciliation capability: resume may re-poll UNKNOWN operations that
  have a persisted `external_id` (guarded `/history`), and an operator command
  must exist to record a terminal operation outcome or `NO_CREATE_PROVEN` with
  evidence, moving sample/acquisition to a terminal state.
- **Confidence:** high (all cited code paths read; no reconciler found by grep
  across src and CLI).

### H-3 · SHOULD-FIX — preflight reports executable-ready from labels/hashes while the default factory refuses

- **Where:** `microdrama/src/microdrama/pipeline/benchmark_service.py:62-101`
  (`preflight`) vs `microdrama/src/microdrama/pipeline/experimental_world.py:227-272`
  (`ExperimentalPresetPolicy.validate`) and `experimental_world.py:355-422`
  (`_validated_sources`).
- **Scenario:** preflight's `ready` depends only on: seal present,
  `schema_evidence == "LIVE_PROVIDER"` (an operator-asserted label), deadline,
  flags, and `authorization.validate_for` (hash chain + quote ceilings). It never
  consults the preset registry record (existence/version/workflow/configuration
  pins), current model-output rights, per-reference rights/asset state, or
  remaining headroom against `cap_micro_usd`. Concrete failure: a sealed reference
  asset falls out of ACCEPTED/LOCKED, or a rights grant lapses, or exposure is
  already at cap → `preflight --experiment-id … --authorization … --quote …`
  prints `ready: true`; `execute` then dies with PolicyDenied/BudgetExhausted
  inside `build_experiment_world`. RESUME-doc item 4 requires exactly this not to
  happen ("must not report executable-ready merely from labels/hashes while
  default factory later refuses"). Note also that no PIKA `PresetRecord` seed
  exists anywhere (`registry_seed.py` has no pika entry), so until an operator
  registers the record out-of-band, preflight is `ready: true` and every execute
  refuses at `record is None`.
- **Fix:** have preflight run `policy.validate` (all local DB reads; no HTTP) and
  include cap headroom/exposure in the ready decision, keeping the reason strings
  secret-free as they are today.
- **Confidence:** high.

### H-4 · SHOULD-FIX — §G raw billing evidence is implemented but never called

- **Where:** `microdrama/src/microdrama/rendering/benchmark_experiments.py:383-423`
  (`BenchmarkRepository.record_billing_evidence`), migration table
  `benchmark_billing_evidence` (`0026_t031_benchmark_experiments.sql:70-77`); no
  caller anywhere in `microdrama/src` or the CLI (grep-verified; only
  `test_migrations.py` names the table).
- **Scenario:** a paid benchmark run ingests RunPod billing through
  `map_billing_history`; the exact provider amount strings ride the transport
  record (`runpod_transport.py:716`) and are hashed into the bucket observation
  (`runpod_billing.py:42-59`), but the append-only evidence row the integration
  contract §G requires "before normalization is used for allocation" is never
  written. After the pod and its buckets age out, the raw strings are not
  reconstructible — precisely the gap §G was written to close for new
  acquisitions.
- **Fix:** wire `record_billing_evidence` into the billing ingestion (or the
  sweep/finality step) for observations on pods owned by benchmark acquisitions,
  keyed by `observation_identity` + raw commit hash as designed.
- **Confidence:** high.

### H-5 · SHOULD-FIX — shot-scoped port maps validate at seal time but cannot stage or bind

- **Where:** `microdrama/src/microdrama/pipeline/benchmark_authorization.py:227-237,240-241`
  (seal validator supports per-shot port groups: "shot-specific ports must cover
  all eight shots"), vs `microdrama/src/microdrama/pipeline/experimental_world.py:566,634`
  (`stage`/`bind` iterate the whole `port_map` for every sample),
  `microdrama/src/microdrama/rendering/workflows/pika_h3_flex.py:89-97,269-270`
  (`PikaPortMap` has no shot scope; duplicate destinations refused), and
  `0026:60` (`UNIQUE(acquisition_id,destination_slot)` on `benchmark_uploads`).
- **Scenario:** the packet's S08 is a deliberate costume-change shot. An operator
  seals a valid shot-scoped map (outfit A for S01–S07, outfit B for S08) — the
  seal validator accepts it (destination uniqueness is checked per shot group).
  At staging, `stage()` inserts both outfit rows with the same
  `destination_slot` → unique-constraint violation → `except BaseException` →
  experiment FAILED after the pod was acquired. The only executable seal form is
  a fully shared map, so a per-shot wardrobe change is unrepresentable through
  the sealed path, and the validator advertises a feature the binder can't run.
- **Fix:** either reject shot-scoped port maps at seal time (honest narrowing to
  the shared-map v1, documented), or thread shot scope through
  `PikaPortMap`/`stage`/`bind` so each sample binds only its shot's ports.
- **Confidence:** high on the mechanics (constraint + code paths verified);
  medium-high on intent (shared-map-only may be a deliberate v1 narrowing that
  the validator failed to encode).

### H-6 · SHOULD-FIX (low risk) — `LIVE_PROVIDER` schema evidence is a self-asserted label; known CPU hash not machine-denied

- **Where:** `microdrama/src/microdrama/pipeline/benchmark_authorization.py:163,398-399`
  (label gated, never corroborated), `microdrama/src/microdrama/pipeline/benchmark_service.py:69`
  (preflight trusts the label).
- **Scenario:** the CPU/no-weight attestation
  (`deployment/pika-h3-flex/schema-attestation.cpu.json`,
  `evidence_kind: ACTUAL_RUNTIME_CPU_NO_WEIGHTS`) and the offline fixture hash to
  the **same** mapped schema hash (`339021b1e3106ee0…` — verified by probe). A
  seal built from that JSON and relabelled `LIVE_PROVIDER` passes preflight and
  `policy.validate` (self-consistent hash). On the weights-free CPU image the
  bind-time live attest would even match, so the failure surfaces only at
  generation (empty loader enums → prompt error), after the pod was paid for —
  waste bounded by the compute hold inside the $8 envelope. Mitigation that keeps
  this from misqualifying a real run: on a weights-provisioned runtime the loader
  filename enums are non-empty, so the live schema hash necessarily differs and
  `attest_schema` fails closed (BUILD_EVIDENCE.md documents the reattestation
  requirement). The checklist item nonetheless asks that the CPU attestation can
  *never* be relabelled — a cheap deterministic guard is available and absent.
- **Fix:** refuse `LIVE_PROVIDER` seals whose `node_schema_sha256` equals the
  published CPU/fixture hashes (and record those hashes as constant pins).
- **Confidence:** high on mechanics; risk assessed low because of the enum drift.

### H-7 · NIT — cleanup holds can link to the wrong acquisition

- **Where:** `microdrama/src/microdrama/rendering/benchmark_experiments.py:131-135,174-175`
  — `reserve_linked` auto-assigns `acquisitions[0]` **ordered by `acquisition_id`**
  (a uuid5 value, not generation) when `acquisition_id is None`;
  `LeaseService._reserve_cleanup_grant` (`leases.py:1390-1430`) reserves the
  `pod.stop` grant through plain `reserve()`, so with two acquisitions the CLEANUP
  link can attach to the acquisition whose UUID sorts first rather than the lease
  being stopped.
- **Impact:** bookkeeping only — exposure() sums per experiment; storage release
  filters on purpose='STORAGE'. The composed test's `CLEANUP: 2` assertion passes
  either way.
- **Fix:** thread the owning lease/acquisition into the cleanup reserve, or order
  by generation.
- **Confidence:** medium-high.

### H-8 · NIT — dead duplicate `ExperimentalPresetPolicy`

- **Where:** `microdrama/src/microdrama/rendering/experimental_presets.py` — used
  only by its own test (`test_pika_h3_flex.py:481-517`). The live factory uses the
  same-named dataclass in `experimental_world.py:221-272`, whose checks differ
  subtly (the dead copy pins `steps == 6` and `authorization_sha256`; the live one
  pins workflow/configuration hashes and rights instead). Two same-named policies
  invite editing/testing the wrong one.
- **Fix:** delete the rendering module (and its test), or make the live policy the
  single implementation both consume.
- **Confidence:** high.

### H-9 · NIT — prompt-hold expiry makes late resume a ~10-minute window with a terminal downside

- **Where:** `comfy_jobs.py:346-369` (hold `expires_at = now + timeout_ms`, 600 s
  default), `comfy_jobs.py:399-424` (`_verify_reservation` demands ACTIVE),
  `benchmark_service.py:358-364` (any submit-time Conflict → `except BaseException`
  → outcome FAILED, terminal).
- **Scenario:** crash between `_claim_sample` and `submit`; if the janitor expires
  the hold before the operator resumes, submit refuses and the whole experiment is
  terminally FAILED rather than reconciled. Contract-conformant (§F: a pre-effect
  refusal "records a terminal outcome and safely closes only its own positively
  unused hold") but the window is undocumented and unforgiving for a human-paced
  restart. (If the janitor has *not* expired it, dispatch proceeds on the
  stale-but-ACTIVE hold, which still counts in exposure — safe.)
- **Fix:** document the resume window, or permit a same-identity hold refresh
  before any effect.
- **Confidence:** medium (both branches traced; which one fires depends on janitor
  timing).

---

## Checklist coverage table

| Item | Result |
|---|---|
| **1. Money** — 3 screen + 21 samples share one budget and hard stops | CHECKED-OK — one experiment, one cap (8·10⁶ µ$), shared exposure projection (`benchmark_experiments.exposure`), aggregate `gpu_ms`, absolute deadline, `execute full` requires a same-experiment screen PASS |
| — $8 envelope vs retries/restarts/crash hold→settle | CHECKED-OK — intent+compute+storage holds commit atomically before any effect; holds survive crashes and keep counting; candidate counted once; CREDIT never replenishes; replay links once; overrun recorded, never edited. Provider-side tail beyond holds remains best-effort exactly as the contract concedes |
| — canonical services and price units | CHECKED-OK — compute/prompt holds via canonical `reserve_in_transaction` (GPU_SECOND lease/prompt house pattern; quote must be whole µ$/GPU-second so `hourly//3600` is exact); storage hold is `PriceUnit.REQUEST` at the attested ceiling; prompt holds settle zero under `lease_covered` (pod invoice is the only GPU cost) |
| — three-attempt canary / production preset eligibility unchanged | CHECKED-OK — `canary.py` untouched by 048cc05; `live_world` refactor is behavior-identical extraction; experimental preset must be disabled/unmeasured; routing contract pin updated to include the new template |
| — storage/invoice finality, raw billing evidence | FINDING — finality itself CHECKED-OK (storage hold released only at verified terminate + BILLED, one transaction); raw evidence H-4 |
| **2. Idempotency** — no duplicate pod create after durable intent | CHECKED-OK — `ADMITTED_WITHOUT_JOB` intent + holds atomic; `claim_pre_reserved` replays the exact hold; unique `(provider, client_token)` insert; first-create-only proof (CN-2); partial unique acquisition index |
| — no duplicate prompt after uncertain outcome | CHECKED-OK — single POST, deterministic client token, existing operation → poll reattach, UNKNOWN never resubmitted, upload POST requires precommitted UNKNOWN row |
| — dispatch-slot races | CHECKED-OK — slot row `FOR UPDATE`, coordinator token + 1 h lease, two-worker atomic boundary test |
| — restart / coordinator adoption | CHECKED-OK — deterministic semantic keys/UUIDs, persisted request incl. expiry, job/lease materialization replays; composed test restarts coordinator objects |
| — expired-lease cleanup | CHECKED-OK — coordinator lease expiry allows takeover; cleanup-only world rebuilds authorization/quote from durable rows while every new-effect guard still refuses |
| — acquisition-scoped uploads / UNKNOWN reconciliation | FINDING — uploads CHECKED-OK (deterministic `t031/…` keys, UNKNOWN-before-POST, reconcile-only after any durable intent, per-pod upload rows); operation/pod UNKNOWN reconciliation missing → H-2 |
| **3. Rights & identity** — model rights AND reference grants | CHECKED-OK — `_validate_model_rights` requires the four `model_rights_*` pins matching the *current* registry row (hash+version) and eligible MODEL_OUTPUT evaluation before any query; per-reference `validate_current_rights_grant` through a live resolver; a reference grant alone can never clear model rights (tested) |
| — auth byte hash and current caps | CHECKED-OK — raw-file SHA-256 (hmac-compared), caps ≤ prepared envelope, recorded authorizations append-only and hash-bound |
| — logical plan alias / seal identity | CHECKED-OK — replay/conflict/alias covered by tests + `UNIQUE(episode_id,plan_sha256)`; seal set-once trigger, hash-verified readback (`decode_seal`) |
| — per-shot speaker/outfit selection | FINDING — speakers CHECKED-OK (`speaker_subject_ids` must exactly equal the voice-anchor set; one anchor per speaker enforced at contract and binder); shot-scoped outfits H-5 |
| **4. Honest readiness** | FINDING — preflight gap H-3; CPU-attestation relabel guard H-6 |
| **5. Safety** — paid/cloud/public effects gated | CHECKED-OK — CLI refuses work commands before DB/provider unless PAID_BENCHMARK + both flags; world composition re-checks `require_effect`; per-request `request_guard`/`dispatch_guard`; cleanup-only world refuses creates/inputs/prompts |
| — no secrets in image/logs/records/exceptions | CHECKED-OK — FILE-only credential resolver (owner-only, no symlinks, values never echoed); `safe_diagnostic` redaction on both transports; whitelist-only billing evidence; loader errors never reflect input |
| — image/weights pinned, pulled only at authorized time | CHECKED-OK — digest-pinned base + source archive (sha256-verified in-layer), HF offline env, no weights in image, `provision.py` requires explicit `--download` with per-file size+sha verification and disk reservation; 42,030,014,463 bytes pinned across five files; gateway token from env at create, none baked in |
| — 0026 guards | CHECKED-OK — immutability/append-only/no-delete/no-truncate/integer-number/set-once triggers on every benchmark table |
| **6. Tests** | CHECKED-OK with gaps — the new suites are behavioral (corruption counterexample matrices, real-ffmpeg stream evidence, live-boundary denials, two-worker atomicity, replay/conflict/alias). Important untested paths: the default `build_experiment_world` composition itself (H-1 proves the gap), shot-scoped port maps (H-5), UNKNOWN-effect recovery (H-2, absent), CLI `sweep` against a recorded authorization |

Not reached: running any suite (orchestrator owns `make check`); independent
re-resolution of `runtime.lock`/`dependency-resolution.json` (taken as pinned
inventories); live provider behavior.

---

## Verdict

**FIX-REQUIRED.**

- BLOCKING: 2 (H-1 live-path `bind_pod_endpoint` crash; H-2 missing UNKNOWN reconciliation)
- SHOULD-FIX: 4 (H-3 preflight honesty; H-4 dead billing evidence; H-5 shot-scoped ports; H-6 CPU-hash relabel guard)
- NIT: 3 (H-7 cleanup link attribution; H-8 dead duplicate policy class; H-9 resume window)

The money, rights and safety architecture is sound and consistently fail-closed;
the two blockers are both in the seam between the fixture-driven tests and the
default live composition — exactly the seam this review was asked to probe. Neither
blocker can overspend the envelope, but H-1 makes every default execution fail
after paying for a pod, and H-2 makes any single ambiguity permanent. Both must be
fixed (with a default-factory composition test) before any paid screen is proposed.
