# T042 offline implementation spec — 31 October 2026

T042 adds a pre-motion still-frame check and timecoded continuity findings over **actual exported media**. It does not qualify a real vision model. Keep the existing two human approvals and `OFFLINE_MOCK` default. T031 supplies any real-model quality, rights, latency and cost evidence before a detector may gate live release.

## Inputs and authority

- Start from the current `EpisodePack`/shot state, assigned `PromptManifest`, typed exact-version `ShotReferenceBinding`s and current accepted source assets. A frame is an asset with a verified checksum and role (`FIRST_FRAME`, `LAST_FRAME`, `HANDOFF_FRAME`); never infer role from list order or prompt prose.
- Evaluate current bytes through an injected read-only still-media inspector with an explicit source label and calibrated capabilities. It returns observations for visible identity, **assigned** outfit, prop details/holder, location geometry, light, eyeline, proof text and handoff. Absence of an inspector or a missing capability yields `UNKNOWN`/`UNAVAILABLE`, never `PASS`. No intended script/canon facts enter a media-only observer call; comparison follows a frozen observation.
- Preflight is a separate step after the T041 exact-reference/rights checks and before `ComfyRenderService.reserve_attempt` in `dispatch_v2_routed_attempt`. A route without a supported still-frame control records `NOT_APPLICABLE` rather than pretending the check passed. A required frame/control with a known mismatch blocks dispatch before a budget hold. A model observation with unknown calibration cannot automatically clear a critical check.
- Bind the result to episode, shot, manifest hash, each frame asset ID/version/hash, evaluator ID/version, capability/threshold hash and evaluation time. Replay with identical inputs is idempotent; changed source or evaluator configuration invalidates that result. Keep durable evidence so T044/T047 can project it after restart. Do not use a mutable in-memory flag as authority.

## Actual-media QA

- Observe exported video/audio first, with independent transcript/visual observations; then compare against shot state and assignments. Emit separate timecoded check IDs for identity, outfit, prop/holder, location/space, eyeline/action handoff, proof text, Thai voice and subtitle/phone readability. The existing `QAFinding` honesty rule applies: `PASS` requires `CHECKED`; unsampled, unsupported or unavailable coverage is `UNKNOWN`. Keyframe pass cannot certify motion; motion findings must cite observed media windows.
- Mismatches route to the earliest correct stage: source sheet/outfit/reference for a bad keyframe; shot for wrong identity/outfit/prop/eyeline/action in rendered footage; audio line/mix for Thai speech; caption or edit for subtitle placement/readability; script only for a true story-plan contradiction. A wrong frame or outfit cannot be repaired by changing a caption.
- Keep distinct coverage evidence per check ID, even when existing `CheckFamily` is shared. If canonical cross-module contract changes are necessary, document the guardian proposal and leave live gating disabled until accepted; do not invent an incompatible enum or migration in a QA module.
- Build a labeled offline defect set with identity, outfit, prop/holder, location geometry, eyeline, proof text, Thai voice, subtitle safe area and clean controls. The calibration runner reports count, applicability by shot class, TP/FP/TN/FN and coverage. Fixture-truth scores verify software behavior only; they cannot qualify a real model or claim measured real-world accuracy.

## Gates and verification

- Seeded defects fail at the earliest applicable stage; unobserved dimensions stay `UNKNOWN`. A clean still frame alone cannot turn a motion check green. Replays do not duplicate findings, spend or dispatch. A stale frame hash, changed outfit assignment and unsupported still-frame control fail before reserve.
- Test scoped rendering/QA paths and a restart/readback case with isolated PostgreSQL; run Ruff and contract checks. After independent review, run `make check` and `make pilot` under CPUQuota45%.
- T042 is only `DONE` when both pre-motion and actual-media parts pass, with fixture calibration labeled as offline. Real evaluator release gating stays disabled until T031 evidence.
