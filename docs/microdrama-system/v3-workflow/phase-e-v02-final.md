**Phase E spec v0.2 done** — folded into `docs/microdrama-system/v3-workflow/phase-E-spec.md` in place, committed as `c04366f` on `feat/microdrama-m0-m4` (no push, no other files touched).

## Blocker / Major disposition (all applied — none BLOCKED)

- **B-1 — applied (second-key arm, as ruled):** EDL hash stays pure; a **mix digest** (`canonical_hash` over music + SFX cue-sheet versions + gap-fill config) replaces `line_sha` as the replay's second key; measured gain recorded inside the replayed outcome; `adjust_mix`-only ⇒ new outputs, never a replay (E-T2); pinned in the E2 note before build (decision 15, §3, §11).
- **M-1** seam marking: §2 "Reused unchanged" → "single implementation, extended in place, V1 byte-identical"; `qa.technical` split out as re-registered; Create/Modify/Reuse marks on every §13 row.
- **M-2** per-artifact loudness gain + recovery verb so step 7 never dead-ends (§5, E-T5 hook case).
- **M-3** recap caption provenance: predecessor pack line text via ED2 + three guards (pack hash in binding, registered rebuild edge, revision fence).
- **M-4** mismatch path stated: observed Thai text in **every** locale's cue, mirrored in E-T4.
- **M-5** transition selection reconstructible: `ShotPlanV3` per-boundary when present, else E config default.
- **M-6** all four orphaned work items assigned: provenance gate → E2/E-T3, `qa.technical`+ASR → E7, `adjust_mix` → E6/E-T8.
- **M-7** teaser loudness owner pinned in ED4 (F's `teaser_cut` reuses E's ebur128/`LoudnessReportV3` seam).
- **M-8** word timings now a hard ED5 requirement; aligner shrinks to the offline fake, no G track (O-E3 marked resolved, §18 risk updated).
- **M-9** E-T6 asserts the recap+CTA master decodes (streams/duration/A/V alignment).
- **M-10** E-T10 drives **each** registered edge (now six, incl. M-3's) with quarantine assertions.
- **M-11** E-T10 positive path: zero blockers ⇒ transition closes step 7, visible to F's step 8.
- **M-12** O-E4 fallback pinned: descriptor fields, `mood: UNKNOWN` as non-blocking proposal metadata, deterministic mood-less sort.
- **M-13…M-21** applied: G identified at first use (`SPEC-v3.md:871`), F §6.3 restated as LAUNCH ≥5 + <2-day alert, `EditV3Store` defined in §2, `deliver_captions` naming fixed, `M/0004:75` + one term, edit-gate headline reworded, gap-fill sentence ungarbled, findings-routing sentence decodable, "N−1-style churn" unpacked.

## Nits (43, grouped — all applied)

Spec mechanics (N-1…N-8: A6b dispatch + readiness evaluation points, duration operand pinned, typed blocker names in §9, `reservations.queue` invariant, rebuild-vs-Apply funnel, D-side evidence marked `UNVERIFIED`/ED5, C/D accountability, libass deviation routed for C sign-off) · citations (N-9…N-16: all xrefs/cite ranges re-pointed and re-verified on the tree — `export.py:118`, `captions.py:49-140`, `M/0004:75`, `e-factmap.md:128`, SPEC §10.5, F §13 wording, §17 header) · conventions (N-17…N-29: `S/`+`M/` roots defined, AR-4/T032/hard-rule-5/W07 glossed, BCP-47 sweep, ms units, one loudness notation, one artifact set, "offline fake", "Gate 2", impersonal header, A1-note loop linked, A4 linked) · parseability (N-30…N-34: four stacked constructions unpacked) · acceptance precision (N-35…N-43: E-T1 comparator, "short-measured" spelled out, "Thai is the timing master", E-T6 antecedent, duck-depth source, uniform tags/delimiters, restart-replay case, E-T11 proxy, §17 §6 added).

**Verified:** every changed cite re-checked against today's tree before writing; table shapes intact; no contradiction with SPEC-v3/B v0.6/C v0.4.1/F v0.4's seam; every E-T row extended, none weakened.

**Commit:** `c04366f` · **653 lines** (was 545; +297/−189).
