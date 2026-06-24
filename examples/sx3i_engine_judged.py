"""SX3i 가지 — 손입력 verdict 0, 전부 엔진(record_judge)이 grounded record 에서 생성.

sx3i_icp_programme.py 는 `_n(tag, 'progressive', ...)` 로 verdict 를 **손입력**한다(자기채점 위험).
이 프로그램은 그걸 닫는다: 각 노드 verdict 를 **engine record_judge() 가 grounded record 에서 생성**.
sx3i_loop_demo(2노드 템플릿, 동시편집자)를 *가지 전체*로 확장.

★드러나는 진실(손입력과 엔진의 divergence) — 이게 이 변환의 가치:
  - c1_marker_detect: 손입력 progressive → 엔진 **partial**(임계초과지만 novel 초과내용 없음 = 과대였음).
  - c3_markerless_real: 손입력 degenerating → 엔진 **rejected**(예측 falsify).
  - sx3i_precision_floor_marker: 손입력 rejected = 엔진 rejected ✅.
  - reader_frame_provenance_fix: **grounded record 없음** → 엔진판결 불가. 측정 뒷받침 없는 손입력
    progressive 는 자기채점 — 엔진기반 트리에선 verdict 부여 불가(narrative/structural 로 분리).

run() 에 verdict 리터럴이 한 줄도 없다(canonical_stage 문제-root 와 'no_record' flag 제외).
실행: python -m examples.sx3i_engine_judged
"""
from __future__ import annotations

from examples import record_judge as J

EV = "/data/kjra/PROJECT/3D/SX3i_ICP_SPEC/evidence"

# (tag, parent, record_path|None, role)  — verdict 는 여기 없다. 엔진이 record 에서 생성.
#   role: 'problem'=canonical_stage(측정 아님), 'measured'=record_judge 판결, 'narrative'=측정 record 없음
NODES = [
    ("sx3i_prob", None, None, "problem"),
    ("c1_marker_detect", "sx3i_prob", f"{EV}/c1_marker_detect_refixed_20260624.aligned_v1.json", "measured"),
    ("c3_markerless_instrument", "sx3i_prob", f"{EV}/view_feature_extract_selftest_20260624.v1.json", "measured"),
    ("c3_markerless_real", "c3_markerless_instrument", f"{EV}/markerless_c3_real_20260624.v1.json", "measured"),
    ("sx3i_precision_floor_marker", "sx3i_prob", f"{EV}/c3pre_precision_floor_20260624.json", "measured"),
    # ↓ 2026-06-24: narrative 였던 2노드에 genuine grounded record 부여 → 엔진판결화(이제 measured).
    ("reader_frame_provenance_fix", "c1_marker_detect", f"{EV}/reader_frame_fix_20260624.json", "measured"),
    ("misdiag_reader_frame", "c1_marker_detect", f"{EV}/misdiag_reader_frame_20260624.json", "measured"),
]


def judged_nodes():
    """엔진 생성 verdict 노드 리스트 (손입력 0). 측정노드=record_judge, 문제-root=canonical_stage."""
    rows = []
    for tag, parent, rec, role in NODES:
        if role == "problem":
            rows.append({"tag": tag, "parent": parent, "verdict": "canonical_stage",
                         "source": "(problem root — 측정 아님)"})
        elif role == "narrative":
            rows.append({"tag": tag, "parent": parent, "verdict": None, "status": "no_record",
                         "source": "측정 record 없음 → 엔진판결 불가(손입력 금지)"})
        else:
            r = J.judge_record(rec)
            rows.append({"tag": tag, "parent": parent,
                         "verdict": r.get("verdict") if r["status"] == "judged" else None,
                         "status": r["status"], "metric": r.get("metric"),
                         "measured": r.get("measured"), "baseline": r.get("baseline"),
                         "source": rec.split("/")[-1]})
    return rows


def run():
    rows = judged_nodes()
    print("═" * 72)
    print("  SX3i 가지 — 엔진 생성 verdict (손입력 0, record_judge)")
    print("═" * 72)
    # 손입력 대조
    try:
        import examples.sx3i_icp_programme as S
        hand = {n["tag"]: n["verdict"] for n in S.BLOOM_NODES}
    except Exception:
        hand = {}
    print(f"\n  {'노드':28}{'엔진 verdict':16}{'손입력':14}{'divergence'}")
    diverge = []
    for r in rows:
        ev = r["verdict"] or f"[{r.get('status','')}]"
        h = hand.get(r["tag"], "—")
        d = "" if (r["verdict"] == h or r["verdict"] is None and h == "—") else "  ← ❌ 불일치"
        if d:
            diverge.append((r["tag"], ev, h))
        print(f"  {r['tag']:28}{str(ev):16}{str(h):14}{d}")
    print(f"\n  엔진판결 노드: {sum(1 for r in rows if r.get('status') == 'judged')}  "
          f"| 문제-root: {sum(1 for r in rows if r['verdict'] == 'canonical_stage')}  "
          f"| 측정-record 없음(narrative): {sum(1 for r in rows if r.get('status') == 'no_record')}")
    print(f"  손입력↔엔진 divergence: {len(diverge)} {[(t, e, h) for t, e, h in diverge]}")
    print("\n  ★narrative(record 없음) 노드 = 측정 뒷받침 없는 손입력 verdict. 엔진기반 트리에선 verdict 부여 불가.")
    print("═" * 72)
    return rows


if __name__ == "__main__":
    run()
