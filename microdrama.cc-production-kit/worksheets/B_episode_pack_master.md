# Appendices

# Appendix B. The Complete Episode Pack Master

The episode pack is the single approved input from which an episode enters shot design, assets, voice, generation,
editing and QC. It does not replace the script with YAML, and it does not ask writers to give up natural language. It
puts literary expression and the production facts that must not be lost into one versioned package.

This master can be trimmed, but never at the cost of versions, fact locks, entry and exit state, asset dependencies,
risks, acceptance and the change record. A small project can keep it in one Markdown file; a large one can split it into
database entities. The field semantics stay the same.

## B.1 Package directory

```text
EP_E001_PACK_v12/
  manifest.yaml
  episode_contract.yaml
  facts.yaml
  states_in.yaml
  beats.yaml
  scenes.yaml
  lines.yaml
  narration.yaml
  shot_requirements.yaml
  sound_plan.yaml
  assets.yaml
  continuity.yaml
  risks.yaml
  acceptance.yaml
  decisions.yaml
  attachments/
```

## B.2 Manifest

```yaml
episode_pack:
  id: EP_E001_PACK
  version: 12
  status: approved
  project: PRJ_NIGUANG
  episode: E001
  schema: episode_pack@1.4
  created_at: 2026-07-05T10:00:00Z
  approved_at: 2026-07-05T18:30:00Z
  approved_by: [SHOWRUNNER, PRODUCER]
  sources:
    season_bible: SEASON_NGSG@v08
    character_bible: CHAR_BIBLE@v11
    continuity_snapshot: CONT_E001_IN@v06
    rights_snapshot: RIGHTS_PRJ_NGSG@v05
  content_hash: sha256:example
  supersedes: EP_E001_PACK@v11
  change_summary:
    - authorization readable duration raised from 18 to 24 frames
    - one duplicated humiliation reaction removed
```

The manifest describes the package; it does not carry the business content. Every downstream task records the actual pack
hash — "uses the latest version" is not acceptable.

## B.3 Episode contract

```yaml
episode_contract:
  episode: E001
  target_duration_sec: 75
  acceptable_range_sec: [68, 82]
  business_mode: paid_unlock
  episode_function:
    - establish that Lin Yun has been excluded
    - prove she holds procedural standing to enter
    - open the question of a dead man's account still paying
  opening_contract:
    first_visible_conflict_max_sec: 3
    promise_confirmation_max_sec: 8
  payoff:
    debt_paid: can Lin Yun get into the meeting
    debt_opened: who is using her father's account
  card:
    type: proof_leads_to_larger_mystery
    exact_question: why is her late father still a payee
  forbidden:
    - Lin Yun gets in through somebody's charity
    - the authorization appears with no provenance
    - the cut lands before the document is readable
```

## B.4 Fact locks

Fact locks hold the truths that downstream may not rewrite.

```yaml
fact_locks:
  - id: FACT_E001_001
    statement: Lin Yun holds an authorization personally signed by the chair
    source: SEASON_FACT_014
    visible_to: [LINYUN]
    revealed_to: [ZHOULAN, LINWEI, BOARD]
    reveal_beat: E001_B05
  - id: FACT_E001_002
    statement: the anomalous payment lists Lin Yun's father as the payee
    source: SEASON_FACT_021
    revealed_to: [LINYUN, AUDIENCE]
    reveal_beat: E001_B09
  - id: FACT_E001_003
    statement: at this point Lin Yun does not know whether her father is alive
    type: knowledge_constraint
```

Numbers, proper nouns, relationships, dates and negations must all be structured. If a line, a graphic or a narration
contradicts a fact lock, the pack cannot be approved.

## B.5 Entry state

```yaml
state_in:
  timeline: DAY_01_16_20
  location: LOC_MEETING_ENTRANCE@v05
  characters:
    CH_LINYUN:
      zone: door_outside
      wardrobe: WD_LINYUN_GREY_SUIT@v04
      props:
        authorization: concealed_inside_folder
        old_pen: left_inner_pocket
      emotion: controlled_anger_2
      knows: [FACT_FATHER_DECLARED_DEAD, FACT_MEETING_TODAY]
      does_not_know: [FACT_FATHER_POSSIBLY_ALIVE]
    CH_LINWEI:
      zone: door_inside
      wardrobe: WD_LINWEI_IVORY@v03
      emotion: public_confidence_3
      tactic: define_linyun_as_intruder
  location_state:
    passage: blocked_by_guard
    screen: agenda_idle
    lighting: MEETING_DUSK@v02
```

## B.6 The beat sheet master

| Beat | Target sec | Function | Trigger | Visible action | Audience gains | State out | Debt |
| --- | ---: | --- | --- | --- | --- | --- | --- |
| B01 | 0–6 | Pressure | Lin Yun reaches the door | The guard's arm blocks her | She is publicly excluded | `passage=blocked` | Can she get in |
| B02 | 6–15 | Framing | Lin Wei speaks | Calls her an intruder | The exclusion rests on an identity story | `board_belief=outsider` | Who is entitled |
| B03 | 15–25 | Strategy | Lin Yun does not argue | Records, observes | She is preparing evidence | `evidence=concealed` | What does she have |
| B04 | 25–39 | Proof begins | The order to remove her | The document slides onto the table | A formal document exists | `evidence=visible` | Is it genuine |
| B05 | 39–50 | Reversal | Zhou Lan verifies it | A nod, the guard stands aside | The authorization is valid | `access=granted` | Who signed it |
| B06 | 50–61 | Consequence | Lin Yun crosses the threshold | Takes the empty seat | Power is redistributed | `power=contested` | How does Lin Wei fight back |
| B07 | 61–75 | New debt | The system opens the accounts | A payee name appears | A dead man's account is still paying | `mystery=open` | Is her father alive |

Each row also carries a stable beat ID. Times are targets, not locks; state outputs and debts cannot change without a new
version.

## B.7 The beat contract card

```yaml
beat:
  id: E001_B04
  scene: E001_SC01
  state_in:
    authorization: concealed
    passage: blocked
  objective:
    CH_LINYUN: turn a dispute over identity into a procedural verification
    CH_LINWEI: end her eligibility before the document is seen
  trigger: CH_LINWEI_orders_removal
  tactic: proof_without_argument
  visible_action:
    subject: CH_LINYUN
    action: takes the authorization from the folder and slides it into the shared area of the table
    world_direction: east_door_to_table_head
  audience_gain: she holds formal proof
  state_out:
    authorization: visible_unverified
    board_attention: on_document
  min_duration_sec: 8
  max_duration_sec: 14
  assets: [PROP_AUTHORIZATION@v07, LOC_MEETING@v05]
  risk: hand_document_interaction_high
  fallback: approach_occlusion_result
```

## B.8 Scene card

```yaml
scene:
  id: E001_SC01
  slugline: DAY_01 / Shenghua boardroom door area / dusk / continuous
  dramatic_question: can Lin Yun force the board to acknowledge her right to enter
  power_in: LINWEI_controls_access
  power_out: PROCEDURE_FORCES_ACCESS
  location_version: LOC_MEETING@v05
  primary_axis: door_to_table_head
  camera_side: south
  scene_delta:
    before: {access: denied, evidence: hidden, belief: outsider}
    after: {access: granted, evidence: public, belief: authorized}
  enters:
    CH_LINYUN: door_outside
  exits: []
  sound_space: ROOM_MEETING_DUSK@v03
  transition_in: hard_cut_from_elevator_ding
  transition_out: screen_hum_J_cut
```

## B.9 Line registry

```yaml
lines:
  - id: LINE_E001_014
    beat: E001_B02
    speaker: CH_LINWEI
    text: She has no right to come through that door.
    action: defines Lin Yun as an outsider
    subtext: as long as the document stays out of public space, I control the interpretation
    target_duration_sec: 2.3
    emphasis: [right, door]
    interruptible_after: right
    lipsync: visible
  - id: LINE_E001_021
    beat: E001_B04
    speaker: CH_LINYUN
    text: My right is right here.
    action: converts an argument into a verification
    subtext: I do not accept your definition
    target_duration_sec: 1.4
    pronunciation: {}
    lipsync: visible_then_offscreen_allowed
```

Line text, function, performance, duration and lip sync are stored separately. Changing the words requires a new version
and a realignment.

## B.10 Narration and inner voice

Even with no narration, write `none` explicitly, so post cannot patch a hole with an improvised explanation.

```yaml
narration:
  mode: none
  rationale: episode one establishes the rules through conflict in the room
  forbidden_information:
    - the father's true status
    - Lin Wei's private plan
```

A narrated comic version instead records POV, authority, target duration, overlapping text and the picture's job for each
unit of thought.

## B.11 Shot requirements

These describe the information that must be covered; they do not lock every camera position on the shot designer's
behalf.

```yaml
shot_requirements:
  - id: SR_E001_B01_ACCESS
    must_observe:
      - the threshold, with Lin Yun outside it
      - the guard's arm forming the block
      - Lin Wei positioned inside
    acceptable_forms: [vertical_master, medium_two_shot]
    min_readability: passage_relationship_clear_on_phone
  - id: SR_E001_B04_PROOF
    must_observe:
      - the document entering publicly visible space
      - the authorization heading or signature legible
      - Lin Wei registering that the document exists
    acceptable_forms: [document_insert_plus_reaction, controlled_two_shot]
    blockers: [wrong_text, mirrored_signature, hand_swap]
```

## B.12 Sound plan

```yaml
sound_plan:
  dialogue_master_required: true
  room_tone: ROOM_MEETING_DUSK@v03
  foley_events:
    - {id: SFX_E001_004, action: guard_arm_blocks, priority: low}
    - {id: SFX_E001_018, action: folder_on_table, priority: medium}
    - {id: SFX_E001_022, action: authorization_hits_table, priority: foreground}
  music:
    cue: CUE_E001_ACCESS@v04
    enter: after_public_humiliation
    clear_for: [LINE_E001_021, authorization_impact]
    motif_state: LINYUN_TRUTH_incomplete_two_notes
  silence_events:
    - before_authorization_impact_ms: 300
```

## B.13 Asset dependencies

| Asset ID | Version | Use | State | Rights | Action if missing |
| --- | --- | --- | --- | --- | --- |
| `CH_LINYUN` | v03 | Identity | approved | original/cleared | None |
| `WD_LINYUN_GREY` | v04 | Base wardrobe | approved | project | None |
| `LOC_MEETING` | v05 | Location | locked | original | None |
| `PROP_AUTHORIZATION` | v07 | Hero prop | approved | original | Re-check advertising use |
| `VOICE_LINYUN` | v02 | Dialogue | approved | project/zh-CN | None |
| `MUS_LINYUN_TRUTH` | v03 | Theme | approved | sync only | Clear advertising separately |

The dependency table does not copy asset content; it references the registry. Any high-risk dependency in
`pending`, `blocked` or `expired` blocks the pack from entering the corresponding workstation.

## B.14 Continuity snapshot and events

```yaml
continuity_events:
  - id: EVT_E001_001
    at: E001_B01
    type: spatial_block
    before: passage_open
    after: passage_blocked_by_guard
  - id: EVT_E001_004
    at: E001_B04
    type: prop_reveal
    prop: PROP_AUTHORIZATION
    before: concealed_in_folder
    after: visible_on_table
  - id: EVT_E001_005
    at: E001_B05
    type: access_granted
    before: CH_LINYUN_door_outside
    after: CH_LINYUN_crosses_doorline
```

The exit state is obtained by replaying the events, and the pack still stores the approved snapshot so downstream can
read and audit it quickly.

## B.15 Risks and fallback routes

```yaml
risks:
  - id: RISK_E001_HANDOFF
    shot_requirement: SR_E001_B04_PROOF
    probability: medium
    impact: high
    symptom: hand and document merge, or left and right hands swap
    primary_route: static_keyframe_plus_short_slide
    fallback_A: hand_approach_cut_to_document_result
    fallback_B: separate_hand_plate_composite
    attempt_limit: 3
    decision_owner: DIRECTOR
  - id: RISK_E001_TEXT
    symptom: garbled text on the authorization
    route: clean_document_plane_plus_graphic_composite
    blocker: final_text_not_bound_to_FACTS_v07
```

## B.16 Acceptance criteria

```yaml
acceptance:
  story:
    - cold viewers can restate why the authorization changes her right to enter
    - the closing question points specifically at the father's account
  continuity:
    - Lin Yun crosses the threshold once, in a consistent direction
    - the authorization stays visible on the table after B04 until it is picked up
  visual:
    - lead close-ups pass the identity contract
    - the evidence text is readable for at least 24 frames on the target phone
  sound:
    - "My right is right here" is not masked by music
    - the document landing has mid-range weight and syncs with contact
  commercial:
    - E001 repays the entry promise before opening the father question
  rights:
    - every use in the episode is cleared
```

Criteria must be observable. Do not make "premium", "cinematic" or "the pacing feels good" the only acceptance.

## B.17 Pack approval record

```yaml
approval:
  status: approved_with_conditions
  conditions:
    - advertising use of PROP_AUTHORIZATION does not affect episode production but blocks creative release
  review_evidence:
    - COLD_READ_E001@v03
    - TABLE_READ_E001@v04
    - TIMING_ANIMATIC_E001@v06
    - ASSET_PREFLIGHT_E001@v05
  blockers_open: []
  decisions:
    - DEC_E001_031 keep the shot of the guard lowering his arm
```

## B.18 Pack diff and change request

```yaml
pack_change:
  from: EP_E001_PACK@v12
  to_candidate: EP_E001_PACK@v13
  request: change Lin Yun's line to "This is my right"
  changed_entities: [LINE_E001_021]
  direct_impacts: [dialogue_master, lipsync, subtitle]
  possible_impacts: [music_ducking, shot_duration]
  unaffected: [character_identity, location, authorization_graphic]
  estimated_cost_index: 3
  decision: rejected
  reason: the current version is shorter, and action and evidence complete the meaning together
```

## B.19 Pack lint

Automated checks include at minimum: IDs are unique; every reference exists; versions are approved or otherwise
permitted; facts agree with lines and graphics; character knowledge stays in bounds; entry and exit states can be
replayed; prop ownership has no break; total beat duration falls in range; every must-observe item has a coverage
requirement; rights blocks are not ignored; the cut point has a payoff contract; every risk has an owner.

Passing lint does not mean the script is good. It only proves there is no known hard conflict in the structure.
Performance, charm and feeling are still reviewed by humans.

## B.20 Minimum pack and full pack

A small experiment can keep only the manifest, episode contract, facts, beats, state, assets, risks and acceptance. Once
you have several characters, long narration, musical themes, multiple languages or commercial distribution, use the full
package. Trim by project risk, not by whether the team finds it tedious.

## B.21 Common counterexamples

- The literary script is approved and each department copies it and edits by hand.
- A line changes and the pack version does not, so lip sync and subtitles keep referencing old audio.
- A risk that says only "AI might fail," with no symptom, route, attempt limit or owner.
- Acceptance that says "consistent characters" without stating angles, shot sizes and tolerances.
- An asset table listing filenames with no version, rights or state.
- A cut point exists, and the next episode's pack has no payoff contract.

## B.22 Usage checklist

- [ ] Manifest, schema, version, hash and approvers are complete.
- [ ] The episode contract states this episode's function, payoff and new debt.
- [ ] Fact locks cover numbers, proper nouns, knowledge and negations.
- [ ] Every character, prop, space and emotion has an entry state.
- [ ] Every beat has a trigger, an action, what the audience gains and an exit state.
- [ ] Scenes produce a verifiable state delta.
- [ ] Lines carry their action function, duration and lip sync strategy.
- [ ] Shot requirements describe what must be seen without locking the shot design.
- [ ] The sound plan covers dialogue, space, Foley, music and silence.
- [ ] Asset dependencies carry version, approval, rights and the action if missing.
- [ ] High-risk actions have alternative routes and an attempt limit.
- [ ] Acceptance criteria are observable and bound to evidence.
- [ ] A pack diff can compute downstream impact.

## B.23 Exercises and deliverables

Exercise one: compile one page of literary script into a minimum pack. Exercise two: deliberately introduce early
knowledge, a swapped prop hand and a conflicting amount, then run a manual lint. Exercise three: change one key line and
list the effects on sound, lip sync, subtitles, music and duration. Exercise four: design three narratively equivalent
routes for one high-risk contact action.

Deliverables for this appendix: episode pack directory, manifest, episode contract, fact locks, state snapshot, beat
contracts, scene cards, line registry, shot requirements, sound plan, asset dependencies, continuity events,
risk and fallback, acceptance, approval, pack diff and lint report.
