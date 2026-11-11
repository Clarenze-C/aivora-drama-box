# A0-R1 fix round 1 (GLM): Codex review findings RR-1..RR-15

Orchestrator: Opus, 11 Nov 2026. Codex reviewed your A0-R1 build:
`/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/codex-review-a0r1.md`. The verdict is
FIX-REQUIRED (round 1).

**All of RR-1..RR-15 are accepted; each "Fix" is binding.** The original brief still binds you:
`a0r1-build-brief.md` (same folder), along with spec `phase-A0-spec.md` v0.4 §3 and your report
`a0r1-build-REPORT.md`.

## Where

- The same worktree: `/root/.claude/.claude/worktrees/a0r1-airoute`, branch `worktree-a0r1-airoute`,
  HEAD `02af779`.
- Commit on top. Never copy anything into the live `/root/.claude`.

## Rulings

1. **RR-1 / RR-2 (dedupe):**
   - one protocol under the registry `flock`: atomically recheck completed and running state, claim
     ownership (an owner token in the `.running` marker), and publish completion under the same lock;
   - duplicate observers only read; **they never write or unlink the owner's files**;
   - a duplicate that finds the owner running returns a non-terminal `IN_PROGRESS` answer (exit 75 with
     `retry_at`), **not `REFUSED`, and never `launched=false`**.
2. **RR-3 / RR-4 (classification):**
   - the isolation evidence (init event, tools, MCP servers, tool calls) is evaluated **before and
     independently of** the exit status and the terminal event;
   - a violation discards the output → `ISOLATION_VIOLATION`;
   - success requires exit 0 **and** a terminal result event with `is_error=false` and `subtype=success`;
   - map the cap and error subtypes explicitly (`error_max_budget_usd` → `CAP_EXCEEDED`, others →
     `CLI_ERROR`).
3. **RR-5 (deadline):**
   - one monotonic deadline from process start;
   - non-blocking or `select`-bounded I/O for the PTY help capture, prompt writing and stream reading;
   - a bounded `wait(timeout)`;
   - TERM → KILL after 10 s;
   - always emit a terminal result (`DEADLINE`).
4. **RR-6 (policy):** reject every executable setting in any policy source: `apiKeyHelper`,
   `awsCredentialExport`, `awsAuthRefresh`, `otelHeadersHelper`, `statusLine`, `fileSuggestion`,
   `policyHelper`, and hooks of any kind. **Use an allowlist of known-inert keys**, so an unknown key
   refuses. Add pinned-version tests.
5. **RR-7:** structured output comes from the terminal result's `structured_output` field. Make the shim
   follow the documented contract.
6. **RR-8:** the parser boundary catches every decoding or conversion failure → a durable `PARSE_ERROR`,
   with the raw evidence kept.
7. **RR-9:** remote policy counts as absent **only when positively established**. Otherwise refuse;
   the `CONFIRMED` string alone must not unlock it. The identity binds to the policy sources the launched
   CLI would use.
8. **RR-10:** remove `AI_ROUTE_TEST_QUOTA_FILE` from the production path. Tests inject the quota reader
   through a module seam (monkeypatch or a test-only entry point), never an environment variable that
   production honours.
9. **RR-11:** always enforce `max_concurrent`.
10. **RR-12:**
    - fix the headless prompt selection;
    - capture the **final** launch argv, environment and stdin through entry-point shims, including the
      session arguments, the progress paragraph, goldfish preparation and `--quota`/`--status`;
    - scope and restore the clock patch;
    - **regenerate the baseline from pristine `main` `02b361a`** (in a temporary detached checkout or
      with `git show main:<path>`), never from your modified code.
11. **RR-13:**
    - validate the parent directory;
    - open with `O_CREAT|O_EXCL|O_NOFOLLOW` and mode 0600;
    - verify the file types;
    - `fchmod` through the descriptor.
12. **RR-14:** qualification is a **separate launch mode** (`--qualification`, plus a qualification
    record ID). **The strict production profile rejects the fixture exception outright.**
13. **RR-15:**
    - reject any `--result-json` path inside the execution cwd;
    - validate ownership and symlinks on the cwd;
    - re-check emptiness **immediately before spawn**.

## Rules

- **Tests first:** each finding gets a test that fails on `02af779`. Record the red summary line, then fix
  it.
- Use the fake `claude` shim only. No real `claude`, credentials, quota calls or network. Never weaken a
  check behind a test seam.
- Run pytest under `systemd-run --scope -p CPUQuota=45% --quiet` with `--basetemp=/tmp/a0r1-fix1-basetemp`.
- Also run the three existing scripts (`python3 scripts/tests/ai_route/test_guards.py`, `test_goldfish.py`,
  `test_observability.py`) and record their results.
  - `test_observability.py` already fails 3 checks on `main`. **Don't fix that here; only show the same
    3.**
- No deletion commands; overwrite files instead. Never print environment variables, keys or tokens.

## Pace

- At the z.ai limit or a 429: commit green work, list anything uncommitted in the report, and update
  "Resume here".
- **Never leave work only in a stash.**

## Report

Append a "Fix round 1" section to `a0r1-build-REPORT.md` with:
- one row per RR: commit, red/green lines;
- the regenerated snapshot proof;
- any judgement calls.

When every RR is done: put `A0-R1 FIX1: ALL DONE` at the top of the report.

Final message: one line per RR, then the report path.
