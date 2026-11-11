Read-only inspection completed; no network calls or tests. Runtime behaviour below is sourced from code and installed CLI help, not a new headless invocation.

| Citation notation | Location |
|---|---|
| `ai_route.py`, `ai_route_mcp.py` | [/root/.claude/scripts](/root/.claude/scripts) |
| `models.json`, `settings.json` | [/root/.claude](/root/.claude) |
| Python paths below | Relative to [/root/AIVORA/drama-box/microdrama/src/microdrama](/root/AIVORA/drama-box/microdrama/src/microdrama) |
| `migrations/`, `tests/` | Relative to [/root/AIVORA/drama-box/microdrama](/root/AIVORA/drama-box/microdrama) |
| `CLI:--help` | Installed [/root/.local/share/claude/versions/2.1.322](/root/.local/share/claude/versions/2.1.322), invoked with `--help` |
| `SPEC-v3.md` | [Requested master spec](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/SPEC-v3.md) |

| Spec boundary | Recorded scope | Source |
|---|---|---|
| Existing infrastructure | JobService + ProviderOperation; UsageReceipt/charges + cost_allocations; existing budget reports. | `SPEC-v3.md:613–638` |
| A0 | Isolated `dramabox-llm` role, machine-result interface, quota admission, jobs/provider-operation schema additions, QuotaObservation, LLM adapter interfaces and fakes. | `SPEC-v3.md:836–856` |
| A | Workers, enforcement, views and Costs page belong to phase A. | `SPEC-v3.md:637–638,843–844` |
| Isolation requirement | No inherited tools/MCP/plugins/hooks; credential allowlist; deadlines/cancellation kill descendants; adapter disabled unless isolation established. | `SPEC-v3.md:640–664` |
| Accounting requirement | Cash, subscription allocation, API-equivalent estimates, quota and operational exposure reported separately; quota observations include concurrent usage and uncertainty. | `SPEC-v3.md:719–733` |

| ai-route roles and launch | What exists | Source |
|---|---|---|
| Role registry | JSON `roles` map; names beginning `_` excluded. No `dramabox-llm` entry. | `models.json:8–76`; `ai_route.py:134–135` |
| Current roles | `plan`→claude-pro; `goldfish`, `build`, `swarm`, `fast`→zai; `build-luna`, `critique`, `review`→codex. | `models.json:10–75` |
| Role fields | Existing entries use `provider`, `model`, `family`, `variant`, `effort`, `max_budget_usd`, `permission_mode`, `autocompact_window`, `requires_plugin`, `prompt_template`, `env`, `sandbox`, `review`, `metered`, `use_for`. | `models.json:10–75` |
| Model resolution | Explicit `model` wins; otherwise family `api_id_upper` or `api_id`, then explicit `variant` or family `cc_model_suffix`; absent family/model returns `None`. | `ai_route.py:138–149` |
| Current Pro role | `plan`: model alias `opus`, effort `high`, budget cap `8`, permission mode `auto`. | `models.json:10–16` |
| Headless selection | Pro is headless when prompt is nonempty and `--interactive` is false; zai is always headless. | `ai_route.py:212–214` |
| Exact current `plan` argv, with prompt/default options | `["claude","-p","--model","opus","--output-format","json","--permission-mode","auto","--effort","high","--max-budget-usd","8","--mcp-config",<JSON below>,"--allowedTools","mcp__ai-route__step","--session-id",<new UUID>]`. | `ai_route.py:217–238,1385–1389` |
| MCP JSON argument | `{"mcpServers": {"ai-route": {"command": <sys.executable>, "args": ["/root/.claude/scripts/ai_route_mcp.py"]}}}` serialized using `json.dumps`. | `ai_route.py:74–75,228–230` |
| Optional argv changes | CLI effort overrides role effort; role budget adds `--max-budget-usd`; supplied worktree adds `--worktree <name>`; `--no-steps` omits progress MCP/allowedTools and prompt paragraph, but retains session ID. | `ai_route.py:222–230,1385–1389` |
| Prompt delivery | File contents or stdin become prompt; headless child receives it on stdin, followed by EOF. Progress instructions are appended unless `--no-steps`. | `ai_route.py:1316–1322,1388–1389,1406–1412` |
| Progress MCP implementation | Stdio server exposes only `step`; schema has `done`, `total`, `note`, requires `done`; tool call returns `"ok"`. | `ai_route_mcp.py:17–51` |
| Interactive Pro | `["claude","--model",model]`, optional CLI effort and positional prompt; `execvpe` replaces router; `--out` ignored and run unrecorded. | `ai_route.py:234–244,1353–1361` |
| Pro caller restriction | Headless Pro is refused for Codex ancestry or GLM caller environment, exit 2. Applies by provider, not just role name. | `ai_route.py:548–563,1363–1367` |
| Environment inherited | `clean_env` copies **all** parent variables except the explicit provider-variable removal list; no credential allowlist. Pro adds OTEL attribution and does not apply `role_env`. | `ai_route.py:204–209,234–244` |
| Removed environment keys | `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL`, `ANTHROPIC_DEFAULT_HAIKU_MODEL`, `CLAUDE_CODE_SKIP_AUTH_LOGIN`, `CLAUDE_CODE_DISABLE_ARTIFACT`, `CLAUDE_CODE_AUTO_COMPACT_WINDOW`. | `ai_route.py:108–114` |
| Added environment key | Replaces `OTEL_RESOURCE_ATTRIBUTES` with `service.name=claude-code,cwd=<resolved cwd>`. Other environment variables remain inherited. | `ai_route.py:204–209` |
| Role-specific environment | `role_env` rejects `ANTHROPIC_*` and `CLAUDE_CODE_*`; values become strings. Called by zai builder only. | `ai_route.py:172–181,247–265` |

| Machine results and persistence | What exists | Source |
|---|---|---|
| JSON parsing | Non-Codex stdout parsed once after child exits; reads `modelUsage`, `result`, `is_error`, `num_turns`, `session_id`, `subtype`. | `ai_route.py:1443–1458` |
| Token capture | Sums each model’s `inputTokens`, `cacheReadInputTokens`, `cacheCreationInputTokens`, `outputTokens` into `input`, `cache_read`, `cache_creation`, `output`; `total` sums those four. | `ai_route.py:97–99,1451–1455` |
| Per-model retention | Retains sorted model names as `models_used`; individual model usage objects and their individual counts are discarded. | `ai_route.py:1451–1455,1472–1476` |
| Dropped result fields | Top-level `usage`, `total_cost_usd`, structured output and other unreferenced JSON fields are neither copied to output nor recorded. `subtype`/`is_error` affect exit classification but are not recorded as fields. | `ai_route.py:1450–1476` |
| `--out` | Writes only `result + "\n"` for Claude children; default `~/.cache/ai-route/<UTC stamp>-<role>-<router PID>.md`. No result means no answer write. | `ai_route.py:1375–1379,1459–1460` |
| Run journal | Appends one JSON object to `OUT_DIR/runs.jsonl`; `OUT_DIR` defaults to `~/.cache/ai-route`, overridable by `AI_ROUTE_OUT`. | `ai_route.py:65,1198–1201` |
| Journal fields | `ts`, `role`, `tag`, `provider`, `model`, `models_used`, `cwd`, `exit`, `secs`, `turns`, `tokens`, `session_id`, `out`, `pid`, `task`, `log`, `owner_session`. | `ai_route.py:1472–1476` |
| Timing/session | `ts` is launch UTC stamp; `secs` is monotonic elapsed duration rounded to 0.1 seconds. Returned session ID wins, otherwise preallocated session ID. No invocation-ID dedupe in `record()`. | `ai_route.py:1375,1385–1394,1405–1418,1472–1476`; `ai_route.py:record` |
| Logs/stdout | Child stderr goes to `<stamp>-<role>-<PID>.log`; child stdout remains in memory for parsing. Router prints answer to stdout and summary/errors to stderr. Full Claude result JSON is not archived by this path. | `ai_route.py:1390,1407–1418,1482–1489` |
| Parse failure | Invalid JSON is ignored; no parsed answer/token fields. Raw stdout may enter diagnostic classification/error tail, but is not written wholesale to a result archive. | `ai_route.py:1457–1458,1464–1484` |
| Persistence order | Answer write → journal append → answer/summary print. No atomic transaction ties these files together. | `ai_route.py:1459–1490` |

| Quota, concurrency and process control | What exists | Source |
|---|---|---|
| Claude percentage source | Reads OAuth access token from `~/.claude/.credentials.json`; GETs `https://api.anthropic.com/api/oauth/usage` with bearer token and `anthropic-beta: oauth-2025-04-20`, HTTP timeout 15 seconds. | `ai_route.py:91–92,407–422` |
| Quota windows | Raw `five_hour.utilization`→`5h.pct`; `seven_day.utilization`→`week.pct`; `resets_at` parsed to epoch. Display rounds to whole percent; admission uses raw float. | `ai_route.py:423–432,474–484` |
| Unreadable quota | Credential/read/parse failures return `None`; `--quota` prints “could not read” and returns 0. Launch preflight **does not block** unreadable windows. Orchestrator recommendation counts unreadable Opus against selecting Opus. | `ai_route.py:407–432,455–506` |
| Pace refusal | `(100 - weekly_pct) / days_to_reset`; minimum remaining duration one hour, missing reset assumes seven days. Refuses below configured `opus_min_pct_per_day_left`, currently 8. | `ai_route.py:435–447,490–497`; `models.json:4–6` |
| Spent-window admission | Refuses at ≥100% only when reset is in the future; monthly windows skipped; ≥90% warns. `--no-quota-check` bypasses this preflight. | `ai_route.py:490–506,1369–1373` |
| Concurrency | Pro: one registered live job. Codex: two, using maximum of discovered Codex jobs and registered Codex jobs. No zai concurrency cap in `claim()`. | `ai_route.py:88–89,1424–1440` |
| Duplicate guard | Rejects a live matching nonempty tag **or** semantic job hash. Hash covers role, cwd, prompt, base, worktree; effort is absent. Check/register occurs under `flock`. | `ai_route.py:1223–1226,1384,1395–1403,1424–1430` |
| Exit codes | 0 success/dry-run/quota display; 2 usage/config/caller/duplicate refusal; 75 quota/pace/concurrency refusal or detected provider rate limit; completed ordinary error becomes 1. | `ai_route.py:121–123,1278–1285,1345–1373,1424–1490` |
| Cap errors | `subtype` beginning `error_max` is classified as role-cap failure, not provider quota; normal error exit 1. | `ai_route.py:1469–1484` |
| Execution deadline | Child `communicate()` has no timeout. Router’s `--timeout` applies only to `--wait`. `--wait` timeout returns 124 and leaves target jobs running. | `ai_route.py:1257,1407–1415,1062–1109` |
| Cancellation/process groups | Popen creates no new session/process group. Exception during `communicate()` calls `child.kill()` only; no descendant traversal, group kill or cancellation API in this launch path. | `ai_route.py:1404–1421` |
| Refusal persistence | Preflight and claim refusals return before `finish()`; no `runs.jsonl` refusal record or durable retry timestamp is written there. | `ai_route.py:1369–1373,1397–1402,1472–1476` |

| Installed CLI/settings | Confirmed controls and current use | Source |
|---|---|---|
| Default headless configuration | `-p` is noninteractive output, not customization isolation. Router supplies none of the installed settings/hook/plugin isolation controls below; normal configured hooks/plugins/MCP loading is not suppressed. No fresh invocation was run to observe hook execution. | `CLI:--help`; `ai_route.py:217–244,1385–1389` |
| User hooks | Settings configure SessionStart, PreToolUse, PostToolUse, PostToolUseFailure and SubagentStart command hooks, among other lifecycle hooks. | `settings.json:18–162` |
| Plugins/MCP settings | Enabled MCP names include `supabase`, `aivora-memory`, `playwright`; enabled plugins include context-mode, runpod, EGM and others. | `settings.json:13–17,168–181` |
| `--mcp-config <configs...>` | Loads MCP JSON files/strings. Router supplies progress server; it does not supply strict MCP mode. | `CLI:--help`; `ai_route.py:228–230` |
| `--strict-mcp-config` | Uses only MCP servers supplied by `--mcp-config`, ignoring other MCP configurations. | `CLI:--help` |
| `--settings <file-or-json>` | Loads **additional** settings. | `CLI:--help` |
| `--setting-sources <sources>` | Selects comma-separated setting sources: `user`, `project`, `local`. | `CLI:--help` |
| `--allowedTools`, `--disallowedTools` | Allow/deny tool names; aliases `--allowed-tools`, `--disallowed-tools` exist. Router only allows progress tool explicitly; it supplies no deny list. | `CLI:--help`; `ai_route.py:220–230` |
| `--tools <tools...>` | Controls built-in tool availability; empty string disables built-in tools; `default` selects defaults. | `CLI:--help` |
| `--permission-mode`, `--permission-prompts` | Modes: `acceptEdits`, `auto`, `bypassPermissions`, `manual`, `dontAsk`, `plan`. Print permission-prompt targets: `host` or `none`; `none` automatically denies requests that would prompt. | `CLI:--help` |
| `--safe-mode` | Disables customizations including CLAUDE.md, skills, installed plugins, hooks and MCP; managed policy settings still apply; auth, model selection, built-in tools/plugins and permissions remain. | `CLI:--help` |
| `--bare` | Skips settings/plugin hooks, plugin sync, several startup features and CLAUDE.md discovery. Sets `CLAUDE_CODE_SIMPLE=1`; OAuth/keychain auth is not read; Anthropic auth uses API key or settings apiKeyHelper. | `CLI:--help` |
| `--restricted` | Ignores user/project/local settings; managed and explicit settings apply. Removes specified command/code tools and WebFetch unless explicitly selected; MCP suppression additionally uses strict MCP mode. | `CLI:--help` |
| Other existing controls | `--disable-slash-commands`, `--plugin-dir`, `--plugin-url`, `--json-schema`, `--no-session-persistence`, `--include-hook-events` are shown. Hook events require stream-json. | `CLI:--help` |

| Durable jobs | What exists | Source |
|---|---|---|
| Enqueue API | `enqueue(tx, *, job_type, semantic_key, payload, episode_id=None, season_id=None, correlation_id=None, causation_id=None, run_after=None, max_attempts=3, priority=100) -> EnqueueResult`. | `core/jobs.py:353–367` |
| Idempotency/routing | Job spec supplies queue/input type; caller cannot select queue. Semantic-key insert conflicts return existing matching type/input; differing content raises IdempotencyConflict. | `core/jobs.py:1–14,353–441`; `contracts/jobs.py:56–69` |
| Queue enum | Exactly `PRODUCTION="production"`, `PUBLICATION="publication"`, `COMMUNITY="community"`; no `llm`. | `contracts/enums.py:242–245` |
| Current job routing | Research, story compile/write and references prepare jobs use production. | `contracts/jobs.py:67–101` |
| Claim API | `claim(queue, *, worker_id, lease_ms, now=None) -> Job|None`; due jobs ordered by priority/run_after/created_at; `FOR UPDATE SKIP LOCKED`. | `core/jobs.py:478–550` |
| Lease semantics | QUEUED claim increments attempt; WAITING_EXTERNAL polling does not. Heartbeat extends only a live owned lease; lease maximum 24 hours. | `core/jobs.py:187–191,525–533,591–618` |
| Transaction lease guard | `lease_guard(tx, job_id, *, worker_id, now=None)` holds shared row lock and rejects lost lease. | `core/jobs.py:629–654` |
| Completion API | One `finish(job_id, *, worker_id, outcome, now=None)` handles completion, retry, failure and reconciliation; no separate `complete()` API. | `core/jobs.py:658–702` |
| Handler outcomes | `Succeeded(result)`, `WaitExternal(external_id,poll_after_ms)`, `RetryLater(error_code,retry_after_ms)`, `Failed(error_code,detail="")`, `NeedsReconciliation(detail,external_id=None)`. | `core/jobs.py:59–88` |
| Persisted statuses | QUEUED, RUNNING, WAITING_EXTERNAL, RETRY_WAIT, SUCCEEDED, FAILED, NEEDS_RECONCILIATION, CANCELLED. | `contracts/enums.py:115–123` |
| Attempt bounds | Default 3; enqueue permits integers 1–10. RetryLater reaches FAILED with `MAX_ATTEMPTS:<code>` when allowance exhausted. | `core/jobs.py:233–245,365–379` |
| Quota deferral | `defer(job_id, *, worker_id, retry_after_ms, now=None)` restores claim attempt, records RATE_DEFERRED and moves to RETRY_WAIT. Runtime uses this for RATE_LIMITED. | `core/jobs.py:552–589`; `workers/runtime.py:216–235` |
| Unknown external work | Claim/finish quarantine in-flight ambiguity. Expired lease requeues only without in-flight operations and with attempts left; otherwise reconciliation or failure. | `core/jobs.py:478–523,658–750` |
| Reconciliation API | `resolve_reconciliation(... actor,resolution,evidence,...)`; owner/operator only; RESUME/SUCCEEDED/FAILED with operation-evidence conditions. | `core/jobs.py:752–780` |
| Cancellation | `cancel(job_id, *, reason, now=None)` changes job state/removes lease; explicitly does not cancel external work or release its reservation. | `core/jobs.py:864–888` |
| Lane draining | Single-threaded `run_cycle()` visits deployment queues in declaration order, executes up to each queue’s slots. `run_cycles(max_cycles=100)` stops when all queues idle or cap reached. | `workers/runtime.py:7–12,175–212` |
| Composed slots | Production 1, publication 1, community 2; default worker lease 300,000 ms. | `pipeline/world.py:193–212`; `workers/runtime.py:119` |

| Provider and money contracts | Fields/behaviour | Source |
|---|---|---|
| Shared payload base | Contract payloads are frozen, reject extra fields; VersionedPayload adds `schema_version="1.0"`. | `contracts/primitives.py:155–172` |
| ProviderOperation fields | `operation_id`, `provider`, `operation_kind`, `client_token`, `request_sha256`, optional `job_id`, optional `reservation_id`, `state`, optional `external_id`, `attempt=1`, optional `submitted_at`, required `deadline_at`. | `contracts/cost.py:711–725` |
| Operation persistence API | `begin`, `load`, `record_result`, `needs_reconcile`, `resubmit_allowed`; recorded result updates state/last_result and emits event. Deadline expiration marks in-flight calls eligible for reconciliation, not process termination. | `core/provider_ops.py:99,145,288–345` |
| UsageReceipt identity/scope | `receipt_id`, `provider`, `provider_receipt_id`, `kind`, `cost_basis`; optional `reservation_id`, `episode_id`, `season_id`, `job_id`. | `contracts/cost.py:194–205` |
| UsageReceipt amount/measurement | `category`, `amount_micro_usd`, `currency="USD"`, `units`, `unit`, optional paired interval bounds, `observed_at`, `provenance`. | `contracts/cost.py:206–214` |
| Receipt validators | ESTIMATED rejected; fake provenance iff SYNTHETIC_FAKE; measured bases require LIVE_PROVIDER; interval endpoints paired and ordered. `measured` means PROVIDER_REPORTED or BILLED. | `contracts/cost.py:216–235` |
| ReceiptKind | ACCRUAL, SETTLEMENT, CREDIT, ADJUSTMENT. | `contracts/enums.py:214–218` |
| CostBasis | SYNTHETIC_FAKE, ESTIMATED, PROVIDER_REPORTED, BILLED. | `contracts/enums.py:205–211` |
| Charge writes | `BudgetService.record_usage()` → `record_usage_in_transaction()` → `_post_charge()` → `_insert_charge()` inserts `charges`, including full receipt JSON, under account/category locks. | `budget/service.py:834–880,1139–1191` |
| Charge deduplication | Provider + provider_receipt_id and receipt_id checked; identical receipt replays return prior charge; differing keys/content/scope conflict. | `budget/service.py:1082–1116` |
| Allocation writes | `allocate_research_cost()` / `_allocate_research_cost()` split eligible research charges across episode accounts and insert `cost_allocations`; ledger settled counters updated. | `budget/service.py:1276–1370` |
| LLMProvider | Runtime-checkable protocol: `provider_id: str`; synchronous `generate(request: LLMRequest) -> LLMResponse`. | `contracts/providers.py:151–155` |
| LLMRequest | `request_id`, `role`, `model_config_ref`, `instruction`, `untrusted_documents=[]`, `output_schema`, `max_input_tokens`, `max_output_tokens`, `client_token`, optional `reservation_id`. No deadline/cancellation field. | `contracts/providers.py:127–139` |
| LLMResponse | `request_id`, `output: dict`, `stop_reason`, `usage: list[UsageReceipt]=[]`, `model_config_ref`, `provenance`. No session/model-token/cache/estimated-cost fields. | `contracts/providers.py:142–148` |
| GenerationProvider | `provider_id`; `submit(op, ImageRequest|VoiceRequest)`, `status(op)`, `reconcile(op)` returning ProviderOperationResult; `fetch_output(OutputRef)->bytes`. | `contracts/providers.py:187–203` |
| Generation reservation | ImageRequest and VoiceRequest require reservation_id; LLMRequest allows it to be absent. | `contracts/providers.py:139,161–184` |

| Fake LLM and current call sites | What exists | Source |
|---|---|---|
| Fake identity/scenarios | `FakeLLMProvider.provider_id="fake-llm"`; HAPPY, TRANSIENT_TIMEOUT, DENIED, MALFORMED_OUTPUT. Timeout raises TransientProviderError; denied raises PolicyDenied. | `testing/fakes/llm.py:35–39,77–117` |
| Fake output selection | Scripted client token first, scripted runtime role second, deterministic schema synthesis otherwise. Malformed scenario removes required key or returns marker. | `testing/fakes/llm.py:42–70,93–121` |
| Fake replay | Cached response by client_token; replay logs without fresh billing. | `testing/fakes/llm.py:107–110,153–163` |
| Fake usage | Tokens approximated as ceil(chars/4), capped by request limits; input/output separately rounded to 1K units and emitted as synthetic SETTLEMENT receipts; response provenance FAKE_SYNTHETIC. | `testing/fakes/llm.py:73–74,123–163` |
| Story writer | `_writer_attempt()` → `_call_llm()` → `.generate()`; role STORY_ARCHITECT, profile `story-architect`. | `story/service.py:1188–1200,1257–1266`; `story/prompts.py:21` |
| Story critic | `_critic_attempt()` → same `_call_llm()`; role CRITIC, profile `story-critic`. | `story/service.py:1292–1303`; `story/prompts.py:22` |
| V2 bible/episode packs | `generate_rich_bible()` and `generate_episode_pack()` → `_invoke()` → `.generate()` at 1043; role STORY_ARCHITECT; both profiles `story-architect`. | `story/script_maker.py:686–715,731–835,965,1043–1054`; `story/prompts.py:23–24` |
| Research notes | Research service `.generate()` at 740; role RESEARCHER, profile `research-note-taker`. | `research/service.py:727–752` |
| Script Maker research | Research ScriptMakerService `.generate()` at 369; role STORY_ARCHITECT, profile `story-architect`. | `research/script_maker.py:363–381` |
| References | No LLMProvider call in this service. Three `.generate()` sites invoke GenerationAdapter for voice anchor, image anchor, dialogue voice line. | `references/service.py:760–772,809–821,1029–1042`; `references/generation.py:202–250` |
| Composition/profile mapping | `build_pipeline_world()` injects the **same** `fakes.llm` into research, story and Script Maker; no profile→live-provider lookup there. References receive `fakes.generation` for image and voice. | `pipeline/world.py:342–383` |
| Factory boundary | Fake factory requires OFFLINE_MOCK and creates one FakeLLMProvider. Current inspected composition is explicitly offline/mock. | `testing/fakes/factory.py:51–69`; `pipeline/world.py:335` |
| Existing adapter surface | Current generic LLM interface is LLMProvider/LLMRequest/LLMResponse; current composed implementation is FakeLLMProvider. The requested isolated role is absent from the role table. | `contracts/providers.py:127–155`; `testing/fakes/factory.py:68`; `models.json:8–76` |

| Budget and reporting | What exists | Source |
|---|---|---|
| Reservation API | `BudgetService.reserve(BudgetReservationRequest)->Reservation`; validates queue/category, price, scope and available exposure before holding budget. | `budget/service.py:323–375` |
| Reservation request fields | `request_id`, semantic_key, scope_kind, optional episode/season/job IDs, category, queue, provider, operation_kind, price, ceilings, worst_case_micro_usd, cleanup flag, expires_at. | `contracts/cost.py:133–158` |
| Units/pricing | ExposureCeilings requires timeout_ms/max_units; optional input/output token and media limits. PriceQuote requires currency/unit/unit_price_micro_usd/source/price_table_version/as_of. | `contracts/cost.py:48–68` |
| Exposure validation | Token/media unit pricing requires corresponding ceilings; exposure units are max(explicit max_units, derived ceiling units); worst-case money must cover price×units. Missing/unknown price is refused by service. | `contracts/cost.py:112–130,160–191`; `budget/service.py:323–348` |
| Queue ownership | Production owns protected categories; publication CPU_STORAGE_TRANSFER; community METERED_MANAGEMENT. No llm ownership entry. | `budget/policy.py:27–49` |
| Settlement API | No separate BudgetService `settle()`; `record_usage()` with SETTLEMENT invokes `Ledger.apply_receipt()`, replaces accrued amount, frees remaining hold and marks reservation SETTLED. | `budget/service.py:834–880,1166`; `budget/ledger.py:303–348` |
| Release API | `release(reservation_id, *, reason)->Reservation`; rejects accrued usage and in-flight provider operations; Runpod lease holds have additional finality checks. | `budget/service.py:484–543` |
| Current LLM reservation pattern | Separate input/output holds; request carries input hold; output receipt is attributed to output hold; receipts posted through record_usage; unbilled failures release holds. | `story/service.py:1173–1226`; `research/service.py:734–773` |
| Report summary | Episode cap, settled, accrued, outstanding reservations, protected shutdown reserve, remaining admission headroom and synthetic-fake amount. | `budget/reports.py:19–55` |
| Cost view | Direct charges plus joined research allocations; includes overruns and expired/unsettled reservations. Reads use REPEATABLE READ, READ ONLY transactions. | `budget/reports.py:58–135` |

| Migrations and schema guards | What exists in this checkout | Source |
|---|---|---|
| Latest migration | `0025_t045_billing_finality.sql`; migration-tail expectations end at `0025`. | `migrations/0025_t045_billing_finality.sql:1–12`; `tests/integration/persistence/test_migrations.py:145,214,270` |
| Discovery | Sorted `*.sql` matching four-digit prefix/name; checksums calculated; duplicate versions refused. | `persistence/migrate.py:24–26,45–56` |
| Guard creation | Historical migration 0009 installs guards on then-existing tables; its loop is not an automatic future-table hook. Later migrations explicitly create their own triggers. | `migrations/0009_m0_round3_hardening.sql:65–113`; `migrations/0019_v2_contract_documents.sql:33–38` |
| Trigger forms | BEFORE DELETE row and BEFORE TRUNCATE statement → `md_forbid_mutation`; BEFORE INSERT OR UPDATE row → `md_forbid_non_integer_numbers`. | `migrations/0019_v2_contract_documents.sql:33–38` |
| Integer guard | Inspects `to_jsonb(NEW)` recursively for noninteger numeric representations and raises check_violation. | `migrations/0009_m0_round3_hardening.sql:85–101` |
| Catalog test table discovery | `test_schema_catalog.py:_catalog` queries all public ordinary tables and noninternal triggers; no manually maintained table list there. | `tests/integration/persistence/test_schema_catalog.py:22–37` |
| Catalog assertions | Every table: delete/truncate guard; integer insert/update guard except policy_versions/schema_migrations/md_runtime_mode; disabled or replica-only guards do not count. | `tests/integration/persistence/test_schema_catalog.py:17–19,40–81` |
| Explicit table inventory | `EXPECTED_TABLES` is instead in `test_migrations.py`; test checks it is a subset of discovered tables. | `tests/integration/persistence/test_migrations.py:32–117` |

| Existing subscription/usage signals | Available today | Source |
|---|---|---|
| Actual router journal | Inspected 275 rows: 167 zai, 108 codex, **zero claude-pro**; no cost/usage-named top-level keys. Current file contains no historical Pro invocation receipt. | `/root/.cache/ai-route/runs.jsonl:1–275` |
| Example stored tokens | Row 275: zai; input 748,096, cache read 5,314,880, cache creation 0, output 259,769, total 6,322,745; duration 2,992.5 seconds. | `/root/.cache/ai-route/runs.jsonl:275` |
| Claude transcript reader | Reads assistant message usage: input_tokens, cache_read_input_tokens, cache_creation_input_tokens, output_tokens; dedupes message IDs and excludes sidechains. Returns total/context/effort/model. | `ai_route.py:821–842` |
| Transcript location/status | Claude transcripts under `~/.claude/projects`; live status finds transcript and derives token/context activity from it. | `ai_route.py:64,687–707,873–895,931–940` |
| Subscription quota signal | Account-wide 5h/week utilization and reset timestamps from OAuth usage reader; not per-invocation attribution and not persisted as QuotaObservation by that reader. | `ai_route.py:407–432,474–506` |
| Status line | Consumes current input/output/cache tokens, transcript path/session ID; distinguishes current context occupancy from cumulative session totals. | `/root/.claude/statusline.sh:40–90` |
| Tool-hook estimates | `log_post_tool()` writes daily tool logs with output_length, rough token_estimate=chars/4, heuristic estimated_cost_usd, session/group/type. These are tool-output estimates, not provider token/cost receipts. | `/root/.claude/hooks/post_tool_use.py:503–540` |
| Monetary constraint | Existing UsageReceipt explicitly rejects ESTIMATED; API-equivalent estimates from a Claude result are not accepted as receipts by that contract. | `contracts/cost.py:216–235` |

