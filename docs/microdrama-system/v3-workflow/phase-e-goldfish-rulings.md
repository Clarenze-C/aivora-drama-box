# Phase E Goldfish rulings — GLM (14 Nov 2026)

Input: `phase-e-review/consolidated_review_report.md` (1 Blocker / 21 Major / 43 Nit) against
`phase-E-spec.md` v0.1. Every ruling is a **GLM ruling, Opus re-check Mon**. **All ACCEPTED**; no
operator decision involved; no acceptance row weakened.

- **B-1 — ACCEPT the Stage-8 second-key arm** (NOT the fold-into-EDL-hash arm): the EDL hash stays
  pure (same session inputs ⇒ same hash); a **mix digest** (cue-sheet versions + gap-fill config)
  becomes the replay key replacing `line_sha`; the measured gain is recorded inside the replayed
  outcome; test: an `adjust_mix`-only change produces new outputs, never a replay; pinned in the E2
  note before build.
- **M-1..M-12 — ACCEPT** each per its report Fix direction: Create/Modify/Reuse marking on the
  `S/editing` seam (M-1); per-artifact loudness evidence + derivative-miss recovery (M-2); recap
  caption provenance pinned (M-3); EN/ZH mismatch-path contradiction resolved (M-4); reconstructible
  transition selection (M-5); QA + `adjust_mix` assigned to packages/tests (M-6); teaser loudness
  owner named (M-7); one utterance-alignment capability (M-8); render-surface acceptance (M-9);
  E-T10 covers all five A4 edges (M-10); readiness→production transition tested (M-11); O-E4 fallback
  specified (M-12).
- **M-13..M-21 + spec-mechanics/citation nits — ACCEPT** (mechanical: name "G" or drop the deferral,
  fix the buffer-rule cite, define `EditV3Store` in §13, align `deliver_captions`, fix cites,
  reheadline the edit-gate line, ungarble the gap-fill trigger + routing sentence + §19 item 3).
- **All 43 Nits — ACCEPT** (grouped mechanical sweep).

**Apply:** fold into **phase-E-spec.md v0.2** (job `dramabox:e-spec-v02`, docs only).
