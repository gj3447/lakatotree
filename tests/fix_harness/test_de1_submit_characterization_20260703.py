"""DE1 특성화 골든 — submit_test_result godmethod 에서 추출한 순수 정책의 거동 고정 (측정주권 2026-07-03).

DE1(측정주권 PROM): 344줄 godmethod 의 *판결 결정 seam* 3종을 server.contexts.tree.judgement_policy
로 순수 추출했다. 추출은 *거동 불변*이어야 한다 — 이 파일이 각 함수의 4-사분면/진리표/키집합을 전수
고정(golden)해, AG3/AG4/AG5 가 이 seam 을 확장할 때 회귀를 즉시 잡는다. godmethod 통합 거동은 기존
design_audit_h3/h6/m5 · novel_anchor_freshen · git_absorption_g1 · spine 테스트가 계속 커버(라이브 골든).

  guard_defect    = test_demote_chain_golden_is_exact   (음성: 강등 체인 규칙 변경 시 RED)
  guard_mechanism = test_receipt_fields_match_sealed_set (양성: 조립이 RECEIPT_FIELDS 정본과 1:1)

노드의 novel_script = 이 파일. # KG 거울: LakatosTree_MeasurementSovereignty_20260703 / de1_godmethod_split
"""
from __future__ import annotations

from server.contexts.tree.judgement_policy import (VerdictDecision, apply_verdict_demotes,
                                                   build_receipt_fields, qualitative_flags)
from lakatos.verdicts import RECEIPT_FIELDS


def test_demote_chain_golden_is_exact():
    """apply_verdict_demotes 4-사분면 + precedence 전수 고정(godmethod L686-696 거동)."""
    # 강등 없음: progressive 는 그대로, novel_independent=bool(novel).
    d = apply_verdict_demotes('progressive', 'ok', hc_derived=None, require_novel_anchor=False,
                              novel=True, cross_metric_novel=True, novel_server_anchored=True)
    assert d == VerdictDecision('progressive', 'ok', True)

    # ① hardcore 위반(hc_derived is False) → different_programme, novel_independent 는 bool(novel) 보존.
    d = apply_verdict_demotes('progressive', 'ok', hc_derived=False, require_novel_anchor=True,
                              novel=True, cross_metric_novel=True, novel_server_anchored=False)
    assert d == VerdictDecision('different_programme', 'hard_core_violated_structural', True)
    # hc_derived is False 라도 verdict 가 progressive 밖이면 강등 안 함.
    d = apply_verdict_demotes('partial', 'x', hc_derived=False, require_novel_anchor=False,
                              novel=False, cross_metric_novel=False, novel_server_anchored=False)
    assert d == VerdictDecision('partial', 'x', False)
    # hc_derived None/True 는 hardcore 강등 발화 안 함(레거시 폴백·보존).
    for hc in (None, True):
        d = apply_verdict_demotes('progressive', 'ok', hc_derived=hc, require_novel_anchor=False,
                                  novel=True, cross_metric_novel=False, novel_server_anchored=False)
        assert d.verdict == 'progressive'

    # ② FF1: require_novel_anchor ∧ novel ∧ cross_metric ∧ ¬server_anchored ∧ progressive → partial.
    d = apply_verdict_demotes('progressive', 'ok', hc_derived=None, require_novel_anchor=True,
                              novel=True, cross_metric_novel=True, novel_server_anchored=False)
    assert d == VerdictDecision('partial', 'novel_not_server_anchored', False)
    # FF1 미발화 조건들(각 조건 하나씩 끔) → 강등 없음.
    assert apply_verdict_demotes('progressive', 'ok', hc_derived=None, require_novel_anchor=False,
                                 novel=True, cross_metric_novel=True, novel_server_anchored=False).verdict == 'progressive'
    assert apply_verdict_demotes('progressive', 'ok', hc_derived=None, require_novel_anchor=True,
                                 novel=True, cross_metric_novel=True, novel_server_anchored=True).verdict == 'progressive'
    assert apply_verdict_demotes('progressive', 'ok', hc_derived=None, require_novel_anchor=True,
                                 novel=True, cross_metric_novel=False, novel_server_anchored=False).verdict == 'progressive'

    # precedence: hardcore(①)가 FF1(②)보다 우선 — 둘 다 조건 충족이면 different_programme.
    d = apply_verdict_demotes('progressive', 'ok', hc_derived=False, require_novel_anchor=True,
                              novel=True, cross_metric_novel=True, novel_server_anchored=False)
    assert d.verdict == 'different_programme'

    # progressive_conditional 도 두 게이트의 대상(_PROGRESSIVE 집합).
    d = apply_verdict_demotes('progressive_conditional', 'ok', hc_derived=None, require_novel_anchor=True,
                              novel=True, cross_metric_novel=True, novel_server_anchored=False)
    assert d.verdict == 'partial'

    # AG4 재현성 천장(측정주권 2026-07-03): reproducibility_ceiling(anchored 게이트) ∧ reproducible is False
    #   ∧ progressive → partial(reproducibility_refuted). ★불가 None/True 는 무천장(dead-σ).
    d = apply_verdict_demotes('progressive', 'ok', hc_derived=None, require_novel_anchor=False, novel=False,
                              cross_metric_novel=False, novel_server_anchored=False,
                              reproducible=False, reproducibility_ceiling=True)
    assert d == VerdictDecision('partial', 'reproducibility_refuted', False)
    for repro in (None, True):   # 불가/재현 → 무천장
        assert apply_verdict_demotes('progressive', 'ok', hc_derived=None, require_novel_anchor=False,
                                     novel=False, cross_metric_novel=False, novel_server_anchored=False,
                                     reproducible=repro, reproducibility_ceiling=True).verdict == 'progressive'
    # 게이트 off(비-anchored) → reproducible False 라도 무천장.
    assert apply_verdict_demotes('progressive', 'ok', hc_derived=None, require_novel_anchor=False, novel=False,
                                 cross_metric_novel=False, novel_server_anchored=False,
                                 reproducible=False, reproducibility_ceiling=False).verdict == 'progressive'
    # precedence: hardcore(①) > 재현성천장(②) > FF1(③). 셋 다 조건 충족 → different_programme.
    d = apply_verdict_demotes('progressive', 'ok', hc_derived=False, require_novel_anchor=True, novel=True,
                              cross_metric_novel=True, novel_server_anchored=False,
                              reproducible=False, reproducibility_ceiling=True)
    assert d.verdict == 'different_programme'
    # ② > ③: 재현성천장 ∧ FF1 둘 다 충족 → reproducibility_refuted(② label 우선).
    d = apply_verdict_demotes('progressive', 'ok', hc_derived=None, require_novel_anchor=True, novel=True,
                              cross_metric_novel=True, novel_server_anchored=False,
                              reproducible=False, reproducibility_ceiling=True)
    assert d == VerdictDecision('partial', 'reproducibility_refuted', False)


def test_qualitative_flags_truth_table():
    """qualitative_flags 진리표 고정(godmethod L705-707 거동)."""
    # backed = anchored ∧ ce_corroborated.
    assert qualitative_flags(have_qual=True, verdict='progressive',
                             novel_server_anchored=True, ce_novel_corroborated=True) == (True, False)
    # 질적 주장 있고 progressive 인데 backed 아님 → self_report=True.
    assert qualitative_flags(have_qual=True, verdict='progressive',
                             novel_server_anchored=False, ce_novel_corroborated=True) == (False, True)
    assert qualitative_flags(have_qual=True, verdict='progressive',
                             novel_server_anchored=True, ce_novel_corroborated=False) == (False, True)
    # progressive 밖이면 self_report 표식 안 함(강등된 verdict 은 floor 대상 아님).
    assert qualitative_flags(have_qual=True, verdict='partial',
                             novel_server_anchored=False, ce_novel_corroborated=False) == (False, False)
    # 질적 주장 자체가 없으면 self_report 없음.
    assert qualitative_flags(have_qual=False, verdict='progressive',
                             novel_server_anchored=False, ce_novel_corroborated=False) == (False, False)
    # progressive_conditional 도 대상.
    assert qualitative_flags(have_qual=True, verdict='progressive_conditional',
                             novel_server_anchored=False, ce_novel_corroborated=False) == (False, True)


def test_receipt_fields_match_sealed_set():
    """build_receipt_fields 가 봉인 정본 RECEIPT_FIELDS 와 *정확히 1:1* — AG3 가 한쪽만 확장하면 RED.

    이 golden 이 receipt 조립과 봉인 필드셋의 동기화를 강제한다(내용주소 receipt_sha 무결성의 전제)."""
    fields = build_receipt_fields(
        tree='T', tag='n', target_id='q1', verdict='progressive', metric_name='m',
        metric_value=0.5, novel_confirmed=True, lakatos_status='ok', judged_at='2026-07-03T00:00:00Z',
        judge_script_sha='deadbeef', prev_receipt_sha=None, measurement_grade='client_asserted')  # AG3: 봉인 등급
    assert set(fields.keys()) == set(RECEIPT_FIELDS), (set(fields) ^ set(RECEIPT_FIELDS))
    assert fields['verdict_source'] == 'scripted'   # 스크립트 판결 고정(수동판결 어휘 아님)
    assert fields['metric_value'] == 0.5 and fields['verdict'] == 'progressive'


guard_defect = "test_demote_chain_golden_is_exact"
guard_mechanism = "test_receipt_fields_match_sealed_set"
