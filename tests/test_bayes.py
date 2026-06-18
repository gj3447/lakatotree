"""베이즈 신뢰도 층 TDD — 강한 가지는 반례 하나로 안 죽는다(수학화).
# KG: SA_LakatoTree_Server_20260612 / span_lakatotree_bayes
"""
from lakatos.quant.bayes import bayes_factor, branch_credence, should_abandon_bayes

def test_bf_ordering():
    # 진보(사전등록 novel 적중) > 땜빵 > 무정보 > 기각
    bf = lambda v: bayes_factor(v, delta=-0.1, noise_band=0.01)
    # F-MATH-1/2: progressive>1=partial(중립), rejected<1 (대칭)
    assert bf('progressive') > 1.0
    assert bayes_factor('partial', delta=-0.1, noise_band=0.01) == 1.0   # 땜빵=무정보
    assert bayes_factor('equivalent') == 1.0
    assert bayes_factor('rejected', delta=0.1, noise_band=0.01) < 1.0

def test_bf_effect_size_monotone():
    # 큰 개선이 마진 개선보다 강한 증거 (BF 가 1에서 더 멀다)
    small = bayes_factor('progressive', delta=-0.005, noise_band=0.01)
    big   = bayes_factor('progressive', delta=-0.2,   noise_band=0.01)
    assert big > small > 1.0
    rs = bayes_factor('rejected', delta=0.005, noise_band=0.01)
    rb = bayes_factor('rejected', delta=0.3,   noise_band=0.01)
    assert rb < rs < 1.0

def test_strong_branch_survives_one_rejection():
    # 라카토스/사용자 직관: 자산 많은 가지는 반례 하나로 안 죽는다
    strong = [{'verdict':'progressive','delta':-0.1,'noise_band':0.01}]*3 + \
             [{'verdict':'rejected','delta':0.05,'noise_band':0.01}]
    ab, c = should_abandon_bayes(strong)
    assert not ab and c > 0.5

def test_weak_branch_abandoned():
    weak = [{'verdict':'partial','delta':-0.002,'noise_band':0.01},
            {'verdict':'rejected','delta':0.2,'noise_band':0.01},
            {'verdict':'rejected','delta':0.2,'noise_band':0.01}]
    ab, c = should_abandon_bayes(weak)
    assert ab and c < 0.1

def test_strong_greater_than_weak():
    strong = [{'verdict':'progressive','delta':-0.1,'noise_band':0.01}]*2
    weak   = [{'verdict':'rejected','delta':0.1,'noise_band':0.01}]*2
    assert branch_credence(strong) > branch_credence(weak)

def test_prior_audit_explicit():
    # 사전확률 주관성(베이즈 한계) → 명시 인자, 같은 증거도 prior 다르면 결과 다름
    ev = [{'verdict':'partial','delta':-0.01,'noise_band':0.01}]
    assert branch_credence(ev, prior=0.8) > branch_credence(ev, prior=0.2)


# === 인터넷 신뢰가중 증거 (P1: 인터넷→베이즈 결합) ===
def test_trust_weighted_evidence():
    from lakatos.quant.bayes import bayes_factor
    # 같은 progressive 증거라도 고신뢰 출처가 신뢰도를 더 움직인다 (BF 가 1에서 더 멀다)
    hi = bayes_factor('progressive', delta=-0.1, noise_band=0.01, source_trust=1.0)
    lo = bayes_factor('progressive', delta=-0.1, noise_band=0.01, source_trust=0.1)
    assert hi > lo > 1.0   # 저신뢰도 증거도 무시는 아님(floor)


def test_branch_credence_source_trust_map_wires_eigentrust():
    # P6: 판결이 source 키를 달면 global_source_trust 맵의 고유벡터 신뢰를 증거가중에 사용
    from lakatos.quant.bayes import branch_credence
    verdicts = [{'verdict': 'progressive', 'delta': 1.0, 'noise_band': 0.1, 'source': 'blog_x'}]
    hi = branch_credence(verdicts, source_trust_map={'blog_x': 0.9})
    lo = branch_credence(verdicts, source_trust_map={'blog_x': 0.05})
    assert hi > lo   # 권위 출처 = 강한 증거 → 높은 신뢰도
    # 맵 미제공 = 기존 동작(scalar default 1.0) 불변
    base = branch_credence([{'verdict': 'progressive', 'delta': 1.0, 'noise_band': 0.1}])
    assert base == branch_credence([{'verdict': 'progressive', 'delta': 1.0, 'noise_band': 0.1}],
                                   source_trust_map=None)


def test_different_programme_distinct_from_degenerating_in_bayes():
    # AXIS-CORR: 정체성 축 분리의 load-bearing 증명 —
    # degenerating(진보축 음의증거)은 credence 를 1/6 BF 로 깎지만,
    # different_programme(정체성축, frontier 범위 밖)은 무정보(BF=1.0)라 credence 불변.
    from lakatos.quant.bayes import branch_credence, BF_BASE, DEFAULT_PRIOR
    assert BF_BASE['different_programme'] == 1.0           # off-axis 무정보(범위 밖)
    assert BF_BASE['degenerating'] < 1.0                   # 진보축 음의증거
    base = DEFAULT_PRIOR
    degen = branch_credence([{'verdict': 'degenerating', 'delta': 0.2, 'noise_band': 0.01}])
    diff = branch_credence([{'verdict': 'different_programme', 'delta': 0.2, 'noise_band': 0.01}])
    assert degen < base          # 퇴행은 신뢰 깎음
    assert diff == base          # 핵이탈은 이 프로그램 신뢰에 무정보(불변)


# ── use-novelty content-dedup (branch_credence 상관보정, Zahar 1973) ──────────
def _p(target=None, delta=-0.5, noise=0.05):
    d = {'verdict': 'progressive', 'delta': delta, 'noise_band': noise}
    if target is not None:
        d['target'] = target
    return d


def test_dedup_same_target_repeats_do_not_inflate():
    from lakatos.quant.bayes import branch_credence
    one = branch_credence([_p('q1')])
    ten = branch_credence([_p('q1')] * 10)           # 같은 타깃 10회 재확증
    assert abs(ten - one) < 1e-12                     # content-dedup: 재확증=초과내용 0 → 불변
    assert ten < 0.9                                  # 인위확신(옛 ~1.0) 제거


def test_distinct_targets_are_independent_evidence():
    from lakatos.quant.bayes import branch_credence
    distinct = branch_credence([_p('q1'), _p('q2'), _p('q3')])
    same = branch_credence([_p('q1')] * 3)
    assert distinct > same                            # 새 예측 3개 > 같은예측 3회(use-novelty)


def test_dedup_commutative_order_independent():
    from lakatos.quant.bayes import branch_credence
    a = branch_credence([_p('q1', delta=-0.2), _p('q1', delta=-0.9), _p('q2', delta=-0.5)])
    b = branch_credence([_p('q2', delta=-0.5), _p('q1', delta=-0.9), _p('q1', delta=-0.2)])
    assert abs(a - b) < 1e-12                          # max-per-target → 순서 무관


def test_dedup_keeps_strongest_confirmation():
    from lakatos.quant.bayes import branch_credence
    weak_then_strong = branch_credence([_p('q1', delta=-0.1), _p('q1', delta=-1.0)])
    strong_only = branch_credence([_p('q1', delta=-1.0)])
    assert abs(weak_then_strong - strong_only) < 1e-12  # 최강 확증만 집계


def test_no_target_is_bit_identical_to_legacy():
    # 현 호출자 대부분(target 미지정) = 기존 동작 비트동일(615 회귀 0 보장)
    from lakatos.quant.bayes import branch_credence
    legacy_style = [{'verdict': 'progressive', 'delta': -0.5, 'noise_band': 0.05}] * 4
    # target 없으면 매번 곱(레거시) — 4회가 1회보다 높아야(누적)
    assert branch_credence(legacy_style) > branch_credence(legacy_style[:1])


def test_negative_evidence_not_deduped():
    from lakatos.quant.bayes import branch_credence
    one = branch_credence([{'verdict': 'rejected', 'delta': 0.3, 'noise_band': 0.01, 'target': 'q1'}])
    three = branch_credence([{'verdict': 'rejected', 'delta': 0.3, 'noise_band': 0.01, 'target': 'q1'}] * 3)
    assert three < one                                 # 반례는 매번 독립부담(약가지 죽어야)


def test_dedup_monotone_nondecreasing():
    from lakatos.quant.bayes import branch_credence
    c1 = branch_credence([_p('q1')])
    c2 = branch_credence([_p('q1'), _p('q2')])
    assert c2 >= c1 and all(0.0 < c < 1.0 for c in (c1, c2))   # 새 타깃 추가 비감소 + 정규화
