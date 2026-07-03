"""FIX-HARNESS #24 (P3 correctness): LakatoHarness._measure 가 judge_cmd exit code 를 버린다.

- finding id: #24
- locations:
    lakatos/harness.py:156  _measure  ->  out, _ = self._bash(s.judge_cmd)   # exit code 폐기
    lakatos/harness.py:157  return _parse_metric(out)                        # exit 무시하고 파싱
  대조군(mechanism, 이미 존재):
    lakatos/harness.py:146-149  _build_gate  ->  out, code = self._bash(...); if code != 0: raise BuildFailed
- bug:
    채점(judge) 스크립트가 비정상 종료(exit != 0)하면서도 stdout 에 'metric=' 를 한 줄
    찍었으면, _measure 는 exit code 를 `_` 로 버리고 _parse_metric(out) 으로 그 값을 그대로
    수용한다. 즉 `print('metric=0.99'); sys.exit(1)` 같은 *크래시한* judge 가 유효한 외부
    측정값 0.99 로 둔갑한다. _build_gate 는 같은 (out, code) 튜플에서 code != 0 을 엄격히
    raise 하는데, _measure 만 ground-truth 게이트를 흘린다(비대칭).
- exact fix (lakatos/harness.py:156):
    out, code = self._bash(s.judge_cmd)
    if code != 0:
        raise BuildFailed(f'채점 스크립트 비정상 종료(exit {code}) — metric 수용 거부. {out[-120:]}')
    return _parse_metric(out)
  (_build_gate 와 동일하게 exit code 를 캡처해 fail-loud. crash 한 judge 의 metric 은 거부.)
- xfail(strict) until fixed. fix 가 들어오면 strict 가 trip 한다.

dual guards:
  guard_defect    = test_measure_must_reject_nonzero_judge_exit   (negative oracle, RED)
  guard_mechanism = test_build_gate_rejects_nonzero_exit          (positive oracle, 이미 green)
"""
from __future__ import annotations

import pytest

from lakatos.harness import LakatoHarness, CycleSpec, BuildFailed


def _bash_judge_crashes(cmd):
    """하계 mock: build 는 통과, judge 는 metric 을 찍고도 exit!=0 (크래시)."""
    if 'build' in cmd or 'pytest' in cmd:
        return ('... 49 passed', 0)
    return ('metric=0.99', 1)            # judge: metric 출력 + 비정상 종료(exit 1)


def _noop_http(method, path, body=None):
    if path.endswith('/test_result'):
        return {'ok': True, 'verdict': 'progressive'}
    if path.endswith('/standing'):
        return {'stands': True}
    return {'ok': True}


def _make_harness():
    return LakatoHarness(http=_noop_http, run_bash=_bash_judge_crashes)


# judge_cmd 만 있는 spec — _measure 가 실제로 judge 를 실행하는 경로를 탄다.
SPEC = CycleSpec(tree='T', tag='v9', parent='v8', metric='p95', baseline=0.5,
                 direction='lower', judge_cmd='python judges/score.py')


# [FIXED 2026-06-27] #24 — green regression (lakatos/harness.py:_measure raises BuildFailed on exit!=0)
def test_measure_must_reject_nonzero_judge_exit():
    """negative oracle: exit!=0 인 judge 의 metric 은 거부(raise)되어야 한다.

    오늘은 _measure 가 0.99 를 그대로 반환한다(버그). fix 후엔 BuildFailed 로 raise.
    """
    h = _make_harness()
    # 사전 조건 증명: judge 가 실제로 metric 을 찍지만 exit 1 로 크래시한다.
    assert _bash_judge_crashes('python judges/score.py') == ('metric=0.99', 1)
    # 올바른(fix 후) 동작: crash 한 judge 의 측정은 수용하지 말고 raise.
    with pytest.raises(BuildFailed):
        h._measure(SPEC)


# [mechanism, 이미 green] _build_gate 는 같은 (out, code) 에서 exit!=0 을 엄격히 거부한다.
def test_build_gate_rejects_nonzero_exit():
    """positive oracle: _measure 가 따라야 할 대칭 메커니즘이 _build_gate 엔 이미 존재."""
    spec = CycleSpec(tree='T', tag='v9', parent='v8', metric='p95', baseline=0.5,
                     direction='lower', build_cmd='pytest tests/ -q')

    def bash_build_crashes(cmd):
        return ('boom', 1)               # build 가 exit 1
    h = LakatoHarness(http=_noop_http, run_bash=bash_build_crashes)
    with pytest.raises(BuildFailed):
        h._build_gate(spec)
