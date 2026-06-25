"""가드 — SX3i 가지가 *엔진 생성* verdict 인가(손입력 0). 자기채점 차단의 종착.

sx3i_engine_judged.run() 의 모든 측정노드 verdict 는 record_judge() 가 grounded record 에서
생성한 것과 *동일*해야 한다(손입력 리터럴이면 어긋남). 측정 record 없는 narrative 노드는
verdict 를 못 받는다(no_record) — 측정 뒷받침 없는 손입력 verdict 금지를 강제.
"""
from examples import record_judge as J
from examples.sx3i_engine_judged import NODES, judged_nodes


def test_measured_verdicts_come_from_engine_not_hand():
    """측정노드 verdict == record_judge(record). 손입력이면 안 맞음."""
    rows = {r["tag"]: r for r in judged_nodes()}
    for tag, parent, rec, role in NODES:
        if role != "measured":
            continue
        eng = J.judge_record(rec)
        assert eng["status"] == "judged", f"{tag}: record 가 엔진판결 불가({eng['status']})"
        assert rows[tag]["verdict"] == eng["verdict"], \
            f"{tag}: 트리 verdict {rows[tag]['verdict']} != 엔진 {eng['verdict']}(손입력 의심)"


def test_node_table_has_no_hand_input_verdict():
    """NODES 정의 자체에 verdict 가 없어야 — (tag, parent, record, role) 4-튜플, role 만.
    verdict 는 run()/judged_nodes() 에서 record_judge 가 생성(손입력 행 없음)."""
    for entry in NODES:
        assert len(entry) == 4, f"NODES 튜플에 verdict 끼어듦?: {entry}"
        tag, parent, rec, role = entry
        assert role in ("problem", "measured", "narrative"), f"알 수 없는 role: {role}"
        # verdict 어휘가 튜플 어디에도 없음
        for v in ("progressive", "degenerating", "rejected", "partial", "canonical_stage"):
            assert v not in (str(parent or ""), str(rec or "")), f"{tag}: 튜플에 verdict 리터럴"


def test_all_sx3i_nodes_engine_judged_no_narrative():
    """★2026-06-24 엔진에 올라탐: 옛 narrative 2노드(reader-fix·misdiag)에 grounded record 부여 →
    이제 전부 엔진판결(measured). narrative(record 없음) 0 = 측정 뒷받침 없는 verdict 0."""
    rows = {r["tag"]: r for r in judged_nodes()}
    assert not any(r.get("status") == "no_record" for r in rows.values()), \
        "측정 record 없는 노드 잔존(자기채점 위험)"
    # 옛 narrative 2노드가 이제 엔진판결됨
    assert rows["reader_frame_provenance_fix"]["verdict"] == "partial"
    assert rows["misdiag_reader_frame"]["verdict"] == "rejected"


def test_c1_engine_judges_partial_not_progressive():
    """★핵심 divergence 문서화: c1 은 엔진 기준 partial(손입력 progressive 는 과대였음)."""
    rows = {r["tag"]: r for r in judged_nodes()}
    assert rows["c1_marker_detect"]["verdict"] == "partial"


def test_c2_full_view_assembly_closes_as_rejected():
    """C2 전체 lot assembly 는 엔진 기준 rejected: 67 posed views < 180 gate."""
    rows = {r["tag"]: r for r in judged_nodes()}
    assert rows["c2_aruco_assembly"]["verdict"] == "partial"
    assert rows["c2_full_view_assembly"]["verdict"] == "rejected"
    assert rows["c2_full_view_assembly"]["measured"] == 67.0
    assert rows["c2_full_view_assembly"]["baseline"] == 180.0


def test_snr_filter_does_not_close_c2():
    """저SNR view culling 은 C2를 닫지 못한다: best filtered posed views = 113 < 180."""
    rows = {r["tag"]: r for r in judged_nodes()}
    assert rows["sx3i_snr_filter_assembly"]["verdict"] == "rejected"
    assert rows["sx3i_snr_filter_assembly"]["metric"] == "snr_filtered_posed_views"
    assert rows["sx3i_snr_filter_assembly"]["measured"] == 113.0
    assert rows["sx3i_snr_filter_assembly"]["baseline"] == 180.0


def test_marker_view_graph_diagnostic_explains_c2_break():
    """>=3 shared-marker view graph 는 후반 view bridge 를 닫지 못한다."""
    rows = {r["tag"]: r for r in judged_nodes()}
    assert rows["sx3i_marker_view_graph_diagnostic"]["verdict"] == "rejected"
    assert rows["sx3i_marker_view_graph_diagnostic"]["metric"] == "largest_component_views_min_shared3"
    assert rows["sx3i_marker_view_graph_diagnostic"]["measured"] == 115.0
    assert rows["sx3i_marker_view_graph_diagnostic"]["baseline"] == 180.0


def test_local_marker_cad_anchor_plan_is_partial_feasibility_branch():
    """후반부는 marker graph 가 아니라 Ypos CAD anchor 로 잇는 branch 로 간다."""
    rows = {r["tag"]: r for r in judged_nodes()}
    assert rows["sx3i_local_marker_cad_anchor_plan"]["verdict"] == "partial"
    assert rows["sx3i_local_marker_cad_anchor_plan"]["metric"] == "late_cad_anchor_views"
    assert rows["sx3i_local_marker_cad_anchor_plan"]["measured"] == 8.0
    assert rows["sx3i_local_marker_cad_anchor_plan"]["baseline"] == 6.0


def test_cad_source_problem_is_visible_in_engine_branch():
    """CAD anchor identifies the part, but scan-derived IGES does not close precision/trueness."""
    rows = {r["tag"]: r for r in judged_nodes()}
    assert rows["sx3i_real_cad_symmetry"]["verdict"] == "partial"
    assert rows["sx3i_real_cad_symmetry"]["metric"] == "y0_mirror_median_mm"
    assert rows["sx3i_real_cad_symmetry"]["measured"] == 0.3
    assert rows["sx3i_real_cad_icp_merge"]["verdict"] == "partial"
    assert rows["sx3i_real_cad_icp_merge"]["metric"] == "real_cad_coverage6_pct"
    assert rows["sx3i_real_cad_icp_merge"]["measured"] == 84.5
    assert rows["sx3i_real_cad_perview_acceptance"]["verdict"] == "rejected"
    assert rows["sx3i_real_cad_perview_acceptance"]["metric"] == "operational_dev_median_delta_mm"
    assert rows["sx3i_real_cad_perview_acceptance"]["measured"] == -0.216
    assert rows["sx3i_real_cad_maxcover_rgb_trash"]["verdict"] == "rejected"
    assert rows["sx3i_real_cad_maxcover_rgb_trash"]["metric"] == "trash_view_count_fit3_lt_0p10"
    assert rows["sx3i_real_cad_maxcover_rgb_trash"]["measured"] == 12.0
    assert rows["sx3i_real_cad_quality_filtered_rgb"]["verdict"] == "rejected"
    assert rows["sx3i_real_cad_quality_filtered_rgb"]["metric"] == "stable_quality_views"
    assert rows["sx3i_real_cad_quality_filtered_rgb"]["measured"] == 17.0
    assert rows["c2_register_to_cad"]["verdict"] == "partial"
    assert rows["c2_register_to_cad"]["metric"] == "panel_over_bracket_fitness_ratio"
    assert rows["c2_register_to_cad"]["measured"] == 4.73
    assert rows["c2b_assembly_to_cad"]["verdict"] == "rejected"
    assert rows["c2b_assembly_to_cad"]["metric"] == "cad_panel_register_fit3"
    assert rows["c2b_assembly_to_cad"]["measured"] == 0.071


def test_planarity_baseline_keeps_infield_frontier_open():
    """Current SX3i baseline is above the 0.45mm gate; after-correction remeasure remains open."""
    rows = {r["tag"]: r for r in judged_nodes()}
    assert rows["sx3i_planarity_baseline"]["verdict"] == "rejected"
    assert rows["sx3i_planarity_baseline"]["measured"] == 1.0796
    assert rows["sx3i_planarity_baseline"]["baseline"] == 0.45
