**REWORK.** Reviewed [B5 v0.1](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B5-design-note.md) at `e8849ef`; the current file matches that version. Read-only; no tests run.

1. **B5-1 — BLOCKING: binding hash conflicts with B1’s record sealing.**  
   §2.1, lines 193–211 makes `content_sha256` hash only the member preimage. B1 §2.3 requires the inherited whole-record hash, including identity, version and timestamps. The actual `V2Record` implementation confirms this at `contracts/v2.py:66–68`. B5’s proposed value would fail the store’s hash verification.  
   **Replacement:** “`content_sha256` retains B1’s whole-record sealing rules. A separate `binding_sha256` hashes the explicitly typed member preimage using the shared canonical encoder. Activations and C consume that binding hash; document-reference triples retain the document content hash.”

2. **B5-2 — BLOCKING: extension authorities and calendar lack a defined durable home.**  
   §5.3 puts pinned authorities in job inputs, but §5.2’s authorization has no authority/calendar fields, and A1’s `season_extensions` has none either. Nothing defines a scope-owned snapshot against which later job inputs can be checked. OQ-4 also proposes replacing the CAST sentinel when C registers, contradicting frozen authority.  
   **Replacement:** “Creation atomically persists an immutable extension-context snapshot containing the authorization, explicit calendar input and every pinned authority. All extension jobs reference and validate that snapshot. CAST is an exact approved reference when available, otherwise an explicit absent sentinel; deployment of C never rewrites an existing snapshot.”

3. **B5-3 — BLOCKING: the initial extension document set is incomplete.**  
   §2.1 requires `seam:<extension>`, while §5.4 merely says an extension *may* carry its own seam revision. Creation starts directly at `BIBLE` and immediately plans episodes; no step creates the required seam. Only the bible has a specified fallback. Initial extension finalization therefore has an unresolved required-member read.  
   **Replacement:** “Before the first extension planning enqueue, persist the extension’s initial seam from the pinned predecessor seam, with source provenance. Define the effective bible/profile resolution explicitly; scoped revisions supersede only extension-local documents. Prior documents remain untouched.”

4. **B5-4 — BLOCKING: authorization matching is weaker than the authority being claimed.**  
   §5.3 checks authorization ID, episode coverage and openness, but does not enumerate agreement with season ancestry, the scope’s exact range, cumulative count or pinned predecessor. The DDL permits `cumulative_episode_count > episode_end`, despite §5.1 defining equality. §5.5’s generic “re-validated” leaves the approval predicate unspecified.  
   **Replacement:** “Enqueue, dispatch and approval verify season/extension ancestry, exact scope-range equality, cumulative count equal to `episode_end`, predecessor contiguity, amendment-account identity and snapshot agreement. Approval requires exactly the authorized pack-number set. Admission also validates the authorized planning state/round; openness alone grants no regeneration authority.”

5. **B5-5 — BLOCKING: the critic’s transaction boundary includes a resumable external call.**  
   §1, lines 90–104 places all handler steps inside one caller transaction, including `LlmStep`. D5 is the **completion** transaction; A0’s step protocol commits durable intent before submission and can return waits across executions. The failure paragraph also calls malformed-output attempts “repair rounds,” risking consumption of the separate episode-repair budget.  
   **Replacement:** “Run the resumable `LlmStep` protocol outside the D5 completion transaction. On valid completion, acquire season track then extension track when applicable, validate fence/lease and frozen inputs, persist outputs, finish and evaluate the join atomically. Preserve A0’s wait/defer/block/reconciliation/lease-loss mappings. Content retries retain the critic round and episode-repair counters.”

6. **B5-6 — BLOCKING: extension input changes and the first driver need an explicit contract delta.**  
   §5.3 requires authorization and authority references absent from B1 §6’s registered input shapes. Existing contract models reject unknown fields. OQ-1 simultaneously leaves the first enqueue unresolved while §8 already mandates it and §0 declares no deviations.  
   **Replacement:** “Register the typed extension-context additions to every affected B1 input model, including conditional validation and regenerated schemas/examples. Resolve OQ-1 before acceptance: adopt the atomic first enqueue and explicitly amend the inherited `J: none` row through D6. Record this as a deliberate delta.”

7. **B5-7 — SHOULD-FIX: pin the binding document’s address across the approval fence bump.**  
   Finalization writes `story-lock:<scope>:<content_revision>` before approval; approval then increments that fence. Neither §2.1 nor §3 tells C or a later extension how to resolve the approved document after that increment.  
   **Replacement:** “Downstream resolution follows the approved activation’s pre-approval content revision and exact bound document version/hash. It never constructs the record address from the subsequently incremented track fence or selects an unqualified current version.” Add an approval→C-reader→extension-pin test.

8. **B5-8 — SHOULD-FIX: complete the callback/command audit, especially tier-only Revise.**  
   §8 lists three commands, and §9 omits the Revise transaction. The shared tier operation must not perform the standalone command’s revision bump during `on_decision`. A1 invokes that callback **before** its sole revision advance; no post-advance callback exists there.  
   **Replacement:** “Add scoped rows for STORY LOCK Approve/Revise/Reject and both finalization entries, inheriting A1’s common events/replay rules and enumerating B5’s jobs/writes/locks. Tier-only Revise persists its update without bumping or opening, then enqueues the human-revise critic continuation in the decision transaction; later finalization opens the successor after the decision commits.”

The main STORY LOCK structure is otherwise aligned: the normative order is **phase-A §6 / A1 §9**, not A1 §7. Initial approval creates all N legacy-`PLANNED`, empty-plan episodes, tracks, accounts and binding rows atomically; packs remain byte-unchanged. Episode and originating scope fences are correctly distinguished. Finalization opens STORY LOCK **after** `BIBLE → PLANNED`; Approve opens no further activation. Inserts after budget work are not themselves an inversion, provided they acquire no new conflicting existing-domain locks.

The extension’s `BIBLE → PLANNED → STORY_LOCKED` edges, appended-only creation, existing-hierarchy reuse, rollback and extension-only track advance match phase-B §8. Keep the funding predicate and production-step treatment explicitly provisional against parked A2 OQ-2/OQ-3.

The season prompt’s ownership, registration, canonical text hash and pinned lookup match B1. Its three call sites match phase-B; B5-5 is the missing execution/failure boundary.

After these fixes and accepted prerequisites, **B5 can independently satisfy B-T7 through B-T11 without C/E/F implementations**. Correctly deferred: C’s casting/forecast/image-volume work; E’s delivered captions; F’s real published-canon source, extension decision screen, viewership windows and calendar semantics. Synthetic canon proves only B’s extension mechanics.