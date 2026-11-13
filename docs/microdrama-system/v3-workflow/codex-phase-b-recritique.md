**Verdict: REWORK.** Eleven findings are closed; four are partial; PB-14 introduces an authority regression. The accepted architecture remains unchanged.

Reviewed the exact `cb8f8b5` spec blob against the current runtime and binding documents. A2 is still v1.0 in this checkout; its in-flight v1.1 was unavailable. Read-only static review; no writes or tests.

`B:line` below means [phase-B-spec.md](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-B-spec.md).

| Finding | Status | Evidence / remaining issue |
|---|---|---|
| PB-1 | **PARTIAL** | §2.4 D5 and §7.1 now specify the correct atomic completion contract, successful-member join, and suppression of runtime’s second finish. Its delivery starts too late: B:217, 258–263, 681–684. **PB5-2**. |
| PB-2 | **CLOSED** | §2, §5.2, §7.1 (B:96–105, 418–422, 539–551): fresh execution keys, stable logical work, replacement links, retained successes and transport identity address `core/jobs.py:429` replay matching. |
| PB-3 | **PARTIAL** | §3.2/§5.2 ordering is corrected, including retaining `PLANNED` after Revise. Fresh-intake round 1 still repeats the initial proposal transition: B:258–263, 655. **PB5-3**. |
| PB-4 | **CLOSED** | §5.1/§5.2/§5.5 (B:378–405, 421–422, 465–475): persisted authorization, bounded automatic repair, retained counters and post-Revise reporting address the original finding; B-T7/B-T10 cover it. |
| PB-5 | **CLOSED** | §4.2/§5.3/§9 (B:320–333, 431, 653): standalone entry requires/supersedes the open activation; decision-context entry does neither. Successor activation follows the decision revision advance; B-T10 uses the real route. |
| PB-6 | **CLOSED** | §7.3 (B:584–598): separate asset-independent registry; V2 `PromptManifest` and storage unchanged. Bible/episode/season critic prompts now ship with B3/B4/B5. |
| PB-7 | **CLOSED** | §5.3/§8 (B:430, 637–644): explicit B5 extension branch, appended children only, existing hierarchy reused, extension track advanced, rollback covered. B5 owns the detailed extension edges. |
| PB-8 | **PARTIAL** | §8 adds immutable count authorization correctly (B:619–628). Amendment qualification remains underspecified, and B-T11 makes the newly created authorization a creation prerequisite. **PB5-4**. |
| PB-9 | **CLOSED** | §5.4/§8 (B:454–459, 629–635): continuity authority is hash-bound; extension inputs pin prior approvals and exact terminal/published canon. No unqualified latest-row authority remains. |
| PB-10 | **CLOSED** | §2.1/§5.4 (B:132, 444–453): distinct episode and lock-scope fences; immutable pack bytes; immediate compatibility-reader coverage in B-T9. |
| PB-11 | **CLOSED** | §3.3/§5.3 (B:273–279, 428–436): common prerequisites stay in `conditions`; Approve blockers run in the rollback callback. B-T10 preserves Revise/Reject with CRITICAL findings. |
| PB-12 | **PARTIAL** | Typed effects, derived seam status and explicit growth reservation are present (B:118, 137, 515–526). The debt-model description contradicts the actual V2 contracts. **PB5-5**. |
| PB-13 | **CLOSED** | §4.1/§4.3/§5.2 (B:291–294, 337–340, 407–410): staged populations and post-promotion deterministic revalidation are explicit; B-T8 covers missing promoted-speaker data. |
| PB-14 | **REGRESSED** | §9 introduces re-entry commands without sufficient lifecycle prerequisites; extension reopening also names the wrong revision owner (B:655–656). **PB5-1**, plus PB5-3. |
| PB-15 | **CLOSED** | B-T5 (B:700) is implementable: restricted planning connections, denial controls, pre-execution capture including failures, and fixture-only emptiness checks. Capture must sit below all SQL entry points; controls run outside the measured planning interval. |
| PB-16 | **CLOSED** | §3.2 (B:247–253): B2 explicitly owns a V3 projection/sibling with mapped fields and verdict behavior; no legacy `SeasonScope` construction. |

**PB5-1 — BLOCKING — Re-entry commands need lifecycle guards and the correct extension revision.**  
§9, [B:655](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-B-spec.md:655).

The listed prerequisites permit intake replacement beyond a rejected concept scope and reopening during regeneration. Those paths can change planning authority outside the amendment protocol or expose a gate before authorized work completes. Additionally, extension commands must compare `season_extensions.revision`, per A1 §5 step 2 and §6; `season_tracks.revision` is not their command revision.

**Replacement:** “`replace_v3_intake` requires an uncancelled V3 season in `PROPOSED`, whose latest concept activation was REJECTED, with no open activation or unfinished proposal work. `reopen_v3_gate` requires the requested gate’s rejected scope, its appropriate planning state (`PROPOSED`/`PLANNED`), and completed required work. Both enforce owner scope, session/CSRF and idempotency. Expected revision belongs to `season_tracks` for season scope and `season_extensions` for extension scope.” Add refusals after Approve, during Revise regeneration, and for stale extension revisions.

**PB5-2 — SHOULD-FIX — Ship the completion seam before the first gate-producing handler.**  
§2.4 D5/§11, [B:217](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-B-spec.md:217).

B2 already opens LOCK inside the proposal handler. Without the seam until B4, the job remains RUNNING until [runtime.py:250](/root/AIVORA/drama-box/microdrama/src/microdrama/workers/runtime.py:250), contrary to §1.7; death between gate commit and finish leaves inconsistent progress.

**Replacement:** “Implement D5’s completion/runtime integration by B2 and use it for proposal completion plus LOCK opening. B3 uses it for bible completion plus continuation; B4/B5 add joins.” Include the B2 commit-boundary crash case.

**PB5-3 — SHOULD-FIX — Fresh intake must not repeat `IDEA → PROPOSED`.**  
§3.2, [B:258](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-B-spec.md:258).

After Reject, planning already remains `PROPOSED`. `replace_v3_intake` resets the displayed round to 1, which currently triggers `advance_planning(PROPOSED)` again. A1 §6 defines forward edges, not a `PROPOSED → PROPOSED` edge.

**Replacement:** “Advance `IDEA → PROPOSED` only for the scope’s initial proposal completion. Fresh-intake and Revise completions retain `PROPOSED`; then open the activation at the final revision.” Exercise this through B-T3’s real replacement route.

**PB5-4 — SHOULD-FIX — Separate authorization creation from its downstream enforcement.**  
§8/B-T11, [B:619](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-B-spec.md:619), B:706.

`create_extension` creates the authorization atomically, yet B-T11 requires it to refuse without an already persisted authorization. “Qualifying amendment” also needs an enforceable definition.

**Replacement:** “The command names the amendment ID and validates that it belongs to this season’s `SEASON` account and funds the requested count under phase-A §5.4; then it atomically creates the authorization and extension. Builder admission and STORY LOCK approval refuse missing or mismatched authorization. Count comes exclusively from the authorization.” Test wrong-account/season and insufficient amendments, creation rollback, and downstream missing-authorization refusal.

**PB5-5 — SHOULD-FIX — Correct the debt schema attribution.**  
§2/§2.1, [B:121](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-B-spec.md:121).

V2 [PayoffDebt already has `debt_id`](/root/AIVORA/drama-box/microdrama/src/microdrama/contracts/v2.py:206). The free-text field is [EpisodePack.payoff_debt](/root/AIVORA/drama-box/microdrama/src/microdrama/contracts/v2.py:361), still reused at B:142.

**Replacement:** “Reuse the ledger’s existing stable `PayoffDebt.debt_id`. V3 pack debt references use those IDs; any retained prose is display-only. Outstanding debt and seam status derive from the bound ledger plus typed settlement effects.” Keep V2 unchanged and test unknown debt references.