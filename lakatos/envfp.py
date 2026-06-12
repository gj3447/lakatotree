"""환경 지문 — 재현성의 마지막 조각. 같은 ZDF+코드라도 환경 다르면 결과 다르다.

캡처: python 버전·플랫폼·핵심 수치패키지(numpy/scipy/trimesh)·결정성 env var
      (OMP/MKL 스레드, PYTHONHASHSEED)·도메인 툴(Zivid/HALCON/CUDA) → 정규화 dict + sha256.
float 파이프라인(consumer_b)은 numpy/scipy/BLAS 버전이 결과를 바꾼다 → "ZDF서 재생성"이 참이려면 env 일치 필수.
# KG: span_lakatotree_envfp
"""
import hashlib
import json
import os
import platform
import sys

DETERMINISM_ENV_VARS = ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS',
                        'PYTHONHASHSEED', 'CUDA_VISIBLE_DEVICES')
NUMERIC_PACKAGES = ('numpy', 'scipy', 'trimesh')


def _pkg_version(name):
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:
        return None


def _detect_tools():
    """도메인 툴(있으면 버전, 없으면 생략) — HALCON/Zivid/CUDA 가 float 결과 좌우."""
    tools = {}
    for pkg in ('zivid', 'pyhalcon'):
        v = _pkg_version(pkg)
        if v:
            tools[pkg] = v
    for ev in ('HALCONROOT', 'CUDA_HOME'):
        if os.environ.get(ev):
            tools[ev.lower()] = os.environ[ev]
    return tools


def environment_fingerprint(probe: dict | None = None) -> dict:
    """결정적 환경 지문 dict. probe 주입 시 테스트용 고정값."""
    p = probe or {}
    return {
        'python': p.get('python', sys.version.split()[0]),
        'platform': p.get('platform', f'{platform.system()}-{platform.machine()}'),
        'packages': p.get('packages') if p.get('packages') is not None
                    else {n: _pkg_version(n) for n in NUMERIC_PACKAGES},
        'env_vars': p.get('env_vars') if p.get('env_vars') is not None
                    else {k: os.environ[k] for k in DETERMINISM_ENV_VARS if os.environ.get(k)},
        'tools': p.get('tools') if p.get('tools') is not None else _detect_tools(),
    }


def fingerprint_sha(fp: dict) -> str:
    return hashlib.sha256(json.dumps(fp, sort_keys=True, default=str).encode()).hexdigest()


def env_matches(recorded_sha: str, current_fp: dict | None = None) -> bool:
    """기록된 환경 지문 == 현재 환경? 다르면 재현 결과 달라질 수 있음."""
    cur = current_fp if current_fp is not None else environment_fingerprint()
    return fingerprint_sha(cur) == recorded_sha
