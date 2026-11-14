# A0-D fix round 4: the four round-4 findings AD7-1..AD7-4 (GLM build; drama-box repo)

Orchestrator: GLM (operator autonomy window), 14 Nov 2026. Fix3 addressed all ten AD6 findings at
`a4e9913`; the round-4 review returned FIX-REQUIRED with AD7-1..4 (2 BLOCKING + 2 SHOULD-FIX).
**You fix all four on top of `a4e9913`.** Round-5 verification follows.

## Read first
- `codex-review-a0d-r4.md` — per-finding statuses + AD7-1..4 with file:line and Fix directions.
  **The review wins over this brief** (say so in the report if they disagree).
- `a0d-fix3-REPORT.md` — round-3 context incl. the AD6-GATE-1 flake diagnosis.

## Where you work
Worktree `/root/AIVORA/drama-box/.scratch/a0d-gateway`, branch `feat/a0d-gateway`, at `a4e9913`.
Commit on top; never amend/rebase; the `.venv` symlink never staged. **If `a0d-fix4-REPORT.md`
exists, resume from its "Resume here".**

## Fix order
AD7-1 first (DONE validation against the frozen call's identity — extend the A→B test through
successful completion), then AD7-2/3 (BLOCKING) per their Fix lines, then AD7-4.

## Test rules and hard limits
Same as fix3: tests first per finding (`test_ad7_…` red recorded); the scheduler-driven flake
(AD6-GATE-1) is known load-sensitive — don't chase it, but keep the pipeline dir green solo. Real
PostgreSQL for races; real transient systemd units for gateway paths; no interactive flags; no new
migrations; standard env + PATH + CPUQuota + `--basetemp=/tmp/a0d-basetemp4`; `make lint` per commit;
no full `make check`/`pilot` (orchestrator gates after R5). Offline only; no pushes/merges/restarts/
deletions; never print env vars/keys. At the z.ai limit: stop clean, commit, update "Resume here".

## Report
`a0d-fix4-REPORT.md`: per-AD7 status + commits, red/green, deviations, "Resume here". Top marker:
`A0-D FIX4: ALL FINDINGS ADDRESSED`. Final message: one line per AD7 id, then the report path.
