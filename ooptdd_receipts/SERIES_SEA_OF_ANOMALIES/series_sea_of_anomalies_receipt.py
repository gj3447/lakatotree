"""OOPTDD emit-adapter — LakatoTree 판정엔진 감사 finding(programme-classify: single-anomaly antipattern)을
*구조화 이벤트 trace*(R02)로 영수증화.

규율(ooptdd): 이벤트 리터럴은 엔진이 아니라 이 adapter 에만(엔진 series.py 는 불변).
verify 가 실제 lakatos.programme.series.programme_series_appraisal 을 *구동*해:
  ① sea-of-anomalies: dominant-progressive 시리즈(5중 1 rival-anomaly 오염)는 여전히 trend='progressive'
     — 이상 하나가 진보 프로그램을 강등하지 않는다(Lakatos MSRP)
  ② marginal 보수성: 2중 1 conceptual 오염(clean 과반 아님)은 'mixed' 유지 — 과잉완화 아님
  ③ degenerating 불변: nonprogressive 우세 + 이상 압력은 여전히 'degenerating'
을 구조화 이벤트로 ship.

음성 오라클(no-fake-green): 옛 결함(zero-tolerance — rival_anomaly==0 ∧ conceptual==0 이어야만
'progressive')이 살아있었다면 ①의 trend 가 'mixed' 라 첫 assert 가 깨진다. 과잉완화(이상 무시)면
②·③이 깨진다. 즉 어느 방향의 결함이든 살아있으면 *틀린다*.

참고 테스트: lakatotree/tests/test_series_sea_of_anomalies_20260713.py.
# KG: lakatotree-judge-engine-audit programme-classify / series-sea-of-anomalies-2026-07-13
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from lakatos.programme.series import ProgrammeSeriesRecord, programme_series_appraisal  # noqa: E402


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.programme.series.sea_of_anomalies", "event": name, **attrs}


def _prog(tag, **kw):
    return ProgrammeSeriesRecord(tag=tag, verdict="progressive", **kw)


def verify(backend, cid):
    """실제 programme_series_appraisal 구동 — sea-of-anomalies + 보수성 + degenerating 불변 증언."""
    # (1) 음성 오라클: 5중 1 rival-anomaly 오염 dominant 시리즈 → 여전히 progressive.
    #     옛 zero-tolerance 가 살아있었다면 trend='mixed' 라 여기서 깨진다.
    dom = programme_series_appraisal([
        _prog("n1"), _prog("n2"), _prog("n3"), _prog("n4"), _prog("n5", rival_anomaly=True)])
    assert dom.trend == "progressive", f"이상 하나가 dominant 를 강등(zero-tolerance 부활): {dom.trend}"
    assert dom.rival_anomaly_count == 1
    backend.ship([_ev(cid, "dominant_survives_lone_anomaly",
                      trend=dom.trend, progressive=dom.progressive_count,
                      anomalies=dom.rival_anomaly_count)])

    # (2) marginal 보수성(과잉완화 회귀가드): 2중 1 conceptual 오염 = clean 과반 아님 → mixed 유지.
    marginal = programme_series_appraisal([
        _prog("m1"), _prog("m2", conceptual_problem_score=2.0)])
    assert marginal.trend == "mixed", f"marginal(clean 과반 아님)인데 progressive(과잉완화): {marginal.trend}"
    backend.ship([_ev(cid, "marginal_stays_mixed", trend=marginal.trend,
                      conceptual=marginal.conceptual_problem_score)])

    # (3) degenerating 게이트 불변: nonprog 우세 + 이상 압력 → 여전히 degenerating.
    degen = programme_series_appraisal([
        ProgrammeSeriesRecord("r1", "rejected"),
        ProgrammeSeriesRecord("r2", "rejected", rival_anomaly=True),
        _prog("p1")])
    assert degen.trend == "degenerating", f"이상 누적·nonprog 우세인데 degenerating 아님: {degen.trend}"
    backend.ship([_ev(cid, "degenerating_gate_unchanged", trend=degen.trend,
                      nonprogressive=degen.nonprogressive_count)])
