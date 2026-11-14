# Codex critique: A2 design note v1.3 — round 4 (verification)

Note: `A2-design-note.md` **v1.3** (`9d0af9c`). GLM closed the five round-3 PARTIALs
(`a2-note-rev3-brief.md`; your reports: `codex-a2-note-recritique.md` N2R2-1..10,
`codex-a2-r3.md` the five PARTIAL). **Round 4 authorized by the operator (rule-7 waiver, 14 Nov):
verify those closures.** Architecture settled; new defects from the round-3 edits in scope.

Binding context: `phase-A-spec.md` v0.3, `A1-design-note.md`, `SPEC-v3.md` v0.4.6 §12.3.
Code (read-only): `microdrama/src/microdrama/` on `feat/microdrama-m0-m4` (budget/, billing.py,
analytics/cost.py, api routes).

## Answer: each of the five PARTIAL items CLOSED/PARTIAL/REGRESSED, with §/file:line + replacement
wording where not closed. Special attention: the global lock-order table (the #6→#7→#6 billing cycle),
the hierarchy helper's aggregate-account path, and the barrier-vs-serialization placement.

## Output: read-only; ≤100 lines; issues `N2R4-n` BLOCKING/SHOULD-FIX/NIT + replacement wording;
verdict **APPROVE / APPROVE-WITH-CHANGES / REWORK**.
