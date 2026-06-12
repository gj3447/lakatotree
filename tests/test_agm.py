"""P1 AGM 신념개정 — hard core 보호 + Levi identity + 공준(success/inclusion/vacuity) 검증."""
import pytest

from lakatos.agm import (
    Belief, HardCoreProtected, RevisionResult,
    contraction, demote_canonical, entrenchment_key, expansion, revision,
)

HC = Belief('hc1', '20뷰 frozen calibration 은 lot 간 재사용 가능', kind='hard_core',
            credence=0.95, problem_balance=3, connectivity=5)
BELT1 = Belief('b1', 'per-view z-only refresh 가 seam 을 닫는다', credence=0.7,
               depends_on=('hc1',))
BELT2 = Belief('b2', 'SNR 컷이 PLATE bias 를 지배한다', credence=0.6)
BASE = [HC, BELT1, BELT2]


def test_expansion_adds_and_replaces():
    r = expansion(BASE, Belief('b3', 'new'))
    assert 'b3' in {b.belief_id for b in r.base}
    r2 = expansion(list(r.base), Belief('b3', 'updated', credence=0.9))
    assert sum(1 for b in r2.base if b.belief_id == 'b3') == 1   # 교체, 중복 없음


def test_contraction_success_and_inclusion():
    r = contraction(BASE, 'b2')
    ids = {b.belief_id for b in r.base}
    assert 'b2' not in ids                       # success
    assert ids <= {b.belief_id for b in BASE}    # inclusion


def test_contraction_vacuity():
    r = contraction(BASE, 'ghost')
    assert {b.belief_id for b in r.base} == {b.belief_id for b in BASE}
    assert r.removed == ()


def test_contraction_cascades_dependents():
    # b1 은 hc1 에 의존 — hc1 을 (동의 하에) 깎으면 b1 도 연쇄 철거
    r = contraction(BASE, 'hc1', allow_hard_core=True)
    assert set(r.removed) == {'hc1', 'b1'}
    assert r.programme_shift_candidate is True   # Kuhn 연동 신호


def test_hard_core_protected_by_default():
    with pytest.raises(HardCoreProtected):
        contraction(BASE, 'hc1')


def test_revision_levi_identity():
    new = Belief('b2v2', 'PLATE bias = floor + SNR컷 분해', credence=0.8)
    r = revision(BASE, new, contradicts=['b2'])
    ids = {b.belief_id for b in r.base}
    assert 'b2' not in ids and 'b2v2' in ids
    assert r.removed == ('b2',) and r.added == ('b2v2',)


def test_entrenchment_order_hard_core_top():
    assert entrenchment_key(HC) > entrenchment_key(BELT1) > entrenchment_key(BELT2)


def test_entrenchment_policy_disclosed():
    # gap5 정직: 모든 결과가 자기 entrenchment 정책을 들고 다닌다
    r = contraction(BASE, 'b2')
    assert '정책 선언' in r.entrenchment_policy


def test_demote_canonical_keeps_former():
    new = Belief('v22', 'hyb3 정본', credence=0.9)
    r = demote_canonical(BASE, 'b1', new)
    by_id = {b.belief_id: b for b in r.base}
    assert 'b1' in by_id                          # 제거 아니라 강등
    assert by_id['b1'].credence < by_id['v22'].credence
