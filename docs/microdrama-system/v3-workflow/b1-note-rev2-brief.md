# B1 note revision v0.3: apply the round-2 rulings (GLM docs-only job)

Orchestrator: GLM (operator autonomy window), 14 Nov 2026. **Docs only.**

Read: `codex-b1-note-recritique.md` (B1R2-1/2 + Replacement paragraphs + the closed table),
`b1-recritique-rulings.md` (both ACCEPTED), `B1-design-note.md` v0.2. Cross-check the real code sites
cited (read-only): `qa/continuity_sources.py:127`, `references/v2_dispatch_context.py:204`.

Produce **v0.3** in place: fold both replacements (B1R2-1 guard placement inside entry transactions /
explicit workflow-check transactions for no-tx entries / ancestry-validated scopes + direct-call
fixture tests; B1R2-2 the extension-scope check defined against a column that exists). Replacement
wording wins; never contradict the accepted specs; no acceptance row weakened; BLOCKED reported.
Header → v0.3, 14 Nov, citing the rulings file.

Hard limits: offline docs job; no pushes/merges/restarts/deletions; never print env vars or keys.
**Commit yourself**: `docs(v3): B1 note v0.3 — round-2 rulings applied (GLM)`.
Final message: one line per finding, commit hash, line count. No report file.
