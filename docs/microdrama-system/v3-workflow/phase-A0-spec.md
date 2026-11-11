# Phase A0: LLM plumbing (gateway, isolated subscription role, metering)

**Version 0.4, 11 Nov 2026.** Author: Opus orchestrator.

**Status: READY FOR BUILD.** All three Codex rounds are applied:
- Round 1: [codex-a0-critique.md](codex-a0-critique.md), A0C-1..18.
- Round 2: [codex-a0-recritique.md](codex-a0-recritique.md), A0R-1..10.
- Round 3, operator-approved and scoped: [codex-a0-round3.md](codex-a0-round3.md), A0S-1..5.
- §12 maps every finding.
- There is no fourth spec round: **the build's Codex diff review verifies A0S-1 and A0S-2 explicitly.**

**Master:** [SPEC-v3.md](SPEC-v3.md) v0.4.2 (§1 rule 3, §10.0, §10.1, §11, §15).

**Facts:** [a0-factmap.md](a0-factmap.md) and [a-factmap.md](a-factmap.md). Code references are relative to
`microdrama/src/microdrama/`.

**Builds on:** `feat/microdrama-m0-m4` **after `feat/t031-fix3` is merged** (migration 0026). A0 takes
migration **0027**.

---

## 1. Design in four decisions

1. **An LLM call is a resumable job step, not a blocking call.**
   - A V3 handler submits the call to the host gateway, records it as `SUBMITTED`, and **returns the
     existing `WaitExternal`** outcome. That clears the lease, preserves attempts and allows a later claim
     (`core/jobs.py:320,527`).
   - The next claim polls the gateway.
   - The legacy synchronous `LLMProvider.generate()` never gets the subscription route.
2. **Subscription calls are an unmetered operation kind** (`llm.subscription`).
   - **Extend the existing `UNMETERED_OPERATION_KINDS`** (`contracts/cost.py:97`) and migration 0016's
     per-kind CHECK.
   - Keep the four publishing exemptions and mandatory job linkage.
   - There is no reservation, no `UsageReceipt` and no charge. Admission is by quota.
   - Guardian-approved.
3. **Each invocation runs in its own transient systemd unit:**
   - whole-cgroup kill;
   - a hard `RuntimeMaxSec`;
   - a deterministic name.

   **The durable result file, not the unit's presence, is the source of truth.** Successful transient
   units are garbage-collected.
4. **Isolation is a verified boundary at two levels:**
   - a pre-launch inspection of every policy source;
   - a **per-call runtime assertion** on the CLI's initialisation event.

   Plus systemd sandboxing.

## 2. Architecture

```
 Drama Box worker (container)                         Host
 ┌──────────────────────────────────┐ unix socket ┌──────────────────────────────────┐
 │ V3 handler                        │────────────►│ dramabox-llm-gateway (systemd)   │
 │  └ LlmStep.ensure(ctx, call)      │ /run/drama- │  durable store + launch ledger    │
 │     ├ ProviderOperation           │ box-llm/    │  └ systemd-run unit per attempt:  │
 │     │  PENDING_SUBMIT→SUBMITTED→… │ gw.sock     │     dramabox-llm-<id>-<n>.service │
 │     └ WaitExternal / Deferred /   │◄────────────│      └ ai-route dramabox-llm      │
 │       Done                        │ result JSON │         └ claude -p (strict)      │
 └──────────────────────────────────┘             └──────────────────────────────────┘
```

## 3. `ai-route` changes (claude-configs repo: `~/.claude/scripts/ai_route.py`, `models.json`)

### 3.1 Role `dramabox-llm`

- `provider: claude-pro`.
- `isolation: "strict"`.
- `--model` passthrough from the allowlist `{sonnet, opus}` (new).
- `--max-budget-microusd <int>`: default 1,000,000, maximum 3,000,000. ai-route converts it to the CLI's
  `--max-budget-usd` **only at the CLI boundary** (A0R-10). It is an estimated stopping threshold that can
  overshoot.
- An `admission` block of pilot policy, not a proven reserve:
  - `refuse_if_quota_unreadable: true`;
  - `max_5h_bp: 7000`;
  - `min_week_bp_per_day_left: 800`;
  - `max_concurrent: 1`.

### 3.2 Strict profile

- **argv:**
  - `-p`, `--safe-mode`;
  - `--tools ""` (an empty argv element);
  - `--strict-mcp-config` with no `--mcp-config`;
  - `--no-session-persistence`;
  - `--permission-prompts none`;
  - **`--output-format stream-json --verbose`** (A0R-9: production and qualification use the same argv);
  - `--max-budget-usd <converted>`;
  - `--json-schema <schema>` when given.
- **Removed:** the progress MCP, `--allowedTools`, the progress paragraph, `--worktree`.
- **`--bare` is forbidden** (it disables OAuth).
- **Environment:** a fixed minimal set: `PATH=/usr/bin:/bin:<pinned claude dir>`, `HOME=/root`,
  `LANG=C.UTF-8`, `TZ=UTC`, `TERM=dumb`, `OTEL_RESOURCE_ATTRIBUTES`.
  - A variable is added only after a recorded probe shows it is necessary; the justification lives in
    `models.json`.
  - Never bisect the full environment.
  - Credentials come only from `HOME/.claude/.credentials.json`.
- **Executables** are resolved to absolute pinned paths (`claude`, the interpreter). `PATH` is not
  searched for them.
- **Working directory:** `~/.cache/ai-route/dramabox-llm/cwd/`. **ai-route refuses to launch unless it is
  empty.**
  - **The only exception** is the live qualification (§7). It may run in a separate, explicitly
    allowlisted canary fixture directory whose contents must match a recorded hash (A0S-3).
  - Production keeps the empty-cwd check.
- **Process:** a new session. On SIGTERM, ai-route signals the group, writes `CANCELLED` (§3.5) and exits.
  The unit (§4.3) contains every descendant.
- **Deadline:** `--deadline-s`, enforced internally as well as by the unit's `RuntimeMaxSec`.

### 3.3 Pre-launch self-check (A0C-10, A0R-8)

ai-route returns outcome **`ISOLATION_UNAVAILABLE`** (`launched=false`) unless all of these hold:

1. **The CLI version** is in `models.json: dramabox_llm.qualified_cli` (`["2.1.322"]`).
2. **Complete help:**
   - capture `claude --help` **through a PTY**; piped capture truncates at about 8 KB;
   - the output must contain every strict flag and the help's known final section;
   - incomplete output is an inspection failure.
3. **The policy-source inventory:**
   - `models.json: dramabox_llm.policy_sources` lists, for the pinned version and from its official
     managed-settings documentation, every Linux policy source:
     - the managed settings file;
     - the drop-in directory;
     - server-managed or remote settings;
     - any executable policy helper;
     - with their precedence.
   - The check reads each one. It **refuses** if:
     - an unlisted source exists;
     - remote policy is configured but not resolved;
     - an executable policy helper is configured;
     - any source sets hooks, plugins, MCP servers, environment injection or tool permissions.
   - It also records the pinned version's built-in executable-extension inventory (built-in plugins and
     hooks); a non-empty executable entry → refuse.
4. **Effective-policy identity:**
   - computed as SHA-256 over the CLI version, the bytes of every present policy source, the strict-profile
     version and the fixed environment;
   - it must equal the identity recorded by the last passing qualification (§7). A mismatch → refuse until
     requalified.

### 3.4 Admission

| Condition | Outcome / reason (exit 75) | `retry_at` |
|-----------|----------------------------|------------|
| Quota unreadable | `REFUSED` / `QUOTA_UNREADABLE` | +10 min |
| 5 h ≥ `max_5h_bp` | `REFUSED` / `QUOTA_5H` | the 5 h reset |
| Week pace below the minimum | `REFUSED` / `PACE_WEEK` | the week reset |
| Concurrency slot taken | `REFUSED` / `CONCURRENCY` | +5 min |

- Every refusal is pre-launch: `launched=false`.
- **`REFUSED` is used only for these admission reasons** (A0R-4). `ISOLATION_UNAVAILABLE` is a separate
  outcome.

### 3.5 Machine-result interface

- **Flags:** `--invocation-id <uuid> --attempt <n> --result-json <path>`.
- **Dedupe:** by `(invocation_id, attempt)` under the `flock` registry. A completed attempt returns its
  stored result.
- **Write order:** `<path>.tmp` → `fsync` → rename → `fsync` the directory → journal line → exit.
- **Result schema `ai-route.result/3`:**
  - `invocation_id`, `attempt`, `launched`, `role`, `requested_model`, `cli_version`;
  - `policy_identity`;
  - `outcome` ∈ `SUCCEEDED`, `CLI_ERROR`, `REFUSED`, `DEADLINE`, `CANCELLED`, `CAP_EXCEEDED`,
    `PARSE_ERROR`, `ISOLATION_UNAVAILABLE`, **`ISOLATION_VIOLATION`**;
  - `refusal_reason`, `retry_at_ms`;
  - `started_at_ms`, `ended_at_ms`, `duration_ms`, `exit_code`;
  - `session_id`, `num_turns`, `subtype`, `is_error`;
  - **`effective_tools`** and **`mcp_servers`** from the stream's initialisation event;
  - **`tool_calls`**: the names of the executed tool-use events;
  - `model_usage` (integers per model), `cost_estimate_microusd` (integer, rounded up; `null` →
    `usage_unavailable: true`);
  - `quota_before` and `quota_after` (integer basis points and ms, or `{unreadable: true}`);
  - `concurrent_jobs` (integer ms).
  - **Arbitrary JSON is carried as canonical text** (A0R-10): `result_text`, `structured_output_text`
    (the exact bytes, plus `structured_output_sha256`). All other fields are integers, strings or booleans.
- **Runtime isolation assertion** (A0R-9). If either of these holds, the outcome is
  **`ISOLATION_VIOLATION`** (`launched=true`), the output is discarded, and the gateway health turns red
  until the role is requalified:
  - `effective_tools ⊄ {"StructuredOutput"}`, or `mcp_servers` is non-empty;
  - `tool_calls` contains anything other than `StructuredOutput`;
  - **the initialisation evidence is not exactly one valid initialisation event with explicit tool and MCP
    inventories.** Missing, malformed or conflicting evidence fails the check too (A0S-4).
- **The raw stream** goes to `<path>.raw.jsonl` (0600), outside every guarded row.

## 4. `dramabox-llm-gateway` (drama-box repo: `microdrama/deployment/llm-gateway/`)

### 4.1 Service, socket, permissions

- **Process:** stdlib Python with a pinned interpreter; the unit `dramabox-llm-gateway.service` runs as
  root.
- **Socket directory:** `/run/dramabox-llm/` is a preserved `RuntimeDirectory`, `root:64010`, mode 0750.
- **Socket:** `gw.sock`, 0660.
- **Container:** `group_add: ["64010"]` and a read-only bind mount of the **directory**. Nothing else
  from the host is mounted.
- **Store:** `/var/lib/dramabox-llm/` (0700, umask 077).
- **Tests:**
  - UID 10001 with GID 64010 connects; another UID without the GID is denied;
  - **a client reconnects after a gateway restart.** Established connections don't survive (A0R
    socket note).
- **The operator installs** the unit, group and directories from tested files.

### 4.2 API (HTTP over the Unix socket; 5 s connect, 10 s read)

| Method | Path | Behaviour |
|--------|------|-----------|
| `POST` | `/v1/invocations` | Body: `{invocation_id, request_text}`, where `request_text` is canonical JSON text: model, profile, prompt, schema, `max_budget_microusd`, `deadline_s`, and the expected policy identity. `request_hash` = SHA-256 of `request_text`, computed identically at both layers. A new ID → `202` (`ACCEPTED`). The same ID + the same hash → the current record. A different hash → `409` |
| `POST` | `/v1/invocations/{id}/readmit` | Body: `{expected_prior_attempt: n}`. If the latest attempt is n and ended `REFUSED` with `launched=false` → create attempt n+1 (`202`). If attempt n+1 already exists → return it (**replay of a lost acknowledgement**). Anything else → `409` (A0R-2) |
| `GET` | `/v1/invocations/{id}` | `{state, attempts[], result?}`. `state` ∈ `ACCEPTED`, `LAUNCH_INTENT`, `RUNNING`, `DONE`, `REFUSED`, `CANCEL_REQUESTED`, `CANCELLED`, `UNKNOWN`; `404` if never accepted |
| `POST` | `/v1/invocations/{id}/cancel` | Persists `CANCEL_REQUESTED` before anything else, and is idempotent. Queued (`ACCEPTED`) → `CANCELLED` with `launched=false`. Launched → `systemctl stop` the unit, then `CANCELLED` **only after the unit is confirmed not active** |
| `GET` | `/v1/health` | Self-check result + policy identity, quota readability, queue depth, the last `ISOLATION_VIOLATION` |

### 4.3 Launch ledger and supervision

**Per attempt, in this order, with an `fsync` after each state write:**
1. Write `request.json` (immutable) on the first attempt.
2. Write `state=LAUNCH_INTENT{n}`.
3. Run `systemd-run`, with **each property as one argv element** (A0R-6):

   ```python
   ["/usr/bin/systemd-run", f"--unit=dramabox-llm-{id}-{n}", "--quiet",
    "--property=KillMode=control-group",
    f"--property=RuntimeMaxSec={deadline_s + 60}",
    "--property=TimeoutStopSec=10",
    "--property=ProtectSystem=strict",
    "--property=ReadWritePaths=/root/.claude /root/.claude.json /root/.cache/ai-route /var/lib/dramabox-llm",
    "--property=InaccessiblePaths=-/root/AIVORA -/root/.secrets -/data",
    "--property=PrivateTmp=yes", "--property=NoNewPrivileges=yes",
    "--setenv=…(the fixed set only)",
    "/usr/bin/python3.<pinned>", "/root/.claude/scripts/ai_route.py", "dramabox-llm", …]
   ```

   - The required write paths are **precreated**.
   - **The live qualification (§7) records the complete write set the CLI needs.** Any additional path is
     added explicitly; `/root` is never made writable wholesale.
   - The exact argv is part of the qualified profile.
4. Write `state=RUNNING`.
5. On unit exit: **classify by the explicit `outcome` first**, then `launched`:
   - `REFUSED` → `REFUSED`;
   - everything else → `DONE` with that outcome.
6. `systemctl reset-failed` if needed.

**Restart recovery** (A0R-7). Unit `ActiveState` is read with `systemctl show`; absent = not loaded:

| Ledger state | Unit | Valid result file | Recovers to |
|--------------|------|-------------------|-------------|
| `ACCEPTED` (no intent yet) | — | — | `ACCEPTED`, re-queued FIFO |
| `LAUNCH_INTENT` / `RUNNING` | `activating` / `active` / `reloading` | — | `RUNNING` (re-attach) |
| `CANCEL_REQUESTED` | `activating` / `active` / `reloading` | — | stays `CANCEL_REQUESTED`; **re-issue the stop and verify** |
| any | `deactivating` | — | re-check every 2 s for up to `TimeoutStopSec + 5 s`, then apply the rows below. **Still `deactivating` at the bound:** keep any cancel intent, mark recovery unresolved (health red), and never relaunch (A0S-5) |
| `CANCEL_REQUESTED` | absent / `inactive` / `failed` | either | `CANCELLED` (any result is kept for metering; its output is discarded) |
| `LAUNCH_INTENT` / `RUNNING` | absent / `inactive` / `failed` | present | `DONE` / `REFUSED` per its outcome |
| `LAUNCH_INTENT` / `RUNNING` | absent / `inactive` / `failed` | absent or invalid | **`UNKNOWN`** |

- The gateway never relaunches `UNKNOWN`.
- **Queue:** FIFO, one running attempt.
- **Retention:** payloads 30 days; tombstones (`invocation_id`, `request_hash`, final state, attempts)
  400 days.

## 5. Drama Box side (drama-box repo)

### 5.1 `LlmStep` (`microdrama/llm/step.py`)

```
LlmStep.ensure(ctx: JobContext, call: FrozenLlmCall)
  -> LlmDone | raises LlmWait | LlmDeferred | LlmBlocked | LlmLeaseLost
```

- **`JobContext`** carries `job_id`, `worker_id`, the lease, and `now()` (freshly sampled at each use).
- **`FrozenLlmCall`** is persisted before any POST, as canonical text (§5.6):
  - `logical_call_id` (`invocation_id = uuid5(LLM_NS, logical_call_id)`);
  - **transport recovery reuses it**; a new content attempt gets a new `logical_call_id`.
- **The operation** is `provider_ops.begin(tx, provider="dramabox-llm-gateway",
  operation_kind="llm.subscription", client_token=str(invocation_id), request_hash, job_id,
  deadline_at=now + deadline_s + 120 s, reservation_id=None)`, under `lease_guard`.

**The step is driven by the operation's current state** (each write runs under `lease_guard` with fresh
time; A0R-1):

| Operation state | Action | Result |
|-----------------|--------|--------|
| none | `begin()` + `llm_invocations` row; commit; then as `PENDING_SUBMIT` | — |
| `PENDING_SUBMIT` | `POST /v1/invocations` (or `readmit` with `expected_prior_attempt`, if a prior gateway attempt was refused). **Accepted** → `record_result(SUBMITTED, external_id=invocation_id)` → raise `LlmWait` | `WaitExternal(invocation_id, 5000 ms)` |
| `PENDING_SUBMIT`, **connect-level failure** (the socket is absent or refused, so the request provably wasn't sent) | `record_result(NOT_FOUND, evidence=TRANSPORT_NOT_SENT)` | `Deferred("GATEWAY_UNAVAILABLE", 60 s)`; after 10 consecutive failures, `LlmBlocked` |
| `PENDING_SUBMIT`, a failure after the request may have been sent | one bounded `GET`: found → `SUBMITTED` and wait; `404` → `NOT_FOUND` + `Deferred`; still unreachable → **leave it `PENDING_SUBMIT`** | `NeedsReconciliation` (§5.3 auto-reconciler) |
| `NOT_FOUND` / `REFUSED_PRELAUNCH` (on the next run) | `resubmit_allowed()` (§5.5) → `PENDING_SUBMIT` (attempt+1, fresh deadline) | continue as `PENDING_SUBMIT` |
| `SUBMITTED` / `RUNNING` | `GET`: `ACCEPTED`/`LAUNCH_INTENT`/`RUNNING` → `record_result(RUNNING)` once, if not already `RUNNING` | `WaitExternal` |
| ″ | `DONE` + `SUCCEEDED` + schema-valid output | `record_result(SUCCEEDED)`; `LlmDone` |
| ″ | `DONE` + `CAP_EXCEEDED` / `CLI_ERROR` / `PARSE_ERROR` / `DEADLINE`, or invalid output | `record_result(FAILED, code)`; a domain error; the handler retries with a new `logical_call_id`, or fails |
| ″ | `DONE` + `ISOLATION_UNAVAILABLE` (`launched=false`) or `ISOLATION_VIOLATION` | **`record_result(FAILED, code)` first (settled)**, then `LlmBlocked` (A0R-4) |
| ″ | `REFUSED` | `record_result(REFUSED_PRELAUNCH, refusal evidence)` | `LlmDeferred(reason, clamp(retry_at − now, 60 s, 6 h))` |
| ″ | `CANCEL_REQUESTED` | — | `WaitExternal` (wait for confirmation) |
| ″ | `CANCELLED` | `record_result(CANCELLED)` | `Failed("CANCELLED")` |
| ″ | `UNKNOWN` | `record_result(UNKNOWN)` | `NeedsReconciliation` (operator, §5.3) |
| `SUCCEEDED` / `FAILED` / `CANCELLED` (replay) | `load()` only | the same result, no transition |

**Lease loss** (A0R-5): if `lease_guard` raises, the step raises `LlmLeaseLost`. The runtime **stops all
guarded writes and does not call `finish()`**. The durable operation stays in flight. The existing
janitor (`requeue_expired`) sees it and quarantines the job, and the §5.3 reconciler resolves it under its
own authority.

### 5.2 Runtime support (A0R-3; shared with phase A)

- **Signals are translated before generic exception handling:**
  - `LlmWait` → `WaitExternal`;
  - `LlmDeferred` → `Deferred`;
  - `LlmBlocked` → `Failed("LLM_BLOCKED")`;
  - `LlmLeaseLost` → no finish.
- **New outcome `Deferred(reason, retry_after_ms)`** is handled before ordinary completion and maps to
  `JobService.defer()`, which is extended with:
  - **`refund_attempt`**: true only if this claim incremented `attempt`. Today `defer()` always subtracts
    one (`core/jobs.py:552`), which under-counts after a polling claim. The claim records
    `consumed_attempt`;
  - a persisted `defer_reason`;
  - **a refusal while any linked operation is in flight** (`PENDING_SUBMIT` / `SUBMITTED` / `RUNNING` /
    `UNKNOWN`): such a job is quarantined instead, as `finish()` does today.

  `REFUSED_PRELAUNCH` and `NOT_FOUND` are settled, so a deferral after them is allowed.
- **The outcome-union contract test** (`test_outcome_union_and_hook_names_are_stable`) is extended
  deliberately. V1 outcome behaviour is unchanged (a V1 regression test).
- Phase A projects `Deferred` into the side states `WAITING_QUOTA` / `WAITING_PROVIDER`.

### 5.3 Reconciliation

- **The automatic LLM reconciler** (a scheduler job, every 2 min; phase A provides the scheduler service,
  and A0 also ships a CLI entry point).

  **It acts on** jobs in `NEEDS_RECONCILIATION` **whose only blocking operations are `llm.subscription`**.

  **How it resumes (A0S-1):**
  - It takes the job through the audited **`RESUME`** resolution, under **its own worker identity and
    lease**.
  - **It never puts a job back in the queue while a linked operation is in flight.** `claim()`
    (`core/jobs.py:478`) would quarantine it again, creating a loop.

  **How it reconciles (A0S-2):**
  - It reconciles **from the operation's current state, using only legal `ALLOWED_MOVES`**. An
    observation identical to the current state is a no-op: it never repeats `SUBMITTED`, and never moves
    `RUNNING` back to it.

  **What it does, by operation state and gateway answer:**

  | Operation state | Gateway answer | Reconciler action |
  |-----------------|----------------|-------------------|
  | `PENDING_SUBMIT` | the record exists | `SUBMITTED` → finish `WaitExternal` |
  | `PENDING_SUBMIT` | `404` | `NOT_FOUND` → resume the handler, which defers or rearms |
  | `SUBMITTED` / `RUNNING` | accepted or running | `RUNNING` if not already → finish `WaitExternal` |
  | `SUBMITTED` / `RUNNING` | `DONE` / `REFUSED` / `CANCELLED` | the matching terminal or `REFUSED_PRELAUNCH` transition → resume the handler to adopt the result, defer or rearm (per §5.1) |
  | `SUBMITTED` / `RUNNING` | `404` (**previously accepted work has vanished**) | **`UNKNOWN`** → left for the operator. `NOT_FOUND` or readmission needs authoritative no-execution evidence |
  | any | `UNKNOWN` | `UNKNOWN` → left for the operator |
  | — | the gateway is unreachable | no change; retried next tick |
- **The operator command** (extending `JobService.resolve_reconciliation`), audited:
  - **adopt result**: the gateway later shows `DONE`;
  - **declare not executed**: needs gateway `launched=false` evidence;
  - **abandon**: terminal; a new content attempt gets a new `logical_call_id`.

### 5.4 Cancellation forwarding (A0C-8)

- `JobService.cancel()` does not forward cancellation to external work today (`core/jobs.py:864`).
- **For jobs with an in-flight `llm.subscription` operation, the cancel transaction:**
  - sets `llm_invocations.cancel_requested_at_ms`;
  - emits the domain event `llm.cancel_requested`.
- **The outbox consumer `llm_gateway_cancel`** (on the existing `OutboxDispatcher`) POSTs the cancel and
  retries until acknowledged.
- `CANCELLED` is recorded only after the gateway confirms.
- Before the gateway acknowledges, the job shows "cancelling".

### 5.5 Contract changes (guardian-approved)

1. **`UNMETERED_OPERATION_KINDS` += `llm.subscription`** (`contracts/cost.py:97`); the per-kind CHECK in
   migration 0016 is extended the same way.
2. **A new `ProviderOperationState.REFUSED_PRELAUNCH`:**
   - terminal in `ALLOWED_MOVES`;
   - reachable from `PENDING_SUBMIT`/`SUBMITTED`/`RUNNING` **only for `llm.subscription`** (checked in
     `record_result` by kind);
   - not in `_IN_FLIGHT`.
3. **`resubmit_allowed()` also re-arms `REFUSED_PRELAUNCH`,** only for `llm.subscription` and only when
   `last_result` carries `launched=false` admission-refusal evidence. NOT_FOUND re-arming and every paid
   restriction are unchanged.
4. **`PENDING_SUBMIT → CANCELLED`** is allowed **only for `llm.subscription`**, with gateway evidence that
   no attempt launched.
5. **No `UsageReceipt` or charge for `llm.subscription`.** `UsageReceipt` still rejects `ESTIMATED`.
6. **The legacy `LLMProvider` path refuses `MICRODRAMA_LLM_ROUTE=subscription`.**
7. **Expected test changes:** the exact publishing-kind assertions, the provider transition matrix, and
   the outcome union. Metered-reservation, terminal-state and ambiguity guards stay.

### 5.6 Records (migration 0027, guard triggers)

- **`llm_invocations`:**
  - `logical_call_id` (unique), `invocation_id` (unique), `operation_id`, `job_id`, `season_id`,
    `episode_id`;
  - `profile`, `model`, `max_budget_microusd`;
  - **`frozen_call_text` (TEXT, canonical JSON) + `frozen_call_sha256`;**
  - **`structured_output_text` (TEXT) + its sha256;**
  - `model_usage` (integer JSONB), `cost_estimate_microusd`, `usage_unavailable`, `outcome`;
  - `policy_identity`, `cancel_requested_at_ms`, `started_at_ms`, `ended_at_ms`, `cli_version`.

  Arbitrary JSON lives only in TEXT columns, so the integer guard on JSONB
  (`migrations/0009…:94`) still applies to every JSONB column. Replay: identical → no-op; different →
  conflict.
- **`llm_invocation_attempts`:**
  - `invocation_id`, `attempt` (unique together);
  - `outcome`, `launched`, `refusal_reason`, `retry_at_ms`, `result_sha256`, `ended_at_ms`.

  It keeps every prior attempt's result.
- **`quota_observations`:**
  - `invocation_id`, `attempt` (unique);
  - integer before/after fields; `concurrent_jobs` (integer ms);
  - the `uncertainty` set; empty only when exclusivity is established.

### 5.7 Composition gate

`LlmStep` is enabled only when all of these hold, checked at startup and at every dispatch:
1. the paid-external effect is authorised (`Settings.require_effect`) with its flag;
2. `MICRODRAMA_LLM_ROUTE=subscription`;
3. gateway health OK with the expected policy identity.

- The staging worker's OFFLINE_MOCK guard stays.
- The production entry point is phase A's `build_production_world`.
- The ai-route Pro caller restriction stays global; tests use injection seams.

### 5.8 API / OpenAI-compatible adapters

A configuration seam and fakes only.

## 6. Acceptance (offline)

| ID | Proves |
|----|--------|
| A0-1 (= V3-AT-27) | Every §5.1 row, through a real test V3 handler and the real runtime. This includes connect-failure vs after-send failure, readmit replay, refusal → defer → rearm → success, isolation failure settled before `Failed`, and terminal replay |
| A0-2 | Strict argv exactly, including `stream-json --verbose`; no MCP config; empty-cwd refusal; `--bare` absent (fake-`claude` shim) |
| A0-3 | The child environment equals the fixed set even with canary secrets in the parent; absolute executable paths |
| A0-4 | Unit containment: a `setsid` grandchild that ignores TERM; after a deadline or cancel, no descendant survives. Kill the gateway and ai-route (SIGKILL) separately: containment holds; recovery follows the §4.3 table |
| A0-5 | Self-check: an unqualified version; truncated (piped) help; a missing flag; an unlisted policy source; an unresolved remote policy; a policy helper; a managed hook; a policy-identity mismatch → `ISOLATION_UNAVAILABLE` → settled `FAILED` → `LlmBlocked`. A shim whose init event lists an extra tool or an MCP server, or which emits a non-`StructuredOutput` tool call → `ISOLATION_VIOLATION`, health red |
| A0-6 | Admission refusals carry the right reason and `retry_at`; `launched=false`; **`defer` refunds the attempt only on an incrementing claim** (initial vs polling claim); readmit after a simulated reset succeeds exactly once; a lost readmit acknowledgement replays |
| A0-7 | Idempotency: concurrent duplicate POSTs → one attempt; a different hash → 409; tombstones block a re-run after pruning |
| A0-8 | Crash at each boundary: after accept; after `LAUNCH_INTENT` before `systemd-run`; after spawn before `RUNNING`; after the result before `DONE`; after `DONE` before the DB commit; **during `CANCEL_REQUESTED`**; **unit garbage-collected with the result present**. Each recovers per §4.3 with no second execution |
| A0-9 | Lease: real test time past 300 s while pending → `WAITING_EXTERNAL`, no lease; a late result is adopted. **Forced lease loss mid-step → no guarded write, no `finish()`; the janitor quarantines; the auto-reconciler resumes the job under its own lease and resolves it from the gateway, covering every §5.3 table row. An accepted operation that vanishes becomes `UNKNOWN`, never `NOT_FOUND`; a job with an operation in flight is never re-queued** |
| A0-10 | Records: one `llm_invocations` row per logical call; one attempts row and one quota row per attempt; fractional quota normalised; **a schema with fractional bounds and a fractional structured output round-trip byte-exactly as text**; no charge; the `REFUSED_PRELAUNCH` and kind-limited transitions enforced (Python + SQL); a paid kind can't use them |
| A0-11 | Socket permissions from the real container UID/GID; **reconnect** after a gateway restart |
| A0-12 | Cancellation forwarding: cancel → intent persisted → outbox delivers → `CANCELLED` only after confirmation; a delivery retry after a gateway outage |
| A0-13 | No regression: existing ai-route roles keep identical argv and environment (snapshots); claude-configs tests; Drama Box **`make check` + `make pilot`** green; V1 outcome behaviour unchanged |

## 7. Live qualification (operator-approved; at most 5 calls; requalify on any CLI, policy or profile change)

1. **Authentication:** `claude auth status --json` under the exact unit environment and sandbox, before
   any model call. It must show subscription OAuth.
2. **Canaries, without touching the operator's global settings.** (A user-level canary would hot-reload
   into every running session, so v0.3 drops it.)
   - **Project-level canaries:** the qualification runs in the allowlisted, hash-bound fixture directory
     (§3.2), which holds:
     - `.claude/settings.json` with a hook writing a marker;
     - `.mcp.json` with a marker-writing MCP server;
     - a `CLAUDE.md` asking for a canary token in the reply.

     Afterwards the fixtures are cleared, and a test verifies that ai-route refuses a production cwd with
     unexpected contents.
   - **Markers** go under `/var/lib/dramabox-llm/qual/markers/`, which the unit can observe (`PrivateTmp`
     hides `/tmp`).
   - **The host's real user-level customisations** (hooks, plugins, MCP servers) are the user-level
     canaries. No hook log line or MCP activity may carry the probe's session ID.
3. **Forbidden capabilities:** the prompt asks the model to read a file, run a command and fetch a URL.
   From the stream:
   - `effective_tools ⊆ {StructuredOutput}`;
   - `mcp_servers` is empty;
   - no `tool_calls` other than `StructuredOutput`;
   - no canary token in the reply;
   - no marker files.
4. **Metering:** `model_usage` and `cost_estimate_microusd` are present; quota before and after are
   recorded.
5. **Sandbox and write set:** reading `/root/AIVORA` fails inside the unit. The complete set of paths the
   CLI wrote is recorded and becomes the qualified `ReadWritePaths`.
6. **Policy identity:** recorded and bound to the qualification.

Results go to `A0-LIVE-REPORT.md`.

## 8. Build constraints

- Offline first. §7 runs only with the operator's explicit OK.
- The operator installs systemd units, groups and directories.
- claude-configs: stage only `scripts/ai_route.py`, `models.json` and the new tests.
- Drama Box: migration 0027 after the T031 merge; §5.5 goes through the guardian.
- Never print environment variables, tokens or credentials.

## 9. Not in A0

- An `llm` queue lane.
- Live API adapters.
- Migrating legacy story/research callers.

## 10. Open questions

None blocking. §7 finalises the write set and the policy-source inventory.

## 11. Master amendments (v0.4.2, applied)

- §1 rule 3, §4 bible note, §10.0 rows, §10.1, §15 A0 row: resumable `LlmStep`, the unmetered
  `llm.subscription` kind, per-invocation units, no `llm` lane.

## 12. Finding → resolution

| Finding | Resolved in |
|---------|-------------|
| A0C-1 | §1.2, §5.5 (1, 5) |
| A0C-2 | §1.1, §5.5 (6) |
| A0C-3 | §5.1 (state-driven table) |
| A0C-4 | §5.1 (settle first), §5.2 |
| A0C-5 | §5.1 |
| A0C-6 | §4.2 readmit, §5.5 (2, 3) |
| A0C-7 | §1.1, §5.1 lease loss, A0-9 |
| A0C-8 | §4.3, §5.4 |
| A0C-9 | §3.5, §4.3 |
| A0C-10 | §3.3, §3.5 runtime assertion, §7 |
| A0C-11 | §3.2 |
| A0C-12 | §4.1 |
| A0C-13 | §3.4, §4.3 step 5, §5.1 |
| A0C-14 | §3.5, §5.6 |
| A0C-15 | §1.1 |
| A0C-16 | §5.7 |
| A0C-17 | §5.7 |
| A0C-18 | §6, §7 |
| A0R-1 | §5.1 (`PENDING_SUBMIT` → `SUBMITTED` before `WaitExternal`; `client_token`, deadline) |
| A0R-2 | §4.2 readmit with `expected_prior_attempt`; §5.5 (2, 3); `llm_invocation_attempts` |
| A0R-3 | §5.2 |
| A0R-4 | §3.4, §4.3 step 5, §5.1, §5.5 (4) |
| A0R-5 | §5.1 lease loss, §5.3 |
| A0R-6 | §4.3 argv |
| A0R-7 | §4.3 recovery table, §5.4 |
| A0R-8 | §3.3 |
| A0R-9 | §3.2, §3.5, §7 |
| A0R-10 | §3.1, §3.5, §5.6 |
| A0S-1 | §5.3 (`RESUME` under the reconciler's own lease; never re-queued while an operation is in flight) |
| A0S-2 | §5.3 (state-dependent table; vanished accepted work → `UNKNOWN`) |
| A0S-3 | §3.2, §7.2 (hash-bound qualification fixture directory) |
| A0S-4 | §3.5 (missing or malformed initialisation evidence fails) |
| A0S-5 | §4.3 (persistent `deactivating`) |
