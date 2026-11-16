# A0-D FIX5: ALL FINDINGS ADDRESSED

# A0-D fix round 5 — the two round-5 findings AD8-1..AD8-2

Build: GLM (A0-D fix5 brief, 14 Nov 2026). Base `15ce674`, worktree
`drama-box/.scratch/a0d-gateway`, branch `feat/a0d-gateway`. Requirement list:
`codex-review-a0d-r5.md` (1 BLOCKING + 1 SHOULD-FIX regression). **Both fixed in
the brief's order (AD8-1 → AD8-2), each with a red test recorded against the
pre-fix code before the fix landed.** Nothing stopped at red; nothing merged or
pushed. `make lint` (ruff check + format --check) clean immediately before
every commit.

Commits (on top of `15ce674`, tip `1e43b70`):
- `1c17405` — AD8-1 (raw quota/concurrency evidence in the per-attempt hash)
- `1e43b70` — AD8-2 (stranded legacy queued probe: cancel/rearm repair)

## Per-finding status

| ID | Status | Commit | Red | Green |
|----|--------|--------|-----|-------|
| AD8-1 | **ADDRESSED** | `1c17405` | `test_ad8_1_a…[quota-readings-added / concurrent-jobs-added / concurrent-jobs-ms-added]` and `…_b…[changed reset timing]`: after attempts 1 (quota-less) and 2 settled, replaying the record with attempt 1's exposed payload gaining readings — or with only `quota_after`'s `5h_reset_ms`/`week_reset_ms` changed, the settling result byte-identical — raised NO Conflict: `Failed: DID NOT RAISE <class 'microdrama.contracts.errors.Conflict'>` (4 failed; the identical-replay control `_c` passed on both sides, as it must) | `quota_before`/`quota_after`/`concurrent_jobs`/`concurrent_jobs_ms` join `_RESULT_EVIDENCE_FIELDS` — the raw payloads hash with field presence included (absence stays evidence), so readings gained, changed or lost between settlements conflict at the append-only attempt row, BEFORE any quota observation is written. The `_b` change (reset timing normalized away by `reset(before) or reset(after)`) now conflicts at the hash; the fabricated observation of `_a` is never inserted (asserted). `tests/unit/llm` 123 passed, no fixture repairs needed this round |
| AD8-2 | **ADDRESSED** | `1e43b70` | `test_ad8_2_a/b`: a genuine probe ledger seeded exactly as the fix3 build froze it (marker + self-consistent request + queued attempt, NO `probe_request_hash`) — HEAD rejected it with the configuration unchanged (`_is_authorized_probe` False, `pump()` False) and `requalify()` returned it stranded: `AssertionError: the repair re-arms a fresh attempt instead of returning the stranded one` / `assert 1 == 2` (2 failed; the two scope guards `_c` marker-less squatter, `_d` launched probe passed pre-fix and pin behavior that must not change) | `_ensure_requalify_probe` repairs a NEVER-LAUNCHED (ACCEPTED) probe ledger that claims the marker but fails authorization: the stranded attempt settles CANCELLED (no unit can exist — ACCEPTED never entered LAUNCH_INTENT), then the re-arm re-freezes the request UNCONDITIONALLY from the current configuration and binds `probe_request_hash` — the armed attempt's bytes are internally written, so a tampered legacy request file can never ride the repair into a launch. Launched ledgers stay with recovery (settle → next re-arm binds, `_d`); a marker-less ledger is left exactly as it is (`_c`: never cancelled, never rearmed, no receipt). Under a changed configuration the repair re-freezes the CURRENT request (`_b`: model `opus`, binding = new record hash, pump launches). `tests/integration/llm_gateway` 84 passed |

## Verification coverage (14 Nov 2026, all on tip `1e43b70` unless noted)

- `tests/unit/llm`: **123 passed** (118 from fix4 + 5 new: AD8-1 ×4 incl. the
  3-param addition matrix, + the identical-replay control).
- `tests/integration/llm_gateway`: **84 passed** (80 from fix4 + 4 new: AD8-2
  upgrade-state repair, changed-config re-freeze, marker-less guard, launched
  guard) — real transient `dramabox-llm-test-*` systemd units (113 s); the
  AD5-10 e2e requalify (a REAL probe through the launch path writing a REAL
  receipt) and the AD7-3/AD7-4 suites stay green under the repair.
- `make lint` equivalent (`ruff check` + `ruff format --check` over
  `src tests tools`): clean before every commit.
- Cross-suite check: no test outside `tests/unit/llm` exercises
  `mirror_invocation_result` or the gateway record replay (grepped), and
  `gateway.py`'s change is confined to `_ensure_requalify_probe` — the
  stdlib-twin envelope reader and `result_validation.py` are untouched. Not
  run, per the brief: full `make check` / `make pilot`, and with them the
  full-unit sweep (the review's 3,222-unit total remains fix4's
  builder-reported evidence; this round's diff touches only the two suites
  above).

## Deviations

1. **AD8-1 hashes both concurrency spellings.** The review asked for "raw
   quota/concurrency evidence"; the payload vocabulary knows two spellings
   (`concurrent_jobs` in the runner/shim, `concurrent_jobs_ms` as the
   quota-reader fallback), so both keys joined `_RESULT_EVIDENCE_FIELDS` —
   whichever a payload carries is pinned, and a replay switching spellings
   (or dropping one) conflicts too.
2. **AD8-2 chose cancel/rearm over in-place migration**, per the review's
   second option: migrating (writing the missing binding onto the legacy
   bytes) would authorize content the current build never froze. The repair
   instead discards the legacy attempt (CANCELLED, evidence kept in the
   ledger) and arms a fresh attempt over an UNCONDITIONAL re-freeze — even
   when the configuration is unchanged, where the terminal re-arm path would
   have kept the old bytes. That closes a repair-loop corner: a tampered
   legacy request file under an unchanged config can never re-strand the
   probe (each requalify would otherwise cancel/rearm forever without
   launching).
3. **The evidence-hash vocabulary change is another cross-version break of
   the same accepted class as fix4's deviation 4**: attempt rows hashed by
   the round-4 code will not compare equal against round-5 replays. No
   migration involved (schema untouched, `result_sha256` is hash-bearing
   TEXT), gateway pre-production, offline/mock by default — accepted and
   noted for the record.
4. **`test_ad8_2_d` pins the launched-ledger path end to end** (seeded
   RUNNING legacy probe → recovery settles DONE from its result, no receipt →
   next requalify re-arms WITH the binding). This is fix4's acknowledged
   self-heal, now covered by a test instead of only by the fix4 report's
   prose.

## Anything stopped at red

Nothing. Both findings reached green.

## Resume here

Nothing to resume. Both round-5 findings are addressed and committed
(`1e43b70` tip, 2 commits on `15ce674`, nothing pushed), and the verification
is complete: `tests/unit/llm` **123 passed** (+5), `tests/integration/
llm_gateway` **84 passed** (+4), `make lint` clean before every commit. For
the orchestrator: round-6 verification against `15ce674..1e43b70`, then
`make check` + `make pilot` (the AD6-GATE-1 note in the fix3 report still
applies to the check).
