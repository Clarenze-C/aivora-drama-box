# Phase F spec v0.3: apply the Codex round-1 critique rulings (GLM docs-only job)

Orchestrator: GLM (weekend runbook), 13 Nov 2026. **Docs only.**

Read: `codex-phase-f-critique.md` (PF-1..17 + Replacement paragraphs), `phase-f-critique-rulings.md`
(**all 17 ACCEPTED**; one-line directions binding, incl. PF-9 = first option), `phase-F-spec.md` v0.2.
Cross-check: `phase-A-spec.md` v0.3, `A1-design-note.md` v1.2, `phase-C-spec.md` v0.2/v0.3-in-flight,
`f-factmap.md`.

Produce **v0.3** in place: fold every replacement into the sections it corrects (version-selected
adapters §4/§7.3; admission comparator; carrier crossing §2.2 + F-3; season DAG; command schedule
resolution; submit revalidation; rebinding; extension carry-forward; Gate-2 feedback extension FD
crossing; A4 dependency registration; completion over identities; binding lifecycle; MISSED precedence;
thumbnail candidate freshness; F5 conditional delivery; gate re-map; buffer/interval counters).
Replacement wording wins; never contradict `SPEC-v3.md`/`DECISIONS.md`/phase-A; no acceptance row
weakened; O-8 stays OPEN (OPERATOR) and F5 conditionally blocked; E-contract stays a declared
dependency; BLOCKED items reported, not forced. Header → v0.3, 13 Nov, citing the rulings file.

Hard limits: offline docs job; no pushes/merges/restarts/deletions; never print env vars or keys.
Commit on `feat/microdrama-m0-m4`: `docs(v3): phase F spec v0.3 — Codex round-1 critique applied (GLM)`.
Final message: one line per finding, commit hash, line count. No report file.
