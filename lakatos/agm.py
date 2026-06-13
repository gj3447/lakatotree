"""AGM 신념개정층 — P1: hard core 개정의 형식화 (THEORY §2 '신념개정' 행 물질화).

라카토스: hard core 는 방법론적 결정으로 반증 불가 — 반례는 보호대(protective belt)가
흡수한다. 그러나 hard core 도 *영원히* 불변은 아니다: 프로그램 교체기엔 바뀐다.
AGM(1985)은 그 '바뀜'을 공준으로 형식화한다: expansion(+), contraction(−), revision(*).

정직 표기 2건:
  ① 원전 AGM 은 연역폐쇄 이론(theory) 위 연산. 여기는 유한 belief *base* 위 연산
     (Hansson 1993 base revision 계열) — 폐쇄 없는 공학적 근사임을 숨기지 않는다.
  ② gap5(entrenchment 순서 유일해 없음)는 *해소가 아니라 정책 선언*으로 닫는다:
     순서는 사전식 (kind, credence, problem_balance, connectivity) — 이는 선택이며,
     모든 contraction 결과에 entrenchment_policy 가 따라붙어 감사 가능하다.

라카토트리 매핑:
  - hard_core belief 의 contraction 은 기본 금지 (PROTECTED) — 명시 allow_hard_core=True
    에서만 가능하고, 그 경우 결과에 programme_shift_candidate=True 가 찍힌다 (Kuhn 연동).
  - CANONICAL demote(전 정본 강등) = revision 의 한 사례: 새 정본 belief 가 옛 정본과
    모순 → 옛것 contraction 후 expansion (Levi identity).
# KG: span_lakatotree_agm_revision / THEORY gap5 / P1
"""
from dataclasses import dataclass, field, replace

ENTRENCHMENT_POLICY = 'lexicographic(kind>credence>problem_balance>connectivity) — 정책 선언(gap5: 유일해 없음)'


class HardCoreProtected(Exception):
    """hard core contraction 은 명시 동의 없이 금지 (라카토스 방법론적 결정)."""


@dataclass(frozen=True)
class Belief:
    belief_id: str
    statement: str
    kind: str = 'protective_belt'       # hard_core | protective_belt
    credence: float = 0.5               # 베이즈층 신뢰도 (bayes.branch_credence)
    problem_balance: int = 0            # 라우든층 문제수지
    connectivity: int = 0               # 의존하는/되는 belief 수 (트리 연결도)
    depends_on: tuple = ()              # 이 belief 가 전제하는 belief_id 들

    def __post_init__(self):
        if self.kind not in ('hard_core', 'protective_belt'):
            raise ValueError("kind 는 'hard_core'|'protective_belt'")
        if not 0.0 <= self.credence <= 1.0:
            raise ValueError('credence ∈ [0,1]')


def entrenchment_key(b: Belief) -> tuple:
    """epistemic entrenchment 전순서 — 클수록 굳건(나중에 포기). 정책 선언 = ENTRENCHMENT_POLICY."""
    return (1 if b.kind == 'hard_core' else 0, b.credence, b.problem_balance, b.connectivity)


@dataclass(frozen=True)
class RevisionResult:
    base: tuple                          # (Belief, ...) 결과 belief base
    removed: tuple                       # contraction 으로 빠진 belief_id 들
    added: tuple                         # expansion 으로 들어온 belief_id 들
    programme_shift_candidate: bool      # hard core 가 깎였는가 (Kuhn 연동 신호)
    entrenchment_policy: str = ENTRENCHMENT_POLICY


def _ids(base) -> set:
    return {b.belief_id for b in base}


def expansion(base: list, new: Belief, allow_hard_core: bool = False) -> RevisionResult:
    """AGM expansion(+): 무모순 가정 하 단순 추가. 같은 id 면 교체(갱신).

    ★ENGINE-ROB-1: 같은 id 의 *hard_core* belief 를 덮어쓰는 것은 hard core 개정이므로
    allow_hard_core 없이는 금지(아니면 contraction 가드를 우회해 보호대 밖에서 핵이 조용히 강등됨).
    동의 하에 hard_core→비-hard_core 강등 시 programme_shift_candidate=True(Kuhn 연동).
    """
    existing = next((b for b in base if b.belief_id == new.belief_id), None)
    if existing is not None and existing.kind == 'hard_core' and not allow_hard_core:
        raise HardCoreProtected(
            f'{new.belief_id} 는 hard core — expansion 으로 개정하려면 allow_hard_core=True '
            f'(보호대가 흡수해야; contraction 과 동일 보호)')
    kept = tuple(b for b in base if b.belief_id != new.belief_id)
    shift = bool(existing is not None and existing.kind == 'hard_core' and new.kind != 'hard_core')
    return RevisionResult(base=kept + (new,), removed=(), added=(new.belief_id,),
                          programme_shift_candidate=shift)


def _dependents_closure(base: list, target_ids: set) -> set:
    """target 에 (전이적으로) 의존하는 belief 전부 — 전제가 무너지면 같이 무너진다."""
    doomed = set(target_ids)
    changed = True
    while changed:
        changed = False
        for b in base:
            if b.belief_id not in doomed and any(d in doomed for d in b.depends_on):
                doomed.add(b.belief_id)
                changed = True
    return doomed


def contraction(base: list, belief_id: str, allow_hard_core: bool = False) -> RevisionResult:
    """AGM contraction(−): belief 제거 + 그것에 의존하는 belief 연쇄 제거.

    AGM success 공준: 결과에 belief_id 없음. inclusion 공준: 결과 ⊆ 원본.
    vacuity 공준: 없는 id 면 원본 그대로. hard core 는 PROTECTED (라카토스).
    """
    by_id = {b.belief_id: b for b in base}
    if belief_id not in by_id:
        return RevisionResult(base=tuple(base), removed=(), added=(),
                              programme_shift_candidate=False)   # vacuity
    target = by_id[belief_id]
    if target.kind == 'hard_core' and not allow_hard_core:
        raise HardCoreProtected(
            f'{belief_id} 는 hard core — 보호대가 흡수해야. 개정하려면 allow_hard_core=True '
            f'(프로그램 교체 후보 신호가 찍힌다)')
    doomed = _dependents_closure(base, {belief_id})
    # hard core 의존자는 보호 — 단 명시 동의 시엔 함께 깎인다 (전제 잃은 hard core 는 허구)
    if not allow_hard_core:
        protected = {b.belief_id for b in base if b.kind == 'hard_core'}
        if doomed & protected:
            raise HardCoreProtected(
                f'{belief_id} contraction 이 hard core {sorted(doomed & protected)} 를 연쇄 철거 — '
                f'allow_hard_core=True 필요')
    kept = tuple(b for b in base if b.belief_id not in doomed)
    shift = any(by_id[i].kind == 'hard_core' for i in doomed)
    return RevisionResult(base=kept, removed=tuple(sorted(doomed)), added=(),
                          programme_shift_candidate=shift)


def revision(base: list, new: Belief, contradicts: list = (),
             allow_hard_core: bool = False) -> RevisionResult:
    """AGM revision(*) = Levi identity: 모순되는 belief 들을 contraction 후 expansion.

    contradicts 충돌 시 보존 우선순위 = entrenchment_key (덜 굳건한 것부터 포기 —
    단, 명시된 모순은 entrenchment 무관 제거: success 공준이 보존보다 우선).
    """
    cur = list(base)
    removed_all, shift = [], False
    # 덜 굳건한 것부터 contraction (entrenchment_key 오름차순) — 선언된 정책을 실제 적용.
    by = {b.belief_id: b for b in base}
    ordered = sorted(contradicts, key=lambda cid: entrenchment_key(by[cid]) if cid in by else (-1, -1, -1, -1))
    for cid in ordered:
        r = contraction(cur, cid, allow_hard_core=allow_hard_core)
        cur = list(r.base)
        removed_all += list(r.removed)
        shift = shift or r.programme_shift_candidate
    r = expansion(cur, new, allow_hard_core=allow_hard_core)   # ENGINE-ROB-1: 가드 전파
    return RevisionResult(base=r.base, removed=tuple(sorted(set(removed_all))),
                          added=r.added, programme_shift_candidate=(shift or r.programme_shift_candidate))


def demote_canonical(base: list, old_canonical_id: str, new_canonical: Belief) -> RevisionResult:
    """CANONICAL demote = revision 사례 (THEORY §2). 옛 정본은 제거가 아니라 *강등*:
    kind/내용 유지, credence 만 새 정본 아래로 — former_canonical 의 AGM 해석."""
    by_id = {b.belief_id: b for b in base}
    if old_canonical_id in by_id:
        old = by_id[old_canonical_id]
        demoted = replace(old, credence=min(old.credence, max(new_canonical.credence - 0.1, 0.0)))
        base = [demoted if b.belief_id == old_canonical_id else b for b in base]
    return expansion(base, new_canonical)
