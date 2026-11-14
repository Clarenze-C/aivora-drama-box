**Verdict: APPROVE.** Reviewed A1 v1.4 (`779099f`) read-only, limited to N1R3-1..6 and defects introduced by their fixes.

**N** = [A1-design-note.md](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A1-design-note.md).

| Finding | Status | Verification |
|---|---|---|
| N1R3-1 | **CLOSED** | §2.3, N:322–362: workflow resolution enforces NULL identity for V1 and required activation for V3. Activation matching checks gate, revision and complete season/episode/extension ancestry, preventing partition bypass. |
| N1R3-2 | **CLOSED** | §8–§9, N:856,891: durable begin/rearm commits before HTTP submission; dispatch reacquires guards and revalidates admission; outcome persists separately. Matches `rendering/comfy_jobs.py:611–649` and accepted A3 §9 A-T18. |
| N1R3-3 | **CLOSED** | §8–§9, N:842–849,855,892: canonical scope → job → operation → lease → budget order replaces the contradictory sequence. Create-request, pod-binding and activation transactions are individually identified, with scope-lock reacquisition and the intervening provider call. |
| N1R3-4 | **CLOSED** | §2.4, N:448–455; §10, N:924: complete-scope replay comparison is V3-only. V1 retains the type/input-hash rule from `core/jobs.py:429–439`; the regression test is explicit. |
| N1R3-5 | **CLOSED** | §2.2, N:96–131,175–184: V1 uses the original `SEASON_CONCEPT` scope equivalence before membership validation. Expanded scope rules are V3-only; A-T1/A-T16 cover the specified legacy diagnostics. |
| N1R3-6 | **CLOSED** | §5, N:740; §9–§10, N:913,922: the distinct-key loser receives `GateNotReady` after checking activation openness; same-key replay returns the stored response. |

No new **N1R4-n** issues found within scope. Approval is for the design note; verification was static against the binding documents and cited code. No files changed or runtime tests run.