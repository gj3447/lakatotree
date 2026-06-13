"""트리 지표 — 라카토스(진보율/기각률/퇴행깊이) + 라우든(문제수지/폐기 후보).

순수함수: 입력 = plain dict 리스트 (서버/스크립트/노트북 어디서든 동일 판정).
# KG: span_lakatotree_S1_laudan_layer
"""
from collections import defaultdict
from .laudan import branch_problem_balance_windowed, problem_balance, psr, should_abandon
from .bayes import branch_credence, should_abandon_bayes
from .fertility import predictive_fertility, nobel_grade
from .multiplicity import false_progressive_screen

# THR-1: dialectical 판결(degenerating/withdrawn)도 비진보로 셈 — 전엔 NONPROGRESSIVE 밖이라
# consec/stall 카운터를 리셋(진보로 오인)했다. progressive_conditional 은 (조건부)진보로 PROGRESS 측.
NONPROGRESSIVE = ('rejected', 'partial', 'equivalent', 'degenerating', 'withdrawn')
PROGRESS_VERDICTS = ('progressive', 'progressive_conditional', 'CANONICAL', 'former_canonical')


def _primary_parent(row: dict) -> str | None:
    if row.get('parent'):
        return row.get('parent')
    parents = row.get('parents') or []
    return parents[0] if parents else None


def branch_inputs(nodes: list, frontier: list, leaf: str | None = None,
                  window: int | None = None) -> dict:
    """가지(leaf) 또는 정본 leaf 의 stack/lifecycle 입력 묶음 — 서버/CLI 단일 어댑터.

    반환: verdicts(시간순, delta/noise 동봉) / consecutive_nonprogressive / nodes_spent /
          prediction_hits / problem_balance_windowed / novel_registered_recent /
          canonical_improved_recent / leaf / window.
    """
    from .grounding import GROUNDED
    window = window or GROUNDED['lifecycle_stall_window']['value']
    by = {r['tag']: r for r in nodes}
    if leaf is None:
        can = [r['tag'] for r in nodes if r['verdict'] == 'CANONICAL']
        leaf = can[0] if can else None
    if leaf is None or leaf not in by:
        raise KeyError(f'가지 leaf 없음: {leaf}')
    chain, cur, seen = [], leaf, set()
    while cur and cur not in seen and cur in by:   # leaf→root, 사이클 가드
        seen.add(cur)
        chain.append(by[cur])
        cur = _primary_parent(by[cur])
    seq = []
    for r in reversed(chain):                      # 베이즈는 시간순(root→leaf)
        d = {'verdict': r['verdict']}
        if r.get('metric_value') is not None and r.get('pred_baseline') is not None:
            d['delta'] = r['metric_value'] - r['pred_baseline']
            d['noise_band'] = r.get('pred_noise_band') or 0.0
        seq.append(d)
    consec = 0
    for r in chain:                                # leaf 쪽부터 연속 비진보
        if r['verdict'] in NONPROGRESSIVE:
            consec += 1
        else:
            break
    recent = chain[:window]
    return dict(
        leaf=leaf, window=window, verdicts=seq,
        consecutive_nonprogressive=consec, nodes_spent=len(chain),
        prediction_hits=sum(1 for r in chain if r['verdict'] in PROGRESS_VERDICTS),
        problem_balance_windowed=branch_problem_balance_windowed(chain, frontier,
                                                                 window=window),
        novel_registered_recent=sum(1 for r in recent if r.get('novel_registered')),
        # 'partial' 은 NONPROGRESSIVE(정체/퇴행 신호)이므로 '정본 개선' 으로 세면 안 됨 —
        # 그러면 diverging/harvesting 조기경보(lifecycle)를 부당하게 막는다 (나생문 F1).
        canonical_improved_recent=any(r['verdict'] in PROGRESS_VERDICTS for r in recent),
    )


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
        cur = _primary_parent(by[cur])
    path = path[::-1]
    # 진보율 (같은 scope 의 정본경로 metric)
    prog = None
    # ENG-HON-1: pred_direction 동봉 — improvement_pct 가 방향 무시하면 higher-is-better 진보를
    # 음수로 오보 + 가짜 정체경보 + leaderboard/kuhn 오염. (default 'lower' → 기존 동작 보존)
    pm = [(t, by[t]['metric_value'], by[t].get('metric_scope'), by[t].get('pred_direction') or 'lower')
          for t in path if by[t].get('metric_value') is not None]
    if len(pm) >= 2:
        scopes = defaultdict(list)
        for t, m, sc, d in pm:
            scopes[sc].append((t, m, d))
        sc = max(scopes.values(), key=len)
        if len(sc) >= 2:
            first_m, last_m, direction = sc[0][1], sc[-1][1], sc[0][2]
            gain = (last_m - first_m) if direction == 'higher' else (first_m - last_m)  # 개선=양수
            common = dict(first={'tag': sc[0][0], 'm': first_m},
                          last={'tag': sc[-1][0], 'm': last_m}, direction=direction)
            if first_m != 0:   # 나생문 F-FG-8: first=0 ZeroDivision 가드
                prog = dict(common, improvement_pct=round(100 * gain / abs(first_m), 1))
            else:              # 기준 0 → 절대 증가량(raw last-first, 부호보존)
                prog = dict(common, improvement_pct=None, abs_gain=round(last_m - first_m, 4))
    children = defaultdict(list)
    for r in nodes:
        for parent in (r.get('parents') or ([r.get('parent')] if r.get('parent') else [])):
            children[parent].append(r)
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
            cur2 = _primary_parent(by[cur2])
        consec = 0
        for r in chain:                      # leaf→분기점 방향 연속 비진보
            if r['verdict'] in NONPROGRESSIVE:
                consec += 1
            else:
                break
        hits = sum(1 for r in chain
                   if r['verdict'] in PROGRESS_VERDICTS)
        # gap4: 규칙③ 가동 — per-branch 질문귀속 (노드 questions=연 질문, frontier closed_by=닫은 노드)
        pb_windowed = branch_problem_balance_windowed(chain, frontier)
        ok, reason = should_abandon(consecutive_nonprogressive=consec,
                                    nodes_spent=len(chain), prediction_hits=hits,
                                    problem_balance_windowed=pb_windowed)
        if ok:
            abandon.append(dict(leaf=leaf, branch_len=len(chain), reason=reason))
    laudan = dict(frontier_balance=problem_balance(closed_q, open_q),
                  psr=round(psr(closed_q, len(path)), 3),
                  abandon_candidates=abandon)
    # 베이즈 연속층: 정본 경로 신뢰도 + 저신뢰 가지 (판결 시퀀스 = 증거)
    def verdict_seq(tags):
        out = []
        for t in tags:
            r = by[t]
            d = {'verdict': r['verdict']}
            if r.get('metric_value') is not None and r.get('pred_baseline') is not None:
                d['delta'] = r['metric_value'] - r['pred_baseline']   # 효과크기 → BF 가중
                d['noise_band'] = r.get('pred_noise_band') or 0.0
            out.append(d)
        return out
    can_cred = round(branch_credence(verdict_seq(path)), 3) if path else None
    low_branches = []
    for leaf in leaves:
        if leaf in path:
            continue
        chain, cur3, seen3 = [], leaf, set()
        while cur3 and cur3 not in path and cur3 not in seen3 and cur3 in by:
            seen3.add(cur3); chain.append(cur3); cur3 = _primary_parent(by[cur3])
        ab, c = should_abandon_bayes(verdict_seq(chain[::-1]))
        if ab:
            low_branches.append(dict(leaf=leaf, credence=round(c, 3)))
    bayes = dict(canonical_credence=can_cred, low_credence_branches=low_branches,
                 note='강한 가지는 반례 하나로 안 죽는다 — 신뢰도<0.1 가지만 폐기')
    # 이론 발전성: 정본 경로의 novel 예측 적중 track record (과학=예측력)
    fert = predictive_fertility([by[t] for t in path]) if path else predictive_fertility(nodes)
    fert['nobel_grade'] = nobel_grade(fert)
    fert['note'] = '진보=새 사실을 미리 맞히는 것. nobel_grade=예측 수 충분∧적중률≥0.7'
    # gap8: 다중비교 — improved 판결을 (metric_name, scope) family 별로 BH/Bonferroni 스크린.
    # 판결은 불변(judge 권위) — family 수준 false-progressive 경보만.
    fam = defaultdict(list)
    for r in nodes:
        if (r['verdict'] in ('progressive', 'partial')
                and r.get('metric_value') is not None and r.get('pred_baseline') is not None):
            fam[(r.get('metric_name'), r.get('metric_scope'))].append(dict(
                tag=r['tag'], delta=r['metric_value'] - r['pred_baseline'],
                noise_band=r.get('pred_noise_band') or 0.0,
                direction=r.get('pred_direction') or 'lower'))
    multiplicity = {}
    for key, cands in fam.items():
        if len(cands) < 2:
            continue   # family 1개 = 다중비교 아님
        rep = false_progressive_screen(cands)
        multiplicity['/'.join(str(k) for k in key)] = dict(
            family_size=rep.family_size, untestable=list(rep.untestable),
            survivors_bh=list(rep.survivors_bh),
            survivors_bonferroni=list(rep.survivors_bonferroni), q=rep.q, note=rep.note)
    coverage_backlog = list(cfg.get('coverage_backlog') or [])
    coverage = dict(statement=cfg.get('coverage_statement') or '',
                    backlog=coverage_backlog, backlog_count=len(coverage_backlog),
                    exhaustive=(len(coverage_backlog) == 0))
    alerts = [a for a in [
        f'퇴행 경보: 연속 비진보 깊이 {stalled} ≥3 — 가지 전환 검토' if stalled >= 3 else None,
        '정체 경보: 진보율 ≤0' if prog and prog.get('improvement_pct') is not None
        and prog['improvement_pct'] <= 0 else None,
        '주석 미완 노드 존재' if annotated < n else None,
        f'커버리지 backlog {len(coverage_backlog)}건 — 전수성 주장 금지' if coverage_backlog else None,
    ] + [f"폐기 후보: {c['leaf']} ({c['reason']})" for c in abandon]
      + [f"다중비교 경보({k}): improved {m['family_size']}건 중 BH 생존 {len(m['survivors_bh'])}건"
         for k, m in multiplicity.items() if len(m['survivors_bh']) < m['family_size']] if a]
    return dict(nodes=n, canonical=(can[0] if can else None), canonical_path=path,
                progress=prog, rejection_ratio=round(len(rejected) / max(1, n), 2),
                rejected=rejected, max_degeneration_depth=stalled,
                frontier=dict(open=open_q, closed=closed_q,
                              close_ratio=round(closed_q / max(1, open_q + closed_q), 2)),
                annotation_coverage=round(annotated / max(1, n), 2),
                coverage=coverage, laudan=laudan, bayes=bayes, fertility=fert,
                multiplicity=multiplicity, alerts=alerts)
