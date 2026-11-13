**Verdict: REWORK.**

Reviewed Phase F v0.2 against `ef63e65` (the file is unchanged), the binding specs, B/C’s in-flight rulings, and current code. Read-only; no files changed or tests run.

The date-column correction is valid, but the full reschedule path remains incomplete. The synthetic carrier still fails enforced contracts. Package gating improved, but some gates remain unpassable at their assigned step.

Below, **F** means [phase-F-spec.md](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-F-spec.md), **S/** means `microdrama/src/microdrama/`, and **M/** means `microdrama/migrations/`.

1. **PF-1 — BLOCKING — The unchanged publishing path contradicts A’s V3 isolation.**  
   **F:437–462, §4, §7.3.** A §1 keeps legacy episode state `PLANNED` forever and refuses V3 at legacy publishing boundaries. A1 §7 explicitly guards `schedule_release`, submit, completion, recovery and metadata loading, and filters V3 out of W09. F nevertheless requires legacy `RELEASE_APPROVED → SCHEDULED`, unchanged W09, and unchanged recovery methods. These paths cannot execute after A lands.  
   **Replacement:** “F supplies version-selected adapters for scheduling, command construction, submit, poll/reconcile, recovery and release views. V3 transitions use `episode_tracks`; legacy state remains pinned. Shared transport and persistence primitives are reused beneath those adapters; V1/V2 behavior remains unchanged.”

2. **PF-2 — BLOCKING — Admission compares two different revision namespaces.**  
   **F:422–424.** `approval_events.expected_revision` is the **decision revision**, not the content fence. A1 §4/§5 distinguishes `expected_revision` from `expected_content_revision` and advances the former independently. Ordinary approvals can therefore fail this comparator without any content change.  
   **Replacement:** “Resolve the effective approval’s decided activation and compare its bound `content_revision` with the authoritative scope `content_revision`. Never compare `approval_events.expected_revision` with the content fence.” Add a test where decision and content revisions differ.

3. **PF-3 — BLOCKING — The carrier does not yet satisfy the ordinary path.**  
   **F:324–340; §8.3; FD3.** `episodes.episode_number >= 1` is enforced by `M/0002_story_and_approvals.sql:62`; `ReleasePackage.episode_number` is `PositiveInt` (`S/contracts/release.py:271`). Episode 0 cannot be created as specified. Additionally, A1’s season-gate command forbids `episode_id` for `TEASER_FINAL`, while existing manifest/live loaders require approval entity = carrier episode (`M/0021:61–62`; `publishing/metadata.py:177–180`). Live submit also requires a current membership catalog (`service.py:502–513`). N11’s approval/calendar binding is unspecified.  
   **Replacement:** “Register the carrier as an explicit V3 contract crossing: guarded carrier identity/numbering, season-gate-to-carrier-package binding, manifest resolution, catalog policy, and corrective-post authority. Preserve V1/V2 constraints through version-aware validation.” F-T6 must exercise these real typed and SQL paths.

4. **PF-4 — BLOCKING — Cross-episode dependencies fail the preserved DAG validator and W09.**  
   **F:347–351, 453, 464–471, 670.** `validate_scope_dag` rejects dependencies outside the package’s own scope (`slots.py:60–68`). Every premiere/predecessor dependency crosses episode packages. W09 also searches verified dependencies only within the current episode (`scheduling/service.py:583–585`). An approved swap cannot work with unchanged numeric predecessors; closeout’s override is ignored by the existing submit checker.  
   **Replacement:** “V3 validates a season-scoped identity graph with same-season/destination checks and cycle detection. Discovery and submit use that graph. Approved swap/closeout decisions supply explicit dependency overrides consumed by both checks; V1/V2 retain package-local DAG validation.”

5. **PF-5 — BLOCKING — Updating post dates does not update the command’s authoritative schedule.**  
   **F:77–88, §7.1.1, §8.1.** `ReleasePackage` already contains mandatory dated plans, and both package/scope hashes cover them (`release.py:280,335–355`). `publication_command_for_post` then uses **`plan.schedule`**, rather than the updated post date (`publishing/commands.py:154`). “Fill at admission” cannot modify the approved package without changing its immutable hash.  
   **Replacement:** “Define V3 content obligations separately from resolved calendar instants. The V3 command builder resolves schedule from the current authorized calendar binding and checks it against the post projection. Legacy dated packages and hashes retain their existing interpretation.” Register this crossing in §2.2.

6. **PF-6 — BLOCKING — Admission’s lock does not fence the later submit transaction.**  
   **F:133–142, 437–443, 533–537, §8.5.** Admission commits before the worker submits. A reschedule/amendment can occur between those transactions. Worse, `_validate_and_begin` commits an operation link while leaving the post **SCHEDULED** during the external call (`service.py:568–595`); locking a SCHEDULED row does not prove it is pre-`begin`. Queued commands also retain old dates.  
   **Replacement:** “Immediately before `provider_ops.begin`, the V3 submit adapter revalidates content, calendar, cancellation and binding authority under A’s lock order. Reschedule checks operation history/linkage, not post state alone; it fences or replaces obsolete queued commands atomically. Past-begin work reconciles.” Add barriers before begin and after begin/before response.

7. **PF-7 — BLOCKING — Renewed approval cannot replace the approval pinned on an admitted row.**  
   **F:179, 459–460, §8.2.** Once admitted, `release_package_id`, `approval_event_id`, media and token are trigger-immutable (`M/0005:77–80`). Metadata-delta Gate 2 produces renewed authority, but no specified operation installs it on that row. Content/teaser repair has the same problem; “different package ⇒ Conflict” makes recovery permanently refuse.  
   **Replacement:** “Define a guarded V3 rebinding operation for an existing unpublished identity after proving no external effect. Specify package/approval/media/token handling and preserve attempt history. Reconcile begun work before replacement; published media remains immutable.” Date-only UPDATE remains valid where content authority is unchanged.

8. **PF-8 — BLOCKING — Extension invalidates the remaining base season under admission’s current-revision rule.**  
   **F:427–429, §8.4, 602.** Extension appends calendar r2 while existing identities retain r1; admission requires equality with the current revision. Existing base episodes therefore stop admitting. Global draft staleness also marks unchanged base content stale. “Never rewrites the bound revision” does not resolve this. After COMPLETE, no release-track continuation rule is given either.  
   **Replacement:** “An extension revision preserves authority for unchanged existing obligations through an explicit carry-forward/equivalence rule; new range authority comes from the extension decision. New Gate 2 approvals supply content authority. Define extension dispatch/completion while preserving prior approvals and the season’s coarse-state rules.”

9. **PF-9 — BLOCKING — Gate 2 Revise notes contradict A’s enforced command contract.**  
   **F:306–310; FD5.** A §2 and A1 §4 require `EPISODE_FINAL` REVISE to carry timecoded feedback and prohibit season notes. Adding `RevisionTargetKind` values alone does not permit F’s notes-based command.  
   **Replacement:** “Either retain A’s Gate 2 feedback contract and add typed targeting through an explicitly registered compatible extension, or register a V3-only decision-contract/SQL delta permitting metadata/thumbnail revision notes. V1/V2 remain unchanged.” Test actual JSON/HTML submission and transaction commit.

10. **PF-10 — BLOCKING — F does not define the amendment dependency closure it relies on.**  
    **F:§8.2, §8.5.** Job fences quarantine stale executions, but they do not discover already-current dependent artifacts. An episode amendment must invalidate dependent teaser sources, successor recaps, captions, metadata, picks, approvals and unpublished submissions. No F `DependencyProvider` mapping or registration owner is specified. Rebuilding draft text alone also misses date-bearing CTA media from step 7.  
    **Replacement:** “F registers its dependency edges and rebuild handlers with A4, including exact source versions and approval/identity bindings. Impact and Apply traverse that closure. E-owned recap/CTA media and captions require E’s pinned rebuild contract; unchanged published artifacts are excluded.” Keep that E contract an explicit dependency.

11. **PF-11 — BLOCKING — Per-slot creation breaks completion based only on existing post rows.**  
    **F:437–460, 401–404.** Existing completion counts required **`platform_posts` rows** (`service.py:928–933`). With independent admission, YouTube can verify before held TikTok/Facebook identities have rows, causing premature episode completion. The spec also does not define subsequent destination admission after the episode has advanced past its first SCHEDULED transition.  
    **Replacement:** “V3 completion quantifies over all required allocated identities, including identities without posts. First-slot admission advances the track once; subsequent destination admissions remain valid in the appropriate release states and cannot replay as whole-episode completion.”

12. **PF-12 — SHOULD-FIX — Binding lifecycle omits legitimate approval orderings.**  
    **F:95–98, 369–379.** Episodes 6+ can receive Gate 2 before LAUNCH, when their “already-allocated” identities do not exist. Conversely, renewed approvals for episodes 1–5 or the teaser have no binding writer after LAUNCH; reschedule only updates the calendar binding.  
    **Replacement:** “Gate 2 records content authority independently of allocation. Allocation binds every already-approved in-scope episode; subsequent effective approvals refresh affected content bindings, including initial-five and teaser replacements, without rerunning LAUNCH.”

13. **PF-13 — SHOULD-FIX — MISSED is neither exclusive nor enforced by discovery.**  
    **F:418–419, 499–501; §5 recovery.** A past-air identity with a refusal and no post can satisfy both HELD and MISSED. W13’s unrestricted `air <= now + lead` then admits it automatically once the blocker clears, although §5 says a passed premiere requires reschedule. SCHEDULED/HELD rows also prevent MISSED indefinitely.  
    **Replacement:** “Define state precedence and the permitted dispatch window. An expired obligation requiring reschedule remains undispatchable until an approved recovery supplies valid calendar authority. Distinguish recoverable held work from unresolved external effects; queued jobs alone do not authorize overdue publication.”

14. **PF-14 — SHOULD-FIX — The C extension needs candidate-level freshness and consumer scope.**  
    **F:F-3, FD1, §3.3.** Adding `ASSET` does not define candidate enumeration, immutable generation dependencies, or inspection evidence **per candidate**. Re-voting cannot make an asset generated from an obsolete pack current. C’s accepted PC-3 ruling specifically requires freshness of the selected candidate; C’s cast membership/forecast queries must also exclude release thumbnails.  
    **Replacement:** “Thumbnail candidates persist exact asset/version/hash, source pack/cast/content bindings and inspection reference. Voting only selects; stale candidates require regeneration and a fresh selection. Release picks use explicit consumer scope and never enter CAST LOCK membership or cast forecasts.”

15. **PF-15 — SHOULD-FIX — Caption-route admission does not implement caption delivery.**  
    **F:433–434, §10, F5.** No job/continuation uploads tracks, reconciles upload outcomes, or verifies required languages. Existing `upload_captions` is not invoked by submit, and ordinary publication verification requires visibility/disclosures, not EN/ZH delivery (`service.py:81–85`).  
    **Replacement:** “Conditional on O-8, F5 implements the selected route’s durable delivery and verification workflow, binding exact E-produced tracks. Required caption failure holds release qualification and exposes retry/reconcile.” **O-8 remains OPEN; F5 remains conditionally blocked.** No operator ruling is requested here.

16. **PF-16 — SHOULD-FIX — Package gates still cannot prove the assigned milestones.**  
    **F:689–721.** F-T2 seeds V3 approvals through the existing Gate 2 path, which A explicitly refuses. F1’s full F-T11 compatibility claim includes V3 behavior built later. F-T8 runs before F7’s recovery execution, so it cannot yet constitute the completed V3-AT-29 simulation. F-T9’s “only date columns changed” also excludes the renewed-content path it claims to cover.  
    **Replacement:** “Use explicit A-compliant test handlers/fixtures for early gates; split schema compatibility from later workflow compatibility. Rerun the real 30-day simulation after recovery integration. Separate date-only reschedule assertions from rebuilt-content re-approval. Add the concrete race, missing-destination, extension and candidate cases above to their package gates.”

17. **PF-17 — SHOULD-FIX — Buffer and daily counters can report misleading results.**  
    **F:409–410, 606–612.** Counting arbitrary approved/unreleased episodes treats distant approvals beyond an unready head episode as usable buffer. A 19:05 snapshot counting approvals “that day” also needs a closed-window rule; otherwise approvals later that evening are omitted permanently.  
    **Replacement:** “Buffer counts the consecutive, currently approved release obligations ahead of the next release, with destination constraints shown. Daily observations cover explicit closed, nonoverlapping intervals and support idempotent catch-up/backfill; rolling rates use those complete intervals.”

The five AT assignments are appropriate, but the specified tests do not yet establish them through the real V3 authority and recovery paths. D/E’s absent contracts and O-8 remain declared dependencies; the findings above concern F’s own contracts and integration obligations.