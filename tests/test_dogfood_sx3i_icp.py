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
    """측정으로 자란 마디 — C1/C1b 는 partial(실재·dict 확인, 신뢰검출 미달)."""
    out = run()
    by = {n['tag']: n for n in BLOOM_NODES}
    assert by['c1_marker_detect']['verdict'] == 'partial'
    assert by['c1b_consistency']['verdict'] == 'partial'
    # 접붙임 체인: C1←sx3i_prob, C1b←C1
    assert by['c1_marker_detect']['parent'] == 'sx3i_prob'
    assert by['c1b_consistency']['parent'] == 'c1_marker_detect'
    assert set(out['sx3i_partial']) == {'c1_marker_detect', 'c1b_consistency'}


def test_sx3i_remaining_frontier_open():
    out = run()
    # C2~C5 는 아직 미측정 → OPEN. 측정이 C1b denoise 선결과제(q_denoise_coverage)를 새로 엶.
    assert all(q['status'] == 'OPEN' for q in BLOOM_FRONTIER)
    assert out['open_frontier'] == ['q_xl250_gsd', 'q_sx3i_assemble',
                                    'q_independent_accuracy', 'q_raw_refine',
                                    'q_crosscam', 'q_denoise_coverage']
    # C3⭐ 독립 정밀게이트가 존재(precision≠accuracy 를 닫는 관문)
    assert 'q_independent_accuracy' in out['open_frontier']
    # 측정이 연 새 질문
    assert 'q_denoise_coverage' in out['open_frontier']
