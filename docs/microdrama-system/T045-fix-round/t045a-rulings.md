## T045-A review (Claude Sonnet 5.5, read-only, stand-in for Codex) — Opus rulings, 2 Nov 2026

The review covered commits `f7f135b..1a60fc5`. They were read only through git, and tests were run
in an isolated worktree:
- `tests/unit/budget tests/unit/rendering`: 426 passed;
- billing persistence + 0025 migration: 7 passed.

The verdict was NEEDS CHANGES, with 1 blocking finding. No path double-counts, loses a charge or
releases a Runpod hold while cost is unknown. Every defect fails closed (the hold stays).

**Migration note for the fix round:** 0025 is unpushed and has never been applied to a persistent
database. The staging volumes predate it: the last drill was 09:29Z, 0025 was written 12:5xZ. So
0025 **may be edited in place**. Verify before editing that the staging postgres volume, if one
exists, has no 0025 row.

| ID | Finding | Ruling |
|----|---------|--------|
| A-B1 | A period with a bucket that was ever skipped as open can never be verified. The skipped table is append-only and the check ignores later closed observations (`billing.py:551-558`; reproduced). | **BINDING.** Refuse only when a skipped row has no stored closed bucket of the same identity observed at or after the skip. Test: open poll, then closed poll, then verify → MATCHED → BILLED. |
| A-S1 | A sent-but-podless create never settles: `compute_window_end_at` is never set, so readiness stays PENDING forever (`leases.py:1119-1146`, `janitor.py:309`). | **BINDING, amended.** Set `compute_window_end_at` = close time on close-without-pod when a create was sent. Finality for a podless sent create needs an **audited operator resolution** `resolve_podless_create(lease_id, actor_ref, reason, evidence_sha256)`: the operator attests that the console shows no Pod and no charge for the owned name and period, and that posts the BILLED 0 SETTLEMENT. If the Pod later appears, the existing stray-adoption path applies and the resolution is refused. Test: ambiguous create → no Pod → resolution → BILLED 0; resolution refused once a Pod is attached. |
| A-S2 | The backoff never grows; it is always 5 min (`finality.py:160-176`). | **BINDING.** Store an attempt count (a 0025 column) and double the delay up to the 1-hour cap. Test three consecutive sweeps. |
| A-S3 | `settle_billed_lease` reads readiness and the GPU sum outside the settlement transaction, so a concurrent ADJUSTMENT can be overwritten by a stale SETTLEMENT (`billing.py:1032-1090`). | **BINDING.** Recompute readiness and the sum and post the SETTLEMENT in **one** transaction, holding the reservation lock. Use an in-transaction ledger post. Concurrency test: an ADJUSTMENT racing a settlement ends with settled = the full posted sum. |
| A-S4 | Readiness returns BILLED 0 when `window_start` is NULL, without checking `pod_id` (`billing.py:883`). | **BINDING.** Return PENDING when `window_start IS NULL AND pod_id IS NOT NULL`. Test. |
| A-S5 | The overstatement evidence uses `max()` over periods and compares one lease to the whole Pod (`billing.py:1069`). | **BINDING.** Make the overstatement Pod-level: the sum of distinct non-superseded MATCHED periods against the total posted for all leases on that Pod over those periods. It is evidence only. Test with two periods and one with a warm transfer. |
| A-S6 | Storage ownership opens only on CLAIMED→ACTIVE or attach. A crash in between leaves no row and disk charges go to recovery. The close runs before the lease-row terminate write, which can leave a gap (`leases.py:~850,410,1076`, `janitor.py:263`). | **BINDING.** Open idempotently from the ensure/ACTIVE path too. Write `terminate_verified_at` first, then close ownership **from the persisted value**. Tests: crash after activation, and crash between terminate write and close. |
| A-S7 | The `test_billing_repository.py:35-45` rewrite dropped assertions. | **BINDING.** Restore equivalent strength: the RECOVERY allocation and pending posting row exist, a new Runpod reservation is blocked, and the provider-reported sum is asserted. |
| A-S8 | The ordering test doesn't prove the commit happens before create, and the "shutdown" test never calls shutdown (`test_t045_timing.py:112`). | **BINDING.** The fake `create_pod` reads `create_requested_at` over a separate connection and asserts it is visible. The shutdown test calls the real shutdown path, or is renamed to what it tests. |
| A-N1 | `_verified_finality` is a public `ingest` keyword (`billing.py:204`). | **BINDING.** Move it to a private method that no public `ingest` can reach. |
| A-N2 | The per-bucket `verify_invoice` is still public (`billing.py:401`). | **BINDING.** Make it private. R5 allows only `verify_invoice_period`. |
| A-N3 | The covering query is account-scoped, not Pod-scoped (`billing.py:~545`). | **BINDING.** Require a Pod-scoped covering query. |
| A-N4 | The boundary check doesn't require buckets to fit inside the period (`billing.py:~565`). | **BINDING.** Every counted bucket must lie fully inside the period, and the edges must be on bucket boundaries. Contiguity stays R7(b)'s job (lease-window coverage). |
| A-N5 | The unresolved-RECOVERY check is Pod-wide, stricter than R7(d) (`billing.py:937`). | **ACCEPTED AS IS.** It is conservative; record it in the evidence. |
| A-N6 | 0025's identity column default `''` is not backfilled, and `MATCHED_ZERO` has no amount CHECK. | **BINDING.** Backfill from the bucket row (0025 is edited in place) and add `CHECK (outcome <> 'MATCHED_ZERO' OR amount_micro_usd = 0)`. |
| A-N7 | `FOR UPDATE` on a join locks the lease rows (`service.py:~1027`). | **BINDING.** Use `FOR UPDATE OF r`. |
| A-N8 | `except Conflict: pass` reports `released=True` after a refused release (`finality.py:150`). | **BINDING.** Re-read the reservation state after the Conflict and report the truth. |
| A-N9 | `settle_reservation_for_lease` doesn't check the pairing. | **BINDING.** Check it there too. |
