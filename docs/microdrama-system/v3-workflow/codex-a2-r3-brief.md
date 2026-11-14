# Codex critique: A2 design note v1.2 — round 3 (verification)

Note: `A2-design-note.md` **v1.2** (`8bb2089`). GLM applied your round-2 rulings
(`a2-recritique-rulings.md`; your reports: `codex-a2-note-critique.md` N2-1..15,
`codex-a2-note-recritique.md` N2R2-1..10). **Round 3 authorized by the operator (rule-7 waiver,
14 Nov): re-check N2R2-1..N2R2-10 only.** Architecture settled; new defects from the round-2 edits in
scope.

Binding context: `phase-A-spec.md` v0.3, `A1-design-note.md` v1.2, `SPEC-v3.md` v0.4.6 §12.3.
Code (read-only): `microdrama/src/microdrama/` on `feat/microdrama-m0-m4` (budget/, billing.py,
analytics/cost.py, api routes for Costs).

## Answer, per finding (N2R2-1..10): CLOSED / PARTIAL / REGRESSED, with §/file:line and replacement
wording where not closed. Special attention: N2R2-1 (aggregate account in the hierarchy helper),
N2R2-4 (the outer billing lock cycle #6→#7→#6), N2R2-6 (valid DDL, amendment matching), N2R2-10
(barrier placement vs serialization).

## Output: read-only; ≤100 lines; issues `N2R3-n` BLOCKING/SHOULD-FIX/NIT + replacement wording;
verdict **APPROVE / APPROVE-WITH-CHANGES / REWORK**.
