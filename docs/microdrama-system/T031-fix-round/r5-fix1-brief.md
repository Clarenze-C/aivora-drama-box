# R5 fix round 1: the ten review findings R5V-1..R5V-10 (GLM build; drama-box repo)

Orchestrator: GLM (weekend runbook), 14 Nov 2026. The R5 build is complete at `6bcdbfa` (make check
green there) but the Codex review round 1 returned FIX-REQUIRED: 4 BLOCKING + 6 SHOULD-FIX. You fix
all ten on top of `6bcdbfa`.

## Read first (absolute paths)
- `codex-review-r5.md` — the findings, each with file:line and a Fix direction. **Your requirement
  list; where this brief disagrees, the review wins** (say so in the report).
- `r5-build-REPORT.md` — what was built, red/green per RR test, the two documented blockers.
- `T031-run-readiness-spec.md` v0.3 — binding spec (the R5C-1..12 replacements especially).

## Where you work
Worktree `/root/AIVORA/drama-box/.scratch/t031-r5`, branch `feat/t031-r5`, at `6bcdbfa`. Commit on
top; never amend/rebase; `microdrama/.venv` is a symlink — never stage it; the untracked
`microdrama/preflight.json` is a test artifact — do not commit it. **If `r5-fix1-REPORT.md` exists,
you are resuming** — continue from its "Resume here".

## Priority order
R5V-1 first (resume must bypass initial boot timing once readiness is durable — the minute-40 case
through real resume/reconcile), then R5V-2..4 per their Fix lines, then the six SHOULD-FIXes.

## Test rules and hard limits
Same as the R5 build brief: tests first per finding (red recorded, `test_r5v…` naming), real
PostgreSQL where touched, no interactive pytest flags, no new migrations, offline env vars +
`env PATH="/usr/sbin:$PATH"` + `systemd-run --scope -p CPUQuota=45%` + `--basetemp=/tmp/t031r5-basetemp2`,
`make lint` per commit, `make check` green at the final commit. **The image rebuild stays
disk-blocked — do not attempt it** (operator item). No pushes/merges/restarts/deletions; never print
env vars/keys.

## Report
Write `r5-fix1-REPORT.md`: per-R5V status + commits, red/green lines, deviations, "Resume here".
Top marker when done: `R5 FIX1: ALL FINDINGS ADDRESSED`. Final message: one line per R5V id, then the
report path.
