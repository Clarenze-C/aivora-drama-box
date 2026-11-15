**A1 FIX1: ALL FINDINGS ADDRESSED** — fix round 1 complete on `feat/a0d-gateway`, tip `3bd8c90` (9 commits on `57df5a9`; tree clean, `.venv`/reports never staged).

- **A1V-1** (BLOCKING) — APPROVE + complete-scope + current binding/revision authority required by `v3_require_gate_approval`; found already committed in `5105794`, red recorded retroactively against the verbatim pre-fix function — **done**
- **A1V-2** (BLOCKING) — track locks before leaf rows in supersede/pod-binding/activation/transfer, competing-service tests on two real connections — `760880a` — **done**
- **A1V-3** (BLOCKING) — single revision writer advances the content fence on lock APPROVEs — `5105794` — **done**
- **A1V-4** — enqueue requirements from the resolved workflow (untracked v3 work refused, zero writes); V1 type/input-hash replay precedes ancestry refusals — `0ad1659` — **done**
- **A1V-5** — one complete scope predicate (`v3_scope_wait`) across activation/admission/heartbeat/janitor; extension ranges resolved completely — `e8f267d` — **done**
- **A1V-6** — HTML form carries `episode_id` + timecoded feedback; every gate × action valid on both surfaces — `4d536e3` — **done**
- **A1V-7** — 0029 trigger renamed `approval_events_v3_gate_rules`, runs after every retained BEFORE guard; 0027 diagnostics restored (42501 human guard wins again) — `3bd8c90` — **done**
- **A1V-8** — nonlocking ownership check before any track error in `_decide_action`; foreign/missing scopes answer NotFound on every shape — `e835e91` — **done**
- **A1V-9** — `gate.decided` + `track.advanced` appended transactionally for every decision — `5105794` — **done**
- **A1V-10** — `AVAILABLE_PLANNING_EDGES` availability control (empty in A1); unshipped edges `NOT_AVAILABLE` with zero writes — `5747724` — **done**
- **A1V-11** — workflow refusal before the empty-result path in `current_lock_row` and before projection in `ProgressProjection.season_view`; V1/missing-row behavior preserved — `accd9b1` — **done**

Verification: integration v3 161 + persistence 151 = **312 passed** on the re-migrated schema; full unit + contract **3694 passed**; `make lint` clean at every commit; red recorded per finding on real PostgreSQL. No new migrations (0029 edited in place — unshipped A1 DDL). One flag for round 2, noted in the report: the review's A-T16 *evidence* gap (unseeded historical approvals, partial column comparison) sits outside the eleven findings and was not fixed here.

Report: `/root/AIVORA/drama-box/.scratch/a0d-gateway/a1-fix1-REPORT.md`
