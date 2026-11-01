# T038 contract freeze brief

## Goal

Publish one canonical V2 contract family for concept intake, story logic, episode packs,
story time, wardrobe/state, typed reference bindings, prompt manifests and event-derived
progress. Preserve V1 audit readback while explicitly declining V2 readiness for a V1
manifest. Do not import the production kit's `E001` IDs, 15–600 second episode bound,
free-form state objects or lifecycle statuses as Drama Box authority.

## Inputs and ownership

- Authority: `SPEC.md` §§2, 4, 7–8, 11, 13 and `task_breakdown.md` T038.
- Existing source of truth: `microdrama/src/microdrama/contracts/`,
  `microdrama/contracts/`, `microdrama/migrations/` and contract tests.
- Design input only: `microdrama.cc-production-kit/schemas/{episode_pack,continuity_ledger,asset_registry,storyboard}.schema.json`.
- Contract guardian owns all shared schema, migration, registry and generated artifacts.
  Downstream T039–T044 must wait for the frozen version and signatures.

## Crosswalk to freeze

| Kit concept | Canonical target | Boundary |
|---|---|---|
| Episode pack and beats | `EpisodePack`, versioned episode/scene/beat IDs, reveal/asset ledgers | Existing UUID episode identity and 180–300 second scope win. |
| Continuity event | `StateEvent`, `StoryTime`, scene state and explicit in/event/out | Typed state, story day, validity interval and contradiction checks; no free-form authority. |
| Asset registry | `AssetSheet`, `WardrobeBible`, `SceneWardrobeAssignment`, `LocationLayout` | Exact asset ID/version/hash, role/subject, rights and validity; identity and clothing stay separate. |
| Storyboard reference policy | `ShotReferenceBinding`, `PromptManifest` | Semantic roles and exact versions; no positional asset list or unsupported workflow control. |
| Task/progress status | `ProgressSnapshot` | Projection from durable events/jobs/assets/reviews/posts; no independent business state. |

`ConceptIntake`, `ConceptCandidate`, `CharacterLogic` and `SecretLedger` also require
typed contracts. Every new top-level payload needs valid and invalid examples, generated
JSON Schema, canonical hash behavior and an explicit compatibility note. Reject role-less,
retired-rights, stale-outfit and contradictory-state inputs before any paid dispatch.

## Implementation and gate

Add source models and register them in `registry.py`; add deterministic examples in
`examples.py`; generate artifacts via `make contracts`; add ordered migration(s) and
upgrade/readback tests. Version the contract deliberately (expected major V2) and record
what legacy V1 readers can still consume. Test with `make contracts-check`, scoped
contract tests and migration tests, then `make check` once T048 has repaired the date
fixture. No cloud, GPU, provider or public action is part of T038.
