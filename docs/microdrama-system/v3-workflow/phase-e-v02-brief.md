# Phase E spec v0.2: apply the Goldfish rulings (GLM docs-only job)

Orchestrator: GLM (weekend runbook), 14 Nov 2026. **Docs only.**

Read: `phase-e-review/consolidated_review_report.md` (findings + Fix directions),
`phase-e-goldfish-rulings.md` (**all ACCEPTED**; B-1 takes the Stage-8 second-key arm — mix digest as
replay key, EDL hash stays pure), `phase-E-spec.md` v0.1.

Produce **v0.2** in place: fold every finding per its Fix direction (B-1 first). Never contradict
`SPEC-v3.md`/`DECISIONS.md`/accepted phases (B v0.6, C v0.4.1) or `phase-F-spec.md` v0.4's seam; no
acceptance row weakened; BLOCKED items reported. Header → v0.2, 14 Nov, citing the rulings file.

Hard limits: offline docs job; no pushes/merges/restarts/deletions; never print env vars or keys.
Commit on `feat/microdrama-m0-m4`: `docs(v3): phase E spec v0.2 — Goldfish rulings applied (GLM)`.
Final message: one line per Blocker/Major (applied / BLOCKED), grouped nits, commit hash, line count.
