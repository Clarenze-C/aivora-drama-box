**Verdict: REWORK.** Reviewed [phase-E-spec.md v0.3](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-E-spec.md) at `8746297`, 784 lines. Scope: PE-1..PE-13 and regressions introduced by their fixes. The second-key principle remains settled. Read-only; no files changed or tests run.

Below, `E:n` means `phase-E-spec.md:n`; `S/` means `microdrama/src/microdrama/`.

1. **PE-1 — CLOSED.** §1.15, E:216–228; E-T2, E:663. Manifest IDs, asset IDs and object keys now distinguish changed mixes; new manifest versions preserve prior outputs and V1 identities.

2. **PE-2 — CLOSED.** §10, E:578–588; E-T2, E:663. Frozen payloads, semantic keys, stable logical IDs, replacement links and real enqueue-conflict/replacement assertions are specified.

3. **PE-3 — CLOSED.** §1.15, E:230–242; §2, E:274; E-T2, E:663. The immutable outcome records exact references and findings atomically with installation. Both crash boundaries and replay without substituting CURRENT tracks are covered. Remaining identity coverage is PE-4 below.

4. **PE-4 — PARTIAL — PE5-1, BLOCKING: complete outcome identity still needs all caption recipes.** §1.15, E:208–211; §2, E:274; §3, E:351–356.
   Layout, mix and tool coverage improved. However, caption recipe coverage is explicitly described **for burned renders**, while the replayed outcome also contains EN/ZH tracks and SRTs. An EN-only text change must distinguish the complete outcome even when Thai burn inputs, layout and mix remain unchanged. The pair-based outcome key needs an explicit mapping to exact versions under the full identity.
   **Replacement:** “The complete outcome digest includes every locale’s caption/SRT recipe, burn recipe, derivative recipes and tool recipe alongside layout/mix. Lookup maps that digest to one exact immutable outcome version; it never selects CURRENT by layout/mix alone. Equal complete execution inputs—not layout hash alone—identify reproducible outputs.”
   Add EN-only text-change and tool-only change replay assertions.

5. **PE-5 — CLOSED.** §11, E:603; E-T8, E:669. Effective mix changes enter A4, freeze replacement inputs, fence old work and invalidate unpublished authority atomically. Approved-content and stale-worker cases are specified.

6. **PE-6 — CLOSED.** §2, E:282–287; §6, E:457–469; E-T7, E:668. Hooks and cropped exports are explicitly Modify, with V1 preservation, speech-safe cuts, native-audio retention, cue remapping and decoded-audio assertions.

7. **PE-7 — PARTIAL — PE5-2, BLOCKING: the simultaneous-speech fix conflicts with the caption contract.** §4, E:369–375; E-T4, E:665.
   Line-addressable observations and namespaces are now specified. But overlapping cues are required, while [`CaptionTrack._cues`](/root/AIVORA/drama-box/microdrama/src/microdrama/contracts/media.py:202) rejects them at lines 206–208. Retaining clamp-to-next also truncates simultaneous utterances (`S/editing/captions.py:109–113`). Deferring serialization to E3 does not resolve the validator conflict.
   **Replacement:** “E1 declares the V3 caption-contract crossing; E3 implements overlap-aware V3 validation and readers while preserving V1/V2 validation. Simultaneous utterances retain their independent windows; clamp-to-next never truncates overlapping speech. E-T4 roundtrips overlapping tracks through persistence, SRT serialization and Thai burn.”

8. **PE-8 — CLOSED.** §5, E:416–427; §11, E:604; E-T5, E:666. Recovery is available before Gate 2 through amendment/rebuild, including cut/mix/source repair and versioned configuration dependencies.

9. **PE-9 — PARTIAL — PE5-3, SHOULD-FIX: copied audio still inherits measurement ambiguously.** §3, E:342–348; §5, E:402–412.
   Analysis versus final encoding and independent derivative gains are clarified. However, E:410–411 says the burned master copies the finalized stream “and therefore its post-normalisation measurement,” conflicting with the per-final-output measurement requirement.
   **Replacement:** “The burned master reuses the clean master’s finalized audio and applied gain. After muxing, analyse the burned artifact itself and persist its own report bound to its asset ID/SHA. Every final audio-bearing artifact receives a post-export measurement.”

10. **PE-10 — CLOSED.** §9, E:536–548; E-T7, E:668. Readiness now requires a complete current inventory, exact assembly correspondence and completed checks; missing, stale, UNKNOWN and incomplete evidence blocks.

11. **PE-11 — CLOSED.** ED5, E:307; §6, E:441–454; §8, E:505–513; E-T3/E-T6, E:664/667. Exact D acceptance correspondence and approved predecessor snapshots replace kind/state-only binding and newly-current recap text.

12. **PE-12 — PARTIAL — PE5-4, SHOULD-FIX: package gates still have forward dependencies.** §13, E:639–644; §14, E:663/666/669.
    The original command/recap/readiness assertions were redistributed. Remaining problems: E2’s complete outcome names captions, loudness reports and derivatives delivered by E3/E4/E7; E4 exposes a recovery verb delivered through E7; E6 proves amendment behavior while E7 owns E’s A4 edge registration.
    **Replacement:** “E2 proves atomic outcome/replay using explicitly identified immutable fixture records for later-package outputs; E7 proves the complete production bundle. E4 proves the recovery descriptor, with command execution asserted at E7. E6 registers the mix dependencies required by `adjust_mix` before E-T8; E7 registers the remaining edges and tests integrated recovery.”

13. **PE-13 — CLOSED.** §15, E:687–698; E-T3, E:664. Every E-created asset now requires provenance in its registration transaction, with source/font/route lineage and a missing-output-record refusal. Valid source inspection reuse and the deterministic-card exception are explicit.