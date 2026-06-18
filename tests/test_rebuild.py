"""재빌드 자동실행 TDD(LTDD) — 매니페스트→하네스로 ZDF서 완성본 실제 재생성.
기대 trace 스펙(LTDD Red): rebuild_start → env_check → step_exec×N → metric_compare → rebuild_verdict
# KG: span_lakatotree_rebuild
"""
from lakatos.io.lineage import RebuildManifest, RawRoot
from lakatos.io.rebuild import RebuildExecutor, RebuildResult

MANI = RebuildManifest(
    final='perview.json',
    roots=[RawRoot('VFEZ0060.zdf', 'z0', 'ZDF')],
    env_sha='ENV1',
    recipe=[
        {'producer': '319.py', 'producer_sha': 's1', 'inputs': ['VFEZ0060.zdf'],
         'output': '_rimobs.npz', 'params': {}, 'env': 'ENV1'},
        {'producer': '334.py', 'producer_sha': 's2', 'inputs': ['_rimobs.npz'],
         'output': 'perview.json', 'params': {}, 'env': 'ENV1'},
    ],
    tolerance='0.01')

def make_exec(exit_codes=(0, 0), final_metric='metric=0.279', recorded=0.279, env='ENV1', trace=None):
    trace = trace if trace is not None else []
    calls = []
    def run_bash(cmd):
        calls.append(cmd)
        i = len([c for c in calls]) - 1
        if 'perview' in cmd or '334' in cmd:
            return (final_metric, exit_codes[1])
        return ('built', exit_codes[0])
    def emit(rec): trace.append(rec)
    ex = RebuildExecutor(run_bash=run_bash, emit=emit, env_now=env, cid='test-cid')
    return ex, calls, trace

def test_rebuild_trace_sequence():   # LTDD: 기대 이벤트 시퀀스
    ex, calls, trace = make_exec()
    res = ex.run(MANI, recorded_metric=0.279, cmd_for=lambda step: f"python {step['producer']}")
    events = [r['event'] for r in trace]
    assert events == ['rebuild_start', 'env_check', 'step_exec', 'step_exec',
                      'metric_compare', 'rebuild_verdict']
    assert all(r['cid'] == 'test-cid' for r in trace)   # correlation_id 전파

def test_rebuild_regenerates_from_roots_ignoring_buffers():
    ex, calls, trace = make_exec()
    res = ex.run(MANI, recorded_metric=0.279, cmd_for=lambda s: f"run {s['producer']}")
    assert len(calls) == 2   # 버퍼 무시하고 recipe 2단계 전부 재실행
    assert res.verdict == 'rebuildable' and res.within_tolerance

def test_metric_mismatch_fails():
    ex, calls, trace = make_exec(final_metric='metric=0.9')   # 재생성 결과 다름
    res = ex.run(MANI, recorded_metric=0.279, cmd_for=lambda s: 'x')
    assert res.verdict == 'metric_mismatch' and not res.within_tolerance

def test_env_drift_blocks():
    ex, calls, trace = make_exec(env='ENV2_DIFFERENT')
    res = ex.run(MANI, recorded_metric=0.279, cmd_for=lambda s: 'x')
    assert res.verdict == 'env_drift'
    assert not any('step_exec' == r['event'] for r in trace)  # env 안 맞으면 실행 안 함

def test_step_failure_aborts():
    ex, calls, trace = make_exec(exit_codes=(1, 0))   # 첫 단계 실패
    res = ex.run(MANI, recorded_metric=0.279, cmd_for=lambda s: 'x')
    assert res.verdict == 'step_failed'
