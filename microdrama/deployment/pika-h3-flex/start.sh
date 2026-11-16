#!/bin/sh
# T031 R5a: image entrypoint. The token gateway always starts first; pinned
# weight provisioning runs only with MICRODRAMA_PROVISION_MODELS=1; ComfyUI is
# exec'd exactly as the pinned base did -- only after PROVISIONED, or
# immediately when provisioning was never requested. On PROVISION_FAILED
# ComfyUI is NEVER started and the gateway keeps serving the failed state
# (fail closed: no GPU work can run without its weights).
#
# This script owns /opt/pika/state.json: PROVISIONING -> PROVISIONED |
# PROVISION_FAILED with UTC start/end, the exit code and a hex-encoded stderr
# tail (hex avoids every JSON-escaping ambiguity). The gateway mirrors only the
# whitelisted fields of this file - the tail stays on the pod.
set -eu

PIKA_ROOT=${PIKA_ROOT:-/opt/pika}
GATEWAY=${MICRODRAMA_GATEWAY:-/opt/canary_gateway.py}
COMFY_MAIN=${MICRODRAMA_COMFY_MAIN:-/opt/ComfyUI/main.py}
STATE_FILE=${MICRODRAMA_PROVISION_STATE_FILE:-$PIKA_ROOT/state.json}
PROVISION_FLAG=${MICRODRAMA_PROVISION_MODELS:-0}

utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }

write_state() {
  # Atomic publish: a reader never observes a torn file.
  _tmp="$STATE_FILE.tmp.$$"
  printf '%s\n' "$1" > "$_tmp"
  mv -f "$_tmp" "$STATE_FILE"
}

python "$GATEWAY" &

if [ "$PROVISION_FLAG" = "1" ]; then
  _start=$(utc)
  write_state "{\"state\":\"PROVISIONING\",\"started_at\":\"$_start\"}"
  _stderr="$PIKA_ROOT/provision.stderr.$$"
  set +e
  python "$PIKA_ROOT/provision.py" \
    --manifest "$PIKA_ROOT/models.json" \
    --destination /opt/ComfyUI/models \
    --download 2>"$_stderr"
  _status=$?
  set -e
  _end=$(utc)
  _tail_hex=$(tail -c 2048 "$_stderr" 2>/dev/null | od -An -tx1 | tr -d ' \n' || printf '')
  rm -f "$_stderr"
  if [ "$_status" -eq 0 ]; then
    _state=PROVISIONED
  else
    _state=PROVISION_FAILED
  fi
  write_state "{\"state\":\"$_state\",\"started_at\":\"$_start\",\"ended_at\":\"$_end\",\"exit_code\":$_status,\"stderr_tail_hex\":\"$_tail_hex\"}"
  if [ "$_status" -ne 0 ]; then
    # ComfyUI is never started on failure; the gateway keeps answering with
    # PROVISION_FAILED until RunPod reaps the pod.
    while :; do sleep 60; done
  fi
fi

exec python "$COMFY_MAIN" --listen 127.0.0.1 --port 8189 --disable-api-nodes --disable-all-custom-nodes
