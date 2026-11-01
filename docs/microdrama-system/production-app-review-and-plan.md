# DramaBox production app: review and implementation plan

Status: planning document. No implementation, deployment, live provider qualification, or domain configuration is implied by this document.

## Sources and scope

- Reviewed all 114 numbered chapters of [*Making the Show*](https://microdrama.cc/en/read/introduction/) and the downloaded `microdrama.cc-production-kit` prompts, schemas, and worksheets.
- Reviewed the current DramaBox implementation, [SPEC](SPEC.md), [task ledger](task_status.csv), and [26 October remediation record](../../microdrama/evidence/build-review-2026-10-25-remediation.md). The remediation record supersedes the open findings in the 25 October build review: F01–F09 were fixed and the offline `make check` passed. M5+ live qualification remains uncompleted in the ledger.
- The five-part “Microdrama Kit App” comparison comes from the owner's description of [the linked video](https://www.youtube.com/watch?v=XM3tJzRw8q4). Video playback and captions were unavailable during this review.
- The book synthesizes Chinese creator reports and a fictional case. Treat its methods as production hypotheses to test, not measured performance claims from a named studio. Its frequent 60–90 second paid-route examples need adaptation to DramaBox's original Thai, 180–300 second, initially organic route.

## Product decision

Build an operator-facing DramaBox production app over the existing canonical contracts, budget ledger, jobs, asset registry, approvals, QA, and publishing services. Proposed host: **`dramabox.aivora.agency`**. This is a target address, not a deployment instruction. The app should make the process understandable to one owner while keeping routine work automated between the existing two human gates: season concept approval and final episode approval/revision.

The production kit is a design input. Do not install its JSON Schemas as a competing source of truth: its episode and shot duration bounds, IDs, and lifecycle states differ from DramaBox contracts. Map useful fields into versioned DramaBox contracts and migrations with compatibility tests.

## Review of the five app features

| Feature | Existing foundation | Product gap and direction |
|---|---|---|
| Script Maker | Research proposals, `SeasonScope`, arc beats and cliffhangers, deterministic `SeasonBible`, Thai script writer/critic | Intake requires a prestructured candidate `SeasonScope`; the bible mostly compiles it. Add story, genre/tone, and episode-count intake; generate several original concept candidates and a deeper bible with character wants, secrets, strategies, relationship pressure, reveal timing, episode promises, payoffs, and cliffhangers. Use Gate 1 for the selected scope. |
| Sheet Maker | Face, wardrobe, location, style and voice anchors; versioning and episode-one identity lock | Add character turnaround and expression stress views, outfit sheets per character, prop sheets, location geometry/empty plates, and coverage checks based on actual planned shots. A six-view sheet is a useful UI checklist, but the views must fit the asset type and production need. |
| Series Look | Season style anchor and style rules | Add a versioned style bible: medium, realism, palette, lighting, lens, camera movement, material, typography, subtitle safe areas, sound motifs, and exclusions. Compare candidates on the same short moving scene. |
| Episode Prompts | `ShotManifest`, shot IDs, line IDs, reference IDs, deterministic shot prompts, routing and attempts | Show roughly six 30-second editorial sections for a three-minute episode, but generate each roughly 10–15 second shot (or shorter when needed) independently. Add explicit shot state, concrete reference binding, wardrobe assignment, and a vendor prompt manifest. Do not force six shots per section if the action or measured audio needs another count. |
| Covers | Three 20–40 second hook recuts; cover extraction from a midpoint frame | Create an approved-asset poster with title and CTA. Offer a separate optional 90-second episode-one preview and shorter acquisition variants from accepted footage. Check spoiler limits, payoff honesty, rights, mobile readability, and platform requirements. |

Relevant book methods: [character logic](https://microdrama.cc/en/read/007-character-relationships/), [episode pack](https://microdrama.cc/en/read/016-episode-pack-qc/), [asset development](https://microdrama.cc/en/read/018-character-visual/), [continuity state](https://microdrama.cc/en/read/023-character-state-machine/), [prompt compilation](https://microdrama.cc/en/read/084-prompt-compiler/), and [acquisition creatives](https://microdrama.cc/en/read/060-acquisition-creatives/).

## Required story-to-shot reference binding

The script maker must output more than prose. Every episode pack should identify its characters, locations, story props, story day/time, planned wardrobe changes, scene states, beats, and required evidence text. Every scene and shot must resolve these to stable IDs before generation. A shot's render packet should include:

```text
episode_id / scene_id / shot_id / beat_id / script_version
story_day, time_of_day, setting, weather, light_state
character_ids + identity_reference_version for each visible character
outfit_id + outfit_reference_version for each visible character
location_id + location_layout/plate/version
prop_ids + prop_reference_versions + prop holder/position/state
voice_ids, style_bible_version, required proof-text overlay IDs
state_in -> action/event -> state_out
screen direction, eyeline target, handoff frame, audio and edit intent
selected model/preset, compiled prompt/version, source hashes, budget reservation
```

The dependency resolver should attach only the references needed by that shot. Character identity, outfit, location, prop, and previous-frame references serve different purposes; a previous frame must never silently replace the locked identity reference. Missing, retired, unlicensed, or mutually contradictory references block dispatch with an actionable reason. The manifest and compiled prompt must carry the same source hashes so a change can identify affected keyframes, shots, exports, and creatives. Text on phones/documents should come from fact-bound editable overlays rather than trusting a video model to spell it.

### Clothing and story-time rules

- Give **each character a wardrobe bible**, with stable outfit IDs, reference sheets, valid settings and story phases, and optional state variants such as wet, damaged, or changed hair. Identity references stay separate from clothing references.
- The episode plan marks `story_day`, `time_of_day`, and `setting` per scene. The wardrobe planner assigns one outfit per visible character per scene, and each shot inherits that assignment until an explicit change event.
- On a **next-day** scene, propose a different outfit for each relevant character by default. Reuse of the same outfit requires an explicit story reason recorded in the plan. A setting change on the same day can also trigger a planned change, such as office clothes to home clothes.
- A clothing change must have a transition/event and an effective story interval. Shots before and after it bind to the correct outfit version. Flag an unexplained mid-scene switch, incompatible outerwear, or a wet/damaged state that disappears without cause.
- Generate missing outfit views when planned camera angles need them; reuse approved views across episodes. Forecast and attribute their cost before generation so wardrobe coverage does not silently defeat the US$10 episode cap.

Acceptance example: if a character wears `WD_A_OFFICE_01` in E001 day 1 and the script begins day 2 at home, the plan binds the new scene to `WD_A_HOME_02` and every shot to its matching outfit sheet. If the same office outfit is intentionally worn again, the plan stores why and continuity QC checks that choice. Revising either outfit lists the affected shots and requires the ordinary repair/review path.

## Operator UI at `dramabox.aivora.agency`

Suggested navigation: **Projects → Series → Episodes → Assets → Review → Releases → Analytics**. The dashboard should open on the active series and show the current task, blockers, actual cost/remaining allowance, and next required owner action. The Script Maker remains a short three-step wizard; advanced settings expose the approved DramaBox policies without making ordinary users fill in schema fields.

### Interactive timeline and percentage

Show an **episode lifecycle timeline** with a prominent overall percentage, a percentage for the active stage, and the complete ordered list of completed, active, upcoming, waiting, blocked, and rework steps. A click expands each step to show scene/shot IDs, work completed versus planned, generated assets, job/attempt state, costs, last event, estimated next action, and any error or approval needed. For an episode section, show labels such as `E001 / section 1.1 / shots 1–6`, with individual shot status rather than a single opaque “generating episode 1.1” message.

The timeline should include, as applicable:

1. Series intake and concept candidates → **Gate 1: waiting for season approval**.
2. Episode plan, script, canon and duration checks.
3. Character identity sheets, each character's wardrobe sheets, location and prop sheets, voice and series look; reuse is shown distinctly from new generation.
4. Scene wardrobe assignments, storyboard/shot list, continuity checks, reference binding and prompt compilation.
5. Still keyframes and shot generation, grouped by section and scene, with accepted/total shots and retry counts.
6. Dialogue, sound, assembly, subtitles, graphics and platform variants.
7. Actual-media QA, targeted repairs, teaser/hooks, poster and final review package → **Gate 2: waiting for episode approval or revision**.
8. Scheduled release, destination-specific submission and verified playback; then management/analytics as a separate post-release track.

Compute percentages from **persisted required work**, not an LLM's guessed completion percentage or elapsed time. For example, the shot stage advances on accepted shots out of planned shots; an attempted or failed render is visible but does not count as accepted. Stage weights can be calibrated from observed cost and duration after a pilot. When a revision changes the denominator or invalidates completed work, recalculate honestly and show the new plan version and reason. Human waits and blocked providers freeze progress with a clear status. Use an indeterminate indicator for a running external call whose internal progress is unknown. Display ETA only when there is enough measured history, and label it as an estimate.

The backend should project this view from existing durable episode states, domain events, jobs, assets, approvals, QA, and platform posts. It must survive a browser refresh and worker restart, never maintain a separate optimistic browser-only production truth. Polling is sufficient initially; server-sent events can improve timeliness later. A separate release track prevents “100% produced” from being mistaken for “published and verified.”

## Rollout: prove V1 before scaling the new app

**Decision:** continue testing the V1 pipeline. The next milestone is a bounded, rights-appropriate Runpod canary followed by a V1 integrated test, not an immediate public launch or a full season render. The [offline pilot](../../microdrama/runbooks/pilot.md) already exercises the two-gate workflow with fake providers and real local FFmpeg. No real Runpod pod has been used for this project. The current [Runpod adapter](../../microdrama/src/microdrama/rendering/pods.py) deliberately raises `EffectDenied` even when credentials are configured, the [composed world](../../microdrama/src/microdrama/pipeline/world.py) uses fakes, and the [preset benchmark tool](../../microdrama/src/microdrama/rendering/presets_benchmark.py) refuses non-mock mode. Turning on effect flags is therefore not a live integration test.

| Gate | Smallest useful run | Advance only when |
|---|---|---|
| 0. Reconfirm V1 baseline | Re-run current offline checks and `make pilot` at the chosen commit; preserve checksums, stage report, and known limitations. Inventory the exact model, ComfyUI graph, reference controls, Thai voice route, output rights, GPU/VRAM need, provider pricing, and storage. | The baseline is reproducible and the selected paid test has a bounded exposure forecast and a rights route suitable for the intended use. |
| 1. Single Runpod technical canary | Launch **one** explicitly bounded pod with pinned image/model/workflow and a hard lifetime. Use generic test references first: load the model, generate a still/keyframe and one short reference-controlled moving shot, download verified output, record cold/warm time, attempts, GPU memory and actual charge; stop and independently verify the pod is off. | The chosen GPU can run the actual graph and controls; output can be retrieved and verified; cost is reconciled; cleanup works. A manual pod proves model/hardware feasibility only. |
| 2. V1 paid adapter canary (T031) | Implement and test the real Runpod lifecycle, ComfyUI transport, credential resolution, bill/usage reconciliation, durable output copy, timeout recovery and independent janitor within V1. Run the same small shot set through **DramaBox's** ordinary reservation → dispatch → poll → QA path. | No orphaned pod, duplicate paid attempt, lost output or unaccounted charge after injected timeout/restart. Registry presets remain disabled until rights, quality and accepted-cost evidence exists. |
| 3. V1 narrative pilot | Produce one 20–30 second Thai scene with a lead profile, two-character exchange, next-day or setting-based outfit change, prop handoff, readable evidence and sound. Then build one complete 180-second episode through the two existing approvals. | Blind comprehension, identity/wardrobe/prop/location continuity, Thai voice and subtitles, phone playback, QA coverage, repair path and **actual all-in variable cost** meet the approved episode criteria. Record every manual intervention; it does not count as automation success. |
| 4. Private app beta | Put the operator app behind authentication on a staging host, then prepare `dramabox.aivora.agency` only after real jobs and events can drive the timeline. Start with one series and one episode. | A restart, retry, approval wait and failed shot all display truthful status/percent and next action. The app cannot bypass budget, rights, approval or reference binding. |
| 5. Controlled release then expansion (T032–T034) | Test account-specific upload, disclosure, scheduling and readback on supported destinations with approved media; release the first approved episode, then qualify successive episodes and management windows. | Required slots really verify, costs and outcomes reconcile, and the existing ten-episode/seven-day qualification rule is met before volume increases. |

For Gate 1, derive the maximum exposure from the **current** pod quote, time limit, storage and cleanup reserve before launch. Use a provider-side stop/termination deadline where available plus an independent watchdog; the V1 lifecycle must still reconcile and verify stopped state. Runpod currently bills compute and storage by the second and retains charges for persistent storage on stopped pods; its CLI supports `--stop-after` and `--terminate-after`. Check the deployment quote at test time rather than copying a price into this plan. [Runpod pricing](https://docs.runpod.io/pods/pricing) · [Runpod pod management](https://docs.runpod.io/pods/manage-pods) · [Runpod CLI pod reference](https://docs.runpod.io/runpodctl/reference/runpodctl-remove-pods)

The new Script Maker, reference binding and progress UI can be designed while Gates 1–3 run, but production claims must follow the V1 evidence. If the canary shows unacceptable identity drift, Thai performance, render time or cost, change the model/preset/visual route or simplify the shot design before committing to a full app workflow. If no route meets quality and the cost cap, record that feasibility result instead of scaling attempts.

## Delivery order and acceptance

| Order | Work | Evidence before advancing |
|---|---|---|
| 1 | Live pilot qualification and source-of-truth design | Rights-cleared Thai model/voice routes, realistic cost per accepted second, representative scene, and a field mapping from kit worksheets into existing contracts. Mock success is not live qualification. |
| 2 | Story intake and episode pack | A short user idea produces several original proposals, a coherent selected bible, first three detailed episode packs, and consistent character/prop/location lists without an extra routine human gate. |
| 3 | Wardrobe, asset sheets and shot-state compiler | Next-day and setting changes assign correct per-character outfits; each short shot binds the exact approved character, outfit, location and prop versions; conflicting/missing references block before paid dispatch. |
| 4 | Operator UI and progress projection | An owner can open E001, see every step and shot, the truthful percent and next action, refresh/restart without losing status, and complete only the two existing approval types. |
| 5 | Teaser/poster and quality loop | Creatives derive from approved assets, pass spoiler/rights/mobile checks, appear in the final package, and remain traceable to their source. |
| 6 | Controlled live release and scale | One complete actual episode passes two approvals, cost/QA/rights gates, and verified required release slots. Scale follows the existing ten-episode qualification policy. |

The existing `SPEC.md` remains the implementation authority until these additions are reviewed and incorporated there. This document records the product direction and acceptance criteria for that subsequent specification update.
