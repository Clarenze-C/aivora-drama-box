# A1 design note (GLM): contracts, discriminator, gates and tracks for phase A package A1

Orchestrator: Opus, 11 Nov 2026. You write the **design note** that the A1 build will follow. Codex
critiques it before any code is written. **This job writes one file and no code.**

## Read first

All files are in `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/`:
1. `phase-A-spec.md` **v0.3**: §0, §1, §2, §3, §6, §10 (the A1 row and the command-activation rule),
   §11 (A-T1..A-T6, A-T16). This is the requirement.
2. `codex-a-critique.md`: AC-1..9 and AC-22/23 replacement wording (binding, per spec §0), **plus its
   reader/writer inventory**, which is your audit checklist.
3. `codex-a-recritique.md`: AR-3, AR-4, AR-6 (binding).
4. `a-factmap.md`: facts about today's code.
5. `SPEC-v3.md` §2.1 (gates) and §2.2 (track states and graph).
6. `phase-A0-spec.md` v0.4 §5.2, §5.5, §5.6 (what A0 changes in jobs, provider operations and migration
   0027; A1 must not duplicate it).

Code (read only): `/root/AIVORA/drama-box/microdrama/src/microdrama/`, `microdrama/migrations/`,
`microdrama/tests/` on branch `feat/microdrama-m0-m4`. Also read migration 0026 in
`/root/AIVORA/drama-box/.scratch/t031-gate-h2/microdrama/migrations/`. **Cite `file:line` for every claim
about existing code.**

## Write

`/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A1-design-note.md`, at most about 600 lines.
Sections:

1. **Migration allocation.**
   - A0 = 0027. Allocate A1's numbers from 0028, with one purpose per migration.
   - **Never edit applied migrations.**
2. **Exact guarded DDL** for each new or changed object, following the repo's guard pattern (append-only,
   no delete/truncate, integer-only JSON, catalog registration):
   - `seasons.workflow_version` with its immutability guard, and the episode re-parent guard;
   - the `GateType` additions;
   - **version-aware constraint triggers replacing the 0002 gate/entity/action/feedback CHECKs, with V1
     rules reproduced exactly** (show the old CHECK beside the new rule);
   - `season_revision_notes`, `gate_activations`, `season_tracks`, `episode_tracks`,
     `season_extensions`;
   - the V3 job work-scope columns (`track`, `extension_id`, `logical_work_id`, `replaces_job_id`);
   - `alert_dismissals`;
   - the `track_waits` view (full SQL);
   - `EXPECTED_TABLES` and catalog updates.
3. **Ownership conflict to flag.** Master §10.0 says A0 owns jobs/provider-operation schema additions.
   State precisely which job columns A0 adds (per A0 v0.4) and which A1 adds, so nothing is added twice.
   The orchestrator will amend the master wording.
4. **Contracts:**
   - `V3_GATE_ACTIONS` and the V3 decision command model (`RevisionNotes`, typed targets);
   - the generated contracts/examples that change (the V1 ones must not change; note the invalid
     `gate1_revise` example at `contracts/examples.py:2180` and how it is handled without changing V1
     behaviour).
5. **The decision transaction (spec §2.6):**
   - the binding-resolver API;
   - the `GateHandler` registry API (scope, binding, conditions, callbacks, all taking the caller's
     `tx`);
   - the handler-registration rules (test-world only, no V1 fallback);
   - the step order;
   - what V1 keeps unchanged (`core/approvals.py:64`).
6. **The command table:** one row per §3 command, with:
   - actor, scope, expected revision, exact source → target states, hash-bound prerequisites, writes,
     jobs, events, replay identity;
   - **activation**: A1, or `NOT_AVAILABLE` until A2/A3, per AR-6.
7. **The `require_workflow` inventory:**
   - every legacy entry point from the critique's inventory (research, intake, story, references, editing,
     QA repair, packaging, publishing, analytics, every scheduler selector including `_w02_compile_backstop`,
     `_w05_render_poll`, `_w09_*`, `_w11_analytics`), as `file:function` → guard placement;
   - the per-version adapters for the shared janitors.
8. **GPU human-wait safety (AC-9):**
   - where V3 wait checks attach: gate/pick activation, lease admission, heartbeat, claim/adoption/
     transfer, janitor candidate + `_cause`;
   - with `file:line`.
9. **Lock audit:**
   - every caller-owned transaction A1 adds or touches, with its locks in order against spec §6;
   - every inversion found, and the competing-transaction test that proves the fix.
10. **Test plan:** A-T1..A-T6 + A-T16 → concrete test files and cases, including the negative cases in
    spec §11 and a migration upgrade on a populated V1 database.
11. **Open questions:** anything the spec doesn't settle, each with a recommendation.

## Limits

- Read-only except the note file.
- No tests, no systemd units, no network, no commits.
- Never print environment variables, keys or tokens.
- No deletion commands.
- Final message: the note's path and a 10-line summary.
