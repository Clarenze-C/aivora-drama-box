# Phase E spec draft (GLM, docs only): edit assembly, derivatives, captions, loudness, the edit gate

Orchestrator: GLM (weekend runbook), 14 Nov 2026. **Write one file:**
`/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-E-spec.md`, **v0.1 DRAFT**. No code, no
other file. It will go through Goldfish and then a Codex critique. If `phase-E-spec.md` already exists,
you are resuming.

## Binding inputs (read fully)

- `SPEC-v3.md` **v0.4.6**: §4.7 (step 7: Edit), §7 (audio providers), §10.5 (generation-unit
  contract), §12.2 (output inspection — consumed by D and F), §15.1 phase E row (V3-AT-10, 25 + their
  definitions), §15.2 (the R-IDs phase E owns).
- `DECISIONS.md`: the YuE2/music and Botnoi/voice rows (C owns voices; E consumes audio), anything on
  recaps/CTAs/teasers' content rules.
- `e-factmap.md` (today's code; cite as `FM §n`; spot-check in `microdrama/src/microdrama/`, read-only).
- Contracts to build on, not contradict: `phase-A-spec.md` v0.3 (jobs/fence/budgets/decision
  transaction), `phase-A0-spec.md` v0.4 (`LlmStep` if any E step is an LLM call), `phase-B-spec.md`
  **v0.6 (ACCEPTED)**, `phase-C-spec.md` **v0.4.1 (ACCEPTED)**, `phase-F-spec.md` v0.4 (E→F seam:
  §13 prerequisites, the O-8 caption ruling in §1.9 — E produces the EN/ZH tracks F delivers).
- Style/structure model: `phase-C-spec.md` (the accepted chain's shape): scope, binding decisions,
  records, steps, jobs/fence/waits, UI, build packages, acceptance, open questions, requirement trace,
  alternatives, risks.

## What the spec must decide

1. **Records:** the edit session/project, its inputs (D's shot plan / renders via the production
   binding path FM §7), the edited master, derivatives (recap, CTA, teaser cut input for F's PROMO_CUT),
   caption tracks per language (E-produced, exact-bound for F5's YouTube delivery), loudness evidence.
   Symbolic migration names `E-1…`.
2. **Assembly:** build on the deterministic `S/editing` seam (FM §1) — native clip audio preserved
   (V3-AT-10); no re-encode of source audio where avoidable; crash-resume of assembly jobs through A's
   job system.
3. **The edit gate:** acceptance/decision surface through phase A's decision transaction (stale hash
   refused; Revise regenerates only noted units); relationship to F's Gate 2 (FM §2).
4. **Derivatives:** recap ≤ 10 s from the previous accepted episode; CTA ≤ 5 s; duration rules as
   enforceable checks (FM §6); teaser source cut handed to F.
5. **Captions:** cue timing carried from production (FM §4); TH cues are the master; ZH/EN tracks
   share TH cue timing (V3-AT-10); delivery shape matches F's `CaptionRouteV3` and the O-8 ruling
   (YouTube files; no burned-in variants).
6. **Loudness:** −14 LUFS ±1 measured and evidenced (FM §5), pass/fail gate before F.
7. **Binding/synchronization (V3-AT-25):** zero-, one- and two-speaker clips through the production
   binding path; all derivatives retain speech/audio/caption synchronization (derivation checks).
8. **QA/inspection (§12.2):** what E inspects on edited artifacts and what it records for D and F.
9. **Build packages `E1…` in order,** each with acceptance rows; name which need a design note
   critiqued before code (money/locks/migrations).
10. **Open questions with recommendations.**

## Rules

- Never contradict `SPEC-v3.md`/`DECISIONS.md`/accepted phases; conflicts → open question, never silent.
- Facts carry `file:line` or `FM §n`; unverified → `UNVERIFIED`. Target 450–650 lines. No deletion
  commands; never print env vars/keys/tokens; no pushes/merges.
- **Final message:** ≤15 lines (decisions + open questions), then the file path.
