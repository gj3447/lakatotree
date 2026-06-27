"""audit-fix dogfood 하네스 가드 — 엔진이 *자기 2026-06-27 감사 수정*을 채점하는 루프가 판별력을 갖는지.

frontier_fix_ff6 와 동일 척추: 발견당 독립 이중가드(guard_defect=개선축, guard_mechanism=novel축)로
judge() 가 progressive/partial/equivalent 를 *판별*한다(단일비트면 progressive/pending 만 = 채점 연극).
또 eureka 가 '완료 주장(felt)했으나 엔진 미확증(¬true)' 을 환각으로 *분리*하는지(anti-confabulation) 가드.

hermetic: 실제 pytest 영수증을 돌리지 않고 합성 receipt(rc)로 채점/판별/eureka 만 검증(재귀·느림 회피).
# KG: span_lakatotree_audit_fix_20260627 / LakatosTree_AuditFix_20260627
"""
from __future__ import annotations

from examples.audit_20260627_programme import (
    AUDIT_NODES,
    _score,
    eureka_board,
    run,
)


def _scoring_nodes():
    return [n for n in AUDIT_NODES if n.prediction is not None]


def _dual_guard_node():
    """이중가드(defect+mechanism 둘 다)를 가진 대표 노드."""
    return next(n for n in AUDIT_NODES if n.prediction is not None and n.guard_defect and n.guard_mechanism)


def test_dual_guard_judge_discriminates_four_cells():
    """이중가드 노드는 judge() 가 4-칸을 판별 — progressive/partial/equivalent 모두 도달(단일비트면 불가)."""
    n = _dual_guard_node()
    cell = {(dc, mp): _score(n, dc, mp)["verdict"] for dc in (True, False) for mp in (True, False)}
    assert cell[(True, True)] == "progressive", cell      # 결함닫힘 + 메커니즘 = 진짜 fix
    assert cell[(True, False)] == "partial", cell         # 우회만 막음 = ad-hoc 천장
    assert cell[(False, True)] == "equivalent", cell      # 메커니즘만, 구멍 여전
    assert {"progressive", "partial", "equivalent"} <= set(cell.values()), cell


def test_every_scoring_node_has_independent_improve_and_novel_axes():
    """FG-2 재발 방지 by-construction: improve metric != novel metric (같은 비트 재사용 금지)."""
    for n in _scoring_nodes():
        assert n.prediction.metric_name != n.novel_target.metric_name, n.tag
        # 이중가드를 선언한 노드는 두 가드 이름이 서로 달라야(같은 테스트 재사용 아님)
        if n.guard_defect and n.guard_mechanism:
            assert n.guard_defect != n.guard_mechanism, n.tag


def test_landed_dual_guard_fixes_score_progressive():
    """양 가드가 착륙(green)한 claimed 수정은 엔진이 progressive 로 채점(손입력 0)."""
    # 합성 receipt: 모든 dual-guard claimed 노드의 양 가드 green, 단일가드는 defect 만 green.
    rc: dict[str, bool] = {}
    for n in _scoring_nodes():
        if not n.claimed:
            continue
        if n.guard_defect:
            rc[n.guard_defect] = True
        if n.guard_mechanism:
            rc[n.guard_mechanism] = True
    rows = {r["tag"]: r for r in run(rc)}
    dual = [n for n in _scoring_nodes() if n.claimed and n.guard_defect and n.guard_mechanism]
    assert dual, "이중가드 claimed 노드가 있어야(비-vacuity)"
    for n in dual:
        # gated(실-Neo4j) 노드는 defect 가드가 합성 rc 에선 green 이라 progressive — 정상.
        assert rows[n.tag]["verdict"] == "progressive", (n.tag, rows[n.tag])
    # 단일가드(mechanism 없음) claimed 노드는 progressive 가 *아니라* partial (천장)
    single = [n for n in _scoring_nodes() if n.claimed and n.guard_defect and not n.guard_mechanism]
    for n in single:
        assert rows[n.tag]["verdict"] == "partial", (n.tag, rows[n.tag])


def test_eureka_separates_true_from_hallucinated():
    """anti-confabulation: progressive=완료주장 → true; partial=완료주장 → hallucinated(felt-but-not-true)."""
    # progressive 케이스(이중가드 green) — true.
    n_prog = _dual_guard_node()
    prog_row = _score(n_prog, defect_closed=True, mech_present=True)
    prog_row["status"] = "CLOSED"
    eb_true = eureka_board([prog_row])
    assert eb_true["felt"] == 1 and eb_true["true"] == 1 and eb_true["hallucinated"] == 0, eb_true

    # partial 케이스(증상만) — felt 이나 not true = hallucinated.
    part_row = _score(n_prog, defect_closed=True, mech_present=False)
    part_row["status"] = "CLOSED(partial)"
    eb_h = eureka_board([part_row])
    assert eb_h["felt"] == 1 and eb_h["true"] == 0 and eb_h["hallucinated"] == 1, eb_h


def test_open_findings_are_not_felt_so_not_hallucinated():
    """미수정(claimed=False) OPEN 발견은 '완료 주장' 이 아니므로 felt 아님 → 환각으로 오집계되지 않는다."""
    open_nodes = [n for n in _scoring_nodes() if not n.claimed]
    assert open_nodes, "OPEN 노드가 있어야(비-vacuity)"
    rows = [dict(_score(n, defect_closed=False, mech_present=True), status="OPEN") for n in open_nodes]
    eb = eureka_board(rows)
    assert eb["felt"] == 0 and eb["hallucinated"] == 0, eb
