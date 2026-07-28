"""in-toto layout fail-open 반전 수리 가드 (OSS 충실도 감사 2026-07-28, DEFECT).

결함: 만료·owner 서명 무효·형식위반(LayoutError) layout 을 서버가 침묵 무시하고 광의
attestors 로 폴백했다 — register_prediction 은 cert 요구 자체가 사라져(무서명 예측 재개,
S6b 가 봉합했다고 주장한 구멍) submit 은 역할 좁힘·disjoint 검사 없이 통과했다.
upstream in-toto 는 만료/서명실패 = 검증 실패(fail-closed)다.

수리 계약: layout 필드가 *선언된* 트리에서 그 layout 이 유효하지 않으면 422 —
선언 자체가 없는 트리(라이브 대다수)는 무회귀(dead-σ: 키 없는 배포를 잠그지 않는다).
# KG: prom16-lakatotree-advancement-20260728 / in-toto fidelity
"""
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
os.environ.setdefault('NEO4J_USER', 'neo4j')
os.environ.setdefault('NEO4J_PASSWORD', 'test')

from fastapi import HTTPException  # noqa: E402

from lakatos import layout as layout_mod  # noqa: E402
from lakatos.write_cert import did_key_encode, ed25519_public_key, ed25519_sign  # noqa: E402
from server.contexts.tree.layout_gate import resolve_role_layout  # noqa: E402

_S = bytes([7]) * 32
DID = did_key_encode(ed25519_public_key(_S))


def _layout(expires=None):
    lo = {"layout_version": 1, "steps": [
        {"verb": "register_prediction", "pubkeys": [DID], "threshold": 1}]}
    if expires:
        lo["expires"] = expires
    return lo


def _signed(lo):
    return dict(research_layout=json.dumps(lo, ensure_ascii=False),
                layout_owner_did=DID,
                layout_sig=ed25519_sign(_S, layout_mod.canonical_layout_blob(lo)).hex())


def test_valid_signed_layout_resolves():
    lo = _layout()
    out = resolve_role_layout(_signed(lo))
    assert out is not None and out['steps'][0]['verb'] == 'register_prediction'


def test_undeclared_layout_is_none_not_error():
    """dead-σ 보존: layout 미선언 트리는 폴백이 옳다(라이브 대다수 — 무회귀)."""
    assert resolve_role_layout({}) is None
    assert resolve_role_layout({'research_layout': None}) is None


def test_expired_layout_is_rejected_not_ignored():
    lo = _layout(expires="2020-01-01T00:00:00+00:00")
    with pytest.raises(HTTPException) as ei:
        resolve_role_layout(_signed(lo))
    assert ei.value.status_code == 422 and 'expired' in str(ei.value.detail).lower()


def test_bad_owner_signature_is_rejected_not_ignored():
    rec = _signed(_layout())
    rec['layout_sig'] = 'ff' * 64          # 유효 길이·무효 서명
    with pytest.raises(HTTPException) as ei:
        resolve_role_layout(rec)
    assert ei.value.status_code == 422


def test_malformed_layout_is_rejected_not_ignored():
    rec = dict(research_layout='{"layout_version": 99, "steps": "nope"}',
               layout_owner_did=DID, layout_sig='00' * 64)
    with pytest.raises(HTTPException) as ei:
        resolve_role_layout(rec)
    assert ei.value.status_code == 422


def test_both_verbs_use_the_shared_gate():
    """register_prediction·submit_test_result 가 같은 fail-closed 게이트를 소비해야 —
    한쪽만 고치면 다른 verb 로 우회된다."""
    import inspect
    from server.contexts.tree import judgement_service as js
    for fn in (js.JudgementService.register_prediction, js.JudgementService.submit_test_result):
        src = inspect.getsource(fn)
        assert 'resolve_role_layout' in src, f'{fn.__name__} 이 공유 게이트 미사용'
        assert 'except layout_mod.LayoutError' not in src, f'{fn.__name__} 에 침묵 폴백 잔존'
