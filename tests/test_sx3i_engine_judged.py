"""가드 — SX3i 가지가 *엔진 생성* verdict 인가(손입력 0). 자기채점 차단의 종착.

sx3i_engine_judged.run() 의 모든 측정노드 verdict 는 record_judge() 가 grounded record 에서
생성한 것과 *동일*해야 한다(손입력 리터럴이면 어긋남). 측정 record 없는 narrative 노드는
verdict 를 못 받는다(no_record) — 측정 뒷받침 없는 손입력 verdict 금지를 강제.
"""
from examples import record_judge as J
from examples.sx3i_engine_judged import NODES, judged_nodes


def test_measured_verdicts_come_from_engine_not_hand():
    """측정노드 verdict == record_judge(record). 손입력이면 안 맞음."""
    rows = {r["tag"]: r for r in judged_nodes()}
    for tag, parent, rec, role in NODES:
        if role != "measured":
            continue
        eng = J.judge_record(rec)
        assert eng["status"] == "judged", f"{tag}: record 가 엔진판결 불가({eng['status']})"
        assert rows[tag]["verdict"] == eng["verdict"], \
            f"{tag}: 트리 verdict {rows[tag]['verdict']} != 엔진 {eng['verdict']}(손입력 의심)"


def test_no_hand_input_verdict_literals_in_source():
    """소스에 verdict 리터럴이 없어야(canonical_stage 문제-root 와 'no_record' flag 제외)."""
    import pathlib
    src = pathlib.Path(__file__).resolve().parent.parent / "examples" / "sx3i_engine_judged.py"
    code = "".join(l for l in src.read_text(encoding="utf-8").splitlines()
                   if "verdict 리터럴" not in l)  # 문서 라인 제외
    for v in ("'progressive'", '"progressive"', "'degenerating'", "'rejected'", "'partial'"):
        assert v not in code, f"손입력 verdict 리터럴 발견: {v} (엔진 생성이어야)"


def test_narrative_nodes_get_no_verdict():
    """측정 record 없는 narrative 노드(reader_frame_provenance_fix·misdiag)는 verdict 못 받음(no_record)."""
    rows = {r["tag"]: r for r in judged_nodes()}
    for tag in ("reader_frame_provenance_fix", "misdiag_reader_frame"):
        assert rows[tag]["verdict"] is None and rows[tag].get("status") == "no_record", \
            f"{tag}: 측정 뒷받침 없는데 verdict 부여됨(자기채점)"


def test_c1_engine_judges_partial_not_progressive():
    """★핵심 divergence 문서화: c1 은 엔진 기준 partial(손입력 progressive 는 과대였음)."""
    rows = {r["tag"]: r for r in judged_nodes()}
    assert rows["c1_marker_detect"]["verdict"] == "partial"
