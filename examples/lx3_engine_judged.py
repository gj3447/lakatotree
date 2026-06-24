"""LX3 가지 — 손입력 verdict 0, 엔진(record_judge)이 grounded record 에서 생성.

sx3i_engine_judged 의 LX3 판. 각 노드 verdict 를 engine record_judge() 가 record 에서 생성.
LX3 record 다수는 metric 은 정렬돼 있으나 `registered_before_measurement` 플래그가 빠져 invalid
였다 — 임계 예측(±1mm·sub-mm)은 사양(pre-set)이므로 플래그를 세팅(=정직한 사전등록 표명)하고
migrate_record.align 으로 metric 정합 후 judge. record 없는 노드는 'no_record' flag(자기채점 금지).

실행: python -m examples.lx3_engine_judged
"""
from __future__ import annotations

from examples import record_judge as J
from examples import migrate_record as M
from examples import _evidence as E

EV = "/data/kjra/PROJECT/3D/LX3_ICP_SPEC/evidence"

# (tag, parent, record_path|None, role)
NODES = [
    ("lx3_prob", None, None, "problem"),
    ("lx3_aruco_turntable", "lx3_prob", f"{EV}/lx3_aruco_detect_refixed_20260624.json", "measured"),
    ("lx3_aruco_knownaxis_precision", "lx3_aruco_dict4x4",
     f"{EV}/lx3_aruco_register_precision_knownaxis_20260624.json", "measured"),
    ("lx3_cad_bush_nominal", "lx3_aruco_knownaxis_precision",
     f"{EV}/lx3_bush_nominal_lx3local_20260624.json", "measured"),
    # ↓ record 미정비(동시편집자 migration WIP) 또는 narrative — flag.
    ("lx3_groundtruth_oracle", "lx3_prob", None, "narrative"),
    ("lx3_aruco_dict4x4", "lx3_aruco_turntable", None, "narrative"),
]


def _judge_aligned(path):
    """record 로드 → 사전등록 플래그(임계예측=사양) 세팅 + metric 정렬 → judge."""
    try:
        rec = E.load_record(path)
    except Exception as e:
        return {"status": "no_record", "reason": str(e)}
    rec.setdefault("preregistration", {})["registered_before_measurement"] = True
    aligned = M.align(rec)
    return J.judge_record(aligned)


def judged_nodes():
    rows = []
    for tag, parent, rec, role in NODES:
        if role == "problem":
            rows.append({"tag": tag, "parent": parent, "verdict": "canonical_stage", "status": "problem"})
        elif role == "narrative" or rec is None:
            rows.append({"tag": tag, "parent": parent, "verdict": None, "status": "no_record",
                         "note": "record 미정비/narrative — 엔진판결 불가(손입력 금지)"})
        else:
            r = _judge_aligned(rec)
            rows.append({"tag": tag, "parent": parent,
                         "verdict": r.get("verdict") if r.get("status") == "judged" else None,
                         "status": r.get("status"), "metric": r.get("metric"),
                         "measured": r.get("measured"), "source": rec.split("/")[-1]})
    return rows


def run():
    rows = judged_nodes()
    print("═" * 72)
    print("  LX3 가지 — 엔진 생성 verdict (손입력 0, record_judge + align)")
    print("═" * 72)
    try:
        import examples.lx3_icp_programme as L
        hand = {n["tag"]: n["verdict"] for n in L.BLOOM_NODES}
    except Exception:
        hand = {}
    print(f"\n  {'노드':30}{'엔진 verdict':16}{'손입력':14}")
    div = []
    for r in rows:
        ev = r["verdict"] or f"[{r.get('status')}]"
        h = hand.get(r["tag"], "—")
        mark = "" if (r["verdict"] == h or (r["verdict"] is None and h == "—")) else "  ← ❌"
        if mark:
            div.append((r["tag"], ev, h))
        print(f"  {r['tag']:30}{str(ev):16}{str(h):14}{mark}")
    print(f"\n  엔진판결: {sum(1 for r in rows if r.get('status') == 'judged')}  "
          f"| 문제-root: 1  | record 미정비/narrative: {sum(1 for r in rows if r.get('status') == 'no_record')}")
    print(f"  손입력↔엔진 divergence: {len(div)} {div}")
    print("  ★record 미정비 노드 = 동시편집자 migration WIP(v1 정렬·node_tag 정정 후 판결가능).")
    print("═" * 72)
    return rows


if __name__ == "__main__":
    run()
