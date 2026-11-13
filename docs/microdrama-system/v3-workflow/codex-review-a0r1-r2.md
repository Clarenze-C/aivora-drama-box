**Verdict: FIX-REQUIRED.**

Reviewed `02af779..b9137f8`, as explicitly scoped. Tracked `git diff HEAD` is empty; untracked debug/cache files were excluded.

| Finding | Status | Evidence and assessment |
|---|---|---|
| RR-1 | **PARTIAL** | [ai_route.py:2199](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:2199): registry protected, but observers still write shared owner output. |
| RR-2 | **CLOSED** | [ai_route.py:1986](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1986), [2005](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:2005): completed/running recheck, claim, and completion use the same lock protocol. |
| RR-3 | **PARTIAL** | [ai_route.py:1380](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1380): parser failures still bypass isolation classification. |
| RR-4 | **CLOSED** | [ai_route.py:1390](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1390): affirmative terminal success required; error/cap mapping implemented. |
| RR-5 | **PARTIAL** | [ai_route.py:1987](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1987), [2241](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:2241): lock/quota operations remain outside deadline enforcement. |
| RR-6 | **CLOSED** | [ai_route.py:1775](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1775): executable and unknown settings refused through allowlists. |
| RR-7 | **CLOSED** | [ai_route.py:1345](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1345): structured output comes from the terminal result. |
| RR-8 | **PARTIAL** | [ai_route.py:1299](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1299): field-conversion examples fixed; JSON decoding failures still silently discarded. |
| RR-9 | **PARTIAL** | [ai_route.py:1725](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1725), [1814](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1814): explicit absence rule added, but qualified cache location is unbound. |
| RR-10 | **PARTIAL** | [ai_route.py:1868](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1868): environment override removed; production file override remains. |
| RR-11 | **CLOSED** | [ai_route.py:1902](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1902): unreadable quota no longer skips concurrency. |
| RR-12 | **CLOSED** | [snap_matrix.py:227](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/tests/ai_route/snap_matrix.py:227), [behavior_matrix.py:43](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/tests/ai_route/behavior_matrix.py:43): final entry-point capture and scoped clock patch implemented. |
| RR-13 | **PARTIAL** | [ai_route.py:1452](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1452): symlinks refused, but existing files truncated before validation. |
| RR-14 | **CLOSED** | [ai_route.py:1509](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1509), [1538](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1538): separate qualification mode and matching record required. |
| RR-15 | **CLOSED** | [ai_route.py:2059](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:2059), [2262](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:2262): nested output rejected; cwd validated and rechecked before spawn. |

The remaining findings are:

- **RR2-1 — BLOCKING — Duplicate observers can overwrite an owner’s terminal output.**  
  [ai_route.py:2206](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:2206) writes the observer response to its supplied result path without checking whether the owner uses that path. The owner can publish `SUCCEEDED` after the observer’s claim check, then the observer overwrites it with `IN_PROGRESS`. I reproduced that ordering in memory. **Fix:** record the owner’s result path and require a separate observer response path; prevent observers from writing owner/registry files.

- **RR2-2 — BLOCKING — Malformed terminal fields suppress known isolation violations.**  
  [ai_route.py:1380](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1380) returns before the isolation assertion when parsing fails. A valid init exposing `Bash`, followed by an invalid cost, produces `PARSE_ERROR`, retains `result_text`, and supplies no violation reason. Deadline/cancellation paths also skip collected evidence at [2331](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:2331). **Fix:** collect and evaluate isolation evidence independently; known violations must win and discard output.

- **RR2-3 — BLOCKING — The shared deadline still does not bound the entire operation.**  
  [ai_route.py:1987](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1987) uses an unlimited blocking `flock`. Quota reads at [2241](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:2241) and [2334](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:2334) receive no remaining deadline. A simulated quota read crossing the deadline returned `REFUSED/QUOTA_UNREADABLE`, not `DEADLINE`. Prompt input also precedes deadline creation. **Fix:** propagate deadline/cancellation through these operations and enforce expiration before selecting terminal outcomes.

- **RR2-4 — SHOULD-FIX — Corrupt stream records can still produce success.**  
  [ai_route.py:1299](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1299) catches decoding errors and drops the offending line. Valid init + malformed JSON line + success terminal reproduced `SUCCEEDED`. **Fix:** retain decoding failure state and emit durable `PARSE_ERROR`, subject to isolation-violation precedence.

- **RR2-5 — SHOULD-FIX — Hard-linked files are damaged before rejection.**  
  [ai_route.py:1452](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1452) opens an existing file with `O_TRUNC` before checking its type/link count. A planted hard link therefore truncates its other pathname before raising. The mocked syscall sequence confirmed truncating open → `fstat` → rejection. **Fix:** refuse `EEXIST`, or open without truncation, validate the descriptor, then truncate.

- **RR2-6 — SHOULD-FIX — Remote-policy absence is not bound to the qualified cache location.**  
  [ai_route.py:1814](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1814) hashes the source name and absence-rule string, omitting the cache path/resolution binding. Changing the configured cache path to another nonexistent location passed inspection with an identical identity. **Fix:** bind the qualified location and resolution rule into the identity and reject unqualified changes.

- **RR2-7 — SHOULD-FIX — The quota test override remains in production execution.**  
  [ai_route.py:1868](/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1868) substitutes file data whenever `quota_file` is configured. The binding fix brief requires module injection or a test-only entry point; moving the override into production configuration does not implement that boundary. **Fix:** remove the production branch and inject the reader through a test bootstrap.

**`b9137f8` is a genuine rig fix.** It snapshots matching call counts before launching the process being awaited. All **101 assertions are unchanged**; production code is untouched.

No additional BLOCKING/SHOULD-FIX regression was found in existing roles. Their configurations and launch/guard/quota/status/wait/watch function ASTs are unchanged. Pure behavior-fixture checks passed.

Validation used read-only inspection, `git diff --check`, and in-memory probes; filesystem-writing pytest was not rerun. One discarded harness check unintentionally reached production quota readers. No model launched and no files changed.