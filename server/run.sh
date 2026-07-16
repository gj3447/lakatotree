#!/usr/bin/env bash
# 라카토트리 서버 기동 — creds 런타임 주입 (echo 금지)
# ★creds 정본 = 자족 env 파일(repo 밖, git 미추적, chmod 600). NEO4J/PG/MONGO 전부 포함.
#   구 경로(vision3d_test/.env + ~/.claude/settings.json[env] + docker exec postgresql)는
#   2026-07 creds 단일사본 소멸 사고로 유실 → server.env 단일 소스로 봉합.
#   위치 override: LAKATOS_SERVER_ENV=/path/to/server.env
LAKATOS_SERVER_ENV="${LAKATOS_SERVER_ENV:-$HOME/.config/lakatotree/server.env}"
if [ ! -r "$LAKATOS_SERVER_ENV" ]; then
  echo "[run.sh] ★creds env 없음/읽기불가: $LAKATOS_SERVER_ENV — 서버 기동 중단" >&2
  echo "[run.sh]   NEO4J/PG/MONGO creds 를 담은 env 파일이 필요하다 (LAKATOS_SERVER_ENV 로 경로 지정 가능)." >&2
  exit 1
fi
set -a; source "$LAKATOS_SERVER_ENV"; set +a
# Mongo 기본값 폴백(env 에 없으면).
export LAKATOS_MONGO_URI="${LAKATOS_MONGO_URI:-mongodb://localhost:27017}"
cd "$(dirname "$0")"
# OPS-HON-1/OPS-BOOTSTRAP-1: 스키마 부트스트랩(멱등 — schema.sql 은 CREATE TABLE/INDEX IF NOT EXISTS).
# ★silent skip 금지: psql 미설치/PG 미가동(benign skip) vs PG 가동중 schema.sql 진짜 오류(loud exit) 구분.
if ! command -v psql >/dev/null 2>&1; then
  echo "[run.sh] psql 미설치 — schema 부트스트랩 skip (best-effort hist 로 계속)" >&2
else
  schema_err="$(PGPASSWORD="$LAKATOS_PG_PASSWORD" psql -v ON_ERROR_STOP=1 \
    -h "${LAKATOS_PG_HOST:-localhost}" -p "$LAKATOS_PG_PORT" \
    -U "$LAKATOS_PG_USER" -d "$LAKATOS_PG_DB" -f schema.sql 2>&1 >/dev/null)"
  schema_rc=$?
  if [ "$schema_rc" -eq 0 ]; then
    echo "[run.sh] schema 적용 완료(멱등)" >&2
  elif printf '%s' "$schema_err" | grep -qiE 'could not connect|connection refused|could not translate|server closed'; then
    echo "[run.sh] PG 미가동 — schema skip (best-effort hist 로 계속): $schema_err" >&2
  else
    echo "[run.sh] ★schema 부트스트랩 실패(PG 가동중인데 schema.sql 오류) — 서버 기동 중단:" >&2
    printf '%s\n' "$schema_err" >&2
    exit 1
  fi
fi
# 파이썬 인터프리터 해석 — systemd 등 최소 PATH 환경에서 'python' 미존재(status 127) 방지.
# 우선순위: LAKATOS_PY > repo .venv > python3 > python.
PY="${LAKATOS_PY:-}"
if [ -z "$PY" ]; then
  if [ -x "$(dirname "$0")/../.venv/bin/python" ]; then PY="$(cd "$(dirname "$0")/.." && pwd)/.venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then PY="python3"
  elif command -v python  >/dev/null 2>&1; then PY="python"
  else echo "[run.sh] ★python 인터프리터 없음 (LAKATOS_PY 로 지정) — 기동 중단" >&2; exit 1; fi
fi
# OPS-UVICORN-1: 워커 수 env 노브(기본 1=현 동작 보존). 멀티워커는 프로세스 분리라 각자
# NEO/MONGO/PG풀을 갖는다(공유 안전). 부하 시 UVICORN_WORKERS=$(nproc) 로 스케일.
exec "$PY" -m uvicorn app:app --host 0.0.0.0 --port 55170 --workers "${UVICORN_WORKERS:-1}" "$@"
