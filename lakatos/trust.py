"""인터넷 출처 신뢰 — 라카토트리가 인터넷 증거에 정량 신뢰가중을 단다 (P1: 인터넷 엮기).

골방 연구가 아니라 기존 웹 신뢰 시스템과 연결: TrustRank(시드 전파) + EigenTrust(고유벡터).
증거(웹 citation)는 출처 신뢰를 달고 베이즈층 P(E|H) 에 결합 — 권위 출처 = 강한 증거.
출처: Kamvar et al. EigenTrust(WWW 2003), Gyöngyi et al. TrustRank(VLDB 2004).
# KG: span_lakatotree_trust
"""


def trustrank(graph: dict, seeds: dict, damping: float = 0.85, iters: int = 50) -> dict:
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


def eigentrust(local_trust: dict, pre_trusted: dict, alpha: float = 0.15,
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
    C = {}   # 행정규화 (i 의 신뢰 합 = 1)
    for i in nodes:
        row = local_trust.get(i, {})
        s = sum(max(v, 0.0) for v in row.values())
        C[i] = {j: max(row.get(j, 0.0), 0.0) / s for j in row} if s > 0 else {}
    sp = sum(pre_trusted.values()) or 1.0
    p = {x: pre_trusted.get(x, 0.0) / sp for x in nodes}
    t = {x: p[x] if any(p.values()) else 1.0 / n for x in nodes}
    for _ in range(iters):
        nxt = {x: alpha * p[x] for x in nodes}
        for i in nodes:
            for j, cij in C[i].items():
                nxt[j] += (1 - alpha) * t[i] * cij
        s = sum(nxt.values()) or 1.0
        t = {x: nxt[x] / s for x in nodes}
    return t


def evidence_weight(source_trust: float, floor: float = 0.2) -> float:
    """출처 신뢰 → 증거 가중 [floor, 1]. 베이즈 BF 지수에 곱해 P(E|H) 결합.

    무신뢰 출처도 floor (완전 무시 아님), 권위 출처는 1.0. 선형.
    """
    return floor + (1.0 - floor) * max(0.0, min(1.0, source_trust))
