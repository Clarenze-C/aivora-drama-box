# A0-D fix round 6: the single round-6 finding AD9-1 (GLM build; drama-box repo)

Orchestrator: GLM (operator autonomy window), 14 Nov 2026. Fix5 addressed both AD8 findings at
`1e43b70`; the round-6 review closed AD8-1 and left **AD9-1 (SHOULD-FIX)**: the requalify repair's
`repaired` state exists only in memory — an interrupt between replacing `request.json` and
`prompt.txt` lets a restart skip the remaining replacements (the persisted request hash already
matches) and launch stale prompt bytes. **You fix this one finding on top of `1e43b70`.** Round-7
verification follows.

## Read first
- `codex-review-a0d-r6.md` — AD9-1 with the exact reproduction (gateway.py:1429 area).
- `a0d-fix5-REPORT.md` — the cancel/rearm design this builds on.

## Fix direction
Make repair completeness durable and re-derivable: either persist per-file replacement progress (a
completion marker per artifact, written as each replacement lands) or re-derive completeness from
the artifacts themselves (both request hash AND prompt-file hash/content must match the frozen
expectation before bind+launch). The restart path must re-enter repair, never skip it on partial
evidence. Red test first: seed the interrupted state (doctored self-consistent request + foreign
prompt), restart, assert the pump refuses/repairs before any launch.

## Where you work / rules
Worktree `/root/AIVORA/drama-box/.scratch/a0d-gateway`, at `1e43b70`; resume from
`a0d-fix6-REPORT.md` if it exists. Tests first (`test_ad9_…`); real transient systemd units for the
gateway path; no interactive flags; no new migrations; standard env + PATH + CPUQuota +
`--basetemp=/tmp/a0d-basetemp6`; `make lint` per commit; no full `make check`/`pilot`. Offline only;
no pushes/merges/restarts/deletions; never print env vars/keys.

## Report
`a0d-fix6-REPORT.md` (top marker `A0-D FIX6: ALL FINDINGS ADDRESSED`). Final message: one line for
AD9-1, then the report path.
