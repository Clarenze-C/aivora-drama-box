# A2 note revision v1.1: apply the round-1 critique rulings (GLM docs-only job)

Orchestrator: GLM (weekend runbook), 13 Nov 2026. **Docs only — no code, no tests.**

Read: `codex-a2-note-critique.md` (findings + Replacement paragraphs), `a2-critique-rulings.md`
(**all 15 ACCEPTED**; the one-line directions there are binding), `A2-design-note.md` (current),
`phase-A-spec.md` v0.3 §2/§7 (LOCK transaction, fence) for cross-checking.

Produce **`A2-design-note.md` v1.1** in place: fold every replacement into the note's sections (mutex
ordering §304-area, cap guard §79, amendment DDL §225/§234, lock audit §575, cleanup §343, steps §153/§182,
authorization §453, command wrapping §547, readers §245, forecast §492/§521, admission ordering §349,
acceptance §625). Replacement wording wins; integrate, don't diff-append. Never contradict
`phase-A-spec.md`/`SPEC-v3.md`/`DECISIONS.md`; never weaken an acceptance case (N2-15 strengthens);
if a replacement cannot be integrated, stop, leave it out, report BLOCKED. Update the version header
(v1.1, 13 Nov, "round-1 critique applied per `a2-critique-rulings.md`").

Hard limits: offline docs job; no pushes/merges/restarts/deletions; never print env vars or keys.
Commit on `feat/microdrama-m0-m4`: `docs(v3): A2 note v1.1 — round-1 critique applied (GLM)`.
Final message: one line per finding (applied / BLOCKED), commit hash, line count. No report file.
