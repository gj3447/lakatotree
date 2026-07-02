"""consilience — 두 연구 가지의 재합류 연산자 (git-흡수 G7, merge-ort 이식).

PIDNA §3.3 이 OPEN 으로 남긴 "재합류의 정량조건"을 닫는다. kuhn.py supersession 은 *이벤트*(교체)지
병합이 아니다 — 여기가 라카토트리 최초의 합류 연산자다.

git merge-ort 에서 가져온 것(merge-ort.c:5303-5391, 소스대조 CONFIRMED):
  · 3-way 순수함수: 두 leaf + 최근접 공통 BRANCHED_FROM 조상이 입력, 리포트가 출력. 그래프 쓰기 0.
  · criss-cross: 최근접 공통조상이 2+ 면 조상들을 *재귀 병합*해 가상조상을 만든다(:5006-5016).
    가상조상은 standing-불활성 — git 가상커밋에 ref 가 없듯 canonical/fertility/leaderboard 에 못 선다.
  · conflict 는 실패가 아니라 *데이터*(stages[3] 패턴): {target, base, side1, side2} 레코드.
    clean=False 여도 병합은 완료된다 — 비양립은 open_question/rival-standing 의 원료다.
  · 결정론: 정렬 고정 순회 + 바이트동일 canonical JSON 리포트(report_bytes).

★핵심 수식(PIDNA 재합류 정량조건 — 기존 수학에서 도출): 병합 credence ≠ max(c1,c2).
  UNION verdict 시퀀스(base + 양측 delta)를 bayes.branch_credence 에 fold 하면 target-keyed
  max-BF dedup(bayes.py:101-117)이 "양측이 같은 타깃 확증 = 1회"(Zahar use-novelty, 재확증=초과내용 0)를,
  음의 증거 매번 누적(Popper 비대칭)이 "부정은 양측 모두 부담"을 이미 구현한다. 새 수학 0.

★fail-closed (q_target_identity_scheme): consilience 경로의 *확증*(BF>1 어휘) verdict 는 target 선언
  의무 — bayes.py:91 의 permissive None(=항상 novel, 할인 없음)은 레거시 호출자 비파괴용이라,
  이 경로로 들어오면 무타깃 재확증이 credence 를 인위 부양한다. 없으면 ConsilienceTargetMissing.
  음의/무정보 증거는 target 없어도 적법(매번 누적이 정직한 기본값).

★anti-absorption (하드제약 — 위반은 different_programme):
  · rerere(과거 해소 자동재생) 금지: 이 모듈은 무상태 순수함수 — 해소 기록을 저장/재생하지 않는다.
  · 유사도 기반 target 동일성 금지: 동일성은 *정확 문자열 일치*뿐 — 유사도 추론은 독립 확증을
    credence 안에서 무음 붕괴시킨다.
  · verdict_mutation=False: incore 계산 → 리포트 → 기존 human/admin 게이트로 canonical 화.
    미해소 conflict 는 canonical 채택만 차단(canonical_adoptable=False), 병합 자체는 완료.

# KG: LakatosTree_GitAbsorption_20260702 / G7_consilience_operator
"""

from __future__ import annotations

import json

from lakatos.quant.bayes import BF_BASE, branch_credence

# criss-cross 재귀 상한 — DAG 에선 도달 불가(조상 재귀는 깊이 단조감소), 부패 그래프(사이클) 방어.
_MAX_BASE_RECURSION = 32


class ConsilienceTargetMissing(ValueError):
    """확증(BF>1) verdict 가 target 없이 consilience fold 에 들어옴 — fail-closed 거부."""


def _canon(x: object) -> str:
    """stance 동등성의 정본 — canonical JSON(정렬 키). 유사도 아님: 바이트가 다르면 다른 stance."""
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _eq(a: object, b: object) -> bool:
    return _canon(a) == _canon(b)


def _ancestors_inclusive(parents: dict, tag: str) -> set:
    """BRANCHED_FROM 조상 집합(자신 포함) — 사이클 안전 BFS."""
    seen, stack = set(), [tag]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(parents.get(cur, []))
    return seen


def nearest_common_ancestors(parents: dict, a: str, b: str) -> tuple:
    """최근접 공통조상(들) — git merge-base 아날로그: 공통조상 중 *다른 공통조상의 진조상이 아닌* 것.
    2+ 개 = criss-cross(가상조상 재귀병합 대상). 결정론: 정렬 튜플."""
    common = _ancestors_inclusive(parents, a) & _ancestors_inclusive(parents, b)
    maximal = [c for c in common
               if not any(o != c and c in _ancestors_inclusive(parents, o) for o in common)]
    return tuple(sorted(maximal))


def _three_way(base: dict, s1: dict, s2: dict) -> tuple:
    """per-target 3-way 병합(merge-ort 규칙): 동일=1회 채택 · 한쪽만 변경=채택(삭제 포함) ·
    비양립=conflict 데이터. 반환 (merged, adopted, conflicts) — 전부 target 정렬(결정론)."""
    merged: dict = {}
    adopted: list = []
    conflicts: list = []
    for t in sorted(set(base) | set(s1) | set(s2)):
        b, x, y = base.get(t), s1.get(t), s2.get(t)
        if _eq(x, y):                       # 양측 동일(동일 변경 포함) → 1회 채택
            if x is not None:
                merged[t] = x
            if not _eq(x, b):
                adopted.append({"target": t, "from": "both", "stance": x})
        elif _eq(x, b):                     # side1 무변경 → side2 채택(None=삭제 존중)
            if y is not None:
                merged[t] = y
            adopted.append({"target": t, "from": "side2", "stance": y})
        elif _eq(y, b):                     # side2 무변경 → side1 채택
            if x is not None:
                merged[t] = x
            adopted.append({"target": t, "from": "side1", "stance": x})
        else:                               # 비양립(modify/modify·modify/delete) → conflict-as-DATA
            conflicts.append({"target": t, "base": b, "side1": x, "side2": y})
    return merged, adopted, conflicts


def _resolve_base(parents: dict, stances: dict, a: str, b: str, _depth: int = 0) -> tuple:
    """병합 base 해석. NCA 1개 → 그 조상의 stance. 2+ 개(criss-cross) → 조상들을 재귀 병합한
    *가상조상*(standing-불활성). 가상조상 내부의 미해소 conflict 타깃은 base 에서 *탈락*시킨다
    (부재 base → 양측 상이 시 conflict 로 표면화 = 무음 해소 금지, 보수적)."""
    if _depth > _MAX_BASE_RECURSION:
        raise ValueError("consilience base 재귀 상한 초과 — BRANCHED_FROM 그래프 부패(사이클?) 의심")
    ncas = nearest_common_ancestors(parents, a, b)
    if len(ncas) <= 1:
        base = dict(stances.get(ncas[0], {})) if ncas else {}
        return base, None
    # criss-cross: 정렬된 조상들을 왼쪽부터 pairwise 재귀 병합(결정론). 첫 쌍은 서로의 재귀 base 로,
    # 3개째부터는 누적 가상조상이 그래프 위치가 없으므로 빈 base(보수: 상이=conflict→탈락)로 접는다.
    virtual_conflicts: list = []
    vbase, _ = _resolve_base(parents, stances, ncas[0], ncas[1], _depth + 1)
    acc, _, confl = _three_way(vbase, dict(stances.get(ncas[0], {})), dict(stances.get(ncas[1], {})))
    virtual_conflicts.extend(confl)
    for extra in ncas[2:]:
        acc, _, confl = _three_way({}, acc, dict(stances.get(extra, {})))
        virtual_conflicts.extend(confl)
    info = {"from": list(ncas), "standing_inert": True,   # ref 없는 가상커밋 — canonical/fertility 불가
            "conflicts": sorted(virtual_conflicts, key=lambda c: c["target"])}
    return acc, info


def union_credence(base_verdicts: list, side1_verdicts: list, side2_verdicts: list,
                   source_trust_map: dict | None = None) -> dict:
    """병합 credence = UNION verdict 시퀀스(base + 양측 delta, tag 정체성)의 branch_credence fold.

    max(c1,c2) 지름길 금지 — dedup(같은 타깃 확증 1회)과 음의 증거 양측 누적은 branch_credence 가
    이미 구현(bayes.py:101-117). 여기선 (1) tag 로 공유 base 를 1회만 합치고 (2) 확증의 무타깃을
    fail-closed 거부한다. verdict dict 는 'tag' 필수(정체성 없인 union 이 정의 불가)."""
    union: list = []
    seen: set = set()
    for v in list(base_verdicts) + list(side1_verdicts) + list(side2_verdicts):
        tag = v.get("tag")
        if not tag:
            raise ValueError("consilience union: verdict 에 'tag'(노드 정체성) 필수")
        if tag in seen:
            continue
        seen.add(tag)
        union.append(v)
    untargeted = sorted(v["tag"] for v in union
                        if BF_BASE.get(v.get("verdict", ""), 1.0) > 1.0 and v.get("target") is None)
    if untargeted:
        raise ConsilienceTargetMissing(
            f"확증 verdict 에 target 없음(fail-closed): {untargeted} — "
            f"q_target_identity_scheme: 확증은 명시 의미키(pred_closes/novel_target) 선언 의무")
    return {
        "merged": branch_credence(union, source_trust_map=source_trust_map),
        "side1": branch_credence(list(side1_verdicts), source_trust_map=source_trust_map),
        "side2": branch_credence(list(side2_verdicts), source_trust_map=source_trust_map),
        "union_size": len(union),
        "rule": "union-fold(branch_credence: 같은타깃 확증 dedup·음의증거 양측누적) — max(c1,c2) 지름길 아님",
    }


def consilience_report(*, parents: dict, stances: dict, leaf1: str, leaf2: str,
                       branch_verdicts: tuple | None = None,
                       source_trust_map: dict | None = None) -> dict:
    """두 가지 leaf 의 incore 3-way 병합 리포트(순수 — 그래프 쓰기 0, 입력 불변).

    parents: tag → BRANCHED_FROM 부모 목록(DAG). stances: tag → {target → stance(JSON-able)}.
    branch_verdicts: (base, side1, side2) verdict 시퀀스를 주면 union_credence 블록 포함.
    canonical 화는 이 리포트를 들고 기존 human/admin 게이트로 — verdict_mutation=False 가 계약이다."""
    base, virtual = _resolve_base(parents, stances, leaf1, leaf2)
    merged, adopted, conflicts = _three_way(
        base, dict(stances.get(leaf1, {})), dict(stances.get(leaf2, {})))
    clean = not conflicts
    report = {
        "operator": "consilience",
        "inputs": {"leaf1": leaf1, "leaf2": leaf2},
        "merge_base": base,
        "virtual_ancestor": virtual,
        "merged_stances": merged,
        "adopted": sorted(adopted, key=lambda a: a["target"]),
        "conflicts": sorted(conflicts, key=lambda c: c["target"]),
        "clean": clean,
        "canonical_adoptable": clean,      # 미해소 conflict = canonical 채택만 차단(병합은 완료)
        "verdict_mutation": False,         # incore — 판결 권위는 judge/human·admin 게이트에 남는다
    }
    if branch_verdicts is not None:
        b, s1, s2 = branch_verdicts
        report["credence"] = union_credence(b, s1, s2, source_trust_map=source_trust_map)
    return report


def report_bytes(report: dict) -> str:
    """바이트동일 결정론 직렬화(정렬 키 canonical JSON) — 리포트는 수송 가능한 증거다."""
    return _canon(report)
