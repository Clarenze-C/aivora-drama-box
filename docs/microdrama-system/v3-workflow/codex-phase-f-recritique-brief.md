# Codex critique: phase F spec v0.3 — round 2 (scoped to the round-1 findings)

Spec: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-F-spec.md` **v0.3** (committed
13 Nov; header cites `phase-f-critique-rulings.md`). GLM applied the round-1 rulings
(`phase-f-critique-rulings.md`; your round-1 report `codex-phase-f-critique.md`, PF-1..PF-17).
**Round 2: re-check those seventeen findings only**; new defects from the round-1 edits are in scope.
O-8 stays OPEN (OPERATOR; F5 conditionally blocked) and the E-contract stays a declared dependency —
flag, don't demand.

Binding context: `SPEC-v3.md` v0.4.6; `phase-A-spec.md` v0.3; `A1-design-note.md` v1.2;
`phase-C-spec.md` v0.3/v0.4-in-flight. Code (read-only): `microdrama/src/microdrama/` on
`feat/microdrama-m0-m4`.

## Answer, per finding (PF-1..PF-17)

CLOSED / PARTIAL / REGRESSED, with `§`/`file:line` and replacement wording where not closed. Attention:
PF-1 (version-selected adapters vs W09/A §1), PF-3 (carrier crossing vs `M/0002:62`, `M/0021:61`),
PF-6 (submit re-fencing barriers), PF-7 (rebinding), PF-8 (extension carry-forward), PF-16 (gate
re-map).

## Output

- Read-only; no writes. Final message at most about 120 lines.
- Issues `PF5-1`… with severity **BLOCKING / SHOULD-FIX / NIT** and replacement wording.
- Verdict: **APPROVE** / **APPROVE-WITH-CHANGES** / **REWORK** (final round this weekend).
