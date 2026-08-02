"""FSM 감사 결함 수리 가드 (PROM16 검증 팬아웃 2026-07-28, DEFECT 3건).

  D1 강등 세탁 : submit_test_result 의 before-상태 재유도가 verdict 필드를 누락해
                 FORMER_CANONICAL/REJECTED(engine·human·reproducible source) 노드가
                 JUDGED_SCRIPTED 로 오판정 → 불법 재채점이 FSM 을 침묵 통과했다.
  D2 클로버    : writer 의 first-write-wins 가드가 'admin'(=CANONICAL 승격 source)을
                 제외해 CANONICAL 노드를 add_node 재호출로 DRAFT/proof 로 덮어썼다.
  D3 상태 드리프트: agm_revise 강등이 node_state 를 갱신하지 않아 영속 'CANONICAL' ∧
                 verdict 'former_canonical' 이 영구 공존했다(fsck 검사도 없었다).

각 항목은 결함 재현(수리 전이면 RED)과 정상 경로 무회귀(과잉 차단 금지)를 쌍으로 건다.
# KG: prom16-lakatotree-advancement-20260728 / FSM audit
"""
from __future__ import annotations

import os

os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
os.environ.setdefault('NEO4J_USER', 'neo4j')
os.environ.setdefault('NEO4J_PASSWORD', 'test')

from lakatos.node_state import NodeState, derive_node_state, transition_allowed  # noqa: E402
from lakatos.verdicts import FORCEFUL_SOURCES  # noqa: E402


# ── D1: 강등 세탁 — before-상태는 verdict 를 포함한 전체 row 에서 파생돼야 ──────────────

def _former_canonical_row():
    return dict(tag='n', verdict='former_canonical', verdict_source='engine',
                pred_registered_at='2026-07-01', pred_metric='m',
                metric_value=1.0, judged_at='2026-07-02')


def test_former_canonical_before_state_is_not_judged_scripted():
    """결함 재현축: verdict 를 뺀 부분 row 는 JUDGED_SCRIPTED 로 오판정된다 —
    전체 row 파생은 FORMER_CANONICAL 이고, 그 전이는 불법이어야 한다."""
    full = derive_node_state(_former_canonical_row())
    assert full == NodeState.FORMER_CANONICAL, full
    assert not transition_allowed(full, NodeState.JUDGED_SCRIPTED), \
        'FORMER_CANONICAL→JUDGED_SCRIPTED 는 강등 세탁 — 전이표상 불법이어야'
    partial = derive_node_state({k: v for k, v in _former_canonical_row().items()
                                 if k != 'verdict'})
    assert partial == NodeState.JUDGED_SCRIPTED, '부분 row 오판정(수리 대상 재현)'


def test_submit_before_row_carries_verdict():
    """수리: submit 이 조립하는 before-row 에 existing_verdict 가 실려야 한다
    (읽기 쿼리는 이미 e.verdict AS existing_verdict 를 반환 중 — 소비만 빠져 있었다)."""
    import inspect
    from server.contexts.tree import judgement_service as js
    src = inspect.getsource(js.JudgementService.submit_test_result)
    assert "'verdict': pr.get('existing_verdict')" in src or \
           '"verdict": pr.get("existing_verdict")' in src, \
        'before-row 에 verdict 미포함 = 강등 세탁 경로 잔존'


def test_rescore_gate_uses_normalized_forceful_membership():
    """재채점 409 게이트가 raw =='scripted' 가 아니라 FORCEFUL 멤버십이어야 —
    engine/human/reproducible 판정 노드의 재제출도 막힌다."""
    import inspect
    from server.contexts.tree import judgement_service as js
    src = inspect.getsource(js.JudgementService.submit_test_result)
    assert 'FORCEFUL_SOURCES' in src, '재채점 게이트가 scripted 만 봄(engine 강등 세탁 통과)'
    assert {'scripted', 'engine', 'human', 'reproducible'} <= set(FORCEFUL_SOURCES)


# ── D2: writer first-write-wins 가 admin(CANONICAL) 도 보존해야 ────────────────────────

def test_writer_preserve_set_includes_admin_source():
    """CANONICAL 승격은 verdict_source='admin' 을 SET 하는데 보존 집합이 FORCEFUL 뿐이라
    add_node 재호출이 CANONICAL 을 proof/DRAFT 로 침묵 클로버했다."""
    from server.contexts.tree.writer import _FORCEFUL
    assert 'admin' in _FORCEFUL, 'admin(CANONICAL 승격 source) 미보호 — 클로버 구멍'
    assert set(FORCEFUL_SOURCES) <= set(_FORCEFUL), 'FORCEFUL 보존 계약 유지(과잉 축소 금지)'


def test_writer_preserve_query_uses_preserve_set():
    import inspect
    from server.contexts.tree import writer as w
    src = inspect.getsource(w)
    assert '_PRESERVE_IF_SCORED' in src and src.count('_PRESERVE_IF_SCORED') >= 2, \
        '가드 상수가 쿼리에서 실제 소비돼야'


# ── D3: AGM 강등이 node_state 도 갱신해야 ─────────────────────────────────────────────

def test_agm_demote_sets_node_state_only_in_receipt_bound_path():
    """AGM 강등은 receipt-bound per-tag CAS 하나만 유지한다.

    예전 blanket fallback은 영수증 없이 forceful head를 만드는 우회였다.
    남은 유일 경로가 verdict·node_state·receipt pointer를 함께 갱신함을 고정한다.
    """
    import inspect
    from server import app as app_mod
    src = inspect.getsource(app_mod._persist_revision)
    demote_blocks = [b for b in src.split('ops.append') if "SET e.verdict='former_canonical'" in b]
    assert len(demote_blocks) == 1, f'receipt-bound AGM 강등 op 1개 기대, 실제 {len(demote_blocks)}'
    block = demote_blocks[0]
    assert "e.node_state='FORMER_CANONICAL'" in block
    assert 'MERGE (rec:VerdictReceipt' in block
    assert 'SET e.current_receipt_sha=$rsha' in block


def test_fsck_has_node_state_drift_check():
    """영속 node_state 와 파생 상태의 드리프트를 fsck 가 검출해야(종전 검사 0건)."""
    from server.contexts.audit import fsck
    src = open(fsck.__file__, encoding='utf-8').read()
    assert 'NODE_STATE_DRIFT' in src, 'fsck 에 node_state 정합성 검사 부재'


def test_fsck_node_state_drift_fires_and_is_silent_when_aligned():
    """음성 오라클: 정렬된 노드에선 무발화(과잉 경보 금지), 드리프트에선 발화."""
    from server.contexts.audit.fsck import fsck_node
    drifted = dict(tag='n', verdict='former_canonical', verdict_source='engine',
                   node_state='CANONICAL', judged_at='2026-07-02', metric_value=1.0,
                   pred_registered_at='2026-07-01', pred_metric='m')
    codes = [f.check_id for f in fsck_node(drifted)]
    assert 'NODE_STATE_DRIFT' in codes, codes
    aligned = dict(drifted, node_state='FORMER_CANONICAL')
    assert 'NODE_STATE_DRIFT' not in [f.check_id for f in fsck_node(aligned)]
