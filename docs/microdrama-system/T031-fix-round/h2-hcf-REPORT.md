# T031 H-2 HCF build report (Codex P4/P5 findings, fix round 3)

Builder: GLM-5.3 build session, 11 Nov 2026. Branch `feat/t031-fix3`, base `4e28514`
(P5 tip + formatting). Findings: [codex-review-h2-p4p5.md](codex-review-h2-p4p5.md);
rulings in the task brief (HC-2 ruled first, as package F1).

## Status

| Pkg | Findings | State | Commit |
|-----|----------|-------|--------|
| F1 | HC-2 (ruling 1: revert + benchmark layer) | **DONE** | `6db5fe8` |
| F2 | HC-6 lock helper + inventory; HC-5 ownership | **DONE** | `9b736da` |
| F3 | HC-1 storage finality; HC-7; HC-8; HC-9 | **DONE** | `e521653` |
| F4 | HC-3 R7 recoverability; HC-4 terminal replay | pending | — |
| F5 | HC-10 test proofs; HC-11; HC-12 | pending | — |

## F1 — HC-2: revert the out-of-spec canonical receipt conversions; benchmark-layer late billing (commit `6db5fe8`)

### What was reverted

- `budget/service.py` `_record_gpu_interval`: the ACCRUAL→ADJUSTMENT conversion for
  closed reservations (added in P4's `941ab6d`) is removed — it rewrote the stored
  receipt AFTER the replay check, so a crash between the interval post and the
  `accrued_until` advance replayed the ACCRUAL payload against the stored ADJUSTMENT
  (`IdempotencyConflict`, service.py:1123).
- `rendering/leases.py` `settle_from_recorded_usage`: the closed-state kind flip
  (SETTLEMENT→ADJUSTMENT, same deterministic receipt id) is removed — an ordinary
  replay after a successful settle rebuilt the same identity with different content,
  and on a closed reservation it restated `_settlement_totals` (which already includes
  prior late ADJUSTMENTs) as a second final amount.

Both files are byte-identical to `45e4f2a` again (`git diff 45e4f2a -- <files>` empty).

### Where the need is met instead (benchmark layer)

The §6.4 incident path must still bill the discovered pod's cost on the closed
COMPUTE hold. The ledger's own rule (`Ledger.apply_receipt`) admits only ADJUSTMENT
after a close — the canonical layer already supports late billing; only the caller
must construct the receipts. The podless-create shape exists only in the benchmark
(`resolve_create` is T031's operator path; the plain `BudgetService` the offline
pipeline uses never sees a closed hold with late pod cost), so both behaviours live
on `ExperimentBudgetService` (`benchmark_experiments.py`), applied BEFORE the
canonical replay comparison:

- `record_gpu_interval`: an ACCRUAL whose reservation is SETTLED/RELEASED is
  normalized to an ADJUSTMENT with a `late:`-prefixed receipt identity
  (`uuid5(RENDERING_NAMESPACE, "late:<receipt_id>")`,
  `provider_receipt_id="late:<original>"`), basis IDLE (the canonical loop's own
  attribution for non-ACCRUAL kinds). Identity and content are stable across
  replay; a pre-close ACCRUAL and a post-close late ADJUSTMENT can never collide
  on one receipt key (the interval's exclusion attribution still refuses overlaps).
- `record_usage`: a SETTLEMENT presented to a closed reservation reuses the
  recorded settlement (returns the recorded charge as `replayed`; posts nothing) —
  mirroring `settle_billed_lease`'s one-final-per-reservation reuse. Genuinely new
  late cost arrives only as ADJUSTMENT deltas through `record_gpu_interval`.

### Red → green (tests first, `tests/unit/rendering/test_t031_hcf_f1_receipts.py`)

Red against committed HEAD `4e28514`: `4 failed in 10.72s`
- settle replay: `IdempotencyConflict: receipt replayed with different content`
  (service.py:1124) — Codex's exact probe;
- closed+late-100: two ADJUSTMENT rows (the restated settle) — 100 became 200;
- crash replay: `IdempotencyConflict` on the replayed interval;
- incident path end-to-end: interval ADJUSTMENT 900250 **plus** settle restatement
  ADJUSTMENT 900250 (`podlease-settle:...` reposts the total).

Green: `4 passed in 10.07s`.

Regressions (all green): p4+p5 `26 passed in 55.30s`; AT-26 canonical/canary
(t045_billing_ingestion + finality_port + canary_gateway + lease_claim/lifecycle/
shutdown) `99 passed in 71.98s`; (t045_live_world + live_world + t045_timing +
quote_attestation + canary_db + canary_runner) `75 passed in 22.67s`;
p3+comfy_recover `46 passed in 138.66s`; benchmark_experiments +
world_composition + authorization + p1 + p2 `67 passed in 175.87s`.
`make lint` clean (ruff format applied to the new test).

### Judgement calls (F1)

1. **The closed-hold-late-cost shape is benchmark-only**, so the benchmark's budget
   boundary (`ExperimentBudgetService`) is the layer that meets the need — no
   canonical change kept. The production composed world
   (`build_experiment_world` → `RunpodInvoiceFinality`) already reuses finals on
   closed reservations canonically (`settle_billed_lease`), and its accrue path goes
   through the world's `ExperimentBudgetService`, which the override intercepts.
2. **Late identity is `late:`-prefixed, not the original receipt id**: the stored
   content must never depend on when a receipt was presented; reserving an identity
   for late billing makes the crash-replay comparison stable and prevents any
   pre-close ACCRUAL from colliding with a post-close late post. Residual edge: an
   ACCRUAL posted while open, followed by a close and a replay of the same interval,
   refuses with the canonical "interval already attributed" Conflict — honest, never
   a double count.
3. **A SETTLEMENT onto a closed hold with no recorded settlement charge** (a
   RELEASED hold) falls through to the canonical post and its ledger Conflict —
   never a synthesized final.
4. **The synthetic settle path keeps its pre-P4 semantics for everyone else**: the
   plain `BudgetService`/`SyntheticUsageFinality` composition (offline pipeline,
   non-benchmark) never sees the shape; the ledger's refusal is the honest answer
   there.

### Uncommitted files

- `microdrama/tests/unit/rendering/test_t031_hcf_f1_receipts.md` — an empty stray
  file created by a typo in this session (a `.md` instead of `.py`); deletion
  commands are forbidden in this brief, so it stays empty and untracked. Safe to
  remove by the operator.

## F2 — HC-6 (the one ordered lock helper) + HC-5 (live ownership everywhere) (commit `9b736da`)

### What shipped

- **HC-6**: `_lock_gate_rows` is now the ONE §6.1 ordered row-lock helper — A rows
  (by id) → the experiment's L rows (by id) → D → S rows (by id) → linked R rows
  (by id) → O rows → upload rows (by key) — and every listed transaction locks
  through it after its account/categories/E prefix:
  - `_acquisition`, `_claim_sample`: the helper FIRST (the old `_claim_sample` locked
    S then re-locked A through the helper — S-before-A; `_acquisition` locked one A
    row, then L, then re-locked all A rows through the helper — A-after-L);
  - `_advance_owned`'s coordination transaction: A(row) before D(slot) (the HB-8
    comment claimed this order but the SQL locked D first);
  - `resolve_create`: the billing advisory (billing.py key 451051) BEFORE its L row
    (the wrapper's own order; the in-tx core re-takes both re-entrantly);
  - both sweep finalization transactions: the helper after E, so the §6.3 lease read
    is L-locked inside the decision, and the storage release / upload fence /
    failed-sample projection / slot clear / outcome write / prompt-hold releases all
    touch rows already locked in the shared order (the old shape locked R
    reservations and wrote uploads before the D/S writes).
- **HC-5**: `_claim_sample` and the extracted `_activate_acquisition` validate the
  FULL live ownership (`_assert_coordination`: BOTH durable tokens, live leases) —
  not the slot token's value / the A row alone; `_mark_create_ambiguity` and
  `_mark_upload_ambiguity` accept `coordinator_token` and refuse a fenced
  coordinator (a stalled original create returning after takeover/fencing can no
  longer rewrite its acquisition to UNKNOWN and collide with a newer acquisition's
  partial-index slot); `ComfyRenderService.submit/submit_v2` accept an optional
  `send_authorizer` (default None — canonical behavior unchanged) that runs INSIDE
  the first-send claim transaction, and `_advance_owned` passes its ownership
  assertion, so a coordinator fenced between the dispatch gate and the claim
  consumes no first-send right and sends nothing. Takeover handlers stay tokenless
  (§5.2); effects authorized before fencing stay with reconciliation (I2).

### Red → green (`tests/unit/rendering/test_t031_hcf_f2_locks.py`)

Red at `6db5fe8`: `5 failed` — the gate completed while an L-only adoption held the
lease (behavior), the claim accepted a half-fenced coordinator (behavior),
`AttributeError`/`TypeError` on the missing ownership surfaces, and the fenced
coordinator POSTed (`fake-prompt-0001` submitted while fenced). Green:
`5 passed in 18.27s`. Regressions: p4+p2 `27 passed in 112.78s`; p1+p5
`25 passed in 75.48s`; p3+F1 `33 passed in 120.70s`; benchmark_experiments +
world_composition + comfy_recover `33 passed in 79.07s`; v2_comfy_submit + lease
suites + authorization `64 passed in 27.57s`. `make lint` clean.

### Corrected transaction inventory (from the actual SQL, post-F2)

Shared order: 1 account, 2 categories, 3 E, 4 A (by id), 5 billing advisory then L
(by id), 6 D, 7 S (by id), 8 R (by id), then R5 suffix: O (by id), uploads (by key).
`_lock_gate_rows` = steps 4–8 + suffix, as one helper.

| Function | Locks in order | Writes |
|---|---|---|
| `execute` | account, categories, E | predicated state write |
| `_advance` | account, categories, E, D | slot coordinator token take |
| `_advance_owned` coordination | account, categories, E, A(row), D(slot) | acquisition coordinator token |
| `_activate_acquisition` | account, categories, E, A(row), D(slot) + ownership assertion | `state='ACTIVE'` |
| `_acquisition` | account, categories, E, helper | acquisition intent + linked COMPUTE/STORAGE holds |
| `_claim_sample` | account, categories, E, helper + ownership assertion | PROMPT hold, sample CLAIMED, slot occupancy |
| `_gate`/`_gate_in_tx` | account, categories, E, helper (+ assertion for dispatch) | none (refusal only) |
| `_observe` | E, D(slot), S(row) (+ assertion) | projection, slot clear, R6 outcome |
| `finalize_terminal` (3+4) | account, categories, E, D(slot), S(row) | projection, slot clear, R6 outcome |
| `_mark_upload_ambiguity` | account, categories, E (+ A, D, assertion when coordinator-driven) | E state |
| `_mark_create_ambiguity` | account, categories, E, A(row) (+ D, assertion when coordinator-driven) | A + E state |
| `_enter_grace` | account, categories, E, A(row) (+ assertion) | recovery_started_at/deadline, E state |
| `_deadline_fence` | account, categories, E, A(row), helper | shorten-only deadline, revoke both tokens |
| `resolve_create` | account, categories, E, A(row), advisory 451051, L(row) | NO_CREATE_PROVEN, window end; canonical audit + zero settlement; never STORAGE |
| `sweep` NO_CREATE finalization | account, categories, E, helper | STORAGE release (the only place), window end |
| `sweep` cleanup finalization | account, categories, E, helper | storage release, upload fence, sample FAILED, slot clear, outcome, prompt releases, A state |
| canonical `provider_ops.begin`/`record_result` | reservation (FOR SHARE on begin) then O | suffix-only |
| canonical first-send claim (`_submit_bound_graph`) | O row via begin; `send_authorizer` predicate reads ownership inside the tx, takes no locks | append-only claim event |
| `_SealedNativeInputs.stage` | A(row) then upload row | upload intent; suffix-only |
| `resolve_podless_create_in_tx` | caller holds 1–5; L re-entrant | audit row, lease window, zero-BILLED receipt |
| operator terminal transition (`resolve_sample`) | O row; commits before financial finalization | audit + terminal state |

### Judgement calls (F2)

1. **The helper locks supersets** (all A/L/S/R/O/upload rows of the experiment) at
   every listed site — slightly wider serialization than the minimal per-site sets,
   but one order for everyone is the HC-6 requirement, and single-experiment row
   counts make the width immaterial.
2. **The `send_authorizer` seam is a minimal additive canonical parameter**
   (default None; canonical suites unchanged): the alternative — validating the
   coordinator inside the claim transaction from the benchmark layer without a hook
   — would require duplicating the canonical begin/claim logic. The predicate READS
   the ownership rows without locking them inside the suffix-only claim transaction
   (locking D/A there would invert the §6.1 order); a fence committing in that
   window leaves the effect "authorized before fencing" — reconciliation owns it
   (I2), which Codex's fix explicitly retains.
3. **Upload and create sends keep their gate authorization** (token checked in the
   dispatch `_gate` immediately before the send); only the prompt claim gained the
   in-transaction predicate — Codex's finding names the prompt claim specifically.
4. **`resolve_create` takes the advisory by key literal** (451051, billing.py's own)
   with a comment, rather than refactoring billing.py to expose a helper — that file
   is canonical and outside the permitted edits.

### Uncommitted files

- `microdrama/tests/unit/rendering/test_t031_hcf_f1_receipts.md` — empty stray file
  (see F1).

## F3 — HC-1 invoice finality; HC-7; HC-8; HC-9 (commit `e521653`)

Resumed from the z.ai-limit stop: the F3 WIP was restored from stash
`1f9bc18` (applied by SHA, never popped; the entry is dropped after this
commit, `wip/t031-hcf-f3-stash` kept for the orchestrator).

### What shipped

- **HC-1 (ruling 2)**: "billing ready" for a CONTRADICTED no-create
  attestation is now the canonical INVOICE finality of the discovered
  resource — `discovered_resource_billing_final(tx, lease)`
  (benchmark_experiments.py): readiness must be `BILLED` AND either no
  reopened liability, or MATCHED invoice period evidence covering the whole
  liability window (compute window, extended to every storage-ownership end,
  no gaps). The podless resolution's zero final never counts: its
  post-contradiction interval accounting alone drives readiness to
  `BILLED(reopened=True)` with zero invoice evidence — Codex's exact probe.
  Used by BOTH the U5 predicate (benchmark_experiments) and the sweep's
  NO_CREATE finalization gate (benchmark_service). The pre-decision
  zero-settling of EXPIRED STORAGE holds is gone — `settle_expired_unused_hold_in_tx`
  rides the SAME locked finalization decision (ACTIVE release and EXPIRED
  closure in one transaction).
- **HC-7**: `ExperimentBudgetService.reserve_in_transaction` overrides the
  transaction-owning canonical core with the same recovery/cleanup mode
  refusal as `reserve`/`reserve_linked` (`is_shutdown_or_cleanup` grants
  preserved) — a composed recovery world can no longer reserve ordinary work
  through the inherited entry point.
- **HC-8**: in the recovery readback, a non-BOUND binding persists the
  durable ambiguity episode BEFORE exiting (`_enter_grace`, idempotent,
  shorten-only — SC2-2 keeps a later ambiguity's episode), and an already
  exhausted episode routes through the fenced cleanup sweep instead of a
  doomed bounded lookup.
- **HC-9**: `_shorten_recovery_deadline` recomputes the effective deadline
  UNDER the §6.1 locks (account → categories → E → A row) before bounded
  recovery work, persists ONLY a shortening, and the callers fence
  immediately when it has elapsed (both the readback path and the UNKNOWN
  grace path). The aggregate GPU deadline counts EVERY open window
  (`consumers = max(open_windows,1)`, `reserved = consumers × margin`) — the
  late-contradiction scenario's two simultaneous windows each consume and
  each need a shutdown tail. The funded-window candidate reads only holds
  that still own funds (`state IN ('ACTIVE','EXPIRED')`).

### Red → green (`tests/unit/rendering/test_t031_hcf_f3_finality.py`)

Red against committed HEAD `9b736da` (edits absent):
`6 failed in 12.92s` — all six (HC-1 ×2, HC-7, HC-8, HC-9 ×2).
Green: `6 passed in 15.40s`.

Regressions (all green): p4+p5 `26 passed in 57.31s` (after the HC-1
semantics updates below); p1+p2+p3 `55 passed in 241.53s`; HCF F1+F2+F3 +
hb13 + lf `23 passed in 44.72s`; experiments + world_composition +
comfy_recover + authorization `58 passed in 89.40s`; AT-26 canonical/canary
(t045_billing_ingestion + finality_port + canary_gateway + lease_claim/
lifecycle/shutdown) `99 passed in 77.44s`. `make lint` clean.

### Regression tests updated to the binding HC-1 semantics

Codex's HC-1 Fix is binding ("a reservation settled before the contradiction
is never evidence"), so four P4 tests and the F1 incident test that asserted
the refuted early clearing were strengthened, not the code weakened:

- AT-06 (adoption_after_resolution), AT-07, HB-9: the sweep now runs twice —
  first sweep completes the discovered pod's terminate→verify tail and
  RETAINS storage (asserted); `_bill_lease_to_billed` drives the canonical
  invoice tail; the second sweep finalizes.
- HB-12: ownership-closed + settled reservation now asserts U5 KEEPS
  blocking while the invoice pends, then clears after the invoice tail.
- F1 incident path: same two-phase shape; the reservation's charge-count
  assertions (exactly one late ADJUSTMENT, settled total never restated)
  are unchanged and still hold after finalization and replay.

### Judgement calls (F3)

1. **No canonical code changed.** The invoice-finality predicate lives at
   the benchmark boundary. Canonical `_lease_readiness_in_transaction`
   (billing.py) — including its `BILLED(reopened=True)` derivation from
   post-settlement accounting — is untouched; the benchmark layer requires
   matched invoice evidence ON TOP of it.
2. **The adopted late pod's lease window is degenerate BY canonical design,
   and that is honoured, not fought.** The podless resolution bounds
   `compute_window_end_at` at the no-create close; migration 0025's set-once
   trigger forbids ever changing it, and §6.4 says the janitor rewrites no
   window. An attempted janitor fix (clear the disproved bound at adoption,
   re-bound at the verified terminate) was written, rejected by the set-once
   trigger, and fully reverted — janitor.py is byte-identical to HEAD.
   Consequences, all canonical and all driven through their real paths in
   tests: the coverage window extends to storage-ownership ends (mirroring
   canonical readiness); the allocation engine parks the pod's invoice GPU
   in the recovery pool (empty lease existence window); the audited
   `BudgetService.resolve_billing_recovery` is the convergence — the test
   helper `_bill_lease_to_billed` ingests the covering bucket, resolves the
   recovery allocation to the owning episode, and verifies the period
   (MATCHED) under PAID_BENCHMARK service settings exactly like the
   canonical reconciliation suite.
3. **The funded-window deadline candidate now filters by hold state.** A
   SETTLED/RELEASED hold's `expires_at` is history: in the spec's own
   late-contradiction scenario gen-1's hold is settled at the podless zero
   while its REOPENED window is (correctly) counted by the aggregate bound —
   letting the dead expiry into the min() collapsed the effective deadline
   onto a closed window's past expiry (observed: 00:34 vs the correct 02:29).
4. **HC-9's recompute test seeds an acquisition-owned COMPUTE hold**: AT-14
   builds its acquisition row directly (only a lease-level link exists), so
   the test inserts the hold + link the real `_acquisition` flow would have
   created, then moves its expiry inside the shutdown margin.
5. **The §5.3 cleanup-path storage release keeps its pre-existing gate**
   (`receipt["storage_final"]` from the world's readiness) — Codex's HC-1
   names the NO_CREATE sweep branch and U5's predicate, both fixed here; the
   normal-cleanup gate was reviewed, not flagged, and is left for a future
   round if the orchestrator wants the same strictness there.

### Uncommitted files

- `microdrama/tests/unit/rendering/test_t031_hcf_f1_receipts.md` — empty
  stray file (F1, see above).
- `microdrama/tests/unit/rendering/zz_debug_f3.py` — docstring-only
  placeholder where this session's trace probes lived (deletion forbidden);
  safe to remove.

## Resume here

F4 — HC-3 (R7 recoverability refuses `--force-unrecoverable` on positively
recoverable work, including client-ID discovery and EXPIRED reads through
the RECOVERY composition); HC-4 (terminal replay completes every stage:
matching-slot cleanup, output/linkage repair, failed-outcome repair, U4
includes missing failed outcomes, durable success assets).
