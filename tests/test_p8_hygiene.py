"""P8 위생: _clamp01 단일정본 + uvicorn 워커 정합성 (TDD).

ENG-DU-5-duplicate-clamp01: _clamp01 가 engine/claim 중복 정의 → engine 단일정본을 claim 이 import.
OPS-UVICORN-1: process-local storage audit authority → 두 launcher 모두 단일 워커 fail-closed.
"""
import os

import lakatos.engine as engine
import lakatos.claim as claim


def test_clamp01_single_source():
    assert claim._clamp01 is engine._clamp01      # 같은 함수 객체 = 중복 제거됨


def test_clamp01_still_works():
    assert claim._clamp01(1.5) == 1.0 and claim._clamp01(-0.2) == 0.0 and claim._clamp01(0.3) == 0.3


def test_launchers_reject_multiworker_split_storage_authority():
    for name in ('run.sh', 'run_internal.sh'):
        text = open(
            os.path.join(os.path.dirname(__file__), '..', 'server', name),
            encoding='utf-8',
        ).read()
        assert 'UVICORN_WORKERS:-1' in text
        assert 'WORKER_COUNT" != "1' in text
        assert '--workers 1' in text
        assert '--workers=*' in text and '-w=*' in text
