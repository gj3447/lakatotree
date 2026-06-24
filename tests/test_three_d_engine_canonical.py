"""정본 enforcement — 통합 트리(three_d_detection)의 ACTIVE 가지(SX3i/LX3) verdict 가 *엔진 생성*인가.

설계: BPC 줄기 = **정착된 연구사 핀**(euler/halcon3d 류). v8_pipeline·aruco_metric 등은 완료된
연구로, 그 사후 verdict 손입력은 자기채점이 아니라 *역사 기록*이다(BPC evidence 72개 중 v1 정렬
record 0 = 라이브 판결 대상 아님). 반면 SX3i/LX3 = **진행중 연구** → 손입력 verdict = 자기채점 위험
→ 엔진(record_judge)이 정본. 이 테스트가 통합 트리의 SX3i/LX3 측정노드 verdict == record_judge 를
강제한다(= judged 정본 스왑의 enforcement; 손입력 드리프트가 들어오면 깨진다).
"""
from examples.three_d_detection import UNIFIED_NODES
from examples import sx3i_engine_judged as SE
from examples import lx3_engine_judged as LE


def _unified():
    return {n["tag"]: n["verdict"] for n in UNIFIED_NODES}


def test_sx3i_active_branch_matches_engine():
    u = _unified()
    for r in SE.judged_nodes():
        if r.get("status") == "judged":
            assert u.get(r["tag"]) == r["verdict"], \
                f"{r['tag']}: 통합트리 {u.get(r['tag'])} != 엔진 record_judge {r['verdict']}(정본 미스왑)"


def test_lx3_active_branch_matches_engine():
    u = _unified()
    for r in LE.judged_nodes():
        if r.get("status") == "judged":
            assert u.get(r["tag"]) == r["verdict"], \
                f"{r['tag']}: 통합트리 {u.get(r['tag'])} != 엔진 record_judge {r['verdict']}(정본 미스왑)"


def test_active_branches_have_no_engine_validated_progressive():
    """엔진 정본 결과: SX3i/LX3 의 *엔진판결* 노드 중 progressive 0(전부 partial/rejected).
    손입력이면 progress 처럼 보였을 것을 엔진이 정직하게 partial 로 못박음."""
    eng = [r["verdict"] for r in (SE.judged_nodes() + LE.judged_nodes()) if r.get("status") == "judged"]
    assert "progressive" not in eng, f"엔진판결에 progressive 존재(예상 외): {eng}"


def test_bpc_trunk_remains_pinned_history_canonical():
    """BPC = 정착 연구사 핀(정당). v8_pipeline 단독 CANONICAL = 통합 정본."""
    u = _unified()
    assert u["v8_pipeline"] == "CANONICAL"
    canon = [n["tag"] for n in UNIFIED_NODES if n["verdict"] == "CANONICAL"]
    assert canon == ["v8_pipeline"], f"CANONICAL 은 BPC v8 단독이어야: {canon}"
