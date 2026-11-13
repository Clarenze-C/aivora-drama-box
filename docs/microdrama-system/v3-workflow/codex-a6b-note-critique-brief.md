# Codex critique: A6b design note (phase A package A6b), before code — round 1

Note: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A6b-design-note.md` v1.0 (the V3 scheduler: try-lock singleton, durable periods, calendar triggers, catch-up). GLM wrote it; nobody has reviewed it yet.

Requirement: `phase-A-spec.md` **v0.3** (§0, §1, §6, §9.1, §9.2, §10 (A6b row), §11 A-T14), plus your binding wording in `codex-a-critique.md` and `codex-a-recritique.md` (AR-5 (the scheduler is critiqued before code)). It must also fit `A1-design-note.md` v1.2 (columns of the command table, lock order, migration allocation: A1 0028–0031, A2 from 0032).

Code (read-only): `/root/AIVORA/drama-box/microdrama/src/microdrama/`, `microdrama/migrations/`, `microdrama/tests/`
on `feat/microdrama-m0-m4`. Migrations 0026 (T031) and 0027 (A0-D) are in `/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/migrations/`.
Master: `SPEC-v3.md` **v0.4.6** (self-contained). A0: `phase-A0-spec.md` v0.4. A1: `A1-design-note.md` v1.2.

## Answer

1. **Singleton (§ try-lock):** exactly one scheduler under crash/restart; lock namespace shared correctly with other advisory locks.
2. **Durable periods and effect intents:** a period fires its effects exactly once across crashes; catch-up after downtime is bounded and correct (no flood, no skip).
3. **Calendar triggers:** time zone (19:00 Bangkok daily release; teaser 3 days before E1) and DST-free correctness; clock injection for tests.
4. **Interaction with A6a's outbox and A3's fence:** no effect bypasses the outbox; stale/fenced work is not scheduled.
5. **V1 coexistence, lock audit, test plan:** nothing can bypass STORY/CAST LOCK; tests prove A-T14 including a real kill of the lock holder.
6. **The note's 7 open questions:** give your answer to each.
7. **Anything that would make the A6b build fail, change V1 behaviour, or contradict spec v0.3, A0 v0.4 or A1 v1.2.**

## Output

- Read-only; no writes. Final message at most about 150 lines.
- Issues use `N6-1`…, with severity **BLOCKING / SHOULD-FIX / NIT**, `file:line` where it applies, and replacement wording.
- Verdict: **APPROVE** / **APPROVE-WITH-CHANGES** / **REWORK**.
