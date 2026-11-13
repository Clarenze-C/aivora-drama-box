# Codex review: A0-D fix round 1 — round 2 (scoped to the round-1 findings)

Diff: `ea1cc10..6974d5a` on `feat/a0d-gateway` (three fix commits: `5e85d3d` AD-1/2/8, `97471b3`
AD-3/4/5/12/13, `6974d5a` AD-6/7/9/10/11) in worktree
`/root/AIVORA/drama-box/.scratch/a0d-gateway`. Your round-1 report is `codex-review-a0d.md`
(AD-1..AD-13). **Round 2: re-check those thirteen findings only**; new defects introduced by the fixes
are in scope.

Builder context: `a0d-fix1-REPORT.md` (per-finding red/green, six documented deviations — notably the
AD-9 twin validators (the gateway cannot import the package) and AD-2's `/etc` case proven green-only).
Spec: `phase-A0-spec.md` v0.4 §4–§5; base gate was green at `ea1cc10`.

## Answer, per finding (AD-1..AD-13)

CLOSED / PARTIAL (what remains) / REGRESSED, with `file:line` and fix directions. Pay attention to:
AD-1 (the shim now enforces the real CLI interface — is the binding right vs A0-R1's validator?),
AD-5 (the two-connection janitor-storm race), AD-9 (are the twin validators really equivalent?),
AD-10 (conflict-rejecting evidence), AD-13 (UNKNOWN precedence).

## Output

- Read-only; no writes. Final message at most about 100 lines.
- Issues `AD5-1`… with severity **BLOCKING / SHOULD-FIX / NIT** and fix directions.
- Verdict: **ACCEPT** / **FIX-REQUIRED** (final round this weekend).
