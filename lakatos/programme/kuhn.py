"""패러다임 전환 모델 — gap7: 단일 트리 한계를 넘는 프로그램 간 비교 판정.

Kuhn(1962)의 위기→혁명은 정성 서사라 그대로 기계화하면 곡해다 (정직: tier=policy).
여기서는 기계화 가능한 라카토스-Zahar(1976) 대체(supersession) 기준을 정본으로 쓰고,
Kuhn 은 상태 어휘(정상과학/위기/혁명후보)만 빌린다:

  대체 판정 (Lakatos & Zahar — 왜 코페르니쿠스가 프톨레마이오스를 이겼나):
    rival 이 incumbent 를 ① 초과 novel 적중(fertility)으로 앞서고
    ② 그 우세가 윈도우(supersession_window) 동안 지속되고
    ③ incumbent 는 그동안 퇴행(발산/소멸 또는 연속 비진보)일 때
    → paradigm_shift_candidate. (한 스냅샷의 우연 우세는 인정 안 함 — 시간 요건)

  상태 어휘:
    normal_science  : incumbent 건재 (active/harvesting, 도전자 우세 없음)
    crisis          : incumbent 퇴행 중인데 지배적 rival 도 아직 없음 (Kuhn 위기)
    shift_candidate : 위 대체 판정 충족 — 인간 oracle 의 프로그램 교체 결정 안건

판정은 자동 교체가 아니라 **안건 상정**이다 — hard core 교체는 AGM allow_hard_core
동의 절차(agm.py)를 거친다. 기계는 후보를 올리고, 결정은 인간이 한다.
# KG: span_lakatotree_kuhn / THEORY gap7 / P2
"""
from dataclasses import dataclass

from lakatos.grounding import GROUNDED
from lakatos.programme.leaderboard import dominates
from lakatos.programme.lifecycle import DIVERGING, EXTINCT

SUPERSESSION_WINDOW = GROUNDED['supersession_window']['value']
# 연속 비진보 퇴행 임계 — grounding 레지스트리에서(매직넘버 금지, 나생문 T3-3).
# abandon_k = 라우든 폐기 규칙①의 '연속 비진보 ≥ k' 와 동일 의미(tier policy_in_scale).
DEGENERATION_K = GROUNDED['abandon_k']['value']

NORMAL_SCIENCE, CRISIS, SHIFT_CANDIDATE = 'normal_science', 'crisis', 'shift_candidate'


@dataclass(frozen=True)
class ParadigmAssessment:
    state: str                   # normal_science | crisis | shift_candidate
    incumbent: str
    rival: str | None            # shift_candidate 일 때 도전자
    reason: str
    window: int
    requires_human_oracle: bool  # shift 는 항상 True — 자동 교체 금지


def incumbent_degenerating(lifecycle_states: list, consecutive_nonprogressive: int,
                           k: int = DEGENERATION_K) -> bool:
    """incumbent 퇴행 판정 — 최근 lifecycle 가 발산/소멸이거나 연속 비진보 ≥ k (grounding)."""
    recent = lifecycle_states[-1] if lifecycle_states else None
    return recent in (DIVERGING, EXTINCT) or consecutive_nonprogressive >= k


def sustained_dominance(snapshots: list, rival: str, incumbent: str,
                        window: int = SUPERSESSION_WINDOW) -> bool:
    """rival 의 우세 지속 — 최근 window 개 리더보드 스냅샷에서 연속 Pareto 지배 또는
    fertility_lb 연속 우위(Lakatos-Zahar 의 초과 novel 적중 기준)."""
    if len(snapshots) < window:
        return False
    for snap in snapshots[-window:]:
        by_name = {s['name']: s for s in snap['rows']}
        if rival not in by_name or incumbent not in by_name:
            return False
        r, i = by_name[rival], by_name[incumbent]
        if not (dominates(r, i) or r['fertility_lb'] > i['fertility_lb']):
            return False
    return True


def assess_paradigm(incumbent: str, rivals: list, snapshots: list,
                    incumbent_lifecycles: list, incumbent_consecutive_nonprogressive: int,
                    window: int = SUPERSESSION_WINDOW) -> ParadigmAssessment:
    """프로그램 수준 판정 — 단일 트리 한계(gap7)를 리더보드 스냅샷 시계열로 넘는다.

    snapshots = leaderboard() 결과의 시간순 리스트 (incumbent+rivals 포함).
    """
    degen = incumbent_degenerating(incumbent_lifecycles, incumbent_consecutive_nonprogressive)
    for rival in rivals:
        if degen and sustained_dominance(snapshots, rival, incumbent, window):
            return ParadigmAssessment(
                SHIFT_CANDIDATE, incumbent, rival,
                f'{rival} 이 {window} 스냅샷 연속 우세(Pareto 또는 novel 적중) ∧ '
                f'incumbent 퇴행 — 프로그램 교체 안건 (hard core 교체는 AGM 동의 절차)',
                window, requires_human_oracle=True)
    if degen:
        return ParadigmAssessment(
            CRISIS, incumbent, None,
            'incumbent 퇴행 중이나 지배적 rival 부재 — Kuhn 위기 (가설공간 확장 신호)',
            window, requires_human_oracle=False)
    return ParadigmAssessment(
        NORMAL_SCIENCE, incumbent, None, 'incumbent 건재 — 정상과학', window,
        requires_human_oracle=False)


def propose_supersession(assessment: ParadigmAssessment) -> dict | None:
    """shift_candidate 판정 → 구조화된 *대체 제안* 안건 레코드 ('합류를 기록한다'의 기계화).

    ★자동 교체가 아니다 — 이 레코드는 어떤 verdict 도 바꾸지 않는다(verdict_mutation=False).
    rival 의 지속 우세(붉은 영수증)가 incumbent 정본(푸른 현재최선)을 대체 *후보*로 미는 염기쌍을
    machine-readable 안건으로 박는다. 확정은 인간 몫: AGM allow_hard_core 동의 + admin
    set_verdict('superseded'). shift_candidate 가 아니면 None(제안 없음 — endpoint 에서 증발 방지).
    DON'T 준수: requires_human_verdict=True, 자동 교체/인간경계 자동화 0.
    """
    if assessment.state != SHIFT_CANDIDATE or not assessment.rival:
        return None
    return {
        'kind': 'supersession_proposal',
        'incumbent': assessment.incumbent,
        'rival': assessment.rival,
        'reason': assessment.reason,
        'window': assessment.window,
        'status': 'proposed',                # proposed → (인간) → confirmed/rejected
        'requires_human_verdict': True,      # 자동 교체 금지 (DON'T)
        'verdict_mutation': False,           # 이 레코드는 어떤 verdict 도 바꾸지 않는다
        'confirm_via': "AGM allow_hard_core 동의 후 admin set_verdict('superseded')",
    }
