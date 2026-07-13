"""record_judge — grounded record → 엔진 생성 verdict 브릿지 (측정→판결 루프).
손입력 verdict 0: judge()가 record 의 사전등록 vs 실측으로 verdict 를 *생성*."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "examples"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from record_judge import judge_record  # noqa: E402

_BASE = {
    "schema": "lakato-evidence-record/v1", "programme": "3d-shape-detection",
    "conjecture": "C1_demo", "harness": {"script": "h.py"},
    "preregistration": {"registered_before_measurement": True},
    "provenance": {"grounded": True, "inputs": [{"name": "x", "source": "y"}]},
}


def _rec(**over):
    import copy
    r = copy.deepcopy(_BASE); r.update(over); return r


def test_judged_partial_from_aligned_record():
    """정렬된 record → 엔진이 verdict 를 *생성*(개선·非novel=partial). 손입력 0."""
    rec = _rec(
        preregistration={"registered_before_measurement": True, "direction": "higher",
                         "predicted": {"metric": "side_px_median", "value_geq": 20, "unit": "px"}},
        measurement={"metric": "side_px_median", "value": 89.6, "unit": "px"})
    r = judge_record(rec)
    assert r["status"] == "judged", r
    assert r["verdict"] == "partial", r   # 개선(89.6>>20)이나 novel 아님 → 엔진이 partial 생성(progressive는 novelty 요구)
    assert r["measured"] == 89.6 and r["baseline"] == 20


def test_measured_pulled_from_derived_when_metric_matches():
    """measurement.metric 이 달라도 derived[예측metric] 에서 정합 실측치를 끌어온다."""
    rec = _rec(
        preregistration={"registered_before_measurement": True, "direction": "higher",
                         "predicted": {"metric": "side_px_median", "value_geq": 20}},
        measurement={"metric": "markers_per_view", "value": 7.82,
                     "derived": {"side_px_median": 89.6}})
    r = judge_record(rec)
    assert r["status"] == "judged" and r["verdict"] == "partial", r


def test_abstain_on_metric_name_misalignment():
    """예측 metric 의 실측치를 못 찾으면 ABSTAIN(손-verdict 로 덮지 않음 — 루프 갭 노출)."""
    rec = _rec(
        preregistration={"registered_before_measurement": True, "direction": "higher",
                         "predicted": {"metric": "marker_side_px", "value_geq": 20}},
        measurement={"metric": "markers_per_view_strict", "value": 7.82,
                     "derived": {"side_px_median": 89.6}})   # 'marker_side_px' 키 없음
    r = judge_record(rec)
    assert r["status"] == "abstain", r


def test_invalid_when_record_carries_verdict():
    """자기채점 차단: record 에 verdict 있으면 거부(엔진만 판결)."""
    rec = _rec(verdict="progressive",
               preregistration={"registered_before_measurement": True, "direction": "higher",
                                "predicted": {"metric": "m", "value": 1}},
               measurement={"metric": "m", "value": 2})
    r = judge_record(rec)
    assert r["status"] == "invalid" and any("verdict" in e for e in r["errors"]), r


