# Phase B spec v0.6: apply the round-2 rulings (GLM docs-only job)

Orchestrator: GLM (weekend runbook), 13 Nov 2026. **Docs only.**

Read: `codex-phase-b-recritique.md` (PB5-1..5 + the per-finding table), `phase-b-recritique-rulings.md`
(**all 5 ACCEPTED**; directions binding), `phase-B-spec.md` v0.5.

Produce **v0.6** in place: fold PB5-1..5 into §9 (lifecycle guards + extension revision owner), §2.4/§11
(D5 ships in B2), §3.2 (initial-edge-only advance), §8/B-T11 (authorization creation/validation split),
§2/§2.1 + B:142 (`PayoffDebt.debt_id` reuse). Replacement wording wins; never contradict
`SPEC-v3.md`/`DECISIONS.md`/phase-A; no acceptance row weakened; BLOCKED items reported, not forced.
Header → v0.6, 13 Nov: "round-2 rulings applied (GLM); awaiting Opus re-check — no round 3 run".

Hard limits: offline docs job; no pushes/merges/restarts/deletions; never print env vars or keys.
Commit on `feat/microdrama-m0-m4`: `docs(v3): phase B spec v0.6 — round-2 rulings applied (GLM)`.
Final message: one line per finding, commit hash, line count. No report file.
