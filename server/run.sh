#!/usr/bin/env bash
# 라카토트리 서버 기동 — creds 런타임 주입 (echo 금지)
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIND_HOST="${LAKATOS_BIND_HOST:-127.0.0.1}"
PYTHON_BIN="${LAKATOS_PYTHON:-$ROOT/.venv/bin/python}"
# Storage readiness is an exhaustive startup/operator audit cached in-process.
# Until that generation is shared durably, multiple workers would disagree
# after an operator refresh.  Fail closed instead of serving split readiness.
WORKER_COUNT="${UVICORN_WORKERS:-1}"
if [ "$WORKER_COUNT" != "1" ]; then
  echo "[run.sh] 거부: storage audit cache는 process-local — UVICORN_WORKERS=1만 지원" >&2
  exit 2
fi
for LAUNCH_ARG in "$@"; do
  case "$LAUNCH_ARG" in
    --workers|-w|--workers=*|-w=*)
      echo "[run.sh] 거부: worker override 금지(process-local storage audit cache)" >&2
      exit 2
      ;;
  esac
done
# Clean CI/system installs may lack the durable repository venv. Auth posture is stdlib-only and
# must run *before* dependency checks, so use an available bootstrap interpreter for preflight;
# the actual server still requires PYTHON_BIN below.
if [ -x "$PYTHON_BIN" ]; then
  PREFLIGHT_PYTHON="$PYTHON_BIN"
elif command -v python3 >/dev/null 2>&1; then
  PREFLIGHT_PYTHON="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PREFLIGHT_PYTHON="$(command -v python)"
else
  echo "[run.sh] Python venv 없음: $PYTHON_BIN (preflight interpreter도 없음)" >&2
  exit 2
fi
cd "$ROOT"
"$PREFLIGHT_PYTHON" -m server.auth_posture "$BIND_HOST" "$@" || exit $?
if [ ! -x "$PYTHON_BIN" ]; then
  echo "[run.sh] Python venv 없음: $PYTHON_BIN" >&2
  exit 2
fi

ENV_FILE="${LAKATOS_ENV_FILE:-$HOME/.config/lakatotree/server.env}"
if [ ! -f "$ENV_FILE" ] || [ -L "$ENV_FILE" ]; then
  echo "[run.sh] canonical env는 symlink 아닌 일반 파일이어야 함: $ENV_FILE" >&2
  exit 2
fi
ENV_UID="$(stat -c '%u' "$ENV_FILE" 2>/dev/null \
  || stat -f '%u' "$ENV_FILE" 2>/dev/null || true)"
ENV_MODE="$(stat -c '%a' "$ENV_FILE" 2>/dev/null \
  || stat -f '%Lp' "$ENV_FILE" 2>/dev/null || true)"
if [ "$ENV_UID" != "$(id -u)" ] || [ "$ENV_MODE" != "600" ]; then
  echo "[run.sh] canonical env는 현재 사용자 소유의 0600 일반 파일이어야 함: $ENV_FILE" >&2
  exit 2
fi
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# The canonical env is authoritative for the final listener and interpreter.
BIND_HOST="${LAKATOS_BIND_HOST:-127.0.0.1}"
PYTHON_BIN="${LAKATOS_PYTHON:-$ROOT/.venv/bin/python}"
WORKER_COUNT="${UVICORN_WORKERS:-1}"
if [ "$WORKER_COUNT" != "1" ] || [ "${WEB_CONCURRENCY:-1}" != "1" ]; then
  echo "[run.sh] 거부: canonical env의 worker count는 1이어야 함" >&2
  exit 2
fi
# sourced env가 token을 지우거나 UVICORN_FD/UDS를 주입할 수 있으므로 최종 자세를 다시 판정한다.
"$PREFLIGHT_PYTHON" -m server.auth_posture "$BIND_HOST" "$@" || exit $?
if [ ! -x "$PYTHON_BIN" ]; then
  echo "[run.sh] Python venv 없음: $PYTHON_BIN" >&2
  exit 2
fi
: "${NEO4J_URI:?NEO4J_URI 설정 필요($ENV_FILE)}"
: "${NEO4J_DATABASE:?NEO4J_DATABASE 설정 필요($ENV_FILE)}"
: "${NEO4J_USER:?NEO4J_USER 설정 필요($ENV_FILE)}"
: "${NEO4J_PASSWORD:?NEO4J_PASSWORD 설정 필요($ENV_FILE)}"
: "${LAKATOS_MONGO_URI:?LAKATOS_MONGO_URI 설정 필요($ENV_FILE)}"
for MIGRATION_SECRET in \
  LAKATOS_STORAGE_PG_MIGRATION_USER \
  LAKATOS_STORAGE_PG_MIGRATION_PASSWORD \
  LAKATOS_STORAGE_NEO4J_MIGRATION_USER \
  LAKATOS_STORAGE_NEO4J_MIGRATION_PASSWORD; do
  if printenv "$MIGRATION_SECRET" >/dev/null 2>&1; then
    echo "[run.sh] 거부: migration credential은 runtime 환경에 둘 수 없음($MIGRATION_SECRET)" >&2
    exit 2
  fi
done
# PostgreSQL is optional for core reads and non-ledger operations.  Every ledger-backed
# mutation remains fail-closed until the explicit storage contract and writer lease pass.
cd "$ROOT/server"
# Single worker is a correctness boundary until storage-audit generations are shared.
"$PREFLIGHT_PYTHON" -m server.auth_posture "$BIND_HOST" "$@" || exit $?
exec "$PYTHON_BIN" -m uvicorn app:app --host "$BIND_HOST" --port 55170 \
  --workers 1 "$@"
