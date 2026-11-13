All checks pass. The other modified docs were dirty before this task; only the spec was touched.

**v0.2 applied** — every ruling and unruled Action, sections §1–§7 kept in order, added: §8 Alternatives considered (C moved there per CON-B1), §9 Finding map (all 39 ids), §10 Failure and retry, §11 Risks and limits, §12 Glossary, target-scope table + RR→package mapping in §6. 363 lines.

One ruling-vs-code finding, written as instructed (CON-M3): `benchmark_acquisitions.state` has **no CHECK** (`migrations/0026…sql:36`) so the DB admits both incident values — but sweep finalization later replaces any non-terminal state (`benchmark_service.py:2031-2037`), so the durable incident copy rides the ruling's coverage-key fallback. All other new code claims verified in the worktree (`_scope`, preflight gate `benchmark_service.py:198`, guard allowlist `live_world.py:368`, `PodCreateRequest`, `build.sh:8`, canary 404/502/503/524 set, `provision.py` finally-unlink, r2 manifest A2-canonical chain).

`/root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md`
