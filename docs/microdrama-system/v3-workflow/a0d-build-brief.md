# A0-D build: LLM gateway, `LlmStep` and migration 0027 (GLM build; drama-box repo)

Orchestrator: Opus, 11 Nov 2026. The operator approved building phase A0. **Don't launch this until its
base is settled (below).**

## The spec is the requirement

Read fully: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-A0-spec.md` **v0.4**.
This package builds **§4 and §5** and their acceptance rows. **§3 (ai-route) is A0-R1; §7 (live
qualification) is operator-gated and not in this build.**

Also read:
- `a0-factmap.md`;
- the three Codex A0 reports (`codex-a0-critique.md`, `codex-a0-recritique.md`, `codex-a0-round3.md`);
- `A1-design-note.md` §3 (the jobs-column ownership split) and §12 OQ-3 (the closed `DeferReason` enum,
  which A0-D owns).

The replacement wording is folded into v0.4 and is binding. **The build's Codex review explicitly
verifies A0S-1/A0S-2 (the auto-reconciler).** If anything is impossible against the code, stop at a red
test and explain it.

## Base (the orchestrator fills this in before launch)

| Case | Base | 0027 |
|------|------|------|
| **T031 accepted** | The accepted `feat/t031-fix3` tip, after its final review; it has migration 0026 | A0 = **0027** |
| **T031 parked** | `feat/microdrama-m0-m4` (migration tail 0025) | A0 takes **0026**. Renumber every reference in your report. T031 renumbers when it merges later |

Work in your own worktree (ai-route `-w a0d-gateway` from the base). Commit on top; never amend.

## Packages, in order

| Pkg | Spec | Acceptance |
|-----|------|------------|
| D1 | Migration 0027 and its guards: `llm_invocations`, `llm_invocation_attempts`, `quota_observations` (§5.6); §5.5 contract changes: `llm.subscription` in `UNMETERED_OPERATION_KINDS` + 0016's per-kind CHECK; `REFUSED_PRELAUNCH`; the kind-limited `resubmit_allowed` rearm; the kind-limited `PENDING_SUBMIT → CANCELLED`; **the closed `DeferReason` enum + a CHECK on `jobs.defer_reason`**; §5.2 runtime: the `Deferred` outcome, `defer(refund_attempt)`, `consumed_attempt`, signal translation before generic handling, refusing a deferral with in-flight operations; deliberate extension of the outcome-union test | A0-10, A0-6 (defer/attempts), A0-13 (V1 outcomes unchanged) |
| D2 | The gateway (§4): `microdrama/deployment/llm-gateway/` stdlib service; the socket/permissions design; the API incl. readmit with `expected_prior_attempt`; the launch ledger with fsync order; the argv-per-property `systemd-run` launcher; **the full §4.3 recovery table incl. persistent `deactivating`**; FIFO, max 1; retention + tombstones; install files for the operator (unit, group 64010, directories, tmpfiles) with an `INSTALL.md` | A0-4, A0-7, A0-8, A0-11 |
| D3 | `LlmStep` (§5.1, the state-driven table incl. connect-level vs after-send failures and lease loss); the auto-reconciler (§5.3: `RESUME` under its own lease, the state-dependent table, never re-queueing with an operation in flight); cancellation forwarding via the outbox consumer `llm_gateway_cancel` (§5.4); the composition gate (§5.7); adapter fakes (§5.8) | A0-1 (= V3-AT-27), A0-9, A0-12 |

## Test rules

- **Tests first:** record red lines against the base, then implement.
- **Real PostgreSQL** for transitions, leases and races (two or more connections, bounded `lock_timeout`).
- **Real transient systemd units for A0-4/A0-8:**
  - unit names prefixed `dramabox-llm-test-`;
  - a **fake ai-route shim** (never the real ai-route or `claude`);
  - `setsid` grandchildren that ignore TERM;
  - SIGKILL of the gateway and of the shim.
  - Leave no test unit loaded afterwards (`systemctl stop` / `reset-failed` on your own test units only).
- **Socket permissions (A0-11):** a client process running as UID 10001 with and without GID 64010
  (`setpriv`), plus a reconnect after restarting the test gateway.
- **The operator installs** the production unit, group and directories. Your tests use a temporary socket
  directory, store and group created **only for the test run**, and never touch `/run/dramabox-llm` or
  `/var/lib/dramabox-llm`.

## Hard limits

- Offline only: OFFLINE_MOCK with paid/cloud/public off. No model, quota or network calls. No real
  `claude`, and never the real credentials.
- No pushes, no merges, no service restarts other than your own test units.
- Run pytest under `systemd-run --scope -p CPUQuota=45% --quiet` with `--basetemp=/tmp/a0d-basetemp`.
  Keep each command under 10 minutes. Run **`make lint` before every commit.**
- Never print environment variables, keys or tokens.
- No deletion commands (`rm`, `git rm`, `git clean`, `git reset`, `find -delete`). **Never leave work only
  in a stash.**
- Don't run the full `make check` or `make pilot`. The orchestrator runs them.

## Pace

At the z.ai limit or a 429:
1. stop at a clean point;
2. commit green work;
3. list anything uncommitted in the report;
4. update "Resume here".

## Report

Write `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/a0d-build-REPORT.md` (separate from
`--out`). It must contain:
- each package's status and commits;
- red/green lines per acceptance row;
- the transaction inventory (function → locks in order → writes);
- the §4.3 recovery-table test matrix;
- judgement calls;
- anything stopped at red;
- "Resume here".

When D1–D3 are done: put `A0-D: ALL PACKAGES DONE` at the top.

Final message: one line per package, then the report path.
