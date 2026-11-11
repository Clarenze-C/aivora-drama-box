# Phase B fact map — today's code (branch `feat/microdrama-m0-m4`)

Paths: `S/` = `microdrama/src/microdrama/`, `M/` = `microdrama/migrations/`, `X/` = `microdrama/tests/`. All line numbers verified today.

## 1. Season proposal today (Script Maker equivalent)

There are **two** proposal-producing paths; both write `season_proposals` rows; neither stores a "revision of the proposal text" beyond `scope_version`.

| What | Where | Facts |
|---|---|---|
| V1 research proposal | `S/research/service.py:878` `_write_proposal` | Picks a `ConceptDraft.scope`, bumps `scope_version = MAX(scope_version)+1`, inserts `season_proposals` row with `scope` jsonb, `scope_hash`, `source_provenance` (evidence docs), `research_reservation_ids`, `status='PROPOSED'`; updates `seasons.current_proposal_id/title_th/title_en/expected_episode_count`. Refuses if season no longer `PROPOSED` |
| V2 candidate drafting | `S/research/script_maker.py:274` `ScriptMakerService.generate_candidates` | LLM drafts 2–3 `ConceptCandidate`s (`SCRIPT_MAKER_INSTRUCTION` at :42: *"Return 2 or 3 materially distinct concepts"*); reserves the whole retry envelope before dispatch; returns `CandidateGenerationResult` (:150) with `candidates` + `scopes` tuples |
| Candidate ↔ proposal binding | `S/story/script_maker.py:130` `build_candidate`, :165 `rebind_candidate_to_proposal`, :88 `CandidateScopeBinding` | `ConceptCandidate.seal(..., scope_sha256=canonical_hash(scope), rights=PendingRightsAssessment(status="PENDING", ...))`; binding verifies `candidate.scope_sha256 == canonical_hash(scope)` and `episode_count == scope.expected_episode_count` |
| Intake record | `S/contracts/v2.py:166` `ConceptIntake` | `story_idea, genre_tags(min 1), tone, requested_episode_count(1–10, default 10), language="th" (Literal), original_fiction=True (Literal)`. One per season: deterministic id `uuid5(NS, f"intake:{season_id}")` (`S/review/intake.py:159`) |
| Wizard (UI entry) | `S/review/intake.py:676` `submit` → :697 `_create_intake` | One idempotent transaction: inserts `seasons` row (state `PROPOSED`, `title_th = story_idea[:200]`), links creator, seals intake, opens research account, enqueues `research.collect_and_propose` (:742) when no blockers |
| Selection | `S/review/intake.py:780` `select` | Owner picks a candidate → enqueues `research.collect_and_propose` restricted to that candidate (`trigger="owner_selection.<rev>.<candidate_id>"`, :104); replay no-op if already bound; **no approval recorded here** |
| Proposal storage | `M/0002_story_and_approvals.sql:24-38` | `season_proposals(id, season_id, scope_version>=1, scope jsonb, scope_hash ~^[0-9a-f]{64}$, status IN ('PROPOSED','APPROVED','REJECTED','SUPERSEDED'), UNIQUE(season_id, scope_version))`; trigger `season_proposals_scope_immutable` (:39) freezes `scope/scope_hash/scope_version` on UPDATE. No content-hash column other than `scope_hash`; no free-text revision history |

## 2. Gate 1 / `SEASON_CONCEPT`

| Aspect | Fact |
|---|---|
| Actions allowed | `S/contracts/states.py:122` `GATE_ACTIONS[GateType.SEASON_CONCEPT] = {APPROVE, REJECT}` — **no REVISE today**. `S/contracts/enums.py:159-169` `GateType.SEASON_CONCEPT="SEASON_CONCEPT"`; `ApprovalAction={APPROVE,REVISE,REJECT}` |
| API | `S/review/api.py:253` `GET /seasons/proposals`; :260 `GET /seasons/{season_id}`; :268 `POST /seasons/{season_id}/approval` |
| Service | `S/review/service.py:381` `decide_season`: rejects non-APPROVE/REJECT with `SchemaInvalid("Gate 1 accepts APPROVE or REJECT only")`; idempotency-wrapped |
| Precondition checks | `S/review/service.py:396-418` `_gate1_action`: season row `FOR UPDATE`; must be `PROPOSED`; open proposal with `status='PROPOSED'` required else `GateNotReady`; `command.package_hash != proposal["scope_hash"]` → `StaleRevision`; same for `expected_revision` |
| Record | `S/core/approvals.py:50` `record_approval_event` — the only writer of `approval_events`; requires human owner + live session; one decision per revision via unique index `approval_events_one_per_revision ON (gate_type, entity_id, expected_revision)` (`M/0002:208`) |
| On REJECT | `S/review/service.py:419-427`: season → `SeasonState.REJECTED`, proposal status → `REJECTED`. Season transitions table `S/contracts/states.py:22` `REJECTED: frozenset()` — terminal |
| On APPROVE | `S/review/service.py:429-469`: season → `SEASON_APPROVED` (+`approved_scope_version/hash/event`), proposal → `APPROVED`, other PROPOSED proposals → `SUPERSEDED`, then **enqueues `story.compile_season`** with `semantic_key=f"story.compile_season:{season_id}:{scope_version}"`, payload `SeasonStepInput(trigger="gate1_approved")` |
| SQL CHECKs | `M/0002:7` seasons.state enum; :20-21 approved fields must be set once approved; :184-202 `approval_events`: `gate_type IN ('SEASON_CONCEPT','EPISODE_FINAL')`, `CHECK (gate_type <> 'SEASON_CONCEPT' OR action IN ('APPROVE','REJECT'))`, `CHECK ((gate_type='SEASON_CONCEPT') = (entity_type='season'))`; session-liveness trigger :222 |
| Season state machine | `S/contracts/states.py:21-25`: `PROPOSED → {SEASON_APPROVED, REJECTED, CANCELLED}`; `(PROPOSED, SEASON_APPROVED)` and `(PROPOSED, REJECTED)` are in `SEASON_HUMAN_ONLY` (:31) |
| Revise path | **NOT FOUND.** Searched `REVISE`+`SEASON_CONCEPT`, `gate1 revise`. `ApprovalCommand._gate_rules` (`S/contracts/season.py:301-304`) allows REVISE only with feedback, but Gate 1 never reaches it |

## 3. Duration and count validators

| file:line | Field | Current rule |
|---|---|---|
| `S/contracts/primitives.py:59-67` `ProductionLimits` (= `DEFAULT_LIMITS`) | limits | `max_attempts_per_shot=3 (1-3)`, `max_final_repair_rounds=2 (0-2)`, `max_active_locations=2`, `max_featured_speaking_characters=3`, `max_speakers_per_shot=2`, `max_shot_duration_ms=15_000 (le)`, `episode_min_duration_ms=180_000`, `episode_max_duration_ms=300_000 (le)` |
| `S/contracts/primitives.py:36` | `EPISODE_CAP_MICRO_USD = 10_000_000` | US$10/episode cap |
| `S/contracts/season.py:213` `SeasonScope.expected_episode_count` | count | `PositiveInt = 10` — **no upper bound** (SQL `M/0002:15` likewise `CHECK (>=1)` only) |
| `S/contracts/season.py:214-215` | episode duration | `episode_min_duration_ms=180_000`, `episode_max_duration_ms=300_000` |
| `S/contracts/season.py:228-231` `_md002` | MD-002 | `180_000 <= min <= max <= 300_000` else `"MD-002: episodes must be 180-300 seconds"`; also arc numbers unique and ≤ expected count; duplicate character_id rejected |
| `S/contracts/season.py:329-337` `EpisodePlan._limits` | plan | target 180–300 s; ≤3 featured characters; ≤2 locations |
| `S/contracts/season.py:374-388` `Script._unique_ids` | script | unique line/scene ids; ≤3 speakers/episode; ≤2 locations/episode |
| `S/contracts/season.py:424-441` `Shot._limits` | shot | ≤15 000 ms; ≤2 speakers; `dialogue_complexity` must match speaker count (NONE/SINGLE/TWO); lines⇒speakers |
| `S/contracts/season.py:84-86` `CreativeConstraints` | caps mirror | `max_active_locations_per_episode`, `max_featured_speaking_characters_per_episode`, `max_speakers_per_shot` — each bounded to the DEFAULT_LIMITS value ("a larger value would be silently ignored, so it is rejected instead") |
| `S/contracts/v2.py:170` `ConceptIntake.requested_episode_count` | count | `Annotated[int, Strict(), Field(ge=1, le=10)] = 10` |
| `S/contracts/v2.py:183` `ConceptCandidate.episode_count` | count | `ge=1, le=10` (Strict) |
| `S/contracts/v2.py:358` `EpisodePack.duration_target_ms` | duration | `Strict, ge=180_000, le=300_000` |
| `S/contracts/v2.py:286` `StoryTime.local_time` | time | `HH:MM` pattern; `story_day: PositiveInt` |
| `S/story/script_maker.py:197-198` `_EpisodePackOutput` | writer output | `episode_number ge=1 le=10`; `duration_target_ms ge=180_000 le=300_000` |
| `S/story/script_maker.py:406-411` `build_episode_pack` | pack vs scope | pack duration must sit inside `scope.episode_min/max_duration_ms`; episode_number within scope count and must have an arc beat |
| `S/story/critics.py:121-131` | runtime critic | estimated runtime outside scope band → `complexity-runtime` REPAIRABLE |
| `S/story/prompts.py:367-375` `estimate_line_ms` | line duration | `800 + 300*len(text_th)`, clamped `1_000..14_000` ms |
| `S/story/service.py:376-381` `estimated_runtime_ms` | episode runtime | line estimates + `1_500` ms per scene |
| Recap / CTA length | **NOT FOUND** | searched `recap`, `cta`, `emotion`, `delivery` in `S/` — only publishing-metadata CTA slots exist (`S/contracts/release.py:136`), nothing in story records |

## 4. Story records

### V1 (frozen contract 1.15.0; tables in `M/0002`)

| Record | Fields / identity | Storage | Historical validation |
|---|---|---|---|
| `SeasonScope` (`S/contracts/season.py:202`) | `season_id, scope_version, source_proposal_id, ...`; hash = `canonical_hash(scope)` | `season_proposals.scope` jsonb + `seasons.approved_scope_hash` | `scope_hash` CHECK `^[0-9a-f]{64}$`; immutability trigger |
| SeasonBible (`S/story/models.py:63`) | `bible_id, season_id, scope_version, approved_scope_hash, canon_version, facts[], knowledge[]`; extends `VersionedPayload` (`schema_version` from primitives) | `canon_versions.facts = {"bible": ...}` (`kind='PLANNED'`, `facts_hash`) | `compile_season` replay path re-parses + compares `approved_scope_hash` (`S/story/service.py:519-535`); `canon_versions` is append-only via `md_forbid_mutation` (`M/0002:56`) |
| `EpisodePlan` (`S/contracts/season.py:313`) | `episode_id, season_id, approved_scope_hash, episode_number, titles, synopsis, target_duration_ms, featured_character_ids, location_ids, planned_beats, planned_reveals, cliffhanger, canon_version` | `episodes.plan` jsonb (`M/0002:71`) | plan column written only in `_persist_success` (`S/story/service.py:1407`) |
| `Script` (`S/contracts/season.py:366`) | `script_id, episode_id, version, approved_scope_hash, canon_version, scenes[Scene[DialogueLine]], estimated_runtime_ms` | `scripts.body` jsonb + `body_hash`, `status IN ('DRAFT','CRITIC_PASSED','CRITIC_FAILED','CURRENT','SUPERSEDED')`, `UNIQUE(episode_id, version)`; body immutability trigger | supersede-then-insert in `_persist_success` (:1372-1396) |
| `ShotManifest` (`S/contracts/season.py:444`) | `manifest_id, episode_id, episode_number, script_id, script_version, version, identity_lock_id, shots[]`; IMP-01 validator :467 | `shot_manifests.body` + `body_hash`, `UNIQUE(episode_id, version)`, `script_id` frozen by trigger | same supersede pattern |
| `IdentityLock` (`S/contracts/season.py:484`) | `lock_id, season_id, source_episode_id, version, approval_event_id, release_package_hash, locked_assets[]` | identity_locks table (0002) + `episodes.identity_lock_id` | created atomically by episode-one Gate 2 approval: `S/references/identity_lock.py:49` `IdentityLockHook.on_recorded`, :82 `create_lock` |
| Characters | `characters(id, season_id, character_key, name_th/en, brief jsonb, state IN ('PROVISIONAL','LOCKED','SUPERSEDED'), first_episode_number)` `M/0002:118-129`, `UNIQUE(season_id, character_key)` | rows seeded by `compile_season._seed_characters` (`S/story/service.py:656-671`) | — |

### V2 (contract package `2.15.0`; append-only documents)

| Record | Definition | ID scheme |
|---|---|---|
| Base | `S/contracts/v2.py:45` `V2Record`: `record_id, version, content_sha256, created_at, updated_at, valid_from, valid_until`; hash verified on every validate (:54-64); `seal()` computes hash (:73-82); `verify_v2_record_hash` :85 | — |
| `CharacterLogic` :190 | `character_id, season_id, observable_goal, strategy, flaw, secret_id, relationship_pressures, knowledge_by_episode` | full-bible: `uuid5(NS, f"logic:{season_id}:{character_id}")` (`S/story/script_maker.py:70`); episode snapshot: `uuid5(NS, f"episode-character:{episode_id}:{source_logic_id}")` (:75) — *"revisions advance the version, not the ID"* |
| `SecretLedger` :201 / `SecretEntry` :276 | `secrets[]`: `secret_id, held_by_character_id, fact, planned_reveal_episode, known_by_character_ids` | `uuid5(NS, f"secrets:{season_id}")` |
| `SeasonStoryLedger` :218 | `approved_scope_hash, promise, payoff_debts[PayoffDebt], escalations[SeasonEscalation], character_logic_record_ids, secret_ledger_id`; ordered/unique validators :227 | `uuid5(NS, f"season-ledger:{season_id}")` |
| `EpisodePack` :353 | `episode_id, season_id, approved_scope_hash, episode_number, duration_target_ms(180-300k), character_logic[], promise, payoff_debt, escalation, scenes[EpisodeScene], scoped_map_only` | pack: `uuid5(NS, f"episode-pack:{episode_id}")` (`S/story/script_maker.py:760`); StoryTime per scene `uuid5(NS, f"story-time:{episode_id}:{scene_id}")` (:486) |
| Other V2 story records | `StoryTime` :284, `StateValue` :291, `PackBeat` :297, `EpisodeScene` :309, `WardrobeBible` :397, `OutfitDefinition` :403, `SceneWardrobeAssignment` :421, `StateEvent` :438, `DirectingShot` :459 (`duration_ms le=15_000`), `AssetSheet` :656, `PropSheet` :681, `StyleBible` :703, `LocationLayout` :728, `ShotReferenceBinding` :754, `PromptManifest` :773 | — |
| Storage | `S/story/v2_store.py:17` `StoryV2Store` → `v2_contract_documents` (`M/0019`): append-only, `PRIMARY KEY(contract_type, record_id, version)`, one `current` row per (type,id), consecutive-version guard `S/story/v2_store.py:84-92`, hash re-verified on read :53-59; allowlist extended by `M/0020` (`SeasonStoryLedger`) and `M/0024` | payload CHECK `schema_version='2.0'` |

**Cross-record validator:** `S/contracts/v2.py:242` `validate_season_story_ledger` binds ledger ⇄ character logic ⇄ secret ledger ⇄ `approved_scope_hash` ⇄ episode count.

### Downstream consumers (direct)

| Consumer | file:function |
|---|---|
| V1 script→manifest compiler | `S/story/compiler.py:144` `compile_episode` (draft+scope+bible → EpisodePlan, Script, ShotManifest; staging simplification :119) |
| V2 pack→shots director | `S/story/directing.py:101` `compile_episode_pack` (secret validation :72 `_validate_secrets`; invalidation :418 `invalidated_shot_ids`) |
| References planning | `S/references/v2_planning.py:551` (pack-driven sheet planning), :1089, :1265 `validate_pack_scope`, :1290 (wardrobe binding) |
| References dispatch | `S/references/v2_binding.py`, `S/references/v2_dispatch_context.py` (EpisodePack consumers) |
| Rendering | `S/rendering/routing.py` (EpisodePack import; shot routing) |
| Editing | `S/editing/edl.py:82,105,192` (ShotManifest+Script→EDL); `S/editing/captions.py`; `S/editing/service.py` |
| QA | `S/qa/continuity_sources.py:76` `_current_script`, :133 (reads EpisodePack); `S/qa/coverage.py`, `S/qa/comparison.py`, `S/qa/observation.py` (script/manifest inputs) |
| Review/packaging | `S/review/packages.py`, `S/review/intake.py` (progress views read EpisodePack), `S/core/hooks.py` (approval hooks) |
| Publishing | reads release packages, not scripts directly (`S/publishing/service.py`) |
| Community grounding | `S/community/grounding.py` (script/dialogue facts for replies) |

## 5. Dialogue lines

| Model | Fields | Notes |
|---|---|---|
| `DialogueLine` `S/contracts/season.py:346` | `line_id, speaker_character_id, voice_id?, text_th (1-1000), text_en (1-1000), estimated_duration_ms, actual_duration_ms?, critical_terms[]` | **No language field beyond th/en; no emotion tag, no delivery note** (grep `emotion|delivery|text_zh` → NOT FOUND in story records). `actual_duration_ms` *"None until measured"* |
| `CriticalTerm` :340 | `kind: CriticalTermKind, value_th, value_en?` | kinds enum in `S/contracts/enums.py` |
| `RawLine` `S/story/models.py:104` | writer output: `speaker_character_id (1-120 chars), text_th, text_en, critical_terms (≤8), staging` | untrusted, parsed defensively (`S/story/service.py` `parse_writer_draft`) |
| Speaker counting per episode | `S/contracts/season.py:383-385` (≤3) + `S/story/critics.py:93-104` (`complexity-speakers`, REPAIRABLE) | |
| Speaker counting per shot | `S/contracts/season.py:428-436` (≤2 + complexity match) | V2 `DirectingShot` carries no speakers (beats do) |

## 6. Characters and identity

- **Definition today:** `CharacterBrief` (`S/contracts/season.py:65`): `character_id: Identifier, name_th, name_en, role, description, voice_direction, featured: bool = True`. The **only tiering is this boolean** — no PRINCIPAL/SUPPORTING/EXTRA (grep → NOT FOUND). V2 adds behaviour: `CharacterLogic` (goal/strategy/flaw/secrets/knowledge) and `SecretEntry`.
- **DB rows:** `characters` table PROVISIONAL→LOCKED→SUPERSEDED with `character_key` unique per season (`M/0002:118`); seeded at compile (`S/story/service.py:656`).
- **Identity locks:** `IdentityLock`/`LockedAsset` (`S/contracts/season.py:475-501`); created only by episode-one Gate 2 approval (`S/references/identity_lock.py:49,82`); enforced: later episodes refuse writing without it — `S/story/service.py:796-802` (`IdentityLockRequired`, *"IMP-01"*), `S/contracts/season.py:467` for manifests.
- **Referencing:** scenes/shots reference characters **by ID string** (`character_id: Identifier`, e.g. `known_characters = {c.character_id ...}` `S/story/critics.py:37`; pack scenes carry `visible_character_ids` `S/contracts/v2.py:314`). Voice binding via `voices` table (`M/0002:131+`) and `DialogueLine.voice_id`.

## 7. Episode row creation

| Site | Fact |
|---|---|
| `S/pipeline/runner.py:290` `create_episode` | *"No module owns episode creation (the cadence trigger is configuration); the runner performs it"* — inserts `state='PLANNED'`, `episode_number = count+1`, `approved_scope_hash` from season |
| `S/scheduling/service.py:199` `_w03_episode_cadence` | The cadence owner: daily schedule `w03-episode-cadence` (`S/scheduling/registry.py:81`, `timedelta(days=1)`), creates next PLANNED episode while `count < scope.expected_episode_count` for every `SEASON_APPROVED` season; idempotent via `UNIQUE(season_id, episode_number)` |
| Coupling to release cadence | **None at creation.** `ReleaseCadence` (`S/contracts/season.py:145`: ISO weekdays + HH:MM times, `Asia/Bangkok`) is consumed only at publishing/slot time — grep `release_cadence` outside `contracts/` → NOT FOUND. Scheduling catalog is a fixed W01–W12 list, not cadence-derived |
| Initial state | `PLANNED`; transitions `PLANNED→SCRIPTING→REFERENCES→RENDERING→ASSEMBLING→AI_REVIEW→AWAITING_FINAL_REVIEW→RELEASE_APPROVED→SCHEDULED→PUBLISHING→PUBLISHED_VERIFIED→MANAGED` (`S/contracts/states.py:35-50`; SQL CHECK `M/0002:63-65`) |
| V3 target ("all planned rows at STORY LOCK") | does not exist today — **NOT FOUND** (`STORY_LOCK`, `CAST_LOCK` in `S/` → no hits) |

## 8. Critics (running today)

| Critic | Input | Failure behaviour |
|---|---|---|
| Deterministic draft critic | `S/story/critics.py:26` `check_draft(draft, scope, bible, episode_number, estimated_runtime_ms, limits)` | Findings typed `BLOCKED` (unknown speaker, translation missing, critical-term missing, premature reveal :143) vs `REPAIRABLE` (speakers, locations, runtime). Runs in-process every round; *"cannot be waived by a green model score"* (`S/story/service.py` module docstring) |
| Paid semantic critic | `S/story/service.py` `_critic_attempt` (op `CRITIC_OPERATION = "story.critic"` :107, instruction `S/story/prompts.py:36`, model ref `story-critic`, schema `CRITIC_OUTPUT_SCHEMA`) | Verdict parsed by `parse_critic_verdict`; failure consumes budget; bounded by `max_rewrite_rounds` → `WriteStatus.CRITIC_FAILED` with spend retained (MD-008) |
| V2 pack/bible validation | `build_rich_bible` / `build_episode_pack` (`S/story/script_maker.py:249,378`) + `validate_season_story_ledger` | Pure validators — raise `ValueError`/`Conflict`; the writer retries up to `writer_max_attempts`, else `status="FAILED"` (`ScriptMakerStoryResult` :215). Secret-leak check: unrevealed secret fact (≥20 normalized chars) appearing in pack text → reject (:540-546); prompt redaction `_redact_text` :644 |
| Season critic | **NOT FOUND** (v3-only concept; grep `season critic` → spec only) | |

## 9. Research (Mode A equivalent)

- `S/research/service.py:313` `ResearchService.run_research(season_id, request)` — bounded pipeline: `_plan` (prospective per-call worst case) → `_search_once` per query (`SEARCH_OPERATION = "research.source_search"` :108) → `_synthesize_notes` (LLM, `LLM_INSTRUCTION` :110: *"research note-taker … list explicit uncertainty notes"*) → `_rank` → `_write_proposal`.
- `ResearchConfig` (:124): `max_queries_per_run=8`, `max_results_per_query=20`, `llm_max_attempts=2`, token/timeout bounds, price quotes — *"a missing price means the step cannot dispatch (typed UNKNOWN, zero spend)"*.
- **Sources:** `S/research/sources.py:45` `_record_for` — fake providers enabled only in `OFFLINE_MOCK`; **live providers are registry/config-driven and hard-disabled** (`disabled_reason=_LIVE_DISABLED_REASON`; *"No real HTTP exists here by design"*). Only `FakeSourceProvider` exists (`S/testing/fakes/sources.py:39`, `provider_id="fake-sources"`). Originality/dedupe: `S/research/originality.py`, `S/research/dedupe.py`.
- **V1 entry points:** job `research.collect_and_propose` (`S/contracts/jobs.py:72`, API-enqueueable :270; scheduled weekly `w01-research` `S/scheduling/registry.py:66`); handler is `S/review/intake.py:1013+` which composes `ScriptMakerService.generate_candidates` (:1076) → `ResearchService.run_research` (:1102).

## 10. LLM plumbing today

- **Protocol:** `S/contracts/providers.py:152` `class LLMProvider(Protocol): provider_id: str; def generate(self, request: LLMRequest) -> LLMResponse: ...` (synchronous, single method). `LLMRequest` :127: `request_id, role: RuntimeRole, model_config_ref, instruction, untrusted_documents, output_schema, max_input/output_tokens, client_token, reservation_id`.
- **Fake:** `S/testing/fakes/llm.py:77` `FakeLLMProvider` (`provider_id="fake-llm"`), schema-driven `synthesize` (:42) + `malform` (:63) + `LLMScenario` (:35); self-books usage receipts against `RESEARCH_SCRIPT_PROMPTS_METADATA`.
- **Models for story work:** model ids are config; only `model_config_ref` strings are pinned: `story-architect` (writer, V2 bible, V2 pack), `story-critic` (`S/story/prompts.py:19-24`). Roles: `RuntimeRole.STORY_ARCHITECT` used in dispatch (`S/story/script_maker.py:1046`).
- **Dispatch + spend pattern (both services):** check provider/price/mode gates (`OFFLINE_MOCK` requires `fake-llm`; live requires `EffectKind.PAID_REQUEST` — `S/story/script_maker.py:977-984`) → reserve worst case per attempt (`BudgetService.reserve`, category `RESEARCH_SCRIPT_PROMPTS_METADATA`, queue `PRODUCTION`) → `llm.generate` with transport retries on `TransientProviderError` → `record_usage` per receipt → parse+validate → release unused holds. See `S/story/script_maker.py:965-1087` `_invoke` and the V1 equivalent in `S/story/service.py:_plan_calls/_reserve/_call_llm`.
- **Parsing/validation:** outputs are plain dicts validated by pydantic models (`WriterDraft`, `CriticVerdict`, `_RichBibleOutput`, `_EpisodePackOutput`, `_CandidateOutput`); instruction text is module constants; all data travels as `untrusted_documents` (injection tests `X/unit/research/test_injection_resistance.py`).
- **V3 LlmStep (gateway) does not exist yet in this branch** — spec §10.1; the phase-A0 build brief targets it. Code search for `LlmStep` in `S/` → NOT FOUND.

## 11. Contracts

| Fact | Location |
|---|---|
| Contract package version on branch | `S/contracts/__init__.py:3` `CONTRACT_VERSION = "2.15.0"`; generated `microdrama/contracts/VERSION` = `2.15.0` |
| Legacy V1 version | `S/contracts/build.py:39` `LEGACY_CONTRACT_VERSION = "1.15.0"` — V1 models (SeasonScope, EpisodePlan, Script, ShotManifest, IdentityLock…) are frozen at 1.15.0; module-local story payloads extend them instead ("Contracts are frozen at 1.5.0" docstring in `S/story/models.py:1` predates the bump) |
| Generation | `S/contracts/build.py:103` `render()` writes `microdrama/contracts/schemas/{v1,v2}/<Model>.schema.json`, `examples/{v1,v2}/valid|invalid/…`, `manifest.json` with canonical hashes + `json_schema_rejects`; `--check` fails on drift. Artifacts exist: `microdrama/contracts/schemas/v1/{SeasonScope,EpisodePlan,Script,ShotManifest,IdentityLock}.schema.json`, `schemas/v2/{ConceptIntake,ConceptCandidate,CharacterLogic,EpisodePack,SeasonStoryLedger,…}.schema.json` |
| Model registry | `S/contracts/registry.py` `ALL_MODELS`, `CORE_PAYLOADS` |
| Pinning tests | `X/contract/contracts/test_generated_contracts.py` (drift + schema validity), `test_v2_contracts.py` (22.6K), `test_conventions.py`, `test_hashing.py`; `X/contract/story/test_story_contract.py` + `story_contract_support.py` |

## 12. V1 tests that pin story behaviour (would break on change)

| Area | Tests |
|---|---|
| Story core | `X/unit/story/`: `test_compile_season.py`, `test_write_episode.py`, `test_canon_and_complexity.py`, `test_critic_and_rewrite.py`, `test_concurrency_and_claims.py`, `test_dialogue_prop_routing.py`, `test_prompts.py`, `test_staging_simplification.py`, `test_story_budget_binding.py`, `test_story_research_attribution.py`, shared `story_support.py` (15K) |
| V2 packs/bible | `X/unit/story/test_v2_story_packs.py` (46.7K — the big V2 pin) |
| Research / candidates | `X/unit/research/`: `test_script_maker.py` (11.6K), `test_run_lifecycle.py`, `test_originality.py`, `test_citations_and_ledger.py`, `test_budget_binding.py`, `test_unknowns.py`, `test_injection_resistance.py` |
| Gate 1 / intake | `X/unit/review/test_gate1.py`, `test_intake_ui.py` (37.3K), `test_owner_scope.py`, `test_http.py`, `test_gate_conditions.py` |
| Contracts | `X/contract/contracts/*` (above) + `X/contract/story/test_story_contract.py` |
| Pipeline/cadence | `X/unit/pipeline/` (runner W01–W03), `X/unit/workers/`, `X/integration/` |
| State machine / SQL | `X/contract/contracts/test_states_routes_jobs.py`; SQL CHECKs exercised via review/story tests against a real DB (conftest) |

## Cross-cutting notes for the spec (facts, not recommendations)

- `SeasonScope.expected_episode_count` has **no upper bound** (pydantic `PositiveInt`, SQL `>=1`); the 1–10 caps live only on `ConceptIntake`/`ConceptCandidate` and `_EpisodePackOutput.episode_number` (`le=10`). V3's 20–30 has no precedent in validators.
- Gate 1 has no REVISE anywhere (enum supports it; `GATE_ACTIONS` and `decide_season` exclude it; SQL CHECK :201 excludes it).
- `episodes` rows are created **outside** any story module, today only by cadence config (`_w03_episode_cadence`) or the integrator runner — both bind `approved_scope_hash` at insert.
- Dialogue has no recap, CTA, emotion, delivery or ZH fields; duration is a deterministic estimate until voice synthesis fills `actual_duration_ms`.
- Historical-record validation today = schema-versioned payload + content hash re-verified on read (V2) and immutability triggers + hash columns (V1); there is no "validate under the record's own schema version" mechanism for V1 rows (`schema_version` column default `'1.0'` is stored but no version-dispatch reader exists — V2 has `read_v1_manifest` as the only compatibility reader, `S/contracts/v2.py:1029-1053`).

## Files read

`S/story/models.py`, `S/story/service.py`, `S/story/script_maker.py`, `S/story/critics.py`, `S/story/prompts.py`, `S/story/v2_store.py`, `S/story/compiler.py` + `S/story/directing.py` (signatures), `S/contracts/season.py`, `S/contracts/v2.py`, `S/contracts/jobs.py`, `S/contracts/states.py`, `S/contracts/enums.py` (gate section), `S/contracts/primitives.py` (limits), `S/contracts/providers.py` (protocol), `S/contracts/build.py`, `S/contracts/__init__.py`, `S/core/approvals.py`, `S/review/api.py`, `S/review/service.py`, `S/review/intake.py`, `S/research/service.py`, `S/research/script_maker.py`, `S/research/sources.py`, `S/references/identity_lock.py` + `v2_planning.py` (signatures), `S/qa/continuity_sources.py`, `S/editing/edl.py`, `S/scheduling/service.py` + `registry.py`, `S/pipeline/runner.py`, `S/testing/fakes/llm.py` + `sources.py`, `M/0002`, `M/0019`, `M/0020`, `M/0024`, `.scratch/t031-gate-h2/microdrama/migrations/0026*`, `docs/microdrama-system/v3-workflow/SPEC-v3.md` §4.1–4.3, §10.1, §13; directory listings of `microdrama/contracts/`, `X/unit/story|research|review`, `X/contract`.
