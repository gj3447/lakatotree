"""데이터 계보 — 버퍼는 임시, 완성본은 source(ZDF)서 전 파이프라인 재생성 가능.

문제(사용자): 데이터가 바뀐다. ZDF→버퍼/캐시(_rimobs/perview)→완성본 사슬에서
  중간 버퍼를 써도 마지막 완성본이 나오면 ZDF서 다시 전체 파이프라인으로 재생성할 수 있어야.
해법: 모든 산출물의 derivation 기록(입력 sha + 생산 코드 sha + params → 출력 sha).
  계보 DAG 로 ①완성본→source 추적 ②재빌드 플랜(topo) ③재현가능성(끊긴 링크 탐지)
  ④stale(입력 데이터 바뀜) 감지. PROV-O wasDerivedFrom + content hashing(DVC/Longinus 동형).
# KG: span_lakatotree_lineage
"""
from dataclasses import dataclass, field


@dataclass
class Derivation:
    output: str                  # 산출물 경로
    output_sha: str
    producer: str                # 생산 스크립트 경로
    producer_sha: str
    inputs: list                 # [(path, sha)]
    params: dict = field(default_factory=dict)
    kind: str = 'intermediate'   # source | intermediate | final
    ts: str = ''


def by_output(derivs: list) -> dict:
    """{output_path: Derivation}."""
    return {d.output: d for d in derivs}


def roots(artifact: str, bo: dict, _seen=None) -> set:
    """artifact 의 궁극 source(derivation 없는 = ZDF) 집합."""
    _seen = _seen or set()
    if artifact in _seen:
        return set()
    _seen = _seen | {artifact}
    d = bo.get(artifact)
    if d is None or not d.inputs:
        return {artifact}
    out = set()
    for path, _ in d.inputs:
        out |= roots(path, bo, _seen)
    return out


def reproducibility_gaps(final: str, bo: dict, sources: set, _seen=None) -> set:
    """완성본→source 사이에 derivation 없는 비-source 산출물(끊긴 링크). 비면 재현 가능."""
    _seen = _seen or set()
    if final in _seen or final in sources:
        return set()
    _seen = _seen | {final}
    d = bo.get(final)
    if d is None:
        return {final}              # 비-source 인데 derivation 없음 = 갭
    gaps = set()
    for path, _ in d.inputs:
        gaps |= reproducibility_gaps(path, bo, sources, _seen)
    return gaps


def is_reproducible(final: str, bo: dict, sources: set) -> bool:
    return not reproducibility_gaps(final, bo, sources)


def rebuild_plan(final: str, bo: dict) -> list:
    """source→완성본 topo 순서 derivation 목록 (source 는 제외=이미 존재). 사이클 가드."""
    order, visiting, done = [], set(), set()

    def visit(art):
        if art in done:
            return
        if art in visiting:
            raise ValueError(f'계보 사이클: {art}')
        visiting.add(art)
        d = bo.get(art)
        if d is not None and d.inputs:
            for path, _ in d.inputs:
                visit(path)
            order.append(d)         # 입력 먼저 → 자신
        visiting.discard(art)
        done.add(art)

    visit(final)
    return order


def stale_inputs(deriv: Derivation, current_shas: dict) -> list:
    """기록된 입력 sha ≠ 현재 디스크 sha → 데이터 바뀜. 하류 완성본 재생성 필요."""
    bad = []
    for path, rec_sha in deriv.inputs:
        cur = current_shas.get(path)
        if cur is not None and cur != rec_sha:
            bad.append((path, rec_sha, cur))
    return bad


def script_history(derivs: list, producer: str) -> list:
    """한 생산 스크립트의 버전 이력 — sha 변화 + 각 버전이 만든 산출물(시간순).

    스크립트도 중간에 수정된다. append-only 기록에서 producer_sha 가 바뀌면 새 버전.
    어느 코드 버전이 어느 데이터를 만들었는지 = 완전 재현의 마지막 조각.
    """
    rows = sorted((d for d in derivs if d.producer == producer), key=lambda x: x.ts)
    versions = {}
    order = []
    for d in rows:
        if d.producer_sha not in versions:
            versions[d.producer_sha] = {'sha': d.producer_sha, 'first_seen': d.ts, 'outputs': []}
            order.append(d.producer_sha)
        versions[d.producer_sha]['outputs'].append(d.output)
    return [versions[k] for k in order]
