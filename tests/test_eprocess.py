"""e-process (S9 흡수) 가드 — anytime-valid 연속 증거층의 수학 불변식.

  guard_mechanism : Ville 임계 발화(연속 miss 에서 abandon 신호) + e-BH 의존-강건 reject —
                    메커니즘 실재. 전수 열거(2^n 가중합)로 optional-stopping 유효성
                    P(sup E_t >= 1/α | H0) <= α 를 *결정론적으로* 검증(시뮬레이션 난수 0).
  guard_defect    : E[e|H0] <= 1 위반(고정 BF 상수 누적의 결함 — finding_b2a8aa7064fc11aa)이
                    새 층에서 재발하면 RED. 전부 hit 인 스트림에서 abandon 오발화하면 RED.
# KG: plan-lktadv-p4-eprocess-s9-20260728
"""
from __future__ import annotations

import itertools
import math

import pytest

from lakatos.quant import eprocess as ep


# ── ① p→e calibrator ─────────────────────────────────────────────────────────────────

def test_p_to_e_calibrator_is_valid_and_monotone():
    """κ-calibrator: ∫₀¹ κp^(κ-1) dp = 1 (균등 p = 유효 p 의 최악 케이스에서 E[e|H0]=1).
    수치 적분(사다리꼴, 결정론)으로 검증 + p 단조감소 + 경계 처리."""
    kappa = 0.5
    n = 200_000
    total = 0.0
    for i in range(1, n + 1):                      # (0,1] 오른쪽 리만 합 — 적분 상계
        p = i / n
        total += ep.p_to_e(p, kappa=kappa) / n
    assert total <= 1.0 + 5e-3, "E[e|H0] <= 1 이 calibrator 정의로 성립해야"
    assert total >= 0.98, "적분이 1 근방 (유효성은 등식 근사)"
    assert ep.p_to_e(0.01) > ep.p_to_e(0.5) > ep.p_to_e(1.0)
    assert ep.p_to_e(None) is None
    assert ep.p_to_e(0.0) is None, "p=0 은 정의역 밖 — 무한 e 침묵 발급 금지"
    with pytest.raises(ValueError):
        ep.p_to_e(0.5, kappa=1.5)


# ── ② betting e-process ──────────────────────────────────────────────────────────────

def test_betting_null_expectation_upper_bound():
    """H0: 적중률 >= p0 인 모든 분포에서 한 스텝 기대 E[e_t] <= 1 — 전 그리드 해석 검증.
    (고정 BF 상수 누적이 위반하던 바로 그 부등식 — 재발 시 RED.)"""
    for p0 in (0.2, 0.35, 0.5, 0.7):
        lam = ep.default_lambda(p0)
        for p_hit_pct in range(int(p0 * 100), 101):
            p_hit = p_hit_pct / 100
            exp_e = p_hit * (1 + lam * (p0 - 1)) + (1 - p_hit) * (1 + lam * p0)
            assert exp_e <= 1.0 + 1e-12, f"E[e]={exp_e} > 1 (p0={p0}, p_hit={p_hit})"


def test_betting_wealth_nonnegative_and_lambda_bounds():
    for p0 in (0.2, 0.5, 0.8):
        lam = ep.default_lambda(p0)
        assert 0 < lam < 1 / (1 - p0)
        r = ep.betting_eprocess([1, 0, 1, 0, 0], p0=p0)
        assert all(w >= 0 for w in r['wealth_path'])
    with pytest.raises(ValueError):
        ep.betting_eprocess([1, 0], p0=0.5, lam=3.0)   # λ >= 1/(1-p0) → 음수 wealth 가능
    with pytest.raises(ValueError):
        ep.betting_eprocess([1, 2], p0=0.5)            # 이진 아님 → fail-loud


def test_ville_abandon_fires_on_sustained_misses():
    """메커니즘 실재: p0=0.5 에서 연속 miss 10 → wealth 1.5^10≈57.7 > 1/α=20 → abandon."""
    r = ep.should_abandon_eprocess([0] * 10, p0=0.5, alpha=0.05)
    assert r['abandon'] is True
    assert r['e_max'] >= r['threshold'] == 20.0
    assert r['fired_at'] is not None and r['fired_at'] <= 10


def test_ville_never_fires_on_hits_negative_oracle():
    """음성 오라클: 전부 hit(프로그램 건강) → wealth 는 1 이하로 수축 — abandon 오발화 금지."""
    r = ep.should_abandon_eprocess([1] * 50, p0=0.5, alpha=0.05)
    assert r['abandon'] is False and r['fired_at'] is None
    assert r['e_max'] <= 1.0


def test_optional_stopping_validity_exhaustive():
    """Ville 부등식 실검증 — H0 경계분포(p_hit=p0)에서 전 2^n 시퀀스 가중 열거(난수 0):
    P(sup_t E_t >= 1/α) <= α. 임의 시점 consult(적대적 optional stopping)에도 유효한 이유."""
    p0, alpha, n = 0.5, 0.1, 12
    threshold = 1 / alpha
    p_cross = 0.0
    for seq in itertools.product((0, 1), repeat=n):
        hits = sum(seq)
        prob = (p0 ** hits) * ((1 - p0) ** (n - hits))
        r = ep.betting_eprocess(list(seq), p0=p0)
        if max(r['wealth_path']) >= threshold:
            p_cross += prob
    assert p_cross <= alpha + 1e-12, f"Ville 위반: P(cross)={p_cross} > α={alpha}"
    assert p_cross > 0, "임계 도달 가능 시퀀스가 존재해야 검정이 vacuous 하지 않음"


# ── ③ e-BH ───────────────────────────────────────────────────────────────────────────

def test_e_bh_threshold_rule_and_none_handling():
    """Wang-Ramdas e-BH: 내림차순 e_[k] >= m/(q·k) 인 최대 k 만 reject — 임의 의존 하 FDR<=q.
    m=검정가능(비-None) 수. None 은 검정 불가=False(침묵 통과 금지)."""
    flags = ep.e_bh([30.0, 10.0, 1.0, None], q=0.1)
    assert flags == [True, False, False, False]      # m=3: e_[1]=30 >= 3/(0.1·1)=30 만 통과
    flags2 = ep.e_bh([40.0, 16.0, 1.0], q=0.1)
    assert flags2 == [True, True, False]             # k=2: 16 >= 3/(0.1·2)=15 → 상위 2 reject
    assert ep.e_bh([], q=0.1) == []
    assert ep.e_bh([None, None], q=0.1) == [False, False]


def test_determinism():
    a = ep.should_abandon_eprocess([0, 1, 0, 0, 1, 0], p0=0.4, alpha=0.05)
    b = ep.should_abandon_eprocess([0, 1, 0, 0, 1, 0], p0=0.4, alpha=0.05)
    assert a == b
    assert not any(isinstance(v, float) and math.isnan(v)
                   for v in a.values() if not isinstance(v, (list, tuple, type(None), bool)))


# ── 배선 가드: metrics 층 + e-BH + GROUNDED 소비 ─────────────────────────────────────

def test_grounded_eprocess_constants():
    """관례(test_multiplicity.test_grounded_fdr_q 형): 상수는 GROUNDED 공시 경유 + 인용 실재."""
    from lakatos.grounding import provenance
    assert provenance('eprocess_alpha')['value'] == 0.05
    assert 'Ville' in provenance('eprocess_alpha')['citation']
    assert provenance('eprocess_kappa')['tier'] == 'policy_in_scale'
    assert provenance('eprocess_p0')['tier'] == 'policy', 'p0 는 정책 — 문헌 위장 금지'


def test_eprocess_layer_isolated_and_structural_demote_exclusion():
    """_eprocess_layer 격리(test_metrics *_layer_isolated 관례): 스트림 구성의 정직 —
    구조적 강등(재현성/앵커/stale-engine)은 예측 빗나감이 아니므로 제외 + 별도 공시."""
    from lakatos.quant.metrics import _eprocess_layer
    nodes = (
        [dict(tag=f'm{i:02d}', verdict='partial', verdict_source='scripted',
              current_receipt_sha='r' * 64, novel_registered=True, novel_confirmed=False,
              judged_at=f'2026-07-{(i % 27) + 1:02d}') for i in range(14)]
        + [dict(tag='s1', verdict='partial', verdict_source='scripted',
                current_receipt_sha='r' * 64, novel_registered=True, novel_confirmed=False,
                lakatos_status='reproducibility_refuted', judged_at='2026-07-28'),
           dict(tag='x1', verdict='proof')])          # novel 미등록 — 스트림 밖
    out = _eprocess_layer(nodes)
    assert out['stream_n'] == 14 and out['hits'] == 0
    assert out['excluded_structural'] == ['s1'], '구조적 강등은 반증 스트림에서 제외+공시'
    assert out['abandon'] is True and out['fired_at'] is not None, \
        '연속 miss 14 → wealth (1+λp0)^14 ≈ 28 > 1/α=20 (p0=0.35, λ=0.769) — Ville 발화'


def test_tree_metrics_exposes_eprocess_challenger_and_alert():
    """오케스트레이터 관통 — eprocess 키 + abandon 시 alert 병행(판정 비구속 명시)."""
    from lakatos.quant.metrics import tree_metrics
    nodes = [dict(tag=f'm{i:02d}', verdict='partial', verdict_source='scripted',
                  current_receipt_sha='r' * 64, novel_registered=True, novel_confirmed=False,
                  judged_at=f'2026-07-{i + 1:02d}') for i in range(14)]
    m = tree_metrics(nodes, [])
    assert m['eprocess']['abandon'] is True
    assert m['eprocess']['note'].startswith('K=3')
    assert any('e-process 폐기 신호' in a for a in m['alerts'])
    # 음성 오라클: 전부 적중이면 무발화 + 무경보
    good = [dict(n, novel_confirmed=True) for n in nodes]
    m2 = tree_metrics(good, [])
    assert m2['eprocess']['abandon'] is False
    assert not any('e-process' in a for a in m2['alerts'])


def test_false_progressive_screen_emits_ebh_survivors():
    """e-BH 병행 출력 — 임의 의존 하 FDR<=q, 통상 BH 보다 보수(부분집합 경향)."""
    from lakatos.quant.multiplicity import false_progressive_screen
    cands = [dict(tag='strong', delta=-9.0, noise_band=1.0, direction='lower'),
             dict(tag='weak', delta=-1.0, noise_band=1.0, direction='lower'),
             dict(tag='untest', delta=-5.0, noise_band=0.0, direction='lower')]
    rep = false_progressive_screen(cands)
    assert 'strong' in rep.survivors_ebh
    assert set(rep.survivors_ebh) <= set(rep.survivors_bh), 'e-BH 는 BH 의 부분집합(이 케이스)'
    assert rep.untestable == ('untest',)


# ── 스트림 유효성 수리 가드 (OSS:popper 대조 DEFECT 3건, 2026-07-28) ──────────────────

def test_stream_excludes_unscored_and_unreceipted_nodes():
    """DEFECT 수리: e-process 는 '예측 적중'만 재야 한다 — '적중 AND 영수증 AND 채점'을 재면
    운영 위생 backlog 가 과학적 반증으로 재라벨링된다(POPPER 는 미완료 실험을 e-value 에
    기여시키지 않는다). ①미채점(novel_confirmed=None) ②무영수증(inconclusive) 둘 다 스트림 밖."""
    from lakatos.quant.metrics import _eprocess_layer
    nodes = [
        dict(tag='hit', verdict='progressive', verdict_source='scripted',
             current_receipt_sha='r' * 64, novel_registered=True, novel_confirmed=True,
             judged_at='2026-07-01'),
        dict(tag='miss', verdict='partial', verdict_source='scripted',
             current_receipt_sha='r' * 64, novel_registered=True, novel_confirmed=False,
             judged_at='2026-07-02'),
        dict(tag='unscored', verdict='proof', novel_registered=True,
             novel_confirmed=None),                       # 아직 판정 안 됨 — miss 아님
        dict(tag='unreceipted', verdict='progressive', novel_registered=True,
             novel_confirmed=False, judged_at='2026-07-03'),   # 영수증 없음(force=INCONCLUSIVE)
    ]
    out = _eprocess_layer(nodes)
    assert out['stream_n'] == 2 and out['hits'] == 1, out
    assert out['excluded_unscored'] == ['unscored'], out
    assert out['excluded_unreceipted'] == ['unreceipted'], out


def test_stream_ordering_is_total_and_unjudged_never_leads():
    """judged_at 부재가 문자열 정렬로 스트림 맨 앞에 오면 초기 wealth 증식이 최대화된다 —
    수리 후 미채점은 애초에 스트림 밖이고, 정렬은 결측을 뒤로 보내는 total order 다."""
    from lakatos.quant.metrics import _eprocess_stream_key
    rows = [dict(tag='b', judged_at=None), dict(tag='a', judged_at='2026-07-05'),
            dict(tag='c', judged_at='2026-07-01')]
    assert [r['tag'] for r in sorted(rows, key=_eprocess_stream_key)] == ['c', 'a', 'b']


def test_lambda_direction_note_matches_math():
    """grounding rationale 의 λ 방향 서술이 수학과 일치해야 — λ↓ 는 '보수'가 아니라
    검출 가능 대립가설 영역이 p0 쪽으로 *넓어지는* 대신 증식 속도가 느려지는 것."""
    from lakatos.grounding import provenance
    note = provenance('eprocess_lambda_fraction')['rationale']
    assert 'λ↓ = 보수' not in note, '방향 반대 서술 잔존'
    assert '검출' in note


def test_note_declares_model_assumptions():
    """Ville 보증을 무조건 주장하지 말 것 — payload note 에 스트림 구성 가정을 명시."""
    from lakatos.quant.metrics import _eprocess_layer
    out = _eprocess_layer([dict(tag='x', verdict='partial', verdict_source='scripted',
                                current_receipt_sha='r' * 64, novel_registered=True,
                                novel_confirmed=False, judged_at='2026-07-01')])
    assert '가정' in out['note'] and '영수증' in out['note'], out['note']
