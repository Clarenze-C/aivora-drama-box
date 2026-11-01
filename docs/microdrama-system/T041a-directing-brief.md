# T041a — episode-pack directing compiler

## Goal

Compile an approved, versioned V2 EpisodePack into scene/beat/short-shot
directing records with state-in → event → state-out, screen direction, eyeline,
action handoff, sound and edit intent. Group shots into approximate 30-second
editorial sections for the owner UI, while every renderable shot is at most
15 seconds. Preserve original Thai reveal timing and the two existing gates.

## Ownership and inputs

Worker writes only `microdrama/src/microdrama/story/` and scoped
`microdrama/tests/unit/story/` or `tests/contract/story/` paths. Existing V1
compiler is `story/compiler.py`; T039 pack/ledger services are in
`story/script_maker.py`; frozen package 2.10.0 contracts include EpisodePack,
StateEvent, StoryTime, ShotManifest and PromptManifest. T040 reference and GPU
workflow code are consumers, not worker-owned. Cross-module payload changes
must be proposed to contract guardian before consumers depend on them.

## Acceptance

Bind exact approved scope and pack hashes; reject contradictory/unknown state
events, impossible prop holder/hand, missing visible cast, future-secret leak,
screen-axis/eyeline or handoff discontinuity before any paid step. Emit stable
scene/beat/shot IDs, <=15s shot durations, section membership and source hash
dependencies so changed input invalidates only affected shots. A V1 manifest
readback is audit-only until recompiled to V2. Test a composed pack→directing
trace with day/setting and prop handoff transitions, same/next-day wardrobe
context, idempotent recompilation and targeted invalidation.

Run scoped tests and Ruff; parent runs full `make check` after T041b. No paid
provider/cloud/public action, no commit. Return changed paths, exact tests,
contract version, missing contract proposal and T041b handoff signatures.
