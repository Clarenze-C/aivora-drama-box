**Verdict: REWORK.** Reviewed B1 v0.1 (`b3343a8`) against the binding documents and current code. Read-only; no files changed or tests run.

1. **B1-1 — BLOCKING: the document DDL does not enforce its immutability claim.**  
   [Lines 149–156](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:149) freeze identity columns but leave `payload`, `content_sha256` and `planning_scope_id` mutable. `md_immutable_columns` checks only its named arguments. The schema-version CHECK also passes SQL NULL when the payload lacks that field.  
   **Replacement:** “Only `current` may change on an existing document row. Freeze payload, hash, scope and all identity/timestamp columns. Require an explicitly present JSON string `schema_version = "3.0"`; missing, null and non-string values fail. B1 tests these through direct SQL.”

2. **B1-2 — BLOCKING: the new module is outside A1’s specified schema classification.**  
   [Lines 174–224](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:174) introduce `contracts.v3_story`, but A1 §4 extends generation specifically for models in `contracts.v3`. The current classifier falls back to V1 for other modules; extending the manifest loop alone does not fix this.  
   **Replacement:** “B1 explicitly classifies every model defined in `contracts.v3_story` as V3, registers its models/examples/negatives, and extends validation discovery. Assert that no B1 model or example appears under V1/V2 and that their frozen artifact bytes remain unchanged.”

3. **B1-3 — BLOCKING: the guard inventory cannot be implemented as written.**  
   [Lines 392–402](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:392) name several pure functions without a transaction, while `RoutingPolicy` is configuration; the actual routing entry is `ShotRouter.route_shot` (`rendering/routing.py:279`). Contrary to the claimed re-verification, `ObservationService.observe_media` and `ComparisonService.compare` read databases and can perform effects; they are not pure helpers (`qa/observation.py:366`, `qa/comparison.py:642`).  
   **Replacement:** “Pin an exact callable and available transaction/workflow context for each consumer. Preserve pure helpers behind explicit guarded boundaries. Cover direct observation/comparison service entry points as well as worker dispatch; only `coverage.py` qualifies for the stated pure-helper treatment. Enumerate binding/dispatch modules separately in the shared fixture.”

4. **B1-4 — BLOCKING: workflow version cannot select all three reader variants.**  
   [Lines 377–384](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:377) resolve V1/V2/V3 through `seasons.workflow_version`, but A1’s enforced vocabulary is only `v1`/`v3`; historical V2 packs belong to the legacy partition. The V3 binding lookup is also unspecified.  
   **Replacement:** “For `v3`, select the binding at the episode track’s current `content_revision`, then load and verify its exact pack ID/version/hash and scope/episode number. For `v1`, explicitly select a qualifying V2 pack when present, otherwise the V1 plan/script. A corrupt selected V2/V3 record fails; it never triggers fallback.”

5. **B1-5 — BLOCKING: intake composition conflicts with A2’s transaction ownership.**  
   [Lines 478–485 and 511](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:478) put `submit_v3_intake` inside `execute`, then call `create_v3_season`. Accepted A2 §7 defines that command as owning its own `execute` transaction. No caller-transaction creation helper is pinned. The blanket lock-order verdict also crosses setup-budget creation before document/job writes without explaining the new-row exception.  
   **Replacement:** “One outer intake idempotency transaction owns season creation, ownership, setup state, intake, generation identity and proposal enqueue. Define a shared caller-transaction creation helper; the existing A2 command delegates to it without nesting `execute`. Audit the complete outer sequence, distinguishing new-row inserts from locks on existing rows.”

6. **B1-6 — BLOCKING: generation identity is not durably linked to the records and replay inputs it governs.**  
   [Lines 226–254 and 446–464](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:226) define a mutable scope counter but no intake-version/generation linkage on `ProposalRoundV3`. The key formulas require a round for profile work, while `PromoteProfileStepInput` has none. Later scoped bible/profile generations also lack a pinned round-allocation rule. `core/jobs.py:429–438` rejects same-key/different-input replay; it does not repair these ambiguities.  
   **Replacement:** “Persist each generation’s exact intake reference `(id, version, sha)`, generation identity and applicable work round, and link produced proposal rounds to them. Specify round allocation for all five job types. Recovery reuses frozen inputs and identity; intentional new work gets a fresh attempt key. Test changed-input collisions, replacement intake, terminal retry, and retention of successful siblings.”

7. **B1-7 — SHOULD-FIX: D2 names enum members without pinning their wire values or target admissibility.**  
   [Line 425](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:425) lists uppercase kinds, whereas A1 §4 serializes existing kinds as lowercase values. Adding an optional field also does not enforce “absent for A1’s existing gates.”  
   **Replacement:** “Add explicit serialized values (`proposal`, `episode_plan`, `bible_section`, `seam`, `tier`) beside unchanged existing values. Require the proposal target for LOCK Approve; reject non-null decision targets on unsupported gate/action combinations. Validate decision and note targets against recomputed binding units.”

8. **B1-8 — SHOULD-FIX: `edit_tier` closes and reopens gates without specifying durable content changes.**  
   [Lines 488 and 514](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:488) omit tier/profile persistence, revised demand/critic/binding records, and revision advancement. Revalidation reads alone cannot make the edit durable.  
   **Replacement:** “Under owner access, workflow/cancellation and expected-revision checks, persist the tier change and affected document versions, rebuild the binding, supersede the old activation, advance the scope revision once, and open its successor with final revisions—all atomically. No `content_revision` bump.”

9. **B1-9 — SHOULD-FIX: the ‘every field’ mapping is incomplete.**  
   [Section 3](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:314) does not individually dispose of `EpisodeScene.scene_number` or `PackBeat.function`, `visible_action`, `proof_object_ids`, `dependency_beat_ids`, `state_in/out`, `required_asset_ids`, and `reveal_ids`. The envelope mapping promises preserved validity-window semantics, while §2.3 omits those fields.  
   **Replacement:** “Map or explicitly drop every listed source field, including nested fields and inherited envelope fields. Pin whether V3 retains `valid_from`/`valid_until`; make the model definition and mapping agree.”

10. **B1-10 — SHOULD-FIX: command events conflict with accepted A2.**  
    [Line 485](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:485) repeats A1’s older `season.created_v3`/`track.created` set. A2 v1.3 §7 explicitly replaces creation with exactly one `season.created {season_id, workflow_version}` event. “Intake-replacement event” is also not a concrete event contract.  
    **Replacement:** “Use A2’s exact creation event once; matching replay emits none. Name and register the intake-replacement event and payload. For every command, state revision effects and same-key/different-parameters refusal explicitly.”

11. **B1-11 — SHOULD-FIX: claim filtering needs a concrete runtime contract.**  
    [Lines 466–474](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:466) do not explain how `JobService.claim` receives deployment handler availability; its current signature has no such input.  
    **Replacement:** “Pass an immutable deployment handler-availability set into claim and exclude unavailable B1 types before candidate row locking. Preserve legacy unknown-handler behavior. Test an unavailable head candidate followed by runnable work, unchanged attempts/events for skipped jobs, and claimability after handler installation.”

12. **B1-12 — SHOULD-FIX: prompt hash verification is implicit.**  
    [Lines 277–285](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:277) specify text comparison but not calculation/verification of `text_sha256`.  
    **Replacement:** “Define canonical text encoding and calculate its SHA-256 at registration. Compare the complete immutable registration on conflict; verify text/hash agreement on lookup. A frozen call resolves its pinned prompt identity/hash without choosing the latest version.”

The symbolic B-1…B-4 purposes and dependency order are reasonable, subject to the build-time tail audit. D1, D3–D5 and D6’s registration approach otherwise align; D2 can be a contract/schema migration without an empty SQL file.

The independent prompt table correctly preserves V2 `PromptManifest` and storage. The limits and neutral-voice decision match the accepted rules. B1 alone gates **B-T1/B-T2**, plus the mandatory `make check` and V1 `make pilot`; B-T3 onward remain preparation only. D5 correctly ships in **B2**, with B3 consuming it.