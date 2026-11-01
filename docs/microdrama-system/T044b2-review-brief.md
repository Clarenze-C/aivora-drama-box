# T044b2 scoped review brief — three-step owner Script Maker intake

You are the independent reviewer for the interrupted T044b2 build (worker stopped
2026-11-01T09:45Z before its final receipt). Review ONLY the files named below.
The working tree contains months of unreviewed-elsewhere dirt; every file not
listed is OUT OF SCOPE (earlier layers T036–T044b1 already had scoped reviews;
`src/microdrama/contracts/` is guardian-owned and predates this build — do not
review it). Do not run the app; read code and reason. Focused receipts were
re-run independently today and are green (9 unit intake UI, 6 integration
script_maker); your job is the code, not the receipts.

## In-scope files (repo root = /root/AIVORA/drama-box)

New (review whole file):
- `microdrama/src/microdrama/review/intake.py` — the service (1597 lines)
- `microdrama/src/microdrama/review/templates/intake_wizard.html`
- `microdrama/src/microdrama/review/templates/intake_status.html`
- `microdrama/src/microdrama/review/templates/workbench.html`
- `microdrama/tests/unit/review/test_intake_ui.py`
- `microdrama/tests/integration/script_maker/test_owner_intake_path.py`

Modified (review the intake-related hunks only; use
`git diff -- <path>` and read the file for context):
- `microdrama/src/microdrama/review/api.py` — wizard/status/selection/workbench routes
- `microdrama/src/microdrama/pipeline/handlers.py` — `research_collect_and_propose` intake hook
- `microdrama/src/microdrama/pipeline/world.py` — intake composition, mock envelope, `_DatabaseClock`
- `microdrama/src/microdrama/api/compose.py` — optional `IntakeService` wiring
- `microdrama/src/microdrama/review/__init__.py`, `microdrama/src/microdrama/research/__init__.py` — exports

## What the build claims (verify against code, do not trust)

See `microdrama/evidence/T044b2.md` for the worker's own account, including its
self-found persistence defect and fix (content-fingerprint comparison, live
binding never un-bound).

## Invariants that must hold (from SPEC + handoff)

1. One wizard submission = one idempotent transaction creating season +
   `link_season_creator` + sealed `ConceptIntake` + (if configured) research
   envelope, BEFORE any candidate work. Double-submit/refresh replays exactly.
2. No default positive spend in any mode: missing envelope/template/sources or
   live paid-request authorization ⇒ typed blockers, submission recorded, NO job.
3. The browser cannot inject policy: closed form field set; the scope template's
   policy reaches the generated scopes byte for byte.
4. Gate 1 stays the only human concept decision. Selection ≠ approval; silence
   approves nothing; post-Gate-1 selection refused typed.
5. Candidate persistence: append-only raw history; only the proposal-bound
   candidate re-versioned on real content change; a stale job replay can never
   un-bind the candidate the CURRENT proposal binds.
6. Owner scoping everywhere: cross-owner reads/selects 404, unassigned legacy
   seasons invisible.
7. Workbench/status projections honest: unknown/missing/ambiguous labelled, never
   guessed.

## Reviewer-seeded candidate findings (verify or refute, then add your own)

a. `_episode_workbench` builds `SceneWardrobeAssignment` and `PromptManifest`
   DocRefs from raw `doc.payload` WITHOUT hash verification, and `_season_subjects`
   reads `EpisodePack.payload` raw for prop/location ids — inconsistent with the
   "each hash-verified on read" claim. Confirm whether unverified content can
   influence anything beyond display — especially `media_asset_id` routing to
   `/ui/media/{asset_id}`, and the prop/location id sets driving which sheets list.
b. `_research_request` indexes `generated.scopes[0]` for a placeholder draft —
   IndexError if a COMPLETED generation ever returns zero scopes; should that be a
   typed `Failed`?
c. `_create_intake` opens the research account whenever an envelope is configured,
   even when other blockers prevent dispatch — is any spend/blocker display
   misleading as a result?
d. `select()` and `handle_research_job` TOCTOU around season state (PROPOSED
   checked at enqueue vs at run) — is every interleaving safe?
e. `_status` computes blockers only when no jobs exist and season is PROPOSED —
   can a dispatcher-relevant blocker appear after dispatch and be hidden?

## Known accepted gaps (documented in T044b2.md — do NOT re-report)

Live wall-clock durable-replay caveat (mock clock only), two-rapid-selections
last-write-wins, missing cosmetic selection interstitial.

## Output

Numbered findings, each with severity (BLOCKING / NON-BLOCKING), `file:line`, a
concrete failure scenario, and a suggested fix. End with a verdict: does this
delta, after fixing any BLOCKING findings, merit closing the T044b2 review?
