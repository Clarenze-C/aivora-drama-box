# Build T045-FIX session 7: the re-review findings (CR-3 residual, CR-9)

You continue the T045 fix round in `/root/AIVORA/drama-box` on `feat/microdrama-m0-m4`. This
is a small, two-finding session. Everything offline: fixture transports, loopback PostgreSQL
only, no provider call, no live key, no pod. Commit, never push.

## Read first

1. `docs/microdrama-system/T045-fix-round/rereview-t045fix6.md` — the re-review **and the
   orchestrator rulings at the end**. The rulings are binding.
2. `docs/microdrama-system/T045-fix-round/brief-t045-fix6.md` — the standing rules from
   session 6 (hard limits, no deletion verbs, basetemp discipline, report path shape).
3. `docs/microdrama-system/T045-fix-round/T045-FIX6-REPORT.md` — what session 6 did (context
   for the two queries you will touch).

## Where the tree is

HEAD `2adf453` plus the orchestrator's docs commits for the re-review record and this brief.
`make check` (unit 2767 / contract 462 / integration 268) and `make pilot` green at
`2adf453`. Tree clean apart from `T045-FIX6-REPORT.md` (leave it; the orchestrator commits it
with this round's record).

## The work (tests-first red→green per finding)

1. **CR-3 residual (BLOCKING):** `_sweep_billing_ingestion`'s pod aggregate
   (`rendering/janitor.py:893-920`) computes `has_unverified_terminal_lease` with a plain
   `BOOL_OR(terminal AND terminate_verified_at IS NULL)` over every lease of the Pod — no
   supersession exclusion. An A→B→C transfer history (C verified, A and B keep their
   by-design NULLs) therefore defers ingest forever while the Pod is still listed. Fix: the
   aggregate must exclude superseded leases with the same `NOT EXISTS` predicate the two
   terminate selections use (a lease with a later lease on the same provider+pod is history;
   the final holder owns the terminate). Pin it with a test that starts from an A→B→C
   history, C verified, Pod present, and asserts **successful ingestion and finality
   progress** (buckets stored, readiness advancing) — zero-provider-call stability alone is
   not the green line, per the ruling.
2. **CR-9 (BLOCKING):** the absence-completion pass (`janitor.py:767-778`) and the F-1 tail
   lease selection (`janitor.py:643-658`) join on provider (+pod_id) and `owned_tag` only,
   never `provider_account_ref`. A scan of account A must not complete, close or DELETE a
   lease labeled for account B — absence was established for A's view only, and B's Pod may
   still exist and accrue. Fix: both selections match the manager's configured provider
   account label on the durable lease row; a foreign-account terminal lease is never selected
   by either pass. Tests pin both shapes: an empty successful scan of account A with a
   same-tag foreign-account terminal lease leaves that lease untouched (no terminate stamp,
   no storage-ownership closure), and the F-1 tail ignores a foreign-account lease for a
   present Pod.

Then: evidence (append to `microdrama/evidence/T045.md`, CR-3 residual and CR-9 with their
red/green lines), the full gates (`make check`, `make pilot`, ruff, `git diff --check`) under
`systemd-run -p CPUQuota=45%`, and the report: write
`docs/microdrama-system/T045-fix-round/T045-FIX7-REPORT.md`, leave it uncommitted.

## Hard limits (unchanged)

No deletion verbs anywhere. No env/`.env`/auth printing; never read `~/.claude/.env` or
`/root/.secrets`. Never push. `canary execute` / `make canary-db` only inside pytest.
Durable-root tests keep the scratchpad basetemp discipline; never chmod `/tmp/claude-0` or
its ancestors. Commit per finding: `fix(microdrama): T045-FIX CR-3 - ...`,
`fix(microdrama): T045-FIX CR-9 - ...`. On a usage limit: stop cleanly, commit only green
work, write what is left to the REPORT path.
