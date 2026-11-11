# Fact map for phase A (Foundations): reuse compatibility audit, read-only

Phase A of `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/SPEC-v3.md` (v0.4.1; read §2, §3,
§9.4, §10.0, §10.5, §10.6, §12.3, §12.6, §15, §16) builds:
- gate types (incl. LAUNCH);
- the two-track state model + the `EXTENDING` flag;
- the stepper shell, episode context and waiting list;
- job workers + budget enforcement at four levels (unit, episode, season-setup sub-budget, season);
- the Costs page;
- the amendment coordinator + revision fencing;
- the outbox + Telegram bot;
- a scheduler service;
- a production-composition skeleton (fail-closed).

It owns V3-AT-1, 2, 13, 16 (superseded wording), 20, 21 and R-11.2–11.6, R-12.6, R-12.7. A0
(`phase-A0-spec.md`) adds the LLM gateway; phase A must stay compatible with it.

**Task:** for every existing component phase A reuses, report **how it works today** and **exactly where it
is incompatible with v0.4.1**. Cite `file:line` or `file:function` for every fact. Facts only; no design.

Code: `/root/AIVORA/drama-box/microdrama/src/microdrama/`, `microdrama/migrations/`, `microdrama/tests/`,
`microdrama/deployment/`. Branch `feat/microdrama-m0-m4`; also note anything in the T031 worktree
`/root/AIVORA/drama-box/.scratch/t031-fix3-worktree` that changes these components.

## Components

1. **Gates/approvals.**
   - `contracts/enums.py` `GateType`;
   - the approval SQL tables and constraints (which migration; CHECK constraints on gate type and action);
   - `review/service.py` `decide_season`, `decide_episode` (`_approve` / `_revise` / `_reject`), how
     approvals bind hashes, the idempotency key and revision;
   - `review/api.py` gate routes and the CSRF/session rules;
   - `review/gate_conditions.py`.

   What must change to add `STORY_LOCK`, `CAST_LOCK`, `TEASER_FINAL`, `LAUNCH` and a LOCK Revise action?
2. **Season/episode state.**
   - The current season and episode state columns and enums (which tables; allowed values; who writes them);
   - `ProgressStage`;
   - the scheduler selectors that choose work by state (`scheduling/service.py`, e.g. `_w03_episode_cadence`,
     `_w03_write`, `_w05_render_dispatch`).

   How would a two-track model (planning/production vs release, plus side states `WAITING_QUOTA`,
   `WAITING_PROVIDER`, `WAITING_BUDGET`, `BLOCKED`, `CANCELLED` and an `EXTENDING` flag) collide with
   them? List every reader/writer of these states.
3. **Progress projection.**
   - `review/progress.py` (`ProgressProjection`, `SeasonProgressView`, `EpisodeProgressView`, the
     denominators, the plan fingerprint);
   - the `progress.json` routes;
   - `templates/progress.html`, `workbench.html`, `base.html`, `episode.html`, `season.html`;
   - the CSS/JS approach.

   What exists for tabs, a header, an episode switcher and polling? What would a 1–10 stepper with
   per-tab statuses need?
4. **Workers and jobs.**
   - `workers/runtime.py` (`run_cycle`, slots per queue, the `RATE_LIMITED` → defer path, error mapping);
   - `api/worker.py` (the OFFLINE_MOCK refusal);
   - `pipeline/world.py` (`build_pipeline_world`, slots);
   - `core/jobs.py` statuses.

   How do handler exceptions map to job outcomes (`TransientProviderError`, `PolicyDenied`, …)?
5. **Budget.**
   - `budget/service.py`: accounts (per episode? per season? the research account), `reserve` admission
     checks, caps (`CostPolicy` $10 per episode, the shutdown reserve), `release`, `record_usage`, allocation;
   - `budget/policy.py`: queue → category ownership;
   - `budget/ledger.py`;
   - `budget/reports.py` + `budget/api.py` (`/episodes/{id}/costs`);
   - `contracts/season.py` `CostPolicy`, `contracts/primitives.py` `DEFAULT_BUDGET_ALLOCATION_MICRO_USD`.

   Is there any **season-level account or cap** today? Any **season-setup sub-budget**? What happens at a
   cap (refusal semantics, overrun exception for cleanup)? Does a zero-priced quote pass `reserve`?
6. **Amendment / invalidation.**
   - `references/v2_planning.py` `targeted_invalidation`;
   - `story/directing.py` `invalidated_shot_ids`;
   - the Gate 2 Revise targeted repair (`review/service.py` `_revise` → the repair-plan jobs);
   - any revision/version fencing of job results (input revision checks in handlers).
6b. **Identity lock.** `references/identity_lock.py` and where Gate 2 invokes it (needed for the later
   CAST LOCK migration; phase A only needs to know the coupling).
7. **Scheduler.**
   - `scheduling/service.py` `TriggerScheduler` (`fire`, triggers, catch-up/idempotency per firing);
   - `scheduling/registry.py` `default_catalog`, `scheduling/__main__.py` (one firing);
   - how a deployment timer is expected to call it;
   - any singleton/lock protection.
8. **Notifications.** Confirm there is no outbound notifier. List any existing event/outbox tables (events,
   audit logs) that an outbox could build on.
9. **Composition and deployment.**
   - `api/compose.py`, `api/serve.py` (`_build_app`), `api/worker.py`;
   - `deployment/compose.staging.yaml` (services, volumes, ports, env, user/group IDs, whether a host
     socket mount is possible);
   - config/env loading (`config.py`): the execution modes, the paid/cloud/public flags;
   - what a "production composition" would need to diverge from staging.
10. **Migrations and tests.** The latest migration on this branch and in the T031 worktree (0026); the guard
    pattern; `EXPECTED_TABLES`; the schema-catalog tests; the `make check` / `make pilot` targets.

## Output

- Read-only: no writes, no network, no tests.
- Put the full map in your final message, at most about 260 lines.
- Use one table per component with three columns: **today**, **incompatible with v0.4.1 because**, and
  **source**.
