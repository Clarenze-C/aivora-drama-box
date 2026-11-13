**Verdict: REWORK.**

Reviewed read-only on `feat/microdrama-m0-m4` at `1c62bb6`, including the A0-D snapshot at `ea1cc10`. No writes or tests.

References below: **N** = [A3-design-note.md](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A3-design-note.md); **S/** = `microdrama/src/microdrama/`; **G/** = `.scratch/a0d-gate/microdrama/src/microdrama/`.

The **0035 allocation**, standard table guards and catalog-registration plan fit 0026/0027 and the A1/A2 allocation. The extension → episode → season revision resolver matches A1, provided A4 bumps every affected scope. No new queue lane or duplicate A0 outcome variant is proposed. The fence, cancellation recovery and lock audit nevertheless need these corrections.

1. **N3-1 — BLOCKING — The revision CHECK accepts missing revisions.**  
   `N:63–73`: with `track` set and the field absent or JSON null, the expression evaluates to SQL NULL, which passes CHECK. Digit strings and arbitrarily large digit values also pass; the latter can break A1’s `::bigint` view reads.

   **Replacement:** “For V3 rows, require a present, non-null JSON number representing an integer within the track revision’s supported range. Make missing/null produce FALSE explicitly; retain the unconditional V1 branch. Add direct-SQL rejection tests for missing, null, string, boolean, fractional, negative and overflowing values.”

2. **N3-2 — BLOCKING — Cancelled-operation reconciliation has no reachable implementation path.**  
   `N:193`, `N:271–275`, `N:424–435` promise recovery from CANCELLED and eventual job SUCCEEDED. However, `S/core/jobs.py:785` and `G/core/jobs.py:894` require NEEDS_RECONCILIATION; `G/llm/reconciler.py:107` selects only that status; CANCELLED has no outgoing transition (`S/contracts/states.py:119`). A0’s `G/llm/cancel_outbox.py:67` handles confirmed cancellation, not late success.

   **Replacement:** “Add an explicitly authorized V3 recovery path discovering unresolved operations on CANCELLED jobs. Specify its ownership, legal operation transitions, evidence collection and settlement. Preserve the cancelled job’s terminal status; operation success does not restore content authority. Do not widen V1 terminal transitions. Replace A-T12a’s CANCELLED→SUCCEEDED expectation accordingly.”

3. **N3-3 — BLOCKING — Stale reconciliation and ordinary execution need different permissions.**  
   `N:188–193` allows stale polling/RESUME but fences `begin`. A0’s `LlmStep.ensure` always enters `_begin_under_lease` before inspecting operation state (`G/llm/step.py:308`); its normal path can subsequently rearm NOT_FOUND/REFUSED_PRELAUNCH (`:310–317`, `:360`). A throwing fence before that initial call prevents stale polling; bypassing it without another restriction permits renewed submission.

   **Replacement:** “Distinguish observation/settlement of an existing operation from admission of new work. Stale or cancelled recovery may observe, record legal results, preserve evidence and settle accounting. It may never create/rearm/submit work, install content or enqueue continuations. Name the integration points in `LlmStep` and the reconciler, and test every terminal/refusal/not-found branch.”

4. **N3-4 — BLOCKING — Terminal cancellation does not close admission or content authority.**  
   `N:158–164`, `N:338–345`: cancellation sets `cancelled_at` without changing `content_revision`, while the proposed fence checks only revision equality. A concurrent enqueue after the cancellation sweep can therefore pass. Skipped NEEDS_RECONCILIATION jobs and extension work can also retain matching revisions.

   **Replacement:** “Under the ordered scope locks, enqueue and canonical mutation must reject cancellation of the relevant scope or ancestor, independently of revision equality. Admission performs the corresponding preliminary check. Retain durable cancellation intent for jobs awaiting reconciliation; recovery remains observation-only. Define evidence for cancelled results whose expected and actual revisions are equal—the current `stale_artifacts` CHECK cannot represent that case.”

5. **N3-5 — BLOCKING — The lock audit omits real provider-operation locks.**  
   `N:360`, `N:369–371` describes `begin` as an INSERT and locates advisory locks only in budget code. Actual `begin` first locks the reservation FOR SHARE (`S/core/provider_ops.py:195–197`), then acquires blocking job/reservation advisory locks (`:215`, `:121–125`), before inserting the operation. This includes a #7→#6 ordering absent from the claimed conforming chain. `resubmit_allowed` also acquires these locks (`:359–360`).

   **Replacement:** “Audit `begin`, rearm and their caller-owned transactions through their actual reservation, advisory and operation locks. Specify a conforming V3 order, preserve V1 semantics, and add competing-transaction coverage. Remove the ‘budget-side only’ and `pg_try_advisory_xact_lock` claims. A1 §9’s handoff remains open until this complete audit passes.”

6. **N3-6 — SHOULD-FIX — The collector transaction described is not the transaction cited.**  
   `N:190–191`, `N:361`: `_collect_outputs` persists assets in its own transaction (`S/rendering/comfy_jobs.py:923`), before the separate result transaction (`:899`). Acceptance opens another transaction (`S/pipeline/handlers.py:82`). Merely fencing `record_result` does not implement the note’s combined registration/quarantine/acceptance transaction.

   **Replacement:** “Name the V3 collector and its caller-owned transaction explicitly. Prepare provider bytes outside it; perform fenced registration, result recording, quarantine or installation through transaction-taking helpers inside it. `rendering/comfy_assets.persist_output(tx, …)` is an existing reusable seam (`:215`). Preserve V1 orchestration and specify crash recovery between result persistence and settlement.”

7. **N3-7 — BLOCKING — The rewind command targets a state that episode tracks do not have.**  
   `N:340` specifies a backward **planning** edge for season or episode scope. A1’s episode table has only `production_state` and `release_state` (`A1-design-note.md:139–150`). The command table also leaves revision increments and exact eligible cancellation statuses implicit.

   **Replacement:** “Enumerate scope-specific source→target edges and the actual state column changed; explicitly reject unsupported targets. State extension handling. Advance each changed scope’s display revision once, and its content revision only where required. Cancellation sweeps enumerate cancellable statuses, excluding NEEDS_RECONCILIATION while retaining recovery intent; they do not call `cancel_in` on every non-terminal status indiscriminately.”

8. **N3-8 — SHOULD-FIX — The new exception and worker-stop semantics are incomplete.**  
   `N:144` subclasses `MicrodramaError`, whose default HTTP status is 500 (`S/contracts/errors.py:18`); the comment does not make it 409. Also, raw `Conflict` is not automatically `LlmLeaseLost`: A0 converts it inside `G/llm/step.py:334–339`. Generic runtime handling otherwise turns errors into Failed and calls finish (`G/workers/runtime.py:283–298`).

   **Replacement:** “Derive `StaleContentRevision` from `Conflict` or set `http_status=409`. Specify how each V3 submit/collector converts stale detection and lease loss into its intended control flow. Self-cancellation or revoked ownership must stop without a subsequent ordinary finish; quarantine detection must preserve the evidence transaction.”

9. **N3-9 — SHOULD-FIX — Worker identity requirements contradict their proposed enforcement.**  
   `N:303`, `N:423`, `N:438`: deterministic lane names collide when scaling the same lane. A-T8 requires duplicate-name refusal, while OQ-6 admits no registration/enforcement exists and defers checks to A6c. The new no-flag default also differs from today’s `staging-worker` (`S/api/worker.py:78`).

   **Replacement:** “Choose enforced name ownership or a unique per-process lease identity in A3, and align the CLI, scaling example and tests with that choice. Preserve the documented no-flag V1 behavior. Do not promise startup duplicate refusal through configuration checks owned by A6c.”

10. **N3-10 — SHOULD-FIX — The acceptance plan needs executable boundaries and corrected assertions.**  
    `N:391–392`, `N:423–425`: the bare CLI constructs fixed handlers (`S/api/worker.py:76–78`), so parent-process fake registration does not reach those subprocesses. A0 signals must be raised, not returned. The “never leased” concurrent-claim assertion contradicts §3.2’s permitted admission-before-amendment interleaving.

    **Replacement:** “Provide a test-only child bootstrap exercising the real CLI/runtime and shared fake-provider state surviving worker death. Raise every A0 signal, including lease loss, and assert no finish after ownership loss. Synchronize race interleavings and require no stale canonical effect. Add SIGTERM coverage. For A-T18, distinguish zero submits before dispatch from one accepted submission; recovery must use provider reconciliation evidence, not infer safety from the stable token alone.”

The requested build gate is therefore **not yet satisfied**: A-T8’s isolation approach is sound, but A-T12a/A-T18 currently depend on unreachable recovery paths and incompletely specified transaction boundaries.