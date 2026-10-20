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

- **1.0.0** (2026-10-20, T002): initial freeze — 29 SPEC §4.2 payloads with valid
  and invalid examples, 38 supporting provider/job/view models, money/time/hash/
  error/state conventions, provider submit/status/reconcile interfaces, route
  and job signatures.
