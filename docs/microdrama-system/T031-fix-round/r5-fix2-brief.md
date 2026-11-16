# R5 fix round 2: Codex round-2 residuals (GLM build; drama-box repo)

Orchestrator: Opus, 16 Nov 2026. Fix1 (`6bcdbfa..c02e918`) closed 7 of 10 findings. The Codex round-2
re-review (`codex-rereview-r5-r2.md`, FIX-REQUIRED) left R5V-9 and R5V-10 PARTIAL, added R5W-1 and
R5W-2 (both in `tools/t031_prepare_run.py`), and left R5V-4 PARTIAL on RR-T3 and real discovery.
You fix these on top of `c02e918`. **Base receipt:** `make check` at `c02e918` is green
(orchestrator, 16 Nov 02:4x–04:1xZ: 3135 unit + 462 contract + 275 integration passed; `make check:
all offline checks passed`). A full `make check` takes ~100 min under CPUQuota=45% — run targeted
suites while fixing and `make check` once at the final commit (in the background, within one command).

## Read first (absolute paths)
- `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/codex-rereview-r5-r2.md` — **your
  requirement list; where this brief disagrees, the review wins** (say so in the report).
- `/root/AIVORA/drama-box/.scratch/t031-r5/r5-fix1-REPORT.md` — what fix1 did.
- `/root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md` v0.3 — binding spec.

## Where you work
Worktree `/root/AIVORA/drama-box/.scratch/t031-r5`, branch `feat/t031-r5`, at `c02e918`. Commit on
top; never amend/rebase; never stage `microdrama/.venv` (symlink) or `microdrama/preflight.json`.
**If `r5-fix2-REPORT.md` exists, you are resuming** — continue from its "Resume here".

## Items (in order)
1. **R5W-2** — `t031_prepare_run.py:509`: validate ALL inputs (WAVs included) before any registration
   write, or make registration one transaction. Test: malformed first voice → nothing registered;
   correct the input → retry succeeds (no "stored asset bytes drifted").
2. **R5V-10 + R5W-1** — `t031_prepare_run.py:169`: check RIFF/chunk lengths and framing against the
   real payload size (a 2 s payload with an oversized data header must be refused, not read as
   100 s); 8-bit PCM is unsigned → `pcm_u8`. Malformed-payload tests (oversized data chunk, truncated
   fmt, odd framing, 8-bit naming).
3. **R5V-9** — `t031_prepare_run.py:377`: replay also compares asset identities/object keys and rights
   expiry/disclosures against the frozen record; drift in each is refused. One test per field group.
4. **R5V-4 / RR-T3 evidence** — the local rebuild PASSED today (orchestrator run, 02:32–02:39Z, flock +
   CPUQuota=45%, `build.sh /tmp/t031r5-buildctx`): image `drama-pika-h3-flex:t031-native`, ID
   `sha256:a9c2092d823b248de02268e65f5e5e290f48b18d568e0b88199a8c4883fd6d31` (9.54 GB); CPU schema
   smoke `--network none` → `ACTUAL_RUNTIME_CPU_NO_WEIGHTS`, sha256
   `1a6023e24ad38cd4ef41e1d3b1c727550a52cba9cd055be2ede8373e487a4c89`, 16 mapped nodes —
   byte-identical to `schema-attestation.cpu.json`. Nothing pushed. Append this as a dated section of
   `microdrama/deployment/pika-h3-flex/BUILD_EVIDENCE.md` (note: the pushed GHCR digest `e4ccc004…`
   is the 12 Nov image and predates R5's gateway; the operator re-pushes). Then run the REAL
   placeholder discovery (the RR-T7 path) inside this LOCAL image with `--network none`, under
   `flock /tmp/t031-native-heavy.lock systemd-run --scope -p CPUQuota=45% timeout 240`, and record
   the receipt. Do NOT rebuild, push or tag the image. If the discovery cannot run in the image
   without code changes beyond these items, record why and stop on this item.

## Test rules and hard limits
Same as fix1: tests first (red recorded, `test_r5w…`/`test_r5v…` naming), real PostgreSQL where
touched, no interactive pytest flags, no new migrations, offline env vars
(`MICRODRAMA_EXECUTION_MODE=OFFLINE_MOCK MICRODRAMA_PAID_REQUESTS_ENABLED=false
MICRODRAMA_CLOUD_RESOURCES_ENABLED=false MICRODRAMA_PUBLIC_ACTIONS_ENABLED=false`) +
`env PATH="/usr/sbin:$PATH"` + `systemd-run --scope -p CPUQuota=45%` + `--basetemp=/tmp/t031r5-basetemp4`,
`make lint` per commit, `make check` green at the final commit. No pushes/merges/restarts/deletions
(no `rm`); never print env vars/keys. Check `df -h /` before the final `make check`.

## Report
Write `r5-fix2-REPORT.md` in the worktree: per-item status + commits, red/green lines, the RR-T3 and
discovery receipts, deviations, "Resume here". Top marker when done: `R5 FIX2: ALL ITEMS ADDRESSED`.
Final message: one line per item, then the report path.
