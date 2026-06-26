"""add_node 가 존재하지 않는 트리에 대해 침묵-성공이 아니라 fail-loud 404 임을 *잠그는* 회귀 테스트.

service.add_node → tree_data(name) → repository.load_tree_data → HTTPException(404, "나무 없음").
(writer.add_node 의 raw MATCH 는 직접 호출 시 침묵 no-op 가능 = defense-in-depth 후속; 사용자 표면은 여기서 404.)
이 테스트는 그 정직한 실패가 미래에 silent 로 퇴행하지 않도록 못 박는다(create_tree dogfood 의 novel 축).
# KG: span_lakatotree_add_node_missing_tree_404
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from server.contexts.tree.schemas import NodeIn
from server.contexts.tree.service import TreeService


def test_add_node_to_missing_tree_is_404_not_silent():
    wrote: list = []

    def kg(query, **params):
        # load_tree_data 의 메타 조회가 0행 → 미존재 트리
        return []

    svc = TreeService(kg=kg, kg_tx=lambda ops: wrote.append(ops), hist=lambda *a: None, pg=lambda: None)

    with pytest.raises(HTTPException) as exc:
        svc.add_node("__missing_tree_zzz__", NodeIn(tag="x", algorithm="problem"))

    assert exc.value.status_code == 404
    assert "나무 없음" in str(exc.value.detail)
    assert wrote == []   # 쓰기 시도 전에 차단 — 침묵 no-op 아님
