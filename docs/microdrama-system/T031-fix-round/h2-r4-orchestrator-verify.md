# T031 H-2 round 4: orchestrator verification (Opus, session e4e3c05c, 12 Nov 2026)

The operator approved R4 with orchestrator-only verification (no 4th Codex round). This file
records what the orchestrator re-ran and read. Build report: [h2-r4-REPORT.md](h2-r4-REPORT.md).
R4 tip: **`0cda424`** on `feat/t031-fix3` (R1 `92f7b51`, R2 `621e49e`, R3 `0cda424`).

## 1. Every red claim, re-run independently

All runs were offline (`OFFLINE_MOCK`, paid/cloud/public off) and used `/usr/sbin` on PATH,
`systemd-run --scope -p CPUQuota=45%` and a separate basetemp. Each ran in a fresh detached
worktree, not the builder's:

- `t031-r4v-prod7060`: the R4 test tree at `0cda424` with both production files R4 changed
  (`pipeline/benchmark_service.py`, `rendering/benchmark_experiments.py`) restored from `7060e02`.
  `git diff --quiet 7060e02 -- microdrama/src` returned true, so production code equals the
  pre-R4 baseline. R2 is test-only.
- `t031-r4v-oldproof` at `ccc9b53`: the builder's scratch branch. Its diff against `621e49e`
  touches only `_deadlocks`, which is back to raw `DeadlockDetected`, and the whitelist, which
  is back to blanket `MicrodramaError`. Read in full.
- `t031-r4v-oldorder` at `05369f7`: the builder's scratch branch. Its diff against `621e49e`
  only removes the account/categories lock prelude from `resolve_podless_create`'s wrapper,
  restoring the pre-P4 order. Read in full.

| Claim | Worktree | Builder's result | Re-run result | Failure reason (re-run) |
|-------|----------|------------------|---------------|-------------------------|
| R1 (a)(b) red, (c) passes | prod7060 | `3 failed, 1 passed` | **`3 failed, 1 passed in 17.11s`** | `Failed: DID NOT RAISE Conflict` ×3 (a, b[RAISE], b[INDETERMINATE]) |
| R3 HD-2 red | prod7060 | `1 failed` | **`1 failed in 7.05s`** | `Conflict: interval already attributed` |
| R2 HD-3 injection red on the old proof | oldproof | `1 failed` | **`1 failed in 6.39s`** | `Failed: DID NOT RAISE AssertionError` |
| R2 wrapper race red on the old lock order | oldorder | `1 failed` | **`1 failed in 15.94s`** | `AssertionError: ServiceUnavailable('deadlock detected')` |

Logs: `scratchpad/keep/t031-r4-redcheck/*.log`, script `scratchpad/keep/t031-r4-redcheck.sh`.
The AT-9 `sweep_finalization_mid` change proves behaviour that was already correct, so no red
exists by design. Its injection evidence is in the test itself: subprocess exit 86, a marker
file, and the mid-crash state.

**Greens:** covered by the full gate at `0cda424` (§3). Every R4 test file is in `make check`.

## 2. R1 diff read against spec R7 (§7.3)

`git diff 7060e02 92f7b51 -- microdrama/src` changes only `resolve_sample`'s BOUND branch:

- Composing the RECOVERY world raises, binding it raises, or the binding is anything other than
  exactly `BOUND`: the result is `Conflict`, which refuses even with force.
- `reconcile_unknown` raises `EffectDenied`: the result is `Conflict`, which also refuses even
  with force.
- Any other `reconcile_unknown` exception keeps `probed_state = None`, which leads to the
  ambiguous/force path.

This matches Codex's HD-1 "Fix" paragraph and R7. Checks made:

- **`bind_for_recovery` (`experimental_world.py:189–242`) writes nothing durable.** It makes two
  read-only transactions, one RunPod GET and a local `bind_pod_endpoint` on the freshly composed
  client. Binding a second time costs one read-only provider GET.
- **Every `EffectDenied` raise site in the transports is a local guard:**
  - unbound client;
  - endpoint/pod mismatch;
  - `OFFLINE_MOCK`;
  - credential reference missing or unresolved;
  - no durable authorization scope.

  None of them is provider evidence, so treating `EffectDenied` as a local probe failure is
  correct (judgement call R1-2).
- **A probe binding of `INDETERMINATE` after a primary `BOUND` (the pod changed between the two
  reads) refuses.** A retry re-enters through the primary binding, which then routes
  `INDETERMINATE` or `VERIFIED_SOURCE_GONE` normally. This fails closed and nothing gets stuck
  (judgement call R1-3).
- **Residual, within spec:** a bound probe whose read fails for another reason (for example a
  resolved but wrong credential returning HTTP 401, or a timeout) still counts as ambiguous. It
  reaches the force path only with `--force-unrecoverable` plus the attestation. That is what R7
  allows for INDETERMINATE cases, and Codex's fix paragraph did not ask for more. Revisit with
  the phase D production adapter, alongside HC-6/HC-9/HC-11/HB-13.

**Verdict R1: matches R7.**

## 3. R3 diff read (money path, not on the brief's list, read because no reviewer saw it)

`git diff 621e49e 0cda424 -- microdrama/src` adds `_late_interval_identity`. It takes the account
lock, reads the reservation state and checks for a charge under the original `receipt_id`, then
decides:

- reservation open: the receipt passes through;
- reservation closed, charge already posted: the receipt passes through with its original
  identity;
- reservation closed, nothing posted: the receipt is re-identified as a `late:` ADJUSTMENT.

**Window between the decision and the post:** the decision transaction commits before the
canonical post takes the lock again. If settlement closes the reservation inside that window,
an ACCRUAL receipt that passed through reaches the base ledger on a closed reservation. The
ledger refuses it with `Conflict` and writes nothing (`budget/service.py:189–190`, `:845–848`).
The replay then mints `late:`. In the other direction, an already-posted charge is immutable,
so a "posted" decision cannot go stale. **Fails closed. Accepted as is.**

## 4. Full offline gate at `0cda424`

- Checkout: `.scratch/t031-gate-r4` (detached, pinned).
- Unit: `t031-r4-offline-gates` (CPUQuota=45%, `/usr/sbin` on PATH), started 03:38Z.
- Receipts: `.scratch/t031-gate-r4/.scratch/gate/`.
- Baseline at `7060e02`: GREEN (3,062 / 462 / 275, pilot OK).

Result: **GREEN, 05:30Z.** `head.txt` = `0cda42434b4e…`; `check.exit` 0, `pilot.exit` 0, `overall.exit` 0.

- contracts 2.16.0 OK; `ruff check` clean; `ruff format --check`: 608 files already formatted;
- unit **`3068 passed, 2 warnings in 3797.49s`**: the baseline's 3,062 plus R4's 6 new tests (R1 ×4,
  the HD-3 injection test, the HD-2 test);
- contract **`462 passed`**; integration **`275 passed`**; `make check: all offline checks passed`;
- `make pilot`: 16 media files exported, settled 303,000 µUSD (fake providers).

## Decision: T031 H-2 ACCEPTED at `0cda424` (12 Nov 05:35Z)

- `feat/t031-pika-flex-native` was fast-forwarded `d971435 → 0cda424` (41 commits, `--ff-only`, local,
  not pushed). Undo if ever needed: `git branch -f feat/t031-pika-flex-native d971435`, run where the
  branch is not checked out.
- Known limits carried to phase D (rulings-hcf-final.md): HC-6, HC-9, HC-11 and HB-13 (broad), plus the
  R1 residual in §2.
- Still operator-gated before any paid T031 run:
  - the $8 sign-off;
  - a pullable image (GHCR token scopes);
  - the weights;
  - the reference assets;
  - the Botnoi voices.
- Scratch branches `t031-r4-red-oldorder` and `t031-r4-red-oldproof` (WIP red checks) must never be
  merged. They and `wip/t031-hcf-f3-stash` can be removed with `git branch -D` once no longer needed.
