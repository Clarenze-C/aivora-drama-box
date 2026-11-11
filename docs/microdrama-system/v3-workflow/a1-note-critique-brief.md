# Codex critique: A1 design note (phase A package A1), before code

Note: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A1-design-note.md`. GLM wrote it;
§12 holds the orchestrator's rulings on its open questions.

Requirement: `phase-A-spec.md` **v0.3** (§0–§3, §6, §10 A1 row, §11 A-T1..A-T6, A-T16), plus your binding
wording in `codex-a-critique.md` (AC-1..9, AC-22, AC-23, and the reader/writer inventory) and
`codex-a-recritique.md` (AR-3, AR-4, AR-6). Master: `SPEC-v3.md` v0.4.4. A0: `phase-A0-spec.md` v0.4.

Code (read-only): `/root/AIVORA/drama-box/microdrama/src/microdrama/`, `microdrama/migrations/`,
`microdrama/tests/` on `feat/microdrama-m0-m4`. Migration 0026 is in
`/root/AIVORA/drama-box/.scratch/t031-gate-h2/microdrama/migrations/`.

## Answer

1. **DDL (§2):**
   - Does 0029 reproduce **every** V1 rule from the 0002 CHECKs exactly, together with the 0007–0021
     approval guards?
   - Are the new tables guarded in the repo's pattern?
   - Is the `track_waits` view correct against AR-4: scope + track identity, unresolved operations even
     for cancelled or stale jobs, `logical_work_id` replacement, dismissals that only hide?
   - Any SQL that won't run on the repo's PostgreSQL version?
2. **The decision transaction (§5)** against spec §2.6/§2.7:
   - replay first;
   - one caller-owned transaction;
   - test handlers can never reach production;
   - `NOT_AVAILABLE` before any write.
3. **The command table (§6):** complete against spec §3 and AC-6? Is the activation by package right
   (AR-6)? Are the Reject semantics right (AR-3)?
4. **The `require_workflow` inventory (§7):** spot-check the `file:line` claims. Name every legacy entry
   point the note misses (the critique's inventory is the checklist).
5. **GPU safety (§8) and the lock audit (§9):** are the attachment points real and complete? Are the
   three recorded pre-existing inversions correctly owned by A2/A3, with nothing A1 itself introduces?
6. **The test plan (§10):** enough to prove A-T1..A-T6 and A-T16, including V1 byte-equality and the
   populated-V1 upgrade?
7. **Anything that would make the A1 build fail, change V1 behaviour, or contradict spec v0.3 or A0
   v0.4.**

## Output

- Read-only; no writes. Final message at most about 150 lines.
- Issues use `N1-1`…, with severity **BLOCKING / SHOULD-FIX / NIT**, `file:line` where it applies, and
  replacement wording.
- Verdict: **APPROVE** / **APPROVE-WITH-CHANGES** / **REWORK**.
