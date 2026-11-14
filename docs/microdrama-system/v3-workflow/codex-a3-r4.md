**Verdict: REWORK.** The lock-order correction is complete; recovery discovery still needs one correction.

Read-only verification: A3 matches `68f906b`; A0-D is `6974d5a`. No writes or tests.

**N** = [A3-design-note.md](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A3-design-note.md). **S/** = `microdrama/src/microdrama/`; **G/** = `.scratch/a0d-gateway/microdrama/src/microdrama/`.

| Finding | Status | Verification |
|---|---|---|
| N3R2-1 | **CLOSED** | N §4.1:452–473 preserves per-kind legal recovery transitions, evidence hooks and CANCELLED status. |
| N3R2-2 | **PARTIAL** | N §3.2:282–284 and §7:650–652 connect classification and recovery authority, but terminal stale-operation discovery remains incomplete. N3R4-1. |
| N3R2-3 | **CLOSED** | N §7:628–649 correctly distinguishes begin’s reservation chain from rearm’s advisory/operation locks; V3 gets separate #6→#7 paths and eligibility checks. Tests :698–708 cover each separately. |
| N3R2-4 | **PARTIAL** | N §4.1:417–434 covers terminal CANCELLED operations, but the newly added stale NEEDS_RECONCILIATION route lacks equivalent independent discovery. N3R4-1. |
| N3R2-5 | **CLOSED** | N §4:365–386 covers runtime completion/defer boundaries and commits evidence before stopping. |
| N3R2-6 | **CLOSED** | N §5.1:512–531 specifies incarnation validation and ownership-loss checks; §9:745 tests connection loss and replacement. |
| N3R2-7 | **CLOSED** | N §7:685–692 and §9:745–746 correct signals versus outcomes, both admission interleavings, and graceful versus forced termination. |

The two round-3 blockers: **N3R3-1 PARTIAL**—classification and authority are fixed, but discovery remains incomplete below. **N3R3-2 CLOSED**—the contradictory lock rows and old-shape test are replaced.

1. **N3R4-1 — BLOCKING — Terminal stale operations lack independent recovery discovery.**  
   N §3.2:284 retains “Discovery … unchanged”; §4.1:417–429 explicitly scans CANCELLED jobs, while :430–434 adds stale NEEDS_RECONCILIATION operations only when *routed in*. A0’s actual candidate scan excludes terminal operations (`G/llm/reconciler.py:126–128`). Consequently, routing before RESUME does not establish restart discovery after an operation becomes terminal but its required aftermath remains incomplete. The completion predicate at N:422–424 also requires `settled_after_cancel`, which does not describe stale NEEDS_RECONCILIATION resolution.

   **Replacement:** “The recovery pass independently discovers stale NEEDS_RECONCILIATION jobs with unresolved operations or terminal operations whose required evidence, accounting or job resolution remains incomplete; it does not depend on A0’s in-flight-only candidate scan. Define completion separately: CANCELLED requires `settled_after_cancel`; stale reconciliation requires quarantine/accounting completion and its legal job resolution. Test automatic rediscovery after a result-commit crash.”

2. **N3R4-2 — SHOULD-FIX — The paid rearm row includes an LLM-only state.**  
   N §7:648 labels paid rearm “NOT_FOUND/REFUSED_PRELAUNCH”. Binding A0 §5.5:369–376 and `G/core/provider_ops.py:429–443` restrict REFUSED_PRELAUNCH rearm to `llm.subscription`; paid rearm remains NOT_FOUND-only.

   **Replacement:** “Fenced V3 paid submit — rearm (**NOT_FOUND only**). REFUSED_PRELAUNCH rearm belongs exclusively to the fenced LLM admission row, retaining A0’s kind and durable-evidence checks.”