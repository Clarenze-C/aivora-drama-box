# Codex re-review (R5 round 3, operator-approved, narrow): T031 R5 fix2 (`c02e918..45811d3`)

Orchestrator: Opus, 16 Nov 2026. Worktree `/root/AIVORA/drama-box/.scratch/t031-r5`, branch
`feat/t031-r5`. The operator approved this third round beyond the two-round rule, **for the fix2 items
only**.

**Scope: only the five fix2 commits `c02e918..45811d3`** (`1e24312`, `d151e17`, `2545946`, `26ecfc1`,
`45811d3`). Check that each residual from your round 2 is now closed and that the fixes add no new
defect. R5V-1/2/3/5/6/7/8 were FIXED in round 2 — do not re-open them unless fix2 regressed one.

## Read (absolute paths under `/root/AIVORA/drama-box/`)
- `docs/microdrama-system/T031-fix-round/codex-rereview-r5-r2.md` — your round-2 findings.
- `.scratch/t031-r5/r5-fix2-REPORT.md` — per-item status, red/green tests, the RR-T3 and in-image
  discovery receipts, final gate (`make check` green at `45811d3`).

## Items
- **R5W-2** — every input (WAVs included) validated before any registration write; correct-then-retry works.
- **R5V-10 + R5W-1** — RIFF/chunk lengths and framing checked against the real payload; oversized
  data header refused; 8-bit PCM named `pcm_u8`; malformed-payload tests.
- **R5V-9** — replay compares asset identities/object keys and rights expiry/disclosures to the frozen record.
- **R5V-4** — RR-T3 receipt (local rebuild `a9c2092d…`, CPU smoke hash `1a6023e2…` byte-identical,
  16 nodes, not pushed) and the REAL placeholder discovery run inside that local image. The pinned-digest
  run waits on the operator's GHCR re-push: judge whether the local-image evidence closes R5V-4 for
  acceptance, with the re-push as a recorded operator follow-up.

## Output
Read-only; ≤60 lines. Per item: CLOSED / NOT CLOSED, one line with file:line. New issues only if
BLOCKING or SHOULD-FIX (`R5X-n`, fix direction). Verdict **ACCEPT / FIX-REQUIRED**.
