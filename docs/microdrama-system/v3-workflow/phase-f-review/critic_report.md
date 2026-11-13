# Goldfish Review Report (Stage 7 — Critic Review)

**Target:** `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-F-spec.md` (FeatureRange lines 1-496)

**Mode:** uninterrupted (Preset 1), headless. Reviewers: `egm-design`, `egm-structural` (standard: `feature-spec-standard.md`), `egm-style` (no standard). Deduplicated by the orchestrator; merged findings credit all lenses.

## Reviewer Status

| Reviewer | Status |
| --- | --- |
| `egm-design` | completed (2 Blocker / 5 Major / 8 Nit) |
| `egm-structural` | completed (0 Blocker / 7 Major / 7 Nit) |
| `egm-style` | completed (0 Blocker / 12 Major / 18 Nit; sibling docs not read, cross-doc terminology unverified) |

After in-stage deduplication: **2 Blocker / 21 Major / 31 Nit** (finding IDs K-1…K-54; cross-references "comprehension"/"zoom-out" note overlap with another stage's report — consolidated in `consolidated_review_report.md`).

## Prioritized Findings (Blockers -> Major -> Nits)

### K-1. Reschedule cancel + re-admission cannot create a second `platform_posts` row for the same stable slot identity — Severity: Blocker

* **Reviewer Lens:** `egm-design`
* **Affected Scope:** §8.1 (386-394), contradicting §1.4 (57-64) and F-4 (137); cascades to §7.3 "push" (355-358), §7.4 MISSED recovery (364-369), §5 teaser recovery option 2 (261-264), §8.3 corrective posts (406-412)
* **Discrepancy Description:** §8.1's apply "cancel[s] dispatched-not-published V3 posts (cancel_slot; their identities' platform_post_id clears for re-admission under the new revision)". `cancel_slot` (`S/publishing/service.py:1045-1058`) moves the row to CANCELLED and deletes nothing; no DELETE path for `platform_posts` exists anywhere in src (grep verified). The cancelled row permanently occupies both `dedupe_key UNIQUE` (`M/0005:42`) and `UNIQUE (series_id, episode_id, part, locale, platform, account_ref, release_slot)` (`M/0005:72`). §6.1 (272-276) makes identities stable and never deleted with the same `release_slot` name, so a re-admission — which §7.1 (330-335) defines as "create the `platform_posts` row" — computes the identical `dedupe_key` and violates both constraints on INSERT. §1.4's claim "no V3 row is ever rescheduled, rewritten or re-created" is contradicted by the spec's own reschedule flow, which is schema-impossible as written. §8.3's corrective post uses a fixed `corrective` release-slot name per destination, so a second reschedule's N11 post for that destination hits the same UNIQUE wall.
* **Rationale & Recommendation:** Reschedule is the designated recovery for MISSED episodes, late teasers and pushes — the entire corrective architecture routes through an unimplementable step. Since `scheduled_utc`/`local_time`/`iana_zone` are NOT in the immutability trigger (`M/0005:77-80`; see K-3), the clean fix is to specify that reschedule's apply UPDATEs the date columns in place on un-submitted V3 rows (SCHEDULED rows it can lock) — same row, new date, V1/V2 triggers untouched. Alternatively design an explicit delete-or-revive mechanism and own its audit consequences (F-5 `platform_post_id` references, append-only ethos). The spec currently specifies neither. (Same defect found independently by the Stage-5 zoom-out reviewer.)

### K-2. Season-scoped posts (teaser PROMO_CUT, N11 corrective) cannot exist in the reused `platform_posts` table — Severity: Blocker

* **Reviewer Lens:** `egm-design`
* **Affected Scope:** §5 (240-255), §8.3 (406-412), §6.1 (270-276), F-4 (137), against §2's "Reused unchanged: `platform_posts` + the publishing service" (153-157)
* **Discrepancy Description:** `M/0005:36` requires `episode_id uuid NOT NULL REFERENCES episodes(id)`; `:45` `release_package_id NOT NULL REFERENCES release_packages(id)`; `:46` `approval_event_id NOT NULL`. The teaser is not an episode (F-4's `episode_number 0` is an identity-table convention; no episodes row exists), has no per-episode release package (packages and `_approved_package` are per-episode, `S/publishing/slots.py:110-152`), and live submit additionally requires the command to name the slot's package and pass full V2 manifest binding (`S/publishing/service.py:368-455`, FM §5) — the `TEASER_FINAL` gate approves no such package/manifest. Corrective community posts (§8.3) have the same shape problem. As specified, F5 and F7 cannot write the rows their designs require into the table §2 freezes as unchanged.
* **Rationale & Recommendation:** This must be decided in the spec, not the F1/F2 notes, because every option reshapes the record model: (a) a synthetic carrier episode + package for season-scoped posts; (b) a new season-posts table outside `platform_posts` (then W09, verification, dedupe and release_view all need a parallel path — a real second-state-machine risk against §1.14); (c) a guarded V3 migration relaxing/extension-typing the constraints (touches a shared V1/V2 table — needs its own compatibility argument against §1.1). Pick one, write its compatibility story, and add an acceptance test. (Stage-5 zoom-out rated the same defect Major with the same anchor set.)

### K-3. §1.4's load-bearing premise ("dates … trigger-immutable") is factually wrong; O-F2 must be re-run — Severity: Major

* **Reviewer Lens:** `egm-design`
* **Affected Scope:** §1.4 (57-60), O-F2 (543)
* **Discrepancy Description:** The spec claims "platform_posts dates are pinned at insert and trigger-immutable (`M/0005:32-78`; FM §4)". The trigger `platform_posts_slot_immutable` (`M/0005:77-80`) pins identity columns (`series_id..client_token`) — not `iana_zone`/`local_time`/`scheduled_utc`. FM §4 correctly says "pinned at schedule time; key columns trigger-immutable"; the spec overstated it into a schema fact. The UNIQUE argument for admission-time creation survives; the immutability argument does not — and O-F2 calls this "the biggest departure from V1's schedule-time pinning".
* **Rationale & Recommendation:** Under the standard's Alternatives Rule, the core timing decision rests partly on a false premise and the viable alternative (create at LAUNCH, UPDATE dates on reschedule — schema-legal) is never evaluated on the true constraint set. Correct the premise; add the update-dates alternative and reject (or adopt) it on real grounds (authoritative-row rewrites weaken audit; note adopting it would also dissolve K-1). The two-part authority model itself (§1.2) also gets no explicit alternatives treatment anywhere — one paragraph is owed.

### K-4. No re-bind actor after reschedule; "LAUNCH binding current" unsatisfiable for extension identities — Severity: Major

* **Reviewer Lens:** `egm-design`
* **Affected Scope:** §1.12 (97-99), §8.1 apply list (391-394), §7.1 check 3 (321-323), §6.1 (277-279, 284), §8.4 (427-429)
* **Discrepancy Description:** Admission requires the identity's `bound_calendar_revision` to equal the current revision, but bindings are written only by LAUNCH (never re-run, §8.4) or a Gate 2 decision — and episodes 6+ are already approved when a mid-season reschedule hits, while §1.12 says reschedule "never supersedes a content approval by itself". §6.1's parenthetical "(only their `bound_calendar_revision` changes)" implies the apply updates it, but §8.1's apply enumeration omits that write entirely — after one reschedule, every not-yet-admitted bound identity refuses admission with no defined recovery. Separately, §7.1(3)'s "LAUNCH binding current" can never hold for extension episodes (`LaunchBindingV3` binds the original revision; §8.4 binds extensions via the extension approval), and no actor is assigned to allocate extension identities (§6.1 assigns allocation to LAUNCH only).
* **Rationale & Recommendation:** Specify in §8.1 that the apply transaction re-binds all not-yet-admitted identities to the new revision (re-checking nothing content-wise, per §1.12); rewrite §7.1(3) as "bound by the latest binding authority (LAUNCH or extension approval) and equal to the current revision"; assign extension-identity allocation to the extension approval handler in §8.4.

### K-5. The O-F10/§8.2 "cosmetic CTA rebuild + metadata-policy edit" default is unimplementable for unpublished slots — Severity: Major

* **Reviewer Lens:** `egm-design`
* **Affected Scope:** §8.2 (396-404), §7.1 check 4 (323-325), O-F10 (551)
* **Discrepancy Description:** Metadata policy edits append `metadata_versions` rows keyed to an existing `platform_posts` row (`platform_post_id NOT NULL`, `M/0005:85`; `S/publishing/metadata.py` `update_with_revision`). Pre-admission slots have no post row to edit; post-admission pre-submit, the live-binding equality (admission check 4; `service.py:386-455`, `519-554`) refuses any current-version drift from the sealed manifest, and only Gate 2 APPROVE can (re)bind a manifest (`M/0021` trigger, FM §2). `SUBSTANTIVE_FIELDS` indeed excludes CTA (`metadata.py:29-37`, verified), but that only governs post-publication edits. So a reschedule touching any sealed-but-unaired episode forces the scoped Gate 2 re-approval — the spec's exception is the only actual path, and the default ("cosmetic via draft rebuild + metadata-policy edit for unpublished") publishes stale CTA text or refuses.
* **Rationale & Recommendation:** Make the metadata-delta Gate 2 re-approval the stated default for unaired sealed episodes (cheap, scoped — §8.2 already sketches it); restrict policy-edit and N11 to already-published slots. Update O-F10's recommendation to match the mechanism the code actually offers.

### K-6. Admission forks `schedule_release`'s invariant-dense row creation without an inventory — Severity: Major

* **Reviewer Lens:** `egm-design`
* **Affected Scope:** §7.1 (330-335), §1.1 (41-46), §1.14 (112-117)
* **Discrepancy Description:** "plan built with `schedule_release`-equivalent fields" creates a second implementation of the most invariant-dense insert in the publishing path, in tension with §1.1's "reused, not forked" and §1.14's "no new mechanism". `schedule_release` (`slots.py:117-223`) does more than insert: locks the episode FOR UPDATE (131-133), revalidates the scope DAG (138), refuses episodes not at RELEASE_APPROVED (153-162), computes deterministic post ids and client tokens (166, 193), emits `platform_post.scheduled` outbox events (199-213), and transitions the episode RELEASE_APPROVED→SCHEDULED (214-222) — the transition the episode-completion logic (`service.py:902-943`) builds on. Which of these per-destination admission replicates is unspecified; per-destination piecemeal creation cannot call `schedule_release` as-is (it creates all plan rows at once), so the fork is real.
* **Rationale & Recommendation:** Enumerate in the spec which invariants admission replicates (episode lock + state transition, DAG check, deterministic ids, client token, outbox event, replay/Conflict rules) and which function owns them; missing the episode transition or the outbox event silently breaks W09, completion and bot consumers. Name the fork and accept it, or refactor `schedule_release` to expose a per-slot variant F calls.

### K-7. Risks & Limits: operational risks of the new runtime pieces are unnamed — Severity: Major

* **Reviewer Lens:** `egm-design`
* **Affected Scope:** document-level (§0-12); §8.5 (433-439); §15 (538-551)
* **Discrepancy Description:** Races are genuinely well covered (§8.5) and §15's ten open questions satisfy most of the Alternatives Rule. But no treatment covers: (a) `w13-release-admission` (313-317) as a NEW single point on the publication critical path — no availability/catch-up statement (time-based discovery self-heals a missed run into late publication; say so and bound acceptable lateness); (b) F-5 REFUSED-row growth and alert fatigue — a persistently-held due slot re-refuses every 5 minutes, appending rows and alerts unboundedly, with only an asserted reliance on F-T13/A §8 dedupe; (c) no mid-RELEASING abort/rollback story (A's cancel_season is never referenced from F); (d) lead time (10 min) vs same-day predecessor verification latency — §7.2's predecessor chain makes episode N's admission hostage to N−1's poll/reconcile finishing inside the window, with no stated expectation.
* **Rationale & Recommendation:** Add a short Risks & Limits treatment covering these four with their mitigations; they are the failure modes a fresh engineer cannot infer from §8.5. (Distinct from the section-shape finding K-13: these four risks are defects independent of any template.)

### K-8. Every "§14 O-Fn" reference is off by one (O-F items live in §15) — Severity: Major

* **Reviewer Lens:** `egm-structural`
* **Affected Scope:** lines 32, 85, 166, 179, 241, 281, 372, 404 (all "§14 O-Fn" references)
* **Discrepancy Description:** Every reference to the open-questions items points to §14, but §14 is "Acceptance" (line 520); the O-F1..O-F10 table lives in §15 "Open questions" (line 538). Eight in-range sites are systematically off by one — the numbering drifted when a section was inserted, and no "§15" reference exists anywhere in the document to compensate. Binding decision 9 (§1.9) routes the load-bearing O-8 caption decision to "§14 O-F1"; a reader obeying the reference lands on the acceptance-test table.
* **Rationale & Recommendation:** Re-point all eight sites to §15 (or renumber), and add a lint pass so section-number drift is caught before the Codex critique.

### K-9. `ReleaseCalendarV3`/`SeasonTeaserPlanV3` mislabeled "(F-2)"; F-n scheme overloaded — Severity: Major

* **Reviewer Lens:** `egm-structural`, `egm-style`
* **Affected Scope:** line 51 "(F-2 store)", line 237 "(F-2)", vs §2 migration table (132-135)
* **Discrepancy Description:** Both documents are labeled F-2, but §2 defines F-2 as `metadata_drafts` (135) and F-1 as `v3_release_documents` (134), whose Documents table (145-148) lists both documents as records of that F-1 store. A builder implementing §1.3 or §5 would look for the calendar/teaser-plan store in the wrong migration. Additionally migrations are "F-1…F-8" (hyphen) vs build packages "F1…F10" (no hyphen), so "(F-2)" resolves to neither cleanly.
* **Rationale & Recommendation:** Change both labels to F-1 (or "the F-1 document store"); state once whether F-n may ever denote a build package.

### K-10. Wrong test id: "the 30-episode simulation (F-T5)" — Severity: Major

* **Reviewer Lens:** `egm-structural`, `egm-style` (also found by Stage-6 comprehension)
* **Affected Scope:** line 380 (§7.5)
* **Discrepancy Description:** §14 defines F-T5 as the drafts/manifest/thumbnail-pick test (line 528) and F-T8 as the 30-episode simulation (line 531, tagged V3-AT-29); §16 (line 565) maps V3-AT-29 to F-T8, and line 451 correctly attributes the simulation to V3-AT-29. A planner verifying §7.5's dedupe coverage would check the wrong test.
* **Rationale & Recommendation:** Change F-T5 to F-T8 at line 380.

### K-11. Bare external section references collide with the document's own numbering — Severity: Major

* **Reviewer Lens:** `egm-structural`, `egm-style` (also found by Stage-6 comprehension)
* **Affected Scope:** line 481 (lead example), line 451, and ~14 further bare refs at lines 18, 20, 22, 24, 27, 30, 46, 50, 67, 101, 268, 337, 346, 384
* **Discrepancy Description:** Two conventions are used inconsistently: external SPEC-v3 clauses are sometimes prefixed ("SPEC §9.2 item 1", lines 173, 487) and sometimes bare (§4.8/§4.9/§4.10, §9.1-9.3, §9.2 items 3/5/6/7, §12.6, §9.4). The bare form collides with the document's own section numbers: line 481 "§3.2's state set and one-primary-action rule" resolves internally to §3.2 Thumbnails (line 183), which contains no such rule — the intended target is SPEC-v3 §3.2; line 451 "(§16.3, G)" cannot resolve internally (§16 is the trace table, no subsections). Bare "§9.2 item n" collides with internal §9 (Throughput), which has no items.
* **Rationale & Recommendation:** Apply the "SPEC §n" prefix uniformly to every master-spec reference; use the doc-letter convention (A §n, C §n) for sibling specs.

### K-12. No Alternatives Considered section; four heaviest decisions single-path — Severity: Major

* **Reviewer Lens:** `egm-structural`
* **Affected Scope:** whole FeatureRange; compare phase-B-spec.md §16 and SPEC-v3.md §17
* **Discrepancy Description:** No Alternatives Considered section exists in the file. In-range alternative evaluation is limited to §1.4's creation-time rationale (57-64); the O-F1/O-F2/O-F4/O-F6/O-F9/O-F10 option analyses live in §15, framed as open questions, not rejected alternatives. Several of the heaviest binding decisions have no documented rejected alternative anywhere: the single `v3_release_documents` store (§2, vs per-contract tables), the separate `publication_admissions` audit table (F-5, vs reusing `approval_events`), the new `w13-release-admission` schedule (§7.1, vs extending W09 — "W09 is not modified" is asserted, not argued), and the calendar-as-versioned-document store shape (§1.3).
* **Rationale & Recommendation:** The standard's Alternatives Rule is mandatory and the document family already has the vehicle (B §16, master §17). Add an "Alternatives rejected" section covering at least the four choices above. If the orchestrator applies the Alternatives Rule to the letter for those un-analysed choices, this finding escalates to Blocker; it is Major here because partial documentation exists in the same file.

### K-13. No Risks & Mitigations roll-up; security of new operator surfaces unaddressed — Severity: Major

* **Reviewer Lens:** `egm-structural`
* **Affected Scope:** whole FeatureRange; compare phase-B-spec.md §15, SPEC-v3.md §18
* **Discrepancy Description:** No Risks & Mitigations section. Failure-mode handling is real but distributed (§5 lines 256-264; §7.3 346-358; §7.5 374-380; §8.5 431-439), and nothing addresses F-specific security implications for the new surfaces it introduces (the per-destination caption route §1.9, N11 corrective community posts §8.3, the operator extension screen §8.4 — auth is silently inherited from A's rules).
* **Rationale & Recommendation:** Add a risks roll-up (or an explicit map table pointing to §5/§7.3/§7.5/§8.5) plus a security note for the three new operator-facing surfaces.

### K-14. No problem statement in §0 — Severity: Major

* **Reviewer Lens:** `egm-structural`
* **Affected Scope:** §0 (14-37)
* **Discrepancy Description:** §0 opens "Phase F builds tabs 8-10 plus Launch…" and enumerates deliverables bound to requirement IDs, but the business/user problem being solved is never stated; the preamble (3-7) lists binding inputs, not motivation. A fresh reader per the standard's Core Principle cannot get the "why" from this document.
* **Rationale & Recommendation:** Add 2-4 sentences of problem statement at the top of §0, or a §0.0. Sibling phase specs share this shape (B §0, C §0 are scope-only), so if family convention governs this drops to Nit — but judged against the standard alone it is a required area.

### K-15. "Admission" named four ways for one transaction — Severity: Major

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** lines 50, 57, 103, 138, 312
* **Discrepancy Description:** "release admission" (50), "dispatch admission" (57), "publication at admission" (103), `publication_admissions` (138), bare "Admission" (§7.1, 312) — all for the single §7.1 transaction. §1.2's precision claim ("the check lives in one place") argues for one name.
* **Rationale & Recommendation:** Pick "release admission" and use it uniformly.

### K-16. §7.4 table mixes units (per-destination vs cross-destination) — Severity: Major

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** lines 360-368
* **Discrepancy Description:** Header "Derived per-destination episode states" parses two ways; HELD/MISSED cells are per-destination but PARTIAL's cell ("≥1 destination verified, ≥1 required destination not verified") is a cross-destination aggregate.
* **Rationale & Recommendation:** Split the table or retitle to make the unit explicit.

### K-17. "The bound revision" ambiguous in the §3.3 staleness rule — Severity: Major

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** line 204 (a Gate-2-refusal trigger at line 206)
* **Discrepancy Description:** "Bound" elsewhere means LAUNCH/Gate-2-bound (`bound_calendar_revision`, §6.1 line 279); drafts created pre-LAUNCH reference nothing bound, so "the recorded `calendar_revision` is no longer the bound revision" has no referent for pre-LAUNCH drafts.
* **Rationale & Recommendation:** State the intended referent (the current calendar revision in force).

### K-18. Missing "that" makes a guarantee ambiguous — Severity: Major

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** line 425 (§8.4)
* **Discrepancy Description:** "The fence guarantees stale results and old approvals cannot release changed artifacts" reads either "guarantees [that] … cannot release" or "guarantees stale results".
* **Rationale & Recommendation:** Insert "that".

### K-19. LAUNCH condition 5 packs condition + exception + rationale with undefined coinages — Severity: Major

* **Reviewer Lens:** `egm-style` (condition shape also flagged by Stage-5 zoom-out)
* **Affected Scope:** lines 294-297
* **Discrepancy Description:** Condition, exception, cross-ref, and rationale in one sentence, with undefined "required route" (caption vs publication route?), "matrix decision", "per-run one".
* **Rationale & Recommendation:** Split into condition / exception / rationale; define or drop the coinages. (Also make condition 5 testable like 1-4 — zoom-out's remedy.)

### K-20. Admission horizon is an example ("e.g. 10 min"), then renamed "the horizon" — Severity: Major

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** lines 314-315 vs 353
* **Discrepancy Description:** "now + lead, e.g. 10 min" makes a binding threshold non-normative; line 353 reuses it as "the horizon" — a second name, no definition.
* **Rationale & Recommendation:** Give the lead a config name and default; use one term.

### K-21. `approved_episodes` defined twice, differently — Severity: Major

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** line 139 (F-6: "first-time Gate 2 approves per content revision") vs line 444 (§9: "first-time Gate 2 approves per episode")
* **Discrepancy Description & Rationale:** Same counter, two definitions that disagree on revision- vs episode-scoping; the throughput SLO reads this counter. Align on one.

### K-22. `step_10`/SEASON metering missing from the §10 job table — Severity: Major

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** lines 118-121 (§1.15) vs 455-460 (§10)
* **Discrepancy Description:** §1.15 defines `step_10` on the SEASON account for teaser key art; §10's table says `make_thumbnails` → "EPISODE/SEASON account, `step_08`" and `teaser_cut` → "none"; `step_10` appears nowhere in §10.
* **Rationale & Recommendation:** Extend the metering cell or add a mapping note. (Compounds with the Stage-5 finding that the SEASON account takes no reservations by design.)

### K-23. "Slot" overloaded across three objects — Severity: Major

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** `slot_key` (135), slot identity (137, 296), platform publish slot (330, 349 "the slot HELDs")
* **Discrepancy Description:** §7 uses bare "slot" for both the identity (pre-admission) and the publish slot (post-admission).
* **Rationale & Recommendation:** Use "slot identity" vs "post"/"publish slot" consistently in §7.

### K-24. Binding-input citations mis-attributed to DECISIONS.md — Severity: Nit

* **Reviewer Lens:** `egm-design`, `egm-structural` (also found by Stage-6 comprehension)
* **Affected Scope:** line 5
* **Discrepancy Description:** Only Q6 is in DECISIONS.md (line 61, correctly cited at line 283); V3C-26, O-8, N35 and N11 are anchored in SPEC-v3.md (§4.3:305, §15:1012-1013, §9.2:602).
* **Rationale & Recommendation:** Attribute each ID to the file that actually defines it, matching the precision used at line 283.

### K-25. F-2 `metadata_drafts` cannot store teaser drafts — Severity: Nit

* **Reviewer Lens:** `egm-design`
* **Affected Scope:** F-2 (135) vs §3.2/§5 (240-241)
* **Discrepancy Description:** F-2 keys rows by `episode_id`, but §3.2/§5 require teaser drafts ("keyed `teaser`"). F-3 acknowledges the teaser key ("episode_id or `teaser` key", 136); F-2's tabulated schema cannot store teaser drafts.
* **Rationale & Recommendation:** Add a target/key column.

### K-26. §7.1 check 1's fence comparator is undefined for a schedule — Severity: Nit

* **Reviewer Lens:** `egm-design`
* **Affected Scope:** §7.1 check 1 (319)
* **Discrepancy Description:** "fence: `expected_content_revision` equality" — admission is a schedule, not a job with a `work_scope`; the comparator (bound approval's recorded revision vs current track `content_revision`) is undefined.
* **Rationale & Recommendation:** One sentence defining the comparison.

### K-27. §7.4's derived states are not exhaustive — Severity: Nit

* **Reviewer Lens:** `egm-design`
* **Affected Scope:** §7.4 (364-369)
* **Discrepancy Description:** An admitted slot past its air instant, unverified, in RETRY_WAIT/NEEDS_RECONCILIATION is neither HELD, nor MISSED ("no admission in flight" excludes it), nor PARTIAL (cross-destination). The release board's most common late case is unnamed.
* **Rationale & Recommendation:** Add an in-flight-late projection.

### K-28. The O-8 route record has no home — Severity: Nit

* **Reviewer Lens:** `egm-design`
* **Affected Scope:** §1.9 (88)
* **Discrepancy Description:** "The chosen route is recorded per destination and enforced at admission" — no home for the O-8 route record exists in F-1..F-8.
* **Rationale & Recommendation:** Assign it (capability record vs `v3_release_documents`).

### K-29. "Reuse the `metadata_versions` pattern" option is non-viable as phrased — Severity: Nit

* **Reviewer Lens:** `egm-design`
* **Affected Scope:** F-2 (135)
* **Discrepancy Description:** Reusing the actual `metadata_versions` table is impossible (`platform_post_id NOT NULL`, `M/0005:85`); the option as phrased is non-viable.
* **Rationale & Recommendation:** Commit to `metadata_draft_versions`.

### K-30. Teaser repair deadline ignores composition latency — Severity: Nit

* **Reviewer Lens:** `egm-design`
* **Affected Scope:** §5 (258-261)
* **Discrepancy Description:** Teaser repair is "legal only while the premiere instant has not passed", but ignores lead-time composition: a repair at premiere−1h must fit re-cut + `TEASER_FINAL` + admission (10-min lead) + submit + verify before episode-1 admission.
* **Rationale & Recommendation:** State the practical deadline (repair complete ≥ lead + expected verify latency before premiere).

### K-31. CONTINUED/RESUMED extension modes never defined — Severity: Nit

* **Reviewer Lens:** `egm-design` (also found by Stage-6 comprehension at Major)
* **Affected Scope:** ReleaseCalendarV3 (147), §8.4 (418-421)
* **Discrepancy Description:** Whether resumed ranges gap, re-date or re-map is undefined in F and in SPEC §4.3:309; the operator decision surface in §8.4 rests on the undefined distinction.
* **Rationale & Recommendation:** Pin the semantics before F1/F8 build the air-instant map.

### K-32. §1.3's "(§1.5)" is a wrong item pointer — Severity: Nit

* **Reviewer Lens:** `egm-structural`
* **Affected Scope:** line 56
* **Discrepancy Description:** "Nothing in `platform_posts` is date-authoritative for V3 (§1.5)" — §1.5 is the LAUNCH-gate decision; the platform_posts/date-pinning decision is §1.4 (57-64).
* **Rationale & Recommendation:** Re-point to §1.4.

### K-33. `reschedule_calendar` used but never defined; command-table row shape mismatch — Severity: Nit

* **Reviewer Lens:** `egm-structural`, `egm-style`
* **Affected Scope:** lines 55, 263 vs §8.1 (386) and §12 (492)
* **Discrepancy Description:** `reschedule_calendar` is used twice but never defined; the defined commands are `propose_reschedule` / `confirm_reschedule(impact_sha256)`. The §12 row's shared cells imply Confirm==Apply without stating it.
* **Rationale & Recommendation:** Use the defined names (the command table is the operable surface a builder implements from); state the confirm/apply relationship.

### K-34. V3-AT-2, V3-AT-5, V3R-6, AR-4 missing from the §16 trace — Severity: Nit

* **Reviewer Lens:** `egm-structural`
* **Affected Scope:** lines 207, 209, 266, 90, 371 vs §16 (553-567)
* **Discrepancy Description:** These IDs are cited in body/headings but have no trace row; AR-4's home (the phase-A/codex-a critique chain) is never named — the same provenance gap phase C's review flagged.
* **Rationale & Recommendation:** Add trace rows (or a note that V3-AT-2/5 are inherited gates verified via §4's mechanics) and name AR-4's home once.

### K-35. §1 binding decisions pre-empt detailed sections at drifting granularity — Severity: Nit

* **Reviewer Lens:** `egm-structural`
* **Affected Scope:** §1.12-§1.13 (97-111) vs §7.1 (316-335) and §8.1-§8.3 (384-412); buffer rule at 139, 304-308, 443-448
* **Discrepancy Description:** §1.13 restates the admission checklist as 4 re-validations where §7.1 defines 6 steps; `buffer_days` is defined in three places. Today they agree; any edit to one copy can silently drift.
* **Rationale & Recommendation:** Keep §1 items as decision + single forward pointer, leaving enumerated lists to one home.

### K-36. §10 omits F's two new schedules — Severity: Nit

* **Reviewer Lens:** `egm-structural`
* **Affected Scope:** §10 (453-466) vs lines 314, 443
* **Discrepancy Description:** §10 "Jobs, fence, waits" enumerates F's four jobs but not its two new schedules (`w13-release-admission`, `w13b-throughput`), which are only discoverable inside §7.1/§9.
* **Rationale & Recommendation:** Add a schedules row/paragraph or pointer.

### K-37. F-2 table cell packs schema + policy + an open decision — Severity: Nit

* **Reviewer Lens:** `egm-structural`, `egm-style`
* **Affected Scope:** §2 table, line 135
* **Discrepancy Description:** The F-2 cell is ~130 words carrying an entire schema, an embedded projection rule, a UNIQUE constraint, an unexplained SUPERSEDED state, and an unresolved either/or ("decided in the F1 note") in one table cell.
* **Rationale & Recommendation:** Split the "Decisive columns / rules" column (Columns / Constraints / Open decision) or move F-2's schema to a short subsection, like B §2.1's per-record layout.

### K-38. "CSF" vs "CSRF" — Severity: Nit

* **Reviewer Lens:** `egm-style` (also found by Stage-6 comprehension)
* **Affected Scope:** line 219 vs 390, 487
* **Discrepancy Description:** "CSF" is undefined and inconsistent with "CSRF" used for the same human-session protection; apparent typo.
* **Rationale & Recommendation:** Correct/expand.

### K-39. Casing/enum drift — Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** W09/W11 (34, 332) vs w13/w13b (314, 443); CONTINUED/RESUMED (147) vs "continued vs resumed" (418); `PROMO_CUT` backticked (23, 272, 410) vs bare (148); "HELD/MISSED/PARTIAL/verified" one lowercase item (479); CAST LOCK (233) vs cast-lock (188); `metadata`/`thumbnail` backticked but bare "content" in the same list (227-229)
* **Discrepancy Description & Rationale:** One convention per family; mixed casing hides enum identity.

### K-40. Unit style: "premiere − 3 d" vs "premiere − 3 days" — Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** lines 23, 148 vs 241

### K-41. Normative bold inconsistent for equal-force rules — Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** lines 55, 90, 93, 274, 393; migration-bytes rule plain at 12, bolded duplicate at 501
* **Discrepancy Description & Rationale:** Deduplicate; pick one emphasis convention.

### K-42. Actor-hiding passives in binding rules — Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** lines 108-109, 306, 435 ("money accounted"), 88
* **Discrepancy Description & Rationale:** Name the enforcing schedule/handler.

### K-43. Density sentences — Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** lines 103-111 (§1.13, ~5 clauses), 386-390 (§8.1), 422-423 (§8.4 paren)
* **Discrepancy Description & Rationale:** Split into multiple sentences.

### K-44. "vote records only" word order parses as a noun phrase — Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** lines 80, 136, 193 vs 491
* **Discrepancy Description & Rationale:** Line 491's "appends a vote; starts no work" is the clear form — use it.

### K-45. Single-use/unexplained terms — Severity: Nit

* **Reviewer Lens:** `egm-style` (partially overlaps Stage-6 comprehension findings)
* **Affected Scope:** "weekend runbook" (3), "the tail" (10), EDL (37), "date-stamp" (99), "guardian-owned bump" (124), "closed out" with no actor (302), "required route" (294), "per-run one" (297)
* **Discrepancy Description & Rationale:** Define or drop.

### K-46. "in flight" used for two objects — Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** admission (367) vs submit (437)

### K-47. Dual hashtag caps — effective minimum unstated — Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** lines 165-167
* **Discrepancy Description:** Platform limit + contract cap 30; the effective cap (min) is unstated.

### K-48. Episode-range naming wobble; meta-aside in a normative sentence — Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** "eps 1–5" (149, 293) / "episodes 1–5" (73) / "first five consecutive episodes" (67-68, 291) / "(≥5 approved = first five)" (306); meta-aside (185-187)

### K-49. Launch-tab refusal shorthand doesn't match §6.2's five conditions — Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** line 478 "(buffer, teaser, staleness)" vs 289-297

### K-50. HELD/MISSED/PARTIAL derivation inputs differ between §1.10 and §7.4 — Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** lines 89-90 (two inputs) vs 362 (three: + admissions)
* **Discrepancy Description & Rationale:** Align the input list (admissions are needed for typed refusal causes).

### K-51. Informal register in normative text — Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** "cheap" (403), "legal only while" (261), "bumps" (99, 173)

### K-52. Fence triad named twice differently — Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** §0 (27-28) vs §8.5 heading (431)

### K-53. `launch:<content_revision>` key: which revision is undefined — Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** line 149

### K-54. Cells hiding rules — Severity: Nit

* **Reviewer Lens:** `egm-style`
* **Affected Scope:** §8.5 cells (433-439); "when applicable" (147)
* **Discrepancy Description & Rationale:** Move policy to prose; qualifying phrases in cells are easy to miss.

## Stage Verdict

2 Blocker / 21 Major / 31 Nit after in-stage deduplication. Both Blockers are design-level impossibilities in the record model (K-1 reschedule re-admission; K-2 season-scoped posts), each independently corroborated by the Stage-5 zoom-out reviewer (as Blocker and Major respectively). Structural findings concentrate on cross-reference drift (K-8, K-9, K-10, K-11) and the standard's Alternatives/Risks sections (K-12, K-13, K-14). Style findings concentrate on terminology overload (K-15, K-23) and normative-precision gaps (K-17, K-19, K-20, K-21, K-22).
