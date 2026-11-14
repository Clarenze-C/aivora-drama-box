# A2 note revision v1.3 (GLM docs-only job)

Orchestrator: GLM (operator-approved R4 path), 14 Nov 2026. **Docs only.**

Context: v1.2 closed 5/10 round-2 findings; round 3 confirmed the rest partial. The heart is the
**global lock order for outer billing transactions** (ingestion, invoice verification, podless-create):
the revision must DEFINE the concrete order (e.g. bucket locks before the season mutex, deterministic
bucket ordering) that eliminates the #6→#7→#6 cycle — not restate that one exists.

Read: `codex-a2-note-recritique.md` (N2R2-1..10), `codex-a2-r3.md` (which five are PARTIAL and why),
`a2-recritique-rulings.md`, `A2-design-note.md` v1.2. Cross-check the real lock sites:
`budget/billing.py:295+`, `core/provider_ops.py:121-215`, `rendering/janitor.py`.

Produce **v1.3** in place: close every PARTIAL item per its replacement wording, with the lock-order
section written as an enforceable order table (transaction → locks in order → writes). Replacement
wording wins; never contradict phase-A/SPEC-v3; no acceptance test weakened; BLOCKED items reported.
Header → v1.3, 14 Nov: "round-3 residuals closed (GLM); operator-authorized R4 follows".

Hard limits: offline docs job; no pushes/merges/restarts/deletions; never print env vars or keys.
**Commit yourself**: `docs(v3): A2 note v1.3 — round-3 residuals closed (GLM)`.
Final message: one line per finding, commit hash, line count.
