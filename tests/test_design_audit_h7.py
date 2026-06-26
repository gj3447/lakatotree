"""설계감사 H7(완성-후 로드맵 2026-06-26) — add_critique 자동강등이 비원자 TOCTOU (H5 의 거울쌍).

결함: add_critique 가 비판 등재 후 노드 스냅샷(verdict, 논증집합)을 읽어(evidence_claim_service.py:127)
reconcile_standing 으로 CANONICAL→former_canonical 강등을 *결정* 한 뒤, 별개 self.kg 세션의 강등 write(:142)
가 스냅샷 재검증 없이 무조건 SET 한다. H5 는 set_verdict 의 *승격* 방향만 원자 CAS 로 잠갔고 이 *강등* 방향은
미러 안 됐다. read→write 사이 동시 재승격(set_verdict)·새 critique(논증집합 변경)가 끼면 이미 무효가 된
판정으로 stale 강등(현재최선 포인터 오염, standing_retracted_at 거짓 기록)이 일어난다.

수정: 강등 write 에 H5 와 동형의 낙관적 CAS — 스냅샷(verdict + 논증집합 지문)이 write 시점에도 동일할 때만
former_canonical SET. 변했으면 0행 → 강등 *미적용*(critique 자체는 등재됨, demote_skipped 표식; 다음
standing read 가 최신상태로 재평가). 강등은 사용자 요청이 아니라 side-effect 라 409 가 아니라 skip.
# KG: span_lakatotree_design_audit_20260625
"""
from __future__ import annotations

from datetime import datetime, timezone

from server.contexts.tree.evidence_claim_service import EvidenceClaimService
from server.contexts.tree.schemas import CritiqueIn

_READ = "RETURN e.verdict AS verdict"
_DEMOTE = "SET e.verdict='former_canonical'"


class _StatefulKg:
    """add_critique 강등 경로의 read→write 사이 *동시변경* 시뮬. race=True 면 demote 시점에 노드가 이미
    재승격/강등돼 verdict 가 바뀐 상태 → 원자 CAS 가 0행을 내야 한다(가드 없으면 무조건 강등)."""

    def __init__(self, *, race: bool) -> None:
        self.race = race
        self.demote_queries: list[str] = []

    def __call__(self, query, **p):
        if "MERGE (a:Argument" in query:            # critique 등재
            return []
        if _READ in query and "collect({id:a.id" in query:   # :127 스냅샷 read — CANONICAL + 미방어 doubt
            return [{"verdict": "CANONICAL", "vur": True,
                     "args": [{"id": "T/d1", "attacks": "n"}]}]   # d1 이 verdict 직접공격 → stands=False
        if _DEMOTE in query:                        # :142 강등 CAS write
            self.demote_queries.append(query)
            if self.race and (p.get("exp_verdict") or "") != "CANONICAL":
                return []   # CAS param 이 현 state 와 불일치(이 모킹에선 race 시 exp 불일치 가정)
            # race 시 현 verdict 는 더 이상 CANONICAL 아님 → exp_verdict=CANONICAL 과 불일치 → 0행
            return [] if self.race else [{"tag": p.get("tag")}]
        return [{"tag": p.get("tag")}]


def _svc(kg):
    return EvidenceClaimService(
        kg=kg, kg_tx=lambda ops: [[{"ok": 1}] for _ in ops], hist=lambda *a, **k: None,
        foundation=lambda *a, **k: None, load_lineage=lambda *a, **k: None,
        reproducible_for_node=lambda *a, **k: None)


def test_add_critique_demote_is_atomic_cas():
    """동시변경 없으면 정상 강등 + 강등 write 가 스냅샷 CAS(verdict+논증지문)를 구조적으로 포함."""
    kg = _StatefulKg(race=False)
    out = _svc(kg).add_critique("T", "n", CritiqueIn(arg_id="d1", attacks="n", by="critic", kind="doubt"))
    assert out["standing"]["demoted"] is True, "미방어 doubt 인데 강등 결정이 안 남"
    assert kg.demote_queries, "강등 write 미실행"
    dq = kg.demote_queries[0]
    # ★구조적(non-vacuous): 강등 write 가 스냅샷 재검증 CAS 를 실제로 포함 (수정 없으면 RED)
    assert "$exp_verdict" in dq, "강등 write 에 verdict 스냅샷 CAS 누락 → TOCTOU 미봉쇄"
    assert "arg_fp" in dq, "강등 write 에 논증집합 지문 재검증 누락"
    assert "RETURN e.tag" in dq, "0행(동시변경) 탐지용 RETURN 누락"


def test_add_critique_demote_skipped_on_concurrent_change():
    """read→write 사이 동시 재승격으로 스냅샷이 변하면 원자 CAS 0행 → stale 강등 미적용(skip, critique 는 등재)."""
    kg = _StatefulKg(race=True)
    out = _svc(kg).add_critique("T", "n", CritiqueIn(arg_id="d1", attacks="n", by="critic", kind="doubt"))
    assert out["ok"] is True, "critique 자체는 등재돼야(강등 skip 이 add_critique 를 실패시키지 않음)"
    assert out["standing"].get("demote_skipped"), "동시변경인데 stale 강등이 그대로 적용됨(skip 표식 없음)"
