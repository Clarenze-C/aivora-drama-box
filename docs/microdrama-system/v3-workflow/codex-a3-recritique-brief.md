# Codex critique: A3 design note v1.1 — round 2 (scoped to the round-1 findings)

Note: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A3-design-note.md` **v1.1** (committed
14 Nov). GLM applied the round-1 rulings (`a3-critique-rulings.md`; your round-1 report
`codex-a3-note-critique.md`, N3-1..N3-10). **Round 2: re-check those ten findings only**; new defects
from the round-1 edits are in scope. Architecture you confirmed stays settled.

Binding context: `phase-A-spec.md` v0.3, `A1-design-note.md` v1.2, `phase-A0-spec.md` v0.4 (A0-D fix1
tree at `.scratch/a0d-gateway` — read-only cross-check), `SPEC-v3.md` v0.4.6. Code (read-only):
`microdrama/src/microdrama/` on `feat/microdrama-m0-m4`.

## Answer, per finding (N3-1..N3-10)

CLOSED / PARTIAL / REGRESSED, with `§`/`file:line` and replacement wording where not closed. Attention:
N3-2 (CANCELLED recovery vs `jobs.py:785`, `states.py:119`, the reconciler's NEEDS_RECONCILIATION-only
selection), N3-3 (observation vs admission split in `LlmStep.ensure`), N3-5 (the provider-op lock audit
vs `provider_ops.py:195-215`), N3-7 (rewind edges vs A1's episode state columns), N3-10 (the child
bootstrap test plan).

## Output

- Read-only; no writes. Final message at most about 100 lines.
- Issues `N3R2-1`… with severity **BLOCKING / SHOULD-FIX / NIT** and replacement wording.
- Verdict: **APPROVE** / **APPROVE-WITH-CHANGES** / **REWORK** (final round this weekend).
