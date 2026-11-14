# A1 note revision v1.4: apply the round-3 findings (GLM docs-only job)

Orchestrator: GLM (operator autonomy window, 14 Nov), 14 Nov 2026. **Docs only.**

Context: A1's round-3 verification (`codex-a1-r3.md`, verdict REWORK) found N1R3-1/2 BLOCKING +
N1R3-3..6 SHOULD-FIX. The operator has approved completing the cycle; an R4 verification follows.

Read: `codex-a1-r3.md` (each finding with §/file:line + replacement wording), `A1-design-note.md`
v1.3, cross-check `phase-A-spec.md` v0.3, `A3-design-note.md` v1.3 (accepted), and the real code
sites the findings cite (read-only).

Produce **v1.4** in place: fold every N1R3 replacement (N1R3-1 the approval-identity NULL partition
vs the two uniqueness indexes; N1R3-2 the Comfy submit ordering vs the real commit-before-HTTP
sequence at `comfy_jobs.py:611-630`; N1R3-3..6 per their wording). Replacement wording wins; never
contradict phase-A/SPEC-v3/accepted notes; no acceptance test weakened; BLOCKED items reported.
Header → v1.4, 14 Nov: "round-3 findings applied (GLM); R4 verification follows".

Hard limits: offline docs job; no pushes/merges/restarts/deletions; never print env vars or keys.
**Commit yourself**: `docs(v3): A1 note v1.4 — round-3 findings applied (GLM)`.
Final message: one line per finding, commit hash, line count.
