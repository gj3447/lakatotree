"""인터넷 출처 신뢰 TDD — TrustRank(시드전파)+EigenTrust(고유벡터).
# KG: span_lakatotree_trust
"""
from lakatos.trust import trustrank, eigentrust, evidence_weight

def test_trustrank_seed_propagates():
    # 시드(신뢰 페이지)에서 아웃링크로 신뢰 전파, 시드가 최고
    g = {'a': ['b'], 'b': ['c'], 'c': []}
    tr = trustrank(g, seeds={'a': 1.0})
    assert tr['a'] > tr['b'] > tr['c'] > 0

def test_trustrank_unreachable_low():
    g = {'a': ['b'], 'b': [], 'spam': []}   # spam 은 시드서 도달 불가
    tr = trustrank(g, seeds={'a': 1.0})
    assert tr['spam'] < tr['a']

def test_eigentrust_converges_to_authority():
    # 모두가 신뢰하는 노드가 최고 글로벌 신뢰 (전이적 신뢰)
    local = {'a': {'c': 1.0}, 'b': {'c': 1.0}, 'c': {'a': 0.5, 'b': 0.5}}
    gt = eigentrust(local, pre_trusted={'a': 0.5, 'b': 0.5})
    assert gt['c'] == max(gt.values())
    assert abs(sum(gt.values()) - 1.0) < 1e-6   # 정규화

def test_evidence_weight_monotone():
    # 높은 출처신뢰 = 높은 증거가중 (베이즈 결합용)
    assert evidence_weight(0.9) > evidence_weight(0.3) > 0
    assert evidence_weight(0.0) >= 0


def test_eigentrust_dangling_redistribution():   # 나생문 F-MATH-3
    # dangling 노드 D 의 사전신뢰가 사라지지 않고 pre-trusted 로 재분배되는가
    import math
    local = {'a': {'b': 1.0}, 'b': {'a': 1.0}, 'd': {}}   # d = dangling
    gt = eigentrust(local, pre_trusted={'a': 0.5, 'b': 0.5})
    assert abs(sum(gt.values()) - 1.0) < 1e-6   # 질량 보존
    assert all(v >= 0 for v in gt.values())
