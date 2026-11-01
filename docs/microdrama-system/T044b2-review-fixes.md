# T044b2 review fix round + re-review — 1 November 2026

Independent scoped review (Codex xhigh): `T044b2-codex-review.md` — 5 BLOCKING,
1 NON-BLOCKING, "do not close as-is". Codex's weekly quota ran out at 3% before
a second round, so the operator directed this session to verify, fix and
re-review. **Independence caveat:** the re-reviewer runs on the same model
family as the original build worker; it is a different session with no build
context, and every finding was verified against code before fixing, but it is
not a second provider. If the operator wants, findings 1 and 3 (money/durability
edges) merit a 5-minute Codex spot-check after the weekly quota resets.

## Re-review, finding by finding (only the fixed findings)

**F1 selection replay — CONFIRMED, FIXED, VERIFIED.** Root cause confirmed at
`intake.py` `select()`/`_research_request`: both the job semantic key and the
research `trigger_key` named only the candidate, so JobService dedupe replayed a
completed selection and the research run replayed the old trigger — B→A→B left
the proposal on A while reporting the selection accepted. Fix verified in code:
revisions are derived under the season `FOR UPDATE` (count of prior selection
jobs + 1), so they are strictly increasing and race-free; the same-revision
double-click dedupes through a status check on the latest intent, and the latest
intent is found by the highest embedded revision — an important correction the
fix round itself needed, because `ORDER BY created_at, id` is not order evidence
under the frozen mock clock (SequentialIds uuid5s are not lexicographic). The
pinned test drives B→A→B end to end: three research runs, final proposal binds
the first candidate's title, double-click adds no fourth job, and the rebound
card's hash equals the final proposal hash.

**F2 cross-owner sheets — CONFIRMED, FIXED, VERIFIED.** The contract models
carry no season field (verified in `contracts/v2.py`); ids are shared
identifiers; the old queries were global with a `rows[-1]` guess. Fix verified:
PropSheet/AssetSheet provenance is `assets.season_id` (column exists since
migration 0004); LocationLayout provenance chains through the season's
location-role AssetSheet `asset_sha256` == layout `geometry_sha256` — sound
because both are minted from the same empty-plate asset
(`references/v2_planning.py` `make_location_layout`). Shared plate bytes across
seasons degrade to an honest unknown, which is the correct failure. The pinned
test seeds a colliding foreign season and asserts invisibility of its prop
sheet, layout and style sheet while the own sheets display.

**F3 silent source-lane skip — CONFIRMED, FIXED, VERIFIED.** `ResearchService
._plan` skips source steps when the provider is missing/disabled or
`search_price` is None — a run would complete without evidence after generation
spent. Fix verified: `_blockers()` now reads the public `registry`
(`enabled`, `disabled_reason`) and `config` (prices) plus a new public `llm`
property, at submission AND at run time (the handler re-checks blockers). The
OFFLINE_MOCK composition is unaffected (fake provider registered and enabled,
synthetic default prices) — proven by the 19 green focused tests and the mock
pilot path. Pinned by the unregistered-provider unit test (no job, typed
blocker, honest page).

**F4 unverified display values — CONFIRMED, FIXED, VERIFIED.** Wardrobe
assignment summaries with `/ui/media/{asset_id}` links, prompt summaries, and
pack-scene-derived prop/location lists were built from raw payloads. Fix
verified: all three now go through `_verified_model` (model validation + hash
match) before any field is read; failures append unknown notes and drop the
media link. The pinned test tampers via a fresh INSERT with a stale hash
(`payload` is immutable on UPDATE by trigger — the tamper shape is realistic:
only an authorized writer path could produce it, which is exactly what hash
verification defends against).

**F5 unverified scope as canon — CONFIRMED, FIXED, VERIFIED.** The workbench
validated the proposal scope but never checked it against `scope_hash`, and the
template titled the section "Approved scope" even for a PROPOSED row. Fix
verified: hash equality gates arc/cast display (mismatch → unknown + absent),
and the heading no longer asserts approval — the status chip carries the real
proposal status. Pinned by the tampered v2 proposal test (edited content, v1's
stale hash).

**F6 hidden blockers — CONFIRMED (non-blocking), FIXED.** Blockers are now
computed on every status read and rendered under a distinct heading when jobs
exist. Low risk: display-only.

**Seeded checks:** (b) zero-scope guard added as typed
`CANDIDATE_GENERATION_EMPTY` (agreed defensive); (c) envelope-before-blockers
account opening left as is (a cap, not a charge — no spend occurs, and the
handler re-checks blockers before any run); (d) agreed, research re-checks
season state at run time; (e) is F6.

## Receipts (all re-run this session, CPUQuota45%)

- Focused: 19/19 (12 unit intake UI, 7 composed script_maker integration).
- Scoped regression: 570/570 `tests/unit/{review,pipeline,api,research,budget}`;
  462/462 `tests/contract`.
- Full `make check` + `make pilot` on the fixed tree: running at the time of
  this note; the result goes into the handoff and the T044 ledger row. A pre-fix
  full-check baseline was cut at unit 31% deliberately (mixed-tree receipts are
  worthless; the pre-fix tree is preserved in the snapshot tarball).

## Verdict

All five BLOCKING findings are fixed with pinned tests, and the NON-BLOCKING
one is fixed as well. Within the scope this re-review was allowed to cover (the
fixed findings only), **the T044b2 review can close** — subject to the full
`make check`/`make pilot` receipt passing and the T044 parent acceptance flow
(T047 composed release path) that the handoff already requires. The original
build's known gaps (live wall-clock replay caveat, cosmetic interstitial) remain
documented and unchanged.
