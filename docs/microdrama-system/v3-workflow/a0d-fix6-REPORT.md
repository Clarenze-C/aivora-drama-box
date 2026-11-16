# A0-D FIX6: ALL FINDINGS ADDRESSED

# A0-D fix round 6 — the single round-6 finding AD9-1

Build: GLM (A0-D fix6 brief, 14 Nov 2026). Base `1e43b70`, worktree
`drama-box/.scratch/a0d-gateway`, branch `feat/a0d-gateway`. Requirement list:
`codex-review-a0d-r6.md` (1 SHOULD-FIX: the interrupted repair can launch
stale prompt bytes). **Fixed with a red test recorded against the pre-fix
code before the fix landed** (3 red + 1 pre-passing scope guard). Nothing
stopped at red; nothing merged or pushed. `make lint` (ruff check + format
--check over `src tests tools`) clean immediately before the commit.

Commit (on top of `1e43b70`, tip `eea2f79`):
- `eea2f79` — AD9-1 (repair completeness re-derived from the frozen
  artifacts; authorization covers the bytes that launch)

## Per-finding status

| ID | Status | Commit | Red | Green |
|----|--------|--------|-----|-------|
| AD9-1 | **ADDRESSED** | `eea2f79` | `test_ad9_1_a/b/d` on `1e43b70`: (a) the repair re-freeze was injected-crashed between the request.json and prompt.txt replacements (OSError out of the real write boundary); the restart's requalify returned the armed attempt with `prompt.txt` still `b'foreign pro…'` where the frozen prompt was expected — `AssertionError: the restart COMPLETED the interrupted replacement before arming`; (b) `_is_authorized_probe` beside an intact bound record and a foreign prompt.txt: `assert True is False` — then `pump()` launched it; (d) the e2e restart POSTed /v1/requalify over the seeded post-crash state and armed attempt 2 with `prompt.txt` still foreign for a REAL unit (which under the bug runs the foreign bytes and still writes a valid receipt). `test_ad9_1_c` (no-churn scope guard) passed pre-fix and pins behavior that must not change (3 failed, 1 passed) | The re-arm re-freezes unless the freeze on disk is PROVABLY complete: request.json is exactly the record of the current probe request (content AND hash) AND `prompt.txt`/`schema.json` carry precisely the bytes that request freezes — `_probe_freeze_intact`/`_request_artifacts_intact` re-derive completeness from the artifacts on every re-arm, so a restart RE-ENTERS the full re-freeze (never skips on a matching state hash) and a partial freeze can never bind or launch. `_is_authorized_probe` now also requires the artifact files to match the FROZEN request (the launch consumes the files, not the record), closing the same hole at bind, pump and settlement without any interrupt. `frozen_schema_bytes` is the single write/verify byte vocabulary (first freeze, re-freeze and checks share it). Intact freezes are never rewritten (`_c`: record bytes + prompt/schema mtimes unchanged across a re-arm). `tests/integration/llm_gateway` **88 passed** |

## Verification coverage (14 Nov 2026, all on tip `eea2f79` unless noted)

- `tests/integration/llm_gateway`: **88 passed** (84 from fix5 + 4 new AD9-1:
  interrupted-repair restart resumes the replacements, foreign-prompt-on-queued
  repaired never launched, intact-freeze no-churn guard, and the e2e — real
  transient `dramabox-llm-test-*` units, a real violation latch, a real
  kill/restart, the requalify route completing the repair BEFORE the real
  unit launch, receipt written, health ok, exactly one execution) — 115 s,
  real systemd, `--basetemp=/tmp/a0d-basetemp6`, under `CPUQuota=45%`.
- `tests/unit/llm`: **123 passed** (unchanged from fix5; the diff touches
  only the gateway and its integration suite).
- `make lint` (`ruff check` + `ruff format --check` over `src tests tools`):
  clean immediately before the commit; `gateway.py` is also format-clean.
- Cross-suite check: no test outside `tests/integration/llm_gateway`
  exercises `_is_authorized_probe`, `_ensure_requalify_probe` or the probe
  artifact paths (grepped). Not run, per the brief: full `make check` /
  `make pilot` (the AD6-GATE-1 note in the fix3 report still applies to the
  check).

## Deviations

1. **Re-derivation chosen over persisted per-file progress markers.** The
   brief offered either; re-deriving completeness from the artifacts
   themselves is strictly stronger — it also heals partial freezes no marker
   witnessed (any stale/foreign/missing artifact from any historical build
   or tamper), needs no new state vocabulary, and cannot itself be
   interrupted into a wrong decision. The in-memory `repaired` flag is kept
   only to preserve fix5's documented unconditional re-freeze after a
   repair-cancel (identical-bytes rewrite); correctness no longer depends
   on it.
2. **Authorization now covers the artifact files, not just request.json.**
   The brief's "before bind+launch" is enforced at three choke points that
   all funnel through `_is_authorized_probe` (pump's launch gate, the
   repair trigger, `_maybe_complete_requalify`'s settlement gate): a
   hash-perfect record beside foreign prompt/schema bytes authorizes
   nothing. Side effect, deliberately conservative: prompt bytes tampered
   while a probe is RUNNING refuse the qualification at settlement; the
   next requalify re-arms over a complete re-freeze and requalifies
   normally (self-healing, never a false pass).
3. **The first-freeze crash window (before `state.json` exists) was already
   safe and is untouched**: `ledger.exists()` is false until `write_request`
   lands the state atomically after the artifacts, so a crash mid-first-freeze
   re-freezes from scratch — no marker-less squatter ambiguity arises.

## Anything stopped at red

Nothing. The finding reached green (3 red tests + 1 pre-passing guard).

## Resume here

Nothing to resume. The round-6 finding is addressed and committed
(`eea2f79` tip, 1 commit on `1e43b70`, nothing pushed), and the
verification is complete: `tests/integration/llm_gateway` **88 passed**
(+4), `tests/unit/llm` **123 passed**, `make lint` clean before the
commit. For the orchestrator: round-7 verification against
`1e43b70..eea2f79`, then `make check` + `make pilot` (the AD6-GATE-1 note
in the fix3 report still applies to the check).
