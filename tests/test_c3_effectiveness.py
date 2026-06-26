"""C3 Phase-1 retrospective 측정 — 역사적 Lakatos corpus 로 engine vs self-report (외부리뷰 B-5).

프로토콜(docs/C3_EFFECTIVENESS_PROTOCOL.md): engine(judge, use-novelty 게이트)이 confabulation baseline
(self-report, novelty 무시)보다 ground-truth 일치/환각에서 우월한가.

★construct-validity caveat(프로토콜 §6 위협#1): corpus 가 Lakatos *자신의 예시*라, 엔진 고정확도는
"Lakatos 를 옳게 기계화했다"는 증거지 *독립* 효과성 증명이 아니다(독립 증명=Phase-2 전향 사전등록).
이 테스트가 고정하는 것: 측정 machinery 가 돌고, 그 위에서 engine 이 self-report 를 이긴다(Phase-1 신호).
"""
from examples.c3_effectiveness_corpus import (
    CORPUS, register_prospective, resolve_prospective, run, score_prospective,
)


def test_corpus_has_ground_truth_and_min_sample_both_classes():
    assert len(CORPUS) >= 9                                 # 프로토콜 §3: Wilson 실효 표본 근거
    assert all(c['ground_truth'] in ('progressive', 'degenerating') for c in CORPUS)
    assert {c['ground_truth'] for c in CORPUS} == {'progressive', 'degenerating'}   # 양쪽 포함


def test_engine_beats_self_report_h1_supported():
    r = run()
    eng, sr = r['engine'], r['self_report']
    # H1(프로토콜 §1): engine Wilson 하한 > self-report Wilson 하한 (반증조건의 반대 = 지지)
    assert eng['accuracy_wilson_lb'] > sr['accuracy_wilson_lb']
    assert eng['accuracy'] >= sr['accuracy']


def test_self_report_hallucinates_on_adhoc_patches_engine_does_not():
    r = run()
    # confabulation baseline 은 ad-hoc 패치(데이터 맞춤·novel 없음)를 진보로 오판(가짜 aha) —
    # engine 은 use-novelty 게이트로 partial(퇴행) 처리. ~37% 인간 false-insight 의 기계 유비.
    assert r['self_report']['hallucination_rate'] > r['engine']['hallucination_rate']
    assert r['engine']['hallucination_rate'] == 0.0
    assert 'lorentz_ether_contraction' in r['self_report']['false_progressives']


# ── Phase 2 (prospective) harness — 기계장치 검증(실 해소는 종단) ─────────────
def test_prospective_harness_register_resolve_score():
    e1 = register_prospective('q-open-1', pred_credence=0.8, novel_target_desc='X>θ')
    e2 = register_prospective('q-open-2', pred_credence=0.7, novel_target_desc='Y<θ')
    assert e1['status'] == 'open' and score_prospective([e1, e2])['resolved'] == 0   # 미해소 = open
    r1 = resolve_prospective(e1, novel_confirmed=True)                                # 신뢰 0.8 + 확증 → hit
    assert r1['status'] == 'resolved' and r1['hit'] is True
    s = score_prospective([r1, e2])
    assert s['resolved'] == 1 and s['open'] == 1 and 0.0 <= s['brier'] <= 1.0
    assert '독립 효과성' in s['note']                  # 순환성 없는 gold standard 명시
