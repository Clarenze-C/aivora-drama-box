# Phase B: Story (Script Maker → LOCK → bible → episode packs → STORY LOCK)

**Version 0.2, 12 Nov 2026** (v0.1 11 Nov; v0.2 records the operator's answers to O-B1..O-B6). Author: Opus orchestrator.

**Status: DRAFT for Codex critique (round 1),** after the Codex week resets (13 Nov 10:30Z).

**Master:** [SPEC-v3.md](SPEC-v3.md) v0.4.4. **Depends on:**
- [phase-A0-spec.md](phase-A0-spec.md) v0.4: `LlmStep`, the gateway and quota admission;
- [phase-A-spec.md](phase-A-spec.md) v0.3: gates, tracks, the decision transaction, budget, the fence;
- [A1-design-note.md](A1-design-note.md) v1.2: migrations 0028–0031 and the command table;
- the A2 and A3 design notes (being drafted).

**Facts:** [b-factmap.md](b-factmap.md) (GLM-Flash, 11 Nov; the orchestrator spot-checked six claims and
corrected one line number). Code references are relative to `microdrama/src/microdrama/` (`S/`);
migrations `M/`; tests `X/`.

**Owns:** V3-AT-3, 4, 18, 19 and R-1.1..R-1.4, R-2.1..R-2.5, R-3.1..R-3.6 (master §15).

---

## 0. Scope

**Phase B builds tabs 1–3 of the stepper and their two gates:**
1. **Script Maker:** Mode B (one-line title) → 2–3 proposals → **LOCK** (Approve / Revise / Reject).
2. **The bible** (`SeasonBibleV3`), character profiles with **tiers**, and the secret and season ledgers.
3. **The episode builder:** every episode as a full `EpisodePackV3`, in order, with a running continuity
   state, a critic per episode and a season critic → the **demand list** → **STORY LOCK**.

**Also in B:**
- Mode A is visibly disabled with a reason.
- The V3 duration and count validators, done as version-selected validation.
- Compatibility readers.
- All planned episode rows are created at STORY LOCK.
- The extension seam, and activating the `create_extension` command (A1 ruling OQ-1).

**Not in B:**
- **C:** asset generation, picks, `CastBinding`/`CastLock`, the voice shortlist and the image-volume
  projection.
- **D:** shots and the shot compiler.
- **F:** the extension decision screen, viewership windows and calendar integration.
- **The live metered LLM adapters,** which come after the pilot decision (O-5).

## 1. Binding decisions

1. **V1 and V2 validators never change** (AT-19, V3C-5; the same rule as phase A §1 and AC-1).
   - The master's "every duration and count validator is replaced consistently" is met by **V3 records
     with their own validators**, selected by `seasons.workflow_version`.
   - The V1 models stay frozen at contract 1.15.0 and the V2 models at 2.15.0, unchanged:
     `SeasonScope`, `EpisodePlan`, `Script`, `EpisodePack`, `ConceptIntake`, `ConceptCandidate`,
     `ProductionLimits` (`S/contracts/primitives.py:59`).
   - Historical records keep validating under their own schema, with their own 180–300 s and 1–10 rules.
2. **V3 story code lives in new modules** (`S/story_v3/`). The existing `S/story/` and `S/research/`
   modules are unchanged.
   - V3 code may **import** their pure functions: the secret-leak check, `estimate_line_ms`, canonical
     hashing and the injection-resistant prompt framing.
   - It never calls their services or writes their tables.
3. **Every V3 LLM call is an `LlmStep`** (master §10.1; A0 §5.1) inside its owning job.
   - The synchronous `LLMProvider` (`S/contracts/providers.py:152`) is never used by V3 code.
   - Pilot calls use the unmetered `llm.subscription` kind, so **phase B makes no reservation and posts no
     charge**.
   - **When a metered LLM adapter ships (O-5),** B's calls reserve under the step keys `script_maker`,
     `bible` and `episodes` (A2 §5.2). B builds the `step_key` plumbing; it does not build the adapter.
4. **Planning authority is the approved LOCK, never STORY LOCK** (V3C-4).
   - The writer reads **no** asset, wardrobe-assignment, identity-lock or voice table.
   - Packs reference **logical demand IDs** (§4), which step 4 binds in `CastBinding` (C).
   - The V1 IMP-01 gate (`S/story/service.py:788`, `IdentityLockRequired`) stays in the V1 writer and is
     not reachable from V3.
5. **Every pack is full.** The T039 rule `scoped_map_only = episode_number > 3`
   (`S/story/script_maker.py:818`) has no V3 equivalent, and `EpisodePackV3` has no map-only field
   (R-3.1).
6. **"≤2 speakers per shot" is enforced at pack level on beats** (AT-3 interpretation).
   - Packs have no shots; D compiles them.
   - A **beat** is the smallest unit D may split into shots and **never merges with another beat**.
   - Each beat has **at most 2 distinct speakers**, so every shot D compiles from it does too. D re-checks
     per shot.
7. **Gates open only when their step's work is complete.** A gate is never open while that step's jobs
   are queued or running, so a decision can't race its own regeneration. Amendment-driven staleness is
   A3's fence.

## 2. Records (contract package, guardian-owned bump)

All V3 story records are **append-only documents** with these properties:
- `record_id`, `version`, `content_sha256` (canonical hash of the payload), `schema_version = '3.0'` and
  timestamps;
- the same sealing and verification rules as `V2Record` (`S/contracts/v2.py:45–85`).

They are stored in a new table **`v3_story_documents`** through `StoryV3Store`, which mirrors
`StoryV2Store` (`S/story/v2_store.py:17`):
- `PRIMARY KEY (contract_type, record_id, version)`;
- one `current` row per `(contract_type, record_id)`;
- consecutive versions;
- the hash is re-verified on read;
- the standard guards (no delete, no truncate, integer-only numbers);
- a `contract_type` allowlist CHECK.

`v2_contract_documents` is not touched.

**Identity:** `record_id = uuid5(STORY_V3_NS, "<type>:<planning_scope_id>[:<key>]")`.
- `planning_scope_id` is the season ID, or the extension ID (§8).
- Regeneration **advances the version and keeps the ID**, the V2 convention
  (`S/story/script_maker.py:70`).

| Record | Key | Content |
|--------|-----|---------|
| `ConceptIntakeV3` | `intake` | `mode` (`TITLE` only; `TREND` refused, §3.1), `idea_line` (1–300 chars), optional genre/tone hints, `requested_episode_count` (20–30, default 24), `language = "th"`, `original_fiction = true` |
| `ProposalRoundV3` | `proposals` (versions = rounds) | `round` (1, 2, …), 2–3 `SeasonProposalV3`, the revision-note refs that produced the round (none for round 1) |
| `SeasonProposalV3` (embedded) | `proposal_id` stable per round slot | the master §4.1 fields: title TH/EN, logline, premise, thesis question, genre/tone, `episode_count` (20–30), `target_length_ms = 120_000`, main cast briefs (3–6), season promise, escalation shape, ending, **extension seam sketch**, why it would trend, originality and rights notes |
| `SeasonBibleV3` | `bible` | the Joey sections **in order** (master §4.2); the camera package (look: spherical or anamorphic, lens family, movement register), palette, lighting language, pacing rule; `characters[]` (`CharacterProfile`); `extras_roles[]` (`ExtrasRole`); the secret ledger; the season ledger; `tbd[]` (field path + reason) |
| `CharacterProfile` (embedded) | `character_key` | `tier`; narrative function; visual lock (text); backstory; psychology by story state; speech (register, texture, cadence, Thai politeness and pronouns, code-switching); movement; stillness; drift exclusions; goal, strategy, flaw, secrets; **voice descriptor** (gender, age band, pitch, timbre, pace, accent/dialect, emotional baseline), required when the character speaks |
| `EpisodePackV3` | `episode:<n>` | §2.1 |
| `ContinuityStateV3` | `continuity:<n>` | the state **after** episode *n*: per character, outfit + appearance states + location + known secrets + end psychology; per prop, holder + state; the story clock; **the wardrobe history by story day** |
| `CriticReportV3` | `critic:<episode n \| season>` | findings with severity, rule ID, the target (pack/scene/beat/line) and evidence; per-episode and season reports |
| `SeasonDemandListV3` | `demands` | §4 |
| `ExtensionSeamV3` | `seam` | threads: `thread_id`, description, the open payoffs it may grow, constraints that must hold to keep the ending; built with the bible and **bound at STORY LOCK** |
| `StoryLockBindingV3` | `story-lock:<content_revision>` | the hashed set STORY LOCK approves (§5.4) |

**Reused shapes:**
- The secret ledger and season ledger reuse the V2 shapes `SecretEntry` (`S/contracts/v2.py:276`),
  `PayoffDebt` and `SeasonEscalation` (`:218`), embedded as V3 models with the same validators.
- `validate_season_story_ledger` (`:242`) gets a V3 sibling that binds the ledger to the bible, the packs
  and the LOCK authority.

### 2.1 `EpisodePackV3`

| Field | Rule |
|-------|------|
| `planning_scope_id`, `episode_number` | identity before rows exist; `episode_id` is bound only at STORY LOCK (§5.4) |
| `lock_authority` | the approved proposal's `content_sha256` + the LOCK approval event ID (V3C-4) |
| `titles` TH/EN; `synopsis` | required |
| `recap_plan` | the beats recalled from the previous episode, with `estimated_ms ≤ 10_000`; **empty for episode 1** |
| `scenes[]` | each: `scene_id`; `story_time` (story day, local time `HH:MM`, setting: reusing `StoryTime`, `S/contracts/v2.py:284`); `location` (demand ID + **light state**); `visible_cast[]` (character demand ID or extras-role demand ID, with framing `RECOGNISABLE` or `BACKGROUND`); `props[]` (prop demand ID + holder character ID or none + state ID); `wardrobe[]` (for **every** visible character: outfit demand ID + appearance-state IDs); `beats[]` |
| `beats[]` | each: `beat_id`, text, `planned_hold_ms` (non-dialogue screen time), `line_ids[]`, `reveals[]` (secret IDs), **≤2 distinct speakers** (§1.6) |
| `cliffhanger_beat_id` | a beat of the last scene |
| `lines[]` | each: `line_id`, `beat_id`, `speaker` (character demand ID), `off_screen` (bool), `text_th`, `text_en`, `text_zh`, **`emotion`** (closed enum, §2.2), `delivery_note` (≤200 chars), `estimated_ms` (from `estimate_line_ms`, `S/story/prompts.py:367`), `critical_terms[]` (the V1 shape) |
| `cta` | `template_id` + an intent line, `estimated_ms ≤ 5_000` |
| `psychology[]` | for each principal or supporting character who appears: start state + end state |
| `promise`, `payoff_debt`, `escalation` | as the V2 pack (`S/contracts/v2.py:353`) |
| `duration_target_ms` | `120_000` |
| `estimated_runtime_ms` | Σ line `estimated_ms` + Σ beat `planned_hold_ms` + recap + CTA; **must lie in 105_000–135_000** |

**Absent by design:** `scoped_map_only`; asset IDs; wardrobe-assignment IDs; voice IDs; `actual_duration_ms`.
Those are bound later, in C (cast) or measured in D/E (durations).

### 2.2 V3 limits and vocabularies (`V3ProductionLimits`, V3 records only)

| Rule | Value | Source |
|------|-------|--------|
| Episode count at LOCK | 20–30 | master §4.1 |
| Episode length | target 120 s, band 105–135 s, including recap ≤10 s and CTA ≤5 s | master §4.1 |
| Distinct speakers per episode | ≤5, counting off-screen speakers | MA19, O-12 |
| Speakers per beat | ≤2 | §1.6 |
| Main cast briefs per proposal | 3–6 | v0.1 §4.1 |
| Active locations per episode | **3** (O-B1, decided 12 Nov) | — |
| `emotion` | `NEUTRAL`, `HAPPY`, `SAD`, `ANGRY`, `FEARFUL`, `SURPRISED` (O-B3, decided 12 Nov) | DECISIONS D2 revised (e.g. neutral, happy, sad, angry) |

Each line's `emotion` drives a voice demand (§4). Every distinct (speaker, emotion) pair becomes one
**manual Botnoi V4 upload** by the operator (DECISIONS "D2 refined"), so the vocabulary size is a labour
decision.

### 2.3 Field mapping, readers and the consumer order (V3C-5)

**Mapping** (master §4.3; the B1 design note extends this to every field of the three source models,
with `file:line`: each field is mapped, dropped with a reason, or V3-new):

| V3 | V1 `EpisodePlan` / `Script` (`S/contracts/season.py:313`, `:366`) | V2 `EpisodePack` (`S/contracts/v2.py:353`) |
|----|------------------|-----------------|
| scope + number; `episode_id` bound at STORY LOCK | `episode_id`, `episode_number` | `episode_id`, `episode_number` |
| `lock_authority` | `approved_scope_hash` | `approved_scope_hash` |
| titles, synopsis | `titles`, `synopsis` | — |
| scenes: story time, location + light | `location_ids` (episode level) | `EpisodeScene` `StoryTime`; location **asset** IDs → **logical** demand IDs |
| visible cast, extras, framing | `featured_character_ids` | `visible_character_ids` (`:314`) |
| props, wardrobe | — | prop and wardrobe-**assignment** IDs → logical outfit + appearance-state demands |
| beats, reveals, cliffhanger | `planned_beats`, `planned_reveals`, `cliffhanger` | `PackBeat` (`:297`) |
| lines: TH/EN, estimate, critical terms | `Script` `DialogueLine` (`:346`) | — |
| lines: ZH, emotion, delivery, off-screen | — (NOT FOUND today) | — |
| recap, CTA | — | — |
| psychology start/end | — | `character_logic` / `knowledge_by_episode` |
| promise, payoff, escalation | — | same fields |
| duration 105–135 s | `target_duration_ms` 180–300 s | `duration_target_ms` 180–300 s |
| — (dropped) | `voice_id`, `actual_duration_ms`, `canon_version` | `scoped_map_only` |

**Readers:**
- `read_episode_story(tx, episode_id)` returns a version-tagged view: `V1(EpisodePlan, Script)`,
  `V2(EpisodePack)` or `V3(EpisodePackV3)`. Each record is validated under its own schema version.
- It reuses `read_v1_manifest` (`S/contracts/v2.py:1029`) where it applies.
- **A V1 or V2 consumer given a V3 episode raises `WORKFLOW_MISMATCH`** (phase A §1).

**Consumer order.** B migrates **no** consumer. They move to the V3 reader in the phase that owns them:
1. **D:** `story/directing.py:101`, which is replaced by the single shot compiler;
   `references/v2_planning.py` and its binding/dispatch modules; `rendering/routing.py`;
   `qa/continuity_sources.py`.
2. **E:** `editing/edl.py`, `editing/captions.py`, `editing/service.py`.
3. **F:** `review/packages.py`, the progress views in `review/intake.py`, `community/grounding.py`.

**A B test enumerates these modules** and proves that each refuses V3 input until its phase registers a
V3 path.

## 3. Step 1: Script Maker → LOCK

### 3.1 Intake

- **`submit_v3_intake(idea_line, hints, requested_count)`:** human session + CSRF + idempotency key.
  1. Calls `create_v3_season` (A2; it returns `NOT_AVAILABLE` until A2 ships).
  2. Writes `ConceptIntakeV3`.
  3. Enqueues `story_v3.propose` (round 1).
  4. Advances planning `IDEA → PROPOSED` when the round is written (§3.2).
- **Mode A:** the intake form shows **Trend research: disabled** with the reason (master §4.1, V3C-32).
  - A `TREND` intake is refused with `MODE_UNAVAILABLE` before any write.
  - The research code (`S/research/service.py:313`) stays V1-only behind the `require_workflow` guards
    (A1 note §7).
- The V1 wizard (`S/review/intake.py:676`) is unchanged and creates only V1 seasons.

### 3.2 Proposal job `story_v3.propose`

- **One `LlmStep`** (role: Opus; see O-B4) produces 2–3 materially distinct interpretations as
  `SeasonProposalV3`. Round *k* > 1 carries the revision notes.
- **Validation:** schema, then the V3 limits, then originality and rights notes present, then no real
  people, brands or celebrities named. The name check is deterministic, against the existing
  originality helpers (`S/research/originality.py`); output inspection proper is phase C's (§12.2).
- **Invalid output:** a retry with a new `logical_call_id`, at most 2. Then the job fails → `BLOCKED
  (failed)` with a retry action.
- **On success, in one transaction:**
  1. write the `ProposalRoundV3` version;
  2. `open_gate(SEASON_CONCEPT, season, binding = canonical_hash({round record_id, version,
     content_sha256}))`;
  3. `advance_planning(PROPOSED)` (round 1 only).

### 3.3 LOCK decisions (the B handler for V3 `SEASON_CONCEPT`)

| Action | Conditions (evaluated in the A1 decision transaction) | Effect in the same transaction |
|--------|-------------------------------------------------------|--------------------------------|
| **Approve** `target = {kind: proposal, id}` | the target is in the bound round; `episode_count` is 20–30 | record the approval; **LOCK authority** = the proposal's `content_sha256` + the event ID; `PROPOSED → LOCKED`; enqueue `story_v3.bible` |
| **Revise** + notes (`season_revision_notes`, ≥1; targets: the round, or specific proposals) | the activation is open | the activation closes; enqueue `story_v3.propose` round *k*+1. A targeted note regenerates only the targeted proposal slots; the others are carried **byte-identical**. Planning stays `PROPOSED`; the job opens the next activation |
| **Reject** | — | A1 note §6: no concept authority; planning stays `PROPOSED`, and the operator may submit a new intake or Revise later. **The season is never cancelled by a Reject** |

The handler is **registered only in compositions where phase B has shipped.** Before that, V3 LOCK
returns `NOT_AVAILABLE` (A1 ruling OQ-5).

## 4. Step 2: bible, tiers and the demand list

### 4.1 Bible job `story_v3.bible`

1. **One `LlmStep` (Opus)** writes `SeasonBibleV3` + `ExtensionSeamV3`, given the LOCK authority, the
   approved proposal and the Joey method digest (`joey-digest.md`; internal method only, no
   redistribution: master §18).
2. **The deterministic bible critic** (§6.1); then **one LLM critic pass** (Opus, O-B5) for drift,
   thesis coherence and density.
3. **Repair:** at most 2 regenerate rounds, each carrying the critic findings. A `[TBD]` in a
   render-required field (the camera package; a character's visual lock or voice descriptor if they speak;
   the locations' light language) is **CRITICAL**.
4. **Success:** `LOCKED → BIBLE`; enqueue `story_v3.plan_episode(1)`.

The bible is reviewed at STORY LOCK, not at its own gate (master §2). Progress (R-2.5): one generation job
plus one critic pass.

### 4.2 Tiers and speaker counting (deterministic, `S/story_v3/tiers.py`)

- **The initial tier** comes from the bible: main cast are `PRINCIPAL`; named non-principals are
  `SUPPORTING`; background roles are `EXTRA` (`ExtrasRole`).
- **Promotion after all packs exist:** a non-principal becomes `SUPPORTING` if it
  - appears in ≥2 episodes, or
  - has any line, or
  - is framed `RECOGNISABLE` in ≥2 scenes.

  An off-screen speaker is always at least `SUPPORTING` (N22). A promoted extras role becomes a
  `CharacterProfile` with a lighter, LLM-completed profile (speech + voice descriptor only if it speaks),
  through one `LlmStep` per promoted role.
- **Operator tier edits at STORY LOCK:** `edit_tier(character_key, tier)` (human session).
  - It **closes the open STORY LOCK activation**.
  - It re-runs promotion validation, demand derivation and the season critic's deterministic checks.
  - It opens a new activation.
  - **Overrides never waive** speaker counting, the voice requirement or identity coverage (V3R-4): a
    demotion that would leave a speaker without a voice demand, or a recognisable character without an
    identity demand, is refused.

### 4.3 The demand list (`SeasonDemandListV3`, deterministic)

Derived from the bible + all packs after the season critic passes. One `LogicalDemand` per item:

| Kind | Logical key | Carries |
|------|-------------|---------|
| `CHARACTER` | `character_key` | tier; identity coverage required (`PRINCIPAL`/`SUPPORTING`, or any `RECOGNISABLE` framing) |
| `OUTFIT` | `character_key` + `outfit_key` | the story days worn |
| `APPEARANCE_STATE` | `character_key` + `state_key` | (e.g. injured, wet) |
| `PROP` | `prop_key` (+ `state_key`) | holders by scene; proof-prop flag |
| `LOCATION` | `location_key` + `light_state` | the local times used |
| `EXTRAS_ROLE` | `role_key` | framing |
| `VOICE` | `character_key` | **the set of emotions its lines use** (§2.2) |

- `demand_id = uuid5(STORY_V3_NS, "demand:<planning_scope_id>:<kind>:<logical key>")`, so it is **stable
  across revisions**. A Revise that keeps an item keeps its ID, which `CastBinding` (C) relies on.
- **Every item lists the episodes and scenes that use it** (AT-4).
- **The pack references and the demand list are checked both ways:** every reference in a pack resolves
  to a demand, and every demand is used at least once.
- **The STORY LOCK screen shows the demand counts by kind and tier.** The step-4 cost forecast and the
  image-volume projection are phase C's. Until C ships, that panel shows `NOT_AVAILABLE`.

## 5. Step 3: episodes → STORY LOCK

### 5.1 Episode job `story_v3.plan_episode(n)`

- **One job per episode, in order** (logical work ID `plan:<planning_scope_id>:<n>`). Each carries:
  - the LOCK authority;
  - the bible version;
  - `ContinuityStateV3(n−1)`: the bible's initial state for episode 1;
  - `expected_content_revision` (A3).
- **Steps:**
  1. **The architect `LlmStep` (Opus)** writes the pack (TH + EN), given the bible, the seam, the
     previous state and the season plan.
  2. **The translation `LlmStep` (Sonnet; master §10.1 roles)** adds `text_zh` and checks EN.
  3. **The deterministic episode critic** (§6.1).
  4. **Optionally, one LLM episode critic** (O-B5).
- **Repair:** at most 2 regenerations, carrying the findings, then the job fails → `BLOCKED (failed)`.
- **On success:**
  1. write the pack version and `ContinuityStateV3(n)`;
  2. enqueue `plan_episode(n+1)`, or, after the last episode, `story_v3.season_critic`.
- **Progress (R-3.6):** *n*/N episodes planned, then the critic checks.
- **Crash and replay:** a frozen call is resumed by its `logical_call_id` (A0), so a crash never calls
  the model twice for one attempt. A completed episode is never re-planned by replay (semantic key per
  `(scope, n, LOCK authority, bible version)`).

### 5.2 Season critic `story_v3.season_critic`

1. **The deterministic season checks** (§6.2).
2. **One LLM season critic (Opus):** character drift against the drift exclusions, psychology resets, a
   weak escalation, payoff timing.
3. **Repair:** for findings that name packs, at most 2 rounds. A repair round re-plans the **earliest**
   named episode and every later episode whose continuity input changed (§5.5).
4. **Then:**
   1. tier promotion (§4.2);
   2. the demand list (§4.3);
   3. `StoryLockBindingV3`;
   4. `open_gate(STORY_LOCK, season, binding)`;
   5. `BIBLE → PLANNED`.

**If CRITICAL findings remain after repair,** the gate still opens, so the operator can see and Revise,
but **Approve's condition fails** while any CRITICAL is open.

### 5.3 STORY LOCK decisions (the B handler for `STORY_LOCK`)

| Action | Conditions | Effect in the same transaction |
|--------|-----------|--------------------------------|
| **Approve** | no open CRITICAL; the binding is current; the tier revalidation passed; **the A2 STORY LOCK budget step succeeds** (A2 §5.1: the `SEASON` account + setup attachment + episode accounts fit the base cap) | record the approval; call **`create_v3_episodes(season, N)`** (A2), which creates **all N episode rows** independently of the release cadence (AT-18); write `v3_episode_story_bindings` (§5.4); `PLANNED → STORY_LOCKED`; `content_revision` bumps (A1). Step 4 starts when phase C's handler is registered |
| **Revise** + notes (targets: `episode:<n>`, a bible section, the seam, or a tier) | the activation is open | the activation closes. **Only the noted units regenerate:** noted packs via `plan_episode(n)`, bible sections via a scoped `story_v3.bible` call. Then the closure revalidation (§5.5) and the season critic run, and the gate reopens with a new binding |
| **Reject** | — | A1 note §6: no episode-creation authority; planning stays `PLANNED` |

**The STORY LOCK screen (R-3.5):**
- the bible;
- every episode's outline (synopsis, scenes, cliffhanger, reveals);
- the critic findings;
- the demand counts;
- tier controls;
- Approve, or Revise with notes per episode or per section.

### 5.4 Episode binding

- **`v3_episode_story_bindings`:** `episode_id`, `season_id`, `episode_number`, `pack_record_id`,
  `pack_version`, `pack_sha256`, `story_lock_approval_event_id`, `content_revision`.
  - It is append-only and guarded, with `UNIQUE(episode_id, content_revision)`.
  - Later amendments (A4) add rows at the new `content_revision`. The current binding is the row at the
    episode's current `content_revision`.
- **`StoryLockBindingV3`** hashes:
  - the bible (record ID, version, sha);
  - every pack in episode order;
  - the demand list;
  - the seam;
  - the tier table;
  - the critic reports.

  **That hash is the activation binding** (phase A §2.5).
- **V3 episodes keep legacy `episodes.state = PLANNED` and an empty `episodes.plan`** (phase A §1).
  `_w03_episode_cadence` (`S/scheduling/service.py:199`) never selects V3 seasons (A1 note §7 guards).

### 5.5 Closure revalidation after a Revise or repair

1. Regenerate the noted packs.
2. **Re-run the deterministic continuity check forward** from the earliest regenerated episode, against
   the stored later packs.
3. A later pack that no longer satisfies its continuity input becomes an **invalid dependent**: a
   CRITICAL finding `continuity-dependent` naming the episode.
4. **Invalid dependents are not regenerated silently.** The STORY LOCK screen lists them with one
   "Revise these too" action, which is the scoped revision authority of master §2.1. Approve stays blocked
   until none remain.

## 6. Critics (deterministic rules; the LLM critics add findings, never waive these)

### 6.1 Bible and episode rules

| Rule | Severity |
|------|----------|
| schema, V3 limits, runtime band, recap ≤10 s, CTA ≤5 s | CRITICAL |
| every visible character has wardrobe (outfit + appearance states) in the scene | CRITICAL |
| every line's speaker is a known character, with TH/EN/ZH text and an emotion | CRITICAL |
| ≤5 distinct speakers per episode; ≤2 per beat | CRITICAL |
| a secret revealed or leaked before its `planned_reveal_episode` (the V2 normalized-substring check, `S/story/script_maker.py:540`) | CRITICAL |
| a `[TBD]` in a render-required field | CRITICAL |
| prop continuity: holder and state follow from the previous state or an on-page beat | MAJOR |
| a location's light state is plausible for its local time | MAJOR |
| missing cliffhanger beat; missing psychology entry for an appearing principal | MAJOR |

### 6.2 Season rules

| Rule | Severity |
|------|----------|
| **Impossible wardrobe day:** a character's outfit changes within one story day without a beat or a scene break that allows it, or contradicts the wardrobe history | CRITICAL |
| a payoff debt left unpaid at the finale, and not assigned to a seam thread | CRITICAL |
| a seam thread is resolved or closed in the finale | CRITICAL |
| the episode count differs from the LOCK authority | CRITICAL |
| an escalation step regresses | MAJOR |
| every pack satisfies §6.1 (a re-check against the final set) | as §6.1 |

**A CRITICAL finding blocks STORY LOCK Approve. MAJOR and MINOR findings are shown.** The LLM critics may
add findings at any severity but **cannot clear a deterministic finding.** This is the V1 principle in
`S/story/service.py`'s module docstring.

## 7. Jobs, LLM calls, fence and waits

| Job | Queue | `LlmStep` calls (role) | Logical work ID |
|-----|-------|------------------------|-----------------|
| `story_v3.propose` | the existing `PRODUCTION` queue (phase A adds no lanes) | 1 per attempt (Opus) | `propose:<scope>:<round>` |
| `story_v3.bible` | ″ | 1 + 1 critic (Opus) per round | `bible:<scope>:<lock authority>` |
| `story_v3.promote_profile` | ″ | 1 per promoted role (Opus) | `profile:<scope>:<character_key>` |
| `story_v3.plan_episode` | ″ | architect (Opus) + translation (Sonnet) (+ critic) per attempt | `plan:<scope>:<n>` |
| `story_v3.season_critic` | ″ | 1 (Opus) per round | `season-critic:<scope>:<binding inputs>` |

- **Every `FrozenLlmCall`** carries:
  - a pinned prompt ID and its sha256 (a prompt manifest, as `PromptManifest`, `S/contracts/v2.py:773`);
  - the inputs as **untrusted documents** (the existing injection-resistant framing,
    `X/unit/research/test_injection_resistance.py`);
  - the output schema.
- **A new content attempt gets a new `logical_call_id`; transport recovery reuses the old one** (A0 §5.1).
- **Waits:** `LlmDeferred` maps to `RETRY_WAIT` with `defer_reason` (A0). The track projects
  `WAITING_QUOTA` or `WAITING_PROVIDER` through `track_waits` (A1). An unreadable quota pauses production
  (master §10.1).
- **The fence:** every B job input carries `expected_content_revision`. A stale result is quarantined
  (A3 §7.1) and never written as the current pack.
- **Offline:** every B test uses A0's fake gateway / fake `LlmStep` adapter with scenario scripts
  (valid, invalid, refused, deferred, crash mid-call).
  - No B test calls `claude`, ai-route or the network.
  - **`make pilot` (V1) stays green and untouched.**

## 8. Extension seam and `create_extension`

- **`ExtensionSeamV3`** is written with the bible, revised at STORY LOCK, and **bound by STORY LOCK.**
- **`create_extension(season, range, calendar)`** activates in B (A1 OQ-1).
  - It checks eligibility: the season release is `RELEASING` or `COMPLETE`; the range lies beyond the
    current count; **an approved `SEASON` amendment covers the new count** (A2 §5.4).
  - It opens a `season_extensions` scope.
- **On an extension scope** (`planning_scope_id = extension_id`), the same builder runs: `plan_episode`
  for the new range, then the season critic, then STORY LOCK for the new packs only. Inputs:
  - the prior STORY LOCK's bible and seam;
  - the **planned-terminal canon** (the last stored `ContinuityStateV3`);
  - a **published canon** input.

  The prior approvals and packs are never touched.
- **Phase F owns** the decision screen, the viewership windows, the published-canon source and the
  calendar integration. **B tests the extension builder with a synthetic published canon.**

## 9. UI (tabs 1–3, built into the phase A shell, A5)

| Tab | Route | Scope | Progress denominator | Primary action |
|-----|-------|-------|----------------------|----------------|
| 1 Script Maker | `/v3/seasons/{id}/script` (`/v3/seasons/new` before a season exists) | season | the proposal job (one call per round) | **Submit** (intake); then the LOCK gate buttons |
| 2 Bible | `/v3/seasons/{id}/bible` | season | generation + critic pass (2 units) | none (reviewed at STORY LOCK); `Next` after completion |
| 3 Episodes | `/v3/seasons/{id}/episodes` | season | *n*/N packs, then season-critic checks | the STORY LOCK gate buttons |

**Every tab has these states** (master §3.2):
- **empty:** not started;
- **loading;**
- **running** n%;
- **waiting for you:** an open activation;
- **waiting for quota** ⏳ (with `retry_at`);
- **blocked** ⚠ (failed or reconcile, with the retry action);
- **error;**
- **done** ✓ or **locked** 🔒.

The Mode A option is shown disabled with its reason. Tier controls and per-episode Revise notes are on
tab 3.

## 10. Build packages (in order; `make check` + V1 `make pilot` green at every gate)

**Prerequisites:**
- A0;
- A1–A3 accepted;
- A5, for B6 only.

The migration numbers are allocated in the B1 note after re-auditing the tail. **Applied migration bytes
are never edited.**

| Package | Builds | Gate | Design note |
|---------|--------|------|-------------|
| **B1** | V3 records + `V3ProductionLimits` + vocabularies; `v3_story_documents` + `StoryV3Store`; `v3_episode_story_bindings`; readers + `WORKFLOW_MISMATCH` guards; contract bump (v3 schemas; V1/V2 artifacts byte-identical) | B-T1, B-T2 | **Critiqued first** (contracts and migration) |
| **B2** | Intake + Mode A refusal; `story_v3.propose`; the LOCK handler | B-T3 | With the diff |
| **B3** | `story_v3.bible` + the bible critic; tiers + promotion + `edit_tier` | B-T4 | With the diff |
| **B4** | `plan_episode` + continuity state + the episode critic + translation | B-T5, B-T6 | With the diff |
| **B5** | The season critic + repair + closure revalidation; the demand list; `StoryLockBindingV3`; the STORY LOCK handler + episode rows + bindings; `create_extension` + the extension builder | B-T7..B-T11 | **Critiqued first** (the lock transaction and the closure) |
| **B6** | Tabs 1–3 | B-T12 | With the diff |

**Routing:**
- GLM builds each package (`ai-route build -w`).
- Codex critiques the B1 and B5 notes, and reviews every package diff.
- One package at a time.

## 11. Acceptance (offline; real PostgreSQL for every transaction test)

| Test | Proves |
|------|--------|
| **B-T1 (V3-AT-19)** | Migration upgrade on a **populated V1 + V2 database**: every V1/V2 record still validates under its own schema, including historical 180–300 s and 1–10 values; recomputed hashes are byte-identical; no row is deleted or rewritten; the V1/V2 generated contracts show no drift |
| B-T2 | Version selection: V3 validators reject 180 s and 10-episode V3 records; V1/V2 validators unchanged (AST-identical source); every listed V1/V2 consumer refuses a V3 episode with `WORKFLOW_MISMATCH` |
| B-T3 | Mode A refused before any write; Mode B → 2–3 proposals. LOCK Approve/Revise/Reject through the A1 decision transaction: a stale binding is refused; idempotent replay; a targeted Revise carries the untargeted proposals byte-identical; Reject leaves `PROPOSED` and doesn't cancel |
| B-T4 | Bible sections in Joey order; a `[TBD]` in a render-required field → CRITICAL → repair → `BLOCKED (failed)` after 2 rounds. Tier promotion rules (≥2 episodes, any line, ≥2 recognisable scenes; off-screen speaker); a refused demotion that would drop a voice or identity demand |
| **B-T5 (V3-AT-18)** | **20 and 30 complete episodes planned with no asset, wardrobe-assignment, identity-lock or voice rows in the database.** The V3 writer opens no such table (a query-log assertion) |
| B-T6 | `LlmStep` behaviour per call: a crash mid-call resumes by `logical_call_id` with no second model call; invalid output → a new attempt; a refusal → `WAITING_QUOTA` with `retry_at`; a stale fence result is quarantined; runtime band, recap and CTA limits |
| **B-T7 (V3-AT-3)** | **All 24 packs fully renderable**: every scene has location + light, wardrobe for every visible character, and props with holder and state; every line has TH/EN/ZH + emotion + an estimate. The season critic catches each injected defect: **a premature secret, an impossible wardrobe day, >2 speakers in a beat**; also >5 speakers in an episode, an unpaid debt and a seam closed in the finale |
| **B-T8 (V3-AT-4)** | **Demand-list completeness:** every character, outfit, appearance state, prop + state, location + light, extras role and voice (with its emotions) used by any scene is listed with exactly its episodes and scenes; no orphan demand; IDs stable across a Revise that keeps the item |
| B-T9 | STORY LOCK Approve: all N episode rows + `episode_tracks` + accounts + bindings in one transaction; a forced failure in any step rolls back everything; `content_revision` bumps; the cadence selector never creates V3 episodes |
| B-T10 | STORY LOCK Revise on episode *k*: only *k* regenerates; a later pack invalidated by *k*'s new continuity appears as `continuity-dependent` and blocks Approve until "Revise these too" |
| B-T11 | `create_extension` eligibility (refused without `RELEASING`/`COMPLETE` or without the `SEASON` amendment); the extension builder plans new packs from a synthetic published canon without touching prior packs or approvals |
| B-T12 | Tabs 1–3 with real routes and templates: each state in §9, one primary action per tab, a disabled Mode A with its reason |

## 12. Open questions: RESOLVED 12 Nov 2026

**Operator, 12 Nov: "B: all recs".** Every recommendation below is adopted as the decision.

| # | Question | Recommendation |
|---|----------|----------------|
| O-B1 | Active locations per episode: V1 caps 2 (`ProductionLimits`), for 3–5-minute episodes | **3** per episode. Cost is governed by the demand list and the forecast (C), not by this cap |
| O-B2 | Default requested episode count | **24** (AT-3's season); the operator may choose 20–30 at intake and LOCK |
| O-B3 | Emotion vocabulary: each (speaker, emotion) pair is one manual Botnoi V4 upload | **6 values** (§2.2). The demand list shows the upload count per character before CAST LOCK |
| O-B4 | Role for the proposal call (master §10.1 lists Opus for bible/builder/critic, not the proposal) | **Opus** |
| O-B5 | LLM critics per episode, as well as per season, during the pilot (subscription quota) | **Season critic always; episode critic off by default**, switchable; the deterministic critics always run |
| O-B6 | Should the B1 note keep V3 documents out of `v2_contract_documents` entirely? | **Yes** (§2): a new table avoids widening the V2 allowlist and its `schema_version = '2.0'` CHECK |

## 13. Requirement trace

| R-ID | Where |
|------|-------|
| R-1.1 | §3.1–3.2 (Mode B complete; Mode A disabled, **partial** by design: V3C-32, master §16.2) |
| R-1.2 | §2 `SeasonProposalV3` |
| R-1.3 | §3.3 |
| R-1.4 | §1.3, §7 (live LLM writer via the subscription `LlmStep`; live trend research **deferred**, O-1) |
| R-2.1 | §2 `SeasonBibleV3`, §4.1, §6.1 (`[TBD]` rule) |
| R-2.2 | §2 `CharacterProfile` |
| R-2.3 | §2 (ledgers), §6 (secret timing, payoff debts) |
| R-2.4 | §2 (camera package, palette, lighting language), consumed by C and D |
| R-2.5 | §4.1, §9 |
| R-3.1 | §1.5, §5.1, B-T7 |
| R-3.2 | §2.1 |
| R-3.3 | §2.1 `psychology[]`, §2 `ContinuityStateV3` |
| R-3.4 | §4.3, B-T8 |
| R-3.5 | §5.3 |
| R-3.6 | §5.1, §9 |

**Findings resolved here:**
- V3C-4: §1.4, B-T5.
- V3C-5: §1.1, §2.3, B-T1, B-T2.
- V3C-26: the seam part, §8.
- V3C-32: §3.1, R-1.1.
- MA19: §2.2.
- V3R-4: §4.2.
- N22: §4.2.
