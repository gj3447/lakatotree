"""jp6-cross-metric-novelty — judge() opt-in 독립출처 게이트 (RED-first 이중가드).

JP 캠페인(LakatosTree_JudgeProprioception_20260708) jp6: FF1 이 의도적으로 남긴 순수 judge()
하네스 경로에서 relabel 공격(m→m_v2 개명 + measured==novel_measured + 빈 sha)이 excess content 0
으로 progressive 를 mint 하던 결함. 봉합 = 비파괴 opt-in(require_independent_source, 기본 False):
armed 시 cross-metric novel 도 distinct sha OR 선언 independence_witness 요구. T3 정직 경계:
순수술어로 causal 독립 증명 불가 — witness 는 silent license 를 explicit·challengeable 선언으로
바꿀 뿐이다. jp6a 정정 준수: 커널 rip-out 은 FF1 2층과 충돌(49 RED)로 반증 — 이 게이트는
same-metric noindep(judge.py:134)와 같은 기제(novel→False demote), 다른 스코프.

guard_defect   : test_relabel_attack_flag_on_demoted_to_partial (fix 전 RED: TypeError — 표면 부재)
guard_mechanism: distinct-sha/witness 변형은 armed 에서도 progressive(과잉차단 배제) + 기본off 무변경 핀
"""
import pytest

from lakatos.verdict.judge import NovelTarget, Prediction, judge

P = dict(metric_name='m', direction='higher', baseline_value=0.0)
_ATTACK = dict(novel_target=NovelTarget('m_v2', 'higher', 1.0), novel_measured=1.0)


def _pred():
    return Prediction(**P, novel_prediction='x')


def test_relabel_attack_flag_on_demoted_to_partial():
    """guard_defect: armed 게이트가 relabel 공격(빈 sha·witness 부재) 기각 — fix 전 TypeError=RED."""
    v = judge(_pred(), 1.0, **_ATTACK, require_independent_source=True)
    assert v.verdict == 'partial' and not v.novel
    assert '비독립' in v.reason and 'cross-metric' in v.reason


def test_relabel_attack_default_unchanged_progressive():
    """비파괴 회귀핀 + FF1 잔여의 정직 기록: 기본(off)에서 커널은 의도적으로 permissive."""
    v = judge(_pred(), 1.0, **_ATTACK)
    assert v.verdict == 'progressive' and v.novel


def test_distinct_sha_cross_metric_still_progressive_flag_on():
    """과잉차단 가드: 독립 출처(distinct sha) cross-metric novel 은 armed 에서도 진짜 초과내용."""
    v = judge(_pred(), 1.0, **_ATTACK, measured_sha='a', novel_sha='b',
              require_independent_source=True)
    assert v.verdict == 'progressive' and v.novel


def test_witness_licenses_and_is_sealed_in_reason():
    """witness = T3 정직 탈출구: 선언이 reason 에 봉인(explicit·challengeable) — causal 증명 주장 아님."""
    v = judge(_pred(), 1.0, **_ATTACK, require_independent_source=True,
              independence_witness='held-out corpus run 2026-07-10')
    assert v.verdict == 'progressive' and v.novel
    assert 'independence_witness: held-out corpus run 2026-07-10' in v.reason


def test_witness_only_stamped_when_it_carries_the_license():
    """distinct sha 가 이미 독립을 증명하면 witness 마커 미봉인 — 일 안 한 장식이 공적을 주장 못 함."""
    v = judge(_pred(), 1.0, **_ATTACK, measured_sha='a', novel_sha='b',
              require_independent_source=True, independence_witness='redundant')
    assert v.verdict == 'progressive' and 'independence_witness' not in v.reason


def test_witness_without_flag_refused():
    """죽은 장식 금지: 아무 일도 안 하는 witness 는 조용히 붙을 수 없다 — fail-loud."""
    with pytest.raises(ValueError):
        judge(_pred(), 1.0, **_ATTACK, independence_witness='x')


def test_witness_without_novel_target_refused():
    """novel 주장 없는 witness 도 장식 — 거부."""
    with pytest.raises(ValueError):
        judge(_pred(), 1.0, require_independent_source=True, independence_witness='x')


def test_blank_witness_does_not_license():
    """공백 witness 는 witness 가 아님(strip) — armed 게이트가 그대로 demote."""
    v = judge(_pred(), 1.0, **_ATTACK, require_independent_source=True,
              independence_witness='   ')
    assert v.verdict == 'partial' and not v.novel


def test_same_metric_sha_gate_not_weakened_by_witness():
    """monotone-stricter 증명: witness 는 cross-metric 전용 — same-metric 동일출처를 witness 로 못 산다."""
    nt = NovelTarget('m', 'higher', 1.0)   # 예측과 같은 metric
    v = judge(_pred(), 1.0, novel_target=nt, novel_measured=1.0,
              measured_sha='s', novel_sha='s',
              require_independent_source=True, independence_witness='irrelevant')
    assert v.verdict == 'partial' and not v.novel


def test_flag_without_novel_target_inert():
    """armed 인데 novel 주장 없음 = 게이트 발화 대상 없음 — 평가만 정상 진행(fail 안 함)."""
    v = judge(_pred(), 1.0, require_independent_source=True)
    assert v.verdict == 'partial'   # improved, novel 없음 — 기존 경로 그대로
