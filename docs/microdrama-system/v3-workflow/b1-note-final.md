Done. `docs/microdrama-system/v3-workflow/B1-design-note.md` v0.1 DRAFT — 599 lines, committed as `b3343a8` ("docs(v3): B1 design note v0.1 (GLM)").

What it pins:
- **Migration re-audit finding:** the applied tail on this branch is **0025** — 0026 (T031) sits only in the fix3 worktree and A0–A3 (0027–0035) are accepted but unmerged. B1's build is recorded as prerequisite-gated; migrations allocated symbolically `B-1..B-4` (expected 0036–0039).
- **Records + DDL:** `v3_story_documents` (+`StoryV3Store` mirroring `StoryV2Store`), the PB-2 generation-round store (with the two advance points), the PB-6 prompt registry, `v3_episode_story_bindings` (both fences), `STORY_V3_NS` + all uuid5 derivations, the full C-N5 field mapping of `EpisodePlan`/`Script`/`EpisodePack` (verified anchors), and the PB-9 `source_pack_version` pin.
- **Delta register D1..D6** (D6 registers B1's own enforced vocabularies for B2–B6); all five §9 command rows in A1 §6 format; a lock audit against the phase-A §6 order; acceptance = B-T1/B-T2 with named fixtures plus a prepared-not-gated table; 7 open questions.
- **New runtime fact surfaced:** unhandled job types fail `NO_HANDLER` (`runtime.py:237-241`), so C-M20's enqueue-vs-handler split needs a claim-boundary skip for the B2→B3 window (OQ-2).

Ready for the Codex critique.
