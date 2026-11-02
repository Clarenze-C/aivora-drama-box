# T045 finality, replay and live wiring — spec addendum, revision 1 (2 November 2026)

Owner: Opus spec rulings. This addendum extends [T045-billing-integration-spec.md](T045-billing-integration-spec.md)
and the [runbook](T045-live-provider-runbook.md). Where this addendum and the older text differ, the
addendum wins. The work is offline only: no provider call, no Pod, no paid request, no public action.

Revision 1 applies a pre-build critique by Claude Sonnet 5.5 (read-only; findings B1–B6 and S1–S9,
all accepted except one partial). The record is at the end of this file.

## Where the code stands (read-only gap check, 2 Nov, tree `f7f135b`)

**Already built and tested:**
- lexical money parsing and the total = GPU + CPU + disk check;
- append-only bucket observations with replay and revision deltas;
- largest-remainder splitting;
- recovery-pool blocking of new Runpod reservations;
- mismatch evidence that persists without finalizing;
- schema guards on all eight billing tables.

The focused suites show 20 passed.

| # | Gap or defect | Where |
|---|---------------|-------|
| G1 | The allocation denominator is the bucket length. A partly used hour sends its unused part to the recovery pool. A normal canary's last hour would therefore block every later Runpod reservation. | `budget/billing.py:409-414` |
| G2 | Positive provider deltas post to the account's **newest** Runpod reservation, not the lease's own one. | `budget/service.py:635-638` |
| G3 | Nothing writes `pod_storage_ownership`. Every disk charge goes to the recovery pool. | 0022:61-76 |
| G4 | The caller chooses bucket finality, including `INVOICE_VERIFIED` on first ingest. | `budget/billing.py:173-177` |
| G5 | A matched invoice only inserts a finalization row. There is no lease-level BILLED, no BILLED receipt and no release of the unused hold. | `budget/service.py:695-723` |
| G6 | Replaying an invoice raises `IntegrityError` (same id) or writes a second verification row before rolling back (new id). There is no unique key on the revision or the evidence. | `budget/billing.py:254-293`, 0022:53-59 |
| G7 | `settle_reservation_for_lease` releases the hold when the recorded total is 0. Runpod `usage()` returns `[]` (unknown), so a live lease would free its hold while real cost is still outstanding. | `rendering/leases.py:418-426`, `runpod_transport.py:441-448` |
| G8 | `live_world` ends in an unconditional `raise PolicyDenied`. It has no `BillingRepository`, and `billing_state` is a constant. | `pipeline/live_world.py:245,317-320` |
| G9 | `accounting_readiness` sums only buckets wholly inside the window but tests coverage by overlap. Nothing calls it. | `budget/billing.py:337-352` |
| G10 | Nothing maps `RunpodBillingRecord` to `RunpodBillingBucketObservation`. | `runpod_transport.py:450-491,543` |
| G11 | `RunpodQuoteAttestation` lacks the quote id, currency, persistent-volume size and maximum storage exposure. | `runpod_transport.py:39-54` |
| G12 | No runnable PAID_BENCHMARK or canary command exists. | Makefile, `__main__` files |
| G13 | Lease timing is not durable. `pod_leases` has no create-request time, compute-window bounds or terminate time; only `stop_verified_at` exists. `create_pod` is called with no prior durable write. Release-without-cost uses a list miss as proof, which the code itself says is not proof. | 0003:161-184, `pods.py:163-190`, `leases.py:982`, `janitor.py:~300-318` |
| G14 | Shutdown only stops the Pod, and its volume keeps billing. `billing_history` refuses once the Pod is absent at the provider, so a terminated Pod's billing can never be read. | `pods.py:255-277`, `runpod_transport.py:462-465` |
| G15 | The janitor's terminal sweep selects only `r.state='ACTIVE'`. A hold that EXPIRED while it waited for an invoice is never revisited. | `janitor.py:488` |
| G16 | A lease that transferred away is RELEASED without `stop_verified_at`, so its window end is unknown. | `leases.py:~1081-1177` |

## Rulings

**R0. Migration 0025** (one new ordered migration; 0001–0024 are never edited) adds the following.

On `pod_leases`:
- `create_requested_at` (set once). It is written and **committed in its own transaction before**
  `create_pod` is sent.
- `compute_window_start_at` (set once).
- `compute_window_end_at` (set once). This is the transfer instant, or the verified stop/terminate
  time.
- `terminate_verified_at` (set once).
- `provider_account_ref` (set at claim; a non-secret label from the attestation, R10).
- `next_finality_check_at` (backoff).

A set-once trigger guards the four timestamps.

On `pod_storage_ownership`:
- a `creating_lease_id` column;
- a BEFORE UPDATE close-once trigger: only `valid_until` NULL → non-NULL, exactly once.

On `runpod_billing_buckets`: drop `UNIQUE(bucket_identity_sha256, raw_response_sha256)` and replace
it with `UNIQUE(bucket_identity_sha256, raw_response_sha256, finality_state)`.

On `runpod_billing_invoice_verifications`:
- `UNIQUE(bucket_observation_id)`;
- `UNIQUE(bucket_identity_sha256, evidence_sha256)`.

New append-only tables:
- `runpod_billing_period_evidence`, for R5;
- `runpod_billing_query_skipped_buckets`, for R4.

Every new table and column follows the schema-catalog invariants: no TRUNCATE, integer numbers, and
append-only or set-once. These are persistence changes only, with no guardian contract change.

**R1. Allocation basis** (fixes G1, using G13 data).

For **Runpod**, `pod_usage_intervals` is empty because `usage()` returns `[]`. So lease windows come
from `pod_leases`:
- The chain root (no `transferred_from`, `pod_id` set) starts at its `create_requested_at`.
- A transfer receiver starts at the transfer instant.
- Each lease ends at its `compute_window_end_at`. While that is unknown, use the bucket end, which
  is conservative.

The **GPU/CPU denominator** is the Pod's existence seconds inside the bucket: from the root's
`create_requested_at` to the last lease's verified stop or terminate. **It is never the bucket
length.** Shares are the window overlap seconds per lease episode.
- Existence covered by no lease goes to the **root lease's episode**.
- It goes to `recovery_pool` only when the Pod has no root lease.
- A non-zero bucket with zero recorded existence goes 100% to recovery.

The **disk denominator** is the storage-ownership seconds inside the bucket.

The fake provider keeps using `pod_usage_intervals` exactly as today.

Red pinning test on real PG: a 90-minute single lease produces two hourly buckets, the second only
30 minutes long. 100% of each goes to the lease's episode, and the recovery pool gets 0.

**R2. Reservation link, GPU only** (fixes G2).
- **GPU** allocations post against the reservation of the lease whose window overlaps, taking the
  earliest overlap for that episode on that Pod. For uncovered existence, use the root lease.
- **CPU and DISK** allocations (`CPU_STORAGE_TRANSFER`) post **unreserved**, as settled spend in
  full. The lease hold is `GPU_GENERATION`, and `_linked_reservation` requires the categories to
  match (`service.py:1005`).
- Never select a reservation by "newest per account".
- A **zero-delta** allocation row is stored but **posts nothing**. In particular a zero-delta
  RECOVERY row must not create `RECOVERY_PENDING` or block reservations.

**R3. Storage ownership** (fixes G3).
- **Open.** On activation or `_attach_stray`, once `pod_id` is known, write the ownership row for the
  root lease's episode, with `valid_from` = the root's `create_requested_at` and `creating_lease_id`
  set.
- **Transfer.** A warm transfer never changes the owner.
- **Close.** Close the row (via the R0 trigger) only at `terminate_verified_at`.

**R4. The repository derives bucket state** (fixes G4).

This overrides billing spec §6 and the runbook's "API observations stay PENDING_PROVIDER_FINALITY".

API ingest stores only **closed** buckets, where `bucket_end ≤ observed_at − settle_lag`:
- a closed bucket is stored as `ALLOCATED_PROVIDER_REPORTED`;
- a malformed one (non-USD, or total ≠ sum) is stored as `DISPUTED`;
- open buckets go to `runpod_billing_query_skipped_buckets`;
- if every returned bucket is open, the query is recorded as `UNKNOWN`.

`settle_lag` defaults to 15 minutes. **This is an unverified assumption about how Runpod settles
buckets**, so it is configurable and labelled as an assumption in the runbook.

Ingest refuses `INVOICE_VERIFIED` with a typed error. `PENDING_PROVIDER_FINALITY` is a lease
readiness state (R7). `EMPTY` and `UNKNOWN` never count as coverage or as zero, except through the
billed-zero route in R5.

**R5. Invoice evidence is pod-scoped and period-level; per-bucket verification is internal** (fixes
G5/G6).

There is one public API: `verify_invoice_period(account_ref, pod_id, period_start, period_end,
amount_micro_usd, currency, evidence_sha256, source, observed_at, supersedes_evidence_id=None,
actor_ref=None, reason=None)`. Account-wide scope is dropped: invoice totals include work this
pipeline never ingests.

Preconditions:
- A completed billing query for the Pod covers the period and ran after `period_end + settle_lag`.
- There are no skipped-open buckets inside the period.
- The period edges lie on bucket boundaries.
- Otherwise it raises a typed refusal.

Outcomes:
- **Sum = amount, with buckets present.** Write one period row (MATCHED). Then, for each bucket,
  write internally an `INVOICE_VERIFIED` revision N+1, a MATCHED verification and a finalization.
  All of it is one transaction, serialized per Pod.
  - The verified revision has the same raw hash; R0 widened the unique key for this.
  - The bypass of the replay `continue` in `ingest` must apply to this path only.
- **Billed zero.** Amount 0, the query result is `EMPTY` and it ran after the settle lag. Write a
  MATCHED_ZERO period row. It counts as zero-amount coverage for R7, which handles a failed create
  or a Pod that lived only seconds.
- **Sum ≠ amount.** Write only a MISMATCHED period row. The buckets stay ALLOCATED, and readiness for
  overlapping leases is `DISPUTED`. This overrides billing spec §6's per-bucket DISPUTED for invoice
  mismatches; malformed provider rows are still DISPUTED per bucket under R4.
- **A later MATCHED for a period** that overlaps a MISMATCHED row requires
  `supersedes_evidence_id` + `actor_ref` + `reason`, which is audited. Without them it is refused.

Spend is never lowered:
- A lower or higher invoice is a mismatch, and nothing is decremented.
- After a downward provider revision, the invoice can match the latest sum while the posted spend is
  higher, because negative deltas are evidence only. The BILLED settlement then uses the posted sum
  (R7), and the overstatement is stored as evidence.

**R6. Idempotent replay** (fixes G6).
- **Replay key:** (account, pod, period, `evidence_sha256`).
- **Identical replay** (same key, amount, currency and outcome) returns the stored outcome, with no
  new rows and no exception.
- **Same key with a different amount, currency or period** raises a typed `IdempotencyConflict`.
- **New evidence for an already-verified period** raises a typed `Conflict`, unless it is an
  explicit supersede (R5).
- `IntegrityError` never reaches a caller.

**R7. Lease billing finality and hold release** (fixes G5/G9/G16).

Lease L (reservation R, account A, Pod P) is **BILLED** iff all of these hold:
- (a) L is terminal and `compute_window_end_at` is set (the transfer instant, or the verified
  stop/terminate);
- (b) L's compute window, and any storage window L's episode owns on P up to `terminate_verified_at`,
  are covered **by overlap**, with no gap, by MATCHED period evidence (bucket-backed or
  MATCHED_ZERO);
- (c) every covering bucket's latest revision is `INVOICE_VERIFIED` and there is no open
  MISMATCHED period row;
- (d) there is no unresolved RECOVERY allocation on any covering bucket.

When L is BILLED:
- Post one deterministic SETTLEMENT on R with `cost_basis=BILLED`. The amount is the sum of GPU
  ACCRUAL + ADJUSTMENT postings on R, which is no new money; it may be 0.
- The ledger's SETTLEMENT releases exactly the unused remainder, including from an EXPIRED R.
- A replay is a no-op.
- Store any posted-versus-invoice overstatement as evidence.

**Readiness** per lease is one of:
- `PENDING_PROVIDER_FINALITY` (the window is incomplete, or buckets are still open or unqueried);
- `AWAITING_INVOICE`;
- `DISPUTED`;
- `RECOVERY_REQUIRED`;
- `BILLED`.

It also reports `pending_since`. `REOPENED` is derived, not stored: it means some bucket revision is
newer than the BILLED settlement. That revision posts an ADJUSTMENT on the closed R; a positive
amount adds to settled and a negative one is evidence only.

Replace `accounting_readiness` with this function, using overlap for both coverage and sums.

**R8. Structural settlement gate, no boolean** (fixes G7/G13/G15).
- **Required port.** `settle_reservation_for_lease`, `LeaseService.__init__`, `Janitor.__init__`
  and their builders take a **required** `finality: LeaseBillingFinality`. There is no default and no
  flag.
  - The constructors themselves check the pairing (`finality.provider_id == provider id`), so
    calling a constructor directly does not bypass it.
- **Two implementations:**
  - `SyntheticUsageFinality` keeps today's offline behaviour exactly, and raises if constructed
    outside OFFLINE_MOCK.
  - `RunpodInvoiceFinality(BillingRepository)` applies R7. Until BILLED it keeps the hold and posts
    nothing.
- **`BudgetService.release` is guarded.** It refuses any reservation bound to a `pod_leases` row
  with provider `runpod` unless `create_requested_at IS NULL AND pod_id IS NULL`, which is durable
  proof that nothing was sent.
  - `_close_claim_without_pod` and the janitor's `_close_without_compute` use that proof, not a list
    miss.
  - Every other close goes through R7, and a BILLED total of 0 is a SETTLEMENT.
- **Runpod shutdown terminates.** The final release of a Runpod chain (no transfer) runs: stop →
  **terminate** → verified read-back → `terminate_verified_at` → close ownership.
  - The fake provider keeps today's stop-only path.
  - A warm transfer sets the old lease's `compute_window_end_at` to the transfer instant.
- **Janitor sweep.** The terminal-lease sweep selects reservations in `ACTIVE` **and** `EXPIRED`
  state. It retries finality with `next_finality_check_at` backoff (pending is not an error and must
  not hot-loop).
- **Pending result.** `ShutdownResult` (or its equivalent) reports `billing_pending=True` instead of
  a bare `settled_micro_usd=0`.
- **Offline.** `make pilot` behaves exactly as before: W01–W12, two gates, 16 exports, 303,000
  synthetic micro-USD.

**R9. Live wiring** (fixes G8/G10/G14).

`live_world`:
- requires a `BillingRepository`;
- builds the lease service and janitor with `RunpodInvoiceFinality`;
- computes `billing_state` from readiness;
- **deletes the unconditional raise** and keeps every earlier fail-closed check;
- still performs no DNS, no credential resolution and no request during construction.

`billing_history` accepts **durable DB ownership proof** when the Pod is absent at the provider. The
proof is a `pod_leases` row with this `pod_id`, a matching owned-tag namespace, the same
`provider_account_ref` and `terminate_verified_at` set. Without it, the call is refused as today.

Janitor billing ingestion:
- covers owned Runpod Pods whose leases are not BILLED, over the lease windows;
- is effect-gated and uses backoff;
- maps records with exact micro-USD (G10);
- ingests closed buckets only (R4) and records EMPTY or UNKNOWN as such;
- then runs finality (R7).

**R10. Quote attestation** (fixes G11). Add these fields to `RunpodQuoteAttestation`:
- `quote_id`;
- `currency` ("USD" only; anything else is refused);
- `persistent_volume_gb`;
- `max_storage_exposure_micro_usd`;
- `provider_account_ref` (a non-secret label). This is written to `pod_leases` at claim and used in
  the bucket identity.

Cross-check every field both ways against `RunpodQuoteEvidence`. `PresetRecord`'s node-schema and
output-ceiling fields stay out of scope (a guardian contract change). The canary authorization pins
`node_schema_sha256`/`output_controls_sha256`, and the runbook records this limitation.

**R11. Canary runner and invoice entrypoint** (fixes G12).

The command is `python -m microdrama.pipeline.canary {preflight,execute,invoice} --authorization
<file.json>`. The authorization schema lives in the runbook, plus a fake-valued example. It carries:
- operator, change ref, `hard_stop_utc`, `max_wall_seconds`;
- the quote, with R10 fields, GPU, rates and USD;
- caps: spend in micro-USD *including* storage and the shutdown reserve, storage GB, prompts,
  attempts;
- the rights route (id, subject, version, territories, evidence id, expiry);
- pins: image digest, workflow, node schema, output controls, preset id/version;
- `credref:` names only;
- the namespace and `provider_account_ref`;
- prompt/reference inputs as content hashes.

`preflight` is the default:
- it runs every gate and needs no network or credential value;
- it prints the plan and `authorization_sha256`.

`execute --authorization-sha256 <hex>`:
- **Refuses** on a sha mismatch, `now ≥ hard_stop_utc`, an expired quote, a wrong mode or flag, or a
  cap above `episode_cap_micro_usd`.
- **Then runs runbook steps 1–6 through the composed `live_world` only:**
  - before the first prompt, check the `/object_info` digest against `node_schema_sha256`; on a
    mismatch, stop and terminate and submit nothing;
  - enforce the deadline with stop + terminate;
  - the janitor is the backstop;
  - write the canary record JSON under `microdrama/evidence/provider-qualification/`, with honest
    billing readiness.
- Its default transports are the real ones that `live_world` builds. **T045 exercises `execute` only
  inside pytest with injected fixture transports.** Running it for real is T031, under the
  operator's authorization.

`invoice` wraps `verify_invoice_period`. It stores only the sha256 of the evidence file.

Nothing in the runner prints credential values, `Authorization` headers or the env.

## Acceptance (T045 → ACCEPTED)

- Every ruling is pinned by tests. Defects G1, G2, G6, G7, G13, G15 and G16 each have a test that was
  red first, on real PG.
- Real-PG cases cover:
  - two warm leases in one bucket;
  - partial and uncovered existence;
  - a failed attempt;
  - a post-stop disk charge up to the verified terminate;
  - a prospective owner change;
  - EMPTY/UNKNOWN, billed zero, a positive revision delta;
  - an EXPIRED hold reaching BILLED;
  - a transferred-away lease reaching BILLED;
  - restart readback.
- Existing fixtures and tests that pre-built verified buckets, or used observed_at < bucket_end +
  settle_lag (`examples.py:~1052`, `test_budget_billing_reconciliation.py:~163-185`), are rewritten
  onto the new paths without weakening any assertion.
- A composed fixture canary runs through `canary execute`: reserve → create → `/object_info` check →
  submit → output copy + checksum → stop → terminate → janitor ingest of the absent Pod → hold kept
  as pending → `canary invoice` match → BILLED settlement releases the exact remainder.
  - Replaying every step adds no money.
  - A mismatch run keeps the hold and gives DISPUTED.
  - The deadline path terminates.
- `make check` ends `make check: all offline checks passed`, and `make pilot` exits 0 with unchanged
  numbers, both under CPUQuota=45%.
- A review by a different model, with rulings closed. T045 acceptance does not authorize T031.

## Critique record (revision 1)

Sonnet 5.5's pre-build critique found these BLOCKING issues, all accepted:
- B1: no durable create-request or terminate time → R0, R1, R8.
- B2: billing can't be read after terminate, and shutdown only stops → R8, R9.
- B3: a verified revision collides with the raw-hash unique key and gives zero-delta postings → R0,
  R2, R5.
- B4: CPU/DISK can't post to a GPU hold → R2.
- B5: EXPIRED holds are never re-swept → R8.
- B6: a transferred-away lease is never BILLED → R0, R7.

SHOULD-FIX items, all accepted:
- S1: drop account-scope evidence;
- S2: billed-zero route;
- S3: posted ≥ invoice is evidence;
- S4: fixture rewrites and a home for skipped buckets;
- S5: close-once trigger instead of a closure table;
- S6: constructor pairing check plus the release guard;
- S7: lease windows from `pod_leases`;
- S8: `creating_lease_id`;
- S9: per-bucket API made internal.

Partly accepted: "cut `execute` from T045". Execute stays built, but T045 runs it only under pytest
with fixture transports. Without it the T031 authorization packet would have no exact command to
approve, and the runbook requires T045 to supply that composed command.
