**Verdict: APPROVE.**

Scoped verification of the two R4 applications:

| Finding | Status | Evidence |
|---|---|---|
| N3R4-1 | **CLOSED** | [§3.2](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A3-design-note.md:284) explicitly requires independent discovery, including terminal operations with incomplete aftermath. [§4.1](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A3-design-note.md:435) separates cancellation and stale-reconciliation completion predicates and requires automatic rediscovery testing after a result-commit crash. |
| N3R4-2 | **CLOSED** | [§7](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A3-design-note.md:654) restricts paid rearm to **NOT_FOUND only**, retaining REFUSED_PRELAUNCH exclusively for `llm.subscription` under A0’s kind and durable-evidence checks. |

Verified against A0-D `6974d5a`. No new defect introduced by these edits was found; no N3R5 findings.

Read-only design verification. No files changed or tests run.