#!/usr/bin/env bash
# 라카토트리 서버 기동 — creds 런타임 주입 (echo 금지)
set -a; source /mnt/hdd/kjra/vision3d_test/.env; set +a
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
# OPS-HON-1: 스키마 부트스트랩(멱등 — schema.sql 은 CREATE TABLE/INDEX IF NOT EXISTS). 신규 PG 에 테이블
# 생성 → 미존재 시 hist/lineage 의 ProgrammingError(500 누수) 방지. psql 미설치/PG 미가동이면 비치명적 skip.
PGPASSWORD="$LAKATOS_PG_PASSWORD" psql -h "${LAKATOS_PG_HOST:-localhost}" -p "$LAKATOS_PG_PORT" \
  -U "$LAKATOS_PG_USER" -d "$LAKATOS_PG_DB" -f schema.sql >/dev/null 2>&1 \
  && echo "[run.sh] schema 적용 완료(멱등)" >&2 \
  || echo "[run.sh] schema 부트스트랩 건너뜀(psql 미설치/PG 미가동) — best-effort hist 로 계속" >&2
exec python -m uvicorn app:app --host 0.0.0.0 --port 55170 "$@"
