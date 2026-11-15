# Codex review: the A1 build (`eea2f79..57df5a9`) — before the gate

Diff: `eea2f79..57df5a9` on `feat/a0d-gateway` (four commits: D1 `bc61252`, D2 `f044056`, D3
`86aab76`, D4 `57df5a9`). Requirements: **`A1-design-note.md` v1.4 (ACCEPTED)** — every § is
normative — and `phase-A-spec.md` v0.3 §10's A1 row. Builder report:
`.scratch/a0d-gateway/a1-build-REPORT.md` (per-package red/green, transaction inventory, **eight
recorded deviations — weigh each**: notably the repaired 429-death WIP, the 0008 package-guard
precedence choice, and the tracked-job fence refusal vs today's closed payload models).

**Verify the A1 acceptance rows explicitly** (the master's V3-AT-1, 2, 13, 16, 20, 21 as superseded):
V3-AT-1 stepper statuses match durable state; V3-AT-2 no transition without approval bound to the
current hash + stale-hash refusal + Revise regenerates only noted units; V3-AT-16 bot dedupe/timeout
seams; V3-AT-13/20/21 as the note defines them. Check the migrations (0028–0031) against the note's
allocation and V1-preservation rules (D2's SQLSTATE/message reproduction especially).

Code (read-only): the worktree `/root/AIVORA/drama-box/.scratch/a0d-gateway`.

## Output: read-only; ≤140 lines; issues `A1V-n` BLOCKING/SHOULD-FIX/NIT + fix directions;
verdict **ACCEPT / FIX-REQUIRED**.
