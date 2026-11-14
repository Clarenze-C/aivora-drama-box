# A0-D fix round 3: the seven round-3 findings AD6-1..AD6-7 (GLM build; drama-box repo)

Orchestrator: GLM (weekend runbook, operator's A-track approval + standing round pattern), 14 Nov 2026.
Fix2 addressed all ten AD5 findings at `b84a397`; the round-3 review returned FIX-REQUIRED with
AD6-1..7 (5 BLOCKING + 2 SHOULD-FIX). **You fix all seven on top of `b84a397`.** The operator's
standing pattern authorizes the round-4 verification after this fix.

## Read first (absolute paths)
- `codex-review-a0d-r3.md` — the AD5 statuses + AD6-1..7, each with file:line and a Fix direction.
  **Your requirement list; where this brief disagrees, the review wins** (say so in the report).
- `a0d-fix2-REPORT.md` — round-2 context.

## Where you work
Worktree `/root/AIVORA/drama-box/.scratch/a0d-gateway`, branch `feat/a0d-gateway`, at `b84a397`.
Commit on top; never amend/rebase; `microdrama/.venv` symlink never staged. **If
`a0d-fix3-REPORT.md` exists, you are resuming** — continue from its "Resume here".

## Fix rules
AD6-1 first (persist the frozen identity once; reload it for existing calls — never refill from
current config), then the four other BLOCKINGs per their Fix lines, then the two SHOULD-FIXes.
Tests first per finding (`test_ad6_…`, red recorded); the producer-vs-admission test from AD5-1 must
stay green. Real PostgreSQL for races; real transient systemd units where the gateway launches;
no interactive pytest flags; no new migrations; the standard offline env + PATH + CPUQuota + basetemp
`/tmp/a0d-basetemp3`; `make lint` per commit; don't run the full `make check`/`pilot` (orchestrator
gates after the round-4 review).

## Hard limits
Offline only; no pushes/merges/service-restarts (own test units excepted); no deletions; never print
env vars/keys/tokens. At the z.ai limit: stop clean, commit, update "Resume here".

## Report
`a0d-fix3-REPORT.md`: per-AD6 status + commits, red/green, deviations, "Resume here". Top marker:
`A0-D FIX3: ALL FINDINGS ADDRESSED`. Final message: one line per AD6 id, then the report path.

## Additional finding (from the orchestrator's gate at `b84a397`, run solo)

- **AD6-GATE-1 (BLOCKING for acceptance)** — `tests/integration/pipeline/test_scheduler_driven_path.py::test_scheduler_and_workers_drive_release_with_only_the_two_gates`
  fails at `b84a397` (810/811 green elsewhere): "the scheduler-driven path never verified a required
  post — assert []" at `test_scheduler_driven_path.py:236`. The gate receipts are at
  `.scratch/a0d-gate3/.scratch/gate/check.log`. Reproduce it red, diagnose whether fix2 caused it
  (reconciler/gateway settlement behavior is the likely interaction), fix, and record red/green. If
  you determine it is pre-existing at `6974d5a` (check out that file's history, do not rebuild the
  tree), say so in the report with evidence instead.
