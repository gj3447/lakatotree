"""Dogfood 회귀 가드 — SX3i 가지가 BPC 줄기에 정직하게 접붙는가.

핵심 정직성: 측정 없는 conjecture 를 progressive 로 박으면 자기채점=가짜green.
2026-06-23 첫 실데이터 구동으로 C1/C1b 는 **partial**(측정 마디, progressive 아님)이 됐다 —
마커 실재·dict ✅ 이나 speckle 로 신뢰검출 미달이라 CONFIRMED 아님. 따라서 *여전히*
진보노드 0(CANONICAL 미획득) 이고 C2~C5 는 OPEN frontier 여야 한다(측정이 q_denoise_coverage 를 새로 엶).
"""
from examples.sx3i_icp_programme import run, BLOOM_NODES, BLOOM_FRONTIER, BLOOM_AT


def test_sx3i_blooms_at_v8_step6_1():
    out = run()
    assert out['bloom_at'] == 'v8_pipeline'              # BPC v8 의 precision≠accuracy 갭에서 피어남
    assert BLOOM_AT == 'v8_pipeline'
    # 가지 root 노드의 parent 가 줄기 마디를 가리킴 (접붙임 증명)
    prob = next(n for n in BLOOM_NODES if n['tag'] == 'sx3i_prob')
    assert prob['parent'] == 'v8_pipeline'


def test_sx3i_no_fake_green():
    out = run()
    # 진보노드 0 — partial 은 측정됐어도 progressive 아님(가짜green 금지). CANONICAL 미획득.
    assert out['sx3i_progressive'] == 0
    assert not any(n['verdict'] in ('progressive', 'CANONICAL') for n in BLOOM_NODES)
    # 통합 정본은 여전히 BPC v8 (SX3i 가 정본 가로채지 않음)
    assert out['canonical'] == 'v8_pipeline'


def test_sx3i_c1_c1b_measured_as_partial():
    """측정으로 자란 마디 — C1/C1b + 분기전환 A/B 노드 모두 partial(가짜green 아님)."""
    out = run()
    by = {n['tag']: n for n in BLOOM_NODES}
    assert by['c1_marker_detect']['verdict'] == 'partial'
    assert by['c1b_consistency']['verdict'] == 'partial'
    # 접붙임 체인: C1←sx3i_prob, C1b←C1
    assert by['c1_marker_detect']['parent'] == 'sx3i_prob'
    assert by['c1b_consistency']['parent'] == 'c1_marker_detect'
    # 분기전환 A(재촬영 root cause)·B(markerless C3 instrument) 도 측정 partial 마디
    assert by['c1_rootcause_settings2d']['verdict'] == 'partial'
    assert by['c3_markerless_instrument']['verdict'] == 'partial'
    assert set(out['sx3i_partial']) == {'c1_marker_detect', 'c1b_consistency',
                                        'c1_rootcause_settings2d', 'c3_markerless_instrument'}


def test_sx3i_denoise_refuted_branch_switch():
    """denoise 다리1 반증 — degenerating 노드 + denoise 질문 CLOSED(부정답) + 분기전환 OPEN."""
    out = run()
    by = {n['tag']: n for n in BLOOM_NODES}
    # denoise salvage 가 degenerating 으로 기록(가짜green 아님 — 반증)
    assert by['c1b_denoise']['verdict'] == 'degenerating'
    assert out['sx3i_degenerating'] == ['c1b_denoise']
    fr = {q['name']: q for q in BLOOM_FRONTIER}
    # denoise 질문은 측정으로 답(부정) → CLOSED, 그 degenerating 노드가 닫음
    assert fr['q_denoise_coverage']['status'] == 'CLOSED'
    assert fr['q_denoise_coverage']['closed_by'] == 'c1b_denoise'
    # 분기전환 질문이 두 갈래로 새로 열림 (A 재촬영 / B markerless)
    assert fr['q_recapture_settings2d']['status'] == 'OPEN'
    assert fr['q_markerless_c3_inputs']['status'] == 'OPEN'


def test_sx3i_remaining_frontier():
    out = run()
    # C2~C5 미측정 → OPEN. C3⭐ 정밀게이트 존재. denoise 닫힘. 분기 A·B 질문 열림.
    assert out['open_frontier'] == ['q_xl250_gsd', 'q_sx3i_assemble',
                                    'q_independent_accuracy', 'q_raw_refine', 'q_crosscam',
                                    'q_recapture_settings2d', 'q_markerless_c3_inputs']
    assert 'q_independent_accuracy' in out['open_frontier']
    assert 'q_denoise_coverage' not in out['open_frontier']  # 측정으로 닫힘
    # 분기전환이 두 갈래로 열림(A 재촬영 / B markerless)
    assert {'q_recapture_settings2d', 'q_markerless_c3_inputs'} <= set(out['open_frontier'])
