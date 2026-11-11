# T031 H-2 fix round HCF: Codex P4/P5 review findings (GLM build, Large, money path)

Orchestrator: Opus, 11 Nov 2026. The operator approved this fix round and one final Codex review.

## The requirement

- **Findings:** `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/codex-review-h2-p4p5.md`.
  - **All of HC-1..HC-12 are accepted.** Codex's "Fix" paragraphs are binding.
  - Its HB/L tables name the partial items. Each one is closed by the matching HC fix below.
- **Spec v3:** `/root/AIVORA/drama-box/docs/microdrama-system/T031-H2-recovery-spec.md`, unchanged.
- **Your build report:** `T031-fix-round/h2-build-REPORT.md`, with its transaction inventory, which HC-6
  says is inaccurate.
- **Contract:** `T031-integration-contract.md`.

If a fix is impossible against the code or the spec, **stop that item at a red test** and explain it.
Never invent behaviour. Record every judgement call with its reason.

## Where

- Worktree (your cwd): `/root/AIVORA/drama-box/.scratch/t031-fix3-worktree`, branch `feat/t031-fix3`,
  HEAD **`4e28514`**. That is the P5 tip plus a formatting-only commit.
- Commit on top. Never amend or rewrite. `microdrama/.venv` is a symlink: never stage it.
- **Don't touch** `.scratch/t031-gate-h2` or `.scratch/t031-gate-h2b`. Those are orchestrator checkouts
  with gates running.

## Orchestrator rulings

1. **HC-2 is ruled first, as package F1.**
   - Spec v3 allows exactly three canonical edits: the billing-wrapper lock order (§6.1), the EXPIRED
     recovery-read exception (§3.3), and the `_settle_if_needed` EXPIRED handling.
   - **The P4/P5 changes to `budget/service.py` and `rendering/leases.py` go beyond them.**
     1. **First, revert those out-of-spec canonical edits** to their `45e4f2a` behaviour.
     2. Meet whatever need they served **in the benchmark layer**.
     3. Only if that is impossible may you keep a canonical change. It must then follow Codex's HC-2 Fix
        exactly:
        - immutable receipt identity and content across replay;
        - reuse the existing settlement;
        - post only genuinely new deltas on closed reservations;
        - normalise interval receipts before the replay comparison.

        Record it as a judgement call.
   - Either way, add replay tests:
     - the same receipt identity → identical content;
     - a closed reservation with a prior late adjustment posts only the new delta (100 stays 100);
     - an interval crash after posting and before advancing `accrued_until` replays cleanly.
   - **The canonical and canary suites stay green (AT-26).**
2. **HC-1:** "billing ready" means the **canonical invoice finality of the discovered resource**. A
   reservation settled before the contradiction is never evidence.
3. **HC-3:** positively recoverable work (including recovery by deterministic client ID, and EXPIRED
   reads through the RECOVERY composition) **refuses resolution even with `--force-unrecoverable`**.
4. **HC-6:** **one** ordered lock helper including L and S, used by every listed transaction. **Rewrite
   the transaction inventory in the report from the actual SQL.**
5. **HC-10:** tests call the real public implementations with fresh worlds, real boundary injection,
   precise exceptions and exact counts (no `>=` for dedup counts, no blanket `except`).
   - `lock_timeout` is applied to the worker connections.
   - HB-13: storage finality requires canonical financial finality.
   - L-1/L-2: S08 is **actually bound** with the changed costume.
6. **HC-11, HC-12** (SHOULD-FIX) are in scope.

## Packages, in order

Commit at the end of each package with its tests green; update the report after each.

| Pkg | Findings | Closes (partials) |
|-----|----------|-------------------|
| F1 | HC-2 (ruling 1) | — |
| F2 | HC-6 lock helper + inventory; HC-5 ownership on every control write and send authorisation | HB-7, HB-8, HB-9 |
| F3 | HC-1 storage finality; HC-7 every reservation entry point; HC-8 durable ambiguity before non-BOUND exits; HC-9 deadline recompute + aggregate windows | HB-5, HB-6, HB-11, HB-12 |
| F4 | HC-3 R7 recoverability; HC-4 complete terminal replay + U4 failed-outcome + durable success assets | — |
| F5 | HC-10 test proofs; HC-11 CLI recovery-first ordering; HC-12 durable incident record in status/export | HB-10, HB-13, L-1, L-2 |

## Rules (as in the original brief)

- **Tests first:** run each new or changed test red against the committed code and record its pytest
  summary line, then fix it.
- **Real PostgreSQL** for every lock and race test (two or more connections, barriers, bounded
  `lock_timeout` on the participating connections).
- Never call `_advance` directly in new tests. **Never weaken a fixture or an assertion to make a test
  pass.**
- Offline only. Export `MICRODRAMA_EXECUTION_MODE=OFFLINE_MOCK MICRODRAMA_PAID_REQUESTS_ENABLED=false
  MICRODRAMA_CLOUD_RESOURCES_ENABLED=false MICRODRAMA_PUBLIC_ACTIONS_ENABLED=false`.
- No provider or network calls, no docker, no pods, no service restarts, no pushes, no merges.
- Leave migrations 0001–0025 alone; edit only 0026, in place.
- Run every pytest under `systemd-run --scope -p CPUQuota=45% --quiet` with
  `--basetemp=/tmp/t031-hcf-basetemp`. Keep each command under 10 minutes and run focused files.
  - **Run `make lint` (it includes `ruff format --check`) before every commit.** The last gate failed on
    formatting.
- Never print environment variables, `.env` files, keys, tokens or auth headers.
- No deletion commands (`rm`, `git rm`, `git clean`, `git reset`, `find -delete`). Overwrite files
  instead.
- Do NOT run the full `make check` or `make pilot`. The orchestrator runs them.

## Pace

- If you are near the z.ai limit or get a 429:
  1. stop at a clean point;
  2. commit the green work;
  3. list any uncommitted files in the report;
  4. update "Resume here".
- No `sleep` polling.

## Report

Write `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/h2-hcf-REPORT.md`, a separate file
from `--out`. It must contain:
- each package's status and commits;
- red/green summary lines per test;
- **the corrected transaction inventory** (function → locks in order → writes);
- every judgement call;
- anything stopped at red;
- "Resume here".

When F1–F5 are all done, put this exact line at the top: `H2-HCF: ALL FIXES DONE`.

Final message: one line per package, then the report path.
