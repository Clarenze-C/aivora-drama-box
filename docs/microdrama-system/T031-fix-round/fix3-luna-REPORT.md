# T031 fix round 3 — Luna continuation report

**Branch:** `feat/t031-fix3`  
**Environment:** offline flags set; no provider, network, Docker, pod, or public action used.  
**Commit status:** changes remain uncommitted. Git writes are blocked because this worktree's shared metadata is outside the writable sandbox (`.git/worktrees/t031-fix3-worktree/index.lock: Read-only file system`). The required style-only commit was blocked for the same reason.  
**Red/green status:** focused green probes are recorded below. Red baseline runs were not captured for the carried implementation; do not treat this as satisfying the brief's red-then-green evidence requirement.

## H-3 — preflight uses factory policy

- **Root cause:** preflight checked authorization identity and seal labels, while the default factory also checked current preset, model rights, and reference rights.
- **Files:** `src/microdrama/pipeline/benchmark_service.py`; `tests/unit/pipeline/test_benchmark_authorization.py`; `tests/unit/pipeline/test_benchmark_world_composition.py`.
- **Green:** `test_preflight_is_not_ready_when_factory_policy_refuses` — `1 passed`.
- **Integration probe:** `tests/unit/pipeline/test_benchmark_world_composition.py` — `1 passed, 2 errors`; its PostgreSQL fixture could not create a socket (`PermissionError: Operation not permitted`). Exact retry for the orchestrator: `cd microdrama && .venv/bin/pytest tests/unit/pipeline/test_benchmark_world_composition.py --basetemp=/tmp/t031-fix3-basetemp -q`.
- **Conservative choice:** preflight catches current-policy failures and reports generic NOT_READY, preserving the existing diagnostic redaction boundary.
- **Commit:** none; blocked by read-only shared Git metadata.

## H-4 — raw billing evidence writer

- **Root cause:** the append-only §G repository writer existed, but Runpod billing normalization never called it.
- **Files:** `src/microdrama/rendering/runpod_billing.py`; `tests/unit/rendering/test_runpod_transport.py`.
- **Green:** `test_benchmark_raw_billing_writer_receives_original_amount_strings` — `1 passed`; confirms exact amount strings reach the evidence writer.
- **Red:** not captured before implementation. The full database-backed billing ingestion probe was not run in this sandbox.
- **Conservative choice:** records without a durable benchmark acquisition are ignored by the benchmark supplement; benchmark-owned records missing raw strings fail closed. Evidence does not replace canonical billing authority.
- **Commit:** none; blocked by read-only shared Git metadata.

## H-5 — shot-scoped port maps

- **Root cause:** migration 0026 prohibited repeated destinations across shots, and staging/binding treated all shots' ports as one map.
- **Files:** `migrations/0026_t031_benchmark_experiments.sql`; `src/microdrama/pipeline/experimental_world.py`; `tests/unit/pipeline/test_benchmark_authorization.py`.
- **Green:** `test_shot_scoped_costume_ports_reuse_the_same_destination_per_shot` passed as part of the focused authorization suite (`46 passed`). It covers valid sealed S01–S08 maps with the S08 outfit change.
- **Red/integration:** no red baseline or database-backed stage/bind execution captured. The DB composition probe is blocked as listed under H-3. Orchestrator probe: `cd microdrama && .venv/bin/pytest tests/unit/pipeline/test_benchmark_world_composition.py --basetemp=/tmp/t031-fix3-basetemp -q`.
- **Conservative choice:** exact sealed shot scope selects the prompt's assets; uploaded bytes remain acquisition-scoped, and each prompt binds only the immutable port entries for its shot. Guard triggers remain unchanged.
- **Commit:** none; blocked by read-only shared Git metadata.

## H-6 — machine-deny CPU/no-weights and label-only evidence

- **Root cause:** a self-consistent seal could relabel the known CPU/no-weights schema hash as LIVE_PROVIDER; the prior model also treated the evidence label alone as sufficient.
- **Files:** `src/microdrama/pipeline/benchmark_authorization.py`; `tests/unit/pipeline/test_benchmark_authorization.py`.
- **Green:** CPU hash denial and self-asserted-label refusal both passed in the focused authorization suite (`46 passed`).
- **Red:** not captured before implementation.
- **Conservative choice:** authorization requires an `INDEPENDENT_RUNTIME_CAPTURE` evidence source plus a schema hash outside the pinned CPU/no-weights deny set. This is an input provenance assertion; live world composition still performs runtime schema re-attestation before generation.
- **Commit:** none; blocked by read-only shared Git metadata.

## H-7 — cleanup hold acquisition link

- **Root cause:** a stop hold without an explicit acquisition used the first acquisition ordered by UUID, which can differ from the stopped lease's owner.
- **Files:** `src/microdrama/rendering/benchmark_experiments.py`.
- **Green:** `make lint` and `make contracts-check` passed; no dedicated database-backed attribution test was run because PostgreSQL socket creation is denied in this sandbox.
- **Red:** not captured before implementation.
- **Conservative choice:** only `pod.stop` cleanup reservations resolve the exact acquisition through the lease UUID embedded in the canonical stop semantic key; other cleanup retains existing fallback behavior.
- **Commit:** none; blocked by read-only shared Git metadata.

## H-8 — remove duplicate policy

- **Root cause:** `rendering.experimental_presets.ExperimentalPresetPolicy` was a dead, weaker implementation separate from the factory's policy.
- **Files:** `src/microdrama/rendering/experimental_presets.py`; `tests/unit/rendering/test_pika_h3_flex.py`.
- **Green:** the Pika workflow unit file passed within the focused run (`46 passed` total across the three focused paths); the dead implementation and its test were removed.
- **Red:** not captured before implementation.
- **Conservative choice:** the old module remains as a stub with no duplicate API; `pipeline.experimental_world.ExperimentalPresetPolicy` is the sole implementation.
- **Commit:** none; blocked by read-only shared Git metadata.

## H-9 — prompt-hold resume window

- **Root cause:** the 600-second default hold window and terminal FAILED result after janitor expiry were undocumented for operators.
- **Files:** `runbooks/t031-benchmark.md`.
- **Verification:** documentation-only; no test applies.
- **Conservative choice:** resume still reconciles history/queue and never resubmits. Expiry remains terminal for execution, while reconciliation, cleanup, and billing continue.
- **Commit:** none; blocked by read-only shared Git metadata.

## Shared gates and probes

- `make lint` — passed: Ruff checks passed; 595 files formatted.
- `make contracts-check` — passed: contracts 2.16.0, 104 schemas, 74 valid and 135 invalid examples.
- Focused command `pytest tests/unit/pipeline/test_benchmark_authorization.py tests/unit/rendering/test_pika_h3_flex.py tests/unit/rendering/test_runpod_transport.py::test_benchmark_raw_billing_writer_receives_original_amount_strings --basetemp=/tmp/t031-fix3-basetemp -q` — `46 passed`.
- Focused composition command listed under H-3 — `1 passed, 2 errors` due sandbox socket denial.
- `git diff --check` — passed.
- No full `make check` or `make pilot` run.
