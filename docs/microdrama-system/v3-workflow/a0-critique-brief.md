# Codex critique — Phase A0 spec (LLM plumbing), before the build

Spec: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-A0-spec.md`.
Master: `SPEC-v3.md` v0.4.1 (read §10.0, §10.1, §11, §15). Facts: `a0-factmap.md`. All three are in the same
folder.

Code:
- `/root/.claude/scripts/ai_route.py`, `/root/.claude/models.json`, and the installed `claude --help`;
- `/root/AIVORA/drama-box/microdrama/src/microdrama/` (`core/jobs.py`, `core/provider_ops.py`,
  `contracts/providers.py`, `contracts/cost.py`, `budget/service.py`, `story/service.py`,
  `research/service.py`, `pipeline/world.py`);
- `microdrama/deployment/compose.staging.yaml`.

## Answer

1. **Isolation.** Does §3.2 actually prevent hooks, plugins, MCP servers, built-in tools, CLAUDE.md and secret
   environment variables from reaching or executing in the child? Check each flag's real semantics in the
   installed CLI help. Can `--safe-mode` + `--tools ""` + `--strict-mcp-config` (no config) coexist with
   OAuth subscription auth? Which of the listed flags could break subscription auth? Is the
   environment-bisection approach for the OAuth allowlist sound?
2. **Process control.** Do the new-session/process-group kill, the deadline and the cancel semantics close
   the gaps in the fact map? What about the gateway → ai-route → claude chain (three levels)?
3. **Gateway.**
   - Idempotency and the `request_hash` conflict rule.
   - The restart/UNKNOWN handling.
   - Is it safe that the gateway never auto-relaunches?
   - Socket permissions and the container bind-mount (compose).
   - What happens if the container worker's lease expires mid-poll (`core/jobs.py` lease semantics)?
4. **Drama Box side.**
   - The `ProviderOperation` usage pattern (`begin` / `record_result` / `needs_reconcile`): does it match
     `core/provider_ops.py`?
   - Does a re-run of the job with the same `client_token` really reach the same `invocation_id` (check how
     story and research derive `client_token`)?
   - Is the `REFUSED` → `TransientProviderError` → RATE_LIMITED `defer` path real?
   - Would `BudgetService.reserve` accept a zero-priced quote?
   - Is emitting no `UsageReceipt` for subscription calls consistent with the existing LLM reservation and
     settle logic (reserve input/output holds, then release)? Does anything require a receipt?
5. **Master amendment v0.4.1** (no `llm` queue lane in A0): sound, given the synchronous `generate()` call
   sites and the production lane's single slot? Risks: long LLM calls blocking the production lane.
6. **Tests.** Are A0-1..10 + A0-L1 sufficient? Is the fake-claude-shim approach valid for proving isolation,
   or does only A0-L1 prove the real CLI's behaviour? What is missing?
7. **Anything else** that would make the A0 build fail, or produce an unsafe subscription adapter.

## Output

- Read-only; no writes. Put the full report in your final message, at most about 200 lines.
- Issues use IDs `A0C-1`…, with severity **BLOCKING / SHOULD-FIX / NIT** and replacement wording.
- Verdict: **APPROVE** / **APPROVE-WITH-CHANGES** / **REWORK**.
