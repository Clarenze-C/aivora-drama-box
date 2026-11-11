**Verdict: REWORK.** The gateway architecture is reasonable, and keeping synchronous LLM calls inside their owning jobs is viable for A0. The specified integration cannot currently work: zero-priced reservations are rejected, two callers require receipts, quota deferral does not follow the claimed path, and long calls outlive worker leases.

Read-only inspection covered the requested documents, code, staging configuration, and installed Claude Code **2.1.322** help. No files changed, tests ran, or model calls occurred.

The installed flags have these semantics:

| Flag | Assessment |
|---|---|
| `--safe-mode` | Disables ordinary customizations and preserves authentication. Managed policy and built-in plugins remain relevant exceptions. |
| `--tools ""` | Removes built-in tools. Pass an actual empty argv element. |
| `--strict-mcp-config`, without `--mcp-config` | Coherent with selecting no supplied MCP servers; does not disable unrelated policy execution. |
| `--no-session-persistence` | Prevents saved/resumable sessions. It does not itself establish a fresh session or isolate credentials. |
| `--permission-prompts none` | Denies requests requiring permission prompts; other permission decisions still apply. |
| `--json-schema` | Requests structured output; its interaction with the complete isolation profile needs real-CLI qualification. |
| `--max-budget-usd` | A client-side estimated-cost stopping threshold. |
| `--restricted` | Ignores user/project/local settings; does not document disabling stored OAuth credentials. |
| `--bare` | **Explicitly disables OAuth/keychain authentication** in the installed help. Unsuitable here. |

Thus, the proposed three-flag combination is **OAuth-compatible by its documented semantics**. Successful execution under the exact service identity and environment remains unproven. [Official CLI reference](https://code.claude.com/docs/en/cli-reference).

**A0C-1 — BLOCKING — Zero-priced reservations deterministically fail (§5.2).**  
[`BudgetReservationRequest`](/root/AIVORA/drama-box/microdrama/src/microdrama/contracts/cost.py:166) rejects zero unit prices before `reserve()` runs. `budget/policy.py:94` independently rejects zero worst-case exposure and zero unit prices. This is already established, rather than a build-time question. `llm.invoke` also lacks an unmetered-operation exemption.

**Replacement:** “Before implementation, obtain a guardian-approved subscription dispatch contract: either explicitly supported zero-cash reservations, or a subscription-specific unmetered operation with corresponding caller and database changes. Preserve existing paid-dispatch safeguards. Do not manufacture a positive cash price.”

**A0C-2 — BLOCKING — Empty receipts break existing callers (§5.2).**  
`LLMResponse.usage=[]` is contractually valid, but [`story/script_maker.py:1060`](/root/AIVORA/drama-box/microdrama/src/microdrama/story/script_maker.py:1060) discards such responses; `research/script_maker.py:387` does likewise. Ordinary story/research success paths iterate receipts without releasing receipt-free holds. Their failure-release branches do not handle successful subscription responses.

**Replacement:** “Update all four LLM caller families to accept validated, receipt-free subscription responses. Validate output independently of receipt presence. Close any retained holds after the operation becomes terminal; preserve holds during ambiguity. Subscription estimates never become `UsageReceipt` charges.”

**A0C-3 — BLOCKING — The adapter lacks the context required by `ProviderOperation` (§5.1).**  
[`begin()`](/root/AIVORA/drama-box/microdrama/src/microdrama/core/provider_ops.py:145) requires `tx`, `provider`, `request_hash`, `job_id`, and `now`, plus a reservation unless exempted. `LLMRequest` supplies no job or worker identity, and current LLM reservations omit `job_id`. `needs_reconcile()` is a Boolean predicate, not a persistence action. `record_result()` requires a typed `ProviderOperationResult`; terminal states cannot transition to themselves.

**Replacement:** “Pass request-scoped owning `JobContext` through the internal service boundary. Commit `begin()` before POST, with `lease_guard()` in the same transaction. Persist accepted, running, ambiguous and terminal results explicitly. Guard result writes by the current lease. Replay terminal operations through `load()` without repeating terminal transitions or requiring a newly ACTIVE reservation.”

**A0C-4 — BLOCKING — The claimed quota-deferral path does not exist (§5.1).**  
`TransientProviderError.code` is `PROVIDER_TRANSIENT`; `RateLimited` is a separate subclass. Story/research catch both through their transport-retry loops. Exceptions reaching [`WorkerRuntime._execute()`](/root/AIVORA/drama-box/microdrama/src/microdrama/workers/runtime.py:216) become `Failed`. Attempt-preserving `defer()` currently runs only for pre-handler throttling; returning `RetryLater("RATE_LIMITED", ...)` from a handler also does not enter that branch.

**Replacement:** “Implement explicit propagation of quota admission outcomes through services and handlers to attempt-preserving `JobService.defer()`. Convert absolute `retry_at` into bounded `retry_after_ms`. Preserve completed work. Treat isolation/configuration failure as disabled or blocked, rather than `WAITING_QUOTA`.”

**A0C-5 — BLOCKING — Deterministic tokens do not establish job resumption (§5.1).**  
The token derivation itself is sound: story uses episode/write-attempt/round/attempt; research uses season/trigger/LLM-attempt. The same token therefore maps to the same UUID. However, [`ResearchService._open_run()`](/root/AIVORA/drama-box/microdrama/src/microdrama/research/service.py:369) replays existing RUNNING/FAILED runs without continuing synthesis. Story can encounter a stale write claim. Recreated reservation requests also change `expires_at`, which participates in their hash and can cause conflicts before `generate()` is reached. Jobs with in-flight operations are quarantined rather than ordinarily reclaimed.

**Replacement:** “Persist and resume the exact logical call, frozen request, reservation identity and deadline. Add explicit service-level continuation for incomplete research/story work and an authorized reconciliation runner. Demonstrate recovery through actual handlers. New content attempts receive new tokens; transport recovery preserves the existing token.”

**A0C-6 — BLOCKING — Persisted refusals make retries permanent (§3.4–§5.1).**  
The gateway returns the existing record for the same ID, while ai-route returns every completed stored result without relaunching. Consequently, a quota refusal remains the same refusal after quota resets. Changing the token casually would undermine the operation’s replay discipline.

**Replacement:** “Separate logical invocation identity from admission attempts. Permit explicit, bounded re-admission only when durable evidence proves no model execution began. Preserve the immutable request and refusal history. Define corresponding ProviderOperation transitions. UNKNOWN executions remain ineligible for resubmission.”

**A0C-7 — BLOCKING — The worker lease expires before the allowed call (§5.1).**  
The default lease is **300 seconds**, versus a **600-second** CLI deadline and **720-second** adapter deadline, before queue delay. [`heartbeat()`](/root/AIVORA/drama-box/microdrama/src/microdrama/core/jobs.py:591) cannot revive an expired lease. Current-time lease guards reject subsequent writes, and the janitor quarantines expired jobs with in-flight operations. The runtime also passes cycle-start `now` into completion, which can mask elapsed time and must not serve as lease proof.

**Replacement:** “Maintain the owning lease throughout queueing and polling, using fresh time, or implement bounded `WAITING_EXTERNAL` continuation. On lease loss, stop domain writes and hand the durable invocation to reconciliation. Bound every socket operation. Include this minimum lifecycle integration in A0 before live use.”

**A0C-8 — BLOCKING — Process groups do not guarantee cleanup across the three-level chain (§3.2, §4).**  
A new session plus `killpg()` fixes the current direct-child-only behavior for descendants remaining in that group. It does not cover descendants that create another session, ai-route being SIGKILLed, or gateway death while ai-route/Claude survive. Cancelling the database job also does not cancel external work: [`JobService.cancel()`](/root/AIVORA/drama-box/microdrama/src/microdrama/core/jobs.py:864) explicitly preserves it.

**Replacement:** “Define supervision for gateway → ai-route → Claude, including abrupt parent death. Use containment capable of reaping every invocation descendant, with an external deadline backstop. Persist cancellation intent, forward TERM, escalate after ten seconds, and confirm cleanup before reporting cancellation. Specify queued cancellation, completion races and job-cancellation wiring.”

**A0C-9 — BLOCKING — Crash-safe launch ownership is underspecified (§3.4, §4).**  
Atomic file replacement does not atomically coordinate request/state/result files or make them durable across host failure. The spawn-to-RUNNING crash window is unspecified. PID liveness alone cannot establish process identity. Deleting invocation records after 30 days can also erase deduplication protection.

**Replacement:** “Serialize acceptance and launch ownership; durably record a launch-intent state before spawning. Recover ambiguous launch intent as UNKNOWN. Define canonical request hashing at both layers, including effective model/configuration and limits. Persist before acknowledgment with the required fsync ordering. Retain immutable deduplication tombstones beyond payload pruning.”

The same-ID/same-hash rule and 409 conflict are sound. **Never automatically relaunching ambiguous work is also sound**, provided UNKNOWN has an explicit API state, reconciliation procedure and operator-visible recovery path.

**A0C-10 — BLOCKING — Strict isolation is overclaimed (§3.2).**  
The installed help explicitly retains managed policy and built-in plugins. Official documentation further identifies policy-configured hooks as surviving safe mode. Flag-name presence therefore cannot prove the master’s “no inherited hooks can execute” property. An empty cwd also provides no filesystem isolation from the retained HOME. [Safe-mode policy exceptions](https://code.claude.com/docs/en/cli-reference#cli-flags).

**Replacement:** “Strict eligibility requires a qualified CLI identity and inspection of effective managed policy, settings-derived environment and executable extensions. Refuse when executable customization remains. Define isolation as the verified CLI configuration boundary; add filesystem/process restrictions if the intended guarantee includes preventing host-file access.”

**A0C-11 — SHOULD-FIX — Environment bisection is a diagnostic, not an OAuth proof (§3.2).**  
A successful prompt can use an unintended authentication path. Environment dependencies need not behave monotonically under bisection, and “retain anything necessary” conflicts with dropping every `*_TOKEN`. The existing router reads subscription credentials from HOME, so no OAuth environment exception is established by the inspected code.

**Replacement:** “Start with a fixed minimal environment and the intended credential directory. Verify authentication method under that exact environment before an approved no-op. Add only individually justified variables; explicitly document any credential exception. Record all probe calls within approval scope. Never bisect from the complete secret-bearing environment.”

**A0C-12 — SHOULD-FIX — Socket deployment needs a concrete permission and restart contract (§4).**  
The worker runs as UID **10001**; current [`compose.staging.yaml`](/root/AIVORA/drama-box/microdrama/deployment/compose.staging.yaml:52) has neither the mount nor supplemental group. Socket mode 0660 alone does not supply parent-directory traversal or matching numeric GID. Mounting the socket inode directly can leave the container attached to an obsolete socket after replacement.

**Replacement:** “Specify service UID/HOME, fixed socket GID, worker `group_add`, directory ownership/traversal permissions, and a read-only mount of a stable runtime directory. Preserve that directory across service restarts. Keep credentials/store unmounted; use private store permissions and umask. Test allowed and denied container identities plus reconnect after restart.”

**A0C-13 — SHOULD-FIX — Transport limits and outcome mappings are incomplete (§3–§5).**  
The gateway command shown omits schema and budget propagation; current ai-route also has no `--model` argument. `LLMRequest.max_input_tokens` and `max_output_tokens` disappear from the gateway request. Existing reservation timeout configuration is not reconciled with the new deadline. UNKNOWN is absent from the GET enum, isolation exits 2 despite the gateway’s exit-75 refusal rule, and CANCELLED lacks an adapter mapping.

**Replacement:** “Publish one complete request/argv/outcome mapping, including schema, effective model, budget and enforced token/time limits. Reject unsupported limits. Distinguish pre-launch refusal from post-launch failure. Define missing usage/cost as unavailable, and define every exit/result combination. Label `--max-budget-usd` as an estimated stopping threshold that can overshoot.” [Budget-cap semantics](https://code.claude.com/docs/en/cli-reference#cli-flags).

**A0C-14 — BLOCKING — Quota records conflict with integer-only database guards (§5.2, §5.4).**  
Quota utilization is read as floats. Registered job snapshots include fractional timestamps. Copying these into guarded JSONB will fail the recursive [`md_forbid_non_integer_numbers`](/root/AIVORA/drama-box/microdrama/migrations/0009_m0_round3_hardening.sql:85) trigger. The spec defines integer cost estimates but no equivalent quota/snapshot normalization.

**Replacement:** “Specify scaled-integer quota utilization, integer timing units and normalized concurrent-job snapshots before persistence. Define conversion precision, nullability, uniqueness and replay-conflict rules. Preserve original decimals outside guarded rows where necessary. CLEAN requires established exclusivity; otherwise record attribution uncertainty, including simultaneous uncertainty causes.”

**A0C-15 — SHOULD-FIX — No separate LLM queue is reasonable, but lane blocking is wider than stated (§2).**  
The current runtime is single-threaded; slots are admission counts. A long production handler delays **publication and community work in the same process**, not merely other production jobs. Adding another queue alone would not fix that. Master §1 rule 3 and §10.0’s generation-unit row still promise an `llm` lane despite v0.4.1 changing only one row.

**Replacement:** “A0 uses owning-job synchronous calls with bounded duration. Phase A must provide independent worker processes or bounded continuation wherever release responsiveness requires it, and measure contention before live qualification. Amend all conflicting master clauses. Treat 70% as a configurable pilot policy, not a proven orchestration reserve.”

**A0C-16 — BLOCKING — Composition conditions omit the existing effect switch (§5.3).**  
“Mode is not OFFLINE_MOCK” does not authorize a model call. [`Settings`](/root/AIVORA/drama-box/microdrama/src/microdrama/config.py:79) requires an allowed mode **and** the explicit effect flag. The proposed adapter conditions could select live execution without that permission.

**Replacement:** “Require the existing external-request effect authorization at each dispatch, alongside route selection and gateway qualification. Preserve explicit operator approval for A0 live probes. Define the separate production composition entry point; retain staging’s OFFLINE_MOCK guard.”

**A0C-17 — SHOULD-FIX — Existing router restrictions affect the new role and its tests (§3, §5.3).**  
The Pro caller prohibition applies by provider, not role: [`ai_route.py:1363`](/root/.claude/scripts/ai_route.py:1363) rejects Codex ancestry or a GLM caller environment. Real-router shim tests launched by either builder can fail before reaching the shim. `build_pipeline_world()` also invokes a factory that requires OFFLINE_MOCK, so replacing its LLM field alone cannot construct production.

**Replacement:** “Name the authorized daemon invocation path and separate production builder. Preserve existing Pro caller restrictions. Provide explicit offline test seams for caller detection, quota and subprocess execution; do not weaken global restrictions to make shim tests pass.”

**A0C-18 — BLOCKING — Acceptance proves less than claimed (§6).**  
The shim approach is valid for adapter mechanics, argv/environment construction, persistence and failure injection. It cannot establish that real Claude interprets the isolation flags correctly. A0-L1 supplies real-CLI evidence, but a no-op plus absent hook-log lines and an MCP process snapshot does not prove every customization/tool boundary.

**Replacement:** “Retain A0-1..10, add targeted coverage below, and make strengthened real-CLI qualification mandatory before enabling the subscription adapter. Requalification follows CLI or effective-policy changes.”

Required additions:

- Exercise actual story/research/Script Maker handlers for receipt-free success, quota deferral and recovery.
- Advance real test time beyond 300 seconds; verify heartbeat, lease loss, cancellation and fenced writes.
- Crash at acceptance, launch-intent, spawn, result persistence and DB-commit boundaries; test concurrent duplicate POSTs.
- Test refusal → quota reset → safe re-admission, terminal replay, request conflicts and payload pruning.
- Kill gateway and ai-route separately; include TERM-resistant and session-detaching descendants.
- Test fractional quota/snapshot normalization and idempotent DB writes.
- Test socket access and restart from the actual container UID/GID.
- Strengthen A0-L1 with controlled customization canaries, verified authentication, attempted forbidden capabilities and observable effective tools. Account for the schema helper: Claude adds a `StructuredOutput` tool for structured responses. [Structured-output behavior](https://code.claude.com/docs/en/agent-sdk/structured-outputs#recognize-the-structuredoutput-tool-call).
- Include the master’s required **`make check` and `make pilot`**, plus focused claude-configs regression tests.

