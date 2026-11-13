# Phase F spec — release: metadata, Gate 2, teaser, calendar, slots, amendment integration (v0.1 DRAFT)

Status: **DRAFT v0.1**, 13 Nov 2026, GLM (weekend runbook). Next: Goldfish (`phase-f-review/`), then a
Codex critique. Binding inputs: `SPEC-v3.md` v0.4.6 (§4.8–4.10, §9, §12.6, §15.1–15.2),
`DECISIONS.md` (V3C-26, Q6, O-8/N35, N11), `phase-A-spec.md` v0.3, `phase-B-spec.md` v0.4,
`phase-A0-spec.md` v0.4, `phase-C-spec.md`, `f-factmap.md` (cited as **FM §n**; spot-checked — every
FM fact relied on below was verified in code unless marked `UNVERIFIED`).

Conventions: `S/` = `microdrama/src/microdrama/`, `M/` = `microdrama/migrations/` (ends at 0025 in
this checkout; 0026–0027 live under `.scratch/a0d-gate/` — FM header). New migrations are symbolic
`F-1…`; real numbers are allocated in the F1 note after re-auditing the tail. Applied migration
bytes are never edited.

## 0. Scope

**Phase F builds tabs 8–10 plus Launch, and the release half of the state model:**

1. **Step 8 (§4.8):** per-slot metadata drafts (prefill → edit → seal) and thumbnail candidates
   (2–3 variants, operator pick) — V3-AT-11, R-8.1, R-8.3.
2. **Step 9 (§4.9):** Gate 2 for V3 episodes through phase A's decision transaction — prefilled
   drafts, the thumbnail pick, caption tracks, later-episode slot binding — R-9.1.
3. **Step 10 (§4.10):** the season teaser contract, `TEASER_FINAL`, the `PROMO_CUT` slot at
   premiere − 3 d, and teaser-gates-premiere — R-10.1, R-10.2, V3-AT-12.
4. **§9.1–9.3:** the versioned release calendar, LAUNCH authority, stable slot identities per
   destination, dispatch admission, predecessor dependencies, HELD/MISSED/PARTIAL handling,
   reschedule + the N11 corrective post — V3-AT-29.
5. **§12.6 / V3C-26:** the release-side amendment fences (publication admission vs job completion
   vs dispatch) and the extension flow's decision screen, calendar continuation and viewership
   windows — V3-AT-30, V3-AT-31, R-3.7.
6. **§9.4 (MA11):** throughput measurement, buffer counters, Costs/status surfaces, bot alerts.
7. **R-8.2 delivery:** EN/ZH caption-track delivery per destination, per the operator's O-8
   decision (§1.9; the decision itself stays open — §14 O-F1).

**Not in F:** caption translation and cue alignment (B's packs carry EN/ZH line text; E's edit
binds tracks to the TH cue timing — V3-AT-10 is E's); the image adapter, cross-system lock and
output inspection (C's — F only calls them); live platform qualification (T032 → G/live);
analytics ingestion (existing W11); the EDL/export tooling the teaser cut assembles from (E's).

## 1. Binding decisions

1. **V1/V2 never change** (B §1.1 / C §1.1 rule). V3 release code lives in new modules
   `S/release_v3/`. Today's publishing machinery is **reused, not forked**: `metadata_versions`,
   `platform_posts`, `approval_events`, `approved_slot_metadata`, `release_approval_manifests`
   and the publishing service's submit/reconcile paths stay the one implementation (FM §1–§2,
   §5). F adds V3 rows and V3-only guards **beside** the V1/V2 rules; no historical row is
   rewritten, and no historical dated approval is reinterpreted against any calendar (§9.2 item 7).
2. **Release authority is two-part.** Content authority = a Gate 2 (or `TEASER_FINAL`) approval
   that is *effective* (A §7.2 `effective_approval` — not superseded) and hash-matches the current
   package. Calendar authority = the LAUNCH decision and the calendar revision it bound. **Dispatch
   requires both** (§9.2 item 5); the check lives in one place, release admission (§7).
3. **The calendar is a versioned document, not slot columns.** `ReleaseCalendarV3` (F-2 store)
   holds the premiere date, the daily 19:00 Asia/Bangkok cadence, the teaser instant
   (premiere − 3 d, 19:00), the episode→date map for every episode number in scope, and a monotone
   revision. It is **proposed before step 7 editing** (release track → `CALENDAR_PROPOSED`). A
   change of any instant is a **new revision** through `reschedule_calendar` (§8) — never an
   in-place edit. Nothing in `platform_posts` is date-authoritative for V3 (§1.5).
4. **V3 `platform_posts` rows are created at dispatch admission**, with the date resolved from the
   bound calendar revision — not at Gate 2 and not at LAUNCH. Reason: `platform_posts` dates are
   pinned at insert and trigger-immutable, and the slot-identity columns carry a hard UNIQUE
   (`M/0005:32-78`; FM §4), so a row written earlier could never be moved or replaced without
   violating one of the two. Creating the row when both authorities already hold means **no V3 row
   is ever rescheduled, rewritten or re-created** — the V1/V2 triggers stay untouched. `ReleaseSlotPlan`
   still requires a `schedule` (`S/contracts/release.py:85`, verified); V3 fills it at admission
   from the calendar. V1/V2 keep pinning at `schedule_release` time (FM §4), unchanged.
5. **LAUNCH is a season gate through A's decision transaction** (A §2.6), binding: the exact
   calendar revision hash, the slot-identity map (§6), and the current approval hashes of **the
   first five consecutive episodes and the teaser** (§9.2 item 3). It is **refused while fewer
   than 5 episodes have current Gate 2 approvals** (O-7; V3-AT-12) or while the teaser approval is
   missing/stale. Reject LAUNCH leaves the release track at `CALENDAR_PROPOSED` without launch
   authority; the planning track is untouched (A §2.2).
6. **Later episodes bind their slot at Gate 2** (N21; §4.9): for episodes after LAUNCH's initial
   five, the Gate 2 APPROVE handler records the binding of that approval to the episode's
   already-allocated slot identities (§6.1). For episodes 1–5 the same binding is recorded by the
   LAUNCH handler. One shape, two writers.
7. **A draft is not an approval.** Metadata drafts and thumbnail picks exist **before** the Gate 2
   activation opens; they carry no release authority of any kind. The sealed manifest equals the
   edited drafts at the moment of Gate 2 APPROVE (V3-AT-11), through the existing manifest path
   (FM §2: `release_approval_manifests`, `md_gate2_manifest_binding`).
8. **Thumbnail pick = the phase C pick pattern** (C §4): generation produces 2–3 candidates; a
   **vote records only and starts no work**; Approve is refused with a typed reason while no
   candidate is picked (or while the pick is stale, §3.3). The picked candidate becomes the cover
   triple (`id/version/sha256`) the existing V2 binding already requires (FM §1).
9. **O-8 stays open; F implements the decision, not the answer.** The operator chooses, per
   destination, between caption-file delivery where the platform supports it and *not delivering*
   EN/ZH there (options and recommendation in §14 O-F1; extra posts are excluded by SPEC §9.1).
   YouTube has a real caption surface today (`upload_captions`, **not part of submit** —
   `S/publishing/youtube/adapter.py:250-258`, FM §9); TikTok/Facebook have none verified. The
   chosen route is recorded per destination and enforced at admission.
10. **HELD / MISSED / PARTIAL are derived, per-destination episode-release states** (SPEC §2.2,
    N43), computed from `platform_posts` rows and the calendar — never stored side state (AR-4).
    The stored per-slot states stay today's enum (`M/0005:51-52`, verified: no PARTIAL/MISSED —
    FM §5). Definitions in §7.4.
11. **A post is never duplicated.** The existing invariants carry over unchanged: unique external
    id per platform+account (`M/0005:76`), idempotent `client_token = hash(dedupe_key,
    package_hash)` (FM §5), reconcile adopts-by-external-id first and **re-arms only a proven-absent
    slot** (FM §5, `S/publishing/service.py:947-980`). F adds no second dedupe mechanism.
12. **Reschedule is calendar authority, not an amendment.** It changes dates, not content: it bumps
    the calendar revision, rebuilds **date-bearing content** (CTA/recap copy that names dates,
    §4.7 SPEC:460-461; teaser instants), and voids the date-stamp of any not-yet-dispatched slot
    binding. It never touches published media, never supersedes a content approval by itself, and
    shares the Confirm-with-impact-hash shape of A §7.3. Content that must materially change still
    goes through Gate 2 (renewed approval, §9.2 item 6).
13. **Amendments fence publication at admission.** Release admission re-validates, in one
    transaction and in A's §6 lock order: the fence (`expected_content_revision`), the effective
    approval, the manifest↔current-metadata equality (FM §2 live binding), **and** the calendar
    revision. An amendment applied anywhere between validation and submit is impossible because
    the track SHARE lock is held through the mutation (A §7.1). A submission already past
    `provider_ops.begin` when an amendment applies is handled by A §7.3 invalidation + the
    existing reconcile; if it published, it stays published (immutable), its approval is
    superseded so **changed artifacts cannot follow it**, and the only remedies are the existing
    metadata policy edits or an N11 corrective post (§8).
14. **No new job system, no new dedupe, no second state machine** (SPEC §10.0). F's jobs are jobs
    + provider operations; F's states are projections; F's queues go through A's four-point
    checklist (A §4; C §1.12 pattern). F adds lanes `release` (admission, calendar ops) —
    thumbnails ride C's `image` lane; the metadata prefill rides A0's LLM runtime on the lane B's
    LLM jobs use (`UNVERIFIED` — B's lane name to be confirmed in the F1 note; the checklist makes
    the name a build-time decision, not a spec fact).
15. **Budgets:** per-episode paid work (thumbnail variants) meters to the episode's EPISODE
    account; season-level paid work (teaser key art) to the SEASON account; step keys `step_08`
    (metadata + thumbnails) and `step_10` (teaser) — final vocabulary allocated in the F1 note
    against A2's step ledger. The metadata prefill is an unmetered `llm.subscription` call
    (A0 §5.1) — quota-admitted, never billed. Unknown price ⇒ refused (C §1.7 rule).

## 2. Records (contract package, guardian-owned bump; symbolic migrations `F-1…`)

Documents live in one new append-only, versioned, hash-sealed store **`v3_release_documents`**
(F-1), mirroring B's `StoryV3Store` / C's `CastV3Store` (C §2): PK `(contract_type, record_id,
version)`, one `current` row, hash re-verified on read, `contract_type` allowlist CHECK,
`record_id = uuid5(RELEASE_V3_NS, "<type>:<season_id>[:<key>]")`. `v2_contract_documents`,
`v3_story_documents`, `v3_cast_documents` are not touched.

| Migration | Object | Decisive columns / rules |
|---|---|---|
| `F-1` | **`v3_release_documents`** | the release document store above; guarded |
| `F-2` | **`metadata_drafts`** | `episode_id`, `slot_key` (destination-scoped: platform + locale + `release_slot` name), `state` (`PREFILLING`/`DRAFT`/`SEALED`/`SUPERSEDED` — a projection of the prefill job + edit commands, never authoritative), `draft jsonb` (typed `MetadataDraftV3`: TH title/caption/description/hashtags/CTA + optional EN/ZH fields + the deterministic disclosure text ref), `prefill_job_id`, `calendar_revision` (the revision the CTA/date text was resolved against), `sealed_manifest_hash` nullable, `sealed_at`; `UNIQUE (episode_id, slot_key)`; append-only versions via `metadata_draft_versions` (or reuse the `metadata_versions` pattern — decided in the F1 note); guarded |
| `F-3` | **`thumbnail_candidates`** + **`thumbnail_votes`** | candidates: `episode_id` (or `teaser` key), `asset_id`, `content_sha256`, `generation_job_id`, `inspection_ref` (C §9 output inspection), `created_at`; votes (append-only): `candidate_id`, `note`, human-session ref — a vote records only (C-2 pattern). The current selection = latest vote |
| `F-4` | **`release_slot_identities`** | `season_id`, `episode_number` (0 = teaser), `platform`, `locale`, `account_ref`, `release_slot` name, `dedupe_key` (computed exactly as `ReleaseSlotKey.canonical_hash`, `S/contracts/release.py:74-76`, verified), `calendar_revision_allocated`, `bound_approval_event_id` nullable, `bound_calendar_revision` nullable, `platform_post_id` nullable (set once, at admission); `UNIQUE (season_id, episode_number, platform, locale, account_ref, release_slot)`; `dedupe_key UNIQUE`; guarded, no-delete |
| `F-5` | **`publication_admissions`** (append-only) | one row per admission decision: `slot_identity_id`, `calendar_revision`, `content_revision`, `approval_event_id`, `manifest_hash`, `admitted_at`, `outcome` (`CREATED_POST`/`REFUSED` + typed reason); the audit trail behind §7 and V3-AT-30 |
| `F-6` | **`release_throughput_observations`** | `season_id`, `observation_date`, `approved_episodes` (first-time Gate 2 approves per content revision), `released_episodes` (episodes reaching all-required-destinations verified), `buffer_days` (approved-and-unreleased ÷ 1 required/day), `sustained_rate_7d`, `catchup_2d`, `cost_to_date`; written daily by the throughput schedule (§9); append-only |
| `F-7` | **`corrective_posts`** | `season_id`, `trigger_kind` (`RESCHEDULE_N11`), `calendar_revision_pair`, `inaccurate_cta_refs jsonb` (the published posts whose CTA text the change made inaccurate), `decision` (`PROPOSED`/`APPROVED`/`POSTED`/`DECLINED`), approval refs; append-only decisions |
| `F-8` | lane + queue plumbing | `jobs.queue` CHECK gains `release`; reservations/charges + `budget/policy.py` ownership + worker set + generated contracts (A §4 checklist) |

**Documents in `v3_release_documents`:**

| Record | Key | Content |
|---|---|---|
| `ReleaseCalendarV3` | `calendar` (versions = revisions) | premiere date; cadence (daily 19:00 Asia/Bangkok); teaser instant; the episode→air-instant map for **every** episode number in the current scope (base season; extension ranges append via new revisions — §8.4); the extension calendar mode (`CONTINUED`/`RESUMED`) when applicable; `calendar_hash` over all of the above |
| `SeasonTeaserPlanV3` | `teaser-plan` | source episodes (approved-only refs), the spoiler limit (from B's beat/reveal vocabulary — the plan names the latest reveal it may show), duration target 30–60 s, the release obligation (PROMO_CUT at premiere − 3 d per destination), own copy + thumbnail refs |
| `LaunchBindingV3` | `launch:<content_revision>` | the calendar revision + `calendar_hash`, the slot-identity set allocated, the approval hashes bound (eps 1–5 + teaser), the LAUNCH approval event ref |
| `RescheduleImpactV3` | `reschedule:<old>:<new>` | the proposed revision pair, per-slot effects (to-dispatch: date change; dispatched-not-published: cancel + re-admit; published: untouched), the rebuilt date-bearing content list, the inaccurate-published-CTA list (N11 input), `impact_sha256` |
| `ExtensionDecisionV3` | `extension:<extension_id>` | V3C-26 decision record: the B `create_extension` ref, continued/resumed calendar choice, the viewership-window evidence (per-episode H24/H72/D7 from `performance_snapshots`, `M/0005:204-227` — FM §10, with freshness), the operator rationale |

**Reused unchanged:** `metadata_versions` + `ApprovedMetadataPolicy` (post-approval edits,
`S/publishing/metadata.py:29-37,78-140`, FM §1), `platform_posts` + the publishing service,
`approval_events` (+ A's V3 gate columns), `approved_slot_metadata` / `release_approval_manifests`
/ `md_gate2_manifest_binding` (M/0021 — verified objects), `performance_snapshots`, the
outbox + bot (A §8), the schedule registry (A6b).

## 3. Step 8: metadata and thumbnail drafts (V3-AT-11; R-8.1, R-8.3)

### 3.1 Drafts

- **One draft per destination slot** (`metadata_drafts` row per (episode, slot_key)), in TH, with
  EN/ZH fields where the destination supports them (§1.9). Fields: title (≤200), caption and
  description (≤5000), hashtags (≤ the platform limit — from the pinned capability record, §14
  O-F7; the contract cap of 30 stays, `S/contracts/release.py:367` verified), CTA, AI-disclosure
  text. Grounded in B's episode pack; **no spoilers beyond the episode** (the prefill prompt takes
  the pack's own reveal boundary as input; deterministic lint refuses draft text that quotes lines
  from later episodes — sources list in the prompt contract).
- **The CTA is resolved from the calendar revision the draft records a dependency on** (SPEC
  §4.7:460-461): the next air time, a confirmed continuation, or the finale follow message — never
  an unapproved extension. `metadata_drafts.calendar_revision` is that dependency record (SPEC
  §9.2 item 1's "date-bearing content records its dependency on the revision"); a calendar bump
  marks dependent drafts stale (rebuilt in §8.2).
- **Prefill** is one `release_v3.prefill_metadata` job per episode (all slots in one job): an A0
  `LlmStep` call (A0 §5.1 — frozen call, resumable, quota-admitted, unmetered) plus deterministic
  assembly (disclosure text from the capability/disclosure config — **never LLM output**; hashtag
  truncation to the platform limit; CTA from the calendar). One call per episode, all locales and
  slots in the result (§14 O-F9).
- **Edit surface** = tab 8: every field editable while the Gate 2 activation for the episode is
  open; edits append draft versions; nothing here starts paid work.

### 3.2 Thumbnails (R-8.3)

1. A `release_v3.make_thumbnails` job produces **2–3 key-art variants (default 3** — SPEC §4.8; the
   count is config so R-8.3's "2–3" and the job's default agree) through C's image adapter
   (Nano Banana seam, cross-system lock + fairness, metering, provenance — C §5) from **locked
   assets only** (the current cast-lock bindings).
2. The job composites the **Thai title locally** with the licensed font (O-3 provenance record;
   no provider call), runs **output inspection** (C §9) on each variant, and registers the
   candidates in `thumbnail_candidates` with inspection refs. Failed inspection ⇒ the candidate is
   not registered (it exists as quarantined job evidence).
3. **Pick** = a `thumbnail_votes` row (vote records only). Approve at Gate 2 is refused with a
   typed list while the episode (or teaser) has no current pick, or while the pick's candidate is
   stale (§3.3).
4. The picked candidate becomes the cover triple + rights in the sealed
   `ApprovedSlotMetadata` (the existing required shape, `S/contracts/v2.py:857-860` — verified),
   re-checked at submit exactly as today (FM §1).

### 3.3 Staleness

A draft or thumbnail pick is **stale** when: the episode's `content_revision` moved (amendment,
Revise); the pack version it was generated from is no longer current; or (drafts) the recorded
`calendar_revision` is no longer the bound revision. Staleness is computed from stored columns,
never a stored flag (C §4 pattern). A stale draft must be re-prefilled/edited; a stale pick must be
re-voted; **Gate 2 APPROVE refuses on any stale dependent** (typed list) — the same refusal shape
as C's lock (C §4, V3-AT-5).

## 4. Step 9: Gate 2 in V3 (R-9.1; V3-AT-2)

- **The gate runs through phase A's decision transaction** (A §2.6): idempotency replay, scope
  locks, activation + binding hash + authoritative content revision comparison (stale page refused),
  conditions, the approval event, the handler callback, the idempotent response — one transaction,
  all-or-nothing.
- **What carries over from V2 exactly** (FM §2, verified): the manifest binding
  (`release_approval_manifests`, `md_gate2_manifest_binding` — only Gate 2 APPROVE binds a release
  manifest; manifest covers every current slot with exact (metadata_id, version, content_sha256));
  the human-session/CSF rules (`actor_owner_id` + `actor_session_id`, `require_human_owner`);
  `gate2_blockers` emptiness (QA findings, per-asset hash + persisted-object verification, policy
  hash, no live pod leases — `S/review/gate_conditions.py:118-190`); the **caption-alignment guard**
  ("a current caption track is not aligned to actual audio", `M/0008:24-34`); live-approve
  requires the manifest, OFFLINE_MOCK exempt.
- **What changes for V3:** (a) the form is **prefilled from `metadata_drafts`** (V3-AT-11) — the
  sealed `ApprovedSlotMetadata` per slot is the edited draft, verbatim; (b) **the thumbnail pick is
  a blocker** (§3.2); (c) the handler records the **slot binding** for later episodes (§1.6) and
  the calendar-revision dependency of the sealed CTA; (d) recaps/CTA previews and costs join the
  existing page (SPEC §4.9); (e) Revise uses `season_revision_notes` with typed targets — "regen
  noted units only": a note targeting `metadata` re-prefills drafts, targeting `thumbnail`
  re-rolls candidates, targeting content routes to the owning phase's amendment path (A §2.2).
- **V1/V2 history stays readable, not reinterpreted:** V3 Gate 2 writes V3 rows beside the
  existing ones; V1/V2 approval events, manifests and dated slots keep their exact semantics and
  readers (no V3 calendar is ever applied to them — §1.4). Compatibility test F-T11 pins this.
- The **episode-1 identity-lock hook never fires for V3** (C §1.8: CAST LOCK replaced it).

## 5. Step 10: teaser (V3-AT-12; R-10.1, R-10.2)

- **`SeasonTeaserPlanV3`** (F-2): multi-episode sources (approved episodes only — the plan refuses
  unapproved sources), the spoiler limit (the latest reveal it may show, expressed against B's
  beat/reveal vocabulary), 30–60 s, hook-led, its own copy + thumbnail (a draft set + candidates
  exactly like an episode's — §3, keyed `teaser`), and the release obligation: one `PROMO_CUT`
  slot per destination at **premiere − 3 days, 19:00 Asia/Bangkok** (§14 O-F3).
- **`TEASER_FINAL`** is a season-scoped gate through A's decision transaction (values from A §2.1).
  It approves teaser *content*: the cut, its metadata drafts, its thumbnail pick. It binds nothing
  calendular — the teaser's slot identities and instant come from the calendar revision that
  LAUNCH binds.
- **The cut** is a `release_v3.teaser_cut` job: deterministic assembly from the source episodes'
  approved edit artifacts (E's EDL/export outputs) per the plan — no new provider, no new budget
  line beyond the key art (§1.15). The spoiler limit is enforced by a deterministic check (cut
  segments must precede the limit's reveal point) — a violation blocks `TEASER_FINAL` with a typed
  blocker.
- **The teaser gates the premiere per destination** (SPEC §9.3): episode 1's slot identity per
  destination declares `depends_on` the teaser's slot identity on the **same destination**
  (`depends_on` semantics = "dedupe_keys that must be PUBLISHED_VERIFIED first",
  `S/contracts/release.py:86-88`, verified; the check at submit is `S/publishing/service.py:654-668`,
  verified). The teaser itself has no predecessor.
- **Late or failed teaser ⇒ the premiere holds.** If the teaser instant passes without a verified
  teaser post on a destination, that destination's episode-1 admission refuses (dependency not
  `PUBLISHED_VERIFIED`) and the episode shows **HELD (teaser)** in the derived state (§7.4). The
  bot alert offers exactly two recoveries, both operator-approved (SPEC §9.3):
  1. **Repair:** fix the teaser (re-cut job + `TEASER_FINAL` re-approval), then the premiere
     proceeds on the original dates — legal only while the premiere instant has not passed;
  2. **Reschedule:** `reschedule_calendar` moves teaser + premiere (new revision; date-bearing
     content rebuilt; §8.2) — the path when the premiere instant already passed (the episode is
     then MISSED on that destination, §7.4, and the calendar must move).

## 6. Calendar, LAUNCH, slots (V3R-6; V3-AT-12)

### 6.1 Slot identities (§9.1)

- **Allocation:** LAUNCH allocates one `release_slot_identities` row per (episode number in the
  calendar revision × destination {YOUTUBE, TIKTOK, FACEBOOK} × locale th-TH × the season's
  account) with `slot_kind FULL_EPISODE` for episodes and `PROMO_CUT` for the teaser
  (`SlotKind` values exist, `S/contracts/enums.py:430-434` — verified). Identities are **stable**:
  they survive reschedules (only their `bound_calendar_revision` changes) and are never deleted.
  A later calendar revision may only **append** identities (extension episodes) or re-bind —
  never renumber.
- **Binding:** `bound_approval_event_id` + `bound_calendar_revision` are set by LAUNCH (teaser +
  eps 1–5) or by later Gate 2 (eps 6+). Admission requires a current binding whose approval is
  effective and hash-matches.
- **Slot matrix per destination:** exactly one full-episode post, TH (§9.1); EN/ZH as caption
  tracks per the O-8 decision (§1.9, §14 O-F1); disclosures ≥1 with MD-015 mandatory (the existing
  plan validator, `S/contracts/release.py:93-101` — verified); capability pin from the destination's
  current capability record. **Instagram is excluded** (Q6/DECISIONS:61).

### 6.2 LAUNCH

`LAUNCH` runs through A's decision transaction with conditions (all must hold, typed refusals):

1. a calendar revision is current and its premiere lies in the future;
2. **≥5 episodes have current Gate 2 approvals** (O-7; V3-AT-12) — the first five consecutive
   episodes by number;
3. the teaser has a current `TEASER_FINAL` approval;
4. the drafts/picks bound for eps 1–5 + teaser are not stale (§3.3);
5. every destination capability record for a required route is qualified — an unqualified
   capability (e.g. Facebook AI disclosure until T032) **does not block LAUNCH**; it holds that
   destination's slots (§7.3), because Instagram-level exclusion is a matrix decision, not a
   per-run one.

APPROVE writes the approval event + `LaunchBindingV3`, allocates identities, records the bindings,
and moves the release track `CALENDAR_PROPOSED → LAUNCH_APPROVED`. RELEASING begins at the first
verified publication (derived), COMPLETE when every in-scope episode is verified or explicitly
closed out on every destination.

### 6.3 Buffer

The buffer rule is enforced at LAUNCH (≥5 approved = first five) and monitored during RELEASING:
`buffer_days` (F-6) = approved-and-unreleased episodes ÷ 1 per day; **alert below 2 days**
(SPEC §9.4), bot alert only — the operator decides (pace, parallelism, start date).

## 7. Dispatch, dependencies, failures (V3-AT-29)

### 7.1 Admission (one transaction, A §6 lock order)

A new schedule **`w13-release-admission`** (5 min; registered in A6b's registry — FM §6 lists
today's 14) discovers due slot identities (air instant ≤ now + lead, e.g. 10 min), and for each,
under the season track lock:

1. **fence:** `expected_content_revision` equality (A §7.1);
2. **content authority:** `effective_approval` for the episode's Gate 2 (A §7.2) and the package
   hash match;
3. **calendar authority:** LAUNCH binding current; the identity's `bound_calendar_revision` equals
   the current revision; the air instant matches the current revision's map;
4. **live binding:** manifest ↔ current metadata equality (FM §2 — existing
   `validate_live_release_metadata` semantics, `S/contracts/v2.py:940-965` verified; OFFLINE_MOCK
   exempt);
5. **caption route:** the O-8 route recorded for the destination is available; a route that needs
   an unqualified capability holds instead (§7.3);
6. **dependencies:** predecessor + teaser `depends_on` verified (existing check semantics).

All hold ⇒ **create the `platform_posts` row** (SCHEDULED, date from the calendar, plan built with
`schedule_release`-equivalent fields), set `platform_post_id` on the identity, append
`publication_admissions (CREATED_POST)`, and enqueue `publish.submit_slot` — the existing W09
(unchanged; FM §6) then submits it through the ordinary command path. Any refusal ⇒
`publication_admissions (REFUSED, reason)`; the derived state shows the typed cause. **W09 is not
modified** — it only ever sees ordinary SCHEDULED rows.

### 7.2 Predecessor dependencies per destination (§9.3)

Episode N's identity per destination depends on episode N−1's identity on the same destination;
episode 1 depends on the teaser's identity on the same destination. The calendar's episode→date
map normally makes predecessors air earlier; the dependency still enforces order when reschedules
compress dates. Successor holding is *derived* (a slot whose dependency is HELD/MISSED waits —
existing `PolicyDenied` "this slot waits" semantics at submit, `S/publishing/service.py:663-668`,
verified — plus the admission-time check).

### 7.3 HELD, and the near-air-time options (§9.3)

- **Destination blockers** (capability stale/unavailable, unsupported disclosure, mock metadata on
  live routes) keep today's `HeldSlot` semantics: **the slot HELDs, the episode does not fail**
  (`S/publishing/service.py:101-102`, verified); `retry_held_slot` re-checks the destination and
  returns HELD→SCHEDULED only when the checks now pass (`service.py:1060-1068`, verified). T032
  qualifying a held capability is exactly this retry — no code change beyond the qualification.
- **A rejected or unready episode near its air time** (admission due within the horizon with no
  current Gate 2, an open Revise, or stale dependents): the derived episode state goes **HELD**,
  successors (same destination) hold, and the bot alert offers three operator-approved options
  (SPEC §9.3): **repair** (Revise/amendment path, then re-admission), **swap** (a later approved
  episode takes this date via a calendar revision that remaps episode→date — numbers immutable,
  §14 O-F4), **push** (`reschedule_calendar` for the affected tail). No option is automatic.

### 7.4 Derived per-destination episode states (N43; §2.2)

Computed from `platform_posts` + admissions + calendar, per destination:

| State | Meaning |
|---|---|
| `HELD` | admission refused or slot HELD with a typed blocker (capability, dependency, teaser, authority) |
| `MISSED` | air instant passed with no verified post and no admission in flight (the calendar moved on; recovery is reschedule) |
| `PARTIAL` | ≥1 destination verified, ≥1 required destination not verified (retry/reconcile per destination; SPEC §9.3) |

The season/episode tracks keep the stored coarse states (A §3); these three are display + bot
projections (AR-4), defined once here because SPEC §2.2 cites N43, which is not defined in
REQUIREMENTS/DECISIONS (grep verified — §14 O-F8 flags the anchor).

### 7.5 Never duplicated; proven absence re-arms

Carried over verbatim from today (FM §5, verified): unique external id per platform+account;
idempotent client token per (slot, package); 3-phase crash-safe submit with
`PUBLISH_DEADLINE_MS`/`MAX_SUBMIT_ATTEMPTS`; ambiguous ⇒ `NEEDS_RECONCILIATION`; reconcile adopts
a found post by external id, or **re-arms only a proven-absent** slot (same token, capped). F adds
no new path; the 30-episode simulation (F-T5) exercises all of them.

## 8. Reschedule, corrective post, amendment, extension (V3C-26; V3-AT-30/31)

### 8.1 Reschedule (§9.2 item 6)

`propose_reschedule` builds `RescheduleImpactV3` (typed effects per slot identity: to-dispatch /
dispatched-not-published / published-untouched; the date-bearing content to rebuild; the
**inaccurate published CTAs** — published posts whose CTA text names an instant the change moves,
found by re-resolving each published CTA against the new revision). **Confirm** requires the human
session, CSRF, and the shown `impact_sha256` + scope revision, both revalidated in the apply
transaction (A §7.3 shape). **Apply** (one transaction): append the new calendar revision; cancel
dispatched-not-published V3 posts (cancel_slot; their identities' `platform_post_id` clears for
re-admission under the new revision); mark dependent drafts stale. **Published media is immutable**
— no row, asset or platform object is touched.

### 8.2 Rebuilding date-bearing content

A `release_v3.rebuild_dated` job re-resolves CTA/date text for stale drafts (deterministic from
the new revision; no LLM), re-runs the thumbnail composite only if the art itself embeds a date
(operator choice at proposal; default: key art carries no dates). Renewed **content** approval:
if the CTA text change is substantive for a sealed manifest, the affected episodes need a fresh
Gate 2 decision (a scoped, cheap re-approval of the metadata-only delta — the amendment
coordinator's metadata rebuild branch, SPEC §12.6 item 6, drives it; §14 O-F10 keeps the
substantive/non-substantive boundary question).

### 8.3 Corrective community post (N11)

The reschedule screen lists the inaccurate published CTAs (from §8.1) with a proposed corrective
post per platform (community post / regular post per the destination's qualified capability —
O-F5). `corrective_posts` records the operator decision; posting rides the ordinary publication
path with its own slot identity (`PROMO_CUT`-kind, `corrective` release-slot name) and the same
verification rules. Nothing auto-posts.

### 8.4 Extension (V3C-26; V3-AT-31)

- **Decision screen (F owns; B §8):** per-episode viewership windows H24/H72/D7 from
  `performance_snapshots` (FM §10) with freshness and unknowns shown; the operator picks
  continued vs resumed and the range. APPROVE ⇒ B's `create_extension(season, range, calendar)`
  (B §9, verified row) + F appends a calendar revision carrying the extension's episode→date map
  and mode. **Extension is always a manual decision** (SPEC §4.3).
- **During release or after completion:** from `RELEASING` or `COMPLETE`; existing approvals,
  published hashes and authority remain intact (the extension scope has its own planning track —
  A §3; B's builder runs on it with the planned-terminal + published canon inputs, B §8).
- **Changed cast:** new packs bind explicit cast versions; only new assets need picks (B §8). The
  fence guarantees stale results and old approvals cannot release changed artifacts (§8.5) —
  V3-AT-31's proof.
- New episodes' Gate 2 decisions bind their (already-appended) slot identities; LAUNCH is not
  re-run (the existing `LaunchBindingV3` stays; the extension's calendar revision is bound by the
  extension approval event — recorded in `ExtensionDecisionV3`).

### 8.5 Amendment vs job vs publication (V3-AT-30)

| Race | Fence |
|---|---|
| Amendment vs F's jobs (prefill, thumbnails, teaser cut, rebuild) | `expected_content_revision` at enqueue, admission, and before every canonical mutation under the track SHARE lock (A §7.1); stale results quarantined (`stale_artifacts`), money accounted |
| Amendment vs admission | admission holds the same locks in the same order and revalidates the fence inside its transaction — an amendment cannot interleave (A §6/A §7.1) |
| Amendment vs in-flight submit | A §7.3 invalidates queued publication submissions; past-`begin` submissions reconcile; if published: immutable, approval superseded ⇒ changed artifacts refused at any later admission; remedies = metadata policy edits / N11 |
| Reschedule vs in-flight submit | reschedule's apply transaction cancels only rows it can lock in SCHEDULED (not yet submitted); a row past `begin` is left to settle and shows on the impact screen as "dispatched — will land on the old date" (typed, operator-visible) |
| Extension vs publication | extension appends; it never rewrites the bound calendar revision — in-flight releases keep their authority; new identities only bind after the extension's own approvals |

## 9. Throughput (MA11; §9.4)

- **Measured** (F-6, written daily by schedule `w13b-throughput` at 19:05 Asia/Bangkok, after the
  day's release instant): first-time Gate 2 approves per episode (sustained 7-day rate and daily),
  released episodes (all required destinations verified), `buffer_days`, catch-up capacity
  (2-episode days over the last 2 days), season cost to date from A's accounts (A2).
- **SLO surface:** the Launch tab shows sustained rate vs **≥1.25 approved episodes/day**, catch-up
  vs **≥2/day for 2 consecutive days**, buffer vs **≥3 days (alert <2)** — bot alerts on breach;
  the operator decides (SPEC §9.4). The **Costs page** (A2's) gains the release-phase cost line;
  the status page shows the same numbers. LIVE acceptance (§16.3, G) reads F-6 — F's obligation is
  the offline counter + surfaces (V3-AT-29 covers the simulation; the live measurement is G's).

## 10. Jobs, fence, waits

| Job | Queue/lane | Provider | Metering |
|---|---|---|---|
| `release_v3.prefill_metadata` | B's LLM lane (name per F1 note) | A0 gateway (`llm.subscription`) | unmetered, quota-admitted, `LlmStep` |
| `release_v3.make_thumbnails` | C's `image` lane | Nano Banana seam (C §5) | EPISODE/SEASON account, `step_08` |
| `release_v3.teaser_cut` | `release` | none (deterministic assembly of approved artifacts) | none |
| `release_v3.rebuild_dated` | `release` | none | none |

All carry A §3's `work_scope` (`track = 'release'`, `logical_work_id`, `expected_content_revision`;
date-sensitive jobs also carry `expected_calendar_revision`, validated at admission and before
each mutation — §8.5). Waits project through `track_waits` (A §3): quota waits
(`WAITING_QUOTA`), the image lock (`WAITING_PROVIDER`, C §5), reconcile blocks. Thumbnail jobs
respect the cross-system lock and fairness exactly as C's (no second lock path).

## 11. UI (tabs 8–10 + Launch; built into the A5 shell)

| Tab | Route | Scope | Progress denominator | Primary action |
|---|---|---|---|---|
| 8 Metadata | `/v3/seasons/{id}/metadata` | episode | slots drafted n/N; thumbnails picked n/N | **Draft** (prefill) — then edits |
| 9 Gate 2 | existing review page, V3 variant | episode | drafts sealed n/N; blockers cleared | the Gate 2 buttons (Approve/Revise/Reject) |
| 10 Teaser | `/v3/seasons/{id}/teaser` | season | plan → cut → inspection → gate | the `TEASER_FINAL` buttons |
| Launch | `/v3/seasons/{id}/launch` | season | calendar proposed → LAUNCH → release board | **Propose calendar**, then the LAUNCH buttons |

The Launch tab carries: the calendar proposal + revision history; the LAUNCH gate with its typed
refusals (buffer, teaser, staleness); the **release board** (episode × destination grid: derived
HELD/MISSED/PARTIAL/verified, per-slot blockers, retry/reconcile actions); the reschedule screen
(§8.1–8.3, with the N11 list); the extension screen (§8.4); throughput (§9). Every screen follows
§3.2's state set and one-primary-action rule; bot alerts link here.

## 12. F commands (A1 note §6 format)

| Command | Actor | Scope / revision owner | Prerequisites | Effect | Events | Replay identity | Activation |
|---|---|---|---|---|---|---|---|
| `propose_calendar(season, premiere, cadence)` | Operator (human session + CSRF) | season / `season_tracks.revision` | planning ≥ STORY_LOCKED (dates need episode count; SPEC §9.2 item 1 — before editing) | appends `ReleaseCalendarV3` r1; release track → `CALENDAR_PROPOSED` | `release.calendar_proposed` | idempotency key | **F** |
| `decide_launch(...)` (gate) | Operator | season / activation binding | §6.2 conditions | LAUNCH approval + `LaunchBindingV3` + identity allocation + bindings; → `LAUNCH_APPROVED` | `release.launched` | gate idempotency (A §2.6) | **F** |
| `decide_teaser(...)` (gate) | Operator | season / activation binding | cut + inspection + drafts + pick current, spoiler check passes | `TEASER_FINAL` approval | `teaser.final` | gate idempotency | **F** |
| `edit_metadata_draft(episode, slot, fields)` | Operator | episode / draft revision | a Gate 2 activation open for the episode, or pre-activation | appends a draft version | `metadata.draft_edited` | idempotency key | **F** |
| `vote_thumbnail(target, candidate, note)` | Operator | episode/teaser | candidates registered | appends a vote; starts no work | — | idempotency key | **F** |
| `propose_reschedule` / `confirm_reschedule(impact_sha256)` | Operator | season / `season_tracks.revision` | a bound calendar exists; LAUNCH_APPROVED/RELEASING | §8.1 apply | `release.rescheduled`, `release.corrective_proposed` | idempotency key | **F** |
| `decide_corrective_post(ref, decision)` | Operator | season | a proposed N11 row | `corrective_posts` decision; posting via the ordinary path | `release.corrective_decided` | idempotency key | **F** |
| `decide_extension(windows_read, range, mode)` | Operator | season / `season_tracks.revision` | release RELEASING/COMPLETE; B §8 eligibility | B `create_extension` + calendar revision append + `ExtensionDecisionV3` | `release.extension_decided` | idempotency key | **F** (needs B §8 shipped) |
| `retry_slot` / `cancel_slot` | existing | — | existing (`service.py:1045,1060`) | existing | existing | existing | today |

## 13. Build packages (in order; `make check` + V1 `make pilot` green at every gate)

Prerequisites: A0–A6 accepted; B, C, **E** accepted (D supplies render/QA; E supplies the edit
artifacts the teaser assembles and the caption tracks Gate 2 checks). Real migration numbers
allocated in the F1 note after re-auditing the tail. **Applied migration bytes are never edited.**

| Package | Builds | Gate | Design note |
|---|---|---|---|
| **F1** | Records + migrations `F-1..F-8`; contracts bump; `ReleaseV3Store`; V1/V2 byte-identity | F-T1, F-T11 | **Critiqued first** (migrations) |
| **F2** | Calendar document + `propose_calendar` + LAUNCH gate + identity allocation/binding + buffer rule + `w13-release-admission` + `publication_admissions` | F-T2, F-T3, F-T4 | **Critiqued first** (authority, locks) |
| **F3** | Metadata drafts + prefill job + thumbnails (variants, composite, inspection, votes) + staleness | F-T5 | With the diff |
| **F4** | Gate 2 V3: prefill, pick blocker, seal = drafts, later-episode slot binding, Revise targets | F-T5, F-T11 | **Critiqued first** (seal transaction) |
| **F5** | Teaser: plan, cut job, spoiler check, `TEASER_FINAL`, PROMO_CUT identities, premiere gating, recovery | F-T6 | With the diff |
| **F6** | HELD/MISSED/PARTIAL derivation + successor holding + near-air bot options + retry/swap/push wiring | F-T7, F-T8 | With the diff |
| **F7** | Reschedule + rebuild + N11 corrective posts | F-T9 | **Critiqued first** (immutability edges) |
| **F8** | Amendment/extension fences + `ExtensionDecisionV3` + viewership windows | F-T10 | **Critiqued first** (races — V3-AT-30) |
| **F9** | Throughput counters + Costs/status surfaces + bot alerts | F-T12 | With the diff |
| **F10** | Tabs 8–10 + Launch UI (all screens, states, events) | F-T13 | With the diff |

**Routing:** GLM builds each package (`ai-route build -w`); Codex critiques the F1/F2/F4/F7/F8
notes and reviews every diff; one package at a time. T032 gates only *live* publishing (SPEC §15
phase F row) — every F package is offline/mock first.

## 14. Acceptance (offline; real PostgreSQL for every transaction test)

| Test | Proves |
|---|---|
| F-T1 | `F-1..F-8` apply on a populated V1+V2 database; guards + catalog; applied migrations unchanged; no generated-contract drift |
| F-T2 (V3-AT-12) | **Teaser scheduled at premiere − 3 d; the buffer rule blocks a start date with fewer than 5 approved episodes** (4 approved ⇒ typed refusal; 5 ⇒ LAUNCH proceeds); LAUNCH binds calendar hash + identities + approval hashes |
| F-T3 | Calendar authority: dispatch refused without LAUNCH; a superseded/stale calendar revision refused at admission; Reject LAUNCH → `CALENDAR_PROPOSED`, planning untouched; reschedule never rewrites a `platform_posts` row (V1/V2 rows byte-identical) |
| F-T4 | Admission refuses typed: fence mismatch, superseded approval, stale binding, unqualified capability (held, not failed), unmet dependency, caption route unavailable |
| F-T5 (V3-AT-11) | **Drafts prefill Gate 2; the sealed manifest equals the edited drafts; Approve refused without a thumbnail pick; a stale pick refused; the CTA records its calendar dependency** |
| F-T6 (V3-AT-12) | Teaser: spoiler check blocks a late-reveal cut; episode 1 waits per destination until the teaser verifies; late teaser → HELD with repair/reschedule options, both approved paths work |
| F-T7 | Derived states: HELD/MISSED/PARTIAL per destination from stored rows only; successors hold; no stored side state |
| **F-T8 (V3-AT-29)** | **The 30-episode release simulation: late teaser, rejected episode near air time, zero buffer, partial destination failure, ambiguous publication — no duplicated post anywhere; re-arm only on proven absence; every recovery operator-approved** |
| F-T9 | Reschedule: impact lists published inaccurate CTAs; rebuild rewrites only date-bearing content; published rows/objects untouched; N11 post decides + posts via the ordinary path; in-flight submit settles and is surfaced |
| **F-T10 (V3-AT-30/31)** | **Races: amendment vs F-job completion vs admission vs in-flight submit — stale results quarantined, old approvals cannot release changed artifacts; extension during RELEASING and after COMPLETE incl. changed cast; published hashes + authority intact** |
| F-T11 | V1/V2 compatibility: V1/V2 Gate 2, manifests, dated slots and their readers unchanged and readable beside V3 rows; no V3 calendar applied to historical approvals |
| F-T12 (MA11 surface) | Throughput counters correct against seeded approvals/releases; buffer alert fires below 2; Costs/status show sustained/catch-up/buffer/cost |
| F-T13 | Tabs 8–10 + Launch: every state in §11; one primary action; admission refusals render typed; bot alerts deduplicated with timeouts (A §8) |

## 15. Open questions (each with a recommendation)

| # | Question | Recommendation |
|---|---|---|
| **O-F1 (O-8)** | **EN/ZH on TikTok/Facebook without caption-file support — the operator decides in phase F.** Options: (a) platform caption files where supported (TT/FB: `subtitles_present` is readback-unverified today — FM §9; needs T032 evidence); (b) burned-in EN/ZH variants as the single post (drops TH burn-in or doubles render; conflicts with the TH-first mix, SPEC §4.7); (c) extra EN/ZH posts (**excluded** by SPEC §9.1 "no extra posts" unless the operator changes it); (d) TH-only on TT/FB; EN/ZH only on YouTube via the existing `upload_captions` surface (adapter-verified, not part of submit — FM §9) | **(d) now, (a) when T032 qualifies it**: YouTube delivers real caption tracks post-publish; TT/FB stay TH-only until their caption route is qualified, then flip per destination by config. Keeps one post per destination, no double render, no unverified claims. **Operator decision required before F5.** |
| O-F2 | `platform_posts` rows created at admission (§1.4) vs at LAUNCH — the design leans on the date-pinning + slot-identity UNIQUE (`M/0005:32-78,54-56`) | Keep **admission-time creation**; W09 untouched; flag for the F2 note's critique (it is the biggest departure from V1's schedule-time pinning) |
| O-F3 | Does the teaser air at 19:00 Asia/Bangkok like episodes? | **Yes** — same daily instant, 3 days earlier; one cadence constant |
| O-F4 | Swap semantics: remap dates vs renumber episodes | **Remap**: episode numbers are immutable identities (continuity, canon); a swap is a calendar revision mapping change, never a renumber |
| O-F5 | N11 corrective post route (community tab vs regular post) per platform | Per-destination capability record decides; offline mock covers both; no auto-fallback — an unqualified corrective route shows as held |
| O-F6 | MA11 window: calendar day vs rolling | Record **both**: daily snapshot (19:05) + rolling 7-day sustained; the SLO reads the rolling one (SPEC §9.4 "sustained") |
| O-F7 | Source of truth for per-platform hashtag/title limits | The pinned **capability record** per destination (it already carries platform constraints — FM §5); static config only as the mock default |
| O-F8 | SPEC §2.2 cites **N43** for HELD/MISSED/PARTIAL, but N43 is defined nowhere in REQUIREMENTS/DECISIONS (grep verified) | Adopt §7.4's derived per-destination reading; **flag to the orchestrator** to anchor N43 in SPEC (formatting fix, not a design change) |
| O-F9 | One LLM call per episode (all slots/locales) vs per slot | **One per episode** (fewer calls, one quota admission); per-slot split only if prefill quality demands it (revisit after P0) |
| O-F10 | Rescheduled CTA text: substantive (re-Gate-2) or cosmetic (policy edit) under `SUBSTANTIVE_FIELDS` (`S/publishing/metadata.py:29-37`, verified — CTA text is *not* in the tuple) | Default **cosmetic via draft rebuild + metadata-policy edit** for unpublished, and **N11 post** for published; a fresh Gate 2 only when the operator marks the change substantive at proposal. Kept as an open boundary for the F7 critique |

## 16. Requirement trace

| Requirement | Section |
|---|---|
| R-3.7 (extend after launch) | §8.4, F8 |
| R-8.1 (LLM per-slot drafts, prefill) | §3.1, F3 |
| R-8.2 (multi-language caption delivery) | §1.9, §7.1.5, O-F1 (production of the tracks: B/E) |
| R-8.3 (thumbnail generator, 2–3 variants → pick) | §3.2, F3 |
| R-9.1 (one Gate 2 screen, prefilled, Revise targeted) | §4, F4 |
| R-9.2 (scheduler posts at the LOCK cadence; held capabilities hold) | §6, §7.1, §7.3, F2/F6 |
| R-10.1 (teaser cut, own copy + thumbnail) | §5, F5 |
| R-10.2 (own slot, X days before ep 1, teaser approval) | §5, §6.1, F2/F5 |
| V3-AT-11 / 12 / 29 / 30 / 31 | F-T5 / F-T2, F-T6 / F-T8 / F-T10 / F-T10 |
| Master §12.6 (amendment integration) | §8.5, F8 |
| MA11 (throughput) | §9, F9 |
