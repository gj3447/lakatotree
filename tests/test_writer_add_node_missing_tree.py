"""writer.add_node 가 미존재 나무에 침묵 no-op 가 아니라 TreeNotFound 를 던짐을 잠금(defense-in-depth).

service.add_node 는 이미 load_tree_data 로 404 지만, writer 를 *직접* 호출(스크립트/우회)하면 raw MATCH 가
침묵 no-op 였다. 이 가드가 그 구멍을 writer 레벨에서 닫는다. dogfood writer_silent_match_hardening 의 guard.
# KG: span_lakatotree_add_node_missing_tree_404
"""
from __future__ import annotations

import pytest

from server.contexts.tree.schemas import NodeIn
from server.contexts.tree.writer import CycleClaimLost, TreeKgWriter, TreeNotFound
from server.ports import KgTxGuardFailed


def test_writer_add_node_missing_tree_raises():
    wrote: list = []

    def kg_tx(ops):
        wrote.append(ops)
        return [[] for _ in ops]   # MATCH 0행 = 미존재 나무 (MERGE 미실행 = 0 노드 write)

    w = TreeKgWriter(kg_tx)
    with pytest.raises(TreeNotFound):
        w.add_node("__missing_tree_zzz__", NodeIn(tag="x", algorithm="problem"), [])
    assert wrote, "kg_tx 는 호출되되 결과 0행으로 fail-loud (침묵 no-op 아님)"


def test_writer_add_node_existing_tree_returns_summary():
    def kg_tx(ops):
        return [[{"t": 1}] for _ in ops]   # MATCH 1행 = 존재

    s = TreeKgWriter(kg_tx).add_node("T", NodeIn(tag="x", algorithm="problem"), [])
    assert s.op_count == 1 and s.tx_count == 1


@pytest.mark.parametrize("cycle_claim", ["claim-b", None])
def test_active_same_tag_cycle_claim_rejects_cycle_and_generic_overwrite(cycle_claim):
    seen = []

    def kg_tx(ops):
        seen.append(ops)
        assert ops.guard_field == "guard_status"
        assert ops[0][1]["cycle_claim"] == cycle_claim
        raise KgTxGuardFailed(
            "guarded first statement rejected: 'claim_conflict'"
        )

    writer = TreeKgWriter(kg_tx)
    with pytest.raises(CycleClaimLost):
        if cycle_claim is None:
            writer.add_node("T", NodeIn(tag="x", algorithm="problem"), [])
        else:
            writer.add_cycle_node(
                "T", NodeIn(tag="x", algorithm="problem"), [], cycle_claim
            )
    assert len(seen) == 1


def test_existing_unclaimed_node_is_not_owned_by_cycle_compensation():
    def kg_tx(ops):
        return [[{
            "t": 1,
            "cycle_created": False,
            "guard_status": "ok",
        }] for _ in ops]

    _summary, created = TreeKgWriter(kg_tx).add_cycle_node(
        "T", NodeIn(tag="x", algorithm="problem"), [], "claim-a"
    )
    assert created is False
