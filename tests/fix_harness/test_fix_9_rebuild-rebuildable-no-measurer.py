"""FIX-HARNESS #9 (P2 정직성): measurer 없는 'rebuildable' 은 생산자 self-report 로 위조 가능.

finding id: #9
locations:
  - lakatos/io/rebuild.py:7-9   모듈 docstring: '측정자≠생산자(감사 M1)' — metric 은 producer
                                self-report stdout 이 아니라 독립 measurer code path 에서 나온다고 광고.
  - lakatos/io/rebuild.py:64    last_producer_out — measurement step 이 *없을 때만* fallback.
  - lakatos/io/rebuild.py:89-97 measurer_separated = (measure_out is not None and measure_cmd not in
                                producer_cmds). measurement step 이 전혀 없으면 measure_out=None →
                                measurer_separated=False → source_out=last_producer_out (producer 자기
                                stdout) → regen==recorded → verdict='rebuildable'.
  - server/cli.py:384-388       유일한 신호인 measurer_separated 에 아무도 게이트하지 않음(그냥 print).

the bug:
  recipe 에 producer step 만 있고 kind=='measurement' step 이 *하나도 없으면*, 모듈이 광고한
  독립 measurer(M1) 가 한 번도 돌지 않는다. 그럼에도 producer 가 print 한 'metric=X' 를 그대로
  믿어 verdict=='rebuildable' 을 낸다 (measurer_separated=False). 즉 생산자가 거짓 metric 을
  print 하면 'rebuildable' 영수증을 자기 자신이 발급한다 — docstring 의 M1 보증과 정면 모순.

the exact fix (lakatos/io/rebuild.py:95):
  'rebuildable' 은 measurer_separated 가 True 일 때만 허용. 독립 measurer 가 없으면
  'rebuildable_unverified' (또는 'no_independent_measurer') 를 내고, 호출자가 bare 'rebuildable'
  와 구별할 수 있어야 한다.

xfail(strict) until fixed — 고쳐지면 strict 가 trip 한다.
"""
from __future__ import annotations

import pytest

from lakatos.io.lineage import RawRoot, RebuildManifest
from lakatos.io.rebuild import RebuildExecutor, RebuildResult

# producer step 단 하나, kind=='measurement' step 은 *전혀 없음*.
# 따라서 어떤 독립 measurer 도 돌지 않는다 — metric 의 유일한 출처는 producer self-report stdout.
NO_MEASURER_MANI = RebuildManifest(
    final="perview.json",
    roots=[RawRoot("VFEZ0060.zdf", "z0", "ZDF")],
    env_sha="ENV1",
    recipe=[
        {"producer": "334.py", "producer_sha": "s1", "inputs": ["VFEZ0060.zdf"],
         "output": "perview.json", "params": {}, "env": "ENV1"},
    ],
    tolerance="0.01")

# producer 가 스스로 print 하는 metric — 독립 측정값이 아니라 자기 주장.
PRODUCER_SELF_REPORT = "metric=0.279"
RECORDED = 0.279


def _make_exec(trace):
    def run_bash(cmd):
        return (PRODUCER_SELF_REPORT, 0)   # producer 가 자기 metric 을 print
    return RebuildExecutor(run_bash=run_bash, emit=trace.append, env_now="ENV1", cid="t9")


# ── 부정 오라클 (defect axis): bug-dead ──────────────────────────────────────────
# [FIXED 2026-06-27] #9 — green regression (rebuild gates 'rebuildable' on measurer_separated; else rebuildable_unverified)
def test_no_measurer_must_not_yield_bare_rebuildable():
    trace = []
    res = _make_exec(trace).run(
        NO_MEASURER_MANI, recorded_metric=RECORDED, cmd_for=lambda s: f"python {s['producer']}")
    # 사전 조건: 독립 measurer 가 실제로 한 번도 분리되지 않았음을 고정(self-report 경로임).
    assert res.measurer_separated is False
    # 올바른(fix 후) 동작: 독립 measurer 가 없으면 bare 'rebuildable' 이면 안 된다.
    # M1(측정자≠생산자) 보증을 못 한 빌드는 'rebuildable' 토큰을 발급할 수 없어야 한다.
    assert res.verdict != "rebuildable", (
        "독립 measurer 없이 producer self-report 만으로 'rebuildable' 발급됨 — M1 위반")


# ── 메커니즘 양성 오라클 (positive axis): 분리 신호 자체는 존재하고 동작함 ──────────────
def test_measurer_separated_flag_distinguishes_independent_measurer():
    # 실제 분리된 measurer(producer 와 다른 명령)가 있으면 measurer_separated=True 가 켜진다 —
    # 신호 메커니즘은 존재한다(버그는 verdict 가 이 신호에 게이트하지 않는 데 있음).
    mani = RebuildManifest(
        final="perview.json",
        roots=[RawRoot("VFEZ0060.zdf", "z0", "ZDF")],
        env_sha="ENV1",
        recipe=[
            {"producer": "334.py", "producer_sha": "s1", "inputs": ["VFEZ0060.zdf"],
             "output": "perview.json", "params": {}, "env": "ENV1"},
            {"producer": "measure.py", "producer_sha": "s2", "inputs": ["perview.json"],
             "output": "metric.txt", "params": {}, "kind": "measurement", "env": "ENV1"},
        ],
        tolerance="0.01")

    def run_bash(cmd):
        # producer 와 measurer 가 서로 다른 명령(서로 다른 producer 파일)
        return (PRODUCER_SELF_REPORT, 0)

    trace = []
    ex = RebuildExecutor(run_bash=run_bash, emit=trace.append, env_now="ENV1", cid="t9b")
    res = ex.run(mani, recorded_metric=RECORDED, cmd_for=lambda s: f"python {s['producer']}")
    assert res.measurer_separated is True
    assert res.verdict == "rebuildable"
