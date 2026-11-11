# Phase B fact map (GLM swarm): today's code for Script Maker, bible, episode packs and STORY LOCK

Orchestrator: Opus, 11 Nov 2026. The orchestrator will write the phase B spec from your facts. **Facts
only:** no design and no recommendations. **Read-only. Write no files.** Put the whole fact map in your
final message.

## Where

- Repo `/root/AIVORA/drama-box`, branch `feat/microdrama-m0-m4` (the main checkout). Code is under
  `microdrama/src/microdrama/` (cite it as `S/…`), migrations under `microdrama/migrations/` (`M/…`), and
  tests under `microdrama/tests/` (`X/…`).
- Migration 0026 exists only in `/root/AIVORA/drama-box/.scratch/t031-gate-h2/microdrama/migrations/`.
- For the v3 context, skim `docs/microdrama-system/v3-workflow/SPEC-v3.md` §4.1–§4.3 and §13. Don't
  summarise it back.

## Rules for every fact

- Cite `file:line` and quote the decisive line or signature (≤ 2 lines).
- If you searched and found nothing, write **NOT FOUND** and the search terms you used. Never guess.
- Keep the whole answer under about 350 lines. Use tables.

## Facts needed

1. **Season proposal today (Script Maker equivalent):** the models and services that create a season
   concept/proposal from a title or from research; their fields; the LLM calls and prompts used; where
   the proposal is stored (table, content hash, revision).
2. **Gate 1 / `SEASON_CONCEPT`:** the approve/reject paths (`core/approvals.py`, `review/api.py`, SQL
   CHECKs in the 0002 migration), what happens on approval (jobs enqueued, state changes), and whether any
   revise path exists.
3. **Duration and count validators:** every constant or validator for episode count, episode target
   length, recap length and CTA length, in `SeasonScope`, `EpisodePlan`, `EpisodePack`, intake and
   candidates, and anywhere else. Table: file:line → field → current rule.
4. **Story records:** for `EpisodePlan`, `Script`, `EpisodePack` (V2) and any bible, character, location,
   prop, wardrobe, continuity or secret-ledger record:
   - the fields, the schema version field, IDs, revisions and hashes;
   - the storage (table or object store) and how historical records are validated;
   - **every consumer** downstream (directing/shot compiler, references, editing, packaging, QA,
     publishing), as `file:function`.
5. **Dialogue lines:** the line model: speaker, language fields, emotion or delivery fields, duration
   estimates, and any per-episode or per-shot speaker counting.
6. **Characters and identity:** how characters are defined today, any tiering (principal/supporting/
   extra), identity locks, and how a character is referenced from a scene or shot (by ID or by name).
7. **Episode row creation:** when and by what code `episodes` rows are created, their initial state, and
   any coupling to the release cadence or calendar.
8. **Critics:** any story/episode/season critic or validator that runs today, with its inputs and its
   failure behaviour.
9. **Research (Mode A equivalent):** the research service, its sources and providers, and where V1 entry
   points call it.
10. **LLM plumbing today:** the `LLMProvider` protocol, its offline fakes, the models and prompts used for
    story work, and how outputs are parsed and validated.
11. **Contracts:** the contract package version on this branch, where `EpisodePlan`/`EpisodePack`/
    `Script` schemas are generated and exported, and the tests that pin them (exact-schema tests,
    examples).
12. **V1 tests that pin story behaviour:** the test files that would break if any of the above changed.

End with a list of the files you read.
