# Phase C spec v0.2: apply the Goldfish rulings (GLM docs-only job)

Orchestrator: GLM (weekend runbook), 13 Nov 2026. **Docs only — no code edits, no worktree, no tests.**

## Read first (absolute paths)

- `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-c-review/consolidated_review_report.md`
  — the findings (2 Blocker / 27 Major / 46 Nit), with Stage-8 remedy steering for both Blockers.
- `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-c-goldfish-rulings.md` — **the
  rulings; every finding is ACCEPTED** with a direction. Where a ruling names a concrete choice
  (3 candidates per root item, one job per candidate, `<gen_seq>` segment, the BLK-2 mapping table,
  NULLS NOT DISTINCT, workflow_version='v1' predicate, etc.) that choice is binding for v0.2.
- `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-C-spec.md` — current v0.1 (490 lines).
- For cross-checking only: `phase-B-spec.md` v0.4 (C-B1 register pattern, §15/§16 conventions),
  `phase-A-spec.md` v0.3, `A1-design-note.md`.

## The job

Produce **v0.2** of `phase-C-spec.md` in place:

1. Apply both Blockers with their steering (initial-generation batch at setup-budget approval; the
   pick-kind → ref_kind/asset_kind mapping table + CHECK growth via C-7's version-aware pattern +
   ref_key namespacing; library items are reference_versions rows).
2. Apply all 27 Majors per the rulings table — including: drop migration C-3 (computed closure
   instead, renumber nothing else — keep symbolic names stable); re-gate C-T3/T4/T12/T14; add the
   command table and the C-B1-style contract-crossing register; C8 routed note-first.
3. Apply the grouped Nits (mechanical sweeps + the substantive ones listed in the rulings).
4. Add the two `[format]` sections (Alternatives Considered per B §16; Risks & Limits per B §15).
5. **Do NOT resolve** the two operator items (O-C1 neutral-source intake; the V1 lock carve-out N34):
   list them as OPEN (OPERATOR) open questions.
6. Never contradict `SPEC-v3.md`/`DECISIONS.md`; never weaken an acceptance row (re-gating moves
   clauses to the package where they can pass — it does not lower any bar); if a ruling cannot be
   integrated without contradiction, stop, leave it out, report BLOCKED.
7. Update the version header (v0.2, 13 Nov, "Goldfish rulings applied per `phase-c-goldfish-rulings.md`")
   and fix stale cross-references to v0.1.

## Hard limits

Offline docs job: no model/network calls, no pushes, no merges, no service restarts, no deletion
commands, never print environment variables or keys. Commit on `feat/microdrama-m0-m4`:
`docs(v3): phase C spec v0.2 — Goldfish rulings applied (GLM)`.

## Report

Final message: one line per Blocker/Major (applied / BLOCKED + why), the grouped-Nit buckets applied,
the commit hash, and the v0.2 line count. No separate report file.
