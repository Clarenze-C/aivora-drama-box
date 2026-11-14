# A1 build: the discriminator, gates and decision transaction — migrations 0028–0031 (GLM build; drama-box repo)

Orchestrator: GLM (operator-approved Phase A day), 14 Nov 2026. **A0-D is ACCEPTED** (R7 ACCEPT +
decisive gate green at `eea2f79`); its branch `feat/a0d-gateway` is your base. The A1 design note is
**ACCEPTED** (v1.4, R4 APPROVE).

## The requirement

Read fully: **`A1-design-note.md` v1.4** — it is the binding design; every § is normative. Also
`phase-A-spec.md` v0.3 (§10's A1 package row: the discriminator, gates registry, decision
transaction; §2 command table; §7 lock order) and `SPEC-v3.md` §2.2/§15 (V3-AT-1, 2, 13, 16, 20, 21
as superseded). If anything is impossible against the code, stop at a red test and explain.

Also read: `A3-design-note.md` v1.3 (accepted — the fence/jobs seams A1 provides), `B1-design-note.md`
v0.3 (accepted — the registry/prompt tables B1 builds on), `A2-design-note.md` v1.3 (parked — budget
hierarchy facts only; conflicts → report, don't resolve).

## Where you work

Worktree `/root/AIVORA/drama-box/.scratch/a0d-gateway`, branch `feat/a0d-gateway`, at `eea2f79`
(A0-D's accepted tip). Commit on top; never amend; the `.venv` symlink never staged. **If
`a1-build-REPORT.md` exists, resume from its "Resume here".**

## Packages, in order (per the note's build plan; one commit each, tests first)

D1 → D2 → D3 → D4 as the note numbers them (migrations **0028–0031 only** — the note's allocation;
no other numbers). Red lines recorded per acceptance row before each implementation. **The build's
Codex review will verify A1's acceptance rows explicitly** (V3-AT-1 stepper/gate statuses, V3-AT-2
no-transition-without-approval + stale-hash refusal + Revise-scope, V3-AT-16 bot dedupe/timeout
seams as the note defines them).

## Test rules and hard limits

Real PostgreSQL for the transaction/race tests (two+ connections, bounded `lock_timeout`); the
decision transaction's concurrency cases from the note §exactly. Offline env vars + `env
PATH="/usr/sbin:$PATH"` + `systemd-run --scope -p CPUQuota=45%` + `--basetemp=/tmp/a1-basetemp`;
each command < 10 min; **no interactive pytest flags**; `make lint` before every commit; no full
`make check`/`make pilot` (the orchestrator gates after the review). Red runs via `git show` or a
scratch-branch WIP commit — never stash-only. Offline only; no pushes/merges/restarts/deletions;
never print env vars/keys. At the z.ai limit: stop clean, commit, update "Resume here".

## Report

`a1-build-REPORT.md`: per-package status + commits, red/green per acceptance row, the transaction
inventory (mutation → locks in order → writes), deviations, "Resume here". Top marker when done:
`A1: ALL PACKAGES DONE`. Final message: one line per package, then the report path.
