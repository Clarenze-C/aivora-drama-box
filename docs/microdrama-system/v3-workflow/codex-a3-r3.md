**Verdict: REWORK.** Two blockers remain; the seven rulings were only partly integrated.

Read-only verification: the note matches `43806c8` byte-for-byte; gateway references match `6974d5a`. No writes or tests.

**N** = [A3-design-note.md](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A3-design-note.md). **S/** = `microdrama/src/microdrama/`; **G/** = `.scratch/a0d-gateway/microdrama/src/microdrama/`.

| Finding | Status | Verification |
|---|---|---|
| N3R2-1 | **CLOSED** | N §4.1:433–454 replaces the illegal paid cancellation edge, requires evidence-backed transitions, extends the LLM adopter’s missing branches/evidence hooks, and preserves CANCELLED without rearm/submit. |
| N3R2-2 | **PARTIAL** | N §3.1:220–228 and §4.1:420–432 introduce classification and recovery authority, but collector/reconciliation rows and §7 still prescribe rejecting paths. N3R3-1. |
| N3R2-3 | **PARTIAL** | N §3.2:270 specifies the corrected order; §7:600–620 and its tests retain the rejected order and conflate begin/rearm. N3R3-2. |
| N3R2-4 | **CLOSED** | N §4.1:406–419 includes terminal operations with incomplete aftermath, defines the completion predicate, and requires idempotent retries after result-commit crashes. |
| N3R2-5 | **CLOSED** | N §4:354–375 explicitly adds runtime completion/defer handling alongside handler guards, uses `cancel_in` for self-cancellation, and preserves evidence before stopping. |
| N3R2-6 | **PARTIAL** | N §5.1:493–509 remains unchanged: reusable worker identity, janitor-cadence connection checks, no incarnation fence. N3R3-3. |
| N3R2-7 | **PARTIAL** | The header claims corrected assertions; §7:653–657 and §9:700–701 retain the reported errors. N3R3-4. |

1. **N3R3-1 — BLOCKING — Recovery classification does not reach every required caller.**  
   N §3.2:271 still starts collection with throwing `fence()` plus the live-worker `lease_guard`; :273 still applies throwing `fence()` to stale reconciliation adoption. N §7:618–620 repeats these paths and retains `settle_under_lease`. Consequently stale collection rejects before quarantine, and stale NEEDS_RECONCILIATION adoption rejects before resolution. Naming `settle_under_recovery` does not connect it to these callers; §4.1’s discovery remains CANCELLED-only. Actual constraints confirm the obstruction: `S/core/jobs.py:621–654,785`; `G/llm/reconciler.py:171–179`.

   **Replacement:** “Collection and reconciliation use ordered `fence_classify` locking. Current worker execution then validates its lease; recovery validates its audited principal and job/operation under locks without requiring a worker lease. Route stale NEEDS_RECONCILIATION operations into this recovery arm before RESUME/admission. Commit quarantine and accounting without installation; successful stale reconciliation may take the existing NEEDS_RECONCILIATION→SUCCEEDED transition. Update every §3.2/§7 row and §9 reference consistently.”

2. **N3R3-2 — BLOCKING — The paid lock audit still contradicts the accepted correction.**  
   N §3.2:270 promises #6→#7, but §7:616–617 explicitly retains #7→#6 for V3. §7:605 also repeats the false implication that rearm takes begin’s reservation-validation chain: compare `S/core/provider_ops.py:195–215` with :354–360. Test :661–663 still validates the old shape; separate begin/rearm tests against settlement are absent. This violates `phase-A-spec.md` §6:279–291.

   **Replacement:** “V3 begin and rearm each take scope locks → job authority → #6 serialization/operation locks → #7 reservation locks, validating reservation eligibility before admission commits. Preserve V1 entry points. Audit begin and rearm separately; test each against release and settlement in both synchronized interleavings. Replace the conflicting audit rows and old-shape test.”

3. **N3R3-3 — SHOULD-FIX — Name-lock connection loss still permits identity reuse.**  
   N §5.1:498 claims two live processes cannot share `lease_owner`, although a disconnected old process can survive until its next janitor check. A replacement can acquire the name meanwhile; `S/core/jobs.py:621–626` authenticates only the reusable worker string and lease expiry.

   **Replacement:** “Separate the configured worker name from a process-unique lease identity. Claims, guards, heartbeat, finish and defer validate that incarnation, so an old process cannot use its replacement’s lease. Define ownership-loss checks before new claims and guarded writes. Test dropping the name-lock connection during a blocked handler, then starting a same-name replacement.”

4. **N3R3-4 — SHOULD-FIX — Acceptance assertions remain uncorrected.**  
   N §9:700 still asks handlers to raise outcome objects `Deferred`/`WaitExternal`; A0 translates actual signals (`G/workers/runtime.py:257–262`). N §7:653–654 still requires “never leased” for the concurrent amendment case. The SIGTERM assertion still assumes abandonment despite the synchronous CLI loop (`S/api/worker.py:88–104`).

   **Replacement:** “Raise `LlmDeferred`, `LlmWait` and the other actual A0 signals; assert translated outcomes separately. Synchronize amendment-first and admission-first orders: the former prevents execution, while the latter permits leasing but no stale canonical effect. Test graceful SIGTERM completion separately from forced-death recovery.”