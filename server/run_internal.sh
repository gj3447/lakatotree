#!/usr/bin/env bash
# 라카토트리 서버 — 내부망(macmini) 기동. 우리 dgx neo4j + dgx mongo 물림.
# PG는 내부망 미가동 → lazy(history append만 degrade, core neo4j ops 정상).
set -e
export NEO4J_URI="${NEO4J_URI:-bolt://100.64.0.3:7687}"
export NEO4J_USER="${NEO4J_USER:-neo4j}"
export NEO4J_PASSWORD="${NEO4J_PASSWORD:-neo4jpassword}"
export LAKATOS_MONGO_URI="${LAKATOS_MONGO_URI:-mongodb://mongo:mongopassword@100.64.0.3:27017/?authSource=admin}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec uv run uvicorn --app-dir server app:app --host 127.0.0.1 --port "${LAKATO_PORT:-55170}"
