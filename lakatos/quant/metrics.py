"""트리 지표 — 라카토스(진보율/기각률/퇴행깊이) + 라우든(문제수지/폐기 후보).

순수함수: 입력 = plain dict 리스트 (서버/스크립트/노트북 어디서든 동일 판정).

★구조(SOLID/SRP): `tree_metrics` 는 *오케스트레이터* — 정본경로·children·leaves 를 한 번 계산하고,
각 지표 *개념*을 자기 이름의 순수함수(`_progress_metric`/`_degeneration_depth`/`_laudan_layer`/
`_bayes_layer`/`_fertility_layer`/`_eureka_layer`/`_multiplicity_screen`/`_assemble_alerts` …)에
위임한다. 한 개념 = 한 함수 = 한 테스트(의미량과 코드량 1:1). 전엔 158-LOC 한 함수에 12 개념이
뭉쳐 있었다(SRP 위반) → 동작 불변 분해(test_metrics 가 영수증).
# KG: span_lakatotree_S1_laudan_layer
"""
from collections import defaultdict
from dataclasses import dataclass
from lakatos.quant.laudan import (branch_problem_balance_windowed, problem_balance, psr, should_abandon,
                     unattributed_closures)
from lakatos.quant.bayes import branch_credence, should_abandon_bayes
from lakatos.quant.fertility import predictive_fertility, nobel_grade
from lakatos.eureka import eureka_over_tree
from lakatos.quant.multiplicity import false_progressive_screen
# verdict 어휘 SSOT — 자체 튜플 하드코딩 제거(lakatos/verdicts.py 가 단일 정본).
from lakatos.verdicts import PROGRESS_VERDICTS, NONPROGRESSIVE_VERDICTS as NONPROGRESSIVE


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
    from lakatos.grounding import GROUNDED
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


# ── 공유 구조 (정본경로 · children · leaves) — 오케스트레이터가 한 번 계산 ──────────────
@dataclass(frozen=True)
class _TreeView:
    """tree_metrics 가 1회 계산해 각 지표 함수에 넘기는 *공유 트리 구조*. 분해가 드러낸 shared-state
    결합을 1급 객체로 — 전엔 _laudan_layer 가 nodes/frontier/path/by/leaves/open_q/closed_q 7개 개별
    param 으로 받아 결합이 시그니처에 그대로 노출됐다. 각 지표 함수는 이제 tv 하나만 받는다."""
    nodes: list
    frontier: list
    by: dict
    path: list
    children: dict
    leaves: list
    open_q: int
    closed_q: int


def _tv(*, nodes: list | None = None, frontier: list | None = None, by: dict | None = None,
        path: list | None = None, children: dict | None = None, leaves: list | None = None,
        open_q: int = 0, closed_q: int = 0) -> _TreeView:
    by = by or {}
    nodes = list(nodes) if nodes is not None else list(by.values())
    return _TreeView(nodes=nodes, frontier=frontier or (), by=by, path=path or (),
                     children=children or {}, leaves=leaves or (),
                     open_q=open_q, closed_q=closed_q)


def _canonical_path(nodes: list, by: dict) -> list:
    """정본(CANONICAL) leaf → root 사이클가드 walk. root→leaf 순 반환. (tv 빌더 — tv 이전 실행.)"""
    can = [r['tag'] for r in nodes if r['verdict'] == 'CANONICAL']
    path, cur, seen = [], (can[0] if can else None), set()
    while cur and cur not in seen and cur in by:   # 사이클 가드(나생문 F-FG-3)
        seen.add(cur)
        path.append(cur)
        cur = _primary_parent(by[cur])
    return path[::-1]


def _children_index(nodes: list) -> dict:
    """parent tag → 자식 노드 리스트 (다중부모 DAG 지원)."""
    children = defaultdict(list)
    for r in nodes:
        for parent in (r.get('parents') or ([r.get('parent')] if r.get('parent') else [])):
            children[parent].append(r)
    return children


def _verdict_seq(tv: '_TreeView | list', tags: list | dict) -> list:
    """판결 시퀀스 → branch_credence 입력. delta/noise(효과크기) + target(use-novelty dedup 키) 동봉.
    target = 닫는 질문(novel target 정체성) — 같은 질문 재확증은 branch_credence 가 content-dedup."""
    if not isinstance(tv, _TreeView):
        tv, tags = _tv(by=tags, path=tv), tv
    out = []
    for t in tags:
        r = tv.by[t]
        d = {'verdict': r['verdict']}
        if r.get('metric_value') is not None and r.get('pred_baseline') is not None:
            d['delta'] = r['metric_value'] - r['pred_baseline']   # 효과크기 → BF 가중
            d['noise_band'] = r.get('pred_noise_band') or 0.0
        if r.get('pred_closes'):
            d['target'] = r['pred_closes']
        out.append(d)
    return out


# ── 지표 개념별 순수함수 (한 개념 = 한 함수 = 한 테스트) ──────────────────────────────
def _progress_metric(tv: '_TreeView | list', by: dict | None = None) -> dict | None:
    """진보율 — 같은 scope 정본경로의 metric 개선 %. 방향 인식(ENG-HON-1) + first=0 가드(F-FG-8)."""
    if not isinstance(tv, _TreeView):
        tv = _tv(by=by, path=tv)
    by = tv.by
    pm = [(t, by[t]['metric_value'], by[t].get('metric_scope'), by[t].get('pred_direction') or 'lower')
          for t in tv.path if by[t].get('metric_value') is not None]
    if len(pm) < 2:
        return None
    scopes = defaultdict(list)
    for t, m, sc, d in pm:
        scopes[sc].append((t, m, d))
    # dogfood: 다중 scope 중 노드 최다 scope 측정 + *어느 scope 인지* 정직 표기. tie 면 이름순(결정성).
    scope_name = max(scopes, key=lambda k: (len(scopes[k]), str(k)))
    sc = scopes[scope_name]
    if len(sc) < 2:
        return None
    first_m, last_m, direction = sc[0][1], sc[-1][1], sc[0][2]
    gain = (last_m - first_m) if direction == 'higher' else (first_m - last_m)   # 개선=양수
    common = dict(first={'tag': sc[0][0], 'm': first_m},
                  last={'tag': sc[-1][0], 'm': last_m}, direction=direction, scope=scope_name)
    if first_m != 0:
        return dict(common, improvement_pct=round(100 * gain / abs(first_m), 1))
    return dict(common, improvement_pct=None, abs_gain=round(last_m - first_m, 4))   # 기준 0 → 절대증가


def _degeneration_depth(tv: '_TreeView | list', children: dict | None = None) -> int:
    """퇴행 깊이 — 정본경로 노드들의 최대 연속 비진보 자식 체인 (≥3 경보)."""
    if not isinstance(tv, _TreeView):
        tv = _tv(path=tv, children=children)
    def depth(tag, _seen=None):
        _seen = _seen or set()
        if tag in _seen:
            return 0                              # 사이클 가드(나생문 F-FG-3)
        _seen = _seen | {tag}
        return max([1 + depth(c['tag'], _seen) for c in tv.children.get(tag, [])
                    if c['verdict'] in NONPROGRESSIVE], default=0)
    return max([depth(t) for t in tv.path], default=0)


def _branch_chain(tv: '_TreeView | str', leaf: str | list, by: dict | None = None) -> list:
    """leaf → (정본경로 만나기 전까지) 분기 가지 노드 리스트, 사이클 가드."""
    if not isinstance(tv, _TreeView):
        tv, leaf = _tv(by=by, path=leaf), tv
    chain, cur, seen = [], leaf, set()
    while cur and cur not in tv.path and cur not in seen and cur in tv.by:
        seen.add(cur)
        chain.append(tv.by[cur])
        cur = _primary_parent(tv.by[cur])
    return chain


def _laudan_layer(tv: '_TreeView | list', frontier: list | None = None,
                  path: list | None = None, by: dict | None = None,
                  leaves: list | None = None, open_q: int = 0,
                  closed_q: int = 0) -> dict:
    """라우든 문제해결력층 — 가지별 폐기 후보(should_abandon 3규칙) + 문제수지 + PSR + 미귀속 폐쇄."""
    if not isinstance(tv, _TreeView):
        tv = _tv(nodes=tv, frontier=frontier, by=by, path=path, leaves=leaves,
                 open_q=open_q, closed_q=closed_q)
    abandon = []
    for leaf in tv.leaves:
        if leaf in tv.path:
            continue
        chain = _branch_chain(tv, leaf)
        consec = 0
        for r in chain:                          # leaf→분기점 방향 연속 비진보
            if r['verdict'] in NONPROGRESSIVE:
                consec += 1
            else:
                break
        hits = sum(1 for r in chain if r['verdict'] in PROGRESS_VERDICTS)
        # gap4: 규칙③ — per-branch 질문귀속 (노드 questions=연 질문, frontier closed_by=닫은 노드)
        pb_windowed = branch_problem_balance_windowed(chain, tv.frontier)
        ok, reason = should_abandon(consecutive_nonprogressive=consec, nodes_spent=len(chain),
                                    prediction_hits=hits, problem_balance_windowed=pb_windowed)
        if ok:
            abandon.append(dict(leaf=leaf, branch_len=len(chain), reason=reason))
    return dict(frontier_balance=problem_balance(tv.closed_q, tv.open_q),
                psr=round(psr(tv.closed_q, len(tv.path)), 3), abandon_candidates=abandon,
                # gap4 정직: closed_by 가 노드 tag 에 안 걸린 폐쇄 — rule③ 미집계(과소계상 신호)
                unattributed_closed=unattributed_closures([r['tag'] for r in tv.nodes], tv.frontier))


def _bayes_layer(tv: '_TreeView | list', by: dict | None = None,
                 leaves: list | None = None) -> dict:
    """베이즈 연속층 — 정본경로 신뢰도(판결 시퀀스 사후확률) + 신뢰도<0.1 저신뢰 가지."""
    if not isinstance(tv, _TreeView):
        tv = _tv(by=by, path=tv, leaves=leaves)
    can_cred = round(branch_credence(_verdict_seq(tv, tv.path)), 3) if tv.path else None
    low_branches = []
    for leaf in tv.leaves:
        if leaf in tv.path:
            continue
        chain = _branch_chain(tv, leaf)           # leaf→분기점
        ab, c = should_abandon_bayes(_verdict_seq(tv, [r['tag'] for r in chain][::-1]))
        if ab:
            low_branches.append(dict(leaf=leaf, credence=round(c, 3)))
    return dict(canonical_credence=can_cred, low_credence_branches=low_branches,
                note='강한 가지는 반례 하나로 안 죽는다 — 신뢰도<0.1 가지만 폐기')


def _fertility_layer(tv: '_TreeView | list', by: dict | None = None,
                     nodes: list | None = None) -> dict:
    """이론 발전성 — 정본경로 novel 예측 적중 track record (과학=예측력). nobel_grade 동봉."""
    if not isinstance(tv, _TreeView):
        tv = _tv(nodes=nodes, by=by, path=tv)
    fert = predictive_fertility([tv.by[t] for t in tv.path]) if tv.path else predictive_fertility(tv.nodes)
    fert['nobel_grade'] = nobel_grade(fert)
    fert['note'] = '진보=새 사실을 미리 맞히는 것. nobel_grade=예측 수 충분∧적중률≥0.7'
    return fert


def _eureka_layer(tv: '_TreeView | list', by: dict | None = None,
                  nodes: list | None = None) -> dict:
    """eureka(measurement-grade) — novel 예측 중 *측정 red* 통과 비율 = true/felt. BF substantial +
    문제수지>0 게이트를 fertility 위에 더 건 엄격본. standing(promotion)은 별도 층이라 제외."""
    if not isinstance(tv, _TreeView):
        tv = _tv(nodes=nodes, by=by, path=tv)
    return eureka_over_tree([tv.by[t] for t in tv.path]) if tv.path else eureka_over_tree(tv.nodes)


def _multiplicity_screen(nodes: list) -> dict:
    """gap8 다중비교 — improved 판결을 (metric_name, scope) family 별 BH/Bonferroni 스크린.
    판결은 불변(judge 권위) — family 수준 false-progressive 경보만."""
    fam = defaultdict(list)
    for r in nodes:
        if (r['verdict'] in ('progressive', 'partial')
                and r.get('metric_value') is not None and r.get('pred_baseline') is not None):
            fam[(r.get('metric_name'), r.get('metric_scope'))].append(dict(
                tag=r['tag'], delta=r['metric_value'] - r['pred_baseline'],
                noise_band=r.get('pred_noise_band') or 0.0,
                direction=r.get('pred_direction') or 'lower'))
    out = {}
    for key, cands in fam.items():
        if len(cands) < 2:
            continue   # family 1개 = 다중비교 아님
        rep = false_progressive_screen(cands)
        out['/'.join(str(k) for k in key)] = dict(
            family_size=rep.family_size, untestable=list(rep.untestable),
            survivors_bh=list(rep.survivors_bh),
            survivors_bonferroni=list(rep.survivors_bonferroni), q=rep.q, note=rep.note)
    return out


def _coverage(cfg: dict) -> dict:
    """커버리지 — 전수성 backlog 강제 노출(과장 방지)."""
    backlog = list(cfg.get('coverage_backlog') or [])
    return dict(statement=cfg.get('coverage_statement') or '', backlog=backlog,
                backlog_count=len(backlog), exhaustive=(len(backlog) == 0))


def _assemble_alerts(*, stalled: int, prog: dict | None, annotated: int, n: int,
                     coverage_backlog: list, abandon: list, multiplicity: dict) -> list:
    """경보 조립 — 퇴행/정체/주석미완/커버리지/폐기후보/다중비교를 사람 읽는 문자열로."""
    base = [
        f'퇴행 경보: 연속 비진보 깊이 {stalled} ≥3 — 가지 전환 검토' if stalled >= 3 else None,
        '정체 경보: 진보율 ≤0' if prog and prog.get('improvement_pct') is not None
        and prog['improvement_pct'] <= 0 else None,
        '주석 미완 노드 존재' if annotated < n else None,
        f'커버리지 backlog {len(coverage_backlog)}건 — 전수성 주장 금지' if coverage_backlog else None,
    ]
    base += [f"폐기 후보: {c['leaf']} ({c['reason']})" for c in abandon]
    base += [f"다중비교 경보({k}): improved {m['family_size']}건 중 BH 생존 {len(m['survivors_bh'])}건"
             for k, m in multiplicity.items() if len(m['survivors_bh']) < m['family_size']]
    return [a for a in base if a]


def tree_metrics(nodes: list, frontier: list, cfg: dict | None = None) -> dict:
    """트리 지표 오케스트레이터 — 공유 구조 1회 계산 후 각 지표 개념을 자기 함수에 위임.
    (개념별 분해는 위 `_*_layer`/`_*_metric`/`_*_screen` 참조 — 한 개념 = 한 함수.)"""
    cfg = cfg or {}
    by = {r['tag']: r for r in nodes}
    n = len(nodes)
    path = _canonical_path(nodes, by)
    children = _children_index(nodes)
    leaves = [r['tag'] for r in nodes if r['tag'] not in children]
    can = [r['tag'] for r in nodes if r['verdict'] == 'CANONICAL']
    rejected = [r['tag'] for r in nodes if r['verdict'] == 'rejected']
    open_q = sum(1 for q in frontier if q['status'] == 'OPEN')
    closed_q = sum(1 for q in frontier if q['status'] == 'CLOSED')
    annotated = sum(1 for r in nodes
                    if r.get('algorithm') and r.get('comment') and r.get('limitation'))
    # 공유 트리 구조 1회 계산 → 각 지표 함수는 tv 하나만 받는다(결합을 1급 객체로).
    tv = _TreeView(nodes=nodes, frontier=frontier, by=by, path=path, children=children,
                   leaves=leaves, open_q=open_q, closed_q=closed_q)

    prog = _progress_metric(tv)
    stalled = _degeneration_depth(tv)
    laudan = _laudan_layer(tv)
    bayes = _bayes_layer(tv)
    fert = _fertility_layer(tv)
    eureka = _eureka_layer(tv)
    multiplicity = _multiplicity_screen(nodes)
    coverage = _coverage(cfg)
    alerts = _assemble_alerts(stalled=stalled, prog=prog, annotated=annotated, n=n,
                              coverage_backlog=coverage['backlog'],
                              abandon=laudan['abandon_candidates'], multiplicity=multiplicity)

    return dict(nodes=n, canonical=(can[0] if can else None), canonical_path=path,
                progress=prog, rejection_ratio=round(len(rejected) / max(1, n), 2),
                rejected=rejected, max_degeneration_depth=stalled,
                frontier=dict(open=open_q, closed=closed_q,
                              close_ratio=round(closed_q / max(1, open_q + closed_q), 2)),
                annotation_coverage=round(annotated / max(1, n), 2),
                coverage=coverage, laudan=laudan, bayes=bayes, fertility=fert,
                eureka=eureka, multiplicity=multiplicity, alerts=alerts)
