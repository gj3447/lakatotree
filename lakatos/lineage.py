"""데이터 계보 — 버퍼는 임시, 완성본은 source root 서 전 파이프라인 재생성 가능.

문제(사용자): 데이터가 바뀐다. root data→버퍼/캐시→완성본 사슬에서
  중간 버퍼를 써도 마지막 완성본이 나오면 root data 서 다시 전체 파이프라인으로 재생성할 수 있어야.
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
    env: str = ''                # 환경 지문 sha (envfp) — 재현성 마지막 조각


def by_output(derivs: list) -> dict:
    """{output_path: Derivation}."""
    return {d.output: d for d in derivs}


def roots(artifact: str, bo: dict, _seen=None) -> set:
    """artifact 의 궁극 source(root artifact) 집합."""
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


@dataclass
class RawRoot:
    """source(raw) 데이터 — consumer_b ZDF 등. 재현의 시작점."""
    path: str
    sha: str
    schema: str = ''             # 예: 'ZDF 2448x2048 xyz+rgb+snr'


@dataclass
class RebuildManifest:
    """완성본을 raw root 에서 재생성하는 완전한 레시피 (코드·params·환경 포함)."""
    final: str
    roots: list                  # [RawRoot]
    env_sha: str                 # 환경 지문 sha
    recipe: list                 # [{producer, producer_sha, inputs, output, params, env}]
    tolerance: str | None = None # float 파이프라인: byte-exact 대신 metric 허용오차


def env_drift(deriv: Derivation, current_env_sha: str) -> bool:
    """이 산출물의 기록 환경 != 현재 환경? — 재현 결과 달라질 수 있음."""
    return bool(deriv.env) and deriv.env != current_env_sha


def build_manifest(final: str, bo: dict, root_schemas: dict | None = None,
                   env_sha: str = '', tolerance: str | None = None) -> RebuildManifest:
    """완성본 → RebuildManifest. roots(schema 부착) + env + topo recipe."""
    root_schemas = root_schemas or {}
    rts = []
    for r in sorted(roots(final, bo)):
        d = bo.get(r)
        rts.append(RawRoot(path=r, sha=(d.output_sha if d else ''),
                           schema=root_schemas.get(r, '')))
    recipe = [{'producer': d.producer, 'producer_sha': d.producer_sha,
               'inputs': [p for p, _ in d.inputs], 'output': d.output,
               'params': d.params, 'env': d.env} for d in rebuild_plan(final, bo)]
    return RebuildManifest(final=final, roots=rts, env_sha=env_sha,
                           recipe=recipe, tolerance=tolerance)
