"""Dogfood 회귀 가드 — LX3 가지가 BPC 줄기에 접붙고, markerless 음의분기를 보존하며,
2026-06-22 ArUco-턴테이블 피벗(과거 "마커 不在" 오해 정정)을 정직하게 반영하는가.

LX3 실측: GROUND_TRUTH σ 37µm progressive, markerless 자동경로는 ceiling(degenerating),
multi-view ICP 는 BPC free-ICP collapse 재확인. 2026-06-22 ArUco-턴테이블로 정합 enabler 확보
(검출 119/121뷰) — 단 정합 정확도는 미측정(OPEN, 검출≠정확도).
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


def test_lx3_aruco_turntable_pivot_corrects_markerless_assumption():
    """2026-06-22 정정: LX3 는 markerless 가 아니라 MIP_36H12 ArUco-턴테이블 정합으로 피벗."""
    out = run()
    # 새 ArUco-턴테이블 가지가 progressive (막힌 enabler 를 닫음)
    assert 'lx3_aruco_turntable' in out['lx3_progressive']
    node = next(n for n in BLOOM_NODES if n['tag'] == 'lx3_aruco_turntable')
    assert node['parent'] == 'lx3_prob'
    # enabler(ArUco init data)는 이제 CLOSED, 정합정확도는 OPEN (검출≠정확도 — 가짜green 금지)
    fr = {q['name']: q for q in BLOOM_FRONTIER}
    assert fr['q_lx3_enabler']['status'] == 'CLOSED'
    assert 'lx3_aruco_turntable' in fr['q_lx3_enabler']['closed_by']
    assert fr['q_lx3_aruco_accuracy']['status'] == 'OPEN'
    # markerless 음의분기는 삭제 아니라 보존(pillar 5: 음의결과 보존)
    assert 'lx3_auto_path_ceiling' in out['lx3_degenerating']
