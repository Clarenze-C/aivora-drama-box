**Verdict: APPROVE** for this scoped design verification. Both round-2 blocking recovery gaps are closed at design level.

Reviewed v1.2 (`9f21c8b`), N6R2-1..5 and regressions introduced by those edits only. Read-only; no runtime tests.

References below are to [A6b-design-note.md](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A6b-design-note.md).

| Finding | Status | Evidence |
|---|---|---|
| **N6R2-1** | **CLOSED** | §4, lines 320–332 explicitly require transaction-safe append-once behavior: matching replay returns the stored event without advancing the sequence or aborting the transaction; conflicting payload reuse fails. Actual `_lease_event` lease-clean events are included. §9 S3, line 612, requires successful replay and unchanged sequence. |
| **N6R2-2** | **CLOSED** | §3 step 4, lines 246–256, runs recovery independently of eligibility and firing claims, covering PENDING and FAILED/RETRYABLE obligations with canonical identities. §4, lines 281–287, separates recovery from reclaiming a period. §9 S2/S3, lines 611–612, tests same-period recovery through `fire()`. |
| **N6R2-3** | **CLOSED** | §6, lines 459–486, resolves effective authority before applying its timestamp window and excludes cancelled episode/season scopes. Lines 508–531 bind buffer posts to the effective approval and exclude both cancellation scopes. §9 S5, line 614, covers replacement approval, stale-bound posts and cancellation without state changes. |
| **N6R2-4** | **CLOSED — gate corrected** | §4, lines 358–363, and §10 OQ-5, line 626, explicitly reopen the contract dependency and block A6b code until accepted schema versions, complete types, identities and deep-link inputs are recorded. This satisfies the permitted open-gate resolution; the schemas themselves remain outstanding. |
| **N6R2-5** | **CLOSED** | §5, lines 380–396, correctly distinguishes Wednesday 08:00/Tuesday from Wednesday 10:00/Wednesday and advances the candidate at 09:00. §9 S2–S4, lines 611–613, adds the separate real render-dispatch takeover, scheduler-entry recovery and successful duplicate-event replay scenarios. |

No new in-scope **N6R3-n** issues found; no replacement wording required.

**A6b implementation remains blocked by OQ-5.** This approval verifies the revised design requirements; runtime recovery remains to be demonstrated by the specified tests.