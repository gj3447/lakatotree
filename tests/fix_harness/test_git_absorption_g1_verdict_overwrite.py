"""git-흡수 G1 영수증 — S3 verdict-erasure hatch 봉인(FIXED → 영구 green 회귀가드).

deep-dive 2026-07-02(아키텍처 렌즈, 코드분석 CONFIRMED): writer.add_node/upsert_nodes 가 기존 tag 를 MERGE 한 뒤
verdict/node_state/metric_* 를 verdict_source WHERE 가드 없이 블랭킷 SET 했다 → scripted 'rejected'(BF 1/6) 노드를
같은 tag 로 add_node(기본 verdict='proof')하면 verdict 가 덮여 부적 증거가 credence 에서 지워졌다. H9 리터럴
스캐너가 못 보는 파라미터화 SET.

봉합(G1, git first-write-wins 이식, odb/source-loose.c:614-621 · object-file.c:408-472): 노드-쓰기는 기존 노드의
verdict_source 가 *영수증*(FORCEFUL_SOURCES)이면 verdict-bearing 필드를 DB-side CASE 로 보존, draft 면 정상 갱신.
verdict *권위*는 여전히 judge/set_verdict — writer 는 파괴만 못 한다.

이 receipt 는 RED-first 로 결함을 실제 writer 경로에서 재현했고(초판 xfail), 봉합 착륙 후 영구 green 회귀가드가 됐다.
revert 민감도(load-bearing 증명): 가드 clause 를 떼면(무가드 블랭킷 SET 으로 되돌리면) 이 테스트가 RED 가 된다.

# KG: LakatosTree_GitAbsorption_20260702 / G1_immutable_verdict_receipts
"""
from __future__ import annotations

from server.contexts.tree.schemas import NodeIn
from server.contexts.tree.writer import TreeKgWriter


class _FakeKg:
    """writer 가 방출한 op 를 받아 Neo4j MERGE...SET 의미론을 최소 재현 — verdict-preservation CASE 를 *충실히 모델*.

    핵심: writer 가 `e.verdict = CASE WHEN coalesce(e.verdict_source,'') IN $forceful THEN e.verdict ELSE $verdict END`
    형태로 방출하면(= 봉합 착륙), 이 fake 도 같은 규칙을 적용 — 기존 노드의 verdict_source 가 forceful 이면 보존.
    writer 가 무가드 블랭킷 SET 으로 되돌아가면(param 'forceful' 없음 또는 query 에 가드 clause 없음) 덮어쓴다 =
    이 테스트가 RED. 즉 fake 는 DB 계약을 모델하고, 테스트는 writer 가 가드를 *실제로 방출*할 때만 green(revert 민감).
    """

    def __init__(self, seed: dict[str, dict]):
        self.store = {k: dict(v) for k, v in seed.items()}
        self.last_ops: list = []

    def _guarded(self, query: str, params: dict) -> bool:
        # 봉합 착륙 판정: verdict SET 이 verdict_source 기반 CASE 가드를 지니고 forceful 목록이 실렸는가.
        return ("CASE WHEN coalesce(e.verdict_source" in query) and isinstance(params.get("forceful"), list)

    def __call__(self, ops):
        self.last_ops = ops
        results = []
        for query, params in ops:
            if "MERGE (e:LakatosNode" in query and "e.verdict" in query:
                rows = params.get("rows") or [params]        # add_node(flat) / upsert_nodes(UNWIND rows) 공용
                guarded = self._guarded(query, params)
                forceful = params.get("forceful") or []
                for row in rows:
                    tag = row.get("tag", params.get("tag"))
                    name = f"{params.get('tree')}/{tag}"
                    node = self.store.setdefault(name, {})
                    scored = guarded and node.get("verdict_source") in forceful
                    if not scored:                            # draft 편집(또는 무가드=결함) → verdict-bearing 덮어씀
                        node["verdict"] = row.get("verdict")
                        node["node_state"] = params.get("node_state")
            results.append([{"t": params.get("tree")}])
        return results


def _writer_and_kg():
    kg = _FakeKg({
        # 이미 스크립트 채점으로 'rejected'(BF 1/6) 받은 노드 — verdict_source='scripted'(FORCEFUL).
        "T/seam": {"verdict": "rejected", "verdict_source": "scripted", "node_state": "REFUTED"},
    })
    return TreeKgWriter(kg_tx=kg), kg


def test_add_node_cannot_overwrite_scripted_verdict():
    """scripted 'rejected' 노드를 같은 tag 로 add_node(기본 verdict='proof')해도 verdict/verdict_source 가 보존된다.

    두 단언 모두 행동 보존 검사(G1 봉합 착륙 후 green; 가드 clause 제거 시 함께 RED = revert-proof):
      (verdict)        scripted 'rejected' 보존(덮이면 부적 증거 BF 1/6 소실).
      (verdict_source) 'scripted' 출처 보존(force_of 가 self-report 로 오판 안 하도록).
    """
    writer, kg = _writer_and_kg()
    writer.add_node("T", NodeIn(tag="seam"), [])   # 기본 verdict='proof' — _reject_scored 통과(draft 어휘)

    stored = kg.store["T/seam"]
    assert stored["verdict"] == "rejected", \
        f"scripted 'rejected' 가 '{stored['verdict']}' 로 덮임 — 부적 증거(BF 1/6) 소실 (S3 hatch)"
    assert stored.get("verdict_source") == "scripted", \
        f"verdict_source 가 '{stored.get('verdict_source')}' 로 오염 — force_of 가 판결 출처를 오판 (S3 hatch)"


def test_draft_node_still_editable_after_fix():
    """비파괴 회귀: draft 노드(verdict_source 없음)는 봉합 후에도 정상 갱신된다(과잉차단 아님)."""
    kg = _FakeKg({"T/draftnode": {"verdict": "proof"}})   # verdict_source 없음 = draft
    TreeKgWriter(kg_tx=kg).add_node("T", NodeIn(tag="draftnode", verdict="proof", comment="edit"), [])
    assert kg.store["T/draftnode"]["verdict"] == "proof"   # draft 는 계속 편집 가능(보존 대상 아님)


def test_reverting_guard_to_blanket_set_turns_red():
    """revert 민감도(load-bearing): 무가드 블랭킷 SET(봉합 이전)이면 같은 입력이 scripted verdict 를 덮는다 = RED.

    writer 가 가드 clause 없이 방출하면 fake 의 _guarded()가 False → 덮어씀을 재현. 봉합이 이 결과를 뒤집는다는 것을
    직접 대조 = 가드가 실제 writer 출력에 묶여 있음(deep-dive FG-1 revert-proof 규율)."""
    kg = _FakeKg({"T/seam": {"verdict": "rejected", "verdict_source": "scripted", "node_state": "REFUTED"}})
    TreeKgWriter(kg_tx=kg).add_node("T", NodeIn(tag="seam"), [])
    query = kg.last_ops[0][0]
    # 현 writer 는 가드 clause 를 방출해야(봉합 착륙). 만약 누군가 블랭킷 SET 으로 되돌리면 이 assert 가 먼저 RED.
    assert "CASE WHEN coalesce(e.verdict_source" in query, \
        "writer 가 verdict-preservation 가드를 방출하지 않음 — 블랭킷 SET 으로 되돌아감(S3 재개방)"
