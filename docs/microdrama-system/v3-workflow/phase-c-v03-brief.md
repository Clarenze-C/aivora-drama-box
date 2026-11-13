# Phase C spec v0.3: apply the Codex round-1 critique rulings (GLM docs-only job)

Orchestrator: GLM (weekend runbook), 13 Nov 2026. **Docs only — no code, no tests.**

Read: `codex-phase-c-critique.md` (16 findings + Replacement paragraphs), `phase-c-critique-rulings.md`
(**all ACCEPTED**; one-line directions binding), `phase-C-spec.md` v0.2 (734 lines), cross-check
`phase-A-spec.md` v0.3, `A1-design-note.md` v1.2, `A2-design-note.md` (setup approval §5), `phase-B-spec.md`.

Produce **v0.3** in place: fold every replacement into the sections it corrects (PC-1 entry helper;
PC-2 CD2 growth; PC-3 candidate stamps; PC-4 voice binding/preimage; PC-5 activation binding; PC-6
adoption helper; PC-7 lock safety model; PC-8 CD4; PC-9 dispatch policy; PC-10 C5-note scope; PC-11
per-voice rights; PC-12 refresh scope; PC-13 likeness split; PC-14 extension scope; PC-15 seed
persistence; PC-16 gate re-map). Replacement wording wins; never contradict `SPEC-v3.md`/`DECISIONS.md`;
never weaken an acceptance row; O-C1/O-C9 stay OPEN (OPERATOR); if a replacement cannot be integrated,
stop, leave it out, report BLOCKED. Version header → v0.3, 13 Nov, citing the rulings file.

Hard limits: offline docs job; no pushes/merges/restarts/deletions; never print env vars or keys.
Commit on `feat/microdrama-m0-m4`: `docs(v3): phase C spec v0.3 — Codex round-1 critique applied (GLM)`.
Final message: one line per finding (applied / BLOCKED), commit hash, line count. No report file.
