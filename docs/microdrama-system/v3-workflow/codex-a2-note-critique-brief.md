# Codex critique: A2 design note (phase A package A2), before code — round 1

Note: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md` v1.0 (budget hierarchy: accounts, lookup, step budgets, hierarchy serialisation, cap amendments, forecasts, Costs data API). GLM wrote it; nobody has reviewed it yet.

Requirement: `phase-A-spec.md` **v0.3** (§0, §1, §5 (all), §6, §10 (A2 row + AR-6), §11 A-T9..A-T11), plus your binding wording in `codex-a-critique.md` and `codex-a-recritique.md` (AC-8, AC-10..AC-13, AR-2 and the money rules). It must also fit `A1-design-note.md` v1.2 (columns of the command table, lock order, migration allocation: A1 0028–0031, A2 from 0032).

Code (read-only): `/root/AIVORA/drama-box/microdrama/src/microdrama/`, `microdrama/migrations/`, `microdrama/tests/`
on `feat/microdrama-m0-m4`. Migrations 0026 (T031) and 0027 (A0-D) are in `/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/migrations/`.
Master: `SPEC-v3.md` **v0.4.6** (self-contained). A0: `phase-A0-spec.md` v0.4. A1: `A1-design-note.md` v1.2.

## Answer

1. **DDL (0032–0034):** guarded in the repo's pattern; CHECKs and the effective-cap derivation correct; nothing weakens 0016's per-kind rules or the $10 episode cap; SQL valid on the repo's PostgreSQL.
2. **Lookup and admission (§3):** explicit scope lookup (AC-10); the lock chain order matches spec §6 and the A1 lock audit; admission order (AC-12/AC-13) refuses before any write; no lost update under ≥2 concurrent admitters.
3. **STORY LOCK transaction and pre-LOCK protocol (§4, AR-2):** one caller-owned transaction; setup spend stays inside episodes × cap; replay-safe.
4. **Cap amendments (§5, AC-11):** approval-bound, append-only, effective only after the recorded approval; races with in-flight reservations.
5. **Forecasts and Costs API (§6):** match spec §5.5/§5.6; settled vs held vs forecast never mixed.
6. **Command table, lock audit, V1 unchanged, test plan (§7–§10):** complete; the pre-existing inversions A1 handed to A2 are actually removed; tests prove A-T9..A-T11 with real PostgreSQL and ≥2 connections.
7. **Anything that would make the A2 build fail, change V1 behaviour, or contradict spec v0.3, A0 v0.4 or A1 v1.2.**

## Output

- Read-only; no writes. Final message at most about 150 lines.
- Issues use `N2-1`…, with severity **BLOCKING / SHOULD-FIX / NIT**, `file:line` where it applies, and replacement wording.
- Verdict: **APPROVE** / **APPROVE-WITH-CHANGES** / **REWORK**.
