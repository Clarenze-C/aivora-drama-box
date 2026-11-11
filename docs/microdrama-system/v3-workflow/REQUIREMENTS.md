# Drama Box v3 — requirements and coverage checklist (DRAFT for operator confirmation)

Author: Opus orchestrator, 11 Nov 2026. This is the "did we cover everything" layer between the
operator's [decisions](DECISIONS.md) and the detailed engineering spec. Nothing here is built yet.

Facts come from [factmap.md](factmap.md) (existing code), [joey-digest.md](joey-digest.md) (Joey's
methods) and [../T031-fix-round/pipeline-map.md](../T031-fix-round/pipeline-map.md).

Status tags:
- **HAVE**: wired today.
- **PART**: callable but not wired, or partial.
- **NEW**: absent today.

Every requirement has an ID (R-x.y) so the spec and the tests can trace back to it.

> **Operator answers, 11 Nov.** These override the rows below wherever they differ; see DECISIONS.md.
> - **Shape (R-1.1, R-3, R-6.3):** about **120 s episodes, 20–30 per season, daily release**, roughly a
>   30-day series. Slower, cinematic pacing.
> - **Extendable season (R-3.7, new):** after launch, viewership can trigger an **"Extend season"** action. It
>   reopens the episode builder for N more episodes on the same locked canon and cast. Only new items go
>   through picks, and STORY/CAST LOCK amendments apply only to the additions. Planning keeps an
>   **extension seam**: threads that can grow without breaking the ending.
> - **Takes (Q2):** 1 take + QA retries; no storyboard gate.
> - **Pace (Q3):** **cost and quota meter + pilot first (R-12.13, new).** Measure the real cost per episode
>   and the usage per provider before choosing a production pace. Usage covers RunPod GPU seconds, LLM
>   tokens, Nano Banana images, ElevenLabs credits and voice slots, and YuE2 GPU. Production should use
>   **metered API keys, never the team's Claude Pro / z.ai / Codex development subscriptions**.
> - **Captions (R-8.2):** Thai burned in + **English + Mandarin**; Vietnamese and Bahasa later.
> - **Platforms (R-9.2):** **YouTube Shorts, TikTok, Facebook**; no Instagram. Facebook's AI-disclosure
>   route is held today, and T032 must verify it and the 2-minute format route.
> - **Notifications (R-11.6):** a dedicated **Dramabox Bot** on Telegram, separate from JARVIS. The
>   operator creates the bot token with BotFather.
> - **Images (R-4.10):** Nano Banana Pro. **Music and SFX (R-7.3, R-7.4):** YuE2 instrumentals and
>   ElevenLabs Sound Effects v2.
> - **Recap and CTA (R-7.7, R-12.8):** a short recap of the previous episode at the start (cut from
>   accepted footage, no new render) and a CTA end card at the end of every episode.
> - **Recurring extras (R-4.7, revised):** roles that recur (≥2 episodes, any line, or recognisable in ≥2 scenes; e.g. secretary, personal doctor) become `SUPPORTING` characters with a locked character-bible package. Only one-off background roles stay in the extras pool. Voices are made manually in Botnoi Web Studio V4 and uploaded (R-4.6, revised).
> - **ElevenLabs:** the account is on the **free tier** (10k credits/month, 3 voice slots, no commercial
>   licence). A paid plan is needed before a real season.

---

## 0. Shape of the product

- **Season-level steps (once per season):** 1 Script → 2 Bible → 3 Episodes → **STORY LOCK** →
  4 Character bible → **CAST LOCK**.
- **Episode-level steps (repeat per episode):** 5 Directing → 6 Render → 7 Edit → 8 Metadata drafts →
  **9 Review + approve (Gate 2)** → schedule.
- **Season-level, once:** 10 Teaser → **teaser approval** → scheduled before episode 1.

The operator's original numbering had "review" at 8 and "metadata" at 9. Decision D3 moves the
metadata drafts **before** review, so the stepper shows Metadata = 8 and Review = 9.

| Gate | Where | The operator clicks | What becomes locked | Today |
|------|-------|---------------------|---------------------|-------|
| LOCK | after step 1 | Approve / Revise / Reject | Title, logline, premise, episode count/length, tone | HAVE as Gate 1 (Approve/Reject only; **no Revise**) |
| STORY LOCK | after step 3 | Approve / Revise (with notes) | Bible + every episode outline: cast, props, locations, story days, reveals, cliffhangers, dialogue | **NEW** gate |
| CAST LOCK | end of step 4 | Picks per item, then Lock | Chosen faces/views, outfits per story day, appearance states, props, locations + coverage plates, voices | **NEW** gate (today the identity lock happens at episode 1's Gate 2) |
| Gate 2 | step 9, per episode | Approve & schedule / Revise (timecoded) / Reject | Exact video, captions per language, hashtags, social copy, thumbnail | HAVE (metadata typed by hand today) |
| Teaser approval | step 10 | Approve & schedule / Revise / Reject | Teaser video + its post copy | **NEW** (preview code is PART; there is no slot) |

---

## 1. Script Maker → LOCK

| ID | Requirement | Today |
|----|-------------|-------|
| R-1.1 | Two entry modes: **(a) trend ideas**: the system researches what is trending and proposes 2–3 series; **(b) one-line title**, e.g. "GOD OF KITCHEN: homeless man is a kitchen prodigy" → 2–3 interpretations. | PART: 3-page wizard (idea, genre/tone, **episode count 1–10**); trend sources are MOCK |
| R-1.2 | Each proposal shows: title (TH/EN), logline, premise and thesis, genre/tone, episode count and length, main cast briefs, season promise, escalation, ending/cliffhanger style. | HAVE (mock content) |
| R-1.3 | LOCK actions: **Approve**, **Revise** (free-text notes → regenerate) and **Reject**. | PART: no Revise today |
| R-1.4 | Live LLM writer (Claude per SPEC) and live trend research. Sources and cost cap to be decided. | NEW (FakeLLM today) |

## 2. Season bible + character briefs (auto after LOCK)

| ID | Requirement | Today |
|----|-------------|-------|
| R-2.1 | Joey-format bible: premise → thesis → timeline → era aesthetics → world rules → locations → characters → relationships → story engines → production rules. "Density over prose." Unknown facts become `[TBD]`, not invention. | PART: the rich V2 bible (goals, strategy, flaw, secrets, payoff debts) is callable, not wired |
| R-2.2 | Per character: narrative function, visual lock, backstory, psychology, **speech / movement / stillness profiles**, **drift exclusions** (what they must not become), Thai register, pronouns and politeness level, and a **voice descriptor** feeding step 4. | PART (character brief + voice direction exist) |
| R-2.3 | A secret ledger (who knows what, reveal episode) and a season ledger (promise, payoff debts, escalation per episode). | PART (callable) |
| R-2.4 | One season camera package (spherical vs anamorphic look), palette and lighting language, shared by scenecraft and shotcaller. | PART (StyleBible stores text) |
| R-2.5 | Progress bar: one generation job (+ critic pass). | NEW in the UI |

## 3. Episode builder → STORY LOCK

| ID | Requirement | Today |
|----|-------------|-------|
| R-3.1 | **Plan every episode up front**, each as a full pack. Today only episodes 1–3 are full; later ones are maps only (an explicit T039 rule) and cannot be rendered. **This rule must change.** | PART |
| R-3.2 | Each episode: title, synopsis, scenes with **story day + time of day + location**, visible cast (incl. extras), props, wardrobe per character per scene, beats, reveals, **cliffhanger**, exact **Thai dialogue + English translation**, target duration. | PART: dialogue/cliffhanger sit in V1 records, the rest in V2 packs; **unify** |
| R-3.3 | Character psychology per episode, so a static bible can't reset characters every episode (Joey gap). | PART (knowledge per episode) |
| R-3.4 | The **demand list** (every character, outfit, appearance state, prop and location needed across the season) is derived from the packs for step 4. | PART (`plan_reference_demands`, callable) |
| R-3.5 | STORY LOCK screen: read bible + all episode outlines; Approve or Revise with notes per episode (only the noted episodes are regenerated). | NEW |
| R-3.6 | Progress bar: episodes planned (n/N), then critic checks. | NEW |

## 4. Character bible → CAST LOCK (picks, SFW-picks style)

| ID | Requirement | Today |
|----|-------------|-------|
| R-4.1 | **Characters (Joey castkit):** face lock on an **18% neutral gray field, no baked lighting**, forehead to upper chest → 2–3 variants → pick. Then sheet views: full-body front (headless), full-body rear, tight face, plus true profiles if needed. **Expression set** (neutral / signature / extreme). | NEW (one 64×64 mock anchor today) |
| R-4.2 | **Wardrobe:** an outfit library per character, valid for given **story days** and settings. Each scene gets an outfit for every visible character. A different outfit on a new day unless reuse has a reason. **Timed changes inside a scene** (e.g. changes into a chef's uniform). Outfits are built on the locked face (castkit outfit station), 2–3 variants → pick. | PART: WardrobeBible, day-based assignment and timed changes are callable but not wired; **the shot resolver ignores timed changes (gap)** |
| R-4.3 | **Appearance states:** injury, bruise, haircut, makeup, dirt or wet, aging, each with the story days or scenes it holds for. Each is a castkit "addition" (a versioned look) → pick. | PART (generic StateEvent only; no dedicated states, no generation) |
| R-4.4 | **Props:** each needed prop (e.g. a knife, a family recipe book) → 2–3 variants → pick. Prop states (clean or bloody, closed or open) and **who holds it** per scene. | PART (PropSheet + holder checks callable) |
| R-4.5 | **Locations (Joey scenecraft):** master plate 2–3 variants → pick. Then **matching coverage plates** (reverse, tighter) with the same geometry, time of day and weather; one per time of day needed. | PART (LocationLayout callable; no plate generation) |
| R-4.6 | **Voices:** per character, **ElevenLabs Voice Design (Thai, v3/v4)** from the voice descriptor → 2–3 candidates of 10–15 s → pick. The pick is stored as the character's **VOICE reference** (WAV + ElevenLabs voice ID + provenance). Chatterbox has no Thai. | NEW |
| R-4.7 | **Extras / background cast** (diners, kitchen staff, crowd): a reusable extras pool, not full characters. | NEW (no extras type today) |
| R-4.8 | **Picks UI:** per item, a grid of 2–3 candidates with zoom; Pick, **Re-roll** (with an optional note) and Lock. Same behaviour as ARISA's SFW picks: votes don't start work, an explicit Lock does. | NEW in Drama Box (the pattern exists in ARISA: SQLite + vanilla JS) |
| R-4.9 | CAST LOCK = one Lock that freezes every pick (hash-bound). Later changes need an explicit re-lock, which flags affected episodes. | NEW (replaces the episode-1 Gate 2 identity lock) |
| R-4.10 | Image model for faces, outfits, props and locations: **to decide** (Nano Banana Pro is available, but its quota is shared with ARISA SFW, and only one Nano Banana process may run at a time). | Decision needed |
| R-4.11 | Progress bars: per category (characters / outfits / states / props / locations / voices): generated n/N, picked n/N. | NEW |

## 5. Directing (Joey shotcaller, per episode, auto)

| ID | Requirement | Today |
|----|-------------|-------|
| R-5.1 | An LLM director turns each scene into **~5-second coverage shots**, one Pika clip each: coverage role, duration, first-frame state, camera/lens (season package), blocking, **eyelines**, focus, light, atmosphere, physics, acting, **listener reactions**, cut-safe dialogue (never cut mid-word). | PART: today's directing is rule-based "medium shot, static"; the V2 compiler is callable but **needs per-beat intent nobody supplies, which this fills** |
| R-5.2 | Joey rules: "if a word doesn't produce a visible pixel or audible sound, cut it"; dialogue defaults to a locked or gentle camera; behaviour, not emotion labels. | NEW |
| R-5.3 | Per shot, pick the **right references** within Pika's limits: ≤9 images (character view, outfit, appearance state, prop, location plate) + **1 voice reference per speaker** (≤3 audio). This needs multi-view selection; today the resolver takes exactly one sheet per subject. | PART |
| R-5.4 | Speakers per shot ≤2 (current limit); a Thai duration estimate per line; long exchanges split across linked shots. | PART |
| R-5.5 | Shot list visible in the workbench before rendering, with **no approval required** (auto), unless the operator wants a storyboard gate (Q2 below). | — |

## 6. Render (Pika H3 Flex Ref2VA, per episode, auto)

| ID | Requirement | Today |
|----|-------------|-------|
| R-6.1 | MiniMax H3 + Pika H3 Flex Ref2VA LoRA on a RunPod A40; 480×832, 24 fps, ~5 s per clip; native Thai speech conditioned on the CAST LOCK voice reference. | T031 in progress (benchmark harness; H-2 build running) |
| R-6.2 | Automatic QA per clip (identity, lipsync, Thai speech, wardrobe/prop continuity); bounded auto-retries; then **takes per shot**: 1 or 2–3 for picks (Q2). | PART (QA observers are mock) |
| R-6.3 | Budget per episode is enforced. **Real cost is unknown until T031:** a 3–5 minute episode is about 36–60 clips plus retries, and the current policy cap is **US$10 per episode**. | Measured in T031 |
| R-6.4 | Progress bar: clips rendered / accepted / retrying, out of N. | PART (progress model counts shots) |

## 7. Edit (auto)

| ID | Requirement | Today |
|----|-------------|-------|
| R-7.1 | Assemble shots with **the audio Pika generated** (dialogue + ambience). Today the editor ignores clip audio and lays separate TTS lines, so this must change. | NEW (switch) |
| R-7.2 | **Transitions:** cut by default; crossfades and fades only where motivated. | PART (schema only; the exporter can't render fades) |
| R-7.3 | **Background music:** instrumental per scene or mood (YuE2, which we already use), ducked under dialogue; rights recorded. | NEW (YuE2 runs elsewhere; no Drama Box hookup) |
| R-7.4 | **SFX:** source to decide (ElevenLabs sound-effects generation, or a licensed library). | NEW |
| R-7.5 | Thai captions burned in, timed to the actual speech; soft caption tracks per language (R-8.2). | HAVE (Thai + English) |
| R-7.6 | Platform variants, covers and three hook cuts (20–40 s). | HAVE |
| R-7.7 | Opening title card or end card with CTA ("next episode" / follow): **to decide**. | NEW |

## 8. Metadata drafts (auto, before Gate 2)

| ID | Requirement | Today |
|----|-------------|-------|
| R-8.1 | The LLM drafts per platform slot: title, description and social caption, **hashtags (≤30)**, CTA, and the **AI disclosure** text. The operator edits them in the Gate 2 form, prefilled. | PART: the form exists but you type everything |
| R-8.2 | **Multi-language captions:** translate the subtitles into the chosen languages (Q5) and time them to the same cues. | PART (TH+EN only; other locales reuse the English text) |
| R-8.3 | **Thumbnail/cover generator:** a designed thumbnail (key character still + Thai title art), 2–3 variants → pick. Today the cover is just a midpoint frame crop. | PART (poster compositor callable; no title art generation) |

## 9. Review + approve (Gate 2) → scheduler

| ID | Requirement | Today |
|----|-------------|-------|
| R-9.1 | One screen per episode: master video, variants, hooks, captions per language, metadata per slot, thumbnail, QA findings, cost. **Approve & schedule / Revise (timecoded) / Reject.** Revise rebuilds only what's affected. | HAVE |
| R-9.2 | The scheduler posts at the cadence chosen at LOCK. YouTube and TikTok first; Instagram and Facebook are **held** (the AI-disclosure capability isn't supported yet). | PART: publishing is mock (T032); **the scheduler isn't even in the staging compose** |

## 10. Teaser (once per season)

| ID | Requirement | Today |
|----|-------------|-------|
| R-10.1 | A 30–90 s teaser cut from accepted footage (hook-led, no spoilers past the reveal limit), with its own copy and thumbnail. | PART (episode-1 preview, ≤90 s, callable) |
| R-10.2 | Its own release slot, scheduled **X days before episode 1** (Q4); a teaser approval like Gate 2. | NEW (no slot; `PROMO_CUT` kind exists) |

---

## 11. UI at dramabox.aivora.agency

| ID | Requirement | Today |
|----|-------------|-------|
| R-11.1 | Private, owner login only, at **dramabox.aivora.agency**: Traefik on Coolify, Let's Encrypt TLS, the DNS record, secure cookies. Per the domain runbook; you authorise the DNS and deploy. | PART (runbook written, not executed; staging on 127.0.0.1:8093 is mock) |
| R-11.2 | **Checkout-style stepper:** tabs 1–10. Each shows a status (not started / running x% / **waiting for you** / locked ✓ / blocked), and the active step shows its progress bars. | NEW (only the 3-page intake has steps) |
| R-11.3 | Season view: steps 1–4 + 10. Episode list: each episode has its own mini-stepper (5–9) and status. | NEW |
| R-11.4 | **"Waiting for you" is always obvious:** a badge on the tab + a list on the home screen. No step advances past a gate without your click. | NEW |
| R-11.5 | Live progress (polls the existing `progress.json`), costs per step, episode and season, and **season total vs budget**. | PART (episode costs only; no season total) |
| R-11.6 | **Notifications:** Telegram message (via JARVIS) when a gate is waiting or a run is blocked. | NEW (no notifier today) |

## 12. Cross-cutting (the "don't miss it" list)

| ID | Item | Today |
|----|------|-------|
| R-12.1 | **Series bug:** episodes created after episode 1 never get the cast lock attached, so the writer stalls at episode 2. Must fix. | Bug |
| R-12.2 | **Continuity state** across scenes and episodes: outfit per story day, timed changes, injuries/hair/makeup/dirt/wet, prop holder/state, location time of day / light. Validated before render, checked by QA after. | PART |
| R-12.3 | **Extras pool** for crowd/background roles. | NEW |
| R-12.4 | **Rights and provenance** for every model output, voice, music and font. AI and synthetic-voice disclosures per platform. ElevenLabs commercial-use terms depend on the plan we're on (to verify). | PART |
| R-12.5 | **Season 2 reuse** of locked cast, voices and locations. | NEW (locks are season-scoped) |
| R-12.6 | **Versioning and invalidation:** changing a pick or a story fact flags exactly the affected episodes and shots. | PART (dependency helpers exist) |
| R-12.7 | **Budget:** per-step and per-episode caps, plus a season cap and forecast before CAST LOCK and before rendering. | PART |
| R-12.8 | **Recap / "previously on"** opener for episode 2+: to decide. | NEW |
| R-12.9 | **Content safety:** original fictional characters only; no real people or brands; no on-screen text in generated frames (text is added in edit). | PART |
| R-12.10 | **Deploy pieces:** scheduler service, backups of the DB and object volumes, live-mode switch per provider. | PART |
| R-12.11 | **Live providers still to wire and qualify:** LLM (Claude), trend research, image model, ElevenLabs, YuE2, SFX, Pika (T031), publishing (T032), analytics. | Mostly NEW |

---

## Open questions for the operator

| Q | Question | Why it matters |
|---|----------|----------------|
| Q1 | **Episodes per season and episode length?** Today: 1–10 episodes, 180–300 s each. Typical microdramas run 30–100+ episodes of 1–3 min. | Drives cost, the planning size and the GPU hours |
| Q2 | **Takes per shot:** one take (fix at Gate 2 with Revise), or 2–3 takes per shot to pick from like SFW? Also: an optional storyboard approval after directing? | 2–3 takes roughly doubles or triples the render cost |
| Q3 | **Production pace:** render all episodes as a batch after CAST LOCK, or one a day? | Cash flow and review load |
| Q4 | **Release cadence** (e.g. daily at 19:00 TH) and **teaser lead time** (e.g. 3 days before episode 1)? | Scheduler setup |
| Q5 | **Caption languages** beyond Thai and English? | Translation jobs and QA |
| Q6 | **Launch platforms:** YouTube + TikTok first (Instagram and Facebook are held on the AI-disclosure capability)? | T032 scope |
| Q7 | **Notifications** via Telegram/JARVIS when you're needed? | R-11.6 |
| Q8 | **Image model** for characters, outfits, props and locations: Nano Banana Pro (shared with ARISA SFW) or another? | R-4.10 and quota |
| Q9 | **Music and SFX sources:** YuE2 instrumentals for music? ElevenLabs sound effects, or a licensed library? | R-7.3, R-7.4 |
| Q10 | **Budget:** keep US$10 per episode as the cap until T031 measures the real cost? Is there a season cap? | R-6.3, R-12.7 |
| Q11 | **Recap opener and end card/CTA:** want them? | R-7.7, R-12.8 |
