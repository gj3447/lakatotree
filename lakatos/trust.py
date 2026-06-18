"""인터넷 출처 신뢰 — 라카토트리가 인터넷 증거에 정량 신뢰가중을 단다 (P1: 인터넷 엮기).

골방 연구가 아니라 기존 웹 신뢰 시스템과 연결: TrustRank(시드 전파) + EigenTrust(고유벡터).
증거(웹 citation)는 출처 신뢰를 달고 베이즈층 P(E|H) 에 결합 — 권위 출처 = 강한 증거.
출처: Kamvar et al. EigenTrust(WWW 2003), Gyöngyi et al. TrustRank(VLDB 2004).
# KG: span_lakatotree_trust
"""


from .grounding import GROUNDED   # T-H-1: damping/alpha 단일 정본(하드코딩 금지 — drift/G5 우회 방지)


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


def evidence_weight(source_trust: float, floor: float = 0.0) -> float:
    """출처 신뢰 → 증거 가중 [floor, 1]. 베이즈 BF 지수에 곱해 P(E|H) 결합.

    나생문 F-MATH-4: floor=0 → zero-trust(junk) 출처는 무정보(BF=1), credence 안 움직임.
    """
    return floor + (1.0 - floor) * max(0.0, min(1.0, source_trust))


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


def build_trust_graph(observations: list, *,
                      authoritative_types=AUTHORITATIVE_SOURCE_TYPES) -> tuple[dict, dict]:
    """실 관측 리스트 → (local_trust, pre_trusted) — eigentrust 입력 그래프.

    observation dict 기대 키: 'source'(또는 url/source_type 로 식별), 'source_type',
    'node'(어느 주장/노드를 받치나), 'corroboration_score'(0..1, 있으면 edge 가중).
    같은 node 를 받치는 관측 i,j 는 서로 corroboration edge(상호신뢰) — co-support 그래프.
    권위 source_type 관측은 pre_trusted seed(sybil 저항 앵커).
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
        if (o.get('source_type') or '').lower() in {t.lower() for t in authoritative_types}:
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


def global_source_trust(observations: list, **kw) -> dict:
    """실 관측 그래프 → 글로벌 출처신뢰 {source: trust} + coverage 메타.

    eigentrust(전이적 신뢰의 고유벡터)를 build_trust_graph 산출 그래프에 돌린다. edge 가 없으면
    eigentrust 는 pre_trusted 분포로 환원(seed-dominated) — 정직하게 coverage 로 표기.
    반환: {'trust': {src: val}, 'coverage': {n_sources, n_seeds, n_edges, mode}}.
    """
    local_trust, pre_trusted = build_trust_graph(observations, **kw)
    n_edges = sum(len(d) for d in local_trust.values())
    trust = eigentrust(local_trust, pre_trusted) if local_trust else {}
    mode = ('graph_propagated' if n_edges > 0
            else ('seed_dominated' if pre_trusted else 'uniform_unlearned'))
    return {
        'trust': {k: round(v, 6) for k, v in trust.items()},
        'coverage': {
            'n_sources': len(local_trust),
            'n_seeds': len(pre_trusted),
            'n_edges': n_edges,
            'mode': mode,   # 정직: edge 없으면 seed_dominated(고유벡터 heavy-lifting 아직 아님)
        },
    }
