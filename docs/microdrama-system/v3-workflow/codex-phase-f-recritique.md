**Verdict: REWORK.** Nine findings are CLOSED; eight remain PARTIAL.

Reviewed v0.3 at `11595fb`, scoped to PF-1…PF-17 and defects introduced by their edits. Read-only; no files changed or tests run.

**F** = [phase-F-spec.md](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-F-spec.md). **A1** = `A1-design-note.md`; **S/** = `microdrama/src/microdrama/`; **M/** = `microdrama/migrations/`.

| Finding | Status | Evidence and disposition |
|---|---|---|
| PF-1 | **PARTIAL** | §1.1, F:60; §7.1, F:551. Adapters and pinned legacy state are correct; job routing and poll/reconcile discovery remain incomplete. **PF5-1**. |
| PF-2 | **CLOSED** | §7.1, F:527; F-T4, F:939. Activation-bound content revision replaces the decision-revision comparator; divergent revisions are tested. |
| PF-3 | **PARTIAL** | FD7, F:247; §5, F:384. Crossing registered, but numbering and season-event SQL binding remain unresolved. **PF5-2**. |
| PF-4 | **CLOSED** | §7.2, F:613. Season-wide graph, destination checks, cycles and decision overrides apply at admission and submit. |
| PF-5 | **PARTIAL** | FD6, F:246 correctly separates obligations from instants; §8.1, F:706 still leaves moved admitted identities bound to the old revision. **PF5-3**. |
| PF-6 | **PARTIAL** | §7.1.2, F:595 adds both barriers and operation checks. Reschedule authority remains inconsistent, and §1.13 retains the false admission-lock claim. **PF5-3**. |
| PF-7 | **PARTIAL** | §8.2, F:733; command F:896. Rebinding is named, but SQL permission and recovery cases remain incomplete. **PF5-4**. |
| PF-8 | **CLOSED** | §3.3, F:321; §8.4, F:785–803. Explicit carry-forward, draft equivalence, new-range authority and continuation after COMPLETE are defined. |
| PF-9 | **CLOSED** | FD5, F:245; §4, F:360; F-T5, F:940. Timecoded feedback retained; targeting is additive; notes-only episode Revise is refused. |
| PF-10 | **CLOSED** | §8.2, F:718; F8, F:924. F owns registered dependency edges/rebuild handlers; Impact/Apply traverse them; E-owned rebuilds remain an explicit dependency. |
| PF-11 | **CLOSED** | §6.2, F:486–497; F-T7, F:942. Completion includes required identities without posts; first admission advances once. |
| PF-12 | **PARTIAL** | §1.6, F:113–123 fixes approval ordering conceptually, but requires writing a column on nonexistent identities. **PF5-5**. |
| PF-13 | **PARTIAL** | §7.1, F:517 fixes discovery’s window; §7.4, F:655 still equates row states with unresolved external effects. **PF5-6**. |
| PF-14 | **CLOSED** | F-3, F:215; §3.2–3.3; F-T14, F:949. Candidate-specific provenance/freshness and release-consumer exclusions are explicit. |
| PF-15 | **CLOSED** | §1.9, F:141; delivery job F:852. Durable upload, reconciliation and language verification are required conditionally on O-8. |
| PF-16 | **PARTIAL** | F:917–946 fixes early fixtures, compatibility staging and simulation rerun, but repair and new workflow coverage remain incomplete. **PF5-7**. |
| PF-17 | **CLOSED** | §6.3, F:502; §9, F:823–836. Consecutive buffer and explicit half-open observation windows with backfill resolve the findings. |

1. **PF5-1 — BLOCKING — V3 execution still lacks a complete routed lifecycle.**  
   F:551 enqueues `publish.submit_slot`, whereas A1:621 requires distinct V3 job types. W09 excludes V3 **submit and poll** candidates (A1:620), and W13 only discovers future calendar obligations. Naming poll/reconcile adapters does not give processing, ambiguous or rearmed posts a discovery path.  
   **Replacement:** “Register distinct V3 submit/poll/reconcile jobs with A’s work scope. W13 also discovers admitted V3 posts needing poll, reconciliation or authorized retry, independently of its admission window. W09 remains legacy-only.”

2. **PF5-2 — BLOCKING — The carrier crossing does not yet resolve the enforced binding.**  
   F:398–405 retains “approval entity = carrier episode,” although `TEASER_FINAL` remains season-scoped. Adding its gate to the allowlist does not fix the package lookup in `M/0021_t037_release_metadata.sql:61`. F-4 also retains logical number 0 without specifying its mapping to the guarded carrier. N11 still needs a concrete source for its required approval/manifest references.  
   **Replacement:** “Keep the approval entity season-scoped. Pin the carrier numbering/mapping and persist an explicit season-decision→carrier-package/manifest binding. A V3 branch of the SQL trigger and loaders validates that binding; the legacy branch remains unchanged. Define N11’s required approval/manifest binding and the carrier catalog policy.”

3. **PF5-3 — BLOCKING — Reschedule changes admitted post dates without changing their calendar binding.**  
   §8.1 updates post projections and replaces commands, but F:706 only rebinds identities with `platform_post_id IS NULL`. A moved admitted identity therefore retains a revision that is no longer equivalent; the new command builder/barrier can reject it or resolve the old instant. F:174 also incorrectly says the admission lock prevents an amendment between admission and submit.  
   **Replacement:** “Atomically update calendar bindings for moved never-admitted and admitted-pre-begin identities, their date projections and replacement commands. Final validation compares the command’s revision and instant with that authority under locks held through begin. Past-begin attempts retain their recorded request and reconcile. Admission and submit are separate fenced transactions.”

4. **PF5-4 — BLOCKING — Rebinding still contradicts SQL immutability and excludes required repairs.**  
   F:747 mandates writes forbidden by `M/0005_distribution_and_analytics.sql:77–80`, without registering a trigger exception. F:744 defines no effect as *never began*, excluding reconciled proven absence. F:896 accepts metadata-delta Gate 2 only, excluding teaser/content replacement.  
   **Replacement:** “Register a guarded V3 SQL rebinding exception preserving legacy immutability. Accept effective episode or teaser re-approval after no begin, or definitive reconciled absence with the old execution fenced. Atomically replace authority/media, current metadata and queued commands; specify token/operation linkage while preserving immutable old requests, history and attempt caps. Published identities refuse.”

5. **PF5-5 — SHOULD-FIX — Pre-allocation content authority needs a real storage rule.**  
   F:115–116 cannot write `release_slot_identities.bound_approval_event_id` before that row exists.  
   **Replacement:** “Before allocation, content authority remains discoverable through the decided activation, approval and package. Allocation resolves and binds every effective in-scope approval. After allocation, approval handlers refresh existing identity bindings.”

6. **PF5-6 — SHOULD-FIX — Overdue classification must use operation evidence.**  
   F:655–665 treats SCHEDULED/HELD rows as unresolved external effects even when no operation began; existing reconciliation refuses those states (`S/publishing/service.py:953`). Discovery’s window also does not itself stop an already queued command executing late.  
   **Replacement:** “Derive unresolved external effects from operation/linkage evidence. Expired never-begun rows become MISSED and require approved recovery. Enforce the dispatch window again before begin and on retry; begun work remains owned by reconciliation.”

7. **PF5-7 — SHOULD-FIX — Finish the acceptance re-map.**  
   F-T6 claims end-to-end repair at F5, before F7 supplies rebinding; it can only cover the never-admitted subset then. F-T6 contains no caption-delivery assertions, and F-T10 explicitly names only the admission→begin race.  
   **Replacement:** “Stage admitted-teaser repair to F7 and rerun it with renewed `TEASER_FINAL` authority and rebinding. Add conditional F5 delivery/reconcile/language-verification assertions; explicitly test both submit barriers, moved admitted bindings, and pre-LAUNCH approvals beyond episode five.”

O-8 remains **OPEN, OPERATOR-owned**; F5 remains conditionally blocked. E’s export/caption/rebuild contract remains a declared dependency, without an additional demand in this review.