# T045-FIX7 build report (session 7: the re-review findings — CR-3 residual, CR-9)

Branch `feat/microdrama-m0-m4`. Base of this session `e56c952` (the orchestrator's
re-review record + fix7 brief commits on top of session 6's `2adf453`). All work
offline: fixture transports, loopback PostgreSQL only, no provider call, no live key,
no pod, nothing left this machine. Commit, never push.

The re-review (`rereview-t045fix6.md`) and its orchestrator rulings were read first;
the rulings are binding and both findings were fixed tests-first with a recorded red
line. Per the two-round review cap, verification of these two fixes goes back to the
operator before any third Codex round.

## Findings by ID (commit, tests, red → green)

| ID | Commit | What was done |
|----|--------|---------------|
| CR-3 residual (BLOCKING, F-1) | `d7f59a6` | The `_sweep_billing_ingestion` pod aggregate computed `has_unverified_terminal_lease` with a plain `BOOL_OR` over every lease of the Pod — no supersession exclusion — so a warm transfer's historical leases (A→B→C, C verified, A and B keeping their by-design NULL `terminate_verified_at`) deferred ingest forever while Runpod still listed the Pod. The aggregate now excludes superseded leases with the same `NOT EXISTS` predicate the two terminate selections use: a lease with a later lease on the same provider+pod is history; the final holder owns the terminate, and its verified terminate makes the window final. Pinned by `test_a_transfer_history_with_the_final_holder_verified_ingests_and_advances`: FIRST sweep INGESTS (bucket stored, no DEFERRED), readiness advances `PENDING_PROVIDER_FINALITY` → `AWAITING_INVOICE` → `BILLED` at the invoice match, a later sweep adds nothing. Red: `assert any(a.outcome == "INGESTED" ...)` → `AssertionError: assert False` (the sweep reported DEFERRED). Per the ruling, the green line is successful ingestion and finality progress — not zero-provider-call stability. |
| CR-9 (BLOCKING) | `d10e1cb` | Both terminate selections — the F-1 retry tail in the orphan sweep and the CR-2 absence-completion pass — joined on provider (+pod_id) and `owned_tag` only, never `provider_account_ref`. An empty successful scan of account A stamped a verified terminate and closed storage ownership on a same-tag lease labeled for account B, and a present Pod held (per the durable row) by a foreign-account terminal lease drew A's full stop → terminate (DELETE) → verify tail. Both selections now match the manager's configured provider account label (`self._config.provider_account_ref`) on the durable lease row; an unconfigured label selects nothing (no label, no attributable ownership). A foreign-account terminal lease is never selected by either pass — its own account's janitor owns it — and the billing ingest defers on the unverified terminate rather than reading a window that is not final for this account. Tests pin both shapes: `test_an_empty_scan_never_completes_a_foreign_account_lease` (no terminate stamp, storage ownership stays open, zero DELETE) and `test_the_terminate_tail_ignores_a_foreign_account_lease_for_a_present_pod` (zero POST/DELETE, no stamp, ownership open, ingest DEFERRED — the money-safe wait). Reds: `terminate_verified_by_absence` WAS reported on the foreign lease, and POST + DELETE WERE issued on B's Pod. |

Evidence: session-7 section appended to `microdrama/evidence/T045.md` (`1ce71cb`) with
both red/green pairs.

## Honest notes

- The CR-3 residual test needed two steps to green: after the aggregate fix the first
  sweep already INGESTED, but readiness reported `RECOVERY_REQUIRED` — the fixture
  seed (like `_seed_terminated_lease` always) creates no `pod_storage_ownership` row,
  and every other test got one written by a terminate tail; this test runs no tail by
  design. The test seeds the closed ownership row a real transfer history leaves on
  the final holder (C held storage until its verified terminate) — the production
  durable shape, not a weakened assertion.
- The first canary-composed focused run errored 34/37 with
  `FileNotFoundError: .../fix7-t045/basetemp-canary-one`: the scratchpad basetemp
  PARENT had been removed (disk-cleaner activity between runs) and pytest's
  `--basetemp` does not create parents. Recreating the parent (`mkdir -p`) re-ran the
  suite to 37 passed; no code was involved.
- No test had assertions weakened or deleted this session; both new CR-9 tests and
  the CR-3 residual test are new files' additions to
  `tests/unit/rendering/test_t045_billing_ingestion.py` only.

## Operator checks the brief demanded

- `git status --porcelain` after the suites: nothing under `microdrama/canary-objects/`
  (the directory does not exist).
- `/tmp/pytest-of-root`: **700 before** the full run, **700 after** (nothing widened).
- `stat -c '%a %n' /tmp/claude-0 /tmp/claude-0/-root-AIVORA` → both **700** after the
  gates (unchanged); no chmod of `/tmp/claude-0` or its ancestors anywhere.
- Focused runs used `--basetemp=/tmp/claude-0/-root-AIVORA-drama-box/fix7-t045/basetemp-*`.
- `git diff --check`: clean.

## SPEC-GAPs

None. The CR-3 residual keeps the deferral semantics the F-1 ruling requires (a
terminal lease's window is final only at its verified terminate) and only stops
counting superseded leases' intentional NULLs; CR-9 narrows two selections to the
manager's own account label. No contract or guardian-owned validator was touched.

## Gates

All under `systemd-run -p CPUQuota=45%`:

```
make check   → last line: "make check: all offline checks passed" (exit 0)
               contracts-check: contracts 2.15.0: 104 schemas ... OK
               ruff check: All checks passed!  ·  ruff format: 580 files already formatted
               unit 2770 passed, 2 warnings (0:45:05)   [was 2767 at session-6 close: +3 = CR-3 residual, CR-9 x2]
               contract 462 passed (0:04:30)            [unchanged]
               integration 268 passed (0:35:51)         [unchanged]
               git diff --check: clean
```

```
make pilot   → exit 0; W01–W12 all OK (W07 GREEN_WITH_UNKNOWNS, W08 APPROVED);
               exactly two gates: GATE1 season_approval APPROVED (HUMAN),
               GATE2 (W08 gate2_approval) APPROVED (HUMAN);
               media exported: 16 file(s); settled micro-usd: 303000 (fake providers)
```

Same pilot profile as the session-6 close-out; the unit count moved only by this
session's three new tests, as itemized above.

Environment note, recorded honestly: the first `make check` launch was killed at the
harness's default 10-minute background cap (30% through the unit lane); it was
restarted with the full 2-hour window and completed clean. No test result was reused
from the killed run.

## Not done

Nothing. Both findings have code + tests + a recorded red/green pair in the evidence;
the gates are green; this report is left uncommitted for the orchestrator to check
and commit with the round record.
