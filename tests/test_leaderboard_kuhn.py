"""P2 리더보드 + gap7 패러다임 전환 — Pareto/Borda 서열과 대체 판정 검증."""
from lakatos.kuhn import (
    CRISIS, NORMAL_SCIENCE, SHIFT_CANDIDATE,
    assess_paradigm, sustained_dominance,
)
from lakatos.leaderboard import Competitor, dominates, leaderboard, score_competitor
from lakatos.lifecycle import ACTIVE, DIVERGING

PROG = {'verdict': 'progressive', 'delta': -0.5, 'noise_band': 0.05}
REJ = {'verdict': 'rejected', 'delta': 0.5, 'noise_band': 0.05}
PART = {'verdict': 'partial', 'delta': -0.1, 'noise_band': 0.05}

HIT = {'novel_registered': True, 'novel_confirmed': True}
MISS = {'novel_registered': True, 'novel_confirmed': False}

STRONG = Competitor('strong', [PROG] * 9, [HIT] * 9,
                    metric_improvement_pct=27.0, closed=5, opened=1)
WEAK = Competitor('weak', [PART, REJ], [MISS, MISS],
                  metric_improvement_pct=2.0, closed=1, opened=3)
MID = Competitor('mid', [PROG, PART], [HIT, MISS],
                 metric_improvement_pct=30.0, closed=1, opened=2)


def test_pareto_dominance():
    s, w = score_competitor(STRONG), score_competitor(WEAK)
    assert dominates(s, w) and not dominates(w, s)


def test_leaderboard_exposes_criteria_not_single_score():
    lb = leaderboard([STRONG, WEAK, MID])
    assert lb['rows'][0]['name'] == 'strong'
    assert 'weak' not in lb['pareto_front'] and 'strong' in lb['pareto_front']
    # mid 는 laudan_score 에선 strong 에 안 밀릴 수 있음(metric 30>27 vs 문제수지) — 기준별 노출 확인
    for row in lb['rows']:
        assert all(k in row for k in ('laudan_score', 'credence', 'fertility_lb', 'borda'))
    assert '단일점수 환원 금지' in lb['note']


def test_borda_ties_share_points():
    lb = leaderboard([STRONG, STRONG.__class__('clone', [PROG] * 9, [HIT] * 9, 27.0, 5, 1)])
    assert lb['rows'][0]['borda'] == lb['rows'][1]['borda']


def _snap(rival_fert, inc_fert):
    rows = [
        {'name': 'rival', 'laudan_score': 10.0, 'credence': 0.9, 'fertility_lb': rival_fert},
        {'name': 'inc', 'laudan_score': 5.0, 'credence': 0.5, 'fertility_lb': inc_fert},
    ]
    return {'rows': rows}


def test_sustained_dominance_needs_full_window():
    snaps = [_snap(0.7, 0.3)] * 2          # 윈도우 3 미달
    assert not sustained_dominance(snaps, 'rival', 'inc')
    snaps = [_snap(0.7, 0.3)] * 3
    assert sustained_dominance(snaps, 'rival', 'inc')


def test_one_snapshot_luck_not_a_shift():
    snaps = [_snap(0.3, 0.7), _snap(0.3, 0.7), _snap(0.7, 0.3)]   # 마지막만 우세
    assert not sustained_dominance(snaps, 'rival', 'inc')


def test_shift_candidate_requires_human_oracle():
    snaps = [_snap(0.7, 0.3)] * 3
    a = assess_paradigm('inc', ['rival'], snaps,
                        incumbent_lifecycles=[DIVERGING],
                        incumbent_consecutive_nonprogressive=3)
    assert a.state == SHIFT_CANDIDATE and a.rival == 'rival'
    assert a.requires_human_oracle is True   # 자동 교체 금지


def test_crisis_when_degenerating_without_dominant_rival():
    snaps = [_snap(0.3, 0.2)] * 1            # 우세 지속 없음
    a = assess_paradigm('inc', ['rival'], snaps,
                        incumbent_lifecycles=[DIVERGING],
                        incumbent_consecutive_nonprogressive=4)
    assert a.state == CRISIS


def test_normal_science_when_incumbent_healthy():
    a = assess_paradigm('inc', ['rival'], [],
                        incumbent_lifecycles=[ACTIVE],
                        incumbent_consecutive_nonprogressive=0)
    assert a.state == NORMAL_SCIENCE
