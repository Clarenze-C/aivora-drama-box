# Phase B: Story (Script Maker → LOCK → bible → episode packs → STORY LOCK)

**Version 0.4, 13 Nov 2026** (v0.1 11 Nov; v0.2 records the operator's answers to O-B1..O-B6; v0.3: one
neutral voice reference per speaker, master v0.4.5 §6; **v0.4 applies the Goldfish rulings
(`phase-b-goldfish-rulings.md`)** — every ruling and review Action; finding map in §17). Author: Opus
orchestrator; v0.4 applied by GLM. **Status: DRAFT for Codex critique (round 1).**

**Master:** [SPEC-v3.md](SPEC-v3.md) v0.4.6. **Depends on:** [phase-A0-spec.md](phase-A0-spec.md) v0.4
(`LlmStep`, the gateway, quota admission); [phase-A-spec.md](phase-A-spec.md) v0.3 (gates, tracks, the
decision transaction, budget, the fence); [A1-design-note.md](A1-design-note.md) v1.2 (migrations
0028–0031, the command table, the guards); [A2-design-note.md](A2-design-note.md) v1.0 (migrations
0032–0034, budget hierarchy, the step keys); [A3-design-note.md](A3-design-note.md) v1.0 (migration
0035, the fence and stale quarantine).

**Citation convention (C-B1):** "A1/A2/A3 note §x" = the design notes; "phase-A §x" =
`phase-A-spec.md`. All citations were swept in v0.4.

**Facts:** [b-factmap.md](b-factmap.md) (GLM-Flash, 11 Nov; v0.4 re-verified every code anchor it
cites). Code references are relative to `microdrama/src/microdrama/` (`S/`); migrations `M/`; tests `X/`.

**Owns:** V3-AT-3, 4, 18, 19 and R-1.1..R-1.4, R-2.1..R-2.5, R-3.1..R-3.6 (master §15).

---

## 0. Scope

**Phase B builds tabs 1–3 of the stepper and their two gates:**
1. **Script Maker:** Mode B (one-line title) → 2–3 proposals → **LOCK** (Approve / Revise / Reject).
2. **The bible** (`SeasonBibleV3`), character profiles with **tiers**, and the secret and season ledgers.
3. **The episode builder:** every episode as a full `EpisodePackV3`, in order, with a running continuity
   state, a critic per episode and a season critic → the **demand list** → **STORY LOCK**.

**Also in B:** Mode A visibly disabled with a reason; the V3 duration/count validators as
version-selected validation; compatibility readers; all planned episode rows created at STORY LOCK; the
extension seam and the `create_extension` command (A1 note §12 OQ-1). **Not in B:** **C** (assets, picks,
`CastBinding`/`CastLock`, the voice shortlist, the image-volume projection); **D** (shots, the shot
compiler); **F** (the extension decision screen, viewership windows, calendar integration); the live
metered LLM adapters (after O-5).

## 1. Binding decisions

1. **V1 and V2 validators never change** (AT-19, V3C-5; as phase A §1 and AC-1). The master's "every
   duration and count validator is replaced consistently" is met by **V3 records with their own
   validators**, selected by `seasons.workflow_version`. The V1 models stay frozen at contract 1.15.0
   and the V2 models at 2.15.0, unchanged: `SeasonScope`, `EpisodePlan`, `Script`, `EpisodePack`,
   `ConceptIntake`, `ConceptCandidate`, `ProductionLimits` (`S/contracts/primitives.py:54`). Historical
   records keep validating under their own schema, with their own 180–300 s and 1–10 rules.
2. **V3 story code lives in new modules** (`S/story_v3/`). The existing `S/story/` and `S/research/`
   modules are unchanged: V3 code may **import** their pure functions (the secret-leak check,
   `estimate_line_ms`, canonical hashing, the injection-resistant prompt framing) but never calls their
   services or writes their tables.
3. **Every V3 LLM call is an `LlmStep`** (master §10.1; A0 §5.1) inside its owning job. The synchronous
   `LLMProvider` (`S/contracts/providers.py:152`) is never used by V3 code. Pilot calls use the unmetered
   `llm.subscription` kind, so **phase B makes no reservation and posts no charge**. **When a metered LLM
   adapter ships (O-5),** B's calls reserve under the step keys `step_01`, `step_02` and `step_03`
   (§2.4 D1) — B names the keys only: A2's reservation machinery already consumes them
   (`md_reservation_step_rules`, A2 note §2.2), and B builds no adapter and no admission logic (the S5-9
   disposition: configuration named, nothing speculative built).
4. **Planning authority is the approved LOCK, never STORY LOCK** (V3C-4). The writer reads **no** asset,
   wardrobe-assignment, identity-lock or voice table; packs reference **logical demand IDs** (§4), which
   step 4 binds in `CastBinding` (C). The V1 IMP-01 gate (`S/story/service.py:790`,
   `IdentityLockRequired`) stays in the V1 writer and is not reachable from V3.
5. **Every pack is full.** The T039 rule `scoped_map_only = episode_number > 3`
   (`S/story/script_maker.py:818`) has no V3 equivalent, and `EpisodePackV3` has no map-only field
   (R-3.1).
6. **"≤2 speakers per shot" is enforced at pack level on beats** (AT-3 interpretation). Packs have no
   shots; D compiles them. A **beat** is the smallest unit D may split into shots and **never merges with
   another beat**; each beat has **at most 2 distinct speakers**, so every shot D compiles from it does
   too. D re-checks per shot.
7. **Gates open only when their step's work is complete.** A gate is never open while that step's jobs
   are queued or running, so a decision can't race its own regeneration; the continuation idiom (§7)
   sequences every fan-out, and promoted profiles complete before STORY LOCK opens (§4.2).
   Amendment-driven staleness is the fence (phase-A §7.1; A3 note §3).

## 2. Records (contract package, guardian-owned bump)

All V3 story records are **append-only documents** with `record_id`, `version`, `content_sha256`
(canonical hash of the payload), `schema_version = '3.0'` and timestamps, under the same sealing and
verification rules as `V2Record` (`S/contracts/v2.py:45–85`).

They are stored in a new table **`v3_story_documents`** through `StoryV3Store`, which mirrors
`StoryV2Store` (`S/story/v2_store.py:17`): `PRIMARY KEY (contract_type, record_id, version)`; one
`current` row per `(contract_type, record_id)`; consecutive versions; the hash re-verified on read; the
standard guards (no delete, no truncate, integer-only numbers); a `contract_type` allowlist CHECK.
`v2_contract_documents` is not touched.

**Identity:** `record_id = uuid5(STORY_V3_NS, "<type>:<planning_scope_id>[:<key>]")`; the
`planning_scope_id` is the season ID, or the extension ID (§8). Regeneration **advances the version and
keeps the ID**, the V2 convention (`S/story/script_maker.py:69`). **Versions vs rounds (C-N7):** for
`ProposalRoundV3`, versions count every round ever written for the scope; the `round` field is a
per-intake counter that resets to 1 on a fresh intake after a Reject, so that intake's round-1 content
lands as version k+1 on the same append-only record.

| Record | Key | Content |
|--------|-----|---------|
| `ConceptIntakeV3` | `intake` | `mode` (`TITLE` only; `TREND` refused, §3.1), `idea_line` (1–300 chars), optional genre/tone hints, `requested_episode_count` (20–30, default 24), `language = "th"`, `original_fiction = true` |
| `ProposalRoundV3` | `proposals` (versions = all rounds, §2 Identity) | `round` (per intake, resets after Reject), 2–3 `SeasonProposalV3`, the revision-note refs that produced the round (none for round 1) |
| `SeasonProposalV3` (embedded) | `proposal_id = uuid5(STORY_V3_NS, "proposal:<scope>:<round>:<slot>")`, stable within its round | the master §4.1 fields: title TH/EN, logline, premise, thesis question, genre/tone, `episode_count` (20–30), `target_length_ms = 120_000`, main cast briefs (3–6), season promise, escalation shape, ending, **extension seam sketch**, why it would trend, originality and rights notes |
| `SeasonBibleV3` | `bible` | **wraps the existing `SeasonBible` (`S/story/models.py:63`) and `RichBible` (`S/story/script_maker.py:206`) for the sections they already cover, plus the new V3 sections — master §4.2 honoured, no deviation (C-M11)**; the Joey sections **in order**; the camera package, palette, lighting language, pacing rule; `characters[]`; `extras_roles[]`; the ledgers; `initial_continuity` (the seed `ContinuityStateV3` for episode 1, C-N1); `tbd[]` (field path + reason) |
| `CharacterProfile` (embedded) | `character_key` | `tier`; narrative function; visual lock (text); backstory; psychology by story state; speech (register, texture, cadence, Thai politeness and pronouns, code-switching); movement; stillness; drift exclusions; goal, strategy, flaw, secrets; **voice descriptor** (gender, age band, pitch, timbre, pace, accent/dialect, emotional baseline), required when the character speaks |
| `EpisodePackV3` | `episode:<n>` | §2.1 |
| `ContinuityStateV3` | `continuity:<n>` | the state **after** episode *n*: per character, outfit + appearance states + location + known secrets + end psychology; per prop, holder + state; the story clock; **the wardrobe history by story day** |
| `CriticReportV3` | `critic:<episode n \| season>` | findings with severity, rule ID, the target (pack/scene/beat/line) and evidence; per-episode and season reports |
| `SeasonDemandListV3` | `demands` | §4 |
| `ExtensionSeamV3` | `seam` | threads: `thread_id`, description, the open payoffs it may grow, constraints that must hold to keep the ending, **`status` (`OPEN`/`RESOLVED`; a thread becomes `RESOLVED` when a pack resolves its last open payoff — C-M9)**; built with the bible and **bound at STORY LOCK** |
| `StoryLockBindingV3` | `story-lock:<content_revision>` | the hashed set STORY LOCK approves (§5.4) |

**Reused shapes:** the secret and season ledgers reuse the V2 shapes `SecretEntry`
(`S/contracts/v2.py:276`), `PayoffDebt` (`:206`) and `SeasonEscalation` (`:213`), embedded as V3 models
with the same validators; `validate_season_story_ledger` (`:242`) gets a V3 sibling that binds the ledger
to the bible, the packs and the LOCK authority.

### 2.1 `EpisodePackV3`

| Field | Rule |
|-------|------|
| `planning_scope_id`, `episode_number` | identity before rows exist; `episode_id` is bound only at STORY LOCK (§5.4) |
| `lock_authority` | the approved proposal's `content_sha256` + the LOCK approval event ID (V3C-4) |
| `titles` TH/EN; `synopsis` | required |
| `recap_plan` | the beats recalled from the previous episode, with `estimated_ms ≤ 10_000`; **empty for episode 1** |
| `scenes[]` | each: `scene_id`; `story_time` (reusing `StoryTime`, `S/contracts/v2.py:284`: story day, local time `HH:MM`, setting — C-N10); `location` (demand ID + **light state**); `visible_cast[]` (character demand ID or extras-role demand ID, with framing `RECOGNISABLE` or `BACKGROUND`); `props[]` (prop demand ID + holder character ID or none + state ID); `wardrobe[]` (for **every** visible character: outfit demand ID + appearance-state IDs); `beats[]` |
| `beats[]` | each: `beat_id`, text, `planned_hold_ms` (non-dialogue screen time), `line_ids[]`, `reveals[]` (secret IDs), **≤2 distinct speakers** (§1.6) |
| `cliffhanger_beat_id` | a beat of the last scene |
| `lines[]` | each: `line_id`, `beat_id`, `speaker` (**a character or an extras-role demand ID** — C-M13b), `off_screen` (bool), `text_th`, `text_en`, `text_zh`, **`emotion`** (closed enum, §2.2), `delivery_note` (≤200 chars), `estimated_ms` (from `estimate_line_ms`, `S/story/prompts.py:367`), `critical_terms[]` (the V1 shape) |
| `cta` | an intent line, `estimated_ms ≤ 5_000`. No `template_id`: no template registry exists in any phase, and the CTA copy is resolved in E/F from the calendar revision it depends on (master §4.7; C-N1) |
| `psychology[]` | for each principal **or supporting** character who appears (§6.1, C-M13a): start state + end state |
| `promise`, `payoff_debt`, `escalation` | as the V2 pack (`S/contracts/v2.py:353`) |
| `duration_target_ms` | `120_000` |
| `estimated_runtime_ms` | Σ line `estimated_ms` + Σ beat `planned_hold_ms` + recap + CTA; **must lie in 105_000–135_000** |

**Absent by design:** `scoped_map_only`; asset IDs; wardrobe-assignment IDs; voice IDs;
`actual_duration_ms` — bound later in C (cast) or measured in D/E (durations).

### 2.2 V3 limits and vocabularies (`V3ProductionLimits`, V3 records only)

| Rule | Value | Source |
|------|-------|--------|
| Episode count at LOCK | 20–30; a proposal's `episode_count` **must equal the intake's `requested_episode_count`** (CRITICAL otherwise, C-M15) | master §4.1 |
| Episode length | target 120 s, band 105–135 s, including recap ≤10 s and CTA ≤5 s | master §4.1 |
| Distinct speakers per episode | ≤5, counting off-screen speakers | MA19, O-12 |
| Speakers per beat | ≤2 | §1.6 |
| Main cast briefs per proposal | 3–6 | master §4.1 |
| Active locations per episode | **3**, counted as **distinct `location_key` values in `scenes[]`, recap excluded** (O-B1; C-M13c) | — |
| `emotion` | `NEUTRAL`, `HAPPY`, `SAD`, `ANGRY`, `FEARFUL`, `SURPRISED` (O-B3; closed — out-of-enum values are rejected, B-T7) | DECISIONS D2 revised |

Each line's `emotion` drives the **prompt's expression text** (master §6), not a voice reference.
**Each speaker needs exactly one neutral voice reference** (DECISIONS "D2 revised again", 12 Nov),
superseding "D2 revised"'s per-(speaker, emotion) variants (DECISIONS:241–243; C-N6); the demand list
(§4) carries one voice demand per speaker.

### 2.3 Field mapping, readers and the consumer order (V3C-5)

**Mapping** (master §4.3; **the B1 note must extend this to every field** of the three source models,
with `file:line` — each field mapped, dropped with a reason, or V3-new; an obligation, not a done
fact — C-N5):

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

**Readers:** `read_episode_story(tx, episode_id)` returns a version-tagged view — `V1(EpisodePlan,
Script)`, `V2(EpisodePack)` or `V3(EpisodePackV3)` — each validated under its own schema version; it
reuses `read_v1_manifest` (`S/contracts/v2.py:1041`) where it applies. **A V1 or V2 consumer given a V3
episode raises `WORKFLOW_MISMATCH`** (phase-A §1).

**Consumer order.** B migrates **no** consumer. They move to the V3 reader in the phase that owns them:
1. **D:** `story/directing.py:101` (replaced by the single shot compiler); `references/v2_planning.py`
   and its binding/dispatch modules; `rendering/routing.py`; `qa/continuity_sources.py`.
2. **E:** `editing/edl.py`, `editing/captions.py`, `editing/service.py`.
3. **F:** `review/packages.py`, the progress views in `review/intake.py`, `community/grounding.py`.
4. **The qa trio** (`qa/coverage.py`, `qa/comparison.py`, `qa/observation.py`) joins the inventory as
   **reachable only through guarded job paths** — pure functions over records already loaded inside
   job/review execution behind A1's replay guard (`S/workers/runtime.py:216`). The B1 note confirms this
   per module and pins **one guard site per listed consumer** (an existing A1 guard, a dispatch guard, or
   a new module guard B1 adds) — C-M10. **B-T2 enumerates those entry points through a shared fixture**
   (imported, not a re-edited copy of A1's A-T5), not refusals hard-coding D/E/F future state.

### 2.4 B contract deltas (C-B1; a first-class, critiqued-first B1 deliverable)

B's migrations start at **0036** (A0=0027, A1=0028–0031, A2=0032–0034, A3=0035; A3 note §1 — the B1
note re-audits the tail before allocating). Every B identifier crossing an A-phase enforced contract:

| # | Delta | Contract touched | Mechanism |
|---|-------|------------------|-----------|
| D1 | Step keys `step_01` = Script Maker, `step_02` = bible, `step_03` = episodes | A2's `budget_steps` CHECK (`step_01..step_10`, `launch`, `episode_production`) and `md_reservation_step_rules` (A2 note §2.2, §11 OQ-2) | **Adopt A2's existing keys; no CHECK amendment.** Pilot calls are unmetered, so B writes no reservation; when a metered adapter ships (O-5), B's flows name these keys and reserve against the `SEASON_SETUP` account (steps 1–4 are setup scope, A2 note §2.2) |
| D2 | Decision-target kinds `PROPOSAL`, `EPISODE_PLAN` (by episode number, before STORY LOCK), `BIBLE_SECTION`, `SEAM`, `TIER` | A1's `RevisionTargetKind` and its validators (A1 note §4, new `S/contracts/v3.py`); `V3DecisionCommand` | **B1 owns a migration in B's range**: contract code + regenerated v3 schemas (note targets are jsonb validated in Python, not a SQL CHECK — A1 note §2.3; the enforced vocabulary is the StrEnum + validators). `V3DecisionCommand` gains an optional typed `target`, **absent for A1's existing gates** — A1's behaviour unchanged, its note and build **not** reopened; the delta lands in B1 after A1 is accepted. Target IDs reuse §2's uuid5 convention: `PROPOSAL` → the slot's `proposal_id`; `EPISODE_PLAN` → the pack `record_id` (`uuid5(STORY_V3_NS, "episode:<scope>:<n>")`); `SEAM` → the seam record ID; `BIBLE_SECTION`/`TIER` → `uuid5(STORY_V3_NS, …)` over the section path / `character_key` (exact derivations pinned in the B1 note) |
| D3 | `edit_tier` command-table row | A1 note §6 command format | §9; ships in B5 (C-M3) |
| D4 | Citation convention | — | header; swept in v0.4 |

**Standing rule (C-B1):** any B identifier that crosses an A-phase contract is checked against that
contract's *enforced* vocabulary (enum, CHECK, validator) **before the B1 note is accepted**. Applied in
v0.4 beyond the table: the LOCK Approve target and Revise note targets ride D2 (validated against the
activation's binding units — A1 note §5); `edit_tier`'s close/reopen uses A1's `supersede_gate` /
`open_gate` (A1 note §6); and the C-M1 continuation idiom rides A1's `replaces_job_id` validation, which
ties a replacement link to **one `logical_work_id`** (A1 note §2.4) — so the round number scopes the
**semantic key**, not the logical work ID (§7).

## 3. Step 1: Script Maker → LOCK

### 3.1 Intake

- **`submit_v3_intake(mode, idea_line, hints, requested_count)`:** human session + CSRF + idempotency
  key. The route accepts a `mode` field; **only `TITLE` is admitted** — `TREND` is refused with
  `MODE_UNAVAILABLE` before any write (C-N12). Steps: call `create_v3_season` (A2; `NOT_AVAILABLE` until
  A2 ships); write `ConceptIntakeV3`; enqueue `story_v3.propose` round 1; advance planning
  `IDEA → PROPOSED` when the round is written (§3.2).
- **Mode A:** the intake form shows **Trend research: disabled** with the reason (master §4.1, V3C-32);
  the research code (`S/research/service.py:313`) stays V1-only behind the `require_workflow` guards
  (A1 note §7). The V1 wizard (`S/review/intake.py:676`) is unchanged and creates only V1 seasons.

### 3.2 Proposal job `story_v3.propose`

- **One `LlmStep`** (role: Opus; O-B4) produces 2–3 materially distinct interpretations as
  `SeasonProposalV3`; round *k* > 1 carries the revision notes.
- **Validation:** schema, then the V3 limits (including **`episode_count == requested_episode_count`**,
  C-M15), then originality and rights notes present, then the name screen.
- **Name screening, stated plainly (C-M6):** B enforces "no real people, brands or celebrities" only
  through **prompt constraints plus originality-vs-corpus screening** (`screen_concept`,
  `S/research/originality.py:179`) — a resemblance screener with **no person/brand list**. The
  real-person/brand/likeness check is phase C's output inspection (master §12.2); residual risk §15.
- **Invalid output:** a repair round with a new `logical_call_id` — **1 initial + 2 repair rounds = 3
  content attempts** (C-N9), then the job fails → `BLOCKED (failed)`.
- **On success, in one transaction:** write the `ProposalRoundV3` version;
  `open_gate(SEASON_CONCEPT, season, binding = canonical_hash({round record_id, version,
  content_sha256}))`; `advance_planning(PROPOSED)` (round 1 only).

### 3.3 LOCK decisions (the B handler for V3 `SEASON_CONCEPT`)

| Action | Conditions (evaluated in the A1 decision transaction, A1 note §5) | Effect in the same transaction |
|--------|-------------------------------------------------------|--------------------------------|
| **Approve** `target = {kind: PROPOSAL, id: proposal_id}` — carried by `V3DecisionCommand.target` (§2.4 D2) and validated against the bound round's slots | the target is in the bound round; `episode_count` is 20–30 and equals the requested count | record the approval; **LOCK authority** = the proposal's `content_sha256` + the event ID; `PROPOSED → LOCKED`; enqueue `story_v3.bible` |
| **Revise** + notes (`season_revision_notes`, ≥1; targets: the round, or specific proposals as prompt guidance) | the activation is open | the activation closes; enqueue `story_v3.propose` round *k*+1. **The whole round regenerates** (2–3 fresh proposals; every note passed to the prompt) — master §4.1's note model is a new proposal revision; no slot-level byte-identical carry (C-N3; §16). Planning stays `PROPOSED`; the job opens the next activation |
| **Reject** | — | A1 note §6: no concept authority; planning stays `PROPOSED`, and the operator may submit a new intake (round counter resets, §2 Identity) or Revise later. **The season is never cancelled by a Reject** |

The handler is **registered only in compositions where phase B has shipped.** Before that, V3 LOCK
returns `NOT_AVAILABLE` (A1 note §12 OQ-5).

## 4. Step 2: bible, tiers and the demand list

### 4.1 Bible job `story_v3.bible`

1. **One `LlmStep` (Opus)** writes `SeasonBibleV3` + `ExtensionSeamV3`, given the LOCK authority, the
   approved proposal and the Joey method digest (`joey-digest.md`; internal method only, no
   redistribution: master §18).
2. **The deterministic bible critic** (§6.1 bible rules); then **one LLM critic pass** (Opus, O-B5) for
   drift, thesis coherence and density.
3. **Repair:** 1 initial + 2 repair rounds (C-N9), each carrying the critic findings. A `[TBD]` in a
   render-required field (the camera package; a speaking character's visual lock or voice descriptor; the
   locations' light language) is **CRITICAL**. **Success:** `LOCKED → BIBLE`; enqueue
   `story_v3.plan_episode(1)`.

**The two TBD mechanisms are one rule (C-N11):** `tbd[]` is the declared form (field path + reason); the
literal `[TBD]` string in a render-required field is the detected form; the critic treats either as
CRITICAL there. The bible is reviewed at STORY LOCK, not at its own gate (master §2). Progress (R-2.5):
one generation job plus one critic pass.

### 4.2 Tiers and speaker counting (deterministic, `S/story_v3/tiers.py`)

- **The initial tier** comes from the bible: main cast are `PRINCIPAL`; named non-principals are
  `SUPPORTING`; background roles are `EXTRA` (`ExtrasRole`).
- **Promotion after all packs exist:** a non-principal becomes `SUPPORTING` if it appears in ≥2 episodes,
  or has any line, or is framed `RECOGNISABLE` in ≥2 scenes. An off-screen speaker is always at least
  `SUPPORTING` (N22). **A known character is a bible profile or an extras-role id already seen; an
  extras-role id is a legal `speaker`** (C-M13b) — which is what makes the "has any line" trigger
  constructible. A promoted extras role becomes a `CharacterProfile` through **one
  `story_v3.promote_profile` call per promoted role** (its acceptance case is B-T8).
- **`story_v3.promote_profile` (C-M12):** 1 initial + **1 repair attempt** = 2 content attempts, then
  `BLOCKED (failed)` — the same policy shape as B's other LLM jobs, deliberately lighter for a profile
  completion. Profiles persist as `CharacterProfile` records in `v3_story_documents` and **complete
  before the gate opens** (§1.7): promotion never bumps the bible record's version while a gate is open;
  `StoryLockBindingV3` (§5.4) hashes the profiles at finalization.
- **Operator tier edits at STORY LOCK — `edit_tier(character_key, tier)`** (human session + CSRF; command
  row §9; the tab-3 tier controls invoke it; ships in **B5** with everything it re-runs — C-M3). The
  single name for its re-check is **tier revalidation**: it supersedes the open STORY LOCK activation
  (`supersede_gate`) and opens a new one (`open_gate`; A1 note §6), re-running promotion validation,
  demand derivation and the season critic's deterministic checks. **Overrides never waive** speaker
  counting, the voice requirement or identity coverage (V3R-4): a demotion that would leave a speaker
  without a voice demand, or a recognisable character without an identity demand, is refused (B-T9).

### 4.3 The demand list (`SeasonDemandListV3`, deterministic)

Derived from the bible + all packs **after the season critic runs**, regardless of remaining findings
(C-M13d; the gate may open with CRITICALs, §5.2). One `LogicalDemand` per item:

| Kind | Logical key | Carries |
|------|-------------|---------|
| `CHARACTER` | `character_key` | tier; identity coverage required (`PRINCIPAL`/`SUPPORTING`, or any `RECOGNISABLE` framing) |
| `OUTFIT` | `character_key` + `outfit_key` | the story days worn |
| `APPEARANCE_STATE` | `character_key` + `state_key` | (e.g. injured, wet) |
| `PROP` | `prop_key` (+ `state_key`) | holders by scene; **proof-prop flag: the prop a beat depends on as evidence (master §0 glossary) and that is therefore never droppable** (C-N2) |
| `LOCATION` | `location_key` + `light_state` | the local times used |
| `EXTRAS_ROLE` | `role_key` | framing |
| `VOICE` | `character_key` | one neutral reference; the set of emotions its lines use is informational (it drives prompts, §2.2) |

- `demand_id = uuid5(STORY_V3_NS, "demand:<planning_scope_id>:<kind>:<logical key>")`, so it is **stable
  across revisions** — a Revise that keeps an item keeps its ID, which `CastBinding` (C) relies on.
- **Promotion merges demands (C-M7):** a promoted extras role's `EXTRAS_ROLE` demand is merged into the
  new `CHARACTER` demand, with lineage (the source `role_key` recorded); pack references to the role
  resolve to the `CHARACTER` demand — one on-screen person, exactly one identity demand (V3R-4).
- **Every item lists the episodes and scenes that use it** (AT-4), and the references are checked both
  ways: every pack reference resolves to a demand, every demand is used at least once.
- **The STORY LOCK screen shows the demand counts by kind and tier.** The step-4 cost forecast and the
  image-volume projection are phase C's (`NOT_AVAILABLE` until C ships).

## 5. Step 3: episodes → STORY LOCK

### 5.1 Episode job `story_v3.plan_episode(n)`

- **One job per episode, in order.** Each carries the LOCK authority; the bible version;
  `ContinuityStateV3(n−1)` (the bible's `initial_continuity` for episode 1, C-N1); **the season plan
  (defined, C-N2):** the approved proposal's season promise, escalation shape and ending, plus the seam;
  and `expected_content_revision` (phase-A §7.1; A3 note §3).
- **Steps:** (1) the **architect `LlmStep` (Opus)** writes the pack (TH + EN), given the bible, the seam,
  the previous state and the season plan; (2) the **translation `LlmStep` (Sonnet; master §10.1 roles)**
  adds `text_zh` and checks EN; (3) the **deterministic episode critic** (§6.1); (4) the **LLM episode
  critic, switchable (O-B5, C-M14):** `Settings.v3_episode_critic` (env
  `MICRODRAMA_V3_EPISODE_CRITIC`; `S/config.py:42`, prefix `:24`), **default off, global, read at
  `plan_episode` dispatch**; B-T6 covers default-off and toggled-on.
- **Repair:** 1 initial + 2 repair rounds (C-N9), carrying the findings, then the job fails →
  `BLOCKED (failed)`.
- **On success:** write the pack version and `ContinuityStateV3(n)`; enqueue `plan_episode(n+1)`, or,
  after the last episode, `story_v3.season_critic` (§7).
- **Progress (R-3.6):** *n*/N episodes planned, then the critic checks. **Crash and replay:** a frozen
  call is resumed by its `logical_call_id` (A0), so a crash never calls the model twice for one attempt;
  a completed episode is never re-planned by replay — the semantic key is
  `(scope, n, LOCK authority, bible version, round)`, whose round component lets a deliberate re-plan
  through and never dedupes it to a no-op (§7; C-M1).

### 5.2 Season critic `story_v3.season_critic`

1. **The deterministic season checks** (§6.2).
2. **One LLM season critic (Opus):** character drift against the drift exclusions, psychology resets, a
   weak escalation, payoff timing.
3. **Repair rounds, bounded (C-M2):** for findings that name packs, at most 2 rounds. A repair round
   re-plans the **earliest** named episode and every later episode whose continuity input changed (§5.5),
   **at most 6 episodes per round**. A round that would exceed 6 stops: the finding is recorded with an
   **impact preview** (the episodes that would re-plan) and the flow continues to finalization — the gate
   opens with the finding and the preview, Approve stays blocked while the CRITICAL is open, and the
   operator decides (Revise, the scoped revision authority of master §2.1). While a repair round runs,
   tab 3's season-critic wait state shows the **blast radius** (re-planning now vs deferred).
4. **Then (the continuation idiom, §7):** tier promotion (§4.2); `story_v3.promote_profile` jobs — the
   **last** one to complete runs the finalization inline; then the demand list (§4.3);
   `StoryLockBindingV3`; `open_gate(STORY_LOCK, season, binding)`; `BIBLE → PLANNED`.

**If CRITICAL findings remain after repair,** the gate still opens, so the operator can see and Revise,
but **Approve's condition fails** while any CRITICAL is open. **Resume (C-M5):** **rounds are the unit of
retry** (round-scoped semantic keys make a re-run idempotent) — the operator's retry action re-runs the
failed round only, from its earliest failed episode. **Completed packs are kept** (stable pack and demand
IDs make them safe), and tab 3 labels each pack's version status during a round (current / superseded /
re-planning).

### 5.3 STORY LOCK decisions (the B handler for `STORY_LOCK`)

| Action | Conditions | Effect in the same transaction |
|--------|-----------|--------------------------------|
| **Approve** | no open CRITICAL; the binding is current; the tier revalidation passed; **the STORY LOCK budget attach succeeds** (phase-A §5.1; A2 note §4: the `SEASON` account + setup attachment + episode accounts fit the base cap) | record the approval; call **`create_v3_episodes(season, N)`** (A2), which creates **all N episode rows** independently of the release cadence (AT-18); write `v3_episode_story_bindings` (§5.4); `PLANNED → STORY_LOCKED`; `content_revision` bumps (A1 note §6). Step 4 starts when phase C's handler is registered |
| **Revise** + notes (targets: `EPISODE_PLAN` packs, `BIBLE_SECTION`s, the `SEAM`, or a `TIER` — §2.4 D2) | the activation is open | the activation closes. **Only the noted units regenerate:** noted packs via `plan_episode(n)` rounds, bible sections via a scoped `story_v3.bible` round, the seam likewise; a tier target routes to `edit_tier` (§9). Then the closure revalidation (§5.5) and the season critic round, and the gate reopens with a new binding |
| **Reject** | — | A1 note §6: no episode-creation authority; planning stays `PLANNED` |

**The STORY LOCK screen (R-3.5):** the bible; every episode's outline (synopsis, scenes, cliffhanger,
reveals) **with per-pack version status** (C-M5); the critic findings **and any cascade impact preview**
(§5.2); the demand counts; tier controls; Approve, or Revise with notes per episode or per section.

### 5.4 Episode binding

- **`v3_episode_story_bindings`:** `episode_id`, `season_id`, `episode_number`, `pack_record_id`,
  `pack_version`, `pack_sha256`, `story_lock_approval_event_id`, `content_revision` — append-only and
  guarded, with `UNIQUE(episode_id, content_revision)`. Later amendments (A4) add rows at the new
  `content_revision`; the current binding is the row at the episode's current `content_revision`.
- **`StoryLockBindingV3`** hashes: the bible (record ID, version, sha); every pack in episode order; the
  demand list; the seam; the tier table; the promoted character profiles (§4.2, C-M12); the critic
  reports. **That hash is the activation binding** (phase-A §2.5).
- **V3 episodes keep legacy `episodes.state = PLANNED` and an empty `episodes.plan`** (phase-A §1).
  `_w03_episode_cadence` (`S/scheduling/service.py:199`) never selects V3 seasons (A1 note §7 guards).

### 5.5 Closure revalidation after a Revise or repair

1. Regenerate the noted units.
2. **Re-run the deterministic continuity check forward** from the earliest regenerated episode, against
   the stored later packs. A later pack that no longer satisfies its continuity input becomes an
   **invalid dependent**: a CRITICAL finding `continuity-dependent` naming the episode.
3. **Invalid dependents are not regenerated silently.** The STORY LOCK screen lists them with one
   "Revise these too" action, which is the scoped revision authority of master §2.1. Approve stays blocked
   until none remain.
4. **Non-episode targets (C-M18):** a bible-section or seam Revise regenerates the noted section/seam,
   then runs this revalidation. **Non-invalidated packs survive** — the machinery catches continuity
   invalidation, not conceptual drift; drift beyond continuity is the operator's judgement at the reopened
   gate (B-T10 covers one bible-section, one seam and one tier Revise).

**The asymmetry, stated (C-M2):** pre-gate repair is silent and bounded because drafts have no
dependents — before STORY LOCK nothing exists downstream (no cast, no shots, no published work);
post-gate regeneration has dependents, so it needs the operator's explicit "Revise these too" authority.

## 6. Critics (deterministic rules; the LLM critics add findings, never waive these)

### 6.1 Bible rules and episode rules

**Bible rules (the deterministic bible critic; C-N8):**

| Rule | Severity |
|------|----------|
| schema; the Joey section order (master §4.2) | CRITICAL |
| the ledgers bind to the bible, the packs and the LOCK authority (the V3 `validate_season_story_ledger` sibling, §2) | CRITICAL |
| a `[TBD]` or `tbd[]` entry in a render-required field (camera package; a speaking character's visual lock or voice descriptor; the locations' light language) | CRITICAL |

**Episode rules:**

| Rule | Severity |
|------|----------|
| schema, V3 limits, runtime band, recap ≤10 s, CTA ≤5 s | CRITICAL |
| every visible character has wardrobe (outfit + appearance states) in the scene | CRITICAL |
| every line's speaker is a known character — a bible profile or an already-seen extras-role id (C-M13b) — with TH/EN/ZH text and an in-enum emotion | CRITICAL |
| ≤5 distinct speakers per episode; ≤2 per beat | CRITICAL |
| a secret revealed or leaked before its `planned_reveal_episode` (the V2 normalized-substring check, `S/story/script_maker.py:540`) | CRITICAL |
| a `[TBD]` in a render-required field | CRITICAL |
| prop continuity: holder and state follow from the previous state or an on-page beat | MAJOR |
| a location's light state is plausible for its local time | MAJOR |
| missing cliffhanger beat; missing psychology entry for an appearing principal **or supporting** character — "appears" = at least one line or one visible-cast entry (C-M13a) | MAJOR |

### 6.2 Season rules

| Rule | Severity |
|------|----------|
| **Impossible wardrobe day:** within a scene, an outfit change is allowed only if a beat references it; across a scene break it is always allowed, subject to the story-day rule (an outfit change within one story day without an allowing beat/scene break, or a contradiction of the wardrobe history) (C-M19) | CRITICAL |
| a payoff debt left unpaid at the finale, and not assigned to a seam thread | CRITICAL |
| a seam thread `RESOLVED` or closed in the finale — read from the thread's `status` field (§2; C-M9) | CRITICAL |
| the episode count differs from the LOCK authority | CRITICAL |
| an escalation step regresses | MAJOR |
| every pack satisfies §6.1 (a re-check against the final set) | as §6.1 |

**On an extension scope (C-M8), three rules are reinterpreted:** the episode-count authority is the
approved `SEASON` amendment's count over the **cumulative** range; the §6.1 "final set" re-check covers
**the extension's packs only**; and "seam thread resolved in the finale" is CRITICAL **only when the
thread reserved further growth** — resolving a thread in an extension finale is a legitimate endpoint.

**A CRITICAL finding blocks STORY LOCK Approve. MAJOR and MINOR findings are shown.** The LLM critics may
add findings at any severity but **cannot clear a deterministic finding** — the V1 principle in
`S/story/service.py`'s module docstring.

## 7. Jobs, LLM calls, prompts, fence and waits

### 7.1 The continuation idiom (C-M1)

B is the family's first fan-out/fan-in phase. One idiom covers the promote join, the repair rounds and the
Revise loop, using only A1 primitives:

- **Work identity is stable; attempts are round-scoped.** Each logical work has a stable
  `logical_work_id`: `propose:<scope>`, `bible:<scope>`, `plan:<scope>:<n>`,
  `profile:<scope>:<character_key>`, `season-critic:<scope>` (this also fixes C-N13 — the season-critic
  work ID's fourth component is the round number, not an undefined "binding inputs"). Each attempt
  carries its round number in the **`jobs.semantic_key`** — `plan`: `(scope, n, LOCK authority, bible
  version, round)`; the others: work id + round — so a re-plan never dedupes to a no-op (semantic keys
  are UNIQUE, `M/0001…sql:78`). A1's `replaces_job_id` validation ties a replacement link to one
  `logical_work_id` (A1 note §2.4), so the round lives in the semantic key, not the work ID (§2.4).
- **Re-plans chain through `replaces_job_id`:** every job that supersedes another's output names it,
  under the same logical work ID — also what clears a terminal `BLOCKED (failed)` projection when the
  replacement succeeds (A1 note §2.4 `track_waits`).
- **The last job of a round enqueues the continuation.** "Last" is evaluated in the completing job's own
  transaction under the scope track lock (every sibling of the round terminal, itself SUCCEEDED):
  `plan(n)` → `plan(n+1)` or the season critic; the last repair re-plan → the next season-critic round;
  the last `promote_profile` → the deterministic finalization inline (§5.2), as does the season critic
  when no promotions are pending; a Revise round's last job enqueues the season critic (§5.3). **No
  quarantined work enqueues anything** (A3 note §3.4).

### 7.2 Job table

| Job | Queue | `LlmStep` calls (role) | Logical work ID |
|-----|-------|------------------------|-----------------|
| `story_v3.propose` | the existing `PRODUCTION` queue (phase A adds no lanes) | 1 per attempt (Opus) | `propose:<scope>` |
| `story_v3.bible` | ″ | 1 + 1 critic (Opus) per round | `bible:<scope>` |
| `story_v3.promote_profile` | ″ | 1 per promoted role (Opus) | `profile:<scope>:<character_key>` |
| `story_v3.plan_episode` | ″ | architect (Opus) + translation (Sonnet) (+ critic) per attempt | `plan:<scope>:<n>` |
| `story_v3.season_critic` | ″ | 1 (Opus) per round | `season-critic:<scope>` |

**B1 registers all five `story_v3.*` job types** (enqueue-allowed, handlers landing per package — C-M20),
so B2's Approve can enqueue `story_v3.bible` (B3's handler) and B4's last episode `story_v3.season_critic`
(B5's) at their own gates.

### 7.3 Prompts (C-M4)

| Prompt | Owning package |
|--------|----------------|
| the proposal prompt | **B2** |
| the bible prompt and the promoted-profile prompt | **B3** |
| the architect and translation prompts | **B4** |
| the critic prompts (bible, episode when switched on, season) | **B5** |

Each is registered in the `PromptManifest` (`S/contracts/v2.py:773`) and **ships with its package**.
Acceptance: **every `FrozenLlmCall` in B's tests references a manifest-registered prompt** (§12).

### 7.4 Calls, fence, waits, offline

- **Every `FrozenLlmCall`** carries a pinned prompt ID and its sha256 (§7.3); the inputs as **untrusted
  documents** (the existing injection-resistant framing,
  `X/unit/research/test_injection_resistance.py`); and the output schema.
- **A new content attempt gets a new `logical_call_id`; transport recovery reuses the old one** (A0 §5.1).
- **Waits:** `LlmDeferred` maps to `RETRY_WAIT` with `defer_reason` (A0). The track projects
  `WAITING_QUOTA` or `WAITING_PROVIDER` through `track_waits` (A1 note §2.4). An unreadable quota pauses
  production (master §10.1).
- **The fence:** every B job input carries `expected_content_revision`. A stale result is quarantined
  (phase-A §7.1; A3 note §3.4: evidence kept, money accounted, **no continuation enqueued**) and never
  written as the current pack.
- **Offline:** every B test uses A0's fake gateway / fake `LlmStep` adapter with scenario scripts (valid,
  invalid, refused, deferred, crash mid-call). No B test calls `claude`, ai-route or the network.
  **`make pilot` (V1) stays green and untouched.**

## 8. Extension seam and `create_extension`

- **`ExtensionSeamV3`** is written with the bible, revised at STORY LOCK, and **bound by STORY LOCK.**
- **`create_extension(season, range, calendar)`** activates in B (A1 note §12 OQ-1); the command row is
  §9. It checks eligibility — the season release is `RELEASING` or `COMPLETE`; the range lies beyond the
  current count; **an approved `SEASON` amendment covers the new count** (phase-A §5.4; A2 note §5) — and
  opens a `season_extensions` scope.
- **On an extension scope** (`planning_scope_id = extension_id`), the same builder runs: `plan_episode`
  for the new range, then the season critic, then STORY LOCK for the new packs only. Inputs: the prior
  STORY LOCK's bible and seam; the **planned-terminal canon** (the last stored `ContinuityStateV3`); a
  **published canon** input. The prior approvals and packs are never touched; the §6.2 extension
  reinterpretations apply.
- **Phase F owns** the decision screen, the viewership windows, the published-canon source and the
  calendar integration. **B tests the extension builder with a synthetic published canon.**

## 9. B commands (C-M3; A1 note §6 format)

| Command | Actor | Scope / revision owner | Prerequisites | Effect | Events | Replay identity | Activation |
|---|---|---|---|---|---|---|---|
| `submit_v3_intake(mode, idea_line, hints, requested_count)` | Operator (human session + CSRF) | season / — (via `create_v3_season`) | mode `TITLE` only; `requested_count` 20–30 | `ConceptIntakeV3` (versioned); enqueue `story_v3.propose` round 1 | (A1's creation events via `create_v3_season`) | idempotency key | **B** (needs A2's `create_v3_season`) |
| `edit_tier(character_key, tier)` | Operator (human session + CSRF) | season / `season_tracks.revision` | a STORY LOCK activation is open | supersedes the activation; runs **tier revalidation** (§4.2); refuses V3R-4-violating demotions; opens a new activation | activation supersede/reopen events | idempotency key | **B5** (C-M3) |
| `create_extension(season, range, calendar)` | Operator (human session + CSRF) | season / `season_tracks.revision` | release `RELEASING`/`COMPLETE`; range beyond the current count; an approved `SEASON` amendment covers the new count (§8) | opens a `season_extensions` scope | (A1's scope events) | idempotency key | **B** (A1 note §12 OQ-1) |

## 10. UI (tabs 1–3, built into the phase A shell, A5)

| Tab | Route | Scope | Progress denominator | Primary action |
|-----|-------|-------|----------------------|----------------|
| 1 Script Maker | `/v3/seasons/{id}/script` (`/v3/seasons/new` before a season exists) | season | the proposal job (one call per round) | **Submit** (intake); then the LOCK gate buttons |
| 2 Bible | `/v3/seasons/{id}/bible` | season | generation + critic pass (2 units) | **`Next`** — navigation only, after completion; it is this tab's one primary action and never approves (master §3.2 N18; C-N20) |
| 3 Episodes | `/v3/seasons/{id}/episodes` | season | *n*/N packs, then season-critic checks | the STORY LOCK gate buttons |

**Every tab has these states** (master §3.2): empty; loading; running n%; **waiting for you** (an open
activation); **waiting for quota** ⏳ (with `retry_at`); **blocked** ⚠ (failed or reconcile, with the
retry action); error; done ✓ or locked 🔒. The Mode A option is disabled with its reason. Tier controls
(invoking `edit_tier`, §9) and per-episode Revise notes are on tab 3, which also shows **per-pack version
status during a round** (current / superseded / re-planning; C-M5) and the season-critic blast radius
while a repair round runs (§5.2).

## 11. Build packages (in order; `make check` + V1 `make pilot` green at every gate)

**Prerequisites:** A0; A1–A3 **shipped** (gates green, migration tail at 0035; C-N18); A5 for B6 only.
B's migrations are allocated in the B1 note after re-auditing the tail (from **0036**, §2.4); applied
migration bytes are never edited.

| Package | Builds | Gate | Design note |
|---------|--------|------|-------------|
| **B1** | V3 records + `V3ProductionLimits` + vocabularies; `v3_story_documents` + `StoryV3Store`; `v3_episode_story_bindings`; readers + `WORKFLOW_MISMATCH` guards (one pinned guard site per consumer, §2.3); **the §2.4 contract deltas (D2's migration, `V3DecisionCommand.target`); registers all five `story_v3.*` job types (C-M20)**; contract bump (v3 schemas; V1/V2 artifacts byte-identical) | B-T1, B-T2 | **Critiqued first** — gate checklist (C-N22): the §2.4 contract-delta register, the §9 command rows, §15/§16 risks and alternatives, and the deviations-considered list (none — C-M11 honours the master) |
| **B2** | Intake + Mode A refusal; `story_v3.propose`; the LOCK handler; **the proposal prompt (§7.3)** | B-T3 | With the diff |
| **B3** | `story_v3.bible` + the bible critic; tiers + promotion; **the bible and promoted-profile prompts** | B-T4 | With the diff |
| **B4** | `plan_episode` + continuity state + the episode critic + translation; **the architect and translation prompts**; **the B4 note pins the B-T5 DB-role mechanism (C-M16)** | B-T5, B-T6 | With the diff |
| **B5** | The season critic + repair + closure revalidation; the demand list; `StoryLockBindingV3`; the STORY LOCK handler + episode rows + bindings; **`edit_tier` + tier revalidation (C-M3)**; `create_extension` + the extension builder; **the critic prompts** | B-T7..B-T11 | **Critiqued first** (the lock transaction and the closure) — same gate checklist as B1 |
| **B6** | Tabs 1–3 | B-T12 | With the diff |

**Routing (C-N21):** GLM builds each package through `ai-route build -w`; Codex critiques the B1/B5
notes and reviews every package diff through `ai-route review` (the workspace's provider bridge,
`~/.claude/scripts/ai_route.py`). One package at a time.

## 12. Acceptance (offline; real PostgreSQL for every transaction test)

| Test | Proves |
|------|--------|
| **B-T1 (V3-AT-19)** | Migration upgrade on a **populated V1 + V2 database** (fixture records named in the B1 note: V1 seasons/episodes/approvals and V2 packs incl. historical 180–300 s and 1–10 values — C-N15): every V1/V2 record still validates under its own schema; recomputed hashes are byte-identical; no row is deleted or rewritten; the V1/V2 generated contracts show no drift (committed `ast.dump` fixtures assert AST-identical validator source) |
| B-T2 | Version selection: V3 validators reject 180 s and 10-episode V3 records; V1/V2 validators unchanged (AST-identical source, as B-T1); **every guarded entry point from §2.3, enumerated through a shared fixture, refuses a V3 episode with `WORKFLOW_MISMATCH`** (C-M10) |
| B-T3 | Mode A refused before any write; Mode B → 2–3 proposals; **a proposal whose `episode_count` ≠ `requested_episode_count` is refused CRITICAL (C-M15)**. LOCK Approve/Revise/Reject through the A1 decision transaction: a stale binding is refused; idempotent replay; **a Revise regenerates the whole round with the notes carried (C-N3)**; Reject leaves `PROPOSED` and doesn't cancel |
| B-T4 | Bible sections in Joey order; a `[TBD]` in a render-required field → CRITICAL → repair → `BLOCKED (failed)` after 1 initial + 2 repair rounds (C-N9). Tier promotion rules (≥2 episodes, any line, ≥2 recognisable scenes; off-screen speaker; an extras-role speaker) |
| **B-T5 (V3-AT-18)** | **20 and 30 complete episodes planned with no asset, wardrobe-assignment, identity-lock or voice rows in the database.** **Mechanism (C-M16):** the test jobs run under a **restricted DB role with no privilege on the exact tables** `assets` + `asset_lineage` (`M/0004…sql:4/:41`), `voices` (`M/0002…sql:134`), `identity_locks` + `identity_lock_assets` (`M/0002…sql:254/:270`), `reference_versions` (`M/0002…sql:154`) and `v2_contract_documents` (`M/0019…sql:4`; wardrobe assignments are its `SceneWardrobeAssignment` rows, `:7`); the run **completes with no access attempted** and the families are asserted empty. The V3 writer opens no such table |
| B-T6 | `LlmStep` behaviour per call: a crash mid-call resumes by `logical_call_id` with no second model call; invalid output → a new attempt; **a refusal with `defer_reason='QUOTA_5H'` → `WAITING_QUOTA` with `retry_at`; provider-reason refusals project `WAITING_PROVIDER` (C-N16)**; a stale fence result is quarantined; runtime band, recap and CTA limits; **the episode critic default-off, and on when `MICRODRAMA_V3_EPISODE_CRITIC` is set (C-M14)**; every `FrozenLlmCall` references a manifest-registered prompt (C-M4) |
| **B-T7 (V3-AT-3)** | **All 24 packs fully renderable**: every scene has location + light, wardrobe for every visible character, props with holder and state; every line has TH/EN/ZH + emotion + an estimate. Defects come from **fake-LLM scenario scripts or new pack versions, never row edits into the append-only store (C-N17)**. The season critic catches each injected defect: **a premature secret, an impossible wardrobe day (both halves, C-M19), >2 speakers in a beat**; also >5 speakers in an episode, **a 4th distinct `location_key` (C-M13c)**, **an out-of-enum emotion (C-M17)**, an unpaid debt and **a seam thread `RESOLVED` in the finale (C-M9)** |
| **B-T8 (V3-AT-4)** | **Demand-list completeness:** every character, outfit, appearance state, prop + state, location + light, extras role and voice (with its emotions) used by any scene is listed with exactly its episodes and scenes; no orphan demand; IDs stable across a Revise that keeps the item; **one promotion → exactly one `promote_profile` call (C-M12); the `EXTRAS_ROLE` demand merges into the `CHARACTER` demand and pack references resolve to it — no duplicate identity demand (C-M7)** |
| B-T9 | STORY LOCK Approve: all N episode rows + `episode_tracks` + accounts + bindings in one transaction; a forced failure in any step rolls back everything; `content_revision` bumps; the cadence selector never creates V3 episodes; **`edit_tier` tier revalidation, incl. a refused demotion that would drop a voice or identity demand (C-M3)** |
| B-T10 | STORY LOCK Revise on episode *k*: only *k* regenerates; a later pack invalidated by *k*'s new continuity appears as `continuity-dependent` and blocks Approve until "Revise these too"; **one bible-section Revise, one seam Revise and one tier Revise: non-invalidated packs survive, closure revalidation runs (C-M18)** |
| B-T11 | `create_extension` eligibility (refused without `RELEASING`/`COMPLETE` or without the `SEASON` amendment); the extension builder plans new packs from a synthetic published canon without touching prior packs or approvals; **the §6.2 extension reinterpretations hold** |
| B-T12 | Tabs 1–3 with real routes and templates: each state in §10, **at most one primary action per tab (tab 2's is `Next`, navigation only — C-N20)**, per-pack version status on tab 3 (C-M5), a disabled Mode A with its reason |

## 13. Open questions: RESOLVED 12 Nov 2026

**Operator, 12 Nov: "B: all recs"** — every recommendation below is adopted as the decision.

| # | Question | Recommendation |
|---|----------|----------------|
| O-B1 | Active locations per episode: V1 caps 2 (`ProductionLimits`), for 3–5-minute episodes | **3** per episode, counted as distinct `location_key`s (§2.2). Cost is governed by the demand list and the forecast (C), not by this cap |
| O-B2 | Default requested episode count | **24** (AT-3's season). The operator chooses 20–30 **at intake**; at LOCK the choice is **which approved proposal**, or Revise — there is no count override at LOCK (C-M15) |
| O-B3 | Emotion vocabulary (the prompt's expression text; since 12 Nov, one neutral voice reference per speaker, not one per emotion) | **6 values** (§2.2); closed and rejection-tested (B-T7) |
| O-B4 | Role for the proposal call (master §10.1 lists Opus for bible/builder/critic, not the proposal) | **Opus** |
| O-B5 | LLM critics per episode, as well as per season, during the pilot (subscription quota) | **Season critic always; episode critic off by default** — `Settings.v3_episode_critic` (§5.1, C-M14); the deterministic critics always run |
| O-B6 | Should the B1 note keep V3 documents out of `v2_contract_documents` entirely? | **Yes** (§2): a new table avoids widening the V2 allowlist and its `schema_version = '2.0'` CHECK |

## 14. Requirement trace

| R-ID | Where |
|------|-------|
| R-1.1 | §3.1–3.2 (Mode B complete; Mode A disabled, **partial** by design: V3C-32, master §16.2) |
| R-1.2 | §2 `SeasonProposalV3` |
| R-1.3 | §3.3 |
| R-1.4 | §1.3, §7 (live LLM writer via the subscription `LlmStep`; live trend research **deferred**, O-1) |
| R-2.1 | §2 `SeasonBibleV3`, §4.1, §6.1 (TBD rules) |
| R-2.2 | §2 `CharacterProfile` |
| R-2.3 | §2 (ledgers), §6 (secret timing, payoff debts) |
| R-2.4 | §2 (camera package, palette, lighting language), consumed by C and D |
| R-2.5 | §4.1, §10 |
| R-3.1 | §1.5, §5.1, B-T7 |
| R-3.2 | §2.1 |
| R-3.3 | §2.1 `psychology[]`, §2 `ContinuityStateV3` |
| R-3.4 | §4.3, B-T8 |
| R-3.5 | §5.3 |
| R-3.6 | §5.1, §10 |
| R-3.7 (mechanism only; the milestone is F's) | §8, B-T11 (C-N19) |

**Findings resolved here:** V3C-4 (§1.4, B-T5); V3C-5 (§1.1, §2.3, B-T1, B-T2); V3C-26 (the seam part,
§8); V3C-32 (§3.1, R-1.1); MA19 (§2.2); V3R-4 (§4.2); N22 (§4.2).

## 15. Risks and limits (C-M21)

| Risk | Limit / mitigation | Owner |
|------|--------------------|-------|
| Bible output size / truncation (one `LlmStep` writes a large document) | schema validation + repair rounds catch truncation deterministically; the B3 note considers section-splitting if truncation is observed | B3 builder |
| Serial planning wall-clock and quota pauses (24 × 2 LLM calls through a max-concurrency-1 gateway with 5 h windows) | progress denominators (§10); waits surface as `WAITING_QUOTA`; rounds are the retry unit (§5.2) | Operator (pacing) |
| Repair-cascade cost (a continuity finding at episode 3 can touch 3–24 episodes) | the 6-episode round cap + impact preview + operator checkpoint (§5.2); blast radius on the wait state | Operator |
| Single-pass ZH translation becomes the record of truth | `text_zh` is a planning aid; delivered captions come from accepted native speech in E (master §4.7) | E |
| "No real people/brands/celebrities" is not machine-checked in B (C-M6) | prompt constraints + corpus screening only (`§3.2`); real enforcement is phase C output inspection (master §12.2) | C |

Master-level risks and their owners: master §18 (Joey licence, quota terms, throughput SLO).

## 16. Alternatives rejected (C-M21; one per major design choice)

| Choice | Rejected alternative | Why rejected |
|--------|----------------------|--------------|
| One `LlmStep` writes the bible (+ critic/repair rounds) | Decomposed multi-call bible assembly | one call keeps section coherence; repair bounds cost; truncation risk accepted (§15) |
| Episodes planned strictly in order | Parallel fan-out after the bible | each pack consumes `ContinuityStateV3(n−1)` — order **is** the continuity mechanism (master §4.3). (All-up-front planning itself is master §17's ruling) |
| Tier promotion after all packs exist | Promotion inline during planning | the triggers count appearances/lines/framings across the whole season (master §4.2); inline promotion would flap tiers |
| Proposal versions = rounds on one append-only record | A new record per round | keeps the V2 convention (regeneration advances the version, `S/story/script_maker.py:69`); the Reject reset is §2 (C-N7) |
| New `v3_story_documents` table | Widening `v2_contract_documents` | O-B6: avoids widening the V2 allowlist and its `schema_version = '2.0'` CHECK (`M/0019…sql:5`) |
| Whole-round LOCK Revise | Slot-targeted notes with byte-identical carry | master §4.1's note model is a new proposal revision; the carry exceeded it (C-N3) |
| Unmetered pilot; step keys named, no admission logic (§1.3) | Building step-key admission now | no metered adapter exists (O-5); A2's reservation machinery already consumes the keys (§2.4 D1) |
| Continuation via the last job of a round (§7) | A dedicated orchestrator/coordinator job type | the family adds no second job system (master §10.0/§17); A1's enqueue + `replaces_job_id` primitives suffice |

## 17. Finding map (Goldfish review → v0.4)

- C-B1 → §2.4 (register: D1–D4 + standing rule); §11 B1.
- C-M1 → §7.1 (idiom); §5.1–§5.2; §4.2; §3.3.
- C-M2 → §5.2 step 3; §5.5 (asymmetry); §10 (blast radius).
- C-M3 → §9 (command rows); §4.2 (`edit_tier` → B5, "tier revalidation"); §10; §11 (B3/B5).
- C-M4 → §7.3; §11 B2–B5; B-T6.
- C-M5 → §5.2 (Resume); §10 (per-pack status).
- C-M6 → §3.2; §15.
- C-M7 → §4.3; B-T8.
- C-M8 → §6.2 (extension reinterpretations); B-T11.
- C-M9 → §2 (thread `status`); §6.2; B-T7.
- C-M10 → §2.3 (guard sites, qa trio, shared fixture); §11 B1; B-T2.
- C-M11 → §2 (wraps `SeasonBible` + `RichBible`); §11 B1 checklist.
- C-M12 → §4.2 (policy/storage/order); §5.2; §7.1; B-T8.
- C-M13 → §6.1 (a, b); §2.2 (c); §4.3 (d); B-T7.
- C-M14 → §5.1; B-T6.
- C-M15 → §2.2; §3.2; §3.3; §13 O-B2; B-T3.
- C-M16 → B-T5; §11 B4.
- C-M17 → §2.2; B-T7.
- C-M18 → §5.3; §5.5; B-T10.
- C-M19 → §6.2; B-T7.
- C-M20 → §7.2; §11 B1.
- C-M21 → §15; §16.
- C-M22 → header (pins re-verified: master v0.4.6 §4.1/§4.2/§6; A2/A3 notes v1.0).
- C-N1 → §2 (`initial_continuity`); §2.1 (`cta`).
- C-N2 → §4.3 (proof-prop); §5.1 (season plan).
- C-N3 → §3.3; §16.
- C-N4 → §3.2 ("master §12.2").
- C-N5 → §2.3 (obligation phrasing).
- C-N6 → §2.2 ("D2 revised", DECISIONS:241–243).
- C-N7 → §2 (Identity).
- C-N8 → §6.1 (bible rules).
- C-N9 → §3.2; §4.1; §5.1; §5.2; B-T4.
- C-N10 → §2.1 (`story_time`).
- C-N11 → §4.1 (TBD linking).
- C-N12 → §3.1 (mode field).
- C-N13 → §7.1 (work IDs).
- C-N14 → header (status).
- C-N15 → B-T1; B-T2.
- C-N16 → B-T6.
- C-N17 → B-T7.
- C-N18 → §11 (prerequisites).
- C-N19 → §14 (R-3.7 row).
- C-N20 → §10 (tab 2); B-T12.
- C-N21 → §11 (routing).
- C-N22 → §11 (B1/B5 gate checklist).
