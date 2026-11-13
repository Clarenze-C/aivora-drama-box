# Apply the Goldfish rulings: phase B spec v0.3 → v0.4 (GLM, docs only)

Orchestrator: Opus, 13 Nov 2026. **Edit one file in place:**
`/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-B-spec.md` → **v0.4**. Change no other file and no code.

Inputs (read fully):
- the spec v0.3;
- the rulings `phase-b-goldfish-rulings.md` beside it, **binding**;
- the review `phase-b-review/consolidated_review_report.md`, whose Actions apply where a ruling is silent.

Contracts to check every cross-phase identifier against (C-B1 standing rule), all read-only:
- `phase-A-spec.md` v0.3;
- `A1-design-note.md` v1.2, `A2-design-note.md` v1.0, `A3-design-note.md` v1.0;
- `SPEC-v3.md` v0.4.6;
- code in `/root/AIVORA/drama-box/microdrama/src/microdrama/`.

Do this:
1. Apply every ruling and Action. Add these sections:
   - §2.4 "B contract deltas" register;
   - "B commands";
   - "Risks and limits";
   - "Alternatives rejected".
2. Header: Version 0.4, 13 Nov 2026, "v0.4 applies the Goldfish rulings (`phase-b-goldfish-rulings.md`)"; status
   "DRAFT for Codex critique (round 1)". Re-pin master v0.4.6.
3. New code claims carry `file:line`. If a ruling turns out impossible against a frozen contract, write what you found;
   never invent a mechanism.
4. Add a final "Finding map" section: one line per finding id (C-B1, C-M1..C-M22, the nits) → the section that
   resolves it.
5. Keep it under about 700 lines.

No deletion commands. Never print env vars, keys or tokens. Final message: at most 10 lines, then the file path.
