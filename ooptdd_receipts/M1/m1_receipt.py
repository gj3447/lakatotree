"""OOPTDD emit-adapter — LakatoTree 설계감사 M1(measurer≠producer) 을 *구조화 이벤트 trace*(R02)로 영수증화.

규율(ooptdd): 이벤트 리터럴은 엔진이 아니라 이 adapter 에만(엔진 lakatos/io/rebuild.py 는 불변).
verify 가 실제 RebuildExecutor.run(producer self-report vs 독립 measurer code path 분리) 을 *구동*하고,
관측한 사실을 구조화 이벤트로 ship. Longinus 바인딩(R10): 이 emit site(verify)가 must_emit 이벤트를 낸다.

구동(재구현 금지): tests/test_design_audit_m1.py 의 _build_lying_executor 패턴을 그대로 차용 —
producer step(334.py)이 자기 stdout 에 거짓 metric=999 를 print 해도, kind='measurement' step
(measure_perview.py)이 *완성된 산출물*에서 측정한 참값 0.279 가 measurement 가 된다(measurer≠producer).

음성 오라클(결함이 있었다면 틀릴 케이스): recorded_metric=999.0(=producer 거짓 self-report 값)으로
대조하면 — M1 결함 코드(measurer==producer, 마지막 producer stdout=999 를 measurement 로 씀)였다면
999==999 동어반복으로 'rebuildable' 통과한다. 고쳐진 코드는 독립 measurer 가 0.279 를 측정하므로
'metric_mismatch'(거짓 잡힘)가 돼야 한다. 이 verdict 가 'rebuildable' 이면 결함 회귀 → assert 실패.
# KG: span_lakatotree_design_audit_20260625 / M1
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

# 실제 엔진 모듈을 import 해 구동(재구현 금지).
from lakatos.io.lineage import RebuildManifest, RawRoot  # noqa: E402
from lakatos.io.rebuild import RebuildExecutor            # noqa: E402


# kind='measurement' step: producer 와 분리된 measurer. input=완성된 산출물 파일(perview.json)뿐.
# producer step 보다 *앞*에 둔다 — fixed 코드는 위치(last)가 아니라 kind 로 measurer 를 골라야 한다.
_MEASURE_STEP = {'producer': 'measure_perview.py', 'producer_sha': 'sm',
                 'inputs': ['perview.json'], 'output': 'perview.json',
                 'params': {}, 'env': 'ENV1', 'kind': 'measurement'}

# producer recipe. topo 마지막 = 완성본 producer 334.py — 자기 stdout 에 거짓 metric=999 를 print.
_RECIPE = [
    {'producer': '319.py', 'producer_sha': 's1', 'inputs': ['VFEZ0060.zdf'],
     'output': '_rimobs.npz', 'params': {}, 'env': 'ENV1'},
    {'producer': '334.py', 'producer_sha': 's2', 'inputs': ['_rimobs.npz'],
     'output': 'perview.json', 'params': {}, 'env': 'ENV1'},
]

_MANI = RebuildManifest(
    final='perview.json',
    roots=[RawRoot('VFEZ0060.zdf', 'z0', 'ZDF')],
    env_sha='ENV1',
    # measurement step 을 producer 들보다 앞에 — 위치(last)로 고르면 거짓 999 를 집게 됨.
    recipe=[_MEASURE_STEP] + _RECIPE,
    tolerance='0.01')


def _build_lying_executor():
    """producer 는 거짓 metric=999 를 print; 독립 measurer 만 완성본서 참값 0.279 를 측정.

    run_bash 가 measurer 명령(measure_perview.py)이면 참값, producer 명령이면 거짓 stdout.
    measurer 가 *완성된 산출물 파일*만 보고 측정한다는 걸 명령 문자열로 흉내(테스트 픽스처 동일).
    """
    calls = []

    def run_bash(cmd):
        calls.append(cmd)
        if 'measure_perview.py' in cmd:        # 독립 measurer code path
            return ('metric=0.279', 0)         # 완성본에서 실제 측정한 참값
        if 'perview' in cmd or '334' in cmd:   # producer 가 자기 stdout 에 거짓 보고
            return ('metric=999', 0)
        return ('built', 0)

    ex = RebuildExecutor(run_bash=run_bash, env_now='ENV1', cid='m1-cid')
    return ex, calls


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.M1", "event": name, **attrs}


def verify(backend, cid):
    """M1 구동 — measurement 가 producer self-report(999)에 오염 안 됨을 구조화 이벤트로 증언.

    measurer≠producer 의 구조적 분리를 *실제 엔진*으로 구동하고, positive(참값 0.279 측정) +
    음성 오라클(거짓 999 를 기대값으로 넣어도 독립 measurer 가 잡음)을 ship.
    """
    cmd_for = lambda st: f"python {st['producer']}"  # noqa: E731

    # ① positive: 참값 0.279 로 기대등록 → 독립 measurer 의 측정(0.279)과 일치 → rebuildable.
    ex, calls = _build_lying_executor()
    res = ex.run(_MANI, recorded_metric=0.279, cmd_for=cmd_for)
    # 독립 measurer 명령이 실제로 실행됐다(producer 와 별개 code path 가 측정에 쓰임).
    assert any('measure_perview.py' in c for c in calls), \
        f"독립 measurer step 이 실행되지 않았다 — producer self-report 에 의존 중: {calls}"
    # producer 의 거짓 999 가 아니라 measurer 의 참값 0.279 가 measurement 가 돼야 한다.
    assert res.regenerated_metric == 0.279, \
        f"measurement 가 producer self-report(999)에 오염됨: {res.regenerated_metric}"
    assert res.verdict == 'rebuildable' and res.within_tolerance, \
        f"독립 measurer 측정값이 기대값과 일치하는데도 rebuildable 이 아니다: {res.verdict}"
    backend.ship([_ev(cid, "measurer_separated_from_producer",
                      phase="positive",
                      regenerated_metric=res.regenerated_metric,
                      recorded_metric=res.recorded_metric,
                      verdict=res.verdict,
                      measurer_cmd_ran=True,
                      producer_self_report=999.0)])

    # ② 음성 오라클: 거짓 999(=producer self-report 값)를 기대값으로 넣어도 — 독립 measurer 가
    #    999 가 아니라 0.279 를 측정하므로 거짓이 잡힌다. M1 결함(measurer==producer)이었다면
    #    999==999 동어반복으로 rebuildable 통과 → 아래 assert 가 그 회귀를 거부한다.
    ex2, _ = _build_lying_executor()
    res2 = ex2.run(_MANI, recorded_metric=999.0, cmd_for=cmd_for)
    assert res2.regenerated_metric == 0.279, \
        f"독립 measurer 가 완성본에서 측정한 값(0.279)이 아니라 producer 거짓 stdout 을 신뢰했다: {res2.regenerated_metric}"
    assert res2.verdict == 'metric_mismatch' and not res2.within_tolerance, \
        f"producer 거짓 self-report(999)가 손입력 기대값(999)과 동어반복으로 통과됐다 — M1 결함 회귀: {res2.verdict}"
    backend.ship([_ev(cid, "measurer_separated_from_producer",
                      phase="negative_oracle",
                      regenerated_metric=res2.regenerated_metric,
                      recorded_metric=res2.recorded_metric,
                      verdict=res2.verdict,
                      tautology_rejected=True,
                      producer_self_report=999.0)])
