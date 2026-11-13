# Codex critique: phase B spec v0.4 (Story: Script Maker → LOCK → bible → episode packs → STORY LOCK), before code — round 1

Spec: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-B-spec.md` **v0.4**. Opus wrote v0.1–v0.3. GLM
applied Opus's rulings on a Goldfish review to make v0.4. The rulings are `phase-b-goldfish-rulings.md` and the review is
`phase-b-review/consolidated_review_report.md`. You did not write any of it.

Binding context:
- `SPEC-v3.md` v0.4.6 §4.1–§4.3, §15 (phase B row: V3-AT-3, 4, 18, 19);
- `DECISIONS.md`: operator answers O-B1..O-B6; "D2 revised again", one neutral voice reference per speaker;
- `phase-A-spec.md` v0.3;
- `A1-design-note.md` v1.2, `A2-design-note.md`, `A3-design-note.md`;
- `phase-A0-spec.md` v0.4 (`LlmStep`);
- facts: `b-factmap.md`.

Code (read-only): `/root/AIVORA/drama-box/microdrama/src/microdrama/` on `feat/microdrama-m0-m4`.

## Answer

1. **The contract-delta register (§2.4, C-B1):**
   - Does every B identifier that crosses A1/A2/A3 now match their *enforced* vocabulary?
   - Is extending A1's `RevisionTargetKind` and `V3DecisionCommand` from B1 sound, and A1-compatible?
2. **V1/V2 coexistence:** version-selected V3 records, validators unchanged, `v3_story_documents` separate.
3. **Planning without cast assets (V3-AT-18):** logical demand ids only; is the query-log mechanism (restricted DB role)
   a real proof?
4. **The continuation idiom and cascade bound (C-M1/M2):** correct with A1 primitives? Any deadlock or lost round?
5. **STORY LOCK (B5):** one transaction, episode rows created at once, binding hash complete, extension seam.
6. **Critics:** the deterministic rules and their scope alignments (C-M13); the gate opens only when its work is
   complete.
7. **Packages and tests:** B1–B6 order, job-type registration (C-M20), B-T1..B-T12 sufficient for the four ATs.
8. **Anything that would make a B build fail or contradict A0/A/A1–A3.**

## Output

- Read-only; no writes. Final message at most about 180 lines.
- Issues use `PB-1`…, with severity **BLOCKING / SHOULD-FIX / NIT**, `file:line`/`§`, and replacement wording.
- Verdict: **APPROVE** / **APPROVE-WITH-CHANGES** / **REWORK**.
