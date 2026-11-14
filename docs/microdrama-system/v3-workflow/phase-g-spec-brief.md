# Phase G spec draft (GLM, docs only): live qualification, composed restore, all-gate composition, the LIVE pilot

Orchestrator: GLM (weekend runbook), 14 Nov 2026. **Write one file:**
`/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md`, **v0.1 DRAFT**. No code,
no other file. Goldfish + Codex critique follow. If `phase-G-spec.md` already exists, you are resuming.

## Binding inputs (read fully)

- `SPEC-v3.md` **v0.4.6**: §16.2 (partial milestones), §16.3 (LIVE quality and throughput),
  §12.5 (backups and restore), §15.1 phase G row (V3-AT-14, 17, 32, 34, the cross-system lock's live
  half, LIVE §16.3), §15.2 (G's R-IDs), §3.3 (the Dramabox Bot), §11 (cost/quota meter and pilot).
- `DECISIONS.md`: pilot/benchmark rows (T031 lineage, $8 envelope conventions), the bot rows.
- `g-factmap.md` (cite as `FM §n`; spot-check read-only).
- Contracts: `phase-A-spec.md` v0.3; `A1-design-note.md` v1.3; accepted **B v0.6, C v0.4.1, E v0.4**;
  `phase-F-spec.md` v0.4; `phase-A0-spec.md` v0.4; the T031 run-readiness spec v0.3 (G's LIVE pilot
  inherits its metering/verification discipline).
- Style model: `phase-C-spec.md`/`phase-E-spec.md` (accepted chains' shape).

## What the spec must decide

1. **Records:** the pilot run + phases (screen/full), per-destination live qualification evidence,
   restore point + composed-restore proof, throughput observations, the all-gate composition run
   record. Symbolic migrations `G-1…` (likely none — prefer records over schema; justify either way).
2. **`dramabox-llm` + Pro off-pace (V3-AT-14):** production pauses with a bot alert rather than
   switching providers silently — wire to A0's surfaces + the bot (§3.3); what "off pace" reads.
3. **Composed restore (V3-AT-32):** DB + objects restored together; scheduler/outbox/jobs resume
   without duplicate effects; notification ambiguity documented honestly.
4. **All-gate composition (V3-AT-34):** the end-to-end composition test across every gate (offline),
   its fixtures, and what it proves that per-phase tests don't.
5. **LIVE pilot (§16.3, V3-AT-17):** P0/P1/P2 phases; `PILOT-REPORT.md` with measured per-episode
   cost and quota per provider; the T031 discipline inherited (authorizations, verification,
   evidence); **all live/paid steps stay operator-gated** — G defines the scaffolding, never spends.
6. **Cross-system lock live half (AT-28's live arm):** what the live ARISA/Drama lock test needs,
   from C's design (read-only) — G owns only the live test procedure.
7. **Throughput (§16.3/MA11):** closed-interval observations (F's counter discipline), reporting.
8. **Build packages `G1…` in order,** acceptance rows mapped to V3-AT-14/17/32/34 where they can pass
   at their own package; notes-first routing where money/locks/migrations demand it.
9. **Open questions with recommendations.**

## Rules

- Never contradict the master/accepted phases; conflicts → open question. Facts carry `file:line` or
  `FM §n`; unverified → `UNVERIFIED`. Target 450–650 lines. No deletions; never print env/keys.
- **Final message:** ≤15 lines, then the file path.
