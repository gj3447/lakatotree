"""SX3i 가지 — 손입력 verdict 0, 전부 엔진(record_judge)이 grounded record 에서 생성.

sx3i_icp_programme.py 는 `_n(tag, 'progressive', ...)` 로 verdict 를 **손입력**한다(자기채점 위험).
이 프로그램은 그걸 닫는다: 각 노드 verdict 를 **engine record_judge() 가 grounded record 에서 생성**.
sx3i_loop_demo(2노드 템플릿, 동시편집자)를 *가지 전체*로 확장.

★드러나는 진실(손입력과 엔진의 divergence) — 이게 이 변환의 가치:
  - c1_marker_detect: 손입력 progressive → 엔진 **partial**(임계초과지만 novel 초과내용 없음 = 과대였음).
  - c3_markerless_real: 손입력 degenerating → 엔진 **rejected**(예측 falsify).
  - sx3i_precision_floor_marker: 손입력 rejected = 엔진 rejected ✅.
  - reader_frame_provenance_fix: **grounded record 없음** → 엔진판결 불가. 측정 뒷받침 없는 손입력
    progressive 는 자기채점 — 엔진기반 트리에선 verdict 부여 불가(narrative/structural 로 분리).

run() 에 verdict 리터럴이 한 줄도 없다(canonical_stage 문제-root 와 'no_record' flag 제외).
실행: python -m examples.sx3i_engine_judged
"""
from __future__ import annotations

from examples import record_judge as J

EV = "/data/kjra/PROJECT/3D/SX3i_ICP_SPEC/evidence"
BLOOM_AT = "v8_pipeline"

# (tag, parent, record_path|None, role)  — verdict 는 여기 없다. 엔진이 record 에서 생성.
#   role: 'problem'=canonical_stage(측정 아님), 'measured'=record_judge 판결, 'narrative'=측정 record 없음
NODES = [
    ("sx3i_prob", None, None, "problem"),
    ("c1_marker_detect", "sx3i_prob", f"{EV}/c1_marker_detect_refixed_20260624.aligned_v1.json", "measured"),
    ("c2_aruco_assembly", "c1_marker_detect", f"{EV}/aruco_assembly_20260624.json", "measured"),
    ("c2_full_view_assembly", "c2_aruco_assembly", f"{EV}/c2_full_views_20260624.v1.json", "measured"),
    ("sx3i_marker_view_graph_diagnostic", "c2_full_view_assembly", f"{EV}/sx3i_marker_view_graph_diagnostic_20260625.v1.json", "measured"),
    ("sx3i_local_marker_cad_anchor_plan", "sx3i_marker_view_graph_diagnostic", f"{EV}/sx3i_local_marker_cad_anchor_plan_20260625.v1.json", "measured"),
    ("sx3i_snr_filter_assembly", "c2_full_view_assembly", f"{EV}/sx3i_snr_filter_assembly_20260624.v1.json", "measured"),
    ("sx3i_real_cad_symmetry", "c2_full_view_assembly", f"{EV}/sx3i_real_cad_symmetry_20260624.v1.json", "measured"),
    ("sx3i_real_cad_icp_merge", "sx3i_real_cad_symmetry", f"{EV}/sx3i_real_cad_icp_merge_20260624.v1.json", "measured"),
    ("sx3i_real_cad_perview_acceptance", "sx3i_real_cad_icp_merge", f"{EV}/sx3i_real_cad_icp_acceptance_20260624.v1.json", "measured"),
    ("sx3i_real_cad_maxcover_rgb_trash", "sx3i_real_cad_perview_acceptance", f"{EV}/sx3i_maxcover_rgb_trash_views_20260624.v1.json", "measured"),
    ("sx3i_real_cad_quality_filtered_rgb", "sx3i_real_cad_maxcover_rgb_trash", f"{EV}/sx3i_quality_filtered_rgb_branch_20260625.v1.json", "measured"),
    ("c2_register_to_cad", "c2_full_view_assembly", f"{EV}/cad_register_20260624.json", "measured"),
    ("c2b_assembly_to_cad", "c2_register_to_cad", f"{EV}/aruco_cad_register_20260624.json", "measured"),
    ("c3_markerless_instrument", "sx3i_prob", f"{EV}/view_feature_extract_selftest_20260624.v1.json", "measured"),
    ("c3_markerless_real", "c3_markerless_instrument", f"{EV}/markerless_c3_real_20260624.v1.json", "measured"),
    ("sx3i_precision_floor_marker", "sx3i_prob", f"{EV}/c3pre_precision_floor_20260624.json", "measured"),
    ("sx3i_planarity_baseline", "sx3i_precision_floor_marker", f"{EV}/sx3i_planarity_baseline_20260624.json", "measured"),
    # ↓ 2026-06-24: narrative 였던 2노드에 genuine grounded record 부여 → 엔진판결화(이제 measured).
    ("reader_frame_provenance_fix", "c1_marker_detect", f"{EV}/reader_frame_fix_20260624.json", "measured"),
    ("misdiag_reader_frame", "c1_marker_detect", f"{EV}/misdiag_reader_frame_20260624.json", "measured"),
]


def judged_nodes():
    """엔진 생성 verdict 노드 리스트 (손입력 0). 측정노드=record_judge, 문제-root=canonical_stage."""
    rows = []
    for tag, parent, rec, role in NODES:
        if role == "problem":
            rows.append({"tag": tag, "parent": parent, "verdict": "canonical_stage",
                         "source": "(problem root — 측정 아님)"})
        elif role == "narrative":
            rows.append({"tag": tag, "parent": parent, "verdict": None, "status": "no_record",
                         "source": "측정 record 없음 → 엔진판결 불가(손입력 금지)"})
        else:
            r = J.judge_record(rec)
            rows.append({"tag": tag, "parent": parent,
                         "verdict": r.get("verdict") if r["status"] == "judged" else None,
                         "status": r["status"], "metric": r.get("metric"),
                         "measured": r.get("measured"), "baseline": r.get("baseline"),
                         "source": rec.split("/")[-1]})
    return rows


def _direction_for(metric: str | None) -> str:
    if metric in {
        "side_px_median",
        "strict_detections",
        "strict_default_detections",
        "n_registered_views",
        "posed_views",
        "largest_component_views_min_shared3",
        "late_cad_anchor_views",
        "operational_dev_median_delta_mm",
    }:
        return "higher"
    return "lower"


def _to_lakato_node(row: dict) -> dict:
    parent = BLOOM_AT if row["tag"] == "sx3i_prob" else row.get("parent")
    return {
        "tag": row["tag"],
        "parent": parent,
        "verdict": row["verdict"],
        "metric_value": row.get("measured"),
        "metric_scope": "detection" if row.get("metric") in {"side_px_median", "strict_detections", "strict_default_detections"} else "registration",
        "metric_name": row.get("metric"),
        "pred_baseline": row.get("baseline"),
        "pred_noise_band": 0.05,
        "pred_direction": _direction_for(row.get("metric")),
        "novel_registered": row.get("status") == "judged",
        "novel_confirmed": False,
        "algorithm": "record_judge" if row.get("status") == "judged" else "problem",
        "comment": f"Engine-generated SX3i verdict from {row.get('source')}.",
        "limitation": "Research branch only; not a prismv2 production adapter.",
        "questions": [],
    }


def bloom_nodes() -> list[dict]:
    """LakatoTree branch interface: all SX3i verdicts are generated by record_judge."""
    return [_to_lakato_node(row) for row in judged_nodes()]


BLOOM_NODES = bloom_nodes()
BLOOM_FRONTIER = [
    dict(name="q_xl250_gsd", status="CLOSED", closed_by="c1_marker_detect",
         body="C1: XL250 색에서 DICT_4X4_250 검출 및 marker side_px 기준 충족 여부."),
    dict(name="q_reader_frame_misdiagnosis", status="CLOSED", closed_by="reader_frame_provenance_fix",
         body="Speckle/denoise/recapture 가설은 read_rgb SNR-frame 오선택으로 생긴 오진인지 여부."),
    dict(name="q_sx3i_assemble", status="CLOSED", closed_by="c2_full_view_assembly",
         body="C2: 212-view assembly가 하나의 connected component로 닫히는가. Current answer is NO: full assembly is rejected because posed_views is 67/211, not because current evidence shows duplicate marker IDs."),
    dict(name="q_sx3i_snr_filter_view_cull", status="CLOSED", closed_by="sx3i_snr_filter_assembly",
         body="Does removing shaky/low-SNR views close C2? No. SNR p50 sweep scored 211 views; unfiltered posed 113, best SNR-filtered also posed 113, and stricter filters reduce connectivity."),
    dict(name="q_sx3i_marker_view_graph_closed", status="CLOSED", closed_by="sx3i_marker_view_graph_diagnostic",
         body="Does the marker camera/viewpoint graph close as one large component? No. With a >=3 shared-marker edge gate, the largest connected component is only 115/211 views and spans views 0..115; after that many views have only 0-2 markers."),
    dict(name="q_sx3i_local_marker_cad_anchor_feasible", status="CLOSED", closed_by="sx3i_local_marker_cad_anchor_plan",
         body="Is the local-marker + Ypos CAD-half anchor branch justified by current data? Yes as a partial/feasibility branch: the largest marker component has 9 stable Ypos CAD-quality views, and 8 additional stable Ypos CAD-quality views sit outside that component for late-segment CAD anchoring."),
    dict(name="q_sx3i_part_identity", status="CLOSED", closed_by="c2_register_to_cad",
         body="CAD-register per-view test identifies the scan as PANEL/quarter-inner, not bracket: panel/bracket fitness ratio 4.73."),
    dict(name="q_sx3i_real_cad_reference", status="CLOSED", closed_by="sx3i_real_cad_symmetry",
         body="Use the newly supplied real.igs as the active SX3i CAD reference. It restores the expected Y=0 left/right symmetry: 392k cloud points vs old 59k, 37 hole candidates vs old 9, mirror median about 0.3mm. Real-CAD ICP then reaches coverage@6 84.5%."),
    dict(name="q_sx3i_real_cad_icp", status="CLOSED", closed_by="sx3i_real_cad_icp_merge",
         body="Does the new real.igs restore CAD-anchored surface ICP merge? Yes: Ypos wins 42/53 views, 35 views align, coverage@6=84.5% vs old CAD color-merge 39%. This closes the CAD-reference blocker, not final sub-0.1mm metrology."),
    dict(name="q_sx3i_perview_acceptance_full_merge", status="CLOSED", closed_by="sx3i_real_cad_perview_acceptance",
         body="Does per-view acceptance alone improve the full SX3i real-CAD merge? No. Clean patches exist (fit3>=0.40 keeps views 52,56,160 at median 3.571mm, coverage@6 34.9%; top20 median 4.524mm, coverage@6 64.2%), but the coverage-preserving operational policy gives median 6.587mm vs raw 6.37mm."),
    dict(name="q_sx3i_maxcover_clean_registration", status="CLOSED", closed_by="sx3i_real_cad_maxcover_rgb_trash",
         body="Is the 40-view PyVista/ZDF-RGB max-cover merge a clean registration branch? No. It covers more of the Ypos half visually, but includes 12 views below fit3 0.10 and 17 below fit3 0.20. Treat it as visualization/coverage evidence, not metrology."),
    dict(name="q_sx3i_one_half_identity", status="CLOSED", closed_by="sx3i_real_cad_maxcover_rgb_trash",
         body="SX3i ZDF object should be registered to one CAD half only. Current real.igs evidence chooses the Ypos half; Yneg is used only as a side-identity comparator, not as a registration target."),
    dict(name="q_sx3i_marker_pose_graph_vs_cad_icp", status="CLOSED", closed_by="sx3i_real_cad_quality_filtered_rgb",
         body="The camera/viewpoint marker-map branch and the one-half CAD ICP visualization branch are separate. Current PyVista RGB images are CAD ICP visualizations against Ypos, not proof that the marker pose graph is closed."),
    dict(name="q_sx3i_quality_filtered_full_coverage", status="CLOSED", closed_by="sx3i_real_cad_quality_filtered_rgb",
         body="Does removing trash/unstable views leave a complete visual coverage branch? No. Quality-filtered RGB branch keeps 17 stable views after excluding 20 low-fit/unstable max-cover views. It is cleaner, but not full coverage."),
    dict(name="q_sx3i_next_bridge_strategy", status="CLOSED", closed_by="sx3i_local_marker_cad_anchor_plan",
         body="Next branch selected: segment-local marker maps plus Ypos CAD-half anchoring/global pose-graph optimization. Recapture/fixture remains the fallback if this branch cannot reduce residuals; blind max-cover view addition is not the metrology objective."),
    dict(name="q_sx3i_robust_pose_graph_implementation", status="OPEN", closed_by=None,
         body="Implement robust global optimization with marker residuals and Ypos CAD-fit residuals as separate factors. Inputs are local marker components, quality17 Ypos CAD anchor views, and explicit outlier rejection by marker residual + CAD fit."),
    dict(name="q_sx3i_cad_nominal", status="OPEN", closed_by=None,
         body="real.igs supersedes the truncated old IGES as the CAD reference, but it is still a PolyWorks IGES/NURBS surface export rather than traceable GD&T nominal STEP. Use it for registration/geometry recovery, not as final CMM-grade trueness truth."),
    dict(name="q_sx3i_cad_precision", status="OPEN", closed_by=None,
         body="Current CAD anchor is useful for coarse part identity/merge, but not for sub-0.1mm precision or accuracy. Evidence: per-view CAD registration rmse about 1.06mm and assembly-to-CAD coverage only 25%; residual may be CAD source quality + segmentation + sensor floor."),
    dict(name="q_independent_accuracy", status="OPEN", closed_by=None,
         body="C3: marker-independent feature coincidence가 sub-0.1mm band를 만족하는가. Current free-hand floor is rejected; this stays open only through a constrained/infield-corrected branch."),
    dict(name="q_sx3i_fixed_constraint_path", status="OPEN", closed_by=None,
         body="Tripod free-motion path is rejected for sub-0.1mm by sx3i_precision_floor_marker. Next branch: fixed jig, known-axis, turntable, or other pose constraint that reduces registration DOF."),
    dict(name="q_sx3i_infield_after_remeasure", status="OPEN", closed_by=None,
         body="Run SX3i_ICP_SPEC/scripts/planarity_baseline.py again after Zivid in-field correction or on a calibrated flat artifact; compare against the 1.0796mm baseline and 0.45mm gate."),
    dict(name="q_raw_refine", status="OPEN", closed_by=None,
         body="C4: raw residual ICP/refine이 overlap RMS를 sub-0.1mm로 낮추는가."),
    dict(name="q_crosscam", status="OPEN", closed_by=None,
         body="C5: XL250과 MR60/BPC cross-camera feature delta가 0.15mm 아래로 닫히는가."),
    dict(name="q_sx3i_precision_floor", status="CLOSED", closed_by="sx3i_precision_floor_marker",
         body="XL250 + current geometry의 precision floor가 C3 목표보다 낮아질 수 있는가."),
    dict(name="q_markerless_c3_inputs", status="OPEN", closed_by=None,
         body="Markerless C3 inputs(feature extractor + nominal)로 independent gate를 닫을 수 있는가."),
    dict(name="q_sx3i_goal_reframe_0p5_1mm", status="OPEN", closed_by=None,
         body="If fixed-constraint or infield correction cannot collapse the 1.076mm floor, split a realistic 0.5-1.0mm precision branch instead of keeping sub-0.1mm as the active SX3i goal."),
]


def run():
    rows = judged_nodes()
    print("═" * 72)
    print("  SX3i 가지 — 엔진 생성 verdict (손입력 0, record_judge)")
    print("═" * 72)
    # 손입력 대조
    try:
        import examples.sx3i_icp_programme as S
        hand = {n["tag"]: n["verdict"] for n in S.BLOOM_NODES}
    except Exception:
        hand = {}
    print(f"\n  {'노드':28}{'엔진 verdict':16}{'손입력':14}{'divergence'}")
    diverge = []
    for r in rows:
        ev = r["verdict"] or f"[{r.get('status','')}]"
        h = hand.get(r["tag"], "—")
        d = "" if (r["verdict"] == h or r["verdict"] is None and h == "—") else "  ← ❌ 불일치"
        if d:
            diverge.append((r["tag"], ev, h))
        print(f"  {r['tag']:28}{str(ev):16}{str(h):14}{d}")
    print(f"\n  엔진판결 노드: {sum(1 for r in rows if r.get('status') == 'judged')}  "
          f"| 문제-root: {sum(1 for r in rows if r['verdict'] == 'canonical_stage')}  "
          f"| 측정-record 없음(narrative): {sum(1 for r in rows if r.get('status') == 'no_record')}")
    print(f"  손입력↔엔진 divergence: {len(diverge)} {[(t, e, h) for t, e, h in diverge]}")
    print("\n  ★narrative(record 없음) 노드 = 측정 뒷받침 없는 손입력 verdict. 엔진기반 트리에선 verdict 부여 불가.")
    print("═" * 72)
    return rows


if __name__ == "__main__":
    run()
