# T036 completion — prop path through pre-dispatch packet

## Goal

Close the remaining V2-F01 acceptance after the compiler fix: a dialogue or
establishing shot requesting `prop_id` must carry that exact ID to its typed
prop sheet and final render packet; it must never become an outfit. Unknown,
wrong-version or retired props fail before any budget reservation or provider
submission. Preserve V1 manifest readback as audit data.

## Existing code and ownership

- `story/compiler.py:263–390` already maps scene/dialogue staging props into
  `Shot.prop_ids`, with focused tests in `tests/unit/story/test_dialogue_prop_routing.py`.
- T040 `references/v2_planning.py` supplies persisted typed prop sheets and
  exact asset versions; frozen 2.6.0 contracts include `PropSheet`,
  `ShotReferenceBinding`, `PromptManifest` and rights validation.
- V1 `rendering/routing.py:523–565` builds `RenderRequest` with a flat
  `reference_asset_ids` list and reserves later in `dispatch_routed_attempt`.

This worker may edit only `story/` compiler/V2 bridge, `references/` resolver,
`rendering/` preflight/packet helper and scoped tests in those module folders.
Do not edit contracts, migrations, root registration, task ledger, publishing,
review or T040's accepted tests except a narrowly owned new test file.

## Acceptance

Add a composed offline test for draft → manifest shot → exact-version PropSheet
→ semantic PROP binding → prompt/render packet, including establishing and
dialogue shots. Verify `RenderRequest.reference_asset_ids` and prompt source
hashes match the typed binding; no unrelated outfit is attached. Missing,
wrong, stale or retired prop must fail before `reserve_attempt`/provider call.
A corrected retry follows normal budget/idempotency rules with no double spend.
Readback of a legacy malformed V1 manifest remains visible as historical data,
not silently V2-ready. Run scoped tests/Ruff, then parent runs `make check`.
No live provider/public effect; do not commit. Report any contract gap rather
than adding a local incompatible field.
