# T037 — Gate 2 live metadata integration brief

## Goal

Complete the remaining offline software path in
`T037-live-metadata-spec.md`: persist an immutable V2 release approval manifest,
bind its hash in the existing human Gate 2 event alongside the legacy package
hash, and verify exact approved slot metadata before any non-mock submit.

## Owned files and anchors

This is an explicitly assigned integrator/foundation task. Worker may edit an
ordered new migration, `core/approvals.py:50–112`, `review/service.py:640–810`,
`review/packages.py:100–230`, `publishing/{commands,metadata,service}.py`,
`scheduling/service.py:540–625`, `pipeline/runner.py:615–745`, and scoped
unit/contract/integration tests for those modules. Worker must coordinate any
new route/job registration or root dependency changes with the orchestrator;
none are preauthorized by this brief. `contracts/` is frozen at 2.4.0 and only
the guardian may change it.

## Existing invariants

- Gate 2 `ApprovalCommand.package_hash` continues to equal the V1
  `ReleasePackage.package_hash`; existing database triggers rely on this.
- New `release_manifest_hash` is separate, optional for V1/offline readback,
  and required for a V2 live approval. An approval event binds both hashes in
  one transaction. A later update cannot attach V2 authority to old approval.
- The V2 manifest binds package ID/hash, slot ID, complete provider-visible
  metadata, cover ID/version/hash, CTA and mutation policy. Its exact current
  version is checked before transport. V1-only approvals are held in live mode.
- The mock metadata path remains explicit in `OFFLINE_MOCK`; no mock label or
  fixture provenance can authorize a live transport.
- Do not weaken the existing owner-session, media, capability, rights,
  budget, idempotency, release DAG or one-approved-package constraints.

## Test gate and handoff

Add isolated migration upgrade/readback/restart and pre-migration compatibility
tests. Fixture tests must cover Gate 2 manifest binding, exact current metadata
projection and all stale/missing/tampered package, event, policy, slot, cover,
CTA, disclosures, links and catalog cases; prove no live transport call when
blocked. Preserve the W09 absent-rearm single-flight tests. Run scoped tests,
Ruff, `make contracts-check`, `make pilot` and `make check` after integration;
use `systemd-run -p CPUQuota=45%` for the heavy full gate. Report exact
results, limitations and external effects (expected none). Do not commit.
