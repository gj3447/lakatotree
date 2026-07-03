#!/usr/bin/env python3
"""DE1 채점기 — submit_test_result 판결 seam 이 순수 정책으로 추출됐는지 실측 (측정주권 2026-07-03).

측정: server.contexts.tree.judgement_policy 의 3 순수 함수(apply_verdict_demotes / qualitative_flags /
build_receipt_fields)가 (a) import 가능하고 (b) 4-사분면/진리표/키집합 골든을 만족하는지 확인해,
아직 godmethod 에 결합돼 있어 추출 안 된 seam 수를 센다. metric=<미추출 seam 수>(목표 0). exit 0.

self-report 아님: 실제 순수 함수를 호출해 알려진 입력→출력을 대조(거동 실측).
# KG 거울: LakatosTree_MeasurementSovereignty_20260703 / de1_godmethod_split
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def unextracted_seams() -> int:
    missing = 0
    try:
        from server.contexts.tree.judgement_policy import (VerdictDecision, apply_verdict_demotes,
                                                           build_receipt_fields, qualitative_flags)
        from lakatos.verdicts import RECEIPT_FIELDS
    except Exception:
        return 3   # 모듈 미추출 → 3 seam 전부 결합

    # seam1: 강등 체인(hardcore precedence + FF1)
    d1 = apply_verdict_demotes('progressive', 'ok', hc_derived=False, require_novel_anchor=True,
                               novel=True, cross_metric_novel=True, novel_server_anchored=False)
    d2 = apply_verdict_demotes('progressive', 'ok', hc_derived=None, require_novel_anchor=True,
                               novel=True, cross_metric_novel=True, novel_server_anchored=False)
    if not (isinstance(d1, VerdictDecision) and d1.verdict == 'different_programme'
            and d2.verdict == 'partial' and d2.lakatos_status == 'novel_not_server_anchored'):
        missing += 1
    # seam2: 질적 플래그
    if qualitative_flags(have_qual=True, verdict='progressive',
                         novel_server_anchored=False, ce_novel_corroborated=True) != (False, True):
        missing += 1
    # seam3: receipt 조립 == 봉인 필드셋
    f = build_receipt_fields(tree='T', tag='n', target_id='q', verdict='progressive', metric_name='m',
                             metric_value=0.5, novel_confirmed=True, lakatos_status='ok',
                             judged_at='t', judge_script_sha='s', prev_receipt_sha=None)
    if set(f.keys()) != set(RECEIPT_FIELDS) or f['verdict_source'] != 'scripted':
        missing += 1
    return missing


if __name__ == "__main__":
    print(f"metric={unextracted_seams()}")
    sys.exit(0)
