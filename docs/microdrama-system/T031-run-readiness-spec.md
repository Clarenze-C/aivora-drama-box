# T031 run-readiness (R5): make the accepted benchmark path able to run one real Pika H3 Flex experiment

**Version 0.1, 12 Nov 2026.** Author: Opus orchestrator. **Status: DRAFT for Codex critique (round 1)**, after the
Codex week resets (13 Nov 10:30Z). Large / money path: spec → Codex critique → GLM build → Codex review →
orchestrator gate.

**Operator decisions (12 Nov, DECISIONS "T031 run-readiness"):** build this package now; any live-capture pod cost
counts **inside the $8 benchmark envelope** (total new exposure ≤ $8). Neither is the paid-run sign-off, which stays a
separate explicit approval of the concrete authorization file.

**Base:** `feat/t031-fix3` @ `104b26b` (T031 H-2 accepted at `0cda424`, plus `304ea77` build.sh fix and evidence
docs). **Facts:** [paid-run fact map](t031-benchmark/paid-run-factmap.md) (GLM swarm, spot-checked), cited `FM §n`.

## 1. Problem

The accepted H-2 controller handles budget, recovery and billing for paid pod runs. It cannot yet run a real model:

| # | Gap (FM §10) | Consequence |
|---|---|---|
| G1 | Nothing provisions the 5 pinned weight files (42,030,014,463 B) on the pod; `provision.py` is invoked by no code (FM §5) | ComfyUI boots without models; every sample fails |
| G2 | No boot/ready wait: after pod create the service goes straight to `stage_inputs` → `attest_schema` → `GET /object_info` with a 30 s request timeout (`benchmark_service.py:1195`, `pika_transport.py:139-205`, `comfy_transport.py:73-74`) | A booting/provisioning pod (gateway 502, connection refused) is misread as a failure or an upload ambiguity |
| G3 | The seal needs `schema_evidence=LIVE_PROVIDER` + `INDEPENDENT_RUNTIME_CAPTURE`, but no tool captures a live schema, and a live schema exists only on a pod with weights (FM §4, `benchmark_authorization.py:410-420`) | No valid seal can be authored before the first paid pod |
| G4 | No authoring tool for plan/seal/quote/authorization; no CLI for real asset, rights, preset and credential rows (FM §2, §6, §10.2-3) | The run can only be assembled by ad-hoc Python |
| G5 | No cold-start, provisioning, sampler or full-job timing writers (FM §5, §9) | `results-template.csv` timing columns can't be filled |
| G6 | Export → `results-template.csv` is manual (FM §9) | Error-prone result tables |

## 2. Scope and non-goals

In scope: R5a–R5e below. **Out of scope:** any change to H-2 recovery, locking, billing or resolution semantics; the
known limits HC-6, HC-9, HC-11, HB-13 and the R1 residual (they stay for phase D); 768p; FL2VA; repair retries; any
hosted Pika service. **No new migration** (A0-D owns 0027 on top of this tree; A1 has 0028–0031). If a fix truly
needs a schema change, the builder stops at a red test and reports.

## 3. Design

### R5a — Weights on the pod (G1): an image start script, gated by a create-time env flag

- New image revision: `ENTRYPOINT ["/opt/pika/start.sh"]`. `start.sh` (POSIX sh):
  1. starts the token gateway (`canary_gateway.py`, unchanged auth) immediately;
  2. if `MICRODRAMA_PROVISION_MODELS=1`, runs `python /opt/pika/provision.py --manifest /opt/pika/models.json
     --destination /opt/ComfyUI/models --download`, writing a state file `/opt/pika/state.json`
     (`PROVISIONING` → `PROVISIONED` | `PROVISION_FAILED` with the failing file and reason; byte counts; UTC start/end);
  3. only after `PROVISIONED` (or when the flag is absent: CPU smoke and tests), `exec`s ComfyUI exactly as today
     (`--listen 127.0.0.1 --port 8189 --disable-api-nodes --disable-all-custom-nodes`).
  4. On `PROVISION_FAILED` ComfyUI is **never** started; the gateway keeps serving the failed state.
- The gateway gains **one** token-checked, read-only endpoint `GET /__drama/ready` returning
  `{"state": BOOTING|PROVISIONING|PROVISIONED|PROVISION_FAILED|READY, "provision": {...}, "comfy_up": bool}`;
  `READY` = provisioned and ComfyUI answering on 127.0.0.1:8189. No secrets or paths outside `/opt/pika` in the body.
  Every other path keeps today's behaviour (401 without token, 502 while ComfyUI boots).
- `runpod_transport.create_pod` adds `MICRODRAMA_PROVISION_MODELS=1` to the existing `env` payload (beside
  `MICRODRAMA_COMFY_TOKEN`), only for the Pika benchmark world. The flag value is part of the attested create
  intent, so a create without it is refused for this world.
- **Storage:** weights live on the **container disk** (`/opt/ComfyUI/models`); `persistent_volume_gb = 0`, so there is
  no stopped-storage tail. Required container disk ≥ image + 42.03 GB + largest file + 8 GiB headroom
  (`provision.py` free-space rule); **default 100 GB**, exact figure set in the quote/authorization. The builder
  verifies from RunPod docs whether container disk includes the image layers and records the answer.
- Hugging Face access is anonymous over HTTPS at the pinned revision (FM §5): no credential.
- The rebuilt image keeps the CPU schema smoke path (flag absent) and must reproduce the 6 Nov CPU attestation
  hash `1a6023e2…` (the gateway and start script don't change node schemas). Rebuild and the operator's re-push give a
  **new image digest**; the seal pins it.

### R5b — Ready gate (G2) and timings (G5)

- New world step `wait_ready(acquisition)`, called after pod create/bind and **before** the first `stage_inputs` of every
  acquisition (screen and full; recovery worlds use it before any read that needs ComfyUI).
  - It polls `GET /__drama/ready` (token-auth) every 10 s.
  - Connection refused, 502/503 and `BOOTING`/`PROVISIONING`/`PROVISIONED` mean "keep waiting". They are
    **never** upload or submit ambiguity, and they create no provider operation.
  - `PROVISION_FAILED` refuses the acquisition (`PolicyDenied PROVISION_FAILED`, durable incident) and proceeds to the
    normal verified cleanup.
  - The **boot deadline** is `min(created_at + boot_budget, lease deadline − shutdown margin)`, with
    `boot_budget` = 25 min by default, set in the plan's `runtime_profile`. On timeout: incident `BOOT_TIMEOUT`,
    no uploads, normal verified cleanup.
- All waiting is GPU time on the experiment's holds (already metered by the lease), so the $8 and 4 GPU-h caps cover it.
- **Timings** are recorded durably in **existing JSON columns only** (the builder names them; if none fit without a
  migration, stop and report):
  - per acquisition: `cold_start_ms` (create request → `READY`) and `provision_ms` with bytes from the ready body;
  - per sample: `full_job_ms` (prompt submit → checksummed durable output, already observed in `observe`) and
    `sampler_ms` from ComfyUI `/history` execution timestamps when present, else `null` (reported UNKNOWN, never 0).
- `export` includes these fields.

### R5c — The seal's schema (G3): a predicted schema, verified live before any upload

**Recommended (P).**

- **Prediction tool.** New tool `tools/t031_schema_predict.py` runs `schema_smoke.py` inside the **pinned image** with
  `--network none`. Five **zero-byte placeholder files**, named exactly as in `models.json`, are bind-mounted
  read-only into the ComfyUI model folders, so the model-name enums match a provisioned pod.
  - It writes `raw_object_info`, the mapped hash and a capture record: image digest, placeholder names, tool
    version, UTC.
  - The builder proves offline that the placeholders populate exactly the enums real files would. Where ComfyUI
    lists files by name and extension, a zero-byte file is enough.
- **Seal evidence.**
  - New `schema_evidence` value `PREDICTED_FROM_PINNED_IMAGE`.
  - New `schema_attestation_source` value `MANIFEST_PLACEHOLDER_CAPTURE`.
  - `BenchmarkAuthorization.validate_for` accepts that pair **only** with all three of:
    1. the mapped hash not in `DENIED_LIVE_SCHEMA_SHA256`;
    2. the seal's `image_ref` digest equal to the capture record's;
    3. the model-name enums in `raw_object_info` equal to the `models.json` file names.
  - `LIVE_PROVIDER` + `INDEPENDENT_RUNTIME_CAPTURE` stays accepted as today. `SELF_ASSERTED` stays refused.
- **Live verification is unchanged and decisive.** At `READY`, the first `attest_schema` of each acquisition
  compares the pod's real mapped schema with the sealed hash before any upload (`experimental_world.py:705-717`)
  and refuses on mismatch.
  - R5c adds **durable recording of that live capture**: raw JSON hash, mapped hash and acquisition id. After the
    first acquisition the experiment holds a genuine runtime capture for the record.
- **Why P over a separate capture pod (C).**
  - P's worst case (prediction wrong) costs one cold start, refused before any prompt. That is exactly C's normal
    cost.
  - C also needs a pre-seal authorization and new experiment states, which likely means a migration.
  - **C is the fallback** if Codex rejects P: a `--phase capture` acquisition, capped inside the $8 at ≤ $1.00 and
    ≤ 45 GPU-min.

### R5d — Run assembly tool (G4): `tools/t031_prepare_run.py`

Offline, against the dedicated loopback paid DB (`tools/canary_db.py`). Every subcommand is idempotent and refuses on
any drift, and none prints a credential value.

1. **`register`.** Creates or validates real rows, never `FAKE_SYNTHETIC` (the builder lists the provenance and
   rights-basis enums that exist):
   - **episode and account:** a dedicated T031 benchmark episode on its EPISODE account ($10 cap). Prior canary
     spend on the canary DB's own episode is reported, not moved (FM §7);
   - **assets:** the 6 PNGs and 2 WAVs from `references-r1/r2-manifest.jsonl` and `voices-manifest.json`, each with
     sha256, kind, state `ACCEPTED` and provenance (generated by Nano Banana via Vertex; Botnoi Studio V4 by the
     operator);
   - **rights records:**
     - the model-output route: MiniMax H3 Community License, private benchmark, territories SG/TH, operator
       attestation of 12 Nov;
     - each reference subject: original fictional, generated;
     - each voice: Botnoi, `OPERATOR_ATTESTED`, O-11;
   - **the preset row:** `pika-flex-ref2va-480p-candidate`, disabled and unmeasured (FM §4);
   - **`credref:` rows (FILE store):** the existing RunPod key file, and a Comfy gateway token file the operator
     writes with `read -rs` into a 0600 file.
2. **`author`.** Writes `plan.json`, `seal.json` and an unsigned `authorization.draft.json` (§4), and prints their
   sha256s (`plan_sha256`, `sealed_sha256`).
   - **`plan.json`:**
     - from `shots.csv` and `trials.csv`: 8 shots and 24 seeded samples, with the screen samples
       S01-R1/S03-R1/S07-R1;
     - frozen prompts: English direction with one-based `<Picture N>`/`<Audio N>` labels in the port-map order;
       the speaker labels; the Thai line;
     - S05/S06 expression text per DECISIONS "D2 revised again";
     - `runtime_profile`: workflow/config hashes, preset id/version, rights refs, `boot_budget`.
   - **`seal.json`:**
     - references and the `port_map`;
     - the new image digest;
     - the R5c prediction;
     - the rights hash, territories, `eligible_until` and `hard_stop_utc`.
3. **`quote`.** Builds `quote.json` from the operator's console quote fields (id, GPU, price, disk, RAM, capture time).
   - It enforces the ≤ 2 h window and whole µUSD per GPU-second, and refuses bare `A40` (FM §2).
   - A RunPod API price read is allowed only as a read-only cross-check, never instead of the operator's quote.
4. **`verify`.** Runs `benchmark preflight` against the authored documents and prints PASS, or the first refusal.

### R5e — Results table (G6): `tools/t031_results.py`

Maps `benchmark export` JSON to `results-template.csv`: ids, seeds, state, output sha, timings, cost fields. The
quality/coverage columns stay blank for the human Pass A/Pass B; UNKNOWN stays UNKNOWN.

## 4. Budget envelope (unchanged cap: $8.00 new exposure, ≤ 4 GPU-h, one A40-class GPU)

| Component | Ceiling | Note |
|---|---:|---|
| Compute | $3.44 | 4 h × $0.86/h ceiling; **includes** boot, weight download and any wasted cold start |
| Container disk while running | $0.06 | 100 GB × $0.10/GB-mo × 4 h / 730 h |
| Persistent volume / stopped tail | $0.00 | none (R5a) |
| Reference/voice preparation | $0.00 | done 12 Nov; the Nano Banana calls billed ARISA's Vertex project, recorded in the manifests |
| Observation / ASR | $0.70 | unchanged proposal |
| Transfer / encoding | $0.30 | unchanged |
| Shutdown / rounding reserve | $3.50 | headroom; the cap itself is unchanged |
| **Total** | **$8.00** | the DB CHECK and authorization caps stay ≤ 8,000,000 µUSD |

## 5. Acceptance tests (offline; real PostgreSQL where the path touches the DB)

| Id | Test |
|---|---|
| RR-T1 | `start.sh` with a fake `provision.py`: (a) PROVISIONED → ComfyUI exec'd; (b) PROVISION_FAILED → ComfyUI never started, ready state FAILED; (c) flag absent → no provisioning |
| RR-T2 | Gateway `/__drama/ready`: 401 without token; state transitions; body has no secret/path outside `/opt/pika` |
| RR-T3 | Rebuilt image (flag absent) reproduces the CPU attestation hash `1a6023e2…` byte-identically |
| RR-T4 | `create_pod` payload carries `MICRODRAMA_PROVISION_MODELS=1` for the Pika world and is refused without it |
| RR-T5 | `wait_ready`: 502/refused/PROVISIONING keep waiting with no provider operation and no ambiguity; FAILED → PROVISION_FAILED incident + verified cleanup; deadline → BOOT_TIMEOUT + cleanup; READY → staging proceeds |
| RR-T6 | Timings recorded and exported; `sampler_ms` null when history lacks timestamps |
| RR-T7 | Placeholder prediction: enums equal `models.json` names; mapped hash ∉ deny set; seal with PREDICTED/MANIFEST accepted by `validate_for`; mismatched image digest, wrong enum or deny-set hash refused |
| RR-T8 | Live mismatch at READY refuses before any upload; a match records the live capture durably |
| RR-T9 | `prepare_run register/author/quote/verify` against a real test DB: preflight PASS on the authored set; any edited byte changes the printed sha; no credential value in output |
| RR-T10 | `t031_results.py` maps a synthetic export to the template header exactly |
| RR-T11 | Full offline scripted experiment (existing 24-sample fixture) still green; `make check` and `make pilot` green |

## 6. Build packages (GLM, in order; one commit each, tests first)

R5a (image + gateway + transport env) → R5b (ready gate + timings) → R5c (prediction tool + seal evidence) →
R5d (prepare-run tool) → R5e (results). The image rebuild runs under the documented flock/CPUQuota command. **No
push**: the operator pushes the new image.

## 7. Operator steps after the build is accepted

1. Push the new image (same two commands; new digest).
2. Write the Comfy gateway token file with `read -rs` (0600).
3. Capture a console quote for an A40 (secure cloud) within 2 h of execute.
4. Sign the authorization.
5. Run `benchmark execute --phase screen` from your own shell.

The orchestrator prepares every file and the exact commands.

## 8. Open questions for the critique

1. Is P (predicted schema, live-verified before upload) an acceptable relaxation of `INDEPENDENT_RUNTIME_CAPTURE`,
   given that runtime re-attestation is unchanged? If not, C.
2. Should `start.sh` delete partial downloads on failure? Recommendation: no. `provision.py` already promotes only
   verified files, and the container disk is discarded at terminate.
3. Is `boot_budget` = 25 min right? The download is about 42 GB from the HF CDN; observed RunPod throughput is
   unknown. Recommendation: 25 min, recorded with the actual.
