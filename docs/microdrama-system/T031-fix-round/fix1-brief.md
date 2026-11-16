# T031 fix round 1 — make the native harness pass the offline gate (GLM build)

Orchestrator: Opus session, 9 Nov 2026. Size: Small. You are the builder.

## Where

- Worktree (your cwd): `/root/AIVORA/drama-box/.scratch/t031-native-worktree`
- Branch `feat/t031-pika-flex-native`, base `0851374`. The whole native-Codex T031
  harness (81 files: H3 Flex bindings, transport, benchmark controller, experimental
  world, CLI/auth, migration `0026_t031_benchmark_experiments.sql`, image sources) is
  committed as WIP `048cc05`. Commit your fixes on top as normal commits. Never amend,
  rebase or rewrite `048cc05`.
- Python project root: `microdrama/` (Makefile there; `PYTHONPATH=src`; pytest via
  `$(PY) -m pytest`). Read the Makefile for the exact interpreter.

## What failed

The full gate (`make check`) on 6 Nov exited 2. Contract, lint, unit (2,879) and contract
tests (462) passed. Integration: 258 passed, 8 failed, 4 setup errors. `make pilot` did not
run. Log: `.scratch/native-gates/check.log` (worktree-relative). All 12 are in
`microdrama/tests/integration/persistence/`:

| Test | Assertion line in log |
|------|-----------------------|
| `test_migrations.py::test_v2_contract_document_migration_and_json_readback` | :145 |
| `test_migrations.py::test_season_story_ledger_migration_preserves_existing_document` | :214 |
| `test_migrations.py::test_pre_0019_backup_restore_recovers_checkpoint` | :270 |
| `test_schema_catalog.py::test_every_table_refuses_delete` | :54 |
| `test_schema_catalog.py::test_every_table_refuses_truncate` | :62 |
| `test_schema_catalog.py::test_every_table_refuses_non_integer_numbers` | :75 |
| `test_t045_finality_migration.py::test_migration_0025_upgrades_and_reads_back` | :79 |
| `test_t045_finality_migration.py::test_migration_0025_backfills_verification_identity_and_drops_the_default` | :306 |
| `test_season_owner_migration.py` — 4 tests ERROR at setup | :113 |

The previous builder's diagnosis, which you must confirm in code before acting on it:
1. Several migration tests hardcode the migration tail or count and broke when 0026 was
   added.
2. The new benchmark tables in 0026 lack the safeguards every table must have: refuse
   DELETE, refuse TRUNCATE, integer-only numbers. **This is a real defect.**

## Rulings (orchestrator)

- **Schema-catalog guards:** fix the migration, never the test. Give every new 0026
  table the same DELETE/TRUNCATE/non-integer protections that existing tables have,
  built the same way (read how 0025 and earlier did it). No exemptions, allowlists or
  skips for benchmark tables. 0026 has never been applied outside test databases, so
  edit `0026_t031_benchmark_experiments.sql` in place; do not add 0027.
- **Migration-tail tests:** update the expectation the way it was updated when 0025 was
  added (`git log -p` on those test files shows the pattern). Keep every assertion's
  strength. If a test pins "latest migration", it must now pin 0026, not something
  looser like "any".
- **Setup errors** (`test_season_owner_migration.py:113`): find the real cause. If it is
  the same tail expectation, fix it the same way. If it is something else, fix that
  narrowly and explain it in the report.
- If any failure turns out to be a defect in the harness code itself (not the
  tests/migration), stop at a red test, write it up in the report, and do not
  redesign. Fix only what these 12 failures require.

## Hard limits

- Do not touch migrations 0001–0025, `microdrama/contracts/` (package 2.16.0 and the
  generated artifacts are guardian-owned), `microdrama/deployment/`, or anything under
  `.scratch/`.
- Offline only. Export these before every test command:
  `MICRODRAMA_EXECUTION_MODE=OFFLINE_MOCK MICRODRAMA_PAID_REQUESTS_ENABLED=false
  MICRODRAMA_CLOUD_RESOURCES_ENABLED=false MICRODRAMA_PUBLIC_ACTIONS_ENABLED=false`.
  No provider/network calls, no docker build or push, no pod creation, no service
  restarts, and no clearing of shared data, volumes or caches. No pushes.
- Run every pytest under `systemd-run --scope -p CPUQuota=45% --quiet` with
  `--basetemp=/tmp/t031-fix1-basetemp` (short path: tests bind Unix sockets, 108-byte
  limit). Each command must finish within 10 minutes, so run the persistence files one
  at a time.
- Never print env vars, `.env` files, keys, tokens or auth headers.
- Do not use deletion commands in shell (`rm`, `git rm`, `git clean`, `git reset`,
  `find -delete`). A hook holds them for 10 minutes and then refuses. Overwrite files
  instead.
- **Do NOT run the full `make check` or `make pilot`.** The orchestrator runs the full
  gate itself after you finish.

## Done when

1. All 12 tests pass. Each of the four files passes in full, run on its own.
2. `make lint` and `make contracts-check` pass, and the unit tests that touch migrations
   or benchmark tables pass (find them with grep).
3. Fixes are committed on `feat/t031-pika-flex-native` with conventional messages. The
   tree is clean except for the pre-existing untracked `.scratch/` and
   `microdrama/.venv`.
4. Report written to
   `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/fix1-REPORT.md`.
   This must be a separate file: your final message overwrites `--out`. The report
   covers: root cause per failure; the files changed; red→green evidence (exact pytest
   summary lines, before and after); commit hashes; anything left unresolved or any
   harness defect found.

Your final message: a 5-line summary, plus the report path.
