# Codex review: T031 R5 build (`104b26b..6bcdbfa`) — money-path code, before the gate

Worktree `/root/AIVORA/drama-box/.scratch/t031-r5` (branch `feat/t031-r5`). Spec:
`docs/microdrama-system/T031-run-readiness-spec.md` **v0.3** (accepted for building; rulings
`T031-fix-round/r5-critique-rulings.md`). Build report: `T031-fix-round/r5-build-REPORT.md`
(marker `R5: ALL PACKAGES DONE`; make check green at `6bcdbfa`). **Review the full build range
`104b26b..6bcdbfa`** (R5a through R5f + base repairs + close-out).

Verify against the spec's §6 file map and the RR-T1..T17 acceptance rows, with special attention to
the R5C-1..12 replacements: the composed flag path (R5C-4: `_spec_for()` → `to_request()` → transport,
intent ∧ request before POST), boot handling before `acquire()` completes, typed pre-sample boot
failures (no sample outcome), acquisition records on unclaimed rows keyed by acquisition ID, lease
liveness during waits, office-reuse staging (role/subject-scoped guard), per-phase resume/reconcile,
the billing-verification wrapper (no new logic), and the P (predicted schema) seal with live
comparison still mandatory. Offline evidence only — no provider calls.

## Output: read-only; ≤120 lines; issues `R5V-n` BLOCKING/SHOULD-FIX/NIT + fix directions;
verdict **ACCEPT / FIX-REQUIRED**.
