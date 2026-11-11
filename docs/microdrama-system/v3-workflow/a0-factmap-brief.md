# Fact map for phase A0 (LLM lane): read-only, facts only

Phase A0 of `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/SPEC-v3.md` (read §10.0, §10.1,
§11 and §15) adds the `llm` job lane, an isolated `dramabox-llm` ai-route role, a machine-result interface,
quota admission, `QuotaObservation`, and LLM adapter interfaces + fakes. Map **exactly what exists**.
Cite `file:line` or `file:function` for every fact. No design advice.

## 1. `/root/.claude/scripts/ai_route.py` (+ `~/.claude/models.json`)

- How roles are defined: the role table, the fields, how a `claude-pro` role launches. Give the exact argv
  built (flags, `--output-format json`, `--permission-mode`, `--allowedTools`, `--mcp-config`, the progress
  MCP) and the env construction (`clean_env`: what is inherited, removed, added).
- Where the JSON result is parsed (around `:1443`): which fields are kept (`result`, `usage`,
  `total_cost_usd`, `session_id`, structured output) and which are dropped. What goes to `--out`,
  `runs.jsonl` and logs.
- Quota checks: how `--quota` is read for claude-pro (the source of the percentages); what happens when the
  read fails; pace refusal (`opus_min_pct_per_day_left`); concurrency limits per provider; the dup-tag
  guard; exit codes (75 etc.).
- Deadlines, timeouts, cancellation and process-group handling: whether descendants are killed.
- Settings and hooks: does a headless `claude -p` launched this way load `~/.claude/settings.json`
  hooks, plugins and MCP servers? Which flags control that (e.g. `--strict-mcp-config`, `--settings`,
  `--setting-sources`, `--disallowedTools`)? Check the installed `claude --help` output for the flags that
  exist. Report only flags that the installed CLI shows.

## 2. Drama Box (`/root/AIVORA/drama-box/microdrama/src/microdrama/`)

- **`core/jobs.py`:**
  - JobService API (enqueue with semantic key, claim/lease, complete, retry-later, needs-reconciliation,
    fail);
  - the `QueueName` (or equivalent) enum and its values;
  - the job outcome vocabulary;
  - attempt limits;
  - how a worker drains lanes.
- **`contracts/cost.py`:** the `ProviderOperation` fields (`:711–726`), the `UsageReceipt` fields and
  validators (`:194–235`), `ReceiptKind`, `CostBasis`; how `charges` and `cost_allocations` are written
  (which repo/service functions).
- **`contracts/providers.py`:** the `LLMProvider` protocol signature (`:152`) and the request/response
  types; `GenerationProvider` (`:188`).
- **`testing/fakes/llm.py`:** how `FakeLLMProvider` works.
- Every place the LLM is called today: `story/`, `research/`, `references/`. List the call sites and the
  role/profile names (`story-architect`, `story-critic`, `research-note-taker`), and how a profile maps to
  a provider in composition (`pipeline/world.py`).
- Budget reservation API used before provider calls (`budget/service.py`): the reserve/settle/release
  functions and what a reservation needs (category, operation kind, units, price quote).
- `budget/reports.py` views (`:19–75`), which the Costs page would extend.
- The migrations directory: the latest migration number; how a new table gets the guards (triggers);
  where the schema-catalog test lists the tables.

## 3. Existing subscription usage signals

- Anything already capturing Claude usage, such as ai-route `runs.jsonl` fields, so A0 knows what token
  and cost data are available today.

## Output

- Read-only: no writes, no network, no tests.
- Put the full map in your final message, at most about 220 lines, using tables.
