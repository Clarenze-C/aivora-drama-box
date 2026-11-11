**Verdict: REWORK.** v0.2 resolves the architectural objections, but its specified operation transitions and systemd launch command still prevent the intended lifecycle from working.

Read-only review of v0.2, master v0.4.2, both factmaps, the round-1 report, current code, and installed Claude **2.1.322** help. No files changed, tests run, units launched, or model calls made. “RESOLVED” below assesses the design, not an implemented capability.

Code references are relative to `microdrama/src/microdrama/`; test and migration references are relative to `microdrama/`.

| Finding | Status | Evidence: v0.2 section + current code fact |
|---|---|---|
| A0C-1 | **RESOLVED** | §1.2/§5.4 select an explicit unmetered exemption; `contracts/cost.py:97` and migration 0016 already support reservation-free publishing kinds using this pattern. |
| A0C-2 | **RESOLVED** | §1.1/§5.4 exclude subscription from legacy callers; `contracts/providers.py:142` permits empty usage, while the receipt-dependent callers can retain their existing behavior. |
| A0C-3 | **PARTIAL** | §5.1 supplies context, frozen identity and guarded writes; `core/jobs.py:684` nevertheless rejects its pending-call path because no `SUBMITTED` transition is specified. |
| A0C-4 | **PARTIAL** | §5.2 explicitly introduces `Deferred`; `workers/runtime.py:216` can dispatch it separately, but generic exception handling and unsettled operations still obstruct the blocked path. |
| A0C-5 | **RESOLVED** | §5.1 freezes calls before transport and separates content attempts from recovery; `provider_ops.begin()` deduplicates by provider/client token and checks request identity. |
| A0C-6 | **PARTIAL** | §4.2 adds gateway readmission, but §5.4 makes refusal terminal; `provider_ops.resubmit_allowed():345` only rearms `NOT_FOUND`, leaving the database operation without a continuation route. |
| A0C-7 | **PARTIAL** | §5.2 correctly chooses bounded continuation; `jobs.py:320,527` clear leases and preserve polling attempts, but §5.1 omits the prerequisite operation transition and cannot write after lease loss. |
| A0C-8 | **PARTIAL** | §4.3 provides appropriate cgroup containment; its command is malformed, and `jobs.cancel():864` still does not forward cancellation to external work. |
| A0C-9 | **PARTIAL** | §3.5/§4.3 add durable intent, deterministic units and tombstones; installed systemd garbage-collects successful inactive units, and the recovery table omits relevant states. |
| A0C-10 | **PARTIAL** | §3.3 requires effective-policy inspection, but installed help provides no general effective-policy export; managed sources and executable helpers need a concrete inspection contract. |
| A0C-11 | **RESOLVED** | §3.2 fixes the environment; `ai_route.py:407` reads OAuth credentials from HOME, and installed `claude auth status --help` confirms a JSON authentication-status facility. |
| A0C-12 | **RESOLVED** | §4.1 supplies numeric GID, traversal permissions and directory mounting; these address the UID 10001 worker’s missing supplemental group/mount in current Compose. |
| A0C-13 | **PARTIAL** | §3.5/§5.1 expand mappings, but §4.3 classifies every `launched=false` result as `REFUSED`, conflicting with isolation handling; `PENDING_SUBMIT → CANCELLED` is also currently forbidden. |
| A0C-14 | **RESOLVED** | §3.5/§5.5 normalize quota and timestamps and allow combined uncertainty; this addresses the decimals rejected by migration 0009’s recursive integer guard. See A0R-10 for a separate new payload contradiction. |
| A0C-15 | **RESOLVED** | §1.1 and master §1/§10 consistently remove the LLM lane; `WorkerRuntime` can return promptly after each bounded gateway interaction instead of blocking on inference. |
| A0C-16 | **RESOLVED** | §5.6 requires effect authorization at startup and dispatch; `Settings.require_effect():79` enforces both permitted mode and explicit switch. |
| A0C-17 | **RESOLVED** | §5.6 preserves global caller restrictions and names injection seams plus separate production composition; `ai_route.py:1363` and `pipeline/world.py:325` confirm both existing constraints. |
| A0C-18 | **PARTIAL** | §6 adds substantial lifecycle coverage and §7 makes qualification mandatory; its transcript/tool evidence is unavailable from the specified final-result-only capture with persistence disabled. |

**A0R-1 — BLOCKING — Pending calls cannot enter `WAITING_EXTERNAL` (§5.1–§5.2).**

`begin()` creates `PENDING_SUBMIT`. The accepted/running row only raises `WaitExternalSignal`; it never records acceptance. Consequently, [`JobService.finish()`](/root/AIVORA/drama-box/microdrama/src/microdrama/core/jobs.py:684) quarantines the job. The existing `WaitExternal` mechanism otherwise does release the lease, preserve attempts and permit later claims.

**Replacement:** “After durable gateway acceptance, persist a typed `SUBMITTED` result with `external_id=invocation_id` under the current lease before returning `WaitExternal`. Supply `begin()`’s required client token and deadline. Poll existing operations without repeating prohibited transitions. Runtime completion uses freshly sampled time.”

**A0R-2 — BLOCKING — Gateway readmission has no matching operation rearm (§4.2, §5.1, §5.4).**

A `NOT_STARTED_REFUSED` operation is terminal, yet the same logical call must later become pending/submitted/succeeded. Terminal replay through `load()` cannot accomplish that. An unqualified `/readmit` retry also cannot distinguish a lost acknowledgment from a request for another admission attempt.

**Replacement:** “Define an LLM-specific, audited rearm from `NOT_STARTED_REFUSED`, requiring durable `launched=false` evidence. Preserve prior attempt results, increment the operation attempt and define its renewed deadline. Readmission takes an expected prior attempt/idempotency key; replay returns that admission attempt. Preserve paid-operation resubmission restrictions.”

**A0R-3 — SHOULD-FIX — `Deferred` needs an explicit compatibility and attempt contract (§5.2).**

The mapping is feasible, but [`defer()`](/root/AIVORA/drama-box/microdrama/src/microdrama/core/jobs.py:552) always subtracts one attempt. A polling claim did not increment it; the counter therefore drops during quota waiting and is restored by the next queued claim. Adding `Deferred` also fails the exact-union assertion in `test_outcome_union_and_hook_names_are_stable`.

**Replacement:** “Handle `Deferred` before ordinary completion and translate signals before generic exception handling. Specify attempt values for initial and polling claims, preserve deferral reasons, and prohibit deferral with ambiguous operations. Extend the outcome contract/test deliberately; retain existing V1 outcome behavior.”

**A0R-4 — BLOCKING — Non-success classification contradicts the outcome table (§4.3, §5.1).**

“`REFUSED` if `launched=false`” includes isolation failure, but `LlmStep` recognizes isolation only under `DONE`. Moreover, raising `LlmBlocked` after `begin()` leaves an in-flight operation, so finishing `Failed` becomes reconciliation. Queued cancellation can encounter the forbidden `PENDING_SUBMIT → CANCELLED` transition.

**Replacement:** “Classify by explicit outcome before the `launched` flag. Only admission refusals become `REFUSED`; isolation failure remains `ISOLATION_UNAVAILABLE`. Settle proven pre-launch configuration failures before failing the job. Define typed transitions for queued cancellation and handling for `CANCEL_REQUESTED`.”

**A0R-5 — SHOULD-FIX — Lease-loss handling assigns writes to a worker forbidden to make them (§5.1–§5.2).**

[`lease_guard()`](/root/AIVORA/drama-box/microdrama/src/microdrama/core/jobs.py:629) rejects the worker after lease loss. That worker cannot both stop writes and persist `UNKNOWN`; its subsequent `finish()` also fails. The janitor currently quarantines the job without necessarily changing the operation state.

**Replacement:** “On lease loss, stop all guarded writes and do not finish using the lost lease. Leave the durable in-flight operation for recovery. A janitor or authorized reconciler records ambiguity under its own authority; acceptance verifies the resulting recovery state.”

**A0R-6 — BLOCKING — The displayed systemd command cannot launch the intended process (§4.3).**

The unquoted `/var/lib/dramabox-llm` becomes a command argument rather than part of `ReadWritePaths`; subsequent property arguments are likewise misplaced. After quoting is corrected, `ProtectSystem=strict` still prevents ai-route’s normal writes to [`~/.cache/ai-route`](/root/.claude/scripts/ai_route.py:65).

Reading `/root/.claude` and executing its script are compatible with `ProtectSystem=strict`. Masking `/root/AIVORA` does not mask that sibling directory or the installed Claude binary.

**Replacement:** “Pass each complete property as one argv element, including `ReadWritePaths=/root/.claude /root/.cache/ai-route /var/lib/dramabox-llm` and `InaccessiblePaths=/root/AIVORA /root/.secrets /data`. Precreate required paths and pin executable/PATH resolution. Qualify this exact argv and its required write locations.”

**A0R-7 — SHOULD-FIX — Recovery loses cancellation intent and omits normal systemd states (§4.3).**

No `--collect` does **not** retain successful inactive units indefinitely. The table lacks absent-unit/present-result, failed, activating, deactivating and accepted-but-not-launched cases. Its “any + active → RUNNING” rule also overwrites `CANCEL_REQUESTED`.

**Replacement:** “Validate durable results even when the unit has unloaded. Recover pre-launch `ACCEPTED` records as queued. Preserve cancellation intent and repeat stop/verification after restart. Enumerate starting/stopping/failed/absent units; ambiguous launch intent remains `UNKNOWN`. Persist job-to-gateway cancellation delivery before acknowledging cancellation.”

**A0R-8 — SHOULD-FIX — The self-check needs a concrete inspection and help-capture implementation (§3.3).**

File locations alone do not establish effective policy: documented sources include drop-ins, remote policy and executable `policyHelper`. Installed help exposes no general merged-policy export. Also, a local piped help capture exited **0** after roughly **8 KB**, omitting required flags; PTY capture returned complete help. [Managed-policy mechanisms](https://code.claude.com/docs/en/managed-settings).

**Replacement:** “Specify the pinned-version policy-source inventory, precedence and built-in executable-extension inventory. Refuse unknown sources, unresolved remote policy and executable policy helpers. Bind qualification to the effective policy identity. Capture and validate complete help using the verified PTY method; incomplete output is an inspection failure.”

**A0R-9 — SHOULD-FIX — Live qualification requires event capture (§3.5, §7).**

Authentication inspection is implementable with `claude auth status --json`. However, final result JSON lacks the initialized tool inventory, and `--no-session-persistence` removes the transcript §7 expects. Tool inventory belongs to the initialization event. [Result and initialization schemas](https://code.claude.com/docs/en/agent-sdk/typescript#sdksystemmessage).

**Replacement:** “For qualification, capture `--output-format stream-json --verbose`, retaining initialization, assistant tool-use and final-result events. Assert the effective tool inventory and executed calls from that stream. Keep session persistence disabled. Place canary markers in explicitly observable paths within the unit’s namespace.” The installed CLI supports these flags; their exact strict-profile interaction remains a live qualification check.

**A0R-10 — SHOULD-FIX — Integer-only envelopes conflict with verbatim arbitrary JSON (§3.5, §5.5).**

`structured_output` is verbatim JSON, while the envelope declares every number integer. Frozen schemas can contain fractional bounds, and `max_budget_usd` can be fractional. Persisting such nested numeric values violates [`md_forbid_non_integer_numbers`](/root/AIVORA/drama-box/microdrama/migrations/0009_m0_round3_hardening.sql:94).

**Replacement:** “Keep accounting/quota fields as scaled integers. Store arbitrary schema/output JSON as canonical text or external hash-bound bytes. Represent frozen budget limits in integer micro-USD and convert only at the CLI boundary. Preserve exact payload semantics and request hashes.”

The unmetered exemption itself is compatible with the existing contract. Extend **`UNMETERED_OPERATION_KINDS`** and migration 0016’s CHECK while retaining all four publishing exemptions and mandatory job linkage. Expected contract-test changes include both exact publishing-kind assertions, the provider transition matrix, and the outcome-union assertion. Preserve the existing metered-reservation, terminal-state and ambiguity guards.

The socket design is buildable as specified: `root:64010` directory traversal, socket mode 0660, supplemental GID 64010 and a read-only directory mount support UID 10001. Acceptance must verify **reconnection** after restart; an established connection does not survive server termination.