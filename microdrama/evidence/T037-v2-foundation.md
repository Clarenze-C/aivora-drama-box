# T037 — live metadata and W09 recovery foundation

Contract package 2.6.0. Software tests use fake transports only; no public or
paid provider action occurred.

W09 discovers reconciled-absent `SUBMITTED` slots and rebuilds commands from
their exact approved package and current metadata. Migration 0021 stores
immutable V2 manifest/slot metadata and a separate hash on the existing human
Gate 2 approval event while preserving the V1 package-hash binding. The review
service accepts owner-supplied metadata, displays the complete manifest in the
authenticated review surface and binds it in the same Gate 2 decision. Live
submission fails closed for missing/stale manifest, approval, slot metadata,
capability, policy, rights, catalog, cover or CTA changes. An approved null
cover/CTA remains valid when the slot policy permits it. OFFLINE_MOCK retains
its explicit synthetic path.

Independent review found a fresh-live-first-submit projection defect. The
owning lane now projects the approved slot metadata when no legacy current row
exists, uses the deterministic initial metadata ID, persists/readbacks it
before the fake transport call, and retains rearm's current-version behavior.
Scoped re-review found the behavior coherent; direct fresh-live transport
ordering still needs a composed fixture in T047.

Observed checks:

- Scoped review/publishing/migration tests: 260 passed in the main targeted
  run; focused first-submit/contract tests: 61 passed; schema-catalog and
  migration tests after integer-guard correction: 12 passed. Ruff passed.
- Integrated `make check` under `systemd-run -p CPUQuota=45%`: exit 0; contracts
  and Ruff passed, unit phase passed, 451 contract and 180 integration tests
  passed.
- `make pilot` under the same CPU limit: W01–W12 passed, exactly two human
  gates, 16 local FFmpeg exports and 303,000 synthetic micro-USD settled.

T037 remains in REVIEW: T044 must invoke
`ReviewService.prepare_release_approval_manifest` from the owner workbench
before the existing Gate 2 approval. No code currently fabricates owner
metadata or adds another routine gate. T047 must exercise the composed V2
live-like fixture path before this software milestone can close. Real-account
qualification is T032.
