"""series 'sea of anomalies' — 판정엔진 감사 finding(programme-classify: single-anomaly antipattern) 가드.

감사: programme_series_appraisal 의 'progressive' 분기가 rival_anomaly_count==0 ∧ conceptual_problem_score==0
을 요구 → *단 하나의* rival anomaly / conceptual problem 이 dominant-progressive 시리즈서도 'progressive' 를
박탈(→'mixed'). 이는 라카토스 MSRP 를 뒤집는다: 진보하는 연구프로그램은 *이상현상의 바다에서 헤엄치며*
전진한다(novel fact 예측). 이상 하나가 진보 프로그램을 강등하면 안 된다 — 강등은 이상이 *누적/우세*할 때만.

수정: 'progressive' 게이트를 zero-anomaly 에서 *clean-progressive strict 과반*(진보 verdict ∧ rival 이상 없음
∧ conceptual 문제 없음 레코드가 in-axis 의 strict 과반)으로 — 매직넘버 신규 도입 없이 과반 비교로
"진보가 troubles 를 능가하면 진보"(sea-of-anomalies)를 이행. degenerating 게이트는 불변(이상 누적·nonprogressive
우세 시). 이 관용 이전엔 anomaly>0 이 즉시 progressive 를 막았으므로, 게이트를 zero-anomaly 로 되돌리면 첫 가드 RED.

# ported from GIT/lakatotree_upstream_landing@6602295 (2026-07-14) — reconciled with progressive_unverified NEUTRAL_VERDICTS.
# KG: lakatotree-judge-engine-audit programme-classify / series-sea-of-anomalies-2026-07-13
"""
from lakatos.programme.series import ProgrammeSeriesRecord, programme_series_appraisal


def _prog(tag, **kw):
    return ProgrammeSeriesRecord(tag=tag, verdict='progressive', **kw)


# ── 핵심: dominant-progressive 시리즈 + 이상 하나 → 여전히 progressive (sea of anomalies) ────────
def test_lone_anomaly_does_not_demote_dominant_progressive_series():
    # 5 progressive, 그중 하나가 rival anomaly 를 마주함(그래도 진보 우세) → 'progressive' 유지.
    rows = [_prog('n1'), _prog('n2'), _prog('n3'), _prog('n4'),
            _prog('n5', rival_anomaly=True)]
    ap = programme_series_appraisal(rows)
    assert ap.progressive_count == 5 and ap.rival_anomaly_count == 1
    assert ap.trend == 'progressive', f"이상 하나가 dominant-progressive 를 강등(sea-of-anomalies 위반): {ap.trend}"


def test_lone_conceptual_problem_does_not_demote_dominant_progressive():
    rows = [_prog('n1'), _prog('n2'), _prog('n3'),
            _prog('n4', conceptual_problem_score=0.4)]
    ap = programme_series_appraisal(rows)
    assert ap.trend == 'progressive', f"conceptual problem 하나가 dominant-progressive 를 강등: {ap.trend}"


# ── 회귀가드(과잉완화 방지): 이상이 진보를 능가하면 여전히 progressive 아님 ───────────────────────
def test_accumulating_anomalies_that_outweigh_progress_are_not_progressive():
    # 2 progressive vs 3 anomaly-carrying → 진보가 이상을 못 능가 → 'progressive' 아님.
    rows = [_prog('n1'), _prog('n2'),
            _prog('a1', rival_anomaly=True), _prog('a2', rival_anomaly=True),
            _prog('a3', rival_anomaly=True)]
    ap = programme_series_appraisal(rows)
    assert ap.trend != 'progressive', f"이상 우세인데 progressive(과잉완화): {ap.trend}"


def test_zero_pressure_progressive_still_progressive():
    # 무압력 progressive 다수 = 명백히 progressive (기존 동작 불변).
    rows = [_prog('n1'), _prog('n2')]
    ap = programme_series_appraisal(rows)
    assert ap.trend == 'progressive'


def test_nonprogressive_dominant_with_pressure_still_degenerating():
    # nonprogressive 우세 + 압력 = 여전히 degenerating (degenerating 게이트 불변).
    rows = [ProgrammeSeriesRecord(tag='r1', verdict='rejected'),
            ProgrammeSeriesRecord(tag='r2', verdict='rejected', rival_anomaly=True),
            _prog('p1')]
    ap = programme_series_appraisal(rows)
    assert ap.trend == 'degenerating', f"이상 누적·nonprog 우세인데 degenerating 아님: {ap.trend}"
