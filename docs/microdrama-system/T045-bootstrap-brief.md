# T045 paid-benchmark composition brief

Goal: one explicit offline-testable `PAID_BENCHMARK` bootstrap that composes
current rights/preset/workflow/quote evidence, credential references, durable
BudgetService reservations and provider operations, Runpod REST v2, Comfy HTTP,
durable outputs, and an independent janitor. The bootstrap must not itself
create a Pod when constructed. T031 separately authorizes and records a
bounded real canary.

Integrator owns a new `microdrama/src/microdrama/pipeline/live_world.py` (or
equivalent), scoped `tests/unit/pipeline/` and `tests/integration/pipeline/`
fixtures, and the operator runbook. Existing gates: `config.py:38–110`,
`rendering/leases.py:454–1210`, `rendering/comfy_jobs.py:179–879`,
`rendering/runpod_transport.py`, `rendering/comfy_transport.py`,
`core/registry/rights.py`, `rendering/presets.py`, `workers/janitor.py`.
Contract package 2.13.0 includes paired PromptManifest locator and billing
payloads. Worker may not edit contracts, migrations, budget billing service,
rendering adapters, T041b references/workflow code, root dependencies or task
ledger without a guardian proposal.

Construction fails closed unless mode is PAID_BENCHMARK, paid/cloud flags are
explicit, credentials are only `credref:` names, rights route/subject/version
is current and eligible, preset/workflow/image digest and node controls match,
operator quote is current with compute/storage exposure under reservation,
and Pod namespace/account ownership is isolated. No public/community action
capacity is enabled. The first external effect occurs only after durable
reservation and provider operation; ambiguity stays UNKNOWN and independent
janitor continues after worker crash. A billed-cost query remains pending
until the T045 billing service allocates/finalizes it; never claim `BILLED`
from a raw API bucket.

Fixture tests: OFFLINE_MOCK/no flags/no quote/no rights/old preset deny before
credential or HTTP access; create/submit timeout-created/not-created/unknown;
restart reconciliation, durable output, stop failure and janitor cleanup;
separate billing pending state. Run scoped tests/Ruff, then parent runs
`make check` and `make pilot` under CPUQuota45%. No live Pod, paid prompt,
public action or commit.
