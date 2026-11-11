The spec needs rework before a build. It captures most of the intended product, but several contracts would make production stall, misstate costs, or invalidate approvals.

I reviewed the binding documents, factmap, Joey digest, pipeline map, main checkout at `0851374`, and the supplied T031 worktree, observed at `bdf1e2b`. This was read-only; I did not run tests or provider calls.

Fidelity is mostly preserved: STORY LOCK before asset spending; CAST LOCK; three candidate picks; ElevenLabs samples conditioning Pika native dialogue; metadata before final approval; the domain; cinematic two-minute episodes; daily releases; TH/EN/ZH captions; YouTube Shorts/TikTok/Facebook; the dedicated bot; Nano Banana Pro; YuE2 and ElevenLabs SFX v2; recap and CTA.

The numbering deserves an explicit crosswalk. DECISIONS has “8. Review + approve” and “9. Multi-language captions…”, while SPEC §2 has Metadata at 8 and Approve at 9. REQUIREMENTS §0 explicitly adopts that renumbering to implement D3’s “Draft before Gate 2.” The dependency is faithful; the original operator numbering has changed.

**V3C-1 — BLOCKING — §§1, 10.1; binding-input precedence.** REQUIREMENTS says production should use “metered API keys, never the team’s Claude Pro / z.ai / Codex development subscriptions.” SPEC says “test with the Claude subscription first.” Your current instruction explicitly requires subscription-first measurement, so the spec follows your latest direction, but its two binding inputs conflict.
  
**Replacement:** “The operator’s latest subscription-first pilot instruction supersedes REQUIREMENTS’ API-only sentence. P0–P2 use the Claude subscription through the qualified `dramabox-llm` role. Full-season provider selection remains an operator decision after measurement.”

**V3C-2 — BLOCKING — §12.3; the season budget exceeds the approved decision.** DECISIONS Q10 says “US$10 per episode cap until T031 measures the real cost; season cap = episodes × cap.” SPEC adds “+ the step-4 cap” and changes the decision point to “until the pilot.” For 24 episodes, that silently changes $240 to $300.
  
**Replacement:** “The episode cap remains $10 until an operator-approved change informed by T031. The season cap is episode count × $10. Step-4 expenditure is a sub-budget within that total. Any additional setup allowance requires a dated operator decision. Shared-cost allocation must reconcile without double counting.”

**V3C-3 — BLOCKING — §§4.1, 4.3, 12.4; unsupported scope changes.** REQUIREMENTS R-12.5 requires “Season 2 reuse of locked cast, voices and locations”; SPEC defers it to “v3.1.” DECISIONS Q1 specifies “20–30 episodes… extended depending on viewership,” whereas the spec inconsistently permits 20–40 initially and introduces an unexplained extension ceiling of 40.
  
**Replacement:** “Initial seasons contain 20–30 episodes. Extensions append an explicitly approved N; any technical maximum is documented separately. V3 includes reuse of cast, voice samples and locations across seasons, preserving source lineage and revalidating rights.”

**V3C-4 — BLOCKING — §§4.3, 14–15; planning has a circular dependency.** The current writer rejects later episodes without an identity lock (`story/service.py:787`); V3 needs every script before CAST LOCK. Meanwhile, `generate_episode_pack` requires available asset and wardrobe-assignment IDs, which step 4 has not generated.
  
**Replacement:** “Step 3 writes complete scripts against stable logical character, outfit, prop and location demand IDs. Step 4 resolves these demands to immutable asset versions in a separate binding record. Planning requires STORY authority; rendering requires CAST authority. Create all planned episode rows independently of daily release cadence.”

**V3C-5 — BLOCKING — §§4.2–4.3, 13; `EpisodePackV3` is insufficiently defined.** “Unifies V1 + V2” does not specify the authoritative schema, migration, projections or consumers. Changing `ProductionLimits` alone also leaves literal 180–300-second validators in `SeasonScope`, `EpisodePlan` and `EpisodePack`, plus 1–10 intake/candidate validators.
  
**Replacement:** “Publish normative V3 schemas and a field-by-field V1/V2 mapping. Define stable IDs, revisions, hashes, storage, compatibility readers and consumer migration order. Replace every duration/count validator consistently. Preserve old records and approvals through explicit schema-version handling. Reuse the existing `contracts.providers.LLMProvider` protocol.”

**V3C-6 — BLOCKING — §§4.4, 13–14; CAST LOCK is a substantial approval migration.** `IdentityLocks.create_lock` explicitly requires episode-one Gate 2 and an approved release package. SQL requires `source_episode_id` and `release_package_hash`. The Gate-2 service still invokes that hook. Adding a gate enum cannot implement the proposed replacement.
  
**Replacement:** “Introduce a season-scoped cast-lock contract with STORY revision, complete asset membership and human CAST approval provenance. Migrate identity-lock readers and episode creation. Remove episode-one lock creation from the V3 Gate-2 path. CAST LOCK atomically freezes accepted members and binds existing episodes; future episodes bind the applicable lock version.”

**V3C-7 — BLOCKING — §2.2; workflow states lack executable transition rules.** Production and release overlap during a daily season, yet the season machine presents them as sequential phases. Reject, cancel, partial failure, quota waiting, amendment and resumption are incompletely defined. Existing scheduler predicates use entirely different states.
  
**Replacement:** “Specify each command’s allowed states, prerequisites, transaction, emitted event, queued jobs and replay result. Represent production and release independently. Persist blocked stage, reason and resume target. Replace old scheduler selectors so no V3 job bypasses STORY LOCK or CAST LOCK.”

**V3C-8 — BLOCKING — §§2.2, 4.4; the picks workflow cannot satisfy its own rules.** Votes “start no work,” but sheets and outfits depend on picked faces, and voice creation/TTS occurs “On pick.” CAST LOCK requires every required item to be picked, while sheets, expressions and coverage are auto-accepted without picks.
  
**Replacement:** “Pick records a vote only. Explicit Generate/Next actions enqueue dependent work against selected parent revisions. Define required human picks separately from derived assets accepted within the final CAST review. CAST LOCK hashes both sets. Parent rerolls invalidate dependent candidates and selections; unrelated picks remain valid.”

**V3C-9 — BLOCKING — §§4.4, 10; partial failures and outages have no recovery contract.** A generic BLOCK state does not define what happens after two successful character jobs and one timed-out voice creation, or after a provider accepts a request whose response is lost.
  
**Replacement:** “Each generation unit persists immutable inputs, semantic attempt ID, reservation, provider request ID, result and status: queued/running/succeeded/retryable/unknown/failed. Restart resumes unfinished units without regenerating successes. Reconcile unknown outcomes before resubmission; retain unresolved exposure. Apply bounded retries, backoff and operator-visible recovery actions. Release GPU resources before human waits.”

**V3C-10 — BLOCKING — §§4.4, 5, 14; wardrobe wiring has existing incompatibilities.** `assign_scene_wardrobes` uses `scene.location_id` as setting; `compile_episode_pack` compares assignment setting with descriptive `StoryTime.setting`. Its previous-outfit memory is local to one invocation, so separate episode calls do not enforce next-day variation across the season. Timed events also require an explicit time basis and boundary policy.
  
**Replacement:** “Use one canonical setting ID throughout planning, assignment and directing. Persist wardrobe history across episodes. Define scene-relative event intervals and shot boundaries; split shots crossing incompatible outfit states. Define composition and precedence for simultaneous appearance states, and persist resulting asset bindings.”

**V3C-11 — BLOCKING — §§5–6, 14; multi-view binding needs more than selection logic.** The resolver expects exactly one sheet per role/subject and derives scene-wide cast requirements. Appearance states and extras need defined semantic bindings. Its mandatory style reference is a moving video, while T031’s native source validator requires PNG images or WAV audio. Also, §5 names `allowed_light_states`; the actual field is `light_states`.
  
**Replacement:** “Define the production reference schema by shot-visible subject, role, view, outfit/state composition and location/light variant. Specify supported cardinalities and current-rights checks. Define an H3-compatible style representation. Resolve views before exact binding validation; never pass a moving style video as an image reference.”

**V3C-12 — BLOCKING — §6; dropping references can remove essential story evidence.** The priority list may discard a proof prop or a silent principal character. Existing semantic validation rejects omission of exact beat proof props. Selecting a headless front sheet as the wide-shot “face/view” also fails to provide facial identity.
  
**Replacement:** “Classify bindings as mandatory or optional. Identity-bearing face references, required wardrobe/state, proof props and necessary location references cannot be dropped. Over-budget shots must use qualified composites, simpler coverage or split shots. Drop only optional references, with recorded reasons.”

**V3C-13 — BLOCKING — §4.5; director output does not match the existing compiler.** The compiler takes `BeatIntent` per beat and allocates duration across beats; it does not consume the proposed per-shot dialogue/timing/lens structure. SPEC permits 4–6-second clips, while T031 pins 124 frames at 24 fps—about 5.17 seconds.
  
**Replacement:** “Choose one authoritative shot-plan compiler and define its mapping to persisted directing manifests and render requests. Store full dialogue coverage, speaker ownership, timing and source dependencies. Generate only qualified frame counts; editing may trim within measured speech-safe boundaries. Validate total episode duration including recap, transitions and CTA.”

**V3C-14 — BLOCKING — §§4.6, 14; T031 promotion is missing a production adapter.** T031 is a benchmark controller. Its Pika binder requires a sealed `PikaBindingContext` with verified uploads; `dispatch_v2_routed_attempt` calls the binder without that context. The benchmark manifest builder also requires nonempty speakers, whereas production needs silent inserts, establishing shots and reactions.
  
**Replacement:** “Build a production native-render adapter over the accepted T031 transport/recovery primitives. Supply verified acquisition-scoped upload/binding context at both binding stages; support zero-, one- and two-speaker shots. Define asset registration, polling, QA handoff, retries and shutdown. Requalify any changed runtime image or workflow.”

**V3C-15 — BLOCKING — §4.7; native audio is an end-to-end edit change.** `build_edl` requires separate dialogue sources and room tone. Both exporters ignore native clip audio. Caption spotting derives timing from EDL dialogue clips, so changing only `plan_master` leaves captions detached from actual speech.
  
**Replacement:** “Add native clip-audio sources and measured utterance alignment to the EDL. Preserve synchronized audio/video trims through masters, crops, hooks, recap and fades. Generate all caption cues from accepted native speech and remap them through edits. Do not synthesize replacement dialogue or duplicate native ambience.”

**V3C-16 — BLOCKING — §§4.6, 8; QA permits undetected continuity errors and incomplete review packages.** Correct words, faces and technical media can coexist with the wrong outfit or prop, so checking continuity mainly after those detectors flag is inadequate. ASR does not verify voice identity or lipsync. “Episode continues” after exhausted retries conflicts with the editor’s requirement for accepted source clips.
  
**Replacement:** “Define required checks, thresholds, applicability and coverage per shot. Unknown is distinct from PASS. Missing/rejected required clips block final assembly. Critical unresolved findings block approval; incomplete diagnostic previews are explicitly non-approvable. Required checks unavailable automatically must receive recorded human assessment within Gate 2.”

**V3C-17 — BLOCKING — §§4.6, 10.2; on-pod QA is neither resource-free nor qualified.** Whisper large is documented at approximately 10 GB VRAM; concurrent fit with H3 on an A40 is unproven. Model loading and QA extend paid lease time. Common InsightFace pretrained weights are restricted to noncommercial research. [Whisper hardware table](https://github.com/openai/whisper), [InsightFace licence](https://github.com/deepinsight/insightface#license).
  
**Replacement:** “Pin commercially usable detector weights and benchmark the exact render-plus-QA image on A40. Specify sequential loading/offload or measured concurrent headroom, OOM handling and deadlines. Meter loading, QA and idle GPU time; preserve shutdown reserves and recovery protection.”

**V3C-18 — BLOCKING — §§4.4, 7; ElevenLabs design and synthesis models are conflated.** Voice Design accepts `eleven_ttv_v3`, distinct from TTS models `eleven_v3`/`eleven_v4`; its default design model is different and preview text requires 100–1000 characters. Thai TTS support does not validate a wrong design-model ID. The DECISIONS account snapshot leaves one free slot, while P0 needs two characters. [Design API](https://elevenlabs.io/docs/api-reference/text-to-voice/design), [model catalogue](https://elevenlabs.io/docs/overview/models/).
  
**Replacement:** “Pin a Thai-capable design model separately from the final TTS model. Preflight credits, commercial entitlement and required slots. Persist previews, chosen generated-voice ID, created voice ID and creation reconciliation. CAST LOCK binds the auditioned WAV; any newly synthesized final sample must be auditioned before locking.”

**V3C-19 — BLOCKING — §10.2; a Drama-only lock cannot protect ARISA’s quota.** The inspected ARISA worker/provider path does not establish participation in the proposed lock. Separate container files or uncoordinated manual processes defeat the guarantee.
  
**Replacement:** “Before enabling live image jobs, qualify one shared exclusive lock used by all ARISA and Drama Box Nano Banana entry points, including manual tooling. Define the shared host/container inode, process lifetime, crash release and queue policy. Waiting is visible and holds no GPU. Coordinate ARISA changes with its owner.”

**V3C-20 — BLOCKING — §§4.7, 7, 14; YuE2 reuse is materially understated.** ARISA’s wrapper hardcodes an RTX 4090 and ARISA ingestion/storage conventions. The instrumental recipe includes score preparation and does not guarantee vocal-free output merely because an instrumental input validates. This is not an interchangeable Drama Box job.
  
**Replacement:** “Define a Drama-owned YuE2 job with pinned instrumental recipe, A40 qualification, duration/loop targets, vocal-leakage inspection, cue selection and rights. Use canonical Drama reservations, ownership, recovery, verified output download and billing finality. Assign music generation explicitly to step 4’s job graph and budget.”

**V3C-21 — BLOCKING — §§10.1–11; the proposed Claude meter cannot read the current router output.** `ai_route.py:1443` parses Claude JSON, prints/stores `result`, and records aggregated tokens. It discards `total_cost_usd` and structured-output metadata. Claude also documents cost as an estimate; resumed conversations can report earlier runs’ cumulative cost. [Programmatic output documentation](https://code.claude.com/docs/en/headless).
  
**Replacement:** “Add a versioned machine-result interface to `ai-route`, preserving result/structured output, per-model token/cache usage, estimated cost, session ID, outcome and timing. Persist it before acknowledging completion. Define per-invocation versus cumulative accounting and deduplicate by durable invocation ID.”

**V3C-22 — BLOCKING — §10.1; a server cannot safely treat `ai-route` as an ordinary synchronous model call.** Current routing permits one Claude-Pro job, blocks on `communicate()`, has no generation wall deadline there, and permits launches when quota reads fail. Its default permission mode is `auto`. `--allowedTools` grants unprompted execution; it does not restrict the available toolset. [CLI permissions reference](https://code.claude.com/docs/en/cli-reference).
  
**Replacement:** “Run subscription calls through a bounded durable service queue with orchestration priority, isolated execution context, restricted tools/plugins and narrowly scoped authentication. Define deadlines, cancellation and process cleanup. Persist pace/concurrency/quota refusal with retry timing; unreadable quota pauses production. Resume accepted units without silent provider fallback or episode restart.”

**V3C-23 — BLOCKING — §11; the pilot cannot yet answer the operator’s economic question.** The meter mixes subscription API-equivalent estimates with actual charges. Shared setup cost, failed calls, GPU loading/QA/idle time, credits, slot occupancy and human review are not reconciled. Quota deltas are contaminated by other sessions, reporting lag and reset boundaries. Four short-season episodes do not measure 20–30-episode planning overhead.
  
**Replacement:** “Report cash spend, subscription allocation, API-equivalent estimates, quota usage and operational exposure separately. Measure representative full-season planning plus the four rendered pilots. Compare frozen workloads and quality/repair rates across candidate LLM routes. Record timing, cache state, resets, other usage and uncertainty; distinguish measured comparisons from forecasts. Use an isolated pilot profile compatible with four episodes.”

**V3C-24 — BLOCKING — §§4.8–4.9, 9; publication slots and caption delivery are underspecified.** “Per platform × language” could create three posts or nine. Existing packaging still creates demo-dated YouTube/Facebook full slots and TikTok/Instagram promo slots. YouTube submission does not upload caption payloads automatically. Local EN/ZH SRTs do not prove viewers receive them.
  
**Replacement:** “Specify the exact destination/account/format/locale slot matrix and requiredness. Publish the full episode through the qualified Shorts/TikTok/Facebook routes; exclude Instagram. Define reviewed EN/ZH caption delivery per destination and verify it through supported readback. Hold unsupported required capabilities, including Facebook disclosure, until T032 qualifies them.”

**V3C-25 — BLOCKING — §§4.10, 9; launch timing and buffer recovery are contradictory.** Gate 2 “schedules all slots,” but a start date cannot be set until five episodes are approved. There is no defined handling for rejection near airtime, zero buffer, late teaser, predecessor failure or changes to dates already sealed into manifests.
  
**Replacement:** “Propose the calendar before review; gate activation on five approved episodes and a valid teaser schedule. Define exact approval binding for dates and permitted rescheduling. Persist per-destination predecessor dependencies and missed-release states. Hold affected successors after rejection/failure, alert with repair/reschedule options, and require approval for changed release authority.”

**V3C-26 — BLOCKING — §4.3; extension lacks canon, cast and analytics contracts.** Every existing pack is bound to an exact Gate-1 scope/count. Increasing count or cast can invalidate old hashes. “Current canon” is ambiguous when some planned episodes remain unpublished. No analytics adapter or extension decision screen is specified, despite R-12.11.
  
**Replacement:** “Create an append-only extension scope linked to prior STORY/CAST locks and both planned-terminal and published canon states. Preserve existing episode approvals. Bind additions to explicit cast versions; new assets alone require picks. Provide viewership windows with freshness/unknowns and manual extension. Support extension from RELEASING or COMPLETE with an explicit continued/resumed calendar.”

**V3C-27 — BLOCKING — §§2.1, 12.6; amendment is described as invalidation without execution semantics.** Regenerating “only the noted packs” can make later scripts inconsistent. Existing helpers compute dependency closure; they do not provide a complete amendment service, cancellation protocol or publish-race protection.
  
**Replacement:** “Regenerate requested packs only, then revalidate the dependency closure. Block newly invalid dependents pending scoped revision authority. Atomically invalidate affected unpublished approvals and queued submissions; fence late job results by input revision. Published media remains immutable. Rebuild dependent recaps, teasers, captions, thumbnails and metadata against new hashes.”

**V3C-28 — BLOCKING — §3; the checkout UI is recognizable but incomplete.** Tabs and progress bars are specified. A usable Next/Approve journey is not: tabs 5–9 all open the board, selected-episode context is unclear, automatic completion is shown as “locked,” and launch, amendment, extension, outage, quota-wait and recovery screens/actions are absent.
  
**Replacement:** “Define each tab’s route, scope, selected episode, progress denominator and primary action. Next navigates completed automatic stages; only designated approval actions advance gates. Show disabled reasons, waiting category, retry timing and recoverable units. Add launch/calendar, amendment-impact and extension screens. Include the operator-to-V3 numbering crosswalk.”

**V3C-29 — SHOULD-FIX — §4.7; recap and CTA dependencies become wrong near the finale.** The default says “next episode tomorrow” even on episode 30, or when release is delayed. A recap can become stale after the preceding episode’s final revision.
  
**Replacement:** “Bind recap ranges and captions to the preceding approved episode version. Rebuild after relevant revisions. Resolve CTA from the approved release calendar: next episode, confirmed continuation, or season-finale follow message. Never promise an unapproved extension or nonexistent air date.”

**V3C-30 — BLOCKING — §§3.1, 10, 15; adding compose services and switches does not create live composition.** App and worker explicitly refuse non-`OFFLINE_MOCK`; the world constructs fake providers. The scheduler entry point fires once and exits. There is no specified qualified production factory, persistent timer or complete restore procedure.
  
**Replacement:** “Build a separate qualified production composition with per-provider credentials, capability gates and fail-closed startup checks. Define scheduler invocation frequency, singleton behavior, catch-up and health reporting. Document DB/object/provenance backup consistency and prove restore before domain activation. Preserve private mock staging.”

**V3C-31 — SHOULD-FIX — §§3.4, 16; bot ‘exactly once’ is stronger than the transport contract.** A successful Telegram send followed by a lost response creates an ambiguous outcome. A deduplicated DB row alone cannot prove one external message.
  
**Replacement:** “Create one durable outbox event per source event. Specify timeout, retry, ambiguous-send and dead-letter behavior; record provider message IDs when available. Promise deduplicated event creation and bounded delivery attempts, with possible duplicate external delivery surfaced honestly. Store the destination chat and deep-link policy explicitly.”

**V3C-32 — SHOULD-FIX — §§4.1, 18; trend research remains a deferred promised feature.** DECISIONS step 1 offers either trend research or one-line input. REQUIREMENTS R-1.1/R-1.4 require live research. O-1 instead defaults to Mode B indefinitely.
  
**Replacement:** “Define trend-source adapters, freshness, provenance, failure behavior and research budget before declaring Mode A complete. Until qualified, disable it visibly with a reason. A Mode-B-only milestone is explicitly partial V3 acceptance.”

**V3C-33 — SHOULD-FIX — §§4.4, 12; rights and inspection obligations need concrete records.** The digest explicitly reports no licence grant in Joey’s supplied files. Provider/model rights records do not establish permission to embed their full prompt text. Prompt-only originality checks also do not inspect generated branding or text.
  
**Replacement:** “Record the authorised basis and version for imported prompt material, detector weights, fonts and generated assets. Distinguish generation-time entitlement from later plan upgrades. Add output inspection findings for forbidden text, branding and likeness; unresolved findings follow existing QA/repair and Gate-2 handling.”

**V3C-34 — BLOCKING — §16; V3-AT-1..17 are useful smoke tests, not sufficient acceptance.** They mostly test happy-path snapshots. They do not prove restart safety, cap enforcement under concurrency, complete production composition, calendar recovery, extension authority or actual caption delivery.
  
**Replacement:** “Add the invariant tests below. Require an end-to-end V3 composition test through all human gates and a 30-episode release simulation. Expand live acceptance beyond the presence of cost numbers to representative Thai quality, measured throughput and qualified destination behavior.”

The §14 code claims check out as follows. Most existence claims are correct; “wire up” substantially understates the work.

| §14 item | Verified code and implication |
|---|---|
| Rich bible + ledgers | Callable in [script_maker.py](/root/AIVORA/drama-box/microdrama/src/microdrama/story/script_maker.py:658); new orchestration, continuity context and V3 contracts remain necessary. |
| Wardrobe + timed outfits | Callable in [v2_planning.py](/root/AIVORA/drama-box/microdrama/src/microdrama/references/v2_planning.py:1043); setting mismatch and cross-episode history require changes. |
| `plan_reference_demands` | Callable, episode-scoped, requiring grants/views/prices and concrete assignments. Its persistence lane accepts labelled offline mocks; live registration is new work. |
| V2 directing compiler | Callable in [directing.py](/root/AIVORA/drama-box/microdrama/src/microdrama/story/directing.py:101); its beat-intent/timing contract differs from `ShotPlanV3`. |
| `dispatch_v2_routed_attempt` | Callable in [routing.py](/root/AIVORA/drama-box/microdrama/src/microdrama/rendering/routing.py:779); native Pika context is not supplied by its current binding calls. |
| Poster/preview compositor | Callable, but requires accepted assets, exact rights/readability/lineage. Preview is episode-one-only and has `release_obligation=False`; season teaser is a contract extension. |
| T039 map rule | Correct: generation flag at line 818, compact-outline prompt at 826, and `first_three_and_later_map` all enforce it. Remove all applicable rules and update tests. |
| `plan_master` native audio | Correct diagnosis in [export.py](/root/AIVORA/drama-box/microdrama/src/microdrama/editing/export.py:52); EDL, captions, variants and hooks also change. |
| Exporter fades | Correct: schemas exist, filter implementation does not. Both master exporters need synchronized timeline handling. |
| Shot resolver | Correct in [v2_binding.py](/root/AIVORA/drama-box/microdrama/src/microdrama/references/v2_binding.py:53): one sheet per role/subject; scene-assigned outfit; no timed substitution. |
| Intake limits | Correct, but constraints also exist in contracts and validators outside intake/`ProductionLimits`. |
| Identity lock at CAST LOCK | Correct desired replacement; [identity_lock.py](/root/AIVORA/drama-box/microdrama/src/microdrama/references/identity_lock.py:82), SQL, review hooks and consumers require coordinated migration. |
| Scheduler in compose | Correct absence in [compose.staging.yaml](/root/AIVORA/drama-box/microdrama/deployment/compose.staging.yaml). Existing CLI is one firing, using the mock world. |
| Gate 1 Revise | Correct absence. Approval actions, SQL constraints, proposal revision/history and job semantics must change together. |

The requirement trace does not establish builder completeness. I found **68 distinct R-IDs**; §17’s family wildcards conceal the following gaps.

| R-IDs | Coverage assessment |
|---|---|
| R-1.1–1.4 | Proposal fields are present; live research, Revise contracts and LLM invocation remain incomplete. |
| R-2.1–2.5 | Bible/character/camera/progress intent is well represented; authoritative schemas and wired generation remain unspecified. |
| R-3.1–3.7 | All-episode intent is present; bootstrap, unified records, revision closure and extension scope are blocking. |
| R-4.1–4.11 | Categories/providers are named; staged picks, live persistence, state composition, failure recovery and locking are incomplete. |
| R-5.1–5.5 | Joey direction and no storyboard gate are preserved; compiler mapping, timing and reference feasibility are incomplete. |
| R-6.1–6.4 | Route, retries, cap and counters are named; production adapter, acceptance states and qualified QA are incomplete. |
| R-7.1–7.7 | All requested edit elements appear; native timing, exporters, music/SFX jobs and final CTA behavior need contracts. |
| R-8.1–8.3 | Drafts, translations and three thumbnails are specified; destination/locale delivery remains ambiguous. |
| R-9.1–9.2 | Gate-2 intent is preserved; calendar activation, required slots and failure recovery are incomplete. |
| R-10.1–10.2 | Teaser intent is present; season-source contract, spoiler authority and release dependency are incomplete. |
| R-11.1–11.6 | Domain, stepper, bars, waiting list and bot are present; actions, episode context and operational screens are missing. |
| R-12.1–12.4 | Lock propagation, continuity, extras and rights need the migrations/contracts identified above. |
| R-12.5 | Explicitly deferred despite being binding. |
| R-12.6–12.11 | Amendment, budgeting, recap, safety, deployment and live providers are partial; analytics is effectively absent from the build plan. |
| R-12.13 | Meter/pilot exists in outline; attribution, comparability and decision criteria are insufficient. |

A full-season walkthrough exposes these operational gaps:

| When | Required behavior still missing |
|---|---|
| Before production | Qualify account entitlements, voice slots, shared image lock, production composition and representative pilot economics. |
| Planning days | Resume all 20–30 packs without asset-lock prerequisites; preserve running canon and expose unresolved dependencies before STORY LOCK. |
| Casting days | Generate dependent assets in stages; preserve successful picks through outages; forecast the full outfit/state/view/light demand. |
| At least three days before premiere | Approve and activate the teaser against an exact premiere calendar and spoiler policy. |
| Premiere and days 2–5 | Activate approved full-episode slots, deliver captions, verify publication and maintain predecessor/recap dependencies. |
| Days 6–29 | Produce while releasing; handle rejected reviews, provider refusal, dry buffers, partial platform publication and bounded repairs. |
| Day 30 | Publish and verify all required slots, use a truthful finale CTA, reconcile costs and retain analytics windows. |
| Extension | Append scope and cast versions without rewriting earlier approvals; plan any new daily dates, assets and recap dependencies. |

Add these tests, with explicit expected state and accounting assertions:

- **V3-AT-18:** Plan 20 and 30 complete episodes before any physical cast assets exist; no identity-lock prerequisite blocks writing.
- **V3-AT-19:** Upgrade existing V1/V2 records and approvals without deletion, hash reinterpretation or rejected historical duration values.
- **V3-AT-20:** Crash after provider acceptance and before local persistence; resume without duplicate creation, lost exposure or regenerated successful units.
- **V3-AT-21:** Concurrent workers cannot exceed step, episode or season caps; retries, shared assets and unsettled charges reconcile once.
- **V3-AT-22:** Face reroll invalidates its dependent outfits/views; unrelated selections survive; CAST LOCK cannot freeze stale descendants.
- **V3-AT-23:** Wardrobe continuity spans episode boundaries; canonical setting IDs agree; timed changes work immediately before/at/after boundaries.
- **V3-AT-24:** Over-budget reference sets preserve mandatory identity/proof assets or block; unsupported media/roles fail before dispatch.
- **V3-AT-25:** Native zero-, one- and two-speaker clips pass the production binding path; all derivatives retain speech/audio/caption synchronization.
- **V3-AT-26:** Correct speech/face with wrong wardrobe still produces a continuity finding; unavailable checks never become PASS.
- **V3-AT-27:** Run the real subscription adapter against fixture CLI outcomes: success, malformed result, missing usage, cumulative cost, refusal, timeout and unreadable quota.
- **V3-AT-28:** Competing ARISA/Drama container processes share the same lock; crash/restart cannot allow overlapping provider processes.
- **V3-AT-29:** Simulate 30 daily releases, late teaser, rejected episode, zero buffer, partial destination failure and ambiguous publication.
- **V3-AT-30:** Race amendment against job completion and publication; stale results and old approvals cannot release changed artifacts.
- **V3-AT-31:** Extend during release and after completion, including changed cast; existing published hashes and authority remain intact.
- **V3-AT-32:** Restore DB and objects together; resume scheduler/outbox/jobs without duplicate effects. Document notification ambiguity honestly.
- **Expand LIVE acceptance:** Measure representative Thai speech/identity/lipsync/continuity, A40 render-plus-QA throughput and total lease cost; separately verify caption/disclosure delivery through T032-controlled publication.

**Verdict: REWORK.**

