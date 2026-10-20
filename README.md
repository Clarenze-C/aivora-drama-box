# AIVORA Drama Box

Automated original Thai micro-drama production and organic social operation.
Local checkout: `/root/AIVORA/drama-box`.

## Implementation branch

Claude's implementation is on
[`feat/microdrama-m0-m4`](https://github.com/Clarenze-C/aivora-drama-box/tree/feat/microdrama-m0-m4).
The branch name describes intended scope, not completed milestones. Its migrated
ledger records T001–T003/T007 ACCEPTED and T004–T006/T008 IN_PROGRESS, with M1
round-3 independent validation unfinished at source commit `7558c2d`.

```bash
git switch feat/microdrama-m0-m4
cd microdrama
```

See that branch's implementation README for environment/check instructions.
The `main` branch retains the original planning baseline; its initial TODO ledger
is historical. Use the feature branch's ledger to continue current work.

## Planning documents

- [Implementation SPEC](docs/microdrama-system/SPEC.md)
- [Multi-agent task breakdown](docs/microdrama-system/task_breakdown.md)
- [Research and operating design](deliverables/thai-microdrama-research-2026-10-19/README.md)
- [Migration provenance](docs/microdrama-system/MIGRATION.md)

Runtime quality, rights, GPU cost and real account publishing still require the
documented later validation. Migration does not deploy or enable live services.
