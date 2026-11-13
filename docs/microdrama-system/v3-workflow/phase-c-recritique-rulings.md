# Phase C Codex round-2 rulings — GLM (13 Nov 2026)

Input: `codex-phase-c-recritique.md` (verdict REWORK; 9/16 CLOSED, PC-16 regressed; PC5-1/2 BLOCKING,
PC5-3..7 SHOULD-FIX) against `phase-C-spec.md` v0.3. Every ruling is a **GLM ruling, Opus re-check
Mon.** Rule 7: round 2 was the last this weekend — **all 7 ACCEPTED and applied as v0.4, no round 3
run**; Opus decides Monday (queued in OPERATOR QUEUE).

| ID | Ruling |
|---|---|
| PC5-1 | ACCEPT — freshness compares the candidate's recorded parent version **and invalidation generation** against the current authority (selected parent version + current generation); a reroll that leaves the selection unchanged still invalidates descendants. |
| PC5-2 | ACCEPT — the C3 note defines durable recovery admission shared by every participating generator, published before submit and checked under flock before any new submit; worker death/ambiguous outcomes block new dispatch until reconciled, with the mount/time clauses per the report's Replacement paragraph. |
| PC5-3 | ACCEPT — reference-pick tuples apply only to `REFERENCE_VERSION` selections; `VOICE_NEUTRAL` contributes through its own voice tuple (registered clip matching the current audition); "other"/community identity disambiguated. |
| PC5-4 | ACCEPT — `generate_next(FACE)` creates three candidates per required OUTFIT **and APPEARANCE_STATE** item, one per derived view; forecasts use the same counts; C-T3 updated. |
| PC5-5 | ACCEPT — the global refresh gets its own fencing/snapshot rule consistent with CD6 (no blanket-fence conflict), per the Replacement paragraph. |
| PC5-6 | ACCEPT — cast documents carry planning scope/extension identity (no cross-scope collisions), consistent with PC-14's scoping. |
| PC5-7 | ACCEPT — C-T11's later-package assertions move to the package that builds them (C7 keeps only its own passable clauses). |

**Apply:** fold all seven into **phase-C-spec.md v0.4** (job `dramabox:c-spec-v04`, docs only, queued
behind a3-note-rev1/a2-note-rev2). Header notes "round-2 rulings applied; awaiting Opus re-check — no
round 3 run".
