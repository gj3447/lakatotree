"""라우든 문제해결력 정량층 — 라카토스의 "판정 기준 애매" 한계 보완.

라우든: 과학의 목적 = 문제를 더 많이/잘/적은 부작용으로 해결.
여기서 문제 = OpenQuestion. 해결력 = 닫은 질문 − 새로 연 질문 + metric 개선.
폐기 타이밍 = 명문 규칙 3개 (라카토스가 못 준 시간표를 코드로 강제).

임계는 야매 아님 — grounding 정본 근거: K=3 은 Wald(1945) SPRT 하한(α=β=0.05, lnB=−2.944)의
이산근사(노드당 ≈1 nat 증거), budget=5 는 SPRT 평균표본수 규모, B/w_problem 은 Laudan 정책값(명시).
# KG: span_lakatotree_S1_laudan_layer
"""
from dataclasses import dataclass
import math
from typing import Iterable

from lakatos.grounding import GROUNDED, sprt_log_boundaries

ABANDON_K = GROUNDED['abandon_k']['value']            # 규칙①: 연속 비진보 (Wald SPRT 이산근사)
ABANDON_BUDGET = GROUNDED['abandon_budget']['value']  # 규칙②: 예측 적중 0 노드 예산 (SPRT ASN)
ABANDON_B = GROUNDED['abandon_b']['value']            # 규칙③: 문제 수지 적자 한계 (Laudan 정책)


def problem_balance(closed: int, opened: int) -> int:
    """문제 수지 = 닫은 질문 − 연 질문. 음수 = 변명이 문제를 낳는 중."""
    return closed - opened


def conceptual_problem_score(
    internal_inconsistency: int,
    external_conflict: int,
    *,
    internal_weight: float = 1.0,
    external_weight: float = 1.0,
) -> float:
    """라우든 개념 문제 점수 — empirical closed/open balance 와 분리된 진단층.

    internal_inconsistency = 전통/프로그램 내부의 자기모순·정의충돌.
    external_conflict     = 배경지식·성공한 인접 이론·허용된 방법론과의 외부충돌.

    Laudan 의 conceptual problem 은 경험적 미해결 문제와 성격이 다르므로
    ``problem_balance`` 에 섞지 않는다. 가중치는 문헌 상수가 아니라 호출자가
    드러내는 정책값이다.
    """
    internal = _nonnegative_int("internal_inconsistency", internal_inconsistency)
    external = _nonnegative_int("external_conflict", external_conflict)
    iw = _nonnegative_finite("internal_weight", internal_weight)
    ew = _nonnegative_finite("external_weight", external_weight)
    return internal * iw + external * ew


@dataclass(frozen=True)
class RivalProblemRecord:
    """One programme's outcome for one problem.

    Comparative anomaly needs typed problem outcomes; otherwise "anomaly" falls
    back to prose. ``solved`` is the receipt, and ``explanation_quality`` is a
    policy threshold hook for weak rival solutions.
    """

    programme: str
    problem: str
    solved: bool
    explanation_quality: float = 1.0

    def __post_init__(self) -> None:
        if not self.programme.strip():
            raise ValueError("programme must be non-empty")
        if not self.problem.strip():
            raise ValueError("problem must be non-empty")
        _nonnegative_finite("explanation_quality", self.explanation_quality)


def rival_relative_anomaly(
    target_programme: str,
    problem: str,
    records: Iterable[RivalProblemRecord],
    *,
    min_rival_quality: float = 0.0,
) -> bool:
    """Laudan comparative anomaly: target unsolved + relevant rival solved.

    A problem unsolved by everyone is not yet anomalous for the target. It
    becomes target-relative pressure only when at least one non-target programme
    solves the same problem with enough explanation quality.
    """
    if not target_programme.strip():
        raise ValueError("target_programme must be non-empty")
    if not problem.strip():
        raise ValueError("problem must be non-empty")
    min_quality = _nonnegative_finite("min_rival_quality", min_rival_quality)
    target_solved = False
    rival_solved = False
    for record in records:
        if record.problem != problem:
            continue
        if record.programme == target_programme:
            target_solved = target_solved or record.solved
        elif record.solved and record.explanation_quality >= min_quality:
            rival_solved = True
    return (not target_solved) and rival_solved


def _nonnegative_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _nonnegative_finite(name: str, value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a non-negative finite number")
    return value


def branch_problem_balance_windowed(chain: list, frontier: list,
                                    window: int = ABANDON_BUDGET) -> int:
    """가지 단위 문제수지 (gap4 해소 — 규칙③을 살리는 per-branch 질문귀속).

    chain    = leaf→분기점 순 노드 dict 리스트. 노드의 'questions' = 그 노드가 연 질문 이름들
               (KG RAISES_QUESTION). window 개의 leaf 쪽 최근 노드만 본다 (윈도우=예산 규모 정책).
    frontier = 질문 dict 리스트. ★'closed_by' = 그 질문을 *닫은 노드 tag* 리스트여야 per-branch
               귀속(gap4)이 산다. 비-노드 문자열(사람이름·커밋 등)로 닫으면 어느 노드 tag 와도
               안 걸려 closed 에 미집계 = 해당 가지 문제수지를 과소계상(조용한 false-abandon).
               미귀속 폐쇄는 `unattributed_closures` 로 별도 가시화(정직 신호).
    opened   = 윈도우 노드가 연 질문 수 / closed = closed_by 가 윈도우 노드인 질문 수.
    같은 질문을 윈도우 안에서 열고 닫으면 자연히 수지 0.
    """
    recent = chain[:max(window, 0)]
    recent_tags = {r.get('tag') for r in recent}
    opened = sum(len(r.get('questions') or []) for r in recent)
    closed = sum(1 for q in frontier
                 if recent_tags & set(q.get('closed_by') or []))
    return problem_balance(closed, opened)


def unattributed_closures(node_tags, frontier: list) -> list:
    """CLOSED 인데 closed_by 가 어떤 노드 tag 에도 안 걸리는 질문 이름들 = rule③(문제수지)이
    어느 가지에도 credit 하지 못하는 '미귀속 폐쇄'.

    closed_by 는 '닫은 노드 tag' 여야 branch_problem_balance_windowed 의 per-branch 귀속이 산다.
    이 리스트가 비어있지 않으면 닫힌 질문이 문제수지에 과소계상 중 → 가지가 부당하게 퇴행으로
    보일 수 있다(조용한 false-abandon). 메트릭에 노출해 운영자가 귀속을 교정하게 한다(정직).
    """
    tags = set(node_tags)
    out = []
    for q in frontier:
        if q.get('status') != 'CLOSED':
            continue
        if not (set(q.get('closed_by') or []) & tags):
            out.append(q.get('name') or q.get('qname') or q.get('question'))
    return out


def psr(closed: int, path_nodes: int) -> float:
    """problem-solving rate = 닫은 질문 / 정본경로 노드 수."""
    return closed / path_nodes if path_nodes else 0.0


def branch_score(metric_improvement_pct: float, closed: int, opened: int,
                 w_metric: float = 1.0, w_problem: float = GROUNDED['w_problem']['value']) -> float:
    """비교 문제해결력 — 경쟁 가지 서열화 (라우든의 'rival 보다 생산적인가').
    w_problem=5(문제 1개 > metric % — Laudan 정책가중, grounding 정본)."""
    return w_metric * metric_improvement_pct + w_problem * problem_balance(closed, opened)


def should_abandon(consecutive_nonprogressive: int, nodes_spent: int, prediction_hits: int,
                   problem_balance_windowed: int,
                   k: int = ABANDON_K, budget: int = ABANDON_BUDGET, b: int = ABANDON_B):
    """폐기 타이밍 명문 규칙 — '언제부터 퇴행인가'를 코드로 닫는다.

    ① 연속 비진보 ≥ k                  (땜빵의 연쇄)
    ② 노드 예산 소진 ∧ 예측 적중 0      (관용은 유한 — 적중 1이면 살린다)
    ③ 문제 수지 ≤ −b (window)          (변명이 문제를 낳는 속도가 해결을 추월)
    """
    if consecutive_nonprogressive >= k:
        return True, f'연속 비진보 {consecutive_nonprogressive} ≥ {k}'
    if nodes_spent >= budget and prediction_hits == 0:
        return True, f'예산 {budget}노드 소진, 예측 적중 0'
    if problem_balance_windowed <= -b:
        return True, f'문제 수지 {problem_balance_windowed} ≤ −{b}'
    return False, None


def should_abandon_sprt(log_likelihood_ratios: list, alpha: float = 0.05, beta: float = 0.05):
    """SPRT-근거 폐기 — Wald(1945) 순차검정으로 should_abandon(이산 K)을 연속 정초.

    각 노드의 로그우도비 lr = ln P(증거|진보) − ln P(증거|퇴행) 를 누적.
    누적 ≤ lnB(하한) → 퇴행 채택(폐기), ≥ lnA(상한) → 진보 채택(존속), 사이면 미결(더 관측).
    α=β=0.05 → (lnA,lnB)=(+2.944,−2.944). ABANDON_K=3 은 이 하한의 정수근사(노드당 ≈−1 nat).
    반환: (verdict, 누적LLR, (lnA,lnB)) — verdict ∈ {'abandon','retain','undecided'}.
    """
    lnA, lnB = sprt_log_boundaries(alpha, beta)
    s = math.fsum(log_likelihood_ratios)
    if s <= lnB:
        return 'abandon', s, (lnA, lnB)
    if s >= lnA:
        return 'retain', s, (lnA, lnB)
    return 'undecided', s, (lnA, lnB)
