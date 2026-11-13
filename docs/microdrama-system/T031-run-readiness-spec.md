# T031 run-readiness (R5): one real Pika H3 Flex experiment on the accepted benchmark path

**Version 0.3, 13 Nov 2026.** Author: Opus orchestrator. v0.2 applied the Goldfish rulings (`T031-fix-round/r5-goldfish-rulings.md`)
to the v0.1 review (`T031-fix-round/r5-goldfish/consolidated_review_report.md`; all findings accepted, ST1 refuted). **v0.3 applies
the Codex round-1 critique** (`T031-fix-round/codex-r5-critique.md`, verdict REWORK) **per `T031-fix-round/r5-critique-rulings.md`**:
all 12 findings accepted (R5C-1..9 BLOCKING, R5C-10..12 SHOULD-FIX), gate placement (a) chosen, nothing rejected, nothing weakened.
**Status: DRAFT — Codex round 1 applied; the R5a–R5f build brief follows against v0.3.** Large / money path: spec → Codex critique
(round 1 applied) → GLM build → Codex review → gate.

**Operator decisions (12 Nov, DECISIONS "T031 run-readiness"):** build this package now; any live-capture
pod cost counts **inside the $8 benchmark envelope** (total new exposure ≤ $8.00 = 8,000,000 µUSD). The
paid-run sign-off stays a separate explicit approval of the concrete authorization file.

**Base:** `feat/t031-fix3` @ `104b26b` (T031 H-2 accepted at `0cda424`, plus `304ea77` build.sh fix and
evidence docs). Every `file:line` cite added in v0.2 was verified in the read-only worktree
`.scratch/t031-fix3-worktree` at that commit; cites are unique basenames under `microdrama/` (migrations
named in full). **Facts:** [paid-run fact map](t031-benchmark/paid-run-factmap.md), cited `FM §n`. The further
`file:line` cites added in v0.3 (from the Codex critique) were re-verified in the same worktree at the same commit.

## 1. Problem

The accepted H-2 controller handles budget, recovery and billing for paid pod runs. It cannot yet run a
real model:

| # | Gap (FM §10) | Consequence |
|---|---|---|
| G1 | Nothing provisions the 5 pinned weight files (42,030,014,463 B) on the pod; `provision.py` is invoked by no code (FM §5) | ComfyUI boots without models; every sample fails |
| G2 | No boot/ready wait: after pod create the service goes straight to `stage_inputs` → `attest_schema` → `GET /object_info` with a 30 s request timeout (`benchmark_service.py:1195`, `pika_transport.py:139-205`, `comfy_transport.py:73-74`) | A booting/provisioning pod (gateway 502, connection refused) is misread as a failure or an upload ambiguity |
| G3 | The seal needs `schema_evidence=LIVE_PROVIDER` + `INDEPENDENT_RUNTIME_CAPTURE`, but no tool captures a live schema, and a live schema exists only on a pod with weights (FM §4, `benchmark_authorization.py:410-420`) | No valid seal can be authored before the first paid pod |
| G4 | No authoring tool for plan/seal/quote/authorization; no CLI for real asset, rights, preset and credential rows (FM §2, §6, §10.2-3) | The run can only be assembled by ad-hoc Python |
| G5 | No cold-start, provisioning, sampler or full-job timing writers (FM §5, §9) | `results-template.csv` timing columns can't be filled |
| G6 | Export → `results-template.csv` is manual (FM §9) | Error-prone result tables |
| G7 | No executable per-pod billing verification: ordinary ingest records provider observations only, nothing drives invoice verification (`budget/billing.py:208`, `:449`; wrapper pattern `pipeline/canary.py:1307-1335`) (R5C-7) | After screen (or a failed boot), pending financial finality keeps the acquisition CLEANUP_PENDING with STORAGE exposure and correctly blocks full/boot retries — the printed sequence was unexecutable |

## 2. Scope and non-goals

In scope: R5a–R5f (R5f added in v0.3). **Out of scope:** any change to H-2 recovery, locking, billing or
resolution semantics; the known limits HC-6, HC-9, HC-11, HB-13 and the R1 residual (glossary; they stay
for phase D); 768p; FL2VA; repair retries; any hosted Pika service. **No new migration** (A0-D owns 0027
on top of this tree; A1 has 0028–0031). If a fix needs a schema change, the builder stops at a red test
and reports. Two v0.3 additions sit **around** H-2's seams without changing its semantics for admitted
work (R5C-2, R5C-7): typed **pre-sample** boot-failure handling diverts failures before the generic
terminal handler ever fires (no admitted work exists yet), and R5f is a thin executable wrapper over the
existing invoice verifier — no new verification, locking or resolution semantics.

## 3. Design

### R5a — Weights on the pod (G1): an image start script, gated by a create-time field

- New image revision: `ENTRYPOINT ["/opt/pika/start.sh"]`. `start.sh` (POSIX sh):
  1. starts the token gateway (`canary_gateway.py`, unchanged auth) immediately;
  2. if `MICRODRAMA_PROVISION_MODELS=1`, runs `python /opt/pika/provision.py --manifest /opt/pika/models.json --destination /opt/ComfyUI/models --download`. **`start.sh` owns the state file** `/opt/pika/state.json`: it wraps `provision.py` and records state (`PROVISIONING` → `PROVISIONED` | `PROVISION_FAILED`), UTC start/end and the stderr tail. `provision.py` is unchanged (`deployment/pika-h3-flex/provision.py:72-78`); per-file byte counts are dropped;
  3. only after `PROVISIONED` (or when the flag is absent: CPU smoke and tests), `exec`s ComfyUI exactly as
     in the pinned base (`--listen 127.0.0.1 --port 8189 --disable-api-nodes --disable-all-custom-nodes`);
  4. on `PROVISION_FAILED` ComfyUI is **never** started; the gateway keeps serving the failed state.
- **Gateway endpoint.** **Both** `canary_gateway.py` copies (byte-identity guard:
  `tests/unit/rendering/test_canary_gateway.py:28-33,41`) gain the identical token-checked, read-only endpoint
  `GET /__drama/ready` returning `{"state": NO_PROVISIONING|BOOTING|PROVISIONING|PROVISIONED|PROVISION_FAILED,
  "provision": {state-file mirror}}`. The gateway **does not probe ComfyUI** — it reports only the state file;
  no state file → `{"state":"NO_PROVISIONING"}` (flag absent, canary/CPU image), so the byte-identity guard
  stays green. `BOOTING` = flag set, state file not yet written. "ComfyUI answering" is learned by the world's
  `/object_info` boot retry (R5b). No secrets and no paths outside `/opt/pika` in the body; every other path
  keeps the pinned base's behaviour (401 without token, 502 while ComfyUI boots).
- **Flag plumbing — through the composed create request (R5C-4).** New field `PodCreateRequest.provision_models: bool = False`
  (`src/microdrama/contracts/providers.py:209-217`; new — the class ends at `volume_gb` today). The transport
  stays world-agnostic: it maps the field to env `MICRODRAMA_PROVISION_MODELS=1` beside
  `MICRODRAMA_COMFY_TOKEN` (`src/microdrama/rendering/runpod_transport.py:382-391`). The Pika acquisition
  intent records the flag; **benchmark-side intent validation** refuses a Pika intent without it.
  The real create path, however, composes `PodCreateRequest` through `LeaseService._spec_for()`
  (`src/microdrama/rendering/leases.py:682`) → `PodSpec.to_request()` (`src/microdrama/rendering/pods.py:60`),
  and neither reads the acquisition intent — a default-False field plus a True intent would silently compose
  a False request (R5C-4). v0.3 therefore specifies **benchmark-scoped request construction**: the frozen
  provisioning flag is transferred from the acquisition intent into the actual `PodCreateRequest` composed
  for benchmark acquisitions (intent → lease/pod-spec construction → `to_request()`), and the **benchmark
  create guard requires both the intent and the composed request to contain `provision_models=True` before
  any POST** — a composed request carrying False never reaches POST. Tested through the composed acquisition
  path with the captured RunPod create payload (RR-T4); a direct field-to-payload mapping test alone cannot
  catch a broken bridge.
- **Image build scope.** Dockerfile `COPY start.sh`; `build.sh` stages it (`deployment/pika-h3-flex/build.sh:8`,
  the `cp "$here"/{…}` list); `test_pika_image_recipe.py` and `test_canary_gateway.py` updated.
- **Storage.** Decimal GB (10⁹ B) throughout; GiB is written explicitly where meant. Weights live on the **container disk** (`/opt/ComfyUI/models`); `persistent_volume_gb = 0`, so there is no stopped-storage tail. Required container disk ≥ image + 42.03 GB decimal (42,030,014,463 B, `models.json`) + largest file + 8 GiB headroom (`provision.py` free-space rule, `deployment/pika-h3-flex/provision.py:44-48`); **default 100 GB** decimal, exact figure set in the quote/authorization. The builder verifies from RunPod docs whether container disk includes the image layers and records the answer.
- Hugging Face access is anonymous over HTTPS at the pinned revision (FM §5): no credential.
- The rebuilt image keeps the CPU schema smoke path (flag absent) and must reproduce the CPU attestation receipt `1a6023e24ad38cd4ef41e1d3b1c727550a52cba9cd055be2ede8373e487a4c89` (the 6 Nov `--network none` schema smoke recorded in `deployment/pika-h3-flex/BUILD_EVIDENCE.md`, equal to `schema-attestation.cpu.json`). Rebuild and the operator's re-push give a new image digest; the seal pins the **registry manifest digest** (R5c).

### R5b — Ready gate (G2) and timings (G5), inside the request-guard architecture

- **What boot handling covers (R5C-1).** Boot handling covers positively identified pod warmup and endpoint
  discovery **before `acquire()` completes**, then gateway/Comfy readiness. Today `world.acquire()` calls
  `leases.ensure_pod()` (`src/microdrama/pipeline/experimental_world.py:176`), which requires RUNNING state
  and an exposed endpoint and raises `TransientProviderError("pod is not running yet (warmup incomplete)")`
  (`src/microdrama/rendering/pods.py:213`) while the pod is pending hardware or pulling the image — before
  any post-acquire wait could run; the generic handler then records terminal FAILED and sweeps, so the
  stated A40 queueing behavior could never reach `BOOT_TIMEOUT`. v0.3: pending state and a missing endpoint
  are waited on inside the boot window like any other non-ready observation — **retries are owned reads
  against the same durable lease/pod, never a second create** (RR-T5 asserts exactly one create); uncertain
  create outcomes (state UNKNOWN) retain H-2 reconciliation semantics unchanged (`pods.py:212` raises
  `NeedsReconciliation`; §2). The new world step `wait_ready(acquisition)` runs after pod create/bind and
  **before** the first `stage_inputs` of every acquisition (screen and full; recovery worlds before any read
  that needs ComfyUI — see the recovery rule below).
- **Guard integration — placement (a) chosen (R5C-10).** `wait_ready` never bypasses `request_guard`.
  Placement **(a)**: **no PROMPT reservation and no sample materialization before readiness** — so no prompt
  hold can expire during the boot window (the 600 s TTL concern is moot under (a);
  `runbooks/t031-benchmark.md:3-5`). Only the two boot reads — the ready poll (`GET /__drama/ready`) and the
  boot-window `/object_info` retries — are authorized, through a **narrowly guarded acquisition-read scope**
  with exact acquisition/COMPUTE-hold/lease/pod linkage. The `_scope()` used for `attest_schema`
  (`src/microdrama/pipeline/experimental_world.py:689-703`) is a sample-job/PROMPT-hold scope, not
  acquisition lease authorization (R5C-10); R5b adds the acquisition-read scope beside it rather than
  widening it. `/__drama/ready` is added to the guard's pre-operation read allowlist beside `/object_info`
  (`src/microdrama/pipeline/live_world.py:334-375`; the allowlist is the `path != "/object_info"` refusal).
  The existing sample/operation guards for uploads and prompts are preserved unchanged. Placement (b) is
  rejected — §8.
- **Lease liveness during boot (R5C-8).** The default heartbeat timeout is 5 min (`heartbeat_timeout_ms =
  300_000`, `src/microdrama/rendering/leases.py:135`) and the janitor sweeps leases whose heartbeat is stale
  (`src/microdrama/rendering/janitor.py:238`); a 25-minute wait that only polls would let an independent
  janitor terminate a healthy provisioning pod well before its deadline. Boot waiting therefore **maintains
  authorized lease liveness throughout** — without extending the hard deadline and without reviving a fenced
  lease — checks deadlines **before every request and after every sleep**, and bounds each transport timeout
  by the remaining boot budget. Tested as a 25-minute boot with concurrent janitor sweeps (RR-T5).
- **Polling.** It polls `GET /__drama/ready` (token-auth) every 10 s. Connection refused and HTTP
  404/502/503/524 — the canary's documented tolerated set through the RunPod proxy
  (`src/microdrama/pipeline/canary.py:1043-1046`) — and states `BOOTING`/`PROVISIONING`/`PROVISIONED` mean
  "keep waiting". They never create an upload or submit ambiguity, and they create no provider operation.
- **Typed pre-sample boot failures (R5C-2).** `PROVISION_FAILED`: the world refuses the acquisition
  (`PolicyDenied PROVISION_FAILED`, durable incident) and runs the normal verified cleanup. Typed,
  pre-sample boot failures — `PolicyDenied PROVISION_FAILED`, boot-phase `TransientProviderError`, and
  `BOOT_TIMEOUT` — are handled **before** the generic terminal failure handler (`except BaseException →
  outcome FAILED`, `src/microdrama/pipeline/benchmark_service.py:1268-1275`): their incident and cleanup
  obligation are persisted **without setting a sample/model failure outcome** (`execution_outcome` stays
  NULL, so the set-once trigger at `migrations/0026_t031_benchmark_experiments.sql:111` and the admission
  check at `benchmark_service.py:333-334` do not make the experiment terminal). Another acquisition is
  admitted only after the canonical blockers clear (preflight). Phase and attempt identity are recorded
  durably, and the three-attempt limit is enforced **under the admission locks** at `execute` admission,
  preserving the same experiment, authorization and budgets (§10; RR-T13).
- **Boot deadline and recovery (R5C-9).** Boot deadline = `min(created_at + boot_budget, lease deadline −
  shutdown margin)`; `boot_budget` = 25 min by default, set in the plan's `runtime_profile`; the shutdown
  margin is 60 s in the benchmark lease config (default 300 s, `src/microdrama/rendering/leases.py:134`,
  FM §7). On timeout: incident `BOOT_TIMEOUT`, no uploads, normal verified cleanup. Successful initial
  readiness is **persisted** (the `cold_start_ms` completion marker below is the durable record), and the
  boot deadline applies **only to unfinished initial boot**. Recovery of already-admitted work uses H-2's
  existing source binding, read authorization and recovery deadlines (`benchmark_service.py:2469-2478`);
  elapsed boot budget cannot reclassify recoverable work as boot failure — a healthy full-phase pod at
  minute 40 with a newly submitted, recoverable prompt is recovered, never `BOOT_TIMEOUT` (RR-T5).
- All waiting is GPU time on the experiment's holds (metered by the lease), so the $8 and 4 GPU-h caps cover
  it. Screen and full are **two acquisitions**: each pays its own cold start and a full 42.03 GB download (§4, §8).
- **Durable landing zone (verified; carrier per R5C-3).** Everything below goes in the **mutable
  `benchmark_samples.coverage` jsonb** — the set-once trigger covers only `job_id, operation_id,
  reservation_id, acquisition_id, request, output` (`migrations/0026_t031_benchmark_experiments.sql:112`),
  so `coverage` is writable. Boot failures precede claiming, so "the first claimed sample" is no carrier at
  all (R5C-3): acquisition records are stored on a **deterministic, already-prepared sample row without
  claiming it**, and **keyed by acquisition ID** so retries preserve every attempt. Incident, timing and
  capture keys are **atomically merged without replacing existing coverage**, and refusal evidence is
  **committed before cleanup** (RR-T14). Keyed:
  - `t031_timings` — per sample: `full_job_ms` is the completion duration and stays **UNKNOWN until the
    first terminal observation with verified durable output** (the first observe normally contains
    SUBMITTED — `benchmark_service.py:1241-1246`, `rendering/comfy_jobs.py:768` — and recording there would
    measure submission acknowledgement, not time to output; R5C-12); once written it is **preserved across
    replay**. `sampler_ms`: genuine sampler timing evidence is carried through the transport when available
    (`PikaHttpClient.history()` currently discards sampler timestamps — R5b preserves them when present),
    else null — exported UNKNOWN, never 0. Per acquisition, on its coverage row: `cold_start_ms` (pod create
    request → `wait_ready` completion, i.e. `PROVISIONED` plus the first successful `/object_info` — also
    the persisted initial-readiness marker, R5C-9) and `provision_ms` (state-file UTC timestamps);
  - `t031_live_schema` — per acquisition, on the same acquisition-keyed coverage row: the R5c live-capture
    record (raw JSON sha256, mapped sha256, acquisition id); the raw JSON itself goes to the object store.
  - **Incidents.** Verified: `benchmark_acquisitions.state` carries **no CHECK** — `state text NOT NULL`
    (`migrations/0026_t031_benchmark_experiments.sql:36`) — so the DB admits `PROVISION_FAILED` and
    `BOOT_TIMEOUT`, and the incident value is written there. Caveat found in code: sweep finalization
    transitions any state outside `('CLOSED','NO_CREATE_PROVEN')` to `CLOSED`/`CLEANUP_PENDING`/`UNKNOWN`
    (`benchmark_service.py:2031-2037`), so the state value marks the open window only; the durable incident
    copy (reason, UTC refusal time, attempt number) rides the acquisition-keyed coverage record — the
    ruling's named fallback zone — is committed before cleanup, and therefore survives the cleanup transition.
- `export` includes these fields.

### R5c — The seal's schema (G3): a predicted schema, verified live before any upload

P is the single design (Q1 decided). A capture-pod alternative exists only as a rejected alternative (§8).
Codex round 1 accepts P for this bounded benchmark provided the guarded live schema comparison stays
mandatory before every acquisition's first upload (verdict preamble) — R5c keeps that comparison decisive
("Live verification unchanged and decisive" below), so the operator's P decision is unchanged.

- **Prediction tool.** New tool `tools/t031_schema_predict.py` runs `schema_smoke.py` inside the **pinned
  image** with `--network none`. Five **zero-byte placeholder files**, named exactly as in `models.json`,
  are bind-mounted read-only into the ComfyUI model folders, so the model-name enums match a provisioned pod.
  - It writes `raw_object_info`, the mapped hash and a capture record: **registry manifest digest only**
    (a local image ID is forbidden there), placeholder names, tool version, UTC.
  - The builder proves offline that the placeholders populate exactly the enums real files would. Enum
    equality means **per-folder listing membership** (the weight-free schema's baked non-file entries, e.g.
    `pixel_space`, are exempt). Where ComfyUI lists files by name and extension, a zero-byte file is enough.
- **Sequence.** The operator pushes first; the orchestrator then runs the prediction **inside the pulled
  registry reference** (`ghcr.io/clarenze-c/drama-pika-h3-flex@sha256:<manifest digest>`); the capture record
  stores that manifest digest. Why binding: the seal's `image_ref` pins the pushed registry digest,
  `validate_for` machine-checks it, and pod create refuses any image not pinned by the attestation
  (`runpod_transport.py:349-350`); the 12 Nov build records local image ID `abd32e9e…` ≠ pinned `e4ccc004…`
  (`deployment/pika-h3-flex/BUILD_EVIDENCE.md:80-88`). §7 states the order.
- **Seal evidence.**
  - New `schema_evidence` value `PREDICTED_FROM_PINNED_IMAGE`; new `schema_attestation_source` value `MANIFEST_PLACEHOLDER_CAPTURE`.
  - `BenchmarkAuthorization.validate_for` accepts that pair **only** with all three of: (1) the mapped hash not in `DENIED_LIVE_SCHEMA_SHA256` (`benchmark_authorization.py:45-47`); (2) the seal's `image_ref` digest equal to the capture record's; (3) the model-name enums in `raw_object_info` equal to the `models.json` file names per folder.
  - `LIVE_PROVIDER` + `INDEPENDENT_RUNTIME_CAPTURE` stays accepted as in the pinned base
    (`benchmark_authorization.py:410-413`); `SELF_ASSERTED` stays refused.
  - **One commit for all R5c touch points**: the Literal widening (`benchmark_authorization.py:172-175`),
    `validate_for` (`:410-420`), **and `benchmark_service.preflight`** — which today independently refuses
    any seal whose `schema_evidence != "LIVE_PROVIDER"` (`benchmark_service.py:198`).
- **Live verification unchanged and decisive.** At readiness, the first `attest_schema` of each acquisition compares the pod's real mapped schema with the sealed hash before any upload (`experimental_world.py:705-717`: `stage` → `_scope` → `attest_schema`) and refuses on mismatch. R5c adds **durable recording of that live capture**: the world already re-reads `raw_object_info` with `schema_evidence="LIVE"` at bind (`experimental_world.py:920-929`); the record goes to the `t031_live_schema` coverage key and the raw JSON to the object store (R5b).

### R5d — Run assembly tool (G4): `tools/t031_prepare_run.py`

Offline, against the dedicated loopback paid DB (`tools/canary_db.py`, FM §1C). Every subcommand is idempotent and refuses on drift — **drift means a named frozen-field set per row type** — and none prints a credential value. Boundary: `prepare_run` authors and registers; **the benchmark CLI stays the only enforcement entry**.

1. **`register`.** Creates or validates real rows, never `FAKE_SYNTHETIC` (the builder lists the provenance and rights-basis enums that exist):
   - **episode and account:** a dedicated T031 benchmark episode on its EPISODE budget account (episode cap $10.00 = 10,000,000 µUSD, FM §7). Prior canary spend on the canary DB's own episode is reported, not moved (FM §7);
   - **assets and picks** (DECISIONS "T031 benchmark inputs"; A2/B2 canonical — r2's A-home was generated
     from r1's `A2.png`, `references-r2-manifest.jsonl` A-home `input_ref …/2026-11-12-r1/A2.png`):

     | Role | Subject | Asset |
     |---|---|---|
     | `character_identity` | A | `A2.png` |
     | `outfit` | A-office | `A2.png` |
     | `outfit` | A-home | `A-home.png` |
     | `character_identity` | B | `B2.png` |
     | `outfit` | B-office | `B2.png` |
     | `location` | office | `SET-office.png` |
     | `location` | home | `SET-home.png` |
     | `prop` | envelope-01 | `PROP-envelope-01.png` |
     | `voice` | A | `A-NEUTRAL.wav` |
     | `voice` | B | `B-NEUTRAL.wav` |

     Unpicked candidates (A1, A3, B1, B3) are **not registered**. **One verified byte upload reused by distinct semantic bindings (R5C-5).** The office outfits reuse the identity PNGs (A2 for identity:A + outfit:A-office; B2 likewise), and the seal permits one asset in different roles — no conditional fallback is needed. But identity:A and outfit:A-office share a digest-derived upload key, staging creates separate role rows, and the staging guard today fetches **one row by acquisition + key without role** (`src/microdrama/pipeline/experimental_world.py:1290`; upload path `src/microdrama/rendering/pika_transport.py:241`) — it can select the already-VERIFIED identity row and refuse the outfit POST because that row is not UNKNOWN (reproduced in an in-memory probe of the real guard; R5C-5). v0.3 therefore requires: staging **supports a single verified byte upload reused by distinct semantic bindings, preserving exact role/subject receipts and checksum readback**, and the **ambiguous key-only guard lookup is eliminated** — upload verification is scoped by acquisition + key + role + subject, never key alone. The authored eight-shot maps, including the office reuse and S08's home outfit, are exercised through real staging/binding (RR-T15). Each asset row: sha256, kind, state `ACCEPTED`, provenance — PNGs generated by Nano Banana (`gemini-nano-banana-2.1`) via Vertex (billed to ARISA's Vertex project, recorded in the manifests); voices by Botnoi Studio V4 from the operator;
   - **rights records:** the model-output route (MiniMax H3 Community License, private benchmark,
     territories SG/TH, operator attestation of 12 Nov); each reference subject (original fictional,
     generated); each voice (Botnoi, `OPERATOR_ATTESTED`, O-11 — glossary);
   - **the preset row:** `pika-flex-ref2va-480p-candidate`, disabled and unmeasured (FM §4);
   - **credentials (reused, registered 4 Nov):** `credref:runpod-drama-box-canary` → `/root/.secrets/drama-box/runpod-canary.key` and `credref:comfy-drama-box-canary` → `/root/.secrets/drama-box/comfy-canary.token`, both mode 0600, FILE store. `register` validates the rows and the files' mode and owner, never their content. **No one writes a new token file** (v0.1 operator step 2 removed).
2. **`author`.** Writes `plan.json`, `seal.json` and an unsigned `authorization.draft.json` that follows the **`BenchmarkAuthorization` schema, FM §2** (it binds `plan_sha256` + `sealed_sha256` and the cap fields listed there), and prints for each document **both** the canonical-JSON sha256 (the values the authorization binds, FM §2 "Hashing") and the file-byte sha256.
   - **`plan.json`:** from `shots.csv` and `trials.csv`: 8 shots and 24 seeded samples, with the screen
     samples S01-R1/S03-R1/S07-R1; frozen prompts: English direction with one-based `<Picture N>`/`<Audio N>`
     labels in the port-map order; the speaker labels; the Thai line; S05/S06 expression text frozen here:
     - S05: "A speaks softly, holding back grief; his breath catches once before the last word; no tears,
       no sobbing."
     - S06: "B speaks low and controlled with restrained anger, jaw tight, no shouting; her voice softens
       on 'แต่ฉันจะฟัง'."
     - `runtime_profile`: workflow/config hashes, preset id/version, rights refs, `boot_budget`.
   - **`seal.json`:** references and the `port_map`; the new image digest (registry manifest digest, R5c);
     the R5c prediction; the rights hash, territories, `eligible_until` and `hard_stop_utc`.
3. **`quote`.** Builds `quote.json` from the operator's console quote fields (id, GPU, price, disk, RAM,
   capture time), loaded through `load_document(AcquisitionQuote)` — the model itself enforces the ≤ 2 h
   window, the allowed GPU names (bare `"A40"` refused) and whole µUSD per GPU-second
   (`benchmark_authorization.py:306-313`). **No RunPod API price read.**
4. **`verify`.** Runs `benchmark preflight` against the authored documents and prints PASS, or the first
   refusal. A PREDICTED seal must pass (RR-T12).

### R5e — Results table (G6): `tools/t031_results.py`

Maps `benchmark export` JSON to `results-template.csv`: ids, seeds, state, output sha, timings, cost fields. The quality/coverage columns stay blank for the human Pass A/Pass B; values the pipeline does not know are exported as UNKNOWN, never as 0.

### R5f — Per-pod billing verification before the next admission (G7, R5C-7)

After every acquisition's **verified termination** — the screen acquisition, the full acquisition, and any
typed boot-failure cleanup alike — the runbook (§7) runs an executable per-pod procedure:

1. **Per-pod billing ingest** — the existing observation-recording path (`src/microdrama/rendering/runpod_billing.py:110-130`
   → `benchmark_billing_evidence`): ordinary ingest records provider observations; it does not verify invoices.
2. **Invoice/console-evidence verification using the existing verifier** — the operator captures the RunPod
   console invoice/billing evidence for the pod's period to a file; the orchestrator runs the new thin tool
   `tools/t031_billing_verify.py`, which wraps `RunpodInvoiceFinality.verify_invoice_period`
   (`src/microdrama/rendering/finality.py`; the established wrapper pattern is `pipeline/canary.py:1300-1335`
   — only the evidence file's sha256 is stored, never the file or a credential). No new verification logic,
   no migration (the `runpod_billing_budget_finalizations` path already exists).
3. **Sweep** — `benchmark sweep` after verification (§7).

**Admission rule.** Another acquisition (full after screen, or a boot retry) is admitted only with the
canonical blockers cleared. **Verified shutdown alone does not release all holds**: after termination,
pending financial finality leaves the acquisition `CLEANUP_PENDING` with STORAGE exposure
(`src/microdrama/pipeline/experimental_world.py:308-316`, `benchmark_service.py:2040`), and H-2 correctly
blocks the next admission until the procedure above completes. Postponing invoice finality until after full
would make the printed sequence unexecutable (R5C-7) — §7 orders it per acquisition.

## 4. Budget envelope (unchanged cap: $8.00 new exposure = 8,000,000 µUSD, ≤ 4 GPU-h, one A40-class GPU)

| Component | Ceiling | Note |
|---|---:|---|
| Compute | $3.44 | 4 h × $0.86/h ceiling; **includes** boot, weight download and any wasted cold start — **twice**: screen and full are two acquisitions, each with its own boot and full 42.03 GB download |
| Container disk while running | $0.06 | 100 GB (decimal) × $0.10/GB-mo × 4 h / 730 h |
| Persistent volume / stopped tail | $0.00 | none (R5a) |
| Reference/voice preparation | $0.00 | done 12 Nov; the Nano Banana calls billed ARISA's Vertex project, recorded in the manifests |
| Observation / ASR | $0.70 | unchanged proposal |
| Transfer / encoding | $0.30 | unchanged |
| Shutdown / rounding reserve | $3.50 | undifferentiated headroom; the cap itself is unchanged |
| **Total** | **$8.00** | the DB CHECK and authorization caps stay ≤ 8,000,000 µUSD |

Attempt semantics against this envelope: §10. **What this envelope does and does not promise (R5C-11):** the
caps are unchanged, but boot arithmetic alone does not establish completion of all 24 samples inside them —
six 25-minute boots would leave ~90 minutes (~84 after shutdown allowances) for 24 samples, with throughput
unproven. Three boot attempts per phase is therefore an **upper bound conditional on remaining canonical
exposure, GPU time and deadlines**, not a promise; each acquisition's runtime window is **sized against that
remainder** at quote time, because admission reserves the quote's complete runtime window plus shutdown
margin against remaining aggregate GPU time (`benchmark_service.py:627-631` — a quote for the whole
remaining cap is refused even initially). Measured screen throughput is used to **report whether the
remaining full run fits** (R5e export; checked at the §7 step-15 full admission, before the full quote is
captured); completion is never promised from boot arithmetic alone.

## 5. Acceptance tests (offline; real PostgreSQL where the path touches the DB)

| Id | Test |
|---|---|
| RR-T1 | `start.sh` with a fake `provision.py`: (a) PROVISIONED → ComfyUI exec'd; (b) PROVISION_FAILED → ComfyUI never started, ready state `PROVISION_FAILED`; (c) flag absent → no provisioning, ready state `NO_PROVISIONING` |
| RR-T2 | Gateway `/__drama/ready`: 401 without token; state transitions; body has no secret and no path outside `/opt/pika`; both gateway copies stay byte-identical (guard test green) |
| RR-T3 | Rebuilt image (flag absent) reproduces the CPU attestation receipt `1a6023e24ad38cd4ef41e1d3b1c727550a52cba9cd055be2ede8373e487a4c89` — the 6 Nov schema-smoke hash in `deployment/pika-h3-flex/BUILD_EVIDENCE.md`, equal to `schema-attestation.cpu.json` |
| RR-T4 | `PodCreateRequest.provision_models=True` maps to env `MICRODRAMA_PROVISION_MODELS=1` in the create payload **captured through the composed acquisition path** (`LeaseService._spec_for()` → `PodSpec.to_request()`); the benchmark create guard refuses POST when either the intent or the composed request lacks `True`; a Pika intent without it is refused at benchmark-side intent validation (R5C-4) |
| RR-T5 | `wait_ready`: 404/502/503/524/refused/`BOOTING`/`PROVISIONING`/`PROVISIONED` keep waiting with no provider operation and no ambiguity; `PROVISION_FAILED` → `PolicyDenied PROVISION_FAILED` + verified cleanup; deadline → `BOOT_TIMEOUT` + cleanup; ready → staging proceeds. Guard (placement (a)): a ready poll without exact acquisition/COMPUTE-hold/lease/pod linkage is refused; **pending state and missing endpoint before `acquire()` completes are waited on with exactly one create — the retry is an owned read against the same durable lease/pod, never a second create** (R5C-1); **a simulated 25-min boot under concurrent janitor sweeps stays alive (heartbeat maintained, deadline checked before every request and after every sleep, transport timeout bounded by remaining budget) and leaves no expired hold and no ambiguity** (R5C-8); **recovery of already-admitted work past the initial boot deadline (minute-40 pod, newly submitted recoverable prompt) is recovered, not classified `BOOT_TIMEOUT`** (R5C-9) |
| RR-T6 | Timings recorded in coverage (`t031_timings`) and exported; `sampler_ms` null when history lacks timestamps; `full_job_ms` stays UNKNOWN through SUBMITTED and intermediate polls (submission acknowledgement is not duration), is written at the first terminal observation with verified durable output, and survives replay; tested through submission → multiple polls → completion → delayed recovery (R5C-12) |
| RR-T7 | Placeholder prediction: enums match `models.json` names per folder; mapped hash ∉ `DENIED_LIVE_SCHEMA_SHA256`; seal with `PREDICTED_FROM_PINNED_IMAGE`/`MANIFEST_PLACEHOLDER_CAPTURE` accepted by `validate_for`; mismatched image digest, wrong enum or deny-set hash refused |
| RR-T8 | Live mismatch at ready refuses before any upload; a match records the live capture durably (`t031_live_schema`) |
| RR-T9 | `prepare_run register/author/quote/verify` against a real test DB: preflight PASS on the authored set; any semantic edit changes the printed canonical sha, any byte edit the file-byte sha; no credential value in output |
| RR-T10 | `t031_results.py` maps a synthetic export to the template header exactly |
| RR-T11 | Full offline scripted experiment (existing 24-sample fixture) still green; `make check` and `make pilot` green |
| RR-T12 | A PREDICTED seal passes `benchmark preflight` end-to-end |
| RR-T13 | Typed pre-sample boot failures (`PROVISION_FAILED`, boot-phase `TransientProviderError`, `BOOT_TIMEOUT`) are handled before generic terminal failure handling: incident + cleanup obligation persisted, `execution_outcome` and all sample/model outcomes left unset, a later `execute` with a fresh quote admissible once canonical blockers clear; attempt identity durable and the fourth attempt refused under the admission locks (R5C-2) |
| RR-T14 | Acquisition records live on the deterministic prepared-but-unclaimed sample row, keyed by acquisition ID: two boot attempts both present after the sweep's CLOSED/CLEANUP_PENDING/UNKNOWN transitions; coverage merges atomically without replacing existing keys; refusal evidence is committed before cleanup (R5C-3) |
| RR-T15 | The authored eight-shot maps through real staging/binding: office reuse (one verified byte upload bound as identity:A and outfit:A-office; B likewise) and S08's home outfit stage and bind with exact per-role/per-subject receipts and checksum readback; the key-only guard lookup is gone (lookup scoped by acquisition + key + role + subject) (R5C-5) |
| RR-T16 | Per-phase completion: after an initial `execute` that returns at the first SUBMITTED observation, the §7 bounded `resume`/`reconcile` commands drive screen to SCREEN_REVIEW with verified cleanup (before Pass A) and full to COMPUTE_COMPLETE; the loop stops on admission blockers or unresolved effects, preserving reconciliation-only handling (R5C-6) |
| RR-T17 | The per-pod billing verification procedure (§3 R5f): after verified termination, per-pod ingest + `verify_invoice_period` from the evidence sha + sweep run end-to-end; another acquisition is refused while canonical billing/storage blockers are uncleared — verified shutdown alone does not release all holds (R5C-7) |

## 6. Implementation plan (build packages)

GLM, in order; one commit each, tests first; **`make check` green per commit**. The image rebuild runs under the documented flock/CPUQuota command (`deployment/pika-h3-flex/README.md:13-16`; the `BUILD_EVIDENCE.md:39-47` variant's paths belong to the superseded t031-native worktree — adapt them). **No push**: the operator pushes the new image. Target scope:

| Package | Files created / modified (tests included) | RR tests |
|---|---|---|
| R5a — image + gateway + flag through the composed request | `deployment/pika-h3-flex/`: `start.sh` (new), `Dockerfile`, `build.sh`, both `canary_gateway.py` copies, `test_pika_image_recipe.py`, `test_canary_gateway.py` (repo test mirror); `src/microdrama/contracts/providers.py` (`provision_models`); `src/microdrama/rendering/pods.py` (`PodSpec.provision_models` → `to_request()`); `src/microdrama/rendering/leases.py` (`_spec_for()` flag transfer, R5C-4); `src/microdrama/rendering/runpod_transport.py` (env mapping); Pika intent recording + benchmark-side intent validation + benchmark create guard (intent ∧ composed request `True` before POST) | T1–T4 |
| R5b — ready gate, boot-failure handling, timings, staging bindings | `src/microdrama/pipeline/experimental_world.py` (`wait_ready` incl. pre-acquire warmup/endpoint waits, acquisition-read scope, role/subject-scoped upload verification, coverage writers); `src/microdrama/pipeline/live_world.py` (allowlist); `src/microdrama/pipeline/benchmark_service.py` (typed pre-sample boot-failure handling, admission attempt enforcement, lease-liveness/deadline plumbing on the wait path); `src/microdrama/rendering/pika_transport.py` (sampler timestamps when present); export fields | T5, T6, T13, T14, T15, T16 |
| R5c — prediction + seal evidence | `tools/t031_schema_predict.py` (new); `src/microdrama/pipeline/benchmark_authorization.py` (Literals, `validate_for`); `src/microdrama/pipeline/benchmark_service.py` (preflight gate, `:198`) — **one commit** | T7, T8, T12 |
| R5d — prepare-run tool | `tools/t031_prepare_run.py` (new); `tools/canary_db.py` only if seeding requires it | T9 |
| R5e — results tool | `tools/t031_results.py` (new) | T10 |
| R5f — per-pod billing verification | `tools/t031_billing_verify.py` (new; thin wrapper over `RunpodInvoiceFinality.verify_invoice_period` — no new verification logic, no migration) | T17 |
| all | — | T11 |

## 7. Operator runbook (complete, FM §3 order; actor, cwd, env, DB per step)

**Common environment** (no `benchmark` console script exists — FM §1): cwd `microdrama/`; `PYTHONPATH=src
.venv/bin/python -m microdrama.pipeline.benchmark <command> --experiment-id <UUID> …`; env
`MICRODRAMA_EXECUTION_MODE=PAID_BENCHMARK`, `MICRODRAMA_PAID_REQUESTS_ENABLED=true`,
`MICRODRAMA_CLOUD_RESOURCES_ENABLED=true` (`MICRODRAMA_PUBLIC_ACTIONS_ENABLED` stays off), loopback
`MICRODRAMA_DATABASE_URL`, absolute `MICRODRAMA_OBJECT_STORE_ROOT`. DB throughout: the dedicated loopback
paid DB. Order per CON-M5/M6: push → predict → author → verify → sign, wrapped around the FM §3 steps.

1. **Operator: push the new image** (commands as used 12 Nov): `gh auth token | docker login ghcr.io -u Clarenze-C --password-stdin`; `docker tag drama-pika-h3-flex:t031-native ghcr.io/clarenze-c/drama-pika-h3-flex:t031-native`; `docker push ghcr.io/clarenze-c/drama-pika-h3-flex:t031-native`; `docker logout ghcr.io`. Digest capture: `docker inspect --format '{{json .RepoDigests}}' <ref>` plus an anonymous manifest check (HTTP 200) — that manifest digest is what the seal pins.
2. **Orchestrator:** `python tools/canary_db.py up` (seeds episode, EPISODE account, preset, fixture rights route; FM §1C).
3. **Orchestrator:** `python tools/t031_prepare_run.py register`.
4. **Orchestrator:** run `tools/t031_schema_predict.py` inside the pulled registry reference (step 1 digest); the capture record stores the manifest digest.
5. **Orchestrator:** `t031_prepare_run.py author` — `plan.json` + `seal.json` (binds the capture); these precede prepare/seal because those commands ingest them.
6. **Orchestrator:** `benchmark prepare --plan plan.json`.
7. **Orchestrator:** `benchmark seal --manifest seal.json`.
8. **Operator:** capture a console quote for an A40 (secure cloud) within 2 h before `benchmark execute`;
   **Orchestrator:** `t031_prepare_run.py quote` → `quote.json`.
9. **Orchestrator:** `t031_prepare_run.py author` — `authorization.draft.json` (binds `plan_sha256` +
   `sealed_sha256`) — then `t031_prepare_run.py verify` (preflight PASS, RR-T12).
10. **Operator:** sign the authorization (the only sign-off; `authorization_sha256` is the file's byte hash).
11. **Operator:** `benchmark execute --phase screen --authorization … --authorization-sha256 … --quote …` —
    run directly by the operator, not via the orchestrator. Note: `execute` returns at the first observation
    (normally SUBMITTED) and exits successfully — **that is not phase completion** (R5C-6).
12. **Orchestrator: drive screen to terminal (R5C-6).** Bounded resume/reconciliation loop, same env/cwd
    preamble as above, stopping on admission blockers or unresolved effects: `benchmark resume
    --experiment-id <UUID> --phase screen --authorization … --authorization-sha256 … --quote …`
    (recovery-first; re-submits/observes the remaining samples; `resume` is what advances screen to
    `SCREEN_REVIEW`, `benchmark_service.py:1463`) and `benchmark reconcile --experiment-id <UUID>
    --authorization … --quote …` (resolves UNKNOWN provider effects without creating a second one).
    **Terminal check before Pass A:** all three screen samples SUCCEEDED with durable outputs, experiment
    state `SCREEN_REVIEW`, verified cleanup complete (`benchmark sweep` where owed). Reconciliation-only
    handling is preserved throughout — resume never repairs or re-runs admitted effects.
13. **Human Pass A**, then `benchmark record-screening --decision decision.json` (requires `SCREEN_REVIEW`
    + verified cleanup; FAIL → terminal).
14. **Operator + Orchestrator: per-pod billing verification for the screen acquisition (R5C-7, §3 R5f).**
    (a) per-pod billing ingest (existing observation path); (b) **Operator** captures the RunPod console
    invoice/billing evidence for the pod's period to a file; (c) **Orchestrator** runs
    `PYTHONPATH=src .venv/bin/python tools/t031_billing_verify.py --experiment-id <UUID> --pod-id <POD>
    --period-start … --period-end … --amount-micro-usd … --evidence <file>` (existing verifier; only the
    evidence sha256 is stored); (d) `benchmark sweep`. **The full-phase execute below is admissible only
    with these canonical blockers cleared — verified shutdown alone does not release all holds.**
15. **Operator:** `benchmark execute --phase full` (only after a durable PASS **and** the step-14 blockers
    cleared). Size the quote against the measured remainder (§4, R5C-11), not a flat window.
16. **Orchestrator: drive full to terminal (R5C-6).** The same bounded `resume`/`reconcile` loop as step 12
    with `--phase full`; terminal check: all 24 samples SUCCEEDED with durable outputs and experiment state
    `COMPUTE_COMPLETE` (`benchmark_service.py:1463`).
17. **Operator + Orchestrator: per-pod billing verification for the full acquisition** — the step-14
    procedure again for the full pod, followed by `benchmark sweep` (verified cleanup; releases holds;
    billing states).
18. **Orchestrator:** `benchmark export --output …` + `python tools/t031_results.py` → `results-template.csv`.
19. **Invoice finality (experiment-level).** The per-pod verifications ran in steps 14 and 17; finality for
    the whole experiment period is confirmed with the same verifier over the consolidated console evidence,
    and the operator watches `billing_state` via `benchmark status` until BILLED (finality machinery:
    `RunpodInvoiceFinality` + `benchmark_billing_evidence`, `src/microdrama/rendering/runpod_billing.py:117`).

## 8. Alternatives considered

- **R5a weight transport.** Chosen: per-run container-disk download (`start.sh` + `provision.py`).
  - RunPod network volume — rejected: billed monthly even when idle, and its region pin narrows A40
    availability.
  - Weights baked into the image — rejected: a public image would redistribute MiniMax-licensed weights,
    and a private one needs registry credentials the create request can't carry.
- **R5b gate placement.** Chosen: world step `wait_ready` under `request_guard`, **placement (a)** — no
  PROMPT reservation or sample materialization before readiness (R5C-10). Two rejections: the canary's
  in-request boot-window retry (`canary.py:1023-1054`) holds a prompt hold across the boot window
  (600 s TTL vs a 25-min boot); and placement (b) — `wait_ready` after `materialize_sample` with the
  materialized hold's expiry provably beyond the boot deadline — is **impossible, not merely worse**
  (R5C-10): claiming/materializing a sample is set-once (`benchmark_samples` links trigger,
  `migrations/0026…sql:112`) and contradicts the no-sample failure contract (§10), and `_scope()` is a
  sample-job/PROMPT-hold scope, not acquisition lease authorization.
- **R5f billing finality timing.** Chosen: per-pod verification after every acquisition's verified
  termination, before the next admission (§3 R5f; §7 steps 14 and 17). Postponing invoice finality until
  after full — rejected: the acquisition stays CLEANUP_PENDING with STORAGE exposure, H-2 correctly blocks
  full/boot admission meanwhile, and the printed sequence becomes unexecutable (R5C-7).
- **R5c seal evidence.** Chosen: P — predicted schema from the pinned image, verified live before any
  upload (§3 R5c). C — a separate capture pod (`--phase capture` acquisition) — rejected for this package:
  it needs a pre-seal authorization and new experiment states, which means a migration, outside this
  package's no-migration rule (§2). **If the Codex critique rejects P, C becomes a new spec round** with
  its own scope and migration approval — not a fallback inside R5.
- Structural note: only R5a/R5b/R5c carry architectural choices; alternatives for every sub-decision
  (poll interval, CSV mapping, quote mechanics) would be ceremony.
- Stated plainly: screen and full are two acquisitions, each with a cold start and a full 42.03 GB
  download (~25 min of the 240 GPU-min budget before any full-phase sample).

## 9. Finding map

| Finding | Resolved in |
|---|---|
| CON-B1 | §3 R5c (P single design); §8 (C rejected, new-round rule); v0.1 §8 Q1 removed |
| CON-M1 | §3 R5b guard integration; RR-T5 |
| CON-M2 | §3 R5c one-commit touch points; RR-T12 |
| CON-M3 | §3 R5b landing zone (coverage keys; state-CHECK finding + fallback) |
| CON-M4 | §3 R5d role→asset table; A2-canonical; office-outfit reuse |
| CON-M5 | §3 R5c sequence; §7 steps 1, 4, 9-10 |
| CON-M6 | §7 (complete runbook) |
| CON-M7 | §7 step 1 (inlined push + digest commands) |
| CON-M8 | §3 R5d (FM §2 schema, S05/S06 text); §6 (build command + superseded paths) |
| CON-M9 | §8 (R5a/R5b alternatives); §3 R5b + §4 (two cold starts) |
| CON-M10 | §10 (failure and retry) |
| CON-M11 | §3 R5a (start.sh owns state file; gateway never probes) |
| CON-M12 | §3 R5a (both gateway copies; build.sh; tests); §6 R5a row |
| CON-M13 | §3 R5a flag plumbing; RR-T4 |
| CON-M14 | §3 R5d credentials; §7 (token-file step removed) |
| CON-M15 | §3 R5a storage; §4 (decimal GB) |
| CON-M16 | §6 target-scope table |
| CON-F1 | §11 (risks and limits) |
| CON-F2 | §8 (document-level alternatives section) |
| CON-N1 | §3 R5b polling (404/502/503/524); RR-T5 |
| CON-N2 | §3 R5d quote (`load_document(AcquisitionQuote)`; no API cross-check) |
| CON-N3 | RR-T1(b) exact value `PROVISION_FAILED` |
| CON-N4 | §3 R5c per-folder enum membership; RR-T7 |
| CON-N5 | §3 R5a + RR-T3 (full digest + referent) |
| CON-N6 | §3 R5d author (canonical + file-byte sha256); RR-T9 |
| CON-N7 | §3 R5b `t031_timings` (completion writer moved from first observe to first terminal observation with verified durable output, R5C-12) |
| CON-N8 | §4 (two cold starts; undifferentiated reserve) |
| CON-N9 | §12 glossary (deferred-limit ids, A0-D/A1, H-2, O-11) |
| CON-N10 | §12 glossary (world … Pass B; shutdown margin value §3 R5b) |
| CON-N11 | §12 glossary (Pika H3 Flex vs MiniMax H3) |
| CON-N12 | §12 glossary (Nano Banana, Botnoi Studio V4, ARISA Vertex) |
| CON-N13 | throughout (header, title, grammar, units phrasing) |
| CON-N14 | §10 (Q2 moot — partials self-removed; Q3 folded); §3 R5a |
| CON-N15 | §7 steps 8, 11 |
| CON-N16 | §7 common environment (entry point + hard env gates) |
| CON-N17 | §6 (RR→package mapping; `make check` per commit) |
| CON-N18 | §3 R5d preamble (boundary; frozen-field drift) |
| CON-N19 | §11 (A40 pending, HF 429, disk slack, placeholder divergence) |

**Codex round 1 (v0.3):**

| Finding | Resolved in |
|---|---|
| R5C-1 | §3 R5b (boot handling before `acquire()` completes; one create, owned-read retries); §11; RR-T5 |
| R5C-2 | §3 R5b (typed pre-sample boot failures); §10; RR-T13 |
| R5C-3 | §3 R5b (acquisition-keyed records on the prepared unclaimed sample row; merge, commit before cleanup); RR-T14 |
| R5C-4 | §3 R5a (composed request construction + benchmark create guard); RR-T4 |
| R5C-5 | §3 R5d (one verified upload, distinct bindings; role/subject-scoped guard lookup); RR-T15 |
| R5C-6 | §7 steps 11-12, 15-16 (bounded resume/reconcile to SCREEN_REVIEW / COMPUTE_COMPLETE); RR-T16 |
| R5C-7 | §3 R5f; §7 steps 14, 17, 19; §10; RR-T17 |
| R5C-8 | §3 R5b (lease liveness, deadline checks, bounded transport timeouts); RR-T5 |
| R5C-9 | §3 R5b (persisted initial readiness; recovery deadlines); RR-T5 |
| R5C-10 | §3 R5b (placement (a) chosen); §8 (placement (b) rejected); RR-T5 |
| R5C-11 | §4 (no completion promise; runtime windows sized against the remainder); §10; §11 |
| R5C-12 | §3 R5b (`t031_timings` completion semantics; sampler evidence through transport); RR-T6 |

## 10. Failure and retry

- **What each failure leaves (R5C-2, R5C-3).** Typed pre-sample boot failures (`PROVISION_FAILED`,
  boot-phase `TransientProviderError`, `BOOT_TIMEOUT`) are handled before the generic terminal handler: the
  acquisition row keeps its incident state plus the durable, acquisition-keyed incident record in coverage
  (committed before cleanup, so it survives the sweep's state transitions); all holds are released by the
  normal verified cleanup; **no sample/model failure outcome is set**. All of them happen before any upload
  or prompt, so no upload ambiguity and no sample state is created.
- **Re-run.** `benchmark execute` again with a **fresh quote** (the ≤ 2 h quote window makes multi-attempt
  the norm) — admissible because `execution_outcome` stayed NULL (R5C-2), and only once the canonical
  blockers cleared (§3 R5f for financial/storage blockers). The signed authorization stays valid until its
  hard stop — no re-sign per attempt.
- **Attempt limit (R5C-11).** At most **3 boot attempts per phase** (screen, full) — an **upper bound,
  conditional on remaining canonical exposure, GPU time and deadlines**, enforced durably under the
  admission locks with phase and attempt identity recorded (R5C-2); then stop for the operator. Worst case
  ≈ 150 of the 240 GPU-min budget spent on boots — inside the cap, but it **does not promise completing the
  samples**: each acquisition's runtime window is sized against the remaining aggregate GPU time at
  admission (quote runtime + shutdown margin reserved, `benchmark_service.py:627-631`), and whether the
  remaining full run fits is **reported from measured screen throughput** (§4, §7 step 15), not promised
  from boot arithmetic.
- **Throughput assumption.** `boot_budget` 25 min assumes ≥ 35 MB/s sustained from the HF CDN for the 42.03 GB download; the actually observed throughput is recorded with the provision timings (`t031_timings`).
- **HF 429 (anonymous).** `provision.py` has no retry — the outcome is `PROVISION_FAILED`; re-run within the attempt limit. Partial downloads are already removed by `provision.py` itself (`.unverified-*` tempfile unlinked in `finally`, `deployment/pika-h3-flex/provision.py:51,67-68`).
- **No in-pod retry or resume machinery** — the container disk dies on pod termination, so machinery would be dead weight.

## 11. Risks and limits

- **A40 queueing (R5C-1):** pending hardware and image pulling are positively identified provider states,
  waited on before `acquire()` completes with owned reads against the same durable lease/pod (exactly one
  create); uncertain create outcomes keep H-2 reconciliation. The boot deadline, not the endpoint, remains
  the discriminator between a slow pod and a broken one.
- **Completion fit (R5C-11):** boot arithmetic cannot establish that all 24 samples finish inside the caps;
  the remaining-run fit is reported from measured screen throughput before full is admitted (§4, §10) and
  may come back negative — then the operator decides, not the arithmetic.
- **HF 429 throttling** (anonymous): no retry in `provision.py`; §10.
- **Disk slack:** the 100 GB (decimal) default leaves ~19–28 GB slack depending on whether container disk
  includes image layers (unresolved; the builder records the answer, §3 R5a).
- **Placeholder divergence:** a node that reads file *contents* (not names) could diverge between the
  zero-byte placeholder prediction and real weights; the live attest at readiness (RR-T8) is decisive,
  and a divergence costs one cold start refused before any prompt.

## 12. Glossary

- **world** — a scoped runtime harness over the pod (execute/recovery/cleanup worlds; built in
  `experimental_world.py`). **acquisition** — one pod generation of the experiment: intent + quote +
  holds + lease; at most one open acquisition per experiment (`migrations/0026…sql:46`).
- **hold** — a budget reservation (COMPUTE/PROMPT/STORAGE/CLEANUP) on the episode account; a PROMPT hold
  expires 600 s after creation (`runbooks/t031-benchmark.md:3-5`). **lease** — the pod's bounded rental
  window (TTL, deadline). **shutdown margin** — the safety gap kept before the deadline: 60 s in the
  benchmark config, default 300 s (`src/microdrama/rendering/leases.py:134`, FM §7).
- **prepared (unclaimed) sample row** — the deterministic `benchmark_samples` row that carries an
  acquisition's coverage records (timings, live schema, incidents) keyed by acquisition ID before any
  sample is claimed; boot failures precede claiming, so this — not "the first claimed sample" — is the
  carrier (R5C-3). **invoice/console evidence** — the operator-captured RunPod console billing evidence
  whose **sha256 only** (never the file) the existing invoice verifier stores (R5f).
- **screen / full** — the two phases: screen runs the 3 frozen samples (S01-R1, S03-R1, S07-R1); full runs
  all 24, only after a durable PASS. Their terminal states are `SCREEN_REVIEW` and `COMPUTE_COMPLETE`,
  reached by `benchmark resume` (`benchmark_service.py:1463`) — one `execute` returning SUBMITTED is not
  phase completion (R5C-6). **verified cleanup** — the cleanup world's stop/terminate/verify
  pass; releases holds and sets `cleanup_state VERIFIED`.
- **Pass A / Pass B** — the human quality gates: Pass A screens the 3 screen samples (`record-screening`);
  Pass B is the human review of the full results (the blank quality/coverage columns in
  `results-template.csv`). **upload ambiguity** — an upload whose outcome is unknown (posted but
  unverified); the INTENT→UNKNOWN→VERIFIED state machine with checksum readback exists to prevent it.
- **stopped-storage tail** — storage cost a stopped pod keeps accruing; none here
  (`persistent_volume_gb = 0`). **the canary DB's two episodes** — the seeded canary fixture episode
  (run-14 canary spend) and the new T031 benchmark episode; spend is reported, not moved (FM §7).
- **Pika H3 Flex** — the ComfyUI reference-to-video (Ref2VA) workflow this benchmark runs
  (`t031-benchmark/upstream-pika-h3-flex-ref2va.json`; `PIKA_TEMPLATE`). **MiniMax H3** — the video model
  that workflow executes; weights pinned from HF `Comfy-Org/MiniMax-H3` (`models.json`); its outputs carry
  the MiniMax H3 Community License (R5d rights route).
- **Nano Banana** — Google's image-generation model (`gemini-nano-banana-2.1`) that produced the reference
  PNGs via Vertex, billed to ARISA's Vertex project (usage recorded in the manifests). **Botnoi Studio
  V4** — the operator's Thai TTS service; the two voice WAVs are its own voices (not community),
  operator-attested. **O-11** — the rights-basis tag `voices-manifest.json` records for that attestation
  (`OPERATOR_ATTESTED (O-11)`).
- **H-2** — the accepted T031 hardening controller for budget/recovery/billing (accepted at `0cda424`).
  **HC-6/HC-9/HC-11/HB-13, R1 residual** — limitation ids from the T031 H-2 review rounds, accepted and
  deferred. **phase D** — the follow-on T031 phase owning those limits, 768p, FL2VA and repair retries.
  **A0-D / A1** — parallel Drama Box workstreams owning migrations 0027 and 0028–0031; this package adds
  none. **T031** — the Drama Box task id for the paid benchmark pipeline (this work).
