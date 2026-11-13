# A2 note Codex round-2 rulings — GLM (13 Nov 2026)

Input: `codex-a2-note-recritique.md` (verdict REWORK; 5/15 CLOSED, N2-8 REGRESSED; N2R2-1..7 BLOCKING,
N2R2-8..10 SHOULD-FIX) against `A2-design-note.md` v1.1. Every ruling is a **GLM ruling, Opus re-check
Mon.** Rule 7: this was round 2, the last this weekend — **all 10 ACCEPTED and applied as v1.2, no round
3 run**; Opus decides Monday (accept v1.2 vs round 3). Queued in OPERATOR QUEUE.

| ID | Ruling |
|---|---|
| N2R2-1 | ACCEPT — fetch + verify the mutex row; under it re-read kind/attachment; SEASON returns no parent; only pre-LOCK SEASON_SETUP may otherwise lack one; attached children require their current parent; same protocol in SQL amendment paths. |
| N2R2-2 | ACCEPT — deferred consistency validates the amendment lineage's **final** tip and proves single delta application (apply-once evidence); contradictions resolved per the report's Replacement paragraph. |
| N2R2-3 | ACCEPT — direct INSERT backstop enforces the same locks, predecessor/revision checks and revision advancement as the sanctioned path (or is refused); equivalent serialization either way. |
| N2R2-4 | ACCEPT — the complete outer billing transactions (ingestion, invoice verification, podless-create) acquire all locks in the defined global order — the #6→#7→#6 cycle is eliminated, not just one loop. |
| N2R2-5 | ACCEPT — authorized cleanup never depends on available recovery allocation; exemptions cover spill too; overrun recorded before any flush, NULL charge reference allowed. |
| N2R2-6 | ACCEPT — the invalid TRUNCATE trigger removed (valid DDL only); step-cap guard accepts only amendment-sanctioned values with strict matching (account + step + revision lineage). |
| N2R2-7 | ACCEPT — the legacy Costs endpoint gets the season-ownership check for V3 accounts (foreign scopes NotFound) or is refused for V3 in favor of the new route. |
| N2R2-8 | ACCEPT — season-creation event/response contracts point at the real A1/A2 records (no nonexistent detail). |
| N2R2-9 | ACCEPT — DIRECTED episodes excluded from double-counted commitment/remaining; production-state residual rules per the Replacement text. |
| N2R2-10 | ACCEPT — barrier placement made compatible with the serialized order (no barrier inside a lock holder that the order itself would deadlock); tests keep the strengthened coverage. |

**Apply:** fold all ten into **`A2-design-note.md` v1.2** (job `dramabox:a2-note-rev2`, docs only, queued
behind f-spec-v03/a3-note-rev1). Header notes "round-2 rulings applied; awaiting Opus re-check — no
round 3 run". The A2 build itself waits behind A1 (stopped, operator) regardless.
