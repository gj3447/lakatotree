"""도달성 스윕 — 물리 소거의 유일 게이트(git-흡수 G9).

git prune(builtin/prune.c:84-109, reachable.c:299-355)의 불변식 이식: *도달가능한 객체는 절대 수집되지 않는다*;
물리 소거 ⟺ (unreachable) ∧ (aged past grace). 루트 집합은 over-inclusive(reflog 도 GC 루트, prune.c:68
mark_reflog=1) — 라카토트리에선 {활성 트리→노드, research_events(reflog 아날로그), prereg 잠금, G1 영수증 체인}.
engine/FORCEFUL verdict-bearing 레코드가 어느 루트서도 도달 불가면 ORPHANED_ENGINE_VERDICT(hard finding) — 증거
불멸의 오라클. 순수 함수(BFS + 게이트) — now_tx·grace·edges 주입, 결정론 단위검증.

★anti-absorption: recency 는 서버 tx 시각만(client mtime 금지, prune.c:98 st_mtime 이식하되 서버가 소유).
★fsck 처럼 구조만 — 판결 권위는 judge 층. 스윕은 '무엇이 도달가능/소거후보인가'만 답한다.
"""

from __future__ import annotations

from dataclasses import dataclass

# 소거 grace(초). ★q_erasure_grace_governance 결정: *코드 상수*(요청 flag/note/트리 가변필드 절대 금지) —
#   낮추려면 소스 편집이 필요해 조용한 약화가 구조적으로 불가능. 물리소거는 grace 경과 *단독*으론 불충분,
#   반드시 unreachable 과 AND. (이상적 거처=lakatos/grounding.py GROUNDED[tier=policy]; 본 슬라이스는 여기 상수.)
ERASURE_GRACE_SECONDS: float = 7 * 24 * 3600   # 7일


@dataclass(frozen=True)
class OrphanFinding:
    node_id: str
    reason: str


def reachable_set(roots, edges) -> set:
    """roots 에서 edges(인접 dict: src→[dst,...])를 따라 BFS mark. git 도달성 walk 이식(사이클 안전)."""
    seen: set = set()
    frontier = list(roots)
    while frontier:
        cur = frontier.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for dst in edges.get(cur, ()):  # type: ignore[union-attr]
            if dst not in seen:
                frontier.append(dst)
    return seen


def sweep_orphans(roots, edges, records) -> list[OrphanFinding]:
    """engine/FORCEFUL verdict-bearing 레코드 중 어느 루트서도 도달 불가한 것 = ORPHANED_ENGINE_VERDICT.

    records: [{id, engine_scored(bool)}, ...]. edges: 인접 dict. roots: 루트 id 목록.
    orphan-free(빈 리스트) = 증거 불멸 불변식 만족. 하나라도 있으면 스윕은 *멈춘다*(hard stop, 경고 아님).
    """
    reach = reachable_set(roots, edges)
    return [OrphanFinding(node_id=rec['id'], reason='ORPHANED_ENGINE_VERDICT')
            for rec in records
            if rec.get('engine_scored') and rec['id'] not in reach]


def prunable(rec: dict, reachable: set, now_tx: float, grace: float = ERASURE_GRACE_SECONDS) -> bool:
    """물리 소거 단일 게이트: 소거가능 ⟺ (unreachable) ∧ (aged past grace). git prune.c:84-109.

    rec: {id, tombstoned_at(서버 tx 시각 float | None)}. reachable: reachable_set 결과. now_tx: 서버 tx 시각.
    - reachable 이면 절대 소거 불가(도달가능 불멸).
    - tombstone 안 됨(tombstoned_at None)이면 소거 불가(포인터가 아직 삼).
    - aged: now_tx − tombstoned_at ≥ grace. grace 미경과면 불가(in-flight 보호).
    engine_scored 레코드는 애초 sweep_orphans 가 hard stop 하므로 여기 도달 전 차단(이중 방어).
    """
    if rec['id'] in reachable:
        return False
    ts = rec.get('tombstoned_at')
    if ts is None:
        return False
    return (now_tx - ts) >= grace
