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


# ── P6 배선: 실 observation 그래프 → 글로벌 출처신뢰 (eigentrust 런타임 배선) ──
from lakatos.trust import build_trust_graph, global_source_trust


def test_build_graph_seeds_from_authoritative_types():
    local, pre = build_trust_graph([
        {'source': 'jeffreys1961', 'source_type': 'literature', 'node': 'v1'},
        {'source': 'blog_x', 'source_type': 'blog', 'node': 'v1'},
    ])
    assert 'jeffreys1961' in pre and 'blog_x' not in pre   # 권위 source_type 만 seed
    # 같은 노드 v1 받친 두 관측 → corroboration edge
    assert local['jeffreys1961'].get('blog_x', 0) > 0


def test_global_trust_authority_beats_blog():
    obs = [
        {'source': 'jeffreys1961', 'source_type': 'literature', 'node': 'v1', 'corroboration_score': 0.9},
        {'source': 'blog_x', 'source_type': 'blog', 'node': 'v1', 'corroboration_score': 0.4},
    ]
    r = global_source_trust(obs)
    assert r['trust']['jeffreys1961'] > r['trust']['blog_x']   # 문헌 앵커 > 블로그
    assert r['coverage']['mode'] == 'graph_propagated'


def test_global_trust_honest_coverage_labels():
    # edge 없으면 seed_dominated (정직 — 고유벡터 heavy-lifting 아님)
    assert global_source_trust(
        [{'source': 'a', 'source_type': 'primary', 'node': 'n1'}]
    )['coverage']['mode'] == 'seed_dominated'
    # 관측 0 → uniform_unlearned
    assert global_source_trust([])['coverage']['mode'] == 'uniform_unlearned'
