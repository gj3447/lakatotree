"""FIX-HARNESS #6 (P3 정직성) — /api/agm/revise 의 expansion 경로가 allow_hard_core 를 무시한다.

finding id: #6
locations:
  - server/app.py:629  — expansion 분기는 `expansion(base, _belief(req.new))` 로 호출하며
    allow_hard_core 를 전달하지 *않는다*. contraction(:633)/revision(:637-638)/
    demote_canonical(:642-643) 는 모두 allow_hard_core=req.allow_hard_core 를 넘긴다.
  - lakatos/programme/agm.py:69-84  — expansion() 은 allow_hard_core(기본 False) 를 받고,
    같은 id 의 *기존 hard_core* belief 를 덮어쓸 때 allow_hard_core=True 가 아니면
    HardCoreProtected 를 던진다(:77-80). app.py 가 안 넘기므로 항상 False 로 고정된다.

bug: op='expansion' 으로 기존 hard_core belief 를 명시 동의(allow_hard_core=True)와 함께
  덮어써도, app.py 가 동의를 전달하지 않아 *항상* HardCoreProtected → HTTP 409 로 막힌다.
  광고된 consent 토글이 expansion 에서는 죽은 코드다(over-enforce / fail-safe 이지만 계약 위반).

fix: server/app.py:629 를
  `r = expansion(base, _belief(req.new), allow_hard_core=req.allow_hard_core)` 로 바꿔
  동의를 expansion() 으로 forwarding 한다.

xfail(strict) until fixed — fix 가 들어오면 expansion+동의가 성공해 strict xfail 이 트립한다.
"""
import importlib
import os

import pytest
from fastapi import HTTPException


def load_app():
    os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
    os.environ.setdefault('NEO4J_USER', 'neo4j')
    os.environ.setdefault('NEO4J_PASSWORD', 'test')
    return importlib.import_module('server.app')


# [FIXED 2026-06-27] #6 — green regression (server/app.py:629 forwards allow_hard_core to expansion)
def test_expansion_with_consent_overwrites_hard_core(monkeypatch):
    """동의(allow_hard_core=True) 하에 기존 hard_core belief 를 expansion 으로 덮어쓰면
    성공해야 한다(post-fix 계약). 실제 엔드포인트 핸들러(app.agm_revise)를 구동한다.

    오늘은 app.py 가 동의를 안 넘겨 HardCoreProtected → HTTP 409 로 막힌다(버그)."""
    app = load_app()
    # 기존 hard_core 'hc' 를 같은 id 의 protective_belt 로 강등(개정)하는 expansion.
    base = [app.BeliefIn(belief_id='hc', statement='hc', kind='hard_core')]
    new = app.BeliefIn(belief_id='hc', statement='hc-revised', kind='protective_belt')

    out = app.agm_revise(app.AgmReviseIn(
        op='expansion', base=base, new=new, allow_hard_core=True))

    # post-fix: 동의했으므로 덮어쓰기 성공. 결과 base 에 'hc' 가 갱신돼 남는다.
    assert out['op'] == 'expansion'
    assert out['added'] == ['hc']
    by = {b['belief_id']: b for b in out['base']}
    assert 'hc' in by
    assert by['hc']['kind'] == 'protective_belt'        # hard_core → 강등 반영
    # hard_core 가 깎였으니 Kuhn 연동 신호도 켜져야 한다.
    assert out['programme_shift_candidate'] is True


# [FIXED 2026-06-27] #6 — green regression (server/app.py:629 forwards allow_hard_core to expansion)
def test_expansion_consent_does_not_raise_409(monkeypatch):
    """동의가 전달되면 HTTPException(409) 가 발생하지 *않아야* 한다(post-fix).
    오늘은 동의가 무시돼 409 가 터진다 — 이 테스트가 그 버그를 핀으로 고정한다."""
    app = load_app()
    base = [app.BeliefIn(belief_id='hc', statement='hc', kind='hard_core')]
    new = app.BeliefIn(belief_id='hc', statement='hc2', kind='hard_core')
    try:
        app.agm_revise(app.AgmReviseIn(
            op='expansion', base=base, new=new, allow_hard_core=True))
    except HTTPException as e:
        # 버그 존재 시 여기로 들어와 assert 실패(RED) — 동의했는데도 막혔다.
        pytest.fail(f"동의(allow_hard_core=True)했는데 expansion 이 막혔다: "
                    f"{e.status_code} {e.detail}")
