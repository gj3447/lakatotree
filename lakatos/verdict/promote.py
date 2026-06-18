"""승격 게이트 — CANONICAL 승격 전 헌법 강제 (나생문 F-CON-1/2/5).

나생문 핵심 비판: 게이트는 write 경로에서 호출돼야 한다. 고아 함수면 '강제'가 아니다.
이 순수함수를 server set_verdict 가 CANONICAL 승격 직전 호출 → 위반 시 409 차단.
  F-CON-5: 후보 스크립트 판결이 rejected = 퇴행 가지 → CANONICAL 금지
  F-CON-2: stands=False = 막지 못한 인간/agent 의문 → 승격 차단
  F-CON-1: reproducible=False = ZDF서 재생성 불가 final → 차단 (None=비-final, 체크 생략)
# KG: span_lakatotree_promote / q-lkt-writepath-enforce
"""

from lakatos.verdicts import SCRIPTED_VERDICTS, ADMIN_VERDICTS

# ENG-CORR-1: deny-by-default allowlist (안전게이트는 fail-closed). 단일 'rejected' denylist 는
# dialectical 'degenerating'/'withdrawn'/'ambiguous' + rebuild 실패 판결을 통과시켜 퇴행 노드가
# CANONICAL 로 승격됐다. verdicts.py 정본서 derive → 미래 판결도 자동 차단(누락=차단).
PROMOTABLE = (SCRIPTED_VERDICTS - {'rejected'}) | ADMIN_VERDICTS | {'progressive_conditional'}


def promotion_gate(*, scripted_verdict: str, stands: bool,
                   reproducible: bool | None = None,
                   blocking_reasons: tuple = ()) -> tuple[bool, tuple]:
    """CANONICAL 승격 가능 여부 + 차단 사유. (ok, reasons)."""
    reasons = []
    if scripted_verdict not in PROMOTABLE:
        reasons.append(f'verdict_not_promotable:{scripted_verdict}')
    if stands is False:
        reasons.append('unresolved_doubt')
    if reproducible is False:
        reasons.append('not_reproducible')
    reasons.extend(blocking_reasons)
    return (not reasons, tuple(reasons))
