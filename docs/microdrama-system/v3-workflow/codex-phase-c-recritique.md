**Verdict: REWORK.** Nine findings are closed; six remain partial; PC-16 regressed through new test-placement requirements. The remaining blockers concern reroll freshness and cross-system recovery safety.

Reviewed the requested 846-line v0.3 at `6ce01a4`; the working file matches that revision. `C` below means [phase-C-spec.md](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-C-spec.md).

| Finding | Status | Evidence / remaining work |
|---|---|---|
| PC-1 | **CLOSED** | §1.2, §4; C:77–86, 283–296, 751. The helper waits for both authorities; early A2 approval no longer loses the initial enqueue. |
| PC-2 | **CLOSED** | §2.2 CD2; C:198, 729, 749. V3 typed kinds/body/views and workflow-aware readers/builders are explicitly included; frozen V1/V2 contracts remain unchanged. |
| PC-3 | **PARTIAL** | §4; C:320–330. Candidate stamps are corrected, but the freshness predicate still ignores invalidation generation. **PC5-1.** |
| PC-4 | **PARTIAL** | §7–8; C:154, 480–486, 525–527, 570–577. Upload binding is corrected; voice membership and the “other” identity remain ambiguous. **PC5-3.** |
| PC-5 | **CLOSED** | §8; C:545–550, 566–579, 762. Activation binds exact clips, wardrobe and inspection records; mutations supersede/reopen it. |
| PC-6 | **CLOSED** | §1.9, §8; C:110–120, 595–602. Creator-owned `tx`, effective approval and rollback/concurrency coverage address `references/service.py:287`’s separate transaction. |
| PC-7 | **PARTIAL** | §5, C-T6; C:361–396, 754. Recovery requirement is added, but its cross-system admission seam and mount/time clauses need resolution. **PC5-2.** |
| PC-8 | **CLOSED** | CD4, C-T5; C:200, 753. Both view predicates and the production-reader assertion are included. |
| PC-9 | **PARTIAL** | §3–4; C:262–265, 315–319. Initial libraries and kind-specific rerolls are corrected; dependent appearance-state counts remain unspecified. **PC5-4.** |
| PC-10 | **CLOSED** | §6; C:411–420. C5’s note must define carry/reset, interval and composition semantics; C-T8 must verify each through the resolver. |
| PC-11 | **CLOSED** | §7–8; C:480–486, 530–539, 553–556, 616–620. Selected-voice rights checks cover the requested paths, including community/“other” cases. |
| PC-12 | **PARTIAL** | CD6, §7, §10; C:202, 444–453, 667–673. Global scope is registered, but fencing and snapshot requirements remain inconsistent. **PC5-5.** |
| PC-13 | **CLOSED** | §9, C-T12; C:634–645, 761. Separate forbidden-likeness assessment covers root candidates and requires human fallback. |
| PC-14 | **PARTIAL** | §1.13 versus §2; C:131–144, 214. Commands/stamping are scoped; document identity remains season-only. **PC5-6.** |
| PC-15 | **CLOSED** | §5, §10, C-T3; C:349–354, 666, 751. Persisted inputs/seeds survive transport retries, reconciliation and restart. |
| PC-16 | **REGRESSED** | C:759, 762–763. Forecast gating moved correctly, but C-T11 now requires later-package paths at C7. **PC5-7.** |

**PC5-1 — BLOCKING — Reroll generation is recorded but absent from freshness.**  
§4, C:320–328. Reroll F1 without changing its selection: an existing child’s recorded parent version still equals selected F1, so the stated predicate returns fresh. Recording an invalidation generation does not fix this unless freshness compares it with current authority.

**Replacement:** “A selected dependent is fresh only when its immutable parent reference/version **and invalidation generation** match the parent’s current selected reference/version and current invalidation generation. An explicit parent reroll advances that generation idempotently, invalidating descendants without enqueueing them. Retries do not advance it. C-T4 covers reroll while the parent selection remains unchanged.”

**PC5-2 — BLOCKING — Shared recovery admission needs an explicit cross-system contract.**  
§5, C:378–396; C-T6, C:754. Drama’s `ProviderOperation` reconciliation alone cannot stop an ARISA process that only acquires flock; the existing ARISA helper at `arisa/studio/sfw/recovery.py:91–106` has no recovery-admission check. The spec also retains “120 s per hold” while allowing unfinished operations to extend the hold, and leaves the prescribed bind mount ambiguous despite rejecting stale file-inode mounts.

**Replacement:** “The C3 note defines durable recovery admission shared by **every participating generator**, published before submit and checked under flock before any new submit. Worker death or ambiguous submission retains the blocker until reconciliation proves no prior work remains active. ARISA adoption includes this protocol and is required before live enablement. Bind the canonical **parent directory**, or specify another replacement-visible topology; a file-only bind is ineligible. The 120-second setting limits further submissions, not total hold duration. C-T6 uses isolated mounts matching deployment topology and tests a competing participant after holder death.”

**PC5-3 — SHOULD-FIX — Voice tuples still overlap the generic “per pick” tuple.**  
§8, C:570–577 still demands a picked `reference_versions` ID “per pick,” although voice votes select `CATALOG_ENTRY`. Separately, C:154 permits NULL catalogue identity for “other,” but C:525–527 defines provider references only for speaker IDs or catalogue rows.

**Replacement:** “Reference-pick tuples apply only to `REFERENCE_VERSION` selections. `VOICE_NEUTRAL` contributes through its voice tuple, using the registered clip matching the current audition. For ‘other,’ use a tagged audition identity such as `other:<audition_vote_id>` in both the voice tuple and stable provider reference; catalogue auditions use their stable catalogue identity.”

**PC5-4 — SHOULD-FIX — Appearance-state generation remains outside the count policy.**  
§3–4, C:233, 262–265, 315–319; C-T2, C:750. `APPEARANCE_STATE` depends on FACE but is neither an initial root nor assigned a generate-next count. The forecast’s claim that counts cannot disagree is therefore unsupported.

**Replacement:** “`generate_next(FACE)` creates three candidates per required `OUTFIT` **and `APPEARANCE_STATE`** item, and one per derived view item. The image forecast uses those same counts; C-T3/C-T14a exercise every dependent image kind.”

**PC5-5 — SHOULD-FIX — Global refresh still conflicts with the blanket fence rule.**  
§7 exempts refresh from season fencing, but §10, C:672–673 still requires a content revision on **every job**. Also, row IDs plus `last_verified` identify mutable catalogue rows rather than preserving the ranked inputs.

**Replacement:** “Every **content-scoped** job carries its scope’s `expected_content_revision`; CD6’s global refresh instead uses its importer-run authority. `VoiceCastingV3` stores the ranked catalogue payload and hash, or immutable catalogue-version references. Refresh never changes an existing shortlist snapshot; explicit reranking creates a new version.”

**PC5-6 — SHOULD-FIX — Cast documents can collide across planning scopes.**  
§2, C:141–144 uses `<season_id>` for all document identities; `cast-lock:<content_revision>` at C:214 can repeat across independent scope fences. Extension wardrobe/forecast writes would also share the initial scope’s current-document stream.

**Replacement:** “Use `record_id = uuid5(CAST_V3_NS, '<type>:<planning_scope_id>[:<key>]')`, where the scope is the season or extension ID. Store and validate scope ownership; resolve current documents and lock keys within that scope. C-T1/C-T13 prove an extension cannot supersede the initial scope’s current documents or bindings.”

**PC5-7 — SHOULD-FIX — C-T11 introduces future-package acceptance requirements.**  
C:759 assigns audition, registration, Approve, import and dispatch validation to C7; C9/C9b have not shipped then.

**Replacement:** “C6 gates audition rights checks; C7 gates intake registration and the reusable rights validator; C9 gates CAST approval; C9b gates import. D gates actual downstream dispatch enforcement against C’s binding. Each package tests its implemented path without requiring later packages.”

Read-only review completed. No files changed, tests run or provider calls made.