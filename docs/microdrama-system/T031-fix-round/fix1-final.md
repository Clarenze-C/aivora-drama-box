1. Root causes confirmed in code, exactly as briefed: 0026's ten benchmark tables lacked the schema-catalog guards (DELETE on 5 mutable tables, TRUNCATE on 5, integer-number on all 10), and 6 hardcoded migration tails (+1 fixture feeding 4 setup errors) still ended at 0025.
2. `0026_t031_benchmark_experiments.sql` edited in place — 5 `no_delete` triggers (0025 style) and the DO loop extended to all 10 tables for `no_truncate` + `integer_numbers`; no exemptions.
3. Test tails advanced to `0026` the same way `25ead05` did for `0025`; the 4 setup errors were the same cause (fixture assertion at `test_season_owner_migration.py:113`); benchmark tables added to `EXPECTED_TABLES`.
4. All 12 pass; each of the four files green on its own (4+9+4+8 passed), `make lint` + `make contracts-check` clean, 17 benchmark unit tests pass; commits `c6e19e0` and `2ceb341` on `feat/t031-pika-flex-native`, `048cc05` untouched, tree clean.
5. No harness defects found; full `make check`/`make pilot` left to the orchestrator per instructions.

Report: `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/fix1-REPORT.md`
