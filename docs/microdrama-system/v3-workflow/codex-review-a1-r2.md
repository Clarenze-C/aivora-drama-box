**FIX-REQUIRED** for `57df5a9...3bd8c90`. Eight findings closed; three require fixes.

1. **A1V2-1 — BLOCKING · A1V-1 PARTIAL.** [v3_gates.py:667](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/core/v3_gates.py:667) orders terminal facts by timestamp and random UUID. [0030:98](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/migrations/0030_v3_tracks_and_gates.sql:98) defaults timestamps to transaction-start `now()`. An earlier-started transaction can supersede a replacement *after* an APPROVE yet sort before it. Supersession leaves revision/fence unchanged, so the old approval still authorizes advancement. Equal timestamps can produce the same failure through UUID ordering. Both reproduced with the current function and in-memory SQL. **Fix:** persist monotonic terminal-event ordering under the scope lock; test reversed transaction-start order and equal timestamps.

2. **A1V2-2 — SHOULD-FIX · A1V-9 PARTIAL.** [v3_gates.py:294](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/core/v3_gates.py:294) classifies every ordinary season decision as planning. Consequently LAUNCH and TEASER_FINAL emit `track.advanced` with planning state; a LAUNCH callback changing `release_state` still produces a planning→planning event. Reproduced in memory. **Fix:** select the event’s track/state column by gate, including release gates; assert payloads alongside event counts, replay and rollback.

3. **A1V2-3 — SHOULD-FIX · A1V-11 REGRESSED.** [identity_lock.py:280](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/references/identity_lock.py:280) now calls `require_workflow` before distinguishing an absent season. A missing-season lookup previously returned `None`; it now raises `NotFound`, also changing public `current_lock`. Comparative probes confirmed this. V3 refusal and projection isolation are fixed. **Fix:** preserve `None` for missing seasons while refusing existing V3 seasons; add the absent-season regression case.

The remaining findings are **CLOSED**; no further changes required:

| Finding | Evidence |
|---|---|
| A1V-2 | Track locks precede leaf locks in the audited paths: [leases.py:1091](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/rendering/leases.py:1091), [v3_tracks.py:356](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/core/v3_tracks.py:356). Competing-connection tests added. |
| A1V-3 | Single revision writer advances lock-approval fences; callback helper writes state only: [v3_gates.py:285](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/core/v3_gates.py:285). |
| A1V-4 | Resolved V3 work requires tracking; V1 replay precedes ancestry refusal: [jobs.py:493](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/core/jobs.py:493). |
| A1V-5 | Complete extension-range resolution and covering-wait checks: [v3_tracks.py:163](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/core/v3_tracks.py:163), [v3_gates.py:585](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/core/v3_gates.py:585). |
| A1V-6 | HTML carries episode identity and feedback; gate/action matrix added: [v3_api.py:124](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/review/v3_api.py:124). |
| A1V-7 | Replacement trigger sorts after retained BEFORE guards: [0029:109](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/migrations/0029_v3_gate_rules.sql:109). |
| A1V-8 | Nonlocking owner check precedes track errors, followed by authoritative recheck: [v3_gates.py:385](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/core/v3_gates.py:385). |
| A1V-10 | Unshipped planning edges refuse before writes: [v3_tracks.py:446](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/core/v3_tracks.py:446). |

A1V-1’s retroactive red is reconstructed evidence, not a pristine pre-fix run; that provenance alone does not disqualify the fix. The ordering failures above prevent closure.

Read-only verification: all 15 changed Python files parse; `git diff --check` passes. Probes used memory only. PostgreSQL suites and the decisive full gate were not independently rerun.