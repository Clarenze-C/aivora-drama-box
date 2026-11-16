# T031 fix round 1 — native harness offline gate, 12 persistence failures

Builder: GLM session (`ai-route build`), 2026-11-09. Branch `feat/t031-pika-flex-native`,
base WIP snapshot `048cc05` (untouched). Commits: `c6e19e0` (migration guards),
`2ceb341` (test tail expectations). The orchestrator's diagnosis was confirmed in code
before either edit; both root causes were exactly as briefed, and no third cause exists.

## Root cause per failure

### 1. Schema-catalog guards missing from 0026 (real defect) — 3 failures

`test_schema_catalog.py::test_every_table_refuses_delete` / `..._refuses_truncate` /
`..._refuses_non_integer_numbers`. The catalog tests require every public table to carry
a BEFORE DELETE trigger on `md_forbid_mutation`, a BEFORE TRUNCATE trigger on
`md_forbid_mutation`, and BEFORE INSERT OR UPDATE triggers on
`md_forbid_non_integer_numbers` (0009's repo-wide "money is integer micro-USD, time is
integer ms" invariant). `0026_t031_benchmark_experiments.sql` created ten benchmark
tables with identity/append-only triggers but only partial catalog guards:

- DELETE guard missing on the five mutable tables: `benchmark_experiments`,
  `benchmark_samples`, `benchmark_acquisitions`, `benchmark_dispatch_slots`,
  `benchmark_uploads` (the five append-only tables were already covered by their
  `BEFORE UPDATE OR DELETE` triggers). Log: `Left contains 5 more items, first extra
  item: 'benchmark_acquisitions'`.
- TRUNCATE guard existed only for the five append-only tables (the DO loop's array);
  the same five mutable tables were missing.
- The integer-number guard was missing on **all ten** tables. Log:
  `Left contains 10 more items`.

**Fix (c6e19e0):** edited `0026` in place (never applied outside test databases, per
ruling). Five explicit `BEFORE DELETE ... md_forbid_mutation()` triggers in 0025 style
(`runpod_billing_ingest_backoff_no_delete` pattern), and the existing DO loop extended
to all ten tables, now creating both the `<table>_no_truncate` statement trigger and the
`<table>_integer_numbers` row trigger (`BEFORE INSERT OR UPDATE ...
md_forbid_non_integer_numbers()`, the 0009 naming). No exemptions, allowlists or skips.

### 2. Hardcoded migration tails — 5 failures + 4 setup errors

`migrate()` now returns one more version, `0026`, so every pinned tail broke:

| File:line | Old expectation | New |
|---|---|---|
| `test_migrations.py:145` (`test_v2_contract_document_migration_and_json_readback`) | `[..., "0024", "0025"]` | `..., "0025", "0026"]` |
| `test_migrations.py:214` (`test_season_story_ledger_migration_preserves_existing_document`) | `["0020", ..., "0025"]` | `..., "0025", "0026"]` |
| `test_migrations.py:270` (`test_pre_0019_backup_restore_recovers_checkpoint`) | `[..., "0024", "0025"]` | `..., "0025", "0026"]` |
| `test_season_owner_migration.py:113` (`backfilled` fixture) | `["0024", "0025"]` | `["0024", "0025", "0026"]` |
| `test_t045_finality_migration.py:79` and `:306` | `["0025"]` | `["0025", "0026"]` |

The four `test_season_owner_migration.py` ERRORs at setup were **not** a separate cause:
the shared `backfilled` fixture's tail assertion at :113 raised during setup, so all four
tests errored before running. Confirmed from the log: every setup traceback ends at
`test_season_owner_migration.py:113: AssertionError: ['0024','0025','0026'] == ['0024','0025']`.

**Fix (2ceb341):** appended `0026` to each tail exactly the way `25ead05` appended `0025`
(`git log -p` shows the same one-line-per-assertion change), and added the ten benchmark
tables to `EXPECTED_TABLES` in `test_migrations.py`, matching what `25ead05` did for
0025's tables. Every assertion keeps its strength: tails still pin the exact version
list, now through `0026`.

## Files changed

- `microdrama/migrations/0026_t031_benchmark_experiments.sql` — guards (+11/−2)
- `microdrama/tests/integration/persistence/test_migrations.py` — 3 tails + EXPECTED_TABLES
- `microdrama/tests/integration/persistence/test_season_owner_migration.py` — fixture tail
- `microdrama/tests/integration/persistence/test_t045_finality_migration.py` — 2 tails

Nothing under `migrations/0001–0025`, `contracts/`, `deployment/` or `.scratch/` was
touched.

## Red → green evidence

Before (full gate, 6 Nov, `.scratch/native-gates/check.log`):

```
============= 8 failed, 258 passed, 4 errors in 2230.58s (0:37:10) =============
FAILED tests/integration/persistence/test_migrations.py::test_v2_contract_document_migration_and_json_readback
FAILED tests/integration/persistence/test_migrations.py::test_season_story_ledger_migration_preserves_existing_document
FAILED tests/integration/persistence/test_migrations.py::test_pre_0019_backup_restore_recovers_checkpoint
FAILED tests/integration/persistence/test_schema_catalog.py::test_every_table_refuses_delete
FAILED tests/integration/persistence/test_schema_catalog.py::test_every_table_refuses_truncate
FAILED tests/integration/persistence/test_schema_catalog.py::test_every_table_refuses_non_integer_numbers
FAILED tests/integration/persistence/test_t045_finality_migration.py::test_migration_0025_upgrades_and_reads_back
FAILED tests/integration/persistence/test_t045_finality_migration.py::test_migration_0025_backfills_verification_identity_and_drops_the_default
ERROR tests/integration/persistence/test_season_owner_migration.py (×4, at setup)
```

After (each file run on its own, offline env vars, `systemd-run --scope -p
CPUQuota=45%`, `--basetemp=/tmp/t031-fix1-basetemp`):

```
tests/integration/persistence/test_schema_catalog.py           ....         [100%]  4 passed in 7.83s
tests/integration/persistence/test_migrations.py               .........   [100%]  9 passed in 35.05s
tests/integration/persistence/test_season_owner_migration.py   ....        [100%]  4 passed in 13.53s
tests/integration/persistence/test_t045_finality_migration.py  ........    [100%]  8 passed in 13.79s
```

All 12 targeted tests pass; each of the four files passes in full.

Acceptance extras:

- `make lint` → `ruff check`: **All checks passed!**; `ruff format --check`: **592 files
  already formatted**.
- `make contracts-check` → `contracts 2.16.0: 104 schemas, 74 valid and 135 invalid
  examples; OK`.
- Unit tests touching benchmark tables (`tests/unit/rendering/test_benchmark_experiments.py`,
  `test_presets_benchmark.py`, `test_routing_support.py` — found by grep):
  **17 passed in 51.09s**.

## Commits

- `c6e19e0` fix(microdrama): 0026 benchmark tables get the full schema-catalog guards
- `2ceb341` test(microdrama): migration-tail expectations advance to 0026

Worktree tree is clean except the pre-existing untracked `.scratch/` and
`microdrama/.venv`.

## Unresolved / harness defects

None found. Two things checked and cleared:

- The new `md_forbid_non_integer_numbers` guard applies to jsonb payloads too (plan,
  quote, amounts). The 0026 writers in `rendering/benchmark_experiments.py`,
  `pipeline/benchmark_service.py` and `pipeline/experimental_world.py` were spot-checked
  and write integer micro-USD/ms values; the 17 benchmark unit tests pass. If a live
  payload ever carries a fractional number, the guard will now reject it loudly — that
  is the invariant working as designed.
- No test outside `tests/integration/persistence/` references the benchmark tables
  (grep), so the stricter guards cannot break any of the 258 previously passing
  integration tests.

The full `make check` / `make pilot` was not run, per instructions — the orchestrator
runs the gate.
