#!/usr/bin/env bash
# D seed(test-infra): verdict 커널 mutation 테스트(mutmut). 커버리지는 '실행됐나'만 보지만 mutation 은
# '테스트가 *실제로 검출하나*'를 본다 — 커널의 생존 mutant = model<->impl 버그 후보. 느림 → CI job(비차단).
# 빠른 검출 위해 커널 직격 테스트만 runner 로(judge/bayes conformance + 단위). 사용: bash scripts/mutation_kernel.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"
RUNNER="$PY -m pytest -x -q tests/test_judge.py tests/test_bayes.py tests/test_pidna_conformance.py tests/test_spine.py"
exec "$PY" -m mutmut run \
  --paths-to-mutate "lakatos/verdict/judge.py,lakatos/quant/bayes.py" \
  --runner "$RUNNER"
