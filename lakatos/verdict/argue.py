"""논증 채널 — Dung 추상 논증(AF). 인간+agent 의 질문/코멘트/의문/반박을 형식화.

역할분담: 인간+agent = 비판(질문/의문 = argument attack) / 순수 agent = 코드빌딩(test_result).
노드 판결 = argument. 의문(doubt) = 그 판결을 공격. 반박(rebuttal) = 의문을 공격.
판결이 '선다(stands)' = grounded extension 에 포함 = 막아낸 의문 없음.
출처: Dung 1995, Abstract Argumentation Framework (A, R), grounded extension = 최소 완전.
# KG: span_lakatotree_argue
"""


def _defended(arg, S, attackers):
    """arg 의 모든 공격자 atk 가 S 의 누군가에게 반격당하면 defended (admissible 핵심).
    s 가 atk 를 공격 ⟺ s ∈ attackers[atk]. 따라서 S ∩ attackers[atk] ≠ ∅ 이어야."""
    for atk in attackers.get(arg, ()):
        if not (S & attackers.get(atk, set())):
            return False
    return True


def grounded_extension(arguments: set, attacks: list) -> set:
    """grounded extension = characteristic function F 의 최소 고정점 (least fixed point)."""
    attackers = {a: set() for a in arguments}
    for u, v in attacks:
        if v in attackers:
            attackers[v].add(u)
    S = set()
    while True:
        nxt = {a for a in arguments if _defended(a, S, attackers)}
        if nxt == S:
            return S
        S = nxt


def verdict_stands(verdict_arg, arguments: set, attacks: list) -> bool:
    """판결 argument 가 grounded extension 에 있는가 = 막아낸 의문 없이 정당한가."""
    return verdict_arg in grounded_extension(arguments, attacks)
