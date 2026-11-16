# T031 fix round 2 — CN-1..CN-6 build report

Builder: GLM session on `feat/t031-pika-flex-native` (worktree
`.scratch/t031-native-worktree`), 9–10 Nov 2026. Brief: fix2-brief.md; findings:
codex-review-canary-night.md; rulings: rulings-canary-night.md (binding).

Base: `2ceb341` (fix round 1). Fix commits on top:

| ID | Commit | One line |
|----|--------|----------|
| CN-1 | `9197c52` | billing totals convert with CEILING; components sum exactly to the total |
| CN-2 | `ce3ff4e` | one create per lease; pod id durable before any verification GET can fail |
| CN-3 | `d372e03` | URL credentials redacted; uncertainty causes are type + sanitised category |
| CN-4 | `881aab6` | storage ownership opens with the durable pod binding; healed before shutdown |
| CN-5 | `eed977b` | token-checking gateway fronts ComfyUI inside both images |
| CN-6 | `5d0ffa9` | deadline checked before every attempt; request timeouts bounded by remainder |
| style | `d971435` | ruff fix/format over the round's files |

All work offline (`OFFLINE_MOCK`, paid/cloud/public disabled), under
`systemd-run -p CPUQuota=45%`, `--basetemp=/tmp/t031-fix2-basetemp`. No pushes,
no docker builds, no migrations, `microdrama/contracts/` untouched
(`make contracts-check`: `contracts 2.16.0: 104 schemas, 74 valid and 135
invalid examples; OK`). `make check`/`make pilot` NOT run — orchestrator's gate.

---

## CN-1 — BLOCKING — billing conversion (commit `9197c52`)

**Root cause.** `_amount_micro` rounded HALF-UP: every fractional micro-USD
below 0.5 rounded DOWN (`0.0000014` USD → 1 µUSD instead of 1.4), and the
shortfall accumulated across a run with no retained remainder. Round 1 had
already moved the component-vs-total consistency check onto the exact provider
Decimals and added largest-remainder normalisation; the ceiling for the total
and the CN-1 test obligations were missing.

**Files.** `rendering/runpod_transport.py` (`_amount_micro` → ROUND_CEILING;
`_BILLING_POLICY` → `decimal-total-ceiling-largest-remainder-gpu-cpu-disk-v2`);
`tests/unit/rendering/test_runpod_transport.py`; `tests/unit/rendering/
test_t045_billing_ingestion.py`.

**Fix.** Total converts with ceiling (house rule: never under-record);
consistent components are floored and topped up to the ceiling total by largest
fractional remainder, ties GPU > CPU > disk. The run-14 observed gpuAmount
`0.03517432510852814` now converts to 35_175 (test cites CN-1). Historical
run-14 evidence, receipts and the pending-billing completion JSON untouched.

**Red:** `6 failed, 15 passed` (`-k billing`: round-up atom test, 24-bucket
accumulation, 4 conservation cases). **Green:** `51 passed`
(test_runpod_transport.py), `27 passed` (test_t045_billing_ingestion.py —
includes new "GPU 0.6 µUSD + disk 0.6 µUSD / total 1.2 is NOT disputed" at
mapper level: `ALLOCATED_PROVIDER_REPORTED`, readiness not DISPUTED; real
Decimal mismatch still DISPUTED). Consumers re-run:
`tests/unit/budget/test_billing_reconciliation.py` +
`tests/integration/pipeline/test_t045_canary_composed.py` +
`test_benchmark_experiments.py`: `55 passed`.

## CN-2 — BLOCKING — duplicate pod create (commit `ce3ff4e`)

**Root cause.** After a successful create POST, `create_pod` ran the
`_verify_existing_match` GET; a 502 raised `TransientProviderError` before the
caller could `_record_pod_id`. The canary retry re-entered acquisition, the
ownership list lagged, and `acquire_or_reconcile` POSTed again — two paid pods
under one reservation.

**Files.** `rendering/runpod_transport.py` (constructor-injected
`created_pod_recorder`, called the moment a POST is accepted — before the
verify GET and before the one-match reconciliation path verifies);
`rendering/leases.py` (`durable_created_pod_recorder` binds by client token —
idempotent, refuses a different pod, also commits the create-request proof;
`_record_create_request` returns `(requested_at, first_request)` atomically;
`ensure_pod` gate: once the proof exists, acquisition is reconciliation-only
and a list miss raises `NeedsReconciliation`, never a create);
`rendering/pods.py` unchanged (the gate lives where the lease is known);
`testing/fakes/pods.py` (`CREATE_VERIFY_502` scenario, recorder + `list_lag`
knobs); `pipeline/live_world.py` + `pipeline/experimental_world.py` (wiring);
`tests/unit/rendering/rendering_support.py`; `tests/unit/rendering/
test_lease_lifecycle.py`.

**Red:** `2 failed` (composed test: no `CREATE_VERIFY_502`; gate test:
`DID NOT RAISE NeedsReconciliation` — the retry silently re-created).
**Green:** `14 passed` (lifecycle, including the composed test: POST 200 →
verify 502 → list miss → retry → exactly ONE create, pod id bound, shutdown
finds and stops the pod). Wider: `tests/unit/rendering` `350 passed`;
composed canary + `test_at04_crash_recovery.py` +
`test_benchmark_authorization.py` `60 passed`.

**Behaviour change (per the binding ruling):** `test_unavailable_gpu_is_
transient_and_leaves_the_claim_releasable` now documents the reconcile-only
retry — a recorded create is never re-POSTed by the worker; capacity returning
is the janitor's reconciliation and a fresh claim. The claim stays releasable.

## CN-3 — BLOCKING — redaction (commit `d372e03`)

**Root cause.** Round 1 bounded body reads and redacted header-shaped secrets,
but URL userinfo and signed-URL query parameters passed through untouched, and
both transports interpolated sanitized-but-RAW exception text into uncertainty
messages — which the canary copies into the persisted run record and stderr.

**Files.** `rendering/diagnostics.py` (`_URL_USERINFO`, `_SIGNED_QUERY`
redaction before any message is built; new `uncertainty_cause(exc)` — exception
type + sanitised category: timeout / connection-reset / connection-refused /
connection-failed / dns-resolution / socket-error / transport-error — never raw
text); `rendering/runpod_transport.py` + `rendering/comfy_transport.py`
(URLError paths use `uncertainty_cause`); new
`tests/unit/rendering/test_diagnostics.py`; `test_runpod_transport.py`,
`test_comfy_transport.py` (old-contract assertions updated: uncertainty
messages now carry type/category only); `test_t045_canary_composed.py`
(end-to-end). `pika_transport.py` inherits Comfy's sanitized transport and
interpolates no raw text (checked; no change needed).

**Red:** collection `ImportError: cannot import name 'uncertainty_cause'` +
stale-contract failures while migrating. **Green:** `80 passed`
(diagnostics + comfy + runpod), pika `28 passed`, and the composed e2e
`1 passed`: a 401 body echoing bearer/api_key/token/URL userinfo/signed URL
through the REAL `UrllibTransport` sanitization — every synthetic secret absent
from the exception, its traceback, the persisted record JSON and captured
stderr, while `401`/`unauthorized` survive.

## CN-4 — SHOULD-FIX — storage ownership with early binding (commit `881aab6`)

**Root cause.** Storage ownership opened only at `_activate`. A pod bound while
its lease was still CLAIMED, whose endpoint verification failed until the
deadline, never activated: no ownership row, the verified terminate closed
nothing, later positive disk charges fell to the recovery pool and readiness
became `RECOVERY_REQUIRED` — manual accounting recovery for a normal failed
startup.

**Files.** `rendering/leases.py` (`ensure_pod` opens/heals ownership in the
bound-pod branch BEFORE verify, and in the create branch right after
`_record_pod_id`; `shutdown` heals a missing row in the bound-pod path before
`begin_shutdown`/stop/terminate/accounting — idempotent per
(provider, pod, creating lease)); `tests/unit/rendering/
test_t045_storage_ownership.py`; `tests/integration/pipeline/
test_t045_canary_composed.py`.

**Red:** composed `AssertionError: storage ownership must exist for an
early-bound pod` (`1 failed`). **Green:** composed `1 passed` — no exposed 8188
port → verification fails to the deadline → termination → ownership closed at
the verified terminate → billing ingest attributes DISK to the lease's episode
(no RECOVERY allocation) and readiness is NOT `RECOVERY_REQUIRED`; unit guard
(ownership exists while still CLAIMED, closes at terminate) green:
`30 passed` (ownership + lifecycle + finality-port).

## CN-5 — SHOULD-FIX — public unauthenticated ComfyUI (commit `eed977b`)

**Root cause.** Both images started ComfyUI on `0.0.0.0:8188` with no
server-side authentication; anyone who learned `https://<pod>-8188.proxy.
runpod.net` could submit graphs, bypassing the runner's reservation/prompt/
attempt checks.

**Files.** New `deployment/canary-image/canary_gateway.py` (stdlib only) with a
byte-identical copy in `deployment/pika-h3-flex/` (COPY cannot cross build
contexts; a test guards the sync); both `Dockerfile`s (ComfyUI →
`127.0.0.1:8189` ONLY and PID 1; gateway owns the exposed 8188);
`deployment/canary-image/README.md`; `rendering/runpod_transport.py`
(`comfy_token_provider` — the create request sets `env:
MICRODRAMA_COMFY_TOKEN` from the Comfy credential ref; an unresolvable token
refuses the create, fail closed); `pipeline/live_world.py` +
`pipeline/experimental_world.py` (wiring); new
`tests/unit/rendering/test_canary_gateway.py`; `test_runpod_transport.py`
(create-env + refusal tests); `test_comfy_transport.py` (every-route bearer).

**Offline tests only — no docker build or push (per the brief).** Gateway:
`26 passed` — 401 on every route (`/prompt`, `/upload/image`, `/view`,
`/history`, `/queue`, `/ws` websockets) for missing/wrong/empty tokens with
NOTHING reaching the upstream; valid-token forwarding that strips
Authorization; fail-closed with no configured token; 502 boot-window while
ComfyUI is starting (the canary's documented retry covers it). Client: every
route carries `Authorization: Bearer …` (also pre-asserted in the existing
prompt test). **Red** (pre-change transport): `2 failed` (no
`comfy_token_provider` kwarg / env payload). **Green:** `28 passed`.

**Not done here (operator action):** the images were NOT rebuilt/re-pushed —
the pinned digest in existing authorizations still names the pre-gateway
image. Shipping the gateway needs an image build + digest re-pin through the
documented validation flow.

## CN-6 — SHOULD-FIX — deadline overshoot (commit `5d0ffa9`)

**Root cause.** Both canary retry loops (and the prompt poll loop) checked the
deadline only AFTER a failure, then slept and dispatched without re-checking;
transports used a fixed 30-second timeout that could outlive the authorized
wall limit.

**Files.** `pipeline/canary.py` (deadline checked immediately before EVERY
attempt and right after every sleep: the `ensure_pod` warmup loop, the endpoint
read-back loop, the `/object_info` boot-window loop, and `submit_prompt`'s
submit attempts + post-sleep polls); `rendering/diagnostics.py`
(`set_request_deadline`/`bound_request_timeout`: contextvar deadline + run
clock); `rendering/runpod_transport.py` + `rendering/comfy_transport.py`
(urlopen timeout bounded by the remaining time, floored at 1 s); canary.py
installs the bound for the run body and removes it BEFORE the shutdown path so
cleanup stop/terminate/sweep keep the transport default;
`tests/unit/rendering/test_diagnostics.py`,
`test_comfy_transport.py` (timeout-bounding unit tests);
`tests/integration/pipeline/test_t045_canary_composed.py` (three fake-clock
tests with a run-phase call recorder; cleanup-phase calls are exempt via the
finally-entry marker). Benchmark controllers checked: `benchmark*.py` and
`experimental_world.py` have no retry loops — acquisition is single-shot
`ensure_pod`, and retries are reconciliation-only per CN-2.

**Red (pre-fix canary.py, tests in place):** `3 failed` — recorded run attempts
at/after the deadline in all three loops. **Green:** `3 passed`; full composed
file `44 passed`.

---

## Final verification (last lines quoted)

- `tests/unit/rendering` + `tests/unit/budget/test_billing_reconciliation.py`:
  `397 passed in 245.18s`
- `tests/unit/pipeline` + diagnostics/runpod/comfy transport files:
  `174 passed in 58.19s`
- `tests/integration/pipeline/test_t045_canary_composed.py`: `44 passed in 70.29s`
- `tests/integration/validation/test_at04_crash_recovery.py`: `4 passed in 307.56s`
- `tests/contract`: `462 passed in 322.24s`
- `make lint`: `All checks passed!` / `594 files already formatted` (after
  `d971435`)
- `make contracts-check`: `contracts 2.16.0: 104 schemas, 74 valid and 135
  invalid examples; OK`

Tree clean except the pre-existing untracked `.scratch/` and
`microdrama/.venv`. Nothing unresolved beyond the CN-5 image build/re-pin noted
above.
