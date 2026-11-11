**Verdict: FIX-REQUIRED (round 1).**

Reviewed `main...HEAD` through `02af779` against spec v0.4 §3 and the requested acceptance criteria. Six findings are blocking.

1. **RR-1 — BLOCKING — A duplicate overwrites the active attempt’s state.**  
   [scripts/ai_route.py:1855](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1855), [scripts/ai_route.py:1830](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1830)  
   A duplicate observing `"running"` calls `finish()`. That writes `REFUSED` into the owner’s canonical completed-result file and deletes its `.running` marker while the owner continues executing. Further duplicates can replay `launched=false` for an executing call. I reproduced both writes and the unlink in memory. **Fix:** give duplicate observers a response path that cannot modify the owner’s registry state; require ownership verification under the lock for completion.

2. **RR-2 — BLOCKING — Lookup and registration do not form an atomic dedupe operation.**  
   [scripts/ai_route.py:1729](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1729), [scripts/ai_route.py:1844](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1844)  
   Request B can miss the completed result, spend time in preflight, then register after request A completes and exits. `strict_register()` checks only `.running`, never the newly written completed result, so B can execute the same attempt again. Completion itself also runs outside the registry lock. **Fix:** atomically recheck completed/running state and claim ownership under `flock`; publish completion under that same protocol.

3. **RR-3 — BLOCKING — Nonzero exits bypass the runtime isolation assertion.**  
   [scripts/ai_route.py:1968](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1968)  
   A stream exposing `Bash`, an MCP server, or missing initialization evidence followed by exit 1 remains `CLI_ERROR`/`CAP_EXCEEDED`. Its output is retained, and the gateway receives no `ISOLATION_VIOLATION` to turn health red. In-memory probes reproduced this. Builder judgment call 4 contradicts §3.5; an error exit does not establish isolation. **Fix:** evaluate initialization and tool evidence independently of the CLI’s success status, discard violating output, and give violations the required outcome.

4. **RR-4 — BLOCKING — Error result events can become `SUCCEEDED`.**  
   [scripts/ai_route.py:1325](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1325)  
   Classification ignores the final event’s `is_error` and effectively ignores its subtype when exit status is zero. A valid init followed by `is_error=true, subtype=error_max_budget_usd` produces `SUCCEEDED`; I reproduced it. **Fix:** classify using validated terminal-event semantics as well as process status. Require affirmative success evidence and map cap/error subtypes explicitly.

5. **RR-5 — BLOCKING — The internal deadline leaves blocking operations unbounded.**  
   [scripts/ai_route.py:1471](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1471), [scripts/ai_route.py:1913](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1913), [scripts/ai_route.py:1946](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1946)  
   PTY capture can block in `os.read()` before reaching its timeout; prompt writing can block before the deadline is established; and a child that closes stdout but remains alive reaches an unlimited `proc.wait()`. The last case was confirmed with an in-memory process substitute. SIGTERM does not reliably release these waits. **Fix:** use a shared deadline and cancellable, bounded I/O/waits throughout, with bounded TERM→KILL cleanup and terminal-result emission.

6. **RR-6 — BLOCKING — Policy inspection permits executable credential helpers.**  
   [scripts/ai_route.py:1446](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1446), [scripts/ai_route.py:1575](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1575)  
   The denylist accepts `apiKeyHelper`, `otelHeadersHelper`, `statusLine`, and `fileSuggestion`; synthetic inspection confirmed this. In particular, `apiKeyHelper` is a shell command supplying model credentials, which defeats the HOME-only credential contract. Managed command customizations can survive safe mode. See the official [settings reference](https://code.claude.com/docs/en/settings-reference#apikeyhelper) and [safe-mode reference](https://code.claude.com/docs/en/cli-reference). **Fix:** inventory and reject executable policy settings beyond `policyHelper`, with pinned-version tests covering authentication and telemetry helpers.

7. **RR-7 — SHOULD-FIX — Structured output comes from an attempted tool call rather than the terminal validated result.**  
   [scripts/ai_route.py:1288](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1288)  
   A terminal event containing `structured_output` without the synthetic assistant tool event becomes `PARSE_ERROR`. Conversely, arbitrary `StructuredOutput` tool input is accepted even without terminal confirmation. Both cases reproduced in memory. The documented result contract exposes validated output in [`structured_output`](https://code.claude.com/docs/en/headless#structured-output). **Fix:** consume the authoritative terminal field, validate its presence and consistency, and make the shim represent that contract.

8. **RR-8 — SHOULD-FIX — Malformed stream fields escape without a machine result.**  
   [scripts/ai_route.py:1281](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1281), [scripts/ai_route.py:1324](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1324)  
   An assistant event with `"message":"bad"` raises `AttributeError`; an invalid cost raises `decimal.InvalidOperation`. These escape through the outer exception handler rather than producing durable `PARSE_ERROR`. Both reproduced. **Fix:** validate event shapes and numeric fields, catch decoding/conversion failures at the parser boundary, and retain the raw evidence while emitting the explicit failure result.

9. **RR-9 — SHOULD-FIX — A missing remote-policy cache is treated as proven absence.**  
   [scripts/ai_route.py:1521](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1521)  
   After an entry becomes `CONFIRMED`, either a null path or nonexistent cache passes inspection as absent. Neither proves that remote policy is unconfigured or resolved; the CLI can fetch policy at startup. The official [managed-settings documentation](https://code.claude.com/docs/en/managed-settings) describes that fetch/cache behavior. **Fix:** distinguish positively established absence from configured/unresolved policy and bind the identity to the policy the launched CLI actually uses. Changing the status string alone must not unlock this path.

10. **RR-10 — SHOULD-FIX — The quota test seam is an ambient production override.**  
    [scripts/ai_route.py:1649](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1649)  
    Any permitted invocation inheriting `AI_ROUTE_TEST_QUOTA_FILE` substitutes caller-controlled quota data for the real reader. Clearing the *child* environment does not protect this parent-side admission decision. The gateway’s fixed environment mitigates its documented launch path, but the production entry point still contains a bypass. **Fix:** inject the quota reader through the test harness rather than an unrestricted environment variable in production execution.

11. **RR-11 — SHOULD-FIX — Allowing unreadable quota also disables concurrency admission.**  
    [scripts/ai_route.py:1678](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1678)  
    With `refuse_if_quota_unreadable=false`, the early `return None` skips `max_concurrent`. An unreadable snapshot with one existing job is admitted; reproduced in memory. This option is explicitly exercised by the new tests. **Fix:** skip only quota-dependent comparisons and always enforce concurrency.

12. **RR-12 — SHOULD-FIX — Regression snapshots omit important paths they claim to cover.**  
    [scripts/tests/ai_route/snap_matrix.py:109](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/tests/ai_route/snap_matrix.py:109)  
    The condition `"brief" in vname` is false for every named headless case. All five `plan` variants therefore record `headless=false` and omit `-p`; independently reproduced. The matrix also stops before `main()` appends session arguments and the progress paragraph, while helper fixtures do not execute `--quota`. **Fix:** correct prompt selection and capture final launch argv/environment/stdin through entry-point shims, including goldfish preparation and quota/status behavior. Scope and restore the global clock patch in `behavior_matrix.load()`.

13. **RR-13 — SHOULD-FIX — Result and raw-stream opens follow symlinks.**  
    [scripts/ai_route.py:1363](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1363), [scripts/ai_route.py:1910](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1910)  
    Predictable `.tmp` and `.raw.jsonl` paths use ordinary truncating opens. In a writable output directory, a planted symlink can cause unrelated files to be truncated; pathname-based `chmod` introduces another race. The specified private gateway store mitigates this, but ai-route accepts arbitrary result paths. **Fix:** validate the parent directory, use exclusive/no-follow opens with mode 0600, verify file types, and apply permissions through the opened descriptor.

14. **RR-14 — SHOULD-FIX — The qualification exception remains available to ordinary production invocations.**  
    [scripts/ai_route.py:1413](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1413)  
    Once the fixture is configured, any caller passing `--allow-qual-fixture` bypasses the production empty-cwd requirement. The hash limits this to the configured fixture; it does not establish that the invocation belongs to live qualification. **Fix:** make qualification a separately controlled launch mode and reject the exception in the production gateway profile.

15. **RR-15 — SHOULD-FIX — Empty-cwd validation does not hold through launch.**  
    [scripts/ai_route.py:1859](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1859), [scripts/ai_route.py:1888](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1888)  
    The directory is checked before help capture and quota reads, then used later without revalidation. No external race is needed: `--result-json <strict-cwd>/nested/result.json` makes ai-route create `nested/` after the check and before spawning. **Fix:** reject output paths inside the execution directory, validate ownership/symlinks, and enforce emptiness immediately before launch in a protected directory.

Several requested properties are implemented correctly: the strict argv omits `--bare`, progress configuration and worktree arguments; the shipped executable path is absolute; the child environment is constructed without inheritance; budget conversion is exact integer arithmetic; and ordinary result publication follows tmp→fsync→rename→directory-fsync→journal. Model allowlisting and UUID parsing prevent the requested model/invocation path-injection cases.

The shipped `UNCONFIRMED` policy and built-in inventories correctly block launch, as does the unset expected identity. Those are deliberate qualification blockers. Identities reported after an early inventory refusal are partial inspection hashes and should not be accepted as qualification evidence.

I verified that the baseline argv/env fixture precedes the production changes and reproduced both committed fixtures against pristine `main` and HEAD, subject to RR-12’s coverage gaps. Existing role builders and the existing Pro caller restriction remain intact. The new tests generally invoke the real entry point with the fake shim; I found no real CLI or network execution in those test paths.

This review made no filesystem changes or credential/quota/model calls. Validation used read-only inspection, `git diff --check`, and in-memory probes. I did not rerun filesystem-writing pytest suites; the supplied 62-pass receipt and baseline-identical observability failures remain orchestrator-provided evidence.