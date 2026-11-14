# Codex critique: phase C spec v0.4 — round 3 (verification)

Spec: `phase-C-spec.md` **v0.4** (`deb850c`). GLM applied your round-2 rulings (`phase-c-recritique-rulings.md`;
your reports: `codex-phase-c-critique.md` PC-1..16, `codex-phase-c-recritique.md` PC5-1..7).
**Round 3 was authorized by the operator (rule-7 waiver, 14 Nov): re-check PC5-1..PC5-7 only.**
Architecture settled; new defects from the round-2 edits in scope.

Binding context: `SPEC-v3.md` v0.4.6; `phase-A-spec.md` v0.3; `A1-design-note.md` v1.2;
`A2-design-note.md` v1.2; `phase-B-spec.md` v0.6. Code (read-only): `microdrama/src/microdrama/` on
`feat/microdrama-m0-m4`; ARISA SFW providers read-only.

## Answer, per finding (PC5-1..PC5-7): CLOSED / PARTIAL / REGRESSED, with §/file:line and replacement
wording where not closed. Special attention: PC5-1 (freshness vs invalidation generation vs current
authority), PC5-2 (shared recovery admission contract + mount/time clauses).

## Output: read-only; ≤120 lines; issues `PC6-n` BLOCKING/SHOULD-FIX/NIT + replacement wording;
verdict **APPROVE / APPROVE-WITH-CHANGES / REWORK**.
