"""role layout 해석 게이트 — in-toto fail-closed 정합 (2026-07-28 충실도 감사 수리).

결함(OSS 대조): 만료·owner 서명 무효·형식위반 layout 을 두 verb(register_prediction /
submit_test_result)가 각자 try/except 로 침묵 무시하고 광의 attestors 로 폴백했다.
결과: 만료된 순간 register_prediction 의 cert 요구 자체가 사라져 무서명 예측이 다시 통과했고
(S6b 가 봉합했다고 주장한 구멍), submit 은 역할 좁힘·disjoint 검사 없이 흘렀다.
upstream in-toto verifylib 은 만료/서명검증 실패를 곧 검증 실패로 취급한다(fail-closed).

계약(dead-σ 보존): layout 을 *선언한* 트리에서 그 layout 이 무효면 422 로 거부한다 —
선언이 아예 없는 트리는 None 을 돌려 기존 폴백(attestors) 그대로(키 없는 배포를 잠그지 않는다).
# KG: prom16-lakatotree-advancement-20260728 / in-toto fidelity
"""
from __future__ import annotations

from fastapi import HTTPException

from lakatos import layout as layout_mod


def resolve_role_layout(rec: dict) -> dict | None:
    """트리 레코드 → 검증된 role layout(dict) 또는 None(미선언). 무효 선언은 422."""
    raw = rec.get('research_layout')
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None                                  # 미선언 — 폴백이 옳다(무회귀)
    try:
        lo = layout_mod.parse_role_layout(raw)
    except layout_mod.LayoutError as exc:
        raise HTTPException(422, f'role layout 형식 위반 — 선언된 정책이 파싱 불가하면 그 트리의 '
                                 f'쓰기는 거부한다(in-toto fail-closed): {exc}')
    if lo is None:
        return None
    if layout_mod.layout_expired(lo):
        raise HTTPException(422, 'role layout expired — 만료된 정책으로는 쓰기를 인정하지 않는다 '
                                 '(in-toto fail-closed: 만료 시 폴백하면 무서명 우회 구멍이 열린다)')
    if not layout_mod.verify_layout_sig(lo, str(rec.get('layout_owner_did') or ''),
                                        str(rec.get('layout_sig') or '')):
        raise HTTPException(422, 'role layout owner 서명 검증 실패 — 위조/훼손된 정책 선언 '
                                 '(fail-closed: 침묵 무시 금지)')
    return lo
