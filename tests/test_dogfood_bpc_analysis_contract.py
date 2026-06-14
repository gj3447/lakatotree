"""Dogfood 회귀 가드 — 엔진이 BPC analysis-contract(측정·운반·DT) 프로그램에서 옳은 결론을 내는가.

examples/bpc_analysis_contract_programme.py(실 작업사: W3 merged 운반/운반 3-way 수렴/
#1~#16 contract 산출/XC forced-NG/W5 DT 렌더 전종/Windows 133 pytest green/monolithic 폐기)를
구동해 엔진 판정을 핀으로 고정. bpc_icp_programme(정합 scope)와 별개 tree(measurement scope).
"""
from examples.bpc_analysis_contract_programme import run, NODES, FRONTIER
from lakatos.metrics import tree_metrics


def test_dogfood_runs_and_concludes_sensibly():
    out = run()
    m = out['metrics']
    assert m['canonical'] == 'dt_render'                            # 정본 = DT 렌더 통합
    assert m['progress']['improvement_pct'] == 800.0               # 1→9 output 누적 진보
    assert m['progress']['scope'] == 'measurement'                 # 정합(registration)과 다른 축
    assert out['stack'] == 'retain' and out['lifecycle'] == 'active'   # 정본 가지 생존
    assert out['rival_stack'] == 'abandon'                        # monolithic/tight-coupling 폐기 합의


def test_dogfood_canonical_path_high_credence_novel_confirmed():
    m = run()['metrics']
    assert m['bayes']['canonical_credence'] >= 0.9                 # 정본경로 강함(novel 전부 확증)
    assert m['bayes']['low_credence_branches'] == []              # 저신뢰 가지 없음(정본 직선)


def test_dogfood_leaderboard_ranks_hexagonal_over_monolithic():
    out = run()
    rows = {r['name']: r for r in out['leaderboard']['rows']}
    assert out['leaderboard']['pareto_front'] == ['hexagonal_contract']
    assert rows['hexagonal_contract']['borda'] > rows['monolithic_coupled']['borda']
    assert rows['hexagonal_contract']['credence'] > rows['monolithic_coupled']['credence']


def test_dogfood_canonical_not_certified_w4_open_and_uncalibrated():
    out = run()
    assert out['certified'] is False                              # ★ 정직: W4 OPEN + credence 보정 부재
    assert set(out['missing']) == {'stands', 'calibrated'}        # stands=W4 미해소 / calibrated=Brier 이력 부재


def test_dogfood_frontier_open_questions_are_real_remaining_work():
    # OPEN frontier = 실제 잔여(블록/연기) 작업과 일치 — 가짜 green 아님
    open_q = {f['name'] for f in FRONTIER if f['status'] == 'OPEN'}
    assert {'q_flight_consumer', 'q_w2prod', 'q_seg', 'q_label_weight'} <= open_q
    closed_q = {f['name'] for f in FRONTIER if f['status'] == 'CLOSED'}
    assert {'q_transport_map', 'q_tab_seat'} <= closed_q          # 운반 수렴 + TAB 3층 = 완료
