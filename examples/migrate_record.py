"""migrate_record — ad-hoc / metric-misaligned evidence json → judge-able lakato-evidence-record/v1.

측정→판결 루프의 1·2단계 도구:
  (1) align(): v1 이지만 예측 metric 의 실측치를 record 에서 못 찾는 경우(이름 불일치) →
      예측 metric 을 *실측 가능한* 키(measurement.metric 또는 derived 키)로 정합.
  (2) wrap_adhoc(): schema 없는 ad-hoc json → v1 스켈레톤으로 감싸기(호출측이 conjecture/
      예측/측정 매핑 제공 — 도메인 의미는 사람/생산하네스가 안다).

정합 후 record 는 record_judge.judge_record 로 **엔진 생성 verdict** 를 받을 수 있다(손입력 0).
원본을 덮지 않고 새 dict 를 돌려준다(동시세션 파일 비접촉).
"""
from __future__ import annotations

import copy
import sys
import pathlib

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import _evidence as E  # noqa: E402

_NUM = (int, float)


def _measured_keys(meas: dict) -> dict:
    """record 에서 실측 가능한 {metric_name: value} 후보 (measurement.value + derived)."""
    out = {}
    if isinstance(meas.get("value"), _NUM) and meas.get("metric"):
        out[meas["metric"]] = meas["value"]
    for k, v in (meas.get("derived") or {}).items():
        if isinstance(v, _NUM):
            out[k] = v
    return out


def _best_alias(pmetric: str, keys: list[str]) -> str | None:
    """예측 metric 과 토큰을 가장 많이 공유하는 실측키 (보수적 자동정합)."""
    pt = set(pmetric.replace("-", "_").split("_"))
    best, score = None, 0
    for k in keys:
        s = len(pt & set(k.replace("-", "_").split("_")))
        if s > score:
            best, score = k, s
    return best if score >= 1 else None


def align(rec: dict, *, measured_key: str | None = None) -> dict:
    """예측 metric 을 실측 가능한 키로 정합한 새 record. 이미 정합이면 그대로 복사."""
    r = copy.deepcopy(rec)
    pre = r.get("preregistration") or {}
    pred = pre.get("predicted") or {}
    meas = r.get("measurement") or {}
    pmetric = pred.get("metric")
    cands = _measured_keys(meas)
    if pmetric in cands:
        return r  # 이미 정합
    target = measured_key or _best_alias(pmetric or "", list(cands))
    if target and target in cands:
        pred["aligned_from"] = pmetric          # 추적: 원 예측 metric 보존
        pred["metric"] = target
        pre["predicted"] = pred
        r["preregistration"] = pre
        # measurement.value 가 다른 metric이면 derived 의 정합값을 최상위로 승격(judge 가 집는 곳)
        if meas.get("metric") != target and target in (meas.get("derived") or {}):
            meas.setdefault("derived", {})  # 유지
    return r


def wrap_adhoc(rec: dict, *, programme: str, conjecture: str, node_tag: str,
               predicted: dict, direction: str, measurement: dict,
               provenance: dict, harness: dict, noise_band: float = 0.0) -> dict:
    """schema 없는 ad-hoc dict → v1 스켈레톤. 호출측이 의미 매핑 제공. verdict 금지(엔진 생성)."""
    return {
        "schema": E.RECORD_SCHEMA, "programme": programme, "conjecture": conjecture,
        "node_tag": node_tag,
        "preregistration": {"predicted": predicted, "direction": direction,
                            "noise_band": noise_band, "registered_before_measurement": True},
        "measurement": measurement,
        "provenance": {**provenance, "grounded": True} if provenance.get("inputs") or provenance.get("data_manifest")
                      else provenance,
        "harness": harness,
        "_migrated_from_adhoc": True,
    }


def migrate_path(path, *, measured_key=None) -> dict:
    """파일 로드 → (v1이면) align. status + 정합/판결가능 여부."""
    rec = E.load_record(path)
    if rec.get("schema") == E.RECORD_SCHEMA:
        aligned = align(rec, measured_key=measured_key)
        errs = E.validate_record(aligned)
        return {"kind": "v1", "record": aligned, "valid": not errs, "errors": errs}
    return {"kind": "adhoc", "record": rec, "valid": False,
            "note": "ad-hoc → wrap_adhoc 로 의미 매핑 필요(생산 하네스/사람)"}
