"""record_judge — grounded evidence-record(lakato-evidence-record/v1)를 **엔진 판결**로 변환.

측정→판결 루프의 빠진 재사용 조각: 지금까지 어느 programme도 record를 *동적으로* judge()에
먹이지 않고 verdict 를 손입력(consumer_d_icp_programme)하거나 Prediction 을 .py 에 하드코딩(consumer3d)했다.
이 모듈은 record 한 장 → `judge()`(+pnr/dialectical) → **엔진 생성 verdict** 로 잇는다. 손입력 0.

자기채점 차단(_evidence.validate_record 위임): record 에 verdict 있으면/grounded 아니면/사전등록
없으면 판결 거부. 그리고 **사전등록 metric 의 실측치를 record 에서 정합으로 못 찾으면 ABSTAIN**
(metric 이름 불일치를 손-verdict 로 덮지 않는다 — 루프의 진짜 갭을 드러낸다).

쓰임:
    from examples.record_judge import judge_record
    r = judge_record("SX3i_ICP_SPEC/evidence/c1_marker_detect_full211_20260624.json")
    # r['status'] in {'judged','abstain','invalid'};  r['verdict'] (judged 일 때, 엔진 생성)
"""
from __future__ import annotations

import sys
import pathlib

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))            # examples/ (for _evidence)
sys.path.insert(0, str(_HERE.parent))     # repo root (for lakatos.*)
import _evidence as E  # noqa: E402

# 엔진 판결 커널 (in-process)
from lakatos.verdict.judge import Prediction, judge  # noqa: E402

_NUM = (int, float)


def _baseline(pred: dict):
    """사전등록 baseline/threshold: value(개선기준) | value_geq | value_leq."""
    for k in ("value", "value_geq", "value_leq"):
        v = pred.get(k)
        if isinstance(v, _NUM):
            return float(v), k
    return None, None


def _measured_for(pmetric: str, meas: dict):
    """예측 metric 에 *정합하는* 실측치를 record 에서 찾는다 (measurement.value 또는 derived[pmetric]).
    못 찾으면 None → 호출측 ABSTAIN. metric 이름이 안 맞으면 사과/오렌지 비교를 하지 않는다."""
    if meas.get("metric") == pmetric and isinstance(meas.get("value"), _NUM):
        return float(meas["value"])
    derived = meas.get("derived") or {}
    if isinstance(derived.get(pmetric), _NUM):
        return float(derived[pmetric])
    return None


def judge_record(rec_or_path) -> dict:
    """record → 엔진 생성 verdict. status: 'invalid'|'abstain'|'judged'."""
    rec = E.load_record(rec_or_path) if isinstance(rec_or_path, (str, pathlib.Path)) else rec_or_path
    errs = E.validate_record(rec)
    if errs:
        return {"status": "invalid", "errors": errs, "source_record": E.source_id(rec)}

    pre = rec.get("preregistration") or {}
    pred = pre.get("predicted") or {}
    meas = rec.get("measurement") or {}
    pmetric = pred.get("metric") or meas.get("metric")
    baseline, baseline_key = _baseline(pred)
    measured = _measured_for(pmetric, meas) if pmetric else None
    direction = pre.get("direction")

    if baseline is None or measured is None or direction not in ("lower", "higher"):
        return {
            "status": "abstain",
            "reason": "record 를 기계판결 불가 — "
                      + ("baseline(value/value_geq/value_leq) 부재; " if baseline is None else "")
                      + (f"예측 metric '{pmetric}' 의 실측치를 measurement.value/derived 에서 못 찾음; "
                         if measured is None else "")
                      + ("direction(lower|higher) 부재; " if direction not in ("lower", "higher") else ""),
            "predicted_metric": pmetric, "measurement_metric": meas.get("metric"),
            "source_record": E.source_id(rec),
        }

    pred_obj = Prediction(metric_name=pmetric, direction=direction,
                          baseline_value=baseline, noise_band=float(pre.get("noise_band") or 0.0))
    v = judge(pred_obj, measured)
    return {
        "status": "judged", "verdict": v.verdict,      # ★엔진 생성 (손입력 아님)
        "metric": pmetric, "baseline": baseline, "baseline_key": baseline_key,
        "measured": measured, "direction": direction, "delta": v.delta, "improved": v.improved,
        "node_tag": rec.get("node_tag"), "source_record": E.source_id(rec),
    }


def audit_dir(evidence_dir) -> list[dict]:
    """디렉토리의 모든 *.json 을 judge_record 로 감사 → 자동판결 가능/abstain/invalid 분류."""
    out = []
    for p in sorted(pathlib.Path(evidence_dir).glob("*.json")):
        try:
            rec = E.load_record(p)
        except Exception as e:  # noqa: BLE001
            out.append({"file": p.name, "status": "unreadable", "error": str(e)[:80]})
            continue
        if not isinstance(rec, dict):
            out.append({"file": p.name, "status": "not_object"})
            continue
        r = judge_record(rec)
        r["file"] = p.name
        out.append(r)
    return out


if __name__ == "__main__":
    import json
    d = sys.argv[1] if len(sys.argv) > 1 else "<WORKSPACE>/PROJECT/3D/SX3i_ICP_SPEC/evidence"
    rows = audit_dir(d)
    by = {}
    for r in rows:
        by[r["status"]] = by.get(r["status"], 0) + 1
    print(f"=== record→judge 감사: {d} ===")
    for r in rows:
        s = r["status"]
        extra = (f"verdict={r['verdict']} ({r['metric']} {r['measured']} vs {r['baseline']})" if s == "judged"
                 else r.get("reason", r.get("errors", [""])[0] if r.get("errors") else "")[:90])
        print(f"  [{s:8s}] {r['file'][:46]:46s} {extra}")
    print(f"\n분류: {by}")
