# Codex final review (round 3): T031 H-2 fix round HCF (money path)

Orchestrator: Opus, 11 Nov 2026. **The operator approved this as the last review round.** No further fix
round is planned: if BLOCKING findings remain, the orchestrator will recommend parking T031.

Read-only. Checkout `/root/AIVORA/drama-box/.scratch/t031-gate-hcf`, detached at the HCF tip
(`git rev-parse HEAD`; also in `.scratch/gate/head.txt`). The full offline gate is running in it under
systemd. Don't run tests there and don't write files.

**Scope: `git diff 4e28514...HEAD`**, the fix-round commits F1–F5. GLM wrote all of them; you did not.
Code that HCF didn't change is out of scope, except the context needed to judge a finding below.

## Inputs (paths relative to `/root/AIVORA/drama-box/docs/microdrama-system/`)

- **Your round-2 findings:** `T031-fix-round/codex-review-h2-p4p5.md` (HC-1..HC-12, the HB and L tables).
- **The fix brief with the orchestrator's rulings 1–6** (binding): `T031-fix-round/h2-hcf-brief.md`.
- **The builder's report:** `T031-fix-round/h2-hcf-REPORT.md`. Read its judgement calls critically. Check
  its transaction inventory against the actual SQL.
- Spec v3 `T031-H2-recovery-spec.md`; contract `T031-integration-contract.md`.

## Review

1. **HC-1..HC-12:** for each, CLOSED / PARTIAL / OPEN, with `file:line`. Check, from the reported red lines
   and the code, that each fix's test fails without the fix.
2. **The round-2 partials:** HB-5..HB-13, L-1, L-2: CLOSED / PARTIAL / OPEN.
3. **HC-2 and ruling 1:**
   - `git diff 45e4f2a HEAD -- microdrama/src/microdrama/budget/service.py
     microdrama/src/microdrama/rendering/leases.py` must hold nothing beyond the three spec-allowed
     canonical edits. It was empty at F4 `c044daf`.
   - The benchmark-layer late billing (`ExperimentBudgetService`) must be correct: stable receipt identity
     and content across replay, one final settlement per reservation, only new deltas after a close, and
     a clean replay after an interval crash between the post and the `accrued_until` advance.
4. **Ruling checks:**
   - HC-6: one ordered lock helper, including L and S, used by every listed transaction.
   - HC-3: positively recoverable work refuses resolution even with `--force-unrecoverable`.
   - HC-10: tests call the real public implementations, with fresh worlds, exact counts and
     `lock_timeout` on the worker connections.
   - L-1/L-2: S08 is actually bound with the changed costume.
5. **New defects that HCF introduced:** money, duplicate provider effects, lock order or deadlock, lost
   recovery, secrets, and weakened or skipped assertions. Compare pre-existing tests against `4e28514`.

## Severity (final round)

**BLOCKING** needs a concrete failure scenario on a path the paid run or its recovery can reach:
- a wrong charge or settlement;
- a duplicate provider effect;
- lost or blind-released exposure;
- a lock inversion or deadlock;
- a secret leak;
- a fix whose proof test would pass without the fix.

Everything else is SHOULD-FIX or NIT.

## Output

- Read-only sandbox: no writes, no `systemd-run`, no integration suite. Small in-memory probes are fine.
- **The Codex week is nearly spent.** Stay inside the scope; don't re-derive the round-1 or round-2
  reviews.
- Put the full report in your final message.
- New findings use IDs `HD-1`…, with severity, `file:line`, a failure scenario and a fix.
- End with one status table covering every HC, HB-5..13, L-1, L-2 and HD ID, then the verdict: **ACCEPT**
  or **FIX-REQUIRED**.
