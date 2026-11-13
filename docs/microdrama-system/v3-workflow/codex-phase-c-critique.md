**Verdict: REWORK.** v0.2 addresses the former omissions, but several contracts remain inconsistent enough to block implementation.

References below use `C` for [phase-C-spec.md](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-C-spec.md); code paths are relative to `microdrama/src/microdrama/`.

The former blockers are **partially resolved**:

- **BLK-1:** three ordinary jobs per root, one candidate per job, and `<gen_seq>` are clear and compatible with “votes start no work.” The setup-approval trigger still conflicts with A2.
- **BLK-2:** the mapping and namespace prefixes are sensible, and `seasons.workflow_version` is the correct discriminator. SQL growth alone does not make the existing typed writers/readers compatible.
- **Crossings:** CD1 and CD3 identify the appropriate changes; CD2 misses typed contracts, CD4 misses a view filter, and CD5’s fallback makes the structured field non-blocking.
- **Packages:** the C9/C9b split and C8’s note-first placeholder are appropriate. Most test placement is improved; C-T14a still includes a future-package condition.

**PC-1 — BLOCKING — Initial generation depends on a setup approval that may already have happened.**  
**C:73–76, 251–264, 591.** A2 §5 makes `approve_setup_budget` a one-time amendment from effective cap zero, funding **steps 1–4**. With paid B calls, approval necessarily precedes STORY LOCK and C’s demand derivation. Approval then finds no cast items; approving again at step 4 is refused. Assigning derivation and transition ownership to C2/C4 does not establish their invocation.
**Replacement:** “A common idempotent entry helper runs after setup approval and after STORY LOCK. Once both authorities exist, it derives items and the forecast, advances the applicable planning scope to CASTING, and enqueues each initial root’s three jobs exactly once. Votes never invoke this helper.”

**PC-2 — BLOCKING — BLK-2’s SQL extension leaves incompatible Python contracts.**  
**C:133, 139–179, 303–304, 482–483.** `RefKind` aliases the five-value `IdentityAssetKind` (`references/models.py:27`). `AnchorSpec` rejects `PROP`/`EXTRAS_LOOK`; existing lock readers cast member kinds through that enum (`references/service.py:228,397`). `IdentityLock` and `LockView` also require the two fields C makes nullable (`contracts/season.py:489–492`; `references/models.py:122–125`).
**Replacement:** “CD2 includes V3 reference-kind, lock-body and lock-view contracts plus workflow-aware readers/builders. V1/V2 schemas and validation remain unchanged. C-T1 exercises every new kind and a V3 lock with NULL source/package fields through the actual typed paths.”

**PC-3 — BLOCKING — Item-level parent stamps can make an old selected candidate appear fresh.**  
**C:127, 279–286, 639–640.** Generate child C1 against face F1 and select it; select F2; generate child C2. Updating the **item’s** parent stamp to F2 makes selected C1 appear current, although it still depicts F1. Also, reroll alone leaves the parent selection unchanged, so the stated predicate does not satisfy V3-AT-22’s reroll invalidation.
**Replacement:** “Each candidate immutably records its parent reference/version and invalidation generation. Freshness is evaluated for the selected candidate. Parent reroll invalidates descendants without enqueueing them; unrelated selections survive. Generating a fresh unselected candidate cannot freshen an older selection.”

**PC-4 — BLOCKING — The ‘exact’ lock preimage cannot represent voice votes or select the applicable upload.**  
**C:128, 403–404, 440–450, 459–479.** A voice selection is `CATALOG_ENTRY`, while the picks preimage requires a picked `reference_versions` ID. `voice_uploads` does not explicitly bind an upload to the audition selection it satisfies. A character-level REGISTERED clip can therefore survive a base-voice change unless the builder invents this relationship.
**Replacement:** “Voice uploads bind immutably to the audition vote and stable catalogue identity. Approve requires the registered clip matching the current audition. Voice hash members contain speaker demand, catalogue identity, audition vote, registered reference-version ID, content hash and normalised hash. Reference picks and derived members retain their separately specified tuples; all member arrays have canonical ordering.”

Also define a stable provider reference for operator catalogue entries without `speaker_id`; `voices.provider_voice_ref` is NOT NULL (`0002:142`).

**PC-5 — BLOCKING — CAST approval does not bind the wardrobe plan and other reviewed content.**  
**C:342–343, 455–456, 470–479.** The activation hashes demand-list version, items and selections. Editing timed wardrobe events can leave that binding unchanged. The lock preimage likewise omits the wardrobe document, although D consumes its assignments and boundaries. Replacing a voice upload under the same catalogue vote presents the same stale-review problem.
**Replacement:** “The activation binds the complete proposed cast membership, exact registered voice clips, wardrobe-plan record/version/hash and reviewed inspection records. The sealed CAST contract includes the wardrobe binding and provenance-basis references. Mutating any bound input supersedes and reopens the activation.”

**PC-6 — BLOCKING — The adoption split is correct, but the real helper cannot run atomically at insert.**  
**C:100–105, 492–498.** `attach_identity_lock` opens its own pooled transaction (`references/service.py:287`; `persistence/db.py:193`). Called inside episode creation, it cannot see the uncommitted episode; called after commit, creation and adoption are no longer atomic. It also chooses the highest lock version without checking effective approval.
**Replacement:** “Factor a transaction-owned adoption helper taking the creator’s `tx`; invoke it before the episode-creation transaction commits, under A’s lock order. Resolve the applicable effectively approved lock. Preserve the existing public V1 wrapper and its typed missing-lock error.”

Stamping all initial episodes at CAST LOCK remains the correct counterpart.

**PC-7 — BLOCKING — Flock release does not establish the claimed crash/in-flight safety or 120-second bound.**  
**C:313–335, 641–642.** Worker death releases flock even if an accepted remote operation continues. Another worker can acquire it and submit different work. Likewise, “submit through final poll” can exceed 120 seconds; releasing at 120 seconds would permit overlap. A file bind mount can also retain the old pinned inode after the host pathname is replaced, defeating an acquisition-only `fstat` check.
**Replacement:** “Batch limits stop new submissions; they do not release protection around unfinished work. Following worker death or ambiguous submission, shared recovery admission blocks new dispatch until prior work is reconciled. The canonical inode is not replaced while generators may run; mount topology must expose canonical-path replacement to acquisition checks.”

C-T6 must exercise accepted-but-unfinished work across holder death and the actual mount topology. Kernel crash release alone is insufficient evidence.

**PC-8 — SHOULD-FIX — CD4 updates the CASE but omits the wait view’s allowlist.**  
**C:178.** A1 §2.4 filters `track_waits` through both a CASE **and** `defer_reason IN (...)` (`A1-design-note.md:357–368`). Adding only the CASE leaves `PROVIDER_LOCK_BUSY` invisible.
**Replacement:** “CD4 extends the typed reason, jobs CHECK, wait-view CASE and wait-view IN filter. C-T5 asserts the resulting row through the production wait reader.”

**PC-9 — SHOULD-FIX — Generation actions do not consistently dispatch by item kind.**  
**C:259–264, 276–281, 555–559, 576–578.** Required music/SFX items have jobs but no stated initial enqueue trigger. Generic reroll always enqueues an **image** job, including when invoked on a library or voice item. Dependent human picks also lack an explicit candidate count; outfits require 2–3 variants.
**Replacement:** “Define dispatch policy per pick kind: image reroll emits one image candidate; library reroll uses its corresponding media job; voice replacement uses intake. Explicitly schedule initial library jobs. Generate-next creates three outfit candidates and the specified derived-view counts; forecasts use those same counts.”

**PC-10 — SHOULD-FIX — Boundary continuity and simultaneous-state composition remain assertions.**  
**C:350–366.** Keeping `StateEvent` episode-scoped is sound, but it does not define persistence across scene/episode ends, interval-end behaviour or conflicting simultaneous appearance states. The existing V2 resolver falls back to the assignment outside active intervals (`references/v2_planning.py:1067–1072`).
**Replacement:** “The C5 note defines transition versus temporary-interval semantics, terminal-state carry into the next scene/episode, explicit-reset rules, simultaneous-state composition/precedence and rejection of incompatible combinations. C-T8 verifies these through the V3 resolver and emitted reference expectations.”

**PC-11 — SHOULD-FIX — Community approval is enforced on shortlist eligibility, not every selection path.**  
**C:398–404, 445–450, 459–460.** “Other” auditions and uploads can bypass shortlist filtering. The CAST condition checks the general Botnoi route rather than explicitly requiring approval for the selected community voice.
**Replacement:** “Audition, intake registration, CAST approval, import and dispatch validate the selected voice’s own rights record. Community voices require explicit per-voice evidence; the general O-11 attestation does not satisfy it. Botnoi-owned voices retain the OPERATOR_ATTESTED basis and WORLDWIDE default.”

**PC-12 — SHOULD-FIX — Global catalogue refresh conflicts with A’s scoped-job contract.**  
**C:376–377, 556, 561.** The refresh is global, but has `logical_work_id`, replacement semantics and a mandatory content fence without a season/track. A1 requires season scope for tracked jobs and `(track IS NULL) = (logical_work_id IS NULL)`.
**Replacement:** “Register the refresh’s scope model explicitly: either an approved global-maintenance exception with its own replay identity, or an explicit season-scoped request. State which fence protects its writes and which catalogue snapshot casting consumes.”

For shortlist determinism, finish the tie-break with a unique catalogue identity and explicit NULL ordering; source-separated/operator rows can otherwise share the stated keys.

**PC-13 — SHOULD-FIX — Selected-cast similarity does not check forbidden real-person likeness.**  
**C:527–535; master §1 rule 6, §12.2.** Comparing against picked fictional faces tests cast consistency. It cannot establish absence of celebrity/real-person likeness, and root candidates may have no selected comparison set.
**Replacement:** “Record cast-consistency and forbidden-likeness assessments separately. Every candidate receives the forbidden-likeness assessment; absent a qualified detector, require the recorded human check. An empty selected set never produces PASS.”

**PC-14 — SHOULD-FIX — C’s season-only scope conflicts with extension planning.**  
**C:122, 234–237, 471–486, 573–582.** B scopes demands/documents by season **or extension**; A1 advances extension planning on `season_extensions`. C commands require the season itself to be CASTING, and its blanket episode stamping would be unsafe if reused for a later changed-cast lock.
**Replacement:** “Carry planning scope/extension identity through C commands, jobs, demand selection and STORY binding resolution. Initial CAST LOCK stamps all initial episodes; extension locking binds the extension’s episodes. Earlier published episode bindings remain unchanged; other rebinding requires scoped amendment authority.”

This defines C’s seam without demanding F’s extension UI now.

**PC-15 — SHOULD-FIX — Seed rotation must distinguish new generation from retry.**  
**C:305–307, 555–567.** “Every attempt rotates the seed” can be implemented using the jobs retry counter, changing request hashes and cache inputs during recovery.
**Replacement:** “Persist the seed and immutable request inputs once per `<pick, gen_seq>`. New initial candidates and explicit rerolls allocate new sequences/seeds. Transport retries, polling, reconciliation and restart retain them.”

**PC-16 — SHOULD-FIX — One future-package test clause remains, and critical integration clauses are missing.**  
**C:637–654.** C-T14a at C2 requires the actual CAST LOCK forecast condition, implemented in C9. The moved lock/refusal clauses, C9b import clauses and split C-T12 halves otherwise land appropriately.
**Replacement:** “C2 gates forecast data/panel behaviour; C9 gates its CAST condition. Extend the relevant package gates with PC-1’s early-budget entry, PC-2’s typed-reader roundtrips, PC-3’s old-selected/new-unselected candidate case, PC-4/5’s stale-review cases, PC-6’s insert rollback/concurrency case and PC-7’s in-flight crash case.”

O-C1 remains a dependency risk before C6/C7; O-C9 remains an operator decision about V1 scope. Neither needs resolution for this critique. C8’s note-first placeholder is sufficient.

Read-only review completed; no files changed and no runtime tests executed.