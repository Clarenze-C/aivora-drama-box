# Drama Box v3 — series production workflow: SPEC

Version 0.1, 11 Nov 2026. Author: Opus orchestrator. Status: **DRAFT for Goldfish + Codex critique.**
Size: Large (new subsystems, paid providers, a public domain).

**Binding inputs:**
- [DECISIONS.md](DECISIONS.md): operator decisions. This spec must not contradict them.
- [REQUIREMENTS.md](REQUIREMENTS.md): R-IDs. Every R-ID maps to a section below (§17).

**Facts:**
- [factmap.md](factmap.md): what exists, WIRED/CALLABLE/ABSENT.
- [joey-digest.md](joey-digest.md): Joey's methods.
- [../T031-fix-round/pipeline-map.md](../T031-fix-round/pipeline-map.md): today's pipeline.

**Not in scope:**
- The T031 H-2 recovery build, which is in progress.
- T032 live publishing transports. Specified only as dependencies here.

---

## 1. Goals and non-goals

**Goal:** an operator-supervised, mostly automated studio that turns a one-line idea into a
**20–30 episode, ~2-minute, slower and cinematic Thai microdrama**, released daily at 19:00 Thailand
time on YouTube Shorts, TikTok and Facebook. Specifically:
- Characters, voices, wardrobe, props and locations stay consistent.
- The operator approves at five gates.
- Everything is driven from **dramabox.aivora.agency** with a checkout-style stepper.

**Non-goals for v3.0:**
- Instagram.
- Languages beyond TH/EN/ZH.
- Approvals from Telegram (the bot notifies and deep-links only).
- Multi-operator teams.
- Automatic season extension (extension is operator-triggered).

**Hard rules:**
1. **No paid effect without a hold.** Every paid call reserves budget first and records its actual
   usage after (existing canonical budget service).
2. **No step passes a gate without the operator's click.**
3. **Production LLM calls never use a raw `claude -p`.** They go through `ai-route` (role
   `dramabox-llm`, §10.1) so quota pace, logging and duplicate guards apply.
4. **Original fictional characters only.** No real people, brands or celebrity voices. No on-screen
   text in generated frames; text is added in edit.
5. **Offline-first.** Every new provider has a fake adapter and offline acceptance tests before any live
   call is allowed.

---

## 2. Stages, gates and the stepper

| Tab | Scope | Step | Auto/You | Gate at end |
|-----|-------|------|----------|-------------|
| 1 | Season | Script Maker | You enter, auto proposes | **LOCK** (existing `SEASON_CONCEPT`, add Revise) |
| 2 | Season | Bible | Auto | none (reviewed at STORY LOCK) |
| 3 | Season | Episodes (all) | Auto | **STORY LOCK** (new `STORY_LOCK`) |
| 4 | Season | Character bible | Auto generates; you pick | **CAST LOCK** (new `CAST_LOCK`) |
| 5 | Episode | Shots (directing) | Auto | none |
| 6 | Episode | Video (render + clip QA) | Auto | none |
| 7 | Episode | Edit (recap, audio, music, SFX, captions, CTA) | Auto | none |
| 8 | Episode | Metadata + thumbnail drafts | Auto | none (reviewed at Gate 2) |
| 9 | Episode | Approve | You | **Gate 2** (existing `EPISODE_FINAL`) |
| 10 | Season | Teaser | Auto, after ≥3 episodes are approved | **TEASER** (new `TEASER_FINAL`) |

### 2.1 Gate behaviour (all gates)

- **Actions:** Approve; Revise (with notes); Reject. CAST LOCK uses per-item Pick/Re-roll plus a single
  Lock instead of Approve.
- **Binding:**
  - A decision binds to the exact content hash shown. A stale page cannot approve.
  - Approvals are human-session only, CSRF-protected and idempotent; the existing `review/api.py` rules
    are reused.
- **Revise:**
  - Records structured notes and regenerates **only** the affected units.
  - LOCK Revise regenerates the proposals.
  - STORY LOCK Revise targets a section of the bible or listed episodes.
  - Gate 2 Revise uses the existing timecoded repair flow.
  - Every Revise creates a new revision. History is kept.
- **Changing a locked artefact later** needs an explicit **amend** (§12.6). Amend marks the dependent
  episodes and shots stale and shows exactly which ones.

### 2.2 State machines

- **Season:**
  - `IDEA → PROPOSED → LOCKED → BIBLE → PLANNED → STORY_LOCKED → CASTING → CAST_LOCKED → PRODUCING →
    RELEASING → COMPLETE`.
  - Side states: `EXTENDING` (after extension is triggered) and `BLOCKED` (a reason is always stated).
- **Episode:**
  - `PLANNED → DIRECTED → RENDERING → EDITING → DRAFTING → AWAITING_REVIEW → APPROVED → SCHEDULED →
    PUBLISHED_VERIFIED`.
  - Side states: `REVISING`, `BLOCKED`.
- **Pick item (step 4):**
  - `QUEUED → GENERATING → CANDIDATES_READY → PICKED → LOCKED`.
  - `REROLL_REQUESTED → GENERATING`.
  - The vote and the lock are separate; a vote starts no work (as in ARISA SFW).
- All states are durable rows. Transitions are written only by the owning service under the existing
  lock-order discipline. The UI is a projection.

---

## 3. UI: dramabox.aivora.agency

### 3.1 Hosting (R-11.1)

- Same FastAPI/Jinja app (`review/api.py`, `render.py`).
- Behind the existing Coolify Traefik, with Let's Encrypt TLS.
- Upstream `127.0.0.1:8093`, per `deployment/staging/DOMAIN-RUNBOOK.md`.
- Owner login only: scrypt sessions, CSRF, `MICRODRAMA_COOKIE_SECURE=1`. No signup.
- The **operator** creates the Cloudflare DNS record and authorises the deploy. The builder prepares and
  tests the config.
- The compose file gains a **scheduler** service (today it is absent; R-12.10) and backup coverage for the
  DB and object volumes.

### 3.2 Stepper (R-11.2..11.4)

- **Every season page** has a fixed header showing tabs 1–10 with: number, short name, status icon
  (not started / running / **waiting for you** / locked ✓ / blocked ⚠) and a thin progress bar.
- **Tabs 1–4 and 10** open season pages.
- **Tabs 5–9** open the **Episodes board**: a table of all episodes, each with its own 5–9 mini-stepper,
  status, cost so far and next action.
- **The active tab** shows one progress bar per generation unit type (table below).
- **Home page:** a "Waiting for you" list (every open gate and every pick screen with unpicked items),
  plus running jobs, blockers and today's releases.
- **Progress updates** by polling the existing `progress.json` endpoints (extended) every 5 s while the
  page is visible. No SPA framework; small vanilla JS only (the ARISA SFW picks pattern).

| Tab | Progress bars (units) |
|-----|-----------------------|
| 1 | Research sources read n/N; proposals generated n/3 |
| 2 | Bible sections drafted n/N; critic pass |
| 3 | Episodes planned n/N; critic checks n/N; demand list built |
| 4 | Per category (characters, sheet views, expressions, outfits, states, extras, props, locations + coverage, voices): **generated n/N** and **picked n/N** |
| 5 | Scenes directed n/N |
| 6 | Clips rendered n/N, passed QA n/N, retrying n |
| 7 | Edit stages (recap, assembly, music, SFX, mix, captions TH/EN/ZH, variants) n/N |
| 8 | Drafts per platform × language n/N; thumbnail variants n/3 |
| 10 | Teaser cut, copy, thumbnail |

### 3.3 Pages

| Page | Content | Actions |
|------|---------|---------|
| 1 Script Maker | Mode A (trend ideas) or B (one-line title); advanced: episode count (default 24, range 20–30; up to 40 with extension), target length (120 s), tone. Then 3 proposal cards (§4.1) | Generate; Select; **Approve / Revise / Reject** |
| 2 Bible | Rendered bible sections (§4.2), with `[TBD]` fields highlighted | Read-only (edits happen through STORY LOCK Revise) |
| 3 Episodes | Season overview (promise, escalation, extension seam), then a list of episodes with title, synopsis, story days, cast, props, locations, reveals, cliffhanger and the full Thai/EN script. Also the season **demand list** with its counts and a **cost forecast for step 4** | **Approve STORY LOCK / Revise** (per episode or section) |
| 4 Character bible | Category tabs. Per item: 3 candidates (zoomable images; audio players for voices), item specs (outfit days, state days, prop holders) and continuity warnings | **Pick / Re-roll (+note)**; then a single **Lock cast** (enabled only when every required item is picked); cost so far + forecast for the season render |
| Episodes board | Episodes × mini-steppers; filters | Open an episode |
| Episode 5–8 | Shot list (shot cards: duration, framing, speakers, references used), clips with QA flags, edit timeline, drafts | View; re-run a failed unit |
| 9 Approve | The existing Gate 2 page **plus** prefilled metadata drafts per platform × language, **thumbnail pick (3)**, captions TH/EN/ZH, recap and CTA preview | **Approve & schedule / Revise (timecoded) / Reject** |
| 10 Teaser | Teaser video, copy, thumbnail pick, schedule (3 days before episode 1) | **Approve & schedule / Revise / Reject** |
| Costs | Per provider, per step, per episode, per season: actual vs cap; LLM tokens and quota (§11) | — |

### 3.4 Dramabox Bot (R-11.6)

- A dedicated Telegram bot (the operator creates the token with BotFather; stored as a FILE credential
  reference, never in `.env` in the repo).
- **Sends:**
  - gate waiting (with a deep link);
  - a pick screen ready;
  - an episode ready for review;
  - published / failed;
  - blocked (with a reason);
  - budget at 80% / 100%;
  - daily 09:00 summary.
- Every send has a timeout and is recorded as a durable notification row (deduplicated).
- **No approvals via Telegram** in v3.0.

---

## 4. Steps: functional spec

The record names below extend the existing V2 contracts unless marked NEW. The LLM roles use
§10.1 and the prompt sources from Joey's methods (digest §1–4), adapted to H3 and Thai.

### 4.1 Step 1: Script Maker → LOCK

- **Mode A (trend ideas):**
  - The research job collects current Thai/SEA microdrama trends from configured sources. The live
    source list is a decision (§18 O-1). The fake source stays the default.
  - The LLM proposes 3 series.
- **Mode B (one-line title):** the LLM proposes 3 interpretations of the title.
- **Proposal fields:** title TH/EN; logline; premise; thesis question; genre/tone; episode count (20–30)
  and target length (120 s); main cast briefs (3–6); season promise; escalation shape; ending + an
  **extension seam**; why it would trend; originality/rights notes.
- **LOCK:**
  - Approve stores an `ApprovalEvent(SEASON_CONCEPT)` bound to the proposal hash.
  - **Revise (NEW)** takes notes and regenerates the proposals.
  - Reject closes the season.
- **Changes:**
  - Intake episode count range 1–10 → **20–40**.
  - `ProductionLimits` episode duration 180–300 s → **105–135 s, target 120 s**, including a recap
    ≤10 s and a CTA ≤5 s.

### 4.2 Step 2: Season bible (auto)

- **Output:** a `SeasonBibleV3` (NEW record wrapping the existing `SeasonBible` and `RichBible`):
  - **Ordered sections (Joey):** premise → thesis → timeline → era aesthetics → world rules →
    locations → factions/groups → characters → relationships → story engines → production rules.
  - **Production rules:** a season **camera package** (one look: spherical or anamorphic, a lens
    family, movement register), palette, lighting language and **pacing rule** (slower, cinematic:
    average shot 4–5 s, held emotional beats, no frantic cutting).
- **Per character (`CharacterProfile`, NEW, extends `CharacterBrief` and `CharacterLogic`):**
  - narrative function, visual lock (text), backstory, psychology by story state;
  - **speech** (register, texture, cadence, Thai politeness and pronouns, code-switching),
    **movement**, **stillness**;
  - **drift exclusions**;
  - **voice descriptor** (for ElevenLabs Voice Design: gender, age range, pitch, timbre, pace, accent
    or dialect, emotional baseline);
  - goal, strategy, flaw, secrets.
- **Ledgers:** the secret ledger and the season ledger (existing, callable) become wired.
- **Rule:** unknowns are `[TBD]` and listed; the critic fails a bible that has a `[TBD]` in a field that
  is required for render.

### 4.3 Step 3: Episode builder → STORY LOCK

- **Plan every episode** as a full `EpisodePackV3`.
  - **The T039 rule `scoped_map_only = episode_number > 3` is removed.**
  - `EpisodePackV3` unifies the V1 `EpisodePlan` + `Script` and the V2 `EpisodePack`. One record holds:
    - title TH/EN; synopsis;
    - **recap plan** (which beats from the previous episode, ≤10 s);
    - scenes: `StoryTime` (story day, local time, setting), location ID + **time-of-day/light
      state**, visible cast **including extras roles**, props + holder + state, **wardrobe per
      character** (outfit ID + **appearance state IDs**), beats, reveals;
    - **cliffhanger** beat;
    - **dialogue** (Thai text + EN + **ZH** translation, speaker, delivery note, estimated duration);
    - **CTA line** (default template, §4.7);
    - target duration;
    - character psychology at episode start and end.
- **Generation:**
  1. One architect call per episode, in episode order, carrying the running continuity state.
  2. A critic pass per episode.
  3. A season-level critic (secret timing, payoff debts, wardrobe/day plausibility, cast budget limits:
     ≤3 featured speakers per episode, ≤2 speakers per shot).
- **Demand list (NEW `SeasonDemandList`):**
  - Built after all packs are planned, using `plan_reference_demands`, extended with sheet views,
    expressions, states, extras, location coverage and voices.
  - Every item lists the episodes and scenes that use it.
  - The UI shows a **step 4 cost forecast** from it.
- **STORY LOCK:** Approve stores `ApprovalEvent(STORY_LOCK)` over the hash of the bible + all packs +
  the demand list. Revise takes per-episode or per-section notes; only the noted packs are regenerated,
  then the season critic and the demand list rerun.
- **Extension (R-3.7):** `Extend season (+N)`, available while `RELEASING`:
  1. Plans N more packs from the current canon, the published state and the extension seam.
  2. Runs a STORY LOCK amendment for the new packs only.
  3. Adds new demand items to step 4 (only those items need picks).
  4. A CAST LOCK amendment.
  5. Production continues.

### 4.4 Step 4: Character bible → CAST LOCK

All image generation uses **Nano Banana Pro** (Vertex), through a NEW `ImageGenProvider` adapter
(fake by default). Joey's prompt compilers (castkit and scenecraft rules, digest §1–2) become **system
prompts + structured prompt builders**, with no interactive chat. The default is **3 candidates per
item**.

| Category | What is generated | Picks |
|----------|-------------------|-------|
| **Character face lock** | Forehead-to-upper-chest plate, **18% neutral gray field, directionless light, no baked lighting** (castkit). Candidates: 3 | 1 pick per character |
| **Sheet views** | Built from the picked face + base outfit: full-body front (headless), full-body rear, tight face, 3/4 left/right (true profile optional). Each view is its own `AssetSheet` (`view_name`) | Auto-accepted unless a QA flag fires; the operator can Re-roll a view |
| **Expression set** | Neutral / signature / extreme, with muscular descriptions | Auto + Re-roll |
| **Outfits** | One per `(character, outfit_id)` from the wardrobe plan; built on the locked face (castkit outfit station). Candidates: 3 | 1 pick per outfit |
| **Appearance states** | Injuries, bruises, haircut, makeup, dirt, wet, aging. Each is a versioned "addition" on the locked face, valid for story days or scenes. Candidates: 3 | 1 pick per state |
| **Extras pool** | Generic background people per role (e.g. diner, line cook, street vendor), 2–4 looks per role. Not full characters: no voice, no lines (or only crowd walla) | Pick the looks to keep |
| **Props** | Each prop and each prop state (e.g. new / broken). Candidates: 3 | 1 pick per prop state |
| **Locations** | Master plate per location per time-of-day/light state (scenecraft), 3 candidates. Then **coverage plates** (reverse, closer, side), generated with the picked master attached and identical geometry/time/weather (scenecraft coverage rule) | Pick the master; coverage auto + Re-roll |
| **Voices** | **ElevenLabs Voice Design (Thai, `eleven_v3`/`eleven_v4`)**: one design call per character with its voice descriptor and a Thai sample script (the character's signature lines, 10–15 s), giving 3 previews. On pick: create the voice (uses one voice slot), render the final 10–15 s Thai reference sample, store it as a VOICE asset (WAV + voice ID + provenance) | 1 pick per speaking character |

- **Wardrobe planning:**
  - The wardrobe plan comes from the episode packs: an outfit per character per story day + setting,
    plus timed changes within a scene.
  - A different outfit on a new story day unless the plan gives a reason (existing
    `assign_scene_wardrobes`, now wired).
  - **Fix:** the shot resolver must honour timed changes (`outfit_for_scene_time`); today it ignores
    them (factmap §1).
- **CAST LOCK:**
  - Enabled only when every required item is picked.
  - Lock writes `ApprovalEvent(CAST_LOCK)` over the hash of every picked asset version, and **creates
    the identity lock for the whole season**. That **replaces** the lock currently created at episode 1's
    Gate 2.
  - **Every** episode row, including ones created later, gets the lock attached: this fixes the
    "series stalls at episode 2" bug (R-12.1).
- **Cost control:**
  - Step 4 shows the forecast (number of images and voices × unit price) before generating, and actual
    usage while it runs.
  - Re-rolls are counted.
  - There is a hard per-season step-4 cap (default **US$60**, editable at LOCK).

### 4.5 Step 5: Directing (auto, per episode)

- The **director** LLM role (shotcaller method, digest §3) runs per scene.
- **Input:** the scene from the pack, the relevant bible slices (only the characters and locations in
  this scene), the continuity state, the camera package, the pacing rule, and the available reference
  assets with their `view_name`s.
- **Output:** `ShotPlanV3[]`, one per **~5 s coverage shot = one Pika clip**:
  - `shot_id`, `coverage_role` (master / single / over-shoulder / insert / reaction);
  - `duration_s` (4–6 s);
  - `first_frame_state`, `end_state`;
  - camera (register, movement), lens/FOV (season package), blocking (lateral, depth), **eyelines**,
    focus target, lighting/palette, atmosphere, physics beats;
  - acting per body (behaviour, not labels), **listener reactions**;
  - dialogue lines (verbatim Thai from the pack, `speaker_id`, delivery note, `start/end` within the
    shot, cut-safe);
  - **reference picks**: ≤9 image assets (role, subject, view, `governs`, `must_not_transfer`) and
    ≤1 VOICE per speaker, ≤3 audio in total;
  - continuity locks.
- **Rules (Joey):**
  - "If a word doesn't produce a visible pixel or an audible sound, cut it."
  - Dialogue defaults to a locked or gentle camera.
  - Every listener reacts.
  - Cuts fall between lines.
  - No mouth mechanics for generated speech.
  - No on-screen text.
- **Thai duration:** each line has an estimated spoken duration (Thai syllable-rate estimator with a
  configurable rate). A line too long for one shot is split across linked shots at a phrase boundary,
  never mid-word.
- **Validation before render:** the shot state resolver checks identity, wardrobe (including timed
  changes), appearance state, prop holder/state, location light state, secret timing and reference
  counts. Invalid plans go back to the director once, then BLOCK with the reason.
- **No approval** (Q2: no storyboard gate). The shot list is visible on the episode page.

### 4.6 Step 6: Render + clip QA (auto)

- **Render route:** the T031 Pika H3 Flex Ref2VA route is promoted to a production preset after T031
  qualifies it. Details are in T031; the production-relevant points:
  - 480×832, 24 fps, ~5 s;
  - the references and voice sample are uploaded once per pod and reused;
  - one `POST /prompt` per attempt;
  - the canonical lease/budget/recovery (H-2 spec v3) applies unchanged.
- **Clip QA (NEW), cost-aware.** It runs **on the render pod** while it's up, with no per-call API cost:
  - **(a)** Thai ASR (Whisper large-v3-class, pinned) → word match against the planned line;
  - **(b)** face-identity similarity (ArcFace-class embedding against the locked face) per speaker;
  - **(c)** basic technical checks (black frames, freeze, audio level, duration).
  - **Lipsync** is best-effort, as a sync score if available; otherwise it is left to Gate 2.
  - A **vision LLM** check (wardrobe/prop/continuity) runs **only on clips flagged** by (a)–(c), or on a
    1-in-N sample. That keeps LLM calls low.
  - The exact models are pinned in the render image.
- **Retries:** ≤2 automatic re-renders per shot, with a different seed. Then the shot is marked
  `NEEDS_ATTENTION` and the episode continues; the operator sees it at Gate 2 and can Revise.
- **Cost:** GPU seconds are metered per clip (lease accounting already exists).

### 4.7 Step 7: Edit (auto)

| Element | Spec |
|---------|------|
| **Recap** | ≤10 s, cut from the previous episode's **accepted** footage per the pack's recap plan, with a "previously" voice/subtitle line optional. No new render. Episode 1 has none |
| **Assembly** | Shots in order, trimmed to cut-safe points; **use each clip's native audio** (dialogue + ambience). Today `plan_master` ignores clip audio, so this is changed (R-7.1) |
| **Transitions** | Cut by default; crossfade or fade only when the director marks it (scene/time jumps). Implement fade/xfade in the exporters (schema exists) |
| **Music** | A season **music library** (YuE2 instrumentals, ~10–15 cues by mood, generated once in step 4's season jobs on RunPod) → cue per scene by mood tag; **ducked under dialogue** (sidechain); rights record per cue |
| **SFX** | A season SFX library + per-episode gaps, generated with **ElevenLabs Sound Effects v2** from director/edit cues (e.g. "knife on board, close"); stored and reused |
| **CTA end card** | ≤5 s template: next-episode title/time ("ตอนต่อไป พรุ่งนี้ 19:00"), follow prompt; Thai + small EN; brand-safe; no new render |
| **Mix/loudness** | Dialogue priority; target **−14 LUFS integrated, −1 dBTP**; consistent across episodes |
| **Captions** | Thai **burned in** (existing libass); EN + **ZH** soft tracks (SRT) timed to the same cues; ZH translated by the LLM in step 3 (the pack carries ZH) and checked against timing limits |
| **Variants** | 9:16 masters for YouTube Shorts, TikTok, Facebook; covers; 3 hook cuts (existing) |

### 4.8 Step 8: Metadata and thumbnail drafts (auto, before Gate 2)

- **The LLM drafts per platform slot × language (TH / EN / ZH):**
  - title, description and social caption;
  - **hashtags** (≤30; the platform-specific count is applied);
  - CTA line;
  - the **AI disclosure** text.

  Grounded in the episode pack; no spoilers beyond the episode.
- **Thumbnail:**
  1. 3 key-art variants (Nano Banana Pro, from locked character, location and state assets, with the
     episode's key emotion).
  2. Local composite of the **Thai title** (licensed Thai font; rights record).
  3. The operator picks one at Gate 2.
- The drafts **prefill** the existing Gate 2 metadata form. The operator edits; the sealed manifest
  (existing) binds exactly what was approved.

### 4.9 Step 9: Gate 2 (existing, extended)

- The existing page adds:
  - prefilled drafts;
  - the thumbnail pick;
  - caption tracks per language;
  - recap and CTA previews;
  - clip QA flags;
  - the cost breakdown (§11).
- Approve & schedule seals the manifest and schedules all slots (§9).

### 4.10 Step 10: Teaser

- **Trigger:** once **≥3 episodes are approved**.
- **Content:** a 30–60 s teaser from accepted footage, hook-led, under the reveal limit (`PreviewPlan`,
  extended beyond episode 1 sources and the 90 s maximum). Plus copy drafts and a thumbnail pick.
- **Release:** a **`PROMO_CUT` slot**, scheduled **3 days before episode 1** at 19:00 ICT on all
  platforms.
- **Gate:** `TEASER_FINAL`, with the same actions as Gate 2.
- **Timing:** if teaser approval would land less than 3 days before episode 1, the scheduler blocks
  episode 1 and asks the operator to move the start date, or to post the teaser late.

---

## 5. Continuity model (R-12.2)

| Concept | Record | Who sets it | Checked where |
|---------|--------|-------------|---------------|
| Story day / time | `StoryTime` per scene | Episode builder | Pack critic, directing validation |
| Wardrobe | `WardrobeBible` + `SceneWardrobeAssignment` + timed outfit events | Wardrobe planner from packs | Shot resolver (incl. timed), clip QA (vision on flags), Gate 2 |
| Appearance state | NEW `AppearanceState` (character, kind, description, valid story days/scenes, asset) | Episode builder → step 4 picks | Shot resolver, clip QA |
| Prop state + holder | `PropSheet` + `StateEvent` | Episode builder | Existing holder/hand validators |
| Location light state | `LocationLayout.allowed_light_states` + scene light state | Episode builder | Shot resolver (picks the coverage plate for that light state) |
| Extras | NEW `ExtrasRole` + picked looks | Episode builder → step 4 | Director (references ≤ limit) |
| Knowledge / secrets | Secret ledger | Bible | Pack critic, director |

---

## 6. Reference selection per shot (R-5.3)

- **Image budget:** 9 slots. The priority order:
  1. Each on-screen speaking character: **face/view** chosen by framing (tight → tight face; wide →
     full-body front; profile shots → 3/4 or profile).
  2. That character's **outfit**.
  3. The **appearance state** (if active).
  4. The **location plate** matching the coverage role and the light state.
  5. **Props** in hand or in focus.
  6. Non-speaking visible characters.
  7. Extras looks.
- When over budget, drop from the bottom of the list and log what was dropped.
- **Audio:** the VOICE reference of each speaker in the shot (≤2 speakers → ≤2 audio).
- **The resolver chooses among multiple `AssetSheet` views** (today it requires exactly one sheet per
  subject; factmap §3). The selection is deterministic and recorded in the shot plan, for replay.

---

## 7. Audio, music and SFX providers

- **Voices:** ElevenLabs Voice Design API (create previews → create voice from the chosen preview →
  text-to-speech for the reference sample).
  - Models `eleven_v3` / `eleven_v4` (Thai-capable; factmap fact).
  - Voice slots and credits are metered (§11).
  - A **paid plan is required** (the free tier has no commercial licence and 3 slots).
- **SFX:** ElevenLabs Sound Effects v2. Each generated effect is stored as an asset with a rights record.
- **Music:** YuE2 instrumentals on RunPod (existing ARISA/YuE2 tooling, wrapped in a Drama Box job).
  Season library; rights record per cue.
- **Pika native audio** stays the dialogue and ambience source. The ElevenLabs reference samples
  condition the voice; they are never mixed into the episode.

---

## 8. QA summary

Clip QA (§4.6), the existing technical and observation QA on the assembled episode, and Gate 2. A
blocking finding (CRITICAL) stops Approve, as today. Unknown coverage is displayed, never silently
passed.

---

## 9. Release and scheduling

- **Cadence:** daily at **19:00 Asia/Bangkok**. Episode n posts on `start_date + (n−1)` days; the teaser
  posts at `start_date − 3 days`.
- **Platforms:**
  - **YouTube Shorts** (9:16, ≤3 min);
  - **TikTok**;
  - **Facebook** (Reel or video route, decided in T032 by the format/length rules and AI-disclosure
    support).

  Instagram is excluded. The publishing transports are T032 work, and **v3 cannot release live until
  T032 is qualified**.
- **Buffer rule:** the scheduler refuses to set a start date unless **≥5 episodes are approved**, and it
  keeps production ≥3 days ahead. If the buffer drops below 2 days, the bot alerts. Both numbers are
  configurable.
- **Extension:** new episodes continue the daily cadence after the last planned episode.

---

## 10. Providers and adapters

### 10.1 LLM: subscription first, then decide

**Operator decision (11 Nov):** test with the **Claude subscription** first, measure the tokens and
quota per episode, then choose between Claude Max ($200/month), the Claude API, or a cheaper capable
model.

- **`LlmProvider` interface (exists, as `FakeLLMProvider`)** with these adapters:
  1. **`ClaudeSubscriptionProvider`:**
     - Runs `ai-route` with a NEW role `dramabox-llm`, which executes `claude -p --output-format json`
       with a pinned model (default **Sonnet 5.5**; **Opus 5.5** for the bible and episode builder).
     - Records `usage` (input, output and cache tokens) and **`total_cost_usd`** (Claude Code's
       API-equivalent cost) from the JSON result, plus Pro 5-hour/weekly window deltas (`ai-route
       --quota` before and after a batch).
     - The ai-route role **refuses when Pro is off pace**. Production must not starve orchestration.
  2. **`AnthropicApiProvider`:** metered key, prompt caching for the long system prompts (Joey method,
     bible).
  3. **`OpenAICompatibleProvider`:** GLM / Qwen / DeepSeek-class models, for the cost comparison.
- **Role → model** is configuration, so switching providers needs no code change.
- **Structured output:** every role returns JSON validated against the record schema. Invalid output →
  one repair attempt → BLOCK with the reason.
- **Caveat for the operator:** using a consumer subscription for automated production is for the
  **pilot measurement**. Confirm that its terms fit before relying on it for a full season.

### 10.2 Other adapters (fake by default; live behind a per-provider switch)

| Adapter | Live service | Metered unit |
|---------|--------------|--------------|
| `ImageGenProvider` | Nano Banana Pro (Vertex). **One Nano Banana process at a time**, because the quota is shared with ARISA SFW; a cross-project lock file is required | Images |
| `VoiceDesignProvider`, `TtsProvider`, `SfxProvider` | ElevenLabs (paid plan) | Credits; voice slots |
| `MusicProvider` | YuE2 on RunPod | GPU seconds |
| Render | Pika H3 Flex (T031 route) | GPU seconds |
| `ClipQaProvider` | On-pod Whisper + face embedding; flagged clips → LLM vision | GPU seconds; LLM tokens |
| `Notifier` | Telegram Dramabox Bot | Free |
| Publishing | T032 transports | Platform quotas |

---

## 11. Cost and quota meter + pilot (R-12.13)

- **Every paid call** writes a `UsageRecord`:
  - provider, model, step, season, episode, unit, item;
  - tokens or units;
  - the actual charge (or `total_cost_usd` for subscription calls);
  - for subscriptions: the quota-window percentages before and after the batch.
- **The Costs page and bot summaries** show:
  - per episode: the actual total and per step/provider;
  - per season: actual vs forecast;
  - per provider: month-to-date, plus subscription quota left (ElevenLabs credits and slots via
    `/v1/user/subscription`; Claude Pro windows via `ai-route --quota`).

### 11.1 Pilot plan (before any full season)

| Pilot | What runs | Measures |
|-------|-----------|----------|
| **P0** | Steps 1–4 for a short test season (4 episodes planned, 2 characters, 2 locations), live LLM via subscription, live Nano Banana and ElevenLabs | Tokens and $-equivalent per step; images and voices per character; step-4 cost |
| **P1** | 1 full episode, steps 5–9, live render (after T031 qualifies) | **Cost per episode** by provider; GPU seconds per clip; QA flag rate; LLM tokens per episode; quota % per episode |
| **P2** | 3 more episodes | Variance; then the **decision table**: subscription (Pro or Max) vs API vs a cheaper model, and the production pace |

**Output:** `PILOT-REPORT.md`, with measured numbers and a recommendation. The operator decides the LLM
plan, the pace and the season start.

---

## 12. Cross-cutting

1. **Rights and provenance** for every asset: model, provider, prompt hash, seed, licence. AI and
   synthetic-voice disclosures per slot (existing). ElevenLabs commercial use requires a paid plan.
2. **Content safety:** an original-only check (no real persons, brands or celebrity likeness) in the
   critic and step 4 prompts. No on-screen text in generated frames.
3. **Budget:** per-episode cap $10 (existing policy, until the pilot); a season cap = episodes × cap +
   the step-4 cap. 80% and 100% alerts. A hard stop at the cap.
4. **Season 2 reuse:** a locked cast can be imported into a new season (copy-on-import with a lineage
   link). NEW, v3.1.
5. **Backups:** the DB and object volumes are added to restic coverage (runbook).
6. **Amend and invalidation:** changing a picked asset or a pack after a lock runs the existing
   dependency helpers, which list the affected episodes and shots and mark them stale. The operator
   confirms the regeneration cost first.

---

## 13. Data-model changes (summary)

- `GateType` += `STORY_LOCK`, `CAST_LOCK`, `TEASER_FINAL`; Gate 1 gains Revise.
- NEW records:
  - `SeasonBibleV3`, `CharacterProfile`, `EpisodePackV3` (unifies the V1/V2 episode records);
  - `SeasonDemandList`, `PickItem` / `PickCandidate` / `PickVote` / `CastLock`;
  - `AppearanceState`, `ExtrasRole`;
  - `ShotPlanV3`, `ClipQaResult`;
  - `MusicCue`, `SfxAsset`, `MetadataDraft`, `ThumbnailCandidate`;
  - `UsageRecord`, `Notification`.
- `ProductionLimits`: episode duration 105–135 s (target 120), episodes per season 20–40.
- Migrations: new numbered migrations (0027+) with the full no-delete/no-truncate/integer guards. The
  contract package is bumped (guardian-owned).

---

## 14. Reuse and change map (from factmap)

| Reuse as-is | Wire up (CALLABLE → WIRED) | Change | New |
|-------------|----------------------------|--------|-----|
| Auth, sessions, CSRF, owner scope; Gate 2 page + metadata sealing; Thai caption burn-in; variants, covers, hooks; budget service; lease/recovery (H-2); progress JSON base | Rich bible + ledgers; wardrobe assignment + timed outfits; `plan_reference_demands`; V2 directing compiler (fed by the director LLM); `dispatch_v2_routed_attempt`; poster/preview compositor | T039 "episodes > 3 are maps" rule; `plan_master` (use clip audio); exporters (fades); shot resolver (multi-view + timed outfit); intake limits; identity lock at CAST LOCK; scheduler in compose; Gate 1 Revise | Stepper UI, picks UI, `ImageGen`/ElevenLabs/YuE2/QA adapters, director role, music + SFX, metadata drafts, thumbnails, teaser slot, Dramabox Bot, cost meter, pilot |

---

## 15. Build phases (each its own package, built offline first)

| Phase | Content | Depends on |
|-------|---------|------------|
| **A Foundations** | Gate types; season and episode state machines; stepper shell + Episodes board + waiting list; `UsageRecord` + Costs page; Dramabox Bot (fake transport, then live); the series-lock bug fix; scheduler in compose | — |
| **B Story** | Script Maker modes + Gate 1 Revise; `SeasonBibleV3`; `EpisodePackV3` for all episodes; season critic; demand list; STORY LOCK; `LlmProvider` adapters + the `dramabox-llm` ai-route role | A |
| **C Cast** | Picks engine + UI; `ImageGenProvider` (castkit/scenecraft builders); sheet views, expressions, outfits, states, extras, props, locations + coverage; ElevenLabs voice design; wardrobe wiring; CAST LOCK | A, B |
| **D Direct + Render** | Director role + `ShotPlanV3`; Thai duration estimator; reference selection; validation; production render preset from T031; clip QA on the pod | C, **T031 qualified** |
| **E Edit** | Recap; native-audio assembly; fades; YuE2 music library + ducking; ElevenLabs SFX; CTA card; loudness; EN/ZH captions | D |
| **F Release** | Metadata drafts; thumbnails; Gate 2 extensions; teaser + `TEASER_FINAL` + slot; buffer rule; extension flow | E; **T032** for live |
| **G Domain + pilot** | dramabox.aivora.agency (operator-authorised); live switches; pilots P0–P2; `PILOT-REPORT.md` | A–F (P0 needs only A–C) |

Each phase gets a build brief, a GLM build, a Codex review, and a full `make check` + `make pilot` by
the orchestrator.

---

## 16. Acceptance tests (offline unless marked LIVE)

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

---

## 17. Requirement trace

R-1.x → §4.1 · R-2.x → §4.2 · R-3.x (incl. 3.7 extension) → §4.3 · R-4.x → §4.4, §5, §6 · R-5.x → §4.5, §6 ·
R-6.x → §4.6, §11 · R-7.x → §4.7, §7 · R-8.x → §4.8 · R-9.x → §4.9, §9 · R-10.x → §4.10 · R-11.x → §3 ·
R-12.x → §5, §11, §12 · R-12.13 (meter + pilot) → §11.

## 18. Open items (decide during critique or pilot)

| O | Item | Default until decided |
|---|------|-----------------------|
| O-1 | Live trend sources for Script Maker mode A | Mode B only, until sources are chosen |
| O-2 | Clip-QA models (ASR, face embedding, lipsync) and their licences | Whisper-class ASR + ArcFace-class embedding on the pod; lipsync left to Gate 2 |
| O-3 | Thai title font licence for thumbnails and the CTA card | Pick a font licensed for commercial use, with a rights record |
| O-4 | Facebook route (Reel vs video) for a 2-minute episode; AI label support | Decided in T032 |
| O-5 | LLM plan after the pilot (Pro / Max / API / cheaper) | Subscription during the pilot only |
| O-6 | The step-4 season cap value | US$60 |
| O-7 | Buffer rule numbers | 5 approved before the start; keep 3 days ahead |
