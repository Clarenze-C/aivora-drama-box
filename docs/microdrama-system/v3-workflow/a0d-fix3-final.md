**A0-D fix3 complete** — tip `a4e9913`, 4 commits on `b84a397`, nothing pushed. Note: the brief said AD6-1..7, but the review lists **AD6-1..AD6-10** (AD6-8/9/10 under AD5-10); the review wins per the brief, so all ten were fixed.

- **AD6-1** — CLOSED (`0893454`): the frozen identity persists once and reloads from `frozen_call_text` for existing calls (never refilled from config); the admission gate binds existing work to the persisted identity, so an A→B config change can't move the request hash or block the replay.
- **AD6-2** — CLOSED (`a4e9913`): the pump's never_created branch consults the durable result like the exited branch; absence alone never establishes non-execution (result → settle, timed-out without result → UNKNOWN, completed systemd-run refusal → ISOLATION_UNAVAILABLE launched=false).
- **AD6-3** — CLOSED (`c3182c2`): `properties` defaults to `{}` under `additionalProperties:false`, and `_json_equal` is recursive in both twins — a nested boolean is never the number 1; corpus extended to 34 cases.
- **AD6-4** — CLOSED (`30a2777`): recovery (cancel adoption + reconciler) binds DONE validation to the invocation's persisted frozen identity (`frozen_policy_identity`); config is only the fallback.
- **AD6-5** — CLOSED (`0893454`): the replay compare covers the complete per-attempt evidence (identity, CLI version, usage availability, timing), and vanishing quota readings on a recorded attempt raise Conflict.
- **AD6-6** — CLOSED (`0893454`): a result naming an earlier attempt is bound to its own attempt — a result-less cancellation settles from its attempt entry, identity columns preserved, stale readings attributed to their attempt.
- **AD6-7** — CLOSED (`30a2777`): a 404 status record is skipped explicitly; the cancellation sweep continues instead of raising AttributeError.
- **AD6-8** — CLOSED (`a4e9913`): the deterministic probe uuid5 is reserved at accept (409 `PROBE_ID_RESERVED`), and the latched pump launches only the internally created, marker+hash-bound probe (re-frozen at re-arm on config change).
- **AD6-9** — CLOSED (`a4e9913`): restart recovery inspects every applicable violation (latch file + all settled ledgers) and clears only when the receipt covers them all, latching the newest uncovered one.
- **AD6-10** — CLOSED (`a4e9913`): a failed qualification-receipt write retains the quarantine — durable persistence is a precondition of clearance.
- **AD6-GATE-1** — PRE-EXISTING at `6974d5a`, not caused by fix2, no code change: fix2's diff touches only llm/gateway files, no pipeline-path module imports `microdrama.llm` (the test's code is byte-identical `6974d5a..b84a397`), and at clean `b84a397` the whole pipeline integration dir passes (53 passed, 9:35) — the gate failure was load-sensitive (real FFmpeg in a 600-iteration loop under a loaded full-`make check` run).

Verification: unit llm 112, gateway integration 75 (real systemd), sweeps 736 + 702 + 462 + 319 (one load-flake in the ffmpeg edit lane, green in isolation), `make lint` before every commit. The interrupted session's pre-written test drafts were repaired (three defects — a shadowing stub, a vacuous AD6-1 test, an FK violation — detailed in the report's Deviations).

Report: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/a0d-fix3-REPORT.md`
