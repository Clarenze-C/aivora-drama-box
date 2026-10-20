# Contract v1.0.0 — conventions and compatibility notes (guardian-owned)

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

## Changing a contract

A worker that needs a missing field **stops** and returns a contract-change
proposal (field, type, reason, downstream impact, migration/compatibility
handling, tests). Only the guardian edits `src/microdrama/contracts/`, bumps
`CONTRACT_VERSION`, regenerates with `make contracts`, records the change
below and notifies affected lanes.

- Additive optional field: minor bump (1.x.0); old payloads stay valid.
- New required field, removed field, narrowed enum/range: major bump; schema
  version string changes; migration notes required.

## Change log

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
