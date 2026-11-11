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

All packages done. Next: the orchestrator's Codex diff review (explicitly verifying A0S-1
and A0S-2 on the drama-box side; this side is §3), then the §7 live qualification to confirm
the remote-settings cache rule and the built-in extension inventory, set
`expected_policy_identity`, and record the fixture hash.
