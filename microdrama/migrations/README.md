# Migrations (integrator-owned) — schema frozen with contract 1.0.0 (T003)

Ordered SQL files applied by `python -m microdrama.persistence.migrate <database-url>`
(each in its own transaction, checksummed in `schema_migrations`, serialized by an
advisory lock). An applied migration whose file changes is refused. Never apply these
to an unrelated live database.

| File | Contents |
|---|---|
| `0001_foundation.sql` | trigger helpers (`md_forbid_mutation`, `md_immutable_columns`), `owners`, `human_sessions`, `service_credentials`, `jobs`, `aggregate_sequences`, `domain_events` (append-only outbox), `event_dispatches`, `event_consumptions`, `idempotency_records`, `provider_operations`, `webhook_events`, `manual_interventions` |
| `0002_story_and_approvals.sql` | `seasons`, `season_proposals`, `canon_versions` (PLANNED / FINAL_APPROVED / PUBLISHED kept separate), `episodes`, `scripts`, `shot_manifests`, `characters`, `voices`, `reference_versions`, `approval_events` (append-only, human-session trigger), `feedback_events`, `identity_locks`, `identity_lock_assets`, `preference_rules` |
| `0003_budget_and_compute.sql` | `budget_accounts` (cap backstop CHECK), `budget_category_allocations`, `budget_transfers`, `reservations`, `charges` (receipt dedupe), `cost_allocations`, `cost_overruns`, `pod_leases` (single live lease in pilot), `pod_usage_intervals` (EXCLUDE: each paid interval once) |
| `0004_media_and_qa.sql` | `assets`, `asset_lineage`, `edit_manifests`, `caption_tracks`, `hook_experiments`, `hook_exposures`, `qa_observations` (immutable Pass A), `qa_findings`, `repair_plans` |
| `0005_distribution_and_analytics.sql` | `release_packages` (one APPROVED per episode), `platform_posts` (SPEC slot key unique), `metadata_versions`, `community_events` (provider dedupe), `management_actions`, `membership_catalog`, `entitlement_links`, `performance_snapshots`, `qualification_runs` |
| `0006_registries.sql` | `credential_refs` (names/locators only, never secrets), `capability_registry`, `rights_registry`, `preset_registry`, `policy_versions` |
| `0008_m0_revalidation_hardening.sql` | a Gate 2 decision can only be recorded against a package of that episode in a decidable state (APPROVE: READY, no blockers, captions CURRENT + actual-audio aligned); caption tracks of an APPROVED package cannot leave CURRENT until it is SUPERSEDED; `md_runtime_mode` makes live databases refuse active fake-only registry rows; enabled presets carry non-zero measured quality |
| `0007_m0_validator_hardening.sql` | approval trigger judges expiry against the server clock and stamps server time; season approval FK + binding to a Gate 1 APPROVE on the scope hash; release-package status machine and binding of APPROVED/REVISED/REJECTED to the matching Gate 2 event (hashes, no blockers); episodes cannot enter release states without an APPROVED package; append-only tables refuse TRUNCATE; asset descriptor immutable and consistent with its columns; slot `asset_sha256` FK to the asset's hash; metered management actions need a reservation; enabled presets carry a measurement; management qualification needs ten |

## Rules for module lanes

1. Use `microdrama.persistence.Database.transaction()` and write SQL against these
   tables **inside your own module**. Do not create/alter tables, indexes or triggers.
2. A state mutation and its outbox event (`domain_events` row) go in the same transaction.
3. Mutable rows carry `revision`; use `persistence.update_with_revision` (raises
   `StaleRevision`) or an equivalent `WHERE revision = %s` guard.
4. Gate-related ordering (0007): set the release package to APPROVED (bound to the Gate 2
   APPROVE) **before** moving the episode to RELEASE_APPROVED; `approval_events.created_at`
   is always server time. Floats are refused as bind parameters (`SchemaInvalid`).
5. Constraint failures arrive as contract errors: unique/exclusion →
   `DuplicateSemanticKey` (`details["constraint"]` names it), check/FK → `Conflict`,
   approval without a live human session → `Unauthorized`.
6. Money columns are `bigint` micro-USD; never write floats.
7. Need a column/table/index? Stop and send the integrator a migration-change proposal
   (what, why, downstream impact). New migrations are appended (`0007_...`), never edits
   to applied files.

## Primary table users by lane

| Lane / task | Tables |
|---|---|
| Core (T004) | `jobs`, `domain_events`, `aggregate_sequences`, `event_dispatches`, `event_consumptions`, `idempotency_records`, `provider_operations`, `owners`, `human_sessions`, `service_credentials`, state columns of `seasons`/`episodes` |
| Cost (T005) | `budget_accounts`, `budget_category_allocations`, `budget_transfers`, `reservations`, `charges`, `cost_allocations`, `cost_overruns`, `pod_usage_intervals` |
| Registry (T006) | `credential_refs`, `capability_registry`, `rights_registry`, `preset_registry`, `policy_versions` |
| Review (T008) | `approval_events`, `feedback_events`, `release_packages`, `season_proposals`, `identity_locks` (via T011 hook) |
| Story/References (T009–T011) | `season_proposals`, `canon_versions`, `scripts`, `shot_manifests`, `characters`, `voices`, `reference_versions`, `identity_locks`, `identity_lock_assets` |
| GPU (T012–T014) | `pod_leases`, `pod_usage_intervals`, `provider_operations`, `preset_registry` |
| Media/QA (T015–T019) | `assets`, `asset_lineage`, `edit_manifests`, `caption_tracks`, `hook_experiments`, `hook_exposures`, `qa_observations`, `qa_findings`, `repair_plans`, `preference_rules` |
| Distribution (T020–T024) | `platform_posts`, `metadata_versions`, `provider_operations`, `capability_registry` |
| Social/Membership (T025–T026) | `community_events`, `management_actions`, `membership_catalog`, `entitlement_links`, `webhook_events` |
| Analytics (T027) | `performance_snapshots`, `hook_exposures`, `qualification_runs`, `manual_interventions`, read-only elsewhere |
