# T031 run-readiness (R5) spec: rulings on the Goldfish review (Opus, spec owner, 13 Nov 04:20Z)

Source: [r5-goldfish/consolidated_review_report.md](r5-goldfish/consolidated_review_report.md): 1 Blocker, 17 Majors, 20
Nits, 1 refuted. **Every finding is accepted** except the refuted ST1. The rulings below are binding on the v0.2 text.
Nits without a ruling are applied as the report's "Action" says.

## Blocker

- **CON-B1. Q1 is decided: P (predicted schema, live-verified before any upload).**
  - §3 R5c states P as the single design.
  - The capture-pod alternative C is moved to "Alternatives considered", with its rejection reason (pre-seal
    authorization and new experiment states mean a migration, which is outside this package's no-migration rule).
  - If the Codex critique rejects P, C becomes a **new spec round** with its own scope and migration approval, not a
    fallback inside R5.
  - §8 Q1 is removed.

## Majors

- **CON-M1. `wait_ready` stays inside the request-guard architecture; it never bypasses `request_guard`.**
  - **Requirement:**
    1. The ready poll (`GET /__drama/ready`) and the boot-window `/object_info` retries run under the acquisition's
       lease authorization (the `_scope()` used for `attest_schema`, `experimental_world.py:690-703`), with
       `/__drama/ready` added to the guard's pre-operation read allowlist beside `/object_info`.
    2. **No prompt hold may be able to expire during the boot window.** The prompt reservation TTL is 600 s
       (`runbooks/t031-benchmark.md:5`).
  - **The builder chooses one conforming placement and documents it.** Either:
    - (a) the guard accepts these two read-only paths with acquisition + lease linkage before any sample is
      materialized; or
    - (b) `wait_ready` runs after `materialize_sample` **only if** the materialized hold's expiry is provably beyond
      the boot deadline.
  - **Tests:** a ready poll without acquisition/lease linkage is refused; a simulated 25-min boot leaves no expired
    hold and no ambiguity.
- **CON-M2. All R5c touch points form one commit:**
  - the `schema_evidence` / `schema_attestation_source` Literal widening (`benchmark_authorization.py:172-175`);
  - `validate_for` (`:410-420`);
  - **`benchmark_service.preflight` (`benchmark_service.py:198`)**.

  New acceptance row: a PREDICTED seal passes `benchmark preflight` end-to-end.
- **CON-M3. The landing zone is named, with no migration.** All of these go in the **mutable
  `benchmark_samples.coverage` jsonb**, keyed `t031_timings` and `t031_live_schema` (the latter with the
  acquisition id):
  - **Per sample:** `full_job_ms` and `sampler_ms`.
  - **Per acquisition, on its first claimed sample:** `cold_start_ms`, `provision_ms` and the R5c live-capture record
    (raw JSON sha256, mapped sha256, acquisition id). The raw JSON itself goes to the object store.

  **Incidents `PROVISION_FAILED` / `BOOT_TIMEOUT`** go in `benchmark_acquisitions.state` if its CHECK already admits
  them, and otherwise in the same coverage key. The builder verifies the CHECK first.
- **CON-M4. The role → asset table is fixed** (DECISIONS "T031 benchmark inputs" picks A2/B2; A-home was edited
  from A2, so A2 is canonical):

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

  Unpicked candidates (A1, A3, B1, B3) are **not registered**. If the seal forbids one asset in two roles, the shot
  binds the identity image for both and records the reuse.
- **CON-M5. Sequence:**
  1. The operator pushes the rebuilt image.
  2. The orchestrator runs the prediction **inside the pulled registry reference**
     (`ghcr.io/clarenze-c/drama-pika-h3-flex@sha256:<manifest digest>`). The capture record stores the **manifest
     digest**; a local image ID is forbidden there.
  3. `author`, then `verify`.
  4. The operator signs.

  §7 states this order.
- **CON-M6. §7 becomes the complete runbook.** Every step in FM §3 order, each with actor, cwd, env and DB:
  1. `canary_db.py up`;
  2. `register`;
  3. `benchmark prepare`;
  4. `benchmark seal`;
  5. `quote`;
  6. `author`/`verify` (preflight);
  7. sign;
  8. `execute --phase screen`;
  9. human Pass A + `record-screening`;
  10. `execute --phase full` (only after PASS);
  11. `sweep`;
  12. export + `t031_results.py`;
  13. invoice finality.
- **CON-M7. The push commands are inlined** (as used on 12 Nov):
  `gh auth token | docker login ghcr.io -u Clarenze-C --password-stdin`; `docker tag`; `docker push`;
  `docker logout ghcr.io`. Then the digest capture: `docker inspect --format '{{json .RepoDigests}}' <ref>` and an
  anonymous manifest check (HTTP 200).
- **CON-M8. Links:**
  - the authorization draft follows the **`BenchmarkAuthorization` schema, FM §2**;
  - the build command is `deployment/pika-h3-flex/README.md:13-16`;
  - **S05/S06 expression text is frozen here:**
    - S05: "A speaks softly, holding back grief; his breath catches once before the last word; no tears, no
      sobbing."
    - S06: "B speaks low and controlled with restrained anger, jaw tight, no shouting; her voice softens on 'แต่ฉันจะฟัง'."
- **CON-M9. "Alternatives considered" for R5a and R5b:**
  - **R5a:**
    - a network volume (rejected: billed monthly even idle, and its region pin narrows A40 availability);
    - weights baked into the image (rejected: a public image would redistribute MiniMax-licensed weights, and a
      private one needs registry credentials the create request can't carry).
  - **R5b:** the canary's in-request retry (rejected: it holds a prompt hold across the boot window).
  - State plainly that screen and full are two acquisitions, each with a cold start and a full 42 GB download.
- **CON-M10. Failure and retry subsection.**
  - **What each failure leaves:** acquisition state/incident, holds released by verified cleanup.
  - **Re-run:** `execute` again with a **fresh quote** (the authorization stays valid until its hard stop).
  - **Limit:** at most **3 boot attempts per phase**; then stop for the operator.
  - **Throughput:** `boot_budget` 25 min assumes ≥ 35 MB/s sustained from the HF CDN; the actual is recorded.
  - **HF 429:** `PROVISION_FAILED` (`provision.py` has no retry); re-run.
  - No in-pod retry machinery.
- **CON-M11.**
  - `start.sh` owns the state file: it wraps `provision.py` and records state, timestamps and the stderr tail.
    `provision.py` is unchanged, and per-file byte counts are dropped.
  - **The gateway does not probe ComfyUI.** `/__drama/ready` reports only the state file.
  - "ComfyUI answering" is learned by the world's `/object_info` boot retry.
- **CON-M12.**
  - **Both** `canary_gateway.py` copies gain the identical endpoint: no state file → `{"state":"NO_PROVISIONING"}`,
    so the byte-identity guard stays green.
  - R5a's scope adds the Dockerfile `COPY start.sh`, `build.sh` staging, and updates to `test_pika_image_recipe.py`
    and `test_canary_gateway.py`.
- **CON-M13. The provisioning flag:**
  - **Field and default:** `PodCreateRequest.provision_models: bool = False`.
  - **Transport:** world-agnostic; it maps the field to env `MICRODRAMA_PROVISION_MODELS=1`.
  - **Recording:** the Pika acquisition intent records it.
  - **Refusal site:** benchmark-side intent validation refuses a Pika intent without it.
- **CON-M14. Reuse the existing credential refs** (registered 4 Nov):
  - `credref:runpod-drama-box-canary` → `/root/.secrets/drama-box/runpod-canary.key`;
  - `credref:comfy-drama-box-canary` → `/root/.secrets/drama-box/comfy-canary.token`;
  - both 0600, FILE store.

  The operator's "write a token file" step is **removed**. `register` validates the rows and the files' mode and
  owner, never their content.
- **CON-M15.** Decimal GB (10⁹ B) throughout. GiB is written explicitly where meant (the 8 GiB headroom).
- **CON-M16.** Add a target-scope table: package → files created or modified, including tests. Map RR-T1..T11 to
  packages (N17), with `make check` per commit.
- **CON-F1/N19.** A short "Risks and limits" section:
  - an A40 pending pod looks broken until `BOOT_TIMEOUT`;
  - HF 429;
  - disk slack;
  - placeholder-vs-real enum divergence for any node that reads file contents.

## Nits

- **N1:** tolerate 404/502/503/524, as the canary does.
- **N2:** the quote loads through `load_document(AcquisitionQuote)`; **drop the RunPod API price cross-check**.
- **N4:** enum equality means per-folder membership.
- **N6:** print both the canonical and the file-byte sha256.
- **N7:** build the `full_job_ms` writer at the first observe.
- **N14:** Q2 is moot (`provision.py` already removes partial temp files); Q3 is folded into M10.
- **N16:** use the real entry point `PYTHONPATH=src .venv/bin/python -m microdrama.pipeline.benchmark …` and the
  hard env gates.
- **N18:** `prepare_run` authors and registers; the benchmark CLI stays the only enforcement entry. "Drift" means a
  named frozen-field set per row type.
- **Glossary:** add a short one covering world, acquisition, hold, lease, screen/full, verified cleanup, Pass A/B,
  Pika H3 Flex vs MiniMax H3, Nano Banana, Botnoi Studio V4.
