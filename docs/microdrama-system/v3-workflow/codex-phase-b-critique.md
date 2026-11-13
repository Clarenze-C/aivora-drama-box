**Verdict: REWORK.**

The main choices are sound: separate V3 documents and validators preserve V1/V2; `step_01..03` match A2; stable `logical_work_id` plus replacement links match A1. Extending `RevisionTargetKind` and adding an optional typed decision target is A1-compatible as a B1 delta, preserving existing command validation. Correctly, v0.4 no longer claims a SQL CHECK enforces note-target kinds.

The remaining problems concern completion, recovery and authority. References below are to [phase-B-spec.md](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-B-spec.md), unless another file is named.

**PB-1 — BLOCKING — §7.1, lines 471–475: the completion transaction does not exist.**

The idiom requires the completing job to be `SUCCEEDED` inside its own transaction. The actual runtime calls the handler first and finishes afterward ([runtime.py:245](/root/AIVORA/drama-box/microdrama/src/microdrama/workers/runtime.py:245)); `finish()` opens another transaction ([jobs.py:676](/root/AIVORA/drama-box/microdrama/src/microdrama/core/jobs.py:676)). A3 explicitly retains job-only `finish`. Checking before finish loses the last completion; independently finishing while holding its job lock can block. Also, “every sibling terminal” admits failed or cancelled siblings.

**Replacement:** “B owns a caller-transaction completion seam. It takes the scope track FOR UPDATE before job locks, validates fence and lease, persists outputs and successful completion, and evaluates the join over the persisted required members. Finalization requires every required member’s current successful output. Continuation/gate creation commits atomically; runtime does not finish the job again.” Register this delta and test concurrent completions and process death at the commit boundary.

**PB-2 — BLOCKING — §2 Identity; §5.2 Resume; §7.1: round keys cannot implement the promised recovery.**

Re-enqueuing a terminal failed job with the same round key returns that failed job; it does not retry it ([jobs.py:429](/root/AIVORA/drama-box/microdrama/src/microdrama/core/jobs.py:429)). Conversely, resetting the proposal round after Reject reuses `propose:<scope>:1`, and proposal IDs also repeat across intakes.

**Replacement:** “Persist a monotonically increasing generation-round identity per scope, separate from the displayed per-intake round. A terminal-failure retry creates a replacement job with a fresh execution-attempt key and unchanged `logical_work_id`; successful members are retained. Transport recovery retains the existing call identity. Proposal identities include the intake version or generation-round identity.” Add failed-round retry and Reject → fresh-intake cases.

**PB-3 — BLOCKING — §3.2, lines 236–238; §5.2, lines 354–356: activation ordering can invalidate the new gate.**

Both sequences open the activation before advancing planning. A1 §5 compares the activation’s decision revision with the current track revision; a subsequent transition bump makes the activation stale. Repeating §5.2 after Revise also attempts `BIBLE → PLANNED` when planning is already `PLANNED`.

**Replacement:** “Complete the initial planning transition and its revision changes before opening the activation. Stamp the activation with the final revisions. Re-finalization retains `PLANNED` and opens a fresh activation without repeating the initial edge.”

**PB-4 — BLOCKING — §5.1, §5.2, §5.3 and §5.5: automatic repair can exceed scoped Revise authority.**

A human Revise eventually invokes the same season critic that automatically repairs named packs and successors. That can silently regenerate the invalid dependents §5.5 requires the operator to authorize. `plan_episode` also unconditionally enqueues episode *n+1*, conflicting with a scoped repair’s stopping point.

**Replacement:** “Persist each round’s origin and authorized episode set. Initial automatic repair may expand within the persisted two-round, six-episode limits. After human Revise, the critic reports newly invalid dependents without regenerating them. Episode continuation follows the round’s authorized membership rather than unconditionally proceeding to *n+1*. Retry does not reset repair counters.” Test six versus seven affected episodes and the post-Revise prohibition.

**PB-5 — BLOCKING — §5.3, line 370; §9, line 540: tier-targeted Revise calls a command whose prerequisite is already false.**

A1 §5 step 7 closes the activation before `on_decision`. The Revise callback then routes to `edit_tier`, which requires an open activation and supersedes it. This path fails or attempts a second terminal activation event.

**Replacement:** “The standalone tier command requires an open activation. Tier-targeted Revise invokes a shared internal tier-update/revalidation operation under the existing decision context; it neither requires nor supersedes the closed activation. Finalization opens the successor activation after the deciding transaction’s revision advance.” Exercise this through the real decision route in B-T10.

**PB-6 — BLOCKING — §7.3, line 501: the referenced `PromptManifest` is the wrong contract.**

The existing [PromptManifest](/root/AIVORA/drama-box/microdrama/src/microdrama/contracts/v2.py:773) describes a render shot. It requires an episode, shot, duration and asset bindings; its validator requires identity, outfit and location references. It cannot register an intake/bible prompt before episodes or assets exist, and using its V2 store contradicts §1.2 and B-T5.

**Replacement:** “B1 defines an asset-independent LLM prompt registry with prompt ID, version, canonical text and SHA-256. Every frozen B call references it. The V2 render `PromptManifest` and V2 storage remain unchanged.”

Also move the **bible critic prompt to B3** and the optional **episode critic prompt to B4**. Their calls and acceptance cases precede B5; only the season critic prompt belongs in B5.

**PB-7 — BLOCKING — §5.3 and §8: extension approval cannot reuse the initial STORY LOCK creation path unchanged.**

A2 §4 creates the unique `SEASON` account, attaches setup exposure and creates the initial episode accounts. An extension already has that hierarchy, and its base cap is immutable. B also does not specify how the new extension track reaches the builder’s and gate’s required planning states.

**Replacement:** “B5 supplies an extension-aware STORY LOCK branch, scoped by `extension_id`. It defines the extension planning edges, creates only the contiguous appended episode range and its tracks/accounts/bindings, reuses the existing budget hierarchy, and advances only the extension planning track. Existing season tracks, accounts, approvals and episode rows remain unchanged.” B-T11 must run through extension approval, including rollback.

**PB-8 — BLOCKING — §6.2, lines 444–445; §8, lines 524–525: A2’s monetary amendment has no approved episode count.**

A2’s `account_cap_amendments` records money, category/step deltas and human provenance. It has no episode count or range. Consequently, “the amendment’s count” and “covers the new count” have no enforced meaning.

**Replacement:** “Persist an immutable authorization linking the exact appended range and cumulative episode count to the qualifying SEASON budget-amendment ID and human command. Extension count validation uses that authorization; it never infers an approved count from a monetary cap.”

**PB-9 — BLOCKING — §5.4, lines 383–385; §8, lines 528–530: the binding omits a later source of story authority.**

Standalone `ContinuityStateV3` records are not in the STORY LOCK hash, yet extension planning consumes the “last stored” state as planned-terminal canon. Changing that current state need not change the prior lock binding. Extension inputs also lack pinned prior CAST authority and published-canon identities required by master §4.3.

**Replacement:** “STORY LOCK binds exact ID/version/hash references for continuity states, or verifies a specified deterministic derivation from the bound packs. Extension scope records pin prior STORY/CAST authorities and exact planned-terminal/published-canon references. The builder consumes those pinned references, never an unqualified latest row.”

**PB-10 — SHOULD-FIX — §5.4, lines 379–382: distinguish episode and season fences.**

The binding lookup uses the episode’s current `content_revision`, whereas STORY LOCK bumps the season or extension fence. A1’s new episode tracks default to revision zero. The binding column’s intended fence is unspecified.

**Replacement:** “`v3_episode_story_bindings.content_revision` is the episode track’s fence value. Store the originating STORY LOCK scope revision separately. Approval does not reseal or modify the approved pack to add its episode ID.” B-T9 should immediately read every newly created episode through the compatibility reader.

**PB-11 — SHOULD-FIX — §5.2 and §5.3: Approve-only blockers need an A1-compatible placement.**

A1’s `conditions(tx, binding)` receives no action and is invoked before **every** decision. Putting CRITICAL findings or budget-attach blockers there prevents Revise and Reject, defeating the deliberately open gate.

**Replacement:** “Handler `conditions` contains common decision prerequisites only. Approve-specific blockers are checked at the start of the Approve callback, within the same rollback transaction.” Alternatively, register an explicit action-aware protocol delta. Test that an open CRITICAL disables Approve while Revise and Reject remain usable.

**PB-12 — SHOULD-FIX — §2.1; §6.2, lines 437–447: deterministic predicates still lack machine-readable evidence.**

Beats contain prose, line IDs and secret reveals, but no outfit-change authorization or payoff-resolution references. The reused V2 pack’s `payoff_debt` is a list of text ([v2.py:361](/root/AIVORA/drama-box/microdrama/src/microdrama/contracts/v2.py:361)). A seam status alone does not define how pack resolutions update it; “reserved further growth” has no declared field.

**Replacement:** “Define typed beat effects for wardrobe changes and payoff settlements, with stable subject/debt IDs. Derive continuity and seam status from those effects, and represent further-growth reservation explicitly. Deterministic checks consume these fields.” Test the derivation, beyond injecting a pre-labelled `RESOLVED` status.

**PB-13 — SHOULD-FIX — §4.1; §5.2; §6.1: validation runs against incomplete or outdated populations.**

The bible critic demands ledger-to-pack binding before packs exist. Conversely, the season’s final pack recheck precedes promotion, although promotion changes the supporting-character population and its required psychology/profile fields.

**Replacement:** “Bible-time validation checks the available bible, ledger and LOCK authority. Pack cross-validation runs after planning. After promotions complete, finalization re-runs deterministic checks against the effective profiles and tiers before deriving demands and opening the gate.” Add a newly promoted speaker with missing psychology/profile data.

**PB-14 — SHOULD-FIX — §3.3 Reject; §5.3 Reject; §9 intake: the promised re-entry path is missing.**

Reject closes the activation. “Revise later” therefore needs a new activation, but B names no operator command that requests one. The intake command always calls `create_v3_season`, so it also does not implement a fresh intake on the rejected scope.

**Replacement:** “Define existing-season intake replacement and explicit gate-reopen commands, with owner/session/CSRF, expected revision and idempotency checks. They preserve prior decisions and append new content/activations.” Cover Reject → reopen → Revise at both gates.

**PB-15 — SHOULD-FIX — B-T5, line 585: restricted privileges prove less than ‘no access attempted’.**

A correctly restricted role proves forbidden direct access cannot succeed. A query can still be attempted, denied and caught while the overall run completes.

**Replacement:** “Run every planning connection under the restricted role, verify denial with negative controls, and capture attempted SQL at the database-access boundary, including failed statements. Assert zero forbidden-table attempts during planning; assert empty table families separately using the fixture connection.” This makes the stronger AT-18 evidence claim real.

**PB-16 — SHOULD-FIX — §3.2, lines 230–233: originality screening needs a V3 input adapter.**

`screen_concept` accepts `ConceptDraft.scope: SeasonScope` and reads legacy arc/character fields ([originality.py:75](/root/AIVORA/drama-box/microdrama/src/microdrama/research/originality.py:75)). A V3 proposal is not that shape; constructing a legacy scope introduces the frozen legacy duration and required-field contracts.

**Replacement:** “B2 defines a V3 screening projection or sibling over the existing pure token-comparison helpers, with an explicit proposal-field mapping and BLOCKED/FLAGGED/UNKNOWN behavior. It does not manufacture a legacy `SeasonScope`.”

B-T1/B-T2 provide a coherent basis for AT-19. AT-3, AT-4 and AT-18 still need the completion, recovery, final-validation and query-attempt cases above. The ≤2-speakers-per-beat interpretation is sound provided D enforces the stated no-cross-beat-merge rule.

Read-only static review; no files changed and no tests executed.