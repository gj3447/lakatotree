"""prom-honesty (R2→정본 결정 2026-06-21): metrics 읽기경로의 verdict_source 미채점 진보 = inconclusive.

쓰기게이트(9b85cf8)는 *앞으로*의 self-report 진보 주입을 막았지만, 읽기/집계 경로·기존 KG 데이터는
NULL-source 진보를 그대로 진보로 셌다(영수증 없는 green — 쓰기게이트의 대칭 누락, R2 fresh-eyes 발견).
이론(ooptdd 3치 LTL3): verdict_source 없는 진보 = *inconclusive*(pass도 fail도 아님) → DEFAULT 로 positive
진보 집계서 제외(비파괴·가역), 재검증으로 해소. cfg.provenance_lenient 로 옛 동작 opt-out.
# KG: span_lakatotree_S1_laudan_layer
"""
from lakatos.quant.metrics import tree_metrics

_ROOT = {"tag": "root", "verdict": "proof", "metric_value": 10.0, "metric_scope": "s", "pred_baseline": 10.0}


def _self_report_canonical():
    """verdict_source 키가 *있고* None = 실 KG self-report(노드 경로 주입/구데이터) = inconclusive."""
    return {"tag": "c", "parent": "root", "verdict": "CANONICAL", "verdict_source": None,
            "metric_value": 1.0, "metric_scope": "s", "pred_baseline": 10.0, "pred_direction": "lower"}


def test_inconclusive_progress_excluded_from_positive_by_default():
    """DEFAULT(3치): verdict_source 없는 진보는 inconclusive → canonical anchor 못 되고 진보 집계서 제외,
    provenance + alert 로 surface. (영수증 없는 green 을 *조용히* 도 *명시적으로*도 진보로 안 센다.)"""
    m = tree_metrics([_ROOT, _self_report_canonical()], [])
    assert m["canonical"] is None                                  # inconclusive ≠ verified canonical
    assert m["provenance"]["mode"] == "inconclusive-excluded"
    assert m["provenance"]["count"] == 1 and "c" in m["provenance"]["inconclusive_progress"]
    assert any("inconclusive" in a for a in m["alerts"])


def test_lenient_mode_opts_out_to_legacy_counting():
    """cfg.provenance_lenient=True = append-only 존중 opt-out: 옛 동작(집계 포함)으로 — 단 alert 로 경고."""
    m = tree_metrics([_ROOT, _self_report_canonical()], [], cfg={"provenance_lenient": True})
    assert m["canonical"] == "c"                                   # 옛 동작 보존(가역)
    assert m["provenance"]["mode"] == "lenient-counted"
    assert any("부풀림" in a for a in m["alerts"])


def _kg_projecting(stored_nodes, stored_obs):
    """실 Neo4j 투영 동형 fake: 노드 행은 *쿼리 RETURN 이 그 필드를 호명할 때만* 그 키를 돌려준다
    (e.verdict_source AS verdict_source 가 없으면 Neo4j 도 그 키를 안 준다). + 관측은 obs 쿼리가
    issue 될 때만 방출. → repository 가 투영/관측쿼리를 빠뜨리면 D1/A2 가 *실제로* 죽는다는 프로덕션
    동치를 단위에서 revert-proof 로 잡는다(전 fake-green: inspect.getsource 로 *죽은* read_models 사본 검사)."""
    passthru = ("tag", "verdict", "parent", "metric_value", "metric_scope", "pred_baseline", "pred_direction")

    def kg(q, **kw):
        if "RETURN t.title" in q:
            return [dict(title="T", hard_core="", frontier_rule="", doc="",
                         coverage_backlog=[], coverage_statement="")]
        if "HAS_RESEARCH_EVENT" in q:
            return stored_obs
        if "HAS_FRONTIER" in q:
            return []
        if "HAS_NODE" in q:
            rows = []
            for n in stored_nodes:
                row = {k: v for k, v in n.items() if k in passthru}
                if "verdict_source" in q:            # 투영이 호명할 때만 키 존재(None 포함)
                    row["verdict_source"] = n.get("verdict_source")
                if "source_trust" in q:
                    row["source_trust"] = n.get("source_trust")
                rows.append(row)
            return rows
        return []
    return kg


def test_prod_path_projects_provenance_and_observations_so_d1_a2_fire():
    """D1 감사 2026-06-26 (HIGH 해소, revert-proof): 프로덕션 read-model(TreeKgRepository.load_tree_data →
    compute_tree_metrics)이 self-report(verdict_source=None) 진보를 inconclusive 로 *실제* 검출(D1)하고,
    internet 관측을 방출해 eigentrust 맵을 *실제* 주입(A2)한다. repository 가 verdict_source 투영 또는 관측
    쿼리를 빠뜨리면(=옛 prod-inert 버그) 아래 단언이 깨진다."""
    import json

    from server.contexts.tree.repository import TreeKgRepository
    from server.read_models import compute_tree_metrics

    stored = [
        {"tag": "root", "verdict": "proof", "metric_value": 10.0, "metric_scope": "s", "pred_baseline": 10.0},
        {"tag": "c", "parent": "root", "verdict": "CANONICAL", "verdict_source": None,
         "metric_value": 1.0, "metric_scope": "s", "pred_baseline": 10.0, "pred_direction": "lower"},
    ]
    obs = [dict(node="c", payload=json.dumps(
        {"url": "peer://a", "source_type": "peer_reviewed", "corroboration_score": 0.9}))]

    td = TreeKgRepository(_kg_projecting(stored, obs)).load_tree_data("T")

    # D1: prod 경로가 verdict_source(None)을 투영 → self-report 진보가 inconclusive 로 제외(영수증 없는 green ✗).
    m = compute_tree_metrics(td)
    assert m["canonical"] is None, "self-report CANONICAL 이 prod 에서 검증 canonical 로 샜다(D1 inert)"
    assert m["provenance"]["mode"] == "inconclusive-excluded"
    assert m["provenance"]["count"] == 1 and "c" in m["provenance"]["inconclusive_progress"]
    # A2: prod 경로가 관측을 방출 → eigentrust 글로벌 신뢰 맵이 실제 구성·주입된다.
    assert td["observations"], "prod 경로가 internet 관측을 안 방출 → A2 eigentrust inert"
    assert m["bayes"]["trust_coverage"]["map_supplied"] is True


def test_legacy_nodes_without_verdict_source_key_unaffected():
    """verdict_source *키 부재*(레거시/테스트 픽스처)는 신뢰 — inconclusive 아님, 집계 정상(타 트리 비트동일)."""
    legit = {"tag": "c", "parent": "root", "verdict": "CANONICAL",
             "metric_value": 1.0, "metric_scope": "s", "pred_baseline": 10.0}
    m = tree_metrics([_ROOT, legit], [])
    assert m["provenance"]["count"] == 0
    assert m["canonical"] == "c"
