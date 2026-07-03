"""Cross-layer read-model metric composition for Lakatos trees.

The tree read-model *projection* itself now lives on the production path
(`server.contexts.tree.repository.TreeKgRepository.load_tree_data`) — the single
source of truth (D1 audit 2026-06-26: there used to be a second, test-only copy
here that diverged, leaving A2 eigentrust + D1 provenance inert on every HTTP
path). This module keeps only the metric composition, which intentionally lives
*outside* the `.importlinter` layered contract so it can merge `quant` + `programme`.
"""

from __future__ import annotations

from lakatos.programme.flip import layer_flips
from lakatos.quant.metrics import tree_metrics


def compute_tree_metrics(td: dict) -> dict:
    """Compute report metrics from a projected tree read model.

    `layer_flips` is merged here (not inside `tree_metrics`) on purpose: it lives in
    `lakatos.programme` and `tree_metrics` lives in `lakatos.quant` — folding it in there
    would be an upward `quant → programme` import that `.importlinter` forbids. The server
    read-model is outside the layered contract, so it is the clean seam to compose them.
    """
    cfg = {
        "coverage_backlog": td.get("coverage_backlog") or [],
        "coverage_statement": td.get("coverage_statement") or "",
    }
    # A2: 관측이 있으면 eigentrust 글로벌 출처신뢰 맵을 구성해 credence 가중에 주입(없으면 레거시).
    observations = td.get("observations")
    if observations:
        from lakatos.trust import global_source_trust
        gst = global_source_trust(observations)
        if gst["trust"]:
            cfg["source_trust_map"] = gst["trust"]
            cfg["trust_coverage_mode"] = gst["coverage"]["mode"]
    m = tree_metrics(td["nodes"], td["frontier"], cfg=cfg)
    m["layer_flips"] = layer_flips(td["nodes"], td["frontier"])
    # G6: 메트릭 소비자에게 보증 tier 를 함께 공시 — 숫자의 신뢰 등급을 숫자 옆에(legacy=G6 이전 트리).
    m["assurance_tier"] = td.get("assurance_tier") or "legacy"
    # G3 S3: note_only_ratio 는 *모니터 신호*로 강등 — 진보 게이트도 채점 오라클도 아니다
    #   (q_adoption_metric_confound: 채택률로 채점하면 행동 confound). 관측만 공시, credence-low.
    nodes = td.get("nodes") or []
    note_only = [n for n in nodes
                 if not n.get("verdict_source") and not n.get("pred_registered_at")]
    m["honesty_monitor"] = {
        "note_only_ratio": round(len(note_only) / len(nodes), 4) if nodes else 0.0,
        "monitor_only": True,   # 게이트 아님 — 정직경로 채택은 G3 경제학(1-verb run_cycle)이 만든다
    }
    return m
