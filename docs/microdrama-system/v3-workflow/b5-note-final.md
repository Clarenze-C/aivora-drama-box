B5 design note v0.1 DRAFT written and committed as `e8849ef` — one file, 583 lines, docs only.

**Path:** `docs/microdrama-system/v3-workflow/B5-design-note.md`

What it pins (all against phase-B v0.6 / B1 v0.3 / A1 v1.4 / phase-A v0.3, with A2 v1.3 cross-checked as parked):
- **STORY LOCK transaction** — lock order per A1 §9 = phase-A §6 (the brief's "A1 §7" pointer recorded as a header note, not a spec conflict), Approve-callback blockers (PB-11), `create_v3_episodes_in` (A2 §7), `v3_episode_story_bindings` writes with both PB-10 fences, `PLANNED → STORY_LOCKED` + `content_revision` bump, no job enqueues.
- **Binding preimage per member class** — the eight §5.4 members as canonical `(record_id, version, sha)` triples with orders, PB-9 continuity verification, the tier table pinned as a derived projection, PB-3 transition-before-activation, and who opens/closes the STORY_LOCK activation.
- **Extension branch (PB-7)** — `create_extension` eligibility incl. the PB5-4 amendment predicate, migration **B-5** (expected 0040) for the immutable authorization, builder admission at enqueue+dispatch, pinned authorities (CAST slot absent-until-C), the extension planning edges, the sibling `create_v3_extension_episodes_in` with envelope-only budget reuse, rollback.
- **Season critic** — deterministic §6.2 checks + extension reinterpretations, PB-4 origin-tagged repair/membership, failure/retry semantics, prompt `story_v3.season_critic` in B1's registry, D5 join call sites.
- **Command rows, lock audit, acceptance mapping** (B-T7..B-T11; B5-alone vs C/E/F clauses) **and 7 open questions** — incl. the extension's first-enqueue driver (OQ-1, D6 register delta vs B1's "J: none") and the A2-parked funding/steps conflicts recorded, not resolved.

Ready for the Codex critique before any B build. `make check` not run: docs-only diff (the workstream's docs commits carry no check run).
