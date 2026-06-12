"""트리 지표 — 라카토스(진보율/기각률/퇴행깊이) + 라우든(문제수지/폐기 후보).

순수함수: 입력 = plain dict 리스트 (서버/스크립트/노트북 어디서든 동일 판정).
# KG: span_lakatotree_S1_laudan_layer
"""
from collections import defaultdict
from .laudan import problem_balance, psr, should_abandon
from .bayes import branch_credence, should_abandon_bayes

NONPROGRESSIVE = ('rejected', 'partial', 'equivalent')


def tree_metrics(nodes: list, frontier: list, cfg: dict | None = None) -> dict:
    cfg = cfg or {}
    by = {r['tag']: r for r in nodes}
    n = len(nodes)
    rejected = [r['tag'] for r in nodes if r['verdict'] == 'rejected']
    can = [r['tag'] for r in nodes if r['verdict'] == 'CANONICAL']
    path, cur, seen = [], (can[0] if can else None), set()
    while cur and cur not in seen and cur in by:   # 사이클 가드(나생문 F-FG-3)
        seen.add(cur)
        path.append(cur)
        cur = by[cur].get('parent')
    path = path[::-1]
    # 진보율 (같은 scope 의 정본경로 metric)
    prog = None
    pm = [(t, by[t]['metric_value'], by[t].get('metric_scope')) for t in path
          if by[t].get('metric_value') is not None]
    if len(pm) >= 2:
        scopes = defaultdict(list)
        for t, m, sc in pm:
            scopes[sc].append((t, m))
        sc = max(scopes.values(), key=len)
        if len(sc) >= 2:
            prog = dict(first={'tag': sc[0][0], 'm': sc[0][1]},
                        last={'tag': sc[-1][0], 'm': sc[-1][1]},
                        improvement_pct=round(100 * (sc[0][1] - sc[-1][1]) / sc[0][1], 1))
    children = defaultdict(list)
    for r in nodes:
        if r.get('parent'):
            children[r['parent']].append(r)
    def degen_depth(tag, _seen=None):
        _seen = _seen or set()
        if tag in _seen:
            return 0                              # 사이클 가드(나생문 F-FG-3)
        _seen = _seen | {tag}
        return max([1 + degen_depth(c['tag'], _seen) for c in children.get(tag, [])
                    if c['verdict'] in NONPROGRESSIVE], default=0)
    stalled = max([degen_depth(t) for t in path], default=0)
    open_q = sum(1 for q in frontier if q['status'] == 'OPEN')
    closed_q = sum(1 for q in frontier if q['status'] == 'CLOSED')
    annotated = sum(1 for r in nodes
                    if r.get('algorithm') and r.get('comment') and r.get('limitation'))
    # 라우든: leaf 별 가지 진단 → 폐기 후보
    leaves = [r['tag'] for r in nodes if r['tag'] not in children]
    abandon = []
    for leaf in leaves:
        if leaf in path:
            continue
        chain, cur2, seen2 = [], leaf, set()
        while cur2 and cur2 not in path and cur2 not in seen2 and cur2 in by:
            seen2.add(cur2)
            chain.append(by[cur2])
            cur2 = by[cur2].get('parent')
        consec = 0
        for r in chain:                      # leaf→분기점 방향 연속 비진보
            if r['verdict'] in NONPROGRESSIVE:
                consec += 1
            else:
                break
        hits = sum(1 for r in chain
                   if r['verdict'] in ('progressive', 'CANONICAL', 'former_canonical'))
        ok, reason = should_abandon(consecutive_nonprogressive=consec,
                                    nodes_spent=len(chain), prediction_hits=hits,
                                    problem_balance_windowed=0)
        if ok:
            abandon.append(dict(leaf=leaf, branch_len=len(chain), reason=reason))
    laudan = dict(frontier_balance=problem_balance(closed_q, open_q),
                  psr=round(psr(closed_q, len(path)), 3),
                  abandon_candidates=abandon)
    # 베이즈 연속층: 정본 경로 신뢰도 + 저신뢰 가지 (판결 시퀀스 = 증거)
    def verdict_seq(tags):
        return [{'verdict': by[t]['verdict']} for t in tags]   # delta 미보유 시 판결만
    can_cred = round(branch_credence(verdict_seq(path)), 3) if path else None
    low_branches = []
    for leaf in leaves:
        if leaf in path:
            continue
        chain, cur3, seen3 = [], leaf, set()
        while cur3 and cur3 not in path and cur3 not in seen3 and cur3 in by:
            seen3.add(cur3); chain.append(cur3); cur3 = by[cur3].get('parent')
        ab, c = should_abandon_bayes(verdict_seq(chain[::-1]))
        if ab:
            low_branches.append(dict(leaf=leaf, credence=round(c, 3)))
    bayes = dict(canonical_credence=can_cred, low_credence_branches=low_branches,
                 note='강한 가지는 반례 하나로 안 죽는다 — 신뢰도<0.1 가지만 폐기')
    alerts = [a for a in [
        f'퇴행 경보: 연속 비진보 깊이 {stalled} ≥3 — 가지 전환 검토' if stalled >= 3 else None,
        '정체 경보: 진보율 ≤0' if prog and prog['improvement_pct'] <= 0 else None,
        '주석 미완 노드 존재' if annotated < n else None,
    ] + [f"폐기 후보: {c['leaf']} ({c['reason']})" for c in abandon] if a]
    return dict(nodes=n, canonical=(can[0] if can else None), canonical_path=path,
                progress=prog, rejection_ratio=round(len(rejected) / max(1, n), 2),
                rejected=rejected, max_degeneration_depth=stalled,
                frontier=dict(open=open_q, closed=closed_q,
                              close_ratio=round(closed_q / max(1, open_q + closed_q), 2)),
                annotation_coverage=round(annotated / max(1, n), 2),
                laudan=laudan, bayes=bayes, alerts=alerts)
