"""인증서-근거 게이트 — 첫 적대적 인증서 *소비자*(consumer, re-deriver 아님).

deep-think 2026-07-08(wf_e41a7b9d-d64) GO게이트 결과: 어떤 결정도 `certified` 를 읽지 않는다 —
G6/attested/engine_rule_sha 전부 *읽히지 않는 credential 방어*(prophylactic). 이 순수 술어가 그 빈
소비자 슬롯을 채운다: foundation admission 을 fail-closed 로 만들어, client 가 주장한 status='satisfied'
+ 자유문자열 evidence_refs 를 불신하고 각 근거가 *실제 certified 노드*로 해소될 때만 satisfied 를 유지한다.
아니면 needed 로 강등(gap) → FoundationGate 실패 → synthesize_promotion → CANONICAL 승격 차단.

설계 계약(collision-free, novelty-fix 교훈 반영):
  ★단방향 안전: satisfied→gap 만, 절대 gap→satisfied 아님 → 최악=과보수, 절대 fail-open 아님.
  ★KG-free : 모든 KG/재유도 접근은 주입된 `evidence_ok` 콜백에 격리 — 순수·hermetic(CLAUDE.md §4 hot-path 함정 회피).
  ★비-재유도: 5게이트 유도를 재구현하지 않는다 — 서버 콜백이 node_certificate(단일출처)+verify_verdict_chain 재사용.
  ★kernel 불변: FoundationRequirement.satisfied / FoundationGate.evaluate 미편집 — 입력(foundation readiness)만 필터.
  ★비파괴  : optional/waived(인간 면제) 및 non-evidence requirement 는 그대로 통과. 서버가 opt-in 트리에서만 적용.
# KG: LakatosTree_JudgeProprioception_20260708 / jp7-cert-consumer
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from lakatos.engine import FoundationMap, FoundationRequirement


def _is_evidence_backed(req: FoundationRequirement) -> bool:
    """근거-기반 satisfied 인가(강등 후보). optional/waived(인간 면제)·needed 는 게이트 밖.

    FoundationRequirement.satisfied 커널 규칙(engine.py)의 *근거 분기*와 정확히 일치:
      satisfied == (optional and status=='waived') or (status=='satisfied' and evidence_refs).
    앞 분기(waived)는 건드리지 않고 뒤 분기(근거)만 인증서로 검증한다.
    """
    return req.status == "satisfied" and bool(req.evidence_refs)


def certified_foundation(fmap: FoundationMap, *, evidence_ok: Callable[[str], bool]) -> FoundationMap:
    """근거-기반 satisfied requirement 중 근거가 certified 미확인이면 needed 로 강등한 *새* FoundationMap 반환.

    evidence_ok(ref) — 서버가 주입하는 fail-safe 술어: ref 가 실제 certified(+체인 무결) 노드로 해소되면
    True, 아니면(uncertified·absent·tampered·해소불가) False. 근거가 *전부* 통과해야 satisfied 유지(AND).
    입력 fmap 은 불변(frozen req 를 replace 로 새로 담아 반환) — 부작용 없음.
    """
    out = FoundationMap()
    for req in fmap.requirements():
        if _is_evidence_backed(req) and not all(evidence_ok(ref) for ref in req.evidence_refs):
            req = replace(req, status="needed")   # 강등 → satisfied False → FoundationGate gap
        out.add(req)
    return out
