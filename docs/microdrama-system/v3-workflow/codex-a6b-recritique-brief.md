# Codex critique: A6b design note v1.1 — round 2 (scoped to the round-1 findings)

Note: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A6b-design-note.md` **v1.1**
(`8cd4453`, 589 lines). GLM applied the round-1 rulings (`a6b-critique-rulings.md`; your round-1 report
`codex-a6b-note-critique.md`, N6-1..N6-11, **plus N6-12** — the A-T14 test-plan expansion, which GLM
ratified applying as the direct test obligation of the accepted findings). **Round 2: re-check those
twelve findings only**; new defects from the round-1 edits are in scope.

Binding context: `phase-A-spec.md` v0.3, `A1-design-note.md` v1.2, `phase-A0-spec.md` v0.4,
`SPEC-v3.md` v0.4.6 (master citation updated v0.4.4 → v0.4.6). Code (read-only):
`microdrama/src/microdrama/` on `feat/microdrama-m0-m4` (scheduling/, rendering/janitor.py, core/events.py).

## Answer, per finding (N6-1..N6-12)

CLOSED / PARTIAL / REGRESSED, with `§`/`file:line` and replacement wording where not closed. Attention:
N6-1 (per-action ownership vs `scheduling/service.py:758-765`), N6-2 (INTENTS recovery identities vs
`rendering/janitor.py:169-179` event dedup), N6-3 (V1 key preservation), N6-4 (V1 cadence + cutover),
N6-6 (the two-minute LLM reconciler trigger), N6-12 (test-plan sufficiency).

## Output

- Read-only; no writes. Final message at most about 100 lines.
- Issues `N6R2-1`… with severity **BLOCKING / SHOULD-FIX / NIT** and replacement wording.
- Verdict: **APPROVE** / **APPROVE-WITH-CHANGES** / **REWORK** (final round this weekend).
