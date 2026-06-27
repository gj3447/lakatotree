"""FIX-HARNESS #13 (P3 정직성/fail-loud): add_critique 가 없는 노드에도 조용히 no-op 하면서
200 ok 를 돌려주고 history 행까지 쓴다 (provenance/audit 부정직).

finding id: #13
locations:
  - server/contexts/tree/evidence_claim_service.py:99-148 (add_critique)
the bug:
  add_critique 의 첫 MERGE 쿼리에는 RETURN/가드가 없다. MATCH 가 0행이면 MERGE 는 no-op 이
  되지만, self.hist(name, 'critique', tag, ...) 는 무조건 append 되고 메서드는 {'ok': True}
  를 반환한다. 형제 mutation 들(add_research_event:169-170, store_research_event:197-198,
  standing:417-418 등)은 모두 "if not rows: raise HTTPException(404)" 를 한다. 결과:
  존재하지 않는 노드의 critique 에 대해 append-only history 행이 남는다 → 감사/계보 부정직.
the fix:
  evidence_claim_service.py:99-105 의 MERGE/MATCH 쿼리에 `RETURN e.tag` 를 추가하고,
  rows 가 0행이면 self.hist 호출 *전에* raise HTTPException(404, f'노드 없음: {tag}').
xfail(strict) until fixed: 픽스가 들어오면 strict xfail 이 trip → 본 스위트는 green 유지.

서비스 구성은 tests/test_standing_retraction.py 의 query-dispatch fake_kg + 최소 서비스
패턴을 따른다. 실제 EvidenceClaimService.add_critique 코드경로를 그대로 태운다(목 단언 아님).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from server.contexts.tree.evidence_claim_service import EvidenceClaimService
from server.contexts.tree.schemas import CritiqueIn


def _service_node_absent():
    """없는 노드 시나리오: 모든 kg 쿼리가 0행을 돌려준다(노드 부재). hist 스파이로 orphan 기록 감시."""
    hist_calls: list = []

    def fake_kg(query: str, **params):
        # 노드가 존재하지 않으므로 어떤 MATCH 도 0행. (픽스 후 첫 쿼리의 RETURN e.tag 도 0행.)
        return []

    def hist_spy(*a, **k):
        hist_calls.append((a, k))

    svc = EvidenceClaimService(
        kg=fake_kg, hist=hist_spy,
        foundation=lambda _n: None, load_lineage=lambda: [],
        reproducible_for_node=lambda _n, _t: None)
    return svc, hist_calls


# [FIXED 2026-06-27] #13 — green regression (evidence_claim_service.add_critique: RETURN e.tag + 404 guard before hist)
def test_critique_on_missing_node_raises_404_and_writes_no_history():
    """없는 노드 critique → 형제 mutation 들처럼 HTTPException(404) 여야 하고,
    그 전에 self.hist 가 호출되면 안 된다(orphan history 행 금지)."""
    svc, hist_calls = _service_node_absent()

    with pytest.raises(HTTPException) as exc:
        svc.add_critique('prog', 'nonexistent-tag',
                         CritiqueIn(arg_id='q-doubt', attacks='nonexistent-tag', kind='doubt'))

    # 픽스 후 기대: 형제 경로(add_research_event:170)와 동일한 404
    assert exc.value.status_code == 404
    # fail-loud 핵심: 404 전이라 orphan critique history 행이 전혀 쓰이면 안 된다
    assert hist_calls == [], (
        '존재하지 않는 노드에 critique history 가 기록됨 — provenance/audit 부정직: '
        f'{hist_calls}')
