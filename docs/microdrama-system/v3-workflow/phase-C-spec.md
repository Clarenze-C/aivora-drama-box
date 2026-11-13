# Phase C: Character bible → picks → wardrobe → voices → CAST LOCK

**Version 0.2 DRAFT, 13 Nov 2026** (v0.1 11 Nov, GLM draft; **v0.2 applies the Goldfish rulings
(`phase-c-goldfish-rulings.md`)** — both Blockers with steering, all 27 Majors, the grouped Nits; two
items stay OPEN (OPERATOR)). Author: GLM (spec draft job); orchestrator Opus.

**Status: DRAFT for Codex critique.**

**Master:** [SPEC-v3.md](SPEC-v3.md) v0.4.6. **Depends on:**
- [phase-A0-spec.md](phase-A0-spec.md) v0.4 (`LlmStep`, the jobs schema incl. `defer_reason`; C consumes
  the jobs/runtime schema, adds no LLM calls);
- [phase-A-spec.md](phase-A-spec.md) v0.3: gates, the decision transaction, budget accounts/steps, the
  fence, the command table, the outbox event names;
- [A1-design-note.md](A1-design-note.md) v1.2 (+ A2/A3 notes): migrations 0028–0034+, the discriminator
  (`seasons.workflow_version`), `RevisionTargetKind`, `work_scope`, the lock order;
- [phase-B-spec.md](phase-B-spec.md) **v0.4**: `SeasonDemandListV3` (§4.3), the STORY LOCK hand-off,
  `v3_story_documents`, `StoryLockBindingV3` (§5.4).

**Citation convention:** "master §x" = [SPEC-v3.md](SPEC-v3.md); "phase-A §x.y" = a real subsection of
`phase-A-spec.md`; "phase-A §2 item 7" = numbered **item** inside phase-A §2 (item refs always say
"item"); "A1/A2/A3 note §x" = the design notes; "B §x" = `phase-B-spec.md` v0.4; "DECISIONS" =
[DECISIONS.md](DECISIONS.md); "REQUIREMENTS" = [REQUIREMENTS.md](REQUIREMENTS.md). All citations were
swept in v0.2.

**Facts:** [c-factmap.md](c-factmap.md) (13 Nov), cited `FM §n`. The orchestrator's spot-checks confirmed
FM §1 (DDL and dead callers), §3, §5 (helpers unwired), §6–§8; v0.2 re-verified every code anchor this
spec cites directly. Code references relative to `microdrama/src/microdrama/` (`S/`); migrations `M/`;
tests `X/`. Migration numbers here are **symbolic `C-1…C-n`**; real numbers are allocated in the C1 note
after A and B land. **`C-3` is dropped in v0.2 (§2); the remaining symbolic names are unchanged.**

**Owns:** V3-AT-5, 6, 7, 15, 22, 23, 33 and the **offline half** of V3-AT-28 (its live half — real ARISA —
is phase G's), plus R-4.1..R-4.11, R-12.1..R-12.5, R-12.9 (master §15.1–15.2). R-12.7 is A-owned; C
consumes its `step_04` key.

**Erratum requested (not edited here):** master §4.4.4 items 3–4 still say "per expression"; DECISIONS
12 Nov supersedes them (one neutral clip per speaker). The erratum request is routed to the master owner
(Opus, Mon 14 Nov) as was done for R-4.6; this spec implements the superseding rule.

---

## 0. Scope

**Phase C builds tab 4 of the stepper and the CAST LOCK gate:**
1. **Pick items** derived from B's `SeasonDemandListV3`: the **initial-generation batch**, candidates,
   votes, re-roll, "generate next", dependent invalidation — the picks engine and its UI.
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
   (master §10.0 state mapping), derived, never stored as side state (AR-4, [codex-a-critique.md](codex-a-critique.md)).
   **The one automatic enqueue in the phase is the initial-generation batch at setup-budget approval**
   (§4): a bounded set of ordinary `cast_v3.generate` job rows — no fourth operator verb, no batch
   orchestrator. `derive_pick_items` is claimed by **C2**; the planning-track entry
   `STORY_LOCKED → CASTING` is claimed by **C4** (asserted by C-T3).
3. **One neutral voice reference per speaker** (DECISIONS "D2 revised again", 12 Nov). Per-emotion voice
   variants are **not built**. The prompt carries emotion (B §2.2 owns the vocabulary); C supplies only
   the neutral clip and its binding.
4. **Botnoi catalogue, two sources** (DECISIONS "D2 update"): API import (`get_speaker_data`,
   `get_speaker_data_v2`, no token) + operator CSV additions. Community voices are excluded from
   shortlists by default and need per-voice operator approval in their rights record. `has_v4` is an
   operator confirmation; `last_verified` >90 days is flagged (N13).
5. **Botnoi rights basis is `OPERATOR_ATTESTED`** (O-11), stored verbatim from DECISIONS in every Botnoi
   voice rights record, **with territories = `WORLDWIDE`** (the sales-page use cases are worldwide; a
   missing territories value would otherwise fail closed as UNKNOWN and block every voice).
6. **Nano Banana (Q8):** model `gemini-nano-banana-2.1` — "Nano Banana Pro" in master §10.3's wording —
   on the shared Vertex project. Fake by default; live behind a per-provider switch + qualification +
   rights + a non-None `image_price` quote (the same predicate as §5). **One Nano Banana process across
   ARISA and Drama Box**, interoperating with ARISA's existing flock (FM §8): same inode, crash-safe,
   bounded Drama batches (master §10.2).
7. **All paid work goes through phase A's accounts:** `SEASON_SETUP` account, `step_key = 'step_04'`
   (A2 0033 CHECK vocabulary; R-12.7 is A-owned — C consumes the key), admission order unit → step →
   child → `SEASON`. Unknown price = refused (FM §3 config rule). The setup sub-budget value is
   **proposed by C, operator-approved** (O-6).
8. **CAST LOCK is a V3 gate through the A1 decision transaction.** The mechanical freeze reuses
   `identity_locks` + `identity_lock_assets` and their readers; the SQL relaxes `source_episode_id` /
   `release_package_hash` to nullable **for V3 rows only** (`seasons.workflow_version`, §2 `C-7`). The
   episode-1 Gate 2 lock path never fires for V3 seasons (master §4.4.5).
9. **R-12.1 fix (adopt-if-present):** CAST LOCK stamps **every** episode row of the season (§8 step 5);
   V3 episodes created at STORY LOCK exist **before any lock** and are stamped by the lock transaction,
   not at insert. `attach_identity_lock` (`S/references/service.py:285`, verified no production caller
   today) becomes the production helper with **adopt-if-present** semantics — it stamps the season's
   current lock when one exists and is used for **extension episodes only** (created after a lock); its
   typed `IdentityLockRequired` error path stays for V1 callers (`service.py:294–299`).
10. **Canonical setting ID = the location demand ID** everywhere in V3 (N30). `StoryTime.setting` free
    text is never a key; the V2 compiler comparison stays V2.
11. **C makes no LLM calls.** Shortlist ranking, casting-sheet scripts, wardrobe derivation, forecasts
    and output inspection are deterministic. Nothing in master §4.4 requires an LLM in step 4.
12. **No second job system** (master §10.0): generation units are jobs + `ProviderOperation`
    (`S/contracts/cost.py:711`) through the existing `GenerationProvider` protocol
    (`S/contracts/providers.py:188`, verified). C adds the lanes `image`, `voice_intake`, `media` through
    phase A's four-point checklist (queue CHECKs, `budget/policy.py` ownership, worker set, generated
    contracts). Music and SFX share the one `media` lane: each carries ~1 job/season with the same
    admission profile, so separate lanes would add CHECK and worker sprawl with no contention to manage.

## 2. Records (contract package, guardian-owned bump; symbolic migrations `C-1…`)

All V3 cast documents are append-only, versioned, hash-sealed, stored in a new **`v3_cast_documents`**
table through `CastV3Store`, mirroring B's `StoryV3Store` (B §2): PK `(contract_type, record_id,
version)`, one `current` row, hash re-verified on read, standard guards, a `contract_type` allowlist
CHECK. `record_id = uuid5(CAST_V3_NS, "<type>:<season_id>[:<key>]")`. `v2_contract_documents` and
`v3_story_documents` are not touched.

| Migration | Object | Decisive columns / rules |
|---|---|---|
| `C-1` | **`cast_pick_items`** | `season_id`, `demand_id`, `pick_kind` (below), `item_key`, `target_ref_kind`/`target_ref_key` (nullable; maps to `reference_versions` per §2.1), `required bool` (one meaning: the item must be *resolved* before Approve — picked or bulk-accepted), `selection_mode` (`HUMAN_PICK` \| `DERIVED`), `parent_pick_id` nullable, `parent_version_at_generation` int nullable (staleness check, §4); `UNIQUE (season_id, demand_id, pick_kind, item_key)`; guarded |
| `C-2` | **`cast_pick_votes`** (append-only) | `pick_id`, `candidate_kind` (`REFERENCE_VERSION` \| `CATALOG_ENTRY`), `candidate_id`, `note`, human-session ref, `created_at`; a vote records only a choice — no state mutation, no job |
| ~~`C-3`~~ | **dropped in v0.2** (MAJ-6): dependency edges are a **computed closure** over `cast_pick_items` (`parent_pick_id` + `pick_kind` determine both edge kinds), delivered to A4's `DependencyProvider` as a function — no table, no registration path to drift. **The remaining symbolic names `C-4…C-8` are unchanged.** |
| `C-4` | **`botnoi_voice_catalog`** (global, not season-scoped) | `source` (`api_v1` \| `api_v2` \| `operator_csv`), `voice_name`, `speaker_id` nullable, `gender`, `age_group`, `accent`, `style_notes`, `has_v4` (NULL = unconfirmed), `voice_kind` (`cast` \| `api` \| `community`), `last_verified`, `raw jsonb`; `UNIQUE NULLS NOT DISTINCT (source, voice_name, speaker_id)` (PG15+ is the deployed floor) so operator rows with NULL speaker are still deduplicated; guarded |
| `C-5` | **`provenance_records`** (append-only) | `subject_kind` (`ASSET` \| `METHOD` \| `DETECTOR_WEIGHTS` \| `FONT` \| `VOICE` \| `SFX_ROUTE` \| `MUSIC_JOB`), `subject_ref`, `basis`, `basis_version`, `entitlement` (generation-time entitlement of the subject — what the licence lets us *generate*; plan/subscription upgrade rights are a different axis and never re-read here), `model_provider`, `prompt_hash`, `seed`, `license_hash`, `evidence jsonb`; `UNIQUE (subject_kind, subject_ref, basis_version)` |
| `C-6` | **`voice_uploads`** (guarded) | `season_id`, `character_demand_id`, `slot` (`neutral`), `state` (`QUARANTINED` \| `REJECTED` \| `NORMALISED` \| `REGISTERED` \| `SUPERSEDED`), `idempotency_key` UNIQUE, `expected_content_revision`, `object_key` (the quarantine object-store key, §7), `source_sha256`, `normalised_sha256`, `rejection_reason`, `checks jsonb`, `attestations jsonb`, `asset_id` nullable |
| `C-7` | **`identity_locks` relaxation + version-aware CHECKs** | `ALTER COLUMN source_episode_id DROP NOT NULL`, same for `release_package_hash` (0002:258, 261 — verified); a version-aware constraint trigger keeps both **required when the lock's season has `seasons.workflow_version = 'v1'`** (join `identity_locks.season_id → seasons.workflow_version`, A1 0028's discriminator; no `schema_version` column is involved). V3 lock rows carry the table's own `schema_version = '1.0'` (the row shape is unchanged; the discriminator is the season's workflow version) and require a `CastLockV3` document ref in `body`. **The same migration grows `reference_versions.ref_kind` and `identity_lock_assets.asset_kind`** (0002:158/275) with the §2.1 values, version-aware the same way: V1 seasons keep exactly the five-kind vocabulary, V3 seasons admit the extended set. `md_forbid_mutation` stays |
| `C-8` | queue lanes + rights/provenance CHECK plumbing | `jobs.queue` CHECK gains `image`, `voice_intake`, `media` (0001:77 today: `production/publication/community` — verified); matching reservations/charges and `budget/policy.py` ownership |

**`pick_kind` vocabulary:** `FACE`, `SHEET_VIEW`, `EXPRESSION`, `OUTFIT`, `APPEARANCE_STATE`, `PROP`,
`LOCATION_MASTER`, `LOCATION_COVERAGE`, `EXTRAS_LOOK`, `VOICE_NEUTRAL`, `MUSIC_LIB`, `SFX_LIB`.

### 2.1 The pick-kind → ref_kind/asset_kind mapping and ref_key namespacing (binding)

`reference_versions.ref_kind` and `identity_lock_assets.asset_kind` are hard CHECKs over
`FACE/VOICE/WARDROBE/LOCATION/STYLE` (0002:158/275). C maps **where the semantics are true** and extends
both CHECKs with honest values for the rest (via `C-7`'s version-aware pattern — V1 rows and writers keep
the five-kind vocabulary):

| pick_kind | `ref_kind` | `asset_kind` | `ref_key` namespace |
|---|---|---|---|
| `FACE` | `FACE` | `FACE` | `face:<character_key>` |
| `SHEET_VIEW` | `FACE` | `FACE` | `sheet:<character_key>:<view>` |
| `EXPRESSION` | `FACE` | `FACE` | `expr:<character_key>:<expression>` |
| `OUTFIT` | `WARDROBE` | `WARDROBE` | `outfit:<character_key>:<outfit_key>` |
| `APPEARANCE_STATE` | `WARDROBE` | `WARDROBE` | `state:<character_key>:<state_key>` |
| `PROP` | `PROP` *(new)* | `PROP` *(new)* | `prop:<prop_key>:<state_key>` |
| `LOCATION_MASTER` | `LOCATION` | `LOCATION` | `loc:<location_demand_id>:<light_state>` |
| `LOCATION_COVERAGE` | `LOCATION` | `LOCATION` | `loc-cov:<location_demand_id>:<light_state>:<view>` |
| `EXTRAS_LOOK` | `EXTRAS_LOOK` *(new)* | `EXTRAS_LOOK` *(new)* | `extras:<role_key>` |
| `VOICE_NEUTRAL` | `VOICE` | `VOICE` | `voice:<character_key>:neutral` |
| `MUSIC_LIB` | `MUSIC_LIB` *(new)* | `MUSIC_LIB` *(new)* | `music:<season_id>:<recipe>` |
| `SFX_LIB` | `SFX_LIB` *(new)* | `SFX_LIB` *(new)* | `sfx:<season_id>:<recipe>` |

The `ref_key` namespace prefixes are load-bearing: §4 defines an item's candidate set per
`(target_ref_kind, target_ref_key)`, and distinct prefixes are what keep a character's `FACE` and its
sheet views (both `ref_kind FACE`) from silently merging candidate sets. `STYLE` stays V1-only (C never
writes it). **Library items (`MUSIC_LIB`, `SFX_LIB`) are `reference_versions` rows** like every other
candidate (their audio assets link by content hash at lock); `cast_pick_votes.candidate_kind` is therefore
`REFERENCE_VERSION | CATALOG_ENTRY` only — no `ASSET` kind.

### 2.2 C contract crossings (the C-B1 pattern, B §2.4)

Every C identifier crossing an A- or B-enforced contract, checked against that contract's enforced
vocabulary **before the C1 note is accepted**:

| # | Delta | Contract touched | Mechanism |
|---|---|---|---|
| CD1 | Queue lanes `image`, `voice_intake`, `media` | A0/A3's `jobs.queue` CHECK (0001:77) | `C-8` grows the CHECK; worker set + `budget/policy.py` ownership land in C3 |
| CD2 | `identity_locks` NOT-NULL relaxation; `ref_kind`/`asset_kind` CHECK growth (§2.1) | 0002:158/258/261/275 | `C-7`'s version-aware constraint triggers keyed on `seasons.workflow_version` (A1 0028); V1 rules preserved exactly (C-T1) |
| CD3 | `RevisionTargetKind` grows `PICK = "pick"` | A1 note §4's StrEnum + validators (`S/contracts/v3.py`) | C-owned migration in C's range, mirroring B's D2; CAST Revise notes target `{kind: pick, id: cast_pick_items.id}` |
| CD4 | `DeferReason` grows `PROVIDER_LOCK_BUSY` | A0's 0027 CHECK; A1 0031's wait-view CASE | C-owned migration; the 0031 view's CASE maps it to `WAITING_PROVIDER` (flock-busy deferrals, §5) |
| CD5 | B's `CharacterProfile` gains structured `visual_lock.sheet_views` (list of view names) | B's `v3_story_documents` contract (v0.4 carries visual lock as **text**) | requested as a B contract delta through this register (B owner confirms in the C2 note); C's deterministic fallback in §3 makes C2 buildable either way |

**Standing rule (C-B1 for C):** any further C identifier that crosses an A/B enforced contract (enum,
CHECK, validator) is added to this register and checked before the C1 note is accepted.

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

## 3. Demand list → work: items, projection, forecast (R-3.4 consumer, R-4.11, R-12.7 consumed)

**Derivation** `derive_pick_items(season, demand_list)` — deterministic, rerun idempotently (items keyed
by demand + kind + key, so a B Revise that keeps an item keeps its picks). It also **upserts `characters`
rows keyed by the character demand ID** (B §4.3's `character_key`): `voices.character_id` is
`NOT NULL REFERENCES characters` (0002:138), so without this the first accepted voice upload fails on the
FK. B's promotion facts are referenced from the demand list — **no lineage table** (B §4.2 is the record).

| Demand (B §4.3) | Pick items |
|---|---|
| `CHARACTER` PRINCIPAL | `FACE`; `SHEET_VIEW` × (front, rear, tight face, profiles if the bible asks — the sheet-view ask below); `EXPRESSION` × (neutral, signature, extreme) |
| `CHARACTER` SUPPORTING | `FACE`; `SHEET_VIEW` × (front, tight face); `EXPRESSION` × (neutral, signature) |
| `OUTFIT` | `OUTFIT` (built on that character's `FACE`) |
| `APPEARANCE_STATE` | `APPEARANCE_STATE` (built on `FACE`) |
| `PROP` (+ state) | `PROP` per `state_key` |
| `LOCATION` + light state | `LOCATION_MASTER` per light state; then a **rerun-safe second pass** creates `LOCATION_COVERAGE` × (reverse, tighter) once the master pick exists (a vote on the master); idempotent — the pass creates each coverage item once, keyed by demand + kind + key |
| `EXTRAS_ROLE` | `EXTRAS_LOOK` (2–4 candidate looks → pick one; §15 O-C6, decided) |
| `VOICE` | `VOICE_NEUTRAL` (§7) |
| — (season libraries, N16) | `MUSIC_LIB`, `SFX_LIB`, accepted in the CAST review (§12) |

"Reverse" = the master plate's opposite camera direction over the same geometry, time and weather;
"tighter" = a tighter framing of the same geometry — both defined in the prompt lineage (§6).

**Sheet-view ask (the named field).** The ask is read from **B's
`CharacterProfile.visual_lock.sheet_views`** (a list of view names; CD5). If B has not shipped the field
when C2 builds, the deterministic fallback is: the tier-standard set (§3's rows) plus any explicitly
enumerated view tokens found in the existing visual-lock **text** (`front`, `rear`, `tight`, `profile`) —
never an LLM, never a guess outside the closed view vocabulary.

**Human picks vs derived assets (master §4.4.1).** `required` keeps one meaning — *the item must be
resolved before Approve*. `selection_mode` says how:

| Class | pick kinds | Resolution before Approve |
|---|---|---|
| `HUMAN_PICK` | `FACE`, `OUTFIT`, `APPEARANCE_STATE`, `PROP`, `LOCATION_MASTER`, `EXTRAS_LOOK`, `VOICE_NEUTRAL` | a latest vote exists (operator vote; audition vote for voices) |
| `DERIVED` | `SHEET_VIEW`, `EXPRESSION`, `LOCATION_COVERAGE`, `MUSIC_LIB`, `SFX_LIB` | accepted at the CAST review (bulk acceptance, §4) or re-rolled |

An item whose `demand_id` is absent from the **current** demand-list version (a post-STORY-LOCK amendment
dropped the demand) is **not-required by derivation** — computed at read time by joining the current
demand list, never a stored flag (append-only rows are never rewritten). It neither blocks the lock nor
enters the binding hash; its votes stay as history.

**Image-volume projection** (master §10.4): projected count = Σ per item (**3 candidates** per root
generation item — master §4.4's "2–3" pinned to 3 for forecast and metering stability — plus derived
views) × (1 + re-roll rate). Re-roll rate and lock throughput (images/hour) are **config with measured
defaults pending P0** (`UNVERIFIED` until then; the panel labels them "estimated"). Wall-clock estimate =
count ÷ throughput, shown with the fairness batch parameters (§5).

**Cost forecast** (master §12.3, before CAST LOCK): volume × unit price + voice/music/SFX lines +
already-committed setup spend; the **average-episode capacity line** (`(season cap − setup) ÷ episodes`)
is shown; a forecast above cap is a **CAST LOCK gate condition blocker** with "raise the cap or cut
scope". **While `image_price` is unknown (pre-qualification) the forecast does not estimate or zero-fill:
the panel and the CAST LOCK forecast condition read BLOCKED (price unverified)** until the operator
supplies the measured price (O-C4, resolved — block, don't estimate). Offline tests configure a fixture
quote. The **setup sub-budget proposal** (O-6) is computed here and approved via A2's
`approve_setup_budget` — no paid setup work before it (AC-13, [codex-a-critique.md](codex-a-critique.md)).

**Panels from B §4.3 that C fills:** the step-4 cost forecast panel and the image-volume projection
panel on the STORY LOCK screen (`NOT_AVAILABLE` until the C2 package ships).

## 4. The picks engine (V3C-8; V3-AT-5, V3-AT-22; R-4.8)

- **Initial generation (the phase's entry flow).** When the operator **approves the setup budget**
  (A2's `approve_setup_budget` decision), the handler enqueues a bounded batch of ordinary
  `cast_v3.generate` job rows: **exactly 3 jobs per root generation item** (`FACE`, `PROP`,
  `LOCATION_MASTER`, `EXTRAS_LOOK` — items with no parent). One job emits **one candidate**; the fairness
  batching in §5 bounds dispatch. No fourth operator verb, no batch-orchestrator component. Dependents
  are never auto-generated — **generate next** is the operator action for them.
- **Candidates** are `reference_versions` rows (FM §1: multiple versions per
  `(season, ref_kind, ref_key)` are the de-facto candidate grid today; nothing records a choice). The
  item's candidate set = versions in `PROVISIONAL`/`ACCEPTED` for its `(target_ref_kind, target_ref_key)`
  (namespaced per §2.1).
- **`vote(pick, candidate, note)`** — human session + CSRF + idempotency key. Appends one
  `cast_pick_votes` row; **starts no work**. The current selection = the latest vote. Votes on superseded
  candidates stay as history.
- **Derived acceptance (one mechanism, two policies).** The CAST review's "accept derived assets" action
  is a **bulk operator action that appends one session-marked `cast_pick_votes` row per derived item**
  (candidate_kind `REFERENCE_VERSION`, note "bulk acceptance", one idempotency key for the batch) — the
  same vote mechanism, the derived policy. No second state machine.
- **`reroll(pick, note)`** — operator action; enqueues exactly **one** item's generation job — one new
  candidate (new versions append; the selection is untouched until a new vote). Counted in the forecast's
  re-roll metric and metered normally.
- **`generate_next(parent_pick)`** — operator action (N23); enqueues the parent's dependents' jobs
  **against the selected parent revision** (the request's `reference_asset_ids` carries it;
  `parent_version_at_generation` is stamped on the child item).
- **Staleness / invalidation (V3-AT-22):** a dependent is *stale* when
  `parent_version_at_generation ≠` the parent's currently selected version — computed from stored
  columns, never a stored flag. A stale dependent's candidates are visually marked; **its item must be
  re-picked (re-roll + vote) before lock**; unrelated picks are untouched. A4's coordinator uses the same
  **computed dependency closure** for post-lock amendments (master §12.6).
- **State projection** per master §10.0: queued/leased → `QUEUED`/`GENERATING`; succeeded → `READY`;
  after a vote → `VOTED`; derived jobs done → `DERIVED_READY`; at CAST review → `ACCEPTED`; retry →
  `FAILED_RETRYABLE` (+`WAITING_PROVIDER`/`WAITING_QUOTA` by cause); unknown → `UNKNOWN`/`BLOCKED
  (reconcile)`; terminal → `FAILED`/`BLOCKED`. Progress bars per category (R-4.11): generated n/N,
  picked n/N.
- **Lock refusal (V3-AT-5):** Approve is refused with the typed list of unresolved required items and
  stale descendants (§8; gated at C9, C-T13).

## 5. Image generation: adapter, cross-system lock, metering (Q8, V3C-19; V3-AT-15/28)

- **Adapter seam:** `NanoBananaProvider` implements `GenerationProvider`
  (`submit(op, ImageRequest | VoiceRequest) / status / reconcile / fetch_output`,
  `S/contracts/providers.py:188–205` — verified). Prompt building is **castkit/scenecraft structured
  builders** (V3-only, `S/cast_v3/promptkit.py`): the face-lock prompt is the 18% neutral gray field,
  directionless light, no baked lighting, forehead-to-upper-chest framing (master §4.4.2). Output
  inspection (§9) runs inside the job after `fetch_output`.
- **Reuse (the adapter wrap):** C3 **wraps/extends the existing `GenerationAdapter`** scoped to
  season/`step_04` work, reusing its `check_rights` and `build_image_request` unchanged. **Seed policy:
  every attempt rotates the seed**, so every generation — initial candidate or byte-identical-looking
  re-roll — derives a distinct `cache_key` input; the fake provider varies its output bytes by seed. The
  `UNIQUE (season_id, cache_key)` constraint on `reference_versions` (FM §1) is the duplicate guard and is
  **never weakened**.
- **Fake by default:** the composition wires `image_provider = 'fake-generation'` (the existing fake,
  FM §3). **Live switch:** per-provider config `nano_banana.enabled` + an A6 `provider_qualifications`
  row + a rights route `route-nano-banana` (evidence required; fail-closed `check_rights`, FM §7) + a
  non-None `image_price` quote. Any missing piece keeps the provider disabled — never zero-priced.
- **Cross-system single-process lock (V3-AT-15, V3-AT-28):** `cross_process_generation_lock(path)`
  opens the configured lock file **read-only** and takes `fcntl.flock(LOCK_EX | LOCK_NB)` — exactly
  ARISA's pattern (`arisa/studio/sfw/recovery.py:91–105`, file verified present). Busy → a typed busy
  error → the job defers `WAITING_PROVIDER` with `retry_after` (**DeferReason `PROVIDER_LOCK_BUSY`**,
  CD4; bounded backoff; **waiting is visible and holds no GPU lease**).
  **Lock-file integrity:** the acquisition `fstat`s the descriptor and compares `st_dev`/`st_ino` against
  the **pinned inode** recorded in the A6 `provider_qualifications` row for the provider (qualified and
  re-expired on the same cadence as any other qualification); a mismatch — an ARISA deploy replaced the
  file, breaking mutual exclusion — raises a typed **BLOCKED** with operator visibility. No watchdog: a
  mid-hold swap can overlap at most one ≤120 s batch. A **missing or unreadable** canonical lock file is
  a typed error (not an unhandled `FileNotFoundError`): the job defers `WAITING_PROVIDER`
  (`GATEWAY_UNAVAILABLE`) with operator visibility.
  **Crash-safe:** the kernel releases flock on process death; a restart cannot inherit a hold.
  **Fairness:** bounded Drama batches — at most `fairness_batch_images` (default 8) or
  `fairness_batch_seconds` (default 120 s) per hold, then release and re-acquire, so ARISA's turns and
  Drama's interleave. **Hold span: submit through final poll** — the lock is held from the first submit
  of a bounded batch through the final status poll of its last operation (not per POST). `retry_after`
  defaults to 20 s mirroring ARISA's. Defaults are config (O-C7); P0 measures real throughput.
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
    **per-episode with resolver continuity across boundaries** — the frozen V2 `StateEvent` shape stays
    episode-scoped; no new season-level wrapper (the C5 note pre-makes the shape). A mid-scene change is
    an **operator-planned refinement** on the wardrobe screen: it must cite a beat or scene break that
    allows it — the same evidence B's "impossible wardrobe day" critic accepts (B §6.2, C-M19). B's pack
    schema expresses per-scene wardrobe only — recorded as O-C2, not silently resolved.
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
  `reference_asset_ids`, fixed seed family, and a provenance link), accepted in the CAST review. The two
  coverage views are §3's **reverse** and **tighter**.
- **`LineAudio`-style orphan note:** FM §6 records that line-level TTS audio is unused by rendering; V3
  has no line TTS at all (native Pika audio), so C adds none.

## 7. Voices (R-4.6 as superseded by D2 chain; V3R-1, V3R-2, V3R-11)

**Catalogue (C-4).** Importer job `cast_v3.botnoi_refresh` (queue `production`; public no-token
endpoints; offline tests use fixture responses):
- maps `get_speaker_data` / `_v2` rows (fields verified in
  `botnoi-api-speakers-2026-11-11.csv`, whose actual header carries a leading `source` column:
  `source, speaker_id, eng_name, thai_name, language, gender, age_style, voice_style, speech_style,
  speed, price, sample_audio`) into catalogue rows, `source = api_v1|api_v2`, stamps `last_verified`;
  **archetype labels are not inferred** (DECISIONS 12 Nov correction: monks 582/583 are unlabelled in
  API fields) — archetypes come only from operator additions;
- never deletes or overwrites `operator_csv` rows; entries with `last_verified` >90 days are flagged
  (N13);
- operator additions import from `botnoi-v4-voices.csv` (header-only today, verified — the seed
  template) with exactly the DECISIONS field list; the Studio archetypes (7 monk, 2 grandpa, 2 grandma,
  Ananda, Bow) are entered when a season casts them.

**Shortlist (V3R-11).** Deterministic ranking of the catalogue against the `CharacterProfile` voice
descriptor (B §2): gender must match exactly; then a **normalized tag-overlap score** over the
descriptor's fields (age band, accent, style tokens — per-field token-set overlap normalised, weighted
age 0.4 / accent 0.3 / style 0.3) with a **stable tie-break** (score desc, then `voice_name` asc, then
`speaker_id` asc). Output: **top-3 suggestions with reasons, no audio generated**, stored in
`VoiceCastingV3`; the shortlist is **flagged "thin"** when the rank-2→3 score gap is < ε (0.05). If
**fewer than 2** voices survive the gender-exact filter, the shortlist is flagged and **1 entry is still
shown** (never padded, never empty when one exists). The exact formula lives in the C6 note; §1.11's
determinism assertion and C-T9's shape check test against it. Community voices are excluded unless their
per-voice approval exists (a `rights_registry` VOICE row with the operator's explicit approval as
evidence); `has_v4 IS NULL` entries may appear but are flagged "confirm V4 in Studio".

**Audition.** The operator auditions in Botnoi externally and records the pick (catalog ref) or "other"
with a reason. The audition pick is the `VOICE_NEUTRAL` item's vote (candidate_kind `CATALOG_ENTRY`) —
it selects no asset yet.

**Casting sheet.** One **neutral** 10–15 s Thai script per speaker, assembled deterministically from the
character's own pack lines (longest TH lines fitting the window; a template fallback is marked if the
character has too few lines). Suggested V4 inline tags are listed **as options only** — the pilot leak
observation (master §4.4.4 8) applies: if tag vocalisations leak into Pika output, scripts go tag-free.

**Upload intake (V3R-1).** One slot per character (`neutral`), single upload or **zip bulk import** with
files named exactly `<character_key>__neutral.wav|.mp3`, where `character_key` is **B's character demand
key** (the `character_key` in `SeasonDemandListV3`); the upload UI shows each character's expected
filename. Every request requires owner scope, CSRF, `expected_content_revision` (the fence value) and an
idempotency key. **Numeric limits C sets:** request ≤ 50 MB; zip entries ≤ 64 (the per-import entry cap
is enforced before extraction — the same 64); expanded total ≤ 500 MB; decoded length 3–60 s per clip;
processing ≤ 120 s per import — **exceeding the processing budget rejects the import** (`REJECTED`,
reason `processing_timeout`; a retry with a new idempotency key is allowed). **Rejected:** path
traversal, absolute paths, symlinks/hardlinks, duplicate slots, unknown keys, undecodable audio.

**Quarantine storage.** Untrusted bytes persist between HTTP request and the async `cast_v3.voice_intake`
job in the **object store under the private bucket prefix `voice-quarantine/<season_id>/<upload_id>/`**
(server-generated keys, recorded in `voice_uploads.object_key`); never local scratch, never the upload
path. Files land `QUARANTINED`; **QUARANTINED rows survive a restart** (the bytes and the row are
durable) and are **re-scanned**: an intake reconcile finds rows with no live job and re-enqueues by
`logical_work_id`. Decoding runs isolated (a subprocess with a timeout against a scratch dir, never from
the quarantine prefix); **failed imports never overwrite accepted assets** (registration only ever
appends versions). Hostile-input tests are acceptance C-T10.

**Normalisation and assessment (V3R-2).** A versioned profile `voice-normalisation-v1`: PCM WAV,
24 kHz, mono, 16-bit (matches the T031 references, 24 kHz mono — DECISIONS 12 Nov). **Validator of
record: C's own profile check**, extending `references/media.py` (`wav_media_info`, `verify_generated` —
the real seam), with **ffmpeg as the isolated-decode subprocess**; the binder's byte validator (which
lands with D's T031 merge) **must agree** with this profile — the C7 note records the agreement
obligation. **Only the resulting PCM WAV is registered** as the asset; `source_sha256` and
`normalised_sha256` are both kept. Recorded technical checks (duration, rate, channels, clipping,
leading/trailing silence) + assessment of Thai speech, transcript match, single-speaker suitability and
consistency with the base voice — automated where a qualified detector exists, otherwise a **recorded
human check**; **V4 origin and voice identity are operator attestations, labelled separately** from
machine checks. The accepted clip becomes the `VOICE` reference version + a `voices` row
(`provider = 'botnoi'`, `provider_voice_ref` = speaker id, `anchor_asset_id` = the WAV) — the table
exists today (0002:134–151, verified). The `VOICE_NEUTRAL` item's **job lifecycle is the intake job**
(`cast_v3.voice_intake`), not image generation.

**Rights (O-11).** A `rights_registry` route `route-botnoi-voice` (subject `VOICE`) with basis stored
verbatim: `OPERATOR_ATTESTED (Botnoi sales-page use cases: ads/product videos, stories, audiobooks; no
licence document found; 11 Nov 2026; territories WORLDWIDE)` + a `provenance_records` row per voice. A
missing, corrupt or unapproved neutral reference **blocks dispatch** (the binding exposes a typed
blocker D enforces). Changing the base voice invalidates the clip (the item goes stale); after lock,
master §12.6.

## 8. CAST LOCK (V3C-6; V3-AT-5/6; R-4.9, R-12.1, R-12.5)

**The gate.** The C handler registers `CAST_LOCK` (phase-A §2 item 7: `NOT_AVAILABLE` before C ships).
The activation opens when every required item's generation work is terminal-successful, with binding =
canonical hash of (demand-list version, all pick items + current selections). **Approve conditions**
(evaluated in the A1 decision transaction): the binding is current; **every required item is resolved**
(human picks have a latest vote; derived items are accepted or re-rolled — refused with the typed list
otherwise, V3-AT-5); **every speaker has a registered, rights-approved neutral voice clip**
(`voice_uploads.state = REGISTERED` for the `VOICE_NEUTRAL` item + the `route-botnoi-voice` approval) —
without this condition the lock could Approve with no voice WAVs and the hash below could not be
computed; **no stale descendant** (V3-AT-22); the wardrobe plan validators pass; the forecast is present
and fits (a forecast above cap — or blocked on an unknown price, §3 — is a blocker); the setup budget is
approved. **Stale hash refused; Revise regenerates only the noted units** — notes target typed
`{kind: pick, id}` (CD3's `RevisionTargetKind.PICK`), and only those items re-roll (a scoped enqueue),
then the gate reopens with a new binding. **Reject** leaves planning at `CASTING` without cast authority
(phase-A §2 item 2).

**The lock transaction** (one transaction, phase-A §6 lock order), on Approve:
1. write the `CastLockV3` document. **`cast_lock_hash` preimage, exactly per member class:**
   - **STORY binding hash:** read from B's `StoryLockBindingV3` (`story-lock:<content_revision>` in
     `v3_story_documents`, §5.4) — the hashed set STORY LOCK approved, named source;
   - **picks:** per pick (demand id, item id, picked `reference_versions` id + `content_sha256`) — as
     today;
   - **derived assets:** per member (`ref_kind`, `ref_key`, `reference_versions` id +
     `content_sha256`) — asset content hashes + kind;
   - **voice WAVs:** per speaker, `voice_uploads.normalised_sha256` of the registered clip.
   All canonical-JSON encoded with a fixed field order, then sha256 (V3-AT-5: the hash covers **every
   picked version**);
2. insert the `identity_locks` row (version = next; `source_episode_id`/`release_package_hash` NULL;
   `approval_event_id` = this decision; `body` references the `CastLockV3` record);
3. write `identity_lock_assets` members per §2.1's mapping table (`pick_kind` → `asset_kind`); the table
   and readers stay (FM §1);
4. freeze: members → `LOCKED`, voices/characters → `LOCKED` (the existing state machines);
5. stamp **every** episode row `identity_lock_id` (all N — the locked episode count — exist from STORY
   LOCK);
6. `advance_planning(CASTING → CAST_LOCKED)`; the handler emits exactly **`gate.waiting`** when it opens
   the activation (before the decision) and **no** gate event after Approve (the activation is closed);
   the picks screens emit **`picks.waiting`** per category activation and the CAST review **`review.ready`**
   (phase-A §8 item 4's registered names — there is no "event family").

**R-12.1 (V3-AT-6):** the V3 episode-creation path is **adopt-if-present** (§1.9): episodes created at
STORY LOCK carry no lock (none exists) and are stamped by step 5 above; **extension episodes created
after a lock adopt at insert** through `attach_identity_lock` (`S/references/service.py:285`, verified no
production caller today) — which becomes the production helper for that path. A regression test creates
an extension episode after lock and proves attachment; the render gate's `IdentityLockRequired` hint
(FM §1) is then unreachable for V3. **V1 carve-out (OPEN — OPERATOR, §15 O-C9):** V1 `create_episode`
still sets no lock and the helper stays unused there; making that permanent needs the operator's nod.

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
revalidated at import** (expired/unknown blocks the item); voices re-attest per season. Built in the
trailing **C9b** package (§13), not in C9.

## 9. Provenance and output inspection (V3C-33, MA7; V3-AT-33; R-12.4, R-12.9)

- **Write path:** every asset registered by V3 code gets a `provenance_records` row **in the same
  transaction** as registration (the seam is the V3 sibling of `ReferencesService._register`, FM §2).
  Basis values include `OPERATOR_ATTESTED` (Botnoi; the T031 benchmark attestation —
  [T031-benchmark-packet.md](../T031-benchmark-packet.md)), `LICENSED` (fonts, detector weights, SFX
  route), `INTERNAL_METHOD_CREDITED` (Joey's skills — [joey-digest.md](joey-digest.md): internal only,
  credited, not redistributed, full text never embedded), `SUBSCRIPTION_TERMS`, `REUSE_WITH_LINEAGE`.
  Imported methods (weights, fonts, routes) get rows once, versioned.
- **Completeness (V3-AT-33):** CAST LOCK Approve additionally checks **every member asset has a complete
  `ProvenanceRecord`** (all §2 `C-5` fields present for its subject kind); a gap blocks the lock with the
  typed list.
- **Output inspection (master §12.2):** an `OutputInspectionProvider` seam runs on **every generated
  image** inside the generation job (and is reusable by D/F for thumbnails and clip-sampled frames):
  on-frame text (OCR), branding (a maintained mark list), likeness (face-embedding similarity against
  **the current selected candidate set** — the faces picked so far; most candidates are generated before
  any lock). Checks without a qualified detector (O-2) — likeness **and** OCR/branding — are a **recorded
  human check** (batched at the picks/CAST review), never an auto-PASS and **no detector plumbing is
  built before detectors exist**. Findings are recorded on the candidate, surfaced on the pick grid and
  the CAST review; unresolved findings follow QA/repair and Gate 2. R-12.9's "no on-frame text in
  generated frames" is enforced here (text is added in edit).
- **SFX route qualification (master §7, O-9):** compare fal.ai `fal-ai/elevenlabs/sound-effects/v2`
  ($0.002/s, commercial label — **re-verified at qualification**; `UNVERIFIED` here) vs OpenRouter
  (unverified → ineligible). The chosen route, terms and billing units are persisted
  (`provenance_records` `SFX_ROUTE` + a rights route); equivalent requests compared at all-in bounded
  prices; the maximum authorised charge reserved per request; unknown capability/terms/price ⇒
  ineligible, never zero-priced; if none qualifies, the SFX library job blocks.
- **YuE2 music library (V3C-20, N16):** a `GenerationProvider` adapter for the Drama-owned YuE2 job.
  **C8 is routed pre-critique, note first (§13)** — the C8 design note pins the **pinned instrumental
  recipe, the host the job runs on, the library composition (track counts, durations, loop targets), the
  fake adapter's unit counts** (the forecast's music line and C-T14c consume them), the
  vocal-leakage inspection (recorded human check until a qualified detector exists — same rule as OCR),
  rights, and the canonical YuE2 holds/recovery/finality semantics (the YuE2 skill's terms; see the
  `yue2-music` skill docs). The season library is generated in step 4's job graph under `step_04`, with
  A40 qualification recorded. Live behind its own per-provider switch; fake by default.

## 10. Jobs, fence and waits

| Job | Queue | Provider ops | Logical work ID |
|---|---|---|---|
| `cast_v3.generate` (one item, **one candidate**) | `image` | 1 image op | `cast-gen:<season>:<pick>:<gen_seq>` — `gen_seq` is a per-item monotone generation counter (1–3 = the initial batch; 4+ = re-rolls); deliberately **not** named "attempt", which is the jobs system's retry vocabulary |
| `cast_v3.botnoi_refresh` | `production` | none (public endpoints, fixture-tested) | `botnoi-refresh:<yyyy-mm-dd>` — the **calendar day** (Asia/Bangkok) at enqueue; a same-day rerun **replaces** the earlier job by `logical_work_id` (A1's `replaces_job_id` validation) |
| `cast_v3.voice_intake` (quarantine → decode → normalise → assess) | `voice_intake` | none (local) | `voice-intake:<season>:<upload>` |
| `cast_v3.music_lib` | `media` | YuE2 ops | `music-lib:<season>:<recipe>` |
| `cast_v3.sfx_lib` | `media` | SFX ops | `sfx-lib:<season>:<recipe>` |

- **Fence:** every job input carries `expected_content_revision`; stale results are quarantined
  (phase-A §7.1; A3 note §3.4).
- **Waits:** lock busy → `WAITING_PROVIDER` (`PROVIDER_LOCK_BUSY`, CD4; `retry_after`); lock file
  missing/unreadable → `WAITING_PROVIDER` (`GATEWAY_UNAVAILABLE`); budget → `WAITING_BUDGET`; reconcile →
  `BLOCKED (reconcile)` — all projected through `track_waits` (phase-A §3).
- **Crash/restart:** a restart resumes unfinished units and never regenerates successes (master §10.5);
  `reconcile` NOT_FOUND = safe to resubmit; QUARANTINED voice uploads are re-scanned (§7).
- **Offline:** every C test uses the fake generation provider, fixture Botnoi responses and synthetic
  flocks; no test calls the network, Vertex or Telegram. `make check` + V1 `make pilot` stay green.

## 11. C commands (A1 note §6 format; MAJ-12)

| Command | Actor | Prerequisites / allowed states | Effect | Events | Replay identity |
|---|---|---|---|---|---|
| `vote(pick, candidate, note)` | Operator (human session + CSRF) | season `CASTING`; candidate in the item's candidate set | appends one `cast_pick_votes` row; starts no work; current selection = latest vote | `picks.waiting` only if a category activation opens | idempotency key (replay returns the stored response) |
| `reroll(pick, note)` | Operator (human session + CSRF) | season `CASTING` | enqueues **one** `cast_v3.generate` job (next `gen_seq`, rotated seed); selection untouched; counted in the re-roll metric | — | idempotency key; a **new** key is a **new** re-roll |
| `generate_next(parent_pick)` | Operator (human session + CSRF) | season `CASTING`; parent has a current selection | enqueues the dependents' jobs against the selected parent revision; stamps `parent_version_at_generation` | — | idempotency key (replay returns the stored job list) |
| `accept_derived(scope)` | Operator (human session + CSRF) | season `CASTING`; scoped derived items' jobs terminal-successful | bulk-appends one session-marked vote per derived item (§4) | `review.ready` when all required items are resolved | one idempotency key for the batch |
| `edit_wardrobe(plan edits)` | Operator (human session + CSRF) | season `CASTING`; expected revision | edits `CastWardrobePlanV3` (validators run) | — | idempotency key |
| `record_audition(character, catalog_ref or "other"+reason)` | Operator (human session + CSRF) | season `CASTING` | appends the `VOICE_NEUTRAL` item's vote (`CATALOG_ENTRY`) | — | idempotency key |
| `upload_voice(file or zip)` | Operator (owner scope + CSRF) | season `CASTING`; `expected_content_revision`; limits §7 | creates `voice_uploads` rows (`QUARANTINED`) in the object store; enqueues `cast_v3.voice_intake` | — | idempotency key |
| `import_cast(source_season → new_season)` | Operator (human session + CSRF) | new season `CASTING`; source season `CAST_LOCKED` with a lock | season-2 copy with lineage + rights revalidation (§8); **C9b** | — | idempotency key |

A-contract deltas these commands rely on are registered in §2.2 (CD3 `RevisionTargetKind.PICK` for CAST
Revise notes; CD4 `PROVIDER_LOCK_BUSY`).

## 12. UI (tab 4, built into the phase A shell, A5)

| Screen | Route | Primary action |
|---|---|---|
| Cast overview + forecast | `/v3/seasons/{id}/cast` | **Approve setup budget** (before any paid work; triggers the initial-generation batch), then the category progress bars (R-4.11) |
| Picks grid per category | `/v3/seasons/{id}/cast/picks/{category}` (`category` ∈ the §2 vocabulary — constrained, nested under `/cast/picks/`, so it cannot collide with the fixed children below) | **Pick** (vote) — the one primary action; Re-roll and Generate next are secondary |
| Wardrobe plan | `/v3/seasons/{id}/cast/wardrobe` | timed-change editor, reuse reasons |
| Voices | `/v3/seasons/{id}/cast/voices` | shortlist → audition record → casting sheet → upload (single + zip, expected filenames shown) |
| CAST review | `/v3/seasons/{id}/cast/review` | derived assets + inspection findings; the CAST LOCK gate buttons |

States per master §3.2 (empty/loading/running/waiting for you/waiting quota/blocked/error/done); the
pick screens emit `picks.waiting` (phase-A §8 item 4). The forecast panel and image-volume projection
appear on B's STORY LOCK screen once C2 ships (filling its `NOT_AVAILABLE` panels).

**Pick-screen activation lifecycle (C-T15's "once per activation"):** an activation is **season-scoped
and per category**. It opens when the planning track enters `CASTING` (C4's transition, after C2's
derivation) and the category has items; it closes when every item in the category is resolved and no
unresolved inspection findings remain, and finally at the CAST LOCK decision. Pick screens are **not
`gate_activations` rows** (A1's CHECK admits the six gate types only): a category shows as **"waiting
for you"** as a UI projection — open human-pick items with candidate sets and no current selection
(unresolved findings also count at review). `picks.waiting` is emitted once per category-activation
open.

## 13. Build packages (in order; `make check` + V1 `make pilot` green at every gate)

Prerequisites: A0–A6 accepted; B accepted. Real migration numbers allocated in the C1 note after
re-auditing the tail. **Applied migration bytes are never edited.**

| Package | Builds | Gate | Design note |
|---|---|---|---|
| **C1** | Records + migrations `C-1`, `C-2`, `C-4..C-8` (`C-3` dropped, §2); §2.1 mapping + §2.2 crossing register delivered; contracts bump; `CastV3Store`; V1/V2 artifact byte-identity | C-T1 | **Critiqued first** (migrations + the crossing register) |
| **C2** | `derive_pick_items` (+ `characters` upsert, coverage second pass) + the **computed dependency closure** for A4; image-volume projection; cost forecast + setup proposal; fills B's panels | C-T2, C-T14a | With the diff |
| **C3** | Generation runtime: lanes, `cast_v3.generate` (gen_seq, seed rotation, the `GenerationAdapter` wrap), fake-first wiring, Nano Banana adapter + live switch, **cross-system lock + fairness + inode pinning**, metering + provenance write path | C-T5, C-T6, C-T14b | **Critiqued first** (money, locks) |
| **C4** | Picks engine: initial-generation batch at setup-budget approval, votes, bulk derived acceptance, re-roll, generate-next, staleness, state projections, **the STORY_LOCKED→CASTING transition** | C-T3, C-T4 | With the diff |
| **C5** | Wardrobe plan + timed changes + appearance/props/locations + resolver wiring (the per-episode StateEvent shape pre-made in the note) | C-T7, C-T8 | With the diff |
| **C6** | Botnoi catalogue + importer + shortlist (the ranking formula pinned in the note) + audition + casting sheet | C-T9 | With the diff |
| **C7** | Voice intake: upload, quarantine storage, normalisation (the profile check of record), assessment, rights | C-T10, C-T11 | **Pre-critique, note first** (trust boundary — in C7's definition of done; N24) |
| **C8** | SFX qualification + YuE2 library job (recipe, host, composition, fake unit counts pinned in the note) | C-T14c | **Pre-critique, note first** (money; MAJ-14) |
| **C9** | CAST LOCK gate + `CastLockV3` + identity-lock reuse + **R-12.1 (adopt-if-present)** + provenance completeness | C-T12 (provenance half), C-T13 | **Critiqued first** (lock transaction, migration) |
| **C9b** | Season-2 `import_cast` (R-12.5) — split out of C9 to shrink the riskiest package's critique surface (N26) | C-T13 (import clauses) | With the diff |
| **C10** | Output inspection seam + deterministic checks | C-T12 (inspection half) | With the diff |
| **C11** | Tab 4 UI (all screens, states, events, activation lifecycle) | C-T15 | With the diff |

**Routing:** GLM builds each package (`ai-route build -w`); Codex critiques the C1/C3/C7/C8/C9 notes
(C7/C8 note-first) and reviews every diff; one package at a time.

## 14. Acceptance (offline; real PostgreSQL for every transaction test)

| Test | Package | Proves |
|---|---|---|
| C-T1 | C1 | `C-1..C-8` (minus the dropped `C-3`) apply on a populated V1+V2 database; V1 `identity_locks` rows still require `source_episode_id` + `release_package_hash` (the version-aware trigger keyed on `seasons.workflow_version = 'v1'`); V1 `ref_kind`/`asset_kind` still admit only the five kinds; no row deleted or rewritten; **generated contracts show no drift — the baseline is committed generated code: regenerate in a clean checkout and diff (V1/V2 families byte-identical; any diff fails)** |
| C-T2 | C2 | Demand→item completeness both ways against a B demand list; tier-correct packages (incl. §3.1's sheet-view ask); **the computed dependency closure is correct** (FACE→sheets/expressions/outfits/states, master→coverage — no edge table); `characters` upserted per character demand; coverage second pass idempotent |
| C-T3 | C4 | **Votes start no work; Re-roll requeues exactly one item (one candidate, rotated seed); the initial batch enqueues exactly 3 jobs per root generation item at setup-budget approval — and nothing before it; generate-next enqueues dependents against the selected revision; the STORY_LOCKED→CASTING transition fires; staleness is computed, never stored** |
| **C-T4 (V3-AT-22)** | C4 | **A face re-roll/stale selection invalidates its dependent outfits/views; unrelated selections survive** |
| **C-T5 (V3-AT-15)** | C3 | **A second concurrent image job waits:** a simulated competitor holds the flock → the job defers `WAITING_PROVIDER` (`PROVIDER_LOCK_BUSY`) with `retry_after`; never two Nano Banana dispatches |
| **C-T6 (V3-AT-28)** | C3 | Competing processes (two workers, separate connections) share the same lock inode; a killed holder releases; crash/restart cannot overlap provider processes; an inode swap (delete+recreate) raises the typed BLOCKED |
| **C-T7 (V3-AT-7)** | C5 | A timed mid-scene outfit change appears in the resolved shot-reference expectations; a new story day gets a different outfit unless a reuse reason is recorded |
| **C-T8 (V3-AT-23)** | C5 | Wardrobe continuity spans episode boundaries (per-episode StateEvents + resolver continuity); canonical setting IDs agree across plan/assignment/resolver; timed changes resolve immediately before/at/after boundaries |
| C-T9 | C6 | Catalogue: two sources merge without deleting operator rows (NULL-speaker rows deduplicated); >90-day and unconfirmed-V4 flags; community voices excluded without per-voice approval, included with it; shortlist = top-3 with reasons (flagged thin on <ε gap; **fewer-than-2 → flagged, 1 shown**), **no audio generated** |
| C-T10 (V3R-1) | C7 | Hostile uploads: traversal, absolute paths, links, duplicate slots, unknown keys, oversized requests/zips, long decodes, processing-timeout rejection — all rejected pre-extraction/post-decode as specified; **failed imports never overwrite accepted assets; QUARANTINED rows survive a restart and are re-scanned** |
| C-T11 (V3R-2) | C7 | Only the normalised PCM WAV registers and passes **C's profile check (the validator of record, extending `references/media.py`; ffmpeg isolated)**; both hashes kept; attestations labelled separately from machine checks; a base-voice change invalidates the clip |
| **C-T12 (V3-AT-33), provenance half** | C9 | **Every member asset has a complete `ProvenanceRecord` (a gap blocks lock)** |
| **C-T12 (V3-AT-33), inspection half** | C10 | **Output inspection catches injected on-frame text, branding and likeness findings** (fixtures; likeness against the current selected candidate set; human-check fallback recorded where no detector is qualified) |
| **C-T13 (V3-AT-5/6/22)** | C9 (+C9b) | **The lock transaction: Approve is refused until every required item is resolved (typed list) and every speaker has a registered, rights-approved neutral clip; the hash covers every picked version + derived + voice preimage (any member change alters it); stale descendants cannot freeze; every episode row is stamped; an extension episode created after lock attaches (adopt-if-present, R-12.1); C9b — import copies with lineage and revalidates rights** |
| C-T14a | C2 | Forecast: volume from the pinned 3-candidate batch; capacity line shown; **unknown `image_price` ⇒ the panel and the CAST LOCK forecast condition read BLOCKED, no estimate**; setup proposal present before any paid work |
| C-T14b | C3 | Budget: admission through `step_04`/`SEASON_SETUP` in phase-A §5.2 order; no paid work before the setup approval; re-rolls counted |
| C-T14c | C8 | **Unknown SFX/YuE2 terms, capability or price ⇒ ineligible and blocked** (never zero-priced); chosen route persisted; the fake adapter's unit counts match the note |
| C-T15 | C11 | Tab 4 screens: every state in §12; one primary action per screen (**Pick** on the grid); `picks.waiting` emitted once per category activation |

## 15. Open questions and decisions

Two items are **OPEN (OPERATOR)** — they are *not* resolved by this spec:

| # | Question | Status |
|---|---|---|
| **O-C1** | **API V2 vs Studio V4 neutral clip** (DECISIONS: "decide before phase C"). T031's evidence clips are V4 (the S05/S06 scenario runs — [T031-authorization-packet.md](../T031-authorization-packet.md)); the public API serves only V1/V2. | **OPEN (OPERATOR)** — needed before C6/C7 build. Recommendation: keep the **manual Studio upload** as the only P0 intake; run the Thai-listener V2-vs-V4 comparison; if V2 qualifies, an API-generation path can later feed the **same** normalisation/assessment intake unchanged |
| **O-C9** | **V1 lock carve-out:** V1 `create_episode` sets no lock and `attach_identity_lock` stays unused for V1 — permanent? | **OPEN (OPERATOR)** — the R-12.1 fix covers V3 paths only; making the V1 carve-out permanent needs the operator's nod (Opus Monday) |

Decisions recorded (were open in v0.1):

| # | Question | Decision |
|---|---|---|
| O-C2 | B's pack expresses per-scene wardrobe only; master §4.4.3 requires mid-scene timed changes | C's operator-planned timed events (citing an allowing beat/scene break, per B §6.2's evidence rule) cover it; **flagged to the orchestrator** whether B §2.1 grows a `wardrobe_change` beat annotation in a B revision — recorded, not resolved here |
| O-C3 | Setup sub-budget value (O-6) | Propose from the forecast arithmetic (image volume × price + libraries); default **US$30** (A2's default) until the first real forecast; operator approves on the cast overview screen |
| O-C4 | Nano Banana per-image price unknown (`UNVERIFIED`) | **Block, don't estimate:** live dispatch refused (fail-closed) **and** the forecast/gate read BLOCKED (price unverified) until the operator supplies the measured price; the fake path is unaffected (§3) |
| O-C5 | Lock-file ownership/placement for cross-system interop | Keep **ARISA's inode** as the one canonical lock (pinned in `provider_qualifications`, §5); Drama binds the same path read-only; ARISA-side adoption is coordinated with the ARISA owner (prerequisite for live jobs, outside C's offline acceptance) |
| O-C6 | Extras: pick one of 2–4 looks, or keep a look pool? | **Decided:** generate 2–4, **pick one** look per role as its reference (master §4.4.1 lists extras looks as required human picks). **"Discarded at lock" defined:** losing candidates stay as `reference_versions` rows (excluded from lock membership); nothing is deleted or unregistered |
| O-C7 | Fairness numbers (batch size / hold time / retry) | Defaults 8 images or 120 s per hold (submit-through-final-poll), `retry_after` 20 s (mirrors ARISA); config-owned, re-measured by P0 (master §10.4) |
| O-C8 | Should the C7 trust-boundary note be Codex-critiqued before code? | **Yes — C7 is pre-critique, note first** (§13; definitive, in C7's definition of done) |

## 16. Requirement trace

| R-ID | Where |
|---|---|
| R-4.1 | §3 (packages by tier), §5 (castkit face lock), §9 (expression set inspection) |
| R-4.2 | §6 (plan, timed changes, resolver wiring — the R-4.2 gap closed for V3) |
| R-4.3 | §6 `AppearanceStateV3` |
| R-4.4 | §6 props; §3 pick items |
| R-4.5 | §6 locations + coverage |
| R-4.6 | §7 (as superseded by D2 refined/revised-again: Botnoi manual neutral, not ElevenLabs Voice Design) |
| R-4.7 | §3 `EXTRAS_LOOK` (recurring roles already promoted by B §4.2) |
| R-4.8 | §4, §12 (votes, re-roll, lock; SFW-picks behaviour) |
| R-4.9 | §8 |
| R-4.10 | §5 (Q8: `gemini-nano-banana-2.1` = "Nano Banana Pro"; shared quota + one process) |
| R-4.11 | §4, §12 |
| R-12.1 | §1.9, §8 (R-12.1 fix; C-T13) |
| R-12.2 | §6 (records + pre-render validation; QA-after is D's) |
| R-12.3 | §3 `EXTRAS_LOOK` items (the extras pool) |
| R-12.4 | §9 (provenance), §7 (rights), §9 SFX terms |
| R-12.5 | §8 season-2 import (C9b) |
| R-12.9 | §9 output inspection + B's originality checks upstream |
| R-12.7 | A-owned (budget steps); **C consumes** `step_04` (§1.7) — no C-owned row |

**Findings resolved here:** V3C-6 (§8), V3C-8 (§4), V3C-10 (§6), V3C-19 (§5), V3C-20 (§9, C8 note),
V3C-33 (§9), V3R-1 (§7), V3R-2 (§7), V3R-9 (§9 SFX qualification), V3R-11 (§7), N7 (§7/§8 — C supplies
the neutral binding D consumes), N13 (§7), N16 (§9), N23 (§4), N30 (§1.10, §6), O-6 (§3, O-C3), O-9
(§9), O-10/O-11 (§7).

## 17. Risks and limits (B §15 convention; master §18)

| Risk | Limit / mitigation | Owner |
|---|---|---|
| Lock starvation / ARISA contention on the shared Vertex process | fairness bounds (≤8 ops or ≤120 s per hold), `retry_after` 20 s, waits visible through `track_waits`; P0 re-measures | Operator (pacing) |
| ARISA-side lock adoption is a prerequisite for live images | offline acceptance simulates the competitor (C-T5/C-T6); live dispatch stays disabled until adoption + qualification | Operator / ARISA owner |
| An ARISA deploy replaces the lock file (inode swap) silently breaking mutual exclusion | inode pinned in `provider_qualifications`; `fstat` on every acquisition; typed BLOCKED on mismatch (§5) | C3 builder |
| Botnoi catalogue drift (API fields/shape change) | importer fixture-tested against the verified header; `last_verified` flags; the operator-CSV path is independent | C6 builder |
| Tag vocalisation leakage into Pika output | pilot observation (master §4.4.4 8); tags are options only; tag-free fallback is one decision | F (observation), C (sheet options) |
| Hostile upload bytes (the phase's only untrusted surface) | quarantine prefix in the object store, isolated ffmpeg decode, bounded limits, C-T10 | C7 builder |
| `OPERATOR_ATTESTED` legal exposure (no licence document) | basis stored verbatim + territories WORLDWIDE; the attestation is the operator's, never implied by machine checks | Operator |
| Quarantine retention (untrusted bytes accumulate) | quarantine objects retained until `SUPERSEDED`/`REJECTED` + a bounded cleanup window (C7 note pins the number) | C7 builder |
| Human-check burden while detectors are unqualified (O-2: likeness, OCR, branding, vocal leakage) | recorded human checks batched at the picks/CAST review; no detector plumbing before detectors exist | Operator |
| Forecast built on `UNVERIFIED` throughput/price | panel labels "estimated"; unknown price blocks the gate rather than estimating (O-C4) | Operator (supplies measured price) |

Master-level risks and their owners: master §18 (Joey licence, quota terms, throughput SLO).

## 18. Alternatives rejected (B §16 convention; one per major design choice)

| Choice | Rejected alternative | Why rejected |
|---|---|---|
| Reuse `identity_locks` + `identity_lock_assets` for CAST LOCK | A new cast-lock table family | master §4.4.5 mandates the identity-lock readers; a second lock family would fork Gate 2 authority and D's consumers |
| `flock` on the shared inode | A Postgres advisory lock for cross-system mutual exclusion | ARISA already flocks this inode (FM §8); an advisory lock needs ARISA-side adoption to be mutual at all — two mechanisms, one winner: the existing one |
| Append-only `cast_pick_votes` (latest vote = selection) | A mutable selection column on the item | master §4.4.1: "a pick records a vote only"; a selection column loses history and races concurrent operators |
| Derived acceptance = bulk-appended session-marked votes | A second acceptance state machine | one mechanism, two policies (§4); a second machine would drift from the vote/projection rules |
| Zip bulk import beside single upload | Single-file upload only | ~one neutral clip per speaker across a 20–30 episode season; per-file uploads are operator-hostile (master §4.4.4 4 mandates the zip path) |
| Adopt-if-present at insert + stamp-at-lock (split by episode kind) | Auto-adopt every episode at insert | episodes at STORY LOCK exist before any lock (verbatim auto-adopt raises `IdentityLockRequired` on every creation, `service.py:294–299`); the split keeps both paths honest (§1.9) |
| New `v3_cast_documents` table | Extending B's `v3_story_documents` | cast documents are C-guarded with a different `contract_type` allowlist; B's store is story-scoped and B-owned (mirrors B's own O-B6 rejection) |
| Computed dependency closure over `cast_pick_items` | A persisted `cast_dependency_edges` table (v0.1's `C-3`) | both edge kinds derive from `parent_pick_id` + `pick_kind`; a second persisted graph only drifts (MAJ-6) |
| Three queue lanes (`image`, `voice_intake`, `media`) | Four lanes (music and SFX separate) | each library is ~1 job/season with the same admission profile; separate lanes are CHECK/worker sprawl (N42) |
