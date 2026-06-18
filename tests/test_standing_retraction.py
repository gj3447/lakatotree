"""certify 자동철회의 *서비스 배선* 검증 — add_critique 가 standing 깨면 CANONICAL 강등 *발화*.

순수 reconcile_standing 은 test_spine.py 가 덮는다. 여기선 evidence_claim_service.add_critique 가
비판 등재 후 grounded standing 을 재계산해 실제로 KG 강등 SET 을 *쏘는지*(felt≠true: 배선이 돈다는
영수증) 를 fake_kg 로 확인한다. certify.py:13 의 선언("새 반박이 G3 깨면 자동 철회")이 코드로 산다.
# KG: span_lakatotree_certify
"""
from server.contexts.tree.evidence_claim_service import EvidenceClaimService
from server.contexts.tree.schemas import CritiqueIn


def _service(node_verdict: str, vur: bool):
    """add_critique 경로만 태우는 최소 서비스 + query-dispatch fake_kg. calls 로 발화 기록."""
    calls: list = []

    def fake_kg(query: str, **params):
        calls.append((query, params))
        if 'MERGE (a:Argument' in query:                      # 비판(공격) 등재
            return []
        if 'coalesce(e.valid_until_rebutted' in query:        # standing 재계산용 노드+args 조회
            # 새 비판 q-doubt 가 노드(tag)를 직접 공격 → verdict 가 막아낼 방어자 없음 → stands=False
            return [{'verdict': node_verdict, 'vur': vur,
                     'args': [{'id': f"{params['tree']}/q-doubt", 'attacks': params['tag']}]}]
        if "SET e.verdict='former_canonical'" in query:       # 강등 발화
            return []
        return []

    svc = EvidenceClaimService(
        kg=fake_kg, hist=lambda *a, **k: None,
        foundation=lambda _n: None, load_lineage=lambda: [],
        reproducible_for_node=lambda _n, _t: None)
    return svc, calls


def _demote_fired(calls) -> bool:
    return any("SET e.verdict='former_canonical'" in q for q, _ in calls)


def test_critique_breaking_standing_demotes_canonical():
    svc, calls = _service('CANONICAL', vur=True)
    out = svc.add_critique('prog', 'cnode', CritiqueIn(arg_id='q-doubt', attacks='cnode', kind='doubt'))
    assert out['standing']['stands'] is False
    assert out['standing']['demoted'] is True
    assert out['standing']['verdict'] == 'former_canonical'
    assert _demote_fired(calls)                      # ★강등 KG SET 이 실제로 쏘였다(영수증)


def test_human_locked_canonical_not_demoted_even_if_standing_breaks():
    # valid_until_rebutted=False = 인간이 반박-자동무효 끔 → standing 깨져도 자동강등 안 함(인간경계)
    svc, calls = _service('CANONICAL', vur=False)
    out = svc.add_critique('prog', 'cnode', CritiqueIn(arg_id='q-doubt', attacks='cnode'))
    assert out['standing']['stands'] is False
    assert out['standing']['demoted'] is False
    assert not _demote_fired(calls)                  # 강등 SET 미발화


def test_non_canonical_node_not_demoted():
    svc, calls = _service('progressive', vur=True)
    out = svc.add_critique('prog', 'cnode', CritiqueIn(arg_id='q-doubt', attacks='cnode'))
    assert out['standing']['demoted'] is False
    assert not _demote_fired(calls)
