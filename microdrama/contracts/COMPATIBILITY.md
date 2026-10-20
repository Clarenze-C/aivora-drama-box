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
- **Fake-evidence records (V-4, accepted with mitigation).** `CapabilityRecord`,
  `RightsRecord` and `PresetRecord` backed only by `FAKE_FIXTURE` evidence may be
  enabled/ELIGIBLE *as mock fixtures*; the offline mock pipeline cannot run without them.
  The registries (T006) must treat such records as UNKNOWN/disabled in every non-OFFLINE_MOCK
  mode. T030 verifies this from behaviour.
- **Package hash scope (V-14, rejected with mitigation).** `package_hash` covers media,
  captions, release scope, management-policy hash and the QA summary, but not `gate_blockers`
  or `cost`. Blockers are derived state, recomputed at decision time by the review service.
  Migration 0007 lets an APPROVED package bind only an approval with matching hashes and an
  empty blocker list.
- **Feedback repair rounds (V-20, no change).** SPEC §5 rule 5 bounds human-requested
  revisions by remaining budget, not by a round count; only automatic final-QA repair is
  capped at two rounds.
- **Caption timing in the package (V-22).** The Gate 2 conditions (T008) must block when any
  package caption track's `caption_tracks.timing_source` is not `ACTUAL_AUDIO_ALIGNMENT` or
  its state is not CURRENT.
- **Float literals (V-12 residual).** The persistence layer refuses float bind parameters.
  A float *literal* written into SQL source would still be cast by PostgreSQL; code review
  catches those, and no DB check can see the pre-cast value.

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
- **1.0.0** (2026-10-20, T002): initial freeze — 29 SPEC §4.2 payloads with valid
  and invalid examples, 38 supporting provider/job/view models, money/time/hash/
  error/state conventions, provider submit/status/reconcile interfaces, route
  and job signatures.
