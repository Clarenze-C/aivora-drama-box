# A6b design note (GLM): the V3 scheduler (phase A package A6b)

Orchestrator: Opus, 11 Nov 2026. You write the **design note** that the A6b build will follow. Codex
critiques it before any code is written (spec §10, AR-5). **This job writes one file and no code.**

## Read first

All files are in `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/`:
1. `phase-A-spec.md` **v0.3**: §0, §1, §6, **§9.1**, §9.2 (only what the scheduler role needs at
   startup), §10 (the A6b row), §11 (A-T14). This is the requirement.
2. `codex-a-critique.md`: AC-20 and AC-21 replacement wording (binding, per spec §0).
3. `codex-a-recritique.md`: **AR-5** (binding).
4. `A1-design-note.md` **v1.2**: §1 (migrations 0028–0031) and §9 (lock audit).
5. `a-factmap.md`: facts about today's code.
6. `SPEC-v3.md` §1 (19:00 Asia/Bangkok release), §3.3 (the 09:00 summary), §9.4 (throughput SLO) and
   §9 generally (buffer).

Code (read only): `/root/AIVORA/drama-box/microdrama/src/microdrama/`, `microdrama/migrations/`,
`microdrama/tests/` on branch `feat/microdrama-m0-m4`. Read especially `scheduling/service.py` (the
selectors, and the GPU and worker sweeps at `:822–835`) and `scheduling/__main__.py`. **Cite `file:line`
for every claim about existing code.**

## Write

`/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A6b-design-note.md`, at most about 450 lines.
Sections:

1. **Migration allocation.** Packages A2–A6a, which come before A6b, aren't all designed yet, so **name
   your migrations `A6b-1`, `A6b-2`…**. The number is assigned at build time after re-auditing the tail.
   Applied migration bytes are never edited.
2. **Exact guarded DDL:** `scheduler_firings(trigger, period_key)` with its unique key, the durable effect
   intents, any health/tick records, and the catalog updates.
3. **The singleton (AR-5):**
   - `pg_try_advisory_lock(<namespaced key>)` on a **dedicated connection**: the key derivation, the
     connection lifecycle, false → skip the tick (never block), release in `finally`;
   - how lost ownership is detected, and how the scheduler then stops starting new actions;
   - a crash releases the lock.
4. **Periods and effects:**
   - for each trigger, what is committed together with its database effects, or with durable effect
     intents;
   - the multi-transaction direct actions (GPU and worker sweeps) as intents, keeping their own canonical
     operation and recovery identities;
   - how an unfinished effect stays recoverable independently of the firing marker.
5. **Calendar triggers:** `CalendarTrigger(local_time, tz='Asia/Bangkok')`, `period_key` = the local date,
   DST-free Bangkok time, the 09:00 summary and the SLO checks; **catch-up fires at most the latest missed
   period** per trigger.
6. **Definitions as queries:** the SLO window (rolling 7 days), the buffer, and health (last successful
   tick ≤ 3 × the interval; errors per tick).
7. **V1 coexistence:** the legacy selectors stay for V1 seasons only; no V3 job bypasses STORY LOCK or
   CAST LOCK. List every selector and its version guard (consistent with the A1 note §7).
8. **Lock audit (spec §6):** every transaction the scheduler owns, with its locks in order.
9. **Test plan:** A-T14 → concrete test files and cases: concurrent ticks (one runs, **the other skips
   without blocking**), lost ownership stops new actions, a multi-transaction sweep's unfinished effect is
   recovered, catch-up fires once, plus a real process death mid-tick.
10. **Open questions:** anything the spec doesn't settle, each with a recommendation.

## Limits

- Read-only except the note file.
- No tests, no systemd units, no network, no commits.
- Never print environment variables, keys or tokens.
- No deletion commands.
- Final message: the note's path and a 10-line summary.
