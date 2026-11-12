# Drama Box v3 workflow — operator decisions (source of truth for the spec)

Recorded by the Opus orchestrator from the operator's own words, 11 Nov 2026. The spec must not
contradict these. Changes need a new dated entry here.

## The 10-step workflow (operator, 11 Nov)

1. **Script Maker.** Either the system generates ideas from trend research, or the operator enters a
   one-line drama title (e.g. *GOD OF KITCHEN: homeless man is a kitchen prodigy*). → **LOCK**.
2. **LOCK generates** the storyline, the number of episodes, cliffhangers and secrets: the season
   bible and character briefs.
3. **Episode builder** constructs **all** episodes: the props, characters, cliffhanger and reveal in
   each.
4. **Character bible.** From the episode plan we know which props and characters are needed.
   - Generate 2–3 variants of each character, **picked SFW-picks style**, multi-angled.
   - Each character's voice: 2–3 variants, picked.
   - All required props, and location photos in 2–3 variants each, picked.
   - Use Joey's **castkit**.
   - This locks voice, character, prop and location consistency.
   - **Wardrobe:** different clothing for characters on different days and episodes. The operator
     explicitly flagged this as easy to miss.
5. **Joey's shotcaller v2** directs the individual shots.
6. **Image/reference-to-video on Pika H3 Flex**, using the character-bible assets and Pika's
   built-in voice, conditioned on the voice reference created in step 4.
7. **FFmpeg** + captions + transitions + background music + other SFX.
8. **Review + approve** → sent to the scheduler.
9. **Multi-language captions,** social hashtags and captions, and a thumbnail/cover generator.
10. **Teaser maker:** post before episode 1.

## Decisions (operator answers, 11 Nov)

| # | Question | Decision |
|---|----------|----------|
| D1 | Review the story text before spending on assets? | **Yes: a STORY LOCK** after steps 2–3 (bible + all episode outlines), before step 4. |
| D2 | Voice candidate source | **ElevenLabs or Chatterbox generate the reference voice sample** per character. The chosen sample is then used as the voice reference in Pika H3 Flex's built-in audio. Orchestrator facts (11 Nov): ElevenLabs supports Thai on `eleven_v4`, `eleven_v4_turbo`, `eleven_v3` and `eleven_v3_conversational` (not `multilingual_v2` or `flash`/`turbo v2.5`); the API key is present. Chatterbox `0.1.7` (in SPECTRE studio's venv) supports 23 languages and **not Thai**. |
| D3 | When step 9 metadata runs | **Draft before Gate 2.** The operator edits, then approves the video, text and thumbnail together. Nothing is published unreviewed. |
| D4 | Spec start | **Start now, covering every detail** so the wrong thing is not specced. |
| D5 | UI location | **dramabox.aivora.agency.** It does not resolve as of 11 Nov 02:00Z. DNS, TLS and deploy are operator-authorised steps. |
| D6 | UI shape | **A checkout-style stepper with tabs for steps 1–10.** Each step with generation shows its own progress bar. The UI must show which steps need a click on Next or Approve before the next stage. |
| D7 | Completeness | The orchestrator must double-check that nothing in the pipeline is missed. Wardrobe is the operator's example. |

## Implied gates (to confirm in the spec review)

| Gate | Step | What is locked |
|------|------|----------------|
| LOCK | 1 | Title/idea and the season direction |
| STORY LOCK | after 3 | Bible, episode count, every episode's outline, cast, props, locations, reveals and cliffhangers |
| CAST LOCK | 4 | Chosen character variants, multi-angle sheets, outfits per story day, props, locations, voices |
| Gate 2 | 8 | Per episode: video, captions in every language, hashtags, social captions, thumbnail |
| Teaser approval | 10 | Teaser video and metadata before episode 1. It may reuse the Gate 2 flow |

## Operator answers to the REQUIREMENTS open questions (11 Nov)

| Q | Decision |
|---|----------|
| Q1 | **About 2-minute episodes, 20–30 episodes per season, 1 episode released daily**, so one series runs about 30 days. The season can be **extended** depending on viewership. Pacing: high-quality, **slower, cinematic**, not the generic fast microdrama feel. |
| Q2 | Defaults OK: **1 take per shot** plus automatic QA retries, fixed at Gate 2 via Revise; **no storyboard gate**. |
| Q3 | Production pace is decided **after measuring the real cost per episode and the quota used per provider/subscription**. That makes a cost and quota meter plus a pilot measurement mandatory before a full season. |
| Q4 | Defaults OK: **daily at 19:00 Thailand time**; teaser **3 days before episode 1**. |
| Q5 | Captions: **Thai (burned in) + English + Mandarin**. Vietnamese, Bahasa Indonesia and others come later. |
| Q6 | Platforms: **YouTube Shorts, TikTok, Facebook**. Instagram is out; the operator believes it can't monetise. Orchestrator note: our Facebook capability record currently **holds** the AI-disclosure route, and T032 must verify Facebook AI labelling and the 2-minute format route. |
| Q7 | Telegram notifications, but through a **dedicated "Dramabox Bot"**, not JARVIS. |
| Q8 | Default OK: **Nano Banana Pro** for characters, outfits, props and locations. Its quota is shared with ARISA SFW, so only one Nano Banana process may run at a time. |
| Q9 | Music: **YuE2 instrumentals**. SFX: **ElevenLabs Sound Effects v2**. |
| Q10 | OK: **US$10 per episode cap** until T031 measures the real cost; season cap = episodes × cap. |
| Q11 | A **short recap of the last episode at the start** of each episode, and a **CTA at the end of each episode**. ("End card" means a few seconds at the end of every episode, not a separate episode.) |

**Orchestrator facts (11 Nov):** the ElevenLabs account is on the **free tier**: 10,000 credits a month (6,800 used; resets 12 Nov 00:45Z), 3 custom voice slots (2 used), no voice cloning, and free plans have no commercial licence. **A paid plan is needed before the first real season**: an operator purchase decision.

## D2 revised — voice source is Botnoi (operator, 11 Nov, later the same day)

**Supersedes D2's ElevenLabs/Chatterbox choice for character voices.**

- **Botnoi Voice** (native Thai AI TTS, https://voice.botnoi.ai/developer/api) generates each character's
  reference voice.
- Botnoi has built-in voice **expressions**. For each character we create **expression variants** (e.g.
  neutral, happy, sad, angry). Each shot attaches the **variant that matches the scene's emotion** as its
  Pika H3 voice reference. Example: the happy variant when the character is happy.
- **ElevenLabs remains the SFX source** (Sound Effects v2, per Q9). It is no longer the voice source.

Orchestrator facts (11 Nov), from a Context7 mirror of the Botnoi API reference; the official page renders
client-side and could not be read directly:
- `POST https://api-voice.botnoi.ai/openapi/v1/generate_audio` (V1) and `.../generate_audio_v2` (V2 premium).
- Header `botnoi-token`.
- Fields: `text`, `speaker` (an ID), `volume` 0.1–2.0, `speed` 0.5–2.0, `type_media` `mp3|wav`,
  `save_file`, `language` (`th`).
- Response: `audio_url` + `message`.
- **That reference documents no emotion/expression field**, no speaker-list endpoint, and no pricing or
  licence terms. The operator must confirm how expressions are selected (a field, or per-expression
  speaker IDs) and the plan and commercial terms.

## D2 refined — Botnoi expressions are manual uploads (operator, 11 Nov)

- The Botnoi **API only has v1/v2**. **Expressions exist only in Web Studio V4 (Beta)**, as inline tags,
  and **not all voices have V4**:
  - vocal actions: `[breath] [cough] [exhale] [sniff] [sneeze] [struggle] [sleep] [speak] [laughter] [sigh]`;
  - emotional reactions: `[surprise-ah] [surprise-oh] [surprise-wa] [surprise-yo] [dissatisfaction-hnn]`;
  - conversational cues: `[confirmation-en] [question-en] [question-ah] [question-oh] [question-ei] [question-yi]`.
- **So voice samples are made by the operator in Botnoi Web Studio V4 and uploaded into Drama Box.** The
  system prepares a per-character casting sheet (the expressions needed, a Thai script per expression with
  suggested tags), validates and normalises the uploads, records provenance, and binds them at CAST LOCK.
- Every speaking character must use a **V4 voice**, and the same voice across all its expressions.
- The Botnoi API is not on the critical path.

## Recurring extras become characters (operator, 11 Nov)

"For extras that appear more than once in the episode/series, we need to generate them as character
bibles as well. Example: secretary, personal doctor, etc." The spec implements three tiers:
- `PRINCIPAL`;
- `SUPPORTING`: recurring roles, auto-promoted when a role appears in ≥2 episodes, has any line, or is
  framed recognisably in ≥2 scenes; the operator can toggle at STORY LOCK. They get a lighter but locked
  package: face, front + face views, 2 expressions, outfits per day, and a voice only if they speak;
- `EXTRA`: one-off background roles.

Proposed alongside, pending the operator: raise the speaking-character cap from 3 to 5 per episode (≤2 per
shot).

## Operator, 11 Nov (later the same day)

- **O-12 resolved:** the speaking-character cap is **5 per episode** (≤2 per shot). **Recurring roles are
  auto-detected** (the `SUPPORTING` tier).
- **SFX:** ElevenLabs Sound Effects via **OpenRouter or fal.ai, whichever is cheaper**. A paid ElevenLabs
  plan is therefore not required, but the reseller's commercial-use terms must be verified.
- **Dramabox Bot:** the operator supplied the token for **@AIVORA_DramaBox_Bot** (id 9266503313, verified
  with `getMe`). It is stored as a FILE credential at `/root/.secrets/drama-box/dramabox-bot.token` (0600).
  - The token was pasted in chat, so it also exists in local root-only logs (`~/.claude/logs/user_prompts.jsonl`,
    the tool logs and the session transcript). **Rotate it with BotFather `/revoke` before going live**, and
    write the new token from the operator's own shell (`read -rs`).
  - The destination chat ID is pending: the operator must send `/start` to the bot.
- **Bot destination:** the operator sent `/start`. The private chat ID is stored at `/root/.secrets/drama-box/dramabox-bot.chat_id` (0600). A test message was delivered on 11 Nov (message_id 5).
- **O-11, Botnoi commercial use (operator, 11 Nov):** "There's no documentation anywhere about licenses on Botnoi website at all. But since its sales page specifically says Ads and product videos, Stories and audiobooks, I don't see any issue." **Operator-accepted basis.** Every Botnoi voice rights record stores this as `basis = OPERATOR_ATTESTED (Botnoi sales-page use cases: ads/product videos, stories, audiobooks; no licence document found; 11 Nov 2026)`, so it can be revisited if Botnoi publishes terms.

## Operator decisions on the final-round critique (11 Nov)

- **V3R-3, mixed emotions in one shot:** "Use the dominant emotion, but in the prompt specify his
  expression as he says whatever line. This maintains continuity rather than having the character suddenly
  switch from neutral to angry."
  - Spec: dominant = the line with the longest estimated spoken duration (a tie goes to the earlier line).
  - The prompt states each line's expression.
  - A missing or unapproved variant blocks dispatch.
- **V3R-11, base voices:** "I need the system to suggest and shortlist the 2–3 voices first (no need to
  generate). I will then generate the neutral and the type of expressions."
  - Spec: the system ranks an **operator-curated Botnoi V4 voice catalogue** (superseded 11 Nov: see "D2 update: Botnoi voice catalogue sources" below; public speaker-list endpoints exist)
    against each voice descriptor, and shows 2–3 suggestions with reasons.
  - The operator auditions them in Botnoi, records the pick, then generates and uploads the neutral and the
    expressions.
- The master spec is final at **v0.3** after two Codex critique rounds. The v0.1 baseline is pinned
  (`SPEC-v3-v0.1.md`, sha256 0a2677c9…).

## D2 update: Botnoi voice catalogue sources (operator + orchestrator, 11 Nov, ~12:20Z)

### What the operator said

- Speaker IDs are listed at https://voice.botnoi.ai/llms.txt.
- The marketplace (https://voice.botnoi.ai/marketplace/selectvoice) has **1,373 voices: 748 Botnoi Cast
  and 491 community voices**.
- Web Studio has character archetypes: grandma/grandpa voices, monk voices, and so on.

### What the orchestrator checked

- **Public speaker-list endpoints exist**, and need no token:
  - `GET https://api-voice.botnoi.ai/openapi/v1/get_speaker_data`: 373 voices, 116 Thai;
  - `GET https://api-voice.botnoi.ai/openapi/v1/get_speaker_data_v2`: 70 voices, 46 Thai.
- **The metadata per voice:**
  - gender;
  - age group (`Child` / `Teens` / `Adult`);
  - voice style, including **regional accents** (Northern 22, Southern 17, Northeastern 15 among the
    Thai V1 voices);
  - speech style, speed, a price tier and a sample WAV URL.
- A snapshot is in `botnoi-api-speakers-2026-11-11.csv` (443 rows, 162 Thai).
- **Correction (orchestrator, 12 Nov):** the API list **does** contain monk voices, but nothing in their
  names or style fields says so:
  - `582` Dhammanit (ธรรมนิตย์) and `583` Namo (นะโม) are labelled only "Male, Adult, Storytelling;
    Narrating";
  - their sample files are `vc_ctb_monk_paradon` and `vc_ctb_monk_sommha`;
  - the operator searched for "monk", found nothing, and then found it in Studio.

  The API's Thai `age_style` has only Child (12), Teens (38) and Adult (112), with no elderly category.
  Older-sounding voices sit under Adult (for example `19` Uncle Warm and `27` Aunty Grace).

  So the phase C importer can't infer archetypes from the API fields. Archetype labels (monk, elderly, …)
  come from operator additions or Studio. `ctb` in a sample filename **may** mark a contributed/community
  voice. That is unconfirmed, so the operator checks in Studio before using one (rule 4).
- *(Original 11 Nov text, superseded by the correction above:)* **The API lists contain no elderly or monk voices.** Those archetypes exist only in the marketplace
  and Studio.
- **V4 is Studio-only:** "not in the public API yet: the API serves V1 and V2". V4 costs 2 points per
  character, charged when the voice is created; downloads are free.
- llms.txt says nothing about licences; it says to check the website terms.

### Rulings

**This supersedes the earlier "Botnoi has no voice-list API" note under V3R-11.**

1. **The catalogue has two sources.**
   - **(a) Auto-imported** from the two public endpoints by a phase C importer, which refreshes it and
     stamps `last_verified`.
   - **(b) Operator additions** in `botnoi-v4-voices.csv`: marketplace and Studio voices that the API
     doesn't list, especially the archetypes (elderly, monk, …).
2. **`has_v4`** is confirmed by the operator in Studio. A voice with unconfirmed V4 may be shortlisted,
   but is flagged "confirm V4 in Studio".
3. **The shortlist matches on** gender, age group, accent (a regional Thai accent is a casting asset for
   Isan, Northern and Southern characters) and voice/speech style.
4. **Community voices: orchestrator default, pending operator confirmation.** Community voices may carry
   their creators' own terms. **Shortlists default to Botnoi Cast and API voices.** A community voice
   needs the operator's explicit per-voice approval, recorded in its rights record, since the O-11
   attestation covers Botnoi's own voices.

## T031 benchmark inputs (operator, 12 Nov)

- **Rights route for the private benchmark: CONFIRMED.** The benchmark runs under the MiniMax H3 Community
  License (Pika H3 Flex adapters); outputs are viewed privately from Singapore/Thailand only. Recorded as
  the operator's attestation.
- **Release-territory question:** the operator declined vendor contact. Their words: "No worries as many
  microdramas are already made with Pika and Minimax H3." Release rights stay T032/T033 evidence; this
  attestation covers the private benchmark only.
- **Thai listener for one-time calibration: available** (operator: "Yes"). Name and access are recorded
  at sign-off.
- **Reference images: GO.** Nano Banana Pro, two original adult fictional characters:
  - A (male, about 30) and B ("May", female, about 28);
  - candidates first, operator picks;
  - then A's home outfit (S08), the office and home sets, and envelope-01.
- **Botnoi Studio archetypes (operator):** Studio has **7 monk voices, 2 grandpa, 2 grandma, Ananda (little
  boy) and Bow (little girl)**. None is API speaker 582 or 583, so those two are additional API monk
  voices. All of these are Studio-only additions for `botnoi-v4-voices.csv`, entered with their Studio
  names when a season casts them. The T031 benchmark needs none of them.
