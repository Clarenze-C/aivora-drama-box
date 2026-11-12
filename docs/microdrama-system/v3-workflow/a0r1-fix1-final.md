**A0-R1 fix round 1 complete.** The previous session had committed the fixes (`ffb3810`) but died before verification; this session verified everything, caught a test-rig race in the full-suite run (fixed in `b9137f8`, production code untouched), ran the three existing scripts with pristine-main parity evidence, and finalized the report.

- **RR-1** ✔ duplicate observers read-only; owner token in `.running`; `IN_PROGRESS` (exit 75 + `retry_at`, never `launched=false`) — `test_rr1_duplicate_observer_never_touches_owner_state`
- **RR-2** ✔ one `flock` claim protocol rechecking completed + running state atomically; completion published under the same lock — 3 × `test_rr2_claim_*`
- **RR-3** ✔ isolation evidence evaluated before/independently of exit status; violations discard output → `ISOLATION_VIOLATION` — 2 × `test_rr3_*`
- **RR-4** ✔ success = exit 0 + terminal `is_error=false` + `subtype=success`; explicit cap/error subtype map — 2 × `test_rr4_*`
- **RR-5** ✔ one monotonic deadline bounding PTY capture, prompt write, stream read, all waits; TERM→KILL 10 s; terminal `DEADLINE` — 3 × `test_rr5_*`
- **RR-6** ✔ inert-key allowlist; all executable settings (`apiKeyHelper`, `aws*`, `otelHeadersHelper`, `statusLine`, `fileSuggestion`, `policyHelper`, hooks) + unknown keys refuse — 10 × `test_rr6_*`
- **RR-7** ✔ structured output from the terminal result's `structured_output` field only — 2 × `test_rr7_*`
- **RR-8** ✔ parser boundary → durable `PARSE_ERROR` with raw evidence kept — 2 × `test_rr8_*`
- **RR-9** ✔ remote policy absent only when positively established; rule binds identity — 3 × `test_rr9_*`
- **RR-10** ✔ `AI_ROUTE_TEST_QUOTA_FILE` gone from production; seam is `dramabox_llm.quota_file` in models.json (null in production) — 3 × `test_rr10_*`
- **RR-11** ✔ `max_concurrent` always enforced (unreadable quota skips only quota comparisons) — `test_rr11_…` (green after the rig-race fix)
- **RR-12** ✔ final argv/env/stdin captured through entry-point shims (`-p`, `--session-id`, paragraph, goldfish, `--quota`/`--status`); scoped clock patch; baselines regenerated from pristine `main` `02b361a` — 2 × `test_rr12_*` + snapshot test
- **RR-13** ✔ validated parent dir; `O_CREAT|O_EXCL|O_NOFOLLOW` 0600; type checks; `fchmod` via fd — 3 × `test_rr13_*`
- **RR-14** ✔ `--qualification <record-id>` separate launch mode; production rejects the fixture exception outright — 4 × `test_rr14_*`
- **RR-15** ✔ `--result-json` outside the execution cwd; cwd ownership/symlink validation; emptiness rechecked immediately before spawn — 3 × `test_rr15_*`

**Verification:** full suite `1 failed, 106 passed in 303.27s` at `ffb3810` (rr11 rig race) → **`107 passed in 306.63s`** after `b9137f8`. `test_goldfish.py` ALL PASS; `test_guards.py` and `test_observability.py` fail identically-shaped on pristine `main` under the same conditions (observability: exact same 7 sleep-window failures on both; the brief's "3 on main" wasn't reproducible under this load — parity evidence recorded instead).

Report: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/a0r1-build-REPORT.md`
