# Drama Box v3 — series production workflow: MASTER SPEC

**Version 0.4.6, 13 Nov 2026.** Author: Opus orchestrator. (v0.4.6 folds the two "as v0.1 §4.1/§4.2" clauses into §4.1/§4.2 and retires the v0.1/v0.3 snapshot files; no rule changes. v0.4.5 changed only the §6 "Voice by emotion" rule: one neutral voice reference per speaker, emotion carried by the prompt; DECISIONS "D2 revised again". v0.4.4 changed only the §10.0 schema-ownership sentence, per the A1 design note §3. v0.4.4 changes only the §10.0 schema-ownership sentence, per the A1 design note §3. v0.4.3 changed only the Botnoi catalogue clause in §4, from the operator's Botnoi facts; DECISIONS "D2 update". v0.4.2 changed only how LLM calls run: §1 rule 3, §4 bible note, §10.0 rows, §10.1, §16 A0 row; see [phase-A0-spec.md](phase-A0-spec.md) v0.2 §11. v0.4.1 changed the §10.0 `LlmService` row.)

**Status: BINDING MASTER.**
- Codex critique rounds 1–2 are applied: [codex-spec-critique.md](codex-spec-critique.md) (V3C-1..34) and
  [codex-spec-recritique.md](codex-spec-recritique.md) (V3R-1..12).
- The Goldfish review is applied: [goldfish/consolidated_review_report.md](goldfish/consolidated_review_report.md)
  (B1, MA1–25, MF1–2 and the nits); see §20.
- Phase specs (A0, A–G) are written and critiqued against this document before each build.
- Earlier versions live in git history only. v0.1 (sha256 `0a2677c9…`) and v0.3 (sha256 prefix
  `04f0c8e9f026aa62`) were committed as snapshot files in `5d79ae8`, e.g.
  `git show 5d79ae8:docs/microdrama-system/v3-workflow/SPEC-v3-v0.1.md`. Review reports that cite their line
  numbers refer to those revisions.

---

## 0. How to read this document

**Precedence (MA14).** Where sources conflict, the higher one wins:
1. The operator's latest dated instruction, recorded in [DECISIONS.md](DECISIONS.md).
2. [DECISIONS.md](DECISIONS.md).
3. [REQUIREMENTS.md](REQUIREMENTS.md): 68 R-IDs (R-1.1 … R-12.13, including R-3.7 and R-12.13 from its
   preamble).
4. **This master spec.**
5. (v0.4.6) The v0.1 baseline is no longer a source: its two inherited clauses are folded into §4.1/§4.2.

**Normative words (N29).** Bold declaratives and the words *must*, *never*, *only* and *requires* are
binding. *Should* is advice. Examples are illustrative.

**Numbering (MA21).**
- "Step N" and "tab N" mean the same thing: the UI tab numbering in §2.
- The operator's original numbering (in DECISIONS.md) swaps 8 and 9; §2 gives the crosswalk.
- **Gate names (MA22):**
  - **LOCK** = `SEASON_CONCEPT` = the legacy name "Gate 1".
  - **Gate 2** = `EPISODE_FINAL`.
  - New: `STORY_LOCK`, `CAST_LOCK`, `TEASER_FINAL`, `LAUNCH`.

**Glossary (MA16–MA18, N5–N8, N17):**

| Term | Meaning |
|------|---------|
| **ARISA** | The sibling AIVORA project on the same host (an AI-influencer studio). Its SFW image pipeline shares the **Nano Banana (Vertex) quota**, and its SFW picks site is the UI pattern reused here |
| **SPECTRE** | The sibling trading/education project. Its studio holds an earlier voice-audition flow (reference only) |
| **T031** | Drama Box task: live render, rights and cost qualification on Pika H3 Flex. IN_PROGRESS; the H-2 build hardens its benchmark controller |
| **T032** | Drama Box task: controlled live publication, community and membership tests. TODO |
| **T045** | Drama Box task: real RunPod/ComfyUI provider composition. DONE |
| **H-2** | The T031 benchmark recovery/reconciliation hardening build (`docs/microdrama-system/T031-H2-recovery-spec.md`) |
| **ai-route** | The workspace's single door for running headless model jobs on another provider (`~/.claude/scripts/ai_route.py`): quota checks, logging, duplicate guard |
| **Binder** | The T031 render pipeline's upload-binding component. It uploads references to the pod, seals them into a `PikaBindingContext`, and validates their bytes. Its byte validator requires non-empty uncompressed PCM WAV for audio |
| **Acquisition** | One rented GPU pod lease and its holds. "Acquisition-scoped" means bound to that lease |
| **Proof prop** | A prop a beat depends on as evidence (e.g. the recipe book being stolen). It is never droppable |
| **Headless sheet** | A full-body view without a head, used for wardrobe. It never counts as an identity reference |
| **Planned-terminal canon** | The canon state at the planned end of the season (all packs). **Published canon** is the state as of the last published episode |
| **Spoiler/reveal authority** | The secret ledger's planned reveal episode per fact. Teasers and recaps may not show a fact before its reveal |
| **Crowd walla** | Unintelligible background crowd murmur |
| **Guards** | The standard migration triggers on every table: no delete, no truncate, integer-only money/time |
| **Guardian-owned** | The contract package (versioned schemas) changes only through its guardian review |

---

## 1. Goals, success criteria, non-goals, hard rules

**Goal:** turn a one-line idea into a **20–30 episode, ~2-minute Thai microdrama** that is slower and
cinematic (**average shot 4–5 s**, held emotional beats; N27), released **daily at 19:00
Asia/Bangkok** on YouTube Shorts, TikTok and Facebook, and **extendable** by operator decision.
Characters, voices, wardrobe, props and locations stay consistent across the season and into later
seasons. Everything is driven from **dramabox.aivora.agency**, with **five content gates plus LAUNCH
calendar approval**.

**Season success criteria (N14).** A season succeeds when:
1. every scheduled slot reaches `PUBLISHED_VERIFIED` on its approved date, or is `HELD` with an approved
   recovery;
2. total cost is ≤ the season cap (§12.3);
3. every episode passed Gate 2 with no open CRITICAL finding;
4. the quality thresholds in §16.3 hold.

**Non-goals (v3.0):**
- Instagram.
- Captions beyond TH/EN/ZH.
- Approvals from Telegram.
- Multi-operator teams.
- Automatic (unapproved) extension.

**Hard rules:**
1. **Paid effects:** hold → effect → record. Every paid call reserves budget first and records its
   receipt after. Ambiguous outcomes are reconciled before any resubmission, and exposure stays held
   until resolved. This is the canonical budget/recovery discipline hardened in T045 and H-2.
2. **Gates:** no gate passes without a human approval event bound to the current hash.
3. **LLM calls** are resumable job steps (`LlmStep`) over the host LLM gateway (§10.1, amendment
   v0.4.2). During the pilot they use the operator's Claude subscription via the isolated `dramabox-llm`
   ai-route role. **Precedence (V3C-1):** the operator's
   subscription-first pilot instruction (11 Nov) supersedes REQUIREMENTS' API-only sentence. The
   full-season provider is an operator decision after measurement.
4. **Content:**
   - original fictional characters only;
   - no real people, brands, or celebrity likeness or voice;
   - no text in generated frames; text is added in edit.

   Output inspection (§12.2) enforces this, not prompts alone.
5. **Offline first.** Every provider has a fake adapter and offline acceptance tests. Live use requires
   the qualified production composition (§10.6) and a per-provider switch that fails closed.

---

## 2. Stages, gates, numbering crosswalk

| Tab | DECISIONS step | Scope | Who acts | Gate |
|-----|----------------|-------|----------|------|
| 1 | 1 Script Maker | Season | Operator enters; system proposes | **LOCK** (`SEASON_CONCEPT`, gains Revise) |
| 2 | 2 Bible | Season | System | reviewed at STORY LOCK |
| 3 | 3 Episode builder | Season | System | **STORY LOCK** |
| 4 | 4 Character bible | Season | System generates; operator picks and uploads voices | **CAST LOCK** |
| 5 | 5 Directing | Episode | System | — |
| 6 | 6 I2V + voice | Episode | System | — |
| 7 | 7 Edit | Episode | System | — |
| 8 | **9** Captions/hashtags/thumbnail | Episode | System drafts | reviewed at Gate 2 |
| 9 | **8** Review + approve | Episode | Operator | **Gate 2** |
| 10 | 10 Teaser | Season | System + operator | **TEASER_FINAL** |
| — | (calendar) | Season | Operator | **LAUNCH** (§9) |

**Crosswalk (N19):** decision D3 ("draft metadata before Gate 2") means the operator's step 9 (metadata)
runs *before* their step 8 (review). The tabs therefore show metadata as tab 8 and review as tab 9. The
labels on screen keep the operator's names.

### 2.1 Gate behaviour

- **Actions:** Approve, Revise (with notes), Reject. CAST LOCK uses staged picks plus one Lock (§4.4).
- **Binding:** every decision binds the exact content hash and revision displayed; a stale page cannot
  decide. Human session, CSRF and an idempotency key are required (the existing `review/api.py` rules).
- **Revise** regenerates the requested units, then revalidates the dependency closure (§12.6). Newly
  invalid dependents block pending scoped revision authority. All revisions are kept.

### 2.2 State model (V3C-7, V3R-5)

**Production and release are separate tracks.** A season may be producing episode 12 while releasing
episode 6.

| Track | States |
|-------|--------|
| Season planning | `IDEA → PROPOSED → LOCKED → BIBLE → PLANNED → STORY_LOCKED → CASTING → CAST_LOCKED` |
| Season release | `NOT_SCHEDULED → CALENDAR_PROPOSED → LAUNCH_APPROVED → RELEASING → COMPLETE` |
| Episode production | `PLANNED → DIRECTED → RENDERING → EDITING → DRAFTING → AWAITING_REVIEW → APPROVED` |
| Episode release | `UNSCHEDULED → SCHEDULED → PUBLISHING → PUBLISHED_VERIFIED`, plus `HELD`, `MISSED`, `PARTIAL` (a per-destination release state; see N43) |

- **Extension:** it has its own planning scope and STORY/CAST lifecycle. `EXTENDING` is an **activity
  flag**; the release track stays `RELEASING` or `COMPLETE`.
- **Waits and failures** belong to the scope and track they affect, and never suspend unrelated approved
  releases.
- **Paid work** has exactly **one persisted lifecycle**: the existing job + provider-operation records
  (§10.0). Track states, pick states and side states are **projections** of it. The mapping is in §10.0.
- **Each phase spec gives a command table:** command, allowed states, prerequisites, the transaction
  (locks in the shared order), events, jobs, and the replay result.
- **Scheduler selectors** are replaced so that no V3 job bypasses STORY LOCK or CAST LOCK. The legacy
  selectors remain for V1 seasons only.

---

## 3. UI: dramabox.aivora.agency

### 3.1 Hosting

- The same FastAPI/Jinja app, behind the Coolify Traefik proxy with Let's Encrypt TLS, upstream
  `127.0.0.1:8093` (`microdrama/deployment/staging/DOMAIN-RUNBOOK.md`; N15).
- Owner-only session login, CSRF, secure cookies.
- **Domain activation requires** the qualified production composition, the scheduler service and a proven
  backup restore (§10.6), plus the operator's dated authorisation and the operator-created DNS record.
- Private mock staging stays.

### 3.2 Stepper and navigation (V3C-28)

- **The header** carries tabs 1–10 plus Launch. Each shows a status icon and a progress bar:
  - not started;
  - running n%;
  - **waiting for you**;
  - done ✓ (an automatic stage completed);
  - locked 🔒 (a gate approved);
  - waiting for quota ⏳;
  - blocked ⚠.
- **Tabs 5–9** act on a **selected episode**, picked from the Episodes board or the header switcher.
- **Primary action:** each tab has **at most one** primary action (N18). `Next` only navigates past a
  completed automatic stage and never approves; only gate buttons advance gates. A disabled button shows
  its reason.
- **Operations screens:**
  - Launch calendar (§9);
  - Amendment impact (§12.6);
  - Extension (viewership windows, §4.3);
  - Recovery (blocked/unknown units with retry, reconcile and resolve);
  - Quota/provider waits;
  - Costs (§11).
- **Home page:** waiting for you; running; blocked; quota waits; today's releases; budget state.
- **Live updates:** poll the extended `progress.json` every 5 s while the page is visible, in vanilla JS
  (the ARISA SFW picks pattern).
- **Per tab,** each phase spec defines the route, scope, progress denominator and primary action, plus the
  empty, loading, error and waiting states.

### 3.3 Dramabox Bot (V3C-31)

- A dedicated Telegram bot, connected 11 Nov. Its token and chat ID are FILE credentials (paths in the
  runbook; N2). The token must be rotated before go-live.
- A durable outbox:
  - one event per source event (deduplicated creation);
  - bounded attempts, each with a timeout;
  - an ambiguous send is retried at most once and flagged as possibly duplicated;
  - a dead letter after the limit;
  - provider message IDs recorded.
- **Deep links only; no approvals.**
- **Events:** gate waiting; picks or voice uploads needed; review ready; published/failed/partial; blocked;
  quota wait; budget 80%/100%; buffer low; throughput below SLO (§9.4); daily 09:00 summary.

---

## 4. Steps

Schemas are defined normatively in the phase specs. This section fixes their content and behaviour.

### 4.1 Step 1: Script Maker → LOCK

- **Mode B (one-line title)** is complete in v3.0.
- **Mode A (trend research)** is visibly disabled with a reason until qualified source adapters exist
  (freshness, provenance, failure behaviour, research budget). The v3 milestone stays labelled
  **partial** until then (V3C-32).
- **Proposal fields:**
  - title TH/EN, logline, premise, thesis question, genre/tone;
  - episode count and target length;
  - main cast briefs (3–6);
  - season promise, escalation shape, ending + extension seam;
  - why it would trend;
  - originality and rights notes.
- **Episode count** at LOCK is 20–30. Extensions append an approved N; there is **no extension ceiling of
  40** (N20). Target length is 120 s (105–135 s), including the recap (≤10 s) and the CTA (≤5 s).
- **Every duration and count validator** is replaced consistently: `SeasonScope`, `EpisodePlan`,
  `EpisodePack`, intake and candidates. Historical records validate under their schema version.
- **LOCK actions:** Approve, **Revise** (notes → a new proposal revision), Reject. The SQL, history and
  jobs change together.

### 4.2 Step 2: Bible, and character tiers

- **Bible:** a `SeasonBibleV3`, wrapping the existing `SeasonBible` and `RichBible`:
  - Joey's section order: premise → thesis → timeline → era aesthetics → world rules → locations →
    factions → characters → relationships → story engines → production rules;
  - production rules: a season **camera package** (one look: spherical or anamorphic, a lens family, a
    movement register), palette, lighting language, and a **pacing rule** (slower, cinematic: average shot
    4–5 s, held emotional beats, no frantic cutting);
  - the secret ledger and the season ledger.

  A `[TBD]` in a field needed for render fails the critic. V3 LLM calls go through `LlmStep` (§10.0);
  the existing synchronous `LLMProvider` protocol stays for offline and legacy callers only.
- **`CharacterProfile`:**
  - narrative function, visual lock, backstory, psychology by story state;
  - speech (register, texture, cadence, Thai politeness and pronouns, code-switching), movement and
    stillness profiles;
  - drift exclusions;
  - goal, strategy, flaw, secrets;
  - a voice descriptor (for the Botnoi shortlist, §4.4.4).
- **Tiers:**

  | Tier | Who | Bible content |
  |------|-----|---------------|
  | `PRINCIPAL` | Main cast | Full profile |
  | `SUPPORTING` | Recurring non-principals (secretary, personal doctor, driver…) | Lighter profile; speech profile + voice descriptor only if they speak |
  | `EXTRA` | One-off background roles | `ExtrasRole` only |

- **Promotion (automatic in step 3, editable at STORY LOCK):** a non-principal becomes `SUPPORTING` if it
  appears in **≥2 episodes**, has **any line**, or is framed recognisably in **≥2 scenes**. An off-screen
  speaker is always at least `SUPPORTING` (N22).
- **Speaking cap (MA19, defined once):** at most **5 distinct dialogue speakers per episode**, counting
  every speaker including off-screen ones, and at most **2 speakers per shot**.
- **Tier integrity (V3R-4):**
  - Overrides never waive speaker counting, the locked-voice requirement or identity coverage.
  - Demands are revalidated after every tier edit, before STORY LOCK.
  - Identity QA (§4.6) covers every recognisably framed locked character.

### 4.3 Step 3: Episodes → STORY LOCK

- **Planning authority (V3C-4):** initial planning requires the **approved LOCK scope**, never the STORY
  LOCK that approves its output. Packs reference **stable logical demand IDs**: character, outfit,
  appearance state, prop/state, location/light, extras role. Step 4 binds these to asset versions in
  **`CastBinding`**. All planned episode rows are created at STORY LOCK, independently of the release
  cadence; the writer needs no identity lock to plan.
- **`EpisodePackV3` (V3C-5):** phase B publishes the schema, a field-by-field V1 (`EpisodePlan`,
  `Script`) and V2 (`EpisodePack`) mapping, IDs, revisions, hashes, storage, compatibility readers and the
  consumer migration order. Content (N28):
  - title TH/EN; synopsis;
  - a recap plan;
  - scenes, each with:
    - `StoryTime` (story day, local time, setting);
    - location ID + light state;
    - visible cast (incl. extras);
    - props + holder + state;
    - wardrobe + appearance states per character;
    - beats and reveals;
  - the cliffhanger;
  - dialogue lines: Thai text, EN, ZH, speaker, **emotion tag**, delivery note, estimated duration;
  - CTA intent;
  - character psychology at the start and end of the episode.
- **Generation:** episodes in order, carrying a running continuity state (including **wardrobe history
  across episodes**); a critic per episode; a season critic.
- **Demand list:** every logical item, with the episodes and scenes that use it. It drives the step-4
  forecast and the **image-volume projection (§10.4)**.
- **STORY LOCK:** approval binds the bible + all packs + the demand list. Revise regenerates the requested
  packs, then revalidates the closure (§12.6).
- **Extension seam (phase B):** the season plan names the threads that can grow without breaking the
  ending, and STORY LOCK binds them.
- **Extension (V3C-26; decision and integration in phase F):**
  - An append-only extension scope, linked to the prior STORY/CAST locks and to both the planned-terminal
    and published canon.
  - Existing approvals are preserved. New packs bind explicit cast versions; only new assets need picks.
  - Available from `RELEASING` or `COMPLETE`, with an explicit continued or resumed calendar.
  - **Viewership windows (MA24):** 24 h / 72 h / 7 d performance per episode, from the existing analytics
    snapshot windows (`analytics/snapshots.py`), fed by the platform insights adapters (T032). Freshness
    and unknowns are shown. Extension is always a manual decision.

### 4.4 Step 4: Character bible → CAST LOCK

#### 4.4.1 Staged picks (V3C-8)

- **Pick** records a vote only. **Generate next** is an operator *action* (N23) that queues dependent work
  against the selected parent revision.
- **Required human picks:**
  1. face lock (principals and supporting characters);
  2. outfits;
  3. appearance states;
  4. extras looks;
  5. prop/state;
  6. location master per light state;
  7. base voice (§4.4.4).
- **Derived assets:** sheet views, expression sets, location coverage plates, and the season music/SFX
  libraries (§4.7). They are accepted, or re-rolled, inside the final **CAST review**.
- **A parent re-roll** invalidates its dependents; unrelated picks stay valid.
- Pick and vote states are **UI projections** of the job lifecycle (§10.0).

#### 4.4.2 Asset packages by tier

| Tier | Package |
|------|---------|
| `PRINCIPAL` | Face lock (an 18% neutral gray field, directionless light, no baked lighting; castkit); all sheet views; expression set (neutral/signature/extreme); outfits per story day; appearance states; voice expression family |
| `SUPPORTING` | Face lock; front + tight-face views; 2 expressions; outfits per story day; appearance states only if scripted; voice only if they speak |
| `EXTRA` | 2–4 looks per role; no continuity; no voice (crowd walla only) |

- **Locations (scenecraft):** a master plate per light state, then coverage plates with identical
  geometry, time and weather.
- **Images:** Nano Banana Pro through the image generation adapter (§10.3), with castkit and scenecraft
  as structured prompt builders.

#### 4.4.3 Wardrobe and continuity (V3C-10)

- **One canonical setting ID** across planning, assignment and directing. Today `assign_scene_wardrobes`
  uses `location_id` while the compiler compares `StoryTime.setting`; **v3 fixes this** (N30).
- Wardrobe history persists across episodes.
- Timed changes use scene-relative intervals. A shot crossing an incompatible outfit boundary is split.
- Composition and precedence are defined for simultaneous appearance states.

#### 4.4.4 Voices: Botnoi Web Studio V4 (operator decisions 11 Nov)

The Botnoi API (v1/v2) has no expressions. V4 inline tags exist only in Web Studio, and not every voice
has V4.

1. **Expressions needed:** the closed set per speaking character, from the packs' emotion tags.
   `neutral` is always included.
2. **Base-voice shortlist (V3R-11):**
   - The system ranks the **Botnoi voice catalogue** against the voice descriptor and shows **2–3
     suggestions with reasons**. No audio is generated.
   - **The catalogue has two sources (amendment v0.4.3; DECISIONS "D2 update", 11 Nov):**
     - (a) auto-imported from Botnoi's public speaker-list endpoints (`get_speaker_data`,
       `get_speaker_data_v2`; no token): gender, age group, voice style including regional accent,
       speech style, sample WAV;
     - (b) operator additions in `botnoi-v4-voices.csv` for marketplace and Studio voices the API lacks
       (elderly, monk, …).
   - The fields are `source, voice_name, speaker_id?, gender, age_group, accent, style_notes, has_v4,
     voice_kind (cast | api | community), last_verified`.
     - `has_v4` is operator-confirmed in Studio, because V4 is not in the API. An unconfirmed voice is
       flagged.
     - **Community voices need per-voice operator approval** in their rights record.
     - `last_verified` addresses freshness (N13); entries older than 90 days are flagged.
   - The operator auditions the shortlist in Botnoi and records the pick (or "other", with a reason).
3. **Casting sheet:** per expression, a 10–15 s Thai script from the character's own lines, with
   suggested V4 inline tags. The rule: **one V4 voice per character for every expression**.
4. **Upload:** one slot per `(character, expression)`, plus a zip bulk import. In the zip, files must be
   **named exactly** `<character_id>__<expression>.wav` or `.mp3` (N23).
5. **Trust boundary (V3R-1):** uploads are **untrusted bytes**.
   - Owner scope, CSRF, the expected revision and an idempotency key are required.
   - Files go to a private quarantine.
   - Bounded: request size, archive entries, expanded size, decoded audio length, processing time.
   - Rejected: path traversal, absolute paths, links, duplicate slots, unknown keys.
   - Storage paths are generated by the server, and decoding is isolated.
   - **Failed imports never overwrite accepted assets.**
   - Phase C sets the numeric limits and tests hostile inputs.
6. **Normalisation and assessment (V3R-2):**
   - A versioned normalisation profile (PCM subtype, sample rate, channels) compatible with the binder.
     **Only the resulting PCM WAV is registered**, and it must pass the binder's byte validator. Source and
     normalised hashes are both kept.
   - Recorded technical checks, plus an automated or human assessment of Thai speech, transcript,
     single-speaker suitability, expression and consistency with the base voice.
   - **V4 origin and voice identity are operator attestations,** labelled separately from machine checks.
   - Changing the base voice invalidates the whole family. Changes after lock go through §12.6.
   - Rights: `OPERATOR_ATTESTED` (O-11).
7. **Audition:** side-by-side, with per-variant replace.
8. **Pilot observation:** check whether tag vocalisations (e.g. `[laughter]`) leak into Pika's output.
   If they do, switch to tag-free scripts.

#### 4.4.5 CAST LOCK (V3C-6)

- A **season-scoped cast-lock contract**: the STORY revision, complete membership (every pick and derived
  asset, and every voice WAV), and the provenance of the human approval.
- Migrations:
  - the identity-lock readers;
  - the SQL (today `source_episode_id` + `release_package_hash` are required);
  - **removing episode-1 lock creation from the V3 Gate 2 path**.
- Lock atomically freezes the members and binds **every** episode row. Episodes created later bind the
  applicable lock version (R-12.1).
- **Season-2 reuse:** a locked cast, voices and locations can be imported with lineage, and rights are
  revalidated.
- **Cost:** step 4 runs inside the season-setup sub-budget (§12.3), with a forecast first. Re-rolls are
  counted.

### 4.5 Step 5: Directing

- **One authoritative compiler (V3C-13):** the director LLM (the shotcaller method) produces
  `ShotPlanV3`. Phase D maps it onto the persisted directing manifests and render requests: it replaces
  or feeds the V2 `BeatIntent` compiler; there is one path.
- **Clip length:** only qualified frame counts (T031: 124 frames at 24 fps ≈ 5.17 s). Edit may trim at
  measured, speech-safe boundaries.
- **Supported shots:** zero-, one- and two-speaker.
- **Validation:** total duration, including recap, transitions and CTA; the shot state resolver
  (including timed wardrobe) runs before dispatch.
- **Split cost (MA11):** a shot split reports the projected clip count and cost against the remaining
  episode budget.

### 4.6 Step 6: Render + clip QA

- **Production native-render adapter (V3C-14):** built over the accepted T031 transport/recovery
  primitives. It is distinct from the benchmark controller.
  - Verified acquisition-scoped binding context at both binding stages: upload and graph binding.
  - Supports 0, 1 and 2 speakers; registration, polling, QA handoff, retries, shutdown.
  - **Phase D requires the T031 qualification record and `feat/t031-fix3` merged** (N36).
- **Clip QA (V3C-16/17, V3R-4):**
  - **Required checks per shot, with thresholds:**
    - Thai ASR word match;
    - **face identity for every recognisably framed locked character**;
    - **wardrobe/state/prop continuity on every shot**;
    - technical checks.
  - Voice similarity and lipsync are scored where a qualified detector exists. Otherwise they are a
    **recorded human check at Gate 2**.
  - **Unknown ≠ PASS.**
  - Detector weights must be commercially licensed. The render + QA image is benchmarked on the A40
    (load/offload, OOM handling, deadlines), and QA and idle GPU time are metered.
  - Implements the existing `ASRProvider` / `MediaReviewProvider` protocols (§10.3).
- **Acceptance:** missing or rejected required clips block assembly. A diagnostic preview is marked
  non-approvable. Critical findings block Gate 2.

### 4.7 Step 7: Edit

- **Native audio, end to end (V3C-15):**
  - native clip-audio sources plus utterance alignment in the EDL;
  - synchronised trims through masters, crops, hooks, recap and fades;
  - **all caption cues come from accepted native speech**;
  - no synthesised replacement dialogue, and no duplicated ambience.
- **Recap:** ≤10 s, bound to the preceding approved episode version; rebuilt if that version changes.
- **CTA (V3R-6):** resolved from the calendar revision it records a dependency on: the next air time, a
  confirmed continuation, or a finale follow message. It never promises an unapproved extension.
- **Transitions:** fade/xfade in both exporters with a synchronised timeline.
- **Music (V3C-20):** a Drama-owned YuE2 job:
  - a pinned instrumental recipe;
  - A40 qualification;
  - duration and loop targets;
  - vocal-leakage inspection;
  - rights;
  - canonical holds, recovery and finality.

  **The season music library is generated in step 4's job graph**, inside the setup sub-budget (N16).
- **SFX:** the source is §7. Season library plus per-episode gaps.
- **Mix:** −14 LUFS integrated, −1 dBTP. Thai captions burned in; EN and ZH as tracks delivered per §9.

### 4.8 Step 8: Metadata and thumbnail drafts

- **Drafts per release slot** (§9.1), in TH, with EN/ZH where the destination supports them:
  - title, description, caption;
  - hashtags (the platform limit);
  - CTA;
  - the AI-disclosure text.

  Grounded in the pack; no spoilers beyond the episode.
- **Thumbnail:**
  1. 3 key-art variants (Nano Banana, from locked assets).
  2. Thai title composited locally with a licensed font.
  3. Output inspection (§12.2).
  4. The operator picks one at Gate 2.

### 4.9 Step 9: Gate 2

- The existing page, plus:
  - prefilled drafts;
  - the thumbnail pick;
  - caption tracks;
  - recap/CTA previews;
  - QA results (including the recorded human checks);
  - costs.
- **Gate 2 approves content.** For **later episodes** (those after LAUNCH's initial five; N21), Gate 2
  also binds the episode's approved calendar slot (§9).

### 4.10 Step 10: Teaser

- 30–60 s from approved episodes, under the spoiler/reveal authority.
- `TEASER_FINAL` gate.
- A `PROMO_CUT` slot at premiere − 3 days.
- `PreviewPlan` is extended into a season teaser contract: multi-episode sources, a spoiler limit, a
  release obligation.

---

## 5. Continuity model

| Concept | Record | Set by | Checked where |
|---------|--------|--------|---------------|
| Story day/time | `StoryTime` per scene | Episode builder | Pack critic, directing validation |
| Wardrobe | `WardrobeBible` + `SceneWardrobeAssignment` + timed events (canonical setting ID, history across episodes) | Wardrobe planner | Shot resolver (timed), clip QA **on every shot**, Gate 2 |
| Appearance state | `AppearanceState` (kind, days/scenes, asset) | Episode builder → picks | Shot resolver, clip QA |
| Prop state + holder | `PropSheet` + `StateEvent` | Episode builder | Holder/hand validators |
| Location light | `LocationLayout.light_states` + scene light state | Episode builder | Resolver picks the matching coverage plate |
| Extras | `ExtrasRole` + looks | Episode builder → picks | Director |
| Knowledge/secrets | Secret ledger | Bible | Pack critic, director, teaser/recap |

## 6. Reference selection per shot (V3C-11, V3C-12, V3R-3)

- **Reference schema:** keyed by shot-visible subject × role × view × outfit/state composition ×
  location/light variant, with defined cardinalities and current-rights checks. Views are resolved before
  exact binding validation. The style reference is a PNG; **a moving video is never passed as an image
  reference.**
- **Budget (N7):** ≤9 image references and ≤3 audio references per clip. These are the pinned Pika H3 Flex
  Ref2VA workflow limits from the T031 benchmark packet.
- **Mandatory (never dropped):**
  - identity-bearing face views for visible principals and recognisably framed `SUPPORTING` characters (a
    headless sheet never counts as identity);
  - the required wardrobe/state;
  - proof props;
  - the necessary location plate.
- **Over budget:** drop optional bindings only, with reasons. Otherwise block and send the shot back to
  directing to simplify or split. (The v0.1 "qualified composite" option is **removed**; N32.)
- **Voice and emotion (operator, 12 Nov; supersedes the V3R-3 per-emotion variants):**
  - **One CAST-locked neutral voice reference per speaker** (Botnoi). Botnoi Studio offers no usable
    emotion control, only inline non-speech tags (sigh, breath, sniff, laughter, …), so per-emotion
    variants are not produced.
  - **The prompt carries the emotion:** it states each line's expression and delivery explicitly (V3R-3
    kept). The shot's emotion tag (the dominant emotion: the line with the longest estimated spoken
    duration; a tie goes to the earlier line) is persisted and drives that prompt text, never a reference
    swap.
  - **A missing, corrupt or unapproved neutral reference blocks dispatch.**
  - **Pilot exit criterion (MA12):** P1 must show emotional and mixed-emotion shots rendering the intended
    expression in at least **80%** of cases, judged by the recorded Gate 2 human assessment. T031's S05
    (grief) and S06 (anger), both run from neutral references, are the first evidence. Below that, the
    **pre-agreed contingency** is to split coverage at speech-safe boundaries so each shot carries one
    expression. Switching to it needs an operator decision, shown with its projected clip/cost impact.

## 7. Audio providers (single normative home for voice, SFX and music sources; MA20)

- **Character voices:** operator-made in Botnoi Web Studio V4 and uploaded (§4.4.4). No voice API is on the
  critical path.
- **SFX (V3R-9):** ElevenLabs Sound Effects through **OpenRouter or fal.ai, the cheapest *eligible*
  route.**
  - Phase C qualifies each route's model/endpoint, commercial basis, settings and billing units.
  - Equivalent requests are compared at current, all-in, bounded prices, and the maximum authorised charge
    is reserved.
  - **Unknown capability, terms or price makes a route ineligible, never zero-priced.** If none
    qualifies, block.
  - The chosen route is persisted; ambiguous submissions are reconciled before any switch.
  - (fal.ai lists `fal-ai/elevenlabs/sound-effects/v2` at $0.002/s with a commercial label; OpenRouter is
    unverified.)
- **Music:** the Drama-owned YuE2 job (§4.7).
- **Pika native audio** is the dialogue/ambience source. Botnoi samples only condition the voice.

## 8. QA

Clip QA (§4.6) plus the existing episode-level technical and observation QA. Unknown coverage is shown
and never PASS. Required checks that can't run automatically are recorded as human assessments at
Gate 2. (§8 is kept only as a pointer; N25.)

## 9. Release, calendar, slots, throughput

### 9.1 Slot matrix (V3C-24)

- One **full-episode post per destination**, in TH, on YouTube Shorts, TikTok and Facebook (Reel or video
  route per T032).
- EN and ZH are delivered as **caption tracks**, not separate posts: YouTube caption upload; TikTok and
  Facebook caption files where supported. Otherwise burned-in variants, a phase F decision **made by the
  operator** (O-8; N35).
- Delivery is verified by readback. Unsupported required capabilities (including Facebook AI disclosure)
  **hold** the slot until T032 qualifies them. Instagram is excluded.

### 9.2 Calendar and authority (V3R-6)

1. A versioned calendar is **proposed before editing**: premiere date, daily 19:00 Asia/Bangkok, teaser at
   premiere − 3 days. Date-bearing content records its dependency on the revision.
2. **Gate 2 and TEASER approve content.**
3. **LAUNCH** binds the exact calendar revision, the stable slot identities and the current approval
   hashes. Initial activation requires current approvals for the **first five consecutive episodes and
   the teaser**.
4. Later episodes bind their slot at Gate 2.
5. **Dispatch requires both** content and calendar authority.
6. **Rescheduling** rebuilds the affected date-bearing content and requires renewed content approval.
   **Published media is immutable.** The reschedule screen lists already-published CTAs that the change
   makes inaccurate, and the operator may approve a corrective community post (N11).
7. Phase F defines V3 publication compatibility (today `ReleaseSlotPlan` requires a schedule) **without
   reinterpreting historical dated approvals**.

### 9.3 Dependencies and failures

- **The teaser gates the premiere:** episode 1 depends on verified teaser publication per destination.
  A late or failed teaser holds the premiere pending an approved recovery or reschedule.
- **Each slot depends on its predecessor** per destination.
- **A rejected or unready episode** near its air time → `HELD`, successors held, and the bot alerts with
  options: repair, swap or push (each needs approval).
- **Partial destination failure** → `PARTIAL`, with per-destination retry/reconcile. A post is never
  duplicated; only proven absence re-arms a slot.

### 9.4 Throughput SLO (MA11)

- **Required sustained production while `RELEASING`:** ≥ **1.25 approved episodes per day** at cost ≤ cap.
- **Catch-up capacity:** ≥ **2 episodes per day** for 2 consecutive days.
- **Buffer:** ≥3 days of approved episodes ahead of release; the bot alerts below 2.
- **Measured:** P2 and live operation measure the actual sustained rate (render + QA + edit + review
  turnaround). Below the SLO, the bot alerts and the operator decides (more GPU parallelism, pace or
  start date).
- **LIVE acceptance requires** measured throughput ≥ the required rate at cost ≤ cap (§16.3).

---

## 10. Platform: reuse, providers, composition

### 10.0 Reuse of existing infrastructure (MA1–MA4, binding)

**The v3 system adds no second job system and no second ledger.**

| v3 concept | Is implemented by (existing) | v3 adds |
|------------|------------------------------|---------|
| Generation unit (all paid work) | `core/jobs.py` **JobService** (idempotent semantic-key enqueue, leased claims, bounded attempts, never-blind-requeue reconciliation) **+** `contracts/cost.py` **ProviderOperation** (one external call: submit → status → reconcile, with request hash, client token, attempt, reservation, external ID, deadline) | New queue lanes (`image`, `voice_intake`, `sfx`, `music`); quota admission; a `Deferred` handler outcome mapped to the existing attempt-preserving `defer()` (phase A) |
| `LlmService` | **`LlmStep`** (amendment v0.4.2): inside its owning job, each call is a `ProviderOperation` of the **unmetered kind `llm.subscription`**, submitted to the host **LLM gateway**; the handler returns the existing `WaitExternal` outcome while the call runs, so no lease is held and the worker isn't blocked. **There is no separate `llm` queue lane.** The synchronous `LLMProvider` protocol stays for offline/legacy callers and refuses the subscription route | Isolation profile, quota admission, machine-result capture, per-invocation systemd units (§10.1); the gateway (phase A0 spec v0.2) |
| Usage and cost records | `contracts/cost.py` **UsageReceipt** (measured only) in `charges`, plus **`cost_allocations`** for shared cost; `budget/reports.py` views | A companion **`QuotaObservation`** record (subscription windows, credits; never money), linked to the job; `llm_invocations` (estimates, never cash). **Subscription calls carry no reservation, no `UsageReceipt` and no charge** (guardian-approved exemption for the unmetered kind only); extended report views → the Costs page |
| Image / SFX / music providers | `contracts/providers.py` **GenerationProvider** (submit/status/reconcile/fetch_output + reservation) | Adapters: Nano Banana, fal.ai/OpenRouter SFX, YuE2 |
| Clip QA | **ASRProvider** + **MediaReviewProvider** | On-pod detectors (§4.6) |
| Amendment/invalidation | `targeted_invalidation`, `invalidated_shot_ids`, Gate 2 targeted repair | A coordinator + revision fencing that subsumes these (phase A; N38) |

**State mapping (one persisted lifecycle):**

| Job / provider-operation outcome | Pick/UI projection | Track side state |
|----------------------------------|--------------------|------------------|
| queued / leased | `QUEUED` / `GENERATING` | — |
| succeeded | `READY` (after vote: `VOTED`; after derivation: `DERIVED_READY`/`ACCEPTED`) | — |
| retry later (bounded) | `FAILED_RETRYABLE` | `WAITING_PROVIDER` or `WAITING_QUOTA` (by cause) |
| needs reconciliation (unknown) | `UNKNOWN` | `BLOCKED` until reconciled |
| failed (terminal) | `FAILED` | `BLOCKED` (with an operator action) |
| cancelled | — | `CANCELLED` |

Phase A0 owns the jobs and provider-operation schema for the LLM plumbing (`defer_reason`, the claim's
`consumed_attempt`, `REFUSED_PRELAUNCH`, the `llm.subscription` kind, the `DeferReason` enum). The phase A
packages own their work-scope columns as allocated in the A1 design note (AC-23; amendment v0.4.4). Phase
A owns the workers, enforcement and views.

### 10.1 LLM calls (V3C-21/22, V3R-10; amendment v0.4.2)

- **Execution:** resumable `LlmStep` job steps (phase A0 v0.2 §5.1); each gateway invocation runs in its
  own transient systemd unit with a hard runtime limit and whole-cgroup kill (§4.3 there).
- **Pilot adapter:** the subscription, through ai-route role `dramabox-llm`. Production waits behind
  orchestration priority.
  - Persisted refusals carry retry times; an **unreadable quota pauses production**.
  - No silent provider fallback. Accepted units are never restarted from scratch.
- **Isolation, proven in A0 acceptance:**
  - inspect and test the effective argv, environment and settings;
  - no inherited tools, MCP servers, plugins or hooks can execute;
  - credentials follow an allowlist;
  - cancellation and deadlines kill every descendant process.

  **If the isolation profile can't be established, the adapter stays disabled.** (Today ai-route
  inherits most environment variables and installs a progress MCP server.)
- **Machine-result interface (A0):** preserves the result and structured output, per-model token and
  cache usage, the estimated cost (`total_cost_usd`, with per-invocation vs cumulative made explicit), the
  session ID, outcome and timing. Persisted before acknowledgement; deduplicated by invocation ID.
- **Roles:**
  - Opus: bible, episode builder, season critic.
  - Sonnet: director, metadata, translation, flagged-clip vision.

  The pilot runs frozen workloads to compare them.
- **API and OpenAI-compatible adapters:** only their interfaces and fakes are built in A0. The live
  adapters are built **after the pilot decision** (O-5; N1).

### 10.2 Nano Banana shared lock (V3C-19, MA10, MA15)

- **One shared exclusive lock** for every Nano Banana entry point in **ARISA and Drama Box**, including
  manual tooling. Phase C defines:
  - the shared inode;
  - the process lifetime;
  - crash release;
  - the queue policy;
  - a **fairness rule** against ARISA, e.g. bounded Drama batches that alternate with ARISA turns.
- **ARISA-side adoption is a prerequisite for live image jobs.** It is coordinated with the ARISA owner
  session, outside phase C's offline acceptance.
- Waiting is visible and holds no GPU.

### 10.3 Adapters

| Adapter | Live service | Protocol |
|---------|--------------|----------|
| Image | Nano Banana Pro | GenerationProvider |
| Voice intake | Operator uploads (Botnoi V4) | — (an intake, not a provider) |
| SFX | Per §7 | GenerationProvider |
| Music | YuE2 job | GenerationProvider |
| Render | T031-based production adapter | Existing render contracts |
| Clip QA | On-pod detectors + flagged-clip LLM vision | ASRProvider / MediaReviewProvider |
| Notifier | Telegram outbox | — |
| Publishing | T032 transports | Existing publishing contracts |

### 10.4 Image-volume projection (MA10)

- Before step-4 generation, phase C shows the **projected image count** (candidates + derived views +
  expected re-roll rate) and the **wall-clock estimate** under the shared lock, from the STORY-locked demand
  list.
- P0 measures the lock throughput (images/hour) and makes it operator-visible **before CAST generation
  starts**.

### 10.5 Generation-unit contract (moved here from §4.4; MA13)

For every paid generation:
- immutable inputs, a semantic attempt ID, the reservation, the provider request ID, the result, and the
  outcome (§10.0 mapping);
- a restart resumes unfinished units and never regenerates successes;
- unknown outcomes are reconciled before resubmission, with exposure held;
- bounded retries with backoff; visible recovery actions;
- no GPU held during human waits.

### 10.6 Production composition (V3C-30)

- A separate qualified production composition: per-provider credentials, capability gates and fail-closed
  startup checks. Staging stays `OFFLINE_MOCK`.
- **Scheduler:** a singleton, firing every 1 min, with catch-up rules and health reporting.
- **Backup consistency:** DB + objects + provenance, with a proven restore before domain activation.
- **Phase G completes and qualifies this composition** (A builds the skeleton).

---

## 11. Cost and quota meter, and the pilot (V3C-23)

**Reported separately, never summed blindly:**
- (a) cash spend;
- (b) subscription allocation;
- (c) API-equivalent estimates;
- (d) quota usage;
- (e) operational exposure.

**Records:**
- Money lives **only** in UsageReceipt/charges and cost_allocations (§10.0).
- Quota lives in QuotaObservation, which records timing, cache state, resets, **other concurrent usage**
  and uncertainty.
- GPU time includes loading, QA and idle time.

**Pilot (in an isolated pilot profile):**

| Pilot | What it runs |
|-------|--------------|
| P0 | **Representative full-season planning** (steps 1–3, 24 episodes) + step 4 for a reduced cast (2 characters, 2 locations, voices for both) + a **Nano Banana lock-throughput measurement** |
| P1 | 1 full episode (after T031 qualifies) + the **mixed-emotion exit check (§6)** |
| P2 | 3 more episodes + a **throughput measurement against the §9.4 SLO** |

**`PILOT-REPORT.md` contents:**
- measured vs forecast, clearly marked;
- cost per episode by provider (cash / allocation / estimate);
- quota per episode;
- **planning wall-clock, quota-pause counts and window pacing** (N12);
- throughput;
- the quality measures of §16.3;
- the frozen-workload LLM comparison;
- a recommendation.

**Operator decides:** the LLM plan, the pace and the season start.

## 12. Cross-cutting

### 12.1 Rights and provenance (V3C-33, MA7: phase C accountable)

- A **`ProvenanceRecord`** per asset and per imported method:
  - the authorised basis and version;
  - the generation-time entitlement (separate from later plan upgrades);
  - the model/provider, prompt hash, seed and licence.
- **Covers:**
  - Joey's skills: internal method only, credited, not redistributed, full text never embedded;
  - detector weights;
  - fonts;
  - Botnoi voices (`OPERATOR_ATTESTED`);
  - SFX route terms;
  - YuE2 music;
  - all generated assets.
- Phases B, D and F are consumers.

### 12.2 Output inspection (phase C accountable; consumed by D and F)

- Checks for forbidden on-frame text, branding and likeness on every generated image, thumbnail and
  clip-sampled frame.
- Unresolved findings follow QA/repair and Gate 2.

### 12.3 Budget enforcement (V3C-2, MA9)

| Level | Cap | Binds |
|-------|-----|-------|
| Unit | the reservation | that unit's effect |
| Episode | **US$10** until an operator-approved change after T031 | **Episode-attributable** spend: directing, render, clip QA, edit, metadata, thumbnail, retries for that episode |
| Season setup | a sub-budget (proposed in phase C, operator-approved; O-6) | Steps 1–4, music/SFX libraries, teaser |
| Season | **episode count × US$10** | Setup sub-budget + all episode spend. **Allocated shared setup counts here, not against episode caps** |

- Because the season cap is episodes × US$10 and setup sits inside it, **average episode spend must stay
  at or below (season cap − setup) ÷ episodes**. The forecast shows this before CAST LOCK.
- **Hard stop at every level:** a reservation that would exceed any applicable cap is **refused**. The unit
  waits (`WAITING_BUDGET`, a side state) for an operator raise or approval. There is never a partial
  overrun, except the existing cleanup/shutdown exception, which is recorded truthfully.

### 12.4 Season-2 reuse

See §4.4.5.

### 12.5 Backups and restore

See §10.6.

### 12.6 Amendment (V3C-27; phase A coordinator, phase F integration)

1. Regenerate the requested units.
2. Revalidate the dependency closure; newly invalid dependents are blocked.
3. Atomically invalidate the affected unpublished approvals and queued submissions.
4. Fence late job results by input revision.
5. Published media is immutable.
6. Rebuild the dependent recaps, teasers, captions, thumbnails and metadata.

The impact screen shows the cost first. The coordinator subsumes the existing invalidation helpers (§10.0).

---

## 13. Data model (summary; normative in the phase specs)

- **`GateType`:** add `STORY_LOCK`, `CAST_LOCK`, `TEASER_FINAL`, `LAUNCH`. LOCK gains Revise.
- **New records:**
  - `SeasonBibleV3`, `CharacterProfile` (with tier), `EpisodePackV3`;
  - `LogicalDemand`, `SeasonDemandList`, `CastBinding`, `CastLock`;
  - `AppearanceState`, `ExtrasRole`, `VoiceVariant`, `BotnoiVoiceCatalogEntry`;
  - `ShotPlanV3`, `ShotReferenceSet`, `ClipQaResult`;
  - `MusicCue`, `SfxAsset`, `MetadataDraft`, `ThumbnailCandidate`;
  - `ReleaseCalendar`, `ExtensionScope`, `Amendment`;
  - `ProvenanceRecord`, `QuotaObservation`, `OutboxEvent`, `LlmInvocation`.
- **Not new (reused, §10.0):** jobs, provider operations, usage receipts/charges, cost allocations. No
  `GenerationUnit` or `UsageRecord` table.
- Compatibility readers; migrations 0027+ with the guards; the contract package bump is guardian-owned.

## 14. Reuse and change map

See §10.0 (infrastructure) and the Codex-verified table in [codex-spec-critique.md](codex-spec-critique.md)
(§14 verification). Every "wire up" item is real work assigned in §15 (N3).

---

## 15. Phases and the single obligation ledger (MA5, MA6, MA7)

Each phase goes through: phase spec → critique → build (GLM) → independent review (Codex) → full offline
gate (`make check` + `make pilot`; N9).

| Phase | Builds | Depends on |
|-------|--------|------------|
| **A0** | LLM gateway + resumable `LlmStep` (isolated `dramabox-llm` role, machine-result interface, quota admission, per-invocation systemd units); the unmetered `llm.subscription` operation kind; jobs/provider-operation schema additions; `llm_invocations` + `QuotaObservation`; LLM adapter interfaces + fakes | — |
| **A** | Gate types; the two-track state model + `EXTENDING` flag; stepper shell, episode context, waiting list; job workers + budget enforcement (§12.3); Costs page; amendment coordinator + fencing; outbox + bot; scheduler service; production-composition skeleton | A0 |
| **B** | Mode B + Mode A disabled; LOCK Revise; bible + tiers + speaker counting; logical demands; `EpisodePackV3` + mappings + validators; all episode rows; season critic; STORY LOCK; extension seam | A |
| **C** | Picks engine + UI; image adapter + castkit/scenecraft; packages by tier; wardrobe fixes; Botnoi catalogue + shortlist + casting sheet + upload intake (trust boundary, normalisation); SFX route qualification; YuE2 job; image-volume projection; Nano Banana shared lock (Drama side + fairness); `CastBinding` + `CastLock` migration; season-2 import; **provenance records + output inspection** | A, B; the ARISA adoption for **live** image jobs |
| **D** | Single shot compiler + `ShotPlanV3`; reference schema + selection + emotion rule; production render adapter; clip QA | C; **T031 qualified and `feat/t031-fix3` merged** |
| **E** | Native-audio EDL + caption remap; fades; recap/CTA binding; music placement + ducking; SFX placement; loudness | D |
| **F** | Metadata drafts; thumbnails; Gate 2 extensions; teaser contract + gate; calendar + LAUNCH; slot matrix; held/missed/partial; extension flow + viewership windows | E; **T032** for live |
| **G** | Domain activation; production composition completion; live switches; pilots P0–P2; `PILOT-REPORT.md`; final qualification | A0–F (P0 needs A0–C) |

### 15.1 Acceptance tests: one accountable phase each

| Phase | Tests |
|-------|-------|
| A0 | V3-AT-27 (incl. the isolation proof) |
| A | V3-AT-1, 2, 13, 16 (as superseded, §19.2), 20, 21 |
| B | V3-AT-3, 4, 18, 19 |
| C | V3-AT-5, 6, 7, 15, 22, 23, 28 (Drama-side lock with a simulated competitor), **33** (new: every asset has a complete `ProvenanceRecord`; output inspection catches injected text/brand/likeness) |
| D | V3-AT-8, 9, 24, 26 |
| E | V3-AT-10, 25 (all derivatives; D supplies the binding evidence) |
| F | V3-AT-11, 12, 29 (**the** 30-episode release simulation), 30 (amendment vs job vs publication race), 31 |
| G | V3-AT-14, 17, 32 (composed restore), **34** (new: the all-gate end-to-end composition test), the cross-system Nano Banana lock with real ARISA (AT-28's live half), and LIVE §16.3 |

**Definitions (v0.4.6: folded in, verbatim).** V3-AT-1..17 come from the v0.1 baseline §16, V3-AT-18..32 from
`codex-spec-critique.md`, and V3-AT-33/34 are in the phase table above. Later decisions apply where they changed a
rule: for V3-AT-8's voice, one neutral reference per speaker (§6, v0.4.5).

| ID | Proves |
|----|--------|
| V3-AT-1 | Stepper statuses match the durable state for every season/episode state; "waiting for you" lists exactly the open gates and pick screens |
| V3-AT-2 | No transition passes a gate without a human approval event bound to the current hash; a stale hash is refused; Revise regenerates only the noted units |
| V3-AT-3 | All 24 episode packs are fully renderable (no map-only packs); the season critic catches a premature secret, an impossible wardrobe day, and >2 speakers in a shot |
| V3-AT-4 | Demand list completeness: every character, outfit, state, prop, location + light state, extras role and voice used by any scene is in the list, with the episodes it's used in |
| V3-AT-5 | Picks: votes start no work; Re-roll requeues one item only; Lock is refused until all required items are picked; the lock hash covers every picked version |
| V3-AT-6 | CAST LOCK attaches the identity lock to **every** episode, including ones created later (regression for R-12.1) |
| V3-AT-7 | Wardrobe: a timed outfit change mid-scene appears in the shot references; a new story day gets a different outfit unless a reason is recorded |
| V3-AT-8 | Reference selection: ≤9 images and ≤1 voice per speaker; deterministic choice by framing; drops are logged |
| V3-AT-9 | Director output validates against `ShotPlanV3`; a Thai line too long for a shot is split at a phrase boundary; no cut lands mid-word |
| V3-AT-10 | Edit uses native clip audio; recap ≤10 s from the previous accepted episode; CTA ≤5 s; loudness −14 LUFS ±1; ZH/EN tracks share the TH cue timing |
| V3-AT-11 | Metadata drafts prefill Gate 2; the sealed manifest equals the edited drafts; a thumbnail must be picked before Approve |
| V3-AT-12 | Teaser is scheduled 3 days before episode 1; the buffer rule blocks a start date with fewer than 5 approved episodes |
| V3-AT-13 | Every paid call writes exactly one `UsageRecord`; the Costs page totals match; subscription calls record tokens + `total_cost_usd` + quota deltas |
| V3-AT-14 | `dramabox-llm` refuses while Pro is off pace, and production pauses with a bot alert rather than switching providers silently |
| V3-AT-15 | Nano Banana single-process lock: a second concurrent image job waits; ARISA SFW and Drama Box never run Nano Banana together |
| V3-AT-16 | Bot: every event sends exactly once (deduplicated); every send has a timeout; no approval path exists via Telegram |
| V3-AT-17 (LIVE) | P0/P1/P2 pilots complete; `PILOT-REPORT.md` has measured per-episode cost and quota per provider |
| V3-AT-18 | Plan 20 and 30 complete episodes before any physical cast assets exist; no identity-lock prerequisite blocks writing. |
| V3-AT-19 | Upgrade existing V1/V2 records and approvals without deletion, hash reinterpretation or rejected historical duration values. |
| V3-AT-20 | Crash after provider acceptance and before local persistence; resume without duplicate creation, lost exposure or regenerated successful units. |
| V3-AT-21 | Concurrent workers cannot exceed step, episode or season caps; retries, shared assets and unsettled charges reconcile once. |
| V3-AT-22 | Face reroll invalidates its dependent outfits/views; unrelated selections survive; CAST LOCK cannot freeze stale descendants. |
| V3-AT-23 | Wardrobe continuity spans episode boundaries; canonical setting IDs agree; timed changes work immediately before/at/after boundaries. |
| V3-AT-24 | Over-budget reference sets preserve mandatory identity/proof assets or block; unsupported media/roles fail before dispatch. |
| V3-AT-25 | Native zero-, one- and two-speaker clips pass the production binding path; all derivatives retain speech/audio/caption synchronization. |
| V3-AT-26 | Correct speech/face with wrong wardrobe still produces a continuity finding; unavailable checks never become PASS. |
| V3-AT-27 | Run the real subscription adapter against fixture CLI outcomes: success, malformed result, missing usage, cumulative cost, refusal, timeout and unreadable quota. |
| V3-AT-28 | Competing ARISA/Drama container processes share the same lock; crash/restart cannot allow overlapping provider processes. |
| V3-AT-29 | Simulate 30 daily releases, late teaser, rejected episode, zero buffer, partial destination failure and ambiguous publication. |
| V3-AT-30 | Race amendment against job completion and publication; stale results and old approvals cannot release changed artifacts. |
| V3-AT-31 | Extend during release and after completion, including changed cast; existing published hashes and authority remain intact. |
| V3-AT-32 | Restore DB and objects together; resume scheduler/outbox/jobs without duplicate effects. Document notification ambiguity honestly. |

### 15.2 Requirement ownership: every R-ID has exactly one accountable phase

| Phase | R-IDs |
|-------|-------|
| A0 | — (it provides LLM plumbing to B–F) |
| A | R-11.2, R-11.3, R-11.4, R-11.5, R-11.6, R-12.6, R-12.7 |
| B | R-1.1, R-1.2, R-1.3, R-1.4, R-2.1, R-2.2, R-2.3, R-2.4, R-2.5, R-3.1, R-3.2, R-3.3, R-3.4, R-3.5, R-3.6 |
| C | R-4.1, R-4.2, R-4.3, R-4.4, R-4.5, R-4.6, R-4.7, R-4.8, R-4.9, R-4.10, R-4.11, R-12.1, R-12.2, R-12.3, R-12.4, R-12.5, R-12.9 |
| D | R-5.1, R-5.2, R-5.3, R-5.4, R-5.5, R-6.1, R-6.2, R-6.3, R-6.4 |
| E | R-7.1, R-7.2, R-7.3, R-7.4, R-7.5, R-7.6, R-7.7, R-12.8 |
| F | R-3.7, R-8.1, R-8.2, R-8.3, R-9.1, R-9.2, R-10.1, R-10.2 |
| G | R-11.1, R-12.10, R-12.11, R-12.13 |

**Total: 68.** The union equals the full R-ID set with no duplicates (MA23b).

Findings that need no phase owner are master-level decisions: V3C-1, V3C-2, V3R-12 (N44).

---

## 16. Acceptance

### 16.1 Offline

V3-AT-1..34 per §15.1. **V3-AT-29 is the 30-episode release simulation** and **V3-AT-34 is the all-gate
end-to-end test**; there are no further unnumbered acceptance items (MA23a).

### 16.2 Partial milestones (MA8)

- **LIVE qualification is claimed per destination.** Destinations held by T032 stay `HELD` and are excluded
  from the claim.
- **Mode A** stays labelled **partial** until research qualifies.

### 16.3 LIVE quality and throughput (MA25)

The proposed thresholds below are confirmed or adjusted by the operator from P1/P2. They are recorded in
`PILOT-REPORT.md` and signed by the operator.

| Measure | Threshold |
|---------|-----------|
| Thai ASR word match per line | ≥90% of lines pass |
| Face identity per recognisably framed locked character | ≥95% of shots pass |
| Open CRITICAL continuity findings at approval | 0 |
| Gate 2 human ratings: Thai delivery, lipsync, voice consistency | "acceptable" or better on ≥90% of shots |
| Mixed-emotion shots | ≥80% read correctly (§6) |
| Throughput | ≥ the §9.4 SLO at cost ≤ cap |

---

## 17. Alternatives considered (MF1)

| Decision | Options | Chosen | Rejected because | Pointer |
|----------|---------|--------|------------------|---------|
| Voice source | ElevenLabs Voice Design; Chatterbox; Botnoi API; Botnoi Studio V4 manual | Botnoi V4 manual | ElevenLabs superseded by the operator; Chatterbox has no Thai; the Botnoi API has no expressions | DECISIONS D2 + revisions |
| Mixed emotion per shot | Split coverage; dominant + per-line prompt | Dominant + prompt | Continuity of the voice; split kept as the P1 contingency | V3R-3 decision, §6 |
| Base-voice candidates | Generate 2–3; system shortlist only; one voice | Shortlist only | The operator generates in Botnoi | V3R-11 decision |
| LLM provider | API; subscription; cheaper model | Subscription for the pilot, then decide | The operator wants measured data first | §1 rule 3, O-5 |
| Job/queue infrastructure | New LlmService + GenerationUnit; extend JobService | Extend | No second job system (MA1) | §10.0 |
| Calendar authority | Gate 2 binds dates; LAUNCH binds | LAUNCH + later Gate 2 | Removes the circularity (V3R-6) | §9.2 |
| Render model | Pika H3 Flex Ref2VA; FL2VA; others | Ref2VA | Voice-reference control | T031 benchmark packet |
| Episode planning | Daily incremental; all up front | All up front | The operator's flow; demand list for casting | DECISIONS step 3 |
| UI framework | SPA; server-rendered + vanilla JS | Server-rendered | Reuses the existing review app and ARISA pattern | §3.2 |

## 18. Risks and limits (MF2)

| Risk | Mitigation | Residual owner |
|------|------------|----------------|
| H3 Flex Thai quality or voice conditioning is insufficient | T031 benchmark + P1 thresholds before phase D | Operator decision after T031 |
| Real GPU cost exceeds the US$10 per episode cap | T031 + P1/P2 measurement; season cap enforcement | Operator (cap change) |
| Nano Banana lock starves casting or ARISA | Volume projection + measured throughput + fairness rule | Phase C + the ARISA owner |
| Subscription quota or terms unsuitable for production | Pilot measurement; isolation; adapters behind configuration | Operator (O-5) |
| T032 publishing delayed | Per-destination LIVE claims; HELD slots | T032 |
| Botnoi V4 voices change or disappear | Catalogue `last_verified`; locked WAVs are ours once uploaded | Operator |
| Joey method licence ambiguity | Internal method only; no redistribution or embedding | Phase C provenance |
| Throughput below SLO | SLO alerts; buffer rule; operator levers | Operator |

## 19. Open items and supersessions

### 19.1 Open items (numeric order; N4, N40)

| O | Item | Default / resolution |
|---|------|----------------------|
| O-1 | Trend sources (Mode A) | Disabled with a reason until qualified |
| O-2 | QA detectors + licences | Commercially licensed only; human checks recorded meanwhile |
| O-3 | Thai font licence | A commercial licence, with a `ProvenanceRecord` |
| O-4 | Facebook route + AI label | Decided in T032; held until then |
| O-5 | LLM plan after the pilot | Subscription for the pilot only; live API/compatible adapters built after the decision |
| O-6 | Season-setup sub-budget value | Phase C proposes it; the operator approves |
| O-7 | Buffer numbers | 5 approved before LAUNCH; keep 3 days ahead; alert below 2 |
| O-8 | EN/ZH on TikTok/Facebook without caption-file support | The operator decides in phase F (no extra posts) |
| O-9 | SFX route | Resolved: the cheapest eligible of fal.ai/OpenRouter (§7) |
| O-10 | Botnoi expressions | Resolved: V4 Studio only, so manual upload |
| O-11 | Botnoi commercial basis | Resolved: `OPERATOR_ATTESTED` (DECISIONS, 11 Nov) |
| O-12 | Speaking cap | Resolved: 5 per episode, ≤2 per shot |

### 19.2 Superseded v0.1 clauses (MA14)

| v0.1 clause | Superseded by |
|-------------|---------------|
| §3.3 "up to 40 with extension" | §4.1 (no ceiling of 40) |
| §3.4 bot "exactly once"; V3-AT-16 "sends exactly once" | §3.3 (deduplicated creation; possible duplicate delivery flagged) |
| §4.4 ElevenLabs Voice Design voices; §7 ElevenLabs voices | §4.4.4 Botnoi V4 manual |
| §4.6 / §5 continuity vision "on flags" | §4.6 (every shot) |
| §4.4/§5 "sheet views auto-accepted" | §4.4.1 (accepted in the CAST review) |
| §6 priority-drop list incl. the headless front for identity; "qualified composite" | §6 (mandatory bindings; no composite) |
| §10.1 GenerationUnit/UsageRecord as new systems | §10.0 (reuse) |
| §12.3 "season cap = episodes × cap + the step-4 cap" | §12.3 (setup inside the season cap) |
| §4.9 "Approve & schedule schedules all slots" | §9.2 (LAUNCH authority) |
| "Gate 1" naming | §0 (LOCK = `SEASON_CONCEPT`) |

## 20. Finding → resolution maps

**Codex round 1 (V3C):**

| Finding | Where resolved |
|---------|----------------|
| V3C-1 | §1 |
| V3C-2 | §12.3 |
| V3C-3 | §4.1, §4.4.5 |
| V3C-4 | §4.3 |
| V3C-5 | §4.1, §4.3 |
| V3C-6 | §4.4.5 |
| V3C-7 | §2.2 |
| V3C-8 | §4.4.1 |
| V3C-9 | §10.5 |
| V3C-10 | §4.4.3, §5 |
| V3C-11 | §6 |
| V3C-12 | §6 |
| V3C-13 | §4.5 |
| V3C-14 | §4.6 |
| V3C-15 | §4.7 |
| V3C-16 | §4.6 |
| V3C-17 | §4.6 |
| V3C-18 | §4.4.4 |
| V3C-19 | §10.2 (N34) |
| V3C-20 | §4.7 |
| V3C-21 | §10.1 |
| V3C-22 | §10.1 |
| V3C-23 | §11 |
| V3C-24 | §9.1 |
| V3C-25 | §9.2–9.3 |
| V3C-26 | §4.3 |
| V3C-27 | §12.6 |
| V3C-28 | §2, §3.2 |
| V3C-29 | §4.7 |
| V3C-30 | §10.6 |
| V3C-31 | §3.3 |
| V3C-32 | §4.1, §16.2 |
| V3C-33 | §12.1–12.2 |
| V3C-34 | §15–16 |

**Codex round 2 (V3R):**

| Finding | Where resolved |
|---------|----------------|
| V3R-1 | §4.4.4 step 5 |
| V3R-2 | §4.4.4 step 6 |
| V3R-3 | §6 (operator decision) |
| V3R-4 | §4.2, §4.6, §6 |
| V3R-5 | §2.2 |
| V3R-6 | §4.7, §4.9, §9.2 |
| V3R-7 | §0 |
| V3R-8 | §15 |
| V3R-9 | §7 |
| V3R-10 | §10.1 |
| V3R-11 | §4.4.4 step 2 (operator decision) |
| V3R-12 | §1 |

**Goldfish:**

| Finding | Where resolved |
|---------|----------------|
| B1 | header |
| MA1–MA4 | §10.0 |
| MA5–MA7 | §15, §12.1–12.2 |
| MA8 | §16.2 |
| MA9 | §12.3 |
| MA10 | §10.2, §10.4 |
| MA11 | §9.4, §4.5 |
| MA12 | §6 |
| MA13 | §4.4 (subsections), §10.5 |
| MA14 | §0, §19.2 |
| MA15 | §10.2, §15 |
| MA16–MA18 | §0 glossary |
| MA19 | §4.2 |
| MA20 | §7 |
| MA21–MA22 | §0, §2 |
| MA23 | §15.2, §16.1 |
| MA24 | §4.3 |
| MA25 | §16.3 |
| MF1 | §17 |
| MF2 | §18 |
| Nits | Applied inline where marked "(Nn)". Runbook-level detail (bot paths, V4 tag mappings) moves to the phase C/A specs and runbooks (N2) |
