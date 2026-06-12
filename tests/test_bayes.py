"""베이즈 신뢰도 층 TDD — 강한 가지는 반례 하나로 안 죽는다(수학화).
# KG: SA_LakatoTree_Server_20260612 / span_lakatotree_bayes
"""
from lakatos.bayes import bayes_factor, branch_credence, should_abandon_bayes

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
    from lakatos.bayes import bayes_factor
    # 같은 progressive 증거라도 고신뢰 출처가 신뢰도를 더 움직인다 (BF 가 1에서 더 멀다)
    hi = bayes_factor('progressive', delta=-0.1, noise_band=0.01, source_trust=1.0)
    lo = bayes_factor('progressive', delta=-0.1, noise_band=0.01, source_trust=0.1)
    assert hi > lo > 1.0   # 저신뢰도 증거도 무시는 아님(floor)
