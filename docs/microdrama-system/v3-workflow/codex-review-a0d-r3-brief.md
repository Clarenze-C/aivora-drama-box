# Codex review: A0-D fix round 2 — round 3 (scoped to the round-2 findings)

Diff: `6974d5a..b84a397` on `feat/a0d-gateway` (worktree `.scratch/a0d-gateway`). Your round-2 report
is `codex-review-a0d-r2.md` (AD5-1..AD5-10). **Round 3 under the operator's standing waiver:
re-check those ten findings only**; new defects from the fixes in scope.

Builder context: `a0d-fix2-REPORT.md` (per-finding red/green; AD5-1's producer-vs-admission test
mandatory). Spec: `phase-A0-spec.md` v0.4 §4–§5. Prior gates green at `ea1cc10` and `6974d5a`.

## Answer, per finding (AD5-1..AD5-10): CLOSED / PARTIAL / REGRESSED, with file:line + fix
directions. Special attention: AD5-1 (the real frozen-call producer through admission),
AD5-3 (twin equivalence, 28-case corpus), AD5-5 (A0-R1 quota names), AD5-10 (requalify probe).

## Output: read-only; ≤100 lines; issues `AD6-n` + fix directions;
verdict **ACCEPT / FIX-REQUIRED**.
