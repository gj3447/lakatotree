"""MSRP 휴리스틱 정책층 — 프로그램이 *다음 실험을 스스로 제안*하게 만드는 라카토스의 심장.

엔진은 지금까지 판결을 *집계*만 했다(`metrics`/`laudan`/`leaderboard`). 라카토스 MSRP 의 정의는
두 휴리스틱이다:

  · negative heuristic — modus tollens 를 hard core 에 겨누지 말 것. 반례는 protective belt
    (보조가설)로 흡수하고, hard core 는 PROTECTED. 흡수가 hard core 개정을 요구하면 그건
    AGM revise 안건(자동 아님).
  · positive heuristic — "프로그램을 어떻게 전개할지에 대한 부분적으로 articulate 된 제안들."
    퇴행 가지는 버리고, 진보 frontier 는 밀고, 미검 hard-core 경계는 탐침한다.

이 모듈은 새 판결 권위가 아니다. 기존 appraisal(`laudan.should_abandon`, `metrics.branch_inputs`,
`branch_score`)을 엮어 *연구 정책(다음 수)*을 산출한다 — 판결→계획. `explore.rank_questions` 가
이 계획의 우선순위를 매긴다.

정직 표기: 아래 가중치는 *정책값*(Lakatos/Laudan 정신의 운영 선택)이지 문헌 상수가 아니다.
`abandon` 임계는 `laudan`(Wald SPRT 정초)에서 가져오고, novel/excess-content 신호는 judge 의
구조적 corroboration 정의를 따른다. 매직넘버 신규 도입 없이 의미가 정직하게 드러나도록 명명한다.
# KG: span_lakatotree_heuristic
"""
from __future__ import annotations

from lakatos.quant.laudan import ABANDON_K, should_abandon


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


# ── positive heuristic 가중치 (정책값 — 문헌상수 아님) ──────────────────────────
# 라카토스: 진보 = 초과경험내용(novel) + 진보노선 모멘텀. 라우든: 미해결 문제압 해소.
PG_BASE = 0.10        # 어떤 frontier 질문이든 닫으면 최소한의 진보 기대(중립 default 와 연속)
PG_NOVEL = 0.40       # 구조적 novel target 보유 = 초과경험내용 잠재(라카토스 진보의 핵심 신호)
PG_MOMENTUM = 0.20    # 정본/진보 frontier 위 질문 = positive heuristic 가 미는 살아있는 전선
PG_PRESSURE = 0.30    # 가지가 진 미해결-문제 적자(=음의 문제수지) 해소 잠재(라우든)


def realized_reward(progressive_hits: int, attempts: int) -> float:
    """bandit reward 를 *실현 진보*로 학습 — Laplace 계승규칙 (hits+1)/(attempts+2).

    gap6(reward 순환) 의 학습 반쪽: 가지가 이 노선에서 시도한 노드(attempts) 중 progressive/partial
    적중(progressive_hits)의 사후 성공확률. attempts=0 → 0.5(미학습 무차별, Laplace 1814 DEFAULT_PRIOR
    와 동일 정신). 노선이 실제로 진보를 내면 ↑, 땜빵만 쌓이면 ↓ — 사전구조 추정을 실측으로 교정.
    # 출처: Laplace rule of succession (1814). grounding DEFAULT_PRIOR 와 동일 무차별 prior.
    """
    a = max(attempts, 0)
    h = max(min(progressive_hits, a), 0)
    return (h + 1.0) / (a + 2.0)


def expected_progress_gain(*, canonical_credence: float = 0.5,
                           problem_pressure: float = 0.0,
                           on_canonical_frontier: bool = False,
                           has_novel_target: bool = False,
                           learned_reward: float | None = None) -> float:
    """E[Δ진보 | q 닫힘] 추정 — VoI 분자. (전엔 `directions` 에서 0.1 하드코딩 = 가짜 분자.)

    구조에서 도출한다:
      · has_novel_target  — q 가 구조적 novel metric/threshold 를 달면 초과경험내용 잠재(진보 신호)
      · on_canonical_frontier — 정본/진보 노드에 달린 질문이면 살아있는 전선(positive heuristic 모멘텀)
      · problem_pressure  — 가지의 미해결-문제 적자 크기 [0,1] (음의 문제수지를 정규화; 클수록 닫을 게 많음)
      · canonical_credence — 신뢰 가는 프로그램의 다음 수가 더 값짐 (베이즈 가지신뢰로 스케일)
      · learned_reward    — `realized_reward` 의 실현 성공률 [0,1] (gap6 학습). 주면 보정 factor
        [0.5,1.5] 로 곱: 0→0.5×(증명된 헛수고는 감쇠), 0.5→1.0×(중립), 1→1.5×(진보노선 가산).
    단조: novel/모멘텀/압력/학습보상↑ → gain↑. 신뢰↓ → 전체 감쇠. 반환 [0,1].
    """
    gain = PG_BASE
    if has_novel_target:
        gain += PG_NOVEL
    if on_canonical_frontier:
        gain += PG_MOMENTUM
    gain += PG_PRESSURE * _clamp01(problem_pressure)
    # 프로그램 신뢰로 스케일: credence 0 이어도 바닥 0.5 (질문 자체의 정보가치는 남음)
    gain *= 0.5 + 0.5 * _clamp01(canonical_credence)
    if learned_reward is not None:
        # 실현 reward 로 보정 (bandit 학습): factor∈[0.5,1.5], reward 0.5 에서 중립(1.0×)
        gain *= 0.5 + _clamp01(learned_reward)
    return round(_clamp01(gain), 4)


def negative_heuristic(*, hard_core, refuted_assumptions, belt=None) -> dict:
    """라카토스 negative heuristic — "modus tollens 를 hard core 에 겨누지 말 것."

    반례가 refute 하는 가정들을 분류한다:
      · protected   — hard core 에 속함 → 금지 타겟. belt 로 redirect 해야 함.
      · redirectable — protective belt(보조가설) → 개정으로 반례 흡수 가능.
    belt 를 안 주면 hard_core 에 없는 모든 refuted 가정을 belt 로 간주(개방세계 default).

    requires_core_revision = refuted 가정이 *전부* hard core 일 때만 True — 즉 belt 로 흡수 불가,
    프로그램의 정체성을 건드려야 하는 상황. 이건 자동 폐기가 아니라 AGM revise 안건이다
    (agm.py / `/api/agm/revise` 로 인간 동의 하 hard_core shift). 자동 금지(negative heuristic 준수).
    # 출처: Lakatos MSRP 1970 §3 (hard core / protective belt / two heuristics).
    """
    core = set(hard_core)
    refuted = list(dict.fromkeys(refuted_assumptions))   # 순서보존 dedup
    belt_set = set(belt) if belt is not None else None

    protected, redirectable = [], []
    for a in refuted:
        if a in core:
            protected.append(a)
        elif belt_set is None or a in belt_set:
            redirectable.append(a)
        else:
            redirectable.append(a)   # 미지 가정 → belt 로 취급(보수적: hard core 오염 금지)

    requires_core_revision = bool(refuted) and not redirectable
    return {
        "protected": protected,
        "redirectable": redirectable,
        "requires_core_revision": requires_core_revision,
        "absorbable_in_belt": bool(redirectable),
        "rule": "modus_tollens_to_belt_not_core",
    }


# ── positive heuristic — 다음 실험 생성 (move kinds) ────────────────────────────
MOVE_ABANDON = "ABANDON"        # 퇴행 가지 → 정지 + 형제 탐색 제안
MOVE_PUSH = "PUSH"              # 진보 frontier 노드의 열린 질문 → novel 예측 사전등록
MOVE_PROBE = "PROBE"            # 미검 hard-core 가정 → 경계 탐침(negative heuristic 가장자리)
MOVE_PRIORITIZE = "PRIORITIZE"  # 높은 미해결-문제압 열린 질문 → 우선 착수


def _abandon_moves(branch: dict, pressure: float) -> list[dict]:
    """ABANDON 생성 — 정본 가지가 라우든 퇴행 규칙(should_abandon SSOT)에 걸리면 정지+형제 제안."""
    abandon, reason = should_abandon(
        consecutive_nonprogressive=int(branch.get("consecutive_nonprogressive", 0)),
        nodes_spent=int(branch.get("nodes_spent", 0)),
        prediction_hits=int(branch.get("prediction_hits", 0)),
        problem_balance_windowed=int(branch.get("problem_balance_windowed", 0)),
    )
    if not abandon:
        return []
    leaf = branch.get("leaf")
    return [{
        "kind": MOVE_ABANDON,
        "target": leaf,
        "rationale": f"퇴행 가지 — {reason}. hard core 보존하며 형제 노선으로 분기 제안.",
        "est_gain": round(0.6 + 0.4 * _clamp01(pressure), 4),
        "suggested_action": f"branch '{leaf}' 정지 → 같은 부모에서 대안 보조가설 시도",
    }]


def _probe_moves(hard_core, tested_core) -> list[dict]:
    """PROBE 생성 — 아직 실측 탐침 안 된 hard core 가정마다 경계 탐침(negative heuristic 가장자리, 보호≠무검증)."""
    untested = [c for c in hard_core if c not in set(tested_core)]
    return [{
        "kind": MOVE_PROBE,
        "target": c,
        "rationale": "hard core 가정 미검 — negative heuristic 은 보호하나 경계는 탐침돼야(맹신 방지).",
        "est_gain": round(0.30, 4),
        "suggested_action": f"'{c}' 가 깨지는 경계 조건을 직접 실측 (반증 시도)",
    } for c in untested]


def _question_moves(nodes: list, open_qs: list, branch: dict,
                    pressure: float, reward: float) -> list[dict]:
    """PUSH/PRIORITIZE 생성 — 열린 질문을 정본 전선(PUSH)/문제압(PRIORITIZE)으로 분류해 est_gain 부여.

    ★ 질문→연 노드 링크는 node['questions'] (KG RAISES_QUESTION) 로 역매핑 — frontier row 엔
    opened_by 가 없다(repository.py). directions 와 동일 규약. opened_by 명시 시 존중(in-memory 호환)."""
    progressive = ("CANONICAL", "progressive", "progressive_conditional")
    front_qnames = {qn for n in nodes if n.get("verdict") in progressive
                    for qn in (n.get("questions") or [])}
    novel_qnames = {qn for n in nodes if n.get("novel_registered")
                    for qn in (n.get("questions") or [])}
    moves: list[dict] = []
    for q in open_qs:
        qn = q.get("name")
        on_front = qn in front_qnames or (
            bool(set(q.get("opened_by") or []) & {n.get("tag") for n in nodes
                 if n.get("verdict") in progressive}))
        # finding D4 (2026-07-12): PG_NOVEL(0.40, 최대 항)은 *등록된* novelty(novel_qnames) 또는 *구조적으로
        # 완전한* NovelTarget spec(metric ∧ direction ∧ threshold) 에만 부여 — 아무 novel_* 필드 하나의 존재로
        # PG_NOVEL 을 사는 Goodhart 구멍 봉합(novel_target='x' 한 줄로 move 랭킹 최상위 조작 방지).
        has_novel = qn in novel_qnames or bool(
            q.get("novel_metric") and q.get("novel_direction")
            and q.get("novel_threshold") is not None)
        eg = expected_progress_gain(
            canonical_credence=float(branch.get("canonical_credence", 0.5) or 0.5),
            problem_pressure=pressure, learned_reward=reward,
            on_canonical_frontier=on_front,
            has_novel_target=has_novel,
        )
        if on_front:
            kind, action = MOVE_PUSH, "정본 전선 — novel metric/threshold 사전등록 후 변경 1개 실행"
        else:
            kind, action = MOVE_PRIORITIZE, "미해결 문제압 해소 — 사전등록 예측으로 착수"
        moves.append({
            "kind": kind,
            "target": q.get("name"),
            "rationale": q.get("body") or q.get("question") or "",
            "est_gain": eg,
            "suggested_action": action,
        })
    return moves


def generate_moves(*, nodes: list, frontier: list, branch: dict,
                   hard_core=(), tested_core=()) -> list[dict]:
    """positive heuristic — 트리 상태에서 다음 실험 후보를 *생성*한다 (손-입력 정렬이 아니라).

    nodes    = 노드 dict 리스트 (tag/verdict/parent/...). frontier = 질문 dict 리스트.
    branch   = `metrics.branch_inputs(...)` 출력 (정본 leaf 의 consecutive_nonprogressive,
               nodes_spent, prediction_hits, problem_balance_windowed, verdicts).
    hard_core/tested_core = 프로그램 hard core 가정과 이미 실측 탐침된 가정들.

    move kinds (라카토스 정신):
      ABANDON    — should_abandon(가지) True → 정지 + 형제 노선 제안 (퇴행 인정)
      PUSH       — 정본/진보 노드에 열린 질문 존재 → 그 전선을 novel 예측으로 밀기
      PROBE      — hard core 가정이 미검 → 경계 탐침 (보호받지만 검증은 받아야)
      PRIORITIZE — 음의 문제수지(미해결 적자) 가지 → 가장 압 큰 열린 질문 우선
    각 move: kind/target/rationale/est_gain/suggested_action. est_gain 내림차순 정렬.
    """
    # 공유 입력 1회 계산 후 move-type 별 생성기에 위임(한 전략=한 함수). append 순서
    # (ABANDON→PROBE→PUSH/PRIORITIZE) 보존 → 안정정렬이라 동률 순서까지 동작 불변.
    open_qs = [q for q in frontier if (q.get("status") or "OPEN") == "OPEN"]
    pressure = branch_pressure(branch)
    reward = realized_reward(int(branch.get("prediction_hits", 0)),
                             int(branch.get("nodes_spent", 0)))
    moves = (_abandon_moves(branch, pressure)
             + _probe_moves(hard_core, tested_core)
             + _question_moves(nodes, open_qs, branch, pressure, reward))
    moves.sort(key=lambda m: -m["est_gain"])
    return moves


def branch_pressure(branch: dict) -> float:
    """음의 문제수지(미해결 적자)를 [0,1] 압력으로. balance ≤ −ABANDON 규모면 포화.
    `directions` 가 VoI 분자 스케일로 재사용(미해결 적자 큰 가지의 질문이 더 값짐)."""
    pb = int(branch.get("problem_balance_windowed", 0))
    if pb >= 0:
        return 0.0
    # −1 → 작은 압, −ABANDON_K(=3) 이상 적자 → 포화 (laudan 임계 규모와 정합)
    return _clamp01(-pb / float(max(ABANDON_K, 1)))


_branch_pressure = branch_pressure   # 내부 별칭(하위호환)


def appraise_and_plan(*, nodes: list, frontier: list, branch: dict,
                      hard_core=(), tested_core=()) -> dict:
    """프로그램 연구정책 = negative(보호 경계) + positive(생성된 다음 수) 한 묶음.

    negative_heuristic 은 *현재 퇴행 신호*를 반례로 보고 hard core vs belt 책임을 가른다
    (consecutive_nonprogressive>0 이면 '뭔가 refute 중'). positive 는 generate_moves.
    """
    moves = generate_moves(nodes=nodes, frontier=frontier, branch=branch,
                           hard_core=hard_core, tested_core=tested_core)
    abandoning = any(m["kind"] == MOVE_ABANDON for m in moves)
    neg = negative_heuristic(
        hard_core=hard_core,
        # 퇴행 중이면 belt(미검 hard-core 제외 가정)가 1차 redirect 대상 — 자동 core 개정 금지
        refuted_assumptions=list(tested_core) if abandoning else [],
        belt=None,
    )
    return {
        "leaf": branch.get("leaf"),
        "negative_heuristic": neg,
        "moves": moves,
        "n_moves": len(moves),
        "abandon_signaled": abandoning,
    }
