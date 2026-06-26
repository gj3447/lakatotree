"""B1-step1 (narrow, non-conflicting): bind_embedded_observation 의 다중 KG write 를 단일 kg_tx 로.

프로젝트의 의도된 비원자성 결정(test_run_cycle_atomicity.py, 2026-06-16: KG=truth/PG=best-effort,
복구=멱등 재실행)은 *cross-service run_cycle* 에 대한 것. 이건 그것과 별개의 좁은 within-method 개선:
한 관측 bind 안의 LOCATED_IN / longinus / rival write 가 부분 실패로 갈라지지 않게 한 트랜잭션으로 묶는다
(submit_test_result 가 이미 쓰는 kg_tx 패턴). kg_tx 미주입 시 self.kg 순차 실행으로 하위호환 보존.
"""
from server.contexts.tree.evidence_claim_service import EvidenceClaimService


class _Emb:
    """bind_embedded_observation 이 호출하는 kg_projection() 만 가진 최소 스텁."""

    def kg_projection(self):
        return {
            'embedding': {'lakatos_location': 'hard_core', 'theoretical_basis': 'tb',
                          'foundation_refs': 'f1,f2'},
            'longinus_refs': [{'sourceId': 's1', 'sourcePath': 'p.py', 'layer': 'io', 'note': 'n'}],
            'rival_links': [],
        }


def _common(**extra):
    return dict(hist=lambda *a, **k: None, foundation=lambda _n: None,
                load_lineage=lambda: [], reproducible_for_node=lambda _n, _t: None, **extra)


def test_bind_embedded_observation_runs_as_single_kg_tx():
    kg_calls, txs = [], []
    svc = EvidenceClaimService(kg=lambda q, **k: kg_calls.append(q) or [],
                               kg_tx=lambda ops: txs.append(ops) or [[]], **_common())
    svc.bind_embedded_observation('T', 'n', 'ev1', _Emb())
    assert len(txs) == 1                                   # 단일 원자 트랜잭션
    cyphers = [c for c, _ in txs[0]]
    assert any('LOCATED_IN' in c for c in cyphers)         # 위치 bind
    assert any('BOUND_BY' in c for c in cyphers)           # longinus bind — 같은 tx
    assert kg_calls == []                                  # kg_tx 경유, 분리 kg() 없음


def test_bind_falls_back_to_kg_without_kg_tx():
    """하위호환: kg_tx 미주입(기존 직접 생성 경로) 시 self.kg 순차 실행."""
    kg_calls = []
    svc = EvidenceClaimService(kg=lambda q, **k: kg_calls.append(q) or [], **_common())
    svc.bind_embedded_observation('T', 'n', 'ev1', _Emb())
    assert any('LOCATED_IN' in q for q in kg_calls)
    assert any('BOUND_BY' in q for q in kg_calls)
