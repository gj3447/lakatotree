"""dogfood: LakatoTree self-dev(create_tree 노출) 프로그램이 엔진 규율을 지키는지 — verdict 손입력 0.

hermetic: 실제 .venv pytest 대신 *합성 receipt* 를 run(rc) 에 주입(빠름·결정론). 실 receipt 는
examples/lakatotree_selfdev_programme.receipt() 가 tests/test_create_tree_surface.py +
tests/test_add_node_missing_tree_404.py 에서 파생한다.
# KG: span_lakatotree_selfdev_create_tree_dogfood
"""
from __future__ import annotations

from examples.lakatotree_selfdev_programme import SELFDEV_NODES, run

# 실 표면 테스트가 전부 green 인 상태를 반영한 합성 receipt(두 가지 guard 다 착륙).
_GREEN = {
    "test_service_create_tree_merges_tree_and_returns_ok": True,
    "test_mcp_create_tree_tool_posts_to_tree_route": True,
    "test_cli_tree_create_posts": True,
    "test_add_node_to_missing_tree_is_404_not_silent": True,
    "test_writer_add_node_missing_tree_raises": True,
    # delete_tree 표면(create 의 짝)
    "test_writer_delete_tree_missing_raises": True,
    "test_mcp_delete_tree_tool": True,
    "test_cli_tree_delete": True,
    "test_delete_nonempty_without_cascade_is_409_and_no_write": True,
}


def _by_tag(rc):
    return {r["tag"]: r for r in run(rc)}


def test_surface_branch_scores_progressive_from_receipt():
    """create_tree_surface 는 judge 가 receipt 에서 progressive 를 *생성*(개선+독립 novel 확증)."""
    s = _by_tag(_GREEN)["create_tree_surface"]
    assert s["verdict"] == "progressive", s
    assert s["improved"] is True
    assert s["novel"] is True          # add_node_missing_tree_fails_loud_404 (독립 축)


def test_delete_branch_scores_progressive_from_receipt():
    """delete_tree_surface(create 의 짝) 도 judge 가 receipt 에서 progressive 생성(novel=파괴적 가드)."""
    d = _by_tag(_GREEN)["delete_tree_surface"]
    assert d["verdict"] == "progressive", d
    assert d["novel"] is True


def test_root_is_canonical_stage_not_scored():
    h = _by_tag(_GREEN)["hard_core"]
    assert h["verdict"] == "canonical_stage" and h["status"] == "ROOT"


def test_writer_hardening_scores_progressive_when_guard_present():
    """writer 하드닝 guard 착륙 → 엔진이 writer_silent_match_hardening 을 progressive 로 채점."""
    w = _by_tag(_GREEN)["writer_silent_match_hardening"]
    assert w["verdict"] == "progressive"
    assert w["novel"] is True


def test_writer_hardening_pending_when_guard_absent():
    """guard 영수증 빠지면 정직한 pending(no-receipt) — '영수증 없는 green 은 거짓말' 규율."""
    rc = {k: v for k, v in _GREEN.items() if k != "test_writer_add_node_missing_tree_raises"}
    w = _by_tag(rc)["writer_silent_match_hardening"]
    assert w["verdict"] == "pending(no-receipt)"
    assert w["status"] == "OPEN"


def test_verdict_is_judge_generated_not_hand_entered():
    """novel 가드(404) 영수증을 False 로 뒤집으면 progressive 가 *안* 나온다 = judge 산출이지 손입력 아님."""
    rc = {**_GREEN, "test_add_node_to_missing_tree_is_404_not_silent": False}
    s = _by_tag(rc)["create_tree_surface"]
    assert s["verdict"] != "progressive"   # 개선됐어도 독립 novel 미확증 → partial
    assert s["novel"] is False


def test_novel_metric_is_independent_of_improvement_metric():
    """PROM-B: 각 가지의 novel metric != 개선 metric (독립 초과경험내용)."""
    for n in SELFDEV_NODES:
        if n.prediction is not None and n.novel_target is not None:
            assert n.novel_target.metric_name != n.prediction.metric_name, n.tag


def test_no_literal_scored_verdict_assigned_in_source():
    """소스에 scored verdict 손입력 없음(judge 만 생성). stage 라벨/산문 예외."""
    import examples.lakatotree_selfdev_programme as mod
    src = open(mod.__file__, encoding="utf-8").read()
    for bad in ('verdict="progressive"', "verdict='progressive'",
                'verdict="rejected"', 'verdict="partial"', 'verdict="equivalent"'):
        assert bad not in src, f"손입력 verdict: {bad}"
