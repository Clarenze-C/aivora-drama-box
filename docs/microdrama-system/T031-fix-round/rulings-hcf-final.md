# Rulings on the final Codex review of HCF (round 3), 11 Nov 2026 23:45Z

Orchestrator: Opus (session e4e3c05c). Review: [codex-review-hcf-final.md](codex-review-hcf-final.md),
scope `4e28514...7060e02` (F1–F5) = **FIX-REQUIRED**: HD-1 and HD-3 BLOCKING, HD-2 SHOULD-FIX.

## Orchestrator verification of the BLOCKING claims (in code, at `7060e02`)

- **HD-1, CONFIRMED.** `pipeline/benchmark_service.py:2978–2987`: inside the `binding == "BOUND"` branch,
  `resolve_sample` composes a **new** RECOVERY world and calls `reconcile_unknown` on it without binding it.
  Every exception from that probe becomes `probed_state = None`, which the code treats as unrecoverable;
  with `--force-unrecoverable` it then resolves the sample. So a local composition or binding failure can
  discard recoverable work. The F4 test hides it because its factory returns the same adapter for both
  modes.
- **HD-3, CONFIRMED.** `tests/unit/rendering/test_t031_h2b_p4_resolution.py:574`: `_deadlocks` matches only
  `psycopg.errors.DeadlockDetected`. `persistence/db.py:92–96` translates `DeadlockDetected` and
  `LockNotAvailable` into `ServiceUnavailable`, and the whitelist at `:725` accepts every `MicrodramaError`,
  so a deadlock or lock timeout passes the test.

## Operator decisions (11 Nov, 23:40Z)

1. **Round 4, verified by the orchestrator only; no 4th Codex round.** GLM fixes HD-1, HD-3, HD-2 and the
   test-only HC-10 proof gaps ([h2-r4-brief.md](h2-r4-brief.md)). The orchestrator verifies the red/green
   lines itself and runs the full gate at the R4 tip. If verification fails, T031 is parked.
2. **The remaining non-BLOCKING partials are recorded as known limits**, not fixed now.

## Known limits (must be revisited before phase D's production render adapter)

Phase D builds its production render adapter over these primitives (master §4.6, N36), so each one is
re-audited there.

| ID | Limit (Codex round 3) |
|----|-----------------------|
| HC-6 (HB-8, HB-9) | The ordered lock helper (A → L → D → S → R → O → uploads) is not used by every listed transaction: `resolve_create`, `_observe`, terminal projection, activation, ambiguity writes, deadline recompute and `reserve_linked` keep their own sequences. No concrete paid-path cycle found. `_shorten_recovery_deadline` is missing from the report's inventory |
| HC-9 (HB-6) | Deadline recompute locks only the A row, and both recovery paths read the provider before recomputing (`benchmark_service.py:2136`, `:2480`) |
| HC-11 (HB-10) | The CLI still loads generation documents before service construction and recovery (`benchmark.py:169`, `:259`); soft validation stands in for literal recovery-first ordering |
| HB-13 (broad) | Broad tests still reuse adapters and clients; there is no fresh-world proof across the whole suite. HD-1's fix adds the fresh-client proof for resolution only |

## Closed in round 3

HC-1, HC-4, HC-5, HC-7, HC-8, HC-12; HB-5, HB-7, HB-11, HB-12; L-1, L-2. The F1 canonical revert holds:
`git diff 45e4f2a 7060e02` on `budget/service.py` and `rendering/leases.py` is empty.
