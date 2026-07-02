"""git-흡수 G1 landed guards — examples/git_absorption_20260702_programme.py 가 scan 하는 이중가드.

G1 = git 의 내용주소 불변 저장 + first-write-wins 발행(odb/source-loose.c:614-621, object-file.c:408-472)을
라카토트리 verdict 에 이식. 두 축:

  guard_defect(개선축)     : test_add_node_cannot_overwrite_scripted_verdict
        — scripted verdict 가 노드-쓰기로 덮이지 않는다(S3 봉합). ✅ 착륙(writer first-write-wins 가드).
  guard_mechanism(novel축) : test_current_verdict_is_fold_over_receipt_chain
        — 현재 verdict 가 불변 :VerdictReceipt 체인의 fold 로 재유도된다(내용주소 메커니즘). ⏳ 미착륙.

두 축이 *독립*이라 judge() 가 판별한다: defect닫힘 ∧ mechanism부재 → **partial**(우회만 막고 git-메커니즘 없음 =
ad-hoc 천장; 정직). mechanism 착륙 시 progressive. 현재 이 파일은 defect guard 만 green → 프로그램이 G1 을
partial 로 채점(가짜 progressive 아님 — 이중가드 판별력이 실제로 무는 증거).

# KG: LakatosTree_GitAbsorption_20260702 / G1_immutable_verdict_receipts
"""
from __future__ import annotations

import pytest

from server.contexts.tree.schemas import NodeIn
from server.contexts.tree.writer import TreeKgWriter


class _FakeKg:
    """writer op 를 받아 Neo4j MERGE...SET 의 verdict-preservation CASE 를 충실히 모델(revert 민감)."""

    def __init__(self, seed: dict[str, dict]):
        self.store = {k: dict(v) for k, v in seed.items()}
        self.last_ops: list = []

    def _guarded(self, query: str, params: dict) -> bool:
        return ("CASE WHEN coalesce(e.verdict_source" in query) and isinstance(params.get("forceful"), list)

    def __call__(self, ops):
        self.last_ops = ops
        out = []
        for query, params in ops:
            if "MERGE (e:LakatosNode" in query and "e.verdict" in query:
                rows = params.get("rows") or [params]
                guarded = self._guarded(query, params)
                forceful = params.get("forceful") or []
                for row in rows:
                    tag = row.get("tag", params.get("tag"))
                    node = self.store.setdefault(f"{params.get('tree')}/{tag}", {})
                    if not (guarded and node.get("verdict_source") in forceful):
                        node["verdict"] = row.get("verdict")
            out.append([{"t": params.get("tree")}])
        return out


# ── guard_defect (개선축, 음성 오라클) — 착륙 ──────────────────────────────────────────────
def test_add_node_cannot_overwrite_scripted_verdict():
    """scripted 'rejected' 노드를 같은 tag 로 add_node(기본 'proof')해도 verdict/verdict_source 보존(S3 봉합)."""
    kg = _FakeKg({"T/seam": {"verdict": "rejected", "verdict_source": "scripted", "node_state": "REFUTED"}})
    TreeKgWriter(kg_tx=kg).add_node("T", NodeIn(tag="seam"), [])
    stored = kg.store["T/seam"]
    assert stored["verdict"] == "rejected", f"scripted verdict 가 '{stored['verdict']}' 로 덮임 (S3)"
    assert stored.get("verdict_source") == "scripted", "verdict_source 오염 (S3)"


def test_upsert_nodes_also_preserves_scripted_verdict():
    """bulk 경로(upsert_nodes)도 동일 가드 — add_node 만 막고 bulk 로 새는 비대칭 방지."""
    kg = _FakeKg({"T/seam": {"verdict": "progressive", "verdict_source": "scripted", "node_state": "CANDIDATE"}})
    TreeKgWriter(kg_tx=kg).upsert_nodes("T", [NodeIn(tag="seam", verdict="proof")])
    assert kg.store["T/seam"]["verdict"] == "progressive", "bulk 경로가 scripted verdict 를 덮음 (S3 비대칭 누수)"


# ── guard_mechanism (novel축, 양성 오라클) — 미착륙: 내용주소 :VerdictReceipt 체인 ────────────
@pytest.mark.skip(reason="G1 메커니즘축 미착륙 — :VerdictReceipt(receipt_sha 내용주소) 체인 + rebuild_verify fold 다음 슬라이스")
def test_current_verdict_is_fold_over_receipt_chain():
    """G1 착륙 후: 노드의 현재 verdict 는 prev_receipt_sha 로 체인된 불변 :VerdictReceipt 들의 fold 로 재유도되고,
    노드-쓰기는 current_receipt_sha 포인터만 CAS 로 전진(verdict 필드 직접 SET 불가) — git first-write-wins 아날로그.

    미착륙이라 skip. defect 축만 green → judge() 가 G1 을 partial 로 채점(정직한 천장). 이 슬라이스가 착륙하면
    skip 을 풀고 rebuild_verify 로 체인 재유도를 검증한다."""
    raise AssertionError("G1 메커니즘축 미착륙")
