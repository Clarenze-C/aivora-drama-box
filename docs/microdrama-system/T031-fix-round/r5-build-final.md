**R5 build complete** — `feat/t031-r5`, `make check` green at the final commit (`275 passed`, all offline checks passed).

- **R5a** — `2757e51` + `2e42540`: image entrypoint, gateway ready state, flag through the composed create request; **RR-T3 image rebuild still blocked on disk** (5.5G free, needs ≥12GiB; refused twice, no push attempted).
- **R5b** — `fab3e7e`: ready gate, typed boot failures, timings, role/subject-scoped staging (previous session; suites re-verified green).
- **R5c** — `b6d3b48`: predicted schema from the pinned image + seal evidence, one commit (previous session; suites re-verified green).
- **Base repairs** — `3b5ea3f`: `_validate_model_rights` read a nonexistent `payload` column (red: `column "payload" does not exist`) and two pre-existing R5b regressions in the H-1/RR-T4 tests (verified failing at `b6d3b48`) — all fixed red-first.
- **R5d** — `5ec7a56`: `t031_prepare_run.py` register/author/quote/verify; RR-T9's 5 tests green including preflight PASS through the **real** `ExperimentalPresetPolicy` (no monkeypatch) on the registered rows.
- **R5e** — `2876466`: `t031_results.py`; an all-NOT_RUN export reproduces the operator's real template byte-for-byte; unknowns blank, never 0.
- **R5f** — `1eddc83`: `t031_billing_verify.py` thin wrapper over the existing verifier — MATCH/loud-MISMATCH/idempotent-replay proven against real PostgreSQL with the per-pod ingest first.
- **Close-out** — `6bcdbfa`: two files shipped unformatted in `b6d3b48` were failing `make lint` at the R5c tip; gate restored.

Untracked (deletions forbidden): `microdrama/.venv` (symlink) and `microdrama/preflight.json` (pre-`6bcdbfa` test artifact).

Report: `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/r5-build-REPORT.md` (top marker: `R5: ALL PACKAGES DONE`; resume items: the disk-gated RR-T3 rebuild + Codex review of `3b5ea3f..6bcdbfa`).
