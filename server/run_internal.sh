#!/usr/bin/env bash
# 라카토트리 서버 — canonical env 또는 명시적 현재 환경으로 기동.
# 저장소 위치/자격증명은 launcher가 추정하지 않으며 배포 env가 전부 지정한다.
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# The exact storage audit is cached per process.  Multiple workers would split
# readiness and mutation authority after a refresh, so both launchers enforce
# one worker until a shared signed audit generation exists.
WORKER_COUNT="${UVICORN_WORKERS:-1}"
if [ "$WORKER_COUNT" != "1" ]; then
  echo "[run_internal.sh] 거부: storage audit cache는 process-local — UVICORN_WORKERS=1만 지원" >&2
  exit 2
fi
for LAUNCH_ARG in "$@"; do
  case "$LAUNCH_ARG" in
    --workers|-w|--workers=*|-w=*)
      echo "[run_internal.sh] 거부: worker override 금지(process-local storage audit cache)" >&2
      exit 2
      ;;
  esac
done

ENV_FILE="${LAKATOS_ENV_FILE:-$HOME/.config/lakatotree/server.env}"
if [ -e "$ENV_FILE" ] || [ -L "$ENV_FILE" ]; then
  if [ ! -f "$ENV_FILE" ] || [ -L "$ENV_FILE" ]; then
    echo "[run_internal.sh] canonical env는 symlink 아닌 일반 파일이어야 함: $ENV_FILE" >&2
    exit 2
  fi
  ENV_UID="$(stat -c '%u' "$ENV_FILE" 2>/dev/null \
    || stat -f '%u' "$ENV_FILE" 2>/dev/null || true)"
  ENV_MODE="$(stat -c '%a' "$ENV_FILE" 2>/dev/null \
    || stat -f '%Lp' "$ENV_FILE" 2>/dev/null || true)"
  if [ "$ENV_UID" != "$(id -u)" ] || [ "$ENV_MODE" != "600" ]; then
    echo "[run_internal.sh] canonical env는 현재 사용자 소유의 0600 일반 파일이어야 함: $ENV_FILE" >&2
    exit 2
  fi
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi
# canonical env가 caller 값을 좁히거나 넓힐 수 있으므로 source 이후 값만 권위다.
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
"$PREFLIGHT_PYTHON" -m server.auth_posture "$BIND_HOST" "$@" || exit $?
if [ ! -x "$PYTHON_BIN" ]; then
  echo "[run_internal.sh] Python venv 없음: $PYTHON_BIN" >&2
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
    echo "[run_internal.sh] 거부: migration credential은 runtime 환경에 둘 수 없음($MIGRATION_SECRET)" >&2
    exit 2
  fi
done
# PostgreSQL remains optional for core reads and non-ledger operation.  The application
# caches an exhaustive storage audit at startup and rejects every ledger-backed mutation
# before its domain change until the explicit predeploy contract and writer lease pass.

# Final listener check stays adjacent to exec so future launcher edits cannot insert an
# unchecked override after the canonical-env preflight.
"$PREFLIGHT_PYTHON" -m server.auth_posture "$BIND_HOST" "$@" || exit $?

exec "$PYTHON_BIN" -m uvicorn --app-dir server app:app --host "$BIND_HOST" \
  --port "${LAKATO_PORT:-55170}" --workers 1 "$@"
