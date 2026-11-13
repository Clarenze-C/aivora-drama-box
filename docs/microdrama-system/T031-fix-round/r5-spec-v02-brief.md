# Apply the Goldfish rulings: T031 run-readiness spec v0.1 → v0.2 (GLM, docs only)

Orchestrator: Opus, 13 Nov 2026. **Edit one file in place:**
`/root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md` → **v0.2**. Change no other file and no code.

Inputs (read fully):
- the spec v0.1;
- the rulings `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/r5-goldfish-rulings.md`, **binding,
  word for word where it gives text**;
- the review `.../T031-fix-round/r5-goldfish/consolidated_review_report.md`, whose "Action" lines apply where a
  ruling is silent;
- the fact map `.../t031-benchmark/paid-run-factmap.md`.

Code to verify claims against (read-only): `/root/AIVORA/drama-box/.scratch/t031-fix3-worktree` (`feat/t031-fix3`).

Do this:
1. Apply **every** ruling and every unruled finding's Action. Keep the section order. Add these sections:
   - "Alternatives considered";
   - "Failure and retry";
   - "Risks and limits";
   - a target-scope table (package → files, RR tests → packages);
   - a glossary.
2. Header: Version 0.2, 13 Nov 2026, "v0.2 applies the Goldfish rulings (`T031-fix-round/r5-goldfish-rulings.md`)";
   status "DRAFT for Codex critique (round 1)".
3. Every new code claim carries `file:line`. If a ruling turns out impossible against the code (for example the
   `benchmark_acquisitions.state` CHECK), write what you found and the ruling's stated fallback. **Never invent a
   mechanism.**
4. Add §9, "Finding map": one line per finding id (CON-B1, CON-M1..M16, CON-F1/F2, CON-N1..N19) → the section that
   resolves it.
5. Keep it under about 420 lines.

No deletion commands. Never print env vars, keys or tokens. Final message: at most 10 lines, then the file path.
