"""층간 통약불가 메타규칙 — gap3 해소: 침묵하는 '가장 관대한 층 OR' 제거.

문제(THEORY §4 gap3): 포퍼=rejected / 베이즈=생존 / 라우든=양호가 충돌할 때 메타규칙이
없어 사실상 가장 관대한 층이 지배했고, 그 선택이 코드 어디에도 명시돼 있지 않았다.

해법 — 명시 투표 + 정족수:
  ① 각 층은 자기 철학에 충실하게 독립 투표한다 (abandon / retain / undecided).
     포퍼: 소박 반증주의 — 최신 판결 rejected 면 abandon (가장 엄격, 단발 반례에 민감)
     베이즈: credence < ABANDON_CREDENCE 면 abandon (자산가중 — 강한 가지는 반례 하나로 안 죽음)
     라우든: should_abandon 3규칙 (문제해결력)
  ② 폐기는 투표 가능한 층 중 **정족수(기본 2) 합의**에서만 (Condorcet jury theorem 정당화,
     grounding 'stack_quorum'). 단일 층의 단독 사형선고 금지 = 라카토스 "반례의 바다" 충실.
  ③ 불일치는 숨기지 않고 conflict 필드로 보고한다 (Feyerabend 다원주의의 정직한 운용 —
     다원주의는 '아무거나 OK'가 아니라 '불일치를 기록하라').

한계 정직: 층 독립성(Condorcet 가정)은 근사다 — 세 층 모두 같은 판결 시퀀스를 입력으로
공유한다. 정족수는 '독립 표본 3개'가 아니라 '서로 다른 철학적 렌즈 3개'의 합의다.
# KG: span_lakatotree_stack_meta_rule / THEORY gap3
"""
from dataclasses import dataclass, field

from lakatos.quant.bayes import should_abandon_bayes
from lakatos.grounding import GROUNDED
from lakatos.quant.laudan import should_abandon

STACK_QUORUM = GROUNDED['stack_quorum']['value']

ABANDON, RETAIN, UNDECIDED = 'abandon', 'retain', 'undecided'


@dataclass(frozen=True)
class LayerVote:
    layer: str        # popper | bayes | laudan
    vote: str         # abandon | retain | undecided
    reason: str
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class StackVerdict:
    decision: str             # abandon | retain | undecided
    votes: tuple              # (LayerVote, ...) — 전 층 공개, 침묵 금지
    conflict: bool            # 층간 불일치 존재 여부 (정직 보고)
    quorum: int
    reason: str


def popper_vote(verdicts: list) -> LayerVote:
    """포퍼층 투표 — 소박 반증주의: 최신 scripted 판결이 rejected 면 abandon.

    라카토스가 비판한 바로 그 엄격함을 *한 표*로만 보존한다 (단독 사형선고는 메타규칙이 차단).
    """
    scripted = [v for v in verdicts if v.get('verdict')]
    if not scripted:
        return LayerVote('popper', UNDECIDED, '판결 없음')
    last = scripted[-1]['verdict']
    if last == 'rejected':
        return LayerVote('popper', ABANDON, f'최신 판결 rejected (반증)', {'last': last})
    return LayerVote('popper', RETAIN, f'최신 판결 {last} (미반증)', {'last': last})


def bayes_vote(verdicts: list, prior: float | None = None) -> LayerVote:
    """베이즈층 투표 — 판결 시퀀스 사후 신뢰도. 자산 많은 가지는 반례 하나로 안 죽는다."""
    if not verdicts:
        return LayerVote('bayes', UNDECIDED, '증거 없음')
    kwargs = {} if prior is None else {'prior': prior}
    abandon, credence = should_abandon_bayes(verdicts, **kwargs)
    vote = ABANDON if abandon else RETAIN
    return LayerVote('bayes', vote, f'credence={credence:.3f}', {'credence': credence})


def laudan_vote(consecutive_nonprogressive: int, nodes_spent: int, prediction_hits: int,
                problem_balance_windowed: int) -> LayerVote:
    """라우든층 투표 — 문제해결력 3규칙 (이산, 해석가능)."""
    abandon, reason = should_abandon(consecutive_nonprogressive, nodes_spent,
                                     prediction_hits, problem_balance_windowed)
    if abandon:
        return LayerVote('laudan', ABANDON, reason)
    return LayerVote('laudan', RETAIN, '폐기 3규칙 전부 미발동')


def stack_verdict(votes: list, quorum: int = STACK_QUORUM) -> StackVerdict:
    """메타규칙 — 명시 정족수 합의. gap3 의 침묵 OR 를 대체한다.

    - 투표 가능한(=undecided 아닌) 층이 quorum 미만이면 decision=undecided (증거 부족 정직).
    - abandon 표 ≥ quorum → abandon. 아니면 retain.
    - 어느 경로든 conflict(불일치) 와 전 층 투표를 그대로 노출 — 가장 관대한 층이
      몰래 지배하는 일이 구조적으로 불가능하다.
    """
    decided = [v for v in votes if v.vote != UNDECIDED]
    abandon_votes = [v for v in decided if v.vote == ABANDON]
    conflict = len({v.vote for v in decided}) > 1
    if len(decided) < quorum:
        decision = UNDECIDED
        reason = f'투표 가능 층 {len(decided)} < 정족수 {quorum}'
    elif len(abandon_votes) >= quorum:
        decision = ABANDON
        reason = f'폐기 합의 {len(abandon_votes)}/{len(decided)} ≥ 정족수 {quorum}: ' \
                 + '; '.join(f'{v.layer}({v.reason})' for v in abandon_votes)
    else:
        decision = RETAIN
        reason = f'폐기 표 {len(abandon_votes)} < 정족수 {quorum}'
        if abandon_votes:
            reason += ' — 이상(anomaly) 관용: ' \
                      + '; '.join(f'{v.layer}({v.reason})' for v in abandon_votes)
    return StackVerdict(decision=decision, votes=tuple(votes), conflict=conflict,
                        quorum=quorum, reason=reason)


def evaluate_stack(verdicts: list, consecutive_nonprogressive: int, nodes_spent: int,
                   prediction_hits: int, problem_balance_windowed: int,
                   prior: float | None = None, quorum: int = STACK_QUORUM) -> StackVerdict:
    """3층 전체 평가 한 번에 — 투표 수집 + 메타규칙. 서버/CLI 의 단일 진입점."""
    votes = [
        popper_vote(verdicts),
        bayes_vote(verdicts, prior=prior),
        laudan_vote(consecutive_nonprogressive, nodes_spent, prediction_hits,
                    problem_balance_windowed),
    ]
    return stack_verdict(votes, quorum=quorum)
