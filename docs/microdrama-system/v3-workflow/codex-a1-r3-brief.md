# Codex critique: A1 design note v1.3 — round 3 (verification)

Note: `A1-design-note.md` **v1.3** (`b894bbe`). GLM applied the round-2 findings
(`a1-note-rev3-brief.md`; your reports: `codex-a1-note-critique.md` N1-1..18,
`codex-a1-note-recritique.md` N1R-1..12, verdict REWORK with 3 BLOCKING). **Round 3 authorized by
the operator (rule-7 waiver, 14 Nov): re-check N1R-1..N1R-12 only.** Architecture settled; new
defects from the edits in scope.

Binding context: `phase-A-spec.md` v0.3 (A is coordinator), `A2-design-note.md` v1.3 (parked —
cross-check only), `A3-design-note.md` v1.3+R4-apply, `phase-A0-spec.md` v0.4, `SPEC-v3.md` v0.4.6.
Code (read-only): `microdrama/src/microdrama/` on `feat/microdrama-m0-m4`.

## Answer, per finding (N1R-1..12): CLOSED / PARTIAL / REGRESSED, with §/file:line + replacement
wording where not closed. Special attention: N1R-1 (the recursive view DDL compiles), N1R-2 (the V1
schema pin preserves frozen bytes — the in-memory probe objection), N1R-3 (extension approval
uniqueness vs `M/0002:208`), N1R-8 (lock ownership across the real advisory sites).

## Output: read-only; ≤100 lines; issues `N1R3-n` BLOCKING/SHOULD-FIX/NIT + replacement wording;
verdict **APPROVE / APPROVE-WITH-CHANGES / REWORK**.
