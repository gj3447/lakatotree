#!/usr/bin/env bash
# 라카토트리 dev 서버(:55170) 재시작 러너 — creds 단일사본 소멸 사고(2026-07-02)의 봉합 (omd F5).
#
# 사고: creds 없는 쉘로 재기동 → neo4j/pg down 인데 /version 은 200(무음 degraded) + 비번 원본이
# 죽은 프로세스와 함께 소멸. 봉합: ① 정본 env(~/.config/lakatotree/server.env, 0600) 없으면 기동
# *거부* ② 죽이기 전 현 프로세스 environ 백업 ③ core healthz Neo4j+Mongo 게이트
# (traffic readiness는 별도 /readyz; version 200 ≠ 건강)
# ④ 포트로 죽임(pkill -f "app:app" 금지 — 자기 쉘 자살).
set -euo pipefail
umask 077

ENV_FILE="${LAKATOS_ENV_FILE:-${LAKATOS_SERVER_ENV:-$HOME/.config/lakatotree/server.env}}"
if [ ! -f "$ENV_FILE" ] || [ -L "$ENV_FILE" ]; then
  echo "[restart] 거부: canonical env 없음($ENV_FILE) — 무-creds 기동은 무음 degraded 를 만든다." >&2
  echo "[restart] 복구: 건강한 서버가 살아있다면:" >&2
  ENV_FILE_Q="$(printf '%q' "$ENV_FILE")"
  echo "  umask 077; RECOVERY_TMP=\$(mktemp ${ENV_FILE_Q}.recovery.XXXXXX)" >&2
  echo "  PID=\$(ss -ltnp | grep :55170 | grep -oP 'pid=\\K[0-9]+' | head -1)" >&2
  echo "  tr '\\0' '\\n' < /proc/\$PID/environ | grep -E '^NEO4J|^LAKATOS|^MONGO' > \"\$RECOVERY_TMP\"" >&2
  echo "  chmod 600 \"\$RECOVERY_TMP\" && mv \"\$RECOVERY_TMP\" ${ENV_FILE_Q}" >&2
  exit 2
fi
ENV_UID="$(stat -c '%u' "$ENV_FILE" 2>/dev/null \
  || stat -f '%u' "$ENV_FILE" 2>/dev/null || true)"
ENV_MODE="$(stat -c '%a' "$ENV_FILE" 2>/dev/null \
  || stat -f '%Lp' "$ENV_FILE" 2>/dev/null || true)"
if [ "$ENV_UID" != "$(id -u)" ] || [ "$ENV_MODE" != "600" ]; then
  echo "[restart] 거부: canonical env는 현재 사용자 소유의 0600 일반 파일이어야 함($ENV_FILE)." >&2
  exit 2
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# The selected canonical file is a full authority snapshot. Clear inherited
# launch/runtime values so an omitted line cannot silently inherit a decoy.
# Migration/readiness secrets remain visible for the rejection loop below.
CANONICAL_ENV_NAMES=(
  LAKATOS_BIND_HOST LAKATOS_PYTHON LAKATOS_API_TOKEN LAKATO_PORT
  UVICORN_WORKERS WEB_CONCURRENCY
  NEO4J_URI NEO4J_DATABASE NEO4J_USER NEO4J_PASSWORD
  LAKATOS_MONGO_URI
  LAKATOS_PG_HOST LAKATOS_PG_PORT LAKATOS_PG_USER
  LAKATOS_PG_PASSWORD LAKATOS_PG_DB
  LAKATOS_STORAGE_ENVIRONMENT
  LAKATOS_STORAGE_FENCE_VERIFIER_SHA256
  LAKATOS_STORAGE_FENCE_PUBLIC_KEY_HEX
  LAKATOS_STORAGE_PREDEPLOY_RECEIPT
  LAKATOS_STORAGE_PREDEPLOY_RECEIPT_SHA256
  LAKATOS_STORAGE_ACCESS_POLICY
  LAKATOS_STORAGE_ACCESS_POLICY_SHA256
  LAKATOS_STORAGE_ACCESS_PREDEPLOY_BUNDLE
  LAKATOS_STORAGE_ACCESS_PREDEPLOY_BUNDLE_SHA256
  LAKATOS_STORAGE_ACCESS_STARTUP_BUNDLE
  LAKATOS_STORAGE_ACCESS_STARTUP_BUNDLE_SHA256
  LAKATOS_STORAGE_RUNTIME_WRITER_VERIFIER
  LAKATOS_STORAGE_RUNTIME_WRITER_VERIFIER_SHA256
  LAKATOS_STORAGE_RUNTIME_WRITER_PUBLIC_KEY_HEX
  LAKATOS_STORAGE_PG_RUNTIME_DSN
  LAKATOS_STORAGE_PG_RUNTIME_CA_SHA256
)
for CANONICAL_ENV_NAME in "${CANONICAL_ENV_NAMES[@]}"; do
  unset "$CANONICAL_ENV_NAME"
done
env_file_identity() {
  local metadata digest
  metadata="$(stat -c '%d:%i:%u:%a:%s:%Y:%Z' "$ENV_FILE" 2>/dev/null \
    || stat -f '%d:%i:%u:%Lp:%z:%m:%c' "$ENV_FILE" 2>/dev/null)" || return 1
  if command -v sha256sum >/dev/null 2>&1; then
    digest="$(sha256sum "$ENV_FILE" | awk '{print $1}')" || return 1
  elif command -v shasum >/dev/null 2>&1; then
    digest="$(shasum -a 256 "$ENV_FILE" | awk '{print $1}')" || return 1
  else
    echo "[restart] 거부: canonical env SHA-256 도구가 없다." >&2
    return 1
  fi
  printf '%s:%s\n' "$metadata" "$digest"
}
ENV_FILE_IDENTITY="$(env_file_identity)" || {
  echo "[restart] 거부: canonical env 초기 identity를 고정할 수 없다." >&2
  exit 2
}
set -a; . "$ENV_FILE"; set +a
if [ "$(env_file_identity)" != "$ENV_FILE_IDENTITY" ]; then
  echo "[restart] 거부: canonical env가 source 도중 변경됐다." >&2
  exit 2
fi

: "${NEO4J_DATABASE:?NEO4J_DATABASE 설정 필요($ENV_FILE)}"
for MIGRATION_SECRET in \
  LAKATOS_STORAGE_PG_MIGRATION_USER \
  LAKATOS_STORAGE_PG_MIGRATION_PASSWORD \
  LAKATOS_STORAGE_PG_MIGRATION_DSN \
  LAKATOS_STORAGE_NEO4J_MIGRATION_URI \
  LAKATOS_STORAGE_NEO4J_MIGRATION_USER \
  LAKATOS_STORAGE_NEO4J_MIGRATION_PASSWORD \
  LAKATOTREE_READINESS_PG_DSN \
  LAKATOTREE_READINESS_NEO4J_URI \
  LAKATOTREE_READINESS_NEO4J_USER \
  LAKATOTREE_READINESS_NEO4J_PASSWORD; do
  if printenv "$MIGRATION_SECRET" >/dev/null 2>&1; then
    echo "[restart] 거부: migration credential 또는 audit credential은 runtime 환경에 둘 수 없음($MIGRATION_SECRET)" >&2
    exit 2
  fi
done

BIND_HOST="${LAKATOS_BIND_HOST:-127.0.0.1}"
case "$BIND_HOST" in
  0.0.0.0|::|'[::]') PROBE_HOST="127.0.0.1" ;;
  *:*) PROBE_HOST="[$BIND_HOST]" ;;
  *) PROBE_HOST="$BIND_HOST" ;;
esac
HEALTH_BASE="http://$PROBE_HOST:55170"
PYTHON_BIN="${LAKATOS_PYTHON:-$ROOT/.venv/bin/python}"
if [ ! -x "$PYTHON_BIN" ]; then
  echo "[restart] 거부: server Python 실행파일 없음($PYTHON_BIN)." >&2
  exit 2
fi
PREFLIGHT_PYTHON="$PYTHON_BIN"

# The critique-history storage audit is cached in-process.  Until that state is
# backed by a shared coordinator, every supported launcher must remain a single
# worker so one process cannot stay green after another observes divergence.
if [ "${WEB_CONCURRENCY:-1}" != "1" ] || [ "${UVICORN_WORKERS:-1}" != "1" ]; then
  echo "[restart] 거부: WEB_CONCURRENCY=${WEB_CONCURRENCY:-<unset>} UVICORN_WORKERS=${UVICORN_WORKERS:-<unset>} — storage audit cache는 단일 worker만 지원한다." >&2
  exit 2
fi
export WEB_CONCURRENCY=1
export UVICORN_WORKERS=1

# Canonical env can widen the bind or inject UVICORN_FD/UDS.  Validate the
# final sourced values before touching the currently healthy listener.
"$PREFLIGHT_PYTHON" -m server.auth_posture "$BIND_HOST" || exit $?
# This stays before listener_pid/TERM. A fully absent profile is core-only;
# declaring any one storage field activates the strict all-or-nothing verifier.
STORAGE_ACCESS_REQUESTED=0
for STORAGE_ACCESS_ENV in \
  LAKATOS_STORAGE_ENVIRONMENT \
  LAKATOS_STORAGE_FENCE_VERIFIER_SHA256 \
  LAKATOS_STORAGE_FENCE_PUBLIC_KEY_HEX \
  LAKATOS_STORAGE_ACCESS_POLICY \
  LAKATOS_STORAGE_ACCESS_POLICY_SHA256 \
  LAKATOS_STORAGE_PREDEPLOY_RECEIPT \
  LAKATOS_STORAGE_PREDEPLOY_RECEIPT_SHA256 \
  LAKATOS_STORAGE_ACCESS_PREDEPLOY_BUNDLE \
  LAKATOS_STORAGE_ACCESS_PREDEPLOY_BUNDLE_SHA256 \
  LAKATOS_STORAGE_ACCESS_STARTUP_BUNDLE \
  LAKATOS_STORAGE_ACCESS_STARTUP_BUNDLE_SHA256 \
  LAKATOS_STORAGE_RUNTIME_WRITER_VERIFIER \
  LAKATOS_STORAGE_RUNTIME_WRITER_VERIFIER_SHA256 \
  LAKATOS_STORAGE_RUNTIME_WRITER_PUBLIC_KEY_HEX \
  LAKATOS_STORAGE_PG_RUNTIME_DSN \
  LAKATOS_STORAGE_PG_RUNTIME_CA_SHA256; do
  if printenv "$STORAGE_ACCESS_ENV" >/dev/null 2>&1; then
    STORAGE_ACCESS_REQUESTED=1
  fi
done
if [ "$STORAGE_ACCESS_REQUESTED" = "1" ]; then
  "$PYTHON_BIN" -m server.storage_access_verify
fi

listener_pid() {
  ss -ltnp 2>/dev/null \
    | grep :55170 \
    | grep -oP 'pid=\K[0-9]+' \
    | head -1 \
    || true
}

PROC_ROOT="${LAKATOS_PROC_ROOT:-/proc}"
process_start_time() {
  sed 's/^.*) //' "$PROC_ROOT/$1/stat" 2>/dev/null | awk '{print $20}'
}
process_is_this_server() {
  local candidate="$1" cmdline cwd exe expected_exe
  [ -r "$PROC_ROOT/$candidate/cmdline" ] || return 1
  [ -r "$PROC_ROOT/$candidate/stat" ] || return 1
  cwd="$(realpath "$PROC_ROOT/$candidate/cwd" 2>/dev/null || true)"
  exe="$(realpath "$PROC_ROOT/$candidate/exe" 2>/dev/null || true)"
  expected_exe="$(realpath "$PYTHON_BIN" 2>/dev/null || true)"
  cmdline="$(tr '\0' ' ' < "$PROC_ROOT/$candidate/cmdline" 2>/dev/null || true)"
  [ "$cwd" = "$ROOT" ] \
    && [ -n "$expected_exe" ] \
    && [ "$exe" = "$expected_exe" ] \
    && [[ "$cmdline" == *"uvicorn"* ]] \
    && [[ "$cmdline" == *"app:app"* ]] \
    && [[ "$cmdline" == *"55170"* ]]
}
backup_process_environment() {
  local candidate="$1" backup_file backup_tmp
  backup_file="$ENV_FILE.lastboot"
  backup_tmp="$(mktemp "$backup_file.XXXXXX")"
  if tr '\0' '\n' < "$PROC_ROOT/$candidate/environ" 2>/dev/null \
      | grep -E "^NEO4J|^LAKATOS|^MONGO" \
      | grep -Ev '^LAKATOS_STORAGE_(PG|NEO4J)_MIGRATION_(USER|PASSWORD|DSN|URI)=' \
      > "$backup_tmp"; then
    chmod 600 "$backup_tmp"
    mv -f "$backup_tmp" "$backup_file"
  else
    rm -f "$backup_tmp"
  fi
}
validate_version_identity() {
  local version_json="$1" expected_sha
  expected_sha="$(git rev-parse HEAD)"
  "$PREFLIGHT_PYTHON" - "$expected_sha" "$version_json" <<'PY'
import json
import sys

expected, raw = sys.argv[1:]
payload = json.loads(raw)
if payload.get("disk_git_sha") != expected:
    raise SystemExit("disk_git_sha mismatch")
if payload.get("boot_git_sha") != expected:
    raise SystemExit("boot_git_sha mismatch")
if payload.get("identity_verified") is not True:
    raise SystemExit("runtime identity is not verified")
if payload.get("stale") is not False:
    raise SystemExit("runtime reports stale code")
PY
}

# A loaded systemd unit remains the sole process authority even while inactive.
# Never TERM its MainPID directly and never fall back to nohup after a managed
# restart failure: either action can race Restart= and create a second listener.
SYSTEMD_UNIT="lakatotree.service"
SYSTEMCTL_BIN="$(command -v systemctl 2>/dev/null || true)"
systemd_property() {
  local property="$1"
  "$SYSTEMCTL_BIN" show "$SYSTEMD_UNIT" "--property=$property" --value
}

SYSTEMD_LOAD_STATE="not-found"
if [ -n "$SYSTEMCTL_BIN" ]; then
  if ! SYSTEMD_LOAD_STATE="$(systemd_property LoadState 2>/dev/null)"; then
    echo "[restart] 거부: systemctl은 있으나 $SYSTEMD_UNIT LoadState를 읽을 수 없다." >&2
    exit 2
  fi
fi

if [ "$SYSTEMD_LOAD_STATE" = "loaded" ]; then
  UNIT_ID="$(systemd_property Id)"
  UNIT_NAMES="$(systemd_property Names)"
  UNIT_TYPE="$(systemd_property Type)"
  UNIT_RESTART="$(systemd_property Restart)"
  UNIT_KILL_MODE="$(systemd_property KillMode)"
  UNIT_WORKING_DIRECTORY="$(systemd_property WorkingDirectory)"
  UNIT_ENVIRONMENT="$(systemd_property Environment)"
  UNIT_ENVIRONMENT_FILES="$(systemd_property EnvironmentFiles)"
  UNIT_EXEC_START="$(systemd_property ExecStart)"
  UNIT_USER="$(systemd_property User)"
  UNIT_GROUP="$(systemd_property Group)"
  UNIT_FRAGMENT_PATH="$(systemd_property FragmentPath)"
  UNIT_DROP_INS="$(systemd_property DropInPaths)"
  UNIT_ACTIVE_STATE="$(systemd_property ActiveState)"
  UNIT_SUB_STATE="$(systemd_property SubState)"
  UNIT_RESULT="$(systemd_property Result)"
  UNIT_MAIN_PID="$(systemd_property MainPID)"
  UNIT_INVOCATION_ID="$(systemd_property InvocationID)"

  if [ "$UNIT_ID" != "$SYSTEMD_UNIT" ] \
      || [ "$UNIT_NAMES" != "$SYSTEMD_UNIT" ] \
      || [ "$UNIT_TYPE" != "simple" ] \
      || [ "$UNIT_RESTART" != "on-failure" ] \
      || [ "$UNIT_KILL_MODE" != "control-group" ] \
      || [ "$UNIT_WORKING_DIRECTORY" != "$ROOT" ] \
      || [ -n "$UNIT_ENVIRONMENT" ] \
      || [ "$UNIT_ENVIRONMENT_FILES" != "$ENV_FILE (ignore_errors=no)" ] \
      || { [ -n "$UNIT_USER" ] && [ "$UNIT_USER" != "root" ]; } \
      || { [ -n "$UNIT_GROUP" ] && [ "$UNIT_GROUP" != "root" ]; } \
      || [ "$UNIT_FRAGMENT_PATH" != "/etc/systemd/system/$SYSTEMD_UNIT" ] \
      || [ -n "$UNIT_DROP_INS" ]; then
    echo "[restart] 거부: $SYSTEMD_UNIT 정적 소유권 계약이 현재 checkout/env와 불일치한다." >&2
    exit 2
  fi
  if [[ "$UNIT_EXEC_START" != *"path=$PYTHON_BIN ;"* ]] \
      || [[ "$UNIT_EXEC_START" != *"argv[]=$PYTHON_BIN -m uvicorn --app-dir server app:app --host $BIND_HOST --port 55170 --log-level warning ;"* ]] \
      || [[ "$UNIT_EXEC_START" != *"ignore_errors=no"* ]]; then
    echo "[restart] 거부: $SYSTEMD_UNIT ExecStart가 고정된 단일-worker uvicorn 계약과 다르다." >&2
    exit 2
  fi

  OLD_PID=""
  case "$UNIT_ACTIVE_STATE/$UNIT_SUB_STATE" in
    active/running)
      if ! [[ "$UNIT_MAIN_PID" =~ ^[1-9][0-9]*$ ]]; then
        echo "[restart] 거부: active unit의 MainPID가 양의 정수가 아니다($UNIT_MAIN_PID)." >&2
        exit 2
      fi
      OLD_PID="$UNIT_MAIN_PID"
      PID="$(listener_pid)"
      if [ "$PID" != "$OLD_PID" ] || ! process_is_this_server "$OLD_PID"; then
        echo "[restart] 거부: systemd MainPID=$OLD_PID 와 :55170 listener/checkout 정체성이 불일치한다." >&2
        exit 2
      fi
      OLD_PID_START="$(process_start_time "$OLD_PID")"
      if [ -z "$OLD_PID_START" ]; then
        echo "[restart] 거부: systemd MainPID $OLD_PID start-time을 읽을 수 없다." >&2
        exit 2
      fi
      if [ "$UNIT_RESULT" != "success" ] \
          || ! [[ "$UNIT_INVOCATION_ID" =~ ^[0-9a-fA-F]{32}$ ]]; then
        echo "[restart] 거부: active unit의 Result/InvocationID 영수증이 유효하지 않다." >&2
        exit 2
      fi
      backup_process_environment "$OLD_PID"
      ;;
    inactive/dead)
      if [ "$UNIT_MAIN_PID" != "0" ] || [ -n "$(listener_pid)" ]; then
        echo "[restart] 거부: inactive unit인데 MainPID 또는 :55170 listener가 남아 있다." >&2
        exit 2
      fi
      if { [ -n "$UNIT_RESULT" ] && [ "$UNIT_RESULT" != "success" ]; } \
          || { [ -n "$UNIT_INVOCATION_ID" ] \
            && ! [[ "$UNIT_INVOCATION_ID" =~ ^[0-9a-fA-F]{32}$ ]]; }; then
        echo "[restart] 거부: inactive unit의 선택적 Result/InvocationID가 손상됐다." >&2
        exit 2
      fi
      ;;
    *)
      echo "[restart] 거부: $SYSTEMD_UNIT 상태가 안정된 active/running 또는 inactive/dead가 아니다($UNIT_ACTIVE_STATE/$UNIT_SUB_STATE)." >&2
      exit 2
      ;;
  esac

  managed_original_state_is_unchanged() {
    local current_active current_sub current_result current_pid current_invocation current_listener
    current_active="$(systemd_property ActiveState 2>/dev/null || true)"
    current_sub="$(systemd_property SubState 2>/dev/null || true)"
    current_result="$(systemd_property Result 2>/dev/null || true)"
    current_pid="$(systemd_property MainPID 2>/dev/null || true)"
    current_invocation="$(systemd_property InvocationID 2>/dev/null || true)"
    current_listener="$(listener_pid)"
    if [ -n "$OLD_PID" ]; then
      [ "$current_active" = "active" ] \
        && [ "$current_sub" = "running" ] \
        && [ "$current_result" = "$UNIT_RESULT" ] \
        && [ "$current_pid" = "$UNIT_MAIN_PID" ] \
        && [ "$current_invocation" = "$UNIT_INVOCATION_ID" ] \
        && [ "$current_listener" = "$OLD_PID" ] \
        && process_is_this_server "$OLD_PID" \
        && [ "$(process_start_time "$OLD_PID")" = "$OLD_PID_START" ]
    else
      [ "$current_active" = "inactive" ] \
        && [ "$current_sub" = "dead" ] \
        && [ "$current_result" = "$UNIT_RESULT" ] \
        && [ "$current_pid" = "0" ] \
        && [ "$current_invocation" = "$UNIT_INVOCATION_ID" ] \
        && [ -z "$current_listener" ]
    fi
  }

  managed_static_contract_is_unchanged() {
    [ "$(systemd_property LoadState 2>/dev/null || true)" = "$SYSTEMD_LOAD_STATE" ] \
      && [ "$(systemd_property Id 2>/dev/null || true)" = "$UNIT_ID" ] \
      && [ "$(systemd_property Names 2>/dev/null || true)" = "$UNIT_NAMES" ] \
      && [ "$(systemd_property Type 2>/dev/null || true)" = "$UNIT_TYPE" ] \
      && [ "$(systemd_property Restart 2>/dev/null || true)" = "$UNIT_RESTART" ] \
      && [ "$(systemd_property KillMode 2>/dev/null || true)" = "$UNIT_KILL_MODE" ] \
      && [ "$(systemd_property WorkingDirectory 2>/dev/null || true)" = "$UNIT_WORKING_DIRECTORY" ] \
      && [ "$(systemd_property Environment 2>/dev/null || true)" = "$UNIT_ENVIRONMENT" ] \
      && [ "$(systemd_property EnvironmentFiles 2>/dev/null || true)" = "$UNIT_ENVIRONMENT_FILES" ] \
      && [ "$(systemd_property ExecStart 2>/dev/null || true)" = "$UNIT_EXEC_START" ] \
      && [ "$(systemd_property User 2>/dev/null || true)" = "$UNIT_USER" ] \
      && [ "$(systemd_property Group 2>/dev/null || true)" = "$UNIT_GROUP" ] \
      && [ "$(systemd_property FragmentPath 2>/dev/null || true)" = "$UNIT_FRAGMENT_PATH" ] \
      && [ "$(systemd_property DropInPaths 2>/dev/null || true)" = "$UNIT_DROP_INS" ]
  }

  old_invocation_is_gone() {
    [ -z "$OLD_PID" ] \
      || [ "$(process_start_time "$OLD_PID")" != "$OLD_PID_START" ]
  }

  stop_managed_unit_and_verify() {
    local stop_rc=0 stopped_active stopped_sub stopped_pid stopped_listener
    "$SYSTEMCTL_BIN" --no-ask-password stop "$SYSTEMD_UNIT" || stop_rc=$?
    for _ in $(seq 1 30); do
      stopped_active="$(systemd_property ActiveState 2>/dev/null || true)"
      stopped_sub="$(systemd_property SubState 2>/dev/null || true)"
      stopped_pid="$(systemd_property MainPID 2>/dev/null || true)"
      stopped_listener="$(listener_pid)"
      if [ "$stopped_active" = "inactive" ] \
          && [ "$stopped_sub" = "dead" ] \
          && [ "$stopped_pid" = "0" ] \
          && [ -z "$stopped_listener" ]; then
        return 0
      fi
      sleep 1
    done
    echo "[restart] 중대 실패: systemctl stop(rc=$stop_rc) 후에도 inactive/dead, MainPID=0, 빈 포트를 증명하지 못했다." >&2
    return 1
  }

  # Keep the posture check before the final compare-and-act window.
  "$PREFLIGHT_PYTHON" -m server.auth_posture "$BIND_HOST" || exit $?

  # Close the observation-to-restart window. Nothing may run between this
  # comparison and the single systemctl mutation.
  if ! managed_static_contract_is_unchanged \
      || ! managed_original_state_is_unchanged \
      || [ "$(env_file_identity)" != "$ENV_FILE_IDENTITY" ]; then
    echo "[restart] 거부: unit/runtime/listener/env identity가 restart 직전 바뀌었다." >&2
    exit 2
  fi

  if ! "$SYSTEMCTL_BIN" --no-ask-password restart "$SYSTEMD_UNIT"; then
    echo "[restart] 실패: systemctl restart가 실패했다. direct/nohup fallback은 금지된다." >&2
    if managed_original_state_is_unchanged; then
      echo "[restart] 기존 systemd invocation은 byte/state-identical하게 유지됐다; 추가 stop은 수행하지 않는다." >&2
      exit 1
    fi
    if ! stop_managed_unit_and_verify; then
      exit 3
    fi
    exit 1
  fi

  H=""
  for _ in $(seq 1 30); do
    sleep 1
    NEW_ACTIVE="$(systemd_property ActiveState 2>/dev/null || true)"
    NEW_SUB="$(systemd_property SubState 2>/dev/null || true)"
    NEW_RESULT="$(systemd_property Result 2>/dev/null || true)"
    NEW_PID="$(systemd_property MainPID 2>/dev/null || true)"
    NEW_INVOCATION_ID="$(systemd_property InvocationID 2>/dev/null || true)"
    LISTENER_PID="$(listener_pid)"
    if [ "$NEW_ACTIVE" = "active" ] \
        && [ "$NEW_SUB" = "running" ] \
        && [ "$NEW_RESULT" = "success" ] \
        && [[ "$NEW_PID" =~ ^[1-9][0-9]*$ ]] \
        && [ "$NEW_PID" != "${OLD_PID:-0}" ] \
        && [ "$NEW_INVOCATION_ID" != "$UNIT_INVOCATION_ID" ] \
        && [[ "$NEW_INVOCATION_ID" =~ ^[0-9a-fA-F]{32}$ ]] \
        && [ "$LISTENER_PID" = "$NEW_PID" ] \
        && process_is_this_server "$NEW_PID" \
        && [[ "$(process_start_time "$NEW_PID")" =~ ^[1-9][0-9]*$ ]] \
        && old_invocation_is_gone \
        && managed_static_contract_is_unchanged \
        && [ "$(env_file_identity)" = "$ENV_FILE_IDENTITY" ]; then
      H="$(curl --connect-timeout 2 --max-time 5 -sf "$HEALTH_BASE/healthz" || true)"
      if echo "$H" | grep -q '"neo4j":"ok"' \
          && echo "$H" | grep -q '"mongo":"ok"'; then
        VERSION_JSON="$(curl --connect-timeout 2 --max-time 5 -sf "$HEALTH_BASE/version" || true)"
        if [ -n "$VERSION_JSON" ] && validate_version_identity "$VERSION_JSON"; then
          echo "[restart] systemd core healthz ready: $H"
          echo "$VERSION_JSON"
          exit 0
        fi
      fi
    fi
  done
  if ! stop_managed_unit_and_verify; then
    exit 3
  fi
  echo "[restart] 실패: systemd unit/PID/core health/version identity가 수렴하지 않음 — direct/nohup fallback 없음." >&2
  exit 1
elif [ "$SYSTEMD_LOAD_STATE" != "not-found" ]; then
  echo "[restart] 거부: $SYSTEMD_UNIT LoadState=$SYSTEMD_LOAD_STATE (loaded/not-found 외 상태)." >&2
  exit 2
fi

# No loaded service manager owns this listener. Preserve the legacy bounded
# foreground-process replacement path for development hosts only.
PID="$(listener_pid)"
if [ -n "${PID:-}" ]; then
  if ! process_is_this_server "$PID"; then
    echo "[restart] 거부: :55170 PID $PID 가 이 checkout의 라카토트리 uvicorn임을 증명할 수 없다." >&2
    exit 2
  fi
  PID_START="$(process_start_time "$PID")"
  if [ -z "$PID_START" ]; then
    echo "[restart] 거부: PID $PID start-time 영수증을 읽을 수 없다." >&2
    exit 2
  fi
  # 죽이기 전 environ 백업 — env 원본이 프로세스 단일사본인 사고 재발 방지(정본과 대조 가능).
  backup_process_environment "$PID"
  if ! process_is_this_server "$PID" \
      || [ "$(process_start_time "$PID")" != "$PID_START" ]; then
    echo "[restart] 거부: TERM 직전 PID $PID 정체성/start-time이 바뀌었다." >&2
    exit 2
  fi
  kill -TERM "$PID"
  for _ in $(seq 1 50); do
    if ! kill -0 "$PID" 2>/dev/null; then
      break
    fi
    sleep 0.1
  done
  if kill -0 "$PID" 2>/dev/null; then
    echo "[restart] 거부: 기존 PID $PID 가 TERM 후에도 살아있다." >&2
    exit 2
  fi
  REMAINING_PID="$(listener_pid)"
  if [ -n "$REMAINING_PID" ]; then
    echo "[restart] 거부: 기존 listener 종료 후 포트를 PID $REMAINING_PID 가 점유한다." >&2
    exit 2
  fi
fi

LOG="${LAKATOS_SERVER_LOG:-$HOME/.config/lakatotree/server.log}"
mkdir -p "$(dirname "$LOG")"   # 로그 디렉 부재 시 nohup 리다이렉트 실패(2026-07-23 LXC301 실측)
# Keep the final posture check adjacent to launch so no unchecked listener
# override can be inserted between validation and exec.
"$PREFLIGHT_PYTHON" -m server.auth_posture "$BIND_HOST" || exit $?
if [ ! -x "$PYTHON_BIN" ]; then
  echo "[restart] 거부: server Python 실행파일 없음($PYTHON_BIN)." >&2
  exit 2
fi
nohup "$PYTHON_BIN" -m uvicorn --app-dir server app:app --host "$BIND_HOST" --port 55170 --workers 1 \
  > "$LOG" 2>&1 &
NEW_PID=$!

# Core health gate. PostgreSQL/critique history may be explicitly disabled while Neo4j+Mongo
# remain usable; the critique endpoint itself fails before mutation until its audit is green.
H=""
for _ in $(seq 1 15); do
  sleep 1
  if ! kill -0 "$NEW_PID" 2>/dev/null; then
    echo "[restart] 실패: 신규 server PID $NEW_PID 가 health 수렴 전 종료됨." >&2
    exit 1
  fi
  H="$(curl --connect-timeout 2 --max-time 5 -sf "$HEALTH_BASE/healthz" || true)"
  if echo "$H" | grep -q '"neo4j":"ok"' \
      && echo "$H" | grep -q '"mongo":"ok"'; then
    LISTENER_PID="$(listener_pid)"
    if [ "$LISTENER_PID" != "$NEW_PID" ]; then
      echo "[restart] 실패: health 응답 listener PID=$LISTENER_PID, 신규 PID=$NEW_PID 불일치." >&2
      kill -TERM "$NEW_PID" 2>/dev/null || true
      exit 1
    fi
    disown "$NEW_PID" 2>/dev/null || true
    echo "[restart] core healthz ready: $H"
    curl --connect-timeout 2 --max-time 5 -s "$HEALTH_BASE/version"; echo
    exit 0
  fi
done
kill -TERM "$NEW_PID" 2>/dev/null || true
echo "[restart] 실패: core healthz 가 수렴하지 않음 — 마지막: ${H:-<no response>}" >&2
echo "[restart] version 200 은 건강이 아니다 — creds($ENV_FILE)/neo4j·mongo 도달성 확인." >&2
exit 1
