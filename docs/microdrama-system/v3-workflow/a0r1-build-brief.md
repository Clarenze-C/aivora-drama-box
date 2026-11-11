# A0-R1 build: the isolated `dramabox-llm` ai-route role (GLM build; claude-configs repo)

Orchestrator: Opus, 11 Nov 2026. The operator approved building phase A0. You are the builder.

## The spec is the requirement

Read it fully first: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-A0-spec.md` **v0.4**.
**This package builds only §3**, the ai-route half.

Also read:
- `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/a0-factmap.md` (facts about `ai_route.py`
  today);
- the three Codex reports beside it (`codex-a0-critique.md`, `codex-a0-recritique.md`,
  `codex-a0-round3.md`).

Their replacement wording is already folded into v0.4 and is binding. If anything is impossible against
the code, **stop at a red test** and explain it in the report. Never invent behaviour. Record every
judgement call with its reason.

## Where

- The repo is claude-configs (`/root/.claude`, branch `main`). You run in **your own git worktree** of it
  (ai-route `-w`). The main checkout has unrelated auto-logger churn: never touch it.
- Files you may change: `scripts/ai_route.py`, `models.json`, and new tests under
  `scripts/tests/ai_route/`. Nothing else.
- **Commit in the worktree, on top. Never amend or rewrite.** The orchestrator merges after review.
  **Never copy your files into the live `/root/.claude`.** Every running session uses that ai-route.

## Work packages, in order

Commit at the end of each package with its tests green. After each package, update the report.

| Pkg | Spec | Acceptance (A0 IDs; ai-route part only) |
|-----|------|------------------------------------------|
| R1a | §3.1 role, the `--model` allowlist, `--max-budget-microusd` → `--max-budget-usd` at the boundary; §3.2 strict argv, fixed environment, absolute executable paths, the empty-cwd check + the hash-bound qualification-fixture exception, new session + SIGTERM handling, `--deadline-s` | A0-2, A0-3 |
| R1b | §3.3 self-check: qualified version, **PTY help capture with a completeness check**, the policy-source inventory + refusals, the built-in executable-extension inventory, policy identity | A0-5 (ai-route part) |
| R1c | §3.4 admission (integer basis points, retry times, `REFUSED` only for admission reasons); §3.5 result/3: dedupe by `(invocation_id, attempt)` under `flock`, the write order, integer fields, canonical-text JSON, stream-json parsing (init event → `effective_tools`/`mcp_servers`, tool-use events → `tool_calls`, the final result event), **the runtime isolation assertion including missing or malformed init**, the raw stream file | A0-5 (runtime assertion), A0-6 (admission), A0-7 (dedupe) |
| R1d | Regression: **every existing role keeps an identical argv and environment** (snapshot tests generated from the current `main` before your changes); the Pro caller restriction (`ai_route.py:1363`) stays global; `--quota`, `--status` and `--list` unchanged | A0-13 (ai-route part) |

### Policy sources (R1b)

- Determine the Linux managed-policy sources for the pinned CLI version from the **official Claude Code
  documentation** (managed settings file, drop-in directory, server-managed/remote settings, MCP policy
  file, any policy helper), with their precedence.
- Record them in `models.json: dramabox_llm.policy_sources` with the documentation URL.
- **Anything you can't confirm from the official docs is recorded `UNCONFIRMED`, and the self-check
  refuses while any entry is unconfirmed (fail closed).** The operator confirms it later. Never guess.

### Rules for every package

- **Tests first:** run each new test red and record its pytest summary line, then implement it.
- **A fake `claude` shim only.** Tests **never run the real `claude` binary** and never make model or
  quota calls. The pinned claude path, the quota reader, caller detection and subprocess execution are
  **injection seams**, not weakened checks.
- **Credentials:** tests use a temporary `HOME` with a synthetic `.credentials.json`. **Never open, copy
  or print the real `/root/.claude/.credentials.json`** or any real token.
- The shim must cover:
  - a help text over 8 KB (to prove PTY capture);
  - an init event with extra tools or MCP servers;
  - a missing or malformed init event;
  - a non-`StructuredOutput` tool call;
  - a `setsid` grandchild that ignores TERM (SIGTERM handling inside ai-route only; unit containment is
    tested in the drama-box package);
  - a missing `total_cost_usd`;
  - fractional quota inputs.

## Hard limits

- **Offline only.** No model calls, no quota endpoint calls, no network except reading the official
  documentation pages for the policy-source inventory.
- No systemd units, no service restarts, no edits outside your worktree, no pushes, no merges.
- Run every pytest under `systemd-run --scope -p CPUQuota=45% --quiet` with
  `--basetemp=/tmp/a0r1-basetemp`. Keep each command under 10 minutes.
- Never print environment variables, `.env` files, keys, tokens or auth headers. Use synthetic secrets
  only.
- No deletion commands in shell (`rm`, `git rm`, `git clean`, `git reset`, `find -delete`). Overwrite
  files instead.

## Pace

- The z.ai window is shared with other sessions' builds.
- If you are near the limit or get a 429:
  1. stop at a clean point;
  2. commit the green work;
  3. list any uncommitted files in the report;
  4. update "Resume here".
- Never poll with `sleep` loops. Run long test files as background units and read their logs when they
  finish.

## Report

Write `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/a0r1-build-REPORT.md`, a separate file
from `--out`, and update it after every package:
- each package's status and commit hashes;
- red/green pytest summary lines per test;
- the argv/environment snapshot diff for every existing role (it must be empty);
- the policy-source inventory with its URLs and `UNCONFIRMED` entries;
- every judgement call;
- anything stopped at red;
- a "Resume here" line.

When R1a–R1d are all done and green, put this exact line at the top: `A0-R1: ALL PACKAGES DONE`.

Final message: one line per package, then the report path.
