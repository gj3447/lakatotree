"""R7-MEASURE — 측정층 정직성 가드 (후속 PROM 2026-07-03).

  guard_defect(음성)     : test_headline_metrics_stop_lying
        — ①eureka 의 closed 가 질문명 *글자수*(len('q_lx3_enabler')=13)로 계산되던 버그 봉합(=1)
          ②무채점 closed_by 의 close 가 close_ratio 1.0 을 떠받치는 왜곡 → close_ratio_receipted 병행
          공시 + 영수증 없는 close 알럿 ③장부부재(closed0∧opened0) felt 가 '실패 사유' hallucinated 로
          뭉개지지 않고 problem_ledger_absent 버킷으로 세분(OmdEngine 7/7 완전체 장르).
  guard_mechanism(양성)  : test_facts_split_without_redefining_truth
        — **true 정의·기존 지표 불변**(사실 세분만 — 지표 마사지 아님): ledger_absent 노드는 여전히
          true 가 아니고, hallucination_rate 헤드라인은 종전 그대로, 기존 close_ratio 도 그대로.
          closed_count 는 seam(judgement 1/0) 의미론과 동형인 단일 정본(G5 단일 프로젝터 장르).

# KG: LakatosTree_GitAbsorption_20260702 / followup-R7-measure
"""
from __future__ import annotations

from lakatos.eureka import _node_to_eureka_input, closed_count, eureka_over_tree
from lakatos.quant.metrics import tree_metrics


def _judged(tag, *, closes='', questions=(), verdict='progressive', source='scripted',
            novel=True, confirmed=True, base=10.0, value=1.0):
    return dict(tag=tag, verdict=verdict, verdict_source=source, node_state='JUDGED_SCRIPTED',
                novel_registered=novel, novel_confirmed=confirmed, source_trust=1.0,
                metric_value=value, pred_baseline=base, pred_noise_band=0.0,
                pred_closes=closes, questions=list(questions), parents=[], parent_edges=[],
                pred_metric='m', judged_at='2026-07-03T00:00:00Z', pred_registered_at='2026-07-02')


# ── guard_defect (음성): 헤드라인 거짓말 3종의 죽음 ────────────────────────────────────────
def test_headline_metrics_stop_lying():
    # (1) 글자수 버그: pred_closes='q_lx3_enabler'(13자) → closed 는 13 이 아니라 1.
    inp = _node_to_eureka_input(_judged('n', closes='q_lx3_enabler'))
    assert inp['closed'] == 1, f"closed={inp['closed']} — 질문명 글자수를 닫은 질문 수로 계산(거짓 수치)"
    assert _node_to_eureka_input(_judged('n', closes=''))['closed'] == 0
    # (2) 무채점 close 왜곡: 13 질문 전부 CLOSED 인데 closed_by 가 미채점(draft) 노드 →
    #     기존 close_ratio 는 1.0 이지만 close_ratio_receipted 는 0.0 + 알럿.
    draft_closer = dict(_judged('closer'), verdict='proof', verdict_source=None,
                        novel_registered=None, novel_confirmed=None)
    frontier = [dict(name=f'q{i}', status='CLOSED', closed_by=['closer'], body='')
                for i in range(13)]
    m = tree_metrics([draft_closer], frontier)
    assert m['frontier']['close_ratio'] == 1.0                     # 기존 지표 불변(비파괴)
    assert m['frontier']['close_ratio_receipted'] == 0.0, \
        f"무채점 close 가 receipted 분자에 삼: {m['frontier']}"
    assert m['frontier']['unreceipted_closes'] == 13
    assert any('영수증 없는 close' in a for a in m['alerts']), m['alerts']
    # (3) 장부부재 세분: 확증+BF substantial 인데 질문 장부가 0/0 인 felt → hallucinated 로 뭉개지지
    #     않고 problem_ledger_absent 버킷 공시(사실 세분 — true 승격은 아님).
    complete_but_no_ledger = _judged('omd', closes='', questions=())
    eu = eureka_over_tree([complete_but_no_ledger])
    assert eu['problem_ledger_absent'] == 1, f"장부부재 버킷 부재: {eu}"
    assert eu['hallucinated_reason_split']['problem_ledger_absent'] == 1


# ── guard_mechanism (양성): 사실 세분이 진실 정의를 건드리지 않는다 ─────────────────────────
def test_facts_split_without_redefining_truth():
    # (1) true 정의 불변: 장부부재 노드는 여전히 true 아님(승격 없음 — 지표 마사지 금지).
    no_ledger = _judged('a', closes='', questions=())
    eu = eureka_over_tree([no_ledger])
    assert eu['true'] == 0 and eu['felt'] == 1
    # 헤드라인 hallucination_rate 는 종전 정의 그대로(felt ∧ ¬true 전부 포함).
    assert eu['hallucinated'] == 1 and eu['hallucination_rate'] == 1.0
    # (2) 진짜 장부(닫은 질문 1, 연 질문 0)를 가진 확증 노드는 true — closed_count 가 이를 가능케 함.
    with_ledger = _judged('b', closes='q-real', questions=())
    eu2 = eureka_over_tree([with_ledger])
    assert eu2['true'] == 1 and eu2['problem_ledger_absent'] == 0
    # (3) closed_count 단일 정본 — seam(1/0) 의미론 동형 + list 는 개수.
    assert closed_count('q-x') == 1 == (1 if 'q-x' else 0)
    assert closed_count('') == 0 == (1 if '' else 0)
    assert closed_count(['a', 'b']) == 2 and closed_count(None) == 0 and closed_count(3) == 3
    # (4) receipted close: scripted-progressive closer 는 분자 포함(기존 close_ratio 와 동행).
    closer = _judged('closer', closes='q0')
    frontier = [dict(name='q0', status='CLOSED', closed_by=['closer'], body=''),
                dict(name='q1', status='OPEN', closed_by=[], body='')]
    m = tree_metrics([closer], frontier)
    assert m['frontier']['close_ratio_receipted'] == 0.5 == m['frontier']['close_ratio']
    assert m['frontier']['unreceipted_closes'] == 0
