# Phase B spec: rulings on the Goldfish review (Opus, spec owner, 13 Nov 06:40Z)

Source: [phase-b-review/consolidated_review_report.md](phase-b-review/consolidated_review_report.md) (1 Blocker, 22
Majors, 22 Nits). **Every finding is accepted.** These rulings bind the v0.4 text. Where a finding has no ruling
below, its "Action" applies as written. GLM applies them to make v0.4; Codex critiques v0.4 (round 1).

## Blocker

- **C-B1. Add a "B contract deltas" register** as a first-class, critiqued-first B1 deliverable (§10 B1 row and a new
  §2.4).
  1. **Step keys:** adopt A2's existing keys. `step_01` = Script Maker, `step_02` = bible, `step_03` = episodes,
     per A2 OQ-2. **No CHECK amendment.**
  2. **Decision targets:**
     - **B1 owns a migration in B's range** that extends A1's `RevisionTargetKind` (and its CHECK) with
       `PROPOSAL`, `EPISODE_PLAN` (by episode number, before STORY LOCK), `BIBLE_SECTION`, `SEAM` and `TIER`.
     - `V3DecisionCommand` gains an optional typed `target`, absent for A1's existing gates, so A1's behaviour is
       unchanged. A1's note and build are **not** reopened. The delta lands in B1, after A1 is accepted.
  3. **`edit_tier`** gets an A1-§6-format command-table row (C-M3).
  4. **Citation convention:**
     - "A1 note §x", "A2 note §x", "A3 note §x" for design notes;
     - "phase-A §x" for `phase-A-spec.md`;
     - sweep every citation.
  5. **Standing rule:** any B identifier that crosses an A-phase contract is checked against that contract's
     *enforced* vocabulary (enum, CHECK, validator) before the B1 note is accepted.

## Majors

- **C-M1.**
  - Define one continuation idiom in §7:
    - every logical round has a round-scoped `logical_work_id` prefix;
    - the last job of a round enqueues the continuation job;
    - re-plans chain through `replaces_job_id`;
    - the semantic key includes the round number, so a re-plan never dedupes to a no-op.
  - Apply it to the promote join, the repair rounds and the Revise loop.
- **C-M2. Cascade bound.**
  - A pre-gate repair round re-plans the noted episode plus its directly invalidated successors, **at most 6
    episodes per round**.
  - Beyond that, the gate opens with the finding and an impact preview (the episodes that would re-plan), and the
    operator decides.
  - State the rationale for the pre-gate silent / post-gate "Revise these too" asymmetry.
  - Show the blast radius on the season-critic wait state.
- **C-M3.**
  - Add a "B commands" section with A1-§6 rows for `submit_v3_intake`, `edit_tier` and `create_extension`.
  - The tab-3 tier controls invoke `edit_tier`.
  - `edit_tier` and the demotion case move to **B5**.
  - The single name is "tier revalidation".
- **C-M4. Prompts.**
  - Ownership: B2 the proposal prompt; B3 the bible and promoted-profile prompts; B4 the architect and translation
    prompts; B5 the critic prompts.
  - Each is registered in the `PromptManifest` and ships with its package.
  - Acceptance: every `FrozenLlmCall` in tests references a manifest-registered prompt.
- **C-M5.** Accepted as written: rounds are the unit of retry, completed packs are kept, and tab 3 shows per-pack
  version status.
- **C-M6.**
  - State plainly that B enforces "no real people, brands or celebrities" only through prompt constraints plus
    originality-vs-corpus screening (`S/research/originality.py`).
  - The real-person/brand check is phase C's (master §12.2).
  - Record it as a residual risk.
- **C-M7.** On promotion, the `EXTRAS_ROLE` demand is merged into the new `CHARACTER` demand, with lineage. Pack
  references resolve to the `CHARACTER` demand. Add the case to B-T8.
- **C-M8.** Accepted: the extension-scope reinterpretations as written in the report.
- **C-M9.**
  - Seam threads get a status field. A thread becomes `RESOLVED` when a pack resolves its last open payoff.
  - The deterministic check reads that field.
  - Add the B-T7 fixture.
- **C-M10.** Accepted as written. The B1 note pins one guard site per consumer, the list is completed (qa trio
  included, or stated as reachable only through guarded job paths), and B-T2 enumerates guarded entry points through
  a shared fixture.
- **C-M11.** **Honour the master** (v0.4.6 §4.2): `SeasonBibleV3` wraps the existing `SeasonBible` and `RichBible`
  for the sections they already cover, plus the new V3 sections. No deviation is recorded.
- **C-M12. `promote_profile`:**
  - Failure policy is the same as B's other LLM jobs (one repair attempt, then BLOCKED).
  - Profiles persist as `CharacterProfile` records in `v3_story_documents`.
  - Profiles complete **before** the gate opens (§1.7), so no bible version bump happens while the gate is open.
  - Add the case "one promotion → one `promote_profile` call".
- **C-M13.**
  - (a) The psychology rule covers PRINCIPAL **and** SUPPORTING. "Appears" means at least one line or one
    visible-cast entry.
  - (b) A known character is a bible profile or an extras-role id already seen. An extras-role id **is** a legal
    `speaker`; the "has any line" promotion trigger stays.
  - (c) The cap counts **distinct `location_key` values in `scenes[]`, recap excluded**. B-T7 injects a 4th
    location.
  - (d) §4.3 reads "after the season critic **runs**".
- **C-M14.** `Settings.v3_episode_critic` (env `MICRODRAMA_V3_EPISODE_CRITIC`): default off, global, read at
  `plan_episode` dispatch. Tests cover default off and toggled on.
- **C-M15.** Accepted as written: proposal `episode_count` == `requested_episode_count`, CRITICAL otherwise; B-T3
  case; O-B2 reworded.
- **C-M16.** The mechanism is a restricted DB role with no privilege on the four table families (list the exact
  tables). The test completes with no access attempted.
- **C-M17.** Add an out-of-vocabulary emotion rejection case to B-T7.
- **C-M18.** Accepted as written, plus one bible-section, one seam and one tier Revise case in B-T10.
- **C-M19.** Within a scene, an outfit change is allowed only if a beat references it. Across scene breaks it is
  always allowed, subject to the story-day rule.
- **C-M20.** B1 registers all five `story_v3.*` job types. Handlers land per package.
- **C-M21.** A short risks table (the report's four items plus a master §18 pointer), and one rejected alternative per
  major design choice, citing master §17 where it rules.
- **C-M22.** Re-pin to master v0.4.6, A2 note v1.0 and A3 note v1.0. Re-verify the §4.1/§4.2/§6 citations.

## Nits

All 22 are applied as the report's Actions say.
