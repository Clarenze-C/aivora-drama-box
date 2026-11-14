**Verdict: REWORK.** Reviewed `b894bbe` read-only, limited to N1R-1..12 and defects introduced by their edits. No files changed.

**N** = [A1-design-note.md](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A1-design-note.md); **S/** = `microdrama/src/microdrama/`.

| Finding | Status | Section and evidence |
|---|---|---|
| N1R-1 | CLOSED¹ | §2.4, N:439,455–459,506: recursive declaration added; episode-cancellation branch now has nine columns with compatible types. |
| N1R-2 | CLOSED | §4, N:550–576: generator adapter preserves the original `$ref` and two-value definition; V3 validation discovery and external rejection probes are specified. An equivalent in-memory adapter reproduced the committed schema bytes exactly. The unadapted model’s expanded schema no longer refutes this design. |
| N1R-3 | PARTIAL | §2.3, N:269–322: valid extension decisions escape the old season collision, but nullable activation identity can bypass the uniqueness partition; N1R3-1. |
| N1R-4 | PARTIAL | §4–§6, N:599,644–647,677,717: exact activation identity is correctly propagated and checked. The concurrent-decision expectation contradicts that order; N1R3-6. |
| N1R-5 | PARTIAL | §2.4, N:371–392: immutability, hydration and resolved-version validation are specified. The unconditional replay comparison changes V1 behavior; N1R3-4. |
| N1R-6 | CLOSED | §2.4, N:411–430,519–520: operation dismissals have canonical NULL job identity throughout the CHECK, writer, index and join. |
| N1R-7 | CLOSED | §4–§6, N:609–613,679,706–715: Reject uses empty feedback and `reason`; the contradictory requirement is removed. |
| N1R-8 | REGRESSED | §8–§9, N:775–789,823–837: reservation/lease transaction ownership and real advisories are acknowledged, but the revised audit loses the durable-before-submit boundary and still contradicts the lock order; N1R3-2/3. |
| N1R-9 | CLOSED | §8, N:785; §10, N:858: transfer chains reach the verified final holder; proven no-create history is distinguished from unresolved creation. Matches `S/rendering/leases.py:1376`. |
| N1R-10 | CLOSED | §7, N:734,757–758: direct reads explicitly refuse after owner access; filters apply only to enumeration. |
| N1R-11 | PARTIAL | §2.2, N:87–107,146–154: diagnostic fields are now explicit, but the shared scope predicate changes V1 diagnostics; N1R3-5. |
| N1R-12 | CLOSED | §5, N:669; §10, N:854: A1 owns and invokes production registry validation; A6 must reuse it. |

¹ Structural review only: PostgreSQL socket access was denied by the sandbox, so native view compilation remains **unverified**.

**N1R3-1 — BLOCKING — Approval identity can select either uniqueness partition.**  
§2.3, N:289,305–311: NULL activation returns without validation, while both index predicates depend solely on that nullable column. A V3 approval without activation and another with activation can share scope/revision across the two indexes. The trigger also never prohibits V1 activation identity, weakening `M/0002_story_and_approvals.sql:208`.

**Replace:** “Resolve workflow from the approval entity. Require V1 `activation_id` and `extension_id` to be NULL; require V3 `activation_id` non-NULL. Validate the activation’s workflow and complete season/episode/extension ancestry against the approval before accepting either index partition.”

**N1R3-2 — BLOCKING — Comfy queue submission now precedes durable intent.**  
§8–§9, N:788,823 explicitly order operation INSERT / queue submit → commit. Actual `S/rendering/comfy_jobs.py:611–623` commits `begin` before HTTP at `:630`, then records submission separately at `:639`. Following the proposed sequence permits an accepted external request with its operation rolled back, contradicting A3 §9 A-T18.

**Replace:** “Commit the guarded begin/rearm transaction before submission. Dispatch reacquires the ordered scope/job/operation/lease/reservation guards and revalidates admission against the already-durable operation. Persist the outcome separately; an ambiguous submission retains its durable reconciliation identity.”

**N1R3-3 — SHOULD-FIX — The lock audit still contains incompatible sequences.**  
§8, N:779–781 puts reservation #7 before lease writes #6; §9 requires #6 before #7. N:824 also compresses `ensure_pod`’s separately committed writes into one apparent lock lifetime (`S/rendering/leases.py:901–913,919,943,970`).

**Replace:** “Each transaction follows scope → job → provider-operation serialization/rows → lease rows → budget locks. Enumerate create-request, pod-binding and activation transactions separately, naming their scope-lock reacquisition and the intervening provider call.”

**N1R3-4 — SHOULD-FIX — Complete-scope replay comparison must be V3-only.**  
§2.4, N:392 extends replay comparison without a version branch. Current V1 replay checks only type/hash (`S/core/jobs.py:434`); changing an explicit season/episode argument can therefore newly refuse an otherwise identical V1 replay.

**Replace:** “Apply complete work-scope replay comparison to resolved V3 work only. Preserve the existing type/input-hash replay rule for V1.”

**N1R3-5 — SHOULD-FIX — V1 diagnostic identity still changes.**  
§2.2, N:86–98: for V1 `STORY_LOCK` on a season, old `0002:200` fails `approval_events_check`; the new shared predicate passes and instead raises `approval_events_gate_type_check`. Episode scope reverses that mismatch.

**Replace:** “Evaluate V1 scope compatibility using the original `gate_type='SEASON_CONCEPT'` equivalence; use the expanded season-gate set only in V3. Preserve legacy failure precedence and test the new gate values on both V1 entity types.”

**N1R3-6 — SHOULD-FIX — Concurrent-decision test expects the wrong refusal.**  
§9, N:845 expects `StaleRevision`, but §5, N:677 checks openness first. After the winner commits, the losing distinct-key command names a decided activation and receives `GateNotReady`, as N:854 already requires.

**Replace:** “Concurrent distinct-key decisions serialize: one commits; the loser receives `GateNotReady` for the closed activation. Same-key replay returns the stored response.”