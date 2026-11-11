# Drama Box v3 — series production workflow: MASTER SPEC

Version **0.3**, 11 Nov 2026: the final master after Codex round 2 ([codex-spec-recritique.md](codex-spec-recritique.md)); every V3R item is applied (§19), and V3R-3/V3R-11 are resolved by operator decisions. Author: Opus orchestrator. Status: **for Goldfish review, then Codex
re-critique (round 2 of 2).**

**Changes from v0.1:** all 34 findings in [codex-spec-critique.md](codex-spec-critique.md) (V3C-1..34)
are accepted; §19 maps each finding to where it is resolved.

**Structure:**
- **This master spec** fixes scope, operator decisions, architecture contracts, invariants, the phase
  boundaries and the acceptance gate.
- **Each phase (A0, A–G)** gets its own **phase spec** carrying the normative schemas, the command and
  state tables and the tests listed in §15.
- A phase spec may not contradict this document. Each phase spec is critiqued before its build.

**Binding inputs, in this order of precedence:**
1. The operator's latest dated instruction in this conversation.
2. [DECISIONS.md](DECISIONS.md).
3. [REQUIREMENTS.md](REQUIREMENTS.md) (68 R-IDs).

**Facts:**
- [factmap.md](factmap.md)
- [joey-digest.md](joey-digest.md)
- [../T031-fix-round/pipeline-map.md](../T031-fix-round/pipeline-map.md)

---

**Pinned v0.1 baseline (V3R-7).** Every "as v0.1 §x" reference and V3-AT-1..17 refer to the immutable
baseline [SPEC-v3-v0.1.md](SPEC-v3-v0.1.md), sha256 `0a2677c9d02e99a790ba7b3bd6f55b74c37261dcb666d9be794e9ea20c1c5dbf`
(recovered verbatim from the session transcript). Its acceptance definitions remain binding except where
explicitly superseded here.

## 1. Goals, non-goals, hard rules

**Goal:** turn a one-line idea into a **20–30 episode, ~2-minute, slower and cinematic Thai
microdrama**, released daily at 19:00 Asia/Bangkok on YouTube Shorts, TikTok and Facebook,
**extendable** by an operator decision, with these properties:
- Characters, voices, wardrobe, props and locations are consistent across the season and into later
  seasons.
- Five content gates, plus LAUNCH calendar approval.
- Everything runs from **dramabox.aivora.agency**.

**Non-goals (v3.0):**
- Instagram.
- Captions beyond TH/EN/ZH.
- Approvals from Telegram.
- Multi-operator teams.
- Automatic (unapproved) extension.

**Hard rules:**
1. **Paid effects:** hold → effect → record. Every paid call reserves budget first and records its
   usage after. Ambiguous outcomes are reconciled before any resubmission. Exposure stays held until
   resolved. (This is the canonical budget/recovery discipline, as hardened in T045 and the H-2 spec.)
2. **Gates:** no gate is passed without a human approval event bound to the current hash.
3. **LLM calls** go through the durable **`LlmService`** queue (§10.1). During the pilot it uses the
   operator's Claude subscription via the qualified `dramabox-llm` route. **Precedence (V3C-1):** the
   operator's subscription-first pilot instruction (11 Nov) supersedes REQUIREMENTS' API-only sentence.
   Choosing the provider for full seasons stays an operator decision after measurement.
4. **Content:** original fictional characters only. No real people, brands or celebrity likeness or
   voice. No text in generated frames; text is added in edit. Output inspection enforces this, not
   prompts alone (§12).
5. **Offline first:** every provider has a fake adapter and offline acceptance tests. Live use needs a
   qualified production composition (§10.4) and a per-provider switch that fails closed.

---

## 2. Stages, gates, numbering

| Tab | Operator's step (DECISIONS) | Scope | Auto/You | Gate |
|-----|-----------------------------|-------|----------|------|
| 1 | 1 Script Maker | Season | You enter; auto proposes | **LOCK** (`SEASON_CONCEPT`; adds Revise) |
| 2 | 2 Bible | Season | Auto | reviewed at STORY LOCK |
| 3 | 3 Episode builder | Season | Auto | **STORY LOCK** (`STORY_LOCK`, new) |
| 4 | 4 Character bible | Season | Auto + your picks | **CAST LOCK** (`CAST_LOCK`, new) |
| 5 | 5 Directing | Episode | Auto | — |
| 6 | 6 I2V (Pika H3 + voice) | Episode | Auto | — |
| 7 | 7 FFmpeg/captions/music/SFX | Episode | Auto | — |
| 8 | **9** Captions/hashtags/thumbnail | Episode | Auto drafts | reviewed at Gate 2 |
| 9 | **8** Review + approve → scheduler | Episode | You | **Gate 2** (`EPISODE_FINAL`) |
| 10 | 10 Teaser | Season | Auto + you | **TEASER** (`TEASER_FINAL`, new) |
| — | Launch calendar | Season | You | **LAUNCH** (§9; activates the release calendar) |

**Numbering crosswalk (V3C-28):** tabs 8 and 9 swap the operator's 8 and 9, because D3 says
"draft before Gate 2". The UI shows the operator's labels, so nothing is renamed on them.

### 2.1 Gates

- **Actions:** Approve / Revise (notes) / Reject. CAST LOCK uses staged picks + Lock (§4.4).
- **Binding:**
  - Every decision binds the exact content hash and revision displayed.
  - A stale page cannot decide.
  - Human session, CSRF and idempotency key, as in the existing `review/api.py` rules.
- **Revise** regenerates the requested units, then **revalidates the dependency closure** (§12.6).
  New invalid dependents are blocked pending scoped revision authority. Every revision is kept.

### 2.2 Command and state model (V3C-7)

- **Production and release are separate tracks.** A season can be producing episode 12 while releasing
  episode 6.
- **Tracks:**
  - **Season planning track:** `IDEA → PROPOSED → LOCKED → BIBLE → PLANNED → STORY_LOCKED → CASTING →
    CAST_LOCKED`.
  - **Season release track:** `NOT_SCHEDULED → CALENDAR_PROPOSED → LAUNCH_APPROVED → RELEASING →
    COMPLETE`.
  - **An extension (V3R-5)** has its own planning scope and STORY/CAST lifecycle. `EXTENDING` is an
    **activity flag**; the season release track stays `RELEASING` or `COMPLETE`. Waits and failures belong
    to their affected scope and track, and never suspend unrelated approved releases. Phase A owns this
    state contract; phase F consumes it.
  - **Episode production track:** `PLANNED → DIRECTED → RENDERING → EDITING → DRAFTING →
    AWAITING_REVIEW → APPROVED`.
  - **Episode release track:** `UNSCHEDULED → SCHEDULED → PUBLISHING → PUBLISHED_VERIFIED`, plus
    `HELD` / `MISSED` / `PARTIAL`.
  - **Pick item:** §4.4.
- **Common side states:** `WAITING_QUOTA`, `WAITING_PROVIDER`, `BLOCKED`, `CANCELLED`. Each persists the
  reason, the resume target and the retry time.
- **Each phase spec gives a command table:** command, allowed states, prerequisites, the transaction
  (locks, in the shared order), events emitted, jobs queued, and the replay result.
- **Scheduler selectors are replaced** so that no V3 job can bypass STORY LOCK or CAST LOCK. The old
  selectors stay only for V1 seasons.

---

## 3. UI: dramabox.aivora.agency

### 3.1 Hosting

- The same FastAPI/Jinja app.
- Coolify Traefik, Let's Encrypt TLS, upstream `127.0.0.1:8093` (DOMAIN-RUNBOOK).
- Owner-only session login with CSRF; secure cookies.
- **Activating the domain requires:**
  1. the qualified production composition (§10.4);
  2. a scheduler service (§10.4);
  3. backups of the DB + object + provenance volumes, with a restore proven;
  4. the operator's dated authorisation, and the DNS record created by the operator.

  Private mock staging stays as it is.

### 3.2 Stepper and navigation (V3C-28)

- **Header on every season page:** tabs 1–10, plus Launch. Each tab has a status icon (not started /
  running n% / **waiting for you** / done ✓ / locked 🔒 / waiting for quota ⏳ / blocked ⚠) and a
  progress bar.
  - **done ✓** = an automatic stage completed.
  - **locked 🔒** = a gate was approved. These two are never conflated.
- **Episode context:** tabs 5–9 always act on a **selected episode**, chosen from the Episodes board or
  the episode switcher in the header. The board remains the overview.
- **Primary actions:**
  - Every tab has exactly one primary action, or none when it is automatic.
  - `Next` only navigates past a completed automatic stage; it never approves.
  - Only gate buttons advance gates.
  - Disabled buttons show their reason.
- **Per tab:** each phase spec defines the route, scope, the progress denominator (unit types as in
  v0.1 §3.2), the primary action, and the empty, loading, error and waiting states.
- **Operations screens:**
  - **Launch calendar** (§9);
  - **Amendment impact** (which approvals and episodes a change invalidates, its cost, then Confirm);
  - **Extension** (viewership windows with freshness and unknowns, then Extend +N);
  - **Recovery** (blocked or unknown units, each with an action: retry / reconcile / resolve);
  - **Quota/provider waits** (what's waiting and until when);
  - **Costs** (§11).
- **Home page:** waiting for you; running; blocked; quota waits; today's releases; budget state.
- **Live updates:** poll the extended `progress.json` every 5 s while the page is visible, using vanilla
  JS (the ARISA SFW pattern).

### 3.3 Dramabox Bot (V3C-31)

- A dedicated Telegram bot, **@AIVORA_DramaBox_Bot**. The token is a FILE credential at
  `/root/.secrets/drama-box/dramabox-bot.token` (0600; rotate before go-live). The destination chat ID is
  stored at `/root/.secrets/drama-box/dramabox-bot.chat_id` (connected 11 Nov; test message delivered).
- **A durable outbox:**
  - one event per source event (deduplicated creation);
  - bounded delivery attempts, each with a timeout;
  - an ambiguous send is retried once, at most, and flagged as possibly duplicated;
  - a dead letter after the limit;
  - provider message IDs recorded.
- **Deep links only.** No approvals in Telegram.
- **Events:** gate waiting; pick screen ready; review ready; published/failed/partial; blocked; quota
  wait; budget at 80%/100%; buffer low; daily 09:00 summary.

---

## 4. Steps

Schemas named here are **defined normatively in the phase specs**. This section fixes their content and
behaviour.

### 4.1 Step 1: Script Maker → LOCK (phase B)

- **Mode B (one-line title)** is complete in v3.0.
- **Mode A (trend research)** requires qualified source adapters (freshness, provenance, failure
  behaviour, research budget). Until then it is **visibly disabled with a reason**, and the v3 milestone
  is labelled **partial** (V3C-32).
- **Proposal fields:** v0.1 §4.1, unchanged.
- **Episode count:** 20–30 at LOCK. Extensions append an explicitly approved N later, with no hidden
  40 ceiling; any technical maximum is documented separately (V3C-3). Target length 120 s (105–135 s,
  including the recap ≤10 s and the CTA ≤5 s).
- **Duration and count validators:** every one is replaced consistently, including those in
  `SeasonScope`, `EpisodePlan`, `EpisodePack`, intake and candidates. Historical V1/V2 records keep
  validating under their schema version (V3C-5).
- **LOCK:** Approve / **Revise** (new: notes → new proposal revision) / Reject. The SQL, proposal history
  and job semantics change together.

### 4.2 Step 2: Bible (phase B)

As v0.1 §4.2: Joey section order; `CharacterProfile` with speech, movement and stillness profiles, drift
exclusions and the voice descriptor; a camera package; a slower pacing rule; ledgers. `[TBD]` in a field
needed for render fails the critic. The existing `contracts.providers.LLMProvider` protocol is reused.

**Character tiers (operator, 11 Nov).** Every on-screen person belongs to one tier:

| Tier | Definition | Bible content |
|------|------------|---------------|
| `PRINCIPAL` | Main cast | Full `CharacterProfile` |
| `SUPPORTING` | A recurring non-principal: secretary, personal doctor, driver, butler… | Lighter `CharacterProfile`: function, visual lock, outfit needs, and speech profile + voice descriptor **only if they speak** |
| `EXTRA` | One-off background role | `ExtrasRole` only (no identity promise) |

**Promotion rule (automatic in step 3, editable at STORY LOCK):** a non-principal role becomes
`SUPPORTING` if **any** of these is true:
- it appears in **≥2 episodes**;
- it has **any dialogue line**;
- it is framed recognisably (not crowd or deep background) in **≥2 scenes**.

The operator can promote or demote any role at STORY LOCK; the step-4 forecast updates. A
`SUPPORTING` character can be upgraded to `PRINCIPAL` in an extension or a later season, keeping the
locked face.

**Speaking-cast limit:** the per-episode featured speaking-character cap rises from 3 to **5** (operator-confirmed 11 Nov, O-12). It stays at **≤2 speakers per shot**. `SUPPORTING` speakers count toward
the cap.

**Tier integrity (V3R-4):**
- Phase B counts **all distinct dialogue speakers, including off-screen speakers**, toward five per
  episode. Phase D enforces two per shot.
- Tier overrides never waive speaker counting, the locked V4 voice requirement, or the required identity
  coverage.
- Demands are revalidated after every tier edit, before STORY LOCK. Phase C freezes the resulting
  packages.
- Phase D applies identity QA to **every recognisably framed locked character**, including `SUPPORTING`,
  with explicit applicability and a recorded human assessment where automation is unavailable.
- Five episode speakers do **not** imply five speakers, or all their references, in one shot.

### 4.3 Step 3: Episodes → STORY LOCK (phase B)

- **Planning without asset IDs (V3C-4).** Step 3 writes **complete scripts** against **stable logical
  demand IDs**: character, outfit, appearance state, prop/state, location/light, extras role. These are
  not asset versions.
  - Step 4 resolves logical IDs to immutable asset versions in a separate **`CastBinding`** record.
  - Planning needs STORY authority. Rendering needs CAST authority.
  - **All planned episode rows** are created at STORY LOCK, independently of the daily release cadence.
    The writer no longer requires an identity lock to plan.
- **`EpisodePackV3` (V3C-5):** the phase B spec publishes:
  - its normative schema;
  - a field-by-field V1 (`EpisodePlan`, `Script`) and V2 (`EpisodePack`) mapping;
  - stable IDs, revisions and hashes;
  - storage;
  - compatibility readers for old records;
  - the order in which consumers migrate.

  Content is as v0.1 §4.3: recap plan, scenes with story time, location/light, visible cast incl.
  extras, props/holder/state, wardrobe and appearance states per character, beats, reveals,
  cliffhanger, dialogue TH/EN/ZH with speaker + delivery + estimated duration, CTA intent, psychology
  at start and end.
- **Generation:** episodes in order, carrying a **running continuity state**, including **wardrobe
  history across episodes** (V3C-10); a critic per episode; a season critic.
- **Demand list:** every logical item, with the episodes and scenes that use it. It gives the step 4
  forecast.
- **STORY LOCK:** approval binds the bible + all packs + the demand list. Revise regenerates the
  requested packs, then revalidates the dependency closure (§12.6).
- **Extension (V3C-26):**
  - An append-only **extension scope**, linked to the prior STORY/CAST locks and to both the
    *planned-terminal* and *published* canon states.
  - Existing episode approvals are preserved.
  - New packs bind explicit cast versions; only new assets need picks.
  - Available from `RELEASING` or `COMPLETE`, with an explicit continued or resumed calendar.
  - The decision screen shows viewership windows with freshness and unknowns. Extension is always
    manual.

### 4.4 Step 4: Character bible → CAST LOCK (phase C)

**Staged picks (V3C-8):**
- **Pick** records a vote only.
- An explicit **Generate next** action enqueues dependent work against the selected parent revision.
- **Required human picks:**
  1. face lock;
  2. outfit;
  3. appearance state;
  4. extras looks (`EXTRA` tier) and the face locks of `SUPPORTING` characters (in step 1, alongside principals);
  5. prop/state;
  6. location master per light state;
  7. voice.
- **Derived assets:** sheet views, expression sets, location coverage plates, the season music library.
  They are generated after their parent is picked and accepted (or re-rolled) inside the final **CAST
  review**.
- **The CAST LOCK hash** covers both the picks and the derived assets.
- **A parent re-roll** invalidates its dependent candidates and selections. Unrelated picks stay valid.

**Asset package by tier:**

| Tier | Package |
|------|---------|
| `PRINCIPAL` | Face lock (pick); all sheet views; expression set (neutral/signature/extreme); outfits per story day (pick); appearance states (pick); voice: the full expression set (Botnoi V4 intake) |
| `SUPPORTING` | Face lock (pick); **front + tight-face views**; **2 expressions** (neutral + signature); outfits per story day (pick; e.g. a uniform); appearance states only if the script needs them; voice: **only if they speak**, `neutral` + the expressions their lines use |
| `EXTRA` | Extras pool: 2–4 looks per role (pick which to keep). No continuity across episodes; no voice (crowd walla only) |

`SUPPORTING` characters are members of the CAST LOCK and the identity lock, exactly like principals.

**Pick item states:** `QUEUED → GENERATING → READY → VOTED → (GENERATE_NEXT) → DERIVED_READY →
ACCEPTED`, plus `REROLL_REQUESTED`, `FAILED_RETRYABLE`, `UNKNOWN`, `FAILED`.

**Generation-unit contract (V3C-9), shared by every paid generation in v3:**
- Each unit persists: its immutable inputs, a semantic attempt ID, the reservation, the provider
  request ID, its result and a status (`queued / running / succeeded / retryable / unknown / failed`).
- A restart resumes unfinished units and never regenerates successes.
- Unknown outcomes are reconciled before resubmission; their exposure stays held.
- Retries are bounded, with backoff. Recovery actions are visible to the operator.
- No GPU is held during a human wait.

**Categories and providers:**
- **Images:** Nano Banana Pro through `ImageGenProvider`. The castkit and scenecraft builders become
  structured prompts.
- **Voices: Botnoi Web Studio V4, shortlisted by the system, made by the operator, uploaded** (operator,
  11 Nov). The Botnoi API (v1/v2) has no expressions; V4 expression tags are web-only, and not every voice
  has V4.
  1. **Expressions needed (auto).** From the STORY-locked packs, derive each speaking character's closed set
     of expressions from the line delivery tags. `neutral` is always included.
  2. **Base-voice shortlist (auto, no generation; operator decision V3R-11).**
     - The system ranks the **Botnoi V4 voice catalogue** against the character's voice descriptor (gender,
       age, timbre, pace, register) and shows **2–3 suggested V4 voices** with the reasons.
     - The catalogue is an **operator-curated data file**: voice name, gender, age range, style notes, V4
       yes/no. Botnoi exposes no voice-list API; phase C defines the import format, and the operator seeds it
       once.
     - The operator auditions the shortlist **inside Botnoi** and picks one. The pick (or "other", with a
       reason) is recorded.
  3. **Voice casting sheet (auto, downloadable and on-screen), per character:**
     - the picked voice;
     - for each expression, a **10–15 s Thai script** from that character's own lines, with **suggested V4
       inline tags** (e.g. `happy` → `[laughter]`; `sad` → `[sigh]`/`[sniff]`; `surprised` →
       `[surprise-oh]`);
     - the rule: **one V4 voice per character for every expression**.
  4. **Upload (operator)** of the neutral sample and each expression. Each slot is keyed
     `(character, expression)`; bulk import via a zip with names like `<character_id>__<expression>.wav`.
  5. **Trust boundary (V3R-1).** Phase C treats uploads as **untrusted bytes**:
     - upload commands require owner scope, CSRF, the expected revision and an idempotency key;
     - files enter a **private quarantine**;
     - request size, archive entries, expanded size, decoded audio and processing time are all bounded;
     - path traversal, absolute paths, links, duplicate slot assignments and unknown character/expression
       keys are rejected;
     - storage paths are generated by the server, and decoding is isolated and bounded;
     - only validated immutable assets can enter the CAST review, and failed imports can never overwrite
       accepted assets.

     The phase C spec sets the numeric limits and tests hostile archives, malformed media, oversized input
     and stale or replayed uploads.
  6. **Normalisation and assessment (V3R-2).**
     - Phase C pins a **versioned normalisation profile** (PCM subtype, sample rate, channels) compatible
       with the qualified production binder. The T031 binder requires non-empty **uncompressed PCM WAV**.
     - **Only the resulting PCM WAV** is registered for dispatch, and it must pass the binder's byte
       validator. Source and normalised hashes are both retained.
     - Technical checks are recorded, plus an automated or human assessment of: Thai speech, the
       transcript, single-speaker suitability, the expression, and consistency with the selected base
       voice.
     - **V4 origin and source-voice identity are operator attestations,** labelled separately from machine
       validation.
     - Changing the base voice **invalidates its whole expression family**.
     - Any addition, replacement or re-normalisation after CAST LOCK creates a new immutable version through
       §12.6.
     - Botnoi rights use the accepted O-11 `OPERATOR_ATTESTED` basis.
  7. **Audition.** In the CAST review the operator plays all variants side by side and can **replace** any
     one.
- **CAST LOCK binds the auditioned normalised PCM WAVs** of every character's full expression set.
- **Pilot observation:** check whether tag vocalisations in a reference (e.g. `[laughter]`) leak into
  Pika's generated line. If they do, the casting sheet switches to tag-free reference scripts.
- **ElevenLabs** is used only for SFX (§4.7, §7).
- **Wardrobe (V3C-10):**
  - **One canonical setting ID** is used in planning, assignment and directing (today
    `assign_scene_wardrobes` uses `location_id` while the compiler compares `StoryTime.setting`; this is
    fixed).
  - Wardrobe history persists across episodes.
  - Timed changes use scene-relative intervals. A shot crossing an incompatible outfit boundary is
    split.
  - Composition and precedence are defined for simultaneous appearance states, and the resulting asset
    bindings persist.

**CAST LOCK (V3C-6):**
- A new **season-scoped cast-lock contract**: STORY revision, complete asset membership, and the
  provenance of the human CAST approval.
- Migrations:
  - the identity-lock readers;
  - the SQL (today it requires `source_episode_id` + `release_package_hash`);
  - **removing episode-1 lock creation from the V3 Gate 2 path**.
- Lock atomically freezes the members and binds every existing episode. Episodes created later bind
  the applicable lock version. This fixes R-12.1.

**Season-2 reuse (V3C-3, in v3):** a new season can import a locked cast, voices and locations
(copy-on-import with source lineage). Rights are revalidated at import time.

**Cost:** step 4 is a **sub-budget inside the season cap** (§12.3), with a forecast before generation.
Re-rolls count.

### 4.5 Step 5: Directing (phase D)

- **One authoritative compiler (V3C-13).** The director LLM (shotcaller method) produces `ShotPlanV3`.
  The phase D spec defines its mapping to the persisted directing manifests and render requests, and
  either replaces the V2 `BeatIntent` compiler or feeds it. One path, not two.
- **Shot length:** generate only **qualified frame counts**. T031 pins 124 frames at 24 fps, about
  5.17 s. Edit may trim at measured, speech-safe boundaries.
- **Stored per shot:** full dialogue coverage, speaker ownership, timing and source dependencies.
- **Total episode duration** is validated, including the recap, transitions and the CTA.
- **Supported shots:** zero-speaker (establishing, insert, reaction), one-speaker and two-speaker.
- Joey's rules, Thai duration estimation and the split at phrase boundaries are as v0.1.
- **Validation:** the shot state resolver (with timed wardrobe) runs before dispatch.

### 4.6 Step 6: Render + clip QA (phase D)

**Production native-render adapter (V3C-14):**
- Built over the accepted T031 transport/recovery primitives; it is not the benchmark controller.
- Supplies a verified, acquisition-scoped upload/binding context (`PikaBindingContext`) at both binding
  stages.
- Supports zero-, one- and two-speaker shots.
- Defines asset registration, polling, QA handoff, retries and shutdown.
- Any changed runtime image or workflow is requalified.

**Clip QA (V3C-16, V3C-17):**
- **Required checks per shot, with thresholds and applicability:**
  - Thai ASR word match;
  - face identity for **every recognisably framed locked character** (`PRINCIPAL` or `SUPPORTING`; V3R-4);
  - **wardrobe/state/prop continuity, on every shot, not just on flags**;
  - technical checks.

  Voice similarity and lipsync are scored where a qualified detector exists. Otherwise each is a
  **required human check at Gate 2**, recorded.
- **Unknown ≠ PASS.**
- **Detector weights must be commercially usable**, pinned with their licence records. (Common
  InsightFace pretrained weights are non-commercial, so they are excluded.)
- The exact render + QA image is **benchmarked on an A40**: sequential load/offload or measured
  concurrent headroom, OOM handling, deadlines. QA load and idle GPU time are metered.

**Acceptance:**
- **Missing or rejected required clips block final assembly.**
- A diagnostic preview may be built but is marked **non-approvable**.
- Critical unresolved findings block Gate 2.

### 4.7 Step 7: Edit (phase E)

- **Native audio, end to end (V3C-15):**
  - The EDL gains **native clip-audio sources** and measured utterance alignment.
  - Synchronised audio/video trims carry through masters, crops, hooks, the recap and fades.
  - **All caption cues** come from accepted native speech and are remapped through edits.
  - No replacement dialogue is synthesised, and native ambience is not duplicated.
- **Recap (V3C-29):** ≤10 s, bound to the **preceding approved episode version**; rebuilt if that
  episode is revised.
- **CTA (V3C-29, V3R-6):** resolved from the **calendar revision** it records a dependency on (proposed before editing; rebuilt and re-approved if rescheduled): next episode at its real air time;
  a confirmed continuation; or a season-finale follow message. It never promises an unapproved
  extension or a non-existent date.
- **Transitions:** fade/xfade filters are implemented in both exporters with a synchronised timeline.
- **Music (V3C-20):** a **Drama-owned YuE2 job**:
  - a pinned instrumental recipe;
  - A40 qualification;
  - duration and loop targets;
  - **vocal-leakage inspection**;
  - cue selection;
  - rights;
  - canonical reservations, ownership, recovery, verified download and billing finality.

  Generated as a season library inside step 4's job graph and budget.
- **SFX:** ElevenLabs Sound Effects v2 (season library + per-episode gaps), with rights records.
- **Mix:** −14 LUFS integrated, −1 dBTP. Thai captions burned in. EN/ZH soft tracks are delivered
  per §9.

### 4.8 Step 8: Metadata + thumbnail drafts (phase F)

As v0.1 §4.8. Drafts are created **per release slot** in the exact slot matrix (§9). The thumbnail uses
a licensed Thai font (rights record) and goes through output inspection for forbidden text, branding
and likeness (§12).

### 4.9 Step 9: Gate 2 (phase F)

As v0.1 §4.9: prefilled drafts, a thumbnail pick, captions, recap/CTA previews, QA (including the
recorded human checks) and costs. **Gate 2 approves content.** For episodes after LAUNCH, Gate 2
also binds the episode's approved calendar slot. Dates and authority follow §9 (V3R-6).

### 4.10 Step 10: Teaser (phase F)

- 30–60 s, from approved episodes, under the spoiler/reveal authority.
- `TEASER_FINAL` gate.
- A `PROMO_CUT` slot at the premiere minus 3 days.
- `PreviewPlan` is extended into a **season teaser contract**: multi-episode sources, a spoiler limit
  and a release obligation.

---

## 5. Continuity model

As v0.1 §5, with these corrections:
- `LocationLayout.light_states` (not `allowed_light_states`; V3C-11).
- One canonical setting ID.
- Wardrobe history across episodes.
- Appearance-state composition rules.

## 6. Reference selection per shot (V3C-11, V3C-12)

- **The production reference schema** is keyed by **shot-visible subject × role × view × outfit/state
  composition × location/light variant**, with defined cardinalities and current-rights checks.
  - Views are resolved **before** exact binding validation.
  - The style reference is **H3-compatible** (PNG). **A moving style video is never passed as an image
    reference.**
- **Mandatory vs optional bindings:**
  - **Mandatory (never dropped):** identity-bearing **face** views for visible principals **and recognisably framed `SUPPORTING` characters** (a headless
    sheet never counts as identity), the required wardrobe/state, **proof props**, the necessary
    location plate.
  - **Optional:** secondary views, extras looks, non-proof props.
- **Over the budget** (9 images; ≤1 voice per speaker, ≤3 audio): drop optional bindings only, with
  reasons. Otherwise **block** and send the shot back to directing to simplify the coverage or split
  the shot (or use a qualified composite).
- **Voice reference by emotion (Botnoi expression variants)**, operator decision on V3R-3, 11 Nov:
  - Each dialogue line in `ShotPlanV3` carries an **emotion tag** from the season's closed expression set.
  - Per speaker, the shot binds **exactly one** CAST-locked voice variant.
  - **When one speaker's lines in a shot carry different emotions,** the shot uses the **dominant
    emotion's** variant. Dominant means the line with the **longest estimated spoken duration**; a tie goes
    to the earlier line.
  - The prompt **states each line's expression and delivery explicitly** (e.g. "says the first line warmly,
    then snaps the second line angrily"). The reference keeps the voice continuous; the prompt directs the
    change. The choice is persisted.
  - The `neutral` fallback applies **only** to an emotion explicitly unsupported in the season set, and is
    recorded. **A missing, corrupt or unapproved required variant blocks dispatch;** it never silently
    falls back.
  - This stays within the T031 contract of one voice anchor per speaker per shot.

## 7. Audio providers

- **Character voices:** operator-made in **Botnoi Web Studio V4** and uploaded through the CAST tab's voice
  intake (§4.4): validated, normalised and provenance-recorded. No voice API call is on the critical path.
- **SFX (V3R-9):** ElevenLabs Sound Effects through **OpenRouter or fal.ai, cheapest eligible route**.
  - Phase C qualifies each reseller's exact SFX model/endpoint, commercial basis, settings and billing
    units.
  - Equivalent requests are compared at their current, all-in, bounded prices, and the maximum authorised
    charge is reserved.
  - **Unknown capability, terms or price makes a route ineligible, never zero-priced.** The cheapest eligible
    route is used; if none qualifies, block.
  - The selected route is persisted, and ambiguous submissions are reconciled before switching resellers.
  - (Codex observed that fal.ai lists `fal-ai/elevenlabs/sound-effects/v2` at $0.002/s with a commercial-use
    label. An OpenRouter equivalent is unverified.)
- **Music:** the Drama-owned YuE2 job (V3C-20).
- **Pika native audio** remains the dialogue and ambience source. Botnoi samples only *condition* the
  voice; they are never mixed into the episode.

## 8. QA

As §4.6, plus the existing episode QA. Unknown coverage is displayed and is never PASS. Required checks
that cannot run automatically are recorded as human assessments at Gate 2.

## 9. Release, calendar, slots (V3C-24, V3C-25)

- **Slot matrix:** one **full-episode post per destination**, in **TH**, on:
  - **YouTube Shorts**;
  - **TikTok**;
  - **Facebook** (Reel or video route per T032).

  EN and ZH are delivered as **caption tracks**, not as separate posts:
  - YouTube caption upload;
  - TikTok and Facebook where the platform supports caption files; otherwise burned-in variants are a
    phase F decision.

  Caption delivery is **verified by readback**. **Unsupported required capabilities**, including
  Facebook AI disclosure, **hold** the slot until T032 qualifies them. Instagram is excluded.
- **Calendar and approval authority (V3R-6):**
  1. A versioned calendar is **proposed before editing and review**: premiere date, daily 19:00
     Asia/Bangkok, and the teaser at premiere − 3 days. Date-bearing content (CTA, teaser copy) records its
     dependency on that proposed revision.
  2. **Gate 2 and TEASER approve content.**
  3. **LAUNCH** binds the exact calendar revision, the stable slot identities and the current
     content-approval hashes. **Initial activation** requires current approvals for the **first five
     consecutive episodes and the teaser**.
  4. Later episodes bind their approved calendar slot at Gate 2.
  5. **Dispatch requires both** current content authority and current calendar authority.
  6. **Rescheduling** rebuilds the affected date-bearing content and requires renewed content approval before
     activation.
  7. Phase F defines V3 publication compatibility (today `ReleaseSlotPlan` requires a schedule, and Gate 2
     binds the package) **without reinterpreting historical dated approvals**.
- **The teaser gates the premiere:** episode 1 depends on **verified teaser publication per destination**.
  A late or failed teaser holds the affected premiere pending an approved recovery or reschedule.
- **Dependencies:** each episode slot depends on its predecessor slot per destination.
- **Missed and failed releases:**
  - A rejected or unready episode near its air time → its slot becomes `HELD`, the successors are held,
    and the bot alerts with options: repair, swap, or push the calendar (each needs approval).
  - Partial destination failure → `PARTIAL`, with per-destination retry/reconcile. A post is never
    duplicated, and only proven absence re-arms a slot.
- **Buffer:** keep ≥3 days produced and approved ahead. The bot alerts below 2.

## 10. Providers and composition

### 10.1 LLM service (V3C-21, V3C-22)

- **`LlmService`:** a **durable, bounded queue** inside Drama Box.
  - Each request is a generation unit (§4.4 contract) with a deadline, cancellation and process
    cleanup.
  - Priorities: orchestration first; production waits.
  - Persisted refusals (pace, concurrency, quota) carry a retry time. **An unreadable quota pauses
    production.**
  - No silent provider fallback. Accepted units are never restarted from scratch.
- **Subscription adapter (pilot):** calls `ai-route` with the new role `dramabox-llm`, in an
  **isolated execution context**:
  - a **restricted toolset**: no tools beyond structured output, no plugins;
  - a narrowly scoped auth;
  - its own working directory.
- **Isolation must be proven (V3R-10), in A0 acceptance.** Inspect and test the effective argv,
  environment and settings. Prove that inherited tools, MCP servers, plugins and hooks cannot execute;
  that credentials follow an allowlist; that an unreadable quota refuses admission; and that cancellation
  and deadlines terminate all descendant processes. If the isolation profile can't be established, the
  subscription adapter is disabled. (Today ai-route inherits most environment variables and installs a
  progress MCP server.)
- **`ai-route` gains a versioned machine-result interface** (package A0). It preserves:
  - the result and structured output;
  - per-model token and cache usage;
  - the **estimated cost** (Claude Code reports `total_cost_usd` as an estimate), with per-invocation
    vs cumulative accounting made explicit;
  - the session ID, outcome and timing.

  Persisted before completion is acknowledged, and deduplicated by a durable invocation ID.
- **Other adapters**, swappable by configuration: Claude API (metered, prompt caching) and an
  OpenAI-compatible adapter (GLM, Qwen, DeepSeek class).
- **Roles:**
  - Opus: bible, episode builder, season critic.
  - Sonnet: director, metadata, translation, flagged-clip vision.

  The pilot may compare them.

### 10.2 Nano Banana shared lock (V3C-19)

Before **any** live image job, one **shared exclusive lock** must be qualified and used by every Nano
Banana entry point in **both ARISA and Drama Box**, including manual tooling. The phase C spec defines:
- the shared host/container inode;
- the process lifetime;
- crash release;
- the queue policy.

Waiting is visible and holds no GPU. **The ARISA side changes are coordinated with the ARISA owner
session.**

### 10.3 Other adapters

`ImageGenProvider`, a voice **intake** (manual Botnoi V4 uploads), `SfxProvider` (ElevenLabs SFX via OpenRouter or fal.ai, cheaper route),
`MusicProvider` (Drama-owned YuE2), the production render adapter (§4.6), `ClipQaProvider` (§4.6),
`Notifier` outbox (§3.3), and publishing (T032).

### 10.4 Production composition (V3C-30)

- A **separate, qualified production composition** with per-provider credentials, capability gates
  and **fail-closed startup checks**. The app and worker today refuse non-`OFFLINE_MOCK`, and that stays
  true for staging.
- **Scheduler:**
  - a singleton service;
  - fires every 1 min;
  - catch-up rules;
  - health reporting.
- **Backup consistency:** DB + objects + provenance, with a proven restore before the domain is
  activated.

## 11. Cost and quota meter, and the pilot (V3C-23)

**Reported separately, never summed blindly:**
- **(a) cash spend:** RunPod, Vertex, ElevenLabs overage, API;
- **(b) subscription allocation:** plan fee share;
- **(c) API-equivalent estimates:** Claude Code `total_cost_usd`;
- **(d) quota usage:** window percentages, credits, voice slots;
- **(e) operational exposure:** held, unsettled.

**Each `UsageRecord` stores:** the unit, its attempt, success or failure, and its share of shared setup
cost (allocated, never double-counted). GPU time includes loading, QA and idle time.

**Quota measurement:**
- Records the timing, cache state, window resets, **other concurrent usage**, and uncertainty.
- Pilot runs use an **isolated pilot profile**, and are scheduled so that other sessions don't
  contaminate the quota deltas, or the contamination is measured.

**Pilot:**

| Pilot | What |
|-------|------|
| **P0** | **Representative full-season planning:** steps 1–3 for a 24-episode season. Step 4 for a reduced cast (2 characters, 2 locations, 1 voice each). |
| **P1** | 1 full episode, steps 5–9 (after T031 qualifies). |
| **P2** | 3 more episodes. |

**Comparability:** where LLM routes are compared, frozen workloads (the same inputs) run across the
candidate routes, and quality and repair rates are recorded.

**Output:** `PILOT-REPORT.md`, with measured vs forecast clearly marked. It gives the cost per episode
by provider (cash vs allocation vs estimate), the quota per episode, throughput, quality flags and a
recommendation. The operator decides the LLM plan, the pace and the season start.

## 12. Cross-cutting

1. **Rights and provenance (V3C-33):**
   - Records the authorised basis and version for:
     - imported prompt material (Joey's skills: no licence stated, so internal method only, credited,
       not redistributed, and the full text is not embedded verbatim);
     - detector weights;
     - fonts;
     - every generated asset.
   - Generation-time entitlement (e.g. the ElevenLabs plan at that time) is distinguished from later
     plan upgrades.
2. **Output inspection** for forbidden on-frame text, branding and likeness. Unresolved findings follow
   QA/repair and Gate 2.
3. **Budget (V3C-2):**
   - The episode cap stays **US$10** until an operator-approved change informed by T031.
   - **Season cap = episode count × $10.** Step 4 and the season setup are **sub-budgets inside it**.
   - Any extra setup allowance needs a dated operator decision.
   - Shared costs are allocated without double counting.
   - Concurrency-safe enforcement: hold before effect.
4. **Season-2 reuse** (§4.4), in v3.
5. **Backups and restore** (§10.4).
6. **Amendment (V3C-27):**
   - Regenerate the requested units, then revalidate the dependency closure.
   - Newly invalid dependents are blocked pending scoped revision authority.
   - **Atomically invalidate** the affected unpublished approvals and queued submissions.
   - **Fence** late job results by input revision.
   - **Published media is immutable.**
   - Rebuild the dependent recaps, teasers, captions, thumbnails and metadata against the new hashes.
   - The amendment impact screen shows the cost first.

## 13. Data model (summary; normative in the phase specs)

- `GateType` += `STORY_LOCK`, `CAST_LOCK`, `TEASER_FINAL`, `LAUNCH`; Gate 1 Revise.
- New:
  - `SeasonBibleV3`, `CharacterProfile`, `EpisodePackV3`, `LogicalDemand`, `SeasonDemandList`,
    `CastBinding`, `CastLock`;
  - `PickItem`/`PickCandidate`/`PickVote`, `GenerationUnit`;
  - `AppearanceState`, `ExtrasRole`, `ShotPlanV3`, `ShotReferenceSet`, `ClipQaResult`;
  - `VoiceVariant` (character, expression, Botnoi speaker/style, WAV), `MusicCue`, `SfxAsset`,
    `MetadataDraft`, `ThumbnailCandidate`;
  - `ReleaseCalendar`, `ExtensionScope`, `Amendment`;
  - `UsageRecord`, `OutboxEvent`, `LlmInvocation`.
- V1/V2 compatibility readers and schema-version handling; migrations 0027+ with the full guards; the
  contract package bump is guardian-owned (V3C-5).

## 14. Reuse and change map

As v0.1 §14, with Codex's verification (critique §14 table): **"wire up" items are real work**, and each
is assigned to a phase with its own tests.

## 15. Phases (each: phase spec → critique → GLM build → Codex review → full gate)

| Phase | Content | Depends on | Phase spec must define |
|-------|---------|------------|------------------------|
| **A0 LLM plumbing** | `ai-route` machine-result interface + the `dramabox-llm` role with **proven isolation**; the `LlmService` queue; **the shared `GenerationUnit` and `UsageRecord` backend contracts and persistence** (V3R-8); subscription/API/OpenAI-compatible adapters (fake first) | — | V3C-21/22, V3R-10; AT-27 |
| **A Foundations** | Gate types incl. LAUNCH; the two-track state/command model (incl. the `EXTENDING` flag, V3R-5); stepper shell, episode context, waiting list; `GenerationUnit` workers + enforcement; Costs page over `UsageRecord`; **the shared amendment coordinator + revision fencing**; outbox + bot (fake → live); scheduler service; production-composition skeleton (fail-closed) | A0 | V3C-7/9/27/28/30/31; AT-1, 2, 13, 16, **20**, 21 |
| **B Story** | Mode B (Mode A **visibly disabled**); Gate 1 Revise; `SeasonBibleV3`; logical demand IDs; **initial planning requires the approved LOCK scope, never the STORY LOCK that approves its output** (V3C-4); `EpisodePackV3` + V1/V2 mapping + validators; all episode rows at STORY LOCK; season critic; STORY LOCK; **the locked extension seam**; tier counting (V3R-4) | A | V3C-3/4/5; AT-3, 4, 18, 19 |
| **C Cast** | Picks engine (staged); `ImageGenProvider` + castkit/scenecraft builders; views/expressions/outfits/states/extras/props/locations + coverage; **shared Nano Banana lock (with ARISA)**; voice casting sheet + manual Botnoi V4 upload intake + validation/normalisation + ElevenLabs SFX adapter + preflight; YuE2 Drama job; wardrobe fixes; `CastBinding` + season `CastLock` migration; season-2 import | A, B | V3C-6/8/10/18/19/20; AT-5, 6, 7, 15, 22, 23, 28 |
| **D Direct + Render** | Single shot compiler; `ShotPlanV3`; reference schema + mandatory/optional selection; production native-render adapter; clip QA (licensed weights, A40 benchmark) | C, **T031 qualified** | V3C-11..14/16/17; AT-8, 9, 24, 25, 26 |
| **E Edit** | Native-audio EDL + caption remapping; fades; recap/CTA binding; music cue placement + ducking; SFX; loudness | D | V3C-15/29; AT-10 |
| **F Release** | Metadata drafts per slot; thumbnails + inspection; Gate 2 extensions; teaser contract + gate; calendar + LAUNCH; slot matrix; held/missed/partial handling; extension flow | E; **T032** for live | V3C-24/25/26; AT-11, 12, 29, 31 |
| **G Domain + pilot** | Domain activation (operator); live switches; P0 (needs A0–C) → P1 → P2; `PILOT-REPORT.md` | A0–F (P0: A0–C) | V3C-23; LIVE AT |

**Acceptance ownership (V3R-8):** each obligation has **one accountable phase**; the contributing phases
supply component evidence.

| Phase | Accountable for |
|-------|-----------------|
| A0 | AT-27 (incl. the V3R-10 isolation proof) |
| A | AT-1, AT-2, AT-13, AT-16, **AT-20**, AT-21 |
| B | AT-3, AT-4, AT-18, AT-19 |
| C | AT-5, AT-6, AT-7, AT-15, AT-22, AT-23, AT-28 |
| D | AT-8, AT-9, AT-24, AT-26 |
| E | AT-10, **AT-25** (all derivatives; D supplies the binding evidence) |
| F | AT-11, AT-12, AT-29, **AT-30** (the full amendment vs job vs publication race, using A's coordinator), AT-31, live analytics + freshness/unknowns + extension decision evidence |
| G | **AT-14, AT-17, AT-32** (composed restore), the **all-gate end-to-end** test, the completed and qualified production factory, final live qualification; it keeps the **partial** label while Mode A is unqualified; it distinguishes the four rendered pilot episodes from the five-episode LAUNCH threshold |

The combined per-R-ID ownership is checked before acceptance, so that cross-cutting requirements cannot
disappear between phases.

## 16. Acceptance (V3C-34)

- **Offline:** V3-AT-1..17 (pinned v0.1 baseline) + **V3-AT-18..32** (critique list, adopted verbatim as obligations).
  Plus an **end-to-end V3 composition test through every human gate** and a **30-episode release
  simulation**.
- **LIVE:** representative Thai speech/identity/lipsync/continuity quality; measured A40 render + QA
  throughput and total lease cost; caption and disclosure delivery verified through T032-controlled
  publication; the pilot report.
- **Trace:** every phase spec includes a **per-R-ID trace table** (all 68 R-IDs across the phases; no
  wildcard families).

## 17. Requirement trace

The per-R-ID matrix is a deliverable of the phase specs (§16). Coverage gaps named by the critique
(R-1.1–R-12.13 table) are assigned in §15.

## 18. Open items

| O | Item | Default |
|---|------|---------|
| O-1 | Trend sources (Mode A) | Disabled with a reason until qualified |
| O-2 | QA detectors + licences | Commercially licensed only; human checks recorded at Gate 2 until qualified |
| O-3 | Thai font licence | Commercial licence with a rights record |
| O-4 | Facebook route and AI label | Decided in T032; the slot holds until then |
| O-5 | LLM plan after the pilot | Subscription for the pilot only |
| O-6 | Step-4 sub-budget value | Within the season cap; the phase C spec proposes a value for the operator |
| O-7 | Buffer numbers | 5 approved before LAUNCH; keep 3 days ahead; alert below 2 |
| O-8 | EN/ZH captions on TikTok and Facebook | Caption files where supported; otherwise a phase F decision (no new post per language) |
| O-9 | SFX route | **ElevenLabs SFX via OpenRouter or fal.ai, whichever is cheaper** (operator, 11 Nov). The phase C spec adds a price preflight per route and verifies the reseller's commercial terms. No direct ElevenLabs plan is required |
| O-10 | Botnoi expression mechanism | **Resolved 11 Nov:** expressions exist only in Web Studio V4 tags, so manual upload (§4.4) |
| O-12 | Speaking-character cap per episode | **Resolved 11 Nov: 5** (was 3); ≤2 per shot; recurring roles auto-detected |
| O-11 | Botnoi commercial use of Web Studio V4 output | **Resolved 11 Nov:** an operator-attested basis (the sales page lists ads/product videos, stories, audiobooks; no licence document exists). Stored in each voice rights record as `OPERATOR_ATTESTED` |

## 19. Finding → resolution map (V3C-1..34)

| Finding | Where resolved |
|---------|----------------|
| V3C-1 | §1 rule 3 |
| V3C-2 | §12.3 |
| V3C-3 | §4.1, §4.4 |
| V3C-4 | §4.3 |
| V3C-5 | §4.1, §4.3, §13 |
| V3C-6 | §4.4 |
| V3C-7 | §2.2 |
| V3C-8 | §4.4 |
| V3C-9 | §4.4 |
| V3C-10 | §4.4, §5 |
| V3C-11 | §5, §6 |
| V3C-12 | §6 |
| V3C-13 | §4.5 |
| V3C-14 | §4.6 |
| V3C-15 | §4.7 |
| V3C-16 | §4.6, §8 |
| V3C-17 | §4.6 |
| V3C-18 | §4.4, §7 |
| V3C-19 | §10.2 |
| V3C-20 | §4.7 |
| V3C-21 | §10.1 |
| V3C-22 | §10.1 |
| V3C-23 | §11 |
| V3C-24 | §9 |
| V3C-25 | §9 |
| V3C-26 | §4.3 |
| V3C-27 | §12.6 |
| V3C-28 | §2, §3.2 |
| V3C-29 | §4.7 |
| V3C-30 | §10.4 |
| V3C-31 | §3.3 |
| V3C-32 | §4.1 |
| V3C-33 | §12.1, §12.2 |
| V3C-34 | §16 |

### V3R (round 2) → resolution

| Finding | Resolution |
|---------|------------|
| V3R-1 | §4.4 step 5 |
| V3R-2 | §4.4 step 6 |
| V3R-3 | §6 (operator: dominant emotion + per-line expression in the prompt) |
| V3R-4 | §4.2 tier integrity, §4.6 |
| V3R-5 | §2.2 |
| V3R-6 | §4.7, §4.9, §9 |
| V3R-7 | header (pinned v0.1 baseline) |
| V3R-8 | §15, ownership table |
| V3R-9 | §7 |
| V3R-10 | §10.1 |
| V3R-11 | §4.4 step 2 (operator: system shortlists 2–3 V4 voices; the operator generates the chosen one) |
| V3R-12 | §1 |
