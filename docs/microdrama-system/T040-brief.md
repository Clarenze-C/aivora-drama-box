# T040 — series look, sheets and wardrobe/state library

## Goal

Build demand-driven, versioned V2 reference planning from a Gate-1-approved
`EpisodePack`: character identity angles, per-character outfit sheets, prop
sheets, location geometry/empty plates, voice/style anchors and a short moving
style sample. Bind one current outfit per visible character and scene using
story day, setting and explicit change/reuse reasons. Preserve the US$10 episode
allowance, rights validity and two human gates.

## Paths and contracts

Worker owns only `microdrama/src/microdrama/references/` and scoped
`microdrama/tests/unit/references/` and `tests/contract/references/` files. The
existing V1 planner is in `references/anchors.py:66–163`; service acquisition,
cache, pricing and registration are in `references/service.py:310–930`, with
config/models in the same module. New V2 code may live beside it. Keep V1
readback and existing mock pilot intact. Export factories; integrator owns
route/job registration and migration ordering. Frozen contracts are package
2.4.0 `EpisodePack`, `WardrobeBible`, `SceneWardrobeAssignment`, `AssetSheet`,
`PropSheet`, `LocationLayout`, `StyleBible`, `StateEvent` and `RightsGrant` in
`contracts/v2.py`. Propose missing shared fields; never edit `contracts/`,
`migrations/`, root configs, task ledger or other lanes.

## Required behavior and gate

- Plan only angles/views required by visible cast, camera needs and key props;
  silent visible characters are included. Distinguish identity, outfit, prop,
  location, style and voice roles. Reuse exact eligible versions by cache key;
  changed/retired assets invalidate only dependent shots/derivatives.
- Next-day office→home defaults to a new outfit; same-outfit reuse requires a
  recorded story reason. Within a scene, a wardrobe change requires an explicit
  state event and effective interval. One approved outfit version per character
  per shot; other outfits are not attached.
- Prop ownership/hand and location geometry/light state must be representable
  and checked. Forecast every distinct asset/version cost before dispatch;
  no charge is silently treated as free because of expected future reuse.
- At any paid dispatch boundary, resolve `RightsGrant` against the current
  registry route/subject/version using `validate_current_rights_grant()`;
  missing, retired or expired rights block. OFFLINE_MOCK fakes stay labeled.

Acceptance tests: day-one office and next-day home outfit change, explicit
reuse reason, silent cast/key prop coverage, wrong/stale outfit and retired
rights rejection before reservation, targeted invalidation and cost/cache
accounting. Run scoped tests and Ruff, then `make check` once integrated under
`systemd-run -p CPUQuota=45%`. No paid/cloud/public action; no commit. Return
exact paths, test receipts, contract version and remaining T041 wiring needs.
