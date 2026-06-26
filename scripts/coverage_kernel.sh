#!/usr/bin/env bash
# D seed(test-infra): verdict+quant 커널 커버리지 ratchet. '768 passed' 수동집계를 *수치* 영수증으로.
# 커널은 model<->impl 버그가 사는 곳(외부리뷰 B-1) — 95% floor 회귀 차단. 전체 lakatos 는 io/cli/mcp
# seam 포함이라 별도(이 ratchet 은 커널만). 사용: bash scripts/coverage_kernel.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"
exec "$PY" -m pytest tests/ -q \
  --cov=lakatos/verdict --cov=lakatos/quant \
  --cov-report=term-missing --cov-fail-under=95
