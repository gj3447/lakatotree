"""Occam step 5 backfill 분류 — pre_receipt(무영수증) vs needs_reverify(영수증필드 보유) vs already_sourced.
정직: 영수증 *필드가 있는* NULL-source 노드는 pre_receipt 로 찍지 않는다(실 source 는 재실행으로만).
# KG: span_lakatotree_verdict_registry
"""
from lakatos.provenance_backfill import classify_unreceipted


def test_null_source_receiptless_progress_is_pre_receipt():
    rows = [{'tag': 'a', 'verdict': 'progressive', 'verdict_source': None},
            {'tag': 'b', 'verdict': 'CANONICAL', 'verdict_source': None, 'n_research': 0}]
    out = classify_unreceipted(rows)
    assert set(out['pre_receipt']) == {'a', 'b'} and out['needs_reverify'] == [] and out['already_sourced'] == []


def test_null_source_with_receipt_fields_needs_reverify_not_stamped():
    # baseline/measured 또는 연구이벤트가 있으면 실 source 는 재실행으로만 — pre_receipt 로 위조 금지
    rows = [{'tag': 'm', 'verdict': 'progressive', 'verdict_source': None, 'baseline': 1.0, 'measured': 0.5},
            {'tag': 'r', 'verdict': 'CANONICAL', 'verdict_source': None, 'n_research': 2}]
    out = classify_unreceipted(rows)
    assert set(out['needs_reverify']) == {'m', 'r'} and out['pre_receipt'] == []


def test_real_source_and_existing_marker_are_left_alone_idempotent():
    rows = [{'tag': 'scripted', 'verdict': 'progressive', 'verdict_source': 'scripted'},   # 실 영수증
            {'tag': 'already', 'verdict': 'CANONICAL', 'verdict_source': 'pre_receipt'}]     # 이미 마커
    out = classify_unreceipted(rows)
    assert set(out['already_sourced']) == {'scripted', 'already'} and out['pre_receipt'] == []


def test_non_progress_verdicts_ignored():
    rows = [{'tag': 'x', 'verdict': 'rejected', 'verdict_source': None},
            {'tag': 'p', 'verdict': 'proof', 'verdict_source': None}]
    out = classify_unreceipted(rows)
    assert out == {'pre_receipt': [], 'needs_reverify': [], 'already_sourced': []}
