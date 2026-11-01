# Appendices

# Appendix C. Asset and Continuity Schema Dictionary

This appendix rewrites "keep the character consistent," "don't let the space jump" and "get the prop position right" as
data contracts that machines can read, teams can review and tools can pass along. Schemas do not turn creative work into
form-filling. They keep creative decisions from being lost across generation, selection, pickups and editing.

## C.1 Six base rules

1. **Stable IDs outrank names.** `char_lin_xia` does not change because a character is renamed.
2. **Separate fact, intent and observation.** "Angry" is intent, "right hand clenched" is observation, "just removed from
   the board" is fact.
3. **Unknown is not the same as false.** `unknown`, `not_visible` and `not_applicable` stay distinct from `false`.
4. **State has time boundaries.** Say which event makes it effective and when it expires.
5. **History is never overwritten.** A change produces a new version, preserving `supersedes`, the author and the reason.
6. **A shot consumes the minimum state.** Do not push the whole season at a model; compile only the identity, action,
   spatial and style constraints this shot needs.

Common metadata:

```yaml
schema_meta:
  schema: continuity.character_state
  schema_version: 1.2.0
  record_id: state_char_lin_xia_e001_s014_pre_v3
  entity_id: char_lin_xia
  project_id: prj_backlight_acquisition
  valid_from: evt_e001_s013_exit
  valid_until: evt_e001_s015_costume_change
  status: approved
  supersedes: state_char_lin_xia_e001_s014_pre_v2
  created_by: continuity_agent
  approved_by: human_continuity_lead
  source_refs: [script://ep_001/scene_014, frame://ep_001/shot_013c/last]
```

## C.2 Base entities and the identity contract

Characters, locations, props, wardrobe, voices and graphic assets all inherit one base entity:

```yaml
entity:
  id: char_lin_xia
  type: character
  canonical_name: Lin Xia
  aliases: [Director Lin, Xia Xia]
  lifecycle: active
  canonical_version: 7
  owner_role: character_supervisor
  rights_profile_id: rights_cast_synthetic_001
  provenance_ids: [prov_char_design_004, prov_voice_011]
```

An identity contract records only the recognition anchors that stay stable across episodes — not this scene's temporary
stain or emotion:

```yaml
identity_contract:
  character_id: char_lin_xia
  identity_version: 3
  narrative_age: 29
  silhouette: {height_band: 168_172cm, build: slender_athletic}
  face_anchors:
    face_shape: narrow_oval
    brow: straight_soft_arch
    eyes: almond_dark_brown
    nose: straight_narrow_bridge
    distinctive_marks: [tiny_mole_below_left_eye]
  hair_default: {color: natural_black, length: below_shoulder, parting: left_30_percent}
  immutable_features: [eye_color, mole_position, face_proportion]
  controlled_variants:
    hair: [down_straight, low_ponytail]
    eyewear: [none, thin_black_frame]
  forbidden_drift: [mole_switches_side, age_shift_over_3_years]
  reference_assets:
    hero_front: asset_char_lin_front_v03
    three_quarter: asset_char_lin_3q_v03
    profile: asset_char_lin_profile_v02
    expression_sheet: asset_char_lin_expr_v04
```

Five to nine anchors is about right. Each has to be checkable in the picture; "commanding presence" is not an anchor. The
counterexample is using `beautiful_ceo_final2.png` as a character's identity. Files belong to asset versions; the
character ID stays stable forever.

## C.3 Per-shot character state

```yaml
character_state:
  character_id: char_lin_xia
  at: ep_001/sc_014/shot_014a/in
  wardrobe_state_id: wr_lin_boardroom_v2_state_06
  hair_state: low_ponytail_intact
  makeup_state: office_clean_cool
  body_state:
    posture: upright_guarded
    left_hand: holding_contract_folder
    right_hand: free
    injury_ids: []
  emotional_intent: {dominant: controlled_anger, intensity_0_5: 3, concealment: high}
  knowledge_state:
    knows: [fact_bid_price_leaked]
    does_not_know: [fact_chairman_is_source]
  relationship_state: {toward_char_gu_zhou: distrust_rising}
```

`knowledge_state` matters. A character cannot react to a fact they have not learned. Continuity checks the cognitive
timeline, not only the clothes.

## C.4 Wardrobe, hair and makeup, and injuries

Wardrobe is written as a base layer plus overlays, so you do not duplicate a whole look for every combination of stains:

```yaml
wardrobe_state:
  base_look_id: look_lin_boardroom_charcoal_v2
  layers:
    inner: ivory_silk_shirt
    outer: charcoal_single_breasted_suit
    lower: charcoal_straight_trousers
  accessories: {left_wrist: silver_watch, ears: small_pearl_studs}
  overlays:
    - {id: overlay_rain_damp_01, region: shoulders_and_hair_ends, intensity: light}
    - {id: overlay_coffee_stain_02, region: right_cuff_outer, mask: asset_stain_mask_02}
  continuity_locks: [watch_on_left_wrist, stain_never_mirrored]

physical_condition:
  injuries:
    - injury_id: inj_lin_palm_cut_01
      body_side: right
      region: palm
      visual_state: fresh_bandage_clean
      pain_behavior: avoids_forceful_grip
      introduced_by: evt_e002_glass_cut
      healed_after: ep_004/sc_006
  fatigue: {level_0_5: 4, visible_signs: [slower_blink, slight_under_eye_shadow]}
```

A prompt should not just say "injured hand." It compiles to: a clean fresh bandage on the right palm; avoids gripping
firmly when picking things up; the bandage must never appear on the left hand. That supplies the visual anchor, the
behavioral consequence and the negative constraint at once.

## C.5 Location, camera zones and the axis

```yaml
location_contract:
  location_id: loc_yuancheng_boardroom
  canonical_layout_asset: asset_boardroom_plan_v05
  fixed_landmarks:
    north: floor_to_ceiling_windows
    east: double_door
    west: display_wall
    center: twelve_seat_table
  material_palette: [dark_walnut, brushed_steel, clear_glass]
  camera_zones:
    zone_a_window_side: {allowed: true}
    zone_b_door_side: {allowed: true}
    zone_c_screen_side: {allowed: conditional, reason: reflection_risk}
  screen_direction:
    axis_id: axis_lin_gu_table
    char_lin_xia_screen_side: left
    char_gu_zhou_screen_side: right
    crossing_allowed_only_with: [visible_reaxis_move, neutral_insert]
```

Location consistency also covers the orientation of doors and windows, the direction characters enter and leave, screen
direction, usable camera positions and reflection risk. Produce a simplified floor plan first, and have shot packs
reference only the current camera zone.

## C.6 Props and ownership events

```yaml
prop_state:
  prop_id: prop_red_contract_folder_01
  canonical_asset_id: asset_contract_folder_red_v03
  owner: company_yuancheng
  holder: char_lin_xia
  location: loc_yuancheng_boardroom/table_south_edge
  orientation: spine_toward_char_lin_xia
  open_state: closed
  contents: {document_id: doc_acquisition_offer_v08, page_visible: null}
  last_event: evt_e001_s013_lin_places_folder
```

Ownership, holder and spatial position are three different things. The company owns the folder, Lin Xia is holding it,
and it may also be resting on the edge of the table. Transfers are written as events:

```yaml
continuity_event:
  id: evt_e001_s014_gu_takes_folder
  type: prop.transfer
  subject_id: prop_red_contract_folder_01
  from: {holder: char_lin_xia, location: lin_left_hand}
  to: {holder: char_gu_zhou, location: gu_right_hand}
  caused_by_shot: sh_e001_s014c
  effective_at: shot_end
```

## C.7 Time, weather and light

```yaml
environment_state:
  story_time: 2026-10-18T18:12:00+08:00
  time_band: blue_hour
  elapsed_since_previous_scene_minutes: 7
  weather: heavy_rain
  exterior_wetness_0_100: 92
  key_light_motivation: window_cool_sky
  fill_motivation: ceiling_practical
  color_temperature: {exterior_k: 7200, interior_k: 4100}
  continuity_locks: [rain_visible_on_north_windows, no_direct_sunlight]
```

## C.8 Action contracts and handing off across shots

An action splits into a start, a peak and an end:

```yaml
action_contract:
  id: act_e001_s014_folder_handoff
  actor: char_lin_xia
  receiver: char_gu_zhou
  object: prop_red_contract_folder_01
  start_state:
    lin_left_hand: holds_folder_lower_edge
    gu_right_hand: resting_on_table
  peak_state:
    folder_center: crosses_axis_midpoint
    eye_contact: maintained
  end_state:
    lin_left_hand: released
    gu_right_hand: holds_folder_spine
  screen_direction: left_to_right
  cut_points:
    safe: [before_extension, at_dual_grip, after_receiver_secures]
    unsafe: [during_single_frame_release]
```

Shot A's `end_state` must equal shot B's `start_state`. When they differ, block high-quality generation rather than
hoping an editor can cover it afterwards.

## C.9 Cast layout and feature ownership

```yaml
cast_layout:
  shot_id: sh_e001_s014_wide
  slots:
    - {slot: foreground_left, character_id: char_lin_xia, identity_ref: identity_lin_v3}
    - {slot: midground_right, character_id: char_gu_zhou, identity_ref: identity_gu_v4}
  feature_ownership:
    mole_below_left_eye: char_lin_xia
    silver_collar_pin: char_gu_zhou
  forbidden_swaps: [face_identity, wardrobe_color, signature_accessory]
```

The commonest error in a multi-person shot is features migrating between people. Declaring feature ownership explicitly
and fixing each person's slot in the frame reduces swapped faces, swapped wardrobe and drifting height.

## C.10 Voice and music state

```yaml
voice_contract:
  character_id: char_lin_xia
  voice_asset_id: voice_lin_mandarin_v05
  register: mid_low
  pace_syllables_per_second: 4.2
  texture: clean_firm_slight_breath
  emotional_limits: {no_shouting_until: ep_006, crying_voice_allowed: false}
  pronunciation_lexicon_id: lexicon_project_v08
  loudness_target_lufs: -18

music_state:
  cue_id: cue_e001_pressure_bed
  composition_id: music_pressure_theme_v03
  stem_state: {pulse: -8db, low_strings: -12db, percussion: muted, melody: absent}
  key: D_minor
  tempo_bpm: 92
  bar_position_at_shot_in: 17.1
  transition_out: hold_tension_no_cadence
```

Musical continuity preserves more than a cue name: version, stems, key, tempo and bar position. When a shot is extended,
continue from the same music state rather than regenerating something that is "about as tense."

## C.11 On-screen text bound to facts

```yaml
graphic_asset:
  id: gfx_offer_price_mobile_01
  type: diegetic_phone_screen
  text_source: fact_offer_price_v3
  rendered_text: "Acquisition offer: 480,000,000 CNY"
  locale: zh-CN
  verification:
    exact_match_required: true
    ocr_threshold: 0.98
    compare_against: fact_registry://offer_price/current
```

Contract amounts, dates and chat logs bind to the fact registry. A generator may decide the typographic texture; it may
not rewrite the numbers.

## C.12 Asset registry and rights

```yaml
asset_record:
  asset_id: asset_char_lin_front_v03
  entity_id: char_lin_xia
  asset_type: identity_reference
  version: 3
  uri: asset://characters/lin_xia/front/v03.png
  checksum_sha256: "..."
  generator: {provider: openai, model: gpt-image, run_id: run_img_0192}
  input_provenance: [prov_prompt_102, prov_sketch_owned_07]
  rights_status: cleared_commercial
  review_status: approved
  supersedes: asset_char_lin_front_v02
```

A recommended lifecycle: `draft → candidate → approved → locked → retired`. Assets missing provenance, likeness rights or
parameters go to `quarantined` and cannot be selected by the episode pack compiler.

## C.13 State events and the dependency graph

```yaml
event:
  event_id: evt_01JCONT7YQ9
  event_type: continuity.state_changed
  event_version: 1
  aggregate_id: prop_red_contract_folder_01
  aggregate_version_before: 11
  aggregate_version_after: 12
  idempotency_key: sh_e001_s014c:folder_transfer:v1
  causation_id: task_render_sh_e001_s014c_v4
  correlation_id: trace_ep001_build_008
  payload: {holder: {from: char_lin_xia, to: char_gu_zhou}}
```

The dependency graph supports at minimum `depends_on`, `derived_from`, `constrains`, `appears_in`, `supersedes` and
`approved_by`. When a character's primary reference is upgraded, it should answer which unreleased shots must be redone
and which locked shots need only an exception recorded.

## C.14 Continuity lint rules

| Rule ID | Check | Severity | Automatic action |
| --- | --- | ---: | --- |
| `CONT-001` | Previous shot's end state differs from the next shot's start state | blocker | Block high-quality generation |
| `CONT-002` | An injury is mirrored left to right | blocker | Quarantine the candidate |
| `CONT-003` | A character uses a fact they do not yet know | blocker | Return to script revision |
| `CONT-004` | A prop is held by two people at once | blocker | State conflict |
| `CONT-005` | The axis is crossed with no explanation | major | Insert a neutral shot or redo |
| `CONT-006` | Hair and makeup improve with no cause | major | Check for a time jump |
| `CONT-007` | Environment time conflicts with the light outside | major | Rebuild the lighting condition |
| `CONT-008` | On-screen text disagrees with the fact table | blocker | Prohibit release |
| `CONT-009` | A musical bar entry is broken | minor | Recompute the edit point |
| `CONT-010` | A quarantined asset is referenced | blocker | Replace the dependency |

Lint finds deterministic conflicts; it does not judge whether a performance is moving. Computable rules and aesthetic
review stay separate.

## C.15 The complete shot state packet

```yaml
shot_state_packet:
  shot_id: sh_e001_s014c
  duration_target_s: 2.8
  frame: {aspect_ratio: "9:16", size: medium_two_shot}
  camera: {location_zone: zone_a_window_side, lens_equivalent_mm: 50, movement: slow_push_5_percent}
  cast_layout_ref: layout_e001_s014c_v2
  character_states: [state_char_lin_xia_e001_s014_pre_v3, state_char_gu_zhou_e001_s014_pre_v2]
  location_state: loc_yuancheng_boardroom_bluehour_v4
  prop_states: [prop_folder_state_11]
  action_contract: act_e001_s014_folder_handoff
  dialogue_line_ids: [line_e001_014_07]
  voice_contracts: [voice_lin_v05, voice_gu_v03]
  music_state_in: cue_pressure_v03_bar17_beat1
  music_state_out: cue_pressure_v03_bar18_beat2
  required_visible: [lin_left_eye_mole, red_folder_dual_grip_at_peak, rain_on_north_window]
  forbidden: [mirrored_composition, smiling, readable_random_documents]
  acceptance:
    identity_score_min: 0.91
    action_state_match: exact
    dialogue_sync_max_offset_ms: 80
    continuity_lint: pass
```

The compiler translates the state packet into each vendor's prompts and control parameters. Vendor formats may change;
the semantic source may not.

## C.16 Failure modes, version migration and rollout

Common failures: putting everything into `notes`; overwriting state with no event; writing "tense" with no observable
behavior; treating one prompt as the sole source of truth; making every field mandatory so the team invents information
it does not have.

Schema versions follow the rule that a patch only changes documentation, a minor adds compatible fields, and a major
changes semantics and ships a migrator. A migration is tested for at least three things: old packs still read, old events
still replay, and released shots stay traceable. Production switches in three steps: dual write, read new, stop old.

Rollout order: establish stable IDs; produce identity contracts and baseline plates for the leads; take one high-risk
scene and write start and end states shot by shot; convert injuries and stains into overlays; establish action contracts;
turn on the event log; implement ten lint rules first; and finally validate the lineage chain with a pickup shot and a
rollback.

## C.17 Delivery checklist and exercise

- [ ] Core entities have stable IDs, and names are only display fields.
- [ ] Identity contracts distinguish stable anchors from temporary state.
- [ ] Injuries, stains and prop transfers all have effective events.
- [ ] An action's end state across shots equals the next shot's start state.
- [ ] Character knowledge state agrees with the story's fact timeline.
- [ ] Music preserves version, stems, tempo and bar position.
- [ ] On-screen text binds to the fact registry and is verified by OCR.
- [ ] Assets carry provenance, rights, checksums and approval state.
- [ ] Schema changes have a migration strategy, and release packages stay fully traceable.

Exercise: choose a 30-second scene with two characters, one key prop and one emotional reversal. Write the identity,
location, prop and five shot states. Deliberately introduce a mirrored injury, a crossed axis and a teleporting prop. Run
lint. Then change a middle shot and produce the impact analysis.

Deliverables: `entity_registry.yaml`, `identity_contracts.yaml`, `shot_states.yaml`, `continuity_events.jsonl`,
`lint_report.json` and a one-page human continuity report.
