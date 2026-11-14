**Verdict: REWORK.** Recovery and the paid-operation lock order remain blocking.

Read-only review at `8461147`; A3 v1.1 commit `8320251`; A0-D gateway tree `6974d5a`. No writes or tests.

References: **N** = [A3-design-note.md](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A3-design-note.md); **A1** = [A1-design-note.md](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A1-design-note.md); **S/** = `microdrama/src/microdrama/`; **G/** = `.scratch/a0d-gateway/microdrama/src/microdrama/`.

| Finding | Status | Round-2 assessment |
|---|---|---|
| N3-1 | **CLOSED** | N §2.1:77–104 rejects missing/null and invalid types/ranges; V1 branch remains unconditional. |
| N3-2 | **PARTIAL** | N §4.1:373–414 preserves CANCELLED and names recovery, but its authority and transition coverage remain incomplete. N3R2-1/2. |
| N3-3 | **PARTIAL** | N §3.2:240–258 separates entry points, but stale/cancelled settlement still encounters admission and live-lease guards. N3R2-2. |
| N3-4 | **CLOSED** | N §3.1:202–216 checks ancestor cancellation independently of revision; §2.2:124–134 admits equal-revision cancellation evidence. |
| N3-5 | **PARTIAL** | N §7:541–573 acknowledges the real locks but retains the prohibited V3 #7→#6 ordering. N3R2-3. |
| N3-6 | **PARTIAL** | N §3.2:255 names the collector and transaction, but quarantine reachability and post-result crash discovery remain incomplete. N3R2-2/4. |
| N3-7 | **CLOSED** | N §6.1:507–530 enumerates real state columns, extension handling, revision rules and cancellable statuses against A1 §2.3. |
| N3-8 | **PARTIAL** | `Conflict` inheritance is corrected; N §4:338–351 still leaves runtime completion outside the stated handler-level conversion. N3R2-5. |
| N3-9 | **PARTIAL** | N §5.1:432–449 preserves the V1 default and adds duplicate refusal; connection-loss handling does not sustain the ownership guarantee. N3R2-6. |
| N3-10 | **PARTIAL** | N §5.1:455–464 supplies the child bootstrap and durable fake journal; §7/§9 still contain incorrect executable assertions. N3R2-7. |

1. **N3R2-1 — BLOCKING — Cancelled recovery still specifies illegal or uncovered operation branches.**  
   N §4.1:386–400 permits paid `PENDING_SUBMIT→CANCELLED`; A0 explicitly restricts that edge to `llm.subscription` (`G/core/provider_ops.py:364–370`). Unchanged `adopt_confirmed_cancels` also skips PENDING_SUBMIT with DONE/REFUSED, missing gateway records, and UNKNOWN (`G/llm/cancel_outbox.py:90–160`). Its completion-race branch keeps metering but discards structured output; it does not create A3’s promised quarantine evidence. Furthermore, `resolve_reconciliation` has no provider-result settlement body to “lift”—it checks recorded operations and changes job status (`S/core/jobs.py:790–862`).

   **Replacement:** “Implement an explicit V3 recovery dispatcher over existing operations, with per-kind legal transitions and provider evidence. Paid PENDING_SUBMIT uses NOT_FOUND only with authoritative no-execution evidence; found work records its actual state. Extend the A0 adopter with V3 evidence hooks and the missing recovery branches. Preserve CANCELLED, record settlement metadata, and never rearm or submit.”

2. **N3R2-2 — BLOCKING — Observation-only recovery still cannot obtain usable authority.**  
   N §3.2:253 sends recovery through `_guarded`, which requires a RUNNING job with a live lease (`G/llm/step.py:439–444`; `S/core/jobs.py:621–654`). CANCELLED cannot satisfy that. Stale NEEDS_RECONCILIATION cannot either: N:257 forbids its RESUME, while A0 obtains reconciliation authority through RESUME (`G/llm/reconciler.py:171–179`). N §7:560–561 also invokes the throwing `fence()` for recovery, although that helper rejects the stale/cancelled conditions recovery must settle.

   **Replacement:** “Separate ordered scope locking and authority inspection from admission rejection. Recovery locks and revalidates the job/operation under an audited recovery principal, without requiring the cancelled worker’s lease or restoring content authority. The collector uses the resulting current/stale/cancelled classification to commit evidence and accounting; only current execution may install content. Define routing into this path before `ensure`’s admission call.”

3. **N3R2-3 — BLOCKING — Calling the paid lock inversion pre-existing does not resolve it.**  
   N §7:557–558 expressly retains reservation SHARE (#7) before provider advisories/operation locks (#6). Binding `phase-A-spec.md:279–291` requires one order, including provider advisories. Also, `resubmit_allowed` does **not** take `begin`’s reservation SHARE/ACTIVE-validation chain (`S/core/provider_ops.py:354–360`).

   **Replacement:** “Preserve V1 entry points, and specify a V3 transaction-taking begin/rearm path whose #6 serialization/operation locks precede #7 reservation locks. Validate reservation eligibility atomically before committing admission. Audit begin and rearm separately, and test each against release and settlement in both interleavings.”

4. **N3R2-4 — BLOCKING — The promised post-result recovery pass cannot discover its own crash case.**  
   N:255 commits the terminal operation before settlement, but §4.1:381–383 discovers only unresolved operations on CANCELLED jobs. A crash after that commit removes the operation from discovery; the terminal job cannot be claimed again. A0’s adopter likewise selects only in-flight states.

   **Replacement:** “Discovery also includes terminal operations whose required evidence, accounting settlement or cancellation annotation is incomplete. Define the durable completion predicate and retry this work idempotently, including after worker death immediately following the result transaction.”

5. **N3R2-5 — SHOULD-FIX — Handler-local conversion cannot catch runtime completion conflicts.**  
   N §4:342–350 puts conversion inside handlers, but A0 calls `_finish` after the handler exception block (`G/workers/runtime.py:298`). Cancellation between handler return and completion therefore escapes that conversion. Ordinary `finish` also has no CANCELLED outcome (`S/core/jobs.py:214–263`).

   **Replacement:** “Specify V3 lease-loss handling at runtime completion/defer boundaries as well as handler guards. Self-cancellation uses `cancel_in`, then the existing stop-without-finish control flow. Commit quarantine evidence before stopping; do not introduce another outcome variant.”

6. **N3R2-6 — SHOULD-FIX — The new name lock has a connection-loss ownership gap.**  
   N §5.1:434–442 checks its dedicated connection only on janitor cadence. A blocked handler can outlive that connection while a same-name replacement acquires the released lock. Other database connections remain usable, and lease checks compare the reusable worker string (`S/core/jobs.py:621–626`).

   **Replacement:** “Retain duplicate-name refusal, and fence process incarnations so a surviving old process cannot use a replacement’s lease. Define ownership-loss checks for claims and guarded writes. Test dropping the name-lock connection during a blocked handler, followed by same-name replacement.”

7. **N3R2-7 — SHOULD-FIX — Correct the remaining acceptance assertions.**  
   N §9:641 says handlers raise `Deferred` and `WaitExternal`; these are outcomes, not exceptions. N §7:594–595 still requires “never leased,” contradicting the permitted admission-first interleaving. The SIGTERM case also assumes abandonment although today’s CLI lets the synchronous handler finish before observing `_STOP` (`S/api/worker.py:88–104`).

   **Replacement:** “Raise actual A0 signals (`LlmDeferred`, `LlmWait`, and the remaining signal classes); assert their translated outcomes separately. Synchronize both claim/amendment orders: amendment-first prevents execution; admission-first permits leasing but no stale canonical effect. Distinguish graceful SIGTERM completion from forced-death recovery.”

The previously confirmed architecture remains settled. These corrections stay within the ten accepted round-1 findings and defects introduced by their edits.