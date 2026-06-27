"""OOPTDD emit-adapter — A2 eigentrust trust-coverage 영수증을 *구조화 이벤트 trace*(R02)로.

버그(2026-06-28 감사): 서빙 로더(TreeKgRepository.load_tree_data)는 `e.verdict_source AS verdict_source`
를 RETURN 해 실-Neo4j 노드 dict 가 verdict_source 키를 *항상* 들고(미설정 시 None) 온다. tree_metrics 의
prom-honesty 패스가 PROGRESS_VERDICTS(='progressive'+'CANONICAL') 노드 중 verdict_source 키가 present-but-empty
인 것을 _inconclusive_unscored 로 강등 → 정본경로의 CANONICAL leaf 까지 강등 → canonical_path 가 *비고* →
trust path source 매칭 0. 유닛 픽스처는 키를 *생략*(force_of=SELF_REPORT=신뢰)해 통과 = fake-green.

이 영수증은 실 server.read_models.compute_tree_metrics 를 *서빙 형상*(verdict_source 키 present)으로 구동해:
  (양성) 정본경로 노드가 영수증(verdict_source)을 달면 path source 가 eigentrust 맵에 매칭(count>=1) → trust_path_source_matched
  (음성) 영수증이 없으면(키=None) inconclusive 강등으로 canonical_path 가 붕괴함을 *명시 이벤트*로 노출 → canonical_path_collapsed_inconclusive
hermetic: Neo4j 불요(서빙 로더의 normalize_node_row/internet_observations 로 형상을 in-process 재현).
Longinus(R10): 이 emit site(verify)가 must_emit 이벤트를 낸다. 리터럴이 verify 본문에서 물리적으로 해소돼야 함.
"""
import json
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from server.contexts.tree.repository import internet_observations, normalize_node_row  # noqa: E402
from server.read_models import compute_tree_metrics  # noqa: E402


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.A2", "event": name, **attrs}


def _raw_nodes(verdict_source):
    """test_a2_eigentrust_credence._seed_tree 와 동형의 *서빙 로더 형상* 노드 행(verdict_source 키 present)."""
    return [
        dict(tag="root", verdict="canonical_stage", verdict_source=verdict_source,
             metric_value=1.0, metric_scope="s", parent=None, parents=[], parent_edges=[], questions=[]),
        dict(tag="p1", verdict="progressive", verdict_source=verdict_source,
             metric_value=0.5, metric_scope="s", pred_baseline=1.0, pred_noise_band=0.02, pred_closes="q1",
             parent="root", parents=["root"], parent_edges=[dict(tag="root")], questions=[]),
        dict(tag="top", verdict="CANONICAL", verdict_source=verdict_source,
             metric_value=0.4, metric_scope="s",
             parent="p1", parents=["p1"], parent_edges=[dict(tag="p1")], questions=[]),
    ]


# 정본경로 노드 p1 을 받치는 두 internet 관측(블로그 0.5 + peer 0.9, co-support → eigentrust 가 블로그<1.0).
_OBS_ROWS = [
    dict(node="p1", payload=json.dumps({"url": "blog://x", "source_type": "blog", "corroboration_score": 0.5})),
    dict(node="p1", payload=json.dumps({"url": "peer://a", "source_type": "peer_reviewed", "corroboration_score": 0.9})),
]


def _metrics(verdict_source):
    """실 compute_tree_metrics 를 서빙 형상으로 구동(Neo4j 불요)."""
    observations, node_source = internet_observations(_OBS_ROWS)
    nodes = [normalize_node_row(r) for r in _raw_nodes(verdict_source)]
    for r in nodes:
        if r["tag"] in node_source:
            r["source"] = node_source[r["tag"]]
    td = {"name": "a2_receipt", "nodes": nodes, "frontier": [], "observations": observations}
    return compute_tree_metrics(td)


def verify(backend, cid):
    """A2 trust-coverage 구동 — 영수증 있으면 path source 매칭(양성), 없으면 붕괴를 명시(음성)."""
    # 양성: 정본경로 노드에 verdict_source 영수증 → canonical_path 보존 → eigentrust 맵에 path source 매칭.
    m_ok = _metrics("engine")
    tc_ok = m_ok["bayes"]["trust_coverage"]
    matched = int(tc_ok.get("path_sources_matched") or 0)
    if matched >= 1:   # 양성 오라클: 속성이 성립할 때만 ship(회귀 시 미발화 → A2-1 RED)
        backend.ship([_ev(cid, "trust_path_source_matched",
                          count=matched, mode=tc_ok.get("mode"), map_supplied=tc_ok.get("map_supplied"))])

    # 음성 오라클: 영수증 없으면(키=None) inconclusive 강등으로 canonical_path 붕괴 → matched=0 을 *명시*.
    m_bad = _metrics(None)
    tc_bad = m_bad["bayes"]["trust_coverage"]
    inconclusive = (m_bad.get("provenance") or {}).get("inconclusive_progress") or []
    if int(tc_bad.get("path_sources_matched") or 0) == 0 and len(inconclusive) >= 1:
        backend.ship([_ev(cid, "canonical_path_collapsed_inconclusive",
                          path_sources_matched=int(tc_bad.get("path_sources_matched") or 0),
                          inconclusive_count=len(inconclusive), inconclusive=sorted(inconclusive))])
    return {"matched_with_receipt": matched, "collapsed_without_receipt": sorted(inconclusive)}
