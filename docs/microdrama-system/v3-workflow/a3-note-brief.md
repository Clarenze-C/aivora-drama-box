# A3 design note (GLM): revision fence, cancellation, stale quarantine, per-queue workers (phase A package A3)

Orchestrator: Opus, 11 Nov 2026. You write the **design note** that the A3 build will follow. Codex
critiques it before any code is written. **This job writes one file and no code.**

## Read first

All files are in `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/`:
1. `phase-A-spec.md` **v0.3**: §0, §1, **§4, §6, §7.1 and §7.4**, §10 (the A3 row and the
   command-activation rule), §11 (A-T8, A-T12a, A-T18). This is the requirement. §7.2–§7.3 (A4) consume
   your fence and `cancel_in`; read them so your API fits.
2. `codex-a-critique.md`: AC-7, AC-15, AC-16 and AC-23 replacement wording (binding, per spec §0), **plus
   its reader/writer inventory**, which is your audit checklist.
3. `codex-a-recritique.md`: AR-4 and AR-6 (binding).
4. `A1-design-note.md` **v1.2**: §1 (migrations 0028–0031), §2.3 (tracks: the `content_revision` you
   fence on), §6 (the command table: `cancel_*` and `rewind_for_amendment` activate in A3), §9 (lock
   audit).
5. `A2-design-note.md`: its §1 migration allocation. **A3's numbers start after A2's last one.** If
   that file doesn't exist yet, name your migrations `A3-1`, `A3-2`… and say so.
6. `a-factmap.md`: facts about today's code.
7. `phase-A0-spec.md` v0.4: §5 (the runtime contract A3 consumes: `Deferred`, `defer_reason`,
   `refund_attempt`, the signal translation, `REFUSED_PRELAUNCH`; §5.3 LLM reconciliation). A3 adds no
   second variant.
8. `SPEC-v3.md` §10.0 (one persisted lifecycle; the state-mapping table) and §12.6 (amendment).

Code (read only): `/root/AIVORA/drama-box/microdrama/src/microdrama/`, `microdrama/migrations/`,
`microdrama/tests/` on branch `feat/microdrama-m0-m4`. Read especially `core/jobs.py` (`cancel()` at
`:875`, claims, leases, `defer()`), the job worker (`api/worker.py`), collectors, continuations and
reconciliation adoption. **Cite `file:line` for every claim about existing code.**

## Write

`/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A3-design-note.md`, at most about 600 lines.
Sections:

1. **Migration allocation** (see item 5 above). Applied migration bytes are never edited.
2. **Exact guarded DDL:** `expected_content_revision` on V3 job inputs (where it lives and how it is
   checked at enqueue), `stale_artifacts`, any job/lease columns, and the catalog updates. Show every
   changed CHECK beside the old one.
3. **The fence:**
   - the single helper that validates `expected_content_revision`, holding the track SHARE lock through
     the mutation's transaction;
   - **every** call site: enqueue, admission, and before every canonical mutation (collectors,
     acceptance, continuations, reconciliation adoption), as `file:function` → placement;
   - season-scope and episode-scope work;
   - how a stale result is quarantined while its money is still accounted normally.
4. **`JobService.cancel_in(tx, job_id, reason)`:** its API beside `cancel()`, lease revocation, and how a
   stale worker stops under the lease guard. The external operations of cancelled jobs go to the
   authorised reconciliation path (A0 §5.3 for LLM, the existing path for paid kinds), with exposure and
   receipts retained.
5. **Per-queue workers:** `api/worker.py --queues …`, the process set, and the checklist later phases use
   to add a lane (spec §4). Phase A adds no lanes.
6. **The command table:** one row per A3 command (`cancel_*`, `rewind_for_amendment`, and any internal
   command), with actor, scope, expected revision, prerequisites, writes, jobs, events and replay identity.
7. **Lock audit (spec §6):** every caller-owned transaction A3 adds or touches, with its locks in order.
   A worker completion that needs both track and job locks takes the track first. For each inversion
   found, the competing-transaction test that proves the fix.
8. **V1 unchanged:** every V1 path A3 touches, and how its behaviour and tests stay identical.
9. **Test plan:** A-T8, A-T12a and A-T18 → concrete test files and cases on real PostgreSQL. A-T18 needs
   a crash at each intent/submit/result/receipt boundary; include at least one real process death
   (`os._exit` or SIGKILL).
10. **Open questions:** anything the spec doesn't settle, each with a recommendation.

## Limits

- Read-only except the note file.
- No tests, no systemd units, no network, no commits.
- Never print environment variables, keys or tokens.
- No deletion commands.
- Final message: the note's path and a 10-line summary.
