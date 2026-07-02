"""인터넷 출처 신뢰 — 라카토트리가 인터넷 증거에 정량 신뢰가중을 단다 (P1: 인터넷 엮기).

골방 연구가 아니라 기존 웹 신뢰 시스템과 연결: TrustRank(시드 전파) + EigenTrust(고유벡터).
증거(웹 citation)는 출처 신뢰를 달고 베이즈층 P(E|H) 에 결합 — 권위 출처 = 강한 증거.
출처: Kamvar et al. EigenTrust(WWW 2003), Gyöngyi et al. TrustRank(VLDB 2004).
# KG: span_lakatotree_trust
"""


from urllib.parse import urlparse

from lakatos.grounding import GROUNDED   # T-H-1: damping/alpha 단일 정본(하드코딩 금지 — drift/G5 우회 방지)


def trustrank(graph: dict, seeds: dict, damping: float = GROUNDED['pagerank_damping']['value'],
              iters: int = 50) -> dict:
    """TrustRank — 시드(신뢰 페이지)에서 biased PageRank 로 신뢰 전파.

    graph = {node: [out-neighbors]}, seeds = {node: trust}. teleport = 시드 분포.
    """
    nodes = set(graph) | {v for outs in graph.values() for v in outs} | set(seeds)
    nodes = list(nodes)
    n = len(nodes)
    if n == 0:
        return {}
    sseed = sum(seeds.values()) or 1.0
    tele = {x: seeds.get(x, 0.0) / sseed for x in nodes}
    tr = {x: tele[x] for x in nodes}
    for _ in range(iters):
        nxt = {x: (1 - damping) * tele[x] for x in nodes}
        for u in nodes:
            outs = graph.get(u, [])
            if outs:
                share = damping * tr[u] / len(outs)
                for v in outs:
                    nxt[v] += share
            else:   # dangling → 시드로 환원
                for v in nodes:
                    nxt[v] += damping * tr[u] * tele[v]
        tr = nxt
    return tr


def eigentrust(local_trust: dict, pre_trusted: dict,
               alpha: float = GROUNDED['eigentrust_alpha']['value'],
               iters: int = 100) -> dict:
    """EigenTrust — 전이적 신뢰의 principal left eigenvector. 글로벌 신뢰 = 정규화 벡터.

    local_trust = {i: {j: c_ij}} (i 가 j 를 믿는 정도), pre_trusted = 시드(sybil 저항).
    t = (1-alpha) C^T t + alpha p,  C 는 행정규화 local trust.
    """
    nodes = set(local_trust) | {j for d in local_trust.values() for j in d} | set(pre_trusted)
    nodes = list(nodes)
    n = len(nodes)
    if n == 0:
        return {}
    sp0 = sum(pre_trusted.values()) or 1.0
    pre_trusted = {x: pre_trusted.get(x, 0.0) / sp0 for x in nodes}
    C = {}   # 행정규화 (i 의 신뢰 합 = 1)
    for i in nodes:
        row = local_trust.get(i, {})
        s = sum(max(v, 0.0) for v in row.values())
        if s > 0:
            C[i] = {j: max(row.get(j, 0.0), 0.0) / s for j in row}
        else:
            C[i] = {x: pre_trusted.get(x, 0.0) for x in nodes}   # 나생문 F-MATH-3: dangling→pre-trusted 재분배
    p = dict(pre_trusted)   # 이미 정규화됨
    t = {x: p[x] if any(p.values()) else 1.0 / n for x in nodes}
    for _ in range(iters):
        nxt = {x: alpha * p[x] for x in nodes}
        for i in nodes:
            for j, cij in C[i].items():
                nxt[j] += (1 - alpha) * t[i] * cij
        s = sum(nxt.values()) or 1.0
        t = {x: nxt[x] / s for x in nodes}
    return t


def evidence_weight(source_trust: float | None, floor: float = 0.0) -> float:
    """출처 신뢰 → 증거 가중 [floor, 1]. 베이즈 BF 지수에 곱해 P(E|H) 결합.

    나생문 F-MATH-4: floor=0 → zero-trust(junk) 출처는 무정보(BF=1), credence 안 움직임.
    G8(git-흡수 2026-07-02, 크래시 봉합): source_trust=None(라이브 데이터에 실재 — repository 가 raw None
    통과)이면 min(1.0, None) 이 TypeError → tree_metrics 500(333v2·ice-orca-dragon 재현). git fsck 정신:
    부패 입력은 crash 가 아니라 *안전 강등*(None = 무신뢰 = 가중 0, fail-safe). 이는 크래시-안전이지 trust
    *기본값 정책*(FF5b: absent 키 default) 이 아니다 — 여기선 present-but-None 만 fail-safe 로 중립화한다.
    """
    st = 0.0 if source_trust is None else source_trust
    return floor + (1.0 - floor) * max(0.0, min(1.0, st))


# ── P6 배선: eigentrust/trustrank 를 *실* observation 그래프에 돌려 글로벌 출처신뢰 산출 ──
#  전엔 trustrank/eigentrust 가 library 함수일 뿐 런타임 미배선이었다(THEORY §6 LKT-T1, P6).
#  여기서 실 데이터로 그래프를 짓는다 — 장식이 아니라 실 seed/edge:
#    seed(pre-trusted) = 권위 source_type 관측 (primary/peer-reviewed/official = 문헌급 앵커)
#    edge             = 같은 노드(주장)를 함께 받치는 관측끼리 corroboration 상호신뢰
#  정직: 관측이 적거나 edge 가 없으면 그래프는 seed-dominated → coverage 라벨로 명시(숨김 금지).
AUTHORITATIVE_SOURCE_TYPES = (
    'primary', 'peer_reviewed', 'peer-reviewed', 'official', 'official_docs',
    'standard', 'specification', 'textbook', 'literature',
)

# 권위 seed 분류는 *URL 도메인*(서버 검증 가능 allowlist)으로 — client 의 source_type 라벨이 아니라.
#   R3 발견(prom-honesty): 인터넷 관측에 source_type='peer_reviewed' 자기선언만으로 pre-trusted eigentrust
#   seed 를 위조할 수 있었다. URL 도메인은 클라가 특정 *실제* 출판사 URL 에 commit 해야 하고, 그 문자열의
#   진위는 후속 url+content_hash 재fetch(world_gates G-Web/Part A)가 닫는다 — 라벨보다 위조면이 좁다.
#   (research_import._source_type 의 권위 도메인을 미러; 이 모듈은 leaf 라 도메인 상수를 자체 보유.)
_AUTHORITATIVE_URL_DOMAINS = (
    'sciencedirect.com', 'springer.com', 'frontiersin.org', 'ncbi.nlm.nih.gov',
    'openaccess.thecvf.com', 'mvtec.com',                 # 1차/peer-reviewed 출판사·벤더 공식문서
    'ietf.org', 'w3.org', 'iso.org', 'iec.ch',            # 표준화 기구(official anchor)
)


def _host(url: str) -> str:
    """URL → 소문자 host(끝점 제거). scheme 없으면 '//' 붙여 netloc 으로 파싱."""
    u = url or ''
    if '://' not in u:
        u = '//' + u
    return (urlparse(u).hostname or '').lower().rstrip('.')


def authoritative_url(url: str) -> bool:
    """URL 의 *host* 가 서버검증 권위 도메인이면 True(eigentrust pre-trusted seed 자격).

    ★host 경계로 매칭한다 — substring 매칭은 도메인 스푸핑에 뚫린다(적대 재검증 2026-06-21):
      sciencedirect.com.attacker.com / evil.com?ref=ietf.org / attacker.com/iso.org 모두 'in url' 은 참이나
      권위 출처가 아니다. host==domain 또는 host.endswith('.'+domain) 만 인정.
    client 가 자기선언하는 source_type 라벨과 달리 도메인은 외부 referent 에 commit 한다 — 잔여
    forge(URL 문자열 자체가 client 공급)는 G-Web 재fetch 가 닫는다(world_gates Part A, 미구현).
    """
    host = _host(url)
    if not host:
        return False
    return any(host == d or host.endswith('.' + d) for d in _AUTHORITATIVE_URL_DOMAINS)


def build_trust_graph(observations: list, *,
                      authoritative_types=AUTHORITATIVE_SOURCE_TYPES,
                      trust_source_type_label: bool = False) -> tuple[dict, dict]:
    """실 관측 리스트 → (local_trust, pre_trusted) — eigentrust 입력 그래프.

    observation dict 기대 키: 'source'(또는 url/source_type 로 식별), 'url', 'source_type',
    'node'(어느 주장/노드를 받치나), 'corroboration_score'(0..1, 있으면 edge 가중).
    같은 node 를 받치는 관측 i,j 는 서로 corroboration edge(상호신뢰) — co-support 그래프.

    seed(pre-trusted) 자격은 기본 *URL 도메인*(authoritative_url, 서버 검증)으로 판정 — client 의
    source_type 라벨은 seed 를 통제하지 못한다(R3 forge 봉쇄). 신뢰된 구조/문헌 앵커(URL 없는 textbook
    인용 등)를 라벨로 seed 하려면 trust_source_type_label=True 로 *명시 opt-in*(그 신뢰는 호출자가 소유).
    """
    sources = {}
    by_node: dict = {}
    pre_trusted: dict = {}
    for o in observations:
        src = (o.get('source') or o.get('url') or o.get('source_type') or '').strip()
        if not src:
            continue
        sources.setdefault(src, o.get('source_type') or '')
        by_node.setdefault(o.get('node') or o.get('tag') or '', []).append((src, o))
        seeded = authoritative_url(o.get('url') or o.get('source') or '')   # 서버 검증 도메인
        if not seeded and trust_source_type_label:                          # 명시 opt-in 시에만 라벨 신뢰
            seeded = (o.get('source_type') or '').lower() in {t.lower() for t in authoritative_types}
        if seeded:
            pre_trusted[src] = 1.0

    local_trust: dict = {s: {} for s in sources}
    for _node, members in by_node.items():
        if not _node or len(members) < 2:
            continue
        for src_i, oi in members:
            for src_j, oj in members:
                if src_i == src_j:
                    continue
                w = float(oj.get('corroboration_score') or 0.5)   # j 가 받친 강도로 i→j 신뢰
                local_trust[src_i][src_j] = local_trust[src_i].get(src_j, 0.0) + max(0.0, min(1.0, w))
    return local_trust, pre_trusted


def global_source_trust(observations: list, *, crosscheck: bool = True, **kw) -> dict:
    """실 관측 그래프 → 글로벌 출처신뢰 {source: trust} + coverage 메타.

    eigentrust(전이적 신뢰의 고유벡터)를 build_trust_graph 산출 그래프에 돌린다. edge 가 없으면
    eigentrust 는 pre_trusted 분포로 환원(seed-dominated) — 정직하게 coverage 로 표기.
    반환: {'trust': {src: val}, 'coverage': {n_sources, n_seeds, n_edges, mode, [crosscheck]}}.

    crosscheck=True(기본, P6 배선): 같은 그래프에 trustrank(시드전파 biased PageRank, brin_page1998)도
    돌려 eigentrust(고유벡터, kamvar2003)와 *최상위 신뢰 출처* 일치를 확인한다 — 독립 알고리즘 robustness
    교차검증(argue mu-toksia 패턴; trustrank=evidence, eigentrust=권위). 발산(top_agrees=False)은
    graph_propagated 모드서 의미있는 경보(seed_dominated 면 둘 다 시드분포로 환원돼 자명 일치).
    """
    local_trust, pre_trusted = build_trust_graph(observations, **kw)
    n_edges = sum(len(d) for d in local_trust.values())
    trust = eigentrust(local_trust, pre_trusted) if local_trust else {}
    mode = ('graph_propagated' if n_edges > 0
            else ('seed_dominated' if pre_trusted else 'uniform_unlearned'))
    coverage = {
        'n_sources': len(local_trust),
        'n_seeds': len(pre_trusted),
        'n_edges': n_edges,
        'mode': mode,   # 정직: edge 없으면 seed_dominated(고유벡터 heavy-lifting 아직 아님)
        # seed 가 서버검증 URL 도메인인지, 호출자-소유 라벨 opt-in 인지 노출(숨김 금지)
        'seed_basis': 'source_type_label' if kw.get('trust_source_type_label') else 'url_domain',
    }
    if crosscheck and trust:   # P6: trustrank 를 *실제로* 런타임에 돌려 eigentrust 와 교차검증
        graph = {s: list(nbrs) for s, nbrs in local_trust.items()}   # i→j out-edges
        tr = trustrank(graph, pre_trusted)
        srcs = list(trust)

        def _top(d):
            return max(srcs, key=lambda s: d.get(s, 0.0)) if srcs else None

        top_e, top_t = _top(trust), _top(tr)
        coverage['crosscheck'] = {
            'method': 'trustrank',
            'top_agrees': top_e == top_t,
            'top_eigentrust': top_e,
            'top_trustrank': top_t,
            'note': 'graph_propagated 모드서 의미; seed_dominated 면 자명 일치',
        }
    return {'trust': {k: round(v, 6) for k, v in trust.items()}, 'coverage': coverage}
