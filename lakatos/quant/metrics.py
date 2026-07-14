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
from lakatos.verdicts import FORCEFUL_SOURCES
from lakatos.quant.multiplicity import false_progressive_screen
# verdict 어휘 SSOT — 자체 튜플 하드코딩 제거(lakatos/verdicts.py 가 단일 정본).
from lakatos.verdicts import (PROGRESS_VERDICTS, CONFIRMED_NOVEL_PROGRESS,
                              NONPROGRESSIVE_VERDICTS as NONPROGRESSIVE, force_of_row)


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
            d['noise_band'] = r.get('pred_noise_band')   # 부재(None)와 선언-0을 보존
        seq.append(d)
    consec = 0
    for r in chain:                                # leaf 쪽부터 연속 비진보
        if r['verdict'] in NONPROGRESSIVE:
            consec += 1
        else:
            break
    recent = chain[:window]
    # finding A(2026-07-12): 폐기 규칙③ 은 영수증 있는(verdict_source ∈ FORCEFUL) 닫은 노드가 낸
    # close 만 credit — 무채점 self-report close 가 문제수지를 부풀려 폐기를 면제하는 것을 차단.
    _rtags = {t for t, r in by.items() if r.get('verdict_source') in FORCEFUL_SOURCES}
    return dict(
        leaf=leaf, window=window, verdicts=seq,
        # root→leaf 시간순 정본경로 (tag,verdict) — programme.series 진단의 입력(#5). additive 키.
        path=[{'tag': r['tag'], 'verdict': r['verdict']} for r in reversed(chain)],
        consecutive_nonprogressive=consec, nodes_spent=len(chain),
        # M3: 폐기규칙②·bandit reward 가 묻는 *적중*은 confirmed-novel 진보만(미확증 conditional/
        #     former_canonical 제외) — 넓은 PROGRESS_VERDICTS 로 세면 미확증이 폐기를 면제·reward 오염.
        prediction_hits=sum(1 for r in chain if r['verdict'] in CONFIRMED_NOVEL_PROGRESS),
        problem_balance_windowed=branch_problem_balance_windowed(chain, frontier,
                                                                 window=window,
                                                                 receipted_tags=_rtags),
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
            d['noise_band'] = r.get('pred_noise_band')   # 부재(None)와 선언-0을 보존
        if r.get('pred_closes'):
            d['target'] = r['pred_closes']
        # A2: 출처신뢰를 credence 로 전달 — 전엔 떨궈서 branch_credence 가 항상 1.0(죽은 경로).
        #   source_trust = 노드별 기록 신뢰(float), source = eigentrust 글로벌 맵 바인딩 키(string).
        if r.get('source_trust') is not None:
            d['source_trust'] = r['source_trust']
        if r.get('source') is not None:
            d['source'] = r['source']
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
    # finding A(2026-07-12): 폐기 규칙③ 은 영수증 있는(verdict_source ∈ FORCEFUL) close 만 credit —
    # 무채점 self-report close 가 문제수지를 부풀려 폐기를 면제(조용한 false-retain)하는 것을 차단.
    _rtags = {r.get('tag') for r in tv.nodes if r.get('verdict_source') in FORCEFUL_SOURCES}
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
        # M3: confirmed-novel 진보만 적중 — 미확증 progressive_conditional 을 적중으로 세면 규칙②
        #     (예산 소진 ∧ 적중 0)가 면제돼 degenerating 가지가 무기한 산다(폐기 지연).
        hits = sum(1 for r in chain if r['verdict'] in CONFIRMED_NOVEL_PROGRESS)
        # gap4: 규칙③ — per-branch 질문귀속 (노드 questions=연 질문, frontier closed_by=닫은 노드)
        pb_windowed = branch_problem_balance_windowed(chain, tv.frontier, receipted_tags=_rtags)
        ok, reason = should_abandon(consecutive_nonprogressive=consec, nodes_spent=len(chain),
                                    prediction_hits=hits, problem_balance_windowed=pb_windowed)
        if ok:
            abandon.append(dict(leaf=leaf, branch_len=len(chain), reason=reason))
    return dict(frontier_balance=problem_balance(tv.closed_q, tv.open_q),
                psr=round(psr(tv.closed_q, len(tv.path)), 3), abandon_candidates=abandon,
                # gap4 정직: closed_by 가 노드 tag 에 안 걸린 폐쇄 — rule③ 미집계(과소계상 신호)
                unattributed_closed=unattributed_closures([r['tag'] for r in tv.nodes], tv.frontier))


def _bayes_layer(tv: '_TreeView | list', by: dict | None = None,
                 leaves: list | None = None, source_trust_map: dict | None = None,
                 trust_coverage_mode: str | None = None) -> dict:
    """베이즈 연속층 — 정본경로 신뢰도(판결 시퀀스 사후확률) + 신뢰도<0.1 저신뢰 가지.

    A2: source_trust_map(eigentrust 글로벌 신뢰) 주면 판결의 source 를 그 신뢰로 가중 —
    노드별 source_trust(float)는 _verdict_seq 가 항상 전달, 맵은 그 위 글로벌 override.
    정직성: 맵을 줬는데 경로 판결의 source 가 맵에 없으면 *조용히 1.0 스냅*이 되므로 trust_coverage
    로 매칭 수를 노출(coverage.mode 가 graph_propagated/seed_dominated/uniform_unlearned 를 그대로 운반)."""
    if not isinstance(tv, _TreeView):
        tv = _tv(by=by, path=tv, leaves=leaves)
    can_seq = _verdict_seq(tv, tv.path) if tv.path else []
    can_cred = round(branch_credence(can_seq, source_trust_map=source_trust_map), 3) if tv.path else None
    low_branches = []
    for leaf in tv.leaves:
        if leaf in tv.path:
            continue
        chain = _branch_chain(tv, leaf)           # leaf→분기점
        ab, c = should_abandon_bayes(_verdict_seq(tv, [r['tag'] for r in chain][::-1]),
                                     source_trust_map=source_trust_map)
        if ab:
            low_branches.append(dict(leaf=leaf, credence=round(c, 3)))
    path_sources = sum(1 for d in can_seq if 'source' in d)
    matched = sum(1 for d in can_seq if source_trust_map and d.get('source') in source_trust_map)
    trust_coverage = dict(
        map_supplied=bool(source_trust_map),
        mode=trust_coverage_mode or ('graph_supplied' if source_trust_map else 'none'),
        path_sources=path_sources, path_sources_matched=matched)
    return dict(canonical_credence=can_cred, low_credence_branches=low_branches,
                trust_coverage=trust_coverage,
                note='강한 가지는 반례 하나로 안 죽는다 — 신뢰도<0.1 가지만 폐기')


def _fertility_layer(tv: '_TreeView | list', by: dict | None = None,
                     nodes: list | None = None) -> dict:
    """이론 발전성 — 정본경로 novel 예측 적중 track record (과학=예측력). nobel_grade 동봉."""
    if not isinstance(tv, _TreeView):
        tv = _tv(nodes=nodes, by=by, path=tv)
    # G5: 스코프 명시 — tree_metrics 는 정본경로(canonical_path) 발전성. path 없으면 all_nodes 로 폴백(라벨도 그렇게).
    fert = (predictive_fertility([tv.by[t] for t in tv.path], scope='canonical_path')
            if tv.path else predictive_fertility(tv.nodes, scope='all_nodes'))
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


def _anchored_ratio(nodes: list) -> dict:
    """P0b(ManifestoGap R8): cross-metric novel 판결(novel_server_anchored 필드 보유) 중 *서버앵커*
    비율 — FF1 이 default-ON(신규 anchored 트리)인지, 아니면 novel 이 client float 한 줄로 서는지의
    단일 관측. 분모 = novel_server_anchored 가 판정된 노드(True/False), 분자 = True. G5 단일 프로젝터."""
    judged = [r for r in nodes if r.get('novel_server_anchored') is not None]
    anchored = sum(1 for r in judged if r.get('novel_server_anchored'))
    return dict(scope='all_nodes', novel_measured=len(judged), server_anchored=anchored,
                anchored_ratio=round(anchored / len(judged), 3) if judged else None,
                note='cross-metric novel 중 서버앵커 영수증 보유 비율(FF1 default-ON 관측). '
                     'None=novel 판정 노드 없음.')


def _multiplicity_screen(nodes: list) -> dict:
    """gap8 다중비교 — metric-improved 판결을 family 별 BH/Bonferroni 스크린.

    ``progressive_unverified``는 프로그램 진전축에서는 중립이지만 metric-progress 자체는
    실재하므로 다중비교 후보에서 빼지 않는다. 판결은 불변이고 family 경보만 산출한다.
    """
    fam = defaultdict(list)
    for r in nodes:
        if (r['verdict'] in ('progressive', 'progressive_unverified', 'partial')
                and r.get('metric_value') is not None and r.get('pred_baseline') is not None):
            fam[(r.get('metric_name'), r.get('metric_scope'))].append(dict(
                tag=r['tag'], delta=r['metric_value'] - r['pred_baseline'],
                noise_band=r.get('pred_noise_band'),   # 부재(None)와 선언-0을 보존
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
    """커버리지 — 명시 scope 없이 전수성을 만들지 않는 fail-closed projection."""
    from lakatos.coverage import resolve_coverage_status

    backlog = list(cfg.get('coverage_backlog') or [])
    statement = cfg.get('coverage_statement') or ''
    status = resolve_coverage_status(
        cfg.get('coverage_status'), statement=statement, backlog=backlog)
    return dict(status=status, statement=statement, backlog=backlog,
                backlog_count=len(backlog), exhaustive=(status == 'exhaustive'))


def _assemble_alerts(*, stalled: int, prog: dict | None, annotated: int, n: int,
                     coverage: dict, abandon: list, multiplicity: dict) -> list:
    """경보 조립 — 퇴행/정체/주석미완/커버리지/폐기후보/다중비교를 사람 읽는 문자열로."""
    base = [
        f'퇴행 경보: 연속 비진보 깊이 {stalled} ≥3 — 가지 전환 검토' if stalled >= 3 else None,
        '정체 경보: 진보율 ≤0' if prog and prog.get('improvement_pct') is not None
        and prog['improvement_pct'] <= 0 else None,
        '주석 미완 노드 존재' if annotated < n else None,
        f"커버리지 backlog {len(coverage['backlog'])}건 — 전수성 주장 금지"
        if coverage['backlog'] else None,
        '커버리지 범위 미검증 — 전수성 주장 금지'
        if not coverage['backlog'] and coverage['status'] == 'unknown' else None,
        '커버리지 partial 선언 — 전수성 주장 금지'
        if not coverage['backlog'] and coverage['status'] == 'partial' else None,
    ]
    base += [f"폐기 후보: {c['leaf']} ({c['reason']})" for c in abandon]
    base += [f"다중비교 경보({k}): improved {m['family_size']}건 중 BH 생존 {len(m['survivors_bh'])}건"
             for k, m in multiplicity.items() if len(m['survivors_bh']) < m['family_size']]
    return [a for a in base if a]


def tree_metrics(nodes: list, frontier: list, cfg: dict | None = None) -> dict:
    """트리 지표 오케스트레이터 — 공유 구조 1회 계산 후 각 지표 개념을 자기 함수에 위임.
    (개념별 분해는 위 `_*_layer`/`_*_metric`/`_*_screen` 참조 — 한 개념 = 한 함수.)"""
    cfg = cfg or {}
    # prom-honesty (R2→정본 결정 2026-06-21): 진보어휘(PROGRESS_VERDICTS) verdict 인데 verdict_source 가
    #   *명시적으로* 비어있는(None/'') 노드 = 노드 self-report 로 들어온 미채점 진보 = *재독 불가 영수증*.
    #   ooptdd 하드코어의 3치 논리(LTL3 present/absent/INCONCLUSIVE)에 따라 이는 inconclusive — pass(진보)도
    #   fail(기각)도 아니다. ∴ DEFAULT 로 positive 진보 집계(canonical anchor/진보율/fertility)에서 *제외*하고
    #   provenance 로 surface(영수증 없는 green=거짓말; 울프람 '추측 말고 돌려라'→재검증으로 inconclusive 해소).
    #   비파괴(노드 보존)·가역: cfg.provenance_lenient=True 면 옛 동작(집계 포함)으로 opt-out(append-only 존중).
    #   ★key 부재=레거시/테스트 픽스처는 신뢰(집계 — 실 KG 읽기만 verdict_source 키를 싣는다, read_models RETURN).
    inconclusive = [r['tag'] for r in nodes if force_of_row(r) == 'INCONCLUSIVE']   # SSOT: verdicts.force_of
    lenient = bool(cfg.get('provenance_lenient'))
    if inconclusive and not lenient:
        _inc = set(inconclusive)
        nodes = [r if r['tag'] not in _inc else {**r, 'verdict': '_inconclusive_unscored'} for r in nodes]
    by = {r['tag']: r for r in nodes}
    n = len(nodes)
    path = _canonical_path(nodes, by)
    children = _children_index(nodes)
    leaves = [r['tag'] for r in nodes if r['tag'] not in children]
    can = [r['tag'] for r in nodes if r['verdict'] == 'CANONICAL']
    rejected = [r['tag'] for r in nodes if r['verdict'] == 'rejected']
    open_q = sum(1 for q in frontier if q['status'] == 'OPEN')
    closed_q = sum(1 for q in frontier if q['status'] == 'CLOSED')
    # R7: receipted close — closed_by 노드가 영수증(FORCEFUL) 판결을 실제로 보유한 close 만 분자.
    #   무채점(draft/미존재) closer 의 close 는 unreceipted 로 세분(기존 close_ratio 는 불변 병행).
    _by_tag = {r.get('tag'): r for r in nodes}
    receipted_closed_q = sum(
        1 for q in frontier if q['status'] == 'CLOSED'
        and any((_by_tag.get(cb) or {}).get('verdict_source') in FORCEFUL_SOURCES
                for cb in (q.get('closed_by') or [])))
    annotated = sum(1 for r in nodes
                    if r.get('algorithm') and r.get('comment') and r.get('limitation'))
    # 공유 트리 구조 1회 계산 → 각 지표 함수는 tv 하나만 받는다(결합을 1급 객체로).
    tv = _TreeView(nodes=nodes, frontier=frontier, by=by, path=path, children=children,
                   leaves=leaves, open_q=open_q, closed_q=closed_q)

    prog = _progress_metric(tv)
    stalled = _degeneration_depth(tv)
    laudan = _laudan_layer(tv)
    # A2: eigentrust 글로벌 신뢰 맵을 cfg 로 받아 credence 가중에 전달(기본 None=레거시 비트동일).
    #   서버 seam(read_models.compute_tree_metrics)이 global_source_trust 로 맵+mode 를 구성해 주입.
    bayes = _bayes_layer(tv, source_trust_map=cfg.get('source_trust_map'),
                         trust_coverage_mode=cfg.get('trust_coverage_mode'))
    fert = _fertility_layer(tv)
    eureka = _eureka_layer(tv)
    anchored = _anchored_ratio(nodes)   # P0b(MG R8): cross-metric novel 중 서버앵커 비율
    multiplicity = _multiplicity_screen(nodes)
    coverage = _coverage(cfg)
    alerts = _assemble_alerts(stalled=stalled, prog=prog, annotated=annotated, n=n,
                              coverage=coverage,
                              abandon=laudan['abandon_candidates'], multiplicity=multiplicity)
    if inconclusive:
        alerts = [*alerts, (
            f"영수증 없는 green: 진보어휘 노드 {len(inconclusive)}개가 verdict_source 없이 self-report = inconclusive "
            + ("→ 진보 집계서 제외(재검증=run the receipt 로 해소). provenance 참조" if not lenient
               else "이지만 lenient 모드라 집계에 포함됨(green 부풀림 — 주의)"))]

    if anchored.get('anchored_ratio') is not None and anchored['anchored_ratio'] < 1.0:
        _drift = anchored['novel_measured'] - anchored['server_anchored']
        alerts = [*alerts, f"서버앵커 안 된 novel {_drift}건 — cross-metric novel 이 client float 로 "
                           f"섰다(P3b notebook-drift: FF1 default-ON 미적용/legacy tier). anchored_ratio="
                           f"{anchored['anchored_ratio']}"]
    if closed_q - receipted_closed_q > 0:
        alerts = [*alerts, f"영수증 없는 close {closed_q - receipted_closed_q}건 — closed_by 가 무채점 "
                           f"노드(close_ratio 는 유지, close_ratio_receipted 로 세분 공시; 재귀속은 ADR+GO)"]
    return dict(nodes=n, canonical=(can[0] if can else None), canonical_path=path,
                progress=prog, rejection_ratio=round(len(rejected) / max(1, n), 2),
                rejected=rejected, max_degeneration_depth=stalled,
                frontier=dict(open=open_q, closed=closed_q,
                              close_ratio=round(closed_q / max(1, open_q + closed_q), 2),
                              # R7: 병행 공시(기존 close_ratio 비파괴) — 분자 = CLOSED 중 closed_by
                              # 노드가 영수증(FORCEFUL) 판결 보유. 무채점 close 가 Pareto/close_ratio 를
                              # 떠받치는 왜곡을 사실로 노출한다(재귀속은 ADR+user GO 별도).
                              close_ratio_receipted=round(
                                  receipted_closed_q / max(1, open_q + closed_q), 2),
                              unreceipted_closes=closed_q - receipted_closed_q),
                annotation_coverage=round(annotated / max(1, n), 2),
                coverage=coverage, laudan=laudan, bayes=bayes, fertility=fert,
                eureka=eureka, anchored=anchored, multiplicity=multiplicity, alerts=alerts,
                provenance=dict(inconclusive_progress=inconclusive, count=len(inconclusive),
                                mode=('lenient-counted' if lenient else 'inconclusive-excluded')))
