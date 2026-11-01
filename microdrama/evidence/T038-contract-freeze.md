# T038 contract freeze evidence

Date: 2026-10-30 UTC  
Contract line: 2.0.0  
Mode: local/offline only; no provider, cloud, GPU, public account or paid action.

## Frozen boundary

- V1 payload models keep `schema_version: "1.0"`; generated `schemas/v1/` and
  `examples/v1/` remain separate and retain their V1 contract IDs.
- V2 records use `schema_version: "2.0"` and are generated under `schemas/v2/`
  and `examples/v2/`.
- V2 adds typed concept intake/candidate, character logic and secret ledger,
  180–300 second UUID-backed episode packs and story time, wardrobe bible and
  scene assignment, state events, asset/prop/location/style sheets, semantic
  shot references, prompt manifests, event-backed progress, and Gate-2 release
  approval manifests for exact slot metadata and mutation policy. The
  `manifest_id` is allocated pre-gate; Gate 2 references the manifest hash,
  avoiding a dependency on a not-yet-created approval event ID.
- `read_v1_manifest()` validates the V1 `ShotManifest`, preserves its payload
  hash and returns `v2_ready: false`. Recompilation with typed V2 bindings is
  required before paid dispatch.
- `validate_wardrobe_assignment()`, `validate_state_event_chain()`,
  `validate_live_release_metadata()` and `verify_v2_record_hash()` provide the
  cross-record checks that JSON Schema cannot express.
- V2 record construction and Pydantic readback reject stale `content_sha256`;
  generated-example validation checks the same invariant. Live metadata
  `metadata_sha256` means the persisted typed slot record's
  `ApprovedSlotMetadata.content_sha256`, not a hash of legacy `PostMetadata`.
  Positive owner-approved and tampered version/content/cover/CTA cases are
  covered.
- Migration 0019 stores append-only typed V2 revisions with payload hash,
  validity and optional paired rights-route index. Migration rollback follows
  project policy: restore a pre-migration backup; there is no destructive down
  migration. The database tests prove a pre-0019 checkpoint, forward upgrade,
  typed JSONB readback, and actual restore of a pre-0019 custom-format backup.
- V2 rights grants now bind route, subject kind/ref and exact version.
  `validate_current_rights_grant()` requires an authoritative current-record
  resolver at dispatch and rejects superseded, revoked, wrong-subject, expired
  and uncovered grants. T041 must wire that resolver before paid dispatch;
  static payload validation cannot establish live registry currentness.

## Commands and observed results

From `microdrama/`:

```text
make contracts
contracts 2.0.0: 95 schemas, 50 valid and 107 invalid examples; OK

make contracts-check
contracts 2.0.0: 95 schemas, 50 valid and 107 invalid examples; OK

PYTHONPATH=src .venv/bin/python -m pytest tests/contract/contracts/test_generated_contracts.py -q
7 passed

PYTHONPATH=src .venv/bin/python -m pytest tests/contract/contracts/test_v2_contracts.py -q
19 passed

PYTHONPATH=src .venv/bin/python -m pytest tests/integration/persistence/test_migrations.py tests/integration/persistence/test_schema_catalog.py -q
10 passed

.venv/bin/ruff check <scoped contract and migration files>
All checks passed
```

The PostgreSQL tests require loopback sockets and were run against an isolated
temporary test server outside the sandbox. They did not touch any configured or
production database. After T048 and this extra T038 round, an independent
validator ran the full offline gate under the host CPU limit:

```text
systemd-run --pipe --working-directory=/root/AIVORA/drama-box/microdrama -p CPUQuota=45% --wait --collect /usr/bin/make check
contracts 2.0.0: 95 schemas, 50 valid and 107 invalid examples; OK
Ruff lint and format: passed
unit: 2357 passed; contract: 431 passed; integration: 177 passed
make check: all offline checks passed
```

This does not claim composed T037/T039–T047 or real-provider acceptance.

## Pre-0019 backup restore acceptance

Executed 2026-10-30 UTC, from `microdrama/`, against the test harness's temporary
PostgreSQL 16 cluster bound to loopback. The test created two random databases
inside that cluster; no configured database URL was used. `pg_dump` and
`pg_restore` were both PostgreSQL 16.15.

Exact test command and result:

```text
PYTHONPATH=src .venv/bin/python -m pytest tests/integration/persistence/test_migrations.py::test_pre_0019_backup_restore_recovers_checkpoint -q
.                                                                        [100%]
1 passed in 4.90s
```

The test's database operations, in order, were:

```text
migrate(source_dsn, target="0018")                         -> final applied version 0018
pg_dump --format=custom --file <tmp>/pre-0019.dump <source_dsn> -> exit 0; non-empty dump
migrate(source_dsn)                                         -> ["0019"]
pg_restore --exit-on-error --dbname <fresh_restore_dsn> <tmp>/pre-0019.dump -> exit 0
```

The source database had a seeded season and episode before dumping. After restore,
the test read back the episode's original season ID and confirmed the latest
`schema_migrations` version was `0018`; `episodes` existed and
`v2_contract_documents` did not. This proves rollback-by-restore recovers the
pre-0019 checkpoint and its sample data. It does not test point-in-time recovery,
external object storage, or a production restore procedure.

## Compatibility and integration handoff

At inspection, no T039–T044 implementation imported or referenced the new V2
models. The production kit was used only as design input; its `E001` IDs,
15–600 second bounds, free-form state, positional reference lists and lifecycle
statuses are not accepted by the new contracts.

T037 must bind Gate 2 to `ReleaseApprovalManifest.gate2_package_hash` (or a
release-package hash that includes it), then use
`validate_live_release_metadata()` to match exact metadata ID/version/content,
cover ID/version/hash and CTA before live submit. This T038 contract does not
wire that behavior into the existing T037 scheduler, so the live-first-submit
path remains blocked pending that integration and composed tests.
