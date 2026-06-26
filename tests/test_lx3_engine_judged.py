"""가드 — LX3 가지 측정노드 verdict 가 *엔진 생성*(record_judge)인가(손입력 0).

LX3 record 다수는 metric 정렬됐으나 registered_before_measurement 플래그만 빠져 invalid 였다 —
lx3_engine_judged 가 임계예측(=사양)에 플래그 세팅 + align 후 judge. 측정노드 verdict 는
record_judge 와 동일해야 한다(손입력이면 어긋남). record 미정비 노드는 verdict 못 받음.
"""
from examples.lx3_engine_judged import NODES, judged_nodes, _judge_aligned


def test_measured_verdicts_come_from_engine():
    rows = {r["tag"]: r for r in judged_nodes()}
    for tag, parent, rec, role in NODES:
        if role != "measured":
            continue
        eng = _judge_aligned(rec)
        assert eng.get("status") == "judged", f"{tag}: 엔진판결 불가({eng.get('status')})"
        assert rows[tag]["verdict"] == eng["verdict"], \
            f"{tag}: 트리 {rows[tag]['verdict']} != 엔진 {eng['verdict']}(손입력 의심)"


def test_node_table_has_no_verdict_literal():
    for entry in NODES:
        assert len(entry) == 4
        tag, parent, rec, role = entry
        assert role in ("problem", "measured", "narrative")
        for v in ("progressive", "degenerating", "rejected", "partial"):
            assert v not in (str(parent or ""), str(rec or ""))


def test_aruco_nodes_engine_judge_partial_not_progressive():
    """★divergence 문서화: LX3 마커 노드들은 엔진 기준 partial(손입력 progressive 는 과대였음)."""
    rows = {r["tag"]: r for r in judged_nodes()}
    for tag in ("lx3_aruco_turntable", "lx3_aruco_knownaxis_precision", "lx3_cad_bush_nominal"):
        assert rows[tag]["verdict"] == "partial", f"{tag}: 엔진 partial 이어야"


def test_cmm_reference_available_is_engine_judged_equivalent():
    """CMM 기준값 확보는 scan-vs-CMM 정확도 성공이 아니라 외부 기준 준비 노드다."""
    rows = {r["tag"]: r for r in judged_nodes()}
    row = rows["lx3_cmm_reference_available"]
    assert row["verdict"] == "equivalent"
    assert row["metric"] == "cmm_specimen_count"
    assert row["measured"] == 5.0


def test_lx3_pair_only_cmm_sweep_is_engine_rejected():
    """ABCDE pair-only sweep은 LX3 폐기가 아니라 해당 estimator path의 엔진 rejected다."""
    rows = {r["tag"]: r for r in judged_nodes()}
    mapping = rows["lx3_lot_cmm_mapping"]
    assert mapping["status"] == "judged"
    assert mapping["metric"] == "sessions_matched_to_cmm_id"
    assert mapping["measured"] == 5.0

    sweep = rows["lx3_pair_only_cmm_sweep"]
    assert sweep["status"] == "judged"
    assert sweep["verdict"] == "rejected"
    assert sweep["metric"] == "max_abs_scan_minus_cmm_pair_distance_mm"
    assert sweep["measured"] == 2.687127
