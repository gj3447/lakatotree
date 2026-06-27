"""FIX-HARNESS #8 (P3 honesty/security): research_import._source_type 의 substring URL 매칭은
도메인 스푸핑에 뚫린다 — trust.py 가 의도적으로 host-경계 매칭으로 대체한 바로 그 위조면.

finding id: #8
locations:
  - lakatos/research_import.py:51-61  _source_type
      raw substring 으로 권위 분류: 'mvtec.com' in u, 'arxiv.org' in u,
      ('sciencedirect','springer',...) in u. host 경계를 보지 않는다.
  - lakatos/trust.py:103-130  authoritative_url / _host
      host==d or host.endswith('.'+d) 로 매칭 — substring 이 도메인 스푸핑에
      뚫리기 때문(적대 재검증 코멘트 2026-06-21).
  - lakatos/trust.py:102  주석은 _source_type 의 권위 도메인을 "미러"한다고 CLAIM 하지만
      실제로는 매칭 의미론이 달라(substring vs host-boundary) 부정확하다.

the bug:
  같은 URL 에 대해 두 분류기가 불일치한다. 스푸핑 host
  'https://mvtec.com.evil.example/x' 에 대해:
    _source_type            -> 'vendor_primary_doc'  (primary_source_bonus=0.85 부여)
    trust.authoritative_url -> False                 (host 경계로 거부)
  즉 attacker 가 권위 벤더 도메인을 자기 host 의 좌측 라벨/경로에 끼워넣어
  1차 출처(primary) 가산점을 위조할 수 있다. trust.py 는 정확히 이 공격을
  막으려고 host-경계로 갔는데, research_import 는 여전히 substring 이다.

the exact fix (lakatos/research_import.py:51-61):
  _source_type 안에서 trust._host / trust.authoritative_url(host 경계)를 재사용해
  권위 벤더/출판사 분류를 host 경계로 판정한다. 그러면 스푸핑 host 는 'web' 으로
  떨어지고 trust.authoritative_url 과 일치한다.

xfail(strict) until fixed — RED until lakatos/research_import.py:54. 고쳐지면 strict 가 trip 한다.

dual guards:
  defect-axis negative oracle  : test_spoof_host_not_classified_as_authoritative_vendor
  mechanism / positive oracle  : test_legit_vendor_host_still_classified
"""
from __future__ import annotations

import pytest

from lakatos import trust
from lakatos.research_import import _source_type

# substring 매칭이 권위로 오분류하는 스푸핑 host: 'mvtec.com' 이 좌측 라벨에 들어있지만
# 실제 host 는 evil.example 다(권위 출처 아님). trust.authoritative_url 은 이미 False.
_SPOOF_URL = "https://mvtec.com.evil.example/x"
# 진짜 벤더 공식문서 host — 권위 분류 유지되어야 한다(회귀 가드).
_LEGIT_URL = "https://www.mvtec.com/x"

# 권위 vendor/primary 로 간주되는 source class 라벨들(분해신뢰에서 가산점 받는 부류).
_AUTHORITATIVE_CLASSES = {"vendor_primary_doc", "peer_reviewed"}


# [FIXED 2026-06-27] #8 — green regression (research_import._source_type reuses trust._host host-boundary matching)
def test_spoof_host_not_classified_as_authoritative_vendor():
    # 사전조건(메커니즘 입증): trust 는 이미 host 경계로 스푸핑을 거부한다.
    assert trust.authoritative_url(_SPOOF_URL) is False

    # 올바른(fix 후) 동작: _source_type 도 스푸핑 host 를 권위로 분류해선 안 된다.
    # 두 분류기는 같은 URL 에 대해 일치해야 한다(trust.py:102 의 "미러" 주장을 진실로 만든다).
    cls = _source_type(_SPOOF_URL)
    assert cls not in _AUTHORITATIVE_CLASSES, (
        f"스푸핑 host 가 권위 출처로 오분류됨: {cls!r} (trust.authoritative_url=False 와 불일치)"
    )


# [mechanism / positive oracle] 진짜 벤더 host 는 그대로 권위 분류 유지 — 회귀 가드.
def test_legit_vendor_host_still_classified():
    assert trust.authoritative_url(_LEGIT_URL) is True
    assert _source_type(_LEGIT_URL) == "vendor_primary_doc"
