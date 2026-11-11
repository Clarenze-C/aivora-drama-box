# T031 H-2 fix round 4 (R4): the final review's HD-1..HD-3 and the test-only proof gaps (GLM build, money path)

Orchestrator: Opus, 11 Nov 2026. **The operator approved this round with orchestrator-only verification:
no further Codex round.** The orchestrator re-runs every red/green line you report and the full gate. If
that fails, T031 is parked, so report exactly what you ran.

**If `T031-fix-round/h2-r4-REPORT.md` already exists, you are resuming:** read it, continue from its
"Resume here", and don't redo committed packages.

## The requirement

- **Findings:** `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/codex-review-hcf-final.md`.
  HD-1, HD-2 and HD-3 are accepted, and **Codex's "Fix" paragraphs are binding.**
- **Rulings and known limits:** `T031-fix-round/rulings-hcf-final.md`. **HC-6, HC-9, HC-11 and HB-13
  (broad) are known limits: out of scope. Don't touch them.**
- Spec v3: `/root/AIVORA/drama-box/docs/microdrama-system/T031-H2-recovery-spec.md` (R7 for HD-1).
- The previous round's report: `T031-fix-round/h2-hcf-REPORT.md`.

If a fix is impossible against the code or the spec, **stop that item at a red test** and explain it.
Never invent behaviour. Record every judgement call with its reason.

## Where

- Worktree (your cwd): `/root/AIVORA/drama-box/.scratch/t031-fix3-worktree`, branch `feat/t031-fix3`,
  HEAD **`7060e02`** (HCF F5).
- Commit on top. Never amend or rewrite. `microdrama/.venv` is a symlink: never stage it.
- **Don't touch** `.scratch/t031-gate-hcf`: the orchestrator's gate is running there.

## Packages, in order

Commit at the end of each package with its tests green, and update the report after each.

| Pkg | Item | What "done" means |
|-----|------|-------------------|
| **R1** | **HD-1** (BLOCKING) | `resolve_sample` binds the newly composed RECOVERY world to the owning acquisition **before** probing. A local composition or binding failure of the RECOVERY probe (`EffectDenied`, a binding that isn't `BOUND`, any exception from composing or binding) **refuses the resolution even with `--force-unrecoverable`**; it is never evidence that work is unrecoverable. Only the evidence that spec R7 names may reach the force path: quote the R7 text you rely on in the report. **Tests** use a world factory that returns **independently constructed, initially unbound** clients for each mode, and prove: (a) recoverable work (an accepted prompt discoverable by deterministic client ID, UNKNOWN without `external_id`) refuses even with force; (b) a RECOVERY bind failure refuses even with force; (c) reachable, genuinely unrecoverable work still resolves with force. Show (a) and (b) red against `7060e02` |
| **R2** | **HD-3** (BLOCKING) + the HC-10 proof gaps | **HD-3:** the race tests whitelist only the specific expected admission refusals and **reject `ServiceUnavailable`**, including translated SQLSTATE `40P01` and `55P03`. Prove the proof works: inject each translated failure and show the assertion fails. **HC-10 gaps** (test-only): (1) the billing-wrapper race (`test_t031_h2b_p4_resolution.py:632`) must fail if the wrapper's lock order is inverted back to its pre-P4 order, so don't queue the wrapper first behind an account holder; show that red with a temporary WIP commit on a scratch branch that restores the old order; (2) AT-9's `sweep_finalization_mid` (`test_t031_h2b_p5_terminal.py:530`) injects a real crash **mid-finalization** (between finalization stages), and the next sweep completes every stage exactly once; (3) F2's L-lock test sets `lock_timeout` **explicitly on the worker connection** |
| **R3** | **HD-2** (SHOULD-FIX) | Before choosing a `late:` identity, the normaliser recovers an already-posted interval's immutable identity, and the decision is serialised with posting and closure. Test: an interval posted while ACTIVE → crash before `accrued_until` advances → settlement closes the reservation → the replay of that interval is accepted as the same receipt (same UUID and provider receipt key) and advances `accrued_until`. Show it red against `7060e02` |

## Rules (as in the HCF brief)

- **Tests first:** run each new or changed test red against the committed code and record its pytest
  summary line, then fix it.
- **Real PostgreSQL** for every lock and race test (two or more connections, barriers, `lock_timeout` set
  on **every** participating connection).
- Never call `_advance` directly in new tests. **Never weaken a fixture or an assertion to make a test
  pass.** Pre-existing tests change only where a finding above requires it; list each one.
- Offline only. Export `MICRODRAMA_EXECUTION_MODE=OFFLINE_MOCK MICRODRAMA_PAID_REQUESTS_ENABLED=false
  MICRODRAMA_CLOUD_RESOURCES_ENABLED=false MICRODRAMA_PUBLIC_ACTIONS_ENABLED=false`.
- No provider or network calls, no docker, no pods, no service restarts, no pushes, no merges.
- Leave migrations 0001–0025 alone; 0026 changes only if a finding requires it (none does).
- Run every pytest under `systemd-run --scope -p CPUQuota=45% --quiet` with
  `--basetemp=/tmp/t031-r4-basetemp`. Keep each command under 10 minutes and run focused files.
- **Run `make lint` (it includes `ruff format --check`) before every commit.**
- **For red runs, never stash:** use a temporary WIP commit on a scratch branch, or restore committed file
  versions with `git show <rev>:<path> > <path>` and re-apply your saved diff from a file.
- Never print environment variables, `.env` files, keys, tokens or auth headers.
- No deletion commands. Overwrite files instead.
- Do NOT run the full `make check` or `make pilot`. The orchestrator runs them.

## Pace

- If you are near the z.ai limit or get a 429:
  1. stop at a clean point;
  2. commit the green work;
  3. list any uncommitted files in the report;
  4. update "Resume here".
- **Never leave code edits only in a stash.** No `sleep` polling.

## Report

Write `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/h2-r4-REPORT.md`, a separate file
from `--out`. It must contain:
- each package's status and commits;
- **the exact command and pytest summary line for every red and every green run**;
- the R7 text relied on for R1;
- every pre-existing test you changed, and why;
- every judgement call;
- anything stopped at red;
- "Resume here".

When R1–R3 are all done, put this exact line at the top: `H2-R4: ALL FIXES DONE`.

Final message: one line per package, then the report path.
