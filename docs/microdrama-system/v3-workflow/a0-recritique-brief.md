# Codex re-critique (round 2 of 2): Phase A0 spec v0.2 (LLM plumbing), before the build

Spec: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-A0-spec.md` **v0.2**.
Your round-1 report: `codex-a0-critique.md` (A0C-1..18, verdict REWORK). v0.2 §12 maps each finding to
the section that resolves it.
Master: `SPEC-v3.md` **v0.4.2** (it changes §1 rule 3, §10.0 rows, §10.1, §15 A0 row to match).
Facts: `a0-factmap.md`, `a-factmap.md`. All are in the same folder.

Code (read-only):
- `/root/.claude/scripts/ai_route.py`, `/root/.claude/models.json`, the installed `claude --help`;
- `/root/AIVORA/drama-box/microdrama/src/microdrama/`: `core/jobs.py`, `core/provider_ops.py`,
  `workers/runtime.py`, `contracts/cost.py`, `contracts/providers.py`, `budget/service.py`,
  `budget/policy.py`, `config.py`, `pipeline/world.py`;
- `microdrama/deployment/compose.staging.yaml`.

## Scope: this is a re-review

Check **only**:
1. For each A0C-1..18: is it **RESOLVED**, **PARTIAL** or **NOT RESOLVED** by v0.2? One line of evidence
   each (spec section + code fact).
2. **New defects introduced by the v0.2 design**, specifically:
   - `LlmStep` + `WaitExternalSignal` (§5.1–5.2): does the existing runtime `WaitExternal` outcome
     really release the lease, preserve attempts and re-claim later (`core/jobs.py`, `workers/runtime.py`)?
     Is the new `Deferred` outcome → `JobService.defer()` mapping feasible without breaking V1?
   - The unmetered kind (§5.4): is `reservation_id=None` + a SQL CHECK + `NOT_STARTED_REFUSED` consistent
     with the `ProviderOperation` contract and its guards? Which existing tests or guards would it break?
   - The per-invocation `systemd-run` unit (§4.3): does the property set work for a unit that must read
     `/root/.claude` credentials and run `claude` (e.g. `ProtectSystem=strict` + `ReadWritePaths`,
     `InaccessiblePaths=/root/AIVORA` while ai-route lives in `/root/.claude/scripts`)? Is the crash-recovery
     table complete?
   - The verified-boundary self-check (§3.3) and live qualification (§7): is each check implementable
     with the installed CLI?
   - Socket permissions (§4.1): fixed GID + `group_add` + directory bind mount with the container's UID.

Do not re-open design choices that v0.2 settled unless they are unsafe or unbuildable.

## Output

- Read-only; no writes. Put the full report in your final message, at most about 150 lines.
- A table A0C-1..18 → RESOLVED / PARTIAL / NOT RESOLVED + evidence.
- New issues use IDs `A0R-1`…, with severity **BLOCKING / SHOULD-FIX / NIT** and replacement wording.
- Verdict: **APPROVE** / **APPROVE-WITH-CHANGES** / **REWORK**.
