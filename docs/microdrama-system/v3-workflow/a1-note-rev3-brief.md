# A1 note revision v1.3 (GLM docs-only job)

Orchestrator: GLM (operator-approved A-track fix + R3 waiver), 14 Nov 2026. **Docs only.**

Context: A1's round-2 critique (`codex-a1-note-recritique.md`, verdict REWORK: N1R-1..3 BLOCKING,
N1R-4..12 SHOULD-FIX) was never applied — the item stopped before the weekend. The operator has
authorized the revision + an R3 verification (rule-7 waiver, 14 Nov).

Read: `codex-a1-note-recritique.md` (the per-finding table N1-1..N1-18 status + N1R-1..12 with
Replacement paragraphs), `A1-design-note.md` v1.2, `phase-A-spec.md` v0.3 (cross-check; A is
coordinator), `A2-design-note.md` v1.2/v1.3-in-flight and `A3-design-note.md` v1.2/v1.3-in-flight (the
notes must stay mutually consistent — the A2/A3 revisions are folding their own round-2 findings now).

Produce **v1.3** in place: fold every N1R replacement into its section (N1R-1 the recursive view DDL;
N1R-2 the V1 schema-pin adapter; N1R-3 extension approval uniqueness; N1R-4..12 per their wording,
incl. the command-table writes/jobs/events, the GPU transaction ownership audit against the real
`comfy_jobs.py`/`provider_ops.py` sites, the shutdown-predicate rework, direct-read guards, and the
A1 production-injection boundary). Replacement wording wins; never contradict phase-A/SPEC-v3; no
acceptance test weakened; BLOCKED items reported. Header → v1.3, 14 Nov: "round-2 findings applied
(GLM); operator-authorized R3 follows".

Hard limits: offline docs job; no pushes/merges/restarts/deletions; never print env vars or keys.
**Commit yourself**: `docs(v3): A1 note v1.3 — round-2 findings applied (GLM)`.
Final message: one line per finding (applied / BLOCKED), commit hash, line count.
