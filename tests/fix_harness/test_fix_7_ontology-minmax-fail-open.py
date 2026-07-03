"""FIX-HARNESS #7 — ontology min/max constraint is fail-open on non-numeric values.

finding id: #7 (P2 correctness)
locations:
  - lakatos/ontology.py:47-65  EntityType.violations
  - 특히 lakatos/ontology.py:60-64  (n = _num(v); min/max 분기는 n is not None 일 때만 검사)
  - server/contexts/tree/validation.py:18-33  _enforce_ontology → 422 (fail-closed 광고)

the bug:
  min/max 경계는 `n = _num(v)` 가 None 이 아닐 때만 검사된다. 값이 *존재하지만*
  비-숫자 문자열이면 _num 은 None 을 돌려주고 min/max 두 분기가 조용히 스킵된다 →
  {'temp':{'min':0,'max':100}} 같은 bare 수치 범위는 같은 rule 에 type:'number' 가
  함께 선언돼 있지 않는 한 임의 문자열로 완전히 우회 가능(fail-open).
  모듈 docstring + 서버 _enforce_ontology(422) 는 이 게이트를 enum/type/min/max 에 대해
  fail-closed 로 광고한다 — 실제 동작과 모순.

the exact fix:
  lakatos/ontology.py:60-64 — 'min' 또는 'max' 가 rule 에 있고 값이 present-but-non-numeric
  (n is None) 이면 위반을 emit. 또는 min/max 경계가 선언되면 암묵적으로 type:number 를 요구.

xfail(strict) until fixed.
"""
from __future__ import annotations

import pytest

from lakatos.ontology import EntityType


# bare 수치 범위 — type 선언 *없음*. fail-closed 라면 비-숫자 문자열은 위반이어야 한다.
_ET = EntityType(name="sensor", constraints={"temp": {"min": 0, "max": 100}})


# [FIXED 2026-06-27] #7 — green regression (lakatos/ontology.py:60-64 fail-closed on non-numeric min/max)
def test_non_numeric_string_must_violate_bare_minmax():
    # 비-숫자 문자열은 수치 범위를 만족할 수 없으므로 위반이어야 한다(현재는 [] = fail-open).
    assert _ET.violations({"temp": "EXTREME-9999"}) != []
    assert _ET.violations({"temp": "hot"}) != []


# [FIXED 2026-06-27] #7 — green regression (numeric gating + non-numeric fail-closed)
def test_numeric_values_still_gate_correctly():
    # 회귀 가드: 숫자 경로는 그대로 동작해야 한다.
    assert _ET.violations({"temp": 50}) == []          # 범위 내 → 통과
    over = _ET.violations({"temp": 500})               # 범위 초과 → max 위반
    assert any("max" in x for x in over)
    # 그리고 비-숫자는 (수정 후) 반드시 위반 — 한 테스트 안에서 fail-open 을 직접 고정.
    assert _ET.violations({"temp": "EXTREME-9999"}) != []
