# Codex critique: phase E spec v0.2 (edit assembly, derivatives, captions, loudness, the edit gate), before code — round 1

Spec: `phase-E-spec.md` **v0.2** (`c04366f`, 653 lines). GLM drafted v0.1 and applied its own
Goldfish rulings (`phase-e-goldfish-rulings.md`, review in `phase-e-review/`). You did not write it.

Binding context: `SPEC-v3.md` v0.4.6 §4.7, §7, §10.5, §12.2, §15.1 phase E row (V3-AT-10, 25);
`phase-A-spec.md` v0.3; `A1-design-note.md` v1.3-in-verify; `phase-B-spec.md` v0.6 (ACCEPTED);
`phase-C-spec.md` v0.4.1 (ACCEPTED); `phase-F-spec.md` v0.4 (E→F seam: caption tracks per the O-8
ruling, `deliver_captions`); facts: `e-factmap.md`. Code (read-only):
`microdrama/src/microdrama/` on `feat/microdrama-m0-m4` (S/editing especially).

## Answer
1. The former Blocker: the second-key replay design (mix digest replaces `line_sha`; EDL hash pure;
   measured gain inside the outcome; adjust_mix-only never replays) — sound and consistent with the
   jobs system's replay matching?
2. The edit seam: Create/Modify/Reuse honesty vs the real `S/editing` modules; native clip audio
   preserved through assembly (V3-AT-10); crash-resume through A's job system.
3. Derivatives and captions: recap ≤10s / CTA ≤5s enforceable; TH cues master; ZH/EN share TH cue
   timing; tracks shaped for F5's `deliver_captions` (O-8 ruling).
4. Loudness: −14 LUFS ±1 measured per artifact with evidence and derivative-miss recovery.
5. Binding/synchronization (V3-AT-25): zero/one/two-speaker clips through the production binding
   path; derivatives retain speech/audio/caption sync.
6. Packages E1… order, notes-first routing (E2 per the B-1 pin), acceptance rows mapped to V3-AT-10/25
   where they can pass at their own package.
7. Anything that would make an E build fail or contradict A/B/C/F.

## Output: read-only; ≤180 lines; issues `PE-1`… BLOCKING/SHOULD-FIX/NIT + replacement wording;
verdict **APPROVE / APPROVE-WITH-CHANGES / REWORK**.
