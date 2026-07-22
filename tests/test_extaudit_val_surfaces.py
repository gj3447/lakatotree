"""EXTAUDIT S3b — VAL 표면 확장: read-model(get_tree 상속) + submit 응답에도 등급 동봉.

S3 는 standing() 한 표면만 닫았다. 급소 #5 의 완결은 *모든* 소비자 표면: repository read-model 에
verdict_display/assurance 를 부착하면 get_tree/tree_metrics/leaderboard 가 자동 상속하고,
submit_test_result 응답에도 동봉해 제출자가 그 자리에서 자기 판정의 보증 등급을 본다.

설계 계약(비파괴): bare `verdict` 필드는 불변 — 내부 술어(PROGRESS_VERDICTS 비교, force_of_row,
metrics)가 전부 그걸 읽는다. 표면 동봉은 *추가 필드* verdict_display + assurance 로만.
(standing 은 S3 에서 이미 치환형으로 착지 — 사람용 단일 표면이라 유지.)
# KG: q-extaudit-verdict-context-parity-20260722 잔여(S3b) / crit-extaudit-20260722-default-disarmed-gates
"""
from pathlib import Path

from server.contexts.tree.repository import normalize_node_row

ROOT = Path(__file__).resolve().parents[1]


def _row(**kw):
    base = dict(tag='n1', verdict='progressive', verdict_source='scripted', current_receipt_sha='r1')
    base.update(kw)
    return base


# ── read-model: verdict_display + assurance 부착 (get_tree/metrics/leaderboard 자동 상속) ────
def test_read_model_attaches_display_and_assurance():
    out = normalize_node_row(_row(measurement_grade='server_regenerated', replay_status='verified'))
    assert out['verdict_display'] == 'progressive@L2(replay_verified)', out.get('verdict_display')
    assert out['assurance']['val'] == 2


def test_read_model_disarmed_shows_l0():
    out = normalize_node_row(_row(measurement_grade='client_asserted', replay_status='not_attempted'))
    assert out['verdict_display'] == 'progressive@L0(client_asserted,client_asserted_unverified)'
    assert out['assurance']['val'] == 0


def test_read_model_admin_verdict_display_stays_bare():
    out = normalize_node_row(dict(tag='n2', verdict='proof'))
    assert out['verdict_display'] == 'proof'   # admin 어휘 — 과잉 포맷 금지


def test_read_model_bare_verdict_field_unchanged():
    # 비파괴 계약: 내부 술어가 읽는 verdict 원문은 불변(치환이면 metrics/PROGRESS 비교 전부 깨짐).
    out = normalize_node_row(_row(measurement_grade='client_asserted', replay_status='not_attempted'))
    assert out['verdict'] == 'progressive'


# ── submit 응답: 순수 헬퍼 + 배선 앵커 (ag1 장르 — 소스 드리프트를 기계 강제) ────────────────
def test_submit_response_assurance_helper():
    from server.contexts.tree.judgement_policy import response_assurance
    display, assur = response_assurance(
        verdict='progressive', current_receipt_sha='r1',
        measurement_grade='server_regenerated', replay_status='verified',
        assurance_tier_resolved='anchored', attested_by_did=None)
    assert display == 'progressive@L2(replay_verified)' and assur['val'] == 2
    d0, a0 = response_assurance(
        verdict='progressive', current_receipt_sha='r1',
        measurement_grade='client_asserted', replay_status='not_attempted',
        assurance_tier_resolved='anchored', attested_by_did=None)
    assert '@L0(client_asserted' in d0 and a0['val'] == 0


def test_submit_response_wires_display():
    src = (ROOT / 'server' / 'contexts' / 'tree' / 'judgement_service.py').read_text(encoding='utf-8')
    assert "'verdict_display':" in src and 'response_assurance(' in src, \
        'submit 응답에 verdict_display 미배선 — 표면 확장(S3b) 붕괴'
