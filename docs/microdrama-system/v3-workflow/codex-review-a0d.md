**Verdict: FIX-REQUIRED.**

Reviewed `0cda424..ea1cc10` at the pinned HEAD. Tracked `git diff HEAD` is empty. No files were changed.

**AD-1 — BLOCKING — The launcher does not implement the real A0-R1 interface.**  
[gateway.py:590](/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/deployment/llm-gateway/gateway.py:590), [ai_route_shim.py:98](/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/tests/fixtures/llm_gateway/ai_route_shim.py:98). The gateway passes only invocation ID, attempt and result path. It omits model, deadline, prompt, schema and budget. A read-only probe of A0-R1’s actual validator rejects this invocation at `--model None`; the shim succeeds because it independently reads `request.json`. **Fix:** propagate the complete frozen request through A0-R1’s supported interface, bind the expected policy identity, and make the shim enforce that interface.

**AD-2 — BLOCKING — Client-supplied invocation IDs escape the root-owned store.**  
[gateway.py:311](/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/deployment/llm-gateway/gateway.py:311). Validation checks only length. An ID such as `/etc` makes `Ledger.dir` resolve to `/etc`, allowing a socket client to create or overwrite `request.json` and `state.json` outside the store through the root service. **Fix:** require canonical UUIDs before every ledger lookup and enforce path containment.

**AD-3 — BLOCKING — Real pending-submit crashes cannot be reconciled or cancelled automatically.**  
[reconciler.py:132](/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/src/microdrama/llm/reconciler.py:132), [jobs.py:1001](/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/src/microdrama/core/jobs.py:1001). Before the `SUBMITTED` write, `provider_operations.external_id` is null. The reconciler returns `SKIPPED_NO_EXTERNAL_ID`, and cancellation skips forwarding. This includes a lost POST acknowledgement followed by an unreachable GET. The pending recovery tests artificially retain an external ID from an earlier submission. **Fix:** recover the already-persisted invocation ID through `llm_invocations.operation_id` for both reconciliation and cancellation.

**AD-4 — BLOCKING — Settled recovery does not safely resume the handler.**  
[reconciler.py:168](/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/src/microdrama/llm/reconciler.py:168). The `NOT_FOUND`, `DONE`, `REFUSED` and `CANCELLED` branches leave the job `RUNNING` until its two-second lease expires. At `max_attempts`, the janitor marks even successfully completed work `FAILED/LEASE_EXPIRED`. Below that limit, refusal recovery drops `retry_at_ms` and immediately rearms after requeue, bypassing the specified quota deferral. **Fix:** explicitly continue adoption or finish a correctly timed deferral under the reconciler’s lease; preserve attempt accounting.

**AD-5 — BLOCKING — Reconciler mutations are not fenced by its lease.**  
[reconciler.py:217](/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/src/microdrama/llm/reconciler.py:217), [reconciler.py:254](/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/src/microdrama/llm/reconciler.py:254). `RESUME` commits separately; subsequent operation writes never check the reconciler’s lease. If an operation lock blocks beyond two seconds, the janitor can quarantine the job before the reconciler settles its last blocking operation. The job then has no candidate for another automatic pass. **Fix:** guard each mutation and reload current state in the same transaction, taking the job lock before the operation lock. Add a two-connection reconciler/janitor race test.

**AD-6 — BLOCKING — The health gate prevents required settlement.**  
[step.py:301](/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/src/microdrama/llm/step.py:301). After a real `ISOLATION_VIOLATION`, gateway health becomes red. The next `ensure()` rejects health before polling the durable result, so it cannot perform the required `FAILED` settlement followed by `LlmBlocked`. Gateway outages similarly bypass the documented transport-deferral path. The isolation test’s fake remains healthy. **Fix:** retain admission checks while allowing existing operations to be polled and settled through explicit recovery handling.

**AD-7 — BLOCKING — Isolation quarantine disappears on restart and does not stop queued launches.**  
[gateway.py:681](/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/deployment/llm-gateway/gateway.py:681), [gateway.py:525](/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/deployment/llm-gateway/gateway.py:525). `last_isolation_violation` exists only in memory; recovery skips terminal `DONE` records. Restart therefore clears red health without requalification. `pump()` also continues launching queued work while the latch is set. **Fix:** persist the qualification-bound quarantine, restore it before serving, and enforce it at launch.

**AD-8 — BLOCKING — Systemd failures are mistaken for proof that nothing is running.**  
[gateway.py:554](/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/deployment/llm-gateway/gateway.py:554), [gateway.py:261](/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/deployment/llm-gateway/gateway.py:261). A timed-out `systemd-run` may already have created its unit, yet the gateway records `DONE`, `launched=false` and releases the queue slot. A failed or timed-out `systemctl show` is also treated as an absent unit, permitting false cancellation confirmation. **Fix:** distinguish authoritative absence from inspection failure; reconcile ambiguous launches by deterministic unit name and keep unresolved work blocking.

**AD-9 — BLOCKING — Success adoption does not validate the frozen output schema.**  
[step.py:564](/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/src/microdrama/llm/step.py:564), [reconciler.py:211](/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/src/microdrama/llm/reconciler.py:211). Any JSON object passes the step; the reconciler trusts `outcome=SUCCEEDED` without parsing it. A probe accepted `{}` against a schema requiring `line` and recorded `SUCCEEDED`. The gateway’s result reader also checks only schema marker, ID and attempt, so incomplete envelopes can become `DONE`. **Fix:** share result-envelope, integrity and frozen-schema validation across normal adoption and recovery.

**AD-10 — BLOCKING — Required attempt and quota evidence is missing.**  
[step.py:190](/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/src/microdrama/llm/step.py:190), [step.py:220](/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/src/microdrama/llm/step.py:220). Refusal/cancellation paths do not mirror attempt records; DONE mirroring inserts only the latest attempt. There is no production insert into `quota_observations`. A refusal→success sequence therefore loses the earlier attempt and all quota observations. Conflicting attempt replays are silently ignored. **Fix:** persist every settled attempt and its quota observation, compare duplicate evidence, and reject conflicting replays.

**AD-11 — SHOULD-FIX — Cancellation loses the completion race.**  
[cancel_outbox.py:94](/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/src/microdrama/llm/cancel_outbox.py:94). If the gateway completes just before receiving cancel, it returns its existing `DONE` state. Delivery is acknowledged, but adoption accepts only `CANCELLED`. The cancelled job retains an in-flight operation indefinitely. **Fix:** reconcile all authoritative terminal answers while preserving job cancellation and discarding content output.

**AD-12 — SHOULD-FIX — The shipped reconciler CLI cannot run.**  
[reconciler.py:291](/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/src/microdrama/llm/reconciler.py:291). It constructs `Database` without opening it. A read-only invocation fails before connecting with `PoolClosed: the pool ... is not open yet`. **Fix:** use the database context manager or explicitly open and close the pool.

**AD-13 — SHOULD-FIX — `PENDING_SUBMIT + UNKNOWN` uses the wrong recovery row.**  
[reconciler.py:161](/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/src/microdrama/llm/reconciler.py:161). Every existing record becomes `SUBMITTED → WaitExternal`, including gateway `UNKNOWN`. The required “any + UNKNOWN” operator branch is reached only for other operation states. **Fix:** give `UNKNOWN` precedence and transition directly to operator reconciliation.

**Explicit A0S-1 / A0S-2 verification**

The table below describes actual behavior, including the exceptions above.

| Operation state | Evidence | Actual reconciler action |
|---|---|---|
| `PENDING_SUBMIT` | GET finds record | `SUBMITTED → WaitExternal`, provided external ID exists; real null-ID recovery fails AD-3 |
| `PENDING_SUBMIT` | GET 404 | `NOT_FOUND`, then deliberate lease expiry; AD-3/4 |
| `SUBMITTED/RUNNING` | GET accepted/launching/running | `RUNNING` once, then `WaitExternal`; ordinary mapping correct |
| `SUBMITTED/RUNNING` | GET DONE | Terminal transition and mirror, then lease expiry; AD-4/5/9/10 |
| `SUBMITTED/RUNNING` | GET REFUSED | `REFUSED_PRELAUNCH`, then lease expiry; retry timing lost, AD-4/10 |
| `SUBMITTED/RUNNING` | GET CANCELLED | `CANCELLED`, then lease expiry; AD-4/10 |
| `SUBMITTED/RUNNING` | GET 404 | `UNKNOWN → NEEDS_RECONCILIATION`; correct |
| Any | GET UNKNOWN | Correct for submitted/running; pending differs, AD-13; existing UNKNOWN operations remain operator-owned |
| Any | Gateway unreachable | No mutation or RESUME; correct when the invocation ID is available |

The reconciler issues GETs only and contains no reservation, receipt or charge path. Its ordinary active-work branches avoid requeueing in-flight operations. **A0S-1 and A0S-2 are nevertheless incomplete** because of the recovery and fencing failures above.

**Gateway §4.3 recovery verification**

| Ledger state | Proof | Recovery behavior |
|---|---|---|
| `ACCEPTED` | Durable request/state, no launch intent | FIFO requeue |
| `LAUNCH_INTENT/RUNNING` | Unit activating/active/reloading | Reattach as RUNNING |
| `CANCEL_REQUESTED` | Unit activating/active/reloading | Reissue stop; watcher confirms |
| Any applicable in-flight state | Persistent deactivating | Bounded startup wait, unresolved/red, no relaunch |
| `CANCEL_REQUESTED` | Unit authoritatively absent/inactive/failed | CANCELLED; retains result for metering |
| `LAUNCH_INTENT/RUNNING` | Unit stopped, valid result | DONE/REFUSED by outcome |
| `LAUNCH_INTENT/RUNNING` | Unit stopped, missing/invalid result | UNKNOWN; malformed-envelope detection is incomplete, AD-9 |

These mappings handle the tested crash boundaries without a second execution. AD-8 prevents accepting the broader supervision guarantee; AD-7 breaks persistent isolation quarantine.

Migration 0027 correctly adds the five-kind unmetered linkage CHECK, closed eight-value `DeferReason` CHECK, and delete/truncate/integer guards. Python enforces the kind/evidence restrictions on refusal, rearm and pending cancellation. Ordinary `consumed_attempt` refunds, signal ordering, in-flight deferral quarantine and the deliberate outcome-union extension are implemented.

No concrete new lock-order cycle was found. The report’s inventory omits the provider helpers’ job advisory locks, and its reconciler row obscures separate committed transactions and missing lease fencing.

The retained gate matches `ea1cc10`: **3,137 unit, 462 contract and 314 integration tests passed; lint and offline pilot passed**. PostgreSQL fixtures and gateway systemd tests are real. Existing test edits follow the planned contract and migration-tail changes; `ea1cc10` adjusts only tail expectations. Original red-before-green evidence is only partly auditable because the report reconstructs lost-session results. My additional checks used read-only, in-memory probes; no full gate was rerun.

