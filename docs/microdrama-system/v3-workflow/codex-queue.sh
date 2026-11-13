#!/usr/bin/env bash
# Drama Box Codex queue for 13-15 Nov (session e4e3c05c). At most 2 Codex jobs at once; items run in order;
# an item whose brief does not exist yet is skipped until it does; exit 75 -> retry every 10 min;
# no new launch once Codex week >= 75%. Log lines: LAUNCH <tag> / END <tag> exit=<rc> / QUEUE DONE.
# Read-only reviews: every job writes only its --out file.
set -uo pipefail
V=/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow
T=/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round
S=${CQ_STATE:-/tmp/claude-0/-root-AIVORA/e4e3c05c-34b4-47d9-b724-b15410f059c2/scratchpad/keep/codex-queue.state}
GAP=${CQ_GAP:-60}; IDLE=${CQ_IDLE:-300}
DEADLINE=$(date -d "2026-11-15 16:00 UTC" +%s)   # Mon 00:00 SGT
touch "$S"
# tag|role|effort|brief|cwd|out
ITEMS=(
"dramabox:a0d-review|review|xhigh|$V/codex-review-a0d-brief.md|/root/AIVORA/drama-box/.scratch/a0d-gate|$V/codex-review-a0d.md"
"dramabox:t031-r5-critique|critique|xhigh|$T/codex-r5-critique-brief.md|/root/AIVORA/drama-box/.scratch/t031-fix3-worktree|$T/codex-r5-critique.md"
"dramabox:a1-note-r2|critique|xhigh|$V/codex-a1-note-r2-brief.md|/root/AIVORA/drama-box|$V/codex-a1-note-recritique.md"
"dramabox:a2-note-r1|critique|xhigh|$V/codex-a2-note-critique-brief.md|/root/AIVORA/drama-box|$V/codex-a2-note-critique.md"
"dramabox:a3-note-r1|critique|xhigh|$V/codex-a3-note-critique-brief.md|/root/AIVORA/drama-box|$V/codex-a3-note-critique.md"
"dramabox:a6b-note-r1|critique|xhigh|$V/codex-a6b-note-critique-brief.md|/root/AIVORA/drama-box|$V/codex-a6b-note-critique.md"
"dramabox:a0r1-review-r2|review|xhigh|$V/codex-a0r1-rereview-brief.md|/root/.claude/.claude/worktrees/a0r1-airoute|$V/codex-review-a0r1-r2.md"
)
codex_week() { ai-route --quota 2>/dev/null | awk '$1=="codex" && $2=="week" {gsub("%","",$3); print $3}'; }
run_one() {  # retries exit 75 for up to 3 h
  local tag=$1 role=$2 eff=$3 brief=$4 cwd=$5 out=$6 rc=75
  for t in $(seq 1 18); do
    ai-route "$role" "$brief" --effort "$eff" --cwd "$cwd" --tag "$tag" --out "$out"; rc=$?
    [ "$rc" -ne 75 ] && break
    sleep 600
  done
  echo "END $tag exit=$rc at $(date -u +%H:%MZ)"; echo "$tag END $rc" >> "$S"
}
echo "queue start $(date -u +%H:%MZ)"
while true; do
  pending=0; launched_now=0
  for it in "${ITEMS[@]}"; do
    IFS='|' read -r tag role eff brief cwd out <<< "$it"
    grep -q "^$tag " "$S" && continue          # launched or ended already
    pending=$((pending+1))
    [ -f "$brief" ] || continue                 # brief not written yet
    [ "$(jobs -rp | wc -l)" -ge 2 ] && continue
    w=$(codex_week); w=${w:-100}
    if [ "$w" -ge 75 ]; then echo "HOLD: codex week ${w}% >= 75% at $(date -u +%H:%MZ)"; continue; fi
    echo "$tag LAUNCH" >> "$S"; echo "LAUNCH $tag ($role) at $(date -u +%H:%MZ)"
    run_one "$tag" "$role" "$eff" "$brief" "$cwd" "$out" &
    launched_now=1; sleep "$GAP"
  done
  if [ "$pending" -eq 0 ]; then wait; echo "QUEUE DONE at $(date -u +%H:%MZ)"; exit 0; fi
  if [ "$launched_now" -eq 0 ]; then
    if [ "$(date +%s)" -ge "$DEADLINE" ]; then echo "DEADLINE: stop launching at $(date -u +%H:%MZ)"; wait; exit 4; fi
    if [ "$(jobs -rp | wc -l)" -gt 0 ]; then wait -n; else sleep "$IDLE"; fi
  fi
done
