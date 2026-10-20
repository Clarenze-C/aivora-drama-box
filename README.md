# AIVORA Drama Box

Automated original Thai micro-drama production and organic social operation.

## Project entry points

- [Implementation SPEC](docs/microdrama-system/SPEC.md)
- [Multi-agent task breakdown](docs/microdrama-system/task_breakdown.md)
- [Current task ledger](docs/microdrama-system/task_status.csv)
- [Research and operating design](deliverables/thai-microdrama-research-2026-10-19/README.md)
- [Python implementation and check instructions](microdrama/README.md)
- [Migration provenance and source commit map](docs/microdrama-system/MIGRATION.md)

## Current implementation checkpoint

This branch is `feat/microdrama-m0-m4`, migrated from Claude's work in
`Clarenze-C/AIVORA-Root` at `7558c2d811c7bacb2538d3c92156b10612c19da2`.
The branch name describes its intended scope, not completed milestones.

The imported ledger records T001–T003 and T007 as ACCEPTED. T004–T006 and T008
remain IN_PROGRESS: M1 round-3 independent validation was unfinished at the
source checkpoint. Resume that validation before starting dependent work.
Historical test receipts are preserved; the migration does not re-certify them.

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
