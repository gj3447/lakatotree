"""P3 VAL 읽기경로 영수증 — L3 가 영구 읽기 표면에서 재도출됨을 실코드로 증언.

규율(ooptdd): 이벤트 리터럴은 엔진이 아니라 이 adapter 에만(엔진 repository/evidence_claim_service
불변). 재구현 금지 — tests/test_p3_val_readpath_20260728.py 의 픽스처/호출을 그대로 차용한다.

음성 오라클(no-fake-green): 수술 전 코드(무-kwargs verdict_assurance)였다면 양성 이벤트 두 개의
assert(val==3)가 깨진다 — 라이브 실측(2026-07-28)이 그 상태였다(SelfDev 47노드 전부 val<=1,
L3 프로브 partial@L1). 또한 판별 오라클(연언별 강등)이 하나라도 L3 로 새면 이 영수증이 틀린다.
# KG: plan-lktadv-p3-val-l3-readpath-20260728 / finding_d286e6ed37a462c1
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

import os  # noqa: E402
os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
os.environ.setdefault('NEO4J_USER', 'neo4j')
os.environ.setdefault('NEO4J_PASSWORD', 'test')

from lakatos.engine_identity import ENGINE_RULE_SHA, effective_floor  # noqa: E402
from server.contexts.tree.repository import TreeKgRepository, normalize_node_row  # noqa: E402

WDID = 'did:key:zReceiptAttestor'


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.val.p3_readpath", "event": name, **attrs}


def _l3_row(**over):
    row = dict(
        tag='n', verdict='partial', verdict_source='scripted', node_state='measured',
        current_receipt_sha='r' * 64,
        measurement_grade='server_regenerated', replay_status='verified',
        measurement_lock_sha='lock' * 16,
        assurance_tier_resolved='anchored', attested_by_did=WDID,
        temporal_witness_verified=True,
        engine_rule_sha=ENGINE_RULE_SHA,
    )
    row.update(over)
    return row


def _tree_kg(node):
    def kg(query, **params):
        if 'HAS_FRONTIER' in query or 'ResearchEvent' in query:
            return []
        if 'HAS_NODE' in query:
            return [node]
        return [dict(title='t', note='', hard_core='', positive_heuristic='',
                     coverage_status=None, coverage_statement='', coverage_backlog=[],
                     attestor_dids=[WDID], research_layout=None, layout_owner_did=None,
                     layout_sig=None, witness_dids=[WDID], witness_threshold=1,
                     require_certified_evidence=None, assurance_tier='anchored')]
    return kg


def verify(backend, cid):
    """읽기 표면 L3 재도출 구동 — repository/standing 양성 + 연언별 판별 음성."""
    # (1) repository 경유 — get_tree/metrics/leaderboard 가 상속하는 유일 정본 경로.
    data = TreeKgRepository(_tree_kg(_l3_row())).load_tree_data('T')
    a = data['nodes'][0]['assurance']
    disp = data['nodes'][0]['verdict_display']
    assert a['val'] == 3, f"repository 읽기서 L3 미달(수술 전 결함 잔존): {a}"
    assert disp.startswith('partial@L3(attested_witnessed'), disp
    backend.ship([_ev(cid, "l3_rederived_on_repository_read", val=a['val'],
                      verdict_display=disp)])

    # (2) standing 표면 — 별도 좁은 쿼리 경로.
    from server.contexts.tree.evidence_claim_service import EvidenceClaimService
    node = _l3_row()
    svc = object.__new__(EvidenceClaimService)
    svc.kg = lambda q, **p: ([dict(node, args=[], attestor_dids=[WDID])]
                             if 'HAS_ARGUMENT' in q else [])
    st = svc.standing('T', 'n')
    assert st['assurance']['val'] == 3, f"standing 표면서 L3 미달: {st['assurance']}"
    backend.ship([_ev(cid, "l3_rederived_on_standing_surface", val=st['assurance']['val'],
                      verdict=st['verdict'])])

    # (3) 판별 음성 오라클 — 연언 하나씩 죽이면 정확히 그 사다리로 떨어져야 한다.
    kw = dict(tree_attestors=[WDID], engine_rule_floor=effective_floor())
    drops = {
        'witness_flip': normalize_node_row(
            _l3_row(temporal_witness_verified=False), **kw)['assurance']['val'],
        'stale_engine_sha': normalize_node_row(
            _l3_row(engine_rule_sha='deadbeef' * 8), **kw)['assurance']['val'],
        'no_lock': normalize_node_row(
            _l3_row(measurement_lock_sha=None), **kw)['assurance']['val'],
        'no_context': normalize_node_row(_l3_row())['assurance']['val'],
    }
    expect = {'witness_flip': 2, 'stale_engine_sha': 2, 'no_lock': 1, 'no_context': 2}
    assert drops == expect, f"판별 실패(어딘가 L3 로 샘 = fake-green): {drops} != {expect}"
    backend.ship([_ev(cid, "negative_oracles_discriminate", **drops)])
