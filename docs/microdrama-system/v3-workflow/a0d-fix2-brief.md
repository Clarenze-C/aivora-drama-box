# A0-D fix round 2: the ten round-2 Codex findings AD5-1..AD5-10 (GLM build; drama-box repo)

Orchestrator: GLM (weekend runbook, operator-approved A-track fix), 14 Nov 2026. Round 1 fixed AD-1..13
at `6974d5a` (gate green there). The round-2 review (`codex-review-a0d-r2.md`) returned FIX-REQUIRED:
6 closed, AD-1 REGRESSED, and AD5-1..10. **You fix all ten on top of `6974d5a`.** The operator has
authorized a round-3 verification after this fix.

## Read first (absolute paths)

- `codex-review-a0d-r2.md` — the findings table + AD5-1..10, each with file:line and a Fix direction.
  **That file is your requirement list; where this brief disagrees, the review wins** (say so in the
  report).
- `a0d-fix1-REPORT.md` — round-1 context incl. the six documented deviations (AD-9 twin validators etc.).
- `phase-A0-spec.md` v0.4 §4–§5.

## Where you work

Worktree `/root/AIVORA/drama-box/.scratch/a0d-gateway`, branch `feat/a0d-gateway`, at `6974d5a`.
Commit on top; never amend/rebase; `microdrama/.venv` is a symlink — never stage it. **If
`a0d-fix2-REPORT.md` exists, you are resuming** — continue from its "Resume here".

## Priority order (regression first)

1. **AD5-1 (AD-1 REGRESSED)** — the gateway now requires `policy_identity` the step never sends:
   normal frozen calls fail admission (`gateway.py:329` vs `step.py:139`). Freeze and propagate the
   expected identity consistently, bind it to qualification, and **test the actual frozen-call
   producer against gateway admission** (the shim's echo masked this producer mismatch).
2. AD5-2 (exited-unit false no-execution evidence), AD5-3/AD5-4 (twin-validator equivalence,
   cancellation adoption bypass), AD5-5 (quota mapping vs A0-R1), AD5-6 (conflicting result/quota
   replays), AD5-7 (settlement evidence loss), AD5-10 (requalification clearance) — each per the
   review's Fix line.
3. AD5-8/AD5-9 (SHOULD-FIX): pending-submit cancellation races; failed admission's blocking intent.

## Test rules

Tests first per finding (named `test_ad5_…`), red recorded then green. The producer-vs-admission test
from AD5-1 is mandatory and must run the real `FrozenLlmCall` producer, not the shim. Real PostgreSQL
for the race cases; real transient systemd units where gateway launch is exercised
(`dramabox-llm-test-` prefix, fake shim, clean up your own units). **No interactive pytest flags.**
No new migrations (0027 is the A0-D tail; 0028–0031 belong to A1).

## Hard limits

Same as round 1: offline only (OFFLINE_MOCK, paid/cloud/public off); no model/network calls; no
pushes/merges/service-restarts (your own test units excepted); no deletion commands; never print env
vars/keys/tokens. pytest under `systemd-run --scope -p CPUQuota=45% --quiet` with
`env PATH="/usr/sbin:$PATH"`, the four offline env vars, `--basetemp=/tmp/a0d-basetemp2`, each command
< 10 min. Red runs via `git show <rev>:<path> > <path>` or a scratch-branch WIP commit — never
stash-only. `make lint` before every commit. Don't run the full `make check`/`make pilot` — the
orchestrator gates after the round-3 review.

## Pace

At the z.ai limit or a 429: stop at a clean point, commit green work, list uncommitted in the report,
update "Resume here".

## Report

Write `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/a0d-fix2-REPORT.md`: per-AD5 status +
commits, red/green lines, deviations with reasons, "Resume here". When done, put
`A0-D FIX2: ALL FINDINGS ADDRESSED` at the top. Final message: one line per AD5 id, then the report path.
