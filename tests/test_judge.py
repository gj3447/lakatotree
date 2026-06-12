"""판결 규칙 TDD — 라카토스: 진보 = 새 예측의 적중. LLM 무관 순수함수.
# KG: SA_LakatoTree_Server_20260612 / span_lakatotree_S2_judge_tdd
"""
import pytest
from lakatos.judge import Prediction, judge, PredictionMissing, PredictionLocked, check_registration

P = dict(metric_name='loo_p95', direction='lower', baseline_value=0.384)

def test_progressive_improved_and_novel():
    from lakatos.judge import NovelTarget
    nt = NovelTarget('loo_p95', 'lower', 0.3)   # F-CON-3: 구조적 예측 필수
    v = judge(Prediction(**P, noise_band=0.01, novel_prediction='OUTER 분기로 0.3 이하'),
              0.279, novel_target=nt, novel_measured=0.279)
    assert v.verdict == 'progressive' and v.improved and round(v.delta, 3) == -0.105

def test_partial_improved_without_novel():
    v = judge(Prediction(**P, noise_band=0.01, novel_prediction=''), 0.279)
    assert v.verdict == 'partial'   # 땜빵성 개선 — 라카토스가 경계한 것

def test_text_only_novelty_is_not_progressive():   # F-CON-3 회귀
    v = judge(Prediction(**P, noise_band=0.01, novel_prediction='x'), 0.279)
    assert v.verdict == 'partial'   # 한 글자 텍스트로 progressive 못 받음

def test_equivalent_within_noise():
    v = judge(Prediction(**P, noise_band=0.02, novel_prediction='x'), 0.380)
    assert v.verdict == 'equivalent'

def test_rejected_worse():
    v = judge(Prediction(**P, noise_band=0.01, novel_prediction='x'), 0.433)
    assert v.verdict == 'rejected'

def test_higher_direction():
    from lakatos.judge import NovelTarget
    v = judge(Prediction(metric_name='psr', direction='higher', baseline_value=0.5,
                         noise_band=0.0, novel_prediction='x'), 0.7,
              novel_target=NovelTarget('psr', 'higher', 0.6), novel_measured=0.7)
    assert v.verdict == 'progressive'

def test_missing_prediction_refused():
    with pytest.raises(PredictionMissing):
        judge(None, 0.279)

def test_post_judgment_registration_refused():
    with pytest.raises(PredictionLocked):
        check_registration(already_judged=True)
    check_registration(already_judged=False)   # 통과


# === 적대 검증(나생문) BLOCKER 회귀 테스트 — F-FG-2 ===
def test_negative_noise_band_refused():
    """음수 노이즈밴드 = worse-is-progressive 조작 → 거부."""
    with pytest.raises(ValueError):
        Prediction(**P, noise_band=-0.5, novel_prediction='x')

def test_nan_measured_refused():
    import math
    with pytest.raises(ValueError):
        judge(Prediction(**P, noise_band=0.01, novel_prediction='x'), float('nan'))

def test_worse_never_progressive():
    """어떤 합법 입력으로도 악화(delta 악화)가 progressive 될 수 없다."""
    v = judge(Prediction(metric_name='m', direction='lower', baseline_value=1.0,
                         noise_band=0.0, novel_prediction='x'), 1.3)
    assert v.verdict == 'rejected'


# === 구조적 corroboration (gap1/F-FG-2 해소) ===
def test_structural_corroboration_hit():
    from lakatos.judge import NovelTarget
    nt = NovelTarget(metric_name='psr', direction='higher', threshold=0.5)
    v = judge(Prediction(**P, noise_band=0.01, novel_prediction='ignored'),
              measured=0.279, novel_target=nt, novel_measured=0.7)
    assert v.verdict == 'progressive' and v.novel   # 예측 적중

def test_structural_corroboration_miss_demotes_to_partial():
    from lakatos.judge import NovelTarget
    nt = NovelTarget(metric_name='psr', direction='higher', threshold=0.5)
    v = judge(Prediction(**P, noise_band=0.01, novel_prediction='텍스트만'),
              measured=0.279, novel_target=nt, novel_measured=0.2)   # 예측 빗나감
    assert v.verdict == 'partial' and not v.novel   # 개선이나 novel 미적중 → 땜빵
