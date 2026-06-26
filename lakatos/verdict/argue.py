"""논증 채널 — Dung 추상 논증(AF). 인간+agent 의 질문/코멘트/의문/반박을 형식화.

역할분담: 인간+agent = 비판(질문/의문 = argument attack) / 순수 agent = 코드빌딩(test_result).
노드 판결 = argument. 의문(doubt) = 그 판결을 공격. 반박(rebuttal) = 의문을 공격.
판결이 '선다(stands)' = grounded extension 에 포함 = 막아낸 의문 없음.
출처: Dung 1995, Abstract Argumentation Framework (A, R), grounded extension = 최소 완전.
# KG: span_lakatotree_argue
라이선스(THEORY §8): dung1995 toulmin1958 walton_reed_macagno2008
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


def assemble_af(tag: str, arg_rows: list) -> tuple[set, list]:
    """노드 verdict + 등재 Argument 들 → Dung AF (arguments, attacks) 의 *정본* 조립.

    standing / set_verdict CANONICAL floor / add_critique 자동강등이 *모두* 이걸 쓴다 — 인라인 조립
    금지(회귀는 클래스-커버 테스트가 잡는다). arg_rows 원소: {id, attacks, by?}. attacks==tag 면 verdict
    직접공격(doubt), 아니면 다른 argument 공격(=verdict 방어).

    #H8 (설계감사 2026-06-26) actor 독립성: 방어 엣지(attacker→non-verdict target)는 두 argument 의
    by(제기자 actor)가 같으면 AF 에 진입 못 한다 — 자기 doubt 를 자기 rebuttal 로 무력화하는 self-vouch
    차단. verdict 직접공격(doubt)은 누구나 가능하므로 actor 무관(제외 안 함). by 누락(레거시)은 same-actor
    판정 불가라 엣지 보존(보수적 하위호환). 작성자 vs 방어자 독립(노드 author 미식별)은 Sybil 천장 —
    by-construction 밖이라 actor 신원 서명바인딩(actor==DID/PeerId) 전엔 닫히지 않는다(irreducible).
    """
    verdict_arg = f'verdict:{tag}'
    arguments = {verdict_arg}
    by_of: dict = {}
    norm: list = []   # (short, target, by)
    for a in arg_rows:
        if not a.get('id'):
            continue
        short = a['id'].split('/')[-1]
        by = (a.get('by') or '').strip()
        arguments.add(short)
        by_of[short] = by
        by_of[a['id']] = by
        tgt = verdict_arg if a.get('attacks') == tag else a.get('attacks')
        norm.append((short, tgt, by))
    attacks: list = []
    for short, tgt, by in norm:
        if tgt != verdict_arg and by and by_of.get(tgt) == by:
            continue   # #H8 self-defense 엣지 제거 (attacker by == target by)
        attacks.append((short, tgt))
    return arguments, attacks


# ── OSS 적용(#5 정비): 외부 ICCMA AF solver 교차검증 + PyArg 식 수용-설명 ──────────────────
#  THEORY §7 경계: 외부 solver(mu-toksia/pyglaf/ASPARTIX 등)는 *evidence/oracle* 일 뿐 judge 아님.
#  argue.grounded_extension/verdict_stands 가 권위를 유지하고, 외부 solver 는 그것을 *교차검증*만 한다.
#  ICCMA 표준 직렬화(TGF/APX)로 argue 의 AF 를 내보내 어떤 ICCMA solver 로도 round-trip 할 수 있다.

def to_tgf(arguments: set, attacks: list) -> str:
    """AF → ICCMA TGF(Trivial Graph Format): 노드들 · '#' · 엣지(공격) 줄. 외부 solver 입력용 *직렬화*.
    결정적(정렬) — 같은 AF 는 같은 문자열. 미등록 노드 가리키는 attack 은 제외(그래프 무결)."""
    nodes = sorted((str(a) for a in arguments))
    edges = sorted((str(u), str(v)) for u, v in attacks if u in arguments and v in arguments)
    return "\n".join([*nodes, "#", *(f"{u} {v}" for u, v in edges)])


def to_apx(arguments: set, attacks: list) -> str:
    """AF → ASPARTIX APX: arg(a). / att(u,v). (ICCMA 대체 입력형식). 직렬화 only(judge 아님)."""
    nodes = sorted((str(a) for a in arguments))
    edges = sorted((str(u), str(v)) for u, v in attacks if u in arguments and v in arguments)
    return "\n".join([*(f"arg({a})." for a in nodes), *(f"att({u},{v})." for u, v in edges)])


def parse_extension(text: str) -> set:
    """외부 ICCMA solver 의 단일 extension 출력([a,b,c] / 공백·줄 구분 / 'w'·'NO' 제외)을 set 으로 파싱."""
    import re as _re
    toks = (t for t in _re.split(r"[\s,\[\]()]+", (text or "").strip()) if t)
    return {t for t in toks if t not in ("w", "NO", "YES")}


def grounded_extension_agrees(arguments: set, attacks: list, external_extension) -> bool:
    """argue 의 grounded extension == 외부 ICCMA solver 가 보고한 extension? (독립 oracle 교차검증).
    True = argue.grounded_extension 이 표준 solver 와 일치(우리 구현의 외부 확증). verdict 권위는 여전히
    내부(argue)에 있고 solver 는 evidence 일 뿐 — THEORY §7 경계 보존."""
    ext = external_extension if isinstance(external_extension, set) else set(external_extension)
    return grounded_extension(arguments, attacks) == ext


def acceptance_explanation(arguments: set, attacks: list) -> dict:
    """PyArg 식 수용-설명 provenance — bare bool 을 *'어느 의문(doubt)이 어느 반박(rebuttal)에 막혀
    판결이 서는가'* 의 계보로 격상. grounded 3치 라벨(accepted/rejected/undecided):
      accepted  : grounded extension 포함 — rebutted_doubts={공격자 atk: 그 atk 를 반격한 수용된 defender 들}
      rejected  : 수용된 공격자(막지 못한 의문)에게 무너짐 — unrebutted_doubts=[그 공격자들]
      undecided : 수용도 반박도 안 됨(grounded 미결)
    grounded_extension 에 의존(verdict 권위 불변) — 설명은 그 위의 read-only 계보."""
    attackers = {a: set() for a in arguments}
    for u, v in attacks:
        if v in attackers and u in arguments:
            attackers[v].add(u)
    ext = grounded_extension(arguments, attacks)
    out: dict = {}
    for a in arguments:
        accepted_attackers = sorted((attackers[a] & ext), key=str)
        if a in ext:
            out[a] = {"status": "accepted",
                      "rebutted_doubts": {atk: sorted(ext & attackers.get(atk, set()), key=str)
                                          for atk in sorted(attackers[a], key=str)}}
        elif accepted_attackers:
            out[a] = {"status": "rejected", "unrebutted_doubts": accepted_attackers}
        else:
            out[a] = {"status": "undecided", "unrebutted_doubts": []}
    return out
