"""Dogfood 회귀 가드 — LX3 가지가 BPC 줄기에 접붙고, markerless 음의분기를 보존하며,
2026-06-22 ArUco-턴테이블 피벗(과거 "마커 不在" 오해 정정)을 정직하게 반영하는가.

LX3 실측: GROUND_TRUTH σ 37µm progressive, markerless 자동경로는 ceiling(degenerating),
multi-view ICP 는 BPC free-ICP collapse 재확인. ★2026-06-24 grounded: 옛 'ArUco 119/121'은 reader
SNR-노이즈였으나, 고친 색프레임+brightening 으로 실 MIP_36H12 마커 검출 → turntable progressive, enabler CLOSED.
"""
from examples.lx3_icp_programme import run, BLOOM_NODES, BLOOM_FRONTIER, BLOOM_AT


def test_lx3_blooms_at_aruco_metric():
    out = run()
    assert out['bloom_at'] == 'aruco_metric'             # ArUco 정합 결정점에서 분기
    assert BLOOM_AT == 'aruco_metric'
    prob = next(n for n in BLOOM_NODES if n['tag'] == 'lx3_prob')
    assert prob['parent'] == 'aruco_metric'


def test_lx3_groundtruth_progressive_but_markerless_autopath_ceiling():
    out = run()
    # 실측 GROUND_TRUTH 는 progressive (R&R σ 37µm BPC-grade)
    assert 'lx3_groundtruth_oracle' in out['lx3_progressive']
    # markerless 자동 정합 경로는 degenerating (보존된 음의분기)
    assert 'lx3_auto_path_ceiling' in out['lx3_degenerating']
    # LX3 정합정확도 미측정 → 통합 정본은 BPC v8 유지 (정직)
    assert out['canonical'] == 'v8_pipeline'


def test_lx3_reconfirms_free_icp_collapse_hardcore():
    out = run()
    # markerless multi-view ICP identity-basin = BPC hard-core(free-ICP collapse) 재확인
    assert 'lx3_identity_basin' in out['lx3_degenerating']
    basin = next(n for n in BLOOM_NODES if n['tag'] == 'lx3_identity_basin')
    assert basin['verdict'] == 'degenerating'


def test_lx3_aruco_markers_real_grounded_by_brightening():
    """★2026-06-24 grounded 최종: 옛 '119/121'은 reader SNR-노이즈였으나, 고친 색프레임+brightening
    (gamma+CLAHE)으로 실 MIP_36H12 마커 검출(23/24뷰·≥3뷰반복 10종·side_px 60px) → progressive,
    enabler CLOSED. 어두움=전처리문제지 하드한계 아님. 정합 정확도는 여전히 OPEN(검출≠정확도)."""
    out = run()
    node = next(n for n in BLOOM_NODES if n['tag'] == 'lx3_aruco_turntable')
    assert node['verdict'] == 'progressive'              # 검출 grounded (실 마커, 노이즈 아님)
    assert node['parent'] == 'lx3_prob'
    assert 'lx3_aruco_turntable' in out['lx3_progressive']
    fr = {q['name']: q for q in BLOOM_FRONTIER}
    # enabler(ArUco init data)는 실 마커 검출로 CLOSED, 정합 정확도는 미측정 OPEN
    assert fr['q_lx3_enabler']['status'] == 'CLOSED'
    assert 'lx3_aruco_turntable' in fr['q_lx3_enabler']['closed_by']
    assert fr['q_lx3_aruco_accuracy']['status'] == 'OPEN'   # 검출≠정확도 — 가짜green 금지
    # markerless 음의분기·collapse 교훈은 그대로 보존(pillar 5)
    assert 'lx3_auto_path_ceiling' in out['lx3_degenerating']
    assert 'lx3_groundtruth_oracle' in out['lx3_progressive']
