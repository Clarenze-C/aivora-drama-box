H-2 build complete — all packages done, tree clean, 25 commits on `feat/t031-fix3` through `0e34630`.

- **P1** — DONE `0bad31b` (modes, provenance, EXPIRED reads)
- **P2** — DONE `67500b6` (unresolved items, admission gate)
- **P3** — DONE `3a5710d` + `45e4f2a` (ambiguity, grace, deadline fence, death tests)
- **P4** — DONE `941ab6d` (lock order, create resolution, storage finalization, incident path)
- **HBF** — DONE `30d5e30`..`5790a45` (Codex HB-1..HB-14)
- **LF** — DONE `8810068`/`3b63acd`/`bdf1e2b` (GLM L-1..L-7)
- **P5** — DONE `0e34630` (this session): reviewed and kept the stopped session's re-applied WIP after recording reds against committed HEAD (`10 failed, 5 passed` P5 file; `3 failed` adapted ATs), then fixed two review findings (RECOVERY worlds now name their acquisition in the reconcile U4 loop and `finalize_terminal` fallback, with an AT-22 naming-factory guard) plus the `_observe` E-before-D/S lock order for the R6 write; green: P5 `15 passed`, H-2B P1–P5 `81 passed`, regressions + canary + HB-13 + LF green, `contracts-check` 2.16.0 OK, ruff clean.

Report: `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/h2-build-REPORT.md` (marker `H2-BUILD: ALL PACKAGES DONE` at the top).
