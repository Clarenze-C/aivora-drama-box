#!/usr/bin/env bash
# T046 staging drills: up -> owner -> intake -> restart durability -> worker ->
# backup -> restore -> verify -> cleanup. Every step prints PASS/FAIL evidence
# lines; the transcript lands in deployment/staging/drill-logs/<timestamp>.log.
#
# Usage: bash deployment/staging/drill.sh [--keep-up]
#   --keep-up  leave the staging stack running at the end (private, loopback)
set -euo pipefail

cd "$(dirname "$0")/../.."
COMPOSE="docker compose -f deployment/compose.staging.yaml --env-file deployment/staging.env"
APP_PORT=$(sed -n "s/^STAGING_APP_PORT=//p" deployment/staging.env | tail -1)
APP_PORT="${APP_PORT:-8091}"
BASE="http://127.0.0.1:${APP_PORT}"
LOG_DIR="deployment/staging/drill-logs"
LOG="$LOG_DIR/$(date -u +%Y%m%dT%H%M%SZ).log"
KEEP_UP=0
[[ "${1:-}" == "--keep-up" ]] && KEEP_UP=1
mkdir -p "$LOG_DIR" "$LOG_DIR/secrets"
chmod 700 "$LOG_DIR/secrets"

log() { echo "$@" | tee -a "$LOG"; }
fail() { log "FAIL: $*"; exit 1; }

wait_health() {
  for _ in $(seq 1 40); do
    if $COMPOSE exec -T app python -m microdrama.api.serve health >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

login() { # $1=jar $2=user $3=pass $4=base(optional, default $BASE)
  local jar="$1" user="$2" pass="$3" base="${4:-$BASE}"
  local page token
  page=$(curl -fsS -c "$jar" "$base/auth/login")
  token=$(grep -o 'name="login_csrf" value="[^"]*"' <<<"$page" | head -1 | sed 's/.*value="//;s/"//')
  [[ -n "$token" ]] || fail "no login CSRF token on the login page"
  local status
  status=$(curl -fsS -o /dev/null -w '%{http_code}' -b "$jar" -c "$jar" \
    --data-urlencode "username=$user" --data-urlencode "password=$pass" \
    --data-urlencode "login_csrf=$token" "$base/auth/login")
  [[ "$status" == "303" ]] || fail "login expected 303, got $status"
}

log "=== T046 staging drill $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

log "--- 1/7 up (build + start, loopback-only)"
$COMPOSE up -d --build >>"$LOG" 2>&1 || fail "compose up"
wait_health || fail "app never became healthy"
log "PASS: stack up, /health OK on 127.0.0.1:${APP_PORT}"

OWNER_NAME="staging.owner.$(date -u +%Y%m%d%H%M%S)"
log "--- 2/7 owner bootstrap + login ($OWNER_NAME)"
if ! $COMPOSE exec -T app python -m microdrama.api.serve create-owner \
    --username "$OWNER_NAME" >"$LOG_DIR/secrets/owner-create.txt" 2>>"$LOG"; then
  log "NOTE: create-owner refused (existing owner from an earlier drill) — reusing"
fi
OWNER_PASS=$(awk '/one-time password/ {print $NF}' "$LOG_DIR/secrets/owner-create.txt" | tail -1)
[[ -n "$OWNER_PASS" ]] || fail "no owner password captured"
chmod 600 "$LOG_DIR/secrets/owner-create.txt" "$LOG_DIR/secrets/cookies.txt" 2>/dev/null || true
JAR="$LOG_DIR/secrets/cookies.txt"; : >"$JAR"
login "$JAR" "$OWNER_NAME" "$OWNER_PASS"
CSRF=$(grep md_csrf "$JAR" | tail -1 | awk '{print $NF}')
[[ -n "$CSRF" ]] || fail "no session CSRF after login"
log "PASS: owner login 303, session cookie durable-side issued"

log "--- 3/7 three-step intake over HTTP (durable season + intake row)"
WIZ=$(curl -fsS -b "$JAR" "$BASE/ui/intake")
KEY=$(grep -o 'name="wizard_key" value="[0-9a-f]*"' <<<"$WIZ" | head -1 | sed 's/.*value="//;s/"//')
[[ -n "$KEY" ]] || fail "wizard page minted no key"
STATUS=$(curl -fsS -o /dev/null -w '%{http_code}' -b "$JAR" \
  --data-urlencode "csrf_token=$CSRF" --data-urlencode "wizard_key=$KEY" \
  --data-urlencode "step=submit" \
  --data-urlencode "story_idea=ร้านข้าวต้มของยายที่ลูกสาวต้องสู้รักษาไว้" \
  --data-urlencode "genre_tags=family-drama" \
  --data-urlencode "tone=อบอุ่นแต่ตึงเครียด" \
  --data-urlencode "episode_count=3" \
  "$BASE/ui/intake")
[[ "$STATUS" == 303 ]] || fail "wizard submit expected 303, got $STATUS"
SEASON=$(curl -fsS -o /dev/null -w '%{redirect_url}' -b "$JAR" -c "$JAR" \
  --data-urlencode "csrf_token=$CSRF" --data-urlencode "wizard_key=$KEY" \
  --data-urlencode "step=submit" \
  --data-urlencode "story_idea=ร้านข้าวต้มของยายที่ลูกสาวต้องสู้รักษาไว้" \
  --data-urlencode "genre_tags=family-drama" \
  --data-urlencode "tone=อบอุ่นแต่ตึงเครียด" \
  --data-urlencode "episode_count=3" \
  "$BASE/ui/intake" | sed 's|.*/ui/intake/||;s|[^0-9a-f-].*||')
[[ -n "$SEASON" ]] || fail "no season id from the wizard redirect (idempotent replay)"
for path in "/ui/intake/$SEASON" "/ui/seasons/$SEASON/workbench"; do
  CODE=$(curl -fsS -o /dev/null -w '%{http_code}' -b "$JAR" "$BASE$path")
  [[ "$CODE" == 200 ]] || fail "GET $path expected 200, got $CODE"
done
log "PASS: intake submitted over HTTP; status + workbench render (season $SEASON)"

log "--- 4/7 restart durability (all services, including postgres)"
ROWS_BEFORE=$($COMPOSE exec -T postgres psql -U microdrama -tA \
  -c "SELECT count(*) FROM seasons; SELECT count(*) FROM v2_contract_documents WHERE contract_type='ConceptIntake';")
$COMPOSE restart >>"$LOG" 2>&1 || fail "compose restart"
wait_health || fail "app never came back after restart"
CODE=$(curl -fsS -o /dev/null -w '%{http_code}' -b "$JAR" "$BASE/ui/intake/$SEASON")
[[ "$CODE" == 200 ]] || fail "post-rerestart status page expected 200 with the OLD session, got $CODE"
ROWS_AFTER=$($COMPOSE exec -T postgres psql -U microdrama -tA \
  -c "SELECT count(*) FROM seasons; SELECT count(*) FROM v2_contract_documents WHERE contract_type='ConceptIntake';")
[[ "$ROWS_BEFORE" == "$ROWS_AFTER" ]] || fail "row counts changed across restart ($ROWS_BEFORE -> $ROWS_AFTER)"
log "PASS: full restart — session survives, season+intake rows identical"

log "--- 5/7 independent worker + janitor (one drain cycle)"
WORKER_JSON=$($COMPOSE run --rm --no-deps worker python -m microdrama.api.worker --once 2>/dev/null | tail -1) \
  || fail "worker --once failed"
log "PASS: worker drained + janitor swept: $WORKER_JSON"

log "--- 6/7 backup (pg_dump + object-store volume)"
DUMP="$LOG_DIR/backup-$(date -u +%Y%m%dT%H%M%SZ).sql"
$COMPOSE exec -T postgres pg_dump -U microdrama microdrama >"$DUMP" || fail "pg_dump"
$COMPOSE exec -T app tar cf - -C /data objects >"$DUMP.objects.tar" || fail "object store tar"
log "PASS: backup written ($(du -h "$DUMP" | cut -f1) sql + $(du -h "$DUMP.objects.tar" | cut -f1) objects)"

log "--- 7/7 restore into a scratch project + verify"
RESTORE_ENV="$LOG_DIR/restore.env"
sed -e 's/^STAGING_APP_PORT=.*/STAGING_APP_PORT=8092/' deployment/staging.env >"$RESTORE_ENV"
RC="docker compose -f deployment/compose.staging.yaml --env-file $RESTORE_ENV -p microdrama-restore"
$RC up -d --no-deps postgres >>"$LOG" 2>&1 || fail "restore postgres up"
for _ in $(seq 1 20); do $RC exec -T postgres pg_isready -U microdrama >/dev/null 2>&1 && break; sleep 2; done
$RC exec -T postgres psql -U microdrama -d microdrama -v ON_ERROR_STOP=1 <"$DUMP" >>"$LOG" 2>&1 || fail "psql restore"
$RC up -d app >>"$LOG" 2>&1 || fail "restore app up"
RESTORED=000
for _ in $(seq 1 45); do
  RESTORED=$(curl -fsS -o /dev/null -w '%{http_code}' "http://127.0.0.1:8092/health" 2>/dev/null || echo 000)
  [[ "$RESTORED" == "200" ]] && break
  sleep 2
done
[[ "$RESTORED" == 200 ]] || fail "restored app health expected 200, got $RESTORED"
RJAR="$LOG_DIR/secrets/restore-cookies.txt"; : >"$RJAR"
login "$RJAR" "$OWNER_NAME" "$OWNER_PASS" "http://127.0.0.1:8092"
RCODE=$(curl -fsS -o /dev/null -w '%{http_code}' -b "$RJAR" "http://127.0.0.1:8092/ui/intake/$SEASON")
[[ "$RCODE" == 200 ]] || fail "restored intake page expected 200, got $RCODE"
log "PASS: restored stack — health OK, owner login OK, season $SEASON readable"
$RC down -v >>"$LOG" 2>&1 || true

if [[ "$KEEP_UP" == 1 ]]; then
  log "--- keeping the staging stack UP (loopback-only; drill.sh without --keep-up tears it down)"
else
  $COMPOSE down >>"$LOG" 2>&1 || true
  log "--- staging stack torn down (volumes kept: docker volume rm to discard)"
fi
log "=== DRILL COMPLETE === transcript: $LOG"
