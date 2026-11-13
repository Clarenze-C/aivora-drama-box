# Codex critique: A2 design note v1.1 — round 2 (scoped to the round-1 findings)

Note: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md` **v1.1** (`b454832`,
954 lines). GLM applied the round-1 rulings (`a2-critique-rulings.md`; your round-1 report
`codex-a2-note-critique.md`, N2-1..N2-15). **Round 2: re-check those fifteen findings only.** The
architecture you confirmed (allocation, setup-inside-season arithmetic) is settled; new defects
introduced by the round-1 edits are in scope.

Binding context: `phase-A-spec.md` v0.3, `A1-design-note.md` v1.2, `SPEC-v3.md` v0.4.6 §12.3.
Code (read-only): `microdrama/src/microdrama/` on `feat/microdrama-m0-m4` (budget/, billing.py,
analytics/cost.py, api routes for Costs).

## Answer, per finding (N2-1..N2-15)

For each: **CLOSED** / **PARTIAL** (what remains) / **REGRESSED**, with `§`/`file:line` and replacement
wording where not closed. Pay particular attention to:

- N2-1: the mutex-first re-read against the real season lock paths;
- N2-4/N2-5: the serialized amendment lineage and the full outer-transaction lock audit (was the
  billing-ingestion cycle (#6→#7→#6) actually resolved with a defined global order?);
- N2-6/N2-7: cleanup exemptions vs the real trigger set; step identities 5–9 vs `budget_steps`;
- N2-9: the season_owners authorization against the actual Costs route;
- N2-15: whether the barrier tests are specified concretely enough to implement.

## Output

- Read-only; no writes. Final message at most about 120 lines.
- Issues `N2R2-1`… with severity **BLOCKING / SHOULD-FIX / NIT** and replacement wording.
- Verdict: **APPROVE** / **APPROVE-WITH-CHANGES** / **REWORK** (final round this weekend).
