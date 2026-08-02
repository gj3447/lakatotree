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

set -a; . "$ENV_FILE"; set +a

: "${NEO4J_DATABASE:?NEO4J_DATABASE 설정 필요($ENV_FILE)}"
for MIGRATION_SECRET in \
  LAKATOS_STORAGE_PG_MIGRATION_USER \
  LAKATOS_STORAGE_PG_MIGRATION_PASSWORD \
  LAKATOS_STORAGE_NEO4J_MIGRATION_USER \
  LAKATOS_STORAGE_NEO4J_MIGRATION_PASSWORD; do
  if printenv "$MIGRATION_SECRET" >/dev/null 2>&1; then
    echo "[restart] 거부: migration credential은 runtime 환경에 둘 수 없음($MIGRATION_SECRET)" >&2
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
if [ -x "$PYTHON_BIN" ]; then
  PREFLIGHT_PYTHON="$PYTHON_BIN"
elif command -v python3 >/dev/null 2>&1; then
  PREFLIGHT_PYTHON="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PREFLIGHT_PYTHON="$(command -v python)"
else
  echo "[restart] 거부: auth posture를 검증할 Python이 없다." >&2
  exit 2
fi

# The critique-history storage audit is cached in-process.  Until that state is
# backed by a shared coordinator, every supported launcher must remain a single
# worker so one process cannot stay green after another observes divergence.
if [ "${WEB_CONCURRENCY:-1}" != "1" ]; then
  echo "[restart] 거부: WEB_CONCURRENCY=${WEB_CONCURRENCY} — storage audit cache는 단일 worker만 지원한다." >&2
  exit 2
fi
export WEB_CONCURRENCY=1

# Canonical env can widen the bind or inject UVICORN_FD/UDS.  Validate the
# final sourced values before touching the currently healthy listener.
"$PREFLIGHT_PYTHON" -m server.auth_posture "$BIND_HOST" || exit $?

listener_pid() {
  ss -ltnp 2>/dev/null \
    | grep :55170 \
    | grep -oP 'pid=\K[0-9]+' \
    | head -1 \
    || true
}

PID="$(listener_pid)"
if [ -n "${PID:-}" ]; then
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
  BACKUP_FILE="$ENV_FILE.lastboot"
  BACKUP_TMP="$(mktemp "$BACKUP_FILE.XXXXXX")"
  if tr '\0' '\n' < "$PROC_ROOT/$PID/environ" 2>/dev/null \
      | grep -E "^NEO4J|^LAKATOS|^MONGO" \
      | grep -Ev '^LAKATOS_STORAGE_(PG|NEO4J)_MIGRATION_(USER|PASSWORD)=' \
      > "$BACKUP_TMP"; then
    chmod 600 "$BACKUP_TMP"
    mv -f "$BACKUP_TMP" "$BACKUP_FILE"
  else
    rm -f "$BACKUP_TMP"
  fi
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
