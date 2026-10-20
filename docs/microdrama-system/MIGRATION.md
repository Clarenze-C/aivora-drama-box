# Migration to AIVORA Drama Box

Migrated 20 October 2026 to `Clarenze-C/aivora-drama-box`, with local checkout
`/root/AIVORA/drama-box`.

- Source repository: `Clarenze-C/AIVORA-Root`.
- Source branch: `feat/microdrama-m0-m4`.
- Source checkpoint: `7558c2d811c7bacb2538d3c92156b10612c19da2`.
- Imported paths: `microdrama/`, `docs/microdrama-system/`, and
  `deliverables/thai-microdrama-research-2026-10-19/`.
- Verified source checkpoint: **422 project files**, identical Git blob IDs before migration-only documentation/path changes.
- Preserved **25 project commits**, including original author/committer metadata and messages.
- [Source-to-filtered commit mapping](source-commit-map.csv).

The new `main` starts from the planning baseline. The feature branch replays
only the project-scoped snapshots, followed by migration documentation updates.
Commit IDs differ because unrelated AIVORA trees/history and original parents
are excluded. This imports no unrelated AIVORA source or private history into
this public repository. The old source branch is retained as provenance.

Implementation paths and orchestration instructions now point at this checkout.
The Python module/package and relative sibling document/research layout are
unchanged. Historical receipts may still mention source commit IDs or the old
working directory; use the mapping to locate their imported equivalents.

## Honest continuation point

M0 tasks T001–T003/T007 are recorded ACCEPTED. T004–T006/T008 remain IN_PROGRESS
pending unfinished M1 round-3 independent validation. Do not reset that ledger
or infer M4 completion from the branch name. No runtime code or task acceptance
was changed during migration.

Migration validation checks file hashes, project-only history scope, local
links, schemas/ledger readability and branch publication. Historical application
test receipts are not rerun or re-certified by these checks. The local migration
host has Python 3.12; the imported application documents Python 3.13 requirements.
