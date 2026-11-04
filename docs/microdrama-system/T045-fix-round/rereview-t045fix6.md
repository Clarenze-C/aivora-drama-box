# Scoped re-review of the CR-1..CR-8 fixes (Codex, 2026-11-04) — FIX-REQUIRED

> **Provenance (GLM orchestrator, 2026-11-04):** Codex re-review, `ai-route review --base
> 72c54fc --effort xhigh`, tag `dramabox-t045fix6-rereview`. The full report was delivered in
> the final message (the sandbox refuses file writes) and is recorded here verbatim, followed
> by the orchestrator rulings.

VERDICT: FIX-REQUIRED

Reviewed `72c54fc...2adf453`. CR-3 remains incomplete; CR-9 is a new blocking defect.

| Finding | Verdict | Evidence |
|---|---|---|
| CR-1 | SATISFIES-RULING | [canary_db.py:90](/root/AIVORA/drama-box/microdrama/tools/canary_db.py:90) excludes the existing root from the traversal chain. The [restart test:123](/root/AIVORA/drama-box/microdrama/tests/integration/pipeline/test_t045_canary_db_durable.py:123) uses real up/down/up, verifies 0700/server ownership, and never patches `geteuid`. |
| CR-2 | SATISFIES-RULING | [janitor.py:764](/root/AIVORA/drama-box/microdrama/src/microdrama/rendering/janitor.py:764) skips unknown scans and present Pods; absent terminal leases receive verified termination and ownership closure without DELETE. Separate account-scope defect below. |
| CR-3 | VIOLATES — BLOCKING | Both terminate selections exclude superseded leases, but [janitor.py:902](/root/AIVORA/drama-box/microdrama/src/microdrama/rendering/janitor.py:902) still counts their intentional NULL timestamps as unverified termination, causing continued billing deferral. |
| CR-4 | SATISFIES-RULING | [canary.py:1041](/root/AIVORA/drama-box/microdrama/src/microdrama/pipeline/canary.py:1041) retries three times; exhausted failures become `run_error` after cleanup, producing NOT_CLEAN and `CanaryRunNotClean`. |
| CR-5 | SATISFIES-RULING | [comfy_jobs.py:1118](/root/AIVORA/drama-box/microdrama/src/microdrama/rendering/comfy_jobs.py:1118) persists the reason event in the settlement transaction; [canary.py:1065](/root/AIVORA/drama-box/microdrama/src/microdrama/pipeline/canary.py:1065) includes it in the record step. |
| CR-6 | SATISFIES-RULING | [canary.py:460](/root/AIVORA/drama-box/microdrama/src/microdrama/pipeline/canary.py:460) checks environment membership. A direct offline probe confirmed empty-string refusal. |
| CR-7 | SATISFIES-RULING | [canary.py:1130](/root/AIVORA/drama-box/microdrama/src/microdrama/pipeline/canary.py:1130) places handler restoration in the record write's `finally`, including write failures. |
| CR-8 | SATISFIES-RULING | [runbook:224](/root/AIVORA/drama-box/docs/microdrama-system/T045-live-provider-runbook.md:224) documents `--observed-at`, matching argparse. |

CR-3 reproduction: executing the actual billing query against an in-memory A→B→C history, with C verified and the Pod still listed, returned `DEFERRED` on all three sweeps. Historical pending reservations remain eligible for the query. The new [test:1280](/root/AIVORA/drama-box/microdrama/tests/unit/rendering/test_t045_billing_ingestion.py:1280) checks zero stop/DELETE calls and stable counts, which also pass when ingestion never progresses. Exclude superseded leases from the unverified-termination aggregate and pin successful ingestion.

The two test adjustments:

- **LEGITIMATE — refused-read reseed:** [test:436](/root/AIVORA/drama-box/microdrama/tests/unit/rendering/test_t045_billing_ingestion.py:436) retains the ownership-failure and zero-bucket assertions. The foreign account prevents the attested ownership proof even after absence completion.
- **LEGITIMATE — invoice equivalence:** [test:1206](/root/AIVORA/drama-box/microdrama/tests/unit/rendering/test_t045_billing_ingestion.py:1206) asserts exactly 500,000 settled, zero outstanding reservation, and SETTLED state. For this ACTIVE-reservation seed, settlement replaces accrual in account counters; summing both charge kinds double-counts their accounting stages.

**CR-9 — BLOCKING — absence completion ignores the provider account.**
[janitor.py:769](/root/AIVORA/drama-box/microdrama/src/microdrama/rendering/janitor.py:769) filters by provider and namespace without matching `provider_account_ref`. An empty successful scan for account A therefore selects a same-namespace terminal lease belonging to account B and stamps termination/closes storage ownership. An in-memory probe confirmed both mutations despite differing configured and lease accounts. B's Pod could still exist and accrue storage charges. Require the durable account label to match the account scanned before treating absence as termination evidence.

Validation: scoped Ruff check/format and `git diff --check` passed. In-memory probes reproduced CR-3 and CR-9. Focused pytest could not start because `systemd-run` returned `Failed to connect to bus: Operation not permitted`; PostgreSQL suites and reported full gates were not independently rerun. No files were changed or external calls made.

---

## Orchestrator rulings (GLM-5.3, 2026-11-04)

- CR-1, CR-2, CR-4, CR-5, CR-6, CR-7, CR-8: **CLOSED** (SATISFIES-RULING).
- The two session-6 test adjustments: **LEGITIMATE** — no weakening.
- **CR-3 residual: accepted as BINDING.** Confirmed at `janitor.py:901-902`: the billing
  aggregate's `has_unverified_terminal_lease` has no supersession exclusion, so a transfer
  history's by-design NULL terminate timestamps defer ingest forever (the F-1 ruling requires
  finality to be reachable and a third sweep to add nothing). Fix: the aggregate must exclude
  superseded leases with the same `NOT EXISTS` predicate the two terminate selections use, and
  a test must pin successful ingestion (buckets stored, readiness advancing) through an
  A→B→C transfer history with C verified and the Pod present — not only zero-provider-call
  stability.
- **CR-9: accepted as BINDING.** Confirmed at `janitor.py:767-778` (absence pass) and
  `643-658` (F-1 tail): both join on provider (+pod_id) and `owned_tag` only, never
  `provider_account_ref`. A scan of account A must not complete, close or DELETE a lease
  labeled for account B. Fix: both terminate selections match the manager's configured
  account label on the durable lease row; a foreign-account terminal lease is never selected
  by either pass (its own account's janitor owns it). Tests pin: an empty scan of account A
  with a same-tag foreign-account terminal lease leaves that lease untouched (no
  terminate stamp, no ownership closure), and the F-1 tail ignores a foreign-account lease
  for a present Pod.

Session 7 carries both fixes (`brief-t045-fix7.md`). Per the two-round review cap this cycle
has now used its review + re-review rounds; the verification of the CR-3/CR-9 fixes goes back
to the operator before any third Codex round runs.
