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
  # In file-backed mode the file is a complete authority snapshot, not an
  # overlay on ambient shell state. Keep one-shot secrets visible so the
  # explicit rejection loop can still catch inherited credential leakage.
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
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi
# canonical env가 caller 값을 좁히거나 넓힐 수 있으므로 source 이후 값만 권위다.
BIND_HOST="${LAKATOS_BIND_HOST:-127.0.0.1}"
PYTHON_BIN="${LAKATOS_PYTHON:-$ROOT/.venv/bin/python}"
WORKER_COUNT="${UVICORN_WORKERS:-1}"
if [ "$WORKER_COUNT" != "1" ] || [ "${WEB_CONCURRENCY:-1}" != "1" ]; then
  echo "[run_internal.sh] 거부: 최종 worker count는 1이어야 함" >&2
  exit 2
fi
if [ ! -x "$PYTHON_BIN" ]; then
  echo "[run_internal.sh] Python venv 없음: $PYTHON_BIN" >&2
  exit 2
fi
PREFLIGHT_PYTHON="$PYTHON_BIN"
"$PREFLIGHT_PYTHON" -m server.auth_posture "$BIND_HOST" "$@" || exit $?
: "${NEO4J_URI:?NEO4J_URI 설정 필요($ENV_FILE)}"
: "${NEO4J_DATABASE:?NEO4J_DATABASE 설정 필요($ENV_FILE)}"
: "${NEO4J_USER:?NEO4J_USER 설정 필요($ENV_FILE)}"
: "${NEO4J_PASSWORD:?NEO4J_PASSWORD 설정 필요($ENV_FILE)}"
: "${LAKATOS_MONGO_URI:?LAKATOS_MONGO_URI 설정 필요($ENV_FILE)}"
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
    echo "[run_internal.sh] 거부: migration credential 또는 audit credential은 runtime 환경에 둘 수 없음($MIGRATION_SECRET)" >&2
    exit 2
  fi
done
# Preserve the documented core-only mode only when the complete storage profile
# is absent. Any declared storage field activates strict raw evidence preflight.
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
# PostgreSQL remains optional for core reads and non-ledger operation.  The application
# caches an exhaustive storage audit at startup and rejects every ledger-backed mutation
# before its domain change until the explicit predeploy contract and writer lease pass.

# Final listener check stays adjacent to exec so future launcher edits cannot insert an
# unchecked override after the canonical-env preflight.
"$PREFLIGHT_PYTHON" -m server.auth_posture "$BIND_HOST" "$@" || exit $?

exec "$PYTHON_BIN" -m uvicorn --app-dir server app:app --host "$BIND_HOST" \
  --port "${LAKATO_PORT:-55170}" --workers 1 "$@"
