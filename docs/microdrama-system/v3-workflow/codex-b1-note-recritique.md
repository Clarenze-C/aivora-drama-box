**Verdict: REWORK.** Reviewed v0.2 (`2669406`) against B1-1..12 and the binding documents. **10 CLOSED; 2 PARTIAL.** Read-only; no files changed or tests run.

1. **B1-1 — CLOSED.** [§2.2:163](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:163) freezes every column except `current`; the schema-version CHECK rejects missing/null/non-string values. Direct-SQL negatives are specified.

2. **B1-2 — CLOSED.** [§2.3:251](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:251) explicitly extends classification, generation, validation discovery and examples to `contracts.v3_story`, with V1/V2 isolation and frozen-byte assertions.

3. **B1-3 — PARTIAL — B1R2-1, BLOCKING: guard placement still leaves direct paths uncovered.** [§4:483–507](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:483) correctly adds observation/comparison entries, but:
   - `continuity_expectations` can return before either proposed helper guard ([continuity_sources.py:127](/root/AIVORA/drama-box/microdrama/src/microdrama/qa/continuity_sources.py:127)).
   - `load_reference_context` owns a transaction and directly interprets episode records; listing its module as having no guard leaves this entry uncovered ([v2_dispatch_context.py:204](/root/AIVORA/drama-box/microdrama/src/microdrama/references/v2_dispatch_context.py:204)).
   - `route_shot` has no caller transaction; persistence opens a separate transaction later. `persist_document(tx, record)` has no explicit episode/season scope.
   
   **Replacement:** “Guard `V2RecordContinuityExpectations.continuity_expectations` and `load_reference_context` inside their entry transactions, before legacy-document reads or early returns. Entry methods without `tx`, including `route_shot`, open an explicit workflow-check transaction before interpretation/effects. Give generic persistence entries an explicit, ancestry-validated scope. The shared fixture tests direct calls with V3 episodes lacking legacy documents, alongside worker paths.”

4. **B1-4 — PARTIAL — B1R2-2, SHOULD-FIX: extension-scope verification remains undefined.** [§4:458](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:458) fixes version selection and fallback, but requires checking `planning_scope_id` “against the binding”; [§2.6:353](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:353) stores no such column. Comparing it with `season_id` would reject extension packs.
   
   **Replacement:** “Resolve the expected planning scope through the binding’s STORY LOCK approval: its `extension_id`, when present, otherwise its season ID. Verify approval/episode/extension ancestry and range, binding season and episode number, then compare the pack’s scope and number. Any mismatch fails without fallback. Test both season and extension bindings.”

5. **B1-5 — CLOSED.** [§7:598](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:598) defines one outer transaction and a shared caller-transaction creation helper; [§8:637](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:637) explains the new-row creation exception.

6. **B1-6 — CLOSED.** [§2.4:295](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:295) persists frozen intake/generation provenance in inputs and proposal records. [§6:563](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:563) supplies all five round-allocation rules and specifies recovery/collision coverage.

7. **B1-7 — CLOSED.** [§5 D2:522](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:522) pins lowercase wire values, requires the LOCK Approve target, rejects unsupported decision targets and validates targets against recomputed binding units.

8. **B1-8 — CLOSED.** [§7:601](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:601) specifies durable tier/document changes, binding rebuild, atomic supersede/reopen and exactly one revision advance without a content-fence bump.

9. **B1-9 — CLOSED.** [§3:435](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:435) individually disposes of the omitted scene/beat fields; [§2.3:206](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:206) and the DDL consistently retain validity windows.

10. **B1-10 — CLOSED.** [§7:598–615](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:598) adopts A2’s exact creation event, names/registers `intake.replaced`, and states revision/replay effects.

11. **B1-11 — CLOSED.** [§6:574](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:574) pins startup handler availability passed into `claim`, exclusion before candidate locking, preserved legacy behavior and the requested skip/install tests.

12. **B1-12 — CLOSED.** [§2.5:333](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:333) defines canonical encoding, calculated hashes, immutable conflict comparison, read-time verification and pinned prompt resolution.