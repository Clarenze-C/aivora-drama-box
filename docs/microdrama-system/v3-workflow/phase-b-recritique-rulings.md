# Phase B Codex round-2 rulings — GLM (13 Nov 2026)

Input: `codex-phase-b-recritique.md` (verdict REWORK; 11/16 CLOSED, PB-14 REGRESSED; PB5-1 BLOCKING,
PB5-2..5 SHOULD-FIX) against `phase-B-spec.md` v0.5. Every ruling is a **GLM ruling, Opus re-check Mon.**

**Rule 7 status:** this was round 2 — the last Codex round this weekend. The findings below are ruled
and applied as **v0.6**, but no round-3 review is launched; **Opus re-checks Monday** and either accepts
v0.6 or orders round 3 (decision queued in OPERATOR QUEUE). The B1/B5 design notes wait for that call.

| ID | Ruling |
|---|---|
| PB5-1 | ACCEPT — `replace_v3_intake` requires an uncancelled V3 season in `PROPOSED` whose latest concept activation was REJECTED, no open activation, no unfinished proposal work; `reopen_v3_gate` requires the gate's rejected scope + appropriate planning state (`PROPOSED`/`PLANNED`) + completed required work; both enforce owner scope, session/CSRF, idempotency; expected revision = `season_tracks` for season scope, **`season_extensions`** for extension scope (A1 §5 step 2/§6). Refusals added: after Approve, during Revise regeneration, stale extension revisions. |
| PB5-2 | ACCEPT — D5's completion/runtime integration ships in **B2** (proposal completion + LOCK opening), B3 (bible completion + continuation), B4/B5 add joins; B2 includes the commit-boundary crash case. |
| PB5-3 | ACCEPT — `IDEA → PROPOSED` advances only on the scope's initial proposal completion; fresh-intake and Revise completions retain `PROPOSED` and open the activation at the final revision; exercised through B-T3's real replacement route. |
| PB5-4 | ACCEPT — `create_extension` names the amendment ID, validates season/SEASON-account ownership + sufficient funding (phase-A §5.4), then atomically creates authorization + extension; builder admission and STORY LOCK approval refuse missing/mismatched authorization; count comes exclusively from the authorization; tests: wrong-account/season, insufficient amendment, creation rollback, downstream refusal. |
| PB5-5 | ACCEPT — reuse the existing `PayoffDebt.debt_id`; V3 pack debt references use those IDs, retained prose is display-only; outstanding debt + seam status derive from the bound ledger + typed settlement effects; V2 unchanged; unknown-debt-reference test added. |

**Apply:** fold all five into **phase-B-spec.md v0.6** (job `dramabox:b-spec-v06`, docs only, queued
behind a2-note-rev1/c-spec-v03). Header notes "round-2 rulings applied; awaiting Opus re-check — no
round 3 run".
