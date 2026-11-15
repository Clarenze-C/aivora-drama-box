# A1 fix round 1: the eleven review findings A1V-1..A1V-11 (GLM build; drama-box repo)

Orchestrator: GLM (operator's standing fix-cycle pattern), 15 Nov 2026. The A1 build
(`eea2f79..57df5a9`) is complete but its review round 1 returned FIX-REQUIRED: A1V-1..3 BLOCKING,
A1V-4..11 SHOULD-FIX. **You fix all eleven on top of `57df5a9`.** Round-2 review follows.

## Read first
- `codex-review-a1.md` — each finding with file:line and a Fix direction. **The review wins over
  this brief** (say so in the report if they disagree).
- `.scratch/a0d-gateway/a1-build-REPORT.md` — build context + the eight deviations the reviewer
  weighed.
- `A1-design-note.md` v1.4 — the binding design (§§5, 8, 9 especially for the lock-order and
  fence findings).

## Priority order
A1V-1 first (gate approval must require APPROVE + complete scope + current binding/revision
authority — REJECT/REVISE/stale must never authorize a transition), then A1V-2/3 (the lock order
vs §§8–9; approvals advancing the content fence), then the eight SHOULD-FIXes per their directions.

## Where you work / rules
Worktree `/root/AIVORA/drama-box/.scratch/a0d-gateway`, branch `feat/a0d-gateway`, at `57df5a9`.
Commit on top; never amend; the `.venv` symlink never staged. **If `a1-fix1-REPORT.md` exists,
resume from its "Resume here".** Tests first per finding (`test_a1v_…` red recorded); real
PostgreSQL for the lock/fence races; no interactive flags; no new migrations beyond 0028–0031
(fix findings in code/contract layers; if a finding truly needs schema, stop and report BLOCKED);
standard env + PATH + CPUQuota + `--basetemp=/tmp/a1-fix1-basetemp`; `make lint` per commit; no
full `make check`/`pilot` (the orchestrator gates after the round-2 review). Offline only; no
pushes/merges/restarts/deletions; never print env vars/keys. At the z.ai limit: stop clean,
commit, update "Resume here".

## Report
`a1-fix1-REPORT.md` (beside the build report in the worktree root): per-A1V status + commits,
red/green, deviations, "Resume here". Top marker when done: `A1 FIX1: ALL FINDINGS ADDRESSED`.
Final message: one line per A1V id, then the report path.
