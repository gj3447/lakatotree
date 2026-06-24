"""sx3i_loop_demo — 측정→판결 루프의 *닫힌* 형태 (손입력 verdict 0).

sx3i_icp_programme.py 는 verdict 를 손입력한다(`_n('c1_marker_detect','progressive',...)`) = 자기채점.
이 데모는 그 대신 **grounded record → judge_record() → 엔진 생성 verdict** 로 잇는다.
record_judge + migrate_record 가 배선한 루프를 한 화면에 보인다. 핫한 sx3i_icp_programme 이
채택해야 할 패턴(손입력 verdict 행을 judge_record(load_record(...)) 로 교체)의 템플릿.

run() → 각 노드의 verdict 는 엔진이 record 에서 *생성*. 어디에도 verdict 리터럴 없음.
"""
from __future__ import annotations

import sys
import pathlib

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))
import record_judge as J  # noqa: E402

EV = "/data/kjra/PROJECT/3D/SX3i_ICP_SPEC/evidence"

# (node_tag, record_path) — verdict 는 여기 없다(엔진 생성). record 가 정합 v1 이어야 한다.
RECORDS = [
    ("c1_marker_detect", f"{EV}/c1_marker_detect_full211_20260624.aligned_v1.json"),
    ("markerless_c3", f"{EV}/markerless_c3_real_20260624.v1.json"),
]


def run() -> list[dict]:
    out = []
    for tag, path in RECORDS:
        if not pathlib.Path(path).exists():
            out.append({"node": tag, "status": "no_record", "path": path})
            continue
        r = J.judge_record(path)          # ★엔진 생성 verdict (손입력 0)
        out.append({"node": tag, "status": r["status"],
                    "verdict": r.get("verdict"), "metric": r.get("metric"),
                    "measured": r.get("measured"), "baseline": r.get("baseline"),
                    "source_record": r.get("source_record")})
    return out


if __name__ == "__main__":
    print("=== SX3i 측정→판결 루프 (엔진 생성 verdict, 손입력 0) ===")
    for r in run():
        if r["status"] == "judged":
            print(f"  {r['node']:18s} → {r['verdict']:11s} ({r['metric']} {r['measured']} vs {r['baseline']})  [{r['source_record']}]")
        else:
            print(f"  {r['node']:18s} → {r['status']} {r.get('verdict') or ''}")
