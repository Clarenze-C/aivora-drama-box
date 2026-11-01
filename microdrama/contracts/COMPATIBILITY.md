# Contract v1.5.0 — conventions and compatibility notes (guardian-owned)

Frozen 2026-10-20 by the integrator/contract guardian (task T002). Python source
of truth: `src/microdrama/contracts/`. Generated artifacts in this folder are
written by `make contracts` and checked by `make contracts-check`; never edit
them by hand.

## Conventions every lane must follow

| Topic | Rule | Where |
|---|---|---|
| Money | Integer **micro-USD** (`MicroUSD`, 1 USD = 1,000,000). Floats, bools and strings are rejected. No runtime float comparison for budgets. | `primitives.py` |
| Cap | `EPISODE_CAP_MICRO_USD = 10_000_000`; default allocation in `DEFAULT_BUDGET_ALLOCATION_MICRO_USD` sums exactly to the cap. | `primitives.py` |
| Time | Durations/timecodes are integer milliseconds (`*_ms`). Datetimes are timezone-aware and normalized to UTC. | `primitives.py` |
| Schedules | `ScheduleInstant` = IANA zone + local wall time string + concrete UTC instant. DST gaps are rejected; DST overlaps need explicit `fold`. | `primitives.py` |
| Ratios | Integer basis points 0..10000 (`*_bp`). | `primitives.py` |
| Hashing | `canonical_hash()` / `model_hash()` only: sorted keys, compact separators, UTF-8 literal Thai, floats rejected, naive datetimes rejected, sets sorted. A hash proves identity/integrity, not truth or rights. | `hashing.py` |
| Unknowns | Missing evidence/coverage/metrics stay representable: `QAOutcome.UNKNOWN`, `CoverageStatus.UNSAMPLED/UNAVAILABLE`, `MetricValue.value=None`, `CapabilitySupport.UNKNOWN`, `EntitlementCheck.active=None`. Never coerce unknown to pass/zero. | `qa.py`, `catalog.py`, `release.py` |
| Closed schemas | Every model forbids unknown fields; every enum is closed. Unknown/unsupported controls are rejected (422), never dropped. | `primitives.ContractModel` |
| Schema version | Every top-level payload carries `schema_version: "1.0"`; other values are rejected. | `primitives.VersionedPayload` |
| Fakes | Fake adapters use `Provenance.FAKE_SYNTHETIC`, `CostBasis.SYNTHETIC_FAKE` receipts and only `https://*.invalid` URLs. Validators reject fake results with real URLs or measured cost bases. | `cost.py`, `release.py` |
| Effects | Paid/cloud/public effects require `Settings.require_effect(...)`; OFFLINE_MOCK can never enable them. | `config.py` |
| Errors | Raise types from `errors.py`; each has a stable `code` and HTTP status (422/409/403/401/404/502/503). | `errors.py` |
| States | Transition tables in `states.py`; enforcement belongs to `core` (T004). Gate transitions are human-only. | `states.py` |
| Principals | Identity comes from authentication. Only `HUMAN_OWNER` principals with a session can produce approval events. | `principals.py` |
| Routes | `routes.ROUTES` is the API surface; owners export `build_router(deps)`; only the integrator registers. Review may add `/ui` and `/auth` pages. | `routes.py` |
| Jobs | `jobs.JOB_SPECS` lists job types, queues and input models; owners export handlers; only the integrator registers. The janitor is an independent process, not a queue job. | `jobs.py` |
| Providers | All external boundaries implement the protocols in `providers.py`/`infra.py` (submit/status/reconcile, `client_token`, owned tags). | `providers.py` |

## Recorded guardian decisions (M0 validation)

- **Validation layers.** The Pydantic models are the canonical validators. The published
  JSON Schemas enforce structure (closed objects, enums, patterns, required fields, ranges)
  but cannot express cross-field rules, and JSON Schema treats `3.0` as an integer, so it
  cannot reject integral floats. Each invalid example's manifest entry says whether the
  JSON Schema alone rejects it.
- **Fake-evidence records (V-4, structural since 0008).** `CapabilityRecord`, `RightsRecord`
  and `PresetRecord` backed only by `FAKE_FIXTURE` evidence may be enabled/ELIGIBLE *as mock
  fixtures*; the offline mock pipeline cannot run without them. Migration 0008 adds the
  database's own `md_runtime_mode`: in any live mode the database refuses enabled/ELIGIBLE
  fake-only rows, and it cannot be switched out of OFFLINE_MOCK while such rows are active.
  The registries (T006) additionally treat them as UNKNOWN/disabled outside OFFLINE_MOCK.
- **Package hash scope (V-14, rejected with mitigation).** `package_hash` covers media,
  captions, release scope, management-policy hash and the QA summary, but not `gate_blockers`
  or `cost`. Blockers are derived state, recomputed at decision time by the review service.
  Migration 0007 lets an APPROVED package bind only an approval with matching hashes and an
  empty blocker list. Migration 0008 enforces the decision-time half: a Gate 2 APPROVE can
  only be *recorded* against a READY package of that episode with no blockers (REVISE/REJECT
  need READY or BLOCKED), so clearing blockers later cannot launder an earlier decision.
- **Feedback repair rounds (V-20, no change).** SPEC §5 rule 5 bounds human-requested
  revisions by remaining budget, not by a round count; the SPEC §9 "two final repair rounds"
  default is read as covering *automatic* final-QA repair only (SPEC.md itself is not edited
  in this build). T019 must reserve funds for every revision before executing it, so the
  episode budget is the hard bound.
- **Caption timing in the package (V-22).** Migration 0008 refuses a Gate 2 APPROVE while any
  current caption track of the episode is not `ACTUAL_AUDIO_ALIGNMENT`, or any track listed in
  the package is missing/not CURRENT; and a caption track used by an APPROVED package cannot
  leave CURRENT until that package is SUPERSEDED (a recut returns to the same Gate 2). T008
  shows these as gate blockers; T020 re-checks before submitting.
- **Link secrecy heuristic (N-2 residual).** The contract's token-like-link rule is a
  heuristic backstop (opaque 32+ character segments, credentials, listed secret query keys).
  It cannot recognise every token shape. T026 must build public/member URLs only from
  verified provider post IDs using a per-provider allow-list of URL shapes, and test it.
- **Runtime-mode deployment (V-4/N-16 residual).** Every database guard assumes the
  application role neither owns the tables nor can alter them: a table owner can
  `DISABLE TRIGGER`. Live deployments must run the application under a role that is not the
  table owner and has no ALTER/DROP/TRIGGER privilege on the microdrama schema, and that
  cannot UPDATE `md_runtime_mode`. The `/ready` check (T029) must report not-ready when the
  database's `md_runtime_mode` differs from `Settings.execution_mode` or when the connected
  role owns the schema's tables. In the offline test databases the migration owner is the
  application role; that is accepted for OFFLINE_MOCK only.
- **Caption checks are decision/transition-time (N-17).** The package's own listed tracks are
  locked while it is APPROVED (0008/0009). A new, unlisted caption track added to the episode
  after approval is not part of the approved release. T020 must re-check the listed tracks
  (CURRENT, ACTUAL_AUDIO_ALIGNMENT) before every submit.
- **Evidence labels are trusted at the database (D3).** The DB cannot tell a fixture mislabelled
  as MEASURED_BENCHMARK from a real benchmark. Fakes (T007) are tested to emit only FAKE_FIXTURE
  evidence, and T006 writers must refuse a non-fake evidence source on any record built from
  `Provenance.FAKE_SYNTHETIC` data.
- **Floats (V-12/N-1/N-9).** The persistence layer refuses floats in bind parameters and at
  any depth inside JSON documents. Since migration 0009, a generic row trigger also refuses
  any non-integer number anywhere in a stored row, including JSON bound as text. The original
  policy file in `policy_versions` is the only exempt table. A float *literal* cast into a
  bigint column in SQL source remains a residual that code review must catch.

- **Cost lines use lowercase identifiers (M1, T005).** `CostLine.category`, `kind` and
  `cost_basis` are `Identifier` fields (lowercase). The cost view emits the enum values
  lowercased (`gpu_generation`, `settlement`, `synthetic_fake`) and `research_allocation` for
  research spend attributed to the episode. This is a display view, not a stored payload, so
  no contract change was made.
- **Reservation close reasons (M1, migration 0012).** Every closed reservation stores why it
  closed (`closed_reason`): the caller's reason for RELEASED, a fixed reason for EXPIRED and
  SETTLED. A RELEASED reservation keeps its state and reason.

- **Review lane decisions (M1, T008).** `GET /seasons/proposals` returns a JSON array of
  `SeasonProposalSummary`. A Gate 2 REVISE sends the episode back to the most upstream stage any
  of its feedback categories needs (not the earliest timecode). Gate 2 also blocks when the
  package's management-policy hash differs from the approved season scope. A material change
  after a Gate 2 APPROVE is refused: the state tables have no RELEASE_APPROVED →
  AWAITING_FINAL_REVIEW edge, so an approved package cannot be superseded in this build. A
  post-approval recut needs a future contract change (a human-only return edge, or a HELD path
  that cancels unscheduled slots), and until then T020 must submit only the approved package's
  hashes. Sign-in uses a pre-session double-submit token (`md_login_csrf`, round-2 V-28).

## Changing a contract

A worker that needs a missing field **stops** and returns a contract-change
proposal (field, type, reason, downstream impact, migration/compatibility
handling, tests). Only the guardian edits `src/microdrama/contracts/`, bumps
`CONTRACT_VERSION`, regenerates with `make contracts`, records the change
below and notifies affected lanes.

- Additive optional field: minor bump (1.x.0); old payloads stay valid.
- New required field, removed field, narrowed enum/range: major bump; schema
  version string changes; migration notes required.

## Contract 2.0.0 — V2 creative and continuity family (T038)

Frozen as a major contract line on 2026-10-30. The prior V1 Python payloads,
their `schema_version: "1.0"`, generated `schemas/v1/` files and V1 examples
remain unchanged and parseable. V2 canonical records use the separate
`V2VersionedPayload` base (`schema_version: "2.0"`) and are generated under
`schemas/v2/` and `examples/v2/`. The registry is the sole generation index.
Generated `$id` values for V1 remain pinned to `1.6.0`; V2 IDs use `2.0.0`.

The V2 family freezes `ConceptIntake`, `ConceptCandidate`, `CharacterLogic`,
`SecretLedger`, `EpisodePack`, `StoryTime`, `WardrobeBible`,
`SceneWardrobeAssignment`, `StateEvent`, `AssetSheet`, `LocationLayout`,
`PropSheet`, `StyleBible`, `ShotReferenceBinding`, `PromptManifest`, `ProgressSnapshot`, and
`ReleaseApprovalManifest`. Canonical hashes use `canonical_hash()`; each V2
record exposes `calculated_content_sha256()` / `content_hash_matches()` and
`verify_v2_record_hash()` for writers and readback validators; V2 Pydantic
construction/readback and generated-example validation reject stale hashes.
Use `V2Record.seal()` to compute the content hash before validation. Rights are
explicit, versioned and eligible on render-bound records. Outfit selection
must pass `validate_wardrobe_assignment()` against the exact wardrobe-bible
revision. Contradictory state transitions are refused by
`validate_state_event_chain()`. Prompt references carry semantic roles, exact
asset IDs/versions/hashes, rights and validity; an untyped list is not a V2
binding.

`RightsGrant` also binds the registry subject kind/reference as well as route
and version. Payload validation checks shape, declared eligibility and expiry
only; it cannot establish live currentness. Every render or release dispatch
must call `validate_current_rights_grant()` with the authoritative live
registry resolver immediately before dispatch. That resolver must return the
current record for the exact route/subject tuple; missing, superseded, revoked,
mismatched or expired records fail closed. V1 readback remains audit-only.

Production-kit crosswalk: its episode pack maps to UUID-backed `EpisodePack`
and typed scenes/beats; its continuity ledger maps to `StoryTime`, `StateValue`
and ordered `StateEvent`; its asset registry maps to `AssetSheet`, `PropSheet`,
`WardrobeBible`, `SceneWardrobeAssignment` and `LocationLayout`; its style
registry maps to `StyleBible`; storyboard
reference policy maps to `ShotReferenceBinding` and `PromptManifest`; task
status maps to event/job/source-backed `ProgressSnapshot`. Kit IDs such as
`E001`, 15–600 second episodes, free-form state objects, positional reference
lists and kit lifecycle statuses do not cross the boundary. Drama Box keeps
UUID episode identity, 180–300 second episodes, ≤15-second generated shots,
closed role/status enums and exact versioned bindings.

`read_v1_manifest()` first validates with the original V1 `ShotManifest`, then
returns a hash-bound `V1ManifestReadback` with `v2_ready: false`. It is audit
readback only; consumers must recompile and bind exact V2 references/rights
before paid dispatch. No V1 manifest can be relabeled as a V2 prompt.

`ReleaseApprovalManifest` wraps the frozen V1 media package ID/hash with an
exact versioned `ApprovedSlotMetadata` row per slot and a versioned
`ApprovedMetadataPolicy`; `approval_manifest_sha256` binds the complete
manifest. `manifest_id` is minted before Gate 2 and is not the future approval
event ID: compile and persist the immutable manifest first, then have Gate 2
create its event referencing `gate2_package_hash`; the event never feeds back
into the manifest hash. Gate 2 must approve that manifest hash (or a package
hash that includes it). The persisted metadata hash is
`ApprovedSlotMetadata.content_sha256`, the canonical typed record hash with
that field excluded. A live submitter must use
`validate_live_release_metadata()` to compare slot, metadata ID/version/content
hash, cover ID/version/hash and CTA with the approved manifest. Example and
OFFLINE_MOCK metadata are refused for live submission. This is a contract only: T037's live-first-submit path remains
blocked until its approval event and scheduler use this manifest, and T044/T047
must retain that binding in the composed Gate-2 flow.

Migration `0019_v2_contract_documents.sql` adds append-only revision storage
for V2 canonical records, with version, canonical payload hash, optional
rights-route index (paired route/version) and validity interval. Upgrade is `migrate()` through 0019 and is
covered by the fresh database/readback test. Migrations are forward-only;
rollback is restore from a pre-0019 database backup, not destructive DDL or
deletion of audit history. There are no downstream T039–T044 consumers at
freeze time; they must build against 2.0.0 after this contract is accepted.

## Contract 2.1.0 — candidate-stage rights uncertainty

Additive, loosening change for `ConceptCandidate.rights` only: it now accepts
either the existing eligible `RightsGrant` or `PendingRightsAssessment` with
`status: "PENDING" | "UNKNOWN"` and a human-readable `note`. This lets
pre-Gate-1 creative proposals state that rights are unresolved without
inventing a registry route, evidence hash, territory or permission. The
existing eligible-grant example and V2 canonical readback remain valid.

The change does not loosen any production contract: render-bound records,
asset sheets, wardrobe assignments, reference bindings and paid dispatch
continue to require an eligible `RightsGrant`, and dispatch still resolves
the exact current registry row through `validate_current_rights_grant()`.
Downstream candidate consumers (T039 and Gate 1 scope conversion) must carry
the candidate assessment truthfully and must not promote PENDING/UNKNOWN to
production rights; they must acquire and validate an eligible grant before
creating production-bound assets or dispatching paid work. V2 records retain
`schema_version: "2.0"`; generated contract package/schema IDs advance to
2.1.0. Existing 2.0.0 payloads remain valid under the new candidate union.

## Contract 2.2.0 — explicit pack proof and dependency graph

Additive fields: `PackBeat.proof_object_ids` and `PackBeat.dependency_beat_ids`
are lists of `Identifier`, and `EpisodeScene.dependency_scene_ids` is a list
of `Identifier`; each defaults to an empty list. Proof IDs must name props in
the containing scene (`proof_object_ids` is a subset of `EpisodeScene.prop_ids`).
This keeps proof objects grounded in the existing typed prop relation rather
than adding a second object registry.

Beat IDs are unique across an `EpisodePack`; beat dependencies resolve to a
beat in that same pack. Scene dependencies resolve to a scene in that same
pack. Neither graph permits self-dependencies, duplicate edges or cycles.
Existing payloads remain valid because all new lists default empty. V2
`schema_version` stays `2.0`; generated package/schema IDs advance to 2.2.0.
T039 producers should emit explicit order/proof links where the story pack
depends on them; consumers can rely on each link being pack-local and acyclic.

## Contract 2.3.0 / V1 schema set 1.7.0 — Gate 2 live metadata binding

`ApprovalCommand.release_manifest_hash` optionally carries the V2
`ReleaseApprovalManifest.approval_manifest_sha256` separately from the
unchanged V1 `package_hash`. When present, it is valid only on Gate 2 APPROVE;
the legacy V1 package hash remains the value used by existing database approval
triggers. This field does not grant V2 live authority to old Gate 2 events.

`ApprovedSlotMetadata` now carries `links`, `disclosures` and
`catalog_version`, so the Gate 2 manifest binds every provider-visible field
in `PostMetadata`. Defaults preserve parsing of prior V2 readbacks, but
`validate_live_release_metadata()` rejects a live approval missing disclosures
or catalog version and compares the complete `PostMetadata` projection with
the approved slot. `PostMetadata.cover_asset_version`,
`cover_asset_sha256` and `cta_text` are additive. Legacy V1 payloads may still
specify only `cover_asset_id`; when V2 command binding is present, publication
requires the complete cover ID/version/hash tuple.

`PublicationCommand` adds optional exact manifest, approved metadata and
metadata policy locators/hashes. They must be either all absent (legacy
command) or all present (V2 queue command); V2 commands require a complete
cover tuple. The existing `release_package_id`, `release_package_hash`,
`approval_event_id` and `metadata_version_id` retain their meaning. V1
`schema_version` remains `1.0`, V2 remains `2.0`; the package version advances
to 2.3.0 and generated V1 schema IDs to 1.7.0.

The V2 family adds `SeasonStoryLedger` with a promise, ordered payoff debts
and escalation-by-episode entries, approved-scope hash, character-logic record
IDs, and a secret-ledger ID. Payoff and escalation lists must be nonempty and
ordered; cross-record validation requires exact same-season CharacterLogic
and SecretLedger records, exact approved-scope hash, and due/escalation episode
bounds. `CharacterLogic.season_id` is optional for old readback, but T039
writers must populate it; ledger validation rejects unbound or cross-season
records. Existing V2 record schema version remains `2.0`.

## Contract 2.4.0 — EpisodePack approved-scope binding

`EpisodePack.approved_scope_hash: Sha256Hex` is required. Producers must copy
the exact Gate 1 approved `SeasonScope` hash into every episode pack; readers
and replay paths can then reject packs compiled against a stale or different
approval. This is a V2 additive required field, so pre-2.4 EpisodePack records
without the field remain audit data but do not validate as current V2 packs.
The package version advances to 2.4.0; V2 `schema_version` remains `2.0` and
the V1 schema set remains 1.7.0.

## Contract 2.5.0 / V1 schema set 1.8.0 — Gate 2 manifest review projection

`EpisodeReviewView.release_approval_manifest: ReleaseApprovalManifest | None`
exposes the exact V2 metadata manifest to the owner-scoped Gate 2 review view.
It defaults to `None`, so prior V1 review responses/readbacks remain valid and
cannot acquire V2 authority by being re-read. The nested manifest is typed and
retains its own V2 schema version and canonical approval hash. Package version
advances to 2.5.0 and generated V1 schema IDs to 1.8.0; V1 `schema_version`
remains `1.0`, V2 remains `2.0`.

## Contract 2.6.0 — optional approved cover and CTA in V2 queues

The complete V2 `PublicationCommand` stale-queue binding now permits its
provider metadata projection to match an approved slot with no cover and/or
no CTA. The cover tuple must be either wholly absent or contain exact asset
ID, version and hash; partial tuples remain invalid. A populated projection
continues to be compared field-for-field with `ApprovedSlotMetadata`, so
omission or substitution cannot bypass the Gate 2 manifest. Legacy V1
`PostMetadata` parsing is unchanged. Package version advances to 2.6.0, V1
schema IDs remain 1.8.0, and V1/V2 schema versions remain 1.0/2.0.

## Contract 2.7.0 / V1 schema set 1.9.0 — Gate 2 creative derivatives

`ReleasePackage.creative_derivatives` optionally carries typed `POSTER` and
`EPISODE_ONE_PREVIEW` derivatives, separate from existing hook experiments and
release slots. Each derivative binds its output asset ID/version/hash, source
IDs/hashes and optional source ranges, per-source eligible rights, platform
safe-zone margins and title/CTA boxes, reveal boundary and no-release-obligation
assertion. Source references identify character, footage, audio, prop, title,
CTA or background roles and carry an eligible grant for that source, exact
version and hash. Previews require at least one ranged footage source and allow
ranged audio sources; the reveal boundary is on a footage source timeline.
Posters require
at least one character source, title/CTA boxes and no duration; previews require
source ranges, reveal boundary and duration at or below 90 seconds. Package
validation binds source hashes to accepted media (poster sources may also be
approved cast-package assets), limits previews to episode one, rejects duplicate
derivative types/IDs, and refuses derivative assets in release slots.

The field defaults to `None` so pre-2.7 package hashes and V1 readbacks remain
valid; when populated, the derivative list is included in `ReleasePackage`
`compute_hash()`. No publication obligation or hook slot is created. Package
version advances to 2.7.0, generated V1 schema IDs to 1.9.0; V1
`schema_version` remains `1.0` and V2 remains `2.0`.

## Contract 2.8.0 / V1 schema set 1.10.0 — preview audio lineage

`DerivativeSourceRef` now carries an exact source asset version and supports
the `AUDIO` role. Episode-one previews may combine accepted FOOTAGE and AUDIO
sources; every source requires an ID, version, hash, source range and eligible
rights grant, and at least one ranged FOOTAGE source is mandatory. The reveal
boundary is measured against a FOOTAGE source interval. Poster source roles,
character requirement and safe-zone constraints are unchanged. V1 packages
without derivatives remain hash/readback compatible. Package version advances
to 2.8.0 and V1 schema IDs to 1.10.0; V1/V2 schema versions remain 1.0/2.0.

## Contract 2.9.0 / V1 schema set 1.11.0 — derivation and poster review evidence

Each creative derivative now requires `derivation_manifest_sha256` and
`approved_reveal_episode`; the package rejects a derivative that reveals beyond
its episode, and an episode-one poster must bind reveal episode 1. Posters also
require `readability_evidence_sha256`. A poster without FOOTAGE cannot carry a
timecode reveal boundary; if it uses FOOTAGE, each footage source needs a source
range and any boundary must fall within one of those ranges. These fields join
the exact references/layout in the containing `ReleasePackage` hash. Packages
without derivatives remain V1 hash/readback compatible. Package version
advances to 2.9.0 and V1 schema IDs to 1.11.0; V1/V2 schema versions remain
1.0/2.0.

## Contract 2.10.0 / V1 schema set 1.12.0 — source-timeline reveal cutoff

`CreativeDerivativeRef.reveal_boundary_ms` is an approved FOOTAGE source-time
cutoff, not output-local time and not a point that must occur inside a used
source range. Preview output duration remains independently capped at 90 seconds.
Every preview FOOTAGE source must end at or before the cutoff; AUDIO ranges use
their own timebases and are not compared with it. This allows a 30–35 second
source excerpt to produce a 5-second preview with a 40-second cutoff. Poster
footage follows the same source-time cutoff rule; posters without footage cannot
carry a timecode boundary. V1 packages without derivatives remain compatible.
Package version advances to 2.10.0 and generated V1 schema IDs to 1.12.0; V1/V2
schema versions remain 1.0/2.0.

## Contract 2.11.0 — canonical directing manifest

`DirectingManifest` is a hash-bound V2 record for compiled shot directing. It
binds exact episode-pack ID/version/hash and approved scope, ordered sections,
shots and aggregate source hashes. `DirectingShot` uses stable shot/scene/beat/
section IDs, contiguous sequence, a maximum 15-second duration, typed state-in,
state events and state-out, screen axis/direction, eyeline, action handoff,
sound/edit intent, framing, dependency IDs and shot-local source hashes.
`DirectingSection` groups ordered shots with an exact summed duration capped at
45 seconds. A validator checks one-to-one shot membership, section order and
duration, embedded event/state consistency, exact EpisodePack scene/beat/entity
references, pack/scope freshness and required local source hashes. Pack hash is
bound at manifest level only; per-shot hashes stay local so targeted source
changes do not invalidate unrelated shots. The scene dependency hash omits the
beat list, while each shot separately binds its own beat hash. Package version advances to 2.11.0;
V2 `schema_version` remains `2.0`, V1 remains `1.0`.

## Contract 2.12.0 / V1 schema set 1.13.0 — render prompt-manifest locator

`RenderRequest` optionally carries `prompt_manifest_id` and
`prompt_manifest_sha256` together. Both absent preserves all existing V1
examples and readbacks; exactly one present is invalid. V2 paid dispatch must
provide both, load the matching `PromptManifest`, and verify its canonical
content hash before budget reservation or provider submission. The locator does
not replace the flat V1 `reference_asset_ids`; the V2 caller must derive those
references from the validated typed manifest. Package version advances to
2.12.0 and generated V1 schema IDs to 1.13.0; V1/V2 schema versions remain
1.0/2.0.

## Contract 2.13.0 / V1 schema set 1.14.0 — Runpod bucket billing reconciliation

The billing contracts keep provider query results, raw bucket revisions,
allocations and invoice verification as separate records. Query results preserve
requested and provider-resolved UTC windows, bucket size and raw response hash;
EMPTY and UNKNOWN are explicit states and cannot produce buckets or allocations
or imply a zero charge. Bucket observations bind account/pod/window/size identity,
monotonic revision/prior observation link, exact integer micro-USD GPU/CPU/disk/
total components, currency, raw response hash, observation time and finality.
Non-USD or component-total mismatches are accepted only as DISPUTED with a reason.

Allocations bind bucket revision, GPU/CPU/DISK component, EPISODE/RECOVERY owner,
MEASURED_OVERLAP/STORAGE_OWNER/UNCOVERED basis and signed micro-USD delta. Cross-
record validation requires each component's allocation deltas to sum exactly to
the current-minus-prior component amount; revision one sums to the full component.
Invoice/console verification links its exact evidence hash/time/amount to a bucket
revision. PROVIDER_REPORTED allocations do not become BILLED without a matched
INVOICE_VERIFIED bucket/evidence pair. V1 `UsageReceipt` schema and readback behavior
remain unchanged. Package version advances to 2.13.0 and generated V1 schema IDs
to 1.14.0; V1/V2 schema versions remain 1.0/2.0.

## Contract 2.14.0 — query-level bucket revision context

`validate_runpod_billing_query()` accepts an optional mapping from each current
bucket observation ID to its exact prior observation. Revision-one buckets
retain their no-prior path; later revisions fail closed without the mapping,
then verify monotonic revision, stable bucket identity, prior observation ID
and prior raw-response hash before validating signed component deltas. The V1
payload schema set is unchanged at 1.14.0; package version advances to 2.14.0.

## Contract 2.15.0 / V1 schema set 1.15.0 — semantic workflow mapping pin

`RenderRequest.semantic_workflow_sha256` is optional for legacy V1 calls, but
required exactly when the paired `prompt_manifest_id` and
`prompt_manifest_sha256` fields are present. The V2 worker must resolve and
hash-check that exact `PromptManifest`, compare the semantic-workflow hash to
the selected pinned code-native template/mapping, and persist the matching
RenderRequest before budget reservation and provider submission. Restart/replay
must load the same immutable mapping or persisted bound graph; a changed mapping
fails the new attempt closed. Legacy V1 requests with all three locator/hash
fields absent remain valid. Package version advances to 2.15.0; V1 schema IDs
advance to 1.15.0, with V1/V2 schema versions still 1.0/2.0.

## Change log

- **2.15.0 / V1 schema set 1.15.0** (2026-10-31, guardian): manifest-bound V2
  render requests also pin the semantic workflow/template mapping hash.

- **2.14.0** (2026-10-31, guardian): query-level validation now requires exact
  prior-observation context for bucket revisions after revision one.

- **2.13.0 / V1 schema set 1.14.0** (2026-10-31, guardian): add typed query,
  raw bucket revision, allocation-delta and invoice-verification payloads.

- **2.12.0 / V1 schema set 1.13.0** (2026-10-30, guardian): optional paired
  prompt-manifest ID/hash on render requests for V2 paid dispatch binding.

- **2.11.0** (2026-10-30, guardian): add hash-bound `DirectingManifest`,
  `DirectingShot` and `DirectingSection` contracts for T041a.

- **2.10.0 / V1 schema set 1.12.0** (2026-10-30, guardian): reveal boundaries
  are source-timeline cutoffs independent of derivative output duration.

- **2.9.0 / V1 schema set 1.11.0** (2026-10-30, guardian): derivative plans and
  poster readability/reveal approval are hash-bound in Gate 2 packages.

- **2.8.0 / V1 schema set 1.10.0** (2026-10-30, guardian): preview derivatives
  may bind dialogue/ambience audio lineage with source-specific rights.

- **2.7.0 / V1 schema set 1.9.0** (2026-10-30, guardian): Gate 2 packages may
  bind hash-bound poster and optional preview derivatives without creating
  release slots; see compatibility section.

- **2.6.0** (2026-10-30, guardian): V2 queue commands can faithfully represent
  manifest-approved absence of cover and CTA; partial cover bindings still fail.

- **2.5.0 / V1 schema set 1.8.0** (2026-10-30, guardian): optional typed
  `EpisodeReviewView.release_approval_manifest` for Gate 2 owner inspection.

- **2.4.0** (2026-10-30, guardian): `EpisodePack` requires
  `approved_scope_hash` for durable Gate 1 scope binding.

- **2.3.0 / V1 schema set 1.7.0** (2026-10-30, guardian): Gate 2 commands can
  carry a V2 release manifest hash separately from the V1 package hash;
  publication commands can carry exact manifest, metadata and policy locators;
  provider metadata projections now include complete cover/CTA fields, and V2
  slot metadata binds links, disclosures and catalog version; V2 adds a
  season-level story ledger. Legacy V1 metadata may still carry only a cover ID;
  V2 live validation requires the exact tuple.

- **2.1.0** (2026-10-30, guardian): `ConceptCandidate.rights` accepts an explicit
  pending/unknown assessment as well as the unchanged eligible `RightsGrant`;
  production rights gates remain strict. See the compatibility section above.

- **2.2.0** (2026-10-30, guardian): pack beats and scenes expose proof-object and
  dependency IDs, with same-pack resolution and acyclic graph checks. See the
  compatibility section above.

- **1.5.0** (2026-10-21, guardian, T012 warm-pod transfer): additive —
  `cost.PodLease.transferred_from: UUID | None = None` names the lease a warm-pod
  handover replaced (the `pod_leases.transferred_from` column has existed since
  migration 0003; only the payload lacked it). No existing field changed; every 1.4.0
  payload stays valid; `schema_version` stays `"1.0"`. Impacted lanes: T012 (writer),
  T013/T014 (readers of lease provenance).
- **1.4.0** (2026-10-20, guardian, M1 round-2 findings V-19, V-20, V-21, V-22, V-24, V-30):
  - `BudgetReservationRequest` refuses a zero unit price (a zero is not a known price).
  - GPU_GENERATION must be priced per GPU_SECOND, so the timeout bounds it.
  - `is_shutdown_or_cleanup` also requires `operation_kind` in `cost.CLEANUP_OPERATION_KINDS`
    (`pod.stop`, `pod.terminate`, `storage.cleanup`); a flagged render is refused.
  - New `cost.UNMETERED_OPERATION_KINDS` (empty): every provider operation needs a reservation
    until the guardian adds a reviewed unmetered kind.
  - New `jobs.API_ENQUEUEABLE_JOB_TYPES`, the closed list `POST /internal/jobs` accepts (schedules,
    webhook ingestion, status polling, analytics). Gate-dependent work, above all `publish.*`
    scheduling and submission, is enqueued only in-process by the service that owns its
    precondition.
  - `JOB_TRANSITIONS` gains QUEUED → NEEDS_RECONCILIATION and RETRY_WAIT → NEEDS_RECONCILIATION,
    so a quarantined job never emits a fake `job.running`.
  Stricter validation plus additive constants; `schema_version` stays `"1.0"` (nothing is
  persisted outside tests). Impacted lanes: T004, T005, and later T012/T013/T020 (operation kinds,
  pricing).
- **1.3.0** (2026-10-20, guardian, M1 validator findings V-1, V-3, V-10, V-12): stricter
  validation plus one additive field. `BudgetReservationRequest`: the worst case must cover
  `unit_price × exposure_units(unit, ceilings)`, where token prices need the matching token
  ceiling, media-second prices need `max_duration_ms`, GPU seconds are bounded by
  `timeout_ms`, and the result is never below `max_units` (missing ceiling = uncertain
  exposure = invalid). `is_shutdown_or_cleanup` is valid only on the production queue for
  GPU_GENERATION, RECOVERY_HEADROOM or CPU_STORAGE_TRANSFER (`cost.CLEANUP_CATEGORIES`).
  `CapabilityRecord`: any SUPPORTED_TESTED operation needs CONTROLLED_ACCOUNT_TEST evidence
  (FAKE_FIXTURE for mock fixtures; `release.TESTED_EVIDENCE_SOURCES`); documentation alone is
  never a test. `CostSummary` gains `shutdown_reserve_micro_usd` (default 0), and
  `remaining_micro_usd` is defined as headroom for paid dispatch (cap − committed − shutdown
  reserve, never below 0). The narrowing ships as a minor bump for the same reason as 1.2.0:
  no payload has been persisted outside tests; `schema_version` stays `"1.0"`. Impacted lanes:
  T005 and T006 (tests updated in their fix round), T008 (cost display), and every later
  lane that reserves money.
- **1.2.1** (2026-10-20, guardian, M0 re-validation N-2): the token-like path rule no longer
  refuses long readable lowercase hyphenated slugs; opaque segments (hex, base64url, mixed
  case, underscores) of 32+ characters are still refused. Loosening only; no payload that was
  valid becomes invalid.
- **1.2.0** (2026-10-20, guardian, M0 validator findings, before any consumer lane started):
  stricter validation only — `PostReadback.links` follow the fake/live URL rule (V-5);
  `QualificationResult` derives the streak from the episode list, a manual fix resets it and
  management QUALIFIED needs ten qualified windows (V-6); enabled dialogue presets need
  measured Thai support and non-zero measured quality (V-7); `PUBLISHED_VERIFIED` must name
  verified fields (V-16); an already-expired record cannot be ELIGIBLE (V-17); non-human
  principals cannot hold approve/approval/gate/reject/revise scopes (V-18); measured cost
  bases only from `LIVE_PROVIDER` provenance (V-19); links may not carry credentials or
  token-like path segments (V-21); `CreativeConstraints` limits are bounded by the enforced
  hard limits instead of being silently ignored (V-25). Narrowing changes are normally a
  major bump; they ship as 1.2.0 because no consumer had produced or persisted payloads yet
  (only test examples), and `schema_version` stays `"1.0"`. The build now records
  `json_schema_rejects` for every invalid example and requires the published schemas to
  reject the structural cases in `build.SCHEMA_MUST_REJECT` (V-13).
- **1.1.0** (2026-10-20, guardian, before M1 dispatch): additive — `RightsRecord`,
  `PresetRecord`, `PresetMeasurements` (`registries.py`) and enums `RightsSubjectKind`,
  `RightsStatus`. Reason: SPEC §4.1 rights/preset registries had no shared type, so T006
  (writer) and T014 (reader) would otherwise define incompatible local schemas. No existing
  field changed; `schema_version` stays `"1.0"`; all 1.0.0 payloads remain valid. Impacted
  lanes: T006, T014, T031 (none had started).
- **1.0.0** (2026-10-20, T002): initial freeze — the 28 SPEC §4.2 payloads plus
  `ProviderOperationResult` (29 core payloads) with valid
  and invalid examples, 38 supporting provider/job/view models, money/time/hash/
  error/state conventions, provider submit/status/reconcile interfaces, route
  and job signatures.
