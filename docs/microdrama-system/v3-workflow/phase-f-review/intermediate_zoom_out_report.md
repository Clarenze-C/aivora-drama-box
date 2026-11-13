# Intermediate Zoom Out Report (Stage 8)

**Target:** `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-F-spec.md` (lines 1-567, full file)

**Mode:** uninterrupted (Preset 1), headless. Reviewer: `egm-zoom-out`, standard `zoom-out-standard.md`, with the Stage 5 (`zoom_out_report.md`), Stage 6 (`comprehension_report.md`) and Stage 7 (`critic_report.md`) findings in scope. Focus: new altitude findings, mitigations already in the document, and an altitude verdict on the two Stage-7 Blockers.

## Reviewer Status

| Reviewer | Status |
| --- | --- |
| `egm-zoom-out` (intermediate pass) | completed — new findings: 0 Blocker / 1 Major / 2 Nit |

## (a) Verdict at Altitude

The architecture is still the simplest sound shape; the two design-level Blockers do not indicate a wrong altitude or design root — they indicate one wrong corollary bolted to the right root, and one unmade carrier decision at the record-model rim.

**On K-1 (reschedule re-admission vs stable identities):** the root decision — admission-time row creation on a stable identity table (F-4) under the two-part authority model — is sound and should be kept. What is wrong is §1.4's absolutist corollary "no V3 row is ever rescheduled, rewritten or re-created." Both prior stages independently verified that the immutability trigger (`M/0005:77-80`) pins identity columns only; `iana_zone`/`local_time`/`scheduled_utc` are ordinary updatable columns. The schema never demanded the never-touch promise; the reschedule flow cannot honor it (cancel + re-admit collides with `dedupe_key UNIQUE` and the slot-identity UNIQUE on stable, never-deleted identities). The simplest sound fix keeps the root and deletes the corollary: reschedule's apply transaction UPDATEs the date columns in place on V3 rows it can lock in SCHEDULED (published rows stay immutable; past-`begin` rows settle per §8.5). That dissolves K-1 without re-rooting, leaves V1/V2 triggers untouched, and keeps the identity table as the single calendar-facing allocation layer. The alternative root — creating rows at LAUNCH and updating dates — would also work but buys nothing admission-time creation doesn't, and weakens the audit story (rows existing before calendar+content authority both hold).

**On K-2 (season-scoped teaser/corrective posts vs platform_posts):** "reuse `platform_posts` and the publishing service as the one implementation" is the right anti-second-state-machine call (§1.14). The defect is not the root but a decision the spec froze one sentence too early: it froze "platform_posts reused unchanged" without deciding how a season-scoped post satisfies `episode_id NOT NULL`, `release_package_id NOT NULL`, `approval_event_id NOT NULL`. Of the three candidate shapes, a synthetic carrier (an episode-0 carrier row + a season-scoped teaser release package riding the entirely ordinary path) preserves every existing invariant with zero new machinery; a parallel season-posts table would be the genuinely wrong-altitude path (a second state machine, violating §1.14). So K-2 is an unmade decision, not a wrong design.

Both fixes touch the shared `platform_posts` usage contract and interact (a second reschedule's corrective post with the fixed `corrective` slot name still hits the UNIQUE wall — inside K-1's blast radius). Both must be decided in the spec text, not deferred to the F1/F2 build notes. One standing prior Major remains unmitigated and worth triage alongside: teaser key art metered to the SEASON account, which A §5.1 defines as "None; aggregate-only" for reservations — a one-line fix (SEASON_SETUP, consistent with SPEC §12.3). No prior finding required re-rooting; no new Blocker found.

## (b) Mitigations Noted (document already answers or blunts)

1. O-F2 (§15) self-identifies admission-time creation as "the biggest departure from V1's schedule-time pinning" and routes it to the F2 critique — the K-1 risk locus is flagged, though unresolved and resting partly on the false immutability premise (K-3).
2. §8.5 row 4 already narrows §8.1's over-broad cancel wording to "only rows it can lock in SCHEDULED; past-`begin` left to settle" — partially answers the §8.1/§8.5 inconsistency, though §8.1's text still contradicts it.
3. O-F1 explicitly excludes extra EN/ZH posts (SPEC §9.1) and recommends (d) — one post per destination, YouTube `upload_captions` only where adapter-verified; correct YAGNI discipline.
4. HELD/MISSED/PARTIAL as derived projections (§1.10, §7.4, AR-4) with the stored enum untouched — blunts the temptation to widen the `platform_posts` state enum.
5. O-F9 picks one LLM call per episode and defers per-slot splitting until quality demands it — YAGNI-positive.
6. Extension decision ownership in F is confirmed correct placement: SPEC-v3.md §4.3:305 says "Extension (V3C-26; decision and integration in phase F)" — no placement violation (verified against the master spec).
7. The "Not in F" boundary holds under scrutiny: image adapter/inspection stay with C, EDL tooling with E, analytics with W11; thumbnail count is config-aligned with R-8.3; V1/V2 byte-identity is pinned by F-T3/F-T11 (but see new finding 3).

## (c) New Findings

### F-3 reinvents phase C's picks engine — Severity: Major

* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** F-3 (§2 migration table, line 136), §3.2 (185-198), §1.8 (79-82), §5 teaser thumbnail candidates (240); compare phase-C-spec.md §2 (C-1 `cast_pick_items`, C-2 `cast_pick_votes`) and §4
* **Discrepancy Description:** F-3 reinvents phase C's picks engine. C already ships the general operator-pick mechanism: `cast_pick_items` (C-1) + append-only `cast_pick_votes` (C-2) with `candidate_kind` (`REFERENCE_VERSION` | `CATALOG_ENTRY` | `ASSET`), "a vote records only", "the current selection = the latest vote", and staleness computed from stored columns. F-3 proposes parallel `thumbnail_candidates` + `thumbnail_votes` with verbatim-identical vote semantics, explicitly as "the C-2 pattern" — pattern-copy rather than reuse — and the teaser (§5) becomes a third consumer of the same pick shape. No prior stage flagged this; K-12's four un-analysed decisions do not include it.
* **Rationale & Recommendation:** The zoom-out standard mandates reuse verification when new components are proposed; this is the clearest reinventing-the-wheel case in the document, and it is permanent duplication (two append-only vote tables, two staleness computations, two UI pick patterns). Either extend C's pick items/votes (pick_kind `THUMBNAIL`, an episode/teaser scope dimension, candidates as ASSET refs plus `inspection_ref`), or record in the spec why parallel tables are cheaper (episode-scoped, generated-asset candidates, C's `demand_id` coupling to B's demand list). C's `candidate_kind` already containing `ASSET` suggests the votes side at minimum is domain-generic. Decide in the spec, not the F1 note.

### F-6 + a second daily schedule precompute derivable counters — Severity: Nit

* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** F-6 (§2 migration table, 139), §9 (443-451), O-F6 (547), schedule `w13b-throughput`
* **Discrepancy Description:** F-6 plus a second new daily schedule precompute counters that are fully derivable at read time from existing tables (`approval_events`, `platform_posts`, A2 accounts) at season scale (≤ ~100 episodes): approved episodes, released episodes, buffer_days, sustained rate, catch-up, cost-to-date. Stage 5 accepted the daily counters and flagged only the stored rolling aggregates; this extends the derivable-state concern to the table and schedule themselves, against the spec's own AR-4 discipline.
* **Rationale & Recommendation:** Compute the Launch-tab/bot numbers on read and keep only the daily alert evaluation; if the operator wants immutable trend history or G's live acceptance genuinely reads persisted rows (§9 says it does — a cross-phase coupling), record that query-cost/anchor argument once in the spec so the materialization is justified rather than habitual. Small machinery, hence Nit, but it is a second schedule plus a migration for a dashboard query.

### No acceptance test pins the V3 row-mutation policy — Severity: Nit

* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** §14 F-T3 (526), F-T9 (532), against §1.4 (62) and §8.1 (391-394)
* **Discrepancy Description:** No acceptance test pins the V3 row-mutation policy — the phase's most contested invariant. F-T3's byte-identity clause is scoped to "V1/V2 rows byte-identical"; F-T9 asserts published rows/objects untouched but nothing asserts what may legally happen to an un-submitted V3 `platform_posts` row across a reschedule. Prior findings note acceptance "depends on" the flow but not that the promise itself is currently untested in both directions.
* **Rationale & Recommendation:** Whichever fix K-1 adopts (in-place date UPDATE with identity columns pinned, or an explicit delete/revive mechanism), add the matching assertion to F-T3/F-T9 (e.g., "reschedule updates only date columns on un-submitted V3 rows; identity/package/token columns byte-identical; exactly one row per identity across two reschedules"). One line now prevents the fix and the acceptance table from silently diverging again.

## Stage Verdict

New findings only: 0 Blocker, 1 Major, 2 Nit. The two Stage-7 Blockers are corollary-level and carrier-level defects on a sound root design; the recommended resolutions (in-place date UPDATE for reschedule; synthetic carrier episode/package for season-scoped posts) stay within the existing architecture and its reuse discipline.
