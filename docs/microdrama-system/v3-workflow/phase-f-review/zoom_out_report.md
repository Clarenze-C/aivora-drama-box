# Zoom Out Report (Stage 5 — Initial Zoom Out)

**Target:** `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-F-spec.md` (lines 1-567, full file)

**Mode:** uninterrupted (Preset 1), headless. Reviewer: `egm-zoom-out`, standard `zoom-out-standard.md`.

## Reviewer Status

| Reviewer | Status |
| --- | --- |
| `egm-zoom-out` | completed |

## Reviewer Coverage

Read fully: the target; `SPEC-v3.md` (goals, §2.2, §4.7-4.10, §9, §10.0, §12.3, §12.6, §15.1-15.2, §19.1); `DECISIONS.md`; `REQUIREMENTS.md` (R-3.7/R-8.x/R-9.x/R-10.x); `f-factmap.md`; `phase-A-spec.md` (§2-§8); `phase-B-spec.md` (§7.2, §8, §9); `phase-C-spec.md` (§2, §4, §5, §9); `phase-A0-spec.md` (§5.1). Code spot-checks against the spec's "verified" claims: `contracts/release.py:63-101,362-374`; `publishing/service.py:101-102,654-668,945-980,1030-1068`; `publishing/youtube/adapter.py:244-257`; `publishing/metadata.py:26-39`; `contracts/v2.py:938-965`; `contracts/enums.py:426-434`; `migrations/0005_distribution_and_analytics.sql:28-101`.

Overall: context sufficiency PASSES (objective, motivation, binding inputs, conventions and the "Not in F" boundary are all stated). Root-problem focus PASSES (the design attacks exactly the gaps f-factmap.md §11 lists: calendar authority, teaser, drafts, throughput, amendment fences). YAGNI is clean — every new table/job/screen traces to an R-ID, V3-AT or SPEC §9 clause; derived-not-stored states (AR-4), reuse of A's decision transaction, C's pick pattern, W09, the manifest path and the reconcile path are all the right minimalist calls. Altitude is right — contract/transaction level throughout, no pseudocode; line-number code citations are evidence anchors, matching the house style of phase-B/C specs. Placement is right (`S/release_v3/` beside story_v3/cast_v3; admission as a new schedule rather than touching W09). The problems are where the spec's own coherence or its verified-fact discipline breaks.

## Prioritized Findings (Blockers -> Major -> Nits)

### Reschedule flow is structurally impossible against the schema and the spec's own invariants — Severity: Blocker

* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** §1.4 (lines 57-64), §1.11 (93-96), §8.1 (386-394), §8.5 row 4 (438), F-4 (137)
* **Discrepancy Description:** §8.1's apply "cancel[s] dispatched-not-published V3 posts (cancel_slot; their identities' platform_post_id clears for re-admission under the new revision)". But: (a) `dedupe_key` is a deterministic hash of the slot identity alone (`release.py:74-76`; F-4 pins "computed exactly as `ReleaseSlotKey.canonical_hash`", no calendar component) and is UNIQUE (`M/0005:42`) — a re-admission INSERT for the same stable identity collides with the cancelled row, and identities are "never deleted" (§6.1); (b) resurrecting the cancelled row needs a CANCELLED→SCHEDULED transition that does not exist (`retry_held_slot` only lifts HELD, `service.py:1060-1068`; cancel is one-way, 1045-1058) and would have to rewrite `client_token` (trigger-immutable, `M/0005:80`) whenever the package hash changed — directly contradicting §1.4's binding promise that "no V3 row is ever rescheduled, rewritten or re-created"; (c) F-4 says `platform_post_id` is "set once, at admission" while §8.1 clears it; (d) §8.1 says `cancel_slot` cancels "dispatched-not-published" posts, but `cancel_slot` refuses once `external_id` is set (`service.py:1050-1054`) — §8.5 itself restricts cancellation to SCHEDULED rows, so the two sections use "dispatched-not-published" inconsistently.
* **Rationale & Recommendation:** This is the one place the phase's central novel mechanism (admission-time row creation on stable identities) collides with its own recovery path, and F-T9/F-T8 acceptance depends on it. Resolve before F2/F7 build: either (i) make the V3 `dedupe_key` calendar-revision-scoped and define an explicit V3-only re-create policy, or (ii) keep one row per identity and specify a guarded V3 re-arm transition stating exactly which immutable columns V3 version-aware triggers may re-pin, or (iii) define deletion semantics for never-submitted V3 rows. Whichever is chosen, §1.4's "never re-created" sentence and F-4's "set once" must be rewritten to match, and §8.1/§8.5 must agree on which states `cancel_slot` can actually reach.

### Teaser and corrective posts cannot become `platform_posts` rows under today's schema — Severity: Major

* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** §5 (235-264), §6.1 (268-276), §7.1 (314-335), §8.3 (408-412), F-4 (137)
* **Discrepancy Description:** The teaser post (and the N11 corrective post) cannot become a `platform_posts` row under today's schema, and the spec never says how. `platform_posts.episode_id` is NOT NULL REFERENCES episodes(id) (`M/0005:36`) — the teaser is season-scoped (F-4 keys it `episode_number 0`, an episode that does not exist); `release_package_id` is NOT NULL (`M/0005:45`) — `SeasonTeaserPlanV3` is a `v3_release_documents` record, not a release package, and no teaser package concept is defined; the same two gaps hit the corrective post ("its own slot identity", §8.3). Additionally §7.1's admission checks (steps 2-4: episode Gate 2 `effective_approval`, manifest equality) are phrased only for episodes; the teaser's content-authority path (`TEASER_FINAL` + what manifest/package equivalent) is unstated, despite §7.1 claiming rows are created "with `schedule_release`-equivalent fields" — `schedule_release` today requires an APPROVED episode package (f-factmap §4).
* **Rationale & Recommendation:** The reuse claim ("the publishing service's … paths stay the one implementation") is verified for episodes but the teaser/corrective rows hit three NOT NULL columns with no defined source, and F5/F-T6 will fail on arrival. Before F5, define the teaser's package shape (a season-scoped teaser release package, or explicit V3 nullable/sentinel columns in a named migration — note F-1..F-8 currently contain no `platform_posts` alteration) and state the teaser's admission checks alongside the episode ones.

### Teaser key-art budget account conflicts with binding inputs — Severity: Major

* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** §1.15 (lines 118-122)
* **Discrepancy Description:** "season-level paid work (teaser key art) to the SEASON account" conflicts with two binding inputs. Phase-A §5.1's account table says the SEASON account takes "None; aggregate-only" reservations (only SEASON_SETUP and EPISODE accounts take reservations), and SPEC §12.3 puts the teaser inside the season setup sub-budget ("Steps 1-4, music/SFX libraries, teaser"). A reservation against SEASON is refused by design, so the binding decision as written is unimplementable.
* **Rationale & Recommendation:** Charge teaser key art to SEASON_SETUP (consistent with SPEC §12.3 and A §5.1's reservation-bearing accounts) or define a season-release step budget under an account kind that accepts reservations; restate §1.15 accordingly and keep the `step_10` key.

### "Dates pinned at insert and trigger-immutable" overstates the trigger — Severity: Nit

* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** §1.4 (lines 59-60)
* **Discrepancy Description:** "platform_posts dates are pinned at insert and trigger-immutable" is factually wrong — the immutability trigger (`M/0005:77-80`) covers identity/package/approval/asset/client_token columns only; `iana_zone`/`local_time`/`scheduled_utc` are not trigger-protected. The header promises every FM fact relied on was "verified in code"; this one was not (FM's own wording was "key columns trigger-immutable").
* **Rationale & Recommendation:** Correct the sentence; the UNIQUE premise carries the argument without it.

### Prefill lane left UNVERIFIED though a binding input states it — Severity: Nit

* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** §1.14 (115-117), §10 job table (457)
* **Discrepancy Description:** The prefill lane is marked UNVERIFIED/deferred to the F1 note, but binding input `phase-B-spec.md` §7.2 states it plainly — "the existing PRODUCTION queue (phase A adds no lanes)".
* **Rationale & Recommendation:** Resolve it in the text now; the job table should not ship with a hole a cited binding input already fills.

### Gate 2 Revise channel conflicts with A's episode-gate feedback rule — Severity: Nit

* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** §4 item (e) (228-229)
* **Discrepancy Description:** F routes Gate 2 Revise targets through `season_revision_notes`, but phase-A §2.3 keeps "EPISODE_FINAL Revise requires timecoded feedback (unchanged)" and defines `season_revision_notes` for V3 season gates (rows carry `season_id`). Clarify the dual channel for Gate 2 (timecoded feedback plus typed targets?) or obtain an A-side rule for episode-gate notes; F4's Revise-targets behavior depends on it.
* **Rationale & Recommendation:** State which channel Gate 2 Revise uses and how typed targets coexist with A's timecoded-feedback rule.

### LAUNCH condition 5 is a non-condition as written — Severity: Nit

* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** §6.2 condition 5 (293-297)
* **Discrepancy Description:** Listed under "conditions (all must hold…)" yet the text describes a non-blocking outcome ("an unqualified capability … does not block LAUNCH").
* **Rationale & Recommendation:** Rewrite as an actual invariant (e.g., "capability records are pinned and evaluated; unqualified ⇒ that destination's slots hold") so condition 5 is testable like 1-4.

### Rolling aggregates stored per daily row duplicate derivable state — Severity: Nit

* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** F-6 (139), O-F6 (547)
* **Discrepancy Description:** Storing rolling aggregates (`sustained_rate_7d`, `catchup_2d`) on each daily row, in addition to the daily counters, duplicates derivable state — a small AR-4 tension in a spec that otherwise derives everything.
* **Rationale & Recommendation:** Store only the daily counters and compute the windows (the SLO already reads the rolling value); keep both only if a query-cost argument is recorded.

## Stage Verdict

Explicitly: 1 Blocker, 2 Major, 5 Nit. No premature-optimization findings (no caching/sharding/extra queues; the two new schedules are proportionate). No placement violations (local title compositing and teaser assembly sit in F because SPEC §4.8/§4.10 assign steps 8/10 to F; C's adapter/inspection and E's EDLs are consumed, not rebuilt). The "Not in F" boundary is respected by the build packages and acceptance table; the R-8.2 production/delivery split (production B/E, delivery enforcement F) is disclosed honestly in the §16 trace even though SPEC §15.2 makes F the single accountable phase for R-8.2's acceptance.
