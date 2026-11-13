# Phase F spec — release: metadata, Gate 2, teaser, calendar, slots, amendment integration (v0.2 DRAFT)

Status: **DRAFT v0.2**, 13 Nov 2026, GLM. Goldfish rulings applied per
`phase-f-goldfish-rulings.md` (all ACCEPTED; findings and Stage-8 resolutions in
`phase-f-review/consolidated_review_report.md` — 4 Blocker / 33 Major / 36 Nit). Next: a Codex
critique. Binding inputs: `SPEC-v3.md` v0.4.6 (§4.8–4.10, §9, §12.6, §15.1–15.2; V3C-26 — SPEC
§4.3; O-8/N35 — SPEC §9.2 + §19.1; N11 — SPEC §9.2; O-3/O-6/O-7 — SPEC §19.1), `DECISIONS.md`
(Q6, line 61), `phase-A-spec.md` v0.3, `phase-B-spec.md` v0.4, `phase-A0-spec.md` v0.4,
`phase-C-spec.md`, `f-factmap.md` (cited as **FM §n**; spot-checked — every FM fact relied on
below was verified in code unless marked `UNVERIFIED`; v0.2 corrects the one v0.1 claim that
broke this promise, §1.4).

Conventions: `S/` = `microdrama/src/microdrama/`, `M/` = `microdrama/migrations/` (ends at 0025 in
this checkout; 0026–0027 live under `.scratch/a0d-gate/` — FM header). New migrations are symbolic
`F-1…`; real numbers are allocated in the F1 note from the migration tail (the highest applied
number at F1 time, counting `.scratch/a0d-gate/`'s 0026–0027 — a lookup against the migrations
directory, not an interpretation). **Applied migration bytes are never edited.** Three id
namespaces, never interchangeable: build packages **F1…F10**, migrations **F-1…F-8**, acceptance
tests **F-T1…F-T14**; prose says "package F2" where a package is meant.

## 0. Scope

**Problem.** A V3 season ends step 7 with approved episodes and nowhere to go: today's publisher
pins dates into `platform_posts` at schedule time and has no calendar, no season teaser, no Gate-2
prefill, no thumbnail pick and no amendment-safe reschedule (FM §11). Phase F closes that gap — it
carries a locked season from "episodes approved" to "published on schedule, in Thai, on three
destinations, with EN/ZH captions where the operator has ruled them in" without touching V1/V2
publishing semantics.

**Phase F builds tabs 8–10 plus Launch, and the release half of the state model:**

1. **Step 8 (SPEC §4.8):** per-slot metadata drafts (prefill → edit → seal) and thumbnail
   candidates (2–3 variants, operator pick) — V3-AT-11, R-8.1, R-8.3.
2. **Step 9 (SPEC §4.9):** Gate 2 for V3 episodes through phase A's decision transaction —
   prefilled drafts, the thumbnail pick, caption tracks, later-episode slot binding — R-9.1.
3. **Step 10 (SPEC §4.10):** the season teaser contract, `TEASER_FINAL`, the `PROMO_CUT` slot at
   premiere − 3 days, and teaser-gates-premiere — R-10.1, R-10.2, V3-AT-12.
4. **SPEC §9.1–9.3:** the versioned release calendar, LAUNCH authority, stable slot identities
   per destination, release admission, predecessor dependencies, HELD/MISSED/PARTIAL handling,
   reschedule + the N11 corrective post (SPEC §9.2) — V3-AT-29.
5. **SPEC §12.6 / V3C-26:** the release-side amendment fences (the amendment-vs-job-vs-publication
   triad, §8.5) and the extension flow's decision screen, calendar continuation and viewership
   windows — V3-AT-30, V3-AT-31, R-3.7.
6. **SPEC §9.4 (MA11):** throughput measurement, buffer counters, Costs/status surfaces, bot
   alerts.
7. **R-8.2 delivery:** EN/ZH caption-track delivery per destination, per the operator's O-8
   decision (§1.9; the decision itself stays open — §15 O-F1).

**Not in F:** caption translation and cue alignment (B's packs carry EN/ZH line text; E's edit
binds tracks to the TH cue timing — V3-AT-10 is E's); the image adapter, cross-system lock and
output inspection (C's — F only calls them); live platform qualification (T032 → G/live);
analytics ingestion (existing W11); the EDL (edit-decision-list) export tooling the teaser cut
assembles from (E's — the deterministic assembly seam itself already exists, `S/editing/`, §5).

## 1. Binding decisions

1. **V1/V2 never change** (B §1.1 / C §1.1 rule). V3 release code lives in new modules
   `S/release_v3/`. Today's publishing machinery is **reused, not forked**: `metadata_versions`,
   `platform_posts`, `approval_events`, `approved_slot_metadata`, `release_approval_manifests`
   and the publishing service's submit/reconcile paths stay the one implementation (FM §1–§2,
   §5). F adds V3 rows and V3-only guards **beside** the V1/V2 rules; no historical row is
   rewritten, and no historical dated approval is reinterpreted against any calendar
   (SPEC §9.2 item 7).
2. **Release authority is two-part.** Content authority = a Gate 2 (or `TEASER_FINAL`) approval
   that is *effective* (A §7.2 `effective_approval` — not superseded) and hash-matches the current
   package. Calendar authority = the LAUNCH decision and the calendar revision it bound.
   **Dispatch requires both** (SPEC §9.2 item 5); the check lives in one place, **release
   admission** (§7) — one name for that transaction everywhere in this document.
3. **The calendar is a versioned document, not slot columns.** `ReleaseCalendarV3` (a record of
   the F-1 store) holds the premiere date, the daily 19:00 Asia/Bangkok cadence, the teaser
   instant (premiere − 3 days, 19:00), the episode→date map for every episode number in scope,
   and a monotone revision. It is **proposed before step 7 editing** (release track →
   `CALENDAR_PROPOSED`). A change of any instant is a **new calendar revision** —
   `reschedule_calendar`, the propose→confirm operator flow of §8.1 in which **Confirm is Apply**;
   a revision is never edited in place (row-level dates follow §1.4). Nothing in
   `platform_posts` is date-authoritative for V3 (§1.4).
4. **V3 `platform_posts` rows are created at release admission**, with the date resolved from the
   bound calendar revision — not at Gate 2 and not at LAUNCH. Grounds (verified; corrects v0.1 —
   CON-M1): the immutability trigger pins **identity columns only** (`M/0005:77-80`);
   `scheduled_utc`/`local_time`/`iana_zone` are ordinary updatable columns, date-pinned in V1/V2
   by service-layer convention at `schedule_release` time. The slot-identity columns carry a hard
   UNIQUE (`M/0005:32-78`; FM §4), so a **second row for the same identity can never be created**.
   Creating the row when both authorities already hold means no V3 row is ever re-created — and
   **reschedule updates the date columns in place** on V3 rows still locked in SCHEDULED
   (identity columns byte-identical; published rows immutable; rows past `provider_ops.begin`
   settle per §8.5 — CON-B1). The V1/V2 triggers and conventions stay untouched.
   `ReleaseSlotPlan` still requires a `schedule` (`S/contracts/release.py:85`, verified); V3
   fills it at admission from the calendar. (Alternatives: §18.)
5. **LAUNCH is a season gate through A's decision transaction** (A §2.6), binding: the exact
   calendar revision hash, the slot-identity map (§6), and the current approval hashes of **the
   first five consecutive episodes and the teaser** (SPEC §9.2 item 3). It is **refused while
   fewer than 5 episodes have current Gate 2 approvals** (O-7 — SPEC §19.1; V3-AT-12) or while
   the teaser approval is missing/stale. Reject LAUNCH leaves the release track at
   `CALENDAR_PROPOSED` without launch authority; the planning track is untouched (A §2.2).
6. **Later episodes bind their slot at Gate 2** (N21 — SPEC §4.9): for episodes after LAUNCH's
   initial five, the Gate 2 APPROVE handler records the binding of that approval to the episode's
   already-allocated slot identities (§6.1). For episodes 1–5 the same binding is recorded by the
   LAUNCH handler. One shape, two writers.
7. **A draft is not an approval.** Metadata drafts and thumbnail picks exist **before** the Gate 2
   activation opens; they carry no release authority of any kind. The sealed manifest equals the
   edited drafts at the moment of Gate 2 APPROVE (V3-AT-11), through the existing manifest path
   (FM §2: `release_approval_manifests`, `md_gate2_manifest_binding`).
8. **Thumbnail pick = phase C's picks engine, extended** (C §4; §2.2 FD1): generation produces
   2–3 candidates; **a vote appends a `cast_pick_votes` row; starts no work**; Approve is refused
   with a typed reason while no candidate is picked (or while the pick is stale, §3.3). The
   picked candidate becomes the cover triple (`id/version/sha256`) the existing V2 binding
   already requires (FM §1).
9. **O-8 stays open — the OPERATOR decides; GLM does not.** **Package F5 is conditionally blocked
   on the ruling; F1–F4 may proceed** (CON-B3). The operator chooses, per destination, between
   caption-file delivery where the platform supports it and *not delivering* EN/ZH there (options
   and the recorded recommendation in §15 O-F1; extra posts are excluded by SPEC §9.1). YouTube
   has a real caption surface today (`upload_captions`, **not part of submit** —
   `S/publishing/youtube/adapter.py:250-258`, FM §9); TikTok/Facebook have none verified. The
   chosen route is recorded per destination in `CaptionRouteV3` (§2; written by
   `record_caption_route`, §12) and enforced at release admission (§7.1 item 5).
10. **HELD / MISSED / PARTIAL are derived, per-destination episode-release states** (SPEC §2.2
    cites N43), computed from three inputs — `platform_posts` rows, `publication_admissions` and
    the calendar — never stored side state (AR-4; §7.4 names its provenance). The stored per-slot
    states stay today's enum (`M/0005:51-52`, verified: no PARTIAL/MISSED — FM §5). Definitions
    in §7.4.
11. **A post is never duplicated.** The existing invariants carry over unchanged: unique external
    id per platform+account (`M/0005:76`), idempotent `client_token = hash(dedupe_key,
    package_hash)` (FM §5), reconcile adopts-by-external-id first and **re-arms only a
    proven-absent publish slot** (FM §5, `S/publishing/service.py:947-980`). F adds no second
    dedupe mechanism.
12. **Reschedule is calendar authority, not an amendment.** It changes dates, not content: it
    appends a new calendar revision (§1.3), rebuilds **date-bearing content** (CTA/recap copy
    that names dates, SPEC §4.7:460-461; teaser instants), **updates the date columns in place**
    on un-submitted V3 `platform_posts` rows (§1.4), and **re-binds every not-yet-admitted slot
    identity** to the new revision (§8.1). It never touches published media, never supersedes a
    content approval by itself, and shares the Confirm-with-impact-hash shape of A §7.3. Content
    that must materially change still goes through Gate 2 (renewed approval, SPEC §9.2 item 6).
13. **Amendments fence publication at release admission.** Release admission re-validates, in one
    transaction and in A's §6 lock order: the fence (`expected_content_revision`), the effective
    approval, the manifest↔current-metadata equality (FM §2 live binding), **and** the calendar
    revision. (§7.1 enumerates the six admission checks authoritatively; this item states the
    principle.) An amendment applied anywhere between validation and submit is impossible because
    the track SHARE lock is held through the mutation (A §7.1). A submission already past
    `provider_ops.begin` when an amendment applies is handled by A §7.3 invalidation + the
    existing reconcile; if it published, it stays published (immutable), its approval is
    superseded so **changed artifacts cannot follow it**, and the only remedies are the existing
    metadata policy edits or an N11 corrective post (§8).
14. **No new job system, no new dedupe, no second state machine** (SPEC §10.0). F's jobs are jobs
    + provider operations; F's states are projections; F's queues go through A's four-point
    checklist (A §4; C §1.12 pattern). F adds the lane `release` (release admission, calendar
    ops) — thumbnails ride C's `image` lane; the metadata prefill rides A0's LLM runtime on the
    existing `production` queue, B's LLM lane (B §7.2 — "the existing `PRODUCTION` queue";
    verified).
15. **Budgets:** per-episode paid work (episode thumbnail variants) meters to the episode's
    EPISODE account; the teaser's key art meters to the **season-setup sub-budget** (SPEC §12.3
    puts the teaser there; A §5.1's SEASON account is aggregate-only — it takes no reservations —
    so season-level reservations must charge the setup sub-budget, which does reserve — CON-M7).
    Step keys `step_08` (metadata + thumbnails) and `step_10` (teaser key art — mapped in §10);
    final vocabulary allocated in the F1 note against A2's step ledger (the ledger is the lookup
    source). The metadata prefill is an unmetered `llm.subscription` call (A0 §5.1) —
    quota-admitted, never billed. Unknown price ⇒ refused (C §1.7 rule).
16. **Per-destination text limits come from the capability record.** `CapabilityLimits` gains
    nullable `max_title_chars` and `max_hashtags` fields (contract bump, package F1 — §2.2 FD4;
    today the class carries neither, `S/contracts/release.py:469-475`, verified, and YouTube's
    100-character title limit exists only in an EvidenceRef note — CON-M13). The **effective
    cap** for a slot = min(capability limit, contract cap) — title ≤ min(cap, 200), hashtags ≤
    min(cap, 30) (`S/contracts/release.py:362-374`) — which resolves the 200-vs-100 conflict for
    the prefill lint (§3.1): a null capability field means "no platform limit pinned" and the
    contract cap governs.

## 2. Records (contract package, guardian-owned bump; symbolic migrations `F-1…`)

Documents live in one new append-only, versioned, hash-sealed store **`v3_release_documents`**
(F-1), mirroring B's `StoryV3Store` / C's `CastV3Store` (C §2): PK `(contract_type, record_id,
version)`, one `current` row, hash re-verified on read, `contract_type` allowlist CHECK,
`record_id = uuid5(RELEASE_V3_NS, "<type>:<season_id>[:<key>]")`. `v2_contract_documents`,
`v3_story_documents`, `v3_cast_documents` are not touched.

| Migration | Object | Decisive columns / rules |
|---|---|---|
| `F-1` | **`v3_release_documents`** | the release document store above; guarded |
| `F-2` | **`metadata_drafts`** + **`metadata_draft_versions`** (committed — CON-M15; the `metadata_versions` reuse option is dropped as non-viable: its `platform_post_id` is NOT NULL, `M/0005:85`, and drafts exist pre-post) | `metadata_drafts`: `season_id`, `target_kind` (`EPISODE` \| `TEASER`), `episode_id` **nullable** (NULL iff `TEASER` — the teaser key shape, CON-N9), `slot_key` (destination-scoped: platform + locale + `release_slot` name), `state` (`PREFILLING`/`DRAFT`/`SEALED`/`SUPERSEDED`; a projection — §2.1), `draft jsonb` (typed `MetadataDraftV3`: TH title/caption/description/hashtags/CTA + optional EN/ZH fields + the deterministic disclosure text ref), `prefill_job_id`, `calendar_revision` (the revision the CTA/date text was resolved against), `sealed_manifest_hash` nullable, `sealed_at`; `UNIQUE NULLS NOT DISTINCT (season_id, target_kind, episode_id, slot_key)`. `metadata_draft_versions`: `draft_id`, `version`, `draft jsonb`, `editor_session`, `created_at` (append-only); guarded |
| `F-3` | **C picks-engine extension — no new tables** (CON-M6; §2.2 FD1) | `cast_pick_items.pick_kind` gains `THUMBNAIL` (item key `thumb:ep:<episode_number>` / `thumb:teaser`; `selection_mode HUMAN_PICK`); candidates are the generated variant **assets**; `cast_pick_votes.candidate_kind` gains `ASSET`; items carry `inspection_ref` (C §9 output-inspection evidence per candidate). Vote, staleness and current-selection semantics are C §4's unchanged |
| `F-4` | **`release_slot_identities`** | `season_id`, `episode_number` (0 = teaser carrier), `platform`, `locale`, `account_ref`, `release_slot` name, `dedupe_key` (computed exactly as `ReleaseSlotKey.canonical_hash`, `S/contracts/release.py:74-76`, verified), `calendar_revision_allocated`, `bound_approval_event_id` nullable, `bound_calendar_revision` nullable, `platform_post_id` nullable (**set once, at release admission; never cleared** — reschedule updates the row's date columns in place, §1.4, so the pointer never moves); `UNIQUE (season_id, episode_number, platform, locale, account_ref, release_slot)`; `dedupe_key UNIQUE`; guarded, no-delete |
| `F-5` | **`publication_admissions`** (append-only) | one row per release-admission decision: `slot_identity_id`, `calendar_revision`, `content_revision`, `approval_event_id`, `manifest_hash`, `admitted_at`, `outcome` (`CREATED_POST`/`REFUSED` + typed reason); the audit trail behind §7 and V3-AT-30 |
| `F-6` | **`release_throughput_observations`** | `season_id`, `observation_date`, `approved_episodes` (episodes whose **first** Gate 2 APPROVE fell that date — CON-M29), `released_episodes` (episodes reaching all-required-destinations verified that date), `buffer_days` (§6.3), `cost_to_date`; written daily by the throughput schedule (§9); append-only. **Rolling aggregates (sustained 7-day rate, catch-up) are derived on read from these rows, never stored** (AR-4 — CON-N3) |
| `F-7` | **`corrective_posts`** | `season_id`, `carrier_episode_id` (each decision's own carrier — §8.3), `trigger_kind` (`RESCHEDULE_N11`), `calendar_revision_pair`, `inaccurate_cta_refs jsonb` (the published posts whose CTA text the change made inaccurate), `decision` (`PROPOSED`/`APPROVED`/`POSTED`/`DECLINED`), approval refs; append-only decisions |
| `F-8` | lane + queue plumbing | `jobs.queue` CHECK gains `release` (§2.2 FD2); reservations/charges + `budget/policy.py` ownership + worker set + generated contracts (A §4 checklist) |

### 2.1 `metadata_drafts` unpacked (CON-N12)

- **Schema:** one live row per (season, target, slot); every edit appends a
  `metadata_draft_versions` row; the row's `draft` jsonb is the latest version's payload.
- **Projection:** `state` is computed from the prefill job, the version chain and the seal ref —
  never authoritative; readers re-derive it the way C §4 derives pick state.
- **UNIQUE:** one live draft per (season, target, slot); `NULLS NOT DISTINCT` keys the teaser
  (NULL episode) cleanly beside episodes.
- **SUPERSEDED:** an older sealed draft replaced by a newer version (re-prefill, an edit past
  seal, or an amendment) — only the newest version is ever `DRAFT`/`SEALED`; the marker keeps
  history legible, it grants no authority.

### 2.2 F contract crossings (the C-B1 pattern, C §2.2 / B §2.4)

Every F identifier crossing an A/B/C-enforced contract, checked against that contract's enforced
vocabulary **before the F1 note is accepted**:

| # | Delta | Contract touched | Mechanism |
|---|---|---|---|
| FD1 | Thumbnail picks: `pick_kind` gains `THUMBNAIL`; `cast_pick_votes.candidate_kind` gains `ASSET`; items carry `inspection_ref` (CON-M6) | C's `cast_pick_items`/`cast_pick_votes` CHECKs and C §2.1's "`candidate_kind` is `REFERENCE_VERSION \| CATALOG_ENTRY` only" | **requested as a C-side register entry** — this row is the note; phase C's owner adds it to C's crossing register (this job does not edit phase-C-spec.md). Item keys and semantics: `F-3` above |
| FD2 | Queue lane `release` | A0/A3's `jobs.queue` CHECK (0001:77) | `F-8` grows the CHECK; worker set + `budget/policy.py` ownership land with F1's migrations and F2's wiring (mirrors C's CD1) |
| FD3 | `GateType` gains `TEASER_FINAL` and `LAUNCH` (FM §11: exactly 2 values today) | A's decision-transaction gate vocabulary; the `md_gate2_manifest_binding` trigger's allowlist (M/0021:50-79 — `TEASER_FINAL` only) | F-owned guarded migration in F's range; V1/V2 gate events and bindings unchanged (F-T11) |
| FD4 | `CapabilityLimits` gains nullable `max_title_chars` / `max_hashtags` (§1.16) | the release contracts (`S/contracts/release.py:469-475` — neither exists today, verified) | contracts bump in package F1; capability records pin per destination |
| FD5 | Gate-2 Revise note targets `metadata` / `thumbnail` | A1's `RevisionTargetKind` (C's CD3 grew it for `PICK`) | F-owned migration mirroring B's D2 / C's CD3; targets `{kind: metadata or thumbnail, id}` |

**Standing rule (C-B1 for F):** any further F identifier that crosses an A/B/C enforced contract
(enum, CHECK, trigger, validator) is added to this register and checked before the F1 note is
accepted.

**Documents in `v3_release_documents`:**

| Record | Key | Content |
|---|---|---|
| `ReleaseCalendarV3` | `calendar` (versions = revisions) | premiere date; cadence (daily 19:00 Asia/Bangkok); teaser instant; the episode→air-instant map for **every** episode number in the current scope (base season; extension ranges append via new revisions — §8.4); `extension_mode` (`CONTINUED`/`RESUMED`) **required on any revision carrying an extension range; base-season revisions omit it**; `calendar_hash` over all of the above |
| `SeasonTeaserPlanV3` | `teaser-plan` | `carrier_episode_id` (§5), source episodes (approved-only refs), the spoiler limit (from B's beat/reveal vocabulary — the plan names the latest reveal it may show), duration target 30–60 s, the release obligation (PROMO_CUT at premiere − 3 days per destination), own copy + thumbnail refs |
| `LaunchBindingV3` | `launch:<release-track revision at approval>` (the `season_tracks.revision` of the release track — CON-N28) | the calendar revision + `calendar_hash`, the slot-identity set allocated, the approval hashes bound (episodes 1–5 + teaser), the LAUNCH approval event ref |
| `CaptionRouteV3` | `caption-route:<platform>` | the O-8 outcome per destination: route (`CAPTION_FILES` \| `TH_ONLY`), the deciding operator decision ref, the flip audit (each flip = a new version) — the storage home behind §1.9/§7.1 item 5 (CON-M14) |
| `EpisodeCloseoutV3` | `closeout:<episode_number>` | the episode, the typed reason, the decision event ref, the successor-override note (§12 `close_out_episode`) |
| `RescheduleImpactV3` | `reschedule:<old>:<new>` | the proposed revision pair, per-slot effects (to-dispatch: date change; dispatched-not-published: in-place date update if still SCHEDULED, else "will land on the old date" — §8.5; published: untouched), the rebuilt date-bearing content list, the inaccurate-published-CTA list (N11 input), `impact_sha256` |
| `ExtensionDecisionV3` | `extension:<extension_id>` | V3C-26 decision record: the B `create_extension` ref, the `CONTINUED`/`RESUMED` choice (§8.4), the viewership-window evidence (per-episode H24/H72/D7 from `performance_snapshots`, `M/0005:204-227` — FM §10, with freshness), the operator rationale |

**Reused unchanged:** `metadata_versions` + `ApprovedMetadataPolicy` (post-approval edits,
`S/publishing/metadata.py:29-37,78-140`, FM §1), `platform_posts` + the publishing service,
`approval_events` (+ A's V3 gate columns), `approved_slot_metadata` / `release_approval_manifests`
/ `md_gate2_manifest_binding` (M/0021 — verified objects), `performance_snapshots`, the
outbox + bot (A §8), the schedule registry (A6b).

## 3. Step 8: metadata and thumbnail drafts (V3-AT-11; R-8.1, R-8.3)

### 3.1 Drafts

- **One draft per destination slot** (`metadata_drafts` row per (episode, slot_key)), in TH, with
  EN/ZH fields where the destination supports them (§1.9). Fields: title and hashtags bounded by
  the **effective cap** = min(capability limit, contract cap) — title ≤ min(`max_title_chars`,
  200), hashtags ≤ min(`max_hashtags`, 30) (§1.16), caption and description (≤5000), CTA,
  AI-disclosure text. Grounded in B's episode pack; **no spoilers beyond the episode** (the
  prefill prompt takes the pack's own reveal boundary as input; deterministic lint refuses draft
  text that quotes lines from later episodes — sources list in the prompt contract).
- **The CTA is resolved from the calendar revision the draft records a dependency on** (SPEC
  §4.7:460-461): the next air time, a confirmed continuation, or the finale follow message — never
  an unapproved extension. `metadata_drafts.calendar_revision` is that dependency record (SPEC
  §9.2 item 1's "date-bearing content records its dependency on the revision"); a calendar bump
  marks dependent drafts stale (rebuilt in §8.2).
- **Prefill** is one `release_v3.prefill_metadata` job per episode (all slots in one job): an A0
  `LlmStep` call (A0 §5.1 — frozen call, resumable, quota-admitted, unmetered) plus deterministic
  assembly (disclosure text from the capability/disclosure config — **never LLM output**; hashtag
  truncation to the effective cap, §1.16; CTA from the calendar). One call per episode, all
  locales and slots in the result (§15 O-F9).
- **Edit surface** = tab 8: every field editable while the Gate 2 activation for the episode is
  open; edits append draft versions; nothing here starts paid work.

### 3.2 Thumbnails (R-8.3)

1. A `release_v3.make_thumbnails` job produces **2–3 key-art variants (default 3** — SPEC §4.8;
   the count is config so R-8.3's "2–3" and the job's default agree) through C's image adapter
   (Nano Banana seam, cross-system lock + fairness, metering, provenance — C §5) from **locked
   assets only** (the current cast-lock bindings). Episode scope meters to the EPISODE account;
   teaser scope to the season-setup sub-budget (§1.15).
2. The job composites the **Thai title locally** with the licensed font (O-3 — SPEC §19.1 —
   provenance record; no provider call), runs **output inspection** (C §9) on each variant, and
   registers the passing candidates as assets carrying `inspection_ref`s (§2.2 FD1). Failed
   inspection ⇒ the candidate is not registered (it exists as quarantined job evidence).
3. **Pick = one vote in C's engine** (`pick_kind THUMBNAIL`): **appends a vote; starts no work**.
   Approve at Gate 2 is refused with a typed list while the episode (or teaser) has no current
   pick, or while the pick's candidate is stale (§3.3).
4. The picked candidate becomes the cover triple + rights in the sealed `ApprovedSlotMetadata`
   (the existing required shape, `S/contracts/v2.py:857-860` — verified), re-checked at submit
   exactly as today (FM §1).

### 3.3 Staleness

A draft or thumbnail pick is **stale** when: the episode's `content_revision` moved (amendment,
Revise); the pack version it was generated from is no longer current; or (drafts) the recorded
`calendar_revision` is no longer the **current calendar revision in force** — the latest proposed
revision before LAUNCH, the bound revision after it (CON-M25). Staleness is computed from stored
columns, never a stored flag (C §4 pattern). A stale draft must be re-prefilled/edited; a stale
pick must be re-voted; **Gate 2 APPROVE refuses on any stale dependent** (typed list) — the same
refusal shape as C's lock (C §4; V3-AT-5 is C's test — §16).

## 4. Step 9: Gate 2 in V3 (R-9.1)

(The gate invariant V3-AT-2 — no transition passes a gate without a human approval event bound to
the current hash — is A's, enforced by the decision transaction F rides; F claims no ownership of
it.)

- **The gate runs through phase A's decision transaction** (A §2.6): idempotency replay, scope
  locks, activation + binding hash + authoritative content revision comparison (stale page
  refused), conditions, the approval event, the handler callback, the idempotent response — one
  transaction, all-or-nothing.
- **What carries over from V2 exactly** (FM §2, verified): the manifest binding
  (`release_approval_manifests`, `md_gate2_manifest_binding` — only Gate 2 APPROVE binds a release
  manifest; manifest covers every current slot with exact (metadata_id, version, content_sha256));
  the human-session/CSRF rules (`actor_owner_id` + `actor_session_id`, `require_human_owner`);
  `gate2_blockers` emptiness (QA findings, per-asset hash + persisted-object verification, policy
  hash, no live pod leases — `S/review/gate_conditions.py:118-190`); the **caption-alignment
  guard** ("a current caption track is not aligned to actual audio", `M/0008:24-34`); live-approve
  requires the manifest, OFFLINE_MOCK exempt.
- **What changes for V3:** (a) the form is **prefilled from `metadata_drafts`** (V3-AT-11) — the
  sealed `ApprovedSlotMetadata` per slot is the edited draft, verbatim; (b) **the thumbnail pick
  is a blocker** (§3.2); (c) the handler records the **slot binding** for later episodes (§1.6)
  and the calendar-revision dependency of the sealed CTA; (d) recaps/CTA previews and costs join
  the existing page (SPEC §4.9); (e) Revise uses `season_revision_notes` with **typed targets**
  (`metadata` / `thumbnail` — §2.2 FD5): "regen noted units only" — a note targeting `metadata`
  re-prefills drafts, targeting `thumbnail` re-rolls candidates, targeting content routes to the
  owning phase's amendment path (A §2.2). These are typed Revise targets, not A's timecoded
  feedback channel; the notes carry the season id and the target payload (CON-N2).
- **V1/V2 history stays readable, not reinterpreted:** V3 Gate 2 writes V3 rows beside the
  existing ones; V1/V2 approval events, manifests and dated slots keep their exact semantics and
  readers (no V3 calendar is ever applied to them — §1.4). Compatibility test F-T11 pins this.
- The **episode-1 identity-lock hook never fires for V3** (C §1.8: CAST LOCK replaced it).

## 5. Step 10: teaser (V3-AT-12; R-10.1, R-10.2)

- **`SeasonTeaserPlanV3`** (a record of the F-1 store): multi-episode sources (approved episodes
  only — the plan refuses unapproved sources), the spoiler limit (the latest reveal it may show,
  expressed against B's beat/reveal vocabulary), 30–60 s, hook-led, its own copy + thumbnail (a
  draft set + candidates exactly like an episode's — §3, keyed `target_kind = TEASER`, §2), and
  the release obligation: one `PROMO_CUT` slot per destination at **premiere − 3 days, 19:00
  Asia/Bangkok** (§15 O-F3).
- **Carrier — season-scoped posts ride the ordinary path (CON-B2, option a).** `platform_posts`
  is episode-scoped — `episode_id`, `release_package_id` and `approval_event_id` are all NOT NULL
  (`M/0005:36,45-46`) — so the teaser travels on a **synthetic carrier episode**: one episodes row
  per season for the teaser (`episode_number = 0`; ordinary data, no shared-table schema change;
  `SeasonTeaserPlanV3.carrier_episode_id` records it), plus a **season-scoped teaser release
  package**: an ordinary `ReleasePackage` whose media is the teaser cut asset, whose
  `release_scope` is the per-destination `PROMO_CUT` slot plans, and whose caption tracks follow
  the O-8 route (§1.9). `TEASER_FINAL` joins `GateType` (§2.2 FD3) and the
  `md_gate2_manifest_binding` trigger's allowlist grows it in F's guarded range (V1/V2 bindings
  unchanged — F-T11), so the teaser seals a manifest exactly as an episode does and §7.1's checks
  read identically for the carrier. N11 corrective posts use the same pattern: each decision's
  own carrier episode (recorded in `corrective_posts.carrier_episode_id`, F-7) carries its slot
  identities, so the fixed `corrective` release-slot name never collides.
- **`TEASER_FINAL`** is a season-scoped gate through A's decision transaction (values from A §2.1;
  entity = the carrier episode). It approves teaser *content*: the cut, its metadata drafts, its
  thumbnail pick. It binds nothing calendular — the teaser's slot identities and instant come from
  the calendar revision that LAUNCH binds.
- **The cut** is a `release_v3.teaser_cut` job: deterministic assembly from the source episodes'
  approved edit artifacts (E's EDL/export outputs) per the plan — **reusing the existing
  deterministic seam `S/editing/{edl,export,ffmpeg}.py`** (T015; CON-M12) — no new provider, no
  new budget line beyond the key art (§1.15). The spoiler limit is enforced by a deterministic
  check (cut segments must precede the limit's reveal point) — a violation blocks `TEASER_FINAL`
  with a typed blocker.
- **The teaser gates the premiere per destination** (SPEC §9.3): episode 1's slot identity per
  destination declares `depends_on` the teaser's slot identity on the **same destination**
  (`depends_on` semantics = "dedupe_keys that must be PUBLISHED_VERIFIED first",
  `S/contracts/release.py:86-88`, verified; the check at submit is `S/publishing/service.py:654-668`,
  verified). The teaser itself has no predecessor.
- **Late or failed teaser ⇒ the premiere holds.** If the teaser instant passes without a verified
  teaser post on a destination, that destination's episode-1 release admission refuses
  (dependency not `PUBLISHED_VERIFIED`) and the episode shows **HELD (teaser)** in the derived
  state (§7.4). The bot alert offers exactly two recoveries, both operator-approved (SPEC §9.3):
  1. **Repair:** fix the teaser (re-cut job + `TEASER_FINAL` re-approval), then the premiere
     proceeds on the original dates — permitted only while the premiere instant has not passed
     **and the repair can still complete in time** (re-cut + re-approval + admission lead +
     verification must all fit before the premiere instant; the alert shows the latest safe
     start — CON-N4);
  2. **Reschedule:** §8.1 moves teaser + premiere (new revision; date-bearing content rebuilt;
     §8.2) — the path when the premiere instant already passed (the episode is then MISSED on
     that destination, §7.4, and the calendar must move).

## 6. Calendar, LAUNCH, slots (V3R-6 — SPEC §4.7/§4.9/§9.2; V3-AT-12)

### 6.1 Slot identities (SPEC §9.1)

- **Allocation:** LAUNCH allocates one `release_slot_identities` row per (episode number in the
  calendar revision × destination {YOUTUBE, TIKTOK, FACEBOOK} × locale th-TH × the season's
  account) with `slot_kind FULL_EPISODE` for episodes and `PROMO_CUT` for the teaser
  (`SlotKind` values exist, `S/contracts/enums.py:430-434` — verified). Identities are **stable**:
  they survive reschedules (only their `bound_calendar_revision` changes) and are never deleted.
  A later calendar revision may only **append** identities (extension episodes) or re-bind —
  never renumber. **Extension identities are allocated and bound by the extension approval
  handler** (§8.4), never by a re-run LAUNCH (CON-M2).
- **Binding:** `bound_approval_event_id` + `bound_calendar_revision` are set by LAUNCH (teaser +
  episodes 1–5) or by later Gate 2 (episodes 6+). Release admission requires a current binding
  whose approval is effective and hash-matches.
- **Slot matrix per destination:** exactly one full-episode post, TH (SPEC §9.1); EN/ZH as caption
  tracks per the O-8 decision (§1.9, §15 O-F1); disclosures ≥1 with MD-015 mandatory (the existing
  plan validator, `S/contracts/release.py:93-101` — verified); capability pin from the
  destination's current capability record. **Instagram is excluded** (Q6 — DECISIONS.md:61).

### 6.2 LAUNCH

`LAUNCH` runs through A's decision transaction with conditions (all must hold, typed refusals):

1. a calendar revision is current and its premiere lies in the future;
2. **≥5 episodes have current Gate 2 approvals** (O-7 — SPEC §19.1; V3-AT-12) — the first five
   consecutive episodes by number;
3. the teaser has a current `TEASER_FINAL` approval;
4. the drafts/picks bound for episodes 1–5 + teaser are not stale (§3.3);
5. **invariant:** every destination in the slot matrix (§6.1) has a current capability record —
   no required destination lacks a pinned, non-stale record at LAUNCH. **Exception:** a record
   that exists but is unqualified for a specific route (e.g. Facebook AI disclosure until T032)
   does not refuse LAUNCH; it holds that destination's slots at release admission (§7.3).
   Rationale: excluding a destination from the matrix is a season decision (Q6), not a per-run
   one (CON-M27).

APPROVE writes the approval event + `LaunchBindingV3`, allocates identities, records the
bindings, and moves the release track `CALENDAR_PROPOSED → LAUNCH_APPROVED`. RELEASING begins at
the first verified publication (derived), COMPLETE when every in-scope episode is verified or
explicitly closed out on every destination (`close_out_episode`, §12 — CON-M16).

### 6.3 Buffer

The buffer rule is enforced at LAUNCH (≥5 approved = first five) and monitored during RELEASING.
**Authoritative definition (cited by §9 and F-6):** `buffer_days` = approved-and-unreleased
episodes ÷ 1 per day; **alert below 2 days** (SPEC §9.4) — the `w13b-throughput` schedule raises
the bot alert (A §8); the operator decides (pace, parallelism, start date).

## 7. Dispatch, dependencies, failures (V3-AT-29)

### 7.1 Release admission (one transaction, A §6 lock order)

A new schedule **`w13-release-admission`** (5 min; registered in A6b's registry — FM §6 lists
today's 14) discovers due slot identities (air instant ≤ now + lead; the lead is config
**`release_admission_lead_seconds`, default 600 s** — CON-M28), and for each, under the season
track lock:

1. **fence:** the bound approval's `expected_revision` equals the episode's current content
   revision (A §7.1's `expected_content_revision` comparator instantiated for release: **bound
   approval revision vs current revision** — CON-N10);
2. **content authority:** `effective_approval` for the episode's Gate 2 — or the carrier's
   `TEASER_FINAL` (§5) — and the package hash match;
3. **calendar authority:** the identity was bound by the **latest binding authority** — LAUNCH, a
   later-episode Gate 2, or an extension approval (§8.4) — and its `bound_calendar_revision`
   equals the current revision; the air instant matches the current revision's map (CON-M2);
4. **live binding:** manifest ↔ current metadata equality (FM §2 — existing
   `validate_live_release_metadata` semantics, `S/contracts/v2.py:940-965` verified; OFFLINE_MOCK
   exempt);
5. **caption route:** the route recorded for the destination in `CaptionRouteV3` (§2) is
   available; a route that needs an unqualified capability holds instead (§7.3);
6. **dependencies:** predecessor + teaser `depends_on` verified (existing check semantics).

All hold ⇒ **create the `platform_posts` row** (SCHEDULED, date from the calendar) through
**`schedule_release_slot`** — the per-slot variant of `schedule_release` that F exposes in
`S/publishing/slots.py` (§7.1.1) — set `platform_post_id` on the identity, append
`publication_admissions (CREATED_POST)`, and enqueue `publish.submit_slot` — the existing
`w09-publish-submit` (unchanged; FM §6) then submits it through the ordinary command path. Any
refusal ⇒ `publication_admissions (REFUSED, reason)`; the derived state shows the typed cause.
**`w09` is not modified** — it only ever sees ordinary SCHEDULED rows.

#### 7.1.1 The row-creation invariants (one owner — CON-M4)

`schedule_release` (`S/publishing/slots.py:116-222`, verified — FM §4) owns the most
invariant-dense insert in the system. Release admission does not fork it blindly: package F2
exposes **`schedule_release_slot`**, a per-slot variant that preserves, for the single identity:

- the episode (or carrier) row lock `FOR UPDATE`;
- the APPROVED-package + approval-event requirement;
- scope-DAG revalidation (`validate_scope_dag`);
- the deterministic `platform_post_id(dedupe_key)` and `client_token = hash(dedupe_key,
  package_hash)`;
- the full slot-column set, `state = SCHEDULED`, the date columns from the calendar-resolved
  schedule;
- the `platform_post.scheduled` outbox event;
- the episode (or carrier) `RELEASE_APPROVED → SCHEDULED` transition in the same transaction;
- replay idempotency; a different package ⇒ `Conflict`.

V1/V2's `schedule_release` is untouched and remains the owner for whole-package expansion.

### 7.2 Predecessor dependencies per destination (SPEC §9.3)

Episode N's identity per destination depends on episode N−1's identity on the same destination;
episode 1 depends on the teaser's identity on the same destination. The calendar's episode→date
map normally makes predecessors air earlier; the dependency still enforces order when reschedules
compress dates. Successor holding is *derived* (a slot identity whose dependency is HELD/MISSED
waits — existing `PolicyDenied` "this slot waits" semantics at submit,
`S/publishing/service.py:663-668`, verified — plus the admission-time check).

### 7.3 HELD, and the near-air-time options (SPEC §9.3)

- **Destination blockers** (capability stale/unavailable, unsupported disclosure, mock metadata on
  live routes) keep today's `HeldSlot` semantics: **the publish slot HELDs, the episode does not
  fail** (`S/publishing/service.py:101-102`, verified); `retry_held_slot` re-checks the
  destination and returns HELD→SCHEDULED only when the checks now pass (`service.py:1060-1068`,
  verified). T032 qualifying a held capability is exactly this retry — no code change beyond the
  qualification.
- **A rejected or unready episode near its air time** (release admission due within the lead
  window — `release_admission_lead_seconds` — with no current Gate 2, an open Revise, or stale
  dependents): the derived episode state goes **HELD**, successors (same destination) hold, and
  the bot alert offers three operator-approved options (SPEC §9.3): **repair**
  (Revise/amendment path, then re-admission), **swap** (a later approved episode takes this date
  via a calendar revision that remaps episode→date — numbers immutable, §15 O-F4), **push**
  (`propose_reschedule`/`confirm_reschedule` for the affected tail — §8.1). No option is
  automatic.

### 7.4 Derived episode-release states (SPEC §2.2 cites N43; AR-4 — phase-A-spec's architecture-rule appendix: side states are derived, never stored)

Computed from three inputs — `platform_posts` rows, `publication_admissions` and the calendar
(CON-N25) — never stored side state.

**Per-destination states:**

| State | Meaning |
|---|---|
| `HELD` | release admission refused, or the publish slot HELD, with a typed blocker (capability, dependency, teaser, authority) |
| `MISSED` | the air instant passed with no verified post, no post row in an in-flight state (SCHEDULED/HELD/SUBMITTED/PROCESSING/NEEDS_RECONCILIATION), and no queued admission or submit job (CON-N22) — recovery is reschedule |
| `UNVERIFIED-PAST-AIR` | a post exists and is past its air instant but not yet verified (RETRY_WAIT / NEEDS_RECONCILIATION / poll pending) — display only; reconcile owns it (CON-N11) |

**Cross-destination aggregate:**

| State | Meaning |
|---|---|
| `PARTIAL` | ≥1 destination verified, ≥1 required destination not verified (retry/reconcile per destination; SPEC §9.3) |

The season/episode tracks keep the stored coarse states (A §3); these are display + bot
projections, defined once here because SPEC §2.2 cites N43, which is not defined in
REQUIREMENTS/DECISIONS (grep verified — §15 O-F8 flags the anchor).

### 7.5 Never duplicated; proven absence re-arms

Carried over verbatim from today (FM §5, verified): unique external id per platform+account;
idempotent client token per (slot, package); 3-phase crash-safe submit with
`PUBLISH_DEADLINE_MS`/`MAX_SUBMIT_ATTEMPTS`; ambiguous ⇒ `NEEDS_RECONCILIATION`; reconcile adopts
a found post by external id, or **re-arms only a proven-absent publish slot** (same token,
capped). F adds no new path; the 30-episode simulation (F-T8) exercises all of them.

## 8. Reschedule, corrective post, amendment, extension (V3C-26 — SPEC §4.3; V3-AT-30/31)

### 8.1 Reschedule (SPEC §9.2 item 6)

`propose_reschedule` builds `RescheduleImpactV3` (typed effects per slot identity: to-dispatch ⇒
date change; dispatched-not-published ⇒ in-place date update if still SCHEDULED, else "will land
on the old date" (§8.5); published ⇒ untouched; the date-bearing content to rebuild; the
**inaccurate published CTAs** — published posts whose CTA text names an instant the change moves,
found by re-resolving each published CTA against the new revision). **Confirm requires** the
human session, CSRF, and the shown `impact_sha256` + scope revision, both revalidated in the
apply transaction (A §7.3 shape). **Confirm is Apply** (one transaction):

1. append the new calendar revision;
2. **update the date columns in place** (`scheduled_utc`, `local_time`, `iana_zone`) on every V3
   `platform_posts` row the transaction can lock in SCHEDULED — identity columns (slot identity,
   package, approval, asset, `client_token`) byte-identical (§1.4); rows past
   `provider_ops.begin` are left to settle and surface on the impact screen (§8.5);
3. **re-bind every not-yet-admitted slot identity** (`platform_post_id IS NULL`) to the new
   revision — without this, an already-approved later episode could never admit after one
   reschedule (CON-M2);
4. mark dependent drafts stale (§3.3).

**Published media is immutable** — no row, asset or platform object is touched. There is no
cancel and no re-create anywhere on this path (CON-B1).

### 8.2 Rebuilding date-bearing content

A `release_v3.rebuild_dated` job re-resolves CTA/date text for stale drafts (deterministic from
the new revision; no LLM), re-runs the thumbnail composite only if the art itself embeds a date
(operator choice at proposal; default: key art carries no dates). Renewed **content** approval —
**for a sealed but unaired episode the default and only path is a metadata-delta Gate 2
re-approval** (a scoped, low-cost re-approval of the metadata-only delta; the amendment
coordinator's metadata rebuild branch, SPEC §12.6 item 6, drives it): `metadata_versions` policy
edits require an existing `platform_posts` row (`M/0005:85`) and the live-binding equality
refuses any drift from the sealed manifest (FM §1/§2), so nothing else can rebind pre-publication
(CON-M3). After publication, the remedies are the existing metadata policy edits and the N11
corrective post (§8.3).

### 8.3 Corrective community post (N11 — SPEC §9.2)

The reschedule screen lists the inaccurate published CTAs (from §8.1) with a proposed corrective
post per platform (community post / regular post per the destination's qualified capability —
O-F5). `corrective_posts` records the operator decision; posting rides the ordinary publication
path on **the decision's own carrier episode** (§5 — `corrective_posts.carrier_episode_id`) with
its own slot identities (`PROMO_CUT`-kind, `corrective` release-slot name) and the same
verification rules. Nothing auto-posts.

### 8.4 Extension (V3C-26 — SPEC §4.3; V3-AT-31)

- **Calendar modes (defined here — CON-M17; recorded as `extension_mode` on the carrying
  revision, §2):** **`CONTINUED`** — the extension's episode→date map continues the daily 19:00
  Asia/Bangkok cadence on consecutive dates immediately after the prior scope's last air date (no
  gap). **`RESUMED`** — the extension starts on an operator-chosen later date (a deliberate gap)
  and resumes the daily cadence from it. In both modes published dates never move, the base map
  is appended (never renumbered), and the mode is a required field on any revision carrying an
  extension range.
- **Decision screen (F owns; B §8):** per-episode viewership windows H24/H72/D7 from
  `performance_snapshots` (FM §10) with freshness and unknowns shown; the operator picks
  `CONTINUED` vs `RESUMED` and the range. APPROVE ⇒ B's `create_extension(season, range,
  calendar)` (B §9, verified row) + F appends a calendar revision carrying the extension's
  episode→date map and mode. **The extension approval handler allocates and binds the extension
  identities** (CON-M2: LAUNCH is never re-run; the extension approval is the binding authority
  for its range). **Extension is always a manual decision** (SPEC §4.3).
- **During release or after completion:** from `RELEASING` or `COMPLETE`; existing approvals,
  published hashes and authority remain intact (the extension scope has its own planning track —
  A §3; B's builder runs on it with the planned-terminal + published canon inputs, B §8).
- **Changed cast:** new packs bind explicit cast versions; only new assets need picks (B §8). The
  fence guarantees **that** stale results and old approvals cannot release changed artifacts
  (§8.5) — V3-AT-31's proof.
- New episodes' Gate 2 decisions bind their (already-appended) slot identities; LAUNCH is not
  re-run (the existing `LaunchBindingV3` stays; the extension's calendar revision is bound by the
  extension approval event — recorded in `ExtensionDecisionV3`).

### 8.5 Amendment vs job vs publication (V3-AT-30)

| Race | Fence |
|---|---|
| Amendment vs F's jobs (prefill, thumbnails, teaser cut, rebuild) | `expected_content_revision` at enqueue, admission, and before every canonical mutation under the track SHARE lock (A §7.1); stale results quarantined (`stale_artifacts`); charges stand — the enqueueing handler's accounting, no refund path added |
| Amendment vs release admission | admission holds the same locks in the same order and revalidates the fence inside its transaction — an amendment cannot interleave (A §6/A §7.1) |
| Amendment vs in-flight submit | A §7.3 invalidates queued publication submissions; past-`begin` submissions reconcile; if published: immutable, approval superseded ⇒ changed artifacts refused at any later admission; remedies = metadata policy edits / N11 |
| Reschedule vs in-flight submit | the apply transaction updates in place only rows it can lock in SCHEDULED (not yet submitted — §8.1); a row past `begin` is left to settle and shows on the impact screen as "dispatched — will land on the old date" (typed, operator-visible) |
| Extension vs publication | extension appends; it never rewrites the bound calendar revision — in-flight releases keep their authority; new identities only bind after the extension's own approvals |

## 9. Throughput (MA11; SPEC §9.4)

- **Measured** (F-6, written daily by schedule `w13b-throughput` at 19:05 Asia/Bangkok — a
  **calendar-triggered** schedule (A6b adds calendar triggers — A §A6b row), **ordered after the
  19:00 release instant** — CON-N31): `approved_episodes` (episodes whose **first** Gate 2
  APPROVE fell that day — CON-M29; re-approvals never count), released episodes (all required
  destinations verified), `buffer_days` (§6.3), season cost to date from A's accounts (A2).
  **Rolling aggregates — sustained 7-day rate, catch-up (2-episode days over the last 2 days) —
  are derived on read from the daily rows, never stored** (CON-N3).
- **SLO surface:** the Launch tab shows sustained rate vs **≥1.25 approved episodes/day**,
  catch-up vs **≥2/day for 2 consecutive days**, buffer vs **≥3 days (alert below 2 days)** — bot
  alerts on breach; the operator decides (SPEC §9.4). The **Costs page** (A2's) gains the
  release-phase cost line; the status page shows the same numbers. LIVE acceptance (SPEC §16.3,
  G) reads F-6 — F's obligation is the offline counter + surfaces (V3-AT-29 covers the
  simulation; the live measurement is G's).

## 10. Jobs, schedules, fence, waits

| Job | Queue/lane | Provider | Metering |
|---|---|---|---|
| `release_v3.prefill_metadata` | the existing `production` queue (B §7.2 — verified, CON-N1) | A0 gateway (`llm.subscription`) | unmetered, quota-admitted, `LlmStep` |
| `release_v3.make_thumbnails` | C's `image` lane | Nano Banana seam (C §5) | episode scope: EPISODE account, `step_08`; teaser scope: season-setup sub-budget, `step_10` (§1.15 — CON-M7) |
| `release_v3.teaser_cut` | `release` | none (deterministic assembly of approved artifacts, reusing `S/editing/{edl,export,ffmpeg}.py` — §5) | none |
| `release_v3.rebuild_dated` | `release` | none | none |

**F adds two schedules** to A6b's registry (CON-N8): `w13-release-admission` (5 min; §7.1) and
`w13b-throughput` (daily 19:05 Asia/Bangkok, calendar-triggered, ordered after the 19:00 release
instant; §9).

All jobs carry A §3's `work_scope` (`track = 'release'`, `logical_work_id`,
`expected_content_revision`; date-sensitive jobs also carry `expected_calendar_revision`,
validated at admission and before each mutation — §8.5). Waits project through `track_waits`
(A §3): quota waits (`WAITING_QUOTA`), the image lock (`WAITING_PROVIDER`, C §5), reconcile
blocks. Thumbnail jobs respect the cross-system lock and fairness exactly as C's (no second lock
path).

## 11. UI (tabs 8–10 + Launch; built into the A5 shell)

| Tab | Route | Scope | Progress denominator | Primary action |
|---|---|---|---|---|
| 8 Metadata | `/v3/seasons/{id}/metadata` | episode | slots drafted n/N; thumbnails picked n/N | **Draft** (prefill) — then edits |
| 9 Gate 2 | existing review page, V3 variant | episode | drafts sealed n/N; blockers cleared | the Gate 2 buttons (Approve/Revise/Reject) |
| 10 Teaser | `/v3/seasons/{id}/teaser` | season | plan → cut → inspection → gate | the `TEASER_FINAL` buttons |
| Launch | `/v3/seasons/{id}/launch` | season | calendar proposed → LAUNCH → release board | **Propose calendar**, then the LAUNCH buttons |

The Launch tab carries: the calendar proposal + revision history; the LAUNCH gate with its typed
refusals (the §6.2 conditions: calendar, five approvals, teaser, staleness, capability records —
CON-N24); the **release board** (episode × destination grid: derived
HELD/MISSED/UNVERIFIED-PAST-AIR/PARTIAL/verified, per-slot blockers, retry/reconcile actions);
the reschedule screen (§8.1–§8.3, with the N11 list); the extension screen (§8.4); throughput
(§9). Every screen follows SPEC §3.2's state set and one-primary-action rule; bot alerts link
here.

## 12. F commands (A1 note §6 format)

| Command | Actor | Scope / revision owner | Prerequisites | Effect | Events | Replay identity | Activation |
|---|---|---|---|---|---|---|---|
| `propose_calendar(season, premiere, cadence)` | Operator (human session + CSRF) | season / `season_tracks.revision` | planning ≥ STORY_LOCKED (dates need episode count; SPEC §9.2 item 1 — before editing) | appends `ReleaseCalendarV3` r1; release track → `CALENDAR_PROPOSED` | `release.calendar_proposed` | idempotency key | **F** |
| `decide_launch(...)` (gate) | Operator | season / activation binding | §6.2 conditions | LAUNCH approval + `LaunchBindingV3` + identity allocation + bindings; → `LAUNCH_APPROVED` | `release.launched` | gate idempotency (A §2.6) | **F** |
| `decide_teaser(...)` (gate) | Operator | season / activation binding | cut + inspection + drafts + pick current, spoiler check passes | `TEASER_FINAL` approval | `teaser.final` | gate idempotency | **F** |
| `edit_metadata_draft(episode, slot, fields)` | Operator | episode / draft revision | a Gate 2 activation open for the episode, or pre-activation | appends a draft version | `metadata.draft_edited` | idempotency key | **F** |
| `vote_thumbnail(target, candidate, note)` | Operator | episode/teaser | candidates registered | appends a vote; starts no work | — | idempotency key | **F** |
| `record_caption_route(destination, route)` | Operator (human session + CSRF) | season | O-8 ruled (or a later flip); route `CAPTION_FILES` only where the destination's capability is qualified | appends a `CaptionRouteV3` version (§2); §7.1 item 5 reads the current row | `release.caption_route_recorded` | idempotency key | **F** |
| `propose_reschedule` / `confirm_reschedule(impact_sha256)` | Operator | season / `season_tracks.revision` | a bound calendar exists; LAUNCH_APPROVED/RELEASING | §8.1 apply (**Confirm is Apply** — the confirm command runs the apply transaction) | `release.rescheduled`, `release.corrective_proposed` | idempotency key | **F** |
| `decide_corrective_post(ref, decision)` | Operator | season | a proposed N11 row | `corrective_posts` decision; posting via the ordinary path | `release.corrective_decided` | idempotency key | **F** |
| `decide_extension(windows_read, range, mode)` | Operator | season / `season_tracks.revision` | release RELEASING/COMPLETE; B §8 eligibility | B `create_extension` + calendar revision append + `ExtensionDecisionV3` + extension-identity allocation/binding (§8.4) | `release.extension_decided` | idempotency key | **F** (needs B §8 shipped) |
| `close_out_episode(episode, reason)` | Operator (human session + CSRF) | season | release track `RELEASING` or later; the episode is not `PUBLISHED_VERIFIED` on any destination; typed reason (`WITHDRAWN_BY_OPERATOR` / `UNAIRABLE`) | appends an `EpisodeCloseoutV3` document (§2); the board shows CLOSED OUT; COMPLETE's predicate counts the episode resolved; successors' `depends_on` on it is treated as resolved (the recorded override) | `release.episode_closed_out` | idempotency key | **F** |
| `retry_slot` / `cancel_slot` | existing | — | existing (`service.py:1045,1060`) | existing | existing | existing | today |

## 13. Build packages (in order; `make check` + V1 `make pilot` green at every gate)

**Prerequisites** (each cited to its acceptance artifact — CON-M12): A0–A6 accepted (the A-spec
acceptance rows; build reports `a0d-build-REPORT.md`, `a0r1-build-REPORT.md`, and the A1/A2/A3/A6b
notes); B accepted (B-spec acceptance table; `phase-b-review/`); C accepted (C-spec acceptance
table; `phase-c-review/`). **Phase D** supplies render/QA and requires the T031 qualification
record with `feat/t031-fix3` merged (SPEC §4.6 N36); no phase-D spec exists yet (verified
13 Nov 2026). **Phase E** supplies the edit artifacts the teaser assembles and the caption tracks
Gate 2 checks; no phase-E spec exists yet (verified 13 Nov 2026) — **package F5 is blocked until
E is accepted and its export/caption contract is pinned; F1–F4 build and test offline with seeded
caption tracks** (the `teaser_cut` job reuses the existing deterministic `S/editing` seam, §5,
but its V3 input contract is E's). Real migration numbers allocated in the F1 note from the
migration tail (§ header conventions). **Applied migration bytes are never edited.**

| Package | Builds | Gate | Design note |
|---|---|---|---|
| **F1** | **Create** migrations `F-1..F-8` (§2), the `ReleaseV3Store` (§2) and the contracts bump — `CapabilityLimits` fields (§1.16, FD4), `GateType` values (FD3), pick-engine kinds (FD1), Revise targets (FD5); **Reuse** V1/V2 rows byte-identical (§1.1) | F-T1, F-T11 | **Critiqued first** (migrations + the §2.2 crossing register) |
| **F2** | **Create** the calendar document type, `propose_calendar`, the LAUNCH gate, identity allocation/binding, the buffer rule (§6), the `w13-release-admission` schedule and the per-slot row-creation variant `schedule_release_slot` (§7.1.1); **Reuse** F1's tables — F2's "`publication_admissions`" and calendar mentions are F2's logic over F1's objects, not second creates (CON-M21) | F-T2, F-T3, F-T4 | **Critiqued first** (authority, locks) |
| **F3** | **Create** metadata drafts — prefill job, edit surface, staleness (§3.1, §3.3) — and thumbnail generation/composite/inspection/pick through C's extended engine (§3.2); **Reuse** C's `image` lane + A0's LLM runtime | F-T14 (+ `make check`) | With the diff |
| **F4** | **Create** the Gate 2 V3 flow — prefilled form, pick blocker, seal = edited drafts, later-episode slot binding, typed Revise targets (§4); **Reuse** A's decision transaction + the existing manifest path | F-T5, F-T11 | **Critiqued first** (seal transaction) |
| **F5** | **Create** the teaser — plan, carrier episode + teaser package (§5), cut job (`S/editing` reuse), spoiler check, `TEASER_FINAL`, `PROMO_CUT` identities, premiere gating, recovery options | F-T6 | **Blocked** until the O-8 ruling (§1.9) and E acceptance (above) |
| **F6** | **Create** the derived states + successor holding + near-air bot options + retry/swap/push wiring (§7.2–§7.4) | F-T7, F-T8 | With the diff |
| **F7** | **Create** reschedule + rebuild + N11 corrective posts (§8.1–§8.3) | F-T9 | **Critiqued first** (immutability edges) |
| **F8** | **Create** amendment/extension fences + `ExtensionDecisionV3` + viewership windows + the `CONTINUED`/`RESUMED` modes (§8.4–§8.5) | F-T10 | **Critiqued first** (races — V3-AT-30) |
| **F9** | **Create** throughput counters + Costs/status surfaces + bot alerts (§9) | F-T12 | With the diff |
| **F10** | **Create** tabs 8–10 + Launch UI (§11) | F-T13 | With the diff |

**Routing:** GLM builds each package (`ai-route build -w`); Codex critiques the F1/F2/F4/F7/F8
notes and reviews every diff; one package at a time. T032 gates only *live* publishing (SPEC §15
phase F row) — every F package is offline/mock first.

## 14. Acceptance (offline; real PostgreSQL for every test; **the transaction tests — F-T2, F-T3, F-T4, F-T5, F-T9, F-T10 — additionally assert one-transaction all-or-nothing behavior**; the rest are contract/UI tests — CON-N35)

| Test | Proves |
|---|---|
| F-T1 | Given a populated V1+V2 database, applying `F-1..F-8` ⇒ every migration applies; guards + catalog present; applied-migration rows byte-unchanged; generated contracts show zero drift |
| F-T2 (V3-AT-12; **seeded**) | Seeding: five current Gate-2 approvals produced through the **existing** episode Gate-2 path in OFFLINE_MOCK (today's machinery, FM §2 — stated seeding, not F4's flow). Stimulus: LAUNCH with 4 approved ⇒ typed refusal; with 5 ⇒ LAUNCH proceeds and binds the calendar hash + identities + approval hashes; the teaser instant lands at premiere − 3 days |
| F-T3 (**seeded as F-T2**) | Given a LAUNCH-approved season: dispatch attempted without LAUNCH ⇒ refused; with a superseded/stale calendar revision ⇒ refused at release admission; Reject LAUNCH ⇒ release track returns to `CALENDAR_PROPOSED`, planning track untouched. (Reschedule assertions live in F-T9 — CON-B4.) |
| F-T4 | Each admission check injected in turn (fence mismatch, superseded approval, stale binding, unqualified capability, unmet dependency, caption route unavailable) ⇒ the matching typed refusal; unqualified capability ⇒ HELD, not failed |
| F-T5 (V3-AT-11) | Drafts prefilled from the pack ⇒ the Gate 2 form is prefilled; after edits ⇒ the sealed manifest equals the edited drafts verbatim; Approve with no thumbnail pick ⇒ typed refusal; with a stale pick ⇒ typed refusal; the sealed CTA records its calendar-revision dependency |
| F-T6 (V3-AT-12) | A cut quoting a later reveal ⇒ the spoiler check blocks `TEASER_FINAL`; episode 1 per destination waits until the teaser verifies; a late teaser ⇒ HELD with repair/reschedule options — **repair proven end-to-end here; the reschedule recovery is staged to F-T9** (here: the option is offered and the hold asserted). **Carrier:** the teaser's posts exist as ordinary `platform_posts` rows — carrier episode + teaser package + `TEASER_FINAL` approval satisfy every NOT NULL of the reused table, and the manifest binds (CON-B2) |
| F-T7 (**seeded**) | Seeding: a held dependency; a passed air instant with no post; one verified + one unverified destination. ⇒ HELD/MISSED/PARTIAL (+ `UNVERIFIED-PAST-AIR`) derived per destination from stored rows only; successors hold; no stored side state |
| **F-T8 (V3-AT-29)** | **The 30-episode release simulation — late teaser, rejected episode near air time, zero buffer, partial destination failure, ambiguous publication ⇒ no duplicated post anywhere; re-arm only on proven absence; every recovery offered and operator-approved (push execution itself is F-T9's assertion; here its offer, approval gate and hold — CON-B4)** |
| F-T9 (**seeded**) | Seeding: a launched season mid-RELEASING with to-dispatch, dispatched and published rows. **Two reschedules applied ⇒ still exactly one `platform_posts` row per identity; only the date columns changed; identity columns byte-identical (CON-B1).** Impact lists published inaccurate CTAs; rebuild rewrites only date-bearing content; published rows/objects untouched; the N11 post decides + posts via the ordinary path; an in-flight submit settles and is surfaced on the impact screen |
| **F-T10 (V3-AT-30/31)** | **Races injected — amendment vs F-job completion vs admission vs in-flight submit ⇒ stale results quarantined, old approvals cannot release changed artifacts; extension during RELEASING and after COMPLETE incl. changed cast ⇒ published hashes + authority intact** |
| F-T11 | V1/V2 compatibility: V1/V2 Gate 2, manifests, dated slots and their readers unchanged and readable beside V3 rows; no V3 calendar applied to a historical approval |
| F-T12 (MA11) | Seeded approvals/releases ⇒ counters correct (`approved_episodes` counts first-time Gate-2 approvals per episode); buffer below 2 days ⇒ the alert fires; Costs/status show sustained/catch-up/buffer/cost |
| F-T13 | Tabs 8–10 + Launch: every state in §11 renders; one primary action per screen; admission refusals render typed; bot alerts deduplicated with timeouts (A §8) |
| F-T14 | Drafts/thumbnails without Gate 2 (F3's own gate — CON-B4): one prefill call assembles all slots (disclosure deterministic; hashtags truncated to the effective cap — §1.16); candidates register with `inspection_ref`s; a vote picks and starts no work; staleness computed from stored columns only (§3.3) |

## 15. Open questions (each with a recommendation)

| # | Question | Recommendation |
|---|---|---|
| **O-F1 (O-8)** | **EN/ZH on TikTok/Facebook without caption-file support — the operator decides in phase F. OPEN (operator queue); package F5 is conditionally blocked on this ruling; F1–F4 may proceed (CON-B3).** Options: (a) platform caption files where supported (TT/FB `subtitles_present` readback-unverified — FM §9; needs T032 evidence); (b) burned-in EN/ZH variants as the single post (drops TH burn-in or doubles render; conflicts with the TH-first mix, SPEC §4.7); (c) extra EN/ZH posts (**excluded** by SPEC §9.1 "no extra posts" unless the operator changes it); (d) TH-only on TT/FB, EN/ZH on YouTube via the existing `upload_captions` surface (adapter-verified, not part of submit — FM §9) | **Recommendation only — GLM does not decide:** (d) now, (a) when T032 qualifies it — YouTube delivers real caption tracks post-publish; TT/FB stay TH-only until their caption route is qualified, then a per-destination flip recorded in `CaptionRouteV3` (§2). Keeps one post per destination, no double render, no unverified claims |
| O-F2 | `platform_posts` rows created at release admission (§1.4) vs at LAUNCH | **Resolved in v0.2 (CON-B1/CON-M1): admission-time creation + in-place date UPDATE on un-submitted rows (§1.4)**; the create-at-LAUNCH alternative is evaluated and rejected in §18 (rows would exist with calendar authority only, visible to `w09` before content authority binds) |
| O-F3 | Does the teaser air at 19:00 Asia/Bangkok like episodes? | **Yes** — same daily instant, 3 days earlier; one cadence constant |
| O-F4 | Swap semantics: remap dates vs renumber episodes | **Remap**: episode numbers are immutable identities (continuity, canon); a swap is a calendar revision mapping change, never a renumber |
| O-F5 | N11 corrective post route (community tab vs regular post) per platform | Per-destination capability record decides; offline mock covers both; no auto-fallback — an unqualified corrective route shows as held |
| O-F6 | MA11 window: calendar day vs rolling | Record the **daily snapshot** (19:05, stored in F-6); **derive the rolling 7-day sustained on read** (§9) — the SLO reads the rolling one (SPEC §9.4 "sustained"); nothing rolling is stored (CON-N3) |
| O-F7 | Source of truth for per-platform hashtag/title limits | **Resolved in v0.2 (CON-M13):** the pinned capability record — `CapabilityLimits` gains `max_title_chars`/`max_hashtags` (package F1, §2.2 FD4); effective cap = min(capability, contract); a null capability field ⇒ the contract cap governs; static config only as the mock default |
| O-F8 | SPEC §2.2 cites **N43** for HELD/MISSED/PARTIAL, but N43 is defined nowhere in REQUIREMENTS/DECISIONS (grep verified) | Adopt §7.4's derived per-destination reading; **flag to the orchestrator** to anchor N43 in SPEC (formatting fix, not a design change) |
| O-F9 | One LLM call per episode (all slots/locales) vs per slot | **One per episode** (fewer calls, one quota admission); per-slot split only if F-T14's prefill evidence pack shows per-slot quality divergence (decidable trigger — CON-N34) |
| O-F10 | Rescheduled CTA text: which renewed-approval path applies where | **Resolved in v0.2 (CON-M3): unaired sealed episodes ⇒ metadata-delta Gate 2 re-approval (§8.2's default — the only implementable path pre-publication); published slots ⇒ metadata policy edits / N11 post.** A fresh full Gate 2 only when the operator marks the change substantive at proposal |

## 16. Requirement trace

| Requirement | Section | Package(s) |
|---|---|---|
| R-3.7 (extend after launch) | §8.4 | F8 |
| R-8.1 (LLM per-slot drafts, prefill) | §3.1 | F3 |
| R-8.2 (multi-language caption delivery) | §1.9, §7.1 item 5, §15 O-F1 (package F5 blocked on O-8; production of the tracks: B/E) | F5 |
| R-8.3 (thumbnail generator, 2–3 variants → pick) | §3.2 | F3 |
| R-9.1 (one Gate 2 screen, prefilled, Revise targeted) | §4 | F4 |
| R-9.2 (scheduler posts at the LOCK cadence; held capabilities hold) | §6, §7.1, §7.3 | F2, F6 |
| R-10.1 (teaser cut, own copy + thumbnail) | §5 | F5 |
| R-10.2 (own slot, X days before episode 1, teaser approval) | §5, §6.1 | F2, F5 |
| V3-AT-11 | §3, §4 | F-T5 |
| V3-AT-12 | §5, §6 | F-T2, F-T6 |
| V3-AT-29 | §7 | F-T8 |
| V3-AT-30 | §8.5 | F-T10 |
| V3-AT-31 | §8.4 | F-T10 |
| V3-AT-5 (C-owned — SPEC §15.1 phase C; F reuses only its refusal shape) | §3.2, §3.3 | — |
| V3R-6 (SPEC §4.7/§4.9/§9.2) | §3.1, §6, §8.1 | F2, F7 |
| AR-4 (phase-A-spec architecture-rule appendix: side states are derived, never stored) | §1.10, §7.4, §9 | F6, F9 |
| SPEC §12.6 (amendment integration) | §8.5 | F8 |
| MA11 (throughput) | §9 | F9 |

## 17. Risks and limits (CON-M32, folding CON-M5)

| Risk | Limit / mitigation | Owner |
|---|---|---|
| `w13-release-admission` is a new single point on the publication critical path | the 5-min registry schedule is stateless (due-slot discovery = air instant ≤ now + lead): a missed tick catches up on the next; the bot alerts when a due slot identity has no admission row within 2 ticks (10 min); a down scheduler delays admissions, it never drops them | F2 builder |
| `publication_admissions` REFUSED rows grow unboundedly while a due slot identity stays held (re-refusal every 5 min) | rows stay append-only audit, but the alert collapses to one deduplicated bot alert per identity per day (`admission_refusal_alert_cap`, default 1/day); the board shows only the latest typed reason | F6 builder |
| No mid-RELEASING abort/rollback story | **A's `cancel_season` / `cancel_episode`** (A §2's command table; terminal) **is the abort path**: it cancels queued jobs through the transaction-owned helper and the release board surfaces the held remainder; F adds no second mechanism | Operator |
| Lead time vs predecessor verification latency (episode N's admission hostage to N−1's verify finishing inside the window) | the daily cadence gives each predecessor ~24 h; the exposure is compressed reschedules only — the reschedule impact screen warns when a compression leaves less than `release_admission_lead_seconds` between consecutive episodes, and a successor that misses shows HELD (dependency) with §7.3's options | Operator |
| Security: three new operator-facing surfaces (caption-route record, N11 corrective posts, extension screen) | every surface is a decision/command with human session + CSRF + idempotency (A §2.6, §12); none auto-posts; blast radius = one season | Operator |

Master-level risks and their owners: SPEC §18.

## 18. Alternatives rejected (CON-M31; one per major design choice)

| Choice | Rejected alternative | Why rejected |
|---|---|---|
| One `v3_release_documents` store (F-1) | Per-record tables | mirrors B's/C's stores (B §2/C §2): one guard/hash/allowlist story; per-record tables duplicate the sealing machinery per type |
| `publication_admissions` (F-5) | Reusing `approval_events` | admissions are high-frequency non-decisions (one refusal row per 5-min tick); `approval_events` is A's one-decision-per-revision gate vocabulary (FM §2) — different invariants |
| New `w13-release-admission` schedule (§7.1) | Extending `w09` | `w09`'s discovery is "due SCHEDULED rows" (FM §6); pre-row discovery needs the calendar + slot identities — a different query shape; `w09` stays untouched (§7.1) |
| Calendar as a versioned document (F-1 store) | Date columns on slot rows | SPEC §9.2 makes the revision the authority; columns cannot express proposal, history or impact (FM §4); V1/V2 already pin dates at schedule time by convention |
| Admission-time row creation **+ in-place date UPDATE** on un-submitted rows (§1.4) — adopted (CON-B1/CON-M1) | Create rows at LAUNCH and UPDATE dates on reschedule | rows would exist with calendar authority only and be visible to `w09` before content authority binds; admission-time creation holds both authorities at insert; the UPDATE is safe because dates are not trigger-pinned (`M/0005:77-80`, §1.4) |
| Cancel + re-create on reschedule | — (structurally impossible) | one-way `cancel_slot`, `dedupe_key`/identity UNIQUEs, no CANCELLED→SCHEDULED transition, trigger-immutable `client_token` (CON-B1) — rejected before B1 adopted the in-place UPDATE |
| Synthetic carrier episode + season-scoped teaser package (§5) — adopted (CON-B2 option a) | (b) a parallel season-posts table; (c) relaxing `platform_posts` constraints | (b) a second state machine (violates §1.14); (c) touches the shared V1/V2 table and needs its own §1.1 compatibility argument; the carrier rides the ordinary path with zero new row machinery |
| Extend C's picks engine — `pick_kind THUMBNAIL` (§2.2 FD1) — adopted (CON-M6) | Parallel `thumbnail_candidates`/`thumbnail_votes` tables (v0.1's F-3) | permanent duplication of vote semantics, staleness computation and UI pick patterns; the teaser makes a third consumer of the same pattern |
| `metadata_draft_versions` (F-2) — committed (CON-M15) | Reusing `metadata_versions` | `metadata_versions.platform_post_id` is NOT NULL (`M/0005:85`) — non-viable for drafts that exist pre-post |
| Metadata-delta Gate 2 re-approval as the unaired default (§8.2) — adopted (CON-M3) | Metadata policy edits pre-publication | policy edits require an existing `platform_posts` row (`M/0005:85`) and live-binding equality refuses any drift from the sealed manifest — only Gate 2 APPROVE can rebind pre-publication |
