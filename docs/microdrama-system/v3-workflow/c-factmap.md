# Phase C fact map — character bible, picks, wardrobe, voices, CAST LOCK (13 Nov 2026)

Paths: `S/` = `microdrama/src/microdrama/`, `M/` = `microdrama/migrations/`, `X/` = `microdrama/tests/`. Scratch migrations 0026/0027 (`.scratch/a0d-gate/`) are T031 benchmark experiments + A0 LLM gateway — nothing phase-C related in them.

## 1. References and identity lock

**Tables** (all `M/0002` unless noted):

| Table | Lines | Decisive columns/quotes |
|---|---|---|
| `reference_versions` | 0002:154–176 | `ref_kind IN ('FACE','VOICE','WARDROBE','LOCATION','STYLE')`; `state IN ('PROVISIONAL','ACCEPTED','LOCKED','SUPERSEDED','FAILED')`; `content_sha256`, `source_hash`, `license_hash`, `cache_key … full input/model/license hash`, `character_key`, `reviewed_in_package_id`; `UNIQUE (season_id, ref_kind, ref_key, version)` + `UNIQUE (season_id, cache_key)`; content-immutable trigger |
| `identity_locks` | 0002:254–268 | `source_episode_id` + `release_package_hash` both `NOT NULL`; `UNIQUE (season_id, version)`; `md_forbid_mutation` (append-only) |
| `identity_lock_assets` | 0002:270–280 | PK `(lock_id, reference_version_id)`, `asset_kind` same 5 kinds, append-only |
| `characters` | 0002:118–131 | `state IN ('PROVISIONAL','LOCKED','SUPERSEDED')`, `brief jsonb` |
| `voices` | 0002:134–152 | `provider`, `provider_voice_ref`, `rights_route_id`, `license_hash`, `anchor_asset_id`, same states |
| `episodes.identity_lock_id` | 0002:74 | nullable uuid |

**Lock creation** — `IdentityLocks.create_lock` (`S/references/identity_lock.py:82–281`), run by `IdentityLockHook.on_recorded` (`identity_lock.py:42–68`), "The ``ApprovalHook`` T008 calls inside the episode-one Gate 2 approval". Guards: only `GateType.EPISODE_FINAL` + `APPROVE` (`identity_lock.py:88`), `episode["episode_number"] != 1` → `SchemaInvalid` (`:100`), package must be `APPROVED` with hash matching the decision (`:114–124`). Members = `reference_versions WHERE season_id=%s AND state='ACCEPTED' AND reviewed_in_package_id IS NOT NULL AND asset_id=ANY(cast_package_asset_ids)` (`:130–132`). Side effects: members → `LOCKED`, voices/characters → `LOCKED` (`:211–229`), then stamps existing episodes:
```python
# identity_lock.py:238–241
"SELECT id, revision FROM episodes WHERE season_id = %s "
"AND episode_number > 1 AND identity_lock_id IS NULL FOR UPDATE"
```
Readers: `current_lock_row`, `members`, `broken_member_keys` ("Members whose version left LOCKED state", `identity_lock.py:284–293`).

**The R-12.1 bug — root cause confirmed:**
1. Episode creation sets no lock: `PipelineRunner.create_episode` (`S/pipeline/runner.py:290–310`) inserts only `id, season_id, episode_number, state='PLANNED', approved_scope_hash` — no `identity_lock_id`.
2. Lock creation stamps only episodes that already exist at that moment; an episode created **after** lock creation stays `NULL` forever.
3. `ReferencesService.attach_identity_lock` (`S/references/service.py:285–306`) exists to "Adopt the season's current lock onto a later episode created after the lock" but has **no production caller** — only tests (`X/unit/references/test_references_lock_hook.py:71,215`, `X/integration/validation/test_at03_identity_lock.py:112`).
4. The render gate then refuses: `render_request_bindings` (`service.py:310–345`) raises `IdentityLockRequired` with hint `"the season has a lock this episode has not adopted (attach_identity_lock)"` (`service.py:332`), and refuses again if `broken_member_keys` is non-empty ("a member superseded after the lock breaks it", `service.py` docstring `:310–317`). Hence "writer stalls at episode 2".

Contract-level enforcement: `ShotManifest._graph`: `if self.episode_number > 1 and self.identity_lock_id is None: raise ValueError("IMP-01: later-episode manifests must reference the identity lock")` (`S/contracts/season.py:467–468`; same in `S/contracts/cost.py:672`). QA binds lock members as `LockedAnchor` rows (`S/qa/comparison.py:608–629`). `PrepareOutcome.reference_lock_version` exists (`S/references/models.py:91`). Season-scoped; no version-selection API beyond `ORDER BY version DESC LIMIT 1`.

**ACCEPTED→lockable flow:** `mark_reviewed_in_package` (`service.py:240–265`) — "PROVISIONAL cast versions become ACCEPTED with ``reviewed_in_package_id`` set, which is exactly what the lock hook requires"; `cast_package_assets` (`service.py:266–283`) — "the episode-one cast package reviews the WHOLE cast — every live reference version of the season".

## 2. Assets and provenance

`assets` (`M/0004:4–33`): kinds `VIDEO/AUDIO/IMAGE/CAPTION/EDL/TRANSCRIPT/REPORT/CONTACT_SHEET/OTHER`; states `PROVISIONAL/ACCEPTED/FAILED/LOCKED/SUPERSEDED`; provenance enum (`0004:17–19`, typed at `S/contracts/enums.py:28–34`):
```python
FAKE_SYNTHETIC | LIVE_PROVIDER | DERIVED_LOCAL | ORIGINAL_FIXTURE | LICENSED
```
Content hashing: `sha256` + `generation_key` ("full input/model/settings hash") + immutable trigger (`0004:30–32`); `version` int default 1; `license_refs jsonb`; `descriptor jsonb` = `contracts.AssetDescriptor`. Lineage: `asset_lineage` append-only `derived_from` (`0004:41–49`).

- **`ProvenanceRecord`: NOT FOUND** (searched `ProvenanceRecord` across `microdrama/src` — zero hits; only the `Provenance` enum and per-asset `provenance` column exist).
- Registration path: `ReferencesService._register` (`S/references/service.py:849–888`) — `verify_generated(...)` → `store.put_bytes(object_key, ...)` → `AssetDescriptor(state=PROVISIONAL, provenance=self._adapter.provenance)` → `register_asset(tx, descriptor, generation_key=...)`.

## 3. Image generation adapters

| Seam | Where | Quote |
|---|---|---|
| `GenerationProvider` protocol | `S/contracts/providers.py:188–205` | "Image or voice generation. Outputs are fetched then copied to durable storage" — `submit(op, request: ImageRequest \| VoiceRequest)`, `status`, `reconcile` ("NOT_FOUND = safe to resubmit"), `fetch_output` |
| `ImageRequest` | `providers.py:156–170` | `model_config_ref`, `rights_route_id`, `prompt_text ≤4000`, `reference_asset_ids`, `width/height/seed`, `client_token`, `reservation_id` |
| Only implementation | `S/testing/fakes/generation.py` | `PROVIDER_ID = "fake-generation"` (`:48`), `MAX_IMAGE_SIDE = 64` (`:49`); real decodable PNG/WAV bytes (`make_png_bytes/make_wav_bytes`, `:55`); scenarios HAPPY/AMBIGUOUS_SUBMIT/NOT_ACCEPTED/DENIED_RIGHTS/LATE_BILLING/PARTIAL_OUTPUT (`:10–17`) |
| Wiring | `S/pipeline/world.py:379–380` | `image_provider=fakes.generation, voice_provider=fakes.generation` |
| Config switch | `S/references/config.py:21–58` | `image_price/voice_price: PriceQuote | None` — "None means 'unknown': every paid dispatch is refused typed" (`:11–14`); `image_model_config_ref="ref-anchor-image-v1"`, `image_rights_route_id="route-ref-image"` (`:23–26`); anchors 64×64 (`:41–42`) |
| Driver | `S/references/generation.py:196+` | `class GenerationAdapter` — budget reserve → submit → poll → fetch |

Image → asset: `_generate_anchor` (`S/references/service.py:737–826`) — `check_rights` → `image_call_plan` → `adapter.generate(build_image_request(...))` → `_register` → `_insert_reference`; object key `references/{season_id}/{REF_KIND}/{ref_key}/v{version}.png` (`:808–812`).

**Nano Banana / Gemini / Vertex adapter in drama-box: NOT FOUND** (searched `nano`, `banana`, `gemini`, `vertex` across `microdrama/src` — zero hits).

## 4. Picks / variant selection

- **Vote / re-roll / pick / lock for candidates: NOT FOUND.** Searched `reroll|re-roll|pick\b|vote` across `microdrama/src` — no pick-record, vote-table or re-roll queue exists.
- **`S/editing/variants*.py` is unrelated:** publishing aspect-ratio variants of the *finished episode* — `VariantSpec`/`plan_variant_specs` (`S/editing/variants.py:121,149`), `center_crop`/`punch_in_crop` (`:91–111`), `VariantsService` (`S/editing/variants_service.py:248`) for exports/covers/hooks.
- Closest existing mechanics: multiple coexisting versions per `(season, ref_kind, ref_key)` via `UNIQUE … version` (de facto candidates, but nothing records *which* was chosen except ACCEPTED/review state); `explicit_change` (`S/references/service.py:1414–1436`) versions one ref with a reason ("an explicit change requires a reason", `:1421`); `targeted_invalidation` (`S/references/v2_planning.py:1062–1078`) walks the dependency graph.

## 5. Wardrobe, appearance, props, locations

Frozen V2 records (persisted in `v2_contract_documents`, `M/0019:6–13`):

| Record | Where | Key fields |
|---|---|---|
| `StoryTime` | `S/contracts/v2.py:284–289` | `story_day`, `local_time`, `setting` (free text), `timezone="Asia/Bangkok"` |
| `WardrobeBible` / `OutfitDefinition` | `v2.py:397–417` | outfits valid for `story_day_from/until` + `setting_tags`; asset id/version/sha per outfit |
| `SceneWardrobeAssignment` | `v2.py:419–433` | per scene+character+day+setting; `reuse_reason` |
| `StateEvent` | `v2.py:438–455` | generic `(entity_id, field, before→after)` with scene-relative `effective_from_ms/until_ms`; validator "state event interval must be non-empty" |
| `PropSheet` | `v2.py:681–694` | `known_states` (≥1), `owner_character_id`, asset refs |
| `LocationLayout` | `v2.py:728–736` | `location_id`, `geometry_sha256`, `light_states`, `prop_ownership` |
| `AssetSheet` | `v2.py:656–657` | `asset_role: "character_identity"|"outfit"|"prop"|"location"|"style"|"voice"` |
| `EpisodeScene` | `v2.py:309–320` | `location_id`, `visible_character_ids`, `prop_ids`, `wardrobe_assignment_ids`, `state_in/out` |

Callable logic:
- `assign_scene_wardrobes` (`S/references/v2_planning.py:1289–1360+`): day-change prefers a different outfit; reuse needs a reason. Setting resolution: `setting = scene.location_id` with the comment "StoryTime.setting is descriptive prose in the frozen contract and is not an Identifier" (`v2_planning.py:1315–1317`).
- `outfit_for_scene_time` (`v2_planning.py:1067+`): resolves a timed `field=="outfit_id"` StateEvent to the exact bible outfit at `at_ms`.
- **Neither has a production caller** — grep for both names finds only `references/__init__.py` exports (`v2_planning.py:1429`, `references/__init__.py:66,110`). REQUIREMENTS.md:99 records the same as the R-4.2 gap: "WardrobeBible, day-based assignment and timed changes are callable but not wired; **the shot resolver ignores timed changes (gap)**".
- Render-side expectations do exist: `resolve_shot_reference_expectations` (`S/references/v2_binding.py:53–130`) takes `wardrobe_assignments`/`wardrobe_bibles`/`state_events` and is used by `V2ReferencePreflightContext.expectations_for` (`S/rendering/routing.py:556–600`, consumed at `routing.py:918`). Fact: the routing call site passes **no** `state_events` argument; the resolver's event supply is `directed_events = [event for item in directing_manifest.shots for event in item.events]` (`v2_binding.py:75–76`). Appearance states have no dedicated type — only generic `StateEvent` ("generic StateEvent only; no dedicated states, no generation", REQUIREMENTS.md:100).

## 6. Voices

- Registry: `voices` table (§1 table list, `M/0002:134–152`); voice anchors are `RefKind.VOICE` reference versions; voice rows inserted by `_insert_voice` (`S/references/service.py:927+`) with `external_id` as `provider_voice_ref`.
- Seam: same `GenerationProvider` protocol with `VoiceRequest` (`S/contracts/providers.py:172–186`): `voice_id`, `line_id`, `text_th ≤1000`, `locale: LocaleTag = "th-TH"`.
- Anchor: voice branch of `_generate_anchor` (`service.py:742–790`), object key `references/{season}/VOICE/{ref_key}/v{N}.wav`.
- Line audio: `_synthesize_line` (`service.py:987–1050+`), idempotent via `_line_asset_id` + descriptor reuse; result `LineAudio` with measured `actual_duration_ms` (`S/references/models.py:76–83`), persisted in `PrepareOutcome.lines`. **`LineAudio` is referenced nowhere under `S/rendering/`** (grep: no hits), and `build_render_request` hardcodes `audio_asset_id=None` (`S/rendering/routing.py:645`). Render requests carry `reference_asset_ids` + `identity_lock_id` (`routing.py:643–645`, from `RenderBindings` at `:1094`); `RenderBindings` includes `locked_ref_keys`/`provisional_ref_keys` (VOICE kinds among them) (`S/references/models.py:128–136`).
- **Botnoi / TTS / ElevenLabs / Pika in drama-box code: NOT FOUND** (searched `botnoi|tts|elevenlabs|pika` across `microdrama/src` — zero hits). The catalogue exists only as docs: `docs/microdrama-system/v3-workflow/botnoi-v4-voices.csv`, `botnoi-api-speakers-2026-11-11.csv`.
- **`OPERATOR_ATTESTED`: NOT FOUND** in `microdrama/src` (searched exact string). Today's voice rights basis is the generic fail-closed `check_rights` on `route-ref-voice-th` (§7).

## 7. Rights registry

`rights_registry` (`M/0006:35–55`): `subject_kind IN ('MODEL','MODEL_OUTPUT','VOICE','MUSIC','FONT','REFERENCE','STOCK')`; `territories jsonb` (ISO codes, "empty = unknown"); `commercial_use`/`output_release_allowed` "NULL = unknown (blocks)"; `required_disclosures`, `expires_at`, `evidence jsonb`; `status IN ('ELIGIBLE','INELIGIBLE','UNKNOWN','EXPIRED')` with CHECK that ELIGIBLE requires non-empty evidence+territories; partial unique index on `current`. Typed record `RightsRecord` (`S/contracts/registries.py:37`).

Gate: `check_rights` (`S/references/generation.py:166–193`) — "Fail-closed rights gate (MD-015/AT-13)… A missing route/registry configuration is a blocker, never a fabricated licence"; evaluates MODEL+MODEL_OUTPUT subjects at `territories=["WORLDWIDE"]`, raises `RightsUncleared`, returns a licence hash. Route ids today: `route-ref-image`, `route-ref-voice-th` (`S/references/config.py:25–26`). V2 documents each carry `rights_route_id`/`rights_version`/`valid_from`/`valid_until` (`M/0019:12–16`). No per-voice/per-community approval flow exists.

## 8. Cross-system Nano Banana lock

**ARISA side** (read-only):
- `provider_generation_lock` — `/root/AIVORA/arisa/studio/sfw/recovery.py:91–105`:
```python
"""Same inode through the host and /workspace bind, including PPV imports.
flock works on a read-only file descriptor; ..."""
with Path(__file__).with_name('vertex-generation.lock').open('rb') as handle:
    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)  # BlockingIOError →
    raise ProviderQuotaError('shared Vertex generator busy', retry_after=20)
```
- Lock file exists: `/root/AIVORA/arisa/studio/sfw/vertex-generation.lock` (98 B, mode 644). Cross-container via the bind mount (same inode), no container name or quota keeper involved.
- Taken around the single Vertex POST: `VertexProvider.generate` (`arisa/studio/sfw/providers/google_vertex.py:172–191`), `with provider_generation_lock(): response = self.transport(payload)`. `google_interactions.py` has 0 references to it. Tests prove re-entry refusal (`arisa/studio/sfw/tests/test_recovery.py:26–30`).

**Drama-box equivalent: NOT FOUND.** Only transaction-scoped Postgres locks exist — `pg_advisory_xact_lock` at `S/budget/billing.py:256,297,496,828`, `S/story/v2_store.py:65`, `S/persistence/migrate.py:86` — none file-based, none shared with ARISA, none around provider dispatch.

## 9. Demand-list hand-off (phase B §4.3 → phase C)

Phase B will emit `SeasonDemandListV3` (`docs/microdrama-system/v3-workflow/phase-B-spec.md:277+`): one `LogicalDemand` per item, kinds `CHARACTER | OUTFIT | APPEARANCE_STATE | PROP | LOCATION(+light_state) | EXTRAS_ROLE | VOICE`, `demand_id = uuid5(STORY_V3_NS, "demand:<planning_scope_id>:<kind>:<logical key>")` stable across revisions, episodes+scenes listed, two-way check against pack references.

Today's nearest structures:
- `AssetDemand` dataclass (`S/references/v2_planning.py:51–59`): `role, subject_id, view_name, prompt, cache_key, rights, estimated_micro_usd, seed` — per-image, not per-logical-item; built by `plan_reference_demands` (`v2_planning.py:1088`).
- `demand_key` (`v2_planning.py:1384–1396`): "Full semantic cache/cost key; rights route, subject and exact version are included" (`canonical_hash` incl. lineage).
- No demand persistence: grep for `demand` across `M/*.sql` — no hits.
- Season-wide cast inventory: `cast_package_assets` (§1).

## 10. Gaps phase C must create from zero

1. Picks layer: pick/vote/re-roll records, candidate grids, "pick = record a vote", lock-refused-until-all-picked (V3-AT-5) — nothing exists; only version rows + `explicit_change` + `mark_reviewed_in_package`.
2. Season-scoped CAST LOCK contract (today's lock is created only by the episode-1 Gate 2 approve and requires `source_episode_id` + `release_package_hash`); lock versions selectable by episode creation date; the V3 plan removes lock creation from the Gate 2 path (SPEC-v3.md §4.4.5).
3. The R-12.1 fix: auto-attach at episode creation (`create_episode` sets no lock; `attach_identity_lock` is dead production code).
4. Dependents/invalidation on parent re-roll (V3-AT-22): only `targeted_invalidation` (generic graph walk) exists; face→outfit/view dependencies are not modeled.
5. Sheet views, expression sets, extras pool, appearance-state records, props-as-picks, location coverage plates: all NOT FOUND (`sheet view|expression set|extras` greps empty; extras/roles have no type).
6. Botnoi voice catalogue registry (CSVs are unloadable docs), voice expression family, upload/zip quarantine pipeline (V3R-1), normalisation profile, audition — all absent; voice seam is the generic fake provider only.
7. `ProvenanceRecord` (V3-AT-33): absent; provenance is one enum column + lineage rows + `license_refs jsonb`.
8. Cross-system Nano Banana single-process lock (V3-AT-15/28): absent on the drama-box side; ARISA's inode-shared flock is the pattern to interoperate with.
9. Demand persistence for `SeasonDemandListV3` (no table today); image-volume projection / cost forecast panels show `NOT_AVAILABLE` until C ships (phase-B-spec.md §4.3).
10. Timed wardrobe in dispatch: `outfit_for_scene_time`/`assign_scene_wardrobes` unwired; routing's preflight passes no `state_events` (§5).
