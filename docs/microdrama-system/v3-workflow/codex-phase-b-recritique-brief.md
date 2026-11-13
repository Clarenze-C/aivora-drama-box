# Codex critique: phase B spec v0.5 — round 2 (scoped to the round-1 findings)

Spec: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-B-spec.md` **v0.5** (`cb8f8b5`,
838 lines). GLM applied the round-1 rulings (`phase-b-critique-rulings.md`; your round-1 report is
`codex-phase-b-critique.md`, PB-1..PB-16). **This is round 2: re-check the sixteen findings only.**
Do not re-litigate the architecture you already blessed; new defects introduced by the round-1 edits
are in scope.

Binding context: `SPEC-v3.md` v0.4.6 §4.1–§4.3, §15; `phase-A-spec.md` v0.3; `A1-design-note.md` v1.2;
`A2-design-note.md` (v1.1 in flight); `phase-A0-spec.md` v0.4; `phase-C-spec.md` v0.2/v0.3 for seams
only. Code (read-only): `microdrama/src/microdrama/` on `feat/microdrama-m0-m4`.

## Answer, per finding (PB-1..PB-16)

For each: **CLOSED** / **PARTIAL** (what remains) / **REGRESSED** (new damage), with `§`/`file:line`
and replacement wording where not closed. Pay particular attention to:

- PB-1: the completion seam vs the real runtime (`workers/runtime.py:245`, `core/jobs.py:676`) and the
  new D5 delta row;
- PB-2: generation-round identity vs `core/jobs.py:429` replay matching;
- PB-5: the two entry points into the shared tier-update operation (open-activation vs decision-context);
- PB-6: the B1 prompt registry vs the V2 `PromptManifest` (`contracts/v2.py:773`) staying untouched;
- PB-7/PB-8: the extension branch against A2's account hierarchy and the immutable count authorization;
- PB-15: the strengthened B-T5 (restricted role + negative controls + attempted-SQL capture) — is it
  now implementable as written?

## Output

- Read-only; no writes. Final message at most about 120 lines.
- Issues `PB5-1`… with severity **BLOCKING / SHOULD-FIX / NIT** and replacement wording.
- Verdict: **APPROVE** / **APPROVE-WITH-CHANGES** / **REWORK** (this is the final round this weekend).
