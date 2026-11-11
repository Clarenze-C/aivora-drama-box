# Codex review: A0-R1, the isolated `dramabox-llm` ai-route role (claude-configs)

Read-only. Worktree `/root/.claude/.claude/worktrees/a0r1-airoute`, branch `worktree-a0r1-airoute`.

**Scope: `git diff main...HEAD`.** That is 5 commits (`9776fb3`, `a6cf997`, `b0ce72e`, `646e42e`,
`02af779`), 11 files, about +3,390, in `scripts/ai_route.py`, `models.json` and
`scripts/tests/ai_route/`. GLM wrote them; you did not.

**This code will replace the live ai-route that every session uses**, so regressions matter as much as the
new role.

## The requirement

- `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-A0-spec.md` **v0.4, §3 only**, plus
  A0-2, A0-3, A0-5, A0-6, A0-7 and A0-13 (ai-route parts). Your A0C, A0R and A0S wording is folded in.
- The builder's brief and report, beside it: `a0r1-build-brief.md`, `a0r1-build-REPORT.md`. Read the
  judgement calls and the `UNCONFIRMED` policy entries critically.

## Orchestrator verification (11 Nov, 14:05Z)

- The 4 new test files: `62 passed`.
- `test_guards.py` and `test_goldfish.py`: ALL PASS.
- **`test_observability.py`: 3 FAILED, identically on `main` `02b361a`** (an existing, timing/load-
  sensitive failure, not from this diff).

## Review

1. **Isolation (§3.2, §3.3):**
   - the exact strict argv;
   - `--bare` absent;
   - the fixed environment (no inheritance leaks; credentials only via `HOME`);
   - absolute executable paths;
   - empty-cwd enforcement, and the hash-bound qualification-fixture exception (can it be abused to run
     a non-empty cwd in production?);
   - PTY help capture and its completeness check;
   - the policy-source inventory, and **fail-closed behaviour on `UNCONFIRMED` entries**;
   - the policy identity.
2. **Admission and results (§3.4, §3.5):**
   - integer basis points;
   - `REFUSED` only for admission reasons;
   - dedupe under `flock` by `(invocation_id, attempt)`;
   - the write order (tmp → fsync → rename → dir fsync → journal);
   - stream-json parsing;
   - **the runtime isolation assertion, including a missing or malformed init event**;
   - canonical-text JSON;
   - the raw stream file mode.
3. **Regression (A0-13):**
   - Do the snapshot fixtures really come from pristine `main`, and do they cover every existing role and
     path (build/swarm/critique/review/goldfish/plan/fast, worktree, progress MCP, `--quota`, `--status`,
     `--list`)?
   - Is the Pro caller restriction still global?
   - Any behaviour change for existing roles that the snapshots would miss?
4. **Tests:** real entry points with the fake shim? No real `claude`, credentials, quota calls or
   network? Any weakened check behind a test seam?
5. **New defects:** security (environment or secret leaks, path injection through `--model` or
   `--invocation-id`, symlink or permission races on the result and cwd paths), and concurrency.

## Output

- Read-only sandbox: no writes. Small in-memory probes are fine.
- Put the full report in your final message.
- Findings use `RR-1`…, with severity **BLOCKING / SHOULD-FIX / NIT**, `file:line`, a failure scenario and
  a fix.
- Verdict: **ACCEPT** or **FIX-REQUIRED** (round 1).
