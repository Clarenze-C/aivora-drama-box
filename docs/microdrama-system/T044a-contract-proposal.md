# T044a contracts-guardian proposal — owner progress views — 1 November 2026

Status: **PROPOSAL, not frozen.** T044a added six owner-progress response models
to public contract surface while the package stayed at 2.15.0. The scoped review
(2026-11-01, finding 3) removed them from `contracts/routes.py`,
`contracts/registry.py`, the generated `schemas/v1/` set and the `ROUTES` table;
they now live as **module-local read-only response models in
`microdrama/src/microdrama/review/progress.py`**, and the two JSON reads are
served under the review module's `/ui` prefix (`/ui/seasons/{id}/progress.json`,
`/ui/episodes/{id}/progress.json`) so the pre-existing "review adds only /ui and
/auth beyond the table" contract test still holds. This document is the precise
proposal for freezing them in a future guardian package.

## Proposed package change (e.g. 2.16.0 — guardian decides the number)

Additive only: six SUPPORTING_PAYLOADS entries (no new core §4.2 payload), six
generated `schemas/v1/` files, no change to any existing model, example or hash.
V1 `schema_version` stays `"1.0"`; V2 stays `"2.0"`.

### 1. `WorkProgress` (routes-local `ContractModel`)

| field | type | notes |
|---|---|---|
| `required` | `int >= 0` | current required work units |
| `accepted` | `int >= 0` | current accepted units (latest attempt only) |
| `progress_bp` | `int 0..10000 \| None` | `None` = indeterminate, never fabricated |
| `indeterminate_reason` | `str \| None` | why no truthful percent exists |

### 2. `PlanProvenance` (routes-local `ContractModel`)

| field | type | notes |
|---|---|---|
| `plan_kind` | `str` | `"DirectingManifest+SceneWardrobeAssignments"` |
| `record_id` | `UUID` | current DirectingManifest record |
| `version` | `int` | current DirectingManifest version |
| `content_sha256` | `str` | manifest content hash |
| `plan_fingerprint` | `str` | canonical hash over the WHOLE current required set (manifest record/version/content/shots + every verified current assignment record/version/payload-hash) — changes on any shot OR outfit requirement change |
| `plan_revision` | `int` | derived, visible: manifest version + every current assignment version; not a stored counter |
| `previous_version` | `int \| None` | previous manifest version when persisted |
| `denominator_changed` | `bool` | true only when persisted comparable history proves a requirement-set change |
| `change_reason` | `str \| None` | exact additions/removals when comparable history exists; never an invented prior count |
| `denominator_basis` | `str` | always: what the current denominator is, and which comparability the persisted rows do not allow |

### 3. `JobsDigest`

`by_status: dict[str,int]`, `retried_jobs: int`, `failed_jobs: int`,
`waiting_external: int`, `latest_activity: UtcDateTime | None`. Durable ledger
states only; provider-internal percentages never surface.

### 4. `SlotProgress`

`post_id: UUID`, `platform: str`, `release_slot: str`, `required: bool`,
`state: ReleaseState`, `verified_fields: list[str]`,
`unverified_fields: list[str]`, `blocker: str | None`.

### 5. `EpisodeProgressView` (`VersionedPayload`)

`episode_id`, `episode_number`, `state: EpisodeState`,
`outcome: EpisodeOutcome | None`, `revision: Revision`,
`production_stage`/`release_stage: ProgressStage` (V2 enum),
`production: WorkProgress`, `plan: PlanProvenance | None`, `jobs: JobsDigest`,
`open_blocking_findings: int`, `unknown_coverage: int`,
`cost: CostSummary | None`, `release_slots: list[SlotProgress]`,
`blockers: list[str]`, `next_action: str | None`,
`snapshot: ProgressSnapshot | None` (V2 record, only with full provenance),
`indeterminate: list[str]`.

### 6. `SeasonProgressView` (`VersionedPayload`)

`season_id: UUID`, `state: str`, `revision: Revision`,
`episodes: list[EpisodeProgressView]`.

### Route-table entries (restore the contract paths on freeze)

```
GET /seasons/{season_id}/progress   HUMAN_SESSION review None -> SeasonProgressView  (200)
GET /episodes/{episode_id}/progress HUMAN_SESSION review None -> EpisodeProgressView (200)
```

On freeze, move the two FastAPI reads from `/ui/.../progress.json` back to these
paths, re-add the two `ROUTES` entries, the six registry entries and the two
expected shapes in `test_states_routes_jobs.py` (`checked == 7` in
`test_review_contract.py`), regenerate with `make contracts` (110 schemas), and
add a COMPATIBILITY.md entry. Suggested valid/invalid examples: one valid
`EpisodeProgressView` with a plan and one with `plan=None`; invalid cases
`progress_bp > 10000` and `accepted > required`.

## Migration 0024 `DirectingManifest` allowlist — kept, with a stated limitation

0024 also extends the `v2_contract_documents_contract_type_check` allowlist with
`DirectingManifest`. This is a **contract-authority change implemented as a
migration** and is kept only because persistence is demonstrably required and it
does not touch generated artifacts:

- `StoryV2Store.save_bundle()` (`story/v2_store.py`) persists any `V2Record` it
  is given; the T041a directing compiler (`story/directing.py`) and the T044a
  progress denominator (`review/progress.py::_work`) read/write current
  `DirectingManifest` rows. Without the allowlist entry every
  `save_bundle([...DirectingManifest...])` insert fails the CHECK —
  `tests/unit/review/test_progress.py` (the `planned` fixture) exercises exactly
  this path against the migrated schema.
- It does **not** alter any 2.15.0 generated artifact: `schemas/v2/` and
  `examples/v2/` generate from the Python models in `contracts/v2.py`
  (unchanged); the CHECK constraint is database-only. `make contracts-check`
  returns the prior **104 schemas** with this migration in place.
- Limitation: the allowlist now names a contract type whose persistence surface
  was previously refused by the database. The guardian should ratify
  `DirectingManifest` as a persistable V2 document type (it is already a frozen
  V2 record in contract 2.11.0) or direct a different storage home; until
  ratified, no further contract types may be added to this CHECK outside a
  guardian-blessed migration.

## Not claimed: DB-enforced actor provenance (T046)

The `season_owners` trigger verifies only `GATE1_APPROVAL_BACKFILL` provenance.
`CREATOR_AT_CREATION`/`AUDITED_ASSIGNMENT` rows are admitted by the database
whenever the shared application DB role writes them; the human-only guard
(`review.scope.link_season_creator` via `owner_id_in_tx`) is an application-layer
control. DB-role isolation and an audited assignment control are T046 work.
There is no assignment endpoint in T044a.
