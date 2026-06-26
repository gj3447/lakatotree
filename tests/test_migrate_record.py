"""migrate_record — ad-hoc/misaligned record → judge-able v1 (측정→판결 루프 1·2단계)."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "examples"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import migrate_record as M, record_judge as J, _evidence as E  # noqa: E402

_V1 = {"schema": E.RECORD_SCHEMA, "programme": "p", "conjecture": "c", "harness": {"script": "h"},
       "provenance": {"grounded": True, "inputs": [{"name": "x", "source": "y"}]}}


def test_align_makes_misaligned_record_judgeable():
    rec = {**_V1,
           "preregistration": {"registered_before_measurement": True, "direction": "higher",
                               "predicted": {"metric": "marker_side_px", "value_geq": 20}},
           "measurement": {"metric": "markers_per_view", "value": 7.0,
                           "derived": {"side_px_median": 89.6}}}
    assert J.judge_record(rec)["status"] == "abstain"            # 정합 전
    aligned = M.align(rec)                                        # marker_side_px → side_px_median (토큰공유)
    r = J.judge_record(aligned)
    assert r["status"] == "judged" and r["verdict"] == "partial", r
    assert aligned["preregistration"]["predicted"]["aligned_from"] == "marker_side_px"


def test_align_explicit_key():
    rec = {**_V1,
           "preregistration": {"registered_before_measurement": True, "direction": "higher",
                               "predicted": {"metric": "frac_ok", "value_geq": 1.0}},
           "measurement": {"metric": "n", "value": 5, "derived": {"frac_side_px_ge20": 1.0}}}
    r = J.judge_record(M.align(rec, measured_key="frac_side_px_ge20"))
    assert r["status"] == "judged" and r["verdict"] == "equivalent", r   # 1.0 vs 1.0


def test_wrap_adhoc_strips_verdict_and_judges():
    """ad-hoc(자기채점 verdict 포함) → wrap → verdict 제거·v1·엔진이 rejected 생성."""
    raw = {"stage": "measure", "n_registered": 1, "views": [1, 2, 3, 4, 5], "verdict": "BLOCKED"}
    v1 = M.wrap_adhoc(raw, programme="3d", conjecture="C3", node_tag="mc3",
                      predicted={"metric": "n_registered_views", "value_geq": 2}, direction="higher",
                      measurement={"metric": "n_registered_views", "value": raw["n_registered"]},
                      provenance={"inputs": [{"name": "v", "source": "s"}]},
                      harness={"script": "h"})
    assert "verdict" not in v1                                    # 자기채점 strip
    assert not E.validate_record(v1)                              # v1 통과
    r = J.judge_record(v1)
    assert r["status"] == "judged" and r["verdict"] == "rejected", r   # 1 < 2 → 엔진 rejected
