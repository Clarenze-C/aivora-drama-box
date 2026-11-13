**Verdict: FIX-REQUIRED.** Reviewed `ea1cc10...6974d5a`, limited to AD-1–AD-13 and regressions introduced by their fixes. No files changed.

| Finding | Status | Assessment |
|---|---|---|
| AD-1 | **REGRESSED** | CLI flags are corrected, but normal frozen calls now fail admission; AD5-1. |
| AD-2 | **CLOSED** | [gateway.py:536](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/deployment/llm-gateway/gateway.py:536): canonical UUID validation and containment guard ledger access. `/etc` green-only coverage is justified. |
| AD-3 | **CLOSED** | [reconciler.py:123](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/llm/reconciler.py:123), [jobs.py:1064](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/core/jobs.py:1064): both paths recover null external IDs through invocation records. |
| AD-4 | **CLOSED** | [reconciler.py:229](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/llm/reconciler.py:229): settlement now finishes the job outcome; refusal timing is preserved. |
| AD-5 | **CLOSED** | [jobs.py:858](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/core/jobs.py:858): job lock precedes operation settlement, with lease verification and job outcome in one transaction. This closes the original torn-settlement race. |
| AD-6 | **PARTIAL** | Existing work can settle under red health; failed admission now leaves an unnecessary blocking intent; AD5-9. |
| AD-7 | **PARTIAL** | Quarantine survives restart and blocks launches; requalification remains defective; AD5-10. |
| AD-8 | **PARTIAL** | Inspection errors stay unresolved, but exited units produce false no-execution evidence; AD5-2. |
| AD-9 | **PARTIAL** | Required-property/hash checks work; schema coverage, validator equivalence and cancellation adoption remain incomplete; AD5-3/4. |
| AD-10 | **PARTIAL** | Attempt-entry conflicts are detected, but quota mapping, complete evidence capture and result replay protection remain incomplete; AD5-5/6/7. |
| AD-11 | **PARTIAL** | Submitted completion races settle; pending-submit completion races remain stranded; AD5-8. |
| AD-12 | **CLOSED** | [reconciler.py:411](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/llm/reconciler.py:411): the database context manager opens and closes the pool. |
| AD-13 | **CLOSED** | [reconciler.py:204](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/llm/reconciler.py:204): UNKNOWN precedes the pending-submit “record exists” branch. |

**AD5-1 — BLOCKING — Normal calls fail the new request contract (AD-1).**  
[gateway.py:329](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/deployment/llm-gateway/gateway.py:329) requires `policy_identity`; [step.py:139](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/llm/step.py:139) never includes it. Passing an actual `FrozenLlmCall.request_text` to validation returns `400 BAD_REQUEST_TEXT`. The machine flags pass A0-R1’s actual validator, but the shim’s identity echo masks this producer mismatch. **Fix:** freeze and propagate the expected identity consistently, bind it to qualification, and test the actual frozen-call producer against gateway admission.

**AD5-2 — BLOCKING — An exited unit is treated as never launched (AD-8).**  
[gateway.py:839](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/deployment/llm-gateway/gateway.py:839) classifies `inactive`/`failed` as refused; [gateway.py:823](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/deployment/llm-gateway/gateway.py:823) then records `ISOLATION_UNAVAILABLE, launched=false`. A timed-out launcher may have completed its execution already. The existing timeout test checks DONE and execution count, allowing this incorrect evidence. **Fix:** reconcile durable results and execution evidence before settlement; retain UNKNOWN when non-execution cannot be established.

**AD5-3 — BLOCKING — Frozen-schema validation remains incomplete, and the twins diverge (AD-9).**  
[result_validation.py:51](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/llm/result_validation.py:51) silently ignores constraints including numeric bounds and array items. Both validators accept `confidence: 2` against `maximum: 1`. They also disagree on mismatched-identity failure results because [gateway.py:294](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/deployment/llm-gateway/gateway.py:294) returns before checking identity. **Fix:** enforce the accepted schema vocabulary or reject unsupported schemas, and establish identical, outcome-aware identity rules. Extend the corpus accordingly.

**AD5-4 — BLOCKING — Cancellation adoption bypasses validation (AD-9).**  
[cancel_outbox.py:124](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/llm/cancel_outbox.py:124) chooses success solely from `outcome`. A probe adopted `{"outcome":"SUCCEEDED"}` without envelope, output or hash. Contrary to the builder report, this path never calls the shared validator; recovery also omits expected identity at [reconciler.py:308](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/llm/reconciler.py:308). **Fix:** validate cancellation and recovery results against the frozen schema and identity before settlement.

**AD5-5 — BLOCKING — Quota mapping does not match A0-R1 (AD-10).**  
[step.py:219](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/llm/step.py:219) expects `five_hour_bp`, `five_hour_reset_at_ms` and `week_reset_at_ms`. A0-R1 emits `5h_bp`, `5h_reset_ms` and `week_reset_ms`. Feeding its actual snapshot into this mapper loses both five-hour readings and both reset timestamps. **Fix:** normalize the actual interface and make the shim use its field names.

**AD5-6 — BLOCKING — Conflicting result and quota replays are still accepted (AD-10).**  
[step.py:263](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/llm/step.py:263) overwrites invocation results; [step.py:340](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/llm/step.py:340) silently ignores duplicate quotas. With unchanged attempt metadata, a changed output/hash and changed quota raised no Conflict: output was replaced while old quota remained. **Fix:** compare complete per-attempt result and quota evidence before mutation, while allowing distinct later attempts.

**AD5-7 — BLOCKING — Several settlement paths still lose evidence (AD-10).**  
[reconciler.py:269](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/llm/reconciler.py:269) mirrors neither refusal nor cancellation; cancellation adoption likewise sets `mirror=None`. [step.py:578](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/llm/step.py:578) readmits a replayed refusal without preserving its quota. The new test accepts three attempts but only two quota rows. **Fix:** mirror every settlement before readmission and expose sufficient historical result evidence to recover missed observations.

**AD5-8 — SHOULD-FIX — Pending-submit cancellation races remain stranded (AD-11).**  
[cancel_outbox.py:120](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/llm/cancel_outbox.py:120) excludes PENDING_SUBMIT from DONE/REFUSED adoption; launched CANCELLED answers are also skipped. After a lost acknowledgement, the cancelled job retains its blocking operation indefinitely. **Fix:** use authoritative evidence to advance through legal submission/terminal transitions, preserving job cancellation and discarding content.

**AD5-9 — SHOULD-FIX — Failed admission creates blocking work locally (AD-6).**  
[step.py:413](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/llm/step.py:413) creates/rearms the operation before the admission gate runs. Reachable red health then raises `GatewayUnhealthy`, leaving PENDING_SUBMIT despite no POST; runtime quarantines it. **Fix:** gate new admissions before creating/rearming their intent, while retaining unrestricted settlement of existing work.

**AD5-10 — BLOCKING — Requalification lacks verified, durable clearance (AD-7).**  
[gateway.py:1029](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/deployment/llm-gateway/gateway.py:1029) clears quarantine using only the configured identity, which health advertises, without proving a new passing qualification. Clearance is also lost on restart: [gateway.py:1015](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/deployment/llm-gateway/gateway.py:1015) rediscovers the historical violation and relatches. **Fix:** require and persist a verified qualification receipt/epoch covering the violation, and honor that clearance during recovery.

Verification: the committed **13-case validator corpus passed**, and `git diff --check` was clean. Additional read-only probes reproduced the failures above. PostgreSQL/systemd suites were not rerun; systemd bus access is denied in this sandbox.