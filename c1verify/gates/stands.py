"""stands gate reverifier (심화 D3) — 판결이 Dung grounded extension 에 서는지 봉인 번들에서 재유도.

엔진의 판결 standing 은 argumentation framework(Dung 1995)의 grounded extension 에 verdict argument
가 포함되는가로 정한다 — 막지 못한 의문(doubt)이 있으면 안 선다. 그 증거는 포인터였다. 이 게이트는
번들이 나르는 sealed arguments/attacks 에서 grounded extension 을 *재계산*(엔진 argue.py 와 동형,
import 0)해 verdict_arg 가 그 안에 있는지 재유도한다.

열거된 잔여: argument SET COMPLETENESS 는 out-of-band — 번들이 실제 제기된 모든 doubt 를 담았는지는
재유도로 알 수 없다(누락된 반박은 재계산에 안 나타난다). 이 게이트는 *동봉된* AF 에서 판결이 선다는
것만 증명한다.
"""
from __future__ import annotations

from .._decision import ACCEPT, REJECT, gate_decision

GATE = "stands"

_RESIDUAL = ("argument-set COMPLETENESS is out-of-band: the gate re-derives that the verdict stands in "
             "the ENCLOSED argumentation framework, NOT that the bundle carries every doubt actually "
             "raised (a withheld rebuttal cannot appear in the re-computation).")


def _defended(arg, S, attackers) -> bool:
    for atk in attackers.get(arg, ()):
        if not (S & attackers.get(atk, set())):
            return False
    return True


def _grounded_extension(arguments: set, attacks: list) -> set:
    """least fixed point of the characteristic function — argue.grounded_extension 와 동형(재구현)."""
    attackers = {a: set() for a in arguments}
    for u, v in attacks:
        if v in attackers:
            attackers[v].add(u)
    S: set = set()
    while True:
        nxt = {a for a in arguments if _defended(a, S, attackers)}
        if nxt == S:
            return S
        S = nxt


def verify_stands(payload, ctx) -> dict:
    """payload = {verdict_arg:'verdict:<tag>', arguments:[...], attacks:[[u,v],...]}. Total, fail-closed."""
    if not isinstance(payload, dict):
        return gate_decision(GATE, REJECT, "stands payload absent or not an object")
    verdict_arg = payload.get("verdict_arg")
    arguments = payload.get("arguments")
    attacks = payload.get("attacks")
    if not verdict_arg or not isinstance(arguments, list) or not isinstance(attacks, list):
        return gate_decision(GATE, REJECT, "stands payload 필드 부족(verdict_arg/arguments/attacks)")
    if verdict_arg not in arguments:
        return gate_decision(GATE, REJECT, "verdict_arg 가 arguments 에 없음(AF 불완전)")
    try:
        edges = [(str(u), str(v)) for u, v in attacks]     # [[u,v],...] → [(u,v),...]
    except (TypeError, ValueError):
        return gate_decision(GATE, REJECT, "attacks 형식 오류(각 원소 [attacker,target] 이어야)")
    ext = _grounded_extension(set(map(str, arguments)), edges)
    if str(verdict_arg) not in ext:
        defeated = sorted(set(map(str, arguments)) - ext)
        return gate_decision(GATE, REJECT,
                             f"판결이 grounded extension 밖 — 막지 못한 의문 존재(defeated={defeated[:5]})")
    return gate_decision(GATE, ACCEPT,
                         f"판결이 grounded extension 에 섬(재계산 |ext|={len(ext)})",
                         residual_trust_surface=_RESIDUAL)
