#!/usr/bin/env bash
# 라카토트리 서버 기동 — creds 런타임 주입 (echo 금지)
set -a; source <WORKSPACE>/vision3d_test/.env; set +a
eval "$(python -c "
import json
e = json.load(open('$HOME/.claude/settings.json'))['env']
print(f\"export NEO4J_URI='{e['NEO4J_URI']}'\")
print(f\"export NEO4J_USER='{e['NEO4J_USERNAME']}'\")
print(f\"export NEO4J_PASSWORD='{e['NEO4J_PASSWORD']}'\")
")"
export LAKATOS_PG_PASSWORD="$(docker exec postgresql printenv POSTGRES_PASSWORD)"
export LAKATOS_PG_USER=admin LAKATOS_PG_PORT=55100 LAKATOS_PG_DB=lakatos
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
# OPS-UVICORN-1: 워커 수 env 노브(기본 1=현 동작 보존). 멀티워커는 프로세스 분리라 각자
# NEO/MONGO/PG풀을 갖는다(공유 안전). 부하 시 UVICORN_WORKERS=$(nproc) 로 스케일.
exec python -m uvicorn app:app --host 0.0.0.0 --port 55170 --workers "${UVICORN_WORKERS:-1}" "$@"
