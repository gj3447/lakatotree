"""4xx advice 레지스트리 — git advice.* 이식 (git-흡수 G3 S4, suggest-only).

git 은 실패마다 '다음에 칠 명령'을 advice.c(43-98)의 *한 레지스트리*에서 가르친다 — 실행하지 않고
제안만 한다. 이식 규율(anti-absorption): advice 는 **suggest-only** — 상태코드를 바꾸지 않고, 아무것도
실행하지 않고, 게이트를 우회할 수단(git --no-verify 류 off-switch)을 절대 제공하지 않는다.

레지스트리는 (detail 부분문자열, 제안) 순서 리스트 — 첫 적중이 이긴다. 새 advice 는 여기에만(H9 SSOT).
"""

from __future__ import annotations

from fastapi import HTTPException

# (detail 부분문자열 → 다음 명령 제안). 엔진의 실제 4xx detail 문구에 앵커.
_REGISTRY: tuple[tuple[str, str], ...] = (
    ("나무 없음", "먼저 create_tree: POST /api/tree/{name} — 신규 트리는 assurance tier 기본 anchored."),
    ("이미 스크립트로 채점", "재채점 금지(re-roll 차단) — 새 tag 로 분기: run_cycle(tag=<새태그>, parent=<이전 tag>)."),
    ("사후 예측등록 금지", "이미 채점/예측된 노드 — 새 노드로 분기해 사이클을 다시 돌릴 것(run_cycle tag=<새태그>)."),
    ("동시/재채점 차단", "동시 제출 감지 — 새 노드로 분기하거나 get_tree 로 최신 상태 확인 후 재시도."),
    ("novel_measured", "novel_metric 을 선언했으면 독립 측정 novel_measured=<float> 를 함께 제출 "
                       "(가능하면 novel_script 도 — 서버앵커 영수증), 아니면 novel_* 필드를 제거."),
    # R2-NOVEL: FF1 앵커-데모트(4xx 아닌 200-partial) 의 다음 수 — run_cycle 이 이 키로 직조회한다.
    ("novel_not_server_anchored", "cross-metric novel 이 서버앵커 미성립으로 partial 강등 — 같은 사이클을 "
                                  "novel_script=<서버가 읽을 실파일 경로 또는 file::symbol> 동봉으로 새 tag "
                                  "에 재실행하거나, 이 노드에 동일 metric_value + 서버앵커 script/novel_script "
                                  "재제출(freshen)로 승급. dry_run=true 가 would_demote_to_partial 로 사전 예고."),
    # jp4: 판관 stale/무능력 provisional 강등의 회복 통로 안내(200-partial 의 다음 수).
    ("provisional_stale_engine", "판관이 stale/무능력(코드경로 변경 미재기동 또는 G6 결손)이라 progressive 가 "
                                 "partial 로 provisional 강등 — scripts/dev_server_restart.sh 재기동 후 "
                                 "*동일 metric_value* 재제출(freshen)로 승급(값 변경은 re-roll 409)."),
    ("metric 온톨로지 위반", "트리 ontology 가 선언한 metric 어휘/방향만 허용 — get_tree 로 ontology 확인."),
    ("judge_script_sha", "script 를 실재 파일 경로(또는 file::symbol)로 제출하면 서버가 sha 를 재유도한다 — "
                         "inline 이면 sha 검증 불가로 미검증 표기."),
    ("assurance_tier", "tier 는 notebook|receipted|anchored 닫힌 어휘 + 단조 ratchet(하향 불가) — "
                       "하향이 필요하면 새 트리로 분기."),
)


def advice_for(detail: object) -> str | None:
    """detail(문자열/dict)에서 첫 적중 advice. 없으면 None — 없는 조언을 지어내지 않는다."""
    text = str(detail or "")
    for needle, tip in _REGISTRY:
        if needle in text:
            return tip
    return None


def with_advice(exc: HTTPException) -> HTTPException:
    """HTTPException 에 advice 를 *덧붙인다* — 상태코드/원본 detail 불변(suggest-only).

    적중 advice 없으면 원본 그대로(포장 안 함). 이미 dict-with-advice 면 재포장 안 함(멱등).
    """
    if isinstance(exc.detail, dict) and "advice" in exc.detail:
        return exc
    tip = advice_for(exc.detail)
    if tip is None:
        return exc
    return HTTPException(exc.status_code, {"error": exc.detail, "advice": tip,
                                           "advice_mode": "suggest-only"})
