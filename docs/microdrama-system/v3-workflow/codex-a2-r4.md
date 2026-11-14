**Verdict: REWORK.** Four round-3 residuals CLOSED; one PARTIAL. The revised lock table also contains two defects.

Reviewed `9d0af9c`; the working note matches that commit. Read-only verification; six in-memory hierarchy-helper assertions passed. No PostgreSQL execution.

| Round-3 residual | Status | Evidence |
|---|---|---|
| N2R3-1 / N2R2-2 — allocation baseline | **PARTIAL** | §2.3 stores SQL-visible evidence, but aggregate amendments contradict its validation rule; N2R4-1 below. |
| N2R3-2 / N2R2-3 — privilege boundary | **CLOSED** | §2.3, [A2:496](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:496): distinct runtime role, inherited-grant restrictions, trusted definer search path, runtime-DSN tests and deployment prerequisite are explicit. |
| N2R3-3 / N2R2-6 — step-cap reduction | **CLOSED** | §2.3, [A2:413](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:413), [A2:480](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:480): final bounds and application completeness are deferred; row guards retain exact approved-value matching. |
| N2R3-4 / N2R2-1 — hierarchy agreement | **CLOSED** | §2.3, [A2:441](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:441); §3.2, [A2:616](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:616): both implementations accept the aggregate and restrict the parentless exception to pre-LOCK setup. |
| N2R3-5 / N2R2-7 — service credentials | **CLOSED** | §6, [A2:938](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:938): explicit `NotFound` mapping precedes ownership and financial reads on both paths; §10 asserts 404. |

**N2R4-1 — BLOCKING — The new baseline capture rejects SEASON amendments.**  
§2.1, [A2:150](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:150) creates zero-valued category rows on aggregate accounts. §2.3’s unconditional `jsonb_object_agg` at [A2:465](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:465) therefore captures a **nonempty** baseline, while deferred validation at [A2:422](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:422) requires `{}`. The hierarchy helper now accepts the aggregate correctly, but its amendment subsequently fails.

**Replacement:** “For `SEASON`, store `category_baseline='{}'`, require empty category deltas, and verify its category allocations remain zero. Capture the complete locked baseline only for spending accounts. Test a successful aggregate-cap amendment followed by a child admission using the increased envelope.”

**N2R4-2 — BLOCKING — Invoice verification’s concrete lock plan omits 451047.**  
§8.2, [A2:1080](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:1080) lists 451045, 451046, 451048 and 451050, but nested ingestion invokes reconciliation ([billing.py:370](/root/AIVORA/drama-box/microdrama/src/microdrama/budget/billing.py:370)), which requires **451047** ([service.py:610](/root/AIVORA/drama-box/microdrama/src/microdrama/budget/service.py:610)). Following that row either leaves required locks unavailable or requests a new advisory after earlier buckets acquired budget locks—the prohibited `#6→#7→#6` sequence. The “one key” entries for query/finalization families also contradict multi-bucket verification. **N2R2-4 is REGRESSED as a concrete specification.**

**Replacement:** “Invoice verification pre-acquires every synthetic-query key (451045), bucket key (451046), derived-allocation key (451047), finalization key (451048), and period key (451050), in that family order and sorted within each family. Each family permits multiple keys. Inner ingestion, reconciliation and finalization reuse this complete plan. Test multi-bucket verification with reconciliation active against competing ingestion.”

**N2R4-3 — SHOULD-FIX — Stage 2 reverses the binding provider/lease order.**  
§8.1, [A2:1037](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:1037) mandates `pod_leases → provider_operations`; binding [phase-A §6:290](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-A-spec.md:290) and [A1 §9:676](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A1-design-note.md:676) require `provider_operations → leases`. The claimed common total order is therefore inconsistent.

**Replacement:** “Within stage 2, transactions requiring both provider-operation and lease row locks acquire `provider_operations` before `pod_leases`, preserving phase-A §6 and A1 §9.”

**Barrier verification:** N2R2-10 remains **CLOSED**. §10, [A2:1169](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:1169) places the start barrier before mutex acquisition, observes B blocked while A holds it, and then releases A; it requires no rendezvous inside the serialized section.