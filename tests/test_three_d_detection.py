"""Dogfood 회귀 가드 — BPC·SX3i·LX3 가 분리 트리가 아니라 한 그루의 나무인가.

사용자 요구: "셋다 완전 따로가 아니다 — 공통점이 있고, 나무처럼 BPC 기반에서
SX3i·LX3 가 피어난다." 이 테스트가 그 통합 구조를 핀으로 고정한다.
"""
from examples.three_d_detection import run, UNIFIED_NODES, HARD_CORE


def test_single_connected_tree_one_root():
    out = run()
    # 분리된 3 트리가 아니라 한 그루 — root 가 정확히 하나(BPC prob_statement)
    assert out['roots'] == ['prob_statement']


def test_both_blooms_attach_to_bpc_trunk():
    out = run()
    tags = {n['tag'] for n in UNIFIED_NODES}
    # 줄기 마디가 통합 노드에 존재하고, 두 가지가 거기에 접붙음
    assert {'v8_pipeline', 'aruco_metric'} <= tags
    assert out['blooms'] == {'sx3i': 'v8_pipeline', 'lx3': 'aruco_metric'}
    # SX3i·LX3 가지 노드가 통합 트리에 실제로 합류
    assert {'sx3i_prob', 'lx3_prob'} <= tags


def test_unified_canonical_is_bpc_v8():
    out = run()
    # 통합 트리의 유일한 공차이하 확증 마디 = BPC v8 (SX3i 미측정·LX3 자동경로 ceiling)
    assert out['canonical'] == 'v8_pipeline'


def test_three_share_hard_core():
    out = run()
    # 세 부품 공유 hard core 3개 (정합 필수 / free-ICP collapse / precision≠accuracy)
    assert len(HARD_CORE) == 3
    assert any('collapse' in h for h in HARD_CORE)
    assert any('precision' in h for h in HARD_CORE)
