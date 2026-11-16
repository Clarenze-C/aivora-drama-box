A0-R1 FIX1: ALL DONE

# A0-R1 build report — the isolated `dramabox-llm` ai-route role (claude-configs)

Builder: GLM (z.ai), 11 Nov 2026. Spec: `phase-A0-spec.md` **v0.4**, §3 only.
Worktree: `/root/.claude/.claude/worktrees/a0r1-airoute` (branch `worktree-a0r1-airoute`,
on top of `main` @ `02b361a`). Every commit is on top; nothing amended or rewritten;
nothing copied into the live `/root/.claude`.

## Status

| Pkg | Scope | Commit | Tests |
|-----|-------|--------|-------|
| baseline | R1d fixtures generated from **pristine main before any change** | `9776fb3` | generator determinism verified |
| R1a | §3.1 role + §3.2 strict profile (argv, fixed env, cwd rules, session, SIGTERM, deadline, budget boundary) | `a6cf997` | 15 passed |
| R1b | §3.3 self-check (qualified version, PTY help, policy inventory, builtin inventory, policy identity) | `b0ce72e` | 25 passed (suite total 40) |
| R1c | §3.4 admission + §3.5 dedupe / result-3 / runtime isolation assertion / raw stream | `646e42e` | 18 passed (suite total 58) |
| R1d | regression snapshots, caller rule global, --list/--status/--quota helpers | `02af779` | 4 passed (suite total 62) |
| fix1 | Codex RR-1..RR-15 + one test-rig race fix (found by the full-suite run) | `ffb3810`, `b9137f8` | 107 passed (full suite) |

Full-suite summary line (final): `62 passed in 144.89s` under
`systemd-run --scope -p CPUQuota=45%` with `--basetemp=/tmp/a0r1-basetemp`.

## Red → green record (pytest summary lines)

- R1a red (before any implementation): `15 errors in 1.54s` (`KeyError: 'dramabox_llm'`),
  then `15 errors` (fixture), then during bring-up `11 failed, 4 passed` →
  `8 failed, 7 passed` → `1 failed, 14 passed` → **`15 passed in 20.79s`** (commit a6cf997).
- R1b: the §3.3 wiring necessarily landed *with* R1a's re-greening (R1a's suite runs the
  strict path, which the self-check gates — deferring it would have left R1a red). The new
  R1b tests were written after and driven to green: `19 failed, 6 passed` (test bugs:
  unwritten restore, non-hex UUID suffixes, empty-dict hooks data) →
  `6 failed, 19 passed` → `3 failed, 22 passed` → **`25 passed`**; suite `40 passed in 63.53s`.
- R1c red: `18 failed in 13.19s` (non-hex/short UUID suffixes in the test rig, call-count
  semantics, sync-job test design) → `2 failed, 16 passed` → **`18 passed in 59.27s`**; suite
  `58 passed in 144.11s`.
- R1d red: `2 failed, 2 passed` (fixture normalization: sibling out-dir, tuple↔list JSON) →
  **`4 passed in 3.26s`**; total `62 passed in 144.89s`.

## The argv/environment snapshot diff (A0-13): EMPTY

`fixtures/argv_env_snapshot.json` was generated from pristine main (`02b361a`) **before any
code change** (commit `9776fb3`), under a fixed parent environment with provider-var canaries.
`test_existing_roles_argv_and_env_are_identical` rebuilds the full matrix (7 roles × up to 5
variants: headless/effort/worktree/no-steps/interactive for plan; headless variants for zai
roles; prompt/scope variants for codex) after the change and asserts equality — the diff is
empty by assertion (`assert not diff`). A second fixture (`behavior_snapshot.json`, frozen
clock) pins `opus_pace`, `pick_orchestrator`, `preflight` outputs and the pre-existing
`--list` lines: all identical.

Pre-existing script suites (`test_guards.py`, `test_observability.py`) are
environment-sensitive from this GLM session and under the 45% CPU quota: both were run
against **pristine main in a detached worktree under identical conditions and failed there
too** (different, timing-shaped failures per run: a stub timeout in the race section; a
live-file glob/unlink race; `Pro login, provider env stripped` leaks the session's
`ANTHROPIC_AUTH_TOKEN` — their own docstrings require a plain/Opus shell). This is recorded
as pre-existing flakiness, not regression; the deterministic fixtures above are the R1d
gate. `test_goldfish.py`: **ALL PASS** after all changes.

## Policy-source inventory (R1b) — from the official docs

Linux, pinned CLI **2.1.322**. Source: the official managed-settings documentation
(https://code.claude.com/docs/en/managed-settings, page dated 2026-11-03) and
https://code.claude.com/docs/en/managed-mcp. Recorded in `models.json: dramabox_llm.policy_sources`:

| # | Source | Linux location | Precedence | Status |
|---|--------|----------------|------------|--------|
| 1 | server-managed (remote) settings | fetched at startup from claude.ai or a gateway; local cache replaces on each successful fetch | 1 (highest) | **UNCONFIRMED** — the docs confirm the mechanism but document **no local cache path** ai-route can read offline |
| 2 | managed settings file | `/etc/claude-code/managed-settings.json` | 3 (file tier; read at startup, reloaded on change) | CONFIRMED |
| 3 | managed settings drop-ins | `/etc/claude-code/managed-settings.d/*.json` (non-hidden, alphabetical, merged after the main file) | 3 (file tier) | CONFIRMED |
| 4 | managed MCP policy file | `/etc/claude-code/managed-mcp.json` (standalone `{"mcpServers": …}}`, exclusive control, not server-managed-deliverable) | file tier (MCP policy) | CONFIRMED |
| 5 | policy helper | the `policyHelper` key inside any present file-tier source; an executable whose emitted `managedSettings` replaces the selected policy | replaces the selected source | CONFIRMED (always refused by the self-check) |

Non-Linux sources excluded and recorded in `policy_non_linux_sources`: macOS MDM plist
(`com.anthropic.claudecode`), Windows HKLM and HKCU registry values. The docs' full order is
remote → MDM → files → HKCU; on Linux only 1 and the file tier exist.

**Fail-closed consequences in production today** (all deliberate, until the operator confirms
at §7): the UNCONFIRMED remote-settings entry and the `builtin_extensions["2.1.322"]` entry
(UNCONFIRMED: the docs say `--safe-mode` keeps "built-in tools/plugins" but document no
enumeration of them) each make the self-check return `ISOLATION_UNAVAILABLE`;
`expected_policy_identity` is `null` (not yet qualified) for the same reason. A builder-level
smoke run against the **real** pinned CLI (local `--version` and PTY `--help` only — no model
call; tests never touch the real CLI) confirmed: version check passes (`2.1.322`), the
complete-help check passes against the real 22,663-byte help (strict flags at bytes 8662–18593
and the tail marker at 22114, all beyond the ~8 KB piped truncation), and the run then refuses
on the UNCONFIRMED inventory, reporting the computed identity (`b8859139b2ea21c7…`) for the
qualification workflow.

## What was built (per package)

- **R1a** — `dramabox-llm` role (provider claude-pro, `isolation: strict`, model allowlist
  {sonnet, opus}, `--max-budget-microusd` default 1,000,000 / max 3,000,000, admission block)
  and the `dramabox_llm` config block in models.json. `run_strict()`: exact strict argv
  (`-p --safe-mode --tools "" --strict-mcp-config --no-session-persistence --permission-prompts
  none --output-format stream-json --verbose --max-budget-usd <converted> [--json-schema
  <exact bytes>]`), the fixed child environment (PATH derived from the pinned CLI dir, HOME,
  LANG, TZ, TERM, OTEL — nothing inherited, proven with parent canary secrets), absolute
  pinned executable, empty-cwd refusal with the A0S-3 hash-bound qualification-fixture
  exception, a new session (`start_new_session`), SIGTERM → group signal + `CANCELLED`
  (armed for the whole run, including during the self-check), internal `--deadline-s` →
  `DEADLINE`, micro→USD conversion by integer arithmetic at the CLI boundary only
  (1000000→"1", 1500000→"1.5", 2999999→"2.999999"), result/3 writer with the §3.5 write
  order, stream parsing and the raw stream at `<result>.raw.jsonl` (0600).
- **R1b** — the §3.3 self-check (all refusals `ISOLATION_UNAVAILABLE`, `launched=false`,
  exit 2): qualified-CLI version; PTY help capture with completeness = every strict flag +
  the version-pinned tail marker (`update|upgrade`); the policy inventory read per entry with
  refusals for unlisted `managed*` sources in the policy dir, unreadable/malformed sources,
  remote configured but unresolved, an executable `policyHelper`, and any source setting
  `hooks`/`enabledPlugins`/`managedMcpServers`/`mcpServers`/`env`/`permissions` (empty values
  count as setting nothing); the built-in executable-extension inventory; the SHA-256 policy
  identity over CLI version + per-source hashes + strict-profile version + the fixed env,
  compared against the qualification-recorded identity (null → unqualified), always reported
  for the qualification workflow.
- **R1c** — §3.4 admission in integer basis points (`QUOTA_UNREADABLE` +10 min;
  `QUOTA_5H` at the 5h reset at ≥ `max_5h_bp`; `PACE_WEEK` at the week reset when per-day
  bp falls under the minimum; `CONCURRENCY` +5 min over live claude-pro jobs) — exit 75,
  `launched=false`, REFUSED only for these; §3.5 dedupe by `(invocation_id, attempt)` under
  the registry lock (completed → stored-result replay incl. to a different result path with a
  journal `replay` line; live duplicate → CONCURRENCY; stale marker with a dead pid reclaimed;
  every terminal outcome stored); the runtime isolation assertion (exactly one valid init with
  explicit inventories, `effective_tools ⊆ {StructuredOutput}`, empty `mcp_servers`,
  StructuredOutput-only `tool_calls`; violation discards the output, keeps evidence + raw
  stream, records `violation_reason`, exit 1); `quota_before`/`quota_after` integer snapshots
  on every run.
- **R1d** — the fixtures/tests above; the Pro caller restriction verified global (GLM-caller
  env refused for `plan` and `dramabox-llm`); `--list`/`--status` run clean.

## Acceptance mapping (ai-route part)

- **A0-2** ✔ `test_strict_argv_exactly` (exact argv, `--tools ""`, no `--mcp-config`,
  `--bare` absent, no progress tool/paragraph/session-id), `test_empty_cwd_required`,
  `test_dotfiles_count_as_contents`, `test_qual_fixture_hash_bound`,
  `test_qual_fixture_requires_allowlist`.
- **A0-3** ✔ `test_fixed_environment` (child env == fixed set with parent canary secrets;
  `PATH` includes the pinned dir but the executable is the absolute pinned path),
  `test_new_session`.
- **A0-5 (ai-route part)** ✔ `test_unqualified_version`, `test_missing_version_output`,
  `test_help_missing_strict_flag`, `test_help_missing_final_section`,
  `test_pty_help_is_complete`, `test_unconfirmed_entry_fails_closed`,
  `test_unlisted_source_exists`, `test_forbidden_policy_keys`,
  `test_managed_mcp_servers_refused`, `test_dropin_forbidden_key_refused`,
  `test_malformed_managed_settings_refused`, `test_policy_helper_refused`,
  `test_remote_unresolved_refused`, `test_builtin_*`, `test_identity_*`; violation half in
  R1c's `test_isolation_violation` (extra tool, MCP server, non-StructuredOutput call, no
  init, malformed init).
- **A0-6 (ai-route part)** ✔ `test_quota_unreadable_refused`,
  `test_quota_unreadable_allowed_when_configured`, `test_5h_cap_refused_at_boundary`
  (retry_at = the 5h reset), `test_week_pace_refused` (retry_at = the week reset),
  `test_concurrent_strict_job_refuses_second`, `test_running_duplicate_attempt_refused_then_replays`,
  `test_5h_just_under_passes_fractional` (69.96% → 6996 bp). (The `defer` refund half is
  drama-box's package.)
- **A0-7 (ai-route part)** ✔ `test_completed_attempt_replays_without_running`,
  `test_next_attempt_runs`, `test_refused_attempt_stored_and_replayed`. (Concurrent-POST
  dedupe and tombstones are the gateway's.)
- **A0-13 (ai-route part)** ✔ snapshot diff empty (above); caller rule global; helpers
  unchanged.

## Injection seams (never weakened checks)

- **Pinned CLI path**: `dramabox_llm.claude_path` in models.json — tests pin the shim;
  production pins `/root/.local/share/claude/versions/2.1.322`.
- **Quota**: `AI_ROUTE_TEST_QUOTA_FILE` (windows-shape JSON) read instead of the endpoint;
  the gateway unit's fixed environment never sets it, and production reads the real OAuth
  windows exactly as before.
- **Caller detection**: unchanged `caller()`; tests control the environment (the existing
  pattern), and the restriction is asserted still-global for both roles.
- **Subprocess execution**: the shim is pinned via models.json; no PATH search.
- Credentials: synthetic `.credentials.json` in a temp HOME; the real one never opened.

## Judgement calls (all recorded with reasons)

1. **Order inside the strict run**: dedupe → cwd → self-check → admission → launch. Rationale:
   a completed attempt is history and must replay regardless of current isolation/quota; the
   cwd and self-check refusals are configuration truths that outweigh quota arithmetic.
2. **`concurrent_jobs`**: recorded as the integer count of *other* live claude-pro jobs at
   admission. Spec §3.5 says "(integer ms)", which reads like a parenthetical grouping with
   the quota fields' ms resets; a count is the only integer that fits the field's name. The
   drama-box side can remap if the spec owner meant an observation timestamp.
3. **Exit-code map**: SUCCEEDED/CANCELLED → 0, REFUSED → 75 (spec), ISOLATION_UNAVAILABLE → 2
   (config class), CLI_ERROR/PARSE_ERROR/DEADLINE/CAP_EXCEEDED/ISOLATION_VIOLATION → 1. The
   gateway classifies by the result file's `outcome`, so this map is diagnostic only.
4. **ISOLATION_VIOLATION vs CLI_ERROR**: the runtime assertion runs only on exit-0 streams;
   a non-zero exit keeps CLI_ERROR/CAP_EXCEEDED (nothing was produced to assert over). A0S-4's
   "missing/malformed init" case is covered for successful-looking streams.
5. **`violation_reason`**: added as one extra string field in result/3 (spec's field list is
   the gateway contract; an additive nullable string keeps it parseable) so gateway health can
   name the violation. `refusal_reason` stays admission-only (A0R-4).
6. **Concurrency counts all live claude-pro jobs** (plan included): the Pro window is shared
   and scarce, and the existing `claim()` already blocks plan behind a dramabox live file, so
   the block is mutual. The dramabox admission block is otherwise exactly §3.4.
7. **Forbidden policy keys with empty values** (`"hooks": {}`) count as setting nothing.
8. **Stale running markers** (dead pid) are reclaimed rather than refused — the gateway's
   recovery marks such attempts UNKNOWN and never relaunches them, so a re-invocation is an
   operator action.
9. **`cmd_list`** now prints `(--model)` for allowlist roles instead of the misleading
   `(codex config.toml)`; pre-existing lines byte-identical (asserted by fixture).
10. **OTEL in the fixed env** carries the role's canonical strict cwd so qualification and
    production hand the CLI identical bytes (the identity hashes the env).
11. **Tests-first deviation (R1b)**: the §3.3 wiring landed together with R1a's re-greening
    because R1a's suite exercises the strict path the self-check gates; R1b's own tests then
    drove the refusal matrix to green. Recorded here rather than hidden.

## Anything stopped at red

Nothing. All four packages are green (`62 passed` total). The production role is
deliberately **fail-closed** until the §7 qualification (UNCONFIRMED inventory entries +
unset `expected_policy_identity`).

## Resume here

R1a–R1d and Codex fix round 1 (RR-1..RR-15) are done and green (`ffb3810` + `b9137f8`,
107 passed). Everything meaningful is committed on `worktree-a0r1-airoute`; the only
uncommitted worktree files are `scripts/tests/ai_route/test_zz_dbg.py` (a comment-only
debug scratch, collects nothing) and `__pycache__` directories. Next: the orchestrator's
re-review of the fix round, then the §7 live qualification to confirm the remote-settings
cache rule and the built-in extension inventory, set `expected_policy_identity`, and
record the fixture hash.

---

## Fix round 1 (Codex review RR-1..RR-15)

Builder: GLM (z.ai), 12 Nov 2026. Input: `codex-review-a0r1.md` (FIX-REQUIRED). All fifteen
findings accepted and fixed; every "Fix" ruling applied as written. Branch
`worktree-a0r1-airoute`, commits on top of `02af779`: **`ffb3810`** (all fifteen fixes +
the 44-test suite) and **`b9137f8`** (one test-rig race in that suite, found by the
full-suite verification run; production code untouched — see judgement call 13).

### Red → green (tests first)

The fix-round suite `scripts/tests/ai_route/test_dramabox_fix1.py` (44 items) was written
first and run against **pristine `02af779`** (script and shim restored byte-exact via
`git show 02af779:…` into the worktree before the run):

- **Red on 02af779: `42 failed, 2 passed in 71.57s`** — every RR group has red tests.
  The two greens are deliberate: `test_rr7_structured_output_from_terminal_without_tool_event`
  (old code accepted the StructuredOutput tool-call input, so that one case happened to
  pass; the RR-7 red is its sibling `…_tool_input_not_accepted_without_terminal_field`)
  and `test_rr15_cwd_symlink_refused` (old code also refused, but via the policy-identity
  change rather than the symlink; the RR-15 reds are its two siblings).
- Green after the fix: see the per-RR table below.

### Per-RR record (all one commit; red lines from the 02af779 run above)

| RR | What was fixed (test → behaviour) | red → green |
|----|-----------------------------------|-------------|
| RR-1 | `strict_claim`/`strict_publish`: one protocol under the registry flock; the running marker carries an owner token; only the owner publishes or clears it. A duplicate observing a live owner answers non-terminal `IN_PROGRESS` (exit 75, `retry_at_ms`, `launched=true`) and writes only its own `--result-json` — never the owner's registry files or result path. | `test_rr1_duplicate_observer_never_touches_owner_state` red (duplicate wrote REFUSED into the owner's canonical result + unlinked the marker) → green |
| RR-2 | `strict_claim` rechecks the completed result AND the live marker inside the same lock that claims ownership (a preflight overlap can no longer re-execute a just-finished attempt); completion publishes under that lock; stale markers (dead pid) are reclaimed with a fresh token. | 3 × `test_rr2_claim_*` red (`strict_claim` did not exist; `strict_register` checked only `.running`) → green |
| RR-3 | The runtime isolation assertion now runs on the collected evidence BEFORE and independently of the exit status: a stream exposing Bash/an MCP server/missing init followed by exit 1 is `ISOLATION_VIOLATION` with the output discarded and the raw stream kept. (Build judgement call 4 is withdrawn.) | `test_rr3_violation_evidence_wins_over_exit_status`, `test_rr3_missing_init_with_error_exit_is_violation` red (CLI_ERROR) → green |
| RR-4 | Success requires exit 0 AND a terminal event with `is_error=false` AND `subtype=success`; subtypes map explicitly (`error_max_budget_usd` → CAP_EXCEEDED, everything else → CLI_ERROR) on both the exit-status and terminal-event branches. | `test_rr4_error_terminal_event_is_not_success`, `test_rr4_success_requires_success_subtype` red (SUCCEEDED) → green |
| RR-5 | One monotonic deadline from process start: select-bounded PTY help capture (cancel-aware), select-bounded prompt write, select-bounded stream read, bounded `wait(timeout=remaining)` for a child that closed stdout, final drain bounded by the same deadline, TERM → KILL after 10 s, and a terminal `DEADLINE` result whenever the deadline fires in any phase. | `test_rr5_child_closing_stdout_cannot_outlive_the_deadline`, `…_help_capture_is_deadline_bounded`, `…_prompt_write_is_deadline_bounded` red (unbounded hangs → test timeouts) → green |
| RR-6 | Policy keys are checked against a per-tier allowlist: `POLICY_INERT_KEYS` for settings sources, `POLICY_MCP_KEYS` for the managed-mcp file; every executable setting (`apiKeyHelper`, `awsCredentialExport`, `awsAuthRefresh`, `otelHeadersHelper`, `statusLine`, `fileSuggestion`, `policyHelper`, hooks of any kind) refuses, and any unknown key refuses. Pinned-version tests parametrize all of them. | 9 × `test_rr6_executable_and_unknown_policy_keys_refused[...]` red (5 helper keys + the unknown key passed) → green; `test_rr6_inert_keys_still_pass` guards the allowlist |
| RR-7 | The structured output is the terminal result event's `structured_output` field (validated to be an object/array); a `StructuredOutput` tool call alone no longer satisfies a schema (PARSE_ERROR when the terminal field is absent). The shim follows the documented contract. | `test_rr7_tool_input_not_accepted_without_terminal_field` red (SUCCEEDED from tool input) → green; the positive case is covered by its sibling |
| RR-8 | The parser boundary catches every decoding/conversion failure (non-object `message`, invalid cost, bad usage numbers) into a durable `PARSE_ERROR` result with the raw stream kept. A malformed event is a parse failure, not a silently skipped one — it cannot hide tool evidence. | `test_rr8_bad_message_field_is_durable_parse_error`, `test_rr8_invalid_cost_is_durable_parse_error` red (tracebacks, no result file) → green |
| RR-9 | Remote policy counts as absent only when positively established: a null path always refuses (CONFIRMED status alone unlocks nothing); a known cache path refuses unless the §7-confirmed `absence_rule` is recorded; the rule (and the cache bytes, when present) bind into the policy identity. | `test_rr9_confirmed_status_alone_does_not_unlock_null_path`, `…_missing_cache_without_established_rule_refuses`, `…_established_rule_missing_cache_passes_and_binds_identity` red → green |
| RR-10 | `AI_ROUTE_TEST_QUOTA_FILE` removed from the production path entirely. The offline seam is `dramabox_llm.quota_file` in models.json (a config seam like `claude_path`, set only in a test HOME, `null` in production, never inheritable through the environment). | `test_rr10_env_quota_file_is_ignored`, `…_no_env_seam_left_in_the_script`, `…_production_models_json_has_no_quota_file` red → green |
| RR-11 | An unreadable quota window (when allowed) skips only the quota-dependent comparisons; `max_concurrent` is still enforced — counted race-free from live attempt markers under the claim lock plus live claude-pro plan jobs. | `test_rr11_concurrency_enforced_when_quota_unreadable_allowed` red (launched a second job) → green |
| RR-12 | The snapshot matrix now drives `main()` itself through entry-point shims (Popen/execvpe/chdir/quota/live-jobs, clock and environment patches scoped and restored), capturing the FINAL launch argv, environment, cwd and stdin per role/variant: the headless `-p`, the `--session-id` argument, the progress paragraph on stdin, goldfish's prompt_template preparation (with the plugin gate), and the `--quota`/`--status` entry points. `behavior_matrix.load()` no longer leaves the global clock frozen (the freeze is scoped inside `matrix()`). Baselines regenerated from pristine main `02b361a` via `git show` extraction (see the proof below). The old `"brief" in vname` prompt-selection bug (all five plan variants recorded `headless=false`, no `-p`) is gone. | `test_rr12_fixture_captures_headless_prompt_session_and_paragraph` red (fixture had no `-p`/session/paragraph) → green; `test_rr12_behavior_matrix_clock_patch_is_scoped` red → green |
| RR-13 | Result-tier writes go through `_validated_dir` (real dir via `O_DIRECTORY|O_NOFOLLOW`, owned by the user, not group/world-writable) and `_open_exclusive` (`O_CREAT|O_EXCL|O_NOFOLLOW` 0600; an existing file is accepted only as a regular file with `nlink==1`, re-chmod through the descriptor). Applied to the result tmp, the raw stream and the strict stderr log. A planted symlink raises instead of being followed. | `test_rr13_result_tmp_symlink_is_not_followed`, `…_raw_stream_symlink_is_not_followed`, `…_world_writable_result_directory_refused` red (canary truncated / launch proceeded) → green |
| RR-14 | Qualification is a separate launch mode: `--qualification <record-id>` must match `qual_fixture.record_id` recorded in models.json, and only inside that mode does `--allow-qual-fixture` do anything. The production profile rejects `--allow-qual-fixture` outright (usage error, exit 2), even with the fixture configured and its hash matching. | 4 × `test_rr14_*` red → green; plus `test_qual_fixture_rejected_outside_qualification_mode` in the r1a suite |
| RR-15 | `--result-json` (and its `.tmp`/`.raw.jsonl` siblings) may not live inside the execution cwd — checked before anything is created there, so a nested path can never manufacture cwd contents. The execution cwd is validated for type/ownership (no symlinked final component, owned, not group-writable) and its emptiness (production) or contents hash (qualification fixture) is rechecked immediately before the spawn, after the self-check and quota reads. | `test_rr15_result_json_inside_execution_cwd_refused`, `…_cwd_symlink_refused`, `…_emptiness_rechecked_immediately_before_spawn` red → green |

### The regenerated snapshot proof (RR-12)

Both fixtures were regenerated from **pristine `main` @ `02b361a`** — never from the
modified code — by extracting the exact blobs and driving the fixed generators against
them (provenance is recorded in the fixtures' `_meta.repo` / `repo` fields):

```
mkdir -p /tmp/a0r1-pristine/scripts
git show main:scripts/ai_route.py > /tmp/a0r1-pristine/scripts/ai_route.py   # main = 02b361a
git show main:models.json       > /tmp/a0r1-pristine/models.json
python3 scripts/tests/ai_route/snap_matrix.py    --generate --repo /tmp/a0r1-pristine
python3 scripts/tests/ai_route/behavior_matrix.py --generate --repo /tmp/a0r1-pristine
```

`fixtures/argv_env_snapshot.json` now records, per role and variant, the final launch
(`cmd`, `env`, `cwd`, `stdin`) that `main()` actually executes — 21 variants across the
7 pre-existing roles plus the `--quota`/`--status` helper output. The committed fixture
provably contains what the old one omitted: the plan `headless*` variants carry `-p` and
`--session-id`, the stdin carries the progress paragraph, goldfish carries its prepared
prompt, and the helpers section is non-empty. `test_existing_roles_argv_and_env_are_identical`
rebuilds the matrix from the CURRENT checkout and demands byte-equality with that pristine
baseline: the diff is empty by assertion.

### Verification: the full suite and the three existing scripts

All runs under `systemd-run --scope -p CPUQuota=45% --quiet`,
`--basetemp=/tmp/a0r1-fix1-basetemp`, from this GLM session.

- **Full pytest suite** (r1a + r1b + r1c + fix1 + r1d, 107 items): the first run at
  `ffb3810` gave **`1 failed, 106 passed in 303.27s`** — `test_rr11_concurrency_enforced_…`
  lost a rig race (judgement call 13). After `b9137f8` (rig fix only):
  **`107 passed in 306.63s`**.
- **`test_guards.py`** (as a script): exit 1. `FAIL plan: Pro login, provider env stripped`
  (the documented GLM-session environment sensitivity — the session's provider env leaks
  into a check whose own docstring requires a plain/Opus shell), and the run then aborted
  with an uncaught 30 s `TimeoutExpired` in the timing-sensitive race section.
  **Pristine `main` @ `02b361a`, same conditions, same hour: also exit 1** with the same
  `Pro login, provider env stripped` failure (its run passed the race section this time —
  that class varies per run, as recorded at R1d). No new deterministic failure.
- **`test_goldfish.py`**: **ALL PASS** (exit 0), unchanged.
- **`test_observability.py`**: 21 PASS / **7 FAIL** at HEAD. **Pristine `main` @ `02b361a`
  under identical conditions: 21 PASS / the same 7 FAIL — the identical failure list**
  (all seven are the sleep-window status checks: `build: status shows background wait`,
  `…model wait after note`, `…counts tool calls`, `…step and usage`, `--json has step…`,
  `review: status shows the running command`, `review: status shows codex's message`).
  Every deterministic contract check (exit codes, runs.jsonl, argv/stdin bytes, watch
  content, quota exit 75) passes on both. The brief's "3 on main" baseline was not
  reproducible under this session's load — the failure count varies with machine
  contention; exact parity with main is the evidence recorded here. The diff introduces
  no new observability failure.

### Judgement calls (fix round 1)

1. **`IN_PROGRESS` semantics.** Non-terminal per the ruling: exit 75 with `retry_at_ms`,
   `launched=true` (the attempt HAS launched — its owner is executing; the old duplicate
   path could answer `launched=false` for a running call), `refusal_reason=null` (REFUSED
   stays admission-only, A0R-4). IN_PROGRESS is never written to the registry; the
   observer writes only its own `--result-json`. If the observer shares the owner's result
   path, the owner's later terminal write wins — the gateway classifies by outcome and
   keeps polling until terminal.
2. **Parse-crash vs violation precedence.** A decoding/conversion failure (RR-8) yields
   PARSE_ERROR before the isolation assertion runs: a crashed parse cannot be trusted to
   have collected complete evidence, and a malformed event must not be able to hide tool
   use behind a crash. A well-parsed stream always runs the isolation assertion first
   (RR-3), whatever the exit status.
3. **Shim `cli_error`/`cap` modes now emit a valid init first** (an isolated CLI that
   fails after initialisation). A no-init stream with a non-zero exit is ISOLATION_VIOLATION
   under the new precedence — that is exactly RR-3's ruling, and `no_init_exit1` covers it.
4. **The quota seam is a models.json key** (`dramabox_llm.quota_file`), not a CLI flag or
   module monkeypatch: the rigs invoke the real entry point as a subprocess, so neither
   monkeypatching nor a hidden argv flag fits; models.json is operator-trust config (the
   same tier that pins `claude_path`), cannot be injected through the environment, and
   production leaves it `null`. This satisfies RR-10's "module seam or test-only entry
   point, never an environment variable that production honours".
5. **The inert-key allowlist is minimal** (`cleanupPeriodDays`, `model`) and lives in the
   code with a comment pointing at qualification for extensions. Supersedes build judgement
   call 7: an unsafe key with an empty value now refuses too (a `{"hooks": {}}` document
   is a configured hooks setting, not "nothing").
6. **Cap mapping is literal** (`error_max_budget_usd` → CAP_EXCEEDED): other `error_max_*`
   subtypes map to CLI_ERROR per the ruling's explicit list; a future documented cap
   subtype is a one-line allowlist change at requalification.
7. **Concurrency counts claimed-but-not-yet-spawned strict markers** (under the claim
   lock), plus live claude-pro plan jobs. A refusal in preflight therefore holds the
   counter for the seconds its quota read takes — a slight over-refusal the retry_at
   (+5 min) absorbs; strict-vs-strict double launch is now impossible (the old
   live-file-only count had that race).
8. **RR-13 on `EEXIST`**: the `<path>.tmp` fallback accepts only a regular file with
   `nlink == 1` (a planted hardlink refuses); a planted symlink errors loudly. When the
   result cannot be written safely there is no result file at all — the gateway sees no
   result (UNKNOWN → operator) rather than a silently truncated file elsewhere. The
   marker stays behind for dead-pid reclaim.
9. **The matrix records only invocations `main()` accepts** (the old generator snapshot
   `build_*` output for argv `main()` itself refuses, e.g. `critique` with no prompt).
   `fast` variants carry `--allow-metered`; codex `review` gains a `review_prompt`
   variant (the instructions path that appends the diff scope to the prompt).
10. **Host-side note:** the first matrix generation run executed goldfish's default
    `--cwd /srv/some/repo` artifact mkdir before that variant was switched to the default
    artifacts path — an empty `/srv/some/repo` directory exists on the host (left in
    place; the no-deletion rule applies). Later runs write only under the matrix temp dirs.
11. **The deadline starts at `run_strict` entry** (after flag validation): argparse,
    `load_models` and the stdin prompt read happen before the strict handler owns the
    process. Everything the handler itself blocks on is bounded.
12. **Interactive-plan pace warnings in the matrix** run under the frozen clock with the
    faked quota readers, so the recorded stdout is byte-stable; `caller()` is shimmed to
    None there (its GLM/codex refusal has its own regression test, which still runs the
    real entry point).
13. **A rig race in the fix1 suite itself (commit `b9137f8`, production code untouched).**
    The module-scoped rig keeps every earlier test's shim calls, so
    `wait_model_call(before=0)` stopped waiting once rr3–rr10 had run the shim: rr11's
    duplicate then raced the owner to the claim lock, could claim first, counted 0
    concurrent, launched and hung to its deadline — `DEADLINE`/exit 1 instead of
    `REFUSED`/`CONCURRENCY`/75. Standalone the test always passed (rr11 was then the
    first `-p` caller); only the full-suite run exposed it. Two *different* invocation
    ids arriving simultaneously with `max_concurrent=1` legitimately race for the claim:
    one launches, the other is refused CONCURRENCY — exactly §3.4 — so the fix snapshots
    the shim-call count before starting the owner at all three wait sites (rr1, rr11,
    rr15's `--version`), making the test wait for *the owner's* call. Assertions
    unchanged; nothing weakened.
14. **The observability/guards "same as main" evidence is parity, not the brief's counts.**
    The brief's "3 checks on main" for `test_observability.py` was not reproducible under
    this session's load (both main and HEAD fail the same 7 sleep-window checks; every
    deterministic check passes on both). Rather than claim the number, both runs were
    executed against pristine `main` @ `02b361a` in the same hour under identical
    conditions and the failure sets compared — identical. Same method for `test_guards.py`
    (main also exits 1 with `Pro login, provider env stripped`).
