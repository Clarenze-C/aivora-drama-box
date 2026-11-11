# Codex re-critique (round 2 of 2) — Drama Box v3 MASTER SPEC v0.2.4

Spec: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/SPEC-v3.md` (v0.2.4).

Your round-1 report: `codex-spec-critique.md`, 34 findings, all accepted; the spec's §19 maps each finding
to its resolution. Binding inputs: `DECISIONS.md` (read the whole file, including the later dated
entries) and `REQUIREMENTS.md`, plus `factmap.md` and `joey-digest.md`. All files are in the same folder.
Code: `/root/AIVORA/drama-box` and the T031 worktree `/root/AIVORA/drama-box/.scratch/t031-fix3-worktree`.

**Structure note:** v0.2 is now a **master spec**. Detailed normative schemas, command tables and the
per-R-ID trace are deliverables of the **phase specs** (A0, A–G; §15). Judge whether the master fixes the
right contracts and assigns every obligation to a phase. Do not require the phase-spec detail to be here.

**Operator changes since v0.1** (must be reflected faithfully):
- **Voices:** Botnoi Web Studio V4, made by the operator and uploaded (expression tags exist only in the
  web UI; there are no API expressions). A casting sheet, an upload intake, validation, provenance, and
  one V4 voice per character.
- **Per-shot voice reference:** the expression variant chosen by the line's emotion tag (fallback
  `neutral`).
- **Character tiers:** `PRINCIPAL`, `SUPPORTING` (recurring roles, auto-promoted, with a locked package)
  and `EXTRA`.
- **Speaking cap:** 5 per episode (≤2 per shot).
- **SFX:** ElevenLabs SFX via OpenRouter or fal.ai, whichever is cheaper.
- **Dramabox Bot:** connected; the token and chat ID are FILE credentials.
- **Botnoi commercial basis:** operator-attested.

## Answer

1. **V3C-1..V3C-34:** CLOSED / PARTIAL / OPEN, one line each. If PARTIAL or OPEN, give exact replacement
   wording, or the precise phase-spec obligation that is missing.
2. **New BLOCKING issues** that v0.2–v0.2.4 introduced. Check especially:
   - the manual voice intake: the trust boundary for operator uploads, the validation gaps, format
     requirements versus the T031 binder (WAV only?), consistency, and amendment after lock;
   - emotion-tag selection with one voice per speaker per shot;
   - `SUPPORTING` promotion versus the cast cap, mandatory references and the 9-image budget;
   - the two-track state model;
   - the LAUNCH gate versus Gate 2 date binding;
   - the `LlmService` / ai-route isolation;
   - the reseller SFX route (commercial terms, unknown price).
3. **Fidelity:** does anything still contradict a dated operator decision?
4. **Phase assignment:** is every obligation (including V3-AT-18..32) owned by exactly one phase? Any
   orphaned obligations?

## Output

- Read-only. Put the full report in your final message, at most about 220 lines.
- New issues use IDs `V3R-1`…, with severity **BLOCKING / SHOULD-FIX / NIT** and replacement wording.
- Verdict: **APPROVE** / **APPROVE-WITH-CHANGES** (with the exact edits listed) / **REWORK**.

This is the **last** critique round for the master spec. Anything left after it goes to the operator.
