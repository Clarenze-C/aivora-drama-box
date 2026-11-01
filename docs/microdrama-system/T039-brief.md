# T039 — Script Maker and richer bible

## Goal

Let an owner submit a short original Thai story idea, genre/tone and episode count.
Generate bounded candidate scopes that the existing Gate 1 can approve without
the owner composing `SeasonScope`. After Gate 1, generate versioned character
logic, secret/reveal timing, first-three detailed episode packs and a later
episode map. Preserve exactly two routine human approval types.

## Ownership and source anchors

- Worker writes only `microdrama/src/microdrama/research/`,
  `microdrama/src/microdrama/story/`, scoped tests in
  `microdrama/tests/unit/{research,story}/` and their contract test folders.
- Existing bounded research/proposal service: `research/service.py:195–890`.
- Existing Gate-1-bound bible and episode writer: `story/service.py:384–950`;
  writer/critic payloads in `story/models.py` and `story/prompts.py`.
- Frozen V2 payloads: `contracts/v2.py` (`ConceptIntake`, `ConceptCandidate`,
  `CharacterLogic`, `SecretLedger`, `EpisodePack`, `StoryTime`). The worker may
  propose a contract change but cannot edit shared contracts/migrations.
- Owner intake UI and route registration belong to T044/integrator.

## Required behavior

Research consumes the existing bounded provider/budget envelope; no free or
unlimited candidate generation. Candidate-to-`SeasonScope` conversion must bind
the selected candidate and exact scope hash that Gate 1 approves. Planned
secrets cannot be exposed as character knowledge or prompt facts before their
reveal point. Packs list visible cast (including silent characters), props,
locations, proof objects, story day/time, required assets and scene/beat state.
The first three episodes have detailed packs; later episodes have a scoped map.
Thai dialogue and the 180–300 second approved episode duration remain enforced.

## Verification and handoff

Test idea → bounded candidates → existing Gate 1 approval → bible/packs/map,
hash/replay behavior, secret timing, missing asset/prop IDs, Thai and duration
bounds. Run scoped tests and Ruff, then `make check` after integration. Return
exact test receipts, contract version, limits and downstream factory/API needs.
Default OFFLINE_MOCK only; no provider spending or public action.
