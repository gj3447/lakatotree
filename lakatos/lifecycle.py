"""프로그램 lifecycle 종료판정 — P1: THEORY §2 '메타-종료' 행 물질화.

라카토스는 프로그램이 *언제* 끝나는지 시간표를 안 줬다 (라우든 3규칙이 '폐기'를,
베이즈가 '신뢰도'를 줬지만, 끝의 *모양*은 하나가 아니다). 여기서는 3-상태로 가른다:

  수확(harvesting)  : 더 이상 novel 예측을 낳지 않지만 정본이 안정·문제수지 흑자 —
                      이론적 동력은 소진, 응용 수확기. 폐기 아님 (성숙).
  발산(diverging)   : 변명이 문제를 낳는 중 — 질문이 닫히는 속도보다 열리는 속도가
                      빠르고 정본 개선 정체. 경보 상태 (폐기 직전 신호).
  소멸(extinct)     : stack 메타규칙(3층 정족수)이 폐기 합의 — 종료.
  활성(active)      : 위 어디에도 아님 — 정상 연구 진행.

판정 우선순위: extinct > diverging > harvesting > active (심각한 진단이 우선).
regret = 마지막 progressive 이후 소비한 노드 수 — bandit 관점의 기회비용 지표.

한계 정직: 윈도우(lifecycle_stall_window=3)는 정책값(grounding). 수확/발산 구분은
fertility(novel 등록) + 문제수지 부호라는 *대리지표* — 원전(Lakatos 1978)은 정성적.
# KG: span_lakatotree_lifecycle / THEORY §2 메타-종료 / P1
"""
from dataclasses import dataclass

from .grounding import GROUNDED
from .stack import ABANDON, StackVerdict

STALL_WINDOW = GROUNDED['lifecycle_stall_window']['value']

HARVESTING, DIVERGING, EXTINCT, ACTIVE = 'harvesting', 'diverging', 'extinct', 'active'


@dataclass(frozen=True)
class LifecycleState:
    state: str               # harvesting | diverging | extinct | active
    reason: str
    regret: int              # 마지막 progressive 이후 노드 수 (기회비용)
    window: int


def regret_nodes(verdicts: list) -> int:
    """마지막 progressive 이후 소비 노드 수. progressive 가 없으면 전체 길이."""
    for i in range(len(verdicts) - 1, -1, -1):
        if verdicts[i].get('verdict') == 'progressive':
            return len(verdicts) - 1 - i
    return len(verdicts)


def lifecycle_state(verdicts: list, stack: StackVerdict,
                    novel_registered_recent: int, problem_balance_windowed: int,
                    canonical_improved_recent: bool,
                    window: int = STALL_WINDOW) -> LifecycleState:
    """3-상태 종료판정. 입력의 'recent' 는 모두 같은 window 기준 (호출자가 맞춰 줌).

    - extinct    : stack.decision == abandon (메타규칙이 유일한 사형 권위 — 단일층 금지)
    - diverging  : 문제수지 적자 ∧ 정본 개선 없음 (변명이 문제를 낳는 중)
    - harvesting : novel 등록 고갈 ∧ 정본 개선 없음 ∧ 문제수지 흑자/균형 ∧ 비퇴행
    - active     : 그 외
    """
    r = regret_nodes(verdicts)
    if stack.decision == ABANDON:
        return LifecycleState(EXTINCT, f'3층 정족수 폐기 합의 — {stack.reason}', r, window)
    if problem_balance_windowed < 0 and not canonical_improved_recent:
        return LifecycleState(
            DIVERGING,
            f'문제수지 {problem_balance_windowed} < 0 ∧ 정본 개선 정체 (window {window})',
            r, window)
    if (novel_registered_recent == 0 and not canonical_improved_recent
            and problem_balance_windowed >= 0):
        return LifecycleState(
            HARVESTING,
            f'novel 예측 등록 0 ∧ 정본 안정 ∧ 문제수지 {problem_balance_windowed} ≥ 0 — '
            f'이론 동력 소진, 응용 수확기 (폐기 아님)',
            r, window)
    return LifecycleState(ACTIVE, '정상 연구 진행', r, window)
