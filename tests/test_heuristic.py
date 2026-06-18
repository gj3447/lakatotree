"""MSRP 휴리스틱 정책층 TDD — 두 휴리스틱이 정책으로 산다(집계만 X).
# KG: span_lakatotree_heuristic
"""
from lakatos.programme.heuristic import (
    expected_progress_gain,
    realized_reward,
    negative_heuristic,
    generate_moves,
    appraise_and_plan,
    MOVE_ABANDON,
    MOVE_PUSH,
    MOVE_PROBE,
    MOVE_PRIORITIZE,
)


# ── realized_reward (bandit 학습 — Laplace 계승규칙, gap6 reward 루프) ─────────
def test_reward_laplace_unlearned_is_half():
    assert realized_reward(0, 0) == 0.5   # 시도 0 → 무차별 (Laplace)


def test_reward_learns_from_outcomes():
    assert realized_reward(3, 3) > realized_reward(0, 3)      # 전승 노선 > 전패 노선
    assert realized_reward(3, 3) > 0.5 > realized_reward(0, 3)
    assert realized_reward(5, 10) == (5 + 1) / (10 + 2)        # (h+1)/(a+2)


def test_reward_clamps_hits_to_attempts():
    assert realized_reward(99, 2) == realized_reward(2, 2)    # hits>attempts 방어


def test_gain_learned_reward_boosts_and_damps():
    base = expected_progress_gain(has_novel_target=True)
    boosted = expected_progress_gain(has_novel_target=True, learned_reward=1.0)
    damped = expected_progress_gain(has_novel_target=True, learned_reward=0.0)
    assert damped < base < boosted   # 진보노선 가산, 헛수고 노선 감쇠
    assert expected_progress_gain(has_novel_target=True, learned_reward=0.5) == base  # 중립


# ── expected_progress_gain (VoI 분자 실계산 — 전엔 0.1 하드코딩) ──────────────
def test_gain_novel_beats_plain():
    novel = expected_progress_gain(has_novel_target=True)
    plain = expected_progress_gain(has_novel_target=False)
    assert novel > plain   # 초과경험내용(novel) = 진보 신호 → 더 값짐


def test_gain_momentum_and_pressure_monotone():
    base = expected_progress_gain()
    assert expected_progress_gain(on_canonical_frontier=True) > base
    assert expected_progress_gain(problem_pressure=1.0) > expected_progress_gain(problem_pressure=0.0)


def test_gain_scales_with_credence_and_clamps():
    lo = expected_progress_gain(canonical_credence=0.0, has_novel_target=True)
    hi = expected_progress_gain(canonical_credence=1.0, has_novel_target=True)
    assert hi > lo
    assert 0.0 <= expected_progress_gain(problem_pressure=99, has_novel_target=True,
                                         on_canonical_frontier=True, canonical_credence=2.0) <= 1.0
    assert expected_progress_gain() != 0.1   # 더 이상 상수 default 가 아님


# ── negative heuristic (modus tollens → belt, not hard core) ──────────────────
def test_negative_protects_hard_core():
    out = negative_heuristic(hard_core=("aruco_backbone", "frozen_calib"),
                             refuted_assumptions=["aruco_backbone", "roi_radius"])
    assert "aruco_backbone" in out["protected"]      # hard core = 금지 타겟
    assert "roi_radius" in out["redirectable"]        # belt = 흡수 가능
    assert out["requires_core_revision"] is False     # belt 로 흡수되므로 자동 core 개정 아님


def test_negative_flags_core_revision_only_when_no_belt_absorber():
    # 반례가 *전부* hard core → belt 흡수 불가 → AGM revise 안건(자동 폐기 아님)
    out = negative_heuristic(hard_core=("hc1", "hc2"),
                             refuted_assumptions=["hc1", "hc2"])
    assert out["requires_core_revision"] is True
    assert out["absorbable_in_belt"] is False


def test_negative_unknown_assumption_treated_as_belt():
    out = negative_heuristic(hard_core=("hc1",), refuted_assumptions=["mystery"],
                             belt=("known_belt",))
    assert "mystery" in out["redirectable"]   # 보수적: hard core 오염 금지


# ── positive heuristic — generate_moves (다음 실험 *생성*) ─────────────────────
def _branch(**kw):
    base = dict(leaf="canon", consecutive_nonprogressive=0, nodes_spent=2,
                prediction_hits=1, problem_balance_windowed=0, canonical_credence=0.7)
    base.update(kw)
    return base


def test_generate_abandon_on_degenerating_branch():
    # 연속 비진보 ≥ K(=3) → laudan should_abandon → ABANDON move 생성
    moves = generate_moves(nodes=[{"tag": "canon", "verdict": "degenerating"}],
                           frontier=[], branch=_branch(consecutive_nonprogressive=3))
    kinds = {m["kind"] for m in moves}
    assert MOVE_ABANDON in kinds
    ab = next(m for m in moves if m["kind"] == MOVE_ABANDON)
    assert ab["target"] == "canon"


def test_generate_probe_for_untested_hard_core():
    moves = generate_moves(nodes=[], frontier=[], branch=_branch(),
                           hard_core=("hc_a", "hc_b"), tested_core=("hc_a",))
    probes = [m for m in moves if m["kind"] == MOVE_PROBE]
    assert {p["target"] for p in probes} == {"hc_b"}   # 미검 hard core 만 탐침


def test_generate_push_vs_prioritize_by_frontier():
    nodes = [{"tag": "canon", "verdict": "CANONICAL"}]
    frontier = [
        {"name": "q-on-front", "status": "OPEN", "opened_by": ["canon"], "novel_metric": "seam_mm"},
        {"name": "q-off-front", "status": "OPEN", "opened_by": ["dead_branch"]},
    ]
    moves = generate_moves(nodes=nodes, frontier=frontier, branch=_branch())
    by_target = {m["target"]: m for m in moves}
    assert by_target["q-on-front"]["kind"] == MOVE_PUSH          # 정본 전선
    assert by_target["q-off-front"]["kind"] == MOVE_PRIORITIZE   # 전선 밖
    # novel + 전선 질문이 더 높은 est_gain
    assert by_target["q-on-front"]["est_gain"] > by_target["q-off-front"]["est_gain"]


def test_push_detected_via_node_questions_not_frontier_opened_by():
    # ★ production KG frontier row 엔 opened_by 가 없다 — 질문→노드 링크는 node['questions'].
    #   이 매핑으로 PUSH 가 잡혀야 한다(안 그러면 전부 PRIORITIZE 로 떨어지는 통합버그).
    nodes = [{"tag": "v1", "verdict": "CANONICAL", "questions": ["q-push"],
              "novel_registered": True, "metric_name": "seam_mm"}]
    frontier = [{"name": "q-push", "status": "OPEN", "closed_by": []}]   # opened_by 없음(현실)
    moves = generate_moves(nodes=nodes, frontier=frontier, branch=_branch())
    push = next(m for m in moves if m["target"] == "q-push")
    assert push["kind"] == MOVE_PUSH


def test_generate_moves_sorted_by_est_gain():
    nodes = [{"tag": "canon", "verdict": "CANONICAL"}]
    frontier = [{"name": f"q{i}", "status": "OPEN", "opened_by": ["canon"]} for i in range(3)]
    moves = generate_moves(nodes=nodes, frontier=frontier, branch=_branch())
    gains = [m["est_gain"] for m in moves]
    assert gains == sorted(gains, reverse=True)


def test_closed_questions_excluded():
    frontier = [{"name": "done", "status": "CLOSED", "opened_by": ["canon"]}]
    moves = generate_moves(nodes=[{"tag": "canon", "verdict": "CANONICAL"}],
                           frontier=frontier, branch=_branch())
    assert all(m["target"] != "done" for m in moves)


# ── appraise_and_plan (negative + positive 한 묶음) ───────────────────────────
def test_appraise_combines_both_heuristics():
    plan = appraise_and_plan(
        nodes=[{"tag": "canon", "verdict": "CANONICAL"}],
        frontier=[{"name": "q1", "status": "OPEN", "opened_by": ["canon"]}],
        branch=_branch(consecutive_nonprogressive=3),
        hard_core=("hc1",), tested_core=("hc1",))
    assert plan["abandon_signaled"] is True
    assert "negative_heuristic" in plan and "moves" in plan
    assert plan["n_moves"] == len(plan["moves"])
