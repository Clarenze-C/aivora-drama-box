# T039 finish brief — bounded Script Maker

## Goal

Complete T039 against contract package 2.3.0. A short owner idea, genre/tone and
episode count must reach the existing Gate 1 proposal without an owner-written
`SeasonScope`; after Gate 1, produce a versioned season story ledger, rich
character/secret bible, detailed first-three packs and a later-episode map.
Preserve the two human gate types, original Thai, 180–300-second approved
episodes, bounded spending, replay/idempotency and future-secret isolation.

## Existing partial work and claimed paths

The shared checkout has uncommitted partial work in
`microdrama/src/microdrama/research/script_maker.py:1–470`,
`microdrama/src/microdrama/story/script_maker.py:1–930`, their `__init__.py`
exports, `story/prompts.py`, and tests
`tests/unit/research/test_script_maker.py` and
`tests/unit/story/test_v2_story_packs.py`. The latter test file was renamed to
avoid pytest's duplicate-module-name collection error. Their combined six
focused tests pass; `make contracts-check` passes. This is not T039 acceptance.
The remaining build may edit only `research/`, `story/`, and scoped tests under
`tests/unit/{research,story}/` or a new T039-specific integration test folder.
No edits to `contracts/`, migrations, review, publishing, root config or ledger.

## Contracts and integration

Use frozen `ConceptIntake`, `ConceptCandidate` with pending rights,
`SeasonStoryLedger`, `CharacterLogic`, `SecretLedger`, `EpisodePack`, proof-object
and dependency fields. Candidate-to-Gate1 binding must use the exact persisted
provenance-stamped `SeasonScope` hash. Do not invent rights or source evidence.
The existing `ResearchService.run_research()` at `research/service.py:299` needs
candidate scopes supplied; its budget/ledger remains authoritative. Existing
Gate1 compiler `StoryService.compile_season()` at `story/service.py:473` checks
the approved scope hash. Export factories/services; integrator owns route/job
registration and T044 owner UI.

## Finish and verify

Make a concrete offline composed path from short idea through bounded fake LLM
candidate generation, ResearchService proposal, existing Gate1 decision and
post-gate rich bible plus first-three/later map. Add tests for malformed/empty
ideas, missing price/rights, provider failure charges, replay with no extra
cost, exact chosen scope hash, secret reveal timing, typed prop/proof/dependency
IDs, Thai/duration bounds and post-gate sequencing. Preserve existing V1 tests.

Run Ruff check/format, focused T039 tests and story/research suites. Run
`make check` under `systemd-run -p CPUQuota=45%` only after scoped tests pass.
No paid/cloud/public effects; no commit. Return exact paths/results, remaining
integration needs and any contract proposal rather than filling gaps locally.
