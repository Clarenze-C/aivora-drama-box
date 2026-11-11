# Codex scoped check (round 3, operator-approved): Phase A0 spec v0.3

Spec: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-A0-spec.md` **v0.3**.
Your round-2 report: `codex-a0-recritique.md` (A0R-1..10). v0.3 §12 maps each finding to its section.

Code (read-only): `/root/AIVORA/drama-box/microdrama/src/microdrama/` (`core/jobs.py`,
`core/provider_ops.py`, `contracts/cost.py`, `contracts/enums.py`, `workers/runtime.py`),
`microdrama/migrations/0009_m0_round3_hardening.sql`, `0016_*`, `/root/.claude/scripts/ai_route.py`, the
installed `claude --help` (capture through a PTY).

## Scope: narrow

1. For each A0R-1..10: **RESOLVED / PARTIAL / NOT RESOLVED**, with one line of evidence.
2. **Only defects introduced by the v0.3 fixes themselves**, mainly:
   - the §5.1 state-driven table against `ALLOWED_MOVES` and `JobService.finish()`;
   - `REFUSED_PRELAUNCH` + the `resubmit_allowed()` extension;
   - the kind-limited `PENDING_SUBMIT → CANCELLED`;
   - `defer(refund_attempt)`;
   - the auto-reconciler;
   - the §4.3 argv and recovery table;
   - the stream-json runtime assertion.

Do not re-open settled design or earlier resolved findings. Anything non-blocking will be fixed during the
build, so mark it NIT or SHOULD-FIX and keep it short.

## Output

- Read-only; no writes. Final message at most about 80 lines.
- A table A0R-1..10 → status + evidence. New issues use `A0S-1`… with severity and replacement wording.
- Verdict: **APPROVE** / **APPROVE-WITH-CHANGES** / **REWORK**.
