# Phase F spec v0.2: apply the Goldfish rulings (GLM docs-only job)

Orchestrator: GLM (weekend runbook), 13 Nov 2026. **Docs only — no code edits, no worktree, no tests.**

## Read first (absolute paths)

- `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-f-review/consolidated_review_report.md`
  — 73 findings (4 Blocker / 33 Major / 36 Nit), Stage-8 resolutions for CON-B1/CON-B2.
- `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-f-goldfish-rulings.md` — **all
  ACCEPTED**; the rulings' concrete choices are binding (in-place date UPDATE; CON-B2 option (a)
  synthetic carrier; F5 conditionally blocked on O-8; extend C's picks engine; `metadata_draft_versions`;
  teaser charged to SEASON_SETUP; CONTINUED/RESUMED defined; etc.).
- `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-F-spec.md` — current v0.1 (567 lines).
- Cross-check only: `phase-C-spec.md` (picks engine, C-B1 register), `phase-B-spec.md` v0.4/0.5
  (§15/§16 conventions), `SPEC-v3.md` §9/§12.6, `f-factmap.md`.

## The job

Produce **v0.2** of `phase-F-spec.md` in place per the rulings: all four Blockers (CON-B3 writes
"F5 conditionally blocked on the operator's O-8 ruling" with the recommendation — it does NOT decide
O-8), all 33 Majors (including the three [format] sections), the grouped Nits. Extra rules:

1. Never contradict `SPEC-v3.md`/`DECISIONS.md`; O-8 stays OPEN (OPERATOR); no acceptance row weakened.
2. CON-M6's C-side delta is only *recorded* as a crossing-register note — do not edit phase-C-spec.md.
3. If a ruling cannot be integrated without contradiction, stop, leave it out, report BLOCKED.
4. Version header → v0.2, 13 Nov, "Goldfish rulings applied per `phase-f-goldfish-rulings.md`".

## Hard limits

Offline docs job: no model/network calls, no pushes, no merges, no service restarts, no deletion
commands, never print environment variables or keys. Commit on `feat/microdrama-m0-m4`:
`docs(v3): phase F spec v0.2 — Goldfish rulings applied (GLM)`.

## Report

Final message: one line per Blocker/Major (applied / BLOCKED + why), the grouped-Nit buckets, the
commit hash, and the v0.2 line count. No separate report file.
