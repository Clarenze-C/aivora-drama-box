# Fact map for the Drama Box v3 workflow spec (read-only, facts only)

The operator's target workflow has 10 steps, plus two locks:

1. Script Maker. Ideas come from trend research, or from a one-line title such as
   "GOD OF KITCHEN: homeless man is a kitchen prodigy". Then **LOCK**.
2. Season bible + character briefs.
3. Episode builder: every episode planned up front, with cast, props, locations,
   reveals and cliffhangers. Then **STORY LOCK** (review).
4. Character bible:
   - 2–3 variants per character, multi-angle, chosen picks-style (like ARISA's SFW picks);
   - 2–3 ElevenLabs voice candidates per character, 10–15 s each, picked;
   - props and locations in 2–3 variants each, picked;
   - wardrobe per story day.

   Then **CAST LOCK**.
5. Shot directing (Joey's shotcaller method).
6. Pika H3 Flex Ref2VA render with the chosen voice sample as the VOICE reference.
7. FFmpeg edit + captions + transitions + background music + sound effects.
8. Captions/hashtags/thumbnail drafted, then **Gate 2** review → scheduler.
9. Multi-language captions, hashtags, social captions and thumbnail (drafted before Gate 2).
10. A teaser before episode 1.

The UI must be at dramabox.aivora.agency, with a checkout-style 1–10 stepper,
per-step progress bars, and clear Next/Approve actions.

Map **what already exists** for each concern below. Report facts with `file:function`
or `file:line`, and mark each item **WIRED** (default worker/scheduler), **CALLABLE**
(exists but not wired), **MOCK**, or **ABSENT**. No design advice.

## Repos (read-only)

- `/root/AIVORA/drama-box` (branch `feat/microdrama-m0-m4`, `microdrama/src/microdrama/`;
  docs in `docs/microdrama-system/`, especially SPEC.md, the T039–T047 briefs/specs,
  and `deployment/staging/DOMAIN-RUNBOOK.md`).
- `/root/AIVORA/arisa`: only the SFW **picks site** (find it; memory names
  `picks_reset.py`, `nb_keep.py` and the picks votes flow).
- `/root/AIVORA/spectre-trading/studio`: only the voice audition flow
  (`examples/voice-audition/`, `scripts/tts_chatterbox.py`, `voice_merge.py`).
- An earlier map exists at
  `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/pipeline-map.md`. Don't
  repeat it; go deeper on the items below.

## Items

1. **Wardrobe and continuity state (T040/T041).**
   - Story-day model and outfit-per-day assignment (`assign_scene_wardrobes`); reuse
     rules.
   - Character state changes (injury, hair, makeup, dirt/wet), prop state and holder,
     location time-of-day.
   - How a shot resolves "which outfit or state now" (the shot state reference
     resolver).
   - What the operator can see or edit.
   - For each, say whether it is WIRED or CALLABLE.
2. **Rich bible and episode packs.**
   - Exact fields of the V2 bible and EpisodePack: secrets, reveals, cliffhangers,
     cast per episode, props, locations, story days.
   - Why episodes after 3 are `scoped_map_only`, and what blocks generating every
     episode pack up front.
3. **Reference demand planning.**
   - How the needed characters, outfits, props and locations are derived from the
     episode packs (`plan_reference_demands`).
   - Multi-angle/view requirements (AssetSheet views).
   - Extras / silent visible cast.
4. **Workbench UI.**
   - Every route and page in `review/api.py` and `review/render.py`: what each shows
     and which actions exist (intake, candidate select, Gate 1, Gate 2, metadata,
     revise).
   - Is it server-rendered HTML? Which templates and tech?
   - The progress projection model (steps, counts, denominators) and whether it maps
     to stages.
   - Auth model (owner session, CSRF).
5. **Domain and deploy.** What `DOMAIN-RUNBOOK.md` and T046 require for a public
   hostname: DNS, TLS, the reverse proxy (Coolify/Traefik?), auth exposure, which
   ports, and what the operator must do.
6. **ARISA SFW picks site.** How variants are generated and shown; vote / keep /
   re-roll / reset; data storage; whether it is a reusable component, or the
   framework it uses.
7. **SPECTRE voice audition.** How candidates are generated and voted on
   (`votes.json` structure), and how a chosen voice is locked.
8. **Audio and music.**
   - Any background-music, SFX or transitions support in Drama Box editing; music
     rights fields.
   - Whether the YuE2/music tooling elsewhere in AIVORA is callable from Drama Box.
9. **Metadata, captions and thumbnails.**
   - Caption languages supported; translation step.
   - Hashtag/description generation (or owner-typed only).
   - Cover/thumbnail derivation.
   - Teaser/preview (T043) inputs, and how it would be scheduled before episode 1.
10. **Budget/cost per episode and per season,** as shown to the operator.
11. **Anything else a full series needs that the operator didn't list.** Name what the
    code or docs already model that is missing from the 10 steps. Examples: recap or
    hook openers, episode length rules, AI-disclosure labels, consent/rights records,
    multi-season reuse of locked cast, notifications to the operator.

## Output

- Read-only: no writes, no network.
- Put the full map in your final message, at most about 260 lines, using tables.
- Cite file references for every item.
