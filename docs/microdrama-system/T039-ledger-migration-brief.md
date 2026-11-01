# T039 SeasonStoryLedger persistence migration

Add an ordered migration after `0019_v2_contract_documents.sql` so the
`v2_contract_documents.contract_type` constraint accepts the frozen 2.3.0
`SeasonStoryLedger` type. Preserve every existing allowed type and all existing
rows. Do not edit migration 0019 in place.

Ownership: the worker may edit only the new migration file, migration README,
and scoped tests in `microdrama/tests/integration/persistence/`. Do not edit
story/research (the T039 lane owns it), contracts, publishing, review, root
configuration or task ledger.

Acceptance: fresh database migrations apply in order; 0019 → new migration
upgrade preserves an existing V2 document and permits an exact
`SeasonStoryLedger` payload; an unknown contract type still fails. Run scoped
PostgreSQL migration tests, Ruff and `make contracts-check`. No configured or
production database, no provider/public action, no commit. Return exact
commands/results and the new migration number to the T039 lane.
