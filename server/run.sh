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
exec python -m uvicorn app:app --host 0.0.0.0 --port 55170 "$@"
