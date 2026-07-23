#!/usr/bin/env bash
# 라카토트리 dev 서버(:55170) 재시작 러너 — creds 단일사본 소멸 사고(2026-07-02)의 봉합 (omd F5).
#
# 사고: creds 없는 쉘로 재기동 → neo4j/pg down 인데 /version 은 200(무음 degraded) + 비번 원본이
# 죽은 프로세스와 함께 소멸. 봉합: ① 정본 env(~/.config/lakatotree/server.env, 0600) 없으면 기동
# *거부* ② 죽이기 전 현 프로세스 environ 백업 ③ healthz **3/3 ok 게이트**(version 200 ≠ 건강)
# ④ 포트로 죽임(pkill -f "app:app" 금지 — 자기 쉘 자살).
set -euo pipefail

ENV_FILE="${LAKATOS_SERVER_ENV:-$HOME/.config/lakatotree/server.env}"
if [ ! -f "$ENV_FILE" ]; then
  echo "[restart] 거부: canonical env 없음($ENV_FILE) — 무-creds 기동은 무음 degraded 를 만든다." >&2
  echo "[restart] 복구: 건강한 서버가 살아있다면:" >&2
  echo "  PID=\$(ss -ltnp | grep :55170 | grep -oP 'pid=\\K[0-9]+' | head -1)" >&2
  echo "  tr '\\0' '\\n' < /proc/\$PID/environ | grep -E '^NEO4J|^LAKATOS|^MONGO' > $ENV_FILE && chmod 600 $ENV_FILE" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PID="$(ss -ltnp 2>/dev/null | grep :55170 | grep -oP 'pid=\K[0-9]+' | head -1 || true)"
if [ -n "${PID:-}" ]; then
  # 죽이기 전 environ 백업 — env 원본이 프로세스 단일사본인 사고 재발 방지(정본과 대조 가능).
  tr '\0' '\n' < "/proc/$PID/environ" 2>/dev/null \
    | grep -E "^NEO4J|^LAKATOS|^MONGO" > "$ENV_FILE.lastboot" || true
  kill -TERM "$PID"
  sleep 2
fi

set -a; . "$ENV_FILE"; set +a
LOG="${LAKATOS_SERVER_LOG:-$HOME/.config/lakatotree/server.log}"
mkdir -p "$(dirname "$LOG")"   # 로그 디렉 부재 시 nohup 리다이렉트 실패(2026-07-23 LXC301 실측)
# 바인드는 auth_posture 와 같은 LAKATOS_BIND_HOST 규약 — 기본 loopback(안전),
# LXC/VM 처럼 외부 socat relay 가 붙는 배포는 env 에 0.0.0.0 선언(하드코딩 시 socat 경유 접속 사망).
BIND_HOST="${LAKATOS_BIND_HOST:-127.0.0.1}"
nohup .venv/bin/python -m uvicorn --app-dir server app:app --host "$BIND_HOST" --port 55170 \
  > "$LOG" 2>&1 &
disown

# healthz 3/3 게이트 — 기동 직후 lazy-connect 과도기(degraded)를 재시도로 흡수, 끝내 degraded 면 fail-loud.
H=""
for _ in $(seq 1 15); do
  sleep 2
  H="$(curl -s http://127.0.0.1:55170/healthz || true)"
  if echo "$H" | grep -q '"status":"ok"'; then
    echo "[restart] healthz ok: $H"
    curl -s http://127.0.0.1:55170/version; echo
    exit 0
  fi
done
echo "[restart] 실패: healthz 가 ok 로 수렴하지 않음 — 마지막: ${H:-<no response>}" >&2
echo "[restart] version 200 은 건강이 아니다 — creds($ENV_FILE)/neo4j·pg 도달성 확인." >&2
exit 1
