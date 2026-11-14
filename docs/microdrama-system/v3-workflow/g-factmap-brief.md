# Phase G fact map (GLM swarm): today's code for live qualification, composed restore, all-gate composition and the LIVE pilot

Orchestrator: GLM (weekend runbook), 14 Nov 2026. A phase G spec will be written from your facts.
**Facts only: no design, no recommendations. Read-only. Write no files.** Whole fact map in your
**final message**.

## Where
- Repo `/root/AIVORA/drama-box`, branch `feat/microdrama-m0-m4`. Code `microdrama/src/microdrama/`
  (`S/…`), migrations `microdrama/migrations/` (`M/…`), tests `microdrama/tests/` (`X/…`).
- Requirement context, skimmed: `docs/microdrama-system/v3-workflow/SPEC-v3.md` §16.2–§16.3 (partial
  milestones; LIVE quality and throughput), §12.5 (backups and restore), §15.1 phase G row (V3-AT-14,
  17, 32, 34, the cross-system lock's live half, LIVE §16.3), §15.2 R-IDs owned by G.

## Rules
- Cite `file:line` + the decisive line (≤2 lines). NOT FOUND + search terms if absent. Never guess.
- ≤350 lines, tables. Never print env vars, `.env`, keys, tokens.

## Facts needed
1. **Backups/restore today:** §12.5 surfaces — what backs up DB + objects, any restore tooling/tests,
   scheduler/outbox/jobs resume-after-restore behavior, notification ambiguity handling.
2. **All-gate composition:** any end-to-end/composition tests across gates today (or NOT FOUND);
   the closest existing composed acceptance runs (make pilot? PILOT-REPORT patterns).
3. **`dramabox-llm` + Pro off-pace (V3-AT-14):** A0-R1/A0-D surfaces for provider refusal and
   production pause w/ bot alert (read-only cross-check of `.scratch/a0d-gateway` tree + the
   `dramabox-llm` role in `/root/.claude/models.json` — never print secrets).
4. **LIVE pilot scaffolding:** `PILOT-REPORT.md` conventions, pilot phases (screen/full), cost/quota
   metering per provider, the benchmark service's live seams (T031 lineage).
5. **Cross-system lock live half:** ARISA-side lock code paths (read-only) + drama-box's (from the
   C spec's design) — what a live AT-28 test needs.
6. **Throughput measurement (§16.3/MA11):** any per-platform throughput tracking, or NOT FOUND.
7. **Gaps:** what G needs that doesn't exist.
