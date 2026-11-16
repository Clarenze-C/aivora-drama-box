# T031 fix round 2 — Codex canary-night findings CN-1..CN-6 (GLM build)

Orchestrator: Opus session, 9 Nov 2026. Size: Medium (money path). You are the builder.

## Where

- Worktree (your cwd): `/root/AIVORA/drama-box/.scratch/t031-native-worktree`, branch
  `feat/t031-pika-flex-native`. Fix round 1 commits are already on it. Commit on top;
  never amend, rebase or rewrite earlier commits.
- Findings: `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/codex-review-canary-night.md`
- Rulings (binding): `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/rulings-canary-night.md`
- Read both first. Line numbers in the review refer to `0851374`, which this branch is
  based on.

## Fix each finding tests-first (red, then green)

Write the failing test, run it red, then fix. Report evidence per ID.

- **CN-1 billing conversion** (`rendering/runpod_transport.py` `_amount_micro`,
  `_billing_record`; `rendering/runpod_billing.py` dispute mapping).
  1. Run the component-vs-total consistency check on the exact provider Decimals, before
     any rounding. Only a real provider mismatch may produce DISPUTED.
  2. Convert to integer µUSD conservatively: the total rounds UP (ceiling).
  3. Normalise the components to sum exactly to the rounded total, using a documented,
     deterministic residual rule (e.g. largest remainder, ties to GPU).
  4. Tests:
     - many fractional buckets accumulate without under-recording;
     - GPU 0.6 + disk 0.6 = total 1.2 is NOT disputed;
     - a real mismatch IS disputed;
     - the run-14 observed value `0.03517432510852814` converts per the new rule. Update
       its expected value, with a comment citing CN-1.

  Do not rewrite any historical run-14 evidence, receipts or the pending-billing
  completion JSON.
- **CN-2 duplicate pod create** (`rendering/leases.py` `ensure_pod`,
  `rendering/pods.py` `acquire_or_reconcile`, `rendering/runpod_transport.py`
  `create_pod`).
  1. Once a create request is durably recorded for a lease, every later acquisition
     attempt is reconciliation-only. It never POSTs again, and a list miss becomes
     `NeedsReconciliation`, never a create.
  2. Persist the pod id from a successful POST response before any secondary
     verification GET can fail. Keep the ownership/name/GPU/image checks, but run them
     after the id is durable.
  3. Composed test: POST succeeds → verification GET 502 → list misses the pod → retry.
     Assert exactly ONE POST, the pod id bound on the lease, and that cleanup can find
     and stop it.
- **CN-3 redaction** (`rendering/runpod_transport.py`, `rendering/comfy_transport.py`,
  and the harness's own transports and diagnostics: `rendering/pika_transport.py`,
  `rendering/diagnostics.py`, plus any other place an upstream body or exception text
  reaches an exception, a persisted record or stderr).
  1. Bound the body READ, not just the slice.
  2. Redact resolved credential values (API key, Comfy bearer token) and secret-shaped
     content before constructing the message: `Authorization`/`Bearer` values, `api_key`
     and `token` fields, URL userinfo, and signed-URL query parameters.
  3. Uncertainty causes carry the exception type plus a sanitised category, not raw
     text.
  4. Tests use synthetic secrets only (never real keys) and assert each one is absent
     from the exception, the persisted run record and the captured stderr.
- **CN-4 storage ownership with early binding** (`rendering/leases.py`). Open storage
  ownership when the pod id is durably bound (it is idempotent per provider, pod and
  creating lease). Heal missing ownership before shutdown and accounting. Test: verify
  fails until the deadline → termination → billing ingest attributes disk to the lease,
  not the recovery pool, and readiness does not become `RECOVERY_REQUIRED`.
- **CN-5 public unauthenticated ComfyUI** (`deployment/canary-image/` and
  `deployment/pika-h3-flex/`, plus the client side if needed). Put a token-checking
  gateway in front of ComfyUI inside the image: ComfyUI listens on `127.0.0.1` only, and
  the gateway on the exposed port refuses any request without the run's bearer token.
  The token arrives via a pod env var set at create time, so no secret goes into the
  image. Add offline tests: the gateway rejects missing or wrong tokens (401) on every
  route, including `/prompt`, `/upload/*`, `/view` and websockets; the client sends the
  token; the pod create request sets the env var from the credential ref (never logged).
  **Do not build or push images.** Dockerfile and source changes plus offline tests only.
  If this cannot be done without a docker build, stop at a red test and say so in the
  report.
- **CN-6 deadline overshoot** (`pipeline/canary.py` retry loops, and any equivalent
  loop in the benchmark controller `pipeline/benchmark*.py` / `experimental_world.py`).
  Check the deadline immediately before every provider attempt, including right after
  sleeping, and bound each request timeout by the time remaining. Fake-clock tests
  assert no request starts after expiry.

## Hard limits (same as round 1)

- Offline only. Export `MICRODRAMA_EXECUTION_MODE=OFFLINE_MOCK
  MICRODRAMA_PAID_REQUESTS_ENABLED=false MICRODRAMA_CLOUD_RESOURCES_ENABLED=false
  MICRODRAMA_PUBLIC_ACTIONS_ENABLED=false`. No provider/network calls, no docker
  build or push, no pod creation, no service restarts, no clearing of shared data. No
  pushes.
- Do not touch migrations 0001–0025 or `microdrama/contracts/` (guardian-owned,
  package 2.16.0). If a fix truly needs a schema change, stop and report it; do not add
  migrations.
- Run every pytest under `systemd-run --scope -p CPUQuota=45% --quiet` with
  `--basetemp=/tmp/t031-fix2-basetemp`. Each command must finish within 10 minutes; run
  focused files.
- Never print env vars, `.env` files, keys, tokens or auth headers.
- Do not use deletion commands in shell (`rm`, `git rm`, `git clean`, `git reset`,
  `find -delete`). Overwrite instead.
- Do NOT run the full `make check` or `make pilot`. The orchestrator runs the full gate.

## Done when

1. Every CN-ID has a red→green test. The focused unit, contract and integration files
   for the touched modules pass. `make lint` and `make contracts-check` pass.
2. Fixes are committed, one or more commits per CN-ID, with messages citing the ID. The
   tree is clean except for the pre-existing untracked `.scratch/` and
   `microdrama/.venv`.
3. Report at
   `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/fix2-REPORT.md`. Per ID
   it covers: root cause, files, red/green pytest summary lines, commit hashes,
   anything unresolved.

Your final message: a 6-line summary, plus the report path.
