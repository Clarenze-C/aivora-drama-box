The strongest material to carry into Drama Box v3 is **flat identity references, physically consistent location coverage, precise dialogue staging, and character-specific voice/movement/stillness**. The platform syntax and interactive approval routines need replacement.

I use your stated H3 limits as the target contract. Fields below are proposed schema material, not claims about existing implementation or proven model behaviour. No files were changed.

**Source key**

All abbreviated line citations below refer to these files:

| Key | Source |
|---|---|
| C | [castkit-v1/SKILL.md](/tmp/claude-0/-root-AIVORA/413d5d13-a4ab-4480-be0b-31a0f3fd90a8/scratchpad/keep/joey-skills/castkit-v1/SKILL.md) |
| S | [scenecraft-v1/SKILL.md](/tmp/claude-0/-root-AIVORA/413d5d13-a4ab-4480-be0b-31a0f3fd90a8/scratchpad/keep/joey-skills/scenecraft-v1/SKILL.md) |
| D | [shotcaller-v2/SKILL.md](/tmp/claude-0/-root-AIVORA/413d5d13-a4ab-4480-be0b-31a0f3fd90a8/scratchpad/keep/joey-skills/shotcaller-v2/SKILL.md) |
| B | [story-bible-builder/SKILL.md](/tmp/claude-0/-root-AIVORA/413d5d13-a4ab-4480-be0b-31a0f3fd90a8/scratchpad/keep/joey-skills/story-bible-builder/SKILL.md) |
| M | [motiondojo-v1/SKILL.md](/tmp/claude-0/-root-AIVORA/413d5d13-a4ab-4480-be0b-31a0f3fd90a8/scratchpad/keep/joey-skills/motiondojo-v1/SKILL.md) |
| CB | Installed [character-builder/SKILL.md](/root/.claude/skills/synced/582df2e9-6fab-480c-8684-4076df1dfd63_621fcd3b-22d3-4b8c-abca-b954ae088c38/character-builder/SKILL.md) |
| CD | Installed [cinema-director-v3/SKILL.md](/root/.claude/skills/synced/582df2e9-6fab-480c-8684-4076df1dfd63_621fcd3b-22d3-4b8c-abca-b954ae088c38/cinema-director-v3/SKILL.md) |

**1. Castkit v1**

**Purpose and stations**
- Builds reusable character identity and wardrobe anchors before scene lighting is introduced.
- Five ordered stations: **face lock → additions → outfit build → outfit replacement → character sheet**.
- Supports photoreal and animated characters; sheets require an approved outfit image, and outfits require a locked face. (C:10–48)

**Concrete method**
- Separate subject realism from photographic lighting: **“The plate carries zero lighting; the scene does the lighting later.”** Keep skin, hair, fabric and metal believable while suppressing directional light, background falloff, contact shadows, spill, bokeh and atmosphere. (C:52–60)
- Every plate uses an **18% neutral gray field**, explicitly described as a color field with no floor, wall or horizon. Five requirements recur: uniform field; directionless illumination; zero exterior shadow; zero light bleed; complete realism/style description. Preserve true skin and garment colors. (C:81–123)
- Photoreal skin is matte, finely textured and flattering; avoid plastic/waxy skin, enlarged pores and unrequested blemishes. This is Joey’s beauty convention, rather than a general requirement for all realistic characters. (C:62–66, 100)
- Face-lock order: framing → reference anchor → build/heritage → skin → facial structure → eyes → brows/lashes → nose/lips/ears → hair → makeup → precisely located identity markers → baseline clothing → pose/expression → flat finish. Forehead-to-upper-chest framing gives the face most pixels. (C:209–230)
- References carry identity; text carries framing, pose, layering, fit and unresolved details. **“Attach the fewest images that carry what’s needed.”** Explicitly assign each reference’s authority so faces/materials are not averaged. (C:68–77)
- Permanent facial/hair changes use an identity firewall and a new versioned lock. Markers are positioned against anatomical landmarks. Expressions use three panels—neutral, signature, extreme—with muscular descriptions rather than emotion labels alone. (C:235–270)
- Outfit method: specify every garment, fabric, cut, closures, layering, footwear, jewelry, accessories and styling; build directly on the locked character. Generate an invisible-mannequin garment plate **only after a specific garment fails**. Replacement uses outfit/pose first, identity second. (C:274–332)
- Default sheet: **headless full-body front / full-body rear with head / tight face**. Every panel is dead-on; explicitly override the outfit reference’s angled or hip-cocked stance. Match skin tone across panels. Six panels add true profiles/detail but reduce face resolution. (C:336–442)
- Headless construction follows the neckline: hollow ghost-mannequin opening for a real collar; clean neck termination for open necklines. Hair disappears with the head, and empty headroom preserves figure scale. (C:366–400)
- Bans/conventions: no character names, numerical aspect ratios, image tags, separate negative blocks, lore or meta-commentary; no teeth-showing smiles unless requested. (C:446–457)

**Mapping to Drama Box**
- **Step 4**, feeding **5–6**. System prompt: preserve locked identity; scope references; build exact wardrobe; create flat references; change only explicitly authorized attributes.
- Records: `character_spec`, `face_lock_revision`, `identity_markers[]`, `render_style`, `style_lock`, `outfit_id`, `garments[]`, `layering_order`, `material_overrides`, `sheet_views[]`, `expression_set[]`, `pick_id`.
- Each view needs its own framing/orientation metadata. For H3, select usable individual views or panel crops rather than assuming a composite sheet transfers cleanly.
- Thai has no special role in these stills. Voice identity must be added separately; reserve H3 image slots for the views needed by the shot, within **9 images**, and bind voice samples separately within **3 audio references**.

**Drop/adapt and gaps**
- Nano Banana Pro is a candidate image adapter, not a locked choice. Drop the Soul Cinema exploration route, Higgsfield-specific “GPT-2” fidelity/cost claims, and user-facing tool selection.
- Convert proposals/checks into structured preparation and picks at **CAST LOCK**; do not reproduce repeated conversational confirmations.
- Your step 4 label leaves **expression sets, versioned appearance states and explicit sheet-view coverage** unspecified. Castkit supplies these, but supplies no voice reference or temporal acting calibration.

**New versus installed Character Builder**
- **New:** photoreal/animated fork, three described animation styles, a verbatim style lock, photoreal-to-animated translation, and animation-aware outfit replacement. (C:24–48, 105–116, 332; CB:10)
- **Stronger/newly explicit:** orthographic orientation clauses, prohibition of unsolicited three-quarter views, overriding the source pose, true 90° profiles, and a more detailed neckline decision table. The predecessor already asked for squared views, but lacked these defenses. (C:350–432; CB:460–506)
- Requested garment wording/logos receive clearer exact-description instructions; text accuracy itself already existed. Flat gray, direct outfit builds, identity firewall, expression triptychs, reference economy and the three-panel layout are **inherited**, not new. (C:129–142; CB:30–108, 308–354, 460–530)

**2. Scenecraft v1**

**Purpose and modes**
- Builds photographed-looking locations, environments and scene stills with coherent depth and light.
- Four modes: **A empty environment; B people in scene; C matching coverage set; D protected plate edit**.
- Registers include narrative, editorial, action, performance, empty locations, night exterior and lit night interior/urban. (S:14–23, 174–196)

**Concrete method**
- Plan six buckets before writing: shot/camera → subject placement → resolvable detail → world/materials → light/air → capture/finish. Use a planning grid, then express positions in ordinary prose. (S:71–97)
- Thirds and depth: center only when symmetry motivates it; leave room ahead of movement; stagger people in depth; organize **foreground mass → subject → deep background**. (S:84–97)
- Resolution filter: would the detail survive **distance/lens, movement and available light**? If any answer is no, omit it. Distant figures need silhouette/posture/color rather than pores or jewelry. (S:99–107)
- Prompt order is five paragraphs: **opening composition → overlay prohibition → world → focal anchor/light → capture finish**. People-in-scene adds a people paragraph before the world. (S:111–124, 238–250)
- **“Light is direction, quality, and temperature. Never a fixture.”** Also state what the source catches and where it stops. Every accent color needs a physical source or surface. In-world practical objects may be named. (S:148–158)
- Depth comes from named planes and progressive contrast/color softening, including the foreground. **“Low macro, high micro”** means lifted broad shadows with detailed nearby textures, grain and bloom at point sources. Avoid fog banks, shafts, god rays and free-floating particulate as generic mood dressing. (S:162–170)
- Camera package is described by appearance: vintage anamorphic by default; clean spherical for editorial. Use field of view, compression, bokeh and edge behaviour, rather than equipment model names. (S:200–218)
- People need reference-bound identity/wardrobe, observable pose, hands, gaze and expression, plus **scale, grounded contact and the correct side of facial illumination**. Every person has an action. (S:238–254)
- Coverage: approve the widest master; attach it to every additional angle; describe each vantage relative to it; preserve geometry/time/weather/dressing; recalculate camera-relative lighting. A source on camera-right may move to camera-left in the reverse. (S:274–283)
- Edits use **target → change → protected**. Protect composition, camera, lens, lighting, other objects/people and existing grain/grade. (S:287–301)
- Bans: overlays, numerical ratios, character names, separate negative blocks, invisible micro-detail, meta-description and unexplained mood. Physical signage is described separately, with exact wording/material/placement. (S:126–143)

**Mapping to Drama Box**
- **Step 2** establishes location/aesthetic intent; **4** produces and picks plate sets; **5–6** consume them; **7** benefits from matching coverage.
- System prompt: plan composition/depth, apply the resolution filter, motivate every light/color, preserve location geometry across coverage.
- Records: `location_id`, `master_plate_id`, `coverage_plates[]`, `vantage_relative_to_master`, `geometry_landmarks`, `time_of_day`, `weather`, `set_dressing`, `depth_planes[]`, `light_sources[]`, `palette`, `lens_family`, `edit_protected_fields`.
- H3: select the relevant approved angle within the nine-image budget. Make scene lighting authoritative while character plates remain flat. Compose for **480×832** and protect speaking-face visibility.
- Use exact Thai physical signage only when required; keep generated frames free of subtitle overlays, adding editorial text in step 7.

**Drop/adapt and gaps**
- Drop claims that Nano Banana rewards a particular prose length or Seedream uniquely benefits from HEX values/text. Preserve reference scoping and protected edits as model-independent methods to test.
- Resolve Scenecraft’s **anamorphic default** against Shotcaller’s **spherical default** through one season/scene camera package.
- Your workflow leaves **master/reverse/tighter plate sets, scene geometry and light-source continuity** unspecified. Scenecraft provides a concrete approach; a single attractive location image does not provide coverage.

**3. Shotcaller v2**

**Purpose and modes**
- Turns a scene into a detailed production prompt covering staging, camera, timing, performance, sound and continuity.
- Uses one shared spine for action, dialogue, performance, product shots, silent scenes and strobe; extension and attached-track lipsync have special protocols.
- Separates fixed identity/voice from scene-specific emotion and line delivery. (D:22–26, 186–213, 369–465)

**Concrete method**
- Core rule: **“If a word doesn’t produce a visible pixel or an audible sound, cut it.”** Replace “stressed” with jaw/shoulder/breath/gaze behaviour; label screen-relative versus character-relative directions. (D:24, 92–104)
- Sixteen-slot order: **header → style → no overlays → critical constraints → assets → geometry → first frame → optics → camera → light/color → atmosphere → action timing → physics → acting → audio → locks**. Limit critical blocks to four; script first for speech. (D:108–129, 167–184)
- Assets bind reference, permanent identity, voice, current-scene role and fidelity. Voice identity specifies register, texture, habitual pace and accent; delivery belongs to the individual line. Props get material, size against a body part and handling. (D:186–215)
- Video character sheets combine an outfit montage and speaking close-up with a pangram/emotional range. They govern **look, voice and how the character expresses emotion**; their panel layout, gray background, framing and spoken test words must not transfer. (D:204–213)
- Geometry fixes lateral position, depth, focus, vertical relationships and off-frame positions. Dialogue also fixes camera-facing angles so mouths remain readable. First frame begins with action already underway. (D:217–233)
- Optics: one lens/FOV lock per shot; spherical large-format default; anamorphic opt-in. Describe the visual consequences of unusual lenses to resist averaging toward a normal view. (D:235–257)
- Camera registers range from locked to violent handheld. **Important dialogue defaults to locked or gentle movement**. Light uses direction/quality/temperature; a roughly 70/20/10 palette gives each band a physical source. (D:259–286)
- Atmosphere names actual depth planes. Visible vapor needs a source; clean-air scenes can explicitly require full clarity. Every body acts in every beat, with character, micro, environment and camera motion accounted for. (D:288–307)
- Physics chain: **mass → contact → deformation → rebound → secondary lag → contact shadow**. Acting uses brows, blinking, explicit eyeline targets and emotional transitions rather than fixed emotion labels. (D:309–327)
- Pacing guide: 1.5–2.5 s high-energy shots; 2.5–4 s narrative/dialogue; 4–7 s held lines; longer continuous takes when warranted. Timings sum exactly; dialogue cuts fall between lines, never within words. (D:133–141)
- Script intake separates spoken words, speaker cues, parentheticals, pauses, actions, off-frame speech, overlaps and nonspoken screenplay markup. Preserve punctuation, repetitions and stutters; flag runtime/pronunciation/speaker problems before rendering. (D:375–397)
- **“Verbatim means verbatim.”** Words appear identically in Script, Action Timing and Audio. Number and assign lines; delivery notes stay outside spoken text; every listener gets a silent reaction; every gap gets duration and ambience. (D:391–444)
- **“No mouth mechanics for generated speech.”** Native dialogue gets words and delivery; detailed lip/phoneme instructions belong only to attached-track matching. Diegetic audio names physical sources and suppresses unwanted music/voices. (D:329–349, 446–475)
- Extensions name the previous final state and continue energy/light/motion across the join. Attached-track lipsync instead makes the track authoritative, requires section-specific transcript/lyrics, visible mouths and cuts on breaths. (D:555–646)

**Mapping to Drama Box**
- Primarily **5–6**, with dialogue preparation in **3**, voice/performance casting in **4**, cut decisions in **7**, checks in **8**, and selected dramatic beats in **10**.
- System prompt: direct observable action; preserve locked Thai text and speaker ownership; stage silent listeners; maintain eyelines/geometry; motivate camera and physical contact.
- Shot fields: `shot_id`, `scene_id`, `story_beat`, `coverage_role`, `duration`, `first_frame_state`, `end_state`, `camera`, `lens`, `blocking`, `eyelines`, `focus_target`, `lighting`, `palette`, `atmosphere`, `physics`, `continuity_locks`.
- Dialogue fields: `line_id`, `speaker_id`, `text_th`, `start/end`, `delivery`, `stress_target`, `listener_actions`, `silence_beats`, `offscreen`, `voice_reference_id`; derive repeated prompt appearances from the **same stored text**.
- H3 adaptation: render roughly **one continuous five-second coverage shot per clip**, then cut in step 7. Longer exchanges become linked shots; do not import 15/30-second multishot templates.
- Keep Thai dialogue verbatim in Thai script, with production direction separately expressed. Replace the English 2.5–3 words/s heuristic with Thai utterance-duration estimates and native review; split lines instead of rushing them.
- A voice reference conditions speaker identity; it is **not automatically the finished soundtrack**. Preserve native generated Thai speech. Bind up to three audio references explicitly to speakers/roles.
- Adapt the video casting sheet into an approved **image-view set + Thai voice sample + expression/performance profile**. Image/audio references do not establish that H3 can inherit the video sheet’s full emotional performance.

**Drop/adapt and gaps**
- Drop Seedance version selection, 50-reference/30-second assumptions, Higgsfield Elements and invented `@handles`.
- Do not copy `@imageN`, `@videoN` or video-only audio packaging into H3. The reviewed skills establish no H3 tagging syntax; the pinned ComfyUI adapter must bind structured references using its actual workflow contract.
- Drop “8K” as an output claim; use **480×832, 24 fps** as settings. Treat shutter, grain and lens language as visual direction, not guaranteed capture parameters.
- Seedance extension and exact attached-track lipsync require separately verified H3 support.
- Your labels leave **speaker-specific performance references, timed silent reactions, mouth visibility, cut-safe speech and continuity at clip boundaries** unspecified.

**New versus installed Cinema Director v3**
- **New:** Element-handle-first reference collection and exact handle preservation; video sheets that jointly anchor look/voice/performance; a complete extension protocol. (D:47–56, 204–213, 555–596)
- **Expanded:** screenplay intake parsing, runtime/pronunciation flags, words-versus-delivery separation, detailed per-line delivery vocabulary and voice-reference-specific instructions. (D:375–475)
- **Changed:** attached-track lipsync now requires whole-second **video** references, including black-frame wrapping of audio, plus exact section lyrics/transcript. Mouth-shape instructions themselves already existed. (D:598–646; CD:632–666)
- **Changed:** separate negative prompt blocks are now prohibited; the predecessor allowed them. A references-first pre-prompt check is explicit. (D:60–88; CD:76–90)
- The sixteen-slot spine, FOV ladder, physics chain, three dialogue appearances, listener silence, eyelines, camera registers and music suppression are **inherited**. Voice descriptions were already present; combined audiovisual performance authority is the new part. (CD:96–115, 214–251, 584–628)

**4. Story Bible Builder — all four files**

**Purpose and modes**
- Builds one dense canon reference containing premise, world, characters, relationships and production rules.
- Two uses: standalone story context, or a canon source feeding a separate cinematography director.
- Its interactive interview and installable Claude skill packaging become automated canon preparation and records in Drama Box. (B:8–47)

Supporting files: [character interview](/tmp/claude-0/-root-AIVORA/413d5d13-a4ab-4480-be0b-31a0f3fd90a8/scratchpad/keep/joey-skills/story-bible-builder/character-interview.md), [character format](/tmp/claude-0/-root-AIVORA/413d5d13-a4ab-4480-be0b-31a0f3fd90a8/scratchpad/keep/joey-skills/story-bible-builder/character-section-format.md), [example excerpts](/tmp/claude-0/-root-AIVORA/413d5d13-a4ab-4480-be0b-31a0f3fd90a8/scratchpad/keep/joey-skills/story-bible-builder/example-bible-excerpts.md).

**Concrete method**
- Ordered canon: **premise → thesis → timeline → era aesthetics → factions → locations → world rules → characters → relationships → structural engines → production rules → downstream usage**. Aesthetic locks specify palette/light/texture rather than “dark and moody.” (B:51–103)
- **“Never invent.”** Unknown information becomes `[TBD]`; vague qualities are sharpened into actionable descriptors. **“Locks exclude as much as they include”**: record likely wrong-answer drift alongside the positive trait. (B:172–184)
- Character inquiry starts with **narrative function**, then visual lock, backstory, current psychology, speech, movement, stillness, optional singing voice and locked subplots. A specific formative detail and an internal contradiction make behaviour less generic. (character-interview.md:9–54)
- Character format stores visual identity, function, backstory and present psychology, followed by quoted prompt-ready **Speech / Movement / Stillness / optional singing** descriptors. Function precedes biography; current psychology anchors the present story moment. (character-section-format.md:9–47)
- Speech captures register, texture, cadence, volume, vocabulary and habitual pauses/fillers/code-switching. Movement captures gesture, carriage, tics and gait. Stillness captures hands, weight, face and breathing while listening or waiting. (character-interview.md:58–99)
- Ensemble dynamics describe who leads, fills silence, watches or destabilizes particular pairings. Structural engines are reusable shapes—confrontation, rescue, confession—not prewritten episodes. (B:122–134)
- **“Density over prose.”** Descriptors must be directly usable by downstream roles; narrative lore becomes visible behaviour only when directing. Examples test whether a stranger could write a correct scene using the bible alone. (B:34–47, 174; example-bible-excerpts.md:111–115)

**Mapping to Drama Box**
- **1–2:** premise, thesis, season engine, world and aesthetic rules. **3:** episode-specific psychology/relationships. **4:** finalized casting identity/voice/movement. **5:** relevant canon projected into shot direction.
- System prompt: distinguish proposed from locked canon; preserve established facts; expose unresolved fields; make character behaviour specific; retrieve only context relevant to the current episode/shot.
- Season fields: `premise`, `thesis_question`, `timeline`, `era_looks`, `world_rules`, `factions`, `locations`, `relationship_dynamics`, `story_engines`, `production_rules`.
- Character fields: `narrative_function`, `visual_lock`, `backstory`, `psychology_by_story_state`, `speech_profile`, `movement_profile`, `stillness_profile`, `drift_exclusions`, `locked_threads`.
- Thai additions: language/dialect, habitual pronouns and address forms, politeness/register, pronunciation notes, code-switching policy and approved voice sample IDs.
- H3 reference counts remain a **shot-level selection problem**, not a reason to compress the entire bible into every render prompt.

**Drop/adapt and gaps**
- Drop Claude memory-slot/installable-skill packaging, the under-500-line constraint, Suno/ElevenLabs routing and Seedance-specific destination blocks.
- Allow upstream LLM roles to **propose** creative canon before LOCK; “never invent” should prevent silent downstream canon changes, not prevent story creation.
- Your sequence needs an explicit handoff between season-level character intent and step 4’s finalized casting, plus episode-specific emotional state. Otherwise a static bible can reset a character’s psychology every episode.
- The supplied supporting files are beside `SKILL.md`, although its links say `references/...`; resolve that packaging mismatch if importing the material.

**5. Motiondojo v1**

**Purpose and forms**
- Transfers selected movement information from a performance video into new characters and surroundings.
- Three forms: **body + original camera; camera only; body + newly directed camera**.
- Separates motion authority from identity, wardrobe, environment and lighting authority. (M:8–24)

**Concrete method**
- Analyze performer count, starting screen positions, depth, duration, speech/mouth activity, camera path and ground. Bind each character to a performer; preserve that assignment through crossings. (M:40–57, 142–159)
- Decide mouth behaviour first: **closed/breathing; exact spoken words; match reference mouth movement**. The opening paragraph and a critical block enforce it. Never guess the transcript. (M:28–36, 111–114)
- Ordered prompt: scope/mouth lock → style → no overlays → critical constraints → reference lines → geometry → first frame → lens/camera → light/air → action → physics → acting/audio → locks. (M:67–86)
- Multi-performer realism requires distinct weight, follow-through, head carriage, breathing and micro-timing. **“Never cloned, never mirrored.”** Preserve genuine unison without making identical mannequins. (M:161–166)
- Lock exact population and exclude plausible intruders. Keep reference staging and flag spaces too small for the movement. (M:168–170, 208–214)
- Camera movement must respond to bodies and operator footing, rather than orbit perfectly. Rebuild physics for **the new ground and clothes**: surface displacement, sole slip/grip, knee absorption, hair/fabric lag and traveling contact shadows. (M:245–289)
- Four motion layers stay live; faces blink/react/breathe. Diegetic sound names the new surface/materials. Bans include invented speech/music, lyrics, overlays and separate negative blocks. (M:274–309, 377–385)

**Mapping to Drama Box**
- Optional material for **5–6**, especially physical action; also useful for teaser performance in **10**.
- System prompt: separate body and camera direction; preserve role assignments; give performers individual movement signatures; ground every move in the current surface and wardrobe.
- Records: `motion_mode`, `source_segment`, `performer_role_map`, `body_beats`, `camera_path`, `individuality`, `population_count`, `mouth_mode`, `surface_response`, `wardrobe_secondary_motion`.
- H3: use analyzed movement as textual directing material unless motion/video conditioning is separately supported. **Ref2VA image/audio capacity does not establish Genjutsu-style motion transfer.**
- Plan roughly five-second action segments with start/end states. Native Thai dialogue comes from the locked episode script and voice references; do not inherit another video’s words accidentally.

**Drop/adapt and gaps**
- Drop Genjutsu’s separately attached, untagged video convention and `<<<image_N>>>` syntax.
- Drop mandatory runtime equality with a source video when using it only as directing analysis, and the 30-second/8K examples.
- Your step 5 leaves **body-versus-camera authority, performer assignment, individuality and surface-aware movement** unspecified. These methods help, but exact choreography transfer remains an additional capability.

**How this fits the ten steps**

| Step | Material to adopt |
|---|---|
| 1. Script Maker → LOCK | Premise, thesis, dramatic engine, explicit unresolved decisions. |
| 2. Season bible | Canon, era aesthetics, world rules, relationship dynamics and character intent. |
| 3. Episode → STORY LOCK | Exact Thai lines, speaker IDs, scene beats, emotional state, duration feasibility. |
| 4. Character bible → CAST LOCK | Flat identity locks, outfits, expression sets, voice samples, props and location coverage picks. |
| 5. Shot directing | Shotcaller spine, Scenecraft composition, Motiondojo physical staging, continuity and coverage. |
| 6. H3 Ref2VA | Compile selected references and direction into the verified workflow; enforce 9 images/3 audio, 480×832, 24 fps, approximately 5 s. |
| 7. Edit | Trim coverage for pacing; cut at speech-safe points; match eyelines/action/light; add subtitles, score and overlays deliberately. |
| 8. Gate 2 | Assess actual output for Thai delivery, voice/identity, lipsync, continuity, physical plausibility and pacing. |
| 9. Metadata | These skills provide little publishing guidance; derive claims from the accepted episode and canon. |
| 10. Teaser | Reuse accepted dramatic beats and matching coverage; these skills do not supply a complete teaser strategy. |

**Rules for adapting the material into automation**

- Replace “ask/check/approve in chat” with structured validation, unresolved-field reporting and the workflow’s designated LOCK/pick points. Preserve the operator’s actual approvals.
- Store reference authority explicitly: `asset_id`, `revision`, `role`, `subject_id`, `view`, `governs`, `must_not_transfer`, `binding_index`. Generate platform syntax in the adapter.
- Keep **voice identity**, **line delivery** and **finished soundtrack** distinct. A voice sample must not accidentally trigger Shotcaller’s sole-source soundtrack lock.
- Maintain one shared camera package across scene plates and shots. Store FOV axis/sensor assumptions if numerical FOV and focal length are used; Joey’s lookup ladder is not a universal conversion.
- Treat grain strength, lifted blacks, matte skin, anamorphic optics and aggressive handheld as selectable aesthetics. At 480×832, excessive grain, haze or movement can sacrifice face and mouth readability.
- Turn checklists into input validation **and output inspection**. Prompt assertions such as “100% match,” exact voice or perfect physics are desired outcomes, not evidence that the generated clip achieved them.

**Licence and usage terms**

No explicit licence, copyright notice, commercial-use grant or redistribution terms appear in the eight supplied files or either installed predecessor. “Made by Joey” is attribution, not a licence.

Shotcaller does state a usage constraint for lyrics: use the user’s own or rights-held lyrics, and avoid reproducing another commercially released song’s lyrics. (D:612) That instruction does not establish permission to redistribute the skills themselves.

