**Verdict: REWORK.** Reviewed `c04366f`; the current [phase-E-spec.md](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-E-spec.md) matches that revision. Read-only review; no files changed or tests run.

The second-key approach is sound **in principle**: keep measured gain out of input keys, distinguish effective mix changes, and replay retries. It is **not yet sufficient for the actual persistence and job contracts**. The main remaining problems are below. `E` references identify spec lines; `S/` uses the spec’s source-path shorthand.

1. **PE-1 — BLOCKING — The second key stops at replay lookup; output identities still collide.**  
   E:183–197, 275–295. Existing `master_asset_id_for` depends only on EDL hash; burned IDs add only caption hash (`S/editing/edl.py:39–45`). Object keys likewise use EDL hash, and persistence reuses an existing manifest ID (`service.py:1069–1095,1155–1179`). A mix-only change therefore encounters the same identities for different bytes. [`register_asset`](/root/AIVORA/drama-box/microdrama/src/microdrama/persistence/assets.py:21) rejects different descriptors under one ID; it does not solve this.  
   **Replacement:** “V3 manifest execution IDs, output asset IDs and object keys distinguish `(EDL hash, mix digest)` and applicable artifact recipe inputs. A changed mix appends a manifest version and preserves prior outputs. V1 identity functions remain unchanged.”

2. **PE-2 — BLOCKING — Job replay identity is unspecified.**  
   E:464–485 lists stable **logical work IDs**, but never defines semantic keys or frozen assembly payloads. [`JobService.enqueue`](/root/AIVORA/drama-box/microdrama/src/microdrama/core/jobs.py:429) rejects different input under one semantic key; A1 §2.4 additionally compares complete work scope. An assembly-level second key cannot fix rejection—or reuse of an already successful job—before its handler runs.  
   **Replacement:** “Each assembly payload freezes session, EDL, mix and authority references. Semantic keys distinguish execution inputs and content authority; `logical_work_id` remains stable across replacements. Retries preserve payload/key/scope; deliberate replacement records `replaces_job_id`. E2 tests changed-input conflict and successful-job replacement through real enqueue.”

3. **PE-3 — BLOCKING — There is no defined durable, complete replay outcome.**  
   E:191–195 says gain lives inside the replayed outcome, but §2 defines no assembly-outcome record or lookup mapping. Existing `_replay_outcome` reconstructs from the latest matching manifest, **current** caption tracks and lineage; it returns empty findings/checks (`service.py:1340–1395`). That cannot recover exact reports, tracks and blockers after persistence succeeds but job completion crashes.  
   **Replacement:** “Persist an immutable V3 assembly outcome, indexed by its complete execution identity, atomically with canonical artifact installation. It names exact manifest, asset, caption-track and report versions plus checks/findings. Replay verifies those references and current authority; it never substitutes arbitrary CURRENT tracks or clears findings. Test crashes before installation and after installation/before job finish.”

4. **PE-4 — BLOCKING — The hash definition still omits output-changing inputs.**  
   E:275–295 describes `[clip_id, asset_id, in, out]` plus audio binding. Actual assembly uses `edl_semantic_hash`, which also includes timeline placement, gain and transition kind; it omits transition duration. Variant hashing omits transitions entirely (`S/editing/edl.py:234`, `variants.py:237`). The spec also attaches music/SFX events to the EDL while excluding their placement from its hash. Loudness configuration and tool drift are not covered by the stated pair.  
   **Replacement:** “Define one V3 layout hash covering ordered source bindings, source/timeline spans, crops, output format and transition kind/duration. Keep mix decisions in immutable cue sheets, covered by the mix digest with gap-fill and normalization configuration. Caption/burn recipes cover text, alignment, style and font inputs. Pin the tool recipe in execution identity. Measured gain remains outcome evidence.”  
   Also replace E:617’s claim that tool drift automatically changes the EDL hash.

5. **PE-5 — BLOCKING — `adjust_mix` bypasses the amendment fence.**  
   E:485 appends sheets and enqueues assembly; only `rebuild_edit_media` explicitly uses A4. A’s content revision changes through amendments/locks. An older assembly can therefore retain a valid fence while a newer mix exists, and “session current; validators pass” does not protect approved content.  
   **Replacement:** “An effective mix change enters A4’s scoped amendment path, freezes replacement inputs, fences affected work and invalidates dependent unpublished authority atomically. Published media remains immutable. Test an old worker completing after the mix change and an adjustment against approved content.”

6. **PE-6 — BLOCKING — Hook reuse is incompatible with native audio.**  
   E:371–375 and E7 describe existing machinery plus V3 wiring. `build_hook_edl` explicitly requires a continuous room bed, slices video arbitrarily, drops boundary dialogue separately, and reconstructs dialogue tracks (`S/editing/hooks.py:245–339`). Neither dropping native speech independently nor requiring that bed satisfies V3. The cropped exporter also currently requires room tone (`variants.py:433`).  
   **Replacement:** “Mark `hooks.py` and the cropped exporter **Modify**, with unchanged V1 branches. V3 hook/preview cuts use measured speech-safe windows, retain each selected clip’s embedded audio exactly once, remap utterances/cues, and preserve or recompute boundary transitions. Test decoded source audio and cue timing across reordered windows, crossfades and a source cut that would bisect speech.”

7. **PE-7 — SHOULD-FIX — ED5 needs line-addressable observations, not merely word timestamps.**  
   E:79–96, 256, 304–321. Existing spotting uses only `dialogue_line_ids[0]` and caches observation by audio SHA (`captions.py:76–86`). A two-speaker clip containing several lines cannot use that unchanged model. Thai word-match checking alone does not establish timestamp capability or line association. Recap/current-episode line IDs also need distinct namespaces.  
   **Replacement:** “Before E1, ED5 pins source-audio identity, observed text, speaker/line association, measured source-relative utterance/word spans and coverage. E maps every included utterance through trims/transitions into Thai master cues, then copies those windows to EN/ZH. Namespace repeated placements and predecessor lines. Define simultaneous-speech handling; missing alignment blocks rather than falling back to script timing.”  
   The O-8 deliverable shape—Thai burn plus exact EN/ZH SRT assets for F—is otherwise consistent.

8. **PE-8 — BLOCKING — Loudness recovery depends on an unreachable gate.**  
   E:343–347 prescribes Gate 2 Revise for a residual derivative miss. E:436–438 prevents leaving step 7 while loudness fails, so that episode cannot reach Gate 2. Raising a gain clamp also cannot generally satisfy both integrated loudness and true peak for high-crest-factor audio.  
   **Replacement:** “Loudness failure exposes a pre-Gate-2 recovery through `rebuild_edit_media`/A4: amend the affected cut, mix or source shot, then regenerate dependent artifacts and reports. Gate 2 Revise uses the same path once available. Configuration changes are versioned dependencies. Test a derivative that remains outside peak/loudness limits after permitted scalar gain.”

9. **PE-9 — SHOULD-FIX — Export-pass and audio-copy claims contradict the real seam.**  
   E:287–288 promises one export pass per artifact; §5 requires measurement followed by gain-adjusted export. Existing cropped exports encode AAC (`variants.py:497–538`), whereas §5 treats copy variants as sharing the master’s bytes. Burned output also re-encodes master video.  
   **Replacement:** “Allow analysis/premeasurement and final normalized export from immutable sources; encode final audio once, and copy that finalized stream into burned renders where applicable. Explicitly identify variants that copy master audio versus independently encode it. Each final artifact receives its own post-export measurement and report.”  
   Keep the −14 LUFS ±1 / ≤−1 dBTP gate.

10. **PE-10 — SHOULD-FIX — Readiness can pass with missing work.**  
    E:427–442 lists failed reports/checks and missing caption tracks, but does not explicitly require a current complete master/derivative set, a report for every required output, or completed required technical/ASR checks. “Every report passes” can be vacuously true before reports exist. Presence of CURRENT captions also does not prove they belong to the current assembly.  
    **Replacement:** “Readiness resolves an explicit required artifact/check inventory for the current session and authority. Missing, stale, UNKNOWN or incomplete artifacts, reports and required checks block. Caption IDs, loudness reports and derivation evidence must match the installed assembly. Only then may E advance `EDITING→DRAFTING`.”

11. **PE-11 — SHOULD-FIX — Binding acceptance needs authoritative correspondence, including recap snapshots.**  
    E:267–269, 357–368, 411–414. Existing `_shot_sources` checks kind/state/duration, not whether an asset belongs to the requested shot or approved predecessor package (`service.py:556–578`). Rebuilding recap text from a newly current predecessor pack can also pair unapproved text with old approved speech.  
    **Replacement:** “Validate each mapping against D’s exact shot/render acceptance evidence, source SHA and required media streams. Recaps consume the pack, alignment and source set bound to the predecessor’s effective approved package. Supersession invalidates that binding; absent replacement approval produces `edit.recap_pending`. Test an unrelated accepted video, wrong source hash, and predecessor text change before re-approval.”

12. **PE-12 — SHOULD-FIX — Several package gates require later packages.**  
    E-T2 requires the real `adjust_mix` behavior delivered in E6; E-T6 requires a registered dependency edge delivered in E7. E-T5 says every artifact/readiness is covered although derivative wiring and readiness arrive in E7. These cannot all prove their stated production paths at their own gates.  
    **Replacement:** “E2 proves the second-key behavior with immutable cue-sheet fixtures; E6 proves the command→enqueue→new-output path. E5 proves recap binding/rendering; E7 proves its registered rebuild edge. E4 proves normalization/report generation on supplied artifacts; E7 proves complete artifact inventory and readiness. Label V3-AT-10/25 contributions as partial until their combined E7 assertions pass.”  
    E1/E2/E6/E7 notes-first routing is appropriate; retain the B-1 pin in E2.

13. **PE-13 — SHOULD-FIX — Provenance completeness covers inputs but omits E’s registrations.**  
    E:555–570 requires source inspection evidence and provenance, but never requires E-created masters, derivatives, SRTs, cards or generated fills to receive their own records. Accepted C §9 requires every V3 asset registration to write provenance in the same transaction.  
    **Replacement:** “Every E-created asset receives a complete `ProvenanceRecord` atomically with registration, with exact source/font/route lineage as applicable. Reuse source inspection evidence where valid; do not require a fabricated generation-inspection record for a deterministic typeset card. Test both missing input evidence and missing output provenance.”

The recap/CTA caps, Thai timing-master policy, O-8 caption routing, and absence of an additional human gate are coherent. Approval should wait for the replay/persistence, fencing, native derivative and recovery contracts above to be pinned and reflected in executable package gates.