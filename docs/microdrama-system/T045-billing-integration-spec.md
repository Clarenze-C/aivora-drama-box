# T045 billing reconciliation — offline implementation spec

Runpod's documented `GET /v2/billing/pods` returns time-bucketed `podId`,
`startTime`, `endTime`, `totalAmount`, `gpuAmount`, `cpuAmount`, `diskAmount` and
the provider-resolved query window/bucket size. These are provider-reported
amounts, not per-second lease receipts or invoice-final costs. Source:
https://docs.runpod.io/api-reference-v2/billing/get-pod-billing-history

## Scope

Build durable, exact-micro-USD ingestion and allocation for T045/T031 behind
fixture transports. This does not authorize a live billing query or paid Pod.
The integrator owns a new ordered migration, `budget/` reconciliation service,
`persistence/` repository and scoped budget/persistence tests. Contract guardian
owns any new cross-module payloads; no worker invents local incompatible
schemas. Rendering's Runpod adapter keeps raw provider records unallocated
until the new service accepts them.

## Invariants

1. Parse provider monetary JSON lexically into `Decimal`, convert to integer
   micro-USD with an explicit precision policy, and reject float arithmetic,
   negative/non-USD/malformed totals. Require total = GPU + CPU + disk exactly.
2. Store append-only raw bucket observations keyed by account, pod, bucket
   start/end/size, with raw hash, observed time, resolved query window and
   component amounts. Identical replay is idempotent. A changed amount appends
   a revision and posts only the delta, never the full amount again.
3. Allocate GPU/CPU over measured overlap with durable running/lease ownership
   intervals; use deterministic largest-remainder micro-USD splitting so sums
   match each component exactly. Uncovered time remains a named recovery pool,
   not zero or a neighboring episode. Failed attempts remain charged.
4. Allocate disk by persisted storage ownership until verified deletion;
   stopped-volume storage continues under its owner. Warm transfer never
   rewrites historical storage charges. Missing owner goes to recovery pool.
5. Persist allocations and provider observation in one transaction. Each
   bucket revision/component is fully allocated once; credits/negative deltas
   cannot restore episode spending allowance. Do not pass full buckets into
   `record_gpu_interval`, which enforces nonoverlapping intervals.
6. API bucket observations remain `PENDING_PROVIDER_FINALITY` or
   `ALLOCATED_PROVIDER_REPORTED`. Only separately matched invoice/console
   evidence can mark `INVOICE_VERIFIED`/`BILLED`; mismatches are `DISPUTED`.
   Empty/missing buckets mean UNKNOWN, never zero or settled. Until finality,
   protect reserved exposure and report actual cost as pending.
7. Existing `UsageReceipt` amounts are nonnegative, while provider bucket
   revisions can have signed component deltas. Add a durable
   `BudgetService.reconcile_provider_allocation` (or equivalent ledger API)
   keyed by stable allocation/revision and owner/reservation. Positive
   provider-reported deltas accrue against the original reservation without
   releasing its outstanding exposure. Negative revisions append adjustment
   evidence but never restore consumed allowance. Invoice verification posts
   the final billed status once and releases only unused reservation exposure;
   a lower invoice does not erase failed spend. Missing finality preserves
   pending cost and the protective hold. Recovery-pool allocations are
   separately durable and prevent an episode from qualifying until resolved.
   Reconciliation, charge and finality transitions are one transaction and
   serialized per bucket/account.

## Verification gate

Fixture tests: identical replay, revised bucket delta, two warm leases in one
bucket, partial/uncovered interval, failed attempt, post-stop disk charge,
storage owner change only prospectively, invoice mismatch, missing/empty
response, precision/total error, concurrent ingestion and restart readback.
Prove no duplicated charge and no allowance restoration. Run scoped tests and
Ruff, then `make check` under CPUQuota45% after integration. No live provider
or public action; no commit.
