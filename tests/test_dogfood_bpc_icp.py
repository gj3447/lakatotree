"""Dogfood 회귀 가드 — 엔진이 실제 BPC/ICP 연구 프로그램에서 옳은 결론을 내는가.

examples/bpc_icp_programme.py(실 연구사: ArUco metric/frozen calib/v8 0.90mm/6-DOF 퇴행/CPD 기각)를
구동해 엔진 판정을 핀으로 고정. 합성 audit 이 못 찾는 실데이터 회귀를 차단.
+ dogfood 가 발견한 progress.scope 미공개 갭 수정 검증.
"""
from examples.bpc_icp_programme import run, NODES, FRONTIER
from lakatos.metrics import tree_metrics


def test_dogfood_runs_and_concludes_sensibly():
    out = run()
    m = out['metrics']
    assert m['canonical'] == 'v8_pipeline'                          # 정본 식별
    assert m['progress']['improvement_pct'] == 43.8                 # 1.6→0.9 진보
    assert m['max_degeneration_depth'] == 3                         # 6-DOF 3연속 퇴행
    assert out['stack'] == 'retain' and out['lifecycle'] == 'active'    # 정본 가지 생존
    assert out['rival_stack'] == 'abandon'                         # 6-DOF 퇴행 가지 폐기 합의


def test_dogfood_canonical_path_high_credence_degenerate_low():
    m = run()['metrics']
    assert m['bayes']['canonical_credence'] >= 0.9                  # 정본경로 강함
    low = {b['leaf'] for b in m['bayes']['low_credence_branches']}
    assert 'pv6dof_c' in low                                        # 6-DOF 가지 저신뢰


def test_dogfood_leaderboard_ranks_classical_over_learning():
    out = run()
    rows = {r['name']: r for r in out['leaderboard']['rows']}
    assert out['leaderboard']['pareto_front'] == ['classical_halcon']
    assert rows['classical_halcon']['borda'] > rows['learning_6dpose']['borda']
    assert rows['classical_halcon']['credence'] > rows['learning_6dpose']['credence']


def test_dogfood_canonical_not_certified_missing_repro_calib():
    out = run()
    assert out['certified'] is False                               # v8 은 manifest/calib 없음 — 정직
    assert set(out['missing']) == {'reproducible', 'calibrated'}


def test_progress_discloses_scope():   # ★dogfood 발견 갭: 진보율이 어느 scope 인지 미공개였음
    m = tree_metrics(NODES, FRONTIER)
    assert m['progress']['scope'] == 'registration'
