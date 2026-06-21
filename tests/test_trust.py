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
from lakatos.trust import build_trust_graph, global_source_trust, authoritative_url


def test_authoritative_url_matches_real_publisher_host():
    for u in ('https://www.sciencedirect.com/science/article/x', 'https://sciencedirect.com/x',
              'https://datatracker.ietf.org/doc/rfc1', 'https://www.iso.org/standard/1.html'):
        assert authoritative_url(u) is True, u


def test_authoritative_url_rejects_domain_spoofing():
    # ★적대 재검증 2026-06-21: substring 매칭이 뚫리던 스푸핑 벡터 — host 경계로 전부 차단
    for u in ('https://www.sciencedirect.com.attacker.com/x',   # suffix 부착
              'https://evil.com/?ref=ietf.org',                  # query 삽입
              'https://attacker.com/iso.org/paper',              # path 삽입
              'https://ietf.org.evil.io/rfc',                    # 도메인 접두 + 다른 TLD
              'https://notsciencedirect.com/x'):                 # 접두 결합(. 경계 없음)
        assert authoritative_url(u) is False, u


def test_build_graph_seeds_from_authoritative_url_domain():
    # 기본(서버검증): seed 는 URL 도메인으로 — client source_type 라벨은 seed 통제 못 함
    local, pre = build_trust_graph([
        {'source': 'https://www.sciencedirect.com/x', 'url': 'https://www.sciencedirect.com/x',
         'source_type': 'blog', 'node': 'v1'},   # 라벨은 blog 라도 권위 도메인 → seed
        {'source': 'blog_x', 'url': 'https://blog.example/y', 'source_type': 'peer_reviewed', 'node': 'v1'},
    ])  # 비권위 도메인 + peer_reviewed *라벨* → seed 아님(forge 봉쇄)
    assert 'https://www.sciencedirect.com/x' in pre and 'blog_x' not in pre


def test_forged_label_without_authoritative_url_is_not_seeded_by_default():
    # ★R3 봉쇄: peer_reviewed 라벨 자기선언만으론(권위 URL 없이) 기본 모드에서 seed 안 됨
    _local, pre = build_trust_graph([{'source': 'fake', 'source_type': 'peer_reviewed', 'node': 'v1'}])
    assert pre == {}


def test_label_seeding_requires_explicit_opt_in():
    # 신뢰된 구조/문헌 앵커(URL 없는 textbook 인용)는 trust_source_type_label=True 로 *명시 opt-in* 시에만
    local, pre = build_trust_graph([
        {'source': 'jeffreys1961', 'source_type': 'literature', 'node': 'v1'},
        {'source': 'blog_x', 'source_type': 'blog', 'node': 'v1'},
    ], trust_source_type_label=True)
    assert 'jeffreys1961' in pre and 'blog_x' not in pre   # opt-in 하면 권위 라벨만 seed
    assert local['jeffreys1961'].get('blog_x', 0) > 0      # 같은 노드 co-support edge


def test_global_trust_authority_beats_blog():
    obs = [
        {'source': 'jeffreys1961', 'source_type': 'literature', 'node': 'v1', 'corroboration_score': 0.9},
        {'source': 'blog_x', 'source_type': 'blog', 'node': 'v1', 'corroboration_score': 0.4},
    ]
    r = global_source_trust(obs, trust_source_type_label=True)   # 문헌 앵커 opt-in
    assert r['trust']['jeffreys1961'] > r['trust']['blog_x']   # 문헌 앵커 > 블로그
    assert r['coverage']['mode'] == 'graph_propagated'
    assert r['coverage']['seed_basis'] == 'source_type_label'   # 정직: 라벨 opt-in 표기


def test_global_trust_honest_coverage_labels():
    # edge 없으면 seed_dominated (정직 — 고유벡터 heavy-lifting 아님); 기본 seed_basis=url_domain
    r = global_source_trust([{'source': 'a', 'source_type': 'primary', 'node': 'n1'}],
                            trust_source_type_label=True)
    assert r['coverage']['mode'] == 'seed_dominated'
    assert global_source_trust([{'source': 'a', 'source_type': 'primary', 'node': 'n1'}]
                               )['coverage']['seed_basis'] == 'url_domain'
    # 관측 0 → uniform_unlearned
    assert global_source_trust([])['coverage']['mode'] == 'uniform_unlearned'
