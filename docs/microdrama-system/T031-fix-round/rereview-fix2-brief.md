# Codex re-review (round 2 of 2) — fixes for CN-1..CN-6

Read-only. Worktree `/root/AIVORA/drama-box/.scratch/t031-native-worktree`, branch
`feat/t031-pika-flex-native`. **Scope: `git diff 2ceb341...d971435`** (7 commits, 22
files, by GLM). Earlier commits on this branch are out of scope: `048cc05` is the native
harness, which gets its own review, and `c6e19e0`/`2ceb341` are the migration-guard fix.

Your round-1 review:
`/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/codex-review-canary-night.md`.
Rulings: `.../T031-fix-round/rulings-canary-night.md`. Builder's report:
`.../T031-fix-round/fix2-REPORT.md`. Read all three first.

| ID | Commit | Claimed fix |
|----|--------|-------------|
| CN-1 | `9197c52` | Dispute check on exact Decimals; total ceiling; components normalised to sum to the total |
| CN-2 | `ce3ff4e` | Pod id bound when the POST is accepted; after a durable create request, retries are reconciliation-only |
| CN-3 | `d372e03` | Redaction of URL credentials and signed params; category-only uncertainty causes |
| CN-4 | `881aab6` | Storage ownership opens with the durable binding; healed before shutdown |
| CN-5 | `eed977b` | Stdlib token gateway in both images; ComfyUI on 127.0.0.1; token via pod env |
| CN-6 | `5d0ffa9` | Deadline checked before every attempt; timeouts bounded by the time remaining |

## Answer for each ID

1. **CLOSED / PARTIAL / OPEN**: does the change remove your round-1 failure scenario?
   Re-run your in-memory probes where you can.
2. Did the fix introduce a new defect? Give special attention to:
   - **CN-2:** can binding at POST-accept bind a pod that is not ours? Is
     reconciliation-only correct when the first POST was never sent (create recorded,
     then crash before send)? Does it stall forever, or route to the janitor/operator?
   - **CN-3:** does redaction cover the resolved API key and Comfy bearer values
     themselves, not only URL parts? Is the body read bounded? Is anything still
     printed raw?
   - **CN-5:** is the token compare constant-time? Does it fail closed when the env var
     is missing or empty? Are websocket and upgrade paths gated? Can the token leak
     into logs, the image, or the create-request record? Can ComfyUI still be reached
     directly?
   - **CN-1:** do ceiling plus normalisation always conserve the total? Is the
     residual rule deterministic? Is a genuine provider mismatch still DISPUTED?
3. Is any test weakened, skipped, or only restating the implementation?

## Constraints and output

- Your sandbox is read-only and cannot write files or run `systemd-run`. The
  orchestrator is running the full offline gate separately, so do not run the
  integration suite.
- **Put the full report in your final message.**
- New findings: ID `CN2-1`…, severity **BLOCKING / SHOULD-FIX / NIT**, `file:line`, a
  concrete failure scenario, and a fix. Report only issues inside the scope diff.
- End with a verdict: **ACCEPT** or **FIX-REQUIRED**. This is the last round in the
  cycle; anything further goes to the operator.
