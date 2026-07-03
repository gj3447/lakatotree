"""git-흡수 G3 스펙트럼 — 이중가드(tests/test_git_absorption_g3.py) 밖의 경계 계약 + LTDD 영수증 CI 이빨.

  - advice 레지스트리: suggest-only(상태코드 불변·미적중 통과·멱등) — git --no-verify 류 off-switch 부재
  - incore trial 이 첫 write *전에* 4xx 격추(무측정 novel)
  - note_only_ratio = 모니터 신호(monitor_only, 게이트 아님 — q_adoption_metric_confound)
  - ooptdd_receipts/G3 영수증이 벤더 ooptdd_loop 러너로 complete+methodology_ok (LTDD 측정층 CI 상주)

# KG: LakatosTree_GitAbsorption_20260702 / G3_one_verb_honest_cycle
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from server.contexts.tree.advice import advice_for, with_advice

_REPO = Path(__file__).resolve().parents[2]


# ── advice 레지스트리 — suggest-only 계약 ────────────────────────────────────────────────
def test_advice_is_suggest_only_and_idempotent():
    e = HTTPException(409, '이미 스크립트로 채점된 노드 — 재채점 금지')
    adv = with_advice(e)
    assert adv.status_code == 409                       # 상태코드 불변(우회 없음)
    assert adv.detail['error'] == e.detail              # 원본 detail 보존
    assert '분기' in adv.detail['advice']               # 다음 명령 제안
    assert adv.detail['advice_mode'] == 'suggest-only'
    assert with_advice(adv) is adv                      # 멱등(재포장 안 함)

    miss = HTTPException(418, '레지스트리에 없는 임의 오류')
    assert with_advice(miss) is miss                    # 미적중 = 원본 그대로(조언 날조 금지)
    assert advice_for(None) is None


def test_advice_registry_has_no_bypass_vocabulary():
    """anti-absorption: advice 가 게이트 우회(--no-verify/skip/force)를 가르치지 않는다."""
    from server.contexts.tree.advice import _REGISTRY
    banned = ('--no-verify', 'skip_gate', 'force=true', 'bypass')
    for _needle, tip in _REGISTRY:
        assert not any(b in tip for b in banned), f"advice 가 우회를 가르침: {tip}"


# ── incore trial: 첫 write 전 4xx 격추 ──────────────────────────────────────────────────
def test_incore_trial_rejects_before_any_write():
    """novel_metric 선언 + novel_measured 누락 = judge 가 잡는 422 인데, 봉인 사이클은 이를
    *첫 write 전에*(incore) 격추한다 — 실패해도 세계가 아예 안 변함(롤백조차 불필요)."""
    from tests.test_git_absorption_g3 import _Cell, _cycle, _svc
    cell = _Cell()
    with pytest.raises(HTTPException) as ei:
        _svc(cell).run_cycle('T', _cycle(novel_metric='nm', novel_direction='higher',
                                         novel_threshold=1.0))   # novel_measured 없음
    assert ei.value.status_code == 422
    assert cell.pipeline == [] and cell.nodes == {}, "incore 거부가 write 를 이미 만듦"
    assert isinstance(ei.value.detail, dict) and 'advice' in ei.value.detail   # advice 동봉


# ── note_only_ratio — 모니터 신호 강등 ───────────────────────────────────────────────────
def test_note_only_ratio_is_monitor_only_signal():
    from server.read_models import compute_tree_metrics

    def _row(tag, **extra):   # tree_metrics 가 요구하는 정규화 노드 row 최소 shape
        return {'tag': tag, 'verdict': 'proof', 'note': '', 'parent': None, 'parents': [],
                'questions': [], 'metric_name': None, 'metric_value': None, **extra}
    td = {'nodes': [
        _row('a', verdict='progressive', verdict_source='scripted', pred_registered_at='ts'),  # 정직경로
        _row('b'),                                                                             # note-only
        _row('c'),                                                                             # note-only
    ], 'frontier': []}
    m = compute_tree_metrics(td)
    hm = m['honesty_monitor']
    assert hm['note_only_ratio'] == round(2 / 3, 4)
    assert hm['monitor_only'] is True   # 진보 게이트/채점 오라클 아님 — 관측 공시만


# ── LTDD 영수증 CI 이빨 — ooptdd_receipts/G3 를 벤더 러너로 실주행 ─────────────────────────
def test_g3_ooptdd_receipt_green_via_vendored_loop():
    """emit-adapter(g3_receipt.verify)가 실 run_cycle 을 구동해 6 요구사항(봉인/경제학/롤백×2/
    내구점/incore/음성오라클) 전부 이벤트 도착 = LTDD 측정층이 pytest 가드와 *같은 사실*을
    독립 경로(trace)로 증언. 러너는 self-contained _vendor(네트워크/시크릿 0)."""
    import lakatos.io  # noqa: F401 — _vendor bootstrap (ooptdd/ooptdd_loop importable)
    from ooptdd_loop.runner import run_loop
    from ooptdd_loop.spec import load_spec
    from ooptdd_loop.tools import _run_payload

    spec = load_spec(str(_REPO / 'ooptdd_receipts' / 'G3' / 'requirements.yaml'))
    spec.target.root = str(_REPO / 'ooptdd_receipts' / 'G3')
    payload = _run_payload(run_loop(spec))
    assert payload.get('total') == 6, payload
    assert payload.get('done') == 6, f"G3 영수증 RED: {payload}"
    assert payload.get('complete') and payload.get('methodology_ok'), payload
