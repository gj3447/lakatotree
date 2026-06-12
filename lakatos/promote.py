"""승격 게이트 — CANONICAL 승격 전 헌법 강제 (나생문 F-CON-1/2/5).

나생문 핵심 비판: 게이트는 write 경로에서 호출돼야 한다. 고아 함수면 '강제'가 아니다.
이 순수함수를 server set_verdict 가 CANONICAL 승격 직전 호출 → 위반 시 409 차단.
  F-CON-5: 후보 스크립트 판결이 rejected = 퇴행 가지 → CANONICAL 금지
  F-CON-2: stands=False = 막지 못한 인간/agent 의문 → 승격 차단
  F-CON-1: reproducible=False = ZDF서 재생성 불가 final → 차단 (None=비-final, 체크 생략)
# KG: span_lakatotree_promote / q-lkt-writepath-enforce
"""

NON_PROMOTABLE = frozenset({'rejected'})   # 퇴행 가지는 CANONICAL 불가


def promotion_gate(*, scripted_verdict: str, stands: bool,
                   reproducible: bool | None = None,
                   blocking_reasons: tuple = ()) -> tuple[bool, tuple]:
    """CANONICAL 승격 가능 여부 + 차단 사유. (ok, reasons)."""
    reasons = []
    if scripted_verdict in NON_PROMOTABLE:
        reasons.append(f'verdict_is_{scripted_verdict}')
    if stands is False:
        reasons.append('unresolved_doubt')
    if reproducible is False:
        reasons.append('not_reproducible')
    reasons.extend(blocking_reasons)
    return (not reasons, tuple(reasons))
