"""데이터 계보 — 버퍼는 임시, 완성본은 source root 서 전 파이프라인 재생성 가능.

문제(사용자): 데이터가 바뀐다. root data→버퍼/캐시→완성본 사슬에서
  중간 버퍼를 써도 마지막 완성본이 나오면 root data 서 다시 전체 파이프라인으로 재생성할 수 있어야.
해법: 모든 산출물의 derivation 기록(입력 sha + 생산 코드 sha + params → 출력 sha).
  계보 DAG 로 ①완성본→source 추적 ②재빌드 플랜(topo) ③재현가능성(끊긴 링크 탐지)
  ④stale(입력 데이터 바뀜) 감지. PROV-O wasDerivedFrom + content hashing(DVC/Longinus 동형).
# KG: span_lakatotree_lineage
"""
import hashlib
import json
import os
import platform as platform_mod
import sys
from dataclasses import dataclass, field
from pathlib import Path


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


@dataclass(frozen=True)
class EnvironmentFingerprint:
    """재현에 필요한 실행 환경 요약.

    HALCON/Zivid/CUDA 같은 외부 도구 버전은 core 가 직접 조회하지 않는다. 호출자가
    이미 관측한 값을 `tool_versions` 에 넣으면 manifest 가 그 값을 고정한다.
    """

    python: str = ''
    platform: str = ''
    package_locks: dict = field(default_factory=dict)
    env_vars: dict = field(default_factory=dict)
    tool_versions: dict = field(default_factory=dict)

    def present(self) -> bool:
        return bool(
            self.python
            or self.platform
            or self.package_locks
            or self.env_vars
            or self.tool_versions
        )


@dataclass(frozen=True)
class DatasetManifest:
    """final artifact 를 source root 에서 다시 만들기 위한 append-only 계약."""

    final_artifact: str
    root_artifacts: tuple[str, ...]
    derivations: tuple[Derivation, ...]
    environment: EnvironmentFingerprint = field(default_factory=EnvironmentFingerprint)
    schema_version: str = 'lakatotree.dataset-manifest.v1'
    tolerance: str = ''
    metadata: dict = field(default_factory=dict)

    def rebuild_plan(self) -> tuple[Derivation, ...]:
        return tuple(rebuild_plan(self.final_artifact, by_output(list(self.derivations))))


@dataclass(frozen=True)
class DatasetManifestResult:
    passed: bool
    reasons: tuple[str, ...] = ()
    roots: tuple[str, ...] = ()
    declared_roots: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()
    rebuild_plan: tuple[Derivation, ...] = ()
    stale: bool = False
    changed: tuple[tuple[str, tuple[tuple[str, str, str], ...]], ...] = ()
    environment_present: bool = False

    def as_dict(self) -> dict:
        return {
            'passed': self.passed,
            'reasons': list(self.reasons),
            'roots': list(self.roots),
            'declared_roots': list(self.declared_roots),
            'gaps': list(self.gaps),
            'rebuild_plan': [derivation_to_dict(d) for d in self.rebuild_plan],
            'stale': self.stale,
            'changed': [
                {'artifact': artifact, 'inputs': [list(item) for item in changed]}
                for artifact, changed in self.changed
            ],
            'environment_present': self.environment_present,
        }


def by_output(derivs: list) -> dict:
    """{output_path: Derivation}."""
    return {d.output: d for d in derivs}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def fingerprint_environment(
    *,
    package_lock_paths: list | tuple = (),
    env_vars: list | tuple = (),
    environ: dict | None = None,
    tool_versions: dict | None = None,
) -> EnvironmentFingerprint:
    """현재 실행환경의 재현 관련 부분만 fingerprint 한다.

    전체 환경변수를 덤프하지 않는다. 재현 계약에 필요한 변수명만 명시적으로 받는다.
    """
    env = os.environ if environ is None else environ
    lock_hashes: dict[str, str] = {}
    for item in package_lock_paths:
        path = Path(item)
        if path.exists() and path.is_file():
            lock_hashes[str(path)] = _sha256_file(path)

    selected_env = {name: env[name] for name in env_vars if name in env}
    return EnvironmentFingerprint(
        python=sys.version.split()[0],
        platform=platform_mod.platform(),
        package_locks=lock_hashes,
        env_vars=selected_env,
        tool_versions=dict(tool_versions or {}),
    )


def derivation_to_dict(deriv: Derivation) -> dict:
    return {
        'output': deriv.output,
        'output_sha': deriv.output_sha,
        'producer': deriv.producer,
        'producer_sha': deriv.producer_sha,
        'inputs': [[path, sha] for path, sha in deriv.inputs],
        'params': dict(deriv.params),
        'kind': deriv.kind,
        'ts': deriv.ts,
        'env': deriv.env,
    }


def derivation_from_dict(data: dict) -> Derivation:
    return Derivation(
        output=data.get('output', ''),
        output_sha=data.get('output_sha', ''),
        producer=data.get('producer', ''),
        producer_sha=data.get('producer_sha', ''),
        inputs=[tuple(item) for item in data.get('inputs', [])],
        params=dict(data.get('params', {})),
        kind=data.get('kind', 'intermediate'),
        ts=data.get('ts', ''),
        env=data.get('env', ''),
    )


def environment_to_dict(env: EnvironmentFingerprint) -> dict:
    return {
        'python': env.python,
        'platform': env.platform,
        'package_locks': dict(env.package_locks),
        'env_vars': dict(env.env_vars),
        'tool_versions': dict(env.tool_versions),
    }


def environment_from_dict(data: dict | None) -> EnvironmentFingerprint:
    data = data or {}
    return EnvironmentFingerprint(
        python=data.get('python', ''),
        platform=data.get('platform', ''),
        package_locks=dict(data.get('package_locks', {})),
        env_vars=dict(data.get('env_vars', {})),
        tool_versions=dict(data.get('tool_versions', {})),
    )


def dataset_manifest_from_derivations(
    final_artifact: str,
    derivations: list,
    *,
    root_artifacts: list | tuple | None = None,
    environment: EnvironmentFingerprint | None = None,
    tolerance: str = '',
    metadata: dict | None = None,
) -> DatasetManifest:
    """Derivation ledger 에서 raw-rooted final artifact manifest 를 만든다."""
    bo = by_output(list(derivations))
    declared_roots = tuple(sorted(root_artifacts or roots(final_artifact, bo)))
    return DatasetManifest(
        final_artifact=final_artifact,
        root_artifacts=declared_roots,
        derivations=tuple(derivations),
        environment=environment or EnvironmentFingerprint(),
        tolerance=tolerance,
        metadata=dict(metadata or {}),
    )


def manifest_to_dict(manifest: DatasetManifest) -> dict:
    return {
        'schema_version': manifest.schema_version,
        'final_artifact': manifest.final_artifact,
        'root_artifacts': list(manifest.root_artifacts),
        'derivations': [derivation_to_dict(d) for d in manifest.derivations],
        'environment': environment_to_dict(manifest.environment),
        'tolerance': manifest.tolerance,
        'metadata': dict(manifest.metadata),
    }


def manifest_from_dict(data: dict) -> DatasetManifest:
    return DatasetManifest(
        final_artifact=data.get('final_artifact', ''),
        root_artifacts=tuple(data.get('root_artifacts', ())),
        derivations=tuple(derivation_from_dict(d) for d in data.get('derivations', ())),
        environment=environment_from_dict(data.get('environment')),
        schema_version=data.get('schema_version', 'lakatotree.dataset-manifest.v1'),
        tolerance=data.get('tolerance', ''),
        metadata=dict(data.get('metadata', {})),
    )


def load_dataset_manifest(path: str | Path) -> DatasetManifest:
    return manifest_from_dict(json.loads(Path(path).read_text(encoding='utf-8')))


def verify_dataset_manifest(
    manifest: DatasetManifest,
    *,
    current_shas: dict[str, str] | None = None,
    require_environment: bool = True,
) -> DatasetManifestResult:
    """Manifest 가 final artifact 를 declared raw roots 에서 재생성할 수 있는지 검증."""
    derivs = list(manifest.derivations)
    bo = by_output(derivs)
    if manifest.final_artifact not in bo:
        return DatasetManifestResult(
            passed=False,
            reasons=('artifact_unrecorded',),
            declared_roots=tuple(sorted(manifest.root_artifacts)),
            environment_present=manifest.environment.present(),
        )

    try:
        actual_roots = tuple(sorted(roots(manifest.final_artifact, bo)))
        gaps = tuple(sorted(reproducibility_gaps(
            manifest.final_artifact,
            bo,
            set(manifest.root_artifacts),
        )))
        plan = tuple(rebuild_plan(manifest.final_artifact, bo))
    except ValueError as exc:
        return DatasetManifestResult(
            passed=False,
            reasons=('lineage_cycle', str(exc)),
            declared_roots=tuple(sorted(manifest.root_artifacts)),
            environment_present=manifest.environment.present(),
        )

    changed: list[tuple[str, tuple[tuple[str, str, str], ...]]] = []
    if current_shas is not None:
        for deriv in plan:
            bad = tuple(stale_inputs(deriv, current_shas))
            if bad:
                changed.append((deriv.output, bad))

    reasons: list[str] = []
    if set(actual_roots) != set(manifest.root_artifacts):
        reasons.append('root_manifest_mismatch')
    if gaps:
        reasons.append('reproducibility_gaps')
    if changed:
        reasons.append('stale_inputs')
    if require_environment and not manifest.environment.present():
        reasons.append('environment_fingerprint_missing')

    return DatasetManifestResult(
        passed=not reasons,
        reasons=tuple(reasons),
        roots=actual_roots,
        declared_roots=tuple(sorted(manifest.root_artifacts)),
        gaps=gaps,
        rebuild_plan=plan,
        stale=bool(changed),
        changed=tuple(changed),
        environment_present=manifest.environment.present(),
    )


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
    """source(raw) 데이터 — BPC ZDF 등. 재현의 시작점."""
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
