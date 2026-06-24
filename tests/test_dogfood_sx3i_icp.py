"""Dogfood 회귀 가드 — SX3i 가지(2026-06-24 리더버그 정정 후).

핵심 정직성:
- 2026-06-23 'speckle 검출취약 / denoise-salvage 반증 / Settings2D 재촬영' 결론은 misdiagnosis 였다 —
  진짜 원인 = prismv2 zdf_reader.read_rgb 가 SNR(float32) 프레임을 색으로 오선택. 고친 리더+STRICT 로
  40뷰 중 34뷰·331마커·side_px median 90.6px(20px 100%) 검출됨.
- C1 = grounded **progressive**, 단 **CONFIRMED/CANONICAL 아님**(전 212뷰 미확정). C2~C5 는 OPEN.
- misdiagnosis 는 삭제가 아니라 rejected 노드 + CLOSED 교훈 frontier 로 **보존**(기둥5).
"""
from examples.sx3i_icp_programme import run, BLOOM_NODES, BLOOM_FRONTIER, BLOOM_AT


def test_sx3i_blooms_at_v8_step6_1():
    out = run()
    assert out['bloom_at'] == 'v8_pipeline'              # BPC v8 의 precision≠accuracy 갭에서 피어남
    assert BLOOM_AT == 'v8_pipeline'
    prob = next(n for n in BLOOM_NODES if n['tag'] == 'sx3i_prob')
    assert prob['parent'] == 'v8_pipeline'


def test_sx3i_c1_regrounded_progressive_not_confirmed():
    """리더fix 후 C1 검출 grounded → progressive. 단 CANONICAL/CONFIRMED 아님(가짜green 금지)."""
    out = run()
    by = {n['tag']: n for n in BLOOM_NODES}
    assert by['c1_marker_detect']['verdict'] == 'progressive'
    assert by['reader_frame_provenance_fix']['verdict'] == 'progressive'
    assert set(out['sx3i_progressive_tags']) == {'c1_marker_detect', 'reader_frame_provenance_fix'}
    # SX3i 는 CANONICAL 노드가 없다(CONFIRMED 아님) — 통합 정본은 여전히 BPC v8
    assert not any(n['verdict'] == 'CANONICAL' for n in BLOOM_NODES)
    assert out['canonical'] == 'v8_pipeline'


def test_sx3i_gsd_closed_by_grounded_measurement():
    """q_xl250_gsd 는 측정으로 닫힘(side_px median 90.6 ≥ 20, 34/40뷰 검출) — 진짜 grounded 답."""
    out = run()
    fr = {q['name']: q for q in BLOOM_FRONTIER}
    assert fr['q_xl250_gsd']['status'] == 'CLOSED'
    assert fr['q_xl250_gsd']['closed_by'] == 'c1_marker_detect'
    assert '90.6' in fr['q_xl250_gsd']['body']
    assert 'q_xl250_gsd' in out['closed_frontier']


def test_sx3i_reader_misdiagnosis_preserved_as_lesson():
    """speckle/denoise/재촬영 = 리더버그 그림자. 삭제 아니라 rejected 노드 + CLOSED 교훈 frontier 로 보존."""
    out = run()
    by = {n['tag']: n for n in BLOOM_NODES}
    assert by['misdiag_reader_frame']['verdict'] == 'rejected'
    assert out['sx3i_rejected'] == ['misdiag_reader_frame']
    fr = {q['name']: q for q in BLOOM_FRONTIER}
    assert fr['q_reader_frame_misdiagnosis']['status'] == 'CLOSED'
    assert fr['q_reader_frame_misdiagnosis']['closed_by'] == 'reader_frame_provenance_fix'
    # 옛 misdiagnosis frontier 는 제거됨(허위질문) — 부활 금지
    names = {q['name'] for q in BLOOM_FRONTIER}
    assert 'q_denoise_coverage' not in names
    assert 'q_recapture_settings2d' not in names
    # 옛 가짜퇴행 노드(c1b_denoise/c1b_consistency = 리더버그 그림자)는 제거됨.
    # (정당한 다른 퇴행 노드 — 예: markerless 실데이터 c3_markerless_real — 은 무관·허용.)
    tags = {n['tag'] for n in BLOOM_NODES}
    assert 'c1b_denoise' not in tags and 'c1b_consistency' not in tags


def test_sx3i_c2_to_c5_still_open_no_fake_green():
    out = run()
    open_names = set(out['open_frontier'])
    # C2~C5 + 물리관문 + markerless 입력 = 전부 미측정 OPEN
    assert {'q_sx3i_assemble', 'q_independent_accuracy', 'q_raw_refine', 'q_crosscam',
            'q_sx3i_precision_floor', 'q_markerless_c3_inputs'} <= open_names
    # C3⭐ 핵심 게이트는 여전히 미측정
    assert 'q_independent_accuracy' in open_names
    # markerless C3 instrument 는 리더버그와 독립 — partial 유지
    by = {n['tag']: n for n in BLOOM_NODES}
    assert by['c3_markerless_instrument']['verdict'] == 'partial'


def test_sx3i_precision_floor_preregistered_open():
    """C3 앞 물리관문 q_sx3i_precision_floor 는 사전등록됐으나 미측정 → OPEN(리더버그와 무관, 그대로)."""
    q = next(q for q in BLOOM_FRONTIER if q['name'] == 'q_sx3i_precision_floor')
    assert q['status'] == 'OPEN' and q['closed_by'] is None        # 측정 전 — 안 닫힘
    assert '250' in q['body'] and '0.10mm' in q['body']            # 사전등록 예측·band 명시
