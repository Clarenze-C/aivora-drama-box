# T047 brief — independent V2 composed mock and fault acceptance

Owner: validator lane, built in-session (GLM) on 2026-11-01. Codex scoped review
NOT available this week (quota 97%, resets 11-04) — recorded as pending in the
ledger; this build follows the T044b2 precedent (operator-directed in-session
review with the same-model caveat).

## Obligations this task closes (from HANDOFF + ledger)

1. **T041 deferral:** supply `verify_current_asset(id, version, sha)` against
   the current ACCEPTED asset row AND stored bytes, authoritative current
   rights resolution from the rights registry, and the selected pinned
   template's semantic hash through the composed dispatch path. The seams
   already exist: `rendering/routing.py` `ReferenceContext` declares
   `resolve_current_rights` + `verify_current_asset` fields.
2. **T042 deferral:** the production typed-expectations reader — compose
   `EpisodeContinuityExpectations` from current V2 records and actual edit
   windows (`ContinuityExpectations` protocol, `qa/continuity.py`), replacing
   the fixture-only seam in the acceptance path.
3. **T037 closure evidence:** the composed release path — Gate 2 invoking
   `ReviewService.prepare_release_approval_manifest` on a season created
   through the finished intake/workbench, then the mock publish leg.
4. **Composed V2 journey + fault acceptance:** validator-lane integration
   tests over real PostgreSQL: records→reader→QA, assets/rights→dispatch
   boundary, intake→Gate 1→Gate 2→publish, and the fault matrix (tampered
   docs with stale hashes, ambiguous current rows, changed expectations
   invalidating cached runs, wrong asset triples, registry-expired rights).

## Build pieces

- `references/v2_dispatch_context.py` (new): `verify_current_asset` factory
  (ACCEPTED row + exact version/sha + stored-bytes hash), `registry_rights_resolver`
  (current `rights_registry` rows → `RightsRecord`), and `load_reference_context`
  (current hash-verified V2 records for an episode → `ReferenceContext`).
- `qa/continuity_sources.py` (new): `V2RecordContinuityExpectations` — windows
  from the current edit manifest's video-track clip spans; per-window fields
  from the verified DirectingManifest/EpisodePack/SceneWardrobeAssignment/
  LocationLayout/PropSheet/StyleBible/approved scope voices + script speakers.
  Missing or unverifiable records leave dimensions honestly undefined; a
  missing edit manifest returns None (whole-episode unknown).
- `tests/integration/validation/test_t047_v2_composed_acceptance.py` (new).

## Non-goals

No guardian-owned contract edits, no new migrations, no pilot composition
change (the pilot's receipt must stay reproducible; the reader is exercised in
the acceptance suite, and wiring it into the pilot is a separate decision).
No real provider, no live mode, no quality claims beyond OFFLINE_FIXTURE_ONLY
labels (T031 owns real-detector evidence).
