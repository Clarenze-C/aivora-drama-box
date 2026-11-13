# Phase C: Character bible → picks → wardrobe → voices → CAST LOCK

**Version 0.1 DRAFT, 13 Nov 2026.** Author: GLM (spec draft job); orchestrator Opus.

**Status: DRAFT for Goldfish, then Codex critique.**

**Master:** [SPEC-v3.md](SPEC-v3.md) v0.4.6. **Depends on:**
- [phase-A0-spec.md](phase-A0-spec.md) v0.4 (`LlmStep`; C consumes the jobs/runtime schema, adds no LLM calls);
- [phase-A-spec.md](phase-A-spec.md) v0.3: gates, the decision transaction, budget accounts/steps, the fence, the command table;
- [A1-design-note.md](A1-design-note.md) v1.2 (+ A2/A3 notes): migrations 0028–0034+, `budget_steps.step_key`, `work_scope`, the lock order;
- [phase-B-spec.md](phase-B-spec.md) v0.3: `SeasonDemandListV3` (§4.3), the STORY LOCK hand-off, `v3_story_documents`.

**Facts:** [c-factmap.md](c-factmap.md) (13 Nov), cited `FM §n`. The orchestrator's spot-checks confirmed
FM §1 (DDL and dead callers), §3, §5 (helpers unwired), §6–§8. Code references relative to
`microdrama/src/microdrama/` (`S/`); migrations `M/`; tests `X/`. Migration numbers here are **symbolic
`C-1…C-n`**; real numbers are allocated in the C1 note after A and B land.

**Owns:** V3-AT-5, 6, 7, 15, 22, 23, 28 (offline half), 33 and R-4.1..R-4.11, R-12.1..R-12.5, R-12.9
(master §15.1–15.2). V3-AT-28's live half (real ARISA) is phase G's.

---

## 0. Scope

**Phase C builds tab 4 of the stepper and the CAST LOCK gate:**
1. **Pick items** derived from B's `SeasonDemandListV3`: candidates, votes, re-roll, "generate next",
   dependent invalidation — the picks engine and its UI.
2. **Image generation:** the Nano Banana adapter seam (fake by default, live behind a per-provider
   switch), the **cross-system single-process lock** shared with ARISA, queue lanes, metering through
   phase A's accounts, the image-volume projection and cost forecast (the panels B §4.3 left
   `NOT_AVAILABLE`).
3. **Wardrobe per story day** with timed changes across episode boundaries, appearance states, props,
   locations with coverage plates, extras looks — castkit/scenecraft packages by tier.
4. **Voices:** the two-source Botnoi catalogue, the deterministic shortlist, the audition record, the
   casting sheet, the **upload intake** (trust boundary, quarantine, normalisation, `OPERATOR_ATTESTED`
   rights). One neutral reference per speaker; **no per-emotion variants**.
5. **CAST LOCK:** the season-scoped lock contract through phase A's decision transaction, the R-12.1
   fix, season-2 import.
6. **Provenance records** (V3-AT-33) and **output inspection** (master §12.2), consumed by D and F.
7. **SFX route qualification** and the **YuE2 music-library job** (master §7, §4.7; the libraries are
   derived assets accepted in the CAST review).

**Not in C:** shots and the shot compiler, the reference-budget selection (≤9/≤3) — D; the EDL, music
placement/ducking, SFX placement — E; thumbnails (they reuse C's image adapter + inspection); the live
LLM adapters; the live-ARISA lock proof.

## 1. Binding decisions

1. **V1/V2 never change** (B §1.1's rule). V3 cast code lives in new modules `S/cast_v3/`. The frozen V2
   wardrobe shapes are **reused as embedded V3 models** (B §2 "reused shapes" pattern), stored in C's own
   document table, never in `v2_contract_documents`.
2. **A pick is a vote only** (master §4.4.1). Votes start no work. **Generate next** and **Re-roll** are
   operator actions that enqueue jobs (N23). Pick/vote states are **UI projections** of the job lifecycle
   (master §10.0 state mapping), derived, never stored as side state (AR-4).
3. **One neutral voice reference per speaker** (DECISIONS "D2 revised again", 12 Nov). Per-emotion voice
   variants are **not built**. The prompt carries emotion (B §2.2 owns the vocabulary); C supplies only
   the neutral clip and its binding.
4. **Botnoi catalogue, two sources** (DECISIONS "D2 update"): API import (`get_speaker_data`,
   `get_speaker_data_v2`, no token) + operator CSV additions. Community voices are excluded from
   shortlists by default and need per-voice operator approval in their rights record. `has_v4` is an
   operator confirmation; `last_verified` >90 days is flagged (N13).
5. **Botnoi rights basis is `OPERATOR_ATTESTED`** (O-11), stored verbatim from DECISIONS in every Botnoi
   voice rights record.
6. **Nano Banana (Q8):** model `gemini-nano-banana-2.1` on the shared Vertex project. Fake by default;
   live behind a per-provider switch + qualification + rights + a non-unknown price. **One Nano Banana
   process across ARISA and Drama Box**, interoperating with ARISA's existing flock (FM §8): same inode,
   crash-safe, bounded Drama batches (master §10.2).
7. **All paid work goes through phase A's accounts:** `SEASON_SETUP` account, `step_key = 'step_04'`
   (A2 0033 CHECK vocabulary), admission order unit → step → child → `SEASON`. Unknown price = refused
   (FM §3 config rule). The setup sub-budget value is **proposed by C, operator-approved** (O-6).
8. **CAST LOCK is a V3 gate through the A1 decision transaction.** The mechanical freeze reuses
   `identity_locks` + `identity_lock_assets` and their readers; the SQL relaxes `source_episode_id` /
   `release_package_hash` to nullable **for V3 rows only**. The episode-1 Gate 2 lock path never fires for
   V3 seasons (master §4.4.5).
9. **R-12.1 fix:** CAST LOCK stamps **every** episode row, and V3 episode creation **auto-adopts** the
   season's current lock (FM §1: `create_episode` sets none; `attach_identity_lock`
   `S/references/service.py:284` has no production caller — verified).
10. **Canonical setting ID = the location demand ID** everywhere in V3 (N30). `StoryTime.setting` free
    text is never a key; the V2 compiler comparison stays V2.
11. **C makes no LLM calls.** Shortlist ranking, casting-sheet scripts, wardrobe derivation, forecasts
    and output inspection are deterministic. Nothing in master §4.4 requires an LLM in step 4.
12. **No second job system** (master §10.0): generation units are jobs + `ProviderOperation`
    (`S/contracts/cost.py:711`) through the existing `GenerationProvider` protocol
    (`S/contracts/providers.py:188`, verified). C adds the lanes `image`, `voice_intake`, `sfx`, `music`
    through phase A's four-point checklist (queue CHECKs, `budget/policy.py` ownership, worker set,
    generated contracts).

## 2. Records (contract package, guardian-owned bump; symbolic migrations `C-1…`)

All V3 cast documents are append-only, versioned, hash-sealed, stored in a new **`v3_cast_documents`**
table through `CastV3Store`, mirroring B's `StoryV3Store` (B §2): PK `(contract_type, record_id,
version)`, one `current` row, hash re-verified on read, standard guards, a `contract_type` allowlist
CHECK. `record_id = uuid5(CAST_V3_NS, "<type>:<season_id>[:<key>]")`. `v2_contract_documents` and
`v3_story_documents` are not touched.

| Migration | Object | Decisive columns / rules |
|---|---|---|
| `C-1` | **`cast_pick_items`** | `season_id`, `demand_id`, `pick_kind` (below), `item_key`, `target_ref_kind`/`target_ref_key` (nullable; maps to `reference_versions`), `required bool`, `parent_pick_id` nullable, `parent_version_at_generation` int nullable (staleness check, §4); `UNIQUE (season_id, demand_id, pick_kind, item_key)`; guarded |
| `C-2` | **`cast_pick_votes`** (append-only) | `pick_id`, `candidate_kind` (`REFERENCE_VERSION` \| `CATALOG_ENTRY` \| `ASSET`), `candidate_id`, `note`, human-session ref, `created_at`; a vote records only |
| `C-3` | **`cast_dependency_edges`** (append-only) | `season_id`, `parent_pick_id`, `child_pick_id`, `edge_kind` (`BUILT_ON_FACE`, `COVERAGE_OF`); derived deterministically at item creation; registered with A's `DependencyProvider` (A4) |
| `C-4` | **`botnoi_voice_catalog`** (global, not season-scoped) | `source` (`api_v1` \| `api_v2` \| `operator_csv`), `voice_name`, `speaker_id` nullable, `gender`, `age_group`, `accent`, `style_notes`, `has_v4` (NULL = unconfirmed), `voice_kind` (`cast` \| `api` \| `community`), `last_verified`, `raw jsonb`; `UNIQUE (source, voice_name, speaker_id)`; guarded |
| `C-5` | **`provenance_records`** (append-only) | `subject_kind` (`ASSET` \| `METHOD` \| `DETECTOR_WEIGHTS` \| `FONT` \| `VOICE` \| `SFX_ROUTE` \| `MUSIC_JOB`), `subject_ref`, `basis`, `basis_version`, `entitlement` (generation-time, separate from plan upgrades), `model_provider`, `prompt_hash`, `seed`, `license_hash`, `evidence jsonb`; `UNIQUE (subject_kind, subject_ref, basis_version)` |
| `C-6` | **`voice_uploads`** (guarded) | `season_id`, `character_demand_id`, `slot` (`neutral`), `state` (`QUARANTINED` \| `REJECTED` \| `NORMALISED` \| `REGISTERED` \| `SUPERSEDED`), `idempotency_key` UNIQUE, `expected_revision`, `source_sha256`, `normalised_sha256`, `rejection_reason`, `checks jsonb`, `attestations jsonb`, `asset_id` nullable |
| `C-7` | **`identity_locks` relaxation** | `ALTER COLUMN source_episode_id DROP NOT NULL`, same for `release_package_hash` (0002:258, 261 — verified); a version-aware constraint trigger keeps both **required when `schema_version = '1.0'`** (V1 rows unchanged); V3 rows require a `cast_lock` document ref in `body` instead; `md_forbid_mutation` stays |
| `C-8` | queue lanes + rights/provenance CHECK plumbing | `jobs.queue` CHECK gains `image`, `voice_intake`, `sfx`, `music` (0001:77 today: `production/publication/community` — verified); matching reservations/charges and `budget/policy.py` ownership |

**`pick_kind` vocabulary:** `FACE`, `SHEET_VIEW`, `EXPRESSION`, `OUTFIT`, `APPEARANCE_STATE`, `PROP`,
`LOCATION_MASTER`, `LOCATION_COVERAGE`, `EXTRAS_LOOK`, `VOICE_NEUTRAL`, `MUSIC_LIB`, `SFX_LIB`.

**Documents in `v3_cast_documents`:**

| Record | Key | Content |
|---|---|---|
| `CastForecastV3` | `forecast` (versions = recomputes) | the image-volume projection and cost forecast (§3), the inputs hash, the proposed setup sub-budget (O-6) |
| `CastWardrobePlanV3` | `wardrobe` | §6: outfit definitions (story-day ranges, setting tags = location demand IDs), per-scene assignments for **every** visible character in **every** episode, timed change events, prop sheets, appearance-state map, reuse reasons |
| `VoiceCastingV3` | `voice:<character_key>` | the shortlist (2–3 entries + reasons), the audition pick (catalog ref, or "other" + reason), the casting sheet (script, source lines, suggested tags), the upload reference (`voice_uploads.id`) |
| `CastLockV3` | `cast-lock:<content_revision>` | §8: the STORY binding hash, the full membership (every pick: demand, item, picked version + `content_sha256`; derived assets; voice WAV hashes), the provenance basis set, the approval event, `cast_lock_hash` |

**`ProvenanceRecord` (V3-AT-33)** is the `C-5` table + a typed contract `ProvenanceRecordV3` — it does not
exist today (FM §2: only the per-asset `Provenance` enum, `S/contracts/enums.py:28`). Covers everything
master §12.1 lists; **every asset registered by V3 code gets one in the same transaction** (§9).

## 3. Demand list → work: items, projection, forecast (R-3.4 consumer, R-4.11, R-12.7)

**Derivation** `derive_pick_items(season, demand_list)` — deterministic, rerun idempotently (items keyed
by demand + kind + key, so a B Revise that keeps an item keeps its picks):

| Demand (B §4.3) | Pick items |
|---|---|
| `CHARACTER` PRINCIPAL | `FACE`; `SHEET_VIEW` × (front-headless, rear, tight face, profiles if the bible asks); `EXPRESSION` × (neutral, signature, extreme) |
| `CHARACTER` SUPPORTING | `FACE`; `SHEET_VIEW` × (front, tight face); `EXPRESSION` × 2 |
| `OUTFIT` | `OUTFIT` (edge `BUILT_ON_FACE` to that character's `FACE`) |
| `APPEARANCE_STATE` | `APPEARANCE_STATE` (edge `BUILT_ON_FACE`) |
| `PROP` (+ state) | `PROP` per `state_key` |
| `LOCATION` + light state | `LOCATION_MASTER` per light state; after the master pick, `LOCATION_COVERAGE` × (reverse, tighter) (edge `COVERAGE_OF`) |
| `EXTRAS_ROLE` | `EXTRAS_LOOK` (2–4 candidate looks → pick one; O-C6) |
| `VOICE` | `VOICE_NEUTRAL` (§7) |
| — (season libraries, N16) | `MUSIC_LIB`, `SFX_LIB`, accepted in the CAST review (§10) |

Edges are written in the same transaction; `FACE` → sheets/expressions/outfits/states,
`LOCATION_MASTER` → coverage. Items are `required = true` except profiles and coverage variants the plan
marks optional.

**Image-volume projection** (master §10.4): projected count = Σ per item (candidates 2–3 + derived
views) × (1 + re-roll rate). Re-roll rate and lock throughput (images/hour) are **config with measured
defaults pending P0** (`UNVERIFIED` until then; the panel labels them "estimated"). Wall-clock estimate =
count ÷ throughput, shown with the fairness batch parameters (§5).

**Cost forecast** (master §12.3, before CAST LOCK): volume × unit price + voice/music/SFX lines +
already-committed setup spend; the **average-episode capacity line** (`(season cap − setup) ÷ episodes`)
is shown; a forecast above cap is a **CAST LOCK gate condition blocker** with "raise the cap or cut
scope". The **setup sub-budget proposal** (O-6) is computed here and approved via A2's
`approve_setup_budget` — no paid setup work before it (AC-13).

**Panels from B §4.3 that C fills:** the step-4 cost forecast panel and the image-volume projection
panel on the STORY LOCK screen (`NOT_AVAILABLE` until the C2 package ships).

## 4. The picks engine (V3C-8; V3-AT-5, V3-AT-22; R-4.8)

- **Candidates** are `reference_versions` rows (FM §1: multiple versions per
  `(season, ref_kind, ref_key)` are the de-facto candidate grid today; nothing records a choice). The
  item's candidate set = versions in `PROVISIONAL`/`ACCEPTED` for its `(target_ref_kind, target_ref_key)`.
- **`vote(pick, candidate, note)`** — human session + CSRF + idempotency key. Appends one
  `cast_pick_votes` row; **starts no work**. The current selection = the latest vote. Votes on superseded
  candidates stay as history.
- **`reroll(pick, note)`** — operator action; enqueues exactly **one** item's generation job (new
  versions append; the selection is untouched until a new vote). Counted in the forecast's re-roll
  metric and metered normally.
- **`generate_next(parent_pick)`** — operator action (N23); enqueues the parent's dependents' jobs
  **against the selected parent revision** (the request's `reference_asset_ids` carries it;
  `parent_version_at_generation` is stamped on the child item).
- **Staleness / invalidation (V3-AT-22):** a dependent is *stale* when
  `parent_version_at_generation ≠ ` the parent's currently selected version — computed from stored
  columns, never a stored flag. A stale dependent's candidates are visually marked; **its item must be
  re-picked (re-roll + vote) before lock**; unrelated picks are untouched. A4's coordinator uses the same
  edges for post-lock amendments (§12.6).
- **State projection** per master §10.0: queued/leased → `QUEUED`/`GENERATING`; succeeded → `READY`;
  after a vote → `VOTED`; derived jobs done → `DERIVED_READY`; at CAST review → `ACCEPTED`; retry →
  `FAILED_RETRYABLE` (+`WAITING_PROVIDER`/`WAITING_QUOTA` by cause); unknown → `UNKNOWN`/`BLOCKED
  (reconcile)`; terminal → `FAILED`/`BLOCKED`. Progress bars per category (R-4.11): generated n/N,
  picked n/N.
- **Lock refusal (V3-AT-5):** Approve is refused with the typed list of unpicked required items and
  stale descendants (§8).

## 5. Image generation: adapter, cross-system lock, metering (Q8, V3C-19; V3-AT-15/28)

- **Adapter seam:** `NanoBananaProvider` implements `GenerationProvider`
  (`submit(op, ImageRequest | VoiceRequest) / status / reconcile / fetch_output`,
  `S/contracts/providers.py:188–205` — verified). Prompt building is **castkit/scenecraft structured
  builders** (V3-only, `S/cast_v3/promptkit.py`): the face-lock prompt is the 18% neutral gray field,
  directionless light, no baked lighting, forehead-to-upper-chest framing (master §4.4.2). Output
  inspection (§9) runs inside the job after `fetch_output`.
- **Fake by default:** the composition wires `image_provider = 'fake-generation'` (the existing fake,
  FM §3). **Live switch:** per-provider config `nano_banana.enabled` + an A6c `provider_qualifications`
  row + a rights route `route-nano-banana` (evidence required; fail-closed `check_rights`, FM §7) + a
  non-None `image_price` quote. Any missing piece keeps the provider disabled — never zero-priced.
- **Cross-system single-process lock (V3-AT-15, V3-AT-28):** `cross_process_generation_lock(path)`
  opens the configured lock file **read-only** and takes `fcntl.flock(LOCK_EX | LOCK_NB)` — exactly
  ARISA's pattern (`arisa/studio/sfw/recovery.py:91–105`, file verified present). Busy → a typed busy
  error → the job defers `WAITING_PROVIDER` with `retry_after` (bounded backoff; **waiting is visible and
  holds no GPU** — image jobs hold no GPU lease at all). The lock is held around each provider POST, as
  ARISA holds it. **Crash-safe:** the kernel releases flock on process death; a restart cannot inherit a
  hold. **Fairness:** bounded Drama batches — at most `fairness_batch_images` (default 8) or
  `fairness_batch_seconds` (default 120 s) per hold, then release and re-acquire, so ARISA turns
  interleave; `retry_after` defaults to 20 s mirroring ARISA's. Defaults are config (O-C8); P0 measures
  real throughput.
- **The shared inode:** the canonical lock file is **ARISA's**
  `/root/AIVORA/arisa/studio/sfw/vertex-generation.lock`, reached through Drama's own bind mount of the
  same path (same inode — the property ARISA's docstring relies on). Drama never creates a second lock
  file. **ARISA-side adoption is coordinated with the ARISA owner and is a prerequisite for live image
  jobs** (master §10.2); C's offline acceptance simulates the competitor (C-T5/C-T6).
- **Metering:** every dispatch is a `ProviderOperation` with a reservation (`step_key = 'step_04'`,
  `SEASON_SETUP` account); `UsageReceipt` measured only; admission per §1.7. Re-rolls are counted in the
  forecast. The season music/SFX libraries also run under `step_04` (N16).

## 6. Wardrobe, appearance, props, locations (V3C-10; V3-AT-7, V3-AT-23; R-4.2–R-4.5, R-12.2)

- **`CastWardrobePlanV3`** is built deterministically from the locked packs + demand list, then
  operator-editable (human session, expected revision, idempotency):
  - **Outfit definitions:** per character, valid for story-day ranges (from the OUTFIT demands' story
    days) and setting tags = **location demand IDs** (§1.10).
  - **Assignments:** every visible character in every scene gets the pack's outfit + appearance states
    (B §2.1 `scenes[].wardrobe` already guarantees coverage; the plan is the season-wide projection).
  - **Reuse rule (V3-AT-7):** a new story day gets a different outfit unless a `reuse_reason` is
    recorded; the validator refuses an unreasoned repeat.
  - **Timed changes:** scene-relative `StateEvent` intervals (non-empty; the frozen V2 validator rule),
    effective across episode boundaries. A mid-scene change is an **operator-planned refinement** on the
    wardrobe screen: it must cite a beat or scene break that allows it (the same evidence B's
    "impossible wardrobe day" critic accepts). B's pack schema expresses per-scene wardrobe only —
    recorded as O-C2, not silently resolved.
  - **Appearance states:** dedicated `AppearanceStateV3` entries (kind, story days/scenes held, asset =
    the picked `APPEARANCE_STATE` item) — today only a generic `StateEvent` exists (FM §5,
    REQUIREMENTS R-4.3).
  - **Props:** `PropSheet`-shaped entries (states, owner) + holder/state per scene from the packs;
    proof-prop flags flow from the demand list.
- **Resolver wiring (the R-4.2 gap):** `outfit_for_scene_time_v3(episode, scene, character, at_ms)`
  resolves the exact outfit + appearance states at any instant, including immediately before/at/after
  episode boundaries (V3-AT-23), and `shot_reference_expectations_v3` feeds it into the reference
  expectation builder (the V2 seam `resolve_shot_reference_expectations` exists, FM §5, but V2 routing
  passes no `state_events` — V3 code is new and wired; V2 routing is untouched, D replaces it). A shot
  crossing an incompatible boundary is **split by D**; C supplies the boundary data.
- **Locations (scenecraft):** `LOCATION_MASTER` pick per light state, then coverage plates generated
  from the picked master (same geometry, time, weather — enforced by prompt lineage: master asset as
  `reference_asset_ids`, fixed seed family, and a provenance link), accepted in the CAST review.
- **`LineAudio`-style orphan note:** FM §6 records that line-level TTS audio is unused by rendering; V3
  has no line TTS at all (native Pika audio), so C adds none.

## 7. Voices (R-4.6 as superseded by D2 chain; V3R-1, V3R-2, V3R-11)

**Catalogue (C-4).** Importer job `cast_v3.botnoi_refresh` (queue `production`; public no-token
endpoints; offline tests use fixture responses):
- maps `get_speaker_data` / `_v2` rows (fields verified in
  `botnoi-api-speakers-2026-11-11.csv`: `speaker_id, eng_name, thai_name, language, gender, age_style,
  voice_style, speech_style, speed, price, sample_audio`) into catalogue rows, `source = api_v1|api_v2`,
  stamps `last_verified`; **archetype labels are not inferred** (DECISIONS 12 Nov correction: monks
  582/583 are unlabelled in API fields) — archetypes come only from operator additions;
- never deletes or overwrites `operator_csv` rows; entries with `last_verified` >90 days are flagged
  (N13);
- operator additions import from `botnoi-v4-voices.csv` (header-only today, verified — the seed
  template) with exactly the DECISIONS field list; the Studio archetypes (7 monk, 2 grandpa, 2 grandma,
  Ananda, Bow) are entered when a season casts them.

**Shortlist (V3R-11).** Deterministic ranking of the catalogue against the `CharacterProfile` voice
descriptor (B §2): gender must match exactly; then age band, accent (a regional accent is a casting
asset) and style tokens score. Output: **2–3 suggestions with reasons, no audio generated**, stored in
`VoiceCastingV3`. Community voices are excluded unless their per-voice approval exists (a
`rights_registry` VOICE row with the operator's explicit approval as evidence); `has_v4 IS NULL` entries
may appear but are flagged "confirm V4 in Studio".

**Audition.** The operator auditions in Botnoi externally and records the pick (catalog ref) or "other"
with a reason. The audition pick is the `VOICE_NEUTRAL` item's vote (candidate_kind `CATALOG_ENTRY`) —
it selects no asset yet.

**Casting sheet.** One **neutral** 10–15 s Thai script per speaker, assembled deterministically from the
character's own pack lines (longest TH lines fitting the window; a template fallback is marked if the
character has too few lines). Suggested V4 inline tags are listed **as options only** — the pilot leak
observation (master §4.4.4 8) applies: if tag vocalisations leak into Pika output, scripts go tag-free.

**Upload intake (V3R-1).** One slot per character (`neutral`), single upload or **zip bulk import** with
files named exactly `<character_id>__neutral.wav|.mp3`. Every request requires owner scope, CSRF, the
expected revision and an idempotency key. **Numeric limits C sets:** request ≤ 50 MB; zip entries ≤ 64;
expanded total ≤ 500 MB; decoded length 3–60 s per clip; processing ≤ 120 s per import; per-import entry
cap enforced before extraction. **Rejected:** path traversal, absolute paths, symlinks/hardlinks,
duplicate slots, unknown keys, undecodable audio. Files land in a **private quarantine**
(`voice_uploads` state `QUARANTINED`); storage paths are server-generated; decoding runs isolated (a
subprocess with a timeout against a scratch dir, never from the upload path); **failed imports never
overwrite accepted assets** (registration only ever appends versions). Hostile-input tests are
acceptance C-T10.

**Normalisation and assessment (V3R-2).** A versioned profile `voice-normalisation-v1`: PCM WAV,
24 kHz, mono, 16-bit (matches the T031 references, 24 kHz mono — DECISIONS 12 Nov) and **must pass the
binder's byte validator**; **only the resulting PCM WAV is registered** as the asset; `source_sha256`
and `normalised_sha256` are both kept. Recorded technical checks (duration, rate, channels, clipping,
leading/trailing silence) + assessment of Thai speech, transcript match, single-speaker suitability and
consistency with the base voice — automated where a qualified detector exists, otherwise a **recorded
human check**; **V4 origin and voice identity are operator attestations, labelled separately** from
machine checks. The accepted clip becomes the `VOICE` reference version + a `voices` row
(`provider = 'botnoi'`, `provider_voice_ref` = speaker id, `anchor_asset_id` = the WAV) — the table
exists today (0002:134–152, verified).

**Rights (O-11).** A `rights_registry` route `route-botnoi-voice` (subject `VOICE`) with basis stored
verbatim: `OPERATOR_ATTESTED (Botnoi sales-page use cases: ads/product videos, stories, audiobooks; no
licence document found; 11 Nov 2026)` + a `provenance_records` row per voice. A missing, corrupt or
unapproved neutral reference **blocks dispatch** (the binding exposes a typed blocker D enforces).
Changing the base voice invalidates the clip (the item goes stale); after lock, §12.6.

## 8. CAST LOCK (V3C-6; V3-AT-5/6; R-4.9, R-12.1, R-12.5)

**The gate.** The C handler registers `CAST_LOCK` (A1 §2.7: `NOT_AVAILABLE` before C ships). The
activation opens when every required item's generation work is terminal-successful, with binding =
canonical hash of (demand-list version, all pick items + current selections). **Approve conditions**
(evaluated in the A1 decision transaction): the binding is current; **every required item is picked**
(refused with the typed list otherwise — V3-AT-5); **no stale descendant** (V3-AT-22); the wardrobe plan
validators pass; the forecast is present and fits (a forecast above cap is a blocker); the setup budget
is approved. **Stale hash refused; Revise regenerates only the noted units** — notes target typed
`{kind: pick, id}`, and only those items re-roll (a scoped enqueue), then the gate reopens with a new
binding. **Reject** leaves planning at `CASTING` without cast authority (A §2.2).

**The lock transaction** (one transaction, A §6 lock order), on Approve:
1. write the `CastLockV3` document; `cast_lock_hash` = canonical hash over the STORY binding hash +
   every pick's (demand, item, picked version id + `content_sha256`) + derived assets + voice WAV hashes
   (V3-AT-5: the hash covers **every picked version**);
2. insert the `identity_locks` row (version = next; `source_episode_id`/`release_package_hash` NULL;
   `approval_event_id` = this decision; `body` references the `CastLockV3` record);
3. write `identity_lock_assets` members (pick kinds map to the five `asset_kind`s; the table and readers
   stay, FM §1);
4. freeze: members → `LOCKED`, voices/characters → `LOCKED` (the existing state machines);
5. stamp **every** episode row `identity_lock_id` (all N exist from STORY LOCK);
6. `advance_planning(CASTING → CAST_LOCKED)`; emit `gate.waiting`-family events per A §8.

**R-12.1 (V3-AT-6):** the V3 episode-creation path (A2's `create_v3_episodes` and the extension
builder's creation) **auto-adopts** the season's current lock at insert time — `attach_identity_lock`
(`S/references/service.py:284`, verified no production caller today) becomes the production helper. A
regression test creates an episode (extension) after lock and proves attachment; the render gate's
`IdentityLockRequired` hint (FM §1) is then unreachable for V3.

**`CastBinding` (master §13):** the per-demand binding D consumes is **read from the lock** —
`cast_binding(tx, episode)` resolves, for every demand that episode's packs use, the locked
reference version/asset + provenance ref, and the voice neutral reference per speaker with its
approval state (a missing/corrupt/unapproved one is a typed blocker). No second binding table: the
`CastLockV3` membership is the binding of record.

**Legacy paths:** the episode-1 Gate 2 `IdentityLockHook` refuses V3 seasons (`require_workflow` guard);
V1 lock creation is unchanged (master §4.4.5 "removing episode-1 lock creation from the V3 Gate 2 path").

**Season-2 reuse (R-12.5):** `import_cast(source_season → new_season)` copies locked faces, outfits,
props, locations, coverage and voices as new-season `reference_versions` with `asset_lineage`
(`derived_from`, 0004:41–49) and carried `provenance_records` (basis noted as reuse); **rights are
revalidated at import** (expired/unknown blocks the item); voices re-attest per season.

## 9. Provenance and output inspection (V3C-33, MA7; V3-AT-33; R-12.4, R-12.9)

- **Write path:** every asset registered by V3 code gets a `provenance_records` row **in the same
  transaction** as registration (the seam is the V3 sibling of `ReferencesService._register`, FM §2).
  Basis values include `OPERATOR_ATTESTED` (Botnoi, the benchmark attestation), `LICENSED` (fonts,
  detector weights, SFX route), `INTERNAL_METHOD_CREDITED` (Joey's skills: internal only, credited, not
  redistributed, full text never embedded), `SUBSCRIPTION_TERMS`, `REUSE_WITH_LINEAGE`. Imported methods
  (weights, fonts, routes) get rows once, versioned.
- **Completeness (V3-AT-33):** CAST LOCK Approve additionally checks **every member asset has a complete
  `ProvenanceRecord`** (all §2 `C-5` fields present for its subject kind); a gap blocks the lock with the
  typed list.
- **Output inspection (master §12.2):** an `OutputInspectionProvider` seam runs on **every generated
  image** inside the generation job (and is reusable by D/F for thumbnails and clip-sampled frames):
  on-frame text (OCR), branding (a maintained mark list), likeness (face-embedding similarity against
  the locked faces — the detector slot is qualified per O-2; until then a **recorded human check** at the
  picks review, never an auto-PASS). Findings are recorded on the candidate, surfaced on the pick grid
  and the CAST review; unresolved findings follow QA/repair and Gate 2. R-12.9's "no on-frame text in
  generated frames" is enforced here (text is added in edit).
- **SFX route qualification (§7 master, O-9):** compare fal.ai `fal-ai/elevenlabs/sound-effects/v2`
  ($0.002/s, commercial label — **re-verified at qualification**; `UNVERIFIED` here) vs OpenRouter
  (unverified → ineligible). The chosen route, terms and billing units are persisted
  (`provenance_records` `SFX_ROUTE` + a rights route); equivalent requests compared at all-in bounded
  prices; the maximum authorised charge reserved per request; unknown capability/terms/price ⇒
  ineligible, never zero-priced; if none qualifies, the SFX library job blocks.
- **YuE2 music library (V3C-20, N16):** a `GenerationProvider` adapter for the Drama-owned YuE2 job
  (pinned instrumental recipe, duration/loop targets, vocal-leakage inspection, rights, canonical
  holds/recovery/finality); the season library is generated in step 4's job graph under `step_04`, with
  A40 qualification recorded. Live behind its own per-provider switch; fake by default.

## 10. Jobs, fence and waits

| Job | Queue | Provider ops | Logical work ID |
|---|---|---|---|
| `cast_v3.generate` (one item, one attempt) | `image` | 1 image op per candidate | `cast-gen:<season>:<pick>:<attempt>` |
| `cast_v3.botnoi_refresh` | `production` | none (public endpoints, fixture-tested) | `botnoi-refresh:<date>` |
| `cast_v3.voice_intake` (quarantine → decode → normalise → assess) | `voice_intake` | none (local) | `voice-intake:<season>:<upload>` |
| `cast_v3.music_lib` / `cast_v3.sfx_lib` | `music` / `sfx` | YuE2 / SFX ops | `music-lib:<season>:<recipe>` |

- **Fence:** every job input carries `expected_content_revision`; stale results are quarantined (A3 §7.1).
- **Waits:** lock busy → `WAITING_PROVIDER` (`retry_after`); budget → `WAITING_BUDGET`; reconcile →
  `BLOCKED (reconcile)` — all projected through `track_waits` (A §3).
- **Crash/restart:** a restart resumes unfinished units and never regenerates successes (master §10.5);
  `reconcile` NOT_FOUND = safe to resubmit.
- **Offline:** every C test uses the fake generation provider, fixture Botnoi responses and synthetic
  flocks; no test calls the network, Vertex or Telegram. `make check` + V1 `make pilot` stay green.

## 11. UI (tab 4, built into the phase A shell, A5)

| Screen | Route | Primary action |
|---|---|---|
| Cast overview + forecast | `/v3/seasons/{id}/cast` | **Approve setup budget** (before any paid work), then the category progress bars (R-4.11) |
| Picks grid per category | `/v3/seasons/{id}/cast/{category}` | **Pick** (vote), **Re-roll** (note), **Generate next** |
| Wardrobe plan | `/v3/seasons/{id}/cast/wardrobe` | timed-change editor, reuse reasons |
| Voices | `/v3/seasons/{id}/cast/voices` | shortlist → audition record → casting sheet → upload (single + zip) |
| CAST review | `/v3/seasons/{id}/cast/review` | derived assets + inspection findings; the CAST LOCK gate buttons |

States per master §3.2 (empty/loading/running/waiting for you/waiting quota/blocked/error/done); the
pick screens emit `picks.waiting` (A §8.4). The forecast panel and image-volume projection appear on B's
STORY LOCK screen once C2 ships (filling its `NOT_AVAILABLE` panels).

## 12. Build packages (in order; `make check` + V1 `make pilot` green at every gate)

Prerequisites: A0–A6 accepted; B accepted. Real migration numbers allocated in the C1 note after
re-auditing the tail. **Applied migration bytes are never edited.**

| Package | Builds | Gate | Design note |
|---|---|---|---|
| **C1** | Records + migrations `C-1..C-8`; contracts bump; `CastV3Store`; V1/V2 artifact byte-identity | C-T1 | **Critiqued first** (migrations) |
| **C2** | `derive_pick_items` + edges; image-volume projection; cost forecast + setup proposal; fills B's panels | C-T2, C-T14 | With the diff |
| **C3** | Generation runtime: lanes, `cast_v3.generate`, fake-first wiring, Nano Banana adapter + live switch, **cross-system lock + fairness**, metering + provenance write path | C-T5, C-T6, C-T14 | **Critiqued first** (money, locks) |
| **C4** | Picks engine: votes, re-roll, generate-next, staleness, state projections | C-T3, C-T4 | With the diff |
| **C5** | Wardrobe plan + timed changes + appearance/props/locations + resolver wiring | C-T7, C-T8 | With the diff |
| **C6** | Botnoi catalogue + importer + shortlist + audition + casting sheet | C-T9 | With the diff |
| **C7** | Voice intake: upload, quarantine, normalisation, assessment, rights | C-T10, C-T11 | Pre-critique **recommended** (trust boundary) |
| **C8** | SFX qualification + YuE2 library job | C-T14 | **Critiqued first** (money) |
| **C9** | CAST LOCK gate + `CastLockV3` + identity-lock reuse + **R-12.1** + provenance completeness + season-2 import | C-T12 (provenance half), C-T13 | **Critiqued first** (lock transaction, migration) |
| **C10** | Output inspection seam + deterministic checks | C-T12 (inspection half) | With the diff |
| **C11** | Tab 4 UI (all screens, states, events) | C-T15 | With the diff |

**Routing:** GLM builds each package (`ai-route build -w`); Codex critiques the C1/C3/C8/C9 notes and
reviews every diff; one package at a time.

## 13. Acceptance (offline; real PostgreSQL for every transaction test)

| Test | Proves |
|---|---|
| C-T1 | `C-1..C-8` apply on a populated V1+V2 database; V1 `identity_locks` rows still require `source_episode_id` + `release_package_hash` (the version-aware trigger); no row deleted or rewritten; generated contracts show no drift |
| C-T2 | Demand→item completeness both ways against a B demand list; tier-correct packages; edges correct (FACE→sheets/expressions/outfits/states, master→coverage) |
| **C-T3 (V3-AT-5)** | **Votes start no work; Re-roll requeues one item only; Lock is refused until every required item is picked (typed list); the lock hash covers every picked version** (any picked-version change alters the hash) |
| **C-T4 (V3-AT-22)** | **A face re-roll/stale selection invalidates its dependent outfits/views; unrelated selections survive; CAST LOCK cannot freeze stale descendants** |
| **C-T5 (V3-AT-15)** | **A second concurrent image job waits:** a simulated competitor holds the flock → the job defers `WAITING_PROVIDER` with `retry_after`; never two Nano Banana dispatches |
| **C-T6 (V3-AT-28)** | Competing processes (two workers, separate connections) share the same lock inode; a killed holder releases; crash/restart cannot overlap provider processes |
| **C-T7 (V3-AT-7)** | A timed mid-scene outfit change appears in the resolved shot-reference expectations; a new story day gets a different outfit unless a reuse reason is recorded |
| **C-T8 (V3-AT-23)** | Wardrobe continuity spans episode boundaries; canonical setting IDs agree across plan/assignment/resolver; timed changes resolve immediately before/at/after boundaries |
| **C-T9** | Catalogue: two sources merge without deleting operator rows; >90-day and unconfirmed-V4 flags; community voices excluded without per-voice approval, included with it; shortlist = 2–3 with reasons, **no audio generated** |
| C-T10 (V3R-1) | Hostile uploads: traversal, absolute paths, links, duplicate slots, unknown keys, oversized requests/zips, long decodes — all rejected pre-extraction/post-decode as specified; **failed imports never overwrite accepted assets** |
| C-T11 (V3R-2) | Only the normalised PCM WAV registers and passes the binder validator; both hashes kept; attestations labelled separately from machine checks; a base-voice change invalidates the clip |
| **C-T12 (V3-AT-33)** | **Every member asset has a complete `ProvenanceRecord` (a gap blocks lock); output inspection catches injected on-frame text, branding and likeness findings** (fixtures) |
| **C-T13 (V3-AT-6)** | **CAST LOCK attaches the identity lock to every episode, including ones created later** (extension episode after lock; R-12.1 regression) |
| C-T14 | Budget: admission through `step_04`/`SEASON_SETUP` in A §5.2 order; no paid work before the setup approval; forecast + capacity line before lock; unknown price refused; re-rolls counted; **unknown SFX/YuE2 terms, capability or price ⇒ ineligible and blocked** (never zero-priced), chosen route persisted |
| C-T15 | Tab 4 screens: every state in §11; one primary action per screen; `picks.waiting` emitted once per activation |

## 14. Open questions (each with a recommendation)

| # | Question | Recommendation |
|---|---|---|
| O-C1 | **API V2 vs Studio V4 neutral clip** (DECISIONS: "decide before phase C"). T031's evidence clips are V4; the public API serves only V1/V2. | Keep the **manual Studio upload** as the only P0 intake (T031's S05/S06 run from V4 neutrals; MA12 measures exactly this); run the Thai-listener V2-vs-V4 comparison; if V2 qualifies, an API-generation path can later feed the **same** normalisation/assessment intake unchanged |
| O-C2 | B's pack expresses per-scene wardrobe only; master §4.4.3 requires mid-scene timed changes | C's operator-planned timed events (citing an allowing beat/scene break, per B's critic evidence rule) cover it; **flag to the orchestrator** whether B §2.1 should grow a `wardrobe_change` beat annotation in a B revision — recorded, not resolved here |
| O-C3 | Setup sub-budget value (O-6) | Propose from the forecast arithmetic (image volume × price + libraries); default **US$30** (A2's default) until the first real forecast; operator approves on the cast overview screen |
| O-C4 | Nano Banana per-image price on the shared Vertex project: `UNVERIFIED` | Live dispatch stays refused (fail-closed) until the operator supplies the measured price from the project's billing; the fake path is unaffected |
| O-C5 | Lock-file ownership/placement for cross-system interop | Keep **ARISA's inode** as the one canonical lock; Drama binds the same path read-only; ARISA-side adoption is coordinated with the ARISA owner (prerequisite for live jobs, outside C's offline acceptance) |
| O-C6 | Extras: pick one of 2–4 looks, or keep a look pool? | Generate 2–4, **pick one** look per role as its reference; others are discarded at lock (matches "extras looks" as a required human pick) |
| O-C7 | Fairness numbers (batch size / hold time / retry) | Defaults 8 images or 120 s per hold, `retry_after` 20 s (mirrors ARISA); config-owned, re-measured by P0 (master §10.4) |
| O-C8 | Should the C7 trust-boundary note be Codex-critiqued before code (it is not money/locks/migrations)? | **Yes, recommended** — the intake is the phase's only untrusted-bytes surface; the operator confirms |

## 15. Requirement trace

| R-ID | Where |
|---|---|
| R-4.1 | §3 (packages by tier), §5 (castkit face lock), §9 (expression set inspection) |
| R-4.2 | §6 (plan, timed changes, resolver wiring — the R-4.2 gap closed for V3) |
| R-4.3 | §6 `AppearanceStateV3` |
| R-4.4 | §6 props; §3 pick items |
| R-4.5 | §6 locations + coverage |
| R-4.6 | §7 (as superseded by D2 refined/revised-again: Botnoi manual neutral, not ElevenLabs Voice Design) |
| R-4.7 | §3 `EXTRAS_LOOK` (recurring roles already promoted by B §4.2) |
| R-4.8 | §4, §11 (votes, re-roll, lock; SFW-picks behaviour) |
| R-4.9 | §8 |
| R-4.10 | §5 (Q8: Nano Banana Pro; shared quota + one process) |
| R-4.11 | §4, §11 |
| R-12.1 | §8 (R-12.1 fix; C-T13) |
| R-12.2 | §6 (records + pre-render validation; QA-after is D's) |
| R-12.3 | §3 `EXTRAS_LOOK` items |
| R-12.4 | §9 (provenance), §7 (rights), §9 SFX terms |
| R-12.5 | §8 season-2 import |
| R-12.9 | §9 output inspection + B's originality checks upstream |

**Findings resolved here:** V3C-6 (§8), V3C-8 (§4), V3C-10 (§6), V3C-19 (§5), V3C-33 (§9), V3R-1 (§7),
V3R-2 (§7), V3R-11 (§7), N7 (D consumes; C supplies the neutral binding), N13 (§7), N16 (§9), N23 (§4),
N30 (§1.10, §6), O-6 (§3, O-C3), O-9 (§9), O-10/O-11 (§7).
