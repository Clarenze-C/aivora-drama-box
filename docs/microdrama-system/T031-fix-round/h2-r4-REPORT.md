H2-R4: ALL FIXES DONE

# T031 H-2 fix round 4 (R4) build report — HD-1..HD-3 + HC-10 proof gaps

Builder: GLM-5.3 build session, 12 Nov 2026. Branch `feat/t031-fix3`, base `7060e02` (HCF F5).
Findings: [codex-review-hcf-final.md](codex-review-hcf-final.md) (HD-1, HD-2, HD-3 — Codex's
"Fix" paragraphs binding); rulings: [rulings-hcf-final.md](rulings-hcf-final.md) (HC-6, HC-9,
HC-11, HB-13 broad = known limits, untouched). Verified by the orchestrator only (no 4th Codex
round).

Every pytest below ran from `microdrama/` under
`env PATH="/usr/sbin:$PATH" MICRODRAMA_EXECUTION_MODE=OFFLINE_MOCK MICRODRAMA_PAID_REQUESTS_ENABLED=false MICRODRAMA_CLOUD_RESOURCES_ENABLED=false MICRODRAMA_PUBLIC_ACTIONS_ENABLED=false systemd-run --scope -p CPUQuota=45% --quiet .venv/bin/python -m pytest <files> --basetemp=/tmp/t031-r4-basetemp -p no:cacheprovider -q`
(the "cmd" lines below abbreviate only the pytest selector).

## Status

| Pkg | Item | State | Commit |
|-----|------|-------|--------|
| R1 | HD-1 (BLOCKING) | **DONE** | `92f7b51` |
| R2 | HD-3 (BLOCKING) + HC-10 proof gaps | **DONE** | `621e49e` |
| R3 | HD-2 (SHOULD-FIX) | **DONE** | `0cda424` |

Final verification net at `0cda424` (all nine H2/HCF test files incl. the new
`test_t031_hcf_r4_hd1_probe.py`): **`85 passed in 223.11s`**. `make lint` clean.

## R1 — HD-1: bind the RECOVERY probe before probing; local probe failures never reach the force path (commit `92f7b51`)

### The fix (`pipeline/benchmark_service.py`, `resolve_sample`, BOUND branch)

The newly composed RECOVERY world is now **bound to the owning acquisition before any probe
runs**:

- `self._world(mode="RECOVERY", ...)` composition raising → `Conflict` (refuses even with
  force);
- `recovery_probe.bind_for_recovery(acquisition_id)` raising → `Conflict` (refuses even with
  force);
- the probe binding returning anything other than `BOUND` (incl. `INDETERMINATE`, or a probe
  object with no binder at all) → `Conflict` (refuses even with force);
- the probe's live read itself raising `EffectDenied` → `Conflict` (refuses even with force)
  — the composition refused the effect, which is a fact about the probe, never about the work.

Only after a `BOUND` probe does `reconcile_unknown` run, and only its own evidence
(`NeedsReconciliation` on empty/missing history, conflicting matches, etc. — broad `except`
→ `probed_state = None`) still reaches the R7 force path. The factory-less service
(`world_factory is None`) probes through its caller-supplied world, which is re-bound and
required `BOUND` like any other probe.

### R7 text relied on (spec §7.3, "Live-source rule (R7, precedence)")

> - Ordinary resolution requires `bind_for_recovery = VERIFIED_SOURCE_GONE`.
> - `BOUND` with **positively recoverable work or usable output** requires reconciliation and
>   refuses operator resolution, **even with force**.
> - Reachability alone is not recoverability: empty, missing, conflicting or unusable history
>   stays ambiguous.
> - Reachable-but-unrecoverable cases, and `INDETERMINATE` cases, require
>   `--force-unrecoverable` plus the recorded attestation. The override is recorded in the
>   audit.
> - Identical-attestation replay is accepted before any live-source check.

Reading: the force path is reserved for facts **about the source** — "reachable-but-
unrecoverable" history and "INDETERMINATE" sources, i.e. what a successfully bound probe
observed. A composition/binding/`EffectDenied` failure of the probe itself establishes
nothing about the source (it is not "reachable", and its history was never read), so R7
grants it no route to `--force-unrecoverable`; the resolution must refuse.

### Tests (`tests/unit/rendering/test_t031_hcf_r4_hd1_probe.py`)

The factory returns **independently constructed, initially unbound** clients per mode: every
factory call builds a NEW `_UnboundUntilBoundFake` (a fresh `FakeComfyClient` that refuses
every live effect until `bind_pod_endpoint` — the production `PikaHttpClient`'s unbound
refusal), a NEW `ComfyRenderService` over it and a NEW world adapter, sharing only the
durable db/leases/jobs/budget and the pod-side server state.

- (a) `test_hd1_recoverable_work_refuses_force_through_fresh_unbound_probe` — an accepted
  prompt discoverable by deterministic client id (UNKNOWN without `external_id`) refuses
  resolution even with force, through the fresh probe.
- (b) `test_hd1_recovery_probe_bind_failure_refuses_force[RAISE|INDETERMINATE]` — the
  RECOVERY probe's own binding raising / not returning `BOUND` refuses even with force (the
  CLEANUP world keeps the honest binder; only the RECOVERY mode is shaped).
- (c) `test_hd1_bound_unrecoverable_still_resolves_with_force` — control: probe BOUND, source
  answering, no prompt by the deterministic client id → `PolicyDenied` without force,
  resolves with force, outcome `FAILED`.

### Red → green

Red against committed `7060e02` (fix restored via `git show HEAD:… > …`, diff saved to
`/tmp/t031-r4-hd1-fix.diff` and re-applied after):

- cmd: `… -m pytest tests/unit/rendering/test_t031_hcf_r4_hd1_probe.py …`
- summary: **`3 failed, 1 passed in 11.75s`**
- (a) `Failed: DID NOT RAISE Conflict` (force resolved positively recoverable work — Codex's
  exact defect), (b) both params `Failed: DID NOT RAISE Conflict`, (c) passed (pre-fix
  control, as expected).

Green with the fix: **`4 passed in 13.07s`** (after ruff format re-run: `4 passed in 12.89s`).

Regressions (green): `test_t031_h2b_p4_resolution.py + test_t031_h2b_p5_terminal.py +
test_t031_hcf_f4_r7_replay.py` → **`32 passed in 72.80s`**. `make lint` clean (ruff format
applied).

### Judgement calls (R1)

1. **A probe without a `bind_for_recovery` method also refuses** (`probe_binding != "BOUND"`
   covers `None`): a probe that cannot bind cannot verify it reached the source, so no
   attestation may rest on it. No existing composition hits this (every factory in the suite
   returns worlds with the canonical binder).
2. **`EffectDenied` from the probe's live read is treated as a local failure, not evidence.**
   `EffectDenied` is raised only by our own boundaries (unbound client, mode/guard refusals,
   offline effect refusals) — never by the provider's history — so it can never testify that
   the work is unrecoverable. All other probe exceptions (`NeedsReconciliation` on empty
   history, conflicting-match `Conflict`, unreachable server) remain R7 evidence and keep
   reaching the force path (test (c) proves the refusal did not widen).
3. **The bind is required to return `BOUND` exactly.** The CLEANUP world's binding already
   returned `BOUND`; a RECOVERY probe that cannot reproduce that binding (e.g. the pod stopped
   between the two reads) leaves recoverability unknown → refuse, never force.

## R2 — HD-3 (translated deadlocks pass the race proof) + the HC-10 proof gaps (commit `621e49e`)

All changes are test-only; no production code changed in R2.

### HD-3 — the race whitelist (`test_t031_h2b_p4_resolution.py`)

- `_deadlocks` (same name, strengthened body) now fails the proof on a deadlock/lock timeout in
  **both** shapes: the raw psycopg error (40P01/55P03) **and** the `ServiceUnavailable` the
  production translator (`persistence/db.py translate_db_error`) produces on every worker path
  through `Database.transaction`.
- `test_at21_ambiguity_vs_admission_vs_sweep_ordered` no longer accepts every `MicrodramaError`:
  an explicit `not isinstance(exc, ServiceUnavailable)` assertion plus a whitelist of the specific
  expected refusals — `_expected_race_refusals()` = `(AdmissionBlocked, NeedsReconciliation,
  PolicyDenied, Conflict)`. The whitelist was verified precise on the green run (the race records
  only those).
- New `test_at21_race_proof_rejects_translated_deadlock_and_lock_timeout` proves the proof works:
  for each of SQLSTATE 40P01 and 55P03 it drives the REAL translator
  (`psycopg.errors.lookup(...)` → `translate_db_error`) and asserts **every** strengthened
  assertion FAILS on the injected translated failure (`pytest.raises(AssertionError)` each).

Red (pre-R4 proof semantics with the injection test present, scratch branch
`t031-r4-red-oldproof` @ `ccc9b53` — WIP commit reverting only the checker body and the
whitelist): cmd `… -m pytest
tests/unit/rendering/test_t031_h2b_p4_resolution.py::test_at21_race_proof_rejects_translated_deadlock_and_lock_timeout …`
→ **`1 failed in 2.87s`** — `Failed: DID NOT RAISE AssertionError` (Codex's exact probe: the old
check misses the translated deadlock and the old blanket whitelist accepts it).

Green (fix branch `621e49e`): the same selector → **`1 passed`** (in the 3-test race run
`3 passed in 11.90s`).

### HC-10 gap 1 — the billing-wrapper race catches the historical inversion

`test_at21_billing_wrapper_vs_resolve_create_never_deadlocks` no longer queues the wrapper first
behind an ACCOUNT holder (that shape completed orderly even with the pre-P4 wrapper inversion,
because the resolver held nothing while it waited). Now a lease-row (L) holder parks the wrapper
INSIDE its lock sequence while the resolver holds the account rows:

- shared order (current code): the wrapper's first locks are the account rows themselves, so the
  two serialise at the head — no cycle is possible; the wrapper completes, the resolver replays
  the identical attestation (green).
- pre-P4 order (advisory+L before account): the wrapper holds the billing advisory while parked
  on L; the resolver holds the account rows and waits on the advisory; when the L holder commits,
  the wrapper proceeds to the settlement's `lock_account` → a real ABBA cycle → PostgreSQL breaks
  it with 40P01.

Red (pre-P4 wrapper order restored on scratch branch `t031-r4-red-oldorder` @ `05369f7`, WIP
commit removing the account/categories prelude from `resolve_podless_create`'s wrapper only):
cmd `… -m pytest
tests/unit/rendering/test_t031_h2b_p4_resolution.py::test_at21_billing_wrapper_vs_resolve_create_never_deadlocks …`
→ **`1 failed in 10.80s`** — `AssertionError: ServiceUnavailable('deadlock detected')` recorded
in the resolver's outcome (the translated 40P01), exactly the defect the proof must catch.

Green (fix branch): same selector passes (in `3 passed in 11.90s`; full-file runs below).

### HC-10 gap 2 — AT-9 `sweep_finalization_mid` crashes for real, between the stages

`test_t031_h2b_p5_terminal.py::test_at09_crash_boundaries_converge[sweep_finalization_mid]` now
uses the suite's §9.3 death harness (the AT-13 pattern): a child subprocess composes the real
`_at6_context`, runs the public `resolve_create` (stage R committed), then sweeps with the
adapter's `leases.shutdown` wrapped by `_DeathAfterLeaseClose` — the delegate commits the
lease-close stage, writes the marker, and `os._exit(86)`s **between the sweep's finalization
stages** (the storage-release transaction never starts).

The parent then proves: returncode 86 + marker; the durable mid-crash state
(`NO_CREATE_PROVEN`, lease `RELEASED`, STORAGE hold still `ACTIVE`); and that its own next sweep
completes every remaining stage exactly once — STORAGE `RELEASED`, exact counts unchanged
(the release posts no new charge receipt; first observation `1 == 1+1` failed on my initial
guess, corrected to the exact observed behaviour: `counts_done == counts_mid`), exactly one
resolution row, and a second sweep changes nothing.

Green (fix branch): selector → **`1 passed in 15.04s`** (after the count correction). This is a
new proof of already-correct behaviour — there is no code defect to show red; the crash itself
(marker + exit code + mid-state assertions) is the injection evidence.

### HC-10 gap 3 — F2's worker connection gets the bounded `lock_timeout` explicitly

`test_t031_hcf_f2_locks.py::test_hc6_gate_serialises_with_l_only_adoption` now calls
`_bounded_worker_locks(db)` (the p4 helper: session `SET lock_timeout` on every pooled worker
connection + the database default for any the pool opens later) before starting the worker
thread, so the worker — not just the holder — is bounded; a wedge fails the test instead of
hanging it. Green: part of the `5 passed` f2 run.

### R2 regression runs (all green, fix branch `621e49e`)

- p4 + p5 + f2 full files → **`32 passed in 77.61s`** (pre-format), and after formatting
  `test_at09_crash_boundaries_converge` (5 params) + f2 (5) + p4 (12) → **`22 passed in 62.13s`**.
- `make lint` clean (ruff format applied to the three files).

### Judgement calls (R2)

1. **The whitelist is by class, not message**: `(AdmissionBlocked, NeedsReconciliation,
   PolicyDenied, Conflict)`. `ServiceUnavailable` is rejected by its own assertion AND by
   exclusion from the whitelist (it subclasses `MicrodramaError` directly, so the whitelist
   cannot admit it). The injection test pins all three assertions.
2. **`_deadlocks` treats every `ServiceUnavailable` as poison** in a race proof, not only the
   translated 40P01/55P03 pair: in a race that must converge without contention failures, any
   service-level unavailability of a worker is a proof failure. The two named SQLSTATEs are the
   shapes Codex demonstrated and are what the injection test drives through the real translator.
3. **The AT-9 exact-count assertion was corrected from observation, not weakened**: my first
   guess (`charges + 1`) was wrong — the storage release posts no charge receipt at all; the
   exact behaviour is `counts_done == counts_mid` plus the hold-state transition, which is a
   STRONGER exactly-once claim (nothing at all doubles).
4. **The two scratch branches are kept as evidence** (`t031-r4-red-oldorder` @ `05369f7`,
   `t031-r4-red-oldproof` @ `ccc9b53`); both carry "WIP(red-check)" commits that must never be
   merged. The brief forbids deletion commands, so they were not deleted.

### Pre-existing tests changed in R2 (all required by the findings)

| Test | Change | Why |
|------|--------|-----|
| `test_t031_h2b_p4_resolution.py::test_at21_ambiguity_vs_admission_vs_sweep_ordered` | whitelist narrowed, ServiceUnavailable rejected | HD-3 Fix paragraph |
| `test_t031_h2b_p4_resolution.py::test_at21_billing_wrapper_vs_resolve_create_never_deadlocks` | rewritten interleave (L holder instead of account holder) | HC-10 gap 1 |
| `test_t031_h2b_p5_terminal.py::test_at09_crash_boundaries_converge[sweep_finalization_mid]` | real subprocess death between the sweep's stages | HC-10 gap 2 |
| `test_t031_hcf_f2_locks.py::test_hc6_gate_serialises_with_l_only_adoption` | explicit worker `lock_timeout` | HC-10 gap 3 |

## R3 — HD-2: an already-posted interval keeps its immutable identity across closure (commit `0cda424`)

### The fix (`rendering/benchmark_experiments.py`, `ExperimentBudgetService`)

The late-identity choice moved from "the reservation's current state at call time" into a new
`_late_interval_identity(receipt)` helper that decides **once, under the account lock** — the same
lock posting and closure take, so the reservation state and the already-posted charges are read at
one serialized point, never between the two:

- reservation still ACTIVE (or not closed) → the receipt passes through unchanged (the ordinary
  path; `_reservation_closed`'s standalone read is no longer used here);
- reservation closed AND a charge already exists under the interval's **original** `receipt_id` →
  the receipt passes through **unchanged**: the posted identity IS the replay identity (immutable);
- reservation closed and nothing posted under the original id → the reserved `late:` ADJUSTMENT
  identity is minted (genuinely new late cost), with basis IDLE, exactly as before.

`record_gpu_interval` now only swaps the identity (and basis) when the helper actually minted a
late identity.

### Why the red was exactly Codex's probe

At `7060e02` the replay of an interval posted while ACTIVE (reservation since SETTLED) minted the
`late:` identity; the canonical replay lookup (`_replay`, keyed by receipt UUID/provider receipt
key) missed the recorded charge; the pod-interval overlap check raised
`Conflict("interval already attributed")` and `accrued_until` could never advance.

### Test (`test_t031_hcf_f1_receipts.py::test_hd2_interval_posted_active_replays_same_receipt_after_close`)

ACTIVE post → the `update_with_revision` death injection kills the accrual after the interval
commits and before the cursor moves → `settle_from_recorded_usage` closes the reservation → the
recovery replay runs `accrue_lease_usage` again. Asserted: the crash state (one ACCRUAL, no
`late:` key, `accrued_until` NULL); then after the replay — `accrued_until == T0+600s`, exactly
one ACCRUAL with the **same receipt UUID and the same provider receipt key**, and no `late:`
charge anywhere for that reservation.

Red against committed `7060e02` (fix restored via `git show HEAD:… > …`, diff saved to
`/tmp/t031-r4-hd2-fix.diff` and re-applied): cmd `… -m pytest
tests/unit/rendering/test_t031_hcf_f1_receipts.py::test_hd2_interval_posted_active_replays_same_receipt_after_close …`
→ **`1 failed in 6.60s`** — `microdrama.contracts.errors.Conflict: interval already attributed`
(budget/service.py:950).

Green with the fix: the full F1 file → **`5 passed in 11.80s`** (and `5 passed in 11.89s` after
ruff format).

Regressions (green): F1 + F3 + `test_benchmark_experiments` +
`tests/unit/pipeline/test_benchmark_world_composition.py` + p1 + p2 → **`53 passed in 200.27s`**.
`make lint` clean (ruff format applied).

### Judgement calls (R3)

1. **"Already posted" is keyed by the original `receipt_id` on the same reservation** — the exact
   key the canonical `_replay` later matches on (it also matches provider+provider_receipt_id;
   the original id is the pair the crash replay reconstructs deterministically from provider
   usage).
2. **The identity-kept replay keeps its original basis** (no IDLE flip): the replay presents the
   same ACCRUAL content the caller constructs, which is byte-identical to what was stored — the
   canonical content comparison and `_check_interval_replay` validate against the recorded
   interval unchanged.
3. **The decision transaction takes the account lock before reading state** (`lock_account` after
   `reservation_account_id`): the closure (settlement) and the interval post both serialize on
   that lock, so the decision cannot observe a closure mid-commit or miss an in-flight post. The
   canonical post that follows re-takes the same lock in its own transaction (sequential, no
   deadlock: one lock, always acquired alone here).
4. **A genuinely-new late interval still mints `late:`** — the F1 proofs (crash-after-close
   replay, incident-path late billing) all still pass unchanged, so the fix narrows only the
   already-posted case.

### Pre-existing tests changed in R3

None (only the new test was added; the four existing F1 tests are untouched and green).

## Anything stopped at red

Nothing. All three packages completed with their red/green evidence recorded above.

## Scratch branches kept as red-proof evidence (never merge)

- `t031-r4-red-oldorder` @ `05369f7` — pre-P4 wrapper lock order + the R4 race test (red:
  `ServiceUnavailable('deadlock detected')`).
- `t031-r4-red-oldproof` @ `ccc9b53` — pre-R4 race-proof semantics + the R4 injection test (red:
  `DID NOT RAISE AssertionError`).

## Uncommitted files

- `docs/microdrama-system/T031-fix-round/h2-r4-REPORT.md` — this report (untracked docs dir, by
  convention).
- Pre-existing untracked strays in the worktree (untouched): `.scratch/`,
  `microdrama/.venv` (symlink), `microdrama/tests/unit/rendering/test_t031_hcf_f1_receipts.md`
  (empty stray from the F1 round), `microdrama/tests/unit/rendering/zz_debug_f3.py`,
  `docs/microdrama-system/T031-fix-round/fix3-luna-REPORT.md`.

## Resume here

All packages (R1–R3) are done and committed on `feat/t031-fix3`:
`92f7b51` (R1/HD-1), `621e49e` (R2/HD-3 + HC-10 gaps), `0cda424` (R3/HD-2).
Final net: 85 passed, lint clean. Nothing in progress.
