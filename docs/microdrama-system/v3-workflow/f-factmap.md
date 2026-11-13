# Phase F fact map — drama-box @ `feat/microdrama-m0-m4`, 2026-11-13

Paths: `S/` = `microdrama/src/microdrama/`, `M/` = `microdrama/migrations/`, SPEC = `docs/microdrama-system/v3-workflow/SPEC-v3.md`. `M/` ends at 0025; `0026_t031_benchmark_experiments.sql` and `0027_a0_llm_gateway.sql` exist only under `.scratch/a0d-gate/microdrama/migrations/`.

## 1. Metadata and thumbnails today

| Thing | Fact | Cite |
|---|---|---|
| Per-slot metadata record | `PostMetadata`: locale, title(≤200), caption/description(≤5000), hashtags(≤30), cover triple (id/version/sha256), cta_text, links, disclosures(min 1), catalog_version | `S/contracts/release.py:362-374` |
| Approved (Gate-2) metadata | `ApprovedSlotMetadata`: metadata_id+version, content_sha256, cover + `cover_rights`, `source: Literal["OWNER_APPROVED","OFFLINE_MOCK","EXAMPLE"]` | `S/contracts/v2.py:843-865` |
| Storage | `metadata_versions` append-only, content trigger-immutable, no delete; `platform_posts.current_metadata_version_id` names current | `M/0005:82-99`, `M/0005:66` |
| Edit surface | Gate 2 only today: `POST /ui/episodes/{id}/metadata` — "Owner-supplied Gate 2 release metadata: seal the V2 manifest, decide nothing" | `S/review/api.py:663-681`; service store `S/review/service.py:1020-1077`; forms `Gate2CoverChoice/Gate2SlotForm/Gate2MetadataForm` `S/review/forms.py:110,127,142` |
| Post-approval edits | new append-only version; `SUBSTANTIVE_FIELDS = ("title","caption","description","hashtags","cover_asset_id","links","disclosures")`; rollback = new version with `rollback_of` | `S/publishing/metadata.py:29-37,78-140` |
| Edit policy | `ApprovedMetadataPolicy`: `mutable_fields ⊆ {title,caption,description,hashtags,cover,cta}`, `cooldown_hours ≥ 24`, `max_substantive_edits_first_7_days ≤ 2`, `allow_unapproved_content_changes = False` | `S/contracts/v2.py:816-825` |
| Thumbnail concept/pick | Cover asset binding only (exact id/version/sha + rights, re-checked at submit, `S/publishing/service.py:467-501`). **NOT FOUND**: `ThumbnailCandidate`, key-art variants, pick workflow. Search terms: `thumbnail`, `ThumbnailCandidate`, `key_art` — only adapter readback fields (`S/publishing/youtube/adapter.py:246`, `capabilities.py:96-97` "documented custom thumbnail set (COVER_UPDATE)") and `S/core/registry/policy.py:437` |

## 2. Gate 2 today

- Only two gate types: `SEASON_CONCEPT = "SEASON_CONCEPT"  # Gate 1`, `EPISODE_FINAL = "EPISODE_FINAL"  # Gate 2` — `S/contracts/enums.py:159-161`. No `TEASER_FINAL`/`LAUNCH` (grep zero).
- Records: `approval_events` with `expected_revision`, `package_hash`, `media_hashes`, `management_policy_hash`, `release_scope_hash`; `UNIQUE (gate_type, entity_id, expected_revision)` "One decision per entity revision"; append-only; insert requires a live human owner session — `M/0002:181-232`.
- V2 binding (T037): `approval_events.release_manifest_hash` (nullable 64-hex) — `M/0021:3-5`; tables `approved_slot_metadata` (PK (metadata_id, version), unique `is_current` per package+slot, immutable/no-delete) and `release_approval_manifests` (PK manifest_hash) — `M/0021:7-48`; DB trigger `md_gate2_manifest_binding`: "only Gate 2 APPROVE can bind a release manifest" and validates manifest↔package — `M/0021:50-79`.
- Approver binding: `actor_owner_id` + `actor_session_id` (human session trigger); service entry `decide_episode` → `require_human_owner(principal)` — `S/review/service.py:1078-1082`.
- What it approves: hashes. `_check_binding` compares command's package_hash/media_hashes/management_policy_hash/release_scope_hash to the current stored package, else `StaleRevision` — `S/review/service.py:1092-1122`; `expected_revision` vs episode row — `review/service.py:1134-1139`. Live approve requires the manifest ("live Gate 2 approval requires a V2 release manifest"); OFFLINE_MOCK exempt — `review/service.py:1145-1148`; manifest must cover every current slot with exact (metadata_id, version, content_sha256) — `review/service.py:1170-1188`.
- On APPROVE: `gate2_blockers` must be empty (state `AWAITING_FINAL_REVIEW`, READY current package, no blocking QA findings, per-asset hash + persisted-object verification, policy hash vs approved season scope, no live pod leases) — `S/review/gate_conditions.py:118-190`; DB CHECK `status <> 'APPROVED' OR (approval_event_id IS NOT NULL AND jsonb_array_length(gate_blockers) = 0)` + one-approved-per-episode index — `M/0005:26-30,40-42`; caption guard "Gate 2 approval refused: a current caption track is not aligned to actual audio" — `M/0008:24-34`; ep 1 needs identity-lock hook — `review/service.py:1204-1205`. Episode state transitions gated on `EPISODE_FINAL` — `S/core/state_machine.py:276,287,359`.

## 3. Teaser

**NOT FOUND in code.** Searches: `teaser` (src, migrations — zero), `TEASER` case-insensitive (zero), `premiere` (only a fixture string "operator moved the premiere" — `X/unit/memberships/test_membership_catalog_transitions.py:121`). Requirement anchors: SPEC §4.10:502-508 (`TEASER_FINAL` gate, `PROMO_CUT` at premiere − 3 days, PreviewPlan → season teaser contract). `SlotKind.PROMO_CUT` exists — `S/contracts/enums.py:430-434`.

## 4. Release slots and calendar

| Thing | Fact | Cite |
|---|---|---|
| Slot identity | `ReleaseSlotKey` "(series, episode, part, locale, platform, account, slot)"; `dedupe_key = canonical_hash(self)` | `S/contracts/release.py:63-76` |
| Plan | `ReleaseSlotPlan`: slot, slot_kind, required, asset_id+sha256, **`schedule: ScheduleInstant`**, `depends_on` ("dedupe_keys that must be PUBLISHED_VERIFIED first"), disclosures ≥1 (MD-015 AI disclosure mandatory, MD-018 no sponsored), capability pin | `S/contracts/release.py:79-101` |
| Package | `ReleasePackage` "What Gate 2 reviews. ``package_hash`` covers every immutable field."; media ≥1, `caption_track_ids` ≥1, `release_scope` ≥1, hash excludes package_hash/gate_blockers/cost; IMP-01 ep-1 cast package | `S/contracts/release.py:265-359` |
| Schedule job | `schedule_release`: locks episode `FOR UPDATE`, needs APPROVED package + approval event, revalidates DAG, one `platform_posts` row per plan (state SCHEDULED), episode RELEASE_APPROVED→SCHEDULED same tx; replay idempotent; different package = Conflict | `S/publishing/slots.py:117-223` |
| Uniqueness | DB `UNIQUE (series_id, episode_id, part, locale, platform, account_ref, release_slot)`; `dedupe_key UNIQUE` | `M/0005:32-78` |
| Date storage/versioning | Pinned at schedule time: `iana_zone`, `local_time`, `scheduled_utc`; key columns trigger-immutable | `M/0005:54-56,80-81` |
| Calendar record | **NOT FOUND**: `calendar`, `ReleaseCalendar`, `reschedule`, `LAUNCH`, `EXTENDING` — zero hits in src+migrations. SPEC §9.2:603 "today `ReleaseSlotPlan` requires a schedule" | — |
| Slot kinds/platforms | `FULL_EPISODE/PART/PROMO_CUT/HOOK`; demo packaging: YT+FB FULL_EPISODE (YT required), TT+IG PROMO_CUT (optional), th-TH, fixed demo schedule | `enums.py:430-434`; `S/pipeline/packaging.py:150-189` |

## 5. Publication workers (M3 wave, today)

- Protocol: `PublisherAdapter` — `capability / submit / status / reconcile / update_metadata / readback` — `S/contracts/providers.py:415-433`. Adapters per platform in `S/publishing/{youtube,tiktok,facebook,instagram}/`.
- Submit is 3-phase, crash-safe: validate + `provider_ops.begin` "committed BEFORE any external call" → adapter call outside tx → outcome tx. `PUBLISH_DEADLINE_MS = 300_000`, `MAX_SUBMIT_ATTEMPTS = 3`, `REQUIRED_VERIFY_FIELDS = ("visibility", "disclosures")` — `S/publishing/service.py:309-339,81-85`.
- Pre-submit checks: command names the slot's package (id+hash) + approval event; asset hash equals pinned hash; client_token match — `service.py:368-384`; live mode requires full V2 binding vs `release_manifest_hash` — `service.py:386-455`; catalog version and links restricted to current catalog URLs — `service.py:502-513`; metadata must be exactly current version — `service.py:519-554`; stored object re-hashed — `service.py:559-565`.
- Disclosure/capability gates: `HeldSlot` — "A destination blocker (capability/rights): the slot HELDs, the episode does not fail" — `service.py:101-102`; HELD codes `CAPABILITY_STALE`, `CAPABILITY_UNAVAILABLE`, `UNSUPPORTED_DISCLOSURE` — `service.py:610-647`; mock-label metadata forbidden on live routes — `service.py:616-627`.
- Dependencies: `_check_dependencies` — every `depends_on` must be `PUBLISHED_VERIFIED` with external_id, else PolicyDenied "dependency is not PUBLISHED_VERIFIED yet; this slot waits" — `service.py:654-668`.
- Failure paths: HELD (idempotent replay) `service.py:672-684`; RATE_LIMITED → RETRY_WAIT, attempt+1 `service.py:686-715`; ambiguous → NEEDS_RECONCILIATION `service.py:717-723`; `retry_held_slot`: "HELD -> SCHEDULED, but only when the destination checks now pass" `service.py:1060-1068`; `cancel_slot` `service.py:1045`.
- Readback verification: `_readback_verifies` — visible True, declared disclosures ⊆ `disclosures_visible`, no required field in `unverified_fields` — `service.py:894-900`; DB `CHECK (state <> 'PUBLISHED_VERIFIED' OR (external_id IS NOT NULL AND verified_at IS NOT NULL))` — `M/0005:79`.
- Episode completion: `SCHEDULED→PUBLISHING→PUBLISHED_VERIFIED` once no required slot is open — `service.py:902-943`.
- Reconcile: adopt found post by external id (unique per platform+account — `M/0005:76`) vs "re-arm only a proven-absent one" (same client token, capped) — `service.py:947-980`; token = hash(dedupe_key, package_hash) — `S/publishing/slots.py:48-50`.
- Per-destination failure view: `release_view` returns per-slot state/blockers, `full_release_ready` — `service.py:1072-1117`. **No `PARTIAL` slot state exists** (`M/0005:50-53`); "PARTIAL" is SPEC language only (§9.3:613).
- Platform readback facts: TikTok `unverified = ["subtitles_present", "thumbnail", "comment_settings"]` — `tiktok/adapter.py:379`; FB `unverified = ["privacy", "subtitles_present"]` — `facebook/adapter.py:354`; IG `READBACK_UNVERIFIED_FIELDS = ("disclosures", "privacy", "subtitles_present", "cover")` + caption length cap + REELS routing — `instagram/adapter.py:74,83-85,170-191`; YT `unverified_fields=["thumbnail", "category"]` — `youtube/adapter.py:246`.

## 6. Scheduler and outbox

- Registry replaces n8n: "The declarative W01–W12 schedule registry (T029; replaces the n8n exports)"; firing = pure function of (registry, now); semantic key `sched:<id>:<bucket>` makes double-fire a no-op — `S/scheduling/registry.py:5-19,38-45`. 14 schedules; publication-relevant: `w09-publish-submit` (5 min, "Submit due SCHEDULED slots whose dependencies are verified"), `w09-publish-poll` (5 min), `w11-analytics` (1 h), `w12-*` janitors (10 min) — `registry.py:65-155`.
- W09 submit discovery: `scheduled_utc <= now`, state SCHEDULED (or stuck SUBMITTED attempt>1), no other pending `publish.submit_slot` job for the slot; deps-verified check; builds command via `publication_command_for_post` with live binding from `approved_live_binding` (OFFLINE_MOCK exempt) — `S/scheduling/service.py:538-628`; binding loader `S/publishing/metadata.py:173-219`.
- W09 poll: SUBMITTED/PROCESSING with external_id and stale `updated_at` → poll/reconcile — `scheduling/service.py:630-676`.
- Durable jobs: `jobs` table — queues `('production','publication','community')`, `semantic_key UNIQUE`, lease/heartbeat, `run_after`, `max_attempts ≤ 10`, identity columns immutable — `M/0001:72-108`. Worker runtime `_throttle` → shared-bucket admission, denial = RetryLater RATE_LIMITED — `S/workers/runtime.py:259-283`.
- Rate limit: `rate_limit_buckets` one row per provider+account, milli-token bucket, shared across processes — `M/0018:1-21`; "A denial is a wait, never a bypass" — `S/workers/limiter.py:11-15`; PG-backed limiter `S/workers/pg_limiter.py`.
- Outbox: transactional outbox (domain_events/dispatch/consumption tables) — `M/0001:115-148`; `append_event` inside tx — `S/core/events.py:82`; consumer dedupe `consume_once` — `events.py:237`; janitors sweep independently — `S/workers/janitor.py:74-91`.

## 7. Amendment vs job vs publication race surfaces (existing fencing a V3C-26 extension / reschedule must respect)

| Surface | Fence | Cite |
|---|---|---|
| Approval | one decision per (gate, entity, expected_revision); hash equality vs current package; episode revision check | `M/0002:226-227`; `S/review/service.py:1092-1143` |
| Package | content columns trigger-immutable; one APPROVED per episode; APPROVED ⇒ approval event + no blockers | `M/0005:21-30,40-42` |
| Manifest/slot metadata | append-only, payload↔indexed-identity binding triggers, `is_current` unique | `M/0021:30-48,81-99` |
| Slot | key columns + package/approval/asset/client_token trigger-pinned; media re-hashed at submit | `M/0005:80-81`; `S/publishing/service.py:559-565` |
| Metadata | append-only versions, current-pointer flip under `update_with_revision` | `S/publishing/metadata.py:115-139` |
| Live submit | manifest id/version + approved metadata (version, sha256) + policy triple must equal current rows; `validate_live_release_metadata` fail-closed | `S/publishing/service.py:434-455`; `S/contracts/v2.py:940-965` |
| Jobs | `jobs` identity (job_type/semantic_key/input) immutable; semantic_key unique enqueue | `M/0001:105-107` |
| Dependency recording | only slot-level `depends_on` (same scope, shape-checked DAG, acyclicity) — nothing records a calendar/date-revision dependency | `S/contracts/release.py:86-88`; `S/publishing/slots.py:53-93` |
| Amendment / calendar revision | **NOT FOUND** — `amendment`, `calendar`, `reschedule`: zero hits in src+migrations | — |

## 8. Buffer/premiere rules

- Code: "5 approved episodes", "teaser at premiere − 3", "predecessor slot per destination": **NOT FOUND**. "buffer" appears once as a description — "Daily cadence check: write the next episode inside the buffer rules." — `S/scheduling/registry.py:91-94`; the actual W03 write gates are approved-scope count + ep-1 identity lock (`e.episode_number = 1 OR e.identity_lock_id IS NOT NULL`) — `S/scheduling/service.py:199-257`.
- Nearest existing analog: membership free-date truth — the frozen announced instant can never silently move; moving requires `FreeDateOwnerDecision` → new catalog version + `membership.free_date_changed` outbox event — `S/memberships/catalog.py:25-32,77-82`.
- SPEC anchors for phase F: §9.2:590-604 (premiere 19:00 Asia/Bangkok, teaser at premiere−3, LAUNCH binds calendar revision + first five consecutive episodes and the teaser, dispatch needs content+calendar authority, reschedule rebuilds date-bearing content, published media immutable); §9.3:606-614 (teaser gates premiere, predecessor-per-destination, HELD successors, PARTIAL, never duplicate a post); §9.4:616-624 (≥1.25 approved episodes/day, catch-up ≥2/day×2d, buffer ≥3 days alert below 2); V3-AT-12 — SPEC:903.

## 9. Caption tracks

- `CaptionTrack` (episode, version, locale, timing_source, `derived_from_audio_sha256`, cues) + `CaptionCue` — `S/contracts/media.py:176-212`; table `caption_tracks`, one CURRENT per (episode, locale), body immutable — `M/0004:71-88`; Gate 2 refuses if package tracks not CURRENT/actual-audio-aligned — `M/0008:24-34`.
- Delivery: YouTube has `upload_captions` — "Documented captions surface for the T029/T025 integration; **NOT part of submit**. A PublicationCommand carries no caption payload" — `S/publishing/youtube/adapter.py:250-258` (`CaptionUploadRequest`/`CaptionResource` — `youtube/transport.py:131,140`). TikTok/Facebook/Instagram: no caption upload; `subtitles_present` is readback-unverified/None — `tiktok/adapter.py:379-389`, `facebook/adapter.py:354-362`, `instagram/adapter.py:74,318`. Burned-in: subtitle safe-zone boxes exist (`release.py:157-180`; examples `subtitle_safe_top_bp` — `examples.py:552-553`) but no burned-in variant seam. O-8 (EN/ZH upload vs burned-in) unimplemented — SPEC §9.1:584-586.

## 10. Throughput (MA11)

**NOT FOUND.** `throughput` and `MA11`: zero hits in src, migrations, tests. Nearest surfaces: `performance_snapshots` append-only per post+window (H24/H72/D7) — `M/0005:204-227`; analytics read-only joins — `S/analytics/ledger.py:3,114,268`; `qualification_runs` — `M/0005:227+`; W11 "Record due 24h/72h/7d windows" — `S/scheduling/registry.py:146-149`. No approved-episodes/day counter exists.

## 11. Gaps — phase F needs with nothing there today

1. `TEASER_FINAL` / `LAUNCH` (and STORY_LOCK/CAST_LOCK per SPEC §13:837) — `GateType` has exactly 2 values.
2. Teaser contract + teaser slot at premiere−3d + "episode 1 depends on verified teaser publication" (§9.3) — zero teaser code.
3. `ReleaseCalendar` record, calendar versioning, LAUNCH binding, reschedule path — schedule is a frozen per-slot `ScheduleInstant`; `schedule_release` is replay-only, a date change requires a new package.
4. `MetadataDraft` + Gate-2 prefill — metadata exists only from the Gate-2 form / deterministic v1 at first submit; no draft state.
5. `ThumbnailCandidate` key-art variants + composite + operator pick — only the cover binding and documented COVER_UPDATE capability.
6. Amendment coordinator + revision fencing + `ExtensionScope` (V3C-26/V3C-27) — no amendment code; extension fence today = hash equality + immutable rows (§7).
7. `PARTIAL` slot/episode state + per-destination partial summary (§9.3) — states enum has no PARTIAL; `release_view` approximates with a blockers list.
8. Successor holding on rejection near air time (§9.3:611) — `depends_on` is checked only at submit; no propagation of holds to dependents.
9. MA11 throughput measurement + buffer counter + bot alerts (§9.3/9.4) — no counters, no alerting consumer found for release events.
10. Calendar-revision dependency recording on date-bearing content (§9.2:593) — nothing exists.
11. O-8 EN/ZH delivery path (TikTok/Facebook caption files vs burned-in variants) — decision pending, no code.
