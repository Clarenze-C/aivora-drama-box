# Phase E fact map (GLM swarm): today's code for edit assembly, derivatives, captions, loudness and the edit gate

Orchestrator: GLM (weekend runbook), 14 Nov 2026. A phase E spec will be written from your facts.
**Facts only: no design and no recommendations. Read-only. Write no files.** Put the whole fact map in
your **final message** (only the final message is kept).

## Where

- Repo `/root/AIVORA/drama-box`, branch `feat/microdrama-m0-m4` (main checkout). Code
  `microdrama/src/microdrama/` (cite as `S/…`), migrations `microdrama/migrations/` (`M/…`), tests
  `microdrama/tests/` (`X/…`). Migrations 0026–0027 exist only under
  `.scratch/a0d-gate/microdrama/migrations/`.
- Requirement context, skimmed and not summarised: `docs/microdrama-system/v3-workflow/SPEC-v3.md` §4.7
  (step 7: Edit), §7 (audio providers), §10.5 (generation-unit contract), §12.2 (output inspection,
  consumed by D and F), §15.1 phase E row (V3-AT-10, 25 and their definitions). Also `DECISIONS.md`
  rows on YuE2 music and Botnoi voices (E consumes, C owns).

## Rules for every fact

- Cite `file:line` and quote the decisive line or signature (≤ 2 lines).
- If you searched and found nothing, write **NOT FOUND** and the search terms you used. Never guess.
- Keep the whole answer under about 350 lines. Use tables.
- Never print environment variables, `.env` files, keys or tokens.

## Facts needed

1. **Editing/assembly today:** the deterministic EDL/export/FFmpeg seam (`S/editing/{edl,export,ffmpeg}.py`,
   T015 lineage) — what assembles clips into an episode, inputs/outputs, and what "native clip audio"
   means in that path.
2. **The edit gate:** any approval/decision surface between edit and release (who accepts an edit,
   records, hashes), or how today's Gate 2 relates to edited output.
3. **Derivatives:** anything producing recap/CTA/teaser-like segments, caption/subtitle files (SRT/VTT
   or similar), per-language audio or caption tracks, burned-in caption renders — or NOT FOUND each.
4. **Cue timing:** how speech/caption timing is carried today (word timings? cue lists?), and whether
   any cross-language timing sharing exists, or NOT FOUND.
5. **Loudness/audio normalization:** any −14 LUFS / loudness measurement/normalization code, ffmpeg
   audio filters in use, or NOT FOUND.
6. **Duration rules:** any recap/CTA/clip duration constraints in code or contracts, or NOT FOUND.
7. **Production binding:** how a clip binds to its source shot/render (the "production binding path"
   of V3-AT-25) — records linking render outputs to episodes today.
8. **What phase D will feed E:** directing output (`ShotPlanV3` does not exist yet — state what today's
   closest shot-plan structure is) and what phase F consumes from E (per `phase-F-spec.md` v0.4 §13
   prerequisites — read-only).
9. **QA/inspection:** any output inspection on edited artifacts (§12.2), or NOT FOUND.
10. **Gaps:** things phase E will need that do not exist at all.
