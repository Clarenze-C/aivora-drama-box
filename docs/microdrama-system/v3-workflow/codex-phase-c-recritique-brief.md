# Codex critique: phase C spec v0.3 — round 2 (scoped to the round-1 findings)

Spec: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-C-spec.md` **v0.3** (`6ce01a4`,
846 lines). GLM applied the round-1 rulings (`phase-c-critique-rulings.md`; your round-1 report
`codex-phase-c-critique.md`, PC-1..PC-16). **Round 2: re-check those sixteen findings only**; new
defects introduced by the round-1 edits are in scope. Architecture you accepted stays settled.

Binding context: `SPEC-v3.md` v0.4.6; `phase-A-spec.md` v0.3; `A1-design-note.md` v1.2;
`A2-design-note.md` v1.1/v1.2-in-flight; `phase-B-spec.md` v0.5/v0.6-in-flight. Code (read-only):
`microdrama/src/microdrama/` on `feat/microdrama-m0-m4`; ARISA SFW providers read-only.

## Answer, per finding (PC-1..PC-16)

CLOSED / PARTIAL (what remains) / REGRESSED, with `§`/`file:line` and replacement wording where not
closed. Pay particular attention to: PC-1 (entry helper vs A2 §5 setup approval); PC-2 (typed
contract growth vs `references/models.py:27`, `contracts/season.py:489`); PC-3 (candidate stamps vs
reroll invalidation); PC-4/PC-5 (voice binding + activation binding staleness); PC-6 (transaction-owned
adoption vs `references/service.py:287`); PC-7 (recovery admission + mount topology, C-T6).

## Output

- Read-only; no writes. Final message at most about 120 lines.
- Issues `PC5-1`… with severity **BLOCKING / SHOULD-FIX / NIT** and replacement wording.
- Verdict: **APPROVE** / **APPROVE-WITH-CHANGES** / **REWORK** (final round this weekend).
