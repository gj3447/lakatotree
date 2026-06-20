"""판결 규칙 TDD — 라카토스: 진보 = 새 예측의 적중. LLM 무관 순수함수.
# KG: SA_LakatoTree_Server_20260612 / span_lakatotree_S2_judge_tdd
"""
import pytest
from lakatos.verdict.judge import Prediction, judge, PredictionMissing, PredictionLocked, check_registration

P = dict(metric_name='loo_p95', direction='lower', baseline_value=0.384)

def test_progressive_improved_and_novel():
    from lakatos.verdict.judge import NovelTarget
    # prom-honesty/2: 진짜 초과경험내용 = *독립* 사실(다른 metric)을 독립 측정으로 적중.
    nt = NovelTarget('held_out_psr', 'higher', 0.6)   # 예측 metric(loo_p95)≠novel metric
    v = judge(Prediction(**P, noise_band=0.01, novel_prediction='OUTER 분기 + held-out psr↑'),
              0.279, novel_target=nt, novel_measured=0.7)   # 독립 측정으로 적중
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
    from lakatos.verdict.judge import NovelTarget
    v = judge(Prediction(metric_name='psr', direction='higher', baseline_value=0.5,
                         noise_band=0.0, novel_prediction='x'), 0.7,
              novel_target=NovelTarget('held_out_recall', 'higher', 0.6), novel_measured=0.8)
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
    from lakatos.verdict.judge import NovelTarget
    nt = NovelTarget(metric_name='psr', direction='higher', threshold=0.5)
    v = judge(Prediction(**P, noise_band=0.01, novel_prediction='ignored'),
              measured=0.279, novel_target=nt, novel_measured=0.7)
    assert v.verdict == 'progressive' and v.novel   # 예측 적중

def test_structural_corroboration_miss_demotes_to_partial():
    from lakatos.verdict.judge import NovelTarget
    nt = NovelTarget(metric_name='psr', direction='higher', threshold=0.5)
    v = judge(Prediction(**P, noise_band=0.01, novel_prediction='텍스트만'),
              measured=0.279, novel_target=nt, novel_measured=0.2)   # 예측 빗나감
    assert v.verdict == 'partial' and not v.novel   # 개선이나 novel 미적중 → 땜빵


# === audit P2: novel default-to-measured 붕괴 차단 (같은 측정 1개로 양쪽 만족 금지) ===
def test_novel_target_without_measured_refused_same_metric():
    from lakatos.verdict.judge import NovelTarget
    nt = NovelTarget('loo_p95', 'lower', 0.3)   # 개선 metric 과 동일
    with pytest.raises(ValueError):   # novel_measured 생략 = 가짜 초과내용 → 거부
        judge(Prediction(**P, noise_band=0.01, novel_prediction='x'), 0.279, novel_target=nt)

def test_novel_target_without_measured_refused_diff_metric():
    from lakatos.verdict.judge import NovelTarget
    nt = NovelTarget('psr', 'higher', 0.6)   # 다른 metric 인데 측정 생략 → measured 로 채점 무의미
    with pytest.raises(ValueError):
        judge(Prediction(**P, noise_band=0.01, novel_prediction='x'), 0.279, novel_target=nt)

def test_novelty_sense_default_zahar_and_surfaced():
    from lakatos.verdict.judge import NovelTarget, NOVELTY_SENSES
    nt = NovelTarget('held_out_psr', 'higher', 0.6)
    assert nt.novelty_sense == 'zahar_use_novelty' and nt.novelty_sense in NOVELTY_SENSES
    v = judge(Prediction(**P, noise_band=0.01, novel_prediction='x'), 0.279,
              novel_target=nt, novel_measured=0.7)
    assert v.verdict == 'progressive' and 'novelty_sense=zahar_use_novelty' in v.reason

# === prom-honesty/2 (적대감사 2026-06-20): novel 독립성 — 같은 측정 재활용 ≠ 초과경험내용 ===
def test_same_metric_same_measurement_is_not_novel():
    """같은 metric 의 *동일 측정*(novel_measured == measured)을 novel 로 재활용 → progressive 불가(partial).
    improved 를 만든 그 수를 novel 확증으로 되쓰는 가짜 초과내용(Zahar use-novelty 위반)."""
    from lakatos.verdict.judge import NovelTarget
    nt = NovelTarget('loo_p95', 'lower', 0.3)   # 예측 metric 과 동일
    v = judge(Prediction(**P, noise_band=0.01, novel_prediction='x'),
              measured=0.279, novel_target=nt, novel_measured=0.279)   # improved 측정 그대로 재활용
    assert v.verdict == 'partial' and not v.novel and '비독립' in v.reason

def test_same_metric_independent_value_can_still_be_novel():
    """같은 metric 이라도 *다른*(독립) 측정값이면 막지 않는다 — 값+epsilon 우회는 출처-sha 강제가 후속 과제."""
    from lakatos.verdict.judge import NovelTarget
    nt = NovelTarget('loo_p95', 'lower', 0.25)
    v = judge(Prediction(**P, noise_band=0.01, novel_prediction='x'),
              measured=0.279, novel_target=nt, novel_measured=0.24)   # measured 와 다른 독립 측정
    assert v.verdict == 'progressive' and v.novel

def test_independent_metric_is_progressive():
    """다른 metric 의 독립 적중 = 진짜 초과경험내용 → progressive."""
    from lakatos.verdict.judge import NovelTarget
    nt = NovelTarget('held_out_psr', 'higher', 0.6)
    v = judge(Prediction(**P, noise_band=0.01, novel_prediction='x'),
              measured=0.279, novel_target=nt, novel_measured=0.7)
    assert v.verdict == 'progressive' and v.novel

# === prom-honesty/sha (적대감사 2026-06-20): 출처 독립성 — 같은 metric+epsilon 우회 봉쇄 ===
def test_same_metric_same_sha_epsilon_rejected():
    """같은 metric + *같은 출처 sha* 면 값이 epsilon 만 달라도 비독립(같은 측정 재활용) → progressive 불가.
    PROM-B 의 값-동일 체크가 못 막던 epsilon 우회를 출처-sha 로 봉쇄."""
    from lakatos.verdict.judge import NovelTarget
    nt = NovelTarget('loo_p95', 'lower', 0.3)   # 예측과 같은 metric
    v = judge(Prediction(**P, noise_band=0.01, novel_prediction='x'),
              measured=0.279, novel_target=nt, novel_measured=0.2790001,   # measured+epsilon
              measured_sha='abc123', novel_sha='abc123')                   # 같은 출처
    assert v.verdict == 'partial' and not v.novel and '비독립' in v.reason

def test_same_metric_distinct_sha_is_novel():
    """같은 metric 이라도 *다른 출처 sha* = 독립 측정 → epsilon 값이어도 novel 정당(held-out 등)."""
    from lakatos.verdict.judge import NovelTarget
    nt = NovelTarget('loo_p95', 'lower', 0.3)
    v = judge(Prediction(**P, noise_band=0.01, novel_prediction='x'),
              measured=0.279, novel_target=nt, novel_measured=0.2790001,
              measured_sha='abc123', novel_sha='def456')                   # 독립 출처
    assert v.verdict == 'progressive' and v.novel

def test_same_sha_exact_value_still_rejected():
    """출처 sha 가 같으면 값이 정확히 같아도 당연히 거부(값-체크를 sha-체크가 포섭)."""
    from lakatos.verdict.judge import NovelTarget
    nt = NovelTarget('loo_p95', 'lower', 0.3)
    v = judge(Prediction(**P, noise_band=0.01, novel_prediction='x'),
              measured=0.279, novel_target=nt, novel_measured=0.279,
              measured_sha='same', novel_sha='same')
    assert v.verdict == 'partial' and not v.novel

def test_sha_absent_falls_back_to_value_check():
    """sha 미제공(레거시)이면 PROM-B 값-동일 폴백 — 동일값 거부, 다른값 허용(비트동일 보존)."""
    from lakatos.verdict.judge import NovelTarget
    nt = NovelTarget('loo_p95', 'lower', 0.3)
    same = judge(Prediction(**P, noise_band=0.01, novel_prediction='x'),
                 0.279, novel_target=nt, novel_measured=0.279)
    diff = judge(Prediction(**P, noise_band=0.01, novel_prediction='x'),
                 0.279, novel_target=nt, novel_measured=0.24)
    assert same.verdict == 'partial' and diff.verdict == 'progressive'


def test_novelty_sense_tag_only_does_not_change_scoring():
    # temporal/worrall 태그여도 채점은 zahar 와 동일(구조적 corroboration) — 의미 논쟁 점수화 안 함
    from lakatos.verdict.judge import NovelTarget
    for sense in ('temporal_novelty', 'worrall_use_novelty'):
        nt = NovelTarget('psr', 'higher', 0.5, novelty_sense=sense)
        v = judge(Prediction(**P, noise_band=0.01, novel_prediction='x'),
                  measured=0.279, novel_target=nt, novel_measured=0.7)
        assert v.verdict == 'progressive' and v.novel
