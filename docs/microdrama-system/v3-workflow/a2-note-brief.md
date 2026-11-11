# A2 design note (GLM): budget hierarchy for phase A package A2 (money path)

Orchestrator: Opus, 11 Nov 2026. You write the **design note** that the A2 build will follow. Codex
critiques it before any code is written. **This job writes one file and no code.**

## Read first

All files are in `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/`:
1. `phase-A-spec.md` **v0.3**: §0, §1, **§5 (all of it)**, §6, §10 (the A2 row and the command-activation
   rule), §11 (A-T9, A-T10, A-T11). This is the requirement.
2. `codex-a-critique.md`: AC-8, AC-10..AC-14 replacement wording (binding, per spec §0), **plus its
   reader/writer inventory**, which is your audit checklist.
3. `codex-a-recritique.md`: **AR-1 and AR-2** (binding).
4. `A1-design-note.md` **v1.2**: §1 (migration allocation: A1 owns 0028–0031), §6 (the command table:
   `create_v3_season` and `create_v3_episodes` activate in A2), §9 (lock audit). Stay consistent with it;
   where you can't, say so in your open questions.
5. `a-factmap.md`: facts about today's code.
6. `SPEC-v3.md` §12.3 (budget enforcement) and §11 (cost meter).
7. `phase-A0-spec.md` v0.4 §5.2, §5.5, §5.6 (the unmetered `llm.subscription` kind: no reservation, no
   receipt, no charge; A2 must not meter it).

Code (read only): `/root/AIVORA/drama-box/microdrama/src/microdrama/`, `microdrama/migrations/`,
`microdrama/tests/` on branch `feat/microdrama-m0-m4`. Read especially `budget/` (`service.py`,
`billing.py`, `ledger.py`, `policy.py`, `reports.py`) and the migrations that define accounts,
reservations, charges and categories. Also read migration 0026 in
`/root/AIVORA/drama-box/.scratch/t031-gate-h2/microdrama/migrations/`. **Cite `file:line` for every claim
about existing code.**

## Write

`/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md`, at most about 600 lines.
Sections:

1. **Migration allocation.** A2's numbers start at **0032**, one purpose per migration. Applied migration
   bytes are never edited.
2. **Exact guarded DDL**, following the guard pattern the A1 note §2 describes:
   - the account kinds `SEASON_SETUP` and `SEASON` and the V3 `EPISODE` account, with the unique indexes
     and the parent references;
   - `season_budget_mutex`;
   - `budget_steps` and the `step_key` on reservations (and receipts, for attribution);
   - `account_cap_amendments` with its guard trigger, and the SQL function `md_effective_cap(account_id)`;
   - every SQL CHECK and guard that changes, **with the old rule shown beside the new one**;
   - `EXPECTED_TABLES` and catalog updates.
3. **Lookup and admission:**
   - explicit lookup per scope kind, `UNSUPPORTED_SCOPE`, and the V1-only research fallback
     (`budget/service.py:372`);
   - the admission order (unit price → step cap → child → `SEASON` aggregate), as pseudo-code against the
     real functions;
   - why admission can never exceed a cap at any level, and how truthful overrun billing and
     `BLOCKED (overrun)` work;
   - cleanup and shutdown are never refused.
4. **The pre-STORY LOCK protocol (AR-2)** and the STORY LOCK transaction (attach setup exposure, create the
   episode accounts, validate against the `SEASON` base cap). **AR-1:** setup consumes the `SEASON`
   envelope and is never added to it. Show the arithmetic of A-T9 (10 episodes + $30 setup ≤ $100).
5. **Cap amendments:** the command, authorisation (human session), idempotency, serialisation with
   admission, the ancestor-limit validation, and the same-transaction `retry_at` wakeup of `RETRY_WAIT`
   jobs with `defer_reason = BUDGET` (A0's column).
6. **Forecasts** (spec §5.5) and **the Costs data API** (spec §5.6): each quantity → the exact ledger
   query, with setup counted once and attribution never counted as cash.
7. **The command table:** one row per A2 command (setup-budget approval, `create_v3_season`,
   `create_v3_episodes`, amendments, the STORY LOCK budget step), with actor, scope, expected revision,
   prerequisites, writes, events and replay identity.
8. **Lock audit (spec §6 #7):** every caller-owned transaction A2 adds or touches, with its locks in order:
   reserve, release, expiry, GPU accrual, usage posting, settlement, adjustment, transfers, and the shared
   helpers that lock a child first (`budget/billing.py:1296`). Include provider-operation advisory locks.
   For each inversion found, the competing-transaction test that proves the fix.
9. **V1 unchanged:** list every V1 path A2 touches and how its behaviour and tests stay identical.
10. **Test plan:** A-T9..A-T11 → concrete test files and cases on real PostgreSQL with two or more
    connections, including the negative cases in spec §11.
11. **Open questions:** anything the spec doesn't settle, each with a recommendation.

## Limits

- Read-only except the note file.
- No tests, no systemd units, no network, no commits.
- Never print environment variables, keys or tokens.
- No deletion commands.
- Final message: the note's path and a 10-line summary.
