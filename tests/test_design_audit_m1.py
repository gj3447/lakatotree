"""설계감사 M1 guard — rebuild 의 '외부 측정'이 producer self-report 가 아니라 *별개 measurer* 다.

결함(감사 M1): RebuildExecutor.run 이 `regen=_parse_metric(last_out)` 로 *마지막 producer
step 의 stdout* 에서 metric 을 긁는다(rebuild.py:66-67). 즉 measurer==producer(측정자=생산자).
cli.py 의 단일 `--cmd-template`(기본 `echo metric=0`)는 모든 step 에 같은 template 를 써 recipe
step별 producer 를 무시하고, 비교 대상 recorded_metric 도 손입력 CLI 인자다. 결과:
"rebuildable" 영수증이 "재실행 스크립트가 metric=X 를 print 하고 사람이 넣은 기대값 X 와 같다"는
동어반복이 될 수 있다 — 핵심 약속(measurement≠producer, verdict=외부측정) 위반.

처방(PROM): kind='measurement' Derivation 을 일급으로 두고, rebuild 가 producer step 의 stdout
이 아니라 *완성된 산출물 파일*만 input 으로 받는 별개 측정 step(measurer code path ≠ producer)
에서 metric 을 뽑는다. 기반지식: 재현≠반복 — measurer 가 producer 와 분리돼야 self-report 위조를
잡는다(reproducible-builds/reprotest 변주, Bazel/Nix hermetic: undeclared input=실패).

음성 명세(이 테스트가 인코딩):
  producer 가 거짓 `metric=999` 를 print 해도, 독립 measurer 가 *완성된 산출물*에서 측정한
  참값(또는 KG 사전등록 기대값)과 대조해 거짓을 잡는다 — producer stdout 을 measurement 로
  신뢰하지 않는다.
# KG: span_lakatotree_design_audit_20260625
"""
from lakatos.io.lineage import RebuildManifest, RawRoot
from lakatos.io.rebuild import RebuildExecutor


# kind='measurement' step: producer 와 분리된 measurer. input=완성된 산출물 파일(perview.json)뿐.
# producer step 보다 *앞*에 둔다 — 그래서 fixed 코드는 위치(last)가 아니라 kind 로 measurer 를
# 골라야 한다. (현 결함 코드는 마지막 step 의 stdout=거짓 producer 999 를 measurement 로 쓴다.)
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

MANI = RebuildManifest(
    final='perview.json',
    roots=[RawRoot('VFEZ0060.zdf', 'z0', 'ZDF')],
    env_sha='ENV1',
    # measurement step 을 producer 들보다 앞에 — 위치(last)로 고르면 거짓 999 를 집게 됨.
    recipe=[_MEASURE_STEP] + _RECIPE,
    tolerance='0.01')


def _build_lying_executor(trace):
    """producer 는 거짓 metric=999 를 print; 독립 measurer 만 완성본서 참값 0.279 를 측정.

    run_bash 가 producer 명령이면 거짓 stdout, measurer 명령(measure_perview.py)이면 참값.
    measurer 가 *완성된 산출물 파일*만 보고 측정한다는 걸 명령 문자열로 흉내.
    """
    calls = []

    def run_bash(cmd):
        calls.append(cmd)
        if 'measure_perview.py' in cmd:        # 독립 measurer code path
            return ('metric=0.279', 0)         # 완성본에서 실제 측정한 참값
        if 'perview' in cmd or '334' in cmd:   # producer 가 자기 stdout 에 거짓 보고
            return ('metric=999', 0)
        return ('built', 0)

    def emit(rec):
        trace.append(rec)

    ex = RebuildExecutor(run_bash=run_bash, emit=emit, env_now='ENV1', cid='m1-cid')
    return ex, calls


def test_rebuild_uses_recipe_producers_and_kg_expected():
    """rebuild 가 producer self-report 를 measurement 로 신뢰하지 않는다.

    producer step(334.py)이 자기 stdout 에 거짓 metric=999 를 print 해도, kind='measurement'
    step(measure_perview.py)이 *완성된 산출물*에서 측정한 참값 0.279 가 measurement 가 돼야 한다.
    recorded_metric=0.279(참값)와 대조하면 rebuildable, recorded=999(거짓)와 대조하면 mismatch.

    Frontier(이 테스트가 닫는 것 / 닫지 않는 것):
      - 닫음: measurer ≠ producer 의 구조적 분리(별개 kind='measurement' step, input=완성본,
              별개 code path). producer stdout 은 measurement 로 쓰이지 않는다.
      - 미닫음(상위 frontier): KG 사전등록 기대값 자동조회로 손입력 recorded_metric 까지 제거하는
              것은 server/judgement 경로(금지영역)라 여기선 분리만 검증한다.
    """
    # ① 참값 0.279 로 기대등록 → 독립 measurer 의 측정(0.279)과 일치 → rebuildable
    trace = []
    ex, calls = _build_lying_executor(trace)
    res = ex.run(MANI, recorded_metric=0.279, cmd_for=lambda st: f"python {st['producer']}")
    # measurer 명령이 실제로 실행됐다(producer 와 별개 code path 가 측정에 쓰임)
    assert any('measure_perview.py' in c for c in calls), \
        f"독립 measurer step 이 실행되지 않았다 — producer self-report 에 의존 중: {calls}"
    # producer 의 거짓 999 가 아니라 measurer 의 참값 0.279 가 measurement 가 돼야 한다
    assert res.regenerated_metric == 0.279, \
        f"measurement 가 producer self-report(999)에 오염됨: {res.regenerated_metric}"
    assert res.verdict == 'rebuildable' and res.within_tolerance

    # ② 거짓 999 를 기대값으로 넣어도 — 독립 measurer 가 999 가 아니라 0.279 를 측정하므로 거짓이 잡힌다
    trace2 = []
    ex2, _ = _build_lying_executor(trace2)
    res2 = ex2.run(MANI, recorded_metric=999.0, cmd_for=lambda st: f"python {st['producer']}")
    assert res2.regenerated_metric == 0.279, \
        "독립 measurer 가 완성본에서 측정한 값이 아니라 producer 거짓 stdout 을 신뢰했다"
    assert res2.verdict == 'metric_mismatch' and not res2.within_tolerance, \
        "producer 의 거짓 self-report(999)가 손입력 기대값(999)과 동어반복으로 통과됐다 — M1 결함"
