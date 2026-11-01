# T045 — paid benchmark adapter and recovery path

## Scope and authority

Build live-capable Runpod/Comfy transports and PAID_BENCHMARK composition behind
the existing budget, effect and rights gates. This task is code and offline
fixture validation only: it does not create a Pod, submit a paid prompt, select
an unqualified rights route, or post to an account. T031 separately records a
bounded authorized real canary and its rights/quality/billed-cost evidence.

Official interface anchors rechecked 30 October 2026 UTC:

- Runpod Pods REST v2: `POST /v2/pods`, action `stop`/`start`, `DELETE
  /v2/pods/{id}`; stopped volume storage can keep billing. The older GraphQL
  route also documents create/resume/stop/terminate/list/get operations.
  https://docs.runpod.io/pods/manage-pods and
  https://docs.runpod.io/sdks/graphql/manage-pods
- ComfyUI self-hosted server: `POST /prompt` returns prompt ID or node errors;
  `/history/{prompt_id}`, `/queue`, `/view`, `/object_info` and `/system_stats`
  support validation/poll/output inspection.
  https://docs.comfy.org/development/comfyui-server/comms_routes
- Runpod compute/storage charges continue on their documented billing bases;
  current exact quote must be captured at canary time, not hardcoded here.
  https://docs.runpod.io/pods/pricing

## Owned implementation

Worker may edit `microdrama/src/microdrama/rendering/{pods,leases,comfy_jobs,
comfy_assets,janitor,presets_benchmark}.py`, add focused live transports under
`rendering/`, and scoped rendering tests. Integrator owns `pipeline/world.py`,
workers registration, root config/dependencies, migration ordering and task
ledger; propose those changes rather than editing them. T041b later owns typed
semantic reference → workflow binding, so do not edit its story/reference code.
Existing disabled slot: `rendering/pods.py:304–370`; lease/reservation path:
`rendering/leases.py:454–1210`; Comfy submit/recover: `comfy_jobs.py:179–879`;
independent janitor: `rendering/janitor.py`.

## Required invariants

OFFLINE_MOCK refuses all live network effects even with credential references.
PAID_BENCHMARK requires explicit effect flags, configured credential *names*,
current eligible rights, pinned image/workflow/GPU allowlist/price ceiling,
reservation and durable operation record before the first external effect.
Never read unrelated project credentials or log raw keys. Use an injectable
transport and real clock/IDs for live composition. Pod create ambiguity must
search only owned tags/client tokens before retry; stop failure is visible to
an independent janitor. Comfy submit ambiguity reconciles by durable prompt
ID/token; outputs are fetched, hashed and copied to durable storage before
marking success. Costs include failed attempts and storage exposure; do not
turn a synthetic estimate into an actual billed receipt. Separate production,
publication and community capacities. Pods stop before human waits.

## Verification

Offline fixture faults: create/submit timeout with operation actually created,
not-created result, restart reconciliation, stop/terminate failure, price/rate
change, missing rights, invalid workflow/control, corrupt/missing output, and
orphan janitor cleanup. Prove no duplicate paid operation or unowned Pod
termination. Check that absent real billed-cost evidence blocks qualification.
Run scoped tests/Ruff, `make check` after integration, and document an operator
canary command with current quote/time/spend/storage cap and verified shutdown
receipt fields. No live command is executed in T045. Do not commit.
