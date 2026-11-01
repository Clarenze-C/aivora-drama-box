# AIVORA Drama Box

Automated original Thai micro-drama production and organic social operation.

## Project entry points

- [Implementation SPEC](docs/microdrama-system/SPEC.md)
- [Production app review and plan](docs/microdrama-system/production-app-review-and-plan.md)
- [Current-build V2 findings](docs/microdrama-system/build-review-v2-2026-10-28.md)
- [Multi-agent task breakdown](docs/microdrama-system/task_breakdown.md)
- [Current task ledger](docs/microdrama-system/task_status.csv)
- [Research and operating design](deliverables/thai-microdrama-research-2026-10-19/README.md)
- [Python implementation and check instructions](microdrama/README.md)
- [Migration provenance and source commit map](docs/microdrama-system/MIGRATION.md)

## Current implementation checkpoint

This branch is `feat/microdrama-m0-m4`, migrated from Claude's work in
`Clarenze-C/AIVORA-Root` at `7558c2d811c7bacb2538d3c92156b10612c19da2`.
The branch name describes its intended scope, not completed milestones.

The current ledger records T001–T030 as ACCEPTED, including the offline M4
workflow. The 26 October 2026 remediation record documents the fixes for the
subsequent build review. The V2 SPEC and ledger add pending T036–T048 for
current-build defects and the new production app. The 28 October full offline
check currently fails in integration because a fixed-time test owner session
has expired; T048 tracks that repair. T031–T035 remain TODO and require live
provider, rights, cost, publishing and episode evidence.
Historical migration receipts are preserved; the migration alone did not
re-certify them.

All software remains offline/mock by default. Live model quality, rights,
GPU costs and real publishing require the documented later validation tasks.

## Local layout

Repository checkout: `/root/AIVORA/drama-box`.
The implementation retains `microdrama/` and the Python package name
`microdrama`; documentation and research remain adjacent at repository root.

```bash
cd /root/AIVORA/drama-box
git switch feat/microdrama-m0-m4
cd microdrama
make install
make check
```

See the implementation README for required Python 3.13, PostgreSQL, Redis and
FFmpeg prerequisites. The `main` branch retains the original planning baseline;
continue implementation on this feature branch.
