# A3 note revision v1.1: apply the round-1 critique rulings (GLM docs-only job)

Orchestrator: GLM (weekend runbook), 13 Nov 2026. **Docs only.**

Read: `codex-a3-note-critique.md` (10 findings + Replacement paragraphs), `a3-critique-rulings.md`
(**all 10 ACCEPTED**; directions binding), `A3-design-note.md` (current), `phase-A-spec.md` v0.3,
`A1-design-note.md` v1.2, and for the A0-D integration points `.scratch/a0d-gateway/microdrama/src/microdrama/llm/`
(read-only cross-check only).

Produce **`A3-design-note.md` v1.1** in place: fold every replacement into its section (revision CHECK,
CANCELLED recovery path, permission split, cancellation fencing, lock audit, collector transaction,
rewind edges, exception semantics, worker identity, acceptance plan). Replacement wording wins; never
contradict `phase-A-spec.md`/`SPEC-v3.md`; no acceptance test weakened (A-T12a corrected to the reachable
path per N3-2); BLOCKED items reported, not forced. Header → v1.1, 13 Nov, citing the rulings file.

Hard limits: offline docs job; no pushes/merges/restarts/deletions; never print env vars or keys.
Commit on `feat/microdrama-m0-m4`: `docs(v3): A3 note v1.1 — round-1 critique applied (GLM)`.
Final message: one line per finding, commit hash, line count. No report file.
