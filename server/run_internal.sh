#!/usr/bin/env bash
# 라카토트리 서버 — 내부망(macmini) 기동. 우리 dgx neo4j + dgx mongo 물림.
# PG는 내부망 미가동 → lazy(history append만 degrade, core neo4j ops 정상).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIND_HOST="${LAKATOS_BIND_HOST:-127.0.0.1}"
PYTHON_BIN="${LAKATOS_PYTHON:-$ROOT/.venv/bin/python}"
if [ -x "$PYTHON_BIN" ]; then
  PREFLIGHT_PYTHON="$PYTHON_BIN"
elif command -v python3 >/dev/null 2>&1; then
  PREFLIGHT_PYTHON="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PREFLIGHT_PYTHON="$(command -v python)"
else
  echo "[run_internal.sh] Python venv 없음: $PYTHON_BIN (preflight interpreter도 없음)" >&2
  exit 2
fi
cd "$ROOT"
"$PREFLIGHT_PYTHON" -m server.auth_posture "$BIND_HOST" "$@" || exit $?

ENV_FILE="${LAKATOS_ENV_FILE:-$HOME/.config/lakatotree/server.env}"
if [ -r "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi
# env 파일이 token/listener 자세를 바꾼 뒤의 값이 권위다. DB 접촉 전에 다시 fail-closed 검증한다.
"$PREFLIGHT_PYTHON" -m server.auth_posture "$BIND_HOST" "$@" || exit $?
if [ ! -x "$PYTHON_BIN" ]; then
  echo "[run_internal.sh] Python venv 없음: $PYTHON_BIN" >&2
  exit 2
fi
: "${NEO4J_URI:?NEO4J_URI 설정 필요($ENV_FILE)}"
: "${NEO4J_USER:?NEO4J_USER 설정 필요($ENV_FILE)}"
: "${NEO4J_PASSWORD:?NEO4J_PASSWORD 설정 필요($ENV_FILE)}"
: "${LAKATOS_MONGO_URI:?LAKATOS_MONGO_URI 설정 필요($ENV_FILE)}"

exec "$PYTHON_BIN" -m uvicorn --app-dir server app:app --host "$BIND_HOST" \
  --port "${LAKATO_PORT:-55170}" "$@"
