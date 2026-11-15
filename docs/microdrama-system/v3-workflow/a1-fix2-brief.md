# A1 fix round 2: the three round-2 findings A1V2-1..A1V2-3 (GLM build; drama-box repo)

Orchestrator: GLM (operator's closing directive: finish A1), 15 Nov 2026. Fix1 addressed all eleven
round-1 findings at `3bd8c90`; the round-2 review closed eight and left **A1V2-1 (BLOCKING,
terminal-event ordering) + A1V2-2/3 (SHOULD-FIX)**. **You fix all three on top of `3bd8c90`.**
Round-3 verification follows.

## Read first
- `codex-review-a1-r2.md` — the three findings with file:line and Fix directions (A1V2-1's two
  reproductions especially). **The review wins.**
- `.scratch/a0d-gateway/a1-fix1-REPORT.md` — round-1 context.

## Priority
A1V2-1 first (persist monotonic terminal-event ordering under the scope lock; the fix direction is
in the review — test reversed transaction-start order AND equal timestamps), then A1V2-2/3 per
their directions.

## Where you work / rules
Worktree `/root/AIVORA/drama-box/.scratch/a0d-gateway`, at `3bd8c90`; resume from
`a1-fix2-REPORT.md` if it exists. Tests first per finding (`test_a1v2_…` red recorded); real
PostgreSQL two-connection races for A1V2-1; no interactive flags; no new migrations beyond
0028–0031 without reporting BLOCKED (A1V2-1 may legitimately need a schema tweak inside 0030's
tables — if so, amend within the existing migration file ONLY if it has not shipped anywhere
(it has not — nothing is merged/pushed; note the choice in the report); standard env + PATH +
CPUQuota + `--basetemp=/tmp/a1-fix2-basetemp`; `make lint` per commit; no full `make check`/`pilot`.
Offline only; no pushes/merges/restarts/deletions; never print env vars/keys. At the z.ai limit:
stop clean, commit, update "Resume here".

## Report
`a1-fix2-REPORT.md` (worktree root, beside the others). Top marker when done:
`A1 FIX2: ALL FINDINGS ADDRESSED`. Final message: one line per A1V2 id, then the report path.
