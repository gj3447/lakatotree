#!/usr/bin/env python3
"""oo positive verification CLI — lakatos.oo_sink.verify_trace 의 얇은 래퍼(단일 정본).

LTDD positive 단언: 주어진 cycle_id 의 test_session trace 가 oo `tests` 스트림에 *실재*하는지
(ship 의 '예외 없음' 보고가 아니라 실제 도착). logs = ground truth.

사용:
  CONSUMER_LOGS_E2E=1 LAKATOS_TEST_CID=<cid> python -m pytest ...           # ship
  python scripts/oo_positive_verify.py <cid> [--expect-total N] [--retries R] [--delay S]
  → oo 에 trace 실재면 exit 0(GREEN), 없으면 exit 1(RED).
env: OO_URL, OO_USER, OO_PASS, (선택) OO_ORG=default. 시크릿은 env 로만.
# KG: span_lakatotree_oo_sink
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lakatos.oo_sink import verify_trace


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog='oo_positive_verify')
    p.add_argument('cycle_id')
    p.add_argument('--expect-total', type=int)
    p.add_argument('--retries', type=int, default=6)
    p.add_argument('--delay', type=float, default=2.0)
    p.add_argument('--minutes-back', type=int, default=60)
    a = p.parse_args(argv)
    res = verify_trace(a.cycle_id, expect_total=a.expect_total, retries=a.retries,
                       delay=a.delay, minutes_back=a.minutes_back)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    s = res['session']
    if res['ok']:
        print(f"GREEN — oo 도착 확인 (session passed={s.get('passed')}/{s.get('total')}, "
              f"outcomes={res['outcomes']}, {res['attempts']} attempt)", file=sys.stderr)
        return 0
    print(f"RED — positive 단언 실패: {res['reasons']}", file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
