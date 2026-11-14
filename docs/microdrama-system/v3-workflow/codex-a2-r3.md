**Verdict: REWORK.** Five findings CLOSED; five PARTIAL.

Reviewed v1.2, byte-identical to `8bb2089`, against the binding documents and current source. Read-only. Exercised the displayed hierarchy helper and cap-reduction arithmetic in memory; **no PostgreSQL execution**.

**A2** below means [A2-design-note.md](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md).

| Finding | Status | Evidence / disposition |
|---|---|---|
| N2R2-1 | **PARTIAL** | §3.2, A2:544–561 fixes aggregate handling and verifies the mutex. §2.3, A2:414–418 still permits other parentless account kinds before LOCK. N2R3-4. |
| N2R2-2 | **PARTIAL** | §2.3, A2:362–391 fixes prior-tip/final-tip handling and refuses multiple same-account amendments. The per-category baseline has no specified SQL-visible representation. N2R3-1. |
| N2R2-3 | **PARTIAL** | §2.3, A2:448–460 chooses function-only insertion, but its required role boundary is not established. N2R3-2. |
| N2R2-4 | **CLOSED** | §8, A2:955–959, :968–988 requires the complete outer transaction’s seven-family lock plan, pre-acquisition of required row locks and all season mutexes, and inner-helper reuse. This addresses `#6→#7→#6` at the design level. |
| N2R2-5 | **CLOSED** | §3.3, A2:613–637, :675–694 explicitly bypasses cleanup spill feasibility, performs no allocation transfer, and records required overruns before flush. |
| N2R2-6 | **PARTIAL** | §2.2, A2:185–187 fixes TRUNCATE DDL; §2.3, A2:435–446 adds exact value/scope matching. Its final-bound check inside a BEFORE ROW guard introduces a valid-amendment refusal. N2R3-3. |
| N2R2-7 | **PARTIAL** | §6, A2:873–884 closes the ownership bypass in the design. The promised service-credential `NotFound` contradicts the named helper’s actual exception. N2R3-5. |
| N2R2-8 | **CLOSED** | §7, A2:918, :932–937 defines creation response, first-success event and replay behavior; §2.4, :490–492 registers the event schema. |
| N2R2-9 | **CLOSED** | §6, A2:835–853 explicitly defines unfinished membership and subtracts every unfinished episode’s existing commitment, including DIRECTED. |
| N2R2-10 | **CLOSED** | §10, A2:1057 places the start barrier before mutex acquisition, observes B blocked while A holds it, then releases A. Boundary amounts, child-only repetition and deadlock/timeout failures are explicit. |

**N2R3-1 — BLOCKING — Deferred allocation validation cannot retrieve its baseline.**  
§2.3, [A2:383](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:383). The amendment DDL stores deltas but no allocation baseline or apply-once evidence. A value held locally by the SQL function is unavailable to a deferred trigger at commit. The zero-net redistribution negative therefore remains unsupported by the specified mechanism.

**Replacement:** “Capture each category’s allocation under locks before applying deltas, and preserve protected SQL-visible baseline evidence bound to the amendment. Deferred validation rejects missing evidence and checks every final allocation against baseline plus approved delta, including zero-net redistributions.”

**N2R3-2 — BLOCKING — Function-only insertion assumes an unprovisioned privilege boundary.**  
§2.3, [A2:448](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:448). The note names application and migration roles without specifying their separation or provisioning. Current [test fixtures](/root/AIVORA/drama-box/microdrama/tests/conftest.py:42) migrate and run services through the same superuser DSN; [staging composition](/root/AIVORA/drama-box/microdrama/deployment/compose.staging.yaml:33) likewise uses the PostgreSQL bootstrap user. The proposed permission-denied negative cannot hold in that configuration. The new SECURITY DEFINER boundary also lacks a trusted search path.

**Replacement:** “Make a distinct non-superuser runtime role, without migration-owner membership, an explicit prerequisite. Specify ownership, grants and revocations so runtime INSERT is unavailable through every inherited grant. Use schema-qualified SQL and a pinned trusted search path in the definer function. Run boundary tests using that runtime role.”

**N2R3-3 — BLOCKING — Row-time bounds can reject a valid multi-step reduction.**  
§2.3, [A2:435](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:435). The BEFORE ROW guard combines exact matching with final aggregate bounds. Lower a setup cap from 100 to 50 and its two step caps from 50/50 to 25/25: whichever step updates first leaves an intermediate total of 75, so the guard rejects although the approved final total is 50.

**Replacement:** “Keep same-transaction, scope and exact approved-value checks in BEFORE ROW validation. Validate aggregate setup/production bounds against the completed amendment state using deferred AFTER ROW constraint validation. Verify all approved step values were applied. Test a cap reduction requiring several step reductions.”

**N2R3-4 — SHOULD-FIX — SQL hierarchy handling still differs from Python.**  
§2.3, [A2:414](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:414). Its final ELSE accepts any parentless account when no aggregate exists; Python correctly restricts that exception to SEASON_SETUP. The aggregate-account defect itself is fixed.

**Replacement:** “Allow a parentless non-SEASON account only when its kind is SEASON_SETUP and no SEASON account exists; otherwise raise detached-hierarchy corruption. Test this SQL path with a parentless V3 EPISODE account.”

**N2R3-5 — SHOULD-FIX — Service-credential refusal does not match the promised contract.**  
§6, [A2:881](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:881) promises `NotFound`, but `require_season_access` calls [owner_id_in_tx](/root/AIVORA/drama-box/microdrama/src/microdrama/core/auth.py:174), whose human-principal check raises `Unauthorized` for service credentials.

**Replacement:** “For both V3 Costs paths, explicitly map non-human service principals to NotFound before invoking the ownership helper or reading financial data. Preserve V1 authentication behavior and assert the exact response in authorization tests.”