"""트리 보증 tier × verb 게이트 디스패치 테이블 — git-흡수 G6 SSOT.

git 은 verb 별 전제조건 비트를 한 commands[] 테이블(git.c:529-685)에 선언하고 단일 run_builtin 이
핸들러 진입 전 일괄검사한다 — 핸들러가 검사를 '잊을' 수 없다(S3 의 핸들러별 비일관 장르 제거).
이식하되 git 의 default-OFF(transfer.fsckObjects 기본 off)는 정확히 *반전*한다(P1 증명: 선택적
보증은 영원히 꺼짐): 신규 트리는 최고 tier(anchored)가 기본이고, 구조 코어는 tier 어휘 *밖*이라
어떤 tier 도 그것을 끄는 문장을 표현할 수 없다(by construction).

tier 서열(단조 — 상위 tier 게이트 ⊇ 하위):
  notebook  : 추가 게이트 없음(탐색 노트북). 구조 코어는 물론 무조건.
  receipted : cross-metric novel 은 서버앵커 영수증(novel_script 서버 재유도) 없이 progressive 못 빚음.
  anchored  : receipted + producer replay 가 *실행되어 실패*하면 CANONICAL 승격 차단(승격 FLOOR).
              LAKATOS_REPLAY_EXEC off(=None)면 비차단 — dead-σ 교정: 검증 불가는 부재지 반증이 아님
              (naive wake 로 floor 를 exec-트리거로 오설정하면 exec-OFF 배포가 anchored 승격 전부 409 lock).
  LEGACY    : G6 이전 트리(assurance_tier 프로퍼티 없음). tier 게이트는 트리 자신의 opt-in 플래그로만
              발동(거동 불변 — 소급 강등 없음). 감사(fsck) 면제는 노드 content-sha skiplist 로만.

이 모듈이 tier 정책의 유일 정본이다: 핸들러(judgement_service 등)는 gates_for() 를 *읽고*,
writer 의 DB-side ratchet Cypher 는 cypher_tier_rank_case() 로 여기서 *생성*된다(표류 불가).
"""

from __future__ import annotations

# 서열 — 단조 ratchet(다운그레이드 409)의 정본. 이름은 의미로 고정:
#   notebook(공책) < receipted(영수증 요구) < anchored(외부앵커 floor).
TIERS: tuple[str, ...] = ("notebook", "receipted", "anchored")
TIER_RANK: dict[str, int] = {"notebook": 0, "receipted": 1, "anchored": 2}
LEGACY = "legacy"                      # resolve 결과 전용 — 선언 어휘(TIERS)엔 없음(선언 불가)
DEFAULT_NEW_TREE_TIER = "anchored"     # git default-OFF 의 반전: 신규는 최고 tier 가 기본

# tier 게이트 비트 어휘.
GATE_NOVEL_ANCHOR = "novel_anchor"     # cross-metric novel → 서버앵커 영수증 필수(FF1 을 tier 정책화)
GATE_REPLAY_FLOOR = "replay_floor"     # producer replay 실행-후-실패 → CANONICAL 승격 차단
GATE_WRITE_CERT = "write_cert"         # G10: 판결 쓰기는 서명 cert 만 명령원 — 발동 = 무장 ∧ 트리
                                       #   attestor allow-list(키 실물) 선언. 키 없는 배포는 잠기지
                                       #   않는다(dead-σ 안전); advisory cert(P1 실패)는 반전 이식.
GATE_REPRODUCIBILITY_CEILING = "reproducibility_ceiling"   # AG4/R-SOV V2(측정주권 2026-07-03):
                                       #   재현성이 *구조적으로 반증*(reproducible is False: lineage
                                       #   dangling/비-source root)된 노드를 submit 에서 progressive 밖
                                       #   partial 로 천장(하드 409 아님, 값 보존). ★불가 None(증명불가)은
                                       #   천장 안 함(부재≠반증, dead-σ) — 라이브 무회귀의 뿌리.

# 구조 코어 — G1 receipt CAS · prereg 409 · writer first-write-wins. *의도적으로* 위 게이트 어휘와
# 분리된 집합: TIER_GATES/VERB_GATES 에 이 토큰이 등장할 수 없어(가드 테스트가 교집합 ∅ 강제),
# tier 로 구조 코어를 끄는 문장 자체가 표현 불가다. 모든 tier·모든 verb 에서 무조건.
STRUCTURAL_CORE: frozenset[str] = frozenset({"receipt_cas", "prereg_409", "first_write_wins"})

# verb → 이 verb 에 적용될 수 있는 tier 게이트 비트(적용 여부는 tier 가 결정 — 아래 TIER_GATES 와 AND).
VERB_GATES: dict[str, frozenset[str]] = {
    "submit_test_result": frozenset({GATE_NOVEL_ANCHOR, GATE_WRITE_CERT, GATE_REPRODUCIBILITY_CEILING}),
    "set_verdict_canonical": frozenset({GATE_REPLAY_FLOOR, GATE_WRITE_CERT}),   # AG5-IDENT: 비가역 승격 서명강제
}

# tier → 무장된 게이트 비트. 서열에 단조증가(상위 ⊇ 하위 — 가드 테스트가 강제).
TIER_GATES: dict[str, frozenset[str]] = {
    "notebook": frozenset(),
    "receipted": frozenset({GATE_NOVEL_ANCHOR}),
    "anchored": frozenset({GATE_NOVEL_ANCHOR, GATE_REPLAY_FLOOR, GATE_WRITE_CERT,
                           GATE_REPRODUCIBILITY_CEILING}),
    LEGACY: frozenset(),   # legacy 는 tier 게이트 없음 — opt-in 플래그로만(거동 불변)
}


def resolve_tier(raw: object) -> str:
    """KG 프로퍼티 → tier. 없음/미정의 어휘 = LEGACY (tolerant read — G8 규율: 부패는 500 이 아니라
    감사 발견으로; 미정의 tier 문자열은 게이트 0 인 LEGACY 로 읽되 쓰기 경계(validate)가 애초에 막는다)."""
    if isinstance(raw, str) and raw in TIER_RANK:
        return raw
    return LEGACY


def tier_rank(tier: object) -> int:
    """서열 랭크. LEGACY/None/미정의 = -1 (어느 명시 tier 로의 선언도 업그레이드)."""
    if isinstance(tier, str):
        return TIER_RANK.get(tier, -1)
    return -1


def gates_for(verb: str, tier: str) -> frozenset[str]:
    """단일 디스패치 조회 — 이 verb 에 이 tier 가 무장한 게이트 비트. 핸들러는 이 결과를 *읽기만* 한다."""
    return VERB_GATES.get(verb, frozenset()) & TIER_GATES.get(tier, frozenset())


def structural_core_gates(tier: str | None = None) -> frozenset[str]:
    """구조 코어 게이트 — 서명이 곧 불변식: tier 인자를 받되 *무시*한다(어떤 tier 도 다른 답을 못 받음)."""
    del tier
    return STRUCTURAL_CORE


def cypher_tier_rank_case(prop_expr: str) -> str:
    """TIER_RANK 에서 DB-side 랭크 CASE 를 생성 — writer 의 단조 ratchet 이 이 문자열을 그대로 방출한다.
    서열의 정본은 TIER_RANK 하나(SSOT): Cypher 리터럴이 따로 살면 표류하므로 여기서 찍어낸다."""
    whens = " ".join(f"WHEN '{t}' THEN {TIER_RANK[t]}"
                     for t in sorted(TIER_RANK, key=lambda t: TIER_RANK[t]))
    return f"CASE {prop_expr} {whens} ELSE -1 END"
