"""P3 VAL 읽기경로 가드 (plan-lktadv-p3-val-l3-readpath-20260728).

결함(finding_d286e6ed37a462c1 + 라이브 실측 2026-07-28): 영구 읽기 표면의 실제 천장은 L1 —
normalize_node_row 가 verdict_assurance 를 무-kwargs 로 호출하고 measurement_lock_bound /
engine_rule_sha / tree_attestors / temporal_witness 를 싣지 않아, 라이브 SelfDev 47노드 전부
val<=1 (L1 16 중 measurement_lock_unbound 14), L3 프로브 노드조차 partial@L1 로 되읽혔다.
L3 를 만들 수 있는 곳은 submit 응답 한 곳뿐 = 원장에서 검증 불가능한 등급.

  guard_mechanism : L3 shape 노드가 읽기 경로(normalize_node_row → load_tree_data → standing)
                    전부에서 val==3 으로 재도출된다 — submit 시점과 동형 의미론
                    (lock=bool(sha) / witness=저장 미러 / floor=head receipt 봉인 sha vs effective_floor).
  guard_defect    : 음성 오라클 4종 — witness 죽이면 L2, floor 밖 sealed sha 면 L2, lock sha
                    없으면 L1(measurement_lock_unbound), kwargs 미주입이면 L3 불가(미주입=승급불가
                    의미론 보존, test_extaudit_val:84 계약 유지).
# KG: plan-lktadv-p3-val-l3-readpath-20260728 / finding_d286e6ed37a462c1
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
os.environ.setdefault('NEO4J_USER', 'neo4j')
os.environ.setdefault('NEO4J_PASSWORD', 'test')

from lakatos.engine_identity import ENGINE_RULE_SHA  # noqa: E402
from server.contexts.tree.repository import TreeKgRepository, normalize_node_row  # noqa: E402

WDID = 'did:key:zAttestor1'


def _l3_row(**over):
    """submit 이 SET 하는 실 property shape (judgement_service.py:1170-1186) + head receipt 봉인 sha."""
    row = dict(
        tag='n', verdict='partial', verdict_source='scripted', node_state='measured',
        current_receipt_sha='r' * 64,
        measurement_grade='server_regenerated', replay_status='verified',
        measurement_lock_sha='lock' * 16,
        assurance_tier_resolved='anchored', attested_by_did=WDID,
        temporal_witness_verified=True,
        engine_rule_sha=ENGINE_RULE_SHA,           # head receipt 조인 산출(r.engine_rule_sha)
    )
    row.update(over)
    return row


def _kwargs():
    from lakatos.engine_identity import effective_floor
    return dict(tree_attestors=[WDID], engine_rule_floor=effective_floor())


# ── guard_mechanism: 읽기 재도출로 L3 ─────────────────────────────────────────────────

def test_legacy_t1_only_marker_cannot_rederive_l3():
    out = normalize_node_row(_l3_row(), **_kwargs())
    assert out['assurance']['val'] == 2, out['assurance']


def test_load_tree_data_caps_legacy_t1_only_marker_at_l2():
    """repository 경유(get_tree/metrics/leaderboard 상속 지점) — 트리 attestor·floor 가
    노드 assurance 까지 관통해야. stub kg 는 쿼리 텍스트로 분기(test_delete_tree_surface 관례)."""
    node = _l3_row()

    def kg(query, **params):
        if 'HAS_FRONTIER' in query:
            return []
        if 'ResearchEvent' in query:
            return []
        if 'HAS_NODE' in query:
            return [node]
        return [dict(title='t', note='', hard_core='', positive_heuristic='',
                     coverage_status=None, coverage_statement='', coverage_backlog=[],
                     attestor_dids=[WDID], research_layout=None, layout_owner_did=None,
                     layout_sig=None, witness_dids=[WDID], witness_threshold=1,
                     require_certified_evidence=None, assurance_tier='anchored')]

    data = TreeKgRepository(kg).load_tree_data('T')
    assert data['nodes'][0]['assurance']['val'] == 2, data['nodes'][0]['assurance']


# ── guard_defect: 음성 오라클 — 각 연언을 죽이면 정확히 그 사다리로 떨어진다 ────────────

def test_negative_witness_flip_drops_to_l2():
    out = normalize_node_row(_l3_row(temporal_witness_verified=False), **_kwargs())
    assert out['assurance']['val'] == 2


def test_negative_stale_engine_sha_outside_floor_drops_to_l2():
    """floor 항진 해소의 실체: sealed sha(노드별 가변) vs effective_floor — 구 판관 노드는 L2 천장.
    (현 프로세스 sha 를 항상 넘기면 항진명제가 읽기로 이동할 뿐이다 — finding_d286e6ed37a462c1.)"""
    out = normalize_node_row(_l3_row(engine_rule_sha='deadbeef' * 8), **_kwargs())
    assert out['assurance']['val'] == 2


def test_negative_no_lock_sha_stays_l1_unbound():
    out = normalize_node_row(_l3_row(measurement_lock_sha=None), **_kwargs())
    assert out['assurance']['val'] == 1
    assert 'measurement_lock_unbound' in out['assurance']['basis']


def test_negative_missing_kwargs_cannot_reach_l3():
    """미주입 = 승급 불가 의미론 보존(test_extaudit_val:84 핀과 동일 계약) — 컨텍스트 없이 L3 금지."""
    out = normalize_node_row(_l3_row())
    assert out['assurance']['val'] == 2


def test_handinjected_lock_bound_is_preserved():
    """기존 계약 보존: row 에 measurement_lock_bound 가 이미 있으면 파생이 덮어쓰지 않는다
    (test_extaudit_val_surfaces 손주입 fixture 호환)."""
    out = normalize_node_row(_l3_row(measurement_lock_sha=None, measurement_lock_bound=True),
                             **_kwargs())
    assert out['assurance']['val'] == 2


# ── standing 표면 ─────────────────────────────────────────────────────────────────────

def test_standing_surface_caps_legacy_t1_only_marker_at_l2():
    from server.contexts.tree.evidence_claim_service import EvidenceClaimService
    node = _l3_row()

    def kg(query, **params):
        if 'HAS_ARGUMENT' in query:
            return [dict(node, args=[], attestor_dids=[WDID])]
        return []

    svc = object.__new__(EvidenceClaimService)
    svc.kg = kg
    out = svc.standing('T', 'n')
    assert out['assurance']['val'] == 2, out


def test_standing_negative_oracle_witness_flip():
    from server.contexts.tree.evidence_claim_service import EvidenceClaimService
    node = _l3_row(temporal_witness_verified=False)

    def kg(query, **params):
        if 'HAS_ARGUMENT' in query:
            return [dict(node, args=[], attestor_dids=[WDID])]
        return []

    svc = object.__new__(EvidenceClaimService)
    svc.kg = kg
    out = svc.standing('T', 'n')
    assert out['assurance']['val'] == 2, out
