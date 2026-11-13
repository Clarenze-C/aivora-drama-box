# Codex critique: A3 design note (phase A package A3), before code — round 1

Note: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A3-design-note.md` v1.0 (revision fence, `cancel_in`, stale quarantine, cancelled-operation reconciliation, per-queue workers). GLM wrote it; nobody has reviewed it yet.

Requirement: `phase-A-spec.md` **v0.3** (§0, §1, §4, §6, §7.1, §7.4, §10 (A3 row), §11 A-T8, A-T12a, A-T18), plus your binding wording in `codex-a-critique.md` and `codex-a-recritique.md` (AC-14..AC-17 and the A0 runtime contract). It must also fit `A1-design-note.md` v1.2 (columns of the command table, lock order, migration allocation: A1 0028–0031, A2 from 0032).

Code (read-only): `/root/AIVORA/drama-box/microdrama/src/microdrama/`, `microdrama/migrations/`, `microdrama/tests/`
on `feat/microdrama-m0-m4`. Migrations 0026 (T031) and 0027 (A0-D) are in `/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/migrations/`.
Master: `SPEC-v3.md` **v0.4.6** (self-contained). A0: `phase-A0-spec.md` v0.4. A1: `A1-design-note.md` v1.2.

## Answer

1. **DDL (0035 and the `expected_content_revision` CHECK):** guarded; correct; no conflict with 0026/0027.
2. **The fence (§3):** one helper; every call site listed and real (spot-check `file:line`); season- vs episode-scope correct; quarantine keeps money accounting normal.
3. **`JobService.cancel_in` (§4):** transaction-owned; cancels only what it may; cancelled-operation reconciliation never re-submits; interacts correctly with A0-D's `LlmStep`/`Deferred`.
4. **Per-queue workers (§5):** process set and CLI; no lane added; shutdown and crash behaviour.
5. **Command table, lock audit, V1 unchanged, test plan (§6–§9):** the open lock-audit row from A1 §9 is closed correctly; tests prove A-T8, A-T12a and A-T18.
6. **Anything that would make the A3 build fail, change V1 behaviour, or contradict spec v0.3, A0 v0.4 or A1 v1.2.**

## Output

- Read-only; no writes. Final message at most about 150 lines.
- Issues use `N3-1`…, with severity **BLOCKING / SHOULD-FIX / NIT**, `file:line` where it applies, and replacement wording.
- Verdict: **APPROVE** / **APPROVE-WITH-CHANGES** / **REWORK**.
