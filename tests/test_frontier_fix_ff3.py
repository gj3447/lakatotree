"""FF3 guard (frontier-fix 2026-06-26): CANONICAL floor 의 human attestation 은 actor(by)≠노드 작성자(author)
일 때만 인정 — 작성자가 자기 노드에 자기 인장을 찍어 floor 를 여는 self-vouch 봉쇄. H2 가 남긴 'Sybil 한계:
노드 author 미식별' 의 후속(Foundation node_author_kg_identity = add_node 가 author 영속).

비파괴: author 미설정(legacy/익명) 노드는 by≠'' 로 기존 동작 보존(H2 테스트 무손상) — author 설정 시에만 강제.
★Sybil 천장: author/by 둘 다 client 선언이라 한 actor 가 두 정체성을 쓰면 우회 가능(실 auth 전 한계).

두 가드(defect/mechanism) green 착륙 시 examples/frontier_fix_20260626_programme.py 가 FF3 를 progressive
로 자동 채점. # KG: LakatosTree_FrontierFix_20260626 / FF3_h2_human_attestation_client_authored
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import NodeIn
from server.contexts.tree.schemas import VerdictIn as _VerdictIn   # noqa: N814 (pytest 수집 회피)
from server.contexts.tree.writer import TreeKgWriter


def _svc(*, args, author):
    """internal proof 노드 + author + 주어진 Argument 목록(args) — test_design_audit_h2 의 set_verdict 픽스처 차용."""
    def kg(q, **kw):
        if "HAS_RESEARCH_EVENT" in q:                      # 인터넷 관측 없음 → internal
            return []
        if "OPTIONAL MATCH (cur)-[:HAS_ARGUMENT]" in q:    # set_verdict pre-query
            return [dict(verdict="proof", verdict_source=None, source_trust=None,
                         novel_confirmed=False, author=author, args=args)]
        if "RETURN e.tag AS tag" in q:                     # promotion 후 최종 read
            return [dict(tag="n")]
        return []
    return JudgementService(kg=kg, kg_tx=lambda ops: None, hist=lambda *a, **k: None,
                            foundation=lambda n: None, reproducible_for_node=lambda n, t: None)


def _canon():
    return _VerdictIn(verdict="CANONICAL", human_verdict=True, valid_until_rebutted=True)


def _human(by: str):
    return [dict(id="T/eval1", attacks=None, by=by, kind="evaluation")]


def test_self_authored_human_attestation_does_not_open_floor():
    """음성 오라클: human attestation 의 by 가 노드 author 와 *같으면*(self-vouch) floor 안 열림(409).
    작성자가 자기 인장으로 CANONICAL 을 사는 경로 봉쇄."""
    with pytest.raises(HTTPException) as e:
        _svc(args=_human("agent:author"), author="agent:author").set_verdict("T", "n", _canon())
    assert e.value.status_code == 409
    assert "no_receipt_for_canonical" in str(e.value.detail)


def test_floor_requires_human_actor_distinct_from_node_author():
    """양성: by 가 author 와 *다르면*(독립 리뷰어) floor 통과 → CANONICAL 승격(과잉차단 아님)."""
    out = _svc(args=_human("human:reviewer"), author="agent:author").set_verdict("T", "n", _canon())
    assert out["ok"] is True


def test_add_node_persists_author_foundation():
    """Foundation node_author_kg_identity: add_node 가 e.author 를 KG 에 영속해야 floor 가 actor≠author 를
    판정할 수 있다(미영속이면 author 항상 '' → 보호 불가 = fake-green). 실 writer 가 e.author 를 SET 하는지 검증."""
    ops: list = []

    def kgtx(o):
        ops.extend(o)
        return [[{"t": "ok"}]] + [[] for _ in o[1:]]   # 첫 op(MATCH t RETURN t) 비어있지 않아야(TreeNotFound 가드)

    TreeKgWriter(kg_tx=kgtx, chunk_size=100).add_node("T", NodeIn(tag="n", author="agent:author"), [])
    cypher, params = ops[0]
    assert "e.author=$author" in cypher, cypher
    assert params.get("author") == "agent:author", params
