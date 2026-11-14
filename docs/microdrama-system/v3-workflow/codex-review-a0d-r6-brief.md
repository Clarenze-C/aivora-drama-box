# Codex review: A0-D fix round 5 — round 6 (scoped to the round-5 findings)

Diff: `15ce674..1e43b70` on `feat/a0d-gateway`. Your round-5 report is `codex-review-a0d-r5.md`
(AD8-1/2). **Round 6 under the operator's standing waiver: re-check those two findings only**;
new defects from the fixes in scope.

Builder context: `a0d-fix5-REPORT.md` (red/green; **4 deviations — notably cancel/rearm chosen over
in-place migration for stranded probes, and an accepted cross-version hash-vocabulary break in the
evidence fields: weigh both explicitly**). Spec: `phase-A0-spec.md` v0.4 §4–§5.

## Output: read-only; ≤60 lines; per finding CLOSED/PARTIAL/REGRESSED + file:line + fix directions;
verdict on the deviations too; issues `AD9-n`; verdict **ACCEPT / FIX-REQUIRED**.
