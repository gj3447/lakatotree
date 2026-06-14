"""P8 위생: _clamp01 단일정본 + uvicorn 워커 노브 (TDD).

ENG-DU-5-duplicate-clamp01: _clamp01 가 engine/claim 중복 정의 → engine 단일정본을 claim 이 import.
OPS-UVICORN-1: run.sh 가 단일워커 고정 → UVICORN_WORKERS env 노브(기본 1).
"""
import os

import lakatos.engine as engine
import lakatos.claim as claim


def test_clamp01_single_source():
    assert claim._clamp01 is engine._clamp01      # 같은 함수 객체 = 중복 제거됨


def test_clamp01_still_works():
    assert claim._clamp01(1.5) == 1.0 and claim._clamp01(-0.2) == 0.0 and claim._clamp01(0.3) == 0.3


def test_run_sh_has_worker_knob():
    text = open(os.path.join(os.path.dirname(__file__), '..', 'server', 'run.sh'), encoding='utf-8').read()
    assert 'UVICORN_WORKERS' in text and '--workers' in text
