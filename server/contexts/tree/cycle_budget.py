"""트리별 채점 사이클 예산 — 소모 집계와 거부의 단일 정본(SSOT).

PROM16 S1/S5 는 '무한 루프 금지'와 '에이전트 자기판단과 독립된 정지'를 요구한다. 첫 구현(2026-07-15)은
run_cycle *만* 거부해서 그 독립성을 스스로 부정했다 — 소진된 에이전트가 3-verb 경로(add_node +
register_prediction + submit_result)나 set_verdict 로 갈아타면 계속 채점됐다(적대검증 2026-07-15:
"the shipped stop is agent-elective"). 에이전트가 고를 수 있는 정지는 정지가 아니다. 이 모듈이 그
초크포인트를 한 곳에 모아, 판결을 민팅할 수 있는 *모든* verb 가 같은 게이트를 지나게 한다.

★세는 것과 막는 것을 같은 술어에 묶는다(대칭):
  세는 것 = 판결을 받은 노드(scored_nodes) = FORCEFUL verdict_source ∨ 비-prediction 영수증 보유.
  막는 것 = 그 집합을 늘릴 수 있는 verb 전부 — run_cycle / submit_test_result / set_verdict.

  술어가 두 겹인 이유(단일 조건은 양쪽 다 틀린다):
    · verdict_source 단독 → CANONICAL 승격이 'scripted' 를 'admin'(STRUCTURAL, 非FORCEFUL)으로
      덮어써 소모가 *감소*한다 = 승격이 예산을 환불(비단조).
    · current_receipt_sha 단독(구 술어) → register_prediction 이 *예측* 영수증으로 체인 포인터를
      세우므로 미채점 노드가 소모로 잡힌다. budget=1 이면 run_cycle 이 방금 등록한 자기 예측 때문에
      자기 submit 을 거부하는 자멸이 된다 — 즉 구 술어는 초크포인트 게이트와 구조적으로 양립 불가였고,
      'cycles_used' 라는 이름도 그래서 거짓이었다(채점 아닌 노드를 셌다).
  영수증은 불멸이라(G1/G9 — 보상 롤백·cascade 삭제 양쪽 하드가드) 이 술어는 단조 증가한다.
  저장소 재파생이므로 재시작·워커 증설에도 같은 답(S5 내구: fresh run == resume).

★권위와 동시성:
  · ``budget_state`` 선조회는 빠른 429/미리보기용 진단일 뿐 권위가 아니다. 실제 submit/set_verdict
    첫 mutation statement 가 트리 write lock 을 먼저 얻고, *그 락을 보유한 채* 같은 scored-node
    술어를 다시 센다. 따라서 서로 다른 프로세스의 판결 verb 도 budget=1 의 마지막 자리를 동시에
    소비할 수 없다. guard 가 0행이면 트랜잭션 전체가 rollback 되고 strict readback 으로 429/409/500을
    구분한다. KG 장애나 malformed budget 은 mutation 자체가 성립하지 않아 fail-closed 다.

★정직한 잔여 비대칭(숨기지 않고 여기 박아둔다):
  · 거부 ⊋ 소모 — 이미 세어진 노드의 freshen 재제출/행정 이동도 소진 트리에선 거부된다(새 소모는
    없는데 막는다). 우회가 아니라 과잉거부(안전한 방향)이며, 회복은 예산 상향 또는 새 트리 분기.
  · add_node/register_prediction 은 세지도 막지도 않는다 — 예산은 *판결*의 상한이지 write 의 상한이
    아니다. 소진 트리에도 노드·예측은 계속 쌓인다(판결만 안 난다).
  · 엔진발 강등(critique→former_canonical / agm_revise auto-rejudge / certify)은 게이트 밖 — 에이전트가
    부르는 채점 verb 가 아니다. 단 '새 소모 0' 은 *대부분*이지 전부가 아니다: 레거시 pre-G1 CANONICAL
    (verdict_source='admin'=STRUCTURAL · 판결 영수증 없음)은 술어상 미집계인데, 강등이 source 를
    'engine'(FORCEFUL)으로 덮고 영수증을 달면 그 노드가 *그때 처음* 집계된다 = 게이트 밖 +1 소모.
    방향은 과대집계(안전)이고, 현행 승격 경로는 판결 영수증을 같이 남겨 이미 집계되므로 신규 노드엔
    안 생긴다 — 잔존 표면은 영수증 이전 시대 노드뿐.
  · 진단 선조회 실패는 미선언처럼 보일 수 있지만, mutation 내부 락-가드는 생략되지 않는다. 즉 UX
    선조회는 fail-open 이어도 판결 write 는 fail-closed 다. dry_run 은 애초에 write/소모가 없어 예외다.
  · ★상한 self-raise 마찰(2026-08-01, q-selfdev-budget-ratchet): create_tree 경로에서 *기존 예산
    상향* 은 confirm_budget_raise=true 필수(미확인 409). attestor_dids 가 있으면 write-cert 도 필수
    (assurance_tier 쓰기와 대칭). writer LWW 는 유지하되 service 게이트가 무마찰 상향을 막는다.
    잔여: 확인 플래그 자체를 아는 적대 에이전트는 여전히 상향 가능 — 운영자 authn 구분 전까지
    완전 정지는 아니다. 다만 우연/자동화 루프의 무음 self-raise 는 닫혔다.
# KG: span_lakatotree_engine / G3_one_verb_honest_cycle
"""

from __future__ import annotations

from fastapi import HTTPException

from lakatos.verdicts import FORCEFUL_SOURCES

# 4xx/advice 앵커 + 테스트 식별자 — 거부 메시지의 안정 부분문자열(바꾸면 advice 레지스트리도 같이).
EXHAUSTED_SIGNATURE = '사이클 예산 소진'

# '판결을 받은 노드' 술어 — 소모 집계와 거부가 같은 정의를 보도록 *한 곳*에만 산다.
#   비-prediction 영수증 = 판결 영수증(receipt_kind 는 prediction 에만 스탬프됨 → 판결은 NULL).
_SCORED_NODE = (
    "e.verdict_source IN $forceful "
    "OR size([(e)-[:HAS_RECEIPT]->(r:VerdictReceipt) "
    "WHERE coalesce(r.receipt_kind,'verdict') <> 'prediction' | 1]) > 0")

LOCKED_BUDGET_GUARD = (
    # Neo4j's documented dummy-property lock: the NODE write lock is held to
    # transaction end, while REMOVE leaves no synthetic domain state behind.
    "SET t._cycle_budget_lock = true "
    "REMOVE t._cycle_budget_lock "
    "WITH t, COUNT { MATCH (t)-[:HAS_NODE]->(budget_node) WHERE "
    "budget_node.verdict_source IN $forceful "
    "OR size([(budget_node)-[:HAS_RECEIPT]->(budget_receipt:VerdictReceipt) "
    "WHERE coalesce(budget_receipt.receipt_kind,'verdict') <> 'prediction' | 1]) > 0 "
    "} AS budget_used "
    "WITH t, budget_used, CASE "
    "WHEN t.cycle_budget IS NULL THEN 'unlimited' "
    "WHEN valueType(t.cycle_budget) STARTS WITH 'INTEGER' "
    "AND t.cycle_budget >= 0 AND budget_used < t.cycle_budget THEN 'proceed' "
    "WHEN valueType(t.cycle_budget) STARTS WITH 'INTEGER' "
    "AND t.cycle_budget >= 0 THEN 'exhausted' ELSE 'corrupt' END AS budget_status "
    "WHERE budget_status IN ['unlimited','proceed'] "
    "WITH t "
)

_STATE_CYPHER = (
    "MATCH (t:LakatosTree {name:$tree}) "
    "OPTIONAL MATCH (t)-[:HAS_NODE]->(e) "
    f"WHERE {_SCORED_NODE} "
    "RETURN t.cycle_budget AS cycle_budget, count(e) AS used")


def budget_state(kg, name: str) -> tuple[int | None, int]:
    """(cycle_budget, scored_nodes) — 트리 메타의 선언 예산과 *저장소서 파생한* 채점노드 수.

    내구성이 요점(S5): 소모를 인메모리 카운터로 세면 서버 재시작·워커 증설·다중 프로세스마다 0 으로
    리셋돼 상한이 허구가 된다. 여기선 이미 판결을 받은 노드를 세어 파생하므로 재시작 후 resume 이
    fresh run 과 같은 답을 낸다.

    이 read 는 빠른 거부와 dry-run 표시를 위한 비권위 진단이다. 조회 실패는 (None, 0)으로 돌려 기존
    KG-less 소비자를 보존하지만, 실제 판결 write 는 ``LOCKED_BUDGET_GUARD`` 를 같은 mutation 안에서
    반드시 실행하므로 장애/동시성으로 예산을 우회하지 못한다.
    """
    try:
        rows = kg(_STATE_CYPHER, tree=name, forceful=sorted(FORCEFUL_SOURCES))
        if not rows or rows[0].get('cycle_budget') is None:
            return None, 0   # 미선언(기존 트리 전부) = 무제한 — 기본 비파괴
        return int(rows[0]['cycle_budget']), int(rows[0].get('used') or 0)
    except Exception:   # noqa: BLE001 — 조회/파싱 실패=예산 미상 → 무제한(위 fail-safe 계약)
        return None, 0


def strict_budget_state(kg, name: str) -> tuple[int | None, int]:
    """Fail-closed diagnostic used after the lock-held mutation guard rejects."""

    try:
        rows = kg(_STATE_CYPHER, tree=name, forceful=sorted(FORCEFUL_SOURCES))
    except Exception as exc:  # noqa: BLE001 - this path classifies a rejected write
        raise HTTPException(503, "cycle budget readback unavailable") from exc
    if len(rows or []) != 1:
        raise HTTPException(500, "cycle budget readback cardinality conflict")
    if not ({"cycle_budget", "used"} & set(rows[0])):
        # Narrow compatibility seam for pure unit fakes that do not model the
        # diagnostic query. Real Neo4j always returns both aliases below.
        return None, 0
    budget = rows[0].get("cycle_budget")
    used = rows[0].get("used")
    if type(used) is not int or used < 0:
        raise HTTPException(500, "cycle budget usage is corrupt")
    if budget is None:
        return None, used
    if type(budget) is not int or budget < 0:
        raise HTTPException(500, "cycle budget declaration is corrupt")
    return budget, used


def raise_after_locked_budget_rejection(kg, name: str, verb: str) -> None:
    """Map a lock-held guard miss to quota exhaustion or a generic CAS conflict."""

    budget, used = strict_budget_state(kg, name)
    if budget is not None and used >= budget:
        raise HTTPException(429, exhausted_detail(name, verb, budget, used))


def remaining_budget(budget: int | None, used: int) -> int | None:
    """잔여 — 미선언(None)이면 None(무제한). 레거시 초과 상태는 0으로 clamp한다."""
    return None if budget is None else max(0, budget - used)


def exhausted_detail(name: str, verb: str, budget: int, used: int) -> str:
    """소진 거부의 detail — 무엇이 막혔고 무엇은 안 막혔는지 *둘 다* 말한다(과대주장 금지)."""
    return (f"{EXHAUSTED_SIGNATURE} — 트리 '{name}' 채점 상한 {budget}(채점노드 {used})에 걸려 {verb} "
            f"거부(쓰기 0). 판결 verb 전부(run_cycle/submit_test_result/set_verdict)에 같은 게이트가 "
            f"걸려 있어 verb 를 갈아타는 우회는 없다. add_node/register_prediction 은 계속 되지만 "
            f"판결은 나지 않는다 — 예산을 올리거나(create_tree cycle_budget) 새 트리로 분기할 것.")


def assert_scoring_budget(kg, name: str, verb: str) -> None:
    """채점 verb의 빠른 진단 게이트. 원자적 권위는 mutation 내부 ``LOCKED_BUDGET_GUARD``다.

    소진 트리면 비싼 판정 작업 전에 429를 돌리고, 미선언이면 no-op이다. 이 선조회가 실패하거나
    오래돼도 실제 판결 mutation은 락을 잡고 다시 세므로 이를 안전 경계로 해석하면 안 된다.

    429(Too Many Requests) 인 이유: 이건 요청의 잘못(4xx-semantic)이 아니라 트리에 걸린 *할당량*이다 —
    같은 요청이 예산 상향 후엔 그대로 성립한다. 409(상태충돌)/403(권한)과 구분해 루프 드라이버가
    'budget' 분기를 오분류 없이 잡게 한다.
    """
    budget, used = budget_state(kg, name)
    if remaining_budget(budget, used) != 0:   # None(미선언)=무제한 → 통과
        return
    raise HTTPException(429, exhausted_detail(name, verb, int(budget), used))
