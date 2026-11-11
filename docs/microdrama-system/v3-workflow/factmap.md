Inspected `feat/microdrama-m0-m4` and the requested ARISA/SPECTRE sources. No writes, network calls or tests.

**WIRED** = connected to the default worker, scheduler or served UI; **CALLABLE** = implemented but requires explicit invocation; **MOCK** = default path uses fake providers/synthetic evidence; **ABSENT** = no implementation found in the inspected scope. Wiring does not establish live qualification.

References below use these roots:

| Prefix | Root |
|---|---|
| `D/` | `/root/AIVORA/drama-box/microdrama/src/microdrama/` |
| `DOC/` | `/root/AIVORA/drama-box/docs/microdrama-system/` |
| `DEP/` | `/root/AIVORA/drama-box/microdrama/deployment/` |
| `A/` | `/root/AIVORA/arisa/` |
| `S/` | `/root/AIVORA/spectre-trading/studio/` |

**1. Wardrobe and continuity state**

| Concern | Status | Existing facts and references |
|---|---|---|
| Story day/time | CALLABLE | `StoryTime` records `story_day`, `local_time` in HH:MM, descriptive `setting`, timezone defaulting to Bangkok. Each V2 scene carries it. `D/contracts/v2.py:StoryTime`, `EpisodeScene`. |
| Outfit library | CALLABLE | `WardrobeBible` belongs to season/character. Each outfit carries outfit/version, exact asset ID/version/hash, day-validity interval, setting tags and rights. `D/contracts/v2.py:WardrobeBible`, `OutfitDefinition`. |
| Assignment | CALLABLE | `assign_scene_wardrobes` assigns every visible character in every scene. Eligibility uses story day and **`scene.location_id` as the setting tag**, rather than descriptive `StoryTime.setting`. `D/references/v2_planning.py:assign_scene_wardrobes`. |
| Selection/reuse rules | CALLABLE | Scenes sort by day/scene number. On a later day, another eligible outfit is preferred; otherwise reuse requires a reason keyed by character/day/setting. Selection uses the lexicographically first eligible outfit ID and its newest version. Prior-outfit tracking is local to this invocation. Same-day selection is recalculated from eligibility. `D/references/v2_planning.py:assign_scene_wardrobes`. |
| Assignment provenance | CALLABLE | Assignment binds episode/scene/character/day/setting, exact wardrobe-bible and outfit versions, asset ID/version/hash, reuse reason and rights. Stale/mismatched assignments are rejected. `D/contracts/v2.py:SceneWardrobeAssignment`, `validate_wardrobe_assignment`. |
| Timed clothing changes | CALLABLE | `outfit_for_scene_time` resolves an `outfit_id` event during its half-open effective interval; outside an active interval it uses the scene assignment. It validates day, setting and current rights. No production caller was found. `D/references/v2_planning.py:outfit_for_scene_time`. |
| Injury, hair, makeup, dirt/wet | CALLABLE; dedicated fields ABSENT | Generic `StateValue(entity_id, field, value)` and `StateEvent` can represent these. There are no dedicated injury/hair/makeup/dirt/wet schemas or automatic state-generation routines in the inspected Drama Box code. `D/contracts/v2.py:StateValue`, `StateEvent`; `D/story/directing.py:_validate_state_values`. |
| State transitions | CALLABLE | Events bind before/after, sequence, scene, effective start/end and evidence hash. Chains reject duplicate sequences, overlapping contradictory transitions and before/after inconsistencies. Directing reconciles scene/beat input, events and output. `D/contracts/v2.py:validate_state_event_chain`; `D/story/directing.py:compile_episode_pack`. |
| Prop state/holder | CALLABLE | `PropSheet` stores purpose, visual anchor, owner, dimensions, known states and optional proof-text hash. Validation checks owner agreement with layout, scene-boundary holder/hand coverage, known state values and holder/hand consistency. `D/contracts/v2.py:PropSheet`; `D/references/v2_planning.py:validate_episode_reference_state`, `_require_scene_state_coverage`. |
| Location/time-of-day | CALLABLE | Scene story time supplies clock/day. `LocationLayout` separately stores geometry hash, entrances, camera zones, allowed light states and prop ownership. Scene boundaries must declare location light state. `D/contracts/v2.py:LocationLayout`; `D/references/v2_planning.py:_require_scene_state_coverage`, `_validate_scene_state_value`. |
| Shot state/reference resolver | CALLABLE | `resolve_shot_reference_expectations` validates pack/directing/secret/state records, resolves the shot’s scene/beat, then exact identity, scene-assigned outfit, location, style, props and explicit frame references. `D/references/v2_binding.py:resolve_shot_reference_expectations`. |
| Outfit resolver limitation | CALLABLE | The semantic shot resolver binds the **scene assignment’s asset**; it does not call `outfit_for_scene_time` to substitute a timed outfit. Generic shot states/events are included in prompt text. `D/references/v2_binding.py:resolve_shot_reference_expectations`, `compose_prompt_text`. |
| Dispatch boundary | CALLABLE | `dispatch_v2_routed_attempt` accepts typed V2 context and checks current documents/assets/rights. Default `RouterShotDispatch` uses the ordinary route; prop-bearing ordinary shots additionally invoke `build_prop_prompt_manifest`. `D/rendering/routing.py:dispatch_v2_routed_attempt`, `RouterShotDispatch`; `D/references/v2_planning.py:build_prop_prompt_manifest`. |
| Persistence/invalidation | CALLABLE | Companion records append versioned current documents to `v2_contract_documents`; exact replay returns the stored record. Dependency helpers compute transitive affected artifacts/shots. `D/references/v2_planning.py:V2ReferenceRepository.persist_companion_records`, `targeted_invalidation`; `D/story/directing.py:invalidated_shot_ids`. |
| Operator visibility/editing | WIRED display; editing ABSENT | Workbench shows wardrobe-bible outfit counts, scene/character→outfit summaries and outfit-media links; shot tables show IDs/timing. It does not expose state-event editing or full injury/holder/light timelines. `D/review/intake.py:_season_level_docs`, `_episode_workbench`; `D/review/templates/workbench.html:46`; `D/review/api.py:build_router`. |
| Default reference behavior | MOCK | Default worker calls V1 `prepare_episode`: speaking-character face/voice anchors, configured wardrobe anchors, location/style anchors and separate dialogue audio. It does not run V2 day-based wardrobe planning. `D/pipeline/handlers.py:build_handlers`; `D/references/anchors.py:plan_anchors`; `D/pipeline/world.py:build_pipeline_world`. |

**2. Rich bible and episode packs**

| Record/behavior | Status | Exact content or restriction |
|---|---|---|
| Shared V2 envelope | CALLABLE | Records carry `record_id`, `version`, `content_sha256`, `created_at`, `updated_at`, `valid_from`, optional `valid_until`, plus inherited schema version. Hashes and validity are checked. `D/contracts/v2.py:V2Record`. |
| Existing compiled bible | WIRED | `SeasonBible`: bible/season IDs, scope version/hash, canon version, Thai/English titles, logline, premise, character briefs, arc, facts, knowledge, playbook version, compilation timestamp. `D/story/models.py:SeasonBible`; `D/pipeline/handlers.py:build_handlers` → `story.compile_season`. |
| Character briefs | WIRED | `character_id`, Thai/English names, role, description, voice direction, `featured`. `D/contracts/season.py:CharacterBrief`. |
| Rich V2 bible container | CALLABLE | `RichBible` groups character-logic records, a secret ledger and a season-story ledger; it is additional to the existing `SeasonBible`. `D/story/script_maker.py:RichBible`, `generate_rich_bible`. |
| Character logic | CALLABLE | Character/season IDs, observable goal, strategy, flaw, optional secret ID, relationship pressures, `knowledge_by_episode`. `D/contracts/v2.py:CharacterLogic`. |
| Secret/reveal ledger | CALLABLE | Secret ID, holder character, fact, planned reveal episode, characters allowed knowledge. Generation rejects out-of-cast holders, out-of-season reveals and premature/unauthorized knowledge. `D/contracts/v2.py:SecretEntry`, `SecretLedger`; `D/story/script_maker.py:build_rich_bible`. |
| Season-story ledger | CALLABLE | Season ID, approved scope hash, promise, payoff debts, escalations, character-logic record IDs and secret-ledger ID. Debt: ID/description/due episode/status. Escalation: episode/description. `D/contracts/v2.py:SeasonStoryLedger`, `PayoffDebt`, `SeasonEscalation`. |
| EpisodePack top level | CALLABLE | Episode/season IDs, approved scope hash, episode number, duration target, character logic, promise, payoff debt, escalation, scenes, `scoped_map_only`. `D/contracts/v2.py:EpisodePack`. |
| Scene fields | CALLABLE | Scene ID/number, `StoryTime`, location ID, visible character IDs, prop IDs, dependency scene IDs, wardrobe-assignment IDs, beats, state-in/state-out. `D/contracts/v2.py:EpisodeScene`. |
| Beat fields | CALLABLE | Beat ID, function, visible action, proof-object IDs, dependency beat IDs, state-in/state-out, required asset IDs, reveal IDs. `D/contracts/v2.py:PackBeat`. |
| Episode cast | CALLABLE | Pack character logic must cover **every approved character**; actual scene cast is separately enumerated in `visible_character_ids`. `D/story/script_maker.py:build_episode_pack`. |
| Cliffhangers/dialogue | WIRED V1; separate from V2 pack | `ArcBeat` stores summary/planned reveals/cliffhanger. `EpisodePlan` additionally has titles, synopsis, featured cast, locations and planned beats. `Script` carries Thai dialogue and English translations. `EpisodePack` has no explicit cliffhanger or dialogue field. `D/contracts/season.py:ArcBeat`, `EpisodePlan`, `Script`, `DialogueLine`; `D/contracts/v2.py:EpisodePack`. |
| Why episodes after 3 are maps | CALLABLE | This is an explicit T039 requirement. `generate_episode_pack` hardcodes `scoped_map_only=episode_number > 3` and requests a compact outline. `first_three_and_later_map` rejects detailed later packs. `DOC/T039-brief.md:23`; `D/story/script_maker.py:generate_episode_pack`, `first_three_and_later_map`. |
| Renderability of later maps | CALLABLE | Directing rejects `scoped_map_only` packs. No later-map expansion operation was found in the service. `D/story/directing.py:compile_episode_pack`; `D/story/script_maker.py:ScriptMakerStoryService`. |
| All packs up front | ABSENT orchestration | No default handler calls rich-bible/pack generation. The service requires durable approved bible/scope, concrete available asset/prop/location/wardrobe IDs, configured LLM/prices and episode-budget reservations. Default cadence creates one next episode per daily firing; later writing requires an attached identity lock. `D/pipeline/handlers.py:build_handlers`; `D/story/script_maker.py:generate_episode_pack`, `_invoke`; `D/scheduling/service.py:_w03_episode_cadence`, `_w03_write`. |
| Requested locks | ABSENT as separate gates | Gate enum contains only `SEASON_CONCEPT` and `EPISODE_FINAL`. Current identity lock is created through episode-one Gate 2; separate Script/STORY/CAST lock actions do not exist. `D/contracts/enums.py:GateType`; `D/references/identity_lock.py:IdentityLocks.create_lock`. |

**3. Reference demand planning**

| Concern | Status | Existing facts and references |
|---|---|---|
| Demand derivation | CALLABLE | `plan_reference_demands` unions scene-visible characters, scene locations and props; outfit subjects come from supplied assignments. It adds identity **and voice** demands per visible character and one season-style subject. Exact Gate-1 scope hash is required. `D/references/v2_planning.py:plan_reference_demands`, `validate_pack_scope`. |
| Views/angles | CALLABLE | Caller supplies `view_requirements[(role, subject)]`; missing views block planning. Names are deduplicated; style always adds `moving_sample`. No fixed six-view generation or automatic camera→view inference occurs here. `D/references/v2_planning.py:plan_reference_demands`. |
| AssetSheet | CALLABLE | One sheet binds role, subject, exact asset ID/version/hash, **one `view_name`**, rights and asset-validity interval. Roles: identity, outfit, prop, location, style, voice. `D/contracts/v2.py:AssetSheet`. |
| Picking a shot’s angle | CALLABLE; automatic angle selection ABSENT | Semantic resolver requires exactly one supplied sheet per role/subject. It does not choose among several sheets using framing/view name. `D/references/v2_binding.py:resolve_shot_reference_expectations` → `one_sheet`. |
| Extras/silent visible cast | CALLABLE V2; default gap | V2 includes every scene-visible character, regardless of speech, but each must exist in approved scope. No separate anonymous-extra demand type exists. Default V1 anchor planner derives characters from dialogue speakers. `D/references/v2_planning.py:plan_reference_demands`; `D/references/anchors.py:plan_anchors`. |
| Cost/cache/rights | CALLABLE | Demands have deterministic cache keys/seeds and per-role forecast costs. Preparation validates current rights before reservation, forecasts all unique missing views and requires explicit cached-cost allocation. `D/references/v2_planning.py:demand_key`, `generate_offline_missing`, `V2ReferenceRepository.prepare_demands`. |
| Actual V2 generation | MOCK by default | Without an injected generator, missing ordinary assets contain cache-key bytes; the style moving sample is synthetic local video. This is not a live image/voice provider pipeline. `D/references/v2_planning.py:generate_offline_missing`, `make_offline_style_video`. |
| Character/prop/location variant picks | ABSENT in Drama Box | Neither the demand planner nor review router implements 2–3 variant auditions, voting, rerolling or selecting sheets. `D/references/v2_planning.py:plan_reference_demands`; `D/review/api.py:build_router`. |

**4. Workbench UI — complete `review/api.py` route inventory**

All routes below are wired by the served composition. Intake/workbench routes are conditional on an injected intake service; staging supplies it. `D/api/compose.py:build_routers`; `D/api/serve.py:_build_app`.

| Method/path | Status | Page/action and source |
|---|---|---|
| `GET /auth/login` | WIRED | Login form; issues stored, one-use sign-in CSRF token. `D/review/api.py:494`; `templates/login.html`. |
| `POST /auth/login` | WIRED | Checks matching cookie/form token, redeems it, authenticates password, sets session/CSRF cookies; redirects to seasons. `D/review/api.py:499`. |
| `POST /auth/logout` | WIRED | Revokes session, clears cookies, redirects to login. `D/review/api.py:537`. |
| `GET /ui` | WIRED | Redirects to `/ui/seasons`. `D/review/api.py:551`. |
| `GET /ui/seasons` | WIRED | Proposal cards: state, scope revision/hash, research spend, uncertainty and links. `D/review/api.py:555`; `templates/proposals.html`. |
| `GET /ui/seasons/{season_id}` | WIRED | Concept, arc/cliffhangers, cast/voice directions, destinations/cadence, policies, category budget, research evidence; Gate 1 Approve/Reject. `D/review/api.py:564`; `templates/season.html`. |
| `POST /ui/seasons/{season_id}/approval` | WIRED | Form-based Gate 1 decision bound to revision/scope hash/idempotency key. No Gate-1 Revise action. `D/review/api.py:582`; `D/review/service.py:_gate1_action`. |
| `GET /ui/intake` | WIRED | Three-page wizard: story idea; genre/tone; episode count 1–10. `D/review/api.py:319`; `templates/intake_wizard.html`. |
| `POST /ui/intake` | WIRED | Advances wizard or creates intake/season and bounded research job. Advanced production settings remain server-side. `D/review/api.py:340`; `D/review/intake.py:submit`. |
| `GET /ui/intake/{season_id}` | WIRED | Intake, research spend, blockers/jobs, candidate titles/loglines/promises/escalation, ranking/rights/originality, evidence and Gate-1 link. `D/review/api.py:406`; `templates/intake_status.html`. |
| `POST /ui/intake/{season_id}/selection` | WIRED | Selects candidate and rebinds current Gate-1 proposal using candidate ID/intake hash; records no approval. `D/review/api.py:425`; `D/review/intake.py:select`. |
| `GET /ui/seasons/{season_id}/workbench` | WIRED | Read-only arc/cast, bible summaries, sheets/wardrobe, per-episode pack/directing summaries, sections/shots, outfit links, reference-binding counts and unknowns. `D/review/api.py:464`; `templates/workbench.html`. |
| `GET /ui/episodes/{episode_id}` | WIRED | Gate-2 master/variants/hooks/covers, subtitle tables, episode-one reference package, QA/coverage, costs, release scope/policy, metadata preparation and decisions. `D/review/api.py:611`; `templates/episode.html`. |
| `POST /ui/episodes/{episode_id}/review` | WIRED | Approve & schedule, timecoded Revise, Reject. Revision returns to the smallest affected stage. `D/review/api.py:641`; `D/review/service.py:_approve`, `_revise`, `_reject`. |
| `POST /ui/episodes/{episode_id}/metadata` | WIRED | Owner enters exact per-slot metadata/policy; seals release manifest without approving. `D/review/api.py:663`; `D/review/service.py:submit_gate2_metadata`. |
| `GET /ui/seasons/{season_id}/progress` | WIRED | All existing episodes’ production/release status, accepted/required counts, plan changes, jobs/retries, QA, costs, blockers and next action. `D/review/api.py:622`; `templates/progress.html`. |
| `GET /ui/seasons/{season_id}/progress.json` | WIRED | JSON season progress projection. `D/review/api.py:293`. |
| `GET /ui/episodes/{episode_id}/progress.json` | WIRED | JSON episode progress projection. `D/review/api.py:302`. |
| `GET /ui/episodes/{episode_id}/qa-findings` | WIRED | All episode findings with QA-cycle information. `D/review/api.py:691`. |
| `GET /ui/media/{asset_id}` | WIRED | Owner-scoped private file streaming. `D/review/api.py:699`; `D/review/service.py:media_file`. |
| `GET /seasons/proposals` | WIRED | JSON owner-visible proposal summaries. `D/review/api.py:253`. |
| `GET /seasons/{season_id}` | WIRED | JSON season/scope view. `D/review/api.py:260`. |
| `POST /seasons/{season_id}/approval` | WIRED | JSON Gate-1 command. `D/review/api.py:268`. |
| `GET /episodes/{episode_id}/review` | WIRED | JSON final-review package, gate conditions and media links. `D/review/api.py:277`. |
| `POST /episodes/{episode_id}/review` | WIRED | JSON Gate-2 command. `D/review/api.py:483`. |

| UI/progress/auth concern | Status | Existing facts and references |
|---|---|---|
| Rendering technology | WIRED | FastAPI/Starlette responses; server-rendered Jinja2 with filesystem templates and HTML autoescaping. `render.py` supplies rendering and money/time/label filters; it defines no routes. `D/review/render.py:render`, `usd`, `timecode`. |
| Templates | WIRED | `base`, `login`, `proposals`, `season`, `episode`, `intake_wizard`, `intake_status`, `workbench`, `progress`. Shared inline CSS, native HTML forms/media controls; no React/Vue frontend in this surface. `D/review/render.py:TEMPLATE_DIR`; `D/review/templates/base.html:1`. |
| Checkout 1–10 stepper | ABSENT | Only intake has numbered steps 1–3 and Next buttons. Workbench/progress use sections/tables; no ten-stage navigation or per-stage progress bars. `D/review/templates/intake_wizard.html:22`; `workbench.html:1`; `progress.html:1`. |
| Progress “steps” | WIRED | `ProgressStage` is `PLANNED/RUNNING/WAITING/BLOCKED/COMPLETE`, independently projected for production and release. These are statuses, not the operator’s ten workflow stages. `D/contracts/v2.py:ProgressStage`; `D/review/progress.py:_production_stage`, `_release_stage`. |
| Denominator | WIRED | Required units = distinct directing shot IDs + distinct `(character_id, outfit_id)` pairs from current assignments. Accepted units use accepted latest render assets and accepted/locked outfit assets. Percentage is integer basis points; no usable plan yields unknown. `D/review/progress.py:ProgressProjection._work`. |
| Progress provenance | WIRED | Whole-plan fingerprint includes directing manifest and assignments; denominator changes are explained. Jobs/retries, release slots, blockers and costs remain separate. Canonical snapshot is computed only with real revision/source-event provenance. `D/review/progress.py:_plan_fingerprint`, `_denominator_basis`, `_snapshot`. |
| Owner authentication | WIRED | Scrypt passwords; PostgreSQL-backed expiring/revocable sessions; session/CSRF token digests stored. Cookies are HttpOnly, SameSite Strict, Secure configurable. No public signup route. `D/core/auth.py:AuthService`; `D/review/api.py:_set_session_cookies`, `build_router`. |
| CSRF/service refusal | WIRED | Unsafe session requests require `X-CSRF-Token` or form token. Review routes reject service bearers before reading request bodies. Login has a separate one-use token. `D/core/http.py:human_session_dependency`; `D/review/api.py:_refuse_non_human_route`; `D/review/signin.py:SignInTokenStore`. |
| Owner scope | WIRED | `season_owners` controls season/episode/media access; unauthorized resources receive not-found-style denial. Asset scope can derive through its episode. `D/review/scope.py:require_season_access`, `require_episode_access`, `require_asset_access`. |

**5. Domain and deployment**

| Concern | Status | Documented/configured facts |
|---|---|---|
| Private stack | MOCK | T046 serves the authenticated `OFFLINE_MOCK` composition; app/worker refuse live mode. Compose contains app, worker and PostgreSQL, with persistent DB/object volumes. `DOC/T046-brief.md:13`; `D/api/worker.py:main`; `DEP/compose.staging.yaml:13`. |
| Ports | WIRED configuration | Host app binding is `127.0.0.1:8093` by default → container `8000`; PostgreSQL `5432` is internal, with no host port mapping. Worker exposes no port. `DEP/compose.staging.yaml:13`, `:28`, `:52`. |
| DNS | ABSENT execution evidence | Runbook explicitly says unexecuted/operator-only: create Cloudflare record pointing to host; defer Cloudflare proxying until end-to-end TLS is confirmed. No DNS was queried here. `DEP/staging/DOMAIN-RUNBOOK.md:1`, `:21`. |
| Reverse proxy | CALLABLE runbook | Existing Coolify **Traefik** proxy; domain router/service in `/data/coolify/proxy/dynamic/`, documented upstream `127.0.0.1:8093`; internal-only middleware, owner-session authentication, no public signup. `DEP/staging/DOMAIN-RUNBOOK.md:18`. |
| TLS/cookies | CALLABLE runbook | Existing ACME resolver issues certificate; operator verifies HTTPS `/health` and certificate chain, then restarts with `MICRODRAMA_COOKIE_SECURE=1` and retests login. `DEP/staging/DOMAIN-RUNBOOK.md:28`. |
| Other operator work | CALLABLE runbook | Run restart/backup/restore drills; accept mock composition; add PostgreSQL/object volumes to backup coverage; inspect compose logs. Rollback removes domain router/DNS while private stack remains independent. `DEP/staging/DOMAIN-RUNBOOK.md:7`, `:33`, `:39`. |
| Scheduler deployment | ABSENT from staging compose | Worker drains queued jobs and sweeps janitor; it does not call `TriggerScheduler.fire`. Scheduler code expects a deployment timer, but this compose has no scheduler service. `D/api/worker.py:main`; `D/scheduling/service.py:TriggerScheduler`; `DEP/compose.staging.yaml:52`. |

**6. ARISA SFW picks**

| Concern | Status | Existing facts and references |
|---|---|---|
| Actual SFW site | WIRED | `/picks/sfw-<batch-id>/` is proxied by shared picks server to a separate SFW authority via `SFW_UPSTREAM`. Legacy picks filesystem handling does not own SFW state. `A/studio/picks/server.py:H._proxy_sfw`; `A/studio/sfw/server.py:create_handler`. |
| Variant generation | WIRED | Batch creates two anchor jobs per scene. Worker builds image request from frozen scene/reference data, calls configured image provider, writes immutable image/prompt/provenance and records candidate. `A/studio/sfw/README.md:82`; `A/studio/sfw/worker.py:run_once`; `A/studio/sfw/production.py:request_for_job`. |
| Presentation | WIRED | Image cards, selection indicators, zoom/keyboard controls, scene locks; separate anchor and final review sections. Finals show versions, approved choice and reroll progress; filters include All/To-pick/Re-roll requested. `A/studio/sfw/review.html:22`, `:125`, `:155`. |
| Vote/lock | WIRED | Vote selects one checked current anchor per scene using expected vote revision. Explicit human lock verifies all selections/hashes and enqueues finals; votes alone do not start final generation. `A/studio/sfw/store.py:Store.vote`, `Store.lock_batch`. |
| Keep/final review | WIRED | Per-candidate approve/reject with file hash, note, review revision and idempotency key. UI distinguishes kept-for-delivery choice from alternatives; global confirmation/export is separate. `A/studio/sfw/store.py:Store.review`; `A/studio/sfw/review.html:190`; `A/studio/sfw/control.py:Control.confirm`. |
| Reroll/reset behavior | WIRED | Anchor reroll clears that scene’s vote, increments revision and queues a new A/B pair; prohibited after lock. Final reroll is a separate explicit feedback request; Reject alone does not request generation. `A/studio/sfw/store.py:Store.reroll_anchor`, `Store.reroll_final`; `A/studio/sfw/review.html:190`. |
| Storage | WIRED | SQLite WAL is authoritative for batches/jobs/candidates/votes/locks/reviews; JSON outputs are projections. Media artifacts are immutable filesystem files. `A/studio/sfw/store.py:49`; `A/studio/sfw/README.md:102`; `A/studio/sfw/worker.py:run_once`. |
| Framework/reusability | CALLABLE source; Drama integration ABSENT | Standard-library `ThreadingHTTPServer`/`BaseHTTPRequestHandler`, static HTML and vanilla JS. Generic legacy pick-1-of-N site exists, but SFW implementation is coupled to scene/batch/store contracts; no Drama Box import/adapter was found. `A/studio/sfw/server.py:create_handler`, `make_server`; `A/studio/picks/README.md:6`; `D/review/api.py:build_router`. |
| Remembered reset/keep scripts | CALLABLE, **PPV** | `picks_reset.py` resets legacy file-backed votes through its HTTP API while retaining/prefixing notes. `nb_keep.py` copies selected full-resolution files/sidecars and maintains keeper/extras JSON. Neither is the SFW state authority. `A/studio/ppv/picks_reset.py:main`; `A/studio/ppv/nb_keep.py:main`. |
| Legacy vote storage | WIRED legacy site | `manifest.json`, `votes.json`, append-only `votes.log.jsonl`, images; vote body is `{slot,pick:candidate_id\|"reroll"\|null,note}`, stored with timestamp. `A/studio/picks/server.py:1`, `H.do_POST`; `A/studio/picks/README.md:12`. |

**7. SPECTRE voice audition**

| Concern | Status | Existing facts and references |
|---|---|---|
| Candidate artifacts | CALLABLE | Round-one key records eight A–H samples: four ElevenLabs multilingual-v2 and four local Kokoro voices, roughly 40–42 seconds each, with engine/model/voice/file/duration/WPM. These are not a 2–3 × 10–15-second character workflow. `S/examples/voice-audition/key.json:1`. |
| Candidate generation tools | CALLABLE | ElevenLabs script renders configured teacher/operator voices; Chatterbox script supports arbitrary owned/permitted reference audio, seed and role. No automatic audition-matrix builder or Drama Box connection was found. `S/scripts/tts_eleven.py:render`, `main`; `S/scripts/tts_chatterbox.py:main`. |
| Audition voting | CALLABLE exported record | `_about` says votes came from a Claude artifact page and were exported for agents. Round 1: collection/timestamp/first/second/note. Round 2: collection/timestamp/direction/teacher/operator/note. Round 3: collection/status. `S/examples/voice-audition/votes.json:2`. |
| Lock | CALLABLE documented/file lock | `locked` records supersession/current/source-of-truth. Current documented choices are Chatterbox `voice/teacher.wav`, `operator-clarenze.wav`, `operator-kenneth.wav`; ElevenLabs narration was retired. This is a textual/file convention, not a transactional vote→lock service. `S/examples/voice-audition/votes.json:34`; `S/brand/DESIGN.md:215`. |
| Reference merge | CALLABLE | `voice_merge.py` loudness-matches sources, finds speech runs, interleaves them with fades/gaps and emits 24-kHz mono PCM16; reports each source’s coverage in conditioning head windows. `S/scripts/voice_merge.py:speech_runs`, `split_long`, `main`. |
| Local synthesis | CALLABLE | Chatterbox-Nano CPU, reference conditioning, deterministic per-chunk seed/cache, sentence/paragraph gaps, 48-kHz stereo output; optional teacher pacing/operator FX. `S/scripts/tts_chatterbox.py:main`. |
| Drama character auditions/VOICE binding | ABSENT in inspected main | Default Drama voice preparation is fake generation. Main `ReferenceRole` lacks a VOICE role, although `AssetSheet` permits voice. Native Pika work is documented in another worktree; it is not default wiring in this checkout. `D/pipeline/world.py:build_pipeline_world`; `D/contracts/v2.py:ReferenceRole`; `DOC/HANDOFF.md:17`. |

**8. Audio, music, SFX and transitions**

| Concern | Status | Existing facts and references |
|---|---|---|
| Default mix | WIRED | EDL places separate measured dialogue assets over continuous synthetic room tone; FFmpeg trims, delays, applies gain and mixes. Rendered video’s audio is not selected by `plan_master`. `D/editing/edl.py:build_edl`; `D/editing/export.py:plan_master`, `render_room_tone`. |
| Music/SFX track models | CALLABLE schema; rendering ABSENT | `TrackKind` includes MUSIC/EFFECTS. Both master exporters only process VIDEO, DIALOGUE and AMBIENCE; no music/SFX selection, placement or ducking implementation was found. `D/contracts/enums.py:TrackKind`; `D/editing/export.py:plan_master`; `D/editing/variants.py:plan_cropped_master`. |
| Transitions | CALLABLE schema; export implementation ABSENT | CUT/CROSSFADE/FADE_FROM_BLACK/FADE_TO_BLACK and transition duration exist; EDL overlap validation understands crossfade. Exporters concatenate video and do not build fade/xfade filters. Default EDL emits cuts. `D/contracts/enums.py:TransitionKind`; `D/contracts/media.py:EdlClip`, `video_overlap_allowed_ms`; `D/editing/export.py:plan_master`. |
| Music rights | CALLABLE registry model | MUSIC is a rights-subject kind. Rights record includes route/subject/version, territories, commercial/release permission, disclosures, expiry, evidence and status. Policy setup explicitly names a voice/music license registry. `D/contracts/enums.py:RightsSubjectKind`; `D/contracts/registries.py:RightsRecord`; `D/core/registry/policy.py:SETUP_KEYS`. |
| YuE2 elsewhere | CALLABLE standalone; Drama integration ABSENT | ARISA exports `planBatch`/`runBatch` for RunPod music generation. Local YuE2 CLI supports generate/plan/decode; instrumental tooling supports prepared-score generation. No caller/import/job in Drama Box source/config was found. `A/automation/posting/music/yue2_job.js:planBatch`, `runBatch`; `/root/.claude/skills/yue2-music/scripts/run_yue2.py:main`; `/root/.claude/skills/yue2-music/instrumental/scripts/instrumental.py:generate`; `D/pipeline/handlers.py:build_handlers`. |

**9. Metadata, captions, thumbnails and teaser**

| Concern | Status | Existing facts and references |
|---|---|---|
| Caption languages | WIRED | Defaults: `th-TH`, `en-US`; Thai burn-in. Writer supplies exact Thai text and English translation. For configured non-Thai locales, current assembly still selects `text_en`; adding a locale does not translate it. `D/editing/config.py:EditingConfig`; `D/editing/service.py:EditingService._execute`; `D/story/prompts.py:WRITER_INSTRUCTION`. |
| Translation stage | MOCK writer; separate translator ABSENT | English translation is generated with script dialogue in the default fake-LLM story path. No standalone multilingual translation job exists. `D/contracts/season.py:DialogueLine`; `D/pipeline/world.py:build_pipeline_world`; `D/pipeline/handlers.py:build_handlers`. |
| Timing/verification | WIRED local; observation MOCK | Captions use actual EDL dialogue placement/measured audio, serialize UTF-8 SRT and burn via libass. Wrong observed speech produces a critical mismatch; unavailable observation remains uncertainty. `D/editing/captions.py:spot_caption_track`, `srt_bytes`; `D/editing/export.py:plan_burn`. |
| Initial social metadata | WIRED owner forms; automatic drafts ABSENT | Owner supplies title, caption, description, ≤30 hashtags, catalog links, disclosures, optional approved cover and CTA per slot. Form does not prefill generated copy. `D/review/templates/episode.html:190`; `D/review/forms.py:metadata_from_form`; `D/review/service.py:submit_gate2_metadata`. |
| Metadata before Gate 2 | WIRED | Preparation seals exact per-slot metadata/policy into release manifest; Approve binds its hash. Preparation itself creates no approval event. `D/review/service.py:_prepare_locked_manifest`; `D/review/api.py:663`. |
| Multilingual metadata/thumbnails | ABSENT automatic flow | Contracts carry per-slot locale, but default package slots use `th-TH`; no multilingual copy/thumbnail drafting stage is registered. `D/contracts/v2.py:ApprovedSlotMetadata`; `D/pipeline/packaging.py:_slot_plan`; `D/pipeline/handlers.py:build_handlers`. |
| Later hashtag optimization | WIRED | Post-publication worker deterministically appends missing approved genre/current hashtags, sorted and bounded; service applies policy/cooldown checks. This does not draft initial descriptions. `D/community/metadata_worker.py:propose_hashtag_optimization`; `D/pipeline/handlers.py:build_handlers` → `community.optimize_metadata`. |
| Cover/thumbnail | WIRED | Extracts master midpoint frame, center-cropped to destination aspect ratios. Default worker invokes cover derivation. No title-art/image-generation stage is involved. `D/editing/covers.py:plan_cover_specs`; `D/editing/variants_service.py:derive_covers`; `D/pipeline/handlers.py:build_handlers`. |
| Designed poster | CALLABLE | Inputs: accepted character/title/CTA image assets with rights, truthful approved text, output dimensions, safe/text boxes, readability PASS/evidence, reveal limit, hashes and lineage. Composites locally. `D/editing/creative_derivatives.py:PosterPlan`; `D/editing/variants_service.py:derive_poster`. |
| Episode-one preview | CALLABLE | Caller supplies EDL, exact accepted/licensed source descriptors/hashes/ranges, reveal cutoff, safe/CTA boxes and approved CTA. Maximum 90 seconds; episode 1 only; no new render. `D/editing/creative_derivatives.py:PreviewPlan`; `D/editing/variants_service.py:derive_episode_one_preview`. |
| Preview review/display | CALLABLE collection; UI gap | Media collector emits `poster`/`preview` roles and source lineage, but episode template’s playable-video filter includes master/variant/hook only. Default variants handler does not derive poster/preview. `D/editing/variants_service.py:final_review_media`; `D/review/templates/episode.html:26`; `D/pipeline/handlers.py:build_handlers`. |
| Teaser before episode 1 | ABSENT scheduling flow | Preview explicitly has `release_obligation=False`; T043 creates no publication slot. Slot kinds include PROMO_CUT/HOOK, but default packaging creates full/short slots at the demo schedule and no teaser-before-episode dependency. `D/editing/creative_derivatives.py:PreviewPlan`; `DOC/T043-brief.md:3`; `D/pipeline/packaging.py:build_release_package`; `D/contracts/enums.py:SlotKind`. |

**10. Operator-visible budgets**

| Concern | Status | Existing facts and references |
|---|---|---|
| Episode policy | WIRED | Maximum US$10/episode; default allocations: research/script/metadata $1; references/dialogue $1.50; GPU $2.50; QA/captions $1; CPU/storage/transfer $0.50; management $1; recovery $2.50. Protected shutdown reserve defaults to $0.25. `D/contracts/primitives.py:DEFAULT_BUDGET_ALLOCATION_MICRO_USD`; `D/contracts/season.py:CostPolicy`. |
| Gate-2 display | WIRED | Cap, settled, accrued, outstanding reserved, protected shutdown reserve, remaining dispatch headroom and separately labeled synthetic fake amount. Missing account displays unknown. `D/review/templates/episode.html:148`; `D/contracts/release.py:CostSummary`. |
| Detailed costs API | WIRED | `GET /episodes/{id}/costs`: summary, receipt/category/amount/basis/kind/time lines, research allocations, overruns and unsettled-expiry unknowns. `D/budget/api.py:build_router`; `D/budget/reports.py:cost_view_for_episode`. |
| Season display | WIRED partial; total ABSENT | Proposal/intake/season pages show season research spend; season page shows per-episode cap/category policy. Progress contains individual episode costs. No full-season actual/forecast aggregate or season total budget UI exists in these views. `D/review/service.py:_research_spend`; `D/review/templates/season.html:58`; `D/review/progress.py:SeasonProgressView`. |
| Season research accounting | WIRED | Separate bounded research account; costs allocate to episode accounts while retaining source charges. This is not a complete season production-budget report. `D/budget/service.py:open_research_account`, `allocate_research_cost`; `D/review/intake.py:_create_intake`. |
| Forecast versus measured production cost | CALLABLE/MOCK | V2 reference planner forecasts demand costs; default provider amounts are synthetic. Policy allocations are not measured evidence that real H3 episodes fit $10. `D/references/v2_planning.py:generate_offline_missing`; `D/budget/reports.py:_synthetic_fake_micro_usd`; `DOC/HANDOFF.md:17`. |

**11. Other modeled series concerns**

| Concern | Status | Existing facts and references |
|---|---|---|
| Runtime/production limits | WIRED | Episodes 180–300 seconds; shots ≤15 seconds; defaults ≤2 active locations, ≤3 featured speaking characters, ≤2 speakers/shot; bounded generation/transport/repair attempts. `D/contracts/primitives.py:ProductionLimits`; `D/contracts/season.py:EpisodePlan`, `CostPolicy`. |
| Hook openers | WIRED | Three 20–40-second accepted-footage recuts: payoff-first cold open, chronological tease, punch-in reaction. Each preserves payoff; candidates do not themselves create posts. Dedicated recap builder absent. `D/editing/hooks.py:1`; `D/pipeline/handlers.py:build_handlers`. |
| Canon/spoiler knowledge | WIRED V1; CALLABLE rich V2 | Planned facts remain distinct from published canon; knowledge/reveal timing and future-secret checks exist. `D/story/models.py:SeasonBible`, `KnowledgeEntry`; `D/story/script_maker.py:build_rich_bible`, `build_episode_pack`; `D/story/directing.py:_validate_secrets`. |
| Identity reuse across episodes/seasons | WIRED within season; cross-season lock reuse ABSENT | Episode-one Gate 2 locks included reviewed versions. Lock queries/memberships are season-scoped. `attach_identity_lock` exists, but newly cadence-created episodes do not receive it in their insertion path. `D/references/identity_lock.py:IdentityLocks.create_lock`; `D/references/service.py:attach_identity_lock`; `D/scheduling/service.py:_w03_episode_cadence`. |
| Rights/disclosures/consent | WIRED checks; dedicated consent record ABSENT | Versioned rights/evidence cover model/output/voice/music/font/reference/stock; release slots carry AI/synthetic-voice/sponsor/member disclosures. No dedicated person-consent form/model was found; SPECTRE cloning scripts state owned/written-permission requirements. `D/contracts/registries.py:RightsRecord`; `D/contracts/enums.py:RightsSubjectKind`, `DisclosureKind`; `S/scripts/tts_chatterbox.py:1`. |
| Actual-media QA/repair | WIRED, default content observers MOCK | Technical inspection, independent observation/comparison, findings/coverage and targeted repair jobs exist. Gate 2 displays unknown coverage and blockers; human timecoded feedback reuses repair flow. `D/pipeline/handlers.py:build_handlers`; `D/review/gate_conditions.py:finding_blocks`; `D/review/service.py:_revise`. |
| Destination capability/reconciliation | WIRED, default MOCK | Release binds account-specific capabilities, schedules, immutable media/metadata/disclosures; ambiguous outcomes reconcile rather than blindly republish. Unsupported required destinations can hold completion. `D/publishing/service.py:PublishingService`; `D/contracts/release.py:ReleaseSlotPlan`; `D/review/service.py:_capability_blockers`. |
| Membership/catalog/social management | CALLABLE services; default handlers MOCK | Early-access/public-free/withdrawn catalog states, truthful dates/prices/links, grounded community replies/moderation and bounded metadata edits are modeled. `D/memberships/catalog.py:MembershipCatalogService`; `D/community/service.py:CommunityService`; `D/pipeline/handlers.py:build_handlers`. |
| Analytics/qualification | CALLABLE; snapshot cadence WIRED | 24-hour/72-hour/seven-day performance windows; ten-episode qualification, seven-day management evidence, cost/manual-intervention checks. `D/analytics/snapshots.py:window_boundary`; `D/analytics/qualification.py:QualificationEvaluator`; `D/scheduling/registry.py:default_catalog`. |
| Operator notifications | ABSENT outbound workflow | UI exposes waiting approvals, jobs, blockers and next action; no email/Telegram/push notification sender or notification job is registered. `D/review/progress.py:EpisodeProgressView`; `D/pipeline/handlers.py:build_handlers`; `D/scheduling/registry.py:default_catalog`. |

